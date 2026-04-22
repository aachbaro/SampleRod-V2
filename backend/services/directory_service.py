# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service backend pour la liste de fichiers du DirectoryWidget.
# - Gere l'import drag and drop, l'indexation recursive et la sync vers la DB.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import pickle
import shutil
import time
from dataclasses import dataclass

import numpy as np
import soundfile as sf
from PySide6.QtCore import QObject, QMimeData, QThread, Signal

from backend.db import SessionLocal
from backend.models.sample import Sample
from backend.services.audio_metadata import (
    audio_path_key,
    collect_audio_file_metadata,
    is_audio_file,
    normalize_audio_path,
)
from backend.services.sample_service import SampleService
import logging

logger = logging.getLogger("directory_service")


@dataclass(slots=True)
class DirectoryIndexSummary:
    folder: str
    total_audio_files: int
    added: int = 0
    updated: int = 0
    recovered: int = 0
    marked_missing: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        indexed = self.total_audio_files > 0 and self.errors == 0
        return {
            "folder": self.folder,
            "total_audio_files": int(self.total_audio_files),
            "added": int(self.added),
            "updated": int(self.updated),
            "recovered": int(self.recovered),
            "marked_missing": int(self.marked_missing),
            "errors": int(self.errors),
            "indexed": bool(indexed),
        }


@dataclass(slots=True)
class DirectoryAudioEntry:
    path: str
    name: str
    sample_id: int | None
    indexed: bool
    missing: bool
    needs_analysis: bool
    duration: float | None = None
    rms_level: float | None = None
    created_at: object | None = None

    @property
    def status_label(self) -> str:
        if self.missing:
            return "Fichier manquant"
        if not self.indexed:
            return "Non indexe"
        if self.needs_analysis:
            return "A analyser"
        return "Indexe"


class _DirectoryIndexWorker(QThread):
    progress = Signal(str, int, int, str)
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, folder: str):
        super().__init__()
        self.folder = normalize_audio_path(folder)

    def run(self):
        folder = self.folder
        if not os.path.isdir(folder):
            self.failed.emit(folder, "Dossier introuvable")
            return

        audio_paths = _scan_audio_paths(folder)
        total = len(audio_paths)
        summary = DirectoryIndexSummary(folder=folder, total_audio_files=total)
        self.progress.emit(folder, 0, total, "Preparation de l'indexation...")

        session = SessionLocal()
        try:
            tracked_samples = {
                audio_path_key(sample.path): sample
                for sample in session.query(Sample).all()
                if _is_path_in_folder(sample.path, folder)
            }

            seen_keys = set()
            for current, path in enumerate(audio_paths, start=1):
                label = os.path.basename(path)
                self.progress.emit(folder, current - 1, total, f"Analyse de {label}")
                try:
                    metadata = collect_audio_file_metadata(path, include_rms=True)
                except Exception as exc:
                    summary.errors += 1
                    logger.info("[DirectoryService] metadata error for %s: %s", path, exc)
                    self.progress.emit(folder, current, total, f"Ignore: {label}")
                    continue

                key = audio_path_key(metadata.path)
                seen_keys.add(key)
                existing = tracked_samples.get(key)
                if existing is None:
                    Sample(
                        metadata.path,
                        duration=metadata.duration,
                        created_at=metadata.created_at,
                        rms_level=metadata.rms_level,
                        missing=False,
                        analyzed_at=None,
                    )
                    summary.added += 1
                    self.progress.emit(folder, current, total, f"Ajout: {label}")
                    continue

                changed = False
                if existing.path != metadata.path:
                    existing.path = metadata.path
                    changed = True
                if existing.name != metadata.name:
                    existing.name = metadata.name
                    changed = True
                if abs(float(existing.duration or 0.0) - float(metadata.duration)) > 0.01:
                    existing.duration = float(metadata.duration)
                    changed = True
                if existing.created_at != metadata.created_at:
                    existing.created_at = metadata.created_at
                    changed = True
                if metadata.rms_level is not None:
                    existing_rms = float(existing.rms_level) if existing.rms_level is not None else None
                    if existing_rms is None or abs(existing_rms - float(metadata.rms_level)) > 1e-6:
                        existing.rms_level = float(metadata.rms_level)
                        changed = True
                if bool(existing.missing):
                    existing.missing = False
                    summary.recovered += 1
                    changed = True
                if changed:
                    session.commit()
                    summary.updated += 1
                self.progress.emit(folder, current, total, f"Synchronise: {label}")

            for key, sample in tracked_samples.items():
                if key in seen_keys or bool(sample.missing):
                    continue
                sample.missing = True
                session.commit()
                summary.marked_missing += 1

            self.completed.emit(folder, summary.to_dict())
        except Exception as exc:
            session.rollback()
            logger.exception("[DirectoryService] index worker failed")
            self.failed.emit(folder, str(exc))
        finally:
            session.close()


