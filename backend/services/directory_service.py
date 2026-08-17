# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service du navigateur de dossiers (onglet "Directory" du panneau droit).
#   Il repond a trois questions :
#   1. "Que contient ce dossier ?"  -> liste des fichiers audio presents ;
#   2. "Ce dossier est-il indexe ?" -> comparaison disque <-> base de donnees ;
#   3. "Que faire de ce depot ?"    -> import par glisser-deposer (fichiers,
#      slices decoupees, cartes de samples).
# - "Indexer" un dossier = enregistrer dans la base tous ses fichiers audio
#   (recursivement), pour qu'ils deviennent de vrais samples avec analyse.
# - Les operations longues tournent dans des QThread dedies pour ne jamais
#   geler l'interface ; elles previennent l'UI par signaux Qt.
#
# CLASSES ET FONCTIONS (sommaire)
# - DirectoryIndexSummary   : bilan d'une indexation (ajouts, maj, erreurs...).
# - DirectoryAudioEntry     : fiche d'un fichier audio pour l'affichage
#   (indexe ?, manquant ?, duree, note, gamme...) + status_label lisible.
# - _DirectoryIndexWorker   (QThread) : indexe un dossier complet en arriere-plan.
# - _DirectoryEntriesWorker (QThread) : construit la liste des fichiers par
#   petits paquets (batches) pour un affichage progressif.
#   /!\ ATTENTION : classe actuellement NON UTILISEE et NON FONCTIONNELLE
#   (elle appelle des fonctions qui n'existent plus). Conservee en attendant
#   decision (reprendre ou supprimer).
# - _DirectoryStatusWorker  (QThread) : calcule le statut indexe/non indexe.
#   /!\ Meme remarque : NON UTILISEE et NON FONCTIONNELLE.
# - DirectoryService (QObject) : la facade utilisee par l'interface
#   - list_samples()            : noms des fichiers audio d'un dossier.
#   - list_audio_entries()      : fiches completes de ces fichiers.
#   - describe_audio_entry()    : fiche d'un seul fichier.
#   - start_index_directory()   : lance l'indexation en arriere-plan.
#   - is_indexing()             : une indexation est-elle en cours ?
#   - get_folder_index_status() : statut detaille disque vs base.
#   - handle_drop()             : traite un glisser-deposer dans le dossier.
#   - _build_audio_entry()      : fabrique une fiche depuis un Sample.
# - _scan_audio_paths()         : tous les fichiers audio d'un dossier (recursif).
# - _parse_compatible_scales()  : decode la liste JSON des gammes compatibles.
# - _is_path_in_folder()        : ce chemin est-il dans ce dossier ?
#
# LIENS CLES
# - frontend/right_panel/directory/  : les widgets qui consomment ce service.
# - backend/services/sample_service.py : ajout des samples importes.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

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
from backend.services.reserve_import_service import ReserveImportService
import logging

logger = logging.getLogger("directory_service")


@dataclass(slots=True)
class DirectoryIndexSummary:
    """Bilan chiffre d'une indexation, affiche a l'utilisateur a la fin.

    added = nouveaux samples crees ; updated = fiches corrigees ;
    recovered = samples "manquants" retrouves ; marked_missing = samples
    dont le fichier a disparu ; errors = fichiers illisibles ignores.
    """

    folder: str
    total_audio_files: int
    added: int = 0
    updated: int = 0
    recovered: int = 0
    marked_missing: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        """Version dictionnaire du bilan (transmise par signal a l'UI)."""
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
    """Fiche d'un fichier audio telle que l'affiche le navigateur de dossiers.

    Rassemble ce qu'on sait du fichier : est-il deja indexe en base
    (sample_id renseigne) ? le fichier existe-t-il encore (missing) ?
    attend-il une analyse musicale ? plus les infos d'analyse si disponibles
    (note dominante, gamme detectee, gammes compatibles...).
    """

    path: str
    name: str
    sample_id: int | None
    indexed: bool
    missing: bool
    needs_analysis: bool
    duration: float | None = None
    rms_level: float | None = None
    created_at: object | None = None
    dominant_note: str | None = None
    detected_scale_label: str | None = None
    detected_scale_kind: str | None = None
    scale_confidence: float | None = None
    compatible_scales: tuple[str, ...] = ()

    @property
    def status_label(self) -> str:
        """Etiquette lisible de l'etat du fichier, par ordre de priorite."""
        if self.missing:
            return "Fichier manquant"
        if not self.indexed:
            return "Non indexe"
        if self.needs_analysis:
            return "A analyser"
        return "Indexe"


