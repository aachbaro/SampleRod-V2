# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Conteneur du panneau droit de la fenetre principale.
# - Regroupe dans un QTabWidget deux outils principaux :
#   * Onglet "Dossiers" : DirectoryToolWidget (navigation multi-onglets de dossiers)
#   * Onglet "Compositeur" : SampleComposerWidget (composition de patterns de slices)
# - Isole la logique des outils de MainWindow pour garder cette derniere courte.
#
# FONCTIONS (sommaire)
# - RightToolsPanel    : widget conteneur avec QTabWidget
# - _build_ui()        : construit les deux onglets et applique les styles
# - _apply_stylesheet() : QSS dynamique du panneau et de ses onglets imbriques
#
# LIENS CLES
# - frontend/right_panel/directory/directory_tool.py   : onglet Dossiers
# - frontend/right_panel/composer/composer_widget.py   : onglet Compositeur
# - frontend/main_window.py                            : instancie ce widget
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService

from .directory.directory_tool import DirectoryToolWidget
from .composer.composer_widget import SampleComposerWidget
from frontend.styles import theme


class RightToolsPanel(QWidget):
    """Panneau droit de la fenetre principale : regroupe Dossiers et Compositeur."""

    def __init__(self, *, directory_service: DirectoryService, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.directory_service = directory_service
        self.app_context = app_context
        self._build_ui()

    def _build_ui(self) -> None:
        """Construit le QTabWidget avec les deux onglets et applique les styles."""
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
        """Applique la feuille de style QSS du panneau et des onglets imbriques."""
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