class _DirectoryEntriesWorker(QThread):
    started = Signal(str, int, int)
    batchReady = Signal(str, int, object, int, int)
    completed = Signal(str, int, int)
    failed = Signal(str, int, str)

    def __init__(
        self,
        folder: str,
        request_id: int,
        sample_map: dict[str, Sample],
        *,
        batch_size: int = 12,
    ):
        super().__init__()
        self.folder = normalize_audio_path(folder)
        self.request_id = int(request_id)
        self.sample_map = dict(sample_map)
        self.batch_size = max(1, int(batch_size))
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        folder = self.folder
        request_id = self.request_id
        started_at = time.perf_counter()
        if not os.path.isdir(folder):
            self.failed.emit(folder, request_id, "Dossier introuvable")
            return

        try:
            filenames = _list_audio_filenames(folder)
            total = len(filenames)
            logger.info(
                "[DirectoryService] charge %s fichiers audio depuis %s (request=%s)",
                total,
                folder,
                request_id,
            )
            self.started.emit(folder, request_id, total)

            batch: list[DirectoryAudioEntry] = []
            for index, filename in enumerate(filenames, start=1):
                if self._cancelled:
                    logger.info(
                        "[DirectoryService] chargement annule pour %s (request=%s)",
                        folder,
                        request_id,
                    )
                    return
                path = normalize_audio_path(os.path.join(folder, filename))
                sample = self.sample_map.get(audio_path_key(path))
                batch.append(_build_directory_audio_entry(path, sample))
                if len(batch) >= self.batch_size:
                    self.batchReady.emit(folder, request_id, list(batch), index, total)
                    batch.clear()
                    self.msleep(1)

            if batch:
                self.batchReady.emit(folder, request_id, list(batch), total, total)

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "[DirectoryService] chargement liste termine pour %s en %sms (request=%s)",
                folder,
                elapsed_ms,
                request_id,
            )
            self.completed.emit(folder, request_id, total)
        except Exception as exc:
            logger.exception("[DirectoryService] entries worker failed")
            self.failed.emit(folder, request_id, str(exc))


class _DirectoryStatusWorker(QThread):
    completed = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(self, folder: str, request_id: int):
        super().__init__()
        self.folder = normalize_audio_path(folder)
        self.request_id = int(request_id)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        folder = self.folder
        request_id = self.request_id
        started_at = time.perf_counter()
        if not os.path.isdir(folder):
            self.failed.emit(folder, request_id, "Dossier introuvable")
            return
        try:
            status = _compute_folder_index_status(folder)
            if self._cancelled:
                return
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "[DirectoryService] statut dossier calcule pour %s en %sms (request=%s)",
                folder,
                elapsed_ms,
                request_id,
            )
            self.completed.emit(folder, request_id, status)
        except Exception as exc:
            logger.exception("[DirectoryService] status worker failed")
            self.failed.emit(folder, request_id, str(exc))


