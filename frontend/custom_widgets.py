# custom_widgets.py

from PyQt6.QtWidgets import QListWidget, QSlider, QStyle
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QDragMoveEvent, QDragEnterEvent, QDropEvent

class QListWidgetDragBugFix(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, e: QDragEnterEvent):
        e.acceptProposedAction()

    def dragMoveEvent(self, e: QDragMoveEvent):
        # pour ne pas perdre l’item sous Windows
        row_under = self.row(self.itemAt(e.pos()))
        if ((row_under == self.currentRow() + 1) or
            (self.currentRow() == self.count() - 1 and row_under == -1)):
            e.ignore()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e: QDropEvent):
        src_row = self.currentRow()
        dest_row = self.row(self.itemAt(e.pos()))
        if dest_row < 0:
            dest_row = self.count() - 1

        # on récupère l'item et son widget
        item = self.takeItem(src_row)
        widget = self.itemWidget(item)
        if widget:
            self.removeItemWidget(item)

        # on le ré‐insère à la bonne place
        self.insertItem(dest_row, item)
        if widget:
            self.setItemWidget(item, widget)

        self.setCurrentRow(dest_row)
        e.acceptProposedAction()

        # enfin on notifie qu’il faut re‐sauvegarder l’ordre
        parent = self.parent()
        while parent and not hasattr(parent, 'updateLibraryOrder'):
            parent = parent.parent()
        if parent:
            parent.updateLibraryOrder()

class CustomSlider(QSlider):
    def mousePressEvent(self, event):
        """Permet de positionner directement le slider là où on clique."""
        if self.orientation() == Qt.Orientation.Horizontal:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().x()),
                self.width(),
                self.invertedAppearance()
            )
        else:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().y()),
                self.height(),
                self.invertedAppearance()
            )

        self.setValue(value)
        self.sliderMoved.emit(value)
        super().mousePressEvent(event)