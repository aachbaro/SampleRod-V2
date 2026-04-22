from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QDesktopServices

from backend.services.audio_metadata import get_audio_duration, normalize_audio_path
from .reserve_entry import ReserveEntry


class ReserveActions(QObject):
    """Common Reserve actions shared by multiple Reserve sources."""

    sendToLabRequested = Signal(list)
    waveformRequested = Signal(object)
    previewChanged = Signal(object)

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context
        self.sample_store = app_context.sample_store
        self.audio_player = app_context.audio_player

    def can_preview(self, entry: ReserveEntry | None) -> bool:
        return bool(entry and entry.path and os.path.isfile(entry.path) and not entry.missing)

    def can_rename(self, entry: ReserveEntry | None) -> bool:
        return bool(entry and entry.path and os.path.isfile(entry.path) and not entry.missing)

    def can_open_waveform(self, entry: ReserveEntry | None) -> bool:
        return self.can_preview(entry)

    def can_reveal_in_folder(self, entry: ReserveEntry | None) -> bool:
        return bool(entry and entry.path)

    def can_send_to_lab(self, entry: ReserveEntry | None) -> bool:
        return self.can_preview(entry)

    def is_previewing(self, entry: ReserveEntry | None) -> bool:
        if not entry or not self.audio_player.is_playing:
            return False
        current_path = normalize_audio_path(self.audio_player.current_sample_path or "")
        return current_path == normalize_audio_path(entry.path)

    def seek_preview(self, entry: ReserveEntry | None, position_ms: int) -> bool:
        if not self.can_preview(entry):
            return False
        assert entry is not None

        duration = self._duration_for_entry(entry)
        if duration <= 0:
            return False

        position_ms = max(0, min(int(position_ms), int(duration * 1000)))
        sample_id = self._preview_sample_id(entry)
        is_playing = self.audio_player.seek_position(
            sample_id,
            entry.path,
            duration,
            position_ms,
        )
        self.previewChanged.emit(entry if is_playing else None)
        return is_playing

    def preview(self, entry: ReserveEntry | None) -> bool:
        if not self.can_preview(entry):
            return False
        assert entry is not None
        if self.is_previewing(entry):
            try:
                self.audio_player.clear_audio()
            except Exception:
                pass
            self.previewChanged.emit(None)
            return False

        try:
            if self.audio_player.is_playing:
                self.audio_player.clear_audio()
        except Exception:
            pass

        duration = self._duration_for_entry(entry)
        sample_id = self._preview_sample_id(entry)
        self.audio_player.toggle_play(sample_id, entry.path, duration)
        self.previewChanged.emit(entry)
        return True

    def rename(self, entry: ReserveEntry | None, new_name: str) -> tuple[bool, str | None]:
        if not self.can_rename(entry):
            return False, "Renommage indisponible"
        assert entry is not None
        if entry.sample_id is not None:
            self.sample_store.rename(int(entry.sample_id), new_name)
            return True, None
        return self.sample_store.rename_by_path(entry.path, new_name)

    def reveal_in_folder(self, entry: ReserveEntry | None) -> bool:
        if not self.can_reveal_in_folder(entry):
            return False
        assert entry is not None
        folder = os.path.dirname(entry.path)
        if not folder:
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        return True

    def open_waveform(self, entry: ReserveEntry | None) -> bool:
        if not self.can_open_waveform(entry):
            return False
        self.waveformRequested.emit(entry)
        return True

    def send_to_lab(self, entry: ReserveEntry | None) -> bool:
        if not self.can_send_to_lab(entry):
            return False
        assert entry is not None
        self.sendToLabRequested.emit([entry.path])
        return True

    @staticmethod
    def _preview_sample_id(entry: ReserveEntry) -> int:
        return int(entry.sample_id) if entry.sample_id is not None else (hash(entry.path) & 0x7FFFFFFF)

    @staticmethod
    def _duration_for_entry(entry: ReserveEntry) -> float:
        duration = float(entry.duration or 0.0)
        if duration > 0:
            return duration
        try:
            return float(get_audio_duration(entry.path))
        except Exception:
            return 0.0
