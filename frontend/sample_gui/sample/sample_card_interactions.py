# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere les interactions "carte": focus visuel + drag & drop.
# - Encapsule la logique de drag (QDrag/QMimeData).
# - Centralise le comportement de focus (click -> focus, outline).
# -----------------------------------------------------------------------------

from __future__ import annotations

import pickle

from PyQt6.QtCore import Qt, QEvent, QMimeData
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import QApplication


class SampleCardInteractions:
    def __init__(self, card):
        self.card = card
        self._drag_start_pos = None

    # ---- Mouse / Drag
    def mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        self.card.setFocus()

    def mouse_move(self, event) -> bool:
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
        ):
            if (
                event.position().toPoint() - self._drag_start_pos
            ).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag()
                self._drag_start_pos = None
                return True
        return False

    def _start_drag(self):
        drag = QDrag(self.card)
        mime = QMimeData()
        payload = {"sample_id": self.card.sample.id}
        mime.setData(
            "application/x-sample-card",
            pickle.dumps(payload),
        )
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    # ---- Focus
    def focus_in(self, event):
        self.card.setProperty("focused", True)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)

    def focus_out(self, event):
        fw = QApplication.focusWidget()
        if fw and (fw is self.card or self.card.isAncestorOf(fw)):
            return
        self.card.setProperty("focused", False)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)

    def event_filter(self, watched, event) -> bool:
        if event.type() == QEvent.MouseButtonPress:
            self.card.setFocus()
        return False
