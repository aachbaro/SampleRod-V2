# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Decoupage d'un enregistrement au TEMPO : a partir d'un point de depart et
#   d'un BPM, pose des marqueurs a intervalle musical regulier jusqu'a la fin.
# - Usage vise : recouper un morceau a tempo stable en patterns de longueur
#   egale (1 bar, 2 bars...), pour les recomposer ensuite dans le Compositeur.
#
# MODELE
# - Un STEP = une double-croche (1/16), meme convention que le generateur de
#   break (`step_duration = (60 / bpm) / 4`).
# - Deux parametres seulement : le BPM, et le nombre de steps par tranche.
#   16 steps = 1 mesure a 4/4, 32 = 2 mesures, 4 = un temps.
#
# LIENS CLES
# - frontend/sample_gui/waveform/waveform_grid_panel.py : les controles.
# - frontend/sample_gui/marker_manager.py               : pose des marqueurs.
# -----------------------------------------------------------------------------

from __future__ import annotations

# Un step = 1/16 de ronde, soit un quart de temps a 4/4.
_STEPS_PER_BEAT = 4

# En dessous, une tranche ne represente plus rien d'exploitable.
MIN_SLICE_DURATION_S = 0.01


def step_duration_s(bpm: float) -> float:
    """Duree d'un step (double-croche) au tempo donne."""
    tempo = float(bpm or 0.0)
    if tempo <= 0.0:
        return 0.0
    return (60.0 / tempo) / float(_STEPS_PER_BEAT)


def slice_duration_s(bpm: float, steps_per_slice: int) -> float:
    """Duree d'une tranche de `steps_per_slice` steps au tempo donne."""
    steps = int(steps_per_slice or 0)
    if steps <= 0:
        return 0.0
    return step_duration_s(bpm) * steps


def bpm_from_span(span_s: float, steps: int) -> float:
    """Tempo implique par une duree dont on affirme le nombre de steps.

    Le geste vise : on selectionne un bout de morceau dont on est SUR qu'il
    fait une mesure (16 steps), et on en deduit le tempo — bien plus fiable
    que de deviner un BPM a l'oreille, surtout sur un disque un peu flottant.
    Ensuite on peut subdiviser autant qu'on veut, la grille reste calee.
    """
    span = float(span_s or 0.0)
    count = int(steps or 0)
    if span <= 0.0 or count <= 0:
        return 0.0
    # span = count * (60 / bpm) / 4  =>  bpm = 15 * count / span
    return (60.0 * count) / (float(_STEPS_PER_BEAT) * span)


def shift_grid_times(times, delta_s: float, duration_s: float) -> list[float]:
    """Translate une grille entiere, en jetant ce qui sort du fichier.

    Sert au reglage du point de depart : le debut d'un pattern est rarement
    evident au tout debut d'un enregistrement, on cale donc la grille apres
    coup en la faisant glisser d'un bloc.
    """
    total = float(duration_s or 0.0)
    delta = float(delta_s or 0.0)
    shifted: list[float] = []
    for value in times or ():
        moved = round(float(value) + delta, 6)
        if moved < 0.0 or moved > total - MIN_SLICE_DURATION_S:
            continue
        shifted.append(moved)
    return shifted


def grid_marker_times(
    *,
    origin_s: float,
    bpm: float,
    steps_per_slice: int,
    duration_s: float,
    include_origin: bool = True,
    extend_before: bool = True,
    max_markers: int = 4096,
) -> list[float]:
    """Positions des marqueurs d'une grille au tempo, autour de `origin_s`.

    Le point de depart est un point d'ANCRAGE, pas un debut : la grille
    rayonne de part et d'autre et couvre tout le fichier. C'est ce qui permet
    de caler sur un endroit dont on est sur — souvent en plein milieu du
    morceau, la ou le pattern est franc — plutot que de devoir identifier le
    tout premier temps de l'enregistrement, qui est justement le passage le
    moins lisible.

    Aux deux bouts, on ne pose rien qui ne delimiterait aucune tranche utile :
    ni sur les dernieres millisecondes, ni avant le debut du fichier.

    `max_markers` est un garde-fou : un BPM absurde sur un long enregistrement
    produirait des dizaines de milliers de marqueurs et figerait l'interface.
    """
    total = float(duration_s or 0.0)
    start = float(origin_s or 0.0)
    if total <= 0.0 or start < 0.0 or start >= total:
        return []

    slice_s = slice_duration_s(bpm, steps_per_slice)
    if slice_s < MIN_SLICE_DURATION_S:
        return []

    # -- En amont de l'ancrage, du plus proche au plus lointain.
    before: list[float] = []
    if extend_before:
        position = start - slice_s
        while position >= -1e-9 and len(before) < max_markers:
            before.append(round(max(position, 0.0), 6))
            position -= slice_s
    before.reverse()

    times: list[float] = list(before)
    if include_origin:
        times.append(start)

    # -- En aval. On s'arrete avant la fin : un marqueur pose sur les
    # dernieres millisecondes ne delimiterait aucune tranche utile.
    position = start + slice_s
    while position < total - MIN_SLICE_DURATION_S and len(times) < max_markers:
        times.append(round(position, 6))
        position += slice_s
    return times


def grid_slice_count(
    *,
    origin_s: float,
    bpm: float,
    steps_per_slice: int,
    duration_s: float,
) -> int:
    """Nombre de tranches completes que la grille decoupera."""
    markers = grid_marker_times(
        origin_s=origin_s,
        bpm=bpm,
        steps_per_slice=steps_per_slice,
        duration_s=duration_s,
    )
    return len(markers)


def merge_grid_markers(
    existing: list[float],
    grid: list[float],
    *,
    tolerance_s: float = 0.002,
) -> list[float]:
    """Ajoute la grille aux marqueurs existants, sans doublon a la tolerance.

    Reposer une grille identique ne doit pas empiler deux marqueurs au meme
    endroit (ils seraient indissociables a la souris).
    """
    merged = sorted(float(value) for value in (existing or []))
    for candidate in grid:
        value = float(candidate)
        if any(abs(value - kept) <= tolerance_s for kept in merged):
            continue
        merged.append(value)
        merged.sort()
    return merged
