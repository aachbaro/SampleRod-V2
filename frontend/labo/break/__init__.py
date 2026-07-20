# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Package du Labo dedie a l'outil Break.
# - Regroupe la facade BreakWidget, son generateur et les controleurs
#   specialises qui allegeaient auparavant de gros fichiers monolithiques.
#
# FONCTIONS exportees
# - BreakWidget          : onglet principal Break.
# - BreakGeneratorPanel  : panneau interne de generation de break.
# -----------------------------------------------------------------------------

from .break_widget import BreakWidget
from .generator import BreakGeneratorPanel

__all__ = [
    "BreakGeneratorPanel",
    "BreakWidget",
]
