# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Shim de compatibilite pour les imports historiques du BreakGeneratorPanel.
# - Le code reel vit maintenant dans frontend/labo/break/generator/generator_widget.py.
# - L'import passe par importlib car "break" est un mot-cle Python.
# -----------------------------------------------------------------------------

from importlib import import_module

BreakGeneratorPanel = import_module(
    "frontend.labo.break.generator.generator_widget"
).BreakGeneratorPanel

__all__ = ["BreakGeneratorPanel"]
