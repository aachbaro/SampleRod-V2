# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Petites preferences globales de la Reserve, partagees entre le chrome
#   (toggle) et les sample cards (affichage conditionnel).
# - Module "leaf" : n'importe que PySide6, pour eviter tout cycle d'import.
#
# PREFERENCE
# - show_key_badge : afficher le badge de gamme sur les cartes analysees.
#   Emet showKeyBadgeChanged(bool) au changement ; les cartes se re-evaluent.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

_KEY_SHOW_BADGE = "reserve/show_key_badge"


class ReservePrefs(QObject):
    """Preferences globales de la Reserve (singleton `prefs`)."""

    showKeyBadgeChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self._show_key = bool(
            QSettings("SampleRod", "Main").value(_KEY_SHOW_BADGE, False, type=bool)
        )

    def show_key_badge(self) -> bool:
        return self._show_key

    def set_show_key_badge(self, value: bool) -> None:
        value = bool(value)
        if value == self._show_key:
            return
        self._show_key = value
        QSettings("SampleRod", "Main").setValue(_KEY_SHOW_BADGE, value)
        self.showKeyBadgeChanged.emit(value)


prefs = ReservePrefs()
