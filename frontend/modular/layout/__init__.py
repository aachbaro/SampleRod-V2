# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Placement spatial des fenetres de l'atelier modulaire : magnetisme entre
#   fenetres, magnetisme aux bords d'ecran, grille d'alignement.
#
# ORGANISATION
# - geometry.py      : rectangles et arrondi grille. AUCUN import Qt.
# - snap_engine.py   : toute la politique de placement. AUCUN import Qt.
# - move_lifecycle.py: cycle d'interaction (debut/fin de geste). Partiellement Qt.
# - layout_manager.py: registre des fenetres, application, persistance. Qt.
#
# POURQUOI CETTE SEPARATION
# - Le moteur de decision est du Python pur : seuils, priorites, egalites et cas
#   limites se testent exhaustivement sans jamais ouvrir de fenetre. C'est le
#   principal garant de robustesse de ce systeme.
#
# LIENS CLES
# - frontend/modular/window_manager.py : registre central des instances
# - RECHERCHE_MAGNETISME_FENETRES.md   : etude prealable et mesures
# -----------------------------------------------------------------------------

from .geometry import (
    Rect,
    rect_from_qrect,
    snap_rect_edges_to_grid,
    snap_resized_edges_to_grid,
    snap_to_grid,
)
from .snap_engine import (
    CandidateKind,
    Relation,
    SnapCandidate,
    SnapResult,
    SnapSettings,
    resolve_snap,
)

__all__ = [
    "Rect",
    "rect_from_qrect",
    "snap_to_grid",
    "snap_rect_edges_to_grid",
    "snap_resized_edges_to_grid",
    "CandidateKind",
    "Relation",
    "SnapCandidate",
    "SnapResult",
    "SnapSettings",
    "resolve_snap",
]
