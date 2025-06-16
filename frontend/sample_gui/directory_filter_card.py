from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
import qtawesome as qta


class DirectoryFilterCard(QWidget):
    """Small clickable card representing a sample directory."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, path: str, active: bool = True, parent=None):
        super().__init__(parent)
        self.path = path
        self.is_active = active
        self.setObjectName("DirectoryFilterCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(qta.icon('fa5s.folder').pixmap(16, 16))
        self.text_label = QLabel(self._display_name())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)

        self._update_style()

    def _display_name(self) -> str:
        import os
        name = os.path.basename(self.path)
        return name or self.path

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_active(not self.is_active)
            self.toggled.emit(self.path, self.is_active)
        super().mousePressEvent(event)

    def set_active(self, active: bool):
        self.is_active = active
        self._update_style()

    def _update_style(self):
        self.setProperty("active", self.is_active)
        self.setStyleSheet(
            """
            DirectoryFilterCard {
                border: 1px solid #555;
                border-radius: 6px;
            }
            DirectoryFilterCard[active="true"] {
                background-color: #555;
                color: white;
            }
            DirectoryFilterCard[active="false"] {
                background-color: #333;
                color: #888;
            }
            """
        )
        self.style().polish(self)

