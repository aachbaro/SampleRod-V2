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

import os
import pickle

import logging

from PySide6.QtCore import Qt, QEvent, QMimeData, QPropertyAnimation, QEasingCurve, QUrl
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QComboBox,
    QCheckBox,
    QGraphicsOpacityEffect,
    QLineEdit,
    QMenu,
    QSlider,
    QWidget,
)
from frontend.dragdrop import (
    DragItem, DragKind, DragPayload, DragProvenance,
    MaterialOperation, MaterialStatus,
    attach_payload, drag_preview_pixmap, drag_session,
)

logger = logging.getLogger("sample_card_dnd")


class SampleCardInteractions:
    """Controleur de focus et de drag & drop pour une SampleCard."""

    def __init__(self, card):
        self.card = card
        self._drag_start_pos = None
        self._drag_source = None
        self._checkbox_width_animation = None

    def set_checkbox_revealed(self, revealed: bool) -> None:
        """Anime la place de la checkbox sans modifier la hauteur de carte."""
        checkbox = self.card.checkbox
        revealed = bool(revealed or checkbox.isChecked())
        for animation in (self._checkbox_width_animation,):
            if animation is not None:
                animation.stop()

        target_width = checkbox.sizeHint().width() if revealed else 0
        if revealed:
            checkbox.show()
        width_animation = QPropertyAnimation(checkbox, b"maximumWidth", checkbox)
        width_animation.setDuration(150)
        width_animation.setStartValue(checkbox.maximumWidth())
        width_animation.setEndValue(target_width)
        width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        if not revealed:
            width_animation.finished.connect(
                lambda: checkbox.hide() if not checkbox.isChecked() else None
            )
        self._checkbox_width_animation = width_animation
        width_animation.start()

    @staticmethod
    def _event_point(event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "position"):
            return event.position().toPoint()
        if hasattr(event, "pos"):
            return event.pos()
        return None

    @staticmethod
    def _is_passive_drag_source(widget: QWidget | None) -> bool:
        return not isinstance(
            widget,
            (QAbstractButton, QSlider, QLineEdit, QComboBox, QMenu),
        )

    # ---- Mouse / Drag
    def mouse_press(self, event):
        """Enregistre la position de depart du drag et donne le focus a la carte."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = self._event_point(event)
            self._drag_source = self.card
        self.card.setFocus()

    def mouse_move(self, event) -> bool:
        """Demarre un QDrag si le deplacement depasse QApplication.startDragDistance()."""
        current_pos = self._event_point(event)
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
            and current_pos is not None
        ):
            if (current_pos - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag()
                self._drag_start_pos = None
                self._drag_source = None
                return True
        return False

    def _start_drag(self):
        """Cree un drag mixte : fichier copiable a l'exterieur + MIME interne.

        - `text/uri-list` permet de deposer le sample vers le bureau ou
          l'explorateur Windows en mode copie.
        - `application/x-sample-card` conserve le comportement interne vers
          le Compositeur / Labo.
        """
        sample_id = getattr(self.card.sample, "id", None)
        logger.info("[SampleCard] drag start (sample_id=%s)", sample_id)
        drag = QDrag(self.card)
        mime = QMimeData()
        file_path = str(getattr(self.card.sample, "path", "") or "").strip()
        if file_path and os.path.isfile(file_path):
            mime.setUrls([QUrl.fromLocalFile(file_path)])
        payload = {"sample_id": self.card.sample.id}
        mime.setData(
            "application/x-sample-card",
            pickle.dumps(payload),
        )
        descriptor = DragPayload(
            kind=DragKind.AUDIO_FILE,
            items=(DragItem(
                item_id=str(sample_id or ""),
                path=file_path,
                display_name=os.path.basename(file_path) or "Sample",
            ),),
            source_id=f"sample-card:{sample_id}",
            source_module="reserve",
            status=MaterialStatus.SOURCE,
            provenance=DragProvenance(file_path, MaterialOperation.IMPORT),
        )
        attach_payload(mime, descriptor)
        drag.setMimeData(mime)
        drag.setPixmap(drag_preview_pixmap(descriptor))
        with drag_session(descriptor):
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
            # Cocher pour une action bulk ne change pas l'entrée inspectée.
            if isinstance(watched, QCheckBox):
                return False
            self.card.setFocus()
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._is_passive_drag_source(watched)
            ):
                self._drag_start_pos = self._event_point(event)
                self._drag_source = watched
        elif (
            event.type() == QEvent.MouseMove
            and watched is self._drag_source
            and self._is_passive_drag_source(watched)
            and self.mouse_move(event)
        ):
            return True
        elif event.type() in (
            QEvent.MouseButtonRelease,
            QEvent.Leave,
        ):
            self._drag_start_pos = None
            self._drag_source = None
        return False
