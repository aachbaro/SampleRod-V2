# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Conteneur multi-onglets de l'outil "Dossiers" du panneau droit.
# - Chaque onglet correspond a un dossier ouvert (DirectoryWidget).
# - Gere le bouton "+" pour ajouter un dossier, la restauration des dossiers
#   recents au demarrage, et la deduplication des onglets.
#
# FONCTIONS (sommaire)
# - DirectoryToolWidget     : widget conteneur (QTabWidget + bouton "+")
# - restore_directories()   : recharge les dossiers recents depuis l'historique
# - add_directory_tab()     : ajoute un onglet pour un dossier (dialogue si None)
# - _update_tab_text()      : met a jour le nom de l'onglet quand le dossier change
# - _close_directory_tab()  : ferme et supprime un onglet
#
# LIENS CLES
# - frontend/right_panel/directory/directory_widget.py   : widget de chaque onglet
# - frontend/right_panel/directory/directory_history.py  : persistance des recents
# - frontend/right_panel/tab_bar.py                      : barre d'onglets avec croix
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import logging

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QFileDialog

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.right_panel.tab_bar import HoverCloseTabBar

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService

from .directory_history import DirectoryHistory
from .directory_widget import DirectoryWidget

logger = logging.getLogger("directory_tool")


class DirectoryToolWidget(QWidget):
    """Conteneur d'onglets de DirectoryWidget (1 onglet = 1 dossier).

    Le choix du dossier se fait uniquement ici via le bouton "+", et non a
    l'interieur de chaque DirectoryWidget, pour que l'UI reste coherente.
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
        """Construit le QTabWidget avec barre d'onglets personnalisee et bouton "+"."""
        # Tool card: le style (background/border/radius) est applique via QSS
        # depuis RightToolsPanel (tools_panel.py).
        self.setObjectName("DirectoryToolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.dir_tab_widget = QTabWidget()
        self.dir_tab_widget.setObjectName("DirectoryTabs")
        # On veut un "overflow" des onglets (chips taille stable) au lieu de compresser.
        # On garde donc le mode scroll, mais on masque les fleches via HoverCloseTabBar.
        self.dir_tab_widget.setUsesScrollButtons(True)

        # Tabs UX: quand il y en a beaucoup, on prefere scroller plutot que compresser.
        tab_bar = HoverCloseTabBar()
        tab_bar.closeRequested.connect(self._close_directory_tab)
        self.dir_tab_widget.setTabBar(tab_bar)
        tab_bar.setMovable(True)
        tab_bar.setUsesScrollButtons(True)  # overflow scroll (fleches masquees)
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
        """Ajoute un onglet pour un dossier.

        Si `path` est None, ouvre un dialogue de selection de dossier.
        Si le dossier est deja ouvert dans un onglet, bascule simplement dessus
        sans en creer un second.
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
        widget.rootDirectoryChanged.connect(lambda p, w=widget: self._update_tab_text(w, p))

        tab_name = os.path.basename(path) or path
        index = self.dir_tab_widget.addTab(widget, tab_name)
        self.dir_tab_widget.setCurrentIndex(index)
        self._update_tab_text(widget, getattr(widget, "root_dir", path) or path)

    def _update_tab_text(self, widget: DirectoryWidget, path: str) -> None:
        """Met a jour le titre de l'onglet avec le nom du dossier affiche."""
        name = os.path.basename(path) or path
        idx = self.dir_tab_widget.indexOf(widget)
        if idx != -1:
            self.dir_tab_widget.setTabText(idx, name)

    def _close_directory_tab(self, index: int) -> None:
        """Retire l'onglet, detruit le widget et le supprime de l'historique."""
        w = self.dir_tab_widget.widget(index)
        if w:
            if getattr(w, "current_dir", None):
                DirectoryWidget.remove_from_history(w.current_dir)
            w.deleteLater()
        self.dir_tab_widget.removeTab(index)
