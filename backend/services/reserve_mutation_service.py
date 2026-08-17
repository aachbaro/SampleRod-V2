from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from backend.services.audio_metadata import normalize_audio_path


class ReserveMutationStatus(StrEnum):
    SUCCESS = "success"
    QUEUED = "queued"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ReserveMutationResult:
    operation: str
    status: ReserveMutationStatus
    sample_id: int | None = None
    old_path: str = ""
    new_path: str = ""
    message: str = ""

    @property
    def success(self) -> bool:
        return self.status in {
            ReserveMutationStatus.SUCCESS,
            ReserveMutationStatus.QUEUED,
        }


class ReserveMutationService:
    """Orchestre les mutations de la Réserve sans dépendre de l'interface."""

    def __init__(self, app_context):
        self.app_context = app_context
        self.sample_store = app_context.sample_store
        self.audio_player = app_context.audio_player

    def unindex(self, entry) -> ReserveMutationResult:
        sample_id = self._sample_id(entry)
        path = self._path(entry)
        if sample_id is None:
            return self._result("unindex", ReserveMutationStatus.NOT_APPLICABLE, entry)
        self._stop_preview(entry)
        ok = bool(self.sample_store.unindex(sample_id))
        return self._result(
            "unindex", ReserveMutationStatus.SUCCESS if ok else ReserveMutationStatus.ERROR, entry
        )

    def delete_file_and_record(self, entry) -> ReserveMutationResult:
        sample_id = self._sample_id(entry)
        path = self._path(entry)
        if sample_id is None and not path:
            return self._result("delete_file_and_record", ReserveMutationStatus.NOT_APPLICABLE, entry)
        self._stop_preview(entry)
        if sample_id is not None:
            ok = bool(self.sample_store.delete(sample_id))
        else:
            ok, _error = self.sample_store.delete_by_path(path, missing_ok=True)
        return self._result(
            "delete_file_and_record",
            ReserveMutationStatus.SUCCESS if ok else ReserveMutationStatus.ERROR,
            entry,
        )

    def rename(self, entry, new_name: str) -> ReserveMutationResult:
        sample_id = self._sample_id(entry)
        path = self._path(entry)
        clean_name = str(new_name or "").strip()
        if not clean_name or not path or not os.path.isfile(path):
            return self._result("rename", ReserveMutationStatus.NOT_APPLICABLE, entry)
        self._stop_preview(entry)
        if sample_id is not None:
            ok = bool(self.sample_store.rename(sample_id, clean_name))
        else:
            ok, _error = self.sample_store.rename_by_path(path, clean_name)
        extension = os.path.splitext(path)[1]
        new_path = normalize_audio_path(os.path.join(os.path.dirname(path), clean_name + extension))
        return self._result(
            "rename", ReserveMutationStatus.SUCCESS if ok else ReserveMutationStatus.ERROR,
            entry, new_path=new_path if ok else "",
        )

    def move(self, entry, target_folder: str) -> ReserveMutationResult:
        sample_id = self._sample_id(entry)
        path = self._path(entry)
        target = normalize_audio_path(target_folder)
        if not path or not target or not os.path.isfile(path):
            return self._result("move", ReserveMutationStatus.NOT_APPLICABLE, entry)
        self._stop_preview(entry)
        if sample_id is not None:
            ok = bool(self.sample_store.move(sample_id, target))
            status = ReserveMutationStatus.QUEUED if ok else ReserveMutationStatus.ERROR
        else:
            ok, _error = self.sample_store.move_by_path(path, target)
            status = ReserveMutationStatus.SUCCESS if ok else ReserveMutationStatus.ERROR
        new_path = normalize_audio_path(os.path.join(target, os.path.basename(path)))
        return self._result("move", status, entry, new_path=new_path if ok else "")

    def _stop_preview(self, entry) -> bool:
        controller = getattr(self.app_context, "reserve_preview", None)
        if controller is not None:
            return bool(controller.interrupt_for_mutation(entry))
        player = self.audio_player
        sample_id = self._sample_id(entry)
        path = self._path(entry)
        current_id = getattr(player, "current_sample_id", None)
        current_path = normalize_audio_path(getattr(player, "current_sample_path", "") or "")
        id_matches = sample_id is not None and current_id is not None and int(current_id) == sample_id
        path_matches = bool(path and current_path and current_path == path)
        if not (id_matches or path_matches):
            return False
        clear = getattr(player, "clear_audio", None) or getattr(player, "stop_playback", None)
        if callable(clear):
            clear()
        return True

    @staticmethod
    def _sample_id(entry) -> int | None:
        value = getattr(entry, "sample_id", None)
        return int(value) if value is not None else None

    @staticmethod
    def _path(entry) -> str:
        return normalize_audio_path(getattr(entry, "path", "") or "")

    def _result(self, operation, status, entry, *, new_path="", message=""):
        return ReserveMutationResult(
            operation=operation,
            status=status,
            sample_id=self._sample_id(entry),
            old_path=self._path(entry),
            new_path=new_path,
            message=message,
        )
