from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import pyqtSignal
import os

class DirectoryFilterCard(QPushButton):
    """Small toggle button representing a directory for filtering."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, directory: str, active: bool = True, parent=None):
        super().__init__(os.path.basename(directory), parent)
        self.directory = directory
        self.setCheckable(True)
        self.setChecked(active)
        self.clicked.connect(self._emit_toggled)

    def _emit_toggled(self, checked: bool):
        self.toggled.emit(self.directory, checked)

