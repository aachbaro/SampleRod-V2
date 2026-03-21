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

        # Styles: keep it minimal + aligned with SampleCard/SampleList/Waveform tokens.
        self.setStyleSheet(
            """
            QWidget#RightToolsPanelRoot {
                background-color: #121212;
            }

            /* Tools tabs: no extra frame; tabs look like subtle "chips" */
            QTabWidget#RightToolsTabs {
                background: transparent;
            }
            QTabWidget#RightToolsTabs::pane {
                border: none;
                background: transparent;
                /* Separation visuelle entre les tabs "tools" et le contenu (Directory tabs, etc.) */
                padding-top: 8px;
            }

            QTabWidget#RightToolsTabs QTabBar {
                background: transparent;
            }
            QTabWidget#RightToolsTabs QTabBar::tab {
                background: transparent;
                color: #cfcfcf;
                border: 1px solid #2a2a2a;
                border-radius: 10px;
                padding: 4px 10px;
                margin-right: 6px;
            }
            QTabWidget#RightToolsTabs QTabBar::tab:selected {
                background: #202020;
                border-color: #3a3a3a;
                color: #f5f5f5;
            }
            QTabWidget#RightToolsTabs QTabBar::tab:hover {
                background: #1f1f1f;
                border-color: #3a3a3a;
            }

            /* Chaque tool (Dossiers / Compositeur) est une carte independante */
            QWidget#DirectoryToolCard,
            QWidget#ComposerToolCard {
                background-color: #1b1b1b;
                border: 1px solid #2a2a2a;
                border-radius: 10px;
            }

            /* Directory inner tabs: remove extra pane borders/backgrounds */
            QTabWidget#DirectoryTabs {
                background: transparent;
            }
            QTabWidget#DirectoryTabs::pane {
                border: none;
                background: transparent;
            }
            QTabWidget#DirectoryTabs QTabBar {
                background: transparent;
            }
            QTabWidget#DirectoryTabs QTabBar::tab {
                background: transparent;
                color: #cfcfcf;
                border: 1px solid #2a2a2a;
                border-radius: 10px;
                padding: 3px 10px;
                /* Pas de margin ici: on a un bouton de fermeture "tabButton" a droite.
                   La margin peut faire sortir le bouton du "chip" et provoquer des
                   reflows/artefacts au survol. */
                margin-right: 0px;
            }
            QTabWidget#DirectoryTabs QTabBar::tab:selected {
                /* L'onglet actif doit donner l'impression d'etre "ouvert" (pas encapsule). */
                background: transparent;
                border: 1px solid transparent; /* garde la meme taille sans bordure visible */
                color: #f5f5f5;
                font-weight: 600;
            }
            QTabWidget#DirectoryTabs QTabBar::tab:selected:hover {
                background: transparent;
                border: 1px solid transparent;
                color: #f5f5f5;
            }
            QTabWidget#DirectoryTabs QTabBar::tab:hover {
                background: #1f1f1f;
                border-color: #3a3a3a;
            }
            """
        )