class DirectoryService(QObject):
    """Service utilitaire pour importer des fichiers et indexer un dossier."""

    indexStarted = Signal(str)
    indexProgress = Signal(str, int, int, str)
    indexFinished = Signal(str, object)
    indexFailed = Signal(str, str)

    def __init__(self, sample_service: SampleService):
        super().__init__()
        self.sample_store = sample_service
        self._index_worker: _DirectoryIndexWorker | None = None
        logger.info("[DirectoryService] Initialisation du service")

    def list_samples(self, folder: str) -> list[str]:
        folder = normalize_audio_path(folder)
        if not os.path.isdir(folder):
            logger.info("[DirectoryService] Dossier introuvable: %s", folder)
            return []
        files = sorted(
            filename
            for filename in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, filename))
            and is_audio_file(filename)
        )
        logger.info("[DirectoryService] %s fichiers audio listes dans %s", len(files), folder)
        return files

    def list_audio_entries(self, folder: str) -> list[DirectoryAudioEntry]:
        folder = normalize_audio_path(folder)
        sample_map = self._cached_samples_by_path()
        entries: list[DirectoryAudioEntry] = []
        for filename in self.list_samples(folder):
            path = normalize_audio_path(os.path.join(folder, filename))
            sample = sample_map.get(audio_path_key(path))
            entries.append(self._build_audio_entry(path, sample))
        return entries

    def describe_audio_entry(self, path: str, *, probe_filesystem: bool = True) -> DirectoryAudioEntry:
        normalized_path = normalize_audio_path(path)
        sample = self._cached_samples_by_path().get(audio_path_key(normalized_path))
        if sample is not None:
            return self._build_audio_entry(normalized_path, sample)

        if not probe_filesystem:
            entry = self._build_audio_entry(normalized_path, None)
            try:
                entry.created_at = os.path.getctime(normalized_path)
            except Exception:
                entry.created_at = None
            return entry

        metadata = collect_audio_file_metadata(normalized_path, include_rms=True)
        return DirectoryAudioEntry(
            path=metadata.path,
            name=metadata.name,
            sample_id=None,
            indexed=False,
            missing=False,
            needs_analysis=False,
            duration=float(metadata.duration),
            rms_level=metadata.rms_level,
            created_at=metadata.created_at,
        )

    def start_index_directory(self, folder: str) -> bool:
        folder = normalize_audio_path(folder)
        if not os.path.isdir(folder):
            self.indexFailed.emit(folder, "Dossier introuvable")
            return False
        if self._index_worker is not None and self._index_worker.isRunning():
            logger.info("[DirectoryService] Une indexation est deja en cours")
            return False

        worker = _DirectoryIndexWorker(folder)
        worker.progress.connect(self.indexProgress)
        worker.completed.connect(self._on_index_completed)
        worker.failed.connect(self._on_index_failed)
        self._index_worker = worker
        self.indexStarted.emit(folder)
        worker.start()
        return True

    def is_indexing(self) -> bool:
        return self._index_worker is not None and self._index_worker.isRunning()

    def get_folder_index_status(self, folder: str) -> dict:
        folder = normalize_audio_path(folder)
        if not os.path.isdir(folder):
            return {
                "indexed": False,
                "label": "Non indexe",
                "tracked": 0,
                "on_disk": 0,
                "missing": 0,
            }

        disk_paths = _scan_audio_paths(folder)
        disk_map = {audio_path_key(path): path for path in disk_paths}

        with SessionLocal() as session:
            tracked = [
                sample
                for sample in session.query(Sample).all()
                if _is_path_in_folder(sample.path, folder)
            ]

        tracked_map = {audio_path_key(sample.path): sample for sample in tracked}
        missing_count = sum(1 for sample in tracked if bool(sample.missing))
        unindexed_on_disk = sum(
            1
            for key in disk_map
            if key not in tracked_map or bool(tracked_map[key].missing)
        )
        stale_present = sum(
            1
            for sample in tracked
            if not bool(sample.missing) and audio_path_key(sample.path) not in disk_map
        )

        indexed = (
            (len(disk_map) > 0 or len(tracked) > 0)
            and unindexed_on_disk == 0
            and stale_present == 0
        )
        return {
            "indexed": bool(indexed),
            "label": "Indexe" if indexed else "Non indexe",
            "tracked": len(tracked),
            "on_disk": len(disk_map),
            "missing": int(missing_count),
        }

    def handle_drop(self, folder: str, mime: QMimeData) -> None:
        logger.info("[DirectoryService] Depot dans %s", folder)
        os.makedirs(folder, exist_ok=True)

        if mime.hasUrls():
            copied = 0
            for url in mime.urls():
                src = normalize_audio_path(url.toLocalFile())
                if not src or not is_audio_file(src):
                    continue
                if not os.path.isfile(src):
                    continue
                dst = os.path.join(folder, os.path.basename(src))
                base, ext = os.path.splitext(dst)
                index = 1
                while os.path.exists(dst):
                    dst = f"{base}_{index}{ext}"
                    index += 1
                try:
                    shutil.copy2(src, dst)
                    self.sample_store.add(dst)
                    copied += 1
                    logger.info("[DirectoryService] Fichier copie %s -> %s", src, dst)
                except Exception as exc:
                    logger.info("[DirectoryService] drop url copy error: %s", exc)
            if copied:
                return

        for fmt in ("application/x-sample-slice-data", "application/x-sample-card"):
            if not mime.hasFormat(fmt):
                continue

            try:
                payload = pickle.loads(bytes(mime.data(fmt)))
            except Exception:
                payload = None

            if isinstance(payload, dict):
                if "audio_data" in payload:
                    logger.info("[DirectoryService] Sauvegarde d'une slice depuis le drag and drop")
                    self._save_slice(folder, payload)
                elif "sample_id" in payload:
                    logger.info("[DirectoryService] Copie d'un sample depuis le drag and drop")
                    self._copy_sample(folder, payload["sample_id"])
                return

            data = bytes(mime.data(fmt)).decode(errors="ignore")
            for line in filter(None, data.splitlines()):
                src = line.strip()
                if os.path.isfile(src):
                    dst = os.path.join(folder, os.path.basename(src))
                    try:
                        shutil.copy(src, dst)
                        self.sample_store.add(dst)
                        logger.info("[DirectoryService] Fichier copie %s -> %s", src, dst)
                    except Exception as exc:
                        logger.info("[DirectoryService] drop copy error: %s", exc)

    def _on_index_completed(self, folder: str, summary: object):
        self.sample_store.load_all()
        self.indexFinished.emit(folder, summary)
        self._clear_worker()

    def _on_index_failed(self, folder: str, message: str):
        self.indexFailed.emit(folder, message)
        self._clear_worker()

    def _clear_worker(self):
        if self._index_worker is not None:
            self._index_worker.deleteLater()
        self._index_worker = None

    def _save_slice(self, folder: str, payload: dict):
        arr = np.asarray(payload.get("audio_data"), dtype="float32")
        sample_rate = int(payload.get("sample_rate", 44100))
        name = payload.get("name", "slice")
        if not name.lower().endswith(".wav"):
            name += ".wav"
        dest = os.path.join(folder, name)

        base, ext = os.path.splitext(dest)
        index = 1
        while os.path.exists(dest):
            dest = f"{base}_{index}{ext}"
            index += 1

        try:
            sf.write(dest, arr, sample_rate)
            self.sample_store.add(dest)
            logger.info("[DirectoryService] Slice enregistree: %s", dest)
        except Exception as exc:
            logger.info("[DirectoryService] save slice error: %s", exc)

    def _copy_sample(self, folder: str, sample_id: int):
        sample = self.sample_store._get(sample_id)
        if not sample:
            return
        src = sample.path
        dest = os.path.join(folder, os.path.basename(src))

        base, ext = os.path.splitext(dest)
        index = 1
        while os.path.exists(dest):
            dest = f"{base}_{index}{ext}"
            index += 1

        try:
            shutil.copy(src, dest)
            self.sample_store.add(dest)
            logger.info("[DirectoryService] Sample copie: %s -> %s", src, dest)
        except Exception as exc:
            logger.info("[DirectoryService] copy sample error: %s", exc)

    def _cached_samples_by_path(self) -> dict[str, Sample]:
        getter = getattr(self.sample_store, "get_cached", None)
        if getter is None:
            return {}
        try:
            samples = getter()
        except Exception:
            return {}
        return {
            audio_path_key(sample.path): sample
            for sample in samples
            if getattr(sample, "path", None)
        }

    @staticmethod
    def _build_audio_entry(path: str, sample: Sample | None) -> DirectoryAudioEntry:
        if sample is None:
            return DirectoryAudioEntry(
                path=path,
                name=os.path.splitext(os.path.basename(path))[0],
                sample_id=None,
                indexed=False,
                missing=False,
                needs_analysis=False,
            )

        return DirectoryAudioEntry(
            path=normalize_audio_path(sample.path),
            name=str(getattr(sample, "name", os.path.splitext(os.path.basename(path))[0])),
            sample_id=int(getattr(sample, "id", 0)) if getattr(sample, "id", None) is not None else None,
            indexed=True,
            missing=bool(getattr(sample, "missing", False)) and not os.path.isfile(path),
            needs_analysis=bool(getattr(sample, "needs_analysis", False)),
            duration=float(getattr(sample, "duration", 0.0) or 0.0),
            rms_level=(
                float(getattr(sample, "rms_level", 0.0))
                if getattr(sample, "rms_level", None) is not None
                else None
            ),
            created_at=getattr(sample, "created_at", None),
        )


def _scan_audio_paths(folder: str) -> list[str]:
    found = []
    for root, _dirs, files in os.walk(folder):
        for filename in files:
            if not is_audio_file(filename):
                continue
            found.append(normalize_audio_path(os.path.join(root, filename)))
    return sorted(found)


def _is_path_in_folder(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([normalize_audio_path(path), folder]) == folder
    except ValueError:
        return False
