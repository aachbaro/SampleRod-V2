"""
Directory Widget (filesystem-first browser)
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import (
    QEasingCurve,
    QDir,
    QModelIndex,
    QPropertyAnimation,
    QSettings,
    QSignalBlocker,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFileSystemModel,
    QListWidgetItem,
    QSizePolicy,
    QWidget,
)

from backend.models.AppContext import AppContext
from backend.services.audio_metadata import normalize_audio_path
from backend.services.directory_service import DirectoryAudioEntry, DirectoryService
from frontend.reserve import (
    ReserveActions,
    ReserveEntry,
    apply_status_badge,
    reserve_entry_from_directory,
    reserve_entry_matches_query,
    reserve_entry_matches_status,
)
from frontend.styles import theme

from . import directory_ui
from .directory_detail import DirectoryDetailWidget
from .directory_history import DirectoryHistory
from .directory_item_widget import DirectoryListItemWidget
from .directory_store_sync import DirectoryStoreSync

logger = logging.getLogger("directory_widget")


class DirectoryWidget(QWidget):
    """Filesystem-first browser for audio folders, enriched by DB metadata."""

    directoryChanged = Signal(str)
    rootDirectoryChanged = Signal(str)
    sendToComposerRequested = Signal(list)
    reserveEntrySelected = Signal(object)

    def __init__(
        self,
        service: DirectoryService,
        app_context: AppContext,
        parent=None,
        path: str | None = None,
        reserve_actions: ReserveActions | None = None,
    ):
        super().__init__(parent)
        logger.info("[DirectoryWidget] Initialisation (start)")

        self.service = service
        self.app_context = app_context
        self.reserve_actions = reserve_actions or ReserveActions(self.app_context)
        self._items_by_id: dict[int, tuple[QListWidgetItem, DirectoryListItemWidget]] = {}
        self._rows_by_path: dict[str, tuple[QListWidgetItem, DirectoryListItemWidget]] = {}
        self._selected_path: str | None = None
        self._reserve_query_text = ""
        self._reserve_status_filter = "all"
        self._qs = QSettings("SampleRod", "Main")
        self._index_status_refresh_timer = QTimer(self)
        self._index_status_refresh_timer.setSingleShot(True)
        self._index_status_refresh_timer.setInterval(180)
        self._index_status_refresh_timer.timeout.connect(self._refresh_index_status)
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
        if self._selected_path and self._selected_path in self._rows_by_path:
            self._refresh_detail_for_path(self._selected_path)

    def choose_root_directory(self):
        start_dir = self.current_dir or self.history.get_last_directory() or os.path.expanduser("~")
        selected = QFileDialog.getExistingDirectory(self, "Choisir un dossier audio", start_dir)
        if selected:
            self.set_root_directory(selected)

    def set_root_directory(self, path: str) -> None:
        if not path:
            return
        normalized = normalize_audio_path(path)
        if not os.path.isdir(normalized):
            return

        self.root_dir = normalized
        self.history.set_last_root_directory(normalized)
        self.history.set_last_directory(normalized)
        self.history.add_recent_directory(normalized)
        self._update_tree_root(normalized)
        self.rootDirectoryChanged.emit(self.root_dir)
        self.open_directory(normalized)

    def open_directory(self, path: str) -> None:
        if not path:
            return
        normalized = normalize_audio_path(path)
        if not os.path.isdir(normalized):
            return

        self.current_dir = normalized
        directory_ui.set_directory_path(self, self.current_dir)
        self.history.set_last_directory(self.current_dir)
        if not self.root_dir:
            self.root_dir = normalized
            self.history.set_last_root_directory(normalized)
            self.rootDirectoryChanged.emit(self.root_dir)
        self._update_tree_root(self.current_dir)
        self._sync_tree_selection(self.current_dir)
        self._update_up_button_state()
        self.refresh_list()
        self._refresh_index_status()
        self.directoryChanged.emit(self.current_dir)

    def go_to_parent_directory(self) -> None:
        if not self.current_dir:
            return
        parent = normalize_audio_path(os.path.dirname(self.current_dir))
        if not parent or parent == self.current_dir:
            return
        self.open_directory(parent)

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
        item = self._rows_by_path.get(normalize_audio_path(path))
        if item is None:
            return
        self._set_selected_row_widget(item[1], list_item=item[0])
        item[1]._start_rename()

    def send_selected_to_composer(self) -> None:
        if self._selected_path:
            self.send_path_to_composer(self._selected_path)

    def send_path_to_composer(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        if os.path.isfile(normalized):
            self.sendToComposerRequested.emit([normalized])

    def set_reserve_query(self, query: str) -> None:
        query = (query or "").strip()
        if query == self._reserve_query_text:
            return
        self._reserve_query_text = query
        self.refresh_list()

    def set_reserve_status_filter(self, status_filter: str) -> None:
        status_filter = status_filter or "all"
        if status_filter == self._reserve_status_filter:
            return
        self._reserve_status_filter = status_filter
        self.refresh_list()

    def current_reserve_entry(self) -> ReserveEntry | None:
        if not self._selected_path:
            return None
        item = self._rows_by_path.get(self._selected_path)
        if item is None:
            return None
        return item[1].entry

    def open_waveform_for_entry(self, entry: ReserveEntry | None) -> bool:
        if entry is None:
            return False
        path = normalize_audio_path(entry.path)
        if path not in self._rows_by_path:
            return False
        self._select_path(path)
        return self.reserve_actions.open_waveform(entry)

    def rename_entry(self, entry: ReserveEntry, new_name: str) -> tuple[bool, str | None]:
        return self.reserve_actions.rename(entry, new_name)

    def refresh_list(self):
        previous_selection = self._selected_path

        # Bloquer les repaints pendant le vidage + remplissage pour éviter
        # les dizaines de redraws simultanés qui causent le clignotement Windows.
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()
        self._items_by_id.clear()
        self._rows_by_path.clear()

        if not self.current_dir:
            self.list_widget.setUpdatesEnabled(True)
            self.files_count_label.setText("0 fichier")
            self.detail_widget.clear_entry()
            self.reserveEntrySelected.emit(None)
            return

        entries = [
            self._build_reserve_entry(entry)
            for entry in self.service.list_audio_entries(self.current_dir)
        ]
        filtered_entries = [
            entry
            for entry in entries
            if reserve_entry_matches_query(entry, self._reserve_query_text)
            and reserve_entry_matches_status(entry, self._reserve_status_filter)
        ]
        logger.info("[DirectoryWidget] Rafraichissement de la liste (%s fichiers visibles)", len(filtered_entries))

        for entry in filtered_entries:
            self._add_row_direct(entry)

        self.list_widget.setUpdatesEnabled(True)

        self._update_files_count_label(len(filtered_entries), len(entries))

        if filtered_entries:
            target_path = (
                previous_selection
                if previous_selection in self._rows_by_path
                else filtered_entries[0].path
            )
            self._select_path(target_path)
        else:
            self._selected_path = None
            self.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            self.reserveEntrySelected.emit(None)

        self._sync_preview_row_state()

    def remove_paths_from_current_view(self, paths: list[str]) -> None:
        removed_any = False
        for raw_path in paths:
            path = normalize_audio_path(raw_path)
            item = self._rows_by_path.get(path)
            if item is None:
                continue
            self._remove_widget(item[1])
            removed_any = True
        if removed_any:
            self.schedule_index_status_refresh()

    def schedule_index_status_refresh(self, delay_ms: int = 180) -> None:
        self._index_status_refresh_timer.start(max(0, int(delay_ms)))

    def _refresh_index_status(self):
        if not self.current_dir or self.service.is_indexing():
            return
        status = self.service.get_folder_index_status(self.current_dir)
        detail = (
            f"Disque: {status['on_disk']} | DB: {status['tracked']} | "
            f"Manquants: {status['missing']}"
        )
        self._set_status(status["label"], detail)

    def _set_status(self, label: str, detail: str | None = None):
        self.status_label.setText(label)
        if detail:
            self.progress_label.setText(detail)
            self.progress_label.setVisible(True)
        else:
            self.progress_label.setText("")
            self.progress_label.setVisible(False)

    def _set_index_busy(self, busy: bool):
        self.index_button.setEnabled(not busy)
        self.index_progress.setVisible(busy)
        if not busy:
            self.index_progress.setRange(0, 100)
            self.index_progress.setValue(0)

    def _on_index_started(self, folder: str):
        if normalize_audio_path(folder) != self.current_dir:
            return
        self._set_index_busy(True)
        self.status_label.setText("Indexation en cours")
        self.progress_label.setText("Preparation du scan...")
        self.progress_label.setVisible(True)
        self.index_progress.setRange(0, 0)

    def _on_index_progress(self, folder: str, current: int, total: int, message: str):
        if normalize_audio_path(folder) != self.current_dir:
            return
        self._set_index_busy(True)
        if total > 0:
            self.index_progress.setRange(0, total)
            self.index_progress.setValue(max(0, min(current, total)))
        else:
            self.index_progress.setRange(0, 0)
        self.progress_label.setText(message)
        self.progress_label.setVisible(True)

    def _on_index_finished(self, folder: str, summary: object):
        if normalize_audio_path(folder) != self.current_dir:
            return
        summary_dict = dict(summary or {})
        self._set_index_busy(False)
        self.refresh_list()
        detail = (
            f"{summary_dict.get('total_audio_files', 0)} fichiers | "
            f"+{summary_dict.get('added', 0)} ajoutes | "
            f"~{summary_dict.get('updated', 0)} sync | "
            f"{summary_dict.get('marked_missing', 0)} manquants"
        )
        self._set_status("Indexe", detail)
        self._refresh_index_status()

    def _on_index_failed(self, folder: str, message: str):
        if normalize_audio_path(folder) != self.current_dir:
            return
        self._set_index_busy(False)
        self._set_status("Non indexe", message or "Erreur d'indexation")

    def _add_row_direct(self, entry: ReserveEntry) -> None:
        """Insertion immédiate sans animation — utilisée par refresh_list()."""
        item_widget = DirectoryListItemWidget(entry, self)
        item_widget.clicked.connect(lambda _widget=None, w=item_widget: self._on_row_clicked(w))
        list_item = QListWidgetItem(self.list_widget)
        list_item.setSizeHint(item_widget.sizeHint())
        self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, item_widget)
        self._rows_by_path[entry.path] = (list_item, item_widget)
        if entry.sample_id is not None:
            self._items_by_id[entry.sample_id] = (list_item, item_widget)

    def _add_row(self, entry_or_path, sample_id: int | None = None) -> None:
        entry = self._build_reserve_entry(entry_or_path, sample_id=sample_id)
        item_widget = DirectoryListItemWidget(entry, self)
        item_widget.clicked.connect(lambda _widget=None, w=item_widget: self._on_row_clicked(w))

        list_item = QListWidgetItem(self.list_widget)
        target_height = max(1, item_widget.sizeHint().height())
        item_widget.setMaximumHeight(0)
        list_item.setSizeHint(QSize(0, 0))
        self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, item_widget)

        self._rows_by_path[entry.path] = (list_item, item_widget)
        if entry.sample_id is not None:
            self._items_by_id[entry.sample_id] = (list_item, item_widget)

        list_widget = self.list_widget
        animation = QPropertyAnimation(item_widget, b"maximumHeight", list_widget)
        animation.setDuration(200)
        animation.setStartValue(0)
        animation.setEndValue(target_height)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _hint(height):
            try:
                list_item.setSizeHint(QSize(list_widget.viewport().width(), height))
            except RuntimeError:
                pass

        animation.valueChanged.connect(_hint)
        animation.finished.connect(
            lambda: (
                item_widget.setMaximumHeight(16777215),
                _hint(target_height),
            )
        )
        animation.start()
        item_widget._anim_in = animation

    def _update_row(self, sample_id: int, new_path: str) -> None:
        item = self._items_by_id.get(sample_id)
        if not item:
            return
        _, widget = item
        old_path = normalize_audio_path(widget.file_path)
        entry = self._build_reserve_entry(new_path, sample_id=sample_id)
        widget.refresh_entry(entry)

        if old_path in self._rows_by_path:
            list_item, _ = self._rows_by_path.pop(old_path)
            self._rows_by_path[entry.path] = (list_item, widget)
        if self._selected_path == old_path:
            self._selected_path = entry.path
            self._refresh_detail_for_path(entry.path)

    def _remove_row(self, sample_id: int) -> None:
        item = self._items_by_id.get(sample_id)
        if not item:
            return
        _, widget = item
        self._remove_widget(widget)

    def _remove_widget(self, widget: DirectoryListItemWidget) -> None:
        target_item = None
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if self.list_widget.itemWidget(item) is widget:
                target_item = item
                break

        if widget.sample_id is not None:
            self._items_by_id.pop(widget.sample_id, None)
        self._rows_by_path.pop(normalize_audio_path(widget.file_path), None)

        if self._selected_path == normalize_audio_path(widget.file_path):
            self._selected_path = None

        if target_item is None:
            self._sync_after_widget_removal()
            return

        start_height = max(1, widget.height())
        list_widget = self.list_widget

        animation = QPropertyAnimation(widget, b"maximumHeight", list_widget)
        animation.setDuration(160)
        animation.setStartValue(start_height)
        animation.setEndValue(0)
        animation.setEasingCurve(QEasingCurve.Type.InCubic)

        def _hint(height):
            try:
                target_item.setSizeHint(QSize(list_widget.viewport().width(), height))
            except RuntimeError:
                pass

        def _finalize():
            try:
                row = list_widget.row(target_item)
                if row >= 0:
                    list_widget.takeItem(row)
            except RuntimeError:
                pass
            try:
                widget.deleteLater()
            except RuntimeError:
                pass
            self._sync_after_widget_removal()

        animation.valueChanged.connect(_hint)
        animation.finished.connect(_finalize)
        animation.start()
        widget._anim_out = animation

    def _sync_after_widget_removal(self) -> None:
        self._update_files_count_label(len(self._rows_by_path), len(self._rows_by_path))
        if self._selected_path and self._selected_path in self._rows_by_path:
            self._refresh_detail_for_path(self._selected_path)
        elif self._rows_by_path:
            self._select_path(next(iter(self._rows_by_path.keys())))
        else:
            self.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            self.reserveEntrySelected.emit(None)
        self._sync_preview_row_state()

    def _on_tree_current_changed(self, current: QModelIndex, _previous: QModelIndex):
        path = self.fs_model.filePath(current)
        if path and os.path.isdir(path) and normalize_audio_path(path) != self.current_dir:
            self.open_directory(path)

    def _on_tree_expanded(self, index: QModelIndex) -> None:
        path = normalize_audio_path(self.fs_model.filePath(index))
        if path and os.path.isdir(path):
            self.history.add_expanded_directory(path)

    def _on_tree_collapsed(self, index: QModelIndex) -> None:
        path = normalize_audio_path(self.fs_model.filePath(index))
        if path and os.path.isdir(path):
            self.history.remove_expanded_directory(path)

    def _on_row_clicked(self, widget: DirectoryListItemWidget) -> None:
        item = self._rows_by_path.get(normalize_audio_path(widget.file_path))
        if item is None:
            return
        self._set_selected_row_widget(widget, list_item=item[0])

    def _on_list_selection_changed(self) -> None:
        list_item = self.list_widget.currentItem()
        if list_item is None:
            self._set_selected_row_widget(None)
            return
        widget = self.list_widget.itemWidget(list_item)
        if isinstance(widget, DirectoryListItemWidget):
            self._set_selected_row_widget(widget, list_item=list_item)

    def _set_selected_row_widget(
        self,
        widget: DirectoryListItemWidget | None,
        *,
        list_item: QListWidgetItem | None = None,
    ) -> None:
        for _, row_widget in self._rows_by_path.values():
            row_widget.set_selected(row_widget is widget)

        if widget is None:
            self._selected_path = None
            self.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            self.reserveEntrySelected.emit(None)
            return

        if list_item is None:
            item = self._rows_by_path.get(normalize_audio_path(widget.file_path))
            list_item = item[0] if item is not None else None

        if list_item is not None:
            with QSignalBlocker(self.list_widget):
                self.list_widget.setCurrentItem(list_item)

        self._selected_path = normalize_audio_path(widget.file_path)
        self._refresh_detail_for_path(self._selected_path)
        self.reserveEntrySelected.emit(widget.entry)

    def _refresh_detail_for_path(self, path: str | None) -> None:
        if not path:
            self.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            return

        row = self._rows_by_path.get(normalize_audio_path(path))
        if row is not None:
            entry = row[1].entry
        else:
            try:
                entry = reserve_entry_from_directory(
                    self.service.describe_audio_entry(path, probe_filesystem=False)
                )
            except Exception as exc:
                logger.info("[DirectoryWidget] detail metadata error for %s: %s", path, exc)
                self.detail_widget.clear_entry()
                self._sync_detail_preview_state()
                return
        self.detail_widget.set_entry(entry)
        self._sync_detail_preview_state()

    def _sync_detail_preview_state(self) -> None:
        entry = self.current_reserve_entry()
        if entry is None:
            self.detail_widget.set_preview_active(False)
            return
        self.detail_widget.set_preview_active(self.reserve_actions.is_previewing(entry))

    def _select_path(self, path: str | None) -> None:
        if not path:
            return
        item = self._rows_by_path.get(normalize_audio_path(path))
        if item is None:
            return
        self._set_selected_row_widget(item[1], list_item=item[0])

    def _sync_tree_selection(self, path: str) -> None:
        index = self.fs_model.index(path)
        if not index.isValid():
            return
        selection_model = self.tree_view.selectionModel()
        if selection_model is None:
            return
        with QSignalBlocker(selection_model):
            self.tree_view.setCurrentIndex(index)
        self.tree_view.scrollTo(index)

    def _update_up_button_state(self) -> None:
        if not self.current_dir:
            self.up_button.setEnabled(False)
            return
        current = normalize_audio_path(self.current_dir)
        parent = normalize_audio_path(os.path.dirname(current))
        self.up_button.setEnabled(bool(parent) and parent != current)

    def _update_tree_root(self, path: str) -> None:
        tree_root = self._tree_root_for(path)
        root_index = self.fs_model.setRootPath(tree_root)
        self.tree_view.setRootIndex(root_index)
        self._restore_tree_expansion(tree_root, path)

    @staticmethod
    def _tree_root_for(path: str) -> str:
        normalized = normalize_audio_path(path)
        parent = normalize_audio_path(os.path.dirname(normalized))
        if parent and parent != normalized and os.path.isdir(parent):
            return parent
        return normalized

    def _restore_tree_expansion(self, tree_root: str, current_path: str) -> None:
        to_expand: list[str] = []
        current = normalize_audio_path(current_path)
        root = normalize_audio_path(tree_root)

        while current:
            to_expand.append(current)
            if current == root:
                break
            parent = normalize_audio_path(os.path.dirname(current))
            if not parent or parent == current:
                break
            current = parent

        for path in self.history.get_expanded_directories():
            normalized = normalize_audio_path(path)
            if normalized not in to_expand and _is_path_in_folder(normalized, root):
                to_expand.append(normalized)

        for path in reversed(to_expand):
            index = self.fs_model.index(path)
            if index.isValid():
                self.tree_view.expand(index)

    def _build_reserve_entry(self, entry_or_path, *, sample_id: int | None = None) -> ReserveEntry:
        if isinstance(entry_or_path, ReserveEntry):
            entry = entry_or_path
        elif isinstance(entry_or_path, DirectoryAudioEntry):
            entry = reserve_entry_from_directory(entry_or_path)
        else:
            path = normalize_audio_path(str(entry_or_path))
            try:
                entry = reserve_entry_from_directory(
                    self.service.describe_audio_entry(path, probe_filesystem=False)
                )
            except Exception:
                entry = ReserveEntry(
                    source_kind="filesystem",
                    path=path,
                    sample_id=sample_id,
                    display_name=os.path.splitext(os.path.basename(path))[0],
                    folder_path=os.path.dirname(path),
                    indexed=sample_id is not None,
                )

        if sample_id is not None and entry.sample_id is None:
            entry.sample_id = sample_id
            entry.indexed = True
        entry.root_path = self.root_dir
        entry.folder_path = entry.folder_path or os.path.dirname(entry.path)
        return entry

    def on_file_renamed(self, old_path: str, new_path: str, sample_id: int | None = None) -> None:
        old_key = normalize_audio_path(old_path)
        new_key = normalize_audio_path(new_path)
        if sample_id is not None and sample_id in self._items_by_id:
            self._update_row(sample_id, new_key)
        else:
            item = self._rows_by_path.get(old_key)
            if item is not None:
                _, widget = item
                widget.refresh_entry(self._build_reserve_entry(new_key, sample_id=sample_id))
                self._rows_by_path.pop(old_key, None)
                self._rows_by_path[new_key] = item
            else:
                self.refresh_list()

        if self._selected_path == old_key:
            self._selected_path = new_key
            self._refresh_detail_for_path(new_key)
        self._sync_preview_row_state()
        self._refresh_index_status()

    def _sync_preview_row_state(self) -> None:
        for _, widget in self._rows_by_path.values():
            widget.set_playing(self.reserve_actions.is_previewing(widget.entry))
        self._sync_detail_preview_state()

    def _on_common_preview_changed(self, entry: ReserveEntry | None) -> None:
        self._sync_preview_row_state()

    def _update_files_count_label(self, visible_count: int, total_count: int) -> None:
        if total_count != visible_count:
            self.files_count_label.setText(
                f"{visible_count} / {total_count} fichier{'s' if total_count != 1 else ''}"
            )
            return
        self.files_count_label.setText(
            f"{visible_count} fichier{'s' if visible_count != 1 else ''}"
        )

    @staticmethod
    def remove_from_history(path: str) -> None:
        DirectoryHistory.remove_from_history(path)


def _is_path_in_folder(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([normalize_audio_path(path), normalize_audio_path(folder)]) == normalize_audio_path(folder)
    except ValueError:
        return False
