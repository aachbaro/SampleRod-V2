# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la reconstruction de liste du DirectoryWidget.
# - Isole l'insertion/suppression des lignes et les animations associees.
#
# CE QUI EST COUVERT
# - refresh_list() : dossiers puis fichiers, avec filtres Reserve.
# - _add_row/_add_row_direct() : ajout anime ou direct.
# - _remove_widget()           : suppression animee.
# - _sync_after_widget_removal(): resynchronise selection et detail.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import QListWidgetItem

from backend.services.audio_metadata import normalize_audio_path
from frontend.reserve import (
    reserve_entry_matches_query,
    reserve_entry_matches_status,
)

from .directory_item_widget import DirectoryListItemWidget, DirectorySubfolderRowWidget

logger = logging.getLogger("directory_widget")


class DirectoryListBuilder:
    """Gere la liste des dossiers/fichiers visibles dans DirectoryWidget."""

    def __init__(self, widget):
        self.widget = widget

    def refresh_list(self):
        previous_selection = self.widget._selected_path or self.widget._selected_folder_path

        self.widget.list_widget.setUpdatesEnabled(False)
        self.widget.list_widget.clear()
        self.widget._items_by_id.clear()
        self.widget._rows_by_path.clear()
        self.widget._folder_rows_by_path.clear()

        if not self.widget.current_dir:
            self.widget.list_widget.setUpdatesEnabled(True)
            self.widget.files_count_label.setText("0 fichier")
            self.widget.detail_widget.clear_entry()
            self.widget.reserveEntrySelected.emit(None)
            return

        try:
            subdirs = sorted(
                [
                    os.path.join(self.widget.current_dir, d)
                    for d in os.listdir(self.widget.current_dir)
                    if os.path.isdir(os.path.join(self.widget.current_dir, d))
                    and not d.startswith(".")
                ]
            )
        except OSError:
            subdirs = []

        for subdir_path in subdirs:
            self._add_subfolder_row(subdir_path)

        entries = [
            self.widget._build_reserve_entry(entry)
            for entry in self.widget.service.list_audio_entries(self.widget.current_dir)
        ]
        filtered_entries = [
            entry
            for entry in entries
            if reserve_entry_matches_query(entry, self.widget._reserve_query_text)
            and reserve_entry_matches_status(entry, self.widget._reserve_status_filter)
            and (
                not self.widget._compat_filter_scales
                or bool(set(entry.compatible_scales) & self.widget._compat_filter_scales)
            )
        ]
        logger.info(
            "[DirectoryWidget] Rafraichissement de la liste (%s fichiers visibles)",
            len(filtered_entries),
        )

        for entry in filtered_entries:
            self._add_row_direct(entry)

        self.widget.list_widget.setUpdatesEnabled(True)

        self.widget._update_files_count_label(
            len(filtered_entries),
            len(entries),
            len(subdirs),
        )

        if previous_selection and previous_selection in self.widget._folder_rows_by_path:
            self.widget._select_folder_path(previous_selection)
        elif filtered_entries:
            target_path = (
                previous_selection
                if previous_selection in self.widget._rows_by_path
                else filtered_entries[0].path
            )
            self.widget._select_path(target_path)
        elif subdirs:
            target_folder = (
                previous_selection
                if previous_selection in self.widget._folder_rows_by_path
                else normalize_audio_path(subdirs[0])
            )
            self.widget._select_folder_path(target_folder)
        else:
            self.widget._selected_path = None
            self.widget._selected_folder_path = None
            self.widget.detail_widget.clear_entry()
            self.widget._sync_detail_preview_state()
            self.widget.reserveEntrySelected.emit(None)

        self.widget._sync_preview_row_state()

    def remove_paths_from_current_view(self, paths: list[str]) -> None:
        removed_any = False
        for raw_path in paths:
            path = normalize_audio_path(raw_path)
            item = self.widget._rows_by_path.get(path)
            if item is None:
                continue
            self._remove_widget(item[1])
            removed_any = True
        if removed_any:
            self.widget.schedule_index_status_refresh()

    def _add_subfolder_row(self, subdir_path: str) -> None:
        row_widget = DirectorySubfolderRowWidget(subdir_path, self.widget)
        row_widget.clicked.connect(self.widget._on_subfolder_clicked)
        list_item = QListWidgetItem(self.widget.list_widget)
        list_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        list_item.setSizeHint(row_widget.sizeHint())
        self.widget.list_widget.addItem(list_item)
        self.widget.list_widget.setItemWidget(list_item, row_widget)
        self.widget._folder_rows_by_path[normalize_audio_path(subdir_path)] = (list_item, row_widget)

    def _add_row_direct(self, entry) -> None:
        item_widget = DirectoryListItemWidget(entry, self.widget)
        item_widget.clicked.connect(lambda _widget=None, w=item_widget: self.widget._on_row_clicked(w))
        list_item = QListWidgetItem(self.widget.list_widget)
        list_item.setSizeHint(item_widget.sizeHint())
        self.widget.list_widget.addItem(list_item)
        self.widget.list_widget.setItemWidget(list_item, item_widget)
        self.widget._rows_by_path[entry.path] = (list_item, item_widget)
        if entry.sample_id is not None:
            self.widget._items_by_id[entry.sample_id] = (list_item, item_widget)

    def _add_row(self, entry_or_path, sample_id: int | None = None) -> None:
        entry = self.widget._build_reserve_entry(entry_or_path, sample_id=sample_id)
        item_widget = DirectoryListItemWidget(entry, self.widget)
        item_widget.clicked.connect(lambda _widget=None, w=item_widget: self.widget._on_row_clicked(w))

        list_item = QListWidgetItem(self.widget.list_widget)
        target_height = max(1, item_widget.sizeHint().height())
        item_widget.setMaximumHeight(0)
        list_item.setSizeHint(QSize(0, 0))
        self.widget.list_widget.addItem(list_item)
        self.widget.list_widget.setItemWidget(list_item, item_widget)

        self.widget._rows_by_path[entry.path] = (list_item, item_widget)
        if entry.sample_id is not None:
            self.widget._items_by_id[entry.sample_id] = (list_item, item_widget)

        list_widget = self.widget.list_widget
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
        item = self.widget._items_by_id.get(sample_id)
        if not item:
            return
        _, widget = item
        old_path = normalize_audio_path(widget.file_path)
        entry = self.widget._build_reserve_entry(new_path, sample_id=sample_id)
        widget.refresh_entry(entry)

        if old_path in self.widget._rows_by_path:
            list_item, _ = self.widget._rows_by_path.pop(old_path)
            self.widget._rows_by_path[entry.path] = (list_item, widget)
        if self.widget._selected_path == old_path:
            self.widget._selected_path = entry.path
            self.widget._refresh_detail_for_path(entry.path)

    def _remove_row(self, sample_id: int) -> None:
        item = self.widget._items_by_id.get(sample_id)
        if not item:
            return
        _, widget = item
        self._remove_widget(widget)

    def _remove_widget(self, widget: DirectoryListItemWidget) -> None:
        target_item = None
        for index in range(self.widget.list_widget.count()):
            item = self.widget.list_widget.item(index)
            if self.widget.list_widget.itemWidget(item) is widget:
                target_item = item
                break

        if widget.sample_id is not None:
            self.widget._items_by_id.pop(widget.sample_id, None)
        self.widget._rows_by_path.pop(normalize_audio_path(widget.file_path), None)

        if self.widget._selected_path == normalize_audio_path(widget.file_path):
            self.widget._selected_path = None

        if target_item is None:
            self._sync_after_widget_removal()
            return

        start_height = max(1, widget.height())
        list_widget = self.widget.list_widget

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
        self.widget._update_files_count_label(
            len(self.widget._rows_by_path),
            len(self.widget._rows_by_path),
            len(self.widget._folder_rows_by_path),
        )
        if self.widget._selected_path and self.widget._selected_path in self.widget._rows_by_path:
            self.widget._refresh_detail_for_path(self.widget._selected_path)
        elif self.widget._rows_by_path:
            self.widget._select_path(next(iter(self.widget._rows_by_path.keys())))
        elif self.widget._folder_rows_by_path:
            self.widget._select_folder_path(next(iter(self.widget._folder_rows_by_path.keys())))
        else:
            self.widget.detail_widget.clear_entry()
            self.widget._sync_detail_preview_state()
            self.widget.reserveEntrySelected.emit(None)
        self.widget._sync_preview_row_state()
