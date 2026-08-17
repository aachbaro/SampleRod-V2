# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la selection d'entrees du DirectoryWidget.
# - Isole la synchro entre la liste, le panneau de detail, la preview partagee
#   et l'ouverture waveform d'une entree.
#
# CE QUI EST COUVERT
# - current_reserve_entry()     : entree actuellement selectionnee.
# - start_rename_for_path()     : focus la ligne puis lance le renommage.
# - open_waveform_for_entry()   : selectionne puis ouvre dans le Labo.
# - _on_row_clicked() / _on_subfolder_clicked() / _on_list_selection_changed()
# - _set_selected_*()           : applique la selection visuelle.
# - _refresh_detail_for_path()  : recharge le detail.
# - _sync_detail_preview_state(): indique si la preview tourne.
# - _sync_preview_row_state()   : synchronise les icones play/pause des lignes.
#
# LIENS CLES
# - directory_widget.py      : facade qui garde les signaux Qt.
# - directory_list_builder.py: rebuild de liste qui reappelle ces helpers.
# - directory_detail.py      : panneau de detail pilote ici.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QListWidgetItem

from backend.services.audio_metadata import normalize_audio_path
from frontend.reserve import ReserveEntry

from .directory_item_widget import DirectoryListItemWidget, DirectorySubfolderRowWidget

logger = logging.getLogger("directory_widget")


class DirectorySelectionController:
    """Gere la selection des lignes, dossiers et le detail associe."""

    def __init__(self, widget):
        self.widget = widget

    def start_rename_for_path(self, path: str) -> None:
        item = self.widget._rows_by_path.get(normalize_audio_path(path))
        if item is None:
            return
        self._set_selected_row_widget(item[1], list_item=item[0])
        item[1]._start_rename()

    def current_reserve_entry(self) -> ReserveEntry | None:
        if not self.widget._selected_path:
            return None
        item = self.widget._rows_by_path.get(self.widget._selected_path)
        if item is None:
            return None
        return item[1].entry

    def open_waveform_for_entry(self, entry: ReserveEntry | None) -> bool:
        if entry is None:
            return False
        path = normalize_audio_path(entry.path)
        if path not in self.widget._rows_by_path:
            return False
        self._select_path(path)
        return self.widget.reserve_actions.open_waveform(entry)

    def _on_row_clicked(self, widget: DirectoryListItemWidget) -> None:
        item = self.widget._rows_by_path.get(normalize_audio_path(widget.file_path))
        if item is None:
            return
        self._set_selected_row_widget(widget, list_item=item[0])

    def _on_subfolder_clicked(self, folder_path: str) -> None:
        self._select_folder_path(folder_path)

    def _on_list_selection_changed(self) -> None:
        # Pointer selection is emitted directly by DirectoryListItemWidget on
        # MouseButtonPress.  Ignore incidental QListWidget current-item changes
        # (notably those produced while hovering native item widgets on
        # Windows); only Up/Down keyboard navigation enters through this slot.
        if not getattr(
            self.widget.list_widget, "_keyboard_selection_in_progress", False
        ):
            return
        list_item = self.widget.list_widget.currentItem()
        if list_item is None:
            self._set_selected_row_widget(None)
            return
        widget = self.widget.list_widget.itemWidget(list_item)
        if isinstance(widget, DirectoryListItemWidget):
            self._set_selected_row_widget(widget, list_item=list_item)
            return
        if isinstance(widget, DirectorySubfolderRowWidget):
            self._set_selected_folder_widget(widget, list_item=list_item)
            return
        self._set_selected_row_widget(None)

    def _set_selected_row_widget(
        self,
        widget: DirectoryListItemWidget | None,
        *,
        list_item: QListWidgetItem | None = None,
    ) -> None:
        for _, row_widget in self.widget._rows_by_path.values():
            row_widget.set_selected(row_widget is widget)
        for _, folder_widget in self.widget._folder_rows_by_path.values():
            folder_widget.set_selected(False)

        if widget is None:
            self.widget._selected_path = None
            self.widget._selected_folder_path = None
            self.widget.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            self.widget.reserveEntrySelected.emit(None)
            return

        if list_item is None:
            item = self.widget._rows_by_path.get(normalize_audio_path(widget.file_path))
            list_item = item[0] if item is not None else None

        if list_item is not None:
            with QSignalBlocker(self.widget.list_widget):
                self.widget.list_widget.setCurrentItem(list_item)

        self.widget._selected_path = normalize_audio_path(widget.file_path)
        self.widget._selected_folder_path = None
        self._refresh_detail_for_path(self.widget._selected_path)
        self.widget.reserveEntrySelected.emit(widget.entry)

    def _set_selected_folder_widget(
        self,
        widget: DirectorySubfolderRowWidget | None,
        *,
        list_item: QListWidgetItem | None = None,
    ) -> None:
        for _, row_widget in self.widget._rows_by_path.values():
            row_widget.set_selected(False)
        for _, folder_widget in self.widget._folder_rows_by_path.values():
            folder_widget.set_selected(folder_widget is widget)

        if widget is None:
            self.widget._selected_folder_path = None
            self.widget._selected_path = None
            self.widget.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            self.widget.reserveEntrySelected.emit(None)
            return

        if list_item is None:
            item = self.widget._folder_rows_by_path.get(normalize_audio_path(widget.folder_path))
            list_item = item[0] if item is not None else None

        if list_item is not None:
            with QSignalBlocker(self.widget.list_widget):
                self.widget.list_widget.setCurrentItem(list_item)

        self.widget._selected_folder_path = normalize_audio_path(widget.folder_path)
        self.widget._selected_path = None
        self.widget.detail_widget.clear_entry()
        self._sync_detail_preview_state()
        self.widget.reserveEntrySelected.emit(None)

    def _refresh_detail_for_path(self, path: str | None) -> None:
        if not path:
            self.widget.detail_widget.clear_entry()
            self._sync_detail_preview_state()
            return

        row = self.widget._rows_by_path.get(normalize_audio_path(path))
        if row is not None:
            entry = row[1].entry
        else:
            try:
                entry = self.widget._build_reserve_entry(
                    self.widget.service.describe_audio_entry(path, probe_filesystem=False)
                )
            except Exception as exc:
                logger.info("[DirectoryWidget] detail metadata error for %s: %s", path, exc)
                self.widget.detail_widget.clear_entry()
                self._sync_detail_preview_state()
                return
        self.widget.detail_widget.set_entry(entry)
        self._sync_detail_preview_state()

    def _sync_detail_preview_state(self) -> None:
        entry = self.current_reserve_entry()
        if entry is None:
            self.widget.detail_widget.set_preview_active(False)
            return
        self.widget.detail_widget.set_preview_active(
            self.widget.reserve_actions.is_previewing(entry)
        )

    def _select_path(self, path: str | None) -> None:
        if not path:
            return
        item = self.widget._rows_by_path.get(normalize_audio_path(path))
        if item is None:
            return
        self._set_selected_row_widget(item[1], list_item=item[0])

    def _select_folder_path(self, path: str | None) -> None:
        if not path:
            return
        item = self.widget._folder_rows_by_path.get(normalize_audio_path(path))
        if item is None:
            return
        self._set_selected_folder_widget(item[1], list_item=item[0])

    def _sync_preview_row_state(self) -> None:
        for _, widget in self.widget._rows_by_path.values():
            widget.set_playing(self.widget.reserve_actions.is_previewing(widget.entry))
        self._sync_detail_preview_state()

    def _on_common_preview_changed(self, entry: ReserveEntry | None) -> None:
        self._sync_preview_row_state()
