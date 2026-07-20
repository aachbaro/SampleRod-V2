"""
------------------------------------------------------------------------------
Directory List Widget (Drop Target)
------------------------------------------------------------------------------
Role
----
Liste des fichiers du dossier courant, et point principal de drag & drop.

Le DirectoryWidget reste un orchestrateur (choix dossier, refresh, preview...),
et cette liste devient:
- la zone de drop (acceptation + dropEvent)
- le conteneur des "rows" DirectoryListItemWidget

La logique de validation / traitement DnD est centralisee dans directory_dnd.py.
------------------------------------------------------------------------------
"""

from __future__ import annotations

from typing import Any

import logging

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtWidgets import QListWidget

from . import directory_dnd

logger = logging.getLogger("directory_list_widget")


class DirectoryListWidget(QListWidget):
    """
    QListWidget specialisee pour servir de drop target.

    NOTE:
    - On garde une reference au parent "DirectoryWidget" (parent_widget) afin de
      deleguer le traitement (DirectoryService + refresh_list).
    - On pourra remplacer cela par une interface/controller plus tard.
    """

    def __init__(self, parent_widget: Any):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        logger.info("[DirectoryListWidget] Initialisation DnD (start)")
        self.setAcceptDrops(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        logger.info("[DirectoryListWidget] DnD target ready (acceptDrops=True)")

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event):
        if directory_dnd.accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        logger.info(
            "[DirectoryListWidget] drop (formats=%s)",
            list(event.mimeData().formats()),
        )
        if directory_dnd.handle_drop(self.parent_widget, event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            # Move selection to prev/next selectable row
            current = self.currentRow()
            direction = -1 if key == Qt.Key.Key_Up else 1
            target = current + direction
            while 0 <= target < self.count():
                item = self.item(target)
                if item is not None and item.flags() & Qt.ItemFlag.ItemIsSelectable:
                    self.setCurrentRow(target)
                    break
                target += direction
            event.accept()
            return
        if key in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Right,
            Qt.Key.Key_Space,
            Qt.Key.Key_F2,
            Qt.Key.Key_Left,
            Qt.Key.Key_Delete,
        ):
            # Delegate to the currently focused item widget
            w = self.itemWidget(self.currentItem()) if self.currentItem() else None
            if w is not None:
                w.keyPressEvent(event)
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refresh_item_widths)

    def _refresh_item_widths(self):
        viewport_width = max(0, self.viewport().width() - 14)
        for row in range(self.count()):
            item = self.item(row)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            item.setSizeHint(QSize(viewport_width, max(1, widget.sizeHint().height(), widget.height())))
