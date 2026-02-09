"""
------------------------------------------------------------------------------
Sample Composer - Clip List Widget (DnD + reorder)
------------------------------------------------------------------------------
Role
----
QListWidget specialise pour le Compositeur:
- accepte les drops externes "slice" (depuis MarkerManager)
- permet le reorder interne (drag & drop entre items)
- notifie le parent via signals Python (Qt)

Pourquoi un widget dedie ?
--------------------------
On veut un comportement DnD propre sans surcharger ComposerWidget:
- isoler la logique dragEnter/dragMove/drop
- garder ComposerWidget concentre sur "modele + rendu preview"
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget

from .composer_dnd import has_slice, has_sample_card, parse_slice_mime, parse_sample_card_mime

logger = logging.getLogger("sample_composer_clip_list")


class ComposerClipListWidget(QListWidget):
    sliceDropped = pyqtSignal(object)  # dict payload normalise
    sampleCardDropped = pyqtSignal(object)  # dict payload (sample_id)
    orderChanged = pyqtSignal(object)  # list[int] clip_ids

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        # DragDrop: permet a la fois les drops externes (Copy) et le reorder interne (Move).
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

        # Pour un widget "colonne", on ne veut pas de focus outline.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event):
        if has_slice(event.mimeData()) or has_sample_card(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if has_slice(event.mimeData()) or has_sample_card(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        # Drop externe: slice depuis MarkerManager.
        if has_slice(event.mimeData()):
            try:
                payload = parse_slice_mime(event.mimeData())
            except Exception:
                logger.exception("[Composer] Invalid slice drop")
                event.ignore()
                return

            self.sliceDropped.emit(payload)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        # Drop externe: sample card
        if has_sample_card(event.mimeData()):
            try:
                payload = parse_sample_card_mime(event.mimeData())
            except Exception:
                logger.exception("[Composer] Invalid sample-card drop")
                event.ignore()
                return

            self.sampleCardDropped.emit(payload)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        # Drop interne (reorder):
        super().dropEvent(event)
        self._emit_order_changed()

    # ------------------------------------------------------------------ helpers
    def _emit_order_changed(self) -> None:
        ids: list[int] = []
        for i in range(self.count()):
            item = self.item(i)
            try:
                cid = int(item.data(Qt.ItemDataRole.UserRole))
            except Exception:
                continue
            ids.append(cid)
        self.orderChanged.emit(ids)
