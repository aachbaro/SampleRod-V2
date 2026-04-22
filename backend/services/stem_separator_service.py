from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from types import ModuleType

from PySide6.QtCore import QObject, Signal

from backend.services.audio_metadata import is_audio_file, normalize_audio_path

logger = logging.getLogger("stem_separator_service")

_MODULE_CACHE: ModuleType | None = None


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _stem_separator_root() -> Path:
    return _workspace_root() / "stem-separator"


def _stem_separator_src() -> Path:
    return _stem_separator_root() / "src"


def _stem_separator_module() -> ModuleType:
    global _MODULE_CACHE
    if _MODULE_CACHE is not None:
        return _MODULE_CACHE

    module_path = _stem_separator_src() / "separator.py"
    if not module_path.is_file():
        raise FileNotFoundError(f"separator.py introuvable: {module_path}")

    spec = importlib.util.spec_from_file_location(
        "samplerod_external_stem_separator",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de charger le module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE = module
    return module


def resolve_stem_separator_python() -> str:
    candidate = _stem_separator_root() / "venv" / "Scripts" / "python.exe"
    if candidate.is_file():
        return str(candidate)
    return sys.executable


class StemSeparatorService(QObject):
    initialized = Signal(bool, str)
    statusChanged = Signal(str)
    fileStarted = Signal(str)
    fileFinished = Signal(str, str)
    fileFailed = Signal(str, str)
    queueIdle = Signal()

    def __init__(self, app_context) -> None:
        super().__init__()
        self.app_context = app_context
        self._module: ModuleType | None = None
        self._module_error = ""
        self._thread = None
        self._worker = None
        self._output_dir = ""
        self._model_name = "htdemucs"
        self._python_executable = resolve_stem_separator_python()
        self.available_models = ["htdemucs"]
        self._load_metadata()

    @property
    def output_dir(self) -> str:
        return self._output_dir

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_available(self) -> bool:
        return self._module is not None

    def availability_error(self) -> str:
        return self._module_error

    def set_output_dir(self, path: str) -> None:
        normalized = normalize_audio_path(path) if path else ""
        if normalized:
            os.makedirs(normalized, exist_ok=True)
        self._output_dir = normalized
        if self._worker is not None:
            self._worker.set_output_dir(normalized)

    def set_model(self, name: str) -> None:
        if not name:
            return
        self._model_name = str(name)
        if self._worker is not None:
            self._worker.set_model(self._model_name)

    def enqueue_paths(self, paths: list[str]) -> int:
        normalized_paths: list[str] = []
        seen: set[str] = set()
        for path in paths or []:
            normalized = normalize_audio_path(path)
            if (
                not normalized
                or normalized in seen
                or not os.path.isfile(normalized)
                or not is_audio_file(normalized)
            ):
                continue
            seen.add(normalized)
            normalized_paths.append(normalized)

        if not normalized_paths:
            return 0
        if not self._output_dir:
            self.statusChanged.emit("Choisis un dossier de travail pour les stems.")
            return 0
        if not self.ensure_started():
            if self._module_error:
                self.statusChanged.emit(self._module_error)
            return 0

        assert self._worker is not None
        for path in normalized_paths:
            self._worker.add_file(path, force_overwrite=True)
        self.statusChanged.emit(
            f"{len(normalized_paths)} fichier{'s' if len(normalized_paths) != 1 else ''} ajoute(s) a la separation."
        )
        return len(normalized_paths)

    def cancel_current(self) -> None:
        if self._worker is not None:
            self._worker.cancel_current()

    def ensure_started(self) -> bool:
        if self._thread is not None and self._thread.isRunning():
            return True
        if self._module is None:
            return False

        try:
            worker_cls = getattr(self._module, "SeparatorWorker")
            make_thread = getattr(self._module, "make_thread")
            self._worker = worker_cls(
                self._output_dir,
                self._model_name,
                python_executable=self._python_executable,
            )
            self._connect_worker()
            self._thread = make_thread(self._worker)
            self._thread.finished.connect(self._on_thread_finished)
            self.statusChanged.emit("Verification de Demucs...")
            self._thread.start()
            return True
        except Exception as exc:
            logger.exception("[StemSeparatorService] impossible de demarrer le worker")
            self._module_error = str(exc)
            self._worker = None
            self._thread = None
            self.initialized.emit(False, self._module_error)
            self.statusChanged.emit(f"Stem separation indisponible: {exc}")
            return False

    def shutdown(self) -> None:
        worker = self._worker
        thread = self._thread
        self._worker = None
        self._thread = None
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                logger.exception("[StemSeparatorService] stop worker impossible")
        if thread is not None:
            try:
                thread.quit()
                if not thread.wait(4000):
                    thread.terminate()
                    thread.wait(1000)
            except Exception:
                logger.exception("[StemSeparatorService] stop thread impossible")

    def _load_metadata(self) -> None:
        try:
            self._module = _stem_separator_module()
            self.available_models = list(getattr(self._module, "AVAILABLE_MODELS", self.available_models))
        except Exception as exc:
            logger.info("[StemSeparatorService] module externe indisponible: %s", exc)
            self._module = None
            self._module_error = f"Stem separator introuvable: {exc}"

    def _connect_worker(self) -> None:
        assert self._worker is not None
        self._worker.initialized.connect(self._on_worker_initialized)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.queue_idle.connect(self._on_queue_idle)
        self._worker.log.connect(self._on_worker_log)

    def _on_worker_initialized(self, ok: bool, message: str) -> None:
        self.initialized.emit(ok, message)
        self.statusChanged.emit(message if ok else f"Initialisation stem echouee: {message}")

    def _on_file_started(self, path: str) -> None:
        self.fileStarted.emit(path)
        self.statusChanged.emit(f"Separation en cours: {os.path.basename(path)}")

    def _on_file_finished(self, path: str, stem_dir: str) -> None:
        self.fileFinished.emit(path, stem_dir)
        self.statusChanged.emit(f"Stems prets: {os.path.basename(path)}")

    def _on_file_failed(self, path: str, message: str) -> None:
        self.fileFailed.emit(path, message)
        self.statusChanged.emit(f"Echec sur {os.path.basename(path)}")

    def _on_queue_idle(self) -> None:
        self.queueIdle.emit()

    def _on_worker_log(self, message: str) -> None:
        lowered = (message or "").lower()
        if "[erreur]" in lowered or "[echec]" in lowered:
            self.statusChanged.emit(message.strip())

    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None
