# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Pont vers l'outil EXTERNE de separation de stems (projet voisin
#   "stem-separator", base sur Demucs) : decouper un morceau en pistes
#   isolees (voix, batterie, basse, autres).
# - Le code de separation n'est PAS dans SampleRod : ce service charge
#   dynamiquement le fichier stem-separator/src/separator.py du projet
#   voisin et utilise, si possible, le Python de SON venv (Demucs et ses
#   dependances lourdes y sont installes).
# - Fonctionne en file d'attente : on ajoute des fichiers, un worker les
#   traite un par un, et les signaux tiennent l'UI informee.
#
# FONCTIONS ET CLASSE (sommaire)
# - _workspace_root() / _stem_separator_root() / _stem_separator_src() :
#   localisent le projet voisin par rapport a ce fichier.
# - _stem_separator_module()       : charge separator.py (une seule fois).
# - resolve_stem_separator_python(): trouve le python.exe du venv voisin,
#   sinon retombe sur celui de SampleRod.
# - mix_stem_files()               : somme plusieurs stems en un WAV (mix
#   d'un canal de routage, protection anti-clip).
# - StemSeparatorService (QObject)
#   - signaux : initialized, statusChanged, fileQueued/Started/Finished/
#     Failed, queueIdle.
#   - is_available()/availability_error() : l'outil est-il utilisable ?
#   - set_output_dir()/set_model() : reglages (dossier de sortie, modele IA).
#   - enqueue_paths()  : valide et ajoute des fichiers a la file.
#   - cancel_current() : annule le fichier en cours.
#   - ensure_started() : demarre le worker/thread a la demande.
#   - shutdown()       : arret propre (stop puis terminate si bloque).
#   - _load_metadata() : charge le module externe + liste des modeles.
#   - _connect_worker() + _on_* : relais des signaux du worker vers l'UI.
#
# LIENS CLES
# - ../stem-separator/src/separator.py  : l'outil externe charge ici.
# - frontend/labo/stem_separator_tool.py : l'interface dans l'onglet Labo.
# -----------------------------------------------------------------------------

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal

from PySide6.QtCore import QObject, Signal

from backend.services.audio_metadata import is_audio_file, normalize_audio_path

logger = logging.getLogger("stem_separator_service")

_MODULE_CACHE: ModuleType | None = None


@dataclass(frozen=True)
class StemQueueEntry:
    path: str
    state: Literal["processing", "queued"]


def _workspace_root() -> Path:
    """Dossier parent commun aux projets (3 niveaux au-dessus de ce fichier)."""
    return Path(__file__).resolve().parents[3]


def _stem_separator_root() -> Path:
    """Racine du projet voisin stem-separator."""
    return _workspace_root() / "stem-separator"


def _stem_separator_src() -> Path:
    """Dossier src/ du projet voisin."""
    return _stem_separator_root() / "src"