class _DirectoryIndexWorker(QThread):
    """Indexe un dossier complet en arriere-plan (thread separe).

    Pour chaque fichier audio du dossier (sous-dossiers compris), met la base
    de donnees en accord avec le disque : creation des samples inconnus,
    correction des fiches obsoletes, marquage des fichiers disparus.
    Emet `progress` regulierement pour la barre de progression de l'UI.
    """

    progress = Signal(str, int, int, str)
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, folder: str):
        super().__init__()
        self.folder = normalize_audio_path(folder)

    def run(self):
        """Corps de l'indexation, execute dans le thread secondaire."""
        folder = self.folder
        if not os.path.isdir(folder):
            self.failed.emit(folder, "Dossier introuvable")
            return

        # Inventaire complet du disque (recursif).
        audio_paths = _scan_audio_paths(folder)
        total = len(audio_paths)
        summary = DirectoryIndexSummary(folder=folder, total_audio_files=total)
        self.progress.emit(folder, 0, total, "Preparation de l'indexation...")

        session = SessionLocal()
        try:
            # Inventaire de la base : tous les samples deja connus qui
            # habitent dans ce dossier, ranges par chemin pour un acces direct.
            tracked_samples = {
                audio_path_key(sample.path): sample
                for sample in session.query(Sample).all()
                if _is_path_in_folder(sample.path, folder)
            }

            # On confronte chaque fichier du disque a la base.
            seen_keys = set()
            for current, path in enumerate(audio_paths, start=1):
                label = os.path.basename(path)
                self.progress.emit(folder, current - 1, total, f"Analyse de {label}")
                try:
                    metadata = collect_audio_file_metadata(path, include_rms=True)
                except Exception as exc:
                    # Fichier illisible : compte comme erreur, on continue.
                    summary.errors += 1
                    logger.info("[DirectoryService] metadata error for %s: %s", path, exc)
                    self.progress.emit(folder, current, total, f"Ignore: {label}")
                    continue

                key = audio_path_key(metadata.path)
                seen_keys.add(key)
                existing = tracked_samples.get(key)
                if existing is None:
                    # Fichier inconnu de la base -> creation d'un nouveau sample.
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

                # Fichier deja connu -> on compare champ par champ et on ne
                # reecrit en base que si quelque chose a vraiment change.
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
                    # Le fichier etait marque disparu mais on vient de le lire :
                    # il est de retour.
                    existing.missing = False
                    summary.recovered += 1
                    changed = True
                if changed:
                    session.commit()
                    summary.updated += 1
                self.progress.emit(folder, current, total, f"Synchronise: {label}")

            # Dernier passage : les samples connus en base qu'on n'a PAS
            # croises sur le disque ont disparu -> marques "missing".
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
    """Construit la liste des fichiers d'un dossier par petits paquets.

    ATTENTION — CODE MORT : cette classe n'est instanciee nulle part et
    appelle des fonctions qui n'existent plus (_list_audio_filenames,
    _build_directory_audio_entry) — elle planterait si on l'utilisait.
    Conservee a titre de reference en attendant d'etre reprise ou supprimee.

    Idee d'origine : plutot que de faire attendre l'utilisateur que TOUTE la
    liste soit prete, envoyer les fiches par lots (batchReady) pour que
    l'interface affiche les premieres lignes immediatement. Le request_id
    permet a l'UI d'ignorer les resultats d'une demande perimee.
    """

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
    """Calcule le statut indexe/non indexe d'un dossier en arriere-plan.

    ATTENTION — CODE MORT : non instanciee, et appelle
    _compute_folder_index_status qui n'existe plus. La version vivante de ce
    calcul est la methode DirectoryService.get_folder_index_status() plus bas.
    """

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
    """Facade du navigateur de dossiers : lister, indexer, importer.

    C'est cette classe que l'interface utilise. Les signaux index* informent
    l'UI de l'avancement de l'indexation lancee en arriere-plan.
    """

    indexStarted = Signal(str)
    indexProgress = Signal(str, int, int, str)
    indexFinished = Signal(str, object)
    indexFailed = Signal(str, str)

    def __init__(self, sample_service: SampleService):
        super().__init__()
        self.sample_store = sample_service
        context = getattr(sample_service, "app_context", None)
        self.import_service = getattr(context, "reserve_imports", None)
        if self.import_service is None:
            self.import_service = ReserveImportService(sample_service)
        self._index_worker: _DirectoryIndexWorker | None = None
        logger.info("[DirectoryService] Initialisation du service")

    def list_samples(self, folder: str) -> list[str]:
        """Noms des fichiers audio directement dans `folder` (non recursif), tries."""
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
        """Fiches completes des fichiers audio d'un dossier.

        Croise la liste du disque avec le cache des samples connus : un
        fichier present en base recupere ses infos (duree, analyse...),
        un fichier inconnu donne une fiche minimale "non indexe".
        """
        folder = normalize_audio_path(folder)
        sample_map = self._cached_samples_by_path()
        entries: list[DirectoryAudioEntry] = []
        for filename in self.list_samples(folder):
            path = normalize_audio_path(os.path.join(folder, filename))
            sample = sample_map.get(audio_path_key(path))
            entries.append(self._build_audio_entry(path, sample))
        return entries

    def describe_audio_entry(self, path: str, *, probe_filesystem: bool = True) -> DirectoryAudioEntry:
        """Fiche d'UN fichier audio donne.

        Si le fichier est connu en base, on repond depuis le cache (rapide).
        Sinon, deux options : probe_filesystem=True lit le fichier pour en
        extraire duree/volume (plus lent mais complet) ; False se contente
        de la date du fichier (rapide, pour de longues listes).
        """
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
        """Lance l'indexation d'un dossier en arriere-plan.

        Refuse si le dossier n'existe pas ou si une indexation tourne deja
        (une seule a la fois). Le worker previent ensuite l'UI via les
        signaux indexProgress / indexFinished / indexFailed.
        """
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
        """Vrai si une indexation est en cours."""
        return self._index_worker is not None and self._index_worker.isRunning()

    def get_folder_index_status(self, folder: str) -> dict:
        """Compare disque et base pour dire si un dossier est "indexe".

        Un dossier est considere indexe quand :
        - chaque fichier audio du disque a sa fiche en base (et non "missing"),
        - aucune fiche en base ne pointe vers un fichier disparu.
        Renvoie aussi les compteurs (suivis, sur disque, manquants) pour
        l'affichage du detail dans l'UI.
        """
        folder = normalize_audio_path(folder)
        if not os.path.isdir(folder):
            return {
                "indexed": False,
                "label": "Non indexe",
                "tracked": 0,
                "on_disk": 0,
                "missing": 0,
            }

        # Inventaire des deux cotes : fichiers reellement sur le disque,
        # et samples enregistres en base pour ce dossier.
        disk_paths = _scan_audio_paths(folder)
        disk_map = {audio_path_key(path): path for path in disk_paths}

        with SessionLocal() as session:
            tracked = [
                sample
                for sample in session.query(Sample).all()
                if _is_path_in_folder(sample.path, folder)
            ]

        tracked_map = {audio_path_key(sample.path): sample for sample in tracked}
        # Trois compteurs de desaccord disque/base :
        # - missing_count    : fiches marquees "fichier disparu" ;
        # - unindexed_on_disk: fichiers du disque sans fiche valable en base ;
        # - stale_present    : fiches censees etre la mais fichier introuvable.
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
        """Adaptateur historique : décode le MIME puis délègue au service unique."""
        from frontend.reserve.reserve_import_adapters import import_request_from_mime

        def sample_path(sample_id: int):
            sample = self.sample_store._get(sample_id)
            return getattr(sample, "path", None) if sample is not None else None

        artifact_store = getattr(self.sample_store.app_context, "lab_artifact_store", None)
        artifact_resolver = getattr(artifact_store, "resolve_path", None)
        request = import_request_from_mime(
            mime,
            sample_path_lookup=sample_path,
            artifact_path_lookup=artifact_resolver if callable(artifact_resolver) else None,
            destination=folder,
        )
        return self.import_service.import_request(request)

    def _on_index_completed(self, folder: str, summary: object):
        """Fin d'indexation : recharge le cache des samples et previent l'UI."""
        self.sample_store.load_all()
        self.indexFinished.emit(folder, summary)
        self._clear_worker()

    def _on_index_failed(self, folder: str, message: str):
        """Echec d'indexation : transmet l'erreur a l'UI et nettoie le worker."""
        self.indexFailed.emit(folder, message)
        self._clear_worker()

    def _clear_worker(self):
        """Libere le worker d'indexation termine (deleteLater = nettoyage Qt)."""
        if self._index_worker is not None:
            self._index_worker.deleteLater()
        self._index_worker = None

    def _cached_samples_by_path(self) -> dict[str, Sample]:
        """Index {chemin -> Sample} construit depuis le cache du SampleService.

        Permet de retrouver instantanement si un fichier du disque
        correspond a un sample connu, sans requete en base.
        """
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
        """Fabrique la fiche d'affichage d'un fichier.

        Sans sample en base : fiche minimale "non indexe". Avec sample :
        fiche complete (duree, volume, note, gamme...). Les getattr avec
        valeur par defaut rendent la fonction tolerante aux fiches
        incompletes (anciennes versions de la base).
        """
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
            dominant_note=str(getattr(sample, "dominant_note", "") or "").strip() or None,
            detected_scale_label=(
                str(getattr(sample, "detected_scale_label", "") or "").strip() or None
            ),
            detected_scale_kind=(
                str(getattr(sample, "detected_scale_kind", "") or "").strip() or None
            ),
            scale_confidence=(
                float(getattr(sample, "scale_confidence", 0.0))
                if getattr(sample, "scale_confidence", None) is not None
                else None
            ),
            compatible_scales=_parse_compatible_scales(
                getattr(sample, "compatible_scales", None)
            ),
        )


