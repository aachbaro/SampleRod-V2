from PyQt6.QtWidgets import QListWidget, QSlider, QStyle
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

class CustomSlider(QSlider):
    def mousePressEvent(self, event):
        """Permet de positionner directement le slider là où on clique"""
        if self.orientation() == Qt.Horizontal:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().x()),  # Convertir en entier
                self.width(),
                self.invertedAppearance()
            )
        else:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().y()),  # Convertir en entier
                self.height(),
                self.invertedAppearance()
            )

        self.setValue(value)
        self.sliderMoved.emit(value)  # Émet le signal pour que l'UI suive immédiatement
        super().mousePressEvent(event)