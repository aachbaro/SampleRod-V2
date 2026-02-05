"""
------------------------------------------------------------------------------
Directory Tool (Tabbed Container)
------------------------------------------------------------------------------
Role
----
Ce module contient le conteneur "Directory tool" du Right Panel.

Concretement, il gere:
- un QTabWidget de dossiers (plusieurs onglets DirectoryWidget, 1 par dossier)
- un bouton "+" (en bas a droite) pour ajouter un dossier (QFileDialog)
- la restauration automatique des dossiers recents (QSettings / DirectoryHistory)

Pourquoi ce fichier existe ?
----------------------------
On veut que MainWindow ne soit pas l'endroit ou toute la logique UI s'accumule.
MainWindow orchestre l'application; les outils du panneau droit s'occupent de leur
propre UI + cycle de vie.

Position dans l'architecture
----------------------------
- DirectoryToolWidget (ce fichier) : conteneur multi-onglets (dossiers)
- DirectoryWidget : UI/interaction pour un dossier donne (liste, DnD, preview, etc.)
- DirectoryHistory : persistance de l'historique (last/recent)
------------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import logging

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QFileDialog

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.right_panel.tab_bar import HoverCloseTabBar

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService

from .directory_history import DirectoryHistory
from .directory_widget import DirectoryWidget

logger = logging.getLogger("directory_tool")


class DirectoryToolWidget(QWidget):
    """
    Conteneur d'onglets de DirectoryWidget (1 onglet = 1 dossier).

    Note: on a volontairement retire le "Choose folder" interne a DirectoryWidget.
    Le choix du dossier se fait uniquement ici, via le bouton "+".
    """

    def __init__(self, *, directory_service: DirectoryService, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.directory_service = directory_service
        self.app_context = app_context

        self._qs = QSettings("SampleRod", "Main")
        self.history = DirectoryHistory(self._qs)

        self._build_ui()
        self.restore_directories()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        # Tool card: le style (background/border/radius) est applique via QSS
        # depuis RightToolsPanel (tools_panel.py).
        self.setObjectName("DirectoryToolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.dir_tab_widget = QTabWidget()
        self.dir_tab_widget.setObjectName("DirectoryTabs")

        # Tabs UX: quand il y en a beaucoup, on prefere scroller plutot que compresser.
        tab_bar = HoverCloseTabBar()
        tab_bar.closeRequested.connect(self._close_directory_tab)
        self.dir_tab_widget.setTabBar(tab_bar)
        self.dir_tab_widget.setUsesScrollButtons(False)
        tab_bar.setMovable(True)
        tab_bar.setUsesScrollButtons(False)  # pas de fleches
        tab_bar.setExpanding(False)
        tab_bar.setElideMode(Qt.TextElideMode.ElideRight)

        layout.addWidget(self.dir_tab_widget)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)

        self.add_dir_btn = HoverIconButton(
            icon_name="fa5s.plus",
            size=24,
            icon_size=10,
            icon_color_normal="#cfcfcf",
            icon_color_hover="#121212",
            border_color="#2a2a2a",
            parent=self,
        )
        self.add_dir_btn.setToolTip("Ajouter un dossier")
        self.add_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_dir_btn.clicked.connect(self.add_directory_tab)

        footer.addWidget(self.add_dir_btn)
        layout.addLayout(footer)

    # ------------------------------------------------------------------ actions
    def restore_directories(self) -> None:
        """Rouvre les dossiers recents (s'ils existent encore)."""
        dirs = self.history.get_recent_directories()
        missing = []
        for path in dirs:
            if os.path.exists(path):
                self.add_directory_tab(path)
            else:
                missing.append(path)

        if missing:
            logger.info(f"[DirectoryTool] Dossiers introuvables: {missing}")

    def add_directory_tab(self, path: str | None = None) -> None:
        """
        Ajoute un onglet "directory" pour un dossier.
        Si path est None, on ouvre un QFileDialog.
        """
        if not path:
            start_dir = self.history.get_last_directory() or os.path.expanduser("~")
            selected = QFileDialog.getExistingDirectory(self, "Choisir un dossier", start_dir)
            if not selected:
                return
            path = selected

        # Evite d'ouvrir deux onglets sur le meme dossier.
        for i in range(self.dir_tab_widget.count()):
            existing = self.dir_tab_widget.widget(i)
            if getattr(existing, "current_dir", None) == path:
                self.dir_tab_widget.setCurrentIndex(i)
                return

        widget = DirectoryWidget(self.directory_service, self.app_context, path=path)
        widget.directoryChanged.connect(lambda p, w=widget: self._update_tab_text(w, p))

        tab_name = os.path.basename(path) or path
        index = self.dir_tab_widget.addTab(widget, tab_name)
        self.dir_tab_widget.setCurrentIndex(index)
        self._update_tab_text(widget, path)

    def _update_tab_text(self, widget: DirectoryWidget, path: str) -> None:
        name = os.path.basename(path) or path
        idx = self.dir_tab_widget.indexOf(widget)
        if idx != -1:
            self.dir_tab_widget.setTabText(idx, name)

    def _close_directory_tab(self, index: int) -> None:
        w = self.dir_tab_widget.widget(index)
        if w:
            if getattr(w, "current_dir", None):
                DirectoryWidget.remove_from_history(w.current_dir)
            w.deleteLater()
        self.dir_tab_widget.removeTab(index)
