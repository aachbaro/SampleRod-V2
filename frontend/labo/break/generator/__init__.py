# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Sous-package du generateur de break integre dans le BreakWidget.
# - Expose la facade BreakGeneratorPanel et le KnobWidget reutilise dans son UI.
# -----------------------------------------------------------------------------

from .generator_widget import BreakGeneratorPanel
from .knob_widget import KnobWidget

__all__ = [
    "BreakGeneratorPanel",
    "KnobWidget",
]