def _scan_audio_paths(folder: str) -> list[str]:
    """Tous les fichiers audio d'un dossier, sous-dossiers compris, tries."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for filename in files:
            if not is_audio_file(filename):
                continue
            found.append(normalize_audio_path(os.path.join(root, filename)))
    return sorted(found)


def _parse_compatible_scales(raw_value) -> tuple[str, ...]:
    """Decode la colonne "gammes compatibles" vers un tuple de textes propres.

    En base, cette information est stockee en JSON (ex: '["Do majeur",
    "La mineur"]'). La fonction accepte aussi une liste deja decodee ou un
    simple texte, et ignore silencieusement les valeurs vides ou invalides.
    """
    if raw_value is None:
        return ()
    if isinstance(raw_value, (list, tuple, set)):
        return tuple(
            text
            for text in (str(value or "").strip() for value in raw_value)
            if text
        )
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return (text,)
        return tuple(
            value
            for value in (str(item or "").strip() for item in parsed if item is not None)
            if value
        )
    return ()


def _is_path_in_folder(path: str, folder: str) -> bool:
    """Vrai si `path` se trouve dans `folder` (ou un de ses sous-dossiers).

    ValueError peut survenir quand les chemins sont sur des disques
    differents (C: vs D:) : dans ce cas la reponse est forcement non.
    """
    try:
        return os.path.commonpath([normalize_audio_path(path), folder]) == folder
    except ValueError:
        return False
