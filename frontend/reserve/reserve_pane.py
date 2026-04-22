from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService
from frontend.reserve import (
    ReserveActions,
    STATUS_ALL,
    STATUS_MISSING,
    STATUS_NEEDS_ANALYSIS,
    STATUS_NON_INDEXED,
    STATUS_NORMAL,
)
from frontend.library_gui.library_widget import LibraryWidget
from frontend.right_panel.directory.directory_widget import DirectoryWidget
from frontend.sample_gui.sample.sample_list import SampleListWidget
from frontend.styles import theme


class ReservePane(QWidget):
    """Unified reserve area: folders, history, indexed library."""

    sendToLaboRequested = Signal(list)

    def __init__(self, *, directory_service: DirectoryService, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.directory_service = directory_service
        self.app_context = app_context
        self.reserve_actions = ReserveActions(self.app_context)
        self._build_ui()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda _: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("ReservePane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.title_label = QLabel("Reserve")
        self.title_label.setObjectName("ReserveTitle")

        self.subtitle_label = QLabel("Toute la matiere sonore, quel que soit son niveau d'analyse.")
        self.subtitle_label.setObjectName("ReserveSubtitle")
        self.subtitle_label.setWordWrap(True)

        self.filters_row = QWidget()
        self.filters_row.setObjectName("ReserveFiltersRow")
        filters_layout = QHBoxLayout(self.filters_row)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("ReserveSearchInput")
        self.search_input.setPlaceholderText("Rechercher un nom, un dossier, un chemin...")

        self.status_filter = QComboBox()
        self.status_filter.setObjectName("ReserveStatusFilter")
        self.status_filter.addItem("Tous les statuts", STATUS_ALL)
        self.status_filter.addItem("Normaux", STATUS_NORMAL)
        self.status_filter.addItem("Non indexes", STATUS_NON_INDEXED)
        self.status_filter.addItem("A analyser", STATUS_NEEDS_ANALYSIS)
        self.status_filter.addItem("Fichiers manquants", STATUS_MISSING)

        filters_layout.addWidget(self.search_input, 1)
        filters_layout.addWidget(self.status_filter, 0)

        self.mode_tabs = QTabWidget()
        self.mode_tabs.setObjectName("ReserveTabs")

        self.directory_widget = DirectoryWidget(
            self.directory_service,
            self.app_context,
            reserve_actions=self.reserve_actions,
        )
        self.history_widget = SampleListWidget(
            self.app_context,
            reserve_actions=self.reserve_actions,
        )
        self.indexed_widget = LibraryWidget(
            self.app_context,
            reserve_actions=self.reserve_actions,
            embedded_in_reserve=True,
        )

        self.mode_tabs.addTab(self.directory_widget, "Dossiers")
        self.mode_tabs.addTab(self.history_widget, "Historique")
        self.mode_tabs.addTab(self.indexed_widget, "Indexe")
        self.mode_tabs.setCurrentIndex(0)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.filters_row)
        layout.addWidget(self.mode_tabs, 1)

        self._apply_styles()

    def _bind_signals(self) -> None:
        self.reserve_actions.sendToLabRequested.connect(self.sendToLaboRequested.emit)
        self.reserve_actions.waveformRequested.connect(self._forward_waveform_request)
        self.directory_widget.sendToComposerRequested.connect(self.sendToLaboRequested.emit)
        self.search_input.textChanged.connect(lambda *_args: self._apply_shared_filters())
        self.status_filter.currentIndexChanged.connect(lambda *_args: self._apply_shared_filters())
        self.mode_tabs.currentChanged.connect(lambda *_args: self._apply_shared_filters())
        self._apply_shared_filters()

    def _forward_waveform_request(self, entry) -> None:
        path = getattr(entry, "path", "") or ""
        if path:
            self.sendToLaboRequested.emit([path])

    def _apply_shared_filters(self) -> None:
        query = self.search_input.text().strip()
        status_filter = self.status_filter.currentData() or STATUS_ALL
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            if hasattr(widget, "set_reserve_query"):
                widget.set_reserve_query(query)
            if hasattr(widget, "set_reserve_status_filter"):
                widget.set_reserve_status_filter(status_filter)

    def open_directory_in_folders(self, path: str) -> bool:
        folder = os.path.normpath(os.path.abspath(path)) if path else ""
        if not folder or not os.path.isdir(folder):
            return False
        self.mode_tabs.setCurrentWidget(self.directory_widget)
        self.directory_widget.set_root_directory(folder)
        return True

    def refresh_current_view(self) -> None:
        current = self.mode_tabs.currentWidget()
        if current is self.directory_widget:
            self.directory_widget.refresh_list()
            return
        if hasattr(current, "refreshList"):
            current.refreshList()
            return
        if hasattr(current, "_refresh_table"):
            current._refresh_table()

    def remove_paths_from_folders_view(self, paths: list[str] | tuple[str, ...]) -> None:
        if not paths:
            return
        self.directory_widget.remove_paths_from_current_view(list(paths))

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#ReservePane {{
                background: {p.BG_DARK};
            }}
            QLabel#ReserveTitle {{
                color: {p.TEXT};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#ReserveSubtitle {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QWidget#ReserveFiltersRow {{
                background: transparent;
            }}
            QLineEdit#ReserveSearchInput,
            QComboBox#ReserveStatusFilter {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 8px;
            }}
            QLineEdit#ReserveSearchInput:focus,
            QComboBox#ReserveStatusFilter:focus {{
                border-color: {p.INFO};
            }}
            QTabWidget#ReserveTabs::pane {{
                border: none;
                background: transparent;
                padding-top: 8px;
            }}
            QTabWidget#ReserveTabs QTabBar::tab {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 4px 10px;
                margin-right: 6px;
            }}
            QTabWidget#ReserveTabs QTabBar::tab:selected {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            QTabWidget#ReserveTabs QTabBar::tab:hover {{
                background: {p.BG_MEDIUM};
                border-color: {p.BORDER_LIGHT};
            }}
            """
        )
