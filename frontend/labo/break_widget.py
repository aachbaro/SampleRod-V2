# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Shim de compatibilite pour les imports historiques du BreakWidget.
# - Le code reel vit maintenant dans frontend/labo/break/break_widget.py.
# - L'import passe par importlib car "break" est un mot-cle Python.
# -----------------------------------------------------------------------------

from importlib import import_module

BreakWidget = import_module("frontend.labo.break.break_widget").BreakWidget

__all__ = ["BreakWidget"]
