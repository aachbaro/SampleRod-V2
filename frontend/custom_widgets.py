from PyQt6.QtWidgets import QListWidget
from PyQt6.QtGui import QDragMoveEvent
from PyQt6.QtCore import Qt

class QListWidgetDragBugFix(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def dragMoveEvent(self, e: QDragMoveEvent):
        """Corrige le bug de disparition des items lors du drag and drop."""
        if ((self.row(self.itemAt(e.pos())) == self.currentRow() + 1) 
            or (self.currentRow() == self.count() - 1 and self.row(self.itemAt(e.pos())) == -1)):
            e.ignore()
        else:
            super().dragMoveEvent(e)