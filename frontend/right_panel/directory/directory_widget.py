# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Facade du navigateur de fichiers audio "disque d'abord".
# - Garde l'orchestration generale et les signaux Qt, tout en deleguant
#   navigation, selection/detail, reconstruction de liste, filtres Reserve
#   et etat d'indexation a des companions specialises.
#
# LIENS CLES
# - directory_navigation.py  : navigation filesystem + arbre.
# - directory_selection.py   : selection, detail et preview partagee.
# - directory_list_builder.py : liste fichiers/dossiers + animations.
# - directory_filter.py       : recherche, statuts, compatibilites.
# - directory_index.py        : index DB, ReserveEntry, renommage.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

from PySide6.QtCore import (
    QDir,
    QSettings,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileSystemModel,
    QListWidgetItem,
    QSizePolicy,
    QWidget,
)

from backend.models.AppContext import AppContext
from backend.services.audio_metadata import normalize_audio_path
from backend.services.directory_service import DirectoryService
from frontend.reserve import (
    ReserveActions,
    ReserveEntry,
    apply_status_badge,
)
from frontend.styles import theme

from . import directory_ui
from .directory_detail import DirectoryDetailWidget
from .directory_filter import DirectoryFilterController
from .directory_history import DirectoryHistory
from .directory_index import DirectoryIndexController
from .directory_item_widget import DirectoryListItemWidget, DirectorySubfolderRowWidget
from .directory_list_builder import DirectoryListBuilder
from .directory_navigation import DirectoryNavigationController
from .directory_selection import DirectorySelectionController
from .directory_store_sync import DirectoryStoreSync

logger = logging.getLogger("directory_widget")


class DirectoryWidget(QWidget):
    """Navigateur de fichiers audio "disque d'abord", enrichi par la DB locale."""

    directoryChanged = Signal(str)
    rootDirectoryChanged = Signal(str)
    sendToComposerRequested = Signal(list)
    reserveEntrySelected = Signal(object)
    compatFilterChanged = Signal(int)

    def __init__(
        self,
        service: DirectoryService,
        app_context: AppContext,
        parent=None,
        path: str | None = None,
        reserve_actions: ReserveActions | None = None,
        embedded_in_reserve: bool = False,
    ):
        super().__init__(parent)
        logger.info("[DirectoryWidget] Initialisation (start)")

        self.service = service
        self.app_context = app_context
        self.reserve_actions = reserve_actions or ReserveActions(self.app_context)
        self.embedded_in_reserve = bool(embedded_in_reserve)
        self._items_by_id: dict[int, tuple[QListWidgetItem, DirectoryListItemWidget]] = {}
        self._rows_by_path: dict[str, tuple[QListWidgetItem, DirectoryListItemWidget]] = {}
        self._folder_rows_by_path: dict[str, tuple[QListWidgetItem, DirectorySubfolderRowWidget]] = {}
        self._selected_path: str | None = None
        self._selected_folder_path: str | None = None
        self._reserve_query_text = ""
        self._reserve_status_filter = "all"
        self._compat_filter_sample_id: int | None = None
        self._compat_filter_scales: set[str] = set()
        self._qs = QSettings("SampleRod", "Main")
        self._index_status_refresh_timer = QTimer(self)
        self._index_status_refresh_timer.setSingleShot(True)
        self._index_status_refresh_timer.setInterval(180)
        self.history = DirectoryHistory(self._qs)
        explicit_path = normalize_audio_path(path) if path else ""
        restored_root = explicit_path or self.history.get_last_root_directory()
        restored_current = explicit_path or self.history.get_last_directory()
        self.root_dir = restored_root if restored_root and os.path.isdir(restored_root) else ""
        self.current_dir = restored_current if restored_current and os.path.isdir(restored_current) else ""
        if not self.current_dir:
            self.current_dir = self.root_dir

        self.detail_widget = DirectoryDetailWidget(
            self.app_context,
            reserve_actions=self.reserve_actions,
            parent=self,
        )

        self.list_builder = DirectoryListBuilder(self)
        self.filters = DirectoryFilterController(self)
        self.index = DirectoryIndexController(self)
        self.navigation = DirectoryNavigationController(self)
        self.selection = DirectorySelectionController(self)
        self._index_status_refresh_timer.timeout.connect(self._refresh_index_status)

        self._build_ui()
        self._init_tree_model()
        self._bind_directory_service()
        self._bind_browser_ui()

        self.store_sync = DirectoryStoreSync(self, self.app_context.sample_store)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(280)

        initial_dir = self.current_dir or self.root_dir
        if initial_dir:
            if not self.root_dir:
                self.root_dir = initial_dir
            self._update_tree_root(initial_dir)
            self.rootDirectoryChanged.emit(self.root_dir)
            self.open_directory(initial_dir)

        logger.info("[DirectoryWidget] Initialisation (ready)")

    def _build_ui(self):
        directory_ui.build_directory_widget_ui(self)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.detail_widget.hide()
        self.compat_filter_row.setVisible(False)
        theme.manager.themeChanged.connect(self._on_theme_changed)

    def _init_tree_model(self):
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)
        self.tree_view.setModel(self.fs_model)
        for column in range(1, self.fs_model.columnCount()):
            self.tree_view.hideColumn(column)
        self.tree_view.setAnimated(True)
        self.tree_view.setIndentation(14)

    def _bind_directory_service(self):
        self.service.indexStarted.connect(self._on_index_started)
        self.service.indexProgress.connect(self._on_index_progress)
        self.service.indexFinished.connect(self._on_index_finished)
        self.service.indexFailed.connect(self._on_index_failed)

    def _bind_browser_ui(self):
        self.list_widget.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.tree_view.selectionModel().currentChanged.connect(self._on_tree_current_changed)
        self.tree_view.expanded.connect(self._on_tree_expanded)
        self.tree_view.collapsed.connect(self._on_tree_collapsed)
        self.reserve_actions.previewChanged.connect(self._on_common_preview_changed)

    def _on_theme_changed(self, _name: str):
        directory_ui.apply_styles(self)
        for _, widget in self._rows_by_path.values():
            directory_ui.restyle_item(widget)
            apply_status_badge(widget.status_badge, widget.entry.status)
        for _, widget in self._folder_rows_by_path.values():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        if self._selected_path and self._selected_path in self._rows_by_path:
            self._refresh_detail_for_path(self._selected_path)

    def choose_root_directory(self):
        self.navigation.choose_root_directory()

    def set_root_directory(self, path: str) -> None:
        self.navigation.set_root_directory(path)

    def open_directory(self, path: str) -> None:
        self.navigation.open_directory(path)

    def go_to_parent_directory(self) -> None:
        self.navigation.go_to_parent_directory()

    def index_current_directory(self):
        if not self.current_dir:
            return
        if not self.service.start_index_directory(self.current_dir):
            if self.service.is_indexing():
                self.progress_label.setText("Une indexation est deja en cours...")
                self.progress_label.setVisible(True)
            else:
                self._set_status("Non indexe", "Impossible de lancer l'indexation.")

    def toggle_preview(self, item_widget: DirectoryListItemWidget) -> None:
        self.reserve_actions.preview(item_widget.entry)

    def toggle_preview_for_path(self, path: str) -> None:
        item = self._rows_by_path.get(normalize_audio_path(path))
        if item is None:
            return
        self.toggle_preview(item[1])

    def seek_preview(self, entry: ReserveEntry, position_ms: int) -> bool:
        return self.reserve_actions.seek_preview(entry, position_ms)

    def start_rename_for_path(self, path: str) -> None:
        self.selection.start_rename_for_path(path)

    def send_selected_to_composer(self) -> None:
        if self._selected_path:
            self.send_path_to_composer(self._selected_path)

    def send_path_to_composer(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        if os.path.isfile(normalized):
            self.sendToComposerRequested.emit([normalized])

    def set_reserve_query(self, query: str) -> None:
        self.filters.set_reserve_query(query)

    def set_reserve_status_filter(self, status_filter: str) -> None:
        self.filters.set_reserve_status_filter(status_filter)

    def set_compatible_scales_filter(self, sample_id: int | None) -> None:
        self.filters.set_compatible_scales_filter(sample_id)

    def clear_compatible_scales_filter(self) -> None:
        self.filters.clear_compatible_scales_filter()

    def on_find_compatibles_requested(self, sample_id: int) -> None:
        self.filters.on_find_compatibles_requested(sample_id)

    def current_reserve_entry(self) -> ReserveEntry | None:
        return self.selection.current_reserve_entry()

    def open_waveform_for_entry(self, entry: ReserveEntry | None) -> bool:
        return self.selection.open_waveform_for_entry(entry)

    def rename_entry(self, entry: ReserveEntry, new_name: str) -> tuple[bool, str | None]:
        return self.reserve_actions.rename(entry, new_name)

    def refresh_list(self):
        self.list_builder.refresh_list()

    def remove_paths_from_current_view(self, paths: list[str]) -> None:
        self.list_builder.remove_paths_from_current_view(paths)

    def schedule_index_status_refresh(self, delay_ms: int = 180) -> None:
        self.index.schedule_index_status_refresh(delay_ms)

    def _refresh_index_status(self):
        self.index._refresh_index_status()

    def _set_status(self, label: str, detail: str | None = None):
        self.index._set_status(label, detail)

    def _set_index_busy(self, busy: bool):
        self.index._set_index_busy(busy)

    def _on_index_started(self, folder: str):
        self.index._on_index_started(folder)

    def _on_index_progress(self, folder: str, current: int, total: int, message: str):
        self.index._on_index_progress(folder, current, total, message)

    def _on_index_finished(self, folder: str, summary: object):
        self.index._on_index_finished(folder, summary)

    def _on_index_failed(self, folder: str, message: str):
        self.index._on_index_failed(folder, message)

    def _add_subfolder_row(self, subdir_path: str) -> None:
        self.list_builder._add_subfolder_row(subdir_path)

    def _add_row_direct(self, entry: ReserveEntry) -> None:
        self.list_builder._add_row_direct(entry)

    def _add_row(self, entry_or_path, sample_id: int | None = None) -> None:
        self.list_builder._add_row(entry_or_path, sample_id)

    def _update_row(self, sample_id: int, new_path: str) -> None:
        self.list_builder._update_row(sample_id, new_path)

    def _remove_row(self, sample_id: int) -> None:
        self.list_builder._remove_row(sample_id)

    def _remove_widget(self, widget: DirectoryListItemWidget) -> None:
        self.list_builder._remove_widget(widget)

    def _sync_after_widget_removal(self) -> None:
        self.list_builder._sync_after_widget_removal()

    def _on_tree_current_changed(self, current, _previous):
        self.navigation._on_tree_current_changed(current, _previous)

    def _on_tree_expanded(self, index) -> None:
        self.navigation._on_tree_expanded(index)

    def _on_tree_collapsed(self, index) -> None:
        self.navigation._on_tree_collapsed(index)

    def _on_row_clicked(self, widget: DirectoryListItemWidget) -> None:
        self.selection._on_row_clicked(widget)

    def _on_subfolder_clicked(self, folder_path: str) -> None:
        self.selection._on_subfolder_clicked(folder_path)

    def _on_list_selection_changed(self) -> None:
        self.selection._on_list_selection_changed()

    def _set_selected_row_widget(
        self,
        widget: DirectoryListItemWidget | None,
        *,
        list_item: QListWidgetItem | None = None,
    ) -> None:
        self.selection._set_selected_row_widget(widget, list_item=list_item)

    def _set_selected_folder_widget(
        self,
        widget: DirectorySubfolderRowWidget | None,
        *,
        list_item: QListWidgetItem | None = None,
    ) -> None:
        self.selection._set_selected_folder_widget(widget, list_item=list_item)

    def _refresh_detail_for_path(self, path: str | None) -> None:
        self.selection._refresh_detail_for_path(path)

    def _sync_detail_preview_state(self) -> None:
        self.selection._sync_detail_preview_state()

    def _select_path(self, path: str | None) -> None:
        self.selection._select_path(path)

    def _select_folder_path(self, path: str | None) -> None:
        self.selection._select_folder_path(path)

    def _sync_tree_selection(self, path: str) -> None:
        self.navigation._sync_tree_selection(path)

    def _update_up_button_state(self) -> None:
        self.navigation._update_up_button_state()

    def _update_tree_root(self, path: str) -> None:
        self.navigation._update_tree_root(path)

    @staticmethod
    def _tree_root_for(path: str) -> str:
        return DirectoryNavigationController._tree_root_for(path)

    def _restore_tree_expansion(self, tree_root: str, current_path: str) -> None:
        self.navigation._restore_tree_expansion(tree_root, current_path)

    def _build_reserve_entry(self, entry_or_path, *, sample_id: int | None = None) -> ReserveEntry:
        return self.index._build_reserve_entry(entry_or_path, sample_id=sample_id)

    def on_file_renamed(self, old_path: str, new_path: str, sample_id: int | None = None) -> None:
        self.index.on_file_renamed(old_path, new_path, sample_id)

    def _sync_preview_row_state(self) -> None:
        self.selection._sync_preview_row_state()

    def _on_common_preview_changed(self, entry: ReserveEntry | None) -> None:
        self.selection._on_common_preview_changed(entry)

    def _update_files_count_label(
        self,
        visible_count: int,
        total_count: int,
        subfolder_count: int = 0,
    ) -> None:
        file_part = (
            f"{visible_count} / {total_count} fichier{'s' if total_count != 1 else ''}"
            if total_count != visible_count
            else f"{visible_count} fichier{'s' if visible_count != 1 else ''}"
        )
        folder_part = (
            f" · {subfolder_count} dossier{'s' if subfolder_count != 1 else ''}"
            if subfolder_count > 0
            else ""
        )
        self.files_count_label.setText(file_part + folder_part)

    @staticmethod
    def remove_from_history(path: str) -> None:
        DirectoryHistory.remove_from_history(path)
