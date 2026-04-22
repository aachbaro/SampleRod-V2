from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService
from frontend.labo.labo_widget import LaboWidget
from frontend.reserve.reserve_pane import ReservePane
from frontend.styles import theme


class AtelierWidget(QWidget):
    """Main workspace: Reserve on the left, Labo on the right."""

    def __init__(self, *, directory_service: DirectoryService, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.directory_service = directory_service
        self.app_context = app_context
        self._build_ui()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda _: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("AtelierRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("AtelierSplitter")

        self.reserve_pane = ReservePane(
            directory_service=self.directory_service,
            app_context=self.app_context,
        )

        self.labo_panel = LaboWidget(self.app_context)
        self.labo_panel.setObjectName("AtelierLaboPanel")

        self.splitter.addWidget(self.reserve_pane)
        self.splitter.addWidget(self.labo_panel)
        self.splitter.setSizes([520, 860])

        layout.addWidget(self.splitter, 1)
        self._apply_styles()

    def _bind_signals(self) -> None:
        self.reserve_pane.sendToLaboRequested.connect(self._send_paths_to_labo)
        self.labo_panel.openReserveDirectoryRequested.connect(self.reserve_pane.open_directory_in_folders)
        self.labo_panel.reserveRefreshRequested.connect(self.reserve_pane.refresh_current_view)
        self.labo_panel.reservePathsMoved.connect(self.reserve_pane.remove_paths_from_folders_view)

    def _send_paths_to_labo(self, paths: list[str]) -> None:
        self.labo_panel.open_paths(paths)

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#AtelierRoot {{
                background: {p.BG_DARK};
            }}
            QWidget#AtelierLaboPanel {{
                background: transparent;
                border: none;
            }}
            """
        )
