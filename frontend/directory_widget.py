from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QListWidget, QFileDialog
from PyQt6.QtCore import QMimeData

from backend.services.directory_service import DirectoryService

import os


class DirectoryWidget(QWidget):
    """Simple widget to import samples into a folder via drag & drop."""

    def __init__(self, service: DirectoryService, parent=None):
        super().__init__(parent)
        self.service = service
        self.current_dir = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.choose_btn = QPushButton("Choose folder")
        self.choose_btn.clicked.connect(self._on_choose)
        self.list_widget = QListWidget()
        self.list_widget.setAcceptDrops(True)
        layout.addWidget(self.choose_btn)
        layout.addWidget(self.list_widget)

    def _on_choose(self):
        start_dir = self.current_dir or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "Choose folder", start_dir)
        if d:
            self.current_dir = d
            self.refresh_list()

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event):
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not self.current_dir:
            event.ignore()
            return
        if self._accepts(event.mimeData()):
            self.service.handle_drop(self.current_dir, event.mimeData())
            self.refresh_list()
            event.acceptProposedAction()
        else:
            event.ignore()

    def _accepts(self, mime: QMimeData) -> bool:
        return (
            mime.hasFormat("application/x-sample-slice-data")
            or mime.hasFormat("application/x-sample-card")
        )

    def refresh_list(self):
        self.list_widget.clear()
        if self.current_dir:
            for name in self.service.list_samples(self.current_dir):
                self.list_widget.addItem(name)

