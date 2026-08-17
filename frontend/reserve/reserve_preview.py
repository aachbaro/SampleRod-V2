from __future__ import annotations

import os
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from backend.services.audio_metadata import get_audio_duration, normalize_audio_path


@dataclass(frozen=True, slots=True)
class ReservePreviewKey:
    sample_id: int | None
    path: str

    @classmethod
    def from_entry(cls, entry) -> "ReservePreviewKey":
        value = getattr(entry, "sample_id", None)
        return cls(
            int(value) if value is not None else None,
            normalize_audio_path(getattr(entry, "path", "") or ""),
        )

    def matches(self, entry) -> bool:
        other = ReservePreviewKey.from_entry(entry)
        if self.path and other.path:
            return os.path.normcase(self.path) == os.path.normcase(other.path)
        return self.sample_id is not None and self.sample_id == other.sample_id


class ReservePreviewController(QObject):
    """Autorité UI de la preview Réserve au-dessus de l'unique AudioPlayer."""

    activeEntryChanged = Signal(object)
    positionChanged = Signal(object, int)
    playbackStateChanged = Signal(object, bool, bool)  # entry, playing, paused
    stopped = Signal(object)

    def __init__(self, audio_player, parent=None):
        super().__init__(parent)
        self.audio_player = audio_player
        self.active_entry = None
        self.active_key: ReservePreviewKey | None = None
        self._path_session_ids: dict[str, int] = {}
        self._next_session_id = -2
        self._renderers: dict[str, tuple[weakref.ReferenceType, list[tuple[object, object]]]] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll_position)

    def play_pause(self, entry) -> bool:
        if not self._can_play(entry):
            return False
        identity = ReservePreviewKey.from_entry(entry)
        if self.active_key is not None and not self.active_key.matches(entry):
            self.stop()
        duration_ms = max(0, int(self._duration(entry) * 1000))
        if self.active_key is not None and self.active_key.matches(entry) and duration_ms:
            try:
                at_end = int(self.audio_player.get_position()) >= duration_ms
            except Exception:
                at_end = False
            if at_end:
                return self.restart(entry)
        player_id = self._effective_player_id(identity)
        try:
            playing = bool(self.audio_player.toggle_play(
                player_id, identity.path, self._duration(entry)
            ))
        except Exception:
            if self.active_key is not None and self.active_key.matches(entry):
                self.stop(entry)
            return False
        self.active_entry = entry
        self.active_key = identity
        self.activeEntryChanged.emit(entry)
        self._emit_state()
        self._timer.start()
        return playing

    def seek(self, entry, milliseconds: int) -> bool:
        if not self._can_play(entry):
            return False
        identity = ReservePreviewKey.from_entry(entry)
        duration = self._duration(entry)
        maximum = max(0, int(duration * 1000))
        position = max(0, min(int(milliseconds), maximum))
        try:
            playing = bool(self.audio_player.seek_position(
                self._effective_player_id(identity), identity.path, duration, position,
            ))
        except Exception:
            return False
        self.active_entry = entry
        self.active_key = identity
        self.activeEntryChanged.emit(entry)
        self.positionChanged.emit(entry, position)
        self._emit_state()
        self._timer.start()
        return playing

    def restart(self, entry) -> bool:
        if not self._can_play(entry):
            return False
        self.stop()
        return self.seek(entry, 0)

    def stop(self, entry=None) -> bool:
        if entry is not None and not self.is_active(entry):
            return False
        previous = self.active_entry
        try:
            self.audio_player.clear_audio()
        except Exception:
            pass
        self._timer.stop()
        self.active_entry = None
        self.active_key = None
        self.activeEntryChanged.emit(None)
        self.playbackStateChanged.emit(previous, False, False)
        self.stopped.emit(previous)
        return previous is not None

    def interrupt_for_mutation(self, entry) -> bool:
        return self.stop(entry) if self.is_active(entry) else False

    def is_active(self, entry) -> bool:
        return bool(entry is not None and self.active_key and self.active_key.matches(entry))

    def attach_renderer(
        self, owner_id: str, owner, *, active=None, position=None, state=None, stopped=None
    ) -> None:
        self.detach_renderer(owner_id)
        connections = []
        for signal, callback in (
            (self.activeEntryChanged, active),
            (self.positionChanged, position),
            (self.playbackStateChanged, state),
            (self.stopped, stopped),
        ):
            if callable(callback):
                signal.connect(callback)
                connections.append((signal, callback))
        self._renderers[owner_id] = (weakref.ref(owner), connections)
        try:
            owner.destroyed.connect(lambda *_args, key=owner_id: self.detach_renderer(key))
        except Exception:
            pass

    def detach_renderer(self, owner_id: str) -> None:
        registration = self._renderers.pop(str(owner_id), None)
        if registration is None:
            return
        for signal, callback in registration[1]:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass

    def _poll_position(self) -> None:
        if self.active_entry is None:
            self._timer.stop()
            return
        try:
            position = int(self.audio_player.get_position())
        except Exception:
            position = -1
        if position < 0:
            self.stop()
            return
        self.positionChanged.emit(self.active_entry, position)
        self._emit_state()

    def _emit_state(self) -> None:
        playing = bool(getattr(self.audio_player, "is_playing", False))
        paused = bool(getattr(self.audio_player, "is_paused", False))
        self.playbackStateChanged.emit(self.active_entry, playing, paused)

    def _player_id(self, identity: ReservePreviewKey) -> int:
        if identity.sample_id is not None:
            return identity.sample_id
        key = os.path.normcase(identity.path)
        if key not in self._path_session_ids:
            self._path_session_ids[key] = self._next_session_id
            self._next_session_id -= 1
        return self._path_session_ids[key]

    def _effective_player_id(self, identity: ReservePreviewKey) -> int:
        if self.active_key is not None and self.active_key.matches(identity):
            current = getattr(self.audio_player, "current_sample_id", None)
            if current is not None and int(current) != -1:
                return int(current)
        return self._player_id(identity)

    @staticmethod
    def _can_play(entry) -> bool:
        path = normalize_audio_path(getattr(entry, "path", "") or "")
        return bool(entry and path and not getattr(entry, "missing", False) and os.path.isfile(path))

    @staticmethod
    def _duration(entry) -> float:
        duration = float(getattr(entry, "duration", 0.0) or 0.0)
        if duration > 0:
            return duration
        try:
            return float(get_audio_duration(getattr(entry, "path", "") or ""))
        except Exception:
            return 0.0


def ensure_reserve_preview(app_context) -> ReservePreviewController:
    controller = getattr(app_context, "reserve_preview", None)
    if controller is None:
        controller = ReservePreviewController(app_context.audio_player)
        app_context.reserve_preview = controller
    return controller
