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
from collections import Counter

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QTabWidget, QVBoxLayout, QWidget

from backend.models.AppContext import AppContext
from backend.services.directory_service import DirectoryService
from frontend.ui import IconButton
from frontend.reserve import (
    ReserveActions,
    ReserveFilterController,
    ReserveInspector,
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
        self.filter_controller = ReserveFilterController(self)
        self._build_ui()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda _: self._apply_styles())

    def closeEvent(self, event):  # noqa: N802
        controller = getattr(self.app_context, "reserve_preview", None)
        if controller is not None:
            controller.stop()
        super().closeEvent(event)

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

        self.scale_filter = QComboBox()
        self.scale_filter.setObjectName("ReserveScaleFilter")
        self.scale_filter.addItem("Toutes les gammes", "__all__")

        self.results_label = QLabel("")
        self.results_label.setObjectName("ReserveResultsLabel")

        self.filters_menu_btn = IconButton(
            "settings", tooltip="Filtres", size="m", parent=self.filters_row
        )
        self.filters_menu = QMenu(self.filters_menu_btn)
        self.filters_menu_btn.clicked.connect(
            lambda: self.filters_menu.exec(
                self.filters_menu_btn.mapToGlobal(self.filters_menu_btn.rect().bottomLeft())
            )
        )

        # Bouton analyse par lots (gamme) — libelle mis a jour dynamiquement selon l'onglet
        self.batch_analyze_btn = IconButton(
            "music",
            tooltip="Analyser les gammes du contexte courant",
            size="m",
        )
        self.batch_analyze_btn.setObjectName("BatchAnalyzeBtn")

        # Toggle : afficher/masquer le badge de gamme sur les cartes analysees.
        from frontend.reserve.reserve_prefs import prefs as _reserve_prefs
        self.show_key_toggle = IconButton(
            "eye" if _reserve_prefs.show_key_badge() else "eye-off",
            tooltip="Afficher la gamme detectee sur les cartes",
            size="m",
        )
        self.show_key_toggle.setObjectName("ShowKeyToggle")
        self.show_key_toggle.setCheckable(True)
        self.show_key_toggle.setChecked(_reserve_prefs.show_key_badge())
        self.show_key_toggle.toggled.connect(self._on_show_key_toggled)

        filters_layout.addWidget(self.search_input, 1)
        filters_layout.addWidget(self.status_filter, 0)
        filters_layout.addWidget(self.scale_filter, 0)
        filters_layout.addWidget(self.results_label, 0)
        filters_layout.addWidget(self.filters_menu_btn, 0)
        filters_layout.addWidget(self.batch_analyze_btn, 0)
        filters_layout.addWidget(self.show_key_toggle, 0)

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
            tooltip="Effacer tous les filtres",
            size="s",
        )
        self.compat_filter_clear_btn.setObjectName("CompatFilterClearBtn")

        compat_row_layout.addWidget(self.compat_filter_label)
        compat_row_layout.addWidget(self.compat_filter_clear_btn)
        compat_row_layout.addStretch()
        self.compat_filter_row.setVisible(False)
        self._rebuild_filters_menu()
        self.filters_menu.aboutToShow.connect(self._rebuild_filters_menu)

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
        self.mode_tabs.addTab(self.history_widget, "Récents")
        self.mode_tabs.addTab(self.indexed_widget, "Indexe")
        self.mode_tabs.setCurrentIndex(0)
        self.inspector = ReserveInspector(
            self.app_context,
            reserve_actions=self.reserve_actions,
            parent=self,
        )
        self.inspector.set_mode("compact")

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.filters_row)
        layout.addWidget(self.compat_filter_row)
        layout.addWidget(self.mode_tabs, 1)
        layout.addWidget(self.inspector, 0)

        self._apply_styles()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        compact = self.width() < 720
        self.status_filter.setVisible(not compact)
        self.scale_filter.setVisible(not compact)
        self.results_label.setVisible(not compact)
        self.filters_menu_btn.setVisible(compact)

    def _rebuild_filters_menu(self) -> None:
        self.filters_menu.clear()
        status_menu = self.filters_menu.addMenu("Statut")
        for index in range(self.status_filter.count()):
            action = status_menu.addAction(self.status_filter.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.status_filter.currentIndex())
            action.triggered.connect(
                lambda checked=False, i=index: self.status_filter.setCurrentIndex(i)
            )
        scale_menu = self.filters_menu.addMenu("Gamme")
        for index in range(self.scale_filter.count()):
            action = scale_menu.addAction(self.scale_filter.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.scale_filter.currentIndex())
            action.triggered.connect(
                lambda checked=False, i=index: self.scale_filter.setCurrentIndex(i)
            )
        self.filters_menu.addSeparator()
        self.filters_menu.addAction("Tout effacer").triggered.connect(self._clear_all_filters)

    def _bind_signals(self) -> None:
        """Connecte les signaux de tous les onglets, filtres et boutons."""
        self.reserve_actions.sendToLabRequested.connect(self.sendToLaboRequested.emit)
        self.reserve_actions.waveformRequested.connect(self._forward_waveform_request)
        self.directory_widget.sendToComposerRequested.connect(self.sendToLaboRequested.emit)
        self.search_input.textChanged.connect(self.filter_controller.set_query)
        self.status_filter.currentIndexChanged.connect(
            lambda *_args: self.filter_controller.set_status(
                self.status_filter.currentData() or STATUS_ALL
            )
        )
        self.scale_filter.currentIndexChanged.connect(
            lambda *_args: self.filter_controller.set_scale(
                self.scale_filter.currentData() or "__all__"
            )
        )
        self.filter_controller.queryChanged.connect(self._apply_query_filter)
        self.filter_controller.statusChanged.connect(self._apply_status_filter)
        self.filter_controller.scaleChanged.connect(self._apply_scale_filter)
        self.filter_controller.compatibilityChanged.connect(self._apply_compat_filter)
        self.filter_controller.scopeChanged.connect(self.indexed_widget.set_reserve_scope)
        self.filter_controller.stateChanged.connect(self._update_active_filter_summary)
        self.mode_tabs.currentChanged.connect(self._sync_inspector_from_current_view)
        self.mode_tabs.currentChanged.connect(lambda *_args: QTimer.singleShot(0, self._update_results_summary))
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            widget.reserveEntrySelected.connect(self.inspector.set_entry)
        self.inspector.entryMutated.connect(lambda *_args: self.refresh_current_view())
        self.inspector.analyzeRequested.connect(self._analyze_entry)
        # Mise a jour du libelle du bouton selon l'onglet/dossier actif
        self.mode_tabs.currentChanged.connect(lambda *_args: self._update_batch_btn_label())
        self.directory_widget.directoryChanged.connect(lambda *_args: self._update_batch_btn_label())
        # Analyse par lots
        self.batch_analyze_btn.clicked.connect(self._on_batch_analyze)
        # Filtre gamme compatible
        self.compat_filter_clear_btn.clicked.connect(self._clear_all_filters)
        self.history_widget.compatFilterChanged.connect(self._on_compat_filter_changed)
        self.directory_widget.compatFilterChanged.connect(self._on_compat_filter_changed)
        self.app_context.sample_store.sampleScaleAnalyzed.connect(
            lambda *_args: self._refresh_scale_options()
        )
        self.indexed_widget.reserveScaleFilterRequested.connect(self._select_scale_filter)
        self.indexed_widget.reserveScopeChanged.connect(self.filter_controller.set_scope)
        # Ouvrir l'emplacement depuis une carte de l'historique
        self.history_widget.openInFoldersRequested.connect(self._open_in_folders)
        self._refresh_scale_options()
        self._update_batch_btn_label()
        self._sync_inspector_from_current_view()

    def _sync_inspector_from_current_view(self, *_args) -> None:
        current = self.mode_tabs.currentWidget()
        getter = getattr(current, "current_reserve_entry", None)
        entry = getter() if callable(getter) else None
        if entry is None:
            self.inspector.clear_entry()
        else:
            self.inspector.set_entry(entry)

    def _analyze_entry(self, entry) -> None:
        if entry is None or entry.sample_id is None or entry.missing:
            return
        analyzer = getattr(self.app_context.sample_store, "_scale_analysis", None)
        enqueue = getattr(analyzer, "enqueue", None)
        if callable(enqueue):
            enqueue(int(entry.sample_id), entry.path)

    def _forward_waveform_request(self, entry) -> None:
        """Retransmet une demande d'ouverture de waveform comme sendToLaboRequested."""
        path = getattr(entry, "path", "") or ""
        if path:
            self.sendToLaboRequested.emit([path])

    def _apply_shared_filters(self) -> None:
        """Adaptateur historique : applique immediatement l'etat des controles."""
        self.filter_controller.set_query(self.search_input.text())
        self.filter_controller.flush_query()
        self.filter_controller.set_status(self.status_filter.currentData() or STATUS_ALL)
        self.filter_controller.set_scale(self.scale_filter.currentData() or "__all__")

    def _apply_query_filter(self, query: str) -> None:
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            if hasattr(widget, "set_reserve_query"):
                widget.set_reserve_query(query)

    def _apply_status_filter(self, status_filter: str) -> None:
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            if hasattr(widget, "set_reserve_status_filter"):
                widget.set_reserve_status_filter(status_filter)

    def _apply_scale_filter(self, scale: str) -> None:
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            setter = getattr(widget, "set_reserve_scale_filter", None)
            if callable(setter):
                setter(scale)

    def _select_scale_filter(self, scale: str) -> None:
        index = self.scale_filter.findData(scale)
        if index >= 0:
            self.scale_filter.setCurrentIndex(index)
        else:
            self.filter_controller.set_scale(scale)

    def _apply_compat_filter(self, sample_id) -> None:
        for widget in (self.directory_widget, self.history_widget, self.indexed_widget):
            widget.set_compatible_scales_filter(sample_id)

    def _refresh_scale_options(self) -> None:
        raw_labels = [
            str(getattr(sample, "detected_scale_label", "") or "").strip()
            for sample in self.app_context.sample_store.get_cached()
        ]
        counts = Counter(label for label in raw_labels if label)
        without_scale = sum(1 for label in raw_labels if not label)
        current = self.filter_controller.state.scale
        self.scale_filter.blockSignals(True)
        self.scale_filter.clear()
        self.scale_filter.addItem("Toutes les gammes", "__all__")
        self.scale_filter.addItem(f"Sans gamme ({without_scale})", "__none__")
        for label in sorted(counts):
            self.scale_filter.addItem(f"{label} ({counts[label]})", label)
        index = self.scale_filter.findData(current)
        self.scale_filter.setCurrentIndex(max(0, index))
        self.scale_filter.blockSignals(False)
        self._rebuild_filters_menu()

    def _update_active_filter_summary(self, state) -> None:
        parts = []
        if state.query:
            parts.append(f'“{state.query}”')
        if state.technical_status != STATUS_ALL:
            parts.append(self.status_filter.currentText())
        if state.scale != "__all__":
            parts.append(self.scale_filter.currentText())
        if state.compatibility_sample_id is not None:
            ref = next((s for s in self.app_context.sample_store.get_cached() if s.id == state.compatibility_sample_id), None)
            label = getattr(ref, "detected_scale_label", None) or getattr(ref, "dominant_note", None) or f"#{state.compatibility_sample_id}"
            parts.append("Compatible avec " + str(label))
        if state.scope_kind != "all":
            scope_label = "Externes" if state.scope_kind == "external" else (state.scope_value or state.scope_kind)
            parts.append("Scope : " + os.path.basename(str(scope_label)))
        self.compat_filter_label.setText("  ·  ".join(parts))
        self.compat_filter_row.setVisible(bool(parts))
        QTimer.singleShot(0, self._update_results_summary)

    def _update_results_summary(self) -> None:
        current = self.mode_tabs.currentWidget()
        if current is self.directory_widget:
            visible = len(getattr(current, "_rows_by_path", {}))
            total = visible
        elif current is self.history_widget:
            visible = len(current.get_filtered_samples())
            total = len(current.samples)
        else:
            visible = len(current.filtered_entries)
            total = len(current.samples)
        active = self.filter_controller.state != type(self.filter_controller.state)()
        if active and visible == 0:
            self.results_label.setText("Aucun résultat")
        elif active:
            self.results_label.setText(f"{visible} / {total}")
        else:
            self.results_label.setText(f"{total}")

    def _clear_all_filters(self) -> None:
        for control in (self.search_input, self.status_filter, self.scale_filter):
            control.blockSignals(True)
        self.search_input.clear()
        self.status_filter.setCurrentIndex(0)
        self.scale_filter.setCurrentIndex(0)
        for control in (self.search_input, self.status_filter, self.scale_filter):
            control.blockSignals(False)
        self.filter_controller.clear_all()

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
                "Analyser la gamme des éléments actuellement affichés.\n"
                "Pour une sélection cochée : menu ⋮ de la vue Récents."
            )

    def _on_batch_analyze(self) -> None:
        """Lance l'analyse de gamme — dossier courant si onglet Dossiers, sinon toute la DB."""
        folder = self._current_folder_for_analysis()
        if folder:
            count = self.app_context.sample_store.batch_analyze_folder(folder)
        else:
            current = self.mode_tabs.currentWidget()
            if current is self.history_widget:
                sample_ids = list(self.history_widget._card_widgets)
            elif current is self.indexed_widget:
                sample_ids = [
                    entry.sample_id for entry in self.indexed_widget.filtered_entries
                    if entry.sample_id is not None
                ]
            else:
                sample_ids = []
            count = self.app_context.sample_store.batch_analyze_ids(sample_ids)
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
        self.filter_controller.set_compatibility(sample_id or None)

    def _open_in_folders(self, folder: str) -> None:
        """Bascule vers l'onglet Dossiers et navigue vers le dossier du sample."""
        self.open_directory_in_folders(folder)

    def _clear_compat_filter(self) -> None:
        """Efface le filtre de gammes compatibles sur tous les onglets."""
        self.filter_controller.set_compatibility(None)

    def _on_show_key_toggled(self, checked: bool) -> None:
        """Toggle global : afficher/masquer le badge de gamme sur les cartes."""
        from frontend.reserve.reserve_prefs import prefs as _reserve_prefs

        _reserve_prefs.set_show_key_badge(bool(checked))
        self.show_key_toggle.set_icon_name("eye" if checked else "eye-off")

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
            "QLabel#ReserveResultsLabel { color: " + p.TEXT_MUTED + "; font-size: 11px; }"
            "QWidget#ReserveFiltersRow {"
            "    background: transparent;"
            "}"
            "QWidget#ReserveFiltersRow QWidget { background: transparent; }"
            "QWidget#ReservePane QToolButton::menu-indicator {"
            "    image: none; width: 0px; height: 0px;"
            "}"
            "QLineEdit#ReserveSearchInput,"
            "QComboBox#ReserveStatusFilter,"
            "QComboBox#ReserveScaleFilter {"
            "    background: " + p.BG_MEDIUM + ";"
            "    color: " + p.TEXT + ";"
            "    border: 1px solid " + p.BORDER + ";"
            "    border-radius: 8px;"
            "    padding: 6px 8px;"
            "}"
            "QLineEdit#ReserveSearchInput:focus,"
            "QComboBox#ReserveStatusFilter:focus,"
            "QComboBox#ReserveScaleFilter:focus {"
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
