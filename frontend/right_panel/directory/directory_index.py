# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la couche d'indexation DB du DirectoryWidget.
# - Isole le statut d'indexation, la conversion ReserveEntry et la mise a jour
#   apres renommage.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from backend.services.audio_metadata import normalize_audio_path
from backend.services.directory_service import DirectoryAudioEntry
from frontend.reserve import ReserveEntry, reserve_entry_from_directory


class DirectoryIndexController:
    """Gere l'etat d'indexation et les conversions ReserveEntry du navigateur."""

    def __init__(self, widget):
        self.widget = widget

    def schedule_index_status_refresh(self, delay_ms: int = 180) -> None:
        self.widget._index_status_refresh_timer.start(max(0, int(delay_ms)))

    def _refresh_index_status(self):
        if not self.widget.current_dir or self.widget.service.is_indexing():
            return
        status = self.widget.service.get_folder_index_status(self.widget.current_dir)
        on_disk = int(status.get("on_disk", 0))
        tracked = int(status.get("tracked", 0))
        detail = (
            f"Disque: {on_disk} | DB: {tracked} | "
            f"Manquants: {status.get('missing', 0)}"
        )
        self._set_status(status["label"], detail)
        if tracked == 0:
            chip_key = "none"
        elif tracked >= on_disk > 0:
            chip_key = "full"
        else:
            chip_key = "partial"
        from . import directory_ui

        directory_ui.update_index_chip(self.widget, chip_key, tracked=tracked, total=on_disk)

    def _set_status(self, label: str, detail: str | None = None):
        self.widget.status_label.setText(label)
        if detail:
            self.widget.progress_label.setText(detail)
            self.widget.progress_label.setVisible(True)
        else:
            self.widget.progress_label.setText("")
            self.widget.progress_label.setVisible(False)

    def _set_index_busy(self, busy: bool):
        self.widget.index_progress.setVisible(busy)
        if busy:
            from . import directory_ui

            directory_ui.update_index_chip(self.widget, "busy")
        else:
            self.widget.index_progress.setRange(0, 100)
            self.widget.index_progress.setValue(0)

    def _on_index_started(self, folder: str):
        if normalize_audio_path(folder) != self.widget.current_dir:
            return
        self._set_index_busy(True)
        self.widget.status_label.setText("Indexation en cours")
        self.widget.progress_label.setText("Preparation du scan...")
        self.widget.progress_label.setVisible(True)
        self.widget.index_progress.setRange(0, 0)

    def _on_index_progress(self, folder: str, current: int, total: int, message: str):
        if normalize_audio_path(folder) != self.widget.current_dir:
            return
        self._set_index_busy(True)
        if total > 0:
            self.widget.index_progress.setRange(0, total)
            self.widget.index_progress.setValue(max(0, min(current, total)))
        else:
            self.widget.index_progress.setRange(0, 0)
        self.widget.progress_label.setText(message)
        self.widget.progress_label.setVisible(True)

    def _on_index_finished(self, folder: str, summary: object):
        if normalize_audio_path(folder) != self.widget.current_dir:
            return
        summary_dict = dict(summary or {})
        self._set_index_busy(False)
        self.widget.refresh_list()
        detail = (
            f"{summary_dict.get('total_audio_files', 0)} fichiers | "
            f"+{summary_dict.get('added', 0)} ajoutes | "
            f"~{summary_dict.get('updated', 0)} sync | "
            f"{summary_dict.get('marked_missing', 0)} manquants"
        )
        self._set_status("Indexe", detail)
        self._refresh_index_status()

    def _on_index_failed(self, folder: str, message: str):
        if normalize_audio_path(folder) != self.widget.current_dir:
            return
        self._set_index_busy(False)
        self._set_status("Non indexe", message or "Erreur d'indexation")

    def _build_reserve_entry(self, entry_or_path, *, sample_id: int | None = None) -> ReserveEntry:
        if isinstance(entry_or_path, ReserveEntry):
            entry = entry_or_path
        elif isinstance(entry_or_path, DirectoryAudioEntry):
            entry = reserve_entry_from_directory(entry_or_path)
        else:
            path = normalize_audio_path(str(entry_or_path))
            try:
                entry = reserve_entry_from_directory(
                    self.widget.service.describe_audio_entry(path, probe_filesystem=False)
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
        entry.root_path = self.widget.root_dir
        entry.folder_path = entry.folder_path or os.path.dirname(entry.path)
        return entry

    def on_file_renamed(self, old_path: str, new_path: str, sample_id: int | None = None) -> None:
        old_key = normalize_audio_path(old_path)
        new_key = normalize_audio_path(new_path)
        if sample_id is not None and sample_id in self.widget._items_by_id:
            self.widget._update_row(sample_id, new_key)
        else:
            item = self.widget._rows_by_path.get(old_key)
            if item is not None:
                _, widget = item
                widget.refresh_entry(self._build_reserve_entry(new_key, sample_id=sample_id))
                self.widget._rows_by_path.pop(old_key, None)
                self.widget._rows_by_path[new_key] = item
            else:
                self.widget.refresh_list()

        if self.widget._selected_path == old_key:
            self.widget._selected_path = new_key
            self.widget._refresh_detail_for_path(new_key)
        self.widget._sync_preview_row_state()
        self._refresh_index_status()
