# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Etat d'une grille au tempo "en cours de reglage" : tant que la session est
#   ouverte, changer le BPM, la longueur de tranche ou le decalage REMPLACE la
#   grille au lieu de l'empiler.
#
# POURQUOI CETTE CLASSE
# - Sans elle, chaque essai de reglage laissait ses marqueurs derriere lui : on
#   ne pouvait pas tatonner. Or le debut d'un pattern est rarement evident au
#   tout debut d'un enregistrement — il FAUT pouvoir caler apres coup.
# - Elle distingue les marqueurs POSES PAR LA GRILLE de ceux poses a la main :
#   un decoupage manuel existant n'est jamais detruit par un reglage.
#
# COUTS (mesures sur 213 marqueurs, fichier de 30 s)
# - Decalage  : ~26 ms  -> assez rapide pour suivre un slider en direct.
# - BPM/steps : ~270 ms -> re-pose complete, declenchee a la validation.
#
# LIENS CLES
# - waveform_grid.py            : le calcul pur (positions, tempo, translation)
# - waveform_markers.py         : le controleur qui pilote cette session
# - waveform_grid_panel.py      : les controles
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .waveform_grid import grid_marker_times


@dataclass(frozen=True)
class GridSettings:
    """Les trois reglages d'une grille."""

    bpm: float = 120.0
    steps_per_slice: int = 16
    offset_s: float = 0.0

    def with_offset(self, offset_s: float) -> "GridSettings":
        return replace(self, offset_s=float(offset_s))


@dataclass
class GridSession:
    """Grille en cours de reglage : ce qu'elle a pose, et ou.

    `owned` est la memoire de la session : les temps que la grille a poses et
    qu'elle a donc le droit de reprendre. Tout le reste appartient a
    l'utilisateur.
    """

    origin_s: float = 0.0
    duration_s: float = 0.0
    settings: GridSettings = field(default_factory=GridSettings)
    owned: tuple[float, ...] = ()
    active: bool = False

    # -- Calcul ---------------------------------------------------------------
    def planned_times(self, settings: GridSettings | None = None) -> list[float]:
        """Positions que produiraient ces reglages, decalage compris.

        Le decalage RE-ANCRE la grille au lieu de translater une grille de
        base : comme elle rayonne des deux cotes, ne translater ferait perdre
        un marqueur au bord sans jamais le rendre. En re-ancrant, la grille
        couvre tout le fichier quel que soit le decalage.
        """
        current = settings or self.settings
        return grid_marker_times(
            origin_s=self.origin_s + float(current.offset_s or 0.0),
            bpm=current.bpm,
            steps_per_slice=current.steps_per_slice,
            duration_s=self.duration_s,
        )

    def is_offset_only(self, settings: GridSettings) -> bool:
        """Vrai si seul le decalage change : on peut translater, pas re-poser.

        C'est ce qui rend le reglage du point de depart fluide — deplacer les
        lignes existantes coute dix fois moins cher que tout reconstruire.
        """
        return (
            self.active
            and abs(float(settings.bpm) - float(self.settings.bpm)) < 1e-9
            and int(settings.steps_per_slice) == int(self.settings.steps_per_slice)
        )

    def offset_delta(self, settings: GridSettings) -> float:
        """De combien translater pour passer du decalage courant au demande."""
        return float(settings.offset_s) - float(self.settings.offset_s)

    # -- Transitions ----------------------------------------------------------
    def opened(self, times, settings: GridSettings) -> "GridSession":
        self.owned = tuple(float(t) for t in times)
        self.settings = settings
        self.active = True
        return self

    def moved(self, times, settings: GridSettings) -> "GridSession":
        self.owned = tuple(float(t) for t in times)
        self.settings = settings
        return self

    def closed(self) -> "GridSession":
        """Fin de session : la grille devient du decoupage ordinaire."""
        self.owned = ()
        self.active = False
        return self
