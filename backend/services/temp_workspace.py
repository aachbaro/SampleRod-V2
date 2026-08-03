# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Point unique pour les dossiers de travail temporaires de SampleRod
#   (%TEMP%/SampleRod/<nom>) et pour leur MENAGE.
#
# POURQUOI
# - Chaque rendu de pattern, chaque preview de step, chaque waveform editee
#   ecrit un WAV horodate par un uuid : jamais reutilise, jamais supprime.
#   Sur une session de travail nourrie, ces dossiers atteignent des centaines
#   de Mo sans que rien ne les vide — jusqu'au disque plein.
# - On garde les N fichiers les plus RECENTS de chaque dossier (les seuls qui
#   peuvent encore etre joues ou glisses) et on jette le reste.
#
# API
# - temp_dir(name)                 -> Path (cree le dossier au besoin)
# - prune_temp_dir(name, ...)      -> int (fichiers supprimes)
# - prune_all_workspaces()         -> dict[str, int] (menage de demarrage)
#
# LIENS CLES
# - backend/services/drum_analysis_service.py : rendus de pattern / preview
# - frontend/labo/break/generator/generator_playback.py : segments de preview
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("temp_workspace")

TEMP_ROOT = Path(tempfile.gettempdir()) / "SampleRod"

# Combien de fichiers garder par dossier lors du menage de demarrage.
# Volontairement genereux : ces fichiers sont bon marche a regenerer, mais on
# ne veut pas casser une session en cours de restauration (le Compositeur
# rouvre ses clips depuis composer_clips).
_STARTUP_BUDGET: dict[str, int] = {
    "break_pattern": 30,
    "break_pattern_segments": 30,
    "break_preview": 10,
    "break_edits": 10,
    "break_tempo_mode": 10,
    "drag_slices": 30,
    "stem_mix": 20,
    "composer_clips": 200,
}

# Age au-dela duquel un fichier est jete quoi qu'il arrive (7 jours).
_MAX_AGE_S = 7 * 24 * 3600


def temp_dir(name: str) -> Path:
    """Dossier de travail temporaire `name`, cree si besoin."""
    path = TEMP_ROOT / str(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def prune_temp_dir(
    name: str,
    *,
    keep_recent: int = 30,
    max_age_s: float | None = _MAX_AGE_S,
    protect: object = (),
) -> int:
    """Supprime les fichiers excedentaires d'un dossier de travail.

    Garde les `keep_recent` plus recents, plus tout chemin cite dans
    `protect` (un fichier en cours de lecture, par exemple). Les erreurs de
    suppression sont ignorees : sous Windows, un fichier encore ouvert par le
    lecteur audio refusera simplement de partir, et on retentera plus tard.
    """
    path = TEMP_ROOT / str(name)
    if not path.is_dir():
        return 0

    protected = {
        os.path.normcase(os.path.normpath(str(item)))
        for item in (protect or ())
        if item
    }
    try:
        entries = [entry for entry in path.iterdir() if entry.is_file()]
    except OSError:
        return 0

    try:
        entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
    except OSError:
        return 0

    now = time.time()
    removed = 0
    for index, entry in enumerate(entries):
        if os.path.normcase(os.path.normpath(str(entry))) in protected:
            continue
        too_many = index >= max(0, int(keep_recent))
        too_old = False
        if max_age_s is not None:
            try:
                too_old = (now - entry.stat().st_mtime) > float(max_age_s)
            except OSError:
                too_old = False
        if not (too_many or too_old):
            continue
        try:
            entry.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def prune_all_workspaces() -> dict[str, int]:
    """Menage de demarrage sur tous les dossiers connus."""
    if not TEMP_ROOT.is_dir():
        return {}
    report: dict[str, int] = {}
    for name, budget in _STARTUP_BUDGET.items():
        removed = prune_temp_dir(name, keep_recent=budget)
        if removed:
            report[name] = removed
    if report:
        logger.info(
            "Menage des dossiers temporaires: %s fichier(s) supprime(s) (%s)",
            sum(report.values()),
            ", ".join(f"{key}:{value}" for key, value in sorted(report.items())),
        )
    return report
