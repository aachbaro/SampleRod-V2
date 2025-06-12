from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QListWidget, QFileDialog
from PyQt6.QtCore import QMimeData, pyqtSignal

from backend.services.directory_service import DirectoryService

import os
import logging
logger = logging.getLogger("directory_widget")

class DirectoryWidget(QWidget):
    """Simple widget to import samples into a folder via drag & drop."""
    # Signal émis quand on change de dossier
    directoryChanged = pyqtSignal(str)

    def __init__(self, service: DirectoryService, parent=None):
        super().__init__(parent)
        self.service = service
        self.current_dir = ""
        self._build_ui()
        logger.info("[DirectoryWidget] Initialisation")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.choose_btn = QPushButton("Choose folder")
        self.choose_btn.clicked.connect(self._on_choose)
        self.list_widget = DirectoryListWidget(self)
        self.list_widget.setAcceptDrops(True)
        layout.addWidget(self.choose_btn)
        layout.addWidget(self.list_widget)

    def _on_choose(self):
        start_dir = self.current_dir or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "Choose folder", start_dir)
        if d:
            self.current_dir = d
            self.refresh_list()
            # On notifie que le dossier a changé
            self.directoryChanged.emit(d)
            logger.info(f"[DirectoryWidget] Dossier sélectionné : {d}")
        else:
            logger.info("[DirectoryWidget] Sélection de dossier annulée")

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event):
        if self._accepts(event.mimeData()):
            logger.info("[DirectoryWidget] dragEnter: accepté")
            event.acceptProposedAction()
        else:
            logger.info("[DirectoryWidget] dragEnter: refusé")
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not self.current_dir:
            logger.info("[DirectoryWidget] dropEvent ignoré (aucun dossier choisi)")
            event.ignore()
            return
        if self._accepts(event.mimeData()):
            logger.info("[DirectoryWidget] dropEvent accepté")
            self.service.handle_drop(self.current_dir, event.mimeData())
            self.refresh_list()
            event.acceptProposedAction()
        else:
            logger.info("[DirectoryWidget] dropEvent refusé")
            event.ignore()

    def _accepts(self, mime: QMimeData) -> bool:
        return (
            mime.hasFormat("application/x-sample-slice-data")
            or mime.hasFormat("application/x-sample-card")
        )

    def refresh_list(self):
        self.list_widget.clear()
        if self.current_dir:
            files = self.service.list_samples(self.current_dir)
            logger.info(f"[DirectoryWidget] Rafraîchissement de la liste ({len(files)} fichiers)")
            for name in files:
                self.list_widget.addItem(name)



class DirectoryListWidget(QListWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.parent_widget = parent  # ton DirectoryWidget

    def dragEnterEvent(self, event):
        fmt = event.mimeData().formats()
        print("DirectoryListWidget dragEnter formats:", fmt)
        if self.parent_widget._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not self.parent_widget.current_dir:
            event.ignore()
            return
        if self.parent_widget._accepts(event.mimeData()):
            self.parent_widget.service.handle_drop(
                self.parent_widget.current_dir,
                event.mimeData()
            )
            self.parent_widget.refresh_list()
            event.acceptProposedAction()
        else:
            event.ignore()