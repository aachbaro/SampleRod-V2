# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget principal de l'onglet "Bibliotheque" (et aussi utilise comme sous-
#   vue dans la Reserve quand embedded_in_reserve=True).
# - Affiche un arbre de navigation (racines / dossiers) a gauche, un tableau
#   de samples au centre, et un panneau de detail a droite.
# - Supporte le glisser-deposer : un sample peut etre glisse vers le Labo ou
#   un autre widget.
#
# FONCTIONS (sommaire)
# - LibraryWidget              : widget principal (arbre + tableau + detail)
# - _configure_table()         : configure les colonnes et les modes de resize
# - _bind_signals()            : connecte store, settings, recherche, selection
# - _refresh_navigation()      : reconstruit l'arbre a partir du LibraryService
# - _refresh_table()           : filtre et peuple le tableau selon le scope actuel
# - _sync_detail_with_selection() : met a jour le panneau de detail
# - set_compatible_scales_filter() : active le filtre de gammes compatibles
# - open_waveform_for_entry()  : selectionne une ligne et ouvre la waveform
# - eventFilter()              : detecte le debut d'un drag depuis le tableau
# - _start_drag_from_selection() : lance un QDrag avec les donnees MIME du sample
#
# LIENS CLES
# - backend/services/library_service.py      : calcul de la navigation et du filtrage
# - frontend/library_gui/library_detail.py   : panneau de detail (detail_widget)
# - frontend/library_gui/library_ui.py       : construction de l'interface
# - frontend/reserve/reserve_entry.py        : type ReserveEntry
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import pickle

from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidgetItem, QTreeWidgetItem, QWidget

from backend.services.library_service import LibraryNavNode, LibraryScope, LibraryService
from frontend.reserve import (
    ReserveActions,
    ReserveEntry,
    reserve_entry_from_sample,
    reserve_entry_matches_query,
    reserve_entry_matches_status,
    reserve_status_label,
    reserve_status_tone,
)
from frontend.styles import theme

from . import library_ui
from .library_detail import LibraryDetailWidget


class LibraryWidget(QWidget):
    """Vue bibliotheque pour naviguer dans les samples indexes.

    Peut fonctionner en mode autonome (onglet Bibliotheque de la fenetre
    principale) ou en mode integre dans la Reserve (embedded_in_reserve=True),
    auquel cas la barre de recherche et le filtre sont masques (la Reserve
    les gere elle-meme a travers set_reserve_query / set_reserve_status_filter).

    Signal :
        reserveEntrySelected(ReserveEntry | None) : emis quand la selection change.
    """

    TREE_SCOPE_KIND_ROLE = Qt.ItemDataRole.UserRole
    TREE_SCOPE_VALUE_ROLE = Qt.ItemDataRole.UserRole + 1
    TABLE_SAMPLE_ID_ROLE = Qt.ItemDataRole.UserRole

    reserveEntrySelected = Signal(object)

    def __init__(
        self,
        app_context,
        parent=None,
        reserve_actions: ReserveActions | None = None,
        embedded_in_reserve: bool = False,
    ):
        super().__init__(parent)
        self.app_context = app_context
        self.sample_store = self.app_context.sample_store
        self.settings = self.app_context.settings
        self.library_service = LibraryService(self.settings, self.sample_store)
        self.reserve_actions = reserve_actions
        self.embedded_in_reserve = embedded_in_reserve
        self.samples = self.library_service.get_cached_samples()
        self.filtered_entries: list[ReserveEntry] = []
        self.current_scope = LibraryScope("all")
        self._selected_sample_id: int | None = None
        self._reserve_query_text = ""
        self._reserve_status_filter = "all"
        self._compat_filter_scales: set[str] = set()
        self._entries_by_sample_id: dict[int, ReserveEntry] = {}
        self._drag_start_pos = None

        self.detail_widget = LibraryDetailWidget(
            self.app_context,
            reserve_actions=self.reserve_actions,
        )
        library_ui.build_library_widget_ui(self)
        self._configure_table()
        self._bind_signals()
        self._refresh_navigation()
        self._refresh_table()
        theme.manager.themeChanged.connect(self._on_theme_changed)

        if self.embedded_in_reserve:
            self.search_input.hide()
            self.status_filter.hide()
            self.title_label.setText("Indexe")

    def _configure_table(self):
        """Configure les modes de redimensionnement des colonnes et installe le filtre d'evenements."""
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnHidden(2, False)
        self.table.viewport().installEventFilter(self)

    def _bind_signals(self):
        """Connecte le store, les settings, la recherche et la selection."""
        self.sample_store.samplesChanged.connect(self.on_samples_changed)
        self.sample_store.sampleDurationChanged.connect(lambda *_args: self._reload_from_store())
        self.settings.librariesChanged.connect(lambda *_args: self._reload_from_store())
        # Refresh de la table quand une analyse de gamme se termine
        self.sample_store.sampleScaleAnalyzed.connect(self._on_sample_scale_analyzed)
        self.search_input.textChanged.connect(lambda *_args: self._refresh_table())
        self.status_filter.currentIndexChanged.connect(lambda *_args: self._refresh_table())
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_args: self.detail_widget.toggle_waveform())

    def _on_theme_changed(self, _name: str):
        library_ui.apply_styles(self)
        self._refresh_table()

    def on_samples_changed(self, samples: list):
        """Slot : reçoit la nouvelle liste de samples depuis le store et rafraichit la vue."""
        self.samples = list(samples)
        self._refresh_navigation()
        self._refresh_table()

    def _reload_from_store(self):
        """Recharge les samples depuis le cache du store (sans attendre le signal samplesChanged)."""
        self.samples = self.library_service.get_cached_samples()
        self._refresh_navigation()
        self._refresh_table()

    def set_reserve_query(self, query: str) -> None:
        """Fixe le texte de recherche quand la Reserve pilote ce widget en mode integre."""
        query = (query or "").strip()
        if query == self._reserve_query_text:
            return
        self._reserve_query_text = query
        if self.embedded_in_reserve:
            self._refresh_table()

    def set_reserve_status_filter(self, status_filter: str) -> None:
        """Fixe le filtre de statut quand la Reserve pilote ce widget en mode integre."""
        status_filter = status_filter or "all"
        if status_filter == self._reserve_status_filter:
            return
        self._reserve_status_filter = status_filter
        if self.embedded_in_reserve:
            self._refresh_table()

    def set_compatible_scales_filter(self, sample_id: int | None) -> None:
        """Active ou efface le filtre de gammes compatibles."""
        if sample_id is None:
            if not self._compat_filter_scales:
                return
            self._compat_filter_scales = set()
        else:
            ref = next((s for s in self.samples if s.id == sample_id), None)
            if ref is None:
                return
            raw = getattr(ref, "compatible_scales", None) or ""
            try:
                scales = set(json.loads(raw)) if raw else set()
            except (ValueError, TypeError):
                scales = set()
            if self._compat_filter_scales == scales:
                return
            self._compat_filter_scales = scales
        self._refresh_table()

    def _on_sample_scale_analyzed(self, sample_id: int) -> None:
        """Actualise les donnees du sample dans le cache local puis refresh la table."""
        updated = next(
            (s for s in self.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        if updated is not None:
            for i, s in enumerate(self.samples):
                if s.id == sample_id:
                    self.samples[i] = updated
                    break
        self._refresh_table()

    def current_reserve_entry(self) -> ReserveEntry | None:
        if self._selected_sample_id is None:
            return None
        return self._entries_by_sample_id.get(int(self._selected_sample_id))

    def open_waveform_for_entry(self, entry: ReserveEntry | None) -> bool:
        """Selectionne la ligne correspondante dans le tableau et ouvre la waveform.

        Retourne True si la ligne a ete trouvee et la waveform ouverte.
        """
        if entry is None or entry.source_kind != "indexed" or entry.sample_id is None:
            return False
        row = self._find_row_for_sample(int(entry.sample_id))
        if row is None:
            return False
        self.table.selectRow(row)
        self.detail_widget.toggle_waveform()
        return True

    def _refresh_navigation(self):
        """Reconstruit l'arbre de navigation (racines/dossiers) depuis le LibraryService.

        Tente de conserver la selection courante (meme scope) apres le rebuild.
        """
        current_scope = (self.current_scope.kind, self.current_scope.value)
        self.tree.blockSignals(True)
        self.tree.clear()
        nodes = self.library_service.build_navigation(self.samples)
        selected_item = None
        for node in nodes:
            item = self._build_tree_item(node)
            self.tree.addTopLevelItem(item)
            self._expand_top_level_if_needed(item)
            if (
                item.data(0, self.TREE_SCOPE_KIND_ROLE),
                item.data(0, self.TREE_SCOPE_VALUE_ROLE),
            ) == current_scope:
                selected_item = item
            if selected_item is None:
                selected_item = self._find_matching_tree_item(item, current_scope)

        if selected_item is None and self.tree.topLevelItemCount() > 0:
            selected_item = self.tree.topLevelItem(0)

        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
            self.current_scope = LibraryScope(
                str(selected_item.data(0, self.TREE_SCOPE_KIND_ROLE)),
                selected_item.data(0, self.TREE_SCOPE_VALUE_ROLE),
            )
        self.tree.blockSignals(False)

    def _build_tree_item(self, node: LibraryNavNode) -> QTreeWidgetItem:
        """Cree recursivement un item d'arbre a partir d'un LibraryNavNode."""
        missing_suffix = f" - {node.missing_count} manquants" if node.missing_count else ""
        item = QTreeWidgetItem([f"{node.label} ({node.sample_count}){missing_suffix}"])
        item.setData(0, self.TREE_SCOPE_KIND_ROLE, node.scope.kind)
        item.setData(0, self.TREE_SCOPE_VALUE_ROLE, node.scope.value)
        for child in node.children:
            item.addChild(self._build_tree_item(child))
        return item

    def _expand_top_level_if_needed(self, item: QTreeWidgetItem):
        if item.parent() is None:
            item.setExpanded(True)

    def _find_matching_tree_item(self, root: QTreeWidgetItem, scope_key: tuple[str, str | None]):
        if (
            root.data(0, self.TREE_SCOPE_KIND_ROLE),
            root.data(0, self.TREE_SCOPE_VALUE_ROLE),
        ) == scope_key:
            return root
        for index in range(root.childCount()):
            found = self._find_matching_tree_item(root.child(index), scope_key)
            if found is not None:
                return found
        return None

    def _on_tree_selection_changed(self):
        item = self.tree.currentItem()
        if item is None:
            return
        self.current_scope = LibraryScope(
            str(item.data(0, self.TREE_SCOPE_KIND_ROLE)),
            item.data(0, self.TREE_SCOPE_VALUE_ROLE),
        )
        self._refresh_table()

    def _refresh_table(self):
        """Filtre les samples selon le scope, la recherche et le statut, puis peuple le tableau.

        Les samples sont d'abord filtres par scope (racine/dossier/all) via le
        LibraryService, puis par texte de recherche, filtre de statut, et filtre
        de gammes compatibles. Les cellules sont colorees en fonction du statut.
        La selection precedente est restauree si le sample est toujours visible.
        """
        self._entries_by_sample_id.clear()
        query = self._reserve_query_text if self.embedded_in_reserve else self.search_input.text()
        status_filter = (
            self._reserve_status_filter if self.embedded_in_reserve else (self.status_filter.currentData() or "all")
        )

        scoped_samples = self.library_service.filter_samples(
            self.samples,
            scope=self.current_scope,
            search_text="",
            status_filter=LibraryService.STATUS_ALL,
        )
        self.filtered_entries = []
        for sample in scoped_samples:
            entry = self._entry_from_sample(sample)
            if not reserve_entry_matches_query(entry, query):
                continue
            if not reserve_entry_matches_status(entry, status_filter):
                continue
            if self._compat_filter_scales:
                raw = getattr(sample, "compatible_scales", None) or ""
                try:
                    samp_scales = set(json.loads(raw)) if raw else set()
                except (ValueError, TypeError):
                    samp_scales = set()
                if not (samp_scales & self._compat_filter_scales):
                    continue
            self.filtered_entries.append(entry)
            if entry.sample_id is not None:
                self._entries_by_sample_id[int(entry.sample_id)] = entry

        self.count_label.setText(
            f"{len(self.filtered_entries)} sample{'s' if len(self.filtered_entries) != 1 else ''}"
        )

        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered_entries))

        selected_sample_id = self._selected_sample_id
        for row, entry in enumerate(self.filtered_entries):
            name_item = QTableWidgetItem(entry.display_name)
            name_item.setData(self.TABLE_SAMPLE_ID_ROLE, int(entry.sample_id or -1))
            folder_item = QTableWidgetItem(entry.folder_name)
            root_item = QTableWidgetItem(entry.root_name)
            duration_item = QTableWidgetItem(self._format_duration(entry))
            duration_item.setData(Qt.ItemDataRole.EditRole, float(entry.duration or 0.0))
            rms_item = QTableWidgetItem(self._format_rms(entry))
            rms_item.setData(Qt.ItemDataRole.EditRole, -1.0 if entry.rms_level is None else float(entry.rms_level))
            status_item = QTableWidgetItem(reserve_status_label(entry.status))

            for item in (name_item, folder_item, root_item, duration_item, rms_item, status_item):
                item.setToolTip(entry.path)

            tone = reserve_status_tone(entry.status)
            if tone == "error":
                color = QColor(theme.manager.p.ERROR)
            elif tone == "warning":
                color = QColor(theme.manager.p.WARNING)
            elif tone == "info":
                color = QColor(theme.manager.p.INFO)
            else:
                color = QColor(theme.manager.p.TEXT)
            for item in (name_item, folder_item, root_item, duration_item, rms_item, status_item):
                item.setForeground(color)

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, folder_item)
            self.table.setItem(row, 2, root_item)
            self.table.setItem(row, 3, duration_item)
            self.table.setItem(row, 4, rms_item)
            self.table.setItem(row, 5, status_item)

        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)

        selected_row = self._find_row_for_sample(selected_sample_id)
        if selected_row is None and self.filtered_entries:
            first_entry = self.filtered_entries[0]
            selected_row = self._find_row_for_sample(first_entry.sample_id)
            self._selected_sample_id = first_entry.sample_id

        if selected_row is not None:
            self.table.selectRow(selected_row)
            self._sync_detail_with_selection()
        else:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)

    def _entry_from_sample(self, sample) -> ReserveEntry:
        path = getattr(sample, "path", "") or ""
        return reserve_entry_from_sample(
            sample,
            source_kind="indexed",
            root_path=self.library_service.get_root_path(sample),
            folder_path=self.library_service.get_parent_folder_path(sample),
        )

    def _format_duration(self, entry: ReserveEntry) -> str:
        return f"{float(entry.duration or 0.0):.1f}s"

    def _format_rms(self, entry: ReserveEntry) -> str:
        if entry.rms_level is None:
            return "-"
        return f"{float(entry.rms_level):.3f}"

    def _on_table_selection_changed(self):
        self._sync_detail_with_selection()

    def _sync_detail_with_selection(self):
        """Lit la ligne selectionnee et met a jour le panneau de detail et le signal."""
        row = self.table.currentRow()
        if row < 0:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
            return
        id_item = self.table.item(row, 0)
        if id_item is None:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
            return
        sample_id = int(id_item.data(self.TABLE_SAMPLE_ID_ROLE) or -1)
        sample = next((item for item in self.samples if int(item.id) == sample_id), None)
        entry = self._entries_by_sample_id.get(sample_id)
        if sample is None or entry is None:
            self._selected_sample_id = None
            self.detail_widget.clear_sample()
            self.reserveEntrySelected.emit(None)
            return
        self._selected_sample_id = int(sample.id)
        self.detail_widget.set_sample(sample, entry, self.library_service)
        self.reserveEntrySelected.emit(entry)

    def _find_row_for_sample(self, sample_id: int | None) -> int | None:
        """Retourne l'indice de ligne du sample dans le tableau, ou None s'il est absent."""
        if sample_id is None:
            return None
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            if int(item.data(self.TABLE_SAMPLE_ID_ROLE) or -1) == int(sample_id):
                return row
        return None

    def eventFilter(self, watched, event):
        """Detecte le debut d'un drag depuis le viewport du tableau.

        Quand la souris se deplace au-dela du seuil startDragDistance avec le
        bouton gauche enfonce, lance _start_drag_from_selection().
        """
        if watched is self.table.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = event.position().toPoint()
            elif (
                event.type() == QEvent.Type.MouseMove
                and event.buttons() & Qt.MouseButton.LeftButton
                and self._drag_start_pos is not None
            ):
                if (
                    event.position().toPoint() - self._drag_start_pos
                ).manhattanLength() >= QApplication.startDragDistance():
                    self._drag_start_pos = None
                    self._start_drag_from_selection()
                    return True
        return super().eventFilter(watched, event)

    def _start_drag_from_selection(self) -> None:
        """Lance un QDrag depuis le sample selectionne.

        Inclut deux types de donnees MIME :
        - URL locale du fichier (pour l'import dans un widget standard).
        - 'application/x-sample-card' avec l'ID du sample (pour l'import dans
          les widgets internes qui savent resoudre l'ID en chemin).
        """
        entry = self.current_reserve_entry()
        if entry is None or not getattr(entry, "path", ""):
            return

        drag = QDrag(self.table)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(entry.path)])
        if entry.sample_id is not None:
            mime.setData(
                "application/x-sample-card",
                pickle.dumps({"sample_id": int(entry.sample_id)}),
            )
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
