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
