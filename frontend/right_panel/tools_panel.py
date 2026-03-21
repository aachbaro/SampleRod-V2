"""
------------------------------------------------------------------------------
Right Tools Panel (Container)
------------------------------------------------------------------------------
Role
----
Ce module regroupe les "outils" qui vivent dans le panneau de droite
de MainWindow.

Pourquoi ?
----------
MainWindow doit rester une orchestration globale. Les outils (Directory,
Sample Composer, etc.) ont chacun leurs sous-composants, leurs styles et leur
cycle de vie. Les regrouper ici permet:
- une arborescence claire (frontend/right_panel/*)
- un endroit unique pour ajouter de nouveaux outils
- moins de code UI dans MainWindow

Contenu
-------
- Onglet "Dossiers" : DirectoryToolWidget (multi-onglets de dossiers)
- Onglet "Compositeur" : SampleComposerWidget (MVP: drop de slices + preview)
------------------------------------------------------------------------------
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService

from .directory.directory_tool import DirectoryToolWidget
from .composer.composer_widget import SampleComposerWidget
from frontend.styles import theme


class RightToolsPanel(QWidget):
    def __init__(self, *, directory_service: DirectoryService, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.directory_service = directory_service
        self.app_context = app_context
        self._build_ui()

    def _build_ui(self) -> None:
        # Root = background of the right side area (like SampleListRoot).
        self.setObjectName("RightToolsPanelRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.tools_tabs = QTabWidget()
        self.tools_tabs.setObjectName("RightToolsTabs")

        self.directory_tool = DirectoryToolWidget(
            directory_service=self.directory_service,
            app_context=self.app_context,
        )
        self.composer_tool = SampleComposerWidget(self.app_context)

        self.tools_tabs.addTab(self.directory_tool, "Dossiers")
        self.tools_tabs.addTab(self.composer_tool, "Compositeur")

        layout.addWidget(self.tools_tabs)
        self._apply_stylesheet()
        theme.manager.themeChanged.connect(lambda _: self._apply_stylesheet())

    def _apply_stylesheet(self):
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#RightToolsPanelRoot {{
                background-color: {p.BG_DARK};
            }}

            QTabWidget#RightToolsTabs {{
                background: transparent;
            }}
            QTabWidget#RightToolsTabs::pane {{
                border: none;
                background: transparent;
                padding-top: 8px;
            }}
            QTabWidget#RightToolsTabs QTabBar {{
                background: transparent;
            }}
            QTabWidget#RightToolsTabs QTabBar::tab {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 4px 10px;
                margin-right: 6px;
            }}
            QTabWidget#RightToolsTabs QTabBar::tab:selected {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            QTabWidget#RightToolsTabs QTabBar::tab:hover {{
                background: {p.BG_MEDIUM};
                border-color: {p.BORDER_LIGHT};
            }}

            QWidget#DirectoryToolCard,
            QWidget#ComposerToolCard {{
                background-color: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}

            QTabWidget#DirectoryTabs {{
                background: transparent;
            }}
            QTabWidget#DirectoryTabs::pane {{
                border: none;
                background: transparent;
            }}
            QTabWidget#DirectoryTabs QTabBar {{
                background: transparent;
            }}
            QTabWidget#DirectoryTabs QTabBar::tab {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
                padding: 3px 10px;
                margin-right: 0px;
            }}
            QTabWidget#DirectoryTabs QTabBar::tab:selected {{
                background: transparent;
                border: 1px solid transparent;
                color: {p.TEXT};
                font-weight: 600;
            }}
            QTabWidget#DirectoryTabs QTabBar::tab:selected:hover {{
                background: transparent;
                border: 1px solid transparent;
                color: {p.TEXT};
            }}
            QTabWidget#DirectoryTabs QTabBar::tab:hover {{
                background: {p.BG_MEDIUM};
                border-color: {p.BORDER_LIGHT};
            }}
            """
        )
