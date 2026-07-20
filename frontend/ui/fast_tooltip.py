# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fait apparaitre les tooltips rapidement (interface icone-only ou le tooltip
#   remplace le texte du bouton). Qt attend ~700ms par defaut ; on descend a
#   ~250ms via un QProxyStyle qui override le style hint, sans changer le rendu.
#
# USAGE
#   from frontend.ui.fast_tooltip import install_fast_tooltips
#   install_fast_tooltips(app, delay_ms=250)   # une fois, sur la QApplication
#
# NOTE
# - QProxyStyle delegue tout au style de base : l'apparence est preservee,
#   seul le delai d'apparition du tooltip est modifie.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle


class FastTooltipStyle(QProxyStyle):
    """Style proxy qui reduit le delai d'apparition des tooltips."""

    def __init__(self, base_style=None, delay_ms: int = 250):
        super().__init__(base_style)
        self._delay_ms = int(delay_ms)

    def styleHint(self, hint, option=None, widget=None, return_data=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return self._delay_ms
        return super().styleHint(hint, option, widget, return_data)


def install_fast_tooltips(app: QApplication, delay_ms: int = 250) -> None:
    """Installe le style rapide sur la QApplication (idempotent)."""
    if isinstance(app.style(), FastTooltipStyle):
        return
    app.setStyle(FastTooltipStyle(app.style(), delay_ms))