def _stem_separator_module() -> ModuleType:
    """Charge separator.py du projet voisin comme module Python.

    Le fichier n'est pas installe comme une bibliotheque classique : on le
    charge directement depuis son chemin (importlib). Le module est garde
    en cache pour ne le charger qu'une fois. Leve FileNotFoundError /
    ImportError si le projet voisin est absent ou casse.
    """
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
    """Python a utiliser pour la separation : celui du venv voisin si present.

    Demucs et ses dependances (PyTorch...) sont installes dans le venv du
    projet stem-separator, pas dans celui de SampleRod : on prefere donc
    son python.exe quand il existe.
    """
    candidate = _stem_separator_root() / "venv" / "Scripts" / "python.exe"
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def mix_stem_files(stem_paths: list[str], output_path: str) -> float:
    """Somme plusieurs stems en un seul WAV (mix d'un canal de routage).

    Les stems issus d'une meme separation partagent normalement le meme
    sample rate ; un mono est duplique en stereo si besoin, les longueurs
    sont alignees sur la plus longue, et le mix est ramene sous 0 dBFS si
    la somme depasse (protection anti-clip). Renvoie la duree en secondes.
    """
    import numpy as np
    import soundfile as sf

    buffers: list = []
    sample_rate = 0
    for path in stem_paths or []:
        data, sr = sf.read(path, always_2d=True, dtype="float32")
        if sample_rate == 0:
            sample_rate = int(sr)
        elif int(sr) != sample_rate:
            raise ValueError(f"sample rates differents entre stems ({sr} vs {sample_rate})")
        buffers.append(data)
    if not buffers or sample_rate <= 0:
        raise ValueError("aucun stem a mixer")

    length = max(len(buffer) for buffer in buffers)
    channels = max(buffer.shape[1] for buffer in buffers)
    mixed = np.zeros((length, channels), dtype=np.float32)
    for buffer in buffers:
        if buffer.shape[1] < channels:
            buffer = np.repeat(buffer, channels, axis=1)[:, :channels]
        mixed[: len(buffer)] += buffer

    peak = float(np.max(np.abs(mixed))) if length else 0.0
    if peak > 1.0:
        mixed /= peak
    sf.write(output_path, mixed, sample_rate)
    return float(length) / float(sample_rate)


