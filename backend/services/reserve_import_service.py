from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from backend.services.audio_metadata import audio_path_key, normalize_audio_path


class ReserveCopyPolicy(StrEnum):
    IN_PLACE = "in_place"
    COPY = "copy"


class ReserveReimportPolicy(StrEnum):
    SKIP = "skip"
    REINDEX = "reindex"


@dataclass(frozen=True, slots=True)
class ReserveImportRequest:
    paths: tuple[str, ...]
    status: str = "source"
    operation: str = "import"
    kind: str = "audio_file"
    provenance: dict[str, Any] | None = None
    destination: str | None = None
    copy_policy: ReserveCopyPolicy = ReserveCopyPolicy.IN_PLACE
    reimport_policy: ReserveReimportPolicy = ReserveReimportPolicy.SKIP


@dataclass(frozen=True, slots=True)
class ReserveImportResult:
    imported_samples: tuple[Any, ...] = ()
    copied_paths: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def success(self) -> bool:
        return bool(self.imported_samples) and not self.errors


class ReserveImportService:
    """Point de décision unique pour copie, indexation et promotion."""

    def __init__(self, sample_store):
        self.sample_store = sample_store

    def import_request(self, request: ReserveImportRequest) -> ReserveImportResult:
        imported, copied, skipped, errors = [], [], [], []
        seen: set[str] = set()
        for raw_path in request.paths:
            path = normalize_audio_path(raw_path)
            key = audio_path_key(path)
            if not path or key in seen:
                continue
            seen.add(key)
            if not os.path.isfile(path):
                errors.append((path, "Fichier introuvable"))
                continue
            try:
                if request.destination or request.copy_policy is ReserveCopyPolicy.COPY:
                    sample, copied_path = self.copy_into_directory(path, request)
                    if sample is not None:
                        imported.append(sample)
                        copied.append(copied_path)
                    else:
                        errors.append((path, "Copie ou indexation impossible"))
                elif request.status == "derived":
                    sample = self.import_derived_as_source(path, request)
                    if sample is not None:
                        imported.append(sample)
                        copied.append(normalize_audio_path(sample.path))
                    else:
                        errors.append((path, "Promotion impossible"))
                else:
                    sample, was_skipped = self.import_source(path, request)
                    if sample is not None:
                        imported.append(sample)
                    elif was_skipped:
                        skipped.append(path)
                    else:
                        errors.append((path, "Indexation impossible"))
            except Exception as exc:
                errors.append((path, str(exc)))
        return ReserveImportResult(tuple(imported), tuple(copied), tuple(skipped), tuple(errors))

    def import_source(self, path: str, request: ReserveImportRequest):
        existing = self._existing(path)
        if existing is not None:
            if request.reimport_policy is ReserveReimportPolicy.SKIP:
                return None, True
            if not self.sample_store.delete_record_by_path(path):
                return None, False
        metadata = self._source_metadata(request) if request.status == "artifact" else None
        return self.sample_store.add(path, material_metadata=metadata), False

    def import_derived_as_source(self, path: str, request: ReserveImportRequest):
        return self.sample_store.promote_to_source(path, self._source_metadata(request))

    def copy_into_directory(self, path: str, request: ReserveImportRequest):
        destination = normalize_audio_path(request.destination or "")
        if not destination:
            return None, ""
        os.makedirs(destination, exist_ok=True)
        target = self._unique_copy_path(destination, os.path.basename(path))
        shutil.copy2(path, target)
        metadata = (
            self._source_metadata(request)
            if request.status in {"derived", "artifact"}
            else None
        )
        sample = self.sample_store.add(target, material_metadata=metadata)
        if sample is None:
            try:
                os.remove(target)
            except OSError:
                pass
            return None, ""
        return sample, target

    def _existing(self, path: str):
        key = audio_path_key(path)
        return next(
            (sample for sample in self.sample_store.get_cached()
             if audio_path_key(getattr(sample, "path", "")) == key),
            None,
        )

    @staticmethod
    def _unique_copy_path(folder: str, filename: str) -> str:
        candidate = normalize_audio_path(os.path.join(folder, filename))
        base, extension = os.path.splitext(candidate)
        index = 1
        while os.path.exists(candidate):
            candidate = normalize_audio_path(f"{base}_{index}{extension}")
            index += 1
        return candidate

    @staticmethod
    def _source_metadata(request: ReserveImportRequest) -> dict[str, Any]:
        provenance = dict(request.provenance or {})
        lightweight = {
            "previous_status": request.status,
            "previous_kind": request.kind,
            "operation": "import",
            "source_path": str(provenance.get("source_path") or ""),
        }
        for key in ("start_seconds", "end_seconds"):
            if provenance.get(key) is not None:
                lightweight[key] = provenance[key]
        return {"material_status": "source", "provenance": lightweight}
