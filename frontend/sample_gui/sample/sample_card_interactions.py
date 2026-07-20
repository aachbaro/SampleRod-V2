# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere les interactions "carte": focus visuel + drag & drop.
# - Encapsule la logique de drag (QDrag/QMimeData avec pickle payload).
# - Centralise le comportement de focus (click -> focus, flash animation).
#
# FONCTIONS (sommaire)
# - SampleCardInteractions  : controleur d'interactions
# - mouse_press / mouse_move : detection du drag (seuil manhattanLength)
# - _start_drag              : cree un QDrag avec MIME "application/x-sample-card"
# - focus_in / focus_out     : met a jour la propriete QSS "focused"
# - _flash_focus             : animation opacity 0.55 -> 1.0 au focus (150 ms)
# - event_filter             : donne le focus sur MouseButtonPress enfant
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py           : carte parente
# - frontend/right_panel/composer/composer_dnd.py       : cote recepteur
# -----------------------------------------------------------------------------

from __future__ import annotations

import pickle

import logging

from PySide6.QtCore import Qt, QEvent, QMimeData, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect

logger = logging.getLogger("sample_card_dnd")


class SampleCardInteractions:
    """Controleur de focus et de drag & drop pour une SampleCard."""

    def __init__(self, card):
        self.card = card
        self._drag_start_pos = None

    # ---- Mouse / Drag
    def mouse_press(self, event):
        """Enregistre la position de depart du drag et donne le focus a la carte."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        self.card.setFocus()

    def mouse_move(self, event) -> bool:
        """Demarre un QDrag si le deplacement depasse QApplication.startDragDistance()."""
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
        """Cree et execute un QDrag avec payload pickle {"sample_id": id}."""
        sample_id = getattr(self.card.sample, "id", None)
        logger.info("[SampleCard] drag start (sample_id=%s)", sample_id)
        drag = QDrag(self.card)
        mime = QMimeData()
        payload = {"sample_id": self.card.sample.id}
        mime.setData(
            "application/x-sample-card",
            pickle.dumps(payload),
        )
        drag.setMimeData(mime)
        result = drag.exec(Qt.DropAction.CopyAction)
        logger.info("[SampleCard] drag end (result=%s)", result)

    # ---- Focus
    def focus_in(self, event):
        """Active la propriete QSS "focused" et lance le flash d'animation."""
        self.card.setProperty("focused", True)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        self._flash_focus()

    def _flash_focus(self):
        """Brief opacity flash (0.55 → 1.0, 150 ms) for a snappy focus feel."""
        effect = QGraphicsOpacityEffect(self.card)
        self.card.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self.card)
        anim.setDuration(150)
        anim.setStartValue(0.55)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.card.setGraphicsEffect(None))
        self.card._focus_anim = anim  # keep reference to avoid GC
        anim.start()

    def focus_out(self, event):
        """Desactive la propriete "focused" sauf si le focus reste dans la carte."""
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