class StemSeparatorService(QObject):
    initialized = Signal(bool, str)
    statusChanged = Signal(str)
    fileQueued = Signal(str)
    fileStarted = Signal(str)
    fileFinished = Signal(str, str)
    fileFailed = Signal(str, str)
    queueIdle = Signal()
    queueUpdated = Signal(object)

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
        self._pending_paths: list[str] = []
        self._current_path = ""
        self._load_metadata()

    @property
    def output_dir(self) -> str:
        return self._output_dir

    @property
    def model_name(self) -> str:
        return self._model_name

    def current_path(self) -> str:
        return self._current_path

    def queued_paths(self) -> list[str]:
        return list(self._pending_paths)

    def queue_entries(self) -> list[StemQueueEntry]:
        entries: list[StemQueueEntry] = []
        if self._current_path:
            entries.append(StemQueueEntry(path=self._current_path, state="processing"))
        entries.extend(
            StemQueueEntry(path=path, state="queued")
            for path in self._pending_paths
        )
        return entries

    def pending_count(self) -> int:
        return len(self._pending_paths)

    def is_available(self) -> bool:
        """Vrai si le module externe a pu etre charge."""
        return self._module is not None

    def availability_error(self) -> str:
        """Message expliquant pourquoi l'outil est indisponible (sinon vide)."""
        return self._module_error

    def set_output_dir(self, path: str) -> None:
        """Definit le dossier ou seront ecrits les stems (cree si besoin)."""
        normalized = normalize_audio_path(path) if path else ""
        if normalized:
            os.makedirs(normalized, exist_ok=True)
        self._output_dir = normalized
        if self._worker is not None:
            self._worker.set_output_dir(normalized)

    def set_model(self, name: str) -> None:
        """Choisit le modele IA de separation (htdemucs par defaut)."""
        if not name:
            return
        self._model_name = str(name)
        if self._worker is not None:
            self._worker.set_model(self._model_name)

    def remove_pending_path(self, path: str) -> bool:
        normalized = normalize_audio_path(path)
        if normalized not in self._pending_paths:
            return False
        self._pending_paths.remove(normalized)
        self._emit_queue_updated()
        self.statusChanged.emit(f"Retire de la file: {os.path.basename(normalized)}")
        return True

    def reorder_pending_paths(self, ordered_paths: list[str]) -> bool:
        normalized_order = [normalize_audio_path(path) for path in ordered_paths if path]
        if not normalized_order:
            return False
        current_set = set(self._pending_paths)
        if set(normalized_order) != current_set or len(normalized_order) != len(self._pending_paths):
            return False
        if normalized_order == self._pending_paths:
            return False
        self._pending_paths = normalized_order
        self._emit_queue_updated()
        return True

    def enqueue_paths(self, paths: list[str]) -> int:
        """Ajoute des fichiers a la file de separation.

        Filtre d'abord les chemins invalides (doublons, fichiers absents,
        formats non audio), verifie qu'un dossier de sortie est choisi et
        que le worker demarre, puis met chaque fichier en file. Renvoie le
        nombre de fichiers reellement ajoutes.
        """
        normalized_paths: list[str] = []
        seen: set[str] = set()
        for path in paths or []:
            normalized = normalize_audio_path(path)
            if (
                not normalized
                or normalized in seen
                or normalized == self._current_path
                or normalized in self._pending_paths
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

        for path in normalized_paths:
            self.fileQueued.emit(path)
            self._pending_paths.append(path)
        self._emit_queue_updated()
        self._dispatch_next_if_possible()
        self.statusChanged.emit(
            f"{len(normalized_paths)} fichier{'s' if len(normalized_paths) != 1 else ''} ajoute(s) a la separation."
        )
        return len(normalized_paths)

    def cancel_current(self) -> None:
        """Annule la separation du fichier en cours (la file continue)."""
        if self._worker is not None:
            self._worker.cancel_current()

    def ensure_started(self) -> bool:
        """Demarre le worker de separation s'il ne tourne pas deja.

        Le worker et son thread sont fournis par le module externe
        (SeparatorWorker + make_thread). Renvoie False si le module est
        indisponible ou si le demarrage echoue.
        """
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
        """Arrete le worker a la fermeture de l'application.

        D'abord poliment (stop + attente 4 s), puis de force (terminate)
        si la separation refuse de s'interrompre : l'application ne doit
        pas rester bloquee.
        """
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
        """Charge le module externe et la liste des modeles disponibles."""
        try:
            self._module = _stem_separator_module()
            self.available_models = list(getattr(self._module, "AVAILABLE_MODELS", self.available_models))
        except Exception as exc:
            logger.info("[StemSeparatorService] module externe indisponible: %s", exc)
            self._module = None
            self._module_error = f"Stem separator introuvable: {exc}"

    def _connect_worker(self) -> None:
        """Branche les signaux du worker externe sur nos relais _on_*."""
        assert self._worker is not None
        self._worker.initialized.connect(self._on_worker_initialized)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.queue_idle.connect(self._on_queue_idle)
        self._worker.log.connect(self._on_worker_log)

    def _emit_queue_updated(self) -> None:
        self.queueUpdated.emit(self.queue_entries())

    def _dispatch_next_if_possible(self) -> bool:
        if self._worker is None or self._current_path or not self._pending_paths:
            return False
        next_path = self._pending_paths.pop(0)
        self._current_path = next_path
        self._worker.add_file(next_path, force_overwrite=True)
        self._emit_queue_updated()
        return True

    def _on_worker_initialized(self, ok: bool, message: str) -> None:
        self.initialized.emit(ok, message)
        self.statusChanged.emit(message if ok else f"Initialisation stem echouee: {message}")
        if ok:
            self._dispatch_next_if_possible()

    def _on_file_started(self, path: str) -> None:
        self._current_path = normalize_audio_path(path)
        self._emit_queue_updated()
        self.fileStarted.emit(path)
        self.statusChanged.emit(f"Separation en cours: {os.path.basename(path)}")

    def _on_file_finished(self, path: str, stem_dir: str) -> None:
        self._current_path = ""
        self._emit_queue_updated()
        self.fileFinished.emit(path, stem_dir)
        self._dispatch_next_if_possible()
        self.statusChanged.emit(f"Stems prets: {os.path.basename(path)}")

    def _on_file_failed(self, path: str, message: str) -> None:
        self._current_path = ""
        self._emit_queue_updated()
        self.fileFailed.emit(path, message)
        self._dispatch_next_if_possible()
        self.statusChanged.emit(f"Echec sur {os.path.basename(path)}")

    def _on_queue_idle(self) -> None:
        if self._dispatch_next_if_possible():
            return
        if self._current_path:
            return
        self._emit_queue_updated()
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
        self._current_path = ""
        self._emit_queue_updated()
