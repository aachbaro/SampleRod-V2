# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Package "Reserve" : regroupe tout ce qui concerne la zone de matiere sonore
#   accessible avant et apres l'indexation.
# - Expose les types, constantes et fonctions utilitaires utilises par les
#   differents onglets de la Reserve (Dossiers, Historique, Indexe).
#
# FONCTIONS exportees (sommaire)
# - ReserveActions         : actions communes (preview, rename, drag, send to lab)
# - ReserveEntry           : dataclass representant un sample dans la Reserve
# - STATUS_* constantes    : normal, non_indexe, needs_analysis, missing, all
# - reserve_entry_from_sample()    : cree un ReserveEntry depuis un sample indexe
# - reserve_entry_from_directory() : cree un ReserveEntry depuis le systeme de fichiers
# - reserve_entry_matches_*()      : fonctions de filtrage
# - apply_status_badge()           : applique couleur + texte sur un QLabel
# -----------------------------------------------------------------------------

from .reserve_actions import ReserveActions
from .reserve_entry import (
    ReserveEntry,
    STATUS_ALL,
    STATUS_MISSING,
    STATUS_NEEDS_ANALYSIS,
    STATUS_NON_INDEXED,
    STATUS_NORMAL,
    apply_status_badge,
    reserve_entry_from_directory,
    reserve_entry_from_sample,
    reserve_entry_matches_query,
    reserve_entry_matches_status,
    reserve_status_badge_stylesheet,
    reserve_status_label,
    reserve_status_tone,
)

__all__ = [
    "ReserveActions",
    "ReserveEntry",
    "STATUS_ALL",
    "STATUS_MISSING",
    "STATUS_NEEDS_ANALYSIS",
    "STATUS_NON_INDEXED",
    "STATUS_NORMAL",
    "apply_status_badge",
    "reserve_entry_from_directory",
    "reserve_entry_from_sample",
    "reserve_entry_matches_query",
    "reserve_entry_matches_status",
    "reserve_status_badge_stylesheet",
    "reserve_status_label",
    "reserve_status_tone",
]
