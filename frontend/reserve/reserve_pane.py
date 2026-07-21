# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Panneau principal de la Reserve, affiche dans le premier onglet de la
#   fenetre principale.
# - Regroupe trois onglets : Dossiers (DirectoryWidget), Historique
#   (SampleListWidget), Indexe (LibraryWidget).
# - Fournit une barre de filtres partagee (recherche + statut) qui pilote
#   les trois onglets simultanement.
# - Gere le filtre de gammes compatibles : quand un sample selectionne a une
#   gamme detectee, un chip s'affiche et tous les onglets sont filtres.
# - Gere le bouton "Analyser" qui lance la detection de gamme sur le dossier
#   courant ou sur toute la base.
#
# FONCTIONS (sommaire)
# - ReservePane              : widget principal
# - _build_ui()              : construit la barre de filtres, le chip gamme et les onglets
# - _bind_signals()          : connecte filtres, onglets, bouton analyse, filtre gamme
# - _apply_shared_filters()  : propage recherche + statut a tous les onglets
# - open_directory_in_folders() : bascule vers l'onglet Dossiers et navigue
# - refresh_current_view()   : rafraichit l'onglet courant
# - _on_batch_analyze()      : lance la detection de gamme (dossier ou global)
# - _on_compat_filter_changed() : propage le filtre gamme a tous les onglets
# - _apply_styles()          : QSS dynamique depuis le theme
#
# LIENS CLES
# - frontend/right_panel/directory/directory_widget.py : onglet Dossiers
# - frontend/sample_gui/sample/sample_list.py          : onglet Historique
# - frontend/library_gui/library_widget.py             : onglet Indexe
# - frontend/reserve/reserve_actions.py                : actions partagees
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService
from frontend.ui import IconButton
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
    """Zone Reserve unifiee : regroupe Dossiers, Historique et Bibliotheque indexee.

    Signal :
        sendToLaboRequested(list[str]) : emis quand l'utilisateur envoie des
                                         fichiers vers le Labo depuis n'importe
                                         quel onglet.
    """

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
        """Construit la barre de filtres, le chip de filtre gamme et les trois onglets."""
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

        # Bouton analyse par lots (gamme) — libelle mis a jour dynamiquement selon l'onglet
        self.batch_analyze_btn = IconButton(
            "music",
            tooltip="Analyser les gammes du contexte courant",
            size="m",
        )
        self.batch_analyze_btn.setObjectName("BatchAnalyzeBtn")

        filters_layout.addWidget(self.search_input, 1)
        filters_layout.addWidget(self.status_filter, 0)
        filters_layout.addWidget(self.batch_analyze_btn, 0)

        # Chip de filtre gamme compatible (masquee par defaut)
        self.compat_filter_row = QWidget()
        self.compat_filter_row.setObjectName("CompatFilterRow")
        compat_row_layout = QHBoxLayout(self.compat_filter_row)
        compat_row_layout.setContentsMargins(0, 0, 0, 0)
        compat_row_layout.setSpacing(6)

        self.compat_filter_label = QLabel("")
        self.compat_filter_label.setObjectName("CompatFilterLabel")

        self.compat_filter_clear_btn = IconButton(
            "x",
            tooltip="Effacer le filtre de compatibilite",
            size="s",
        )
        self.compat_filter_clear_btn.setObjectName("CompatFilterClearBtn")

        compat_row_layout.addWidget(self.compat_filter_label)
        compat_row_layout.addWidget(self.compat_filter_clear_btn)
        compat_row_layout.addStretch()
        self.compat_filter_row.setVisible(False)

        def _clear_compat_filter_from_double_click(event) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._clear_compat_filter()
                event.accept()
                return
            QWidget.mouseDoubleClickEvent(self.compat_filter_label, event)

        self.compat_filter_label.mouseDoubleClickEvent = _clear_compat_filter_from_double_click  # type: ignore[assignment]

        self.mode_tabs = QTabWidget()
        self.mode_tabs.setObjectName("ReserveTabs")

        self.directory_widget = DirectoryWidget(
            self.directory_service,
            self.app_context,
            reserve_actions=self.reserve_actions,
            embedded_in_reserve=True,
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
        layout.addWidget(self.compat_filter_row)
        layout.addWidget(self.mode_tabs, 1)

        self._apply_styles()

    def _bind_signals(self) -> None:
        """Connecte les signaux de tous les onglets, filtres et boutons."""
        self.reserve_actions.sendToLabRequested.connect(self.sendToLaboRequested.emit)
        self.reserve_actions.waveformRequested.connect(self._forward_waveform_request)
        self.directory_widget.sendToComposerRequested.connect(self.sendToLaboRequested.emit)
        self.search_input.textChanged.connect(lambda *_args: self._apply_shared_filters())
        self.status_filter.currentIndexChanged.connect(lambda *_args: self._apply_shared_filters())
        self.mode_tabs.currentChanged.connect(lambda *_args: self._apply_shared_filters())
        # Mise a jour du libelle du bouton selon l'onglet/dossier actif
        self.mode_tabs.currentChanged.connect(lambda *_args: self._update_batch_btn_label())
        self.directory_widget.directoryChanged.connect(lambda *_args: self._update_batch_btn_label())
        # Analyse par lots
        self.batch_analyze_btn.clicked.connect(self._on_batch_analyze)
        # Filtre gamme compatible
        self.compat_filter_clear_btn.clicked.connect(self._clear_compat_filter)
        self.history_widget.compatFilterChanged.connect(self._on_compat_filter_changed)
        self.directory_widget.compatFilterChanged.connect(self._on_compat_filter_changed)
        # Ouvrir l'emplacement depuis une carte de l'historique
        self.history_widget.openInFoldersRequested.connect(self._open_in_folders)
        self._apply_shared_filters()
        self._update_batch_btn_label()

    def _forward_waveform_request(self, entry) -> None:
        """Retransmet une demande d'ouverture de waveform comme sendToLaboRequested."""
        path = getattr(entry, "path", "") or ""
        if path:
            self.sendToLaboRequested.emit([path])

    def _apply_shared_filters(self) -> None:
        """Propage la recherche et le filtre de statut a tous les onglets."""
        query = self.search_input.text().strip()
        status_filter = self.status_filter.currentData() or STATUS_ALL
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            if hasattr(widget, "set_reserve_query"):
                widget.set_reserve_query(query)
            if hasattr(widget, "set_reserve_status_filter"):
                widget.set_reserve_status_filter(status_filter)

    def open_directory_in_folders(self, path: str) -> bool:
        """Bascule sur l'onglet Dossiers et navigue vers le chemin donne.

        Retourne False si le chemin n'existe pas ou n'est pas un dossier.
        """
        folder = os.path.normpath(os.path.abspath(path)) if path else ""
        if not folder or not os.path.isdir(folder):
            return False
        self.mode_tabs.setCurrentWidget(self.directory_widget)
        self.directory_widget.set_root_directory(folder)
        return True

    def refresh_current_view(self) -> None:
        """Rafraichit le contenu de l'onglet actuellement visible."""
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
        """Retire des chemins de la vue Dossiers (apres un import ou un deplaacement)."""
        if not paths:
            return
        self.directory_widget.remove_paths_from_current_view(list(paths))

    # ------------------------------------------------------------------ analyse

    def _current_folder_for_analysis(self) -> str | None:
        """Retourne le dossier courant si on est sur l'onglet Dossiers, sinon None."""
        if self.mode_tabs.currentWidget() is self.directory_widget:
            return getattr(self.directory_widget, "current_dir", None) or None
        return None

    def _update_batch_btn_label(self) -> None:
        """Met a jour le libelle/tooltip du bouton selon le contexte (dossier ou global)."""
        folder = self._current_folder_for_analysis()
        if folder:
            self.batch_analyze_btn.set_icon_name("music")
            folder_name = os.path.basename(folder) or folder
            self.batch_analyze_btn.setToolTip(
                "Detecte la gamme des samples de : " + folder_name + "\n"
                "Les autres samples de la base ne sont pas relances."
            )
        else:
            self.batch_analyze_btn.set_icon_name("music")
            self.batch_analyze_btn.setToolTip(
                "Lance la detection de gamme sur tous les samples non encore analyses."
            )

    def _on_batch_analyze(self) -> None:
        """Lance l'analyse de gamme — dossier courant si onglet Dossiers, sinon toute la DB."""
        folder = self._current_folder_for_analysis()
        if folder:
            count = self.app_context.sample_store.batch_analyze_folder(folder)
        else:
            count = self.app_context.sample_store.batch_analyze_missing()
        if count == 0:
            self.batch_analyze_btn.set_icon_name("check")
            self.batch_analyze_btn.setToolTip("Tous les samples du contexte sont deja analyses.")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, self._update_batch_btn_label)
        else:
            self.batch_analyze_btn.set_icon_name("refresh")
            self.batch_analyze_btn.setToolTip(f"Analyse de {count} sample(s) en cours.")
            self.batch_analyze_btn.setEnabled(False)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._reset_batch_btn)

    def _reset_batch_btn(self) -> None:
        """Remet le bouton d'analyse en etat actif apres le delai d'attente."""
        self.batch_analyze_btn.setEnabled(True)
        self.batch_analyze_btn.set_icon_name("music")
        self._update_batch_btn_label()

    # ------------------------------------------------------------------ filtre gamme

    def _on_compat_filter_changed(self, sample_id: int) -> None:
        """Propage le filtre gamme a tous les onglets et met a jour le chip."""
        if sample_id == 0:
            self.history_widget.set_compatible_scales_filter(None)
            self.indexed_widget.set_compatible_scales_filter(None)
            self.directory_widget.set_compatible_scales_filter(None)
            self.compat_filter_row.setVisible(False)
            return
        self.history_widget.set_compatible_scales_filter(sample_id)
        self.indexed_widget.set_compatible_scales_filter(sample_id)
        self.directory_widget.set_compatible_scales_filter(sample_id)
        ref = next(
            (s for s in self.app_context.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        note = getattr(ref, "detected_scale_label", None) if ref else None
        if not note and ref is not None:
            note = getattr(ref, "dominant_note", None)
        name = getattr(ref, "name", None) if ref else None
        label_name = note or (os.path.basename(name) if name else "#" + str(sample_id))
        label = "Compatibles avec : " + label_name
        self.compat_filter_label.setText(label)
        self.compat_filter_row.setVisible(True)

    def _open_in_folders(self, folder: str) -> None:
        """Bascule vers l'onglet Dossiers et navigue vers le dossier du sample."""
        self.open_directory_in_folders(folder)

    def _clear_compat_filter(self) -> None:
        """Efface le filtre de gammes compatibles sur tous les onglets."""
        self.history_widget.set_compatible_scales_filter(None)
        self.indexed_widget.set_compatible_scales_filter(None)
        self.directory_widget.set_compatible_scales_filter(None)
        self.compat_filter_row.setVisible(False)

    # ------------------------------------------------------------------ styles

    def _apply_styles(self) -> None:
        """Applique la feuille de style QSS depuis les couleurs du theme courant."""
        p = theme.manager.p
        self.setStyleSheet(
            "QWidget#ReservePane {"
            "    background: " + p.BG_DARK + ";"
            "}"
            "QLabel#ReserveTitle {"
            "    color: " + p.TEXT + ";"
            "    font-size: 16px;"
            "    font-weight: 700;"
            "}"
            "QLabel#ReserveSubtitle {"
            "    color: " + p.TEXT_MUTED + ";"
            "    font-size: 11px;"
            "}"
            "QWidget#ReserveFiltersRow {"
            "    background: transparent;"
            "}"
            "QLineEdit#ReserveSearchInput,"
            "QComboBox#ReserveStatusFilter {"
            "    background: " + p.BG_MEDIUM + ";"
            "    color: " + p.TEXT + ";"
            "    border: 1px solid " + p.BORDER + ";"
            "    border-radius: 8px;"
            "    padding: 6px 8px;"
            "}"
            "QLineEdit#ReserveSearchInput:focus,"
            "QComboBox#ReserveStatusFilter:focus {"
            "    border-color: " + p.INFO + ";"
            "}"
            "QWidget#CompatFilterRow {"
            "    background: " + p.BG_MEDIUM + ";"
            "    border: 1px solid " + p.INFO + ";"
            "    border-radius: 8px;"
            "    padding: 4px 8px;"
            "}"
            "QLabel#CompatFilterLabel {"
            "    color: " + p.INFO + ";"
            "    font-size: 12px;"
            "}"
            "QTabWidget#ReserveTabs::pane {"
            "    border: none;"
            "    background: transparent;"
            "    padding-top: 8px;"
            "}"
            "QTabWidget#ReserveTabs QTabBar::tab {"
            "    background: transparent;"
            "    color: " + p.TEXT_MUTED + ";"
            "    border: 1px solid " + p.BORDER + ";"
            "    border-radius: 10px;"
            "    padding: 4px 10px;"
            "    margin-right: 6px;"
            "}"
            "QTabWidget#ReserveTabs QTabBar::tab:selected {"
            "    background: " + p.BG_HOVER + ";"
            "    border-color: " + p.BORDER_LIGHT + ";"
            "    color: " + p.TEXT + ";"
            "}"
            "QTabWidget#ReserveTabs QTabBar::tab:hover {"
            "    background: " + p.BG_MEDIUM + ";"
            "    border-color: " + p.BORDER_LIGHT + ";"
            "}"
        )
