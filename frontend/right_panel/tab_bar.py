"""
------------------------------------------------------------------------------
Tab Bar Helpers (Right Panel)
------------------------------------------------------------------------------
Ce module contient des composants "UI infrastructure" reutilisables pour le
panneau droit.

Actuellement:
- HoverCloseTabBar: barre d'onglets avec une croix de fermeture minimaliste
  qui n'apparait qu'au survol de l'onglet (style "Chrome-like", mais sobre).
------------------------------------------------------------------------------
"""

from __future__ import annotations

import qtawesome as qta
from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QTabBar, QToolButton


class HoverCloseTabBar(QTabBar):
    """
    QTabBar avec bouton de fermeture discret:
    - invisible par defaut (ne reserve pas de place)
    - apparait en rouge quand on survole l'onglet
    """

    closeRequested = pyqtSignal(int)

    def __init__(
        self,
        parent=None,
        *,
        close_icon: str = "fa5s.times",
        close_color: str = "#d77a7a",
        close_color_hover: str = "#ff6b6b",
        close_size: int = 14,
        close_icon_size: int = 10,
    ):
        super().__init__(parent)
        self.setMouseTracking(True)

        self._hover_index = -1
        self._close_icon = close_icon
        self._close_color = close_color
        self._close_color_hover = close_color_hover
        self._close_size = close_size
        self._close_icon_size = close_icon_size

        # Precompute icons: hover can generate a LOT of events, avoid recreating icons each time.
        self._icon_close = qta.icon(self._close_icon, color=self._close_color)
        self._icon_close_hover = qta.icon(self._close_icon, color=self._close_color_hover)
        self._icon_empty = QIcon()

    # ------------------------------------------------------------------ close button plumbing
    def tabInserted(self, index: int) -> None:  # noqa: N802 (Qt API)
        super().tabInserted(index)

        btn = QToolButton(self)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # avoid stealing focus
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(self._close_icon_size, self._close_icon_size))
        btn.setStyleSheet(
            "QToolButton { border: none; background: transparent; padding: 0px; margin: 0px; }"
        )
        btn.installEventFilter(self)

        # Connect click -> index lookup (indexes can change after closes/moves)
        btn.clicked.connect(self._on_close_clicked)

        # Important:
        # Pour eviter que la largeur des onglets "bouge" au survol (reflow),
        # on reserve TOUJOURS la place du bouton de fermeture.
        # On ne fait qu'afficher/masquer l'icone + activer/desactiver le bouton.
        btn.setFixedSize(self._close_size, self._close_size)
        btn.setIcon(self._icon_empty)
        btn.setEnabled(False)

        self.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def tabRemoved(self, index: int) -> None:  # noqa: N802 (Qt API)
        super().tabRemoved(index)
        # Keep hover state consistent when tabs shift.
        if self._hover_index == index:
            self._hover_index = -1
        elif self._hover_index > index:
            self._hover_index -= 1

    def _on_close_clicked(self) -> None:
        btn = self.sender()
        if btn is None:
            return

        # Find which tab owns this button.
        for i in range(self.count()):
            if self.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self.closeRequested.emit(i)
                return

    # ------------------------------------------------------------------ hover handling
    def mouseMoveEvent(self, ev):  # noqa: ANN001 (Qt signature)
        idx = self.tabAt(ev.position().toPoint())
        if idx != self._hover_index:
            self._set_hover_tab(idx)
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):  # noqa: ANN001 (Qt signature)
        self._set_hover_tab(-1)
        super().leaveEvent(ev)

    def eventFilter(self, obj, ev):  # noqa: ANN001 (Qt signature)
        # Make the close icon a bit stronger when hovering the X itself.
        if isinstance(obj, QToolButton):
            if ev.type() == QEvent.Type.Enter:
                obj.setIcon(self._icon_close_hover)
            elif ev.type() == QEvent.Type.Leave:
                obj.setIcon(self._icon_close)
        return super().eventFilter(obj, ev)

    def _set_hover_tab(self, idx: int) -> None:
        # Hide previous
        if 0 <= self._hover_index < self.count():
            self._set_close_visible(self._hover_index, False)

        self._hover_index = idx

        # Show new
        if 0 <= idx < self.count():
            self._set_close_visible(idx, True)

    def _set_close_visible(self, index: int, visible: bool) -> None:
        btn = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if not isinstance(btn, QToolButton):
            return

        if visible:
            btn.setIcon(self._icon_close)
            btn.setToolTip("Fermer")
            btn.setEnabled(True)
        else:
            btn.setIcon(self._icon_empty)
            btn.setEnabled(False)
