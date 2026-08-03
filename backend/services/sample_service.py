# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - LE service central des samples : c'est lui que toute l'application appelle
#   pour ajouter, supprimer, renommer, deplacer ou retrouver un sample.
# - Il maintient un CACHE memoire (self._samples) : la liste complete des
#   samples, chargee une fois depuis la base. L'interface lit ce cache
#   (rapide) plutot que la base ; chaque modification met a jour le cache,
#   la base ET emet un signal Qt pour que tous les ecrans se rafraichissent.
# - Il orchestre aussi les traitements automatiques autour d'un sample :
#   * verification d'integrite au demarrage (IntegrityCheckWorker) ;
#   * normalisation automatique du volume (NormalizeWorker) ;
#   * analyse musicale de la gamme en arriere-plan (ScaleAnalysisService) ;
#   * proposition de CONCATENATION : quand deux prises d'enregistrement
#     s'enchainent sans interruption, l'application propose de les coller
#     en un seul fichier (logique des "_concat_candidates" ci-dessous).
#
# LA LOGIQUE DE CONCATENATION EN BREF
# - Quand une prise demarre alors que le buffer retro n'a pas eu le temps de
#   se re-remplir depuis la prise precedente, les deux prises se suivent
#   probablement dans la realite -> la nouvelle est notee "candidate a la
#   concatenation" avec la precedente (_concat_candidates[nouvelle] = precedente).
# - Tant que la question n'est pas tranchee, la normalisation des deux
#   fichiers est BLOQUEE (_normalization_locked_ids) : il ne faut pas
#   modifier le volume de fichiers qu'on va peut-etre fusionner.
# - L'utilisateur choisit : concat_with_previous() colle les deux fichiers,
#   dismiss_concat() les laisse separes ; dans les deux cas on debloque et
#   on lance la normalisation.
#
# FONCTIONS (sommaire)
# - SampleService (QObject)
#   - signaux : sampleAdded, samplesChanged, sampleDeleted, sampleRenamed,
#     sampleMoved, sampleDurationChanged, sampleStarted/Finished/Failed-
#     Normalization, sampleRemovedFromHistory, sampleConcatCandidateChanged,
#     sampleNormalizationLockChanged, sampleScaleAnalyzed.
#   - _initialize_cache()/load_all() : (re)charge le cache depuis la base.
#   - get_cached()          : copie de la liste des samples (pour l'UI).
#   - add()                 : enregistre un nouveau fichier comme sample.
#   - delete()/delete_by_path()/bulkDelete() : suppressions (fichier + base).
#   - delete_record_by_path(): supprime la fiche en base SANS toucher au fichier.
#   - rename()/rename_by_path() : renommage (avec arret de la lecture si besoin).
#   - move()                : deplacement vers un autre dossier.
#   - updateDurationFromFile(): re-mesure la duree apres modification du fichier.
#   - mark_missing()        : marque un sample comme disparu/retrouve.
#   - removeFromHistory()   : retire de l'application sans supprimer le fichier.
#   - is_normalization_locked()/get_concat_previous_id() : etats pour l'UI.
#   - on_retro_refill_complete() : debloque la normalisation apres re-remplissage.
#   - concat_with_previous()/dismiss_concat() : decision de concatenation.
#   - _register_recorded_sample()/_lock_normalization()/_unlock_and_maybe_
#     normalize()/_is_concat_linked()/_cleanup_concat_state_for_deleted() :
#     mecanique interne de la concatenation.
#   - _start_auto_normalization() : lance un NormalizeWorker si l'option est active.
#   - _on_scale_analysis_complete()/_on_scale_analysis_failed() : retours d'analyse.
#   - batch_analyze_missing()/batch_analyze_folder()/_batch_analyze_candidates():
#     analyse de gamme en masse.
#   - shutdown()            : arrete les services de fond.
#   - _append_wav_files()   : colle physiquement deux WAV en un troisieme.
#
# LIENS CLES
# - backend/models/sample.py : les operations fichier/base unitaires.
# - backend/models/normalize_worker.py / integrity_worker.py : les workers.
# - backend/services/scale_analysis_service.py : analyse musicale.
# - frontend/sample_gui/ : les ecrans qui ecoutent les signaux de ce service.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import shutil
from time import perf_counter

import soundfile as sf
from PySide6.QtCore import QObject, QThread, Signal, Slot
from sqlalchemy.exc import SQLAlchemyError

from backend.db import SessionLocal
from backend.models.integrity_worker import IntegrityCheckWorker
from backend.models.normalize_worker import NormalizeWorker
from backend.models.sample import Sample
from backend.services.audio_metadata import get_audio_duration, normalize_audio_path
from backend.services.notification_service import NotificationType
from backend.services.scale_analysis_service import ScaleAnalysisService

logger = logging.getLogger("sample_service")


class _SampleMoveWorker(QObject):
    """Deplacement disque+base execute hors du thread UI."""

    succeeded = Signal(int, str, str, str, float)
    failed = Signal(int, str)

    def __init__(self, sample_id: int, target_folder: str):
        super().__init__()
        self.sample_id = int(sample_id)
        self.target_folder = normalize_audio_path(target_folder)

    @Slot()
    def run(self) -> None:
        start = perf_counter()
        session = SessionLocal()
        old_path = ""
        new_path = ""
        try:
            inst = session.get(Sample, self.sample_id)
            if inst is None:
                raise RuntimeError(f"Sample introuvable: {self.sample_id}")

            old_path = normalize_audio_path(str(getattr(inst, "path", "") or ""))
            if not old_path:
                raise RuntimeError("Chemin source introuvable")

            os.makedirs(self.target_folder, exist_ok=True)
            basename = os.path.basename(old_path)
            new_path = normalize_audio_path(os.path.join(self.target_folder, basename))

            shutil.move(old_path, new_path)
            inst.path = new_path
            session.commit()
            self.succeeded.emit(
                self.sample_id,
                self.target_folder,
                old_path,
                new_path,
                (perf_counter() - start) * 1000.0,
            )
        except Exception as exc:
            session.rollback()
            if new_path and old_path:
                try:
                    if os.path.exists(new_path) and not os.path.exists(old_path):
                        shutil.move(new_path, old_path)
                except Exception:
                    logger.exception(
                        "[SampleMoveWorker] rollback move impossible sample=%s %s -> %s",
                        self.sample_id,
                        new_path,
                        old_path,
                    )
            self.failed.emit(self.sample_id, str(exc))
        finally:
            session.close()


class SampleService(QObject):
    """Service Qt pour gerer les Samples avec cache memoire."""

    sampleAdded = Signal(int)
    samplesChanged = Signal(list)
    sampleDeleted = Signal(int)
    sampleRenamed = Signal(int, str, str)
    sampleMoved = Signal(int, str)
    sampleDurationChanged = Signal(int, float)
    sampleStartedNormalization = Signal(int)
    sampleFinishedNormalization = Signal(int)
    sampleNormalizationFailed = Signal(int, str)
    sampleRemovedFromHistory = Signal(int)
    sampleConcatCandidateChanged = Signal(int, bool, object)
    sampleNormalizationLockChanged = Signal(int, bool)
    sampleScaleAnalyzed = Signal(int)  # emet l'ID apres analyse de gamme terminee

    def __init__(self, app_context):
        super().__init__()
        logger.info("[SampleService] Initialisation du service")
        # Le cache memoire : la liste de tous les samples connus.
        self._samples = []
        # Workers de normalisation en cours, ranges par id de sample.
        self._normalize_threads = {}
        # Deplacements asynchrones en cours.
        self._move_threads: dict[int, tuple[QThread, _SampleMoveWorker]] = {}
        self._move_started_at: dict[int, float] = {}
        # Concatenation : {id du nouveau sample -> id de la prise precedente}.
        self._concat_candidates: dict[int, int] = {}
        # Samples dont la normalisation est temporairement interdite.
        self._normalization_locked_ids: set[int] = set()
        # Dernier sample issu de l'enregistreur (pour chainer les prises).
        self._last_recorded_sample_id: int | None = None
        self.app_context = app_context

        self._initialize_cache()

        # Verification d'integrite au demarrage (fichiers disparus, durees).
        self._integrity_worker = IntegrityCheckWorker(self.app_context)
        self._integrity_worker.fileMissing.connect(self._onMissingStateChanged)
        self._integrity_worker.durationMismatch.connect(self._onDurationMismatch)
        self._integrity_worker.start()

        # Analyse musicale (gamme/note) en file d'attente d'arriere-plan.
        self._scale_analysis = ScaleAnalysisService(self)
        self._scale_analysis.scaleAnalysisComplete.connect(self._on_scale_analysis_complete)
        self._scale_analysis.scaleAnalysisFailed.connect(self._on_scale_analysis_failed)

    def _initialize_cache(self):
        """Charge tous les samples de la base dans le cache memoire."""
        try:
            with SessionLocal() as session:
                self._samples = session.query(Sample).order_by(Sample.id).all()
        except SQLAlchemyError as exc:
            logger.info("[SampleService] init load error: %s", exc)
            self._samples = []
        finally:
            # Quoi qu'il arrive, on previent l'UI de l'etat du cache.
            self.samplesChanged.emit(list(self._samples))

    def load_all(self):
        """Recharge le cache depuis la base (apres une indexation par ex.)."""
        self._initialize_cache()

    def get_cached(self):
        """Copie de la liste des samples en cache (sans toucher la base)."""
        return list(self._samples)

    def add(
        self,
        path: str,
        *,
        from_recorder: bool = False,
        sequential_with_previous: bool = False,
    ):
        """Enregistre un fichier audio comme nouveau sample.

        Etapes : creation de la fiche en base (avec lecture des metadonnees),
        notification, ajout au cache, puis traitements automatiques :
        - sample venant de l'ENREGISTREUR (from_recorder=True) : on bloque
          d'abord la normalisation, le temps de savoir s'il doit etre
          concatene avec la prise precedente (sequential_with_previous) ;
        - sample venant d'un IMPORT : normalisation automatique immediate.
        Dans tous les cas, l'analyse de gamme est mise en file d'attente.
        Renvoie le sample cree, ou None en cas d'erreur.
        """
        path = normalize_audio_path(path)
        new_sample = None
        try:
            new_sample = Sample(path)
            self.app_context.notifications.notify(
                title="Nouveau sample ajoute",
                message=(
                    f"{new_sample.name} - {new_sample.duration:.1f}s\n"
                    f"Emplacement : {new_sample.path}"
                ),
                type=NotificationType.SUCCESS,
            )

            self._samples.append(new_sample)
            self._samples.sort(key=lambda sample: sample.id)
            self.sampleAdded.emit(new_sample.id)

            if from_recorder:
                self._register_recorded_sample(
                    new_sample.id,
                    sequential_with_previous=sequential_with_previous,
                )
            else:
                self._start_auto_normalization(new_sample.id)

            # Enqueue scale analysis in the background
            self._scale_analysis.enqueue(new_sample.id, new_sample.path)

            return new_sample
        except Exception as exc:
            logger.info("[SampleService] add error: %s", exc)
            return None
        finally:
            self.samplesChanged.emit(list(self._samples))

    def delete(self, sample_id: int):
        """Supprime un sample : son fichier, sa fiche en base, le cache."""
        samp = self._get(sample_id)
        if not samp:
            return
        logger.info("[SampleService][Perf] delete(%s) start", sample_id)
        total_start = perf_counter()
        delete_ms = 0.0
        notify_ms = 0.0
        emit_deleted_ms = 0.0
        emit_changed_ms = 0.0
        try:
            step_start = perf_counter()
            samp.delete()
            delete_ms = (perf_counter() - step_start) * 1000.0
            self._cleanup_concat_state_for_deleted(sample_id)
            self._samples = [sample for sample in self._samples if sample.id != sample_id]
            step_start = perf_counter()
            self.app_context.notifications.notify(
                title="Sample supprime",
                message=f"{samp.name}",
                type=NotificationType.WARNING,
            )
            notify_ms = (perf_counter() - step_start) * 1000.0
            step_start = perf_counter()
            self.sampleDeleted.emit(sample_id)
            emit_deleted_ms = (perf_counter() - step_start) * 1000.0
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur suppression",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] delete error: %s", exc)
        finally:
            step_start = perf_counter()
            self.samplesChanged.emit(list(self._samples))
            emit_changed_ms = (perf_counter() - step_start) * 1000.0
            total_ms = (perf_counter() - total_start) * 1000.0
            logger.info(
                "[SampleService][Perf] delete(%s) done total=%.1fms file_db=%.1fms notify=%.1fms sampleDeleted.emit=%.1fms samplesChanged.emit=%.1fms remaining=%s",
                sample_id,
                total_ms,
                delete_ms,
                notify_ms,
                emit_deleted_ms,
                emit_changed_ms,
                len(self._samples),
            )

    def delete_by_path(self, file_path: str):
        """Supprime par chemin de fichier (utilise par le navigateur de dossiers).

        Si le fichier correspond a un sample connu, suppression complete via
        delete(). Sinon, on efface juste le fichier du disque. Renvoie
        (succes, message d'erreur eventuel).
        """
        file_path = normalize_audio_path(file_path)
        samp = next((sample for sample in self._samples if sample.path == file_path), None)
        if samp:
            self.delete(samp.id)
            return True, None

        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                self.app_context.notifications.notify(
                    title="Sample supprime",
                    message=os.path.basename(file_path),
                    type=NotificationType.WARNING,
                )
                return True, None
            raise FileNotFoundError(file_path)
        except Exception as exc:
            logger.info("[SampleService] delete_by_path error: %s", exc)
            self.app_context.notifications.notify(
                title="Erreur suppression",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            return False, str(exc)

    def delete_record_by_path(self, path: str) -> bool:
        """Supprime la fiche en base SANS toucher au fichier sur le disque.

        Utile pour "des-indexer" un fichier : il reste sur le disque mais
        l'application l'oublie.
        """
        path = normalize_audio_path(path)
        session = SessionLocal()
        try:
            sample = session.query(Sample).filter_by(path=path).one_or_none()
            if not sample:
                return False
            sample_id = sample.id
            session.delete(sample)
            session.commit()
            self._cleanup_concat_state_for_deleted(sample_id)
            self._samples = [item for item in self._samples if item.path != path]
            self.samplesChanged.emit(list(self._samples))
            return True
        except SQLAlchemyError as exc:
            session.rollback()
            logger.info("[SampleService] delete_record_by_path error: %s", exc)
            return False
        finally:
            session.close()

    def rename_by_path(self, file_path: str, new_name: str):
        """Renomme par chemin : sample connu (fiche + fichier) ou simple fichier.

        Deux cas : si le chemin correspond a un sample en base, on renomme
        fiche + fichier ensemble ; sinon on renomme juste le fichier sur le
        disque (en conservant son extension). Renvoie (succes, erreur).
        """
        file_path = normalize_audio_path(file_path)
        samp = next((sample for sample in self._samples if sample.path == file_path), None)
        if samp:
            old_name = samp.name
            sample_id = samp.id
            old_path = samp.path
            try:
                samp.rename(new_name)
                samp.name = new_name
                new_path = samp.path
                self.sampleRenamed.emit(sample_id, old_path, new_path)
                self.app_context.notifications.notify(
                    title="Sample renomme",
                    message=f"{old_name} -> {new_name}",
                    type=NotificationType.SUCCESS,
                )
                return True, None
            except Exception as exc:
                self.app_context.notifications.notify(
                    title="Erreur renommage",
                    message=str(exc),
                    type=NotificationType.ERROR,
                )
                logger.info("[SampleService] rename_by_path error: %s", exc)
                return False, str(exc)
            finally:
                self.samplesChanged.emit(list(self._samples))

        folder = os.path.dirname(file_path)
        old_basename = os.path.basename(file_path)
        ext = os.path.splitext(old_basename)[1]
        new_filename = new_name.strip() + ext
        new_path = normalize_audio_path(os.path.join(folder, new_filename))
        try:
            os.rename(file_path, new_path)
            self.app_context.notifications.notify(
                title="Fichier renomme",
                message=f"{old_basename} -> {new_filename}",
                type=NotificationType.SUCCESS,
            )
            return True, None
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur renommage",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] rename_by_path error: %s", exc)
            return False, str(exc)

    def rename(self, sample_id: int, new_name: str):
        """Renomme un sample par son id (fichier + fiche en base).

        Si le sample est en cours de lecture, on doit d'abord arreter le
        lecteur : sous Windows, un fichier en lecture est verrouille et ne
        peut pas etre renomme.
        """
        samp = next((sample for sample in self._samples if sample.id == sample_id), None)
        if not samp:
            return
        logger.info("[SampleService][Perf] rename(%s, %s) start", sample_id, new_name)
        total_start = perf_counter()
        old_name = samp.name
        old_path = samp.path
        stop_ms = 0.0
        rename_ms = 0.0
        emit_renamed_ms = 0.0
        notify_ms = 0.0
        emit_changed_ms = 0.0

        player = self.app_context.audio_player
        if hasattr(player, "is_playing_sample") and player.is_playing_sample(sample_id):
            try:
                import pygame
                import time

                # On attend (2 s max) que pygame libere vraiment le fichier.
                step_start = perf_counter()
                player.stop_playback()
                start = time.time()
                while pygame.mixer.music.get_busy():
                    if time.time() - start > 2:
                        raise RuntimeError("Impossible d'arreter la lecture")
                    time.sleep(0.05)
                stop_ms = (perf_counter() - step_start) * 1000.0
            except Exception as exc:
                self.app_context.notifications.notify(
                    title="Erreur arret lecture",
                    message=str(exc),
                    type=NotificationType.ERROR,
                )
                logger.info("[SampleService] rename stop playback error: %s", exc)
                return

        try:
            step_start = perf_counter()
            samp.rename(new_name)
            rename_ms = (perf_counter() - step_start) * 1000.0
            samp.name = new_name
            new_path = samp.path
            step_start = perf_counter()
            self.sampleRenamed.emit(sample_id, old_path, new_path)
            emit_renamed_ms = (perf_counter() - step_start) * 1000.0
            step_start = perf_counter()
            self.app_context.notifications.notify(
                title="Sample renomme",
                message=f"{old_name} -> {new_name}",
                type=NotificationType.SUCCESS,
            )
            notify_ms = (perf_counter() - step_start) * 1000.0
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur renommage",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] rename error: %s", exc)
        finally:
            step_start = perf_counter()
            self.samplesChanged.emit(list(self._samples))
            emit_changed_ms = (perf_counter() - step_start) * 1000.0
            total_ms = (perf_counter() - total_start) * 1000.0
            logger.info(
                "[SampleService][Perf] rename(%s) done total=%.1fms stop=%.1fms rename=%.1fms sampleRenamed.emit=%.1fms notify=%.1fms samplesChanged.emit=%.1fms",
                sample_id,
                total_ms,
                stop_ms,
                rename_ms,
                emit_renamed_ms,
                notify_ms,
                emit_changed_ms,
            )

    def move(self, sample_id: int, target_folder: str):
        """Deplace le fichier d'un sample vers un autre dossier (drag and drop)."""
        samp = next((sample for sample in self._samples if sample.id == sample_id), None)
        if not samp:
            return
        target_folder = normalize_audio_path(target_folder)
        if not target_folder:
            return
        current_folder = normalize_audio_path(os.path.dirname(getattr(samp, "path", "") or ""))
        if current_folder == target_folder:
            logger.info("[SampleService][Perf] move(%s) ignored same-folder=%s", sample_id, target_folder)
            return
        if int(sample_id) in self._move_threads:
            logger.info(
                "[SampleService][Perf] move(%s) ignored pending target=%s",
                sample_id,
                target_folder,
            )
            return

        logger.info("[SampleService][Perf] move(%s, %s) start", sample_id, target_folder)
        total_start = perf_counter()
        stop_ms = 0.0
        player = self.app_context.audio_player
        if getattr(player, "current_sample_id", -1) == sample_id:
            try:
                step_start = perf_counter()
                player.clear_audio()
                stop_ms = (perf_counter() - step_start) * 1000.0
            except Exception:
                pass

        thread = QThread(self)
        worker = _SampleMoveWorker(sample_id, target_folder)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_move_worker_succeeded)
        worker.failed.connect(self._on_move_worker_failed)
        worker.succeeded.connect(lambda sid, *_args: self._cleanup_move_thread(sid))
        worker.failed.connect(lambda sid, *_args: self._cleanup_move_thread(sid))
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._move_threads[int(sample_id)] = (thread, worker)
        self._move_started_at[int(sample_id)] = total_start
        thread.start()

        queue_ms = (perf_counter() - total_start) * 1000.0
        logger.info(
            "[SampleService][Perf] move(%s) queued total=%.1fms stop=%.1fms target=%s",
            sample_id,
            queue_ms,
            stop_ms,
            target_folder,
        )
        return
        logger.info("[SampleService][Perf] move(%s, %s) start", sample_id, target_folder)
        total_start = perf_counter()
        stop_ms = 0.0
        move_ms = 0.0
        emit_moved_ms = 0.0
        notify_ms = 0.0
        emit_changed_ms = 0.0
        # Arrêter la lecture si ce sample est en cours — comme pour la suppression.
        player = self.app_context.audio_player
        if getattr(player, "current_sample_id", -1) == sample_id:
            try:
                step_start = perf_counter()
                player.clear_audio()
                stop_ms = (perf_counter() - step_start) * 1000.0
            except Exception:
                pass
        try:
            step_start = perf_counter()
            samp.move_to(target_folder)
            move_ms = (perf_counter() - step_start) * 1000.0
            step_start = perf_counter()
            self.sampleMoved.emit(sample_id, target_folder)
            emit_moved_ms = (perf_counter() - step_start) * 1000.0
            step_start = perf_counter()
            self.app_context.notifications.notify(
                title="Sample deplace",
                message=f"Vers {target_folder}",
                type=NotificationType.SUCCESS,
            )
            notify_ms = (perf_counter() - step_start) * 1000.0
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur deplacement",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] move error: %s", exc)
        finally:
            step_start = perf_counter()
            self.samplesChanged.emit(list(self._samples))
            emit_changed_ms = (perf_counter() - step_start) * 1000.0
            total_ms = (perf_counter() - total_start) * 1000.0
            logger.info(
                "[SampleService][Perf] move(%s) done total=%.1fms stop=%.1fms move=%.1fms sampleMoved.emit=%.1fms notify=%.1fms samplesChanged.emit=%.1fms",
                sample_id,
                total_ms,
                stop_ms,
                move_ms,
                emit_moved_ms,
                notify_ms,
                emit_changed_ms,
            )

    @Slot(int, str, str, str, float)
    def _on_move_worker_succeeded(
        self,
        sample_id: int,
        target_folder: str,
        old_path: str,
        new_path: str,
        worker_ms: float,
    ) -> None:
        sample = self._get(sample_id)
        if sample is not None:
            sample.path = new_path

        step_start = perf_counter()
        self.sampleMoved.emit(sample_id, target_folder)
        emit_moved_ms = (perf_counter() - step_start) * 1000.0

        step_start = perf_counter()
        self.app_context.notifications.notify(
            title="Sample deplace",
            message=f"Vers {target_folder}",
            type=NotificationType.SUCCESS,
        )
        notify_ms = (perf_counter() - step_start) * 1000.0

        step_start = perf_counter()
        self.samplesChanged.emit(list(self._samples))
        emit_changed_ms = (perf_counter() - step_start) * 1000.0

        started_at = self._move_started_at.pop(int(sample_id), None)
        total_ms = (
            (perf_counter() - started_at) * 1000.0
            if started_at is not None
            else worker_ms + emit_moved_ms + notify_ms + emit_changed_ms
        )
        logger.info(
            "[SampleService][Perf] move(%s) done total=%.1fms worker=%.1fms sampleMoved.emit=%.1fms notify=%.1fms samplesChanged.emit=%.1fms old=%s new=%s",
            sample_id,
            total_ms,
            worker_ms,
            emit_moved_ms,
            notify_ms,
            emit_changed_ms,
            old_path,
            new_path,
        )

    @Slot(int, str)
    def _on_move_worker_failed(self, sample_id: int, error_msg: str) -> None:
        self._move_started_at.pop(int(sample_id), None)
        self.app_context.notifications.notify(
            title="Erreur deplacement",
            message=error_msg,
            type=NotificationType.ERROR,
        )
        logger.info("[SampleService] move worker error (%s): %s", sample_id, error_msg)

    def _cleanup_move_thread(self, sample_id: int) -> None:
        record = self._move_threads.pop(int(sample_id), None)
        if record is None:
            return
        thread, _worker = record
        if thread.isRunning():
            thread.quit()

    def updateDurationFromFile(self, file_path: str):
        """Re-mesure la duree d'un fichier modifie et met a jour base + cache.

        Appele apres une edition du fichier (decoupe dans l'editeur de forme
        d'onde, concatenation...) pour que la duree affichee reste juste.
        """
        file_path = normalize_audio_path(file_path)
        samp = next((sample for sample in self._samples if sample.path == file_path), None)
        if not samp:
            return
        try:
            new_duration = get_audio_duration(file_path)
        except Exception as exc:
            logger.info("[SampleService] updateDurationFromFile error: %s", exc)
            return

        session = SessionLocal()
        try:
            inst = session.get(Sample, samp.id)
            if inst:
                inst.duration = new_duration
                session.commit()
            samp.duration = new_duration
            self.sampleDurationChanged.emit(samp.id, new_duration)
        except SQLAlchemyError as exc:
            session.rollback()
            logger.info("[SampleService] updateDurationFromFile DB error: %s", exc)
        finally:
            session.close()

    def _get(self, sample_id: int):
        """Retrouve un sample du cache par son id (None si inconnu)."""
        return next((sample for sample in self._samples if sample.id == sample_id), None)

    def _onNormalizationFailed(self, sample_id: int, message: str):
        """Relaie l'echec d'une normalisation vers l'UI."""
        self.sampleNormalizationFailed.emit(sample_id, message)

    def _onDurationMismatch(self, sample_id: int, new_duration: float):
        """Le verificateur d'integrite a corrige une duree : maj du cache."""
        samp = self._get(sample_id)
        if samp:
            samp.duration = new_duration
            self.sampleDurationChanged.emit(sample_id, new_duration)

    def _onMissingStateChanged(self, sample_id: int, missing: bool):
        """Le verificateur d'integrite a change l'etat manquant/present."""
        samp = self._get(sample_id)
        if samp:
            samp.missing = bool(missing)
            self.samplesChanged.emit(list(self._samples))

    def mark_missing(self, sample_id: int, missing: bool = True):
        """Marque manuellement un sample comme disparu (ou retrouve)."""
        samp = self._get(sample_id)
        if not samp:
            return False
        session = SessionLocal()
        try:
            inst = session.get(Sample, sample_id)
            if not inst:
                return False
            inst.missing = bool(missing)
            session.commit()
            samp.missing = bool(missing)
            return True
        except SQLAlchemyError as exc:
            session.rollback()
            logger.info("[SampleService] mark_missing DB error: %s", exc)
            return False
        finally:
            session.close()
            self.samplesChanged.emit(list(self._samples))

    def removeFromHistory(self, sample_id: int):
        """Retire un sample de l'application SANS supprimer son fichier.

        La fiche disparait de la base et du cache, mais le fichier audio
        reste intact sur le disque.
        """
        samp = self._get(sample_id)
        if not samp:
            return
        try:
            session = SessionLocal()
            inst = session.get(Sample, sample_id)
            if inst:
                session.delete(inst)
                session.commit()
            session.close()
            self._cleanup_concat_state_for_deleted(sample_id)
            self._samples = [sample for sample in self._samples if sample.id != sample_id]
            self.sampleRemovedFromHistory.emit(sample_id)
            self.app_context.notifications.notify(
                title="Historique mis a jour",
                message="Sample retire de l'historique",
                type=NotificationType.INFO,
            )
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur historique",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] removeFromHistory error: %s", exc)
        finally:
            self.samplesChanged.emit(list(self._samples))

    def bulkDelete(self, sample_ids: list[int]):
        """Supprime plusieurs samples d'un coup (selection multiple).

        Plus efficace que delete() en boucle : une seule session de base
        pour toutes les fiches. Si l'un des samples est en lecture, on
        arrete d'abord le lecteur (verrou de fichier Windows).
        """
        current = self.app_context.audio_player.current_sample_id
        if current in sample_ids:
            try:
                self.app_context.audio_player.clear_audio()
            except Exception:
                pass

        try:
            for samp in [sample for sample in self._samples if sample.id in sample_ids]:
                if os.path.isfile(samp.path):
                    os.remove(samp.path)
                    logger.info("[SampleService] Fichier %s supprime", samp.path)

            session = SessionLocal()
            for sample_id in sample_ids:
                inst = session.get(Sample, sample_id)
                if inst:
                    session.delete(inst)
            session.commit()
            session.close()

            self._samples = [sample for sample in self._samples if sample.id not in sample_ids]

            for sample_id in sample_ids:
                self._cleanup_concat_state_for_deleted(sample_id)
            for sample_id in sample_ids:
                self.sampleDeleted.emit(sample_id)
        except Exception as exc:
            logger.info("[SampleService] bulkDelete error: %s", exc)
        finally:
            self.samplesChanged.emit(list(self._samples))

    def is_normalization_locked(self, sample_id: int) -> bool:
        """Vrai si la normalisation de ce sample est en attente de decision."""
        return sample_id in self._normalization_locked_ids

    def get_concat_previous_id(self, sample_id: int):
        """Id de la prise precedente proposee a la concatenation (ou None)."""
        return self._concat_candidates.get(sample_id)

    def on_retro_refill_complete(self):
        """Le buffer retro est re-rempli : plus d'enchainement possible.

        La derniere prise enregistree ne sera donc pas suivie d'une prise
        "collable" -> on peut debloquer et normaliser.
        """
        sid = self._last_recorded_sample_id
        if sid is None:
            return
        self._unlock_and_maybe_normalize(sid)

    def concat_with_previous(self, sample_id: int):
        """Colle ce sample a la fin de la prise precedente (choix utilisateur).

        Deroulement :
        1. assembler les deux WAV dans un fichier temporaire, puis remplacer
           le fichier de la prise PRECEDENTE par le resultat ;
        2. supprimer le sample courant (fichier + fiche + cache) ;
        3. re-cabler les candidatures : si une prise suivante pointait vers
           le sample supprime, elle pointe maintenant vers la prise fusionnee ;
        4. debloquer la normalisation de la prise fusionnee.
        Renvoie True si la fusion a reussi.
        """
        prev_id = self._concat_candidates.get(sample_id)
        if not prev_id:
            return False
        cur = self._get(sample_id)
        prev = self._get(prev_id)
        if not cur or not prev:
            self.dismiss_concat(sample_id)
            return False

        # Aucun des deux fichiers ne doit etre en lecture (verrou Windows).
        player = self.app_context.audio_player
        if getattr(player, "current_sample_id", -1) in (sample_id, prev_id):
            try:
                player.clear_audio()
            except Exception:
                pass

        # Assemblage via un fichier temporaire : si quelque chose echoue,
        # le fichier original de la prise precedente reste intact.
        tmp_path = prev.path + ".concat_tmp.wav"
        try:
            self._append_wav_files(prev.path, cur.path, tmp_path)
            os.replace(tmp_path, prev.path)
            self.updateDurationFromFile(prev.path)

            # Le sample courant disparait (il vit desormais dans prev).
            if os.path.isfile(cur.path):
                os.remove(cur.path)
            with SessionLocal() as session:
                inst = session.get(Sample, sample_id)
                if inst:
                    session.delete(inst)
                    session.commit()

            self._samples = [sample for sample in self._samples if sample.id != sample_id]
            self.sampleDeleted.emit(sample_id)

            # Re-cablage des candidatures qui visaient le sample supprime.
            self._concat_candidates.pop(sample_id, None)
            self.sampleConcatCandidateChanged.emit(sample_id, False, None)
            for child_id, parent_id in list(self._concat_candidates.items()):
                if parent_id == sample_id:
                    self._concat_candidates[child_id] = prev_id
                    self.sampleConcatCandidateChanged.emit(child_id, True, prev_id)

            if sample_id in self._normalization_locked_ids:
                self._normalization_locked_ids.discard(sample_id)
                self.sampleNormalizationLockChanged.emit(sample_id, False)

            if self._last_recorded_sample_id == sample_id:
                self._last_recorded_sample_id = prev_id

            self._unlock_and_maybe_normalize(prev_id)

            self.app_context.notifications.notify(
                title="Samples concatenes",
                message=f"{cur.name} ajoute a la fin de {prev.name}",
                type=NotificationType.SUCCESS,
            )
            self.samplesChanged.emit(list(self._samples))
            return True
        except Exception as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            logger.info("[SampleService] concat_with_previous error: %s", exc)
            self.app_context.notifications.notify(
                title="Erreur concatenation",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            return False

    def dismiss_concat(self, sample_id: int):
        """L'utilisateur refuse la concatenation : les prises restent separees.

        On retire la candidature et on debloque la normalisation des deux
        samples concernes.
        """
        prev_id = self._concat_candidates.pop(sample_id, None)
        self.sampleConcatCandidateChanged.emit(sample_id, False, None)

        self._unlock_and_maybe_normalize(sample_id)
        if prev_id is not None:
            self._unlock_and_maybe_normalize(prev_id)

        self.app_context.notifications.notify(
            title="Concat ignoree",
            message="Les samples restent separes.",
            type=NotificationType.INFO,
        )

    def _register_recorded_sample(self, sample_id: int, sequential_with_previous: bool):
        """Enregistre une nouvelle prise venant de l'enregistreur.

        La normalisation est toujours bloquee dans un premier temps. Si la
        prise suit la precedente (le buffer retro n'avait pas fini de se
        re-remplir), on cree la candidature a la concatenation et on bloque
        aussi la prise precedente.
        """
        self._lock_normalization(sample_id)

        prev_id = self._last_recorded_sample_id
        if sequential_with_previous and prev_id and self._get(prev_id):
            self._concat_candidates[sample_id] = prev_id
            self.sampleConcatCandidateChanged.emit(sample_id, True, prev_id)
            self._lock_normalization(prev_id)

        self._last_recorded_sample_id = sample_id

    def _lock_normalization(self, sample_id: int):
        """Interdit (temporairement) la normalisation de ce sample."""
        if sample_id not in self._normalization_locked_ids:
            self._normalization_locked_ids.add(sample_id)
            self.sampleNormalizationLockChanged.emit(sample_id, True)

    def _unlock_and_maybe_normalize(self, sample_id: int):
        """Leve le blocage et lance la normalisation, sauf concat en attente.

        Si le sample est encore implique dans une candidature de
        concatenation (d'un cote ou de l'autre), on ne touche a rien :
        la decision de l'utilisateur prime.
        """
        if self._is_concat_linked(sample_id):
            return
        if sample_id in self._normalization_locked_ids:
            self._normalization_locked_ids.discard(sample_id)
            self.sampleNormalizationLockChanged.emit(sample_id, False)
        self._start_auto_normalization(sample_id)

    def _is_concat_linked(self, sample_id: int) -> bool:
        """Vrai si ce sample participe a une candidature de concatenation."""
        if sample_id in self._concat_candidates:
            return True
        return sample_id in self._concat_candidates.values()

    def _cleanup_concat_state_for_deleted(self, sample_id: int):
        """Nettoie tous les etats de concat quand un sample est supprime.

        Trois choses a defaire : sa propre candidature (en tant que nouvel
        enregistrement), les candidatures d'autres samples qui pointaient
        vers lui, et son eventuel blocage de normalisation. Les samples
        liberes sont alors normalises.
        """
        if sample_id in self._concat_candidates:
            parent_id = self._concat_candidates.pop(sample_id, None)
            self.sampleConcatCandidateChanged.emit(sample_id, False, None)
            if parent_id is not None:
                self._unlock_and_maybe_normalize(parent_id)

        for child_id, parent_id in list(self._concat_candidates.items()):
            if parent_id == sample_id:
                self._concat_candidates.pop(child_id, None)
                self.sampleConcatCandidateChanged.emit(child_id, False, None)
                self._unlock_and_maybe_normalize(child_id)

        if sample_id in self._normalization_locked_ids:
            self._normalization_locked_ids.discard(sample_id)
            self.sampleNormalizationLockChanged.emit(sample_id, False)

        if self._last_recorded_sample_id == sample_id:
            self._last_recorded_sample_id = None

    def _start_auto_normalization(self, sample_id: int):
        """Lance la normalisation automatique d'un sample (si activee).

        Cree un NormalizeWorker (thread) en mode LUFS avec le niveau cible
        des parametres, et le garde dans _normalize_threads le temps qu'il
        travaille. Ne fait rien si l'option est desactivee ou si une
        normalisation de ce sample tourne deja.
        """
        if not self.app_context.settings.isAutoNormalizeEnabled():
            return
        samp = self._get(sample_id)
        if not samp:
            return

        worker = self._normalize_threads.get(sample_id)
        if worker is not None and worker.isRunning():
            return

        target_db = self.app_context.settings.getNormalizationLevel()
        worker = NormalizeWorker(
            sample_id=sample_id,
            file_path=samp.path,
            mode="lufs",
            target_db=target_db,
        )
        worker.startedNormalization.connect(self.sampleStartedNormalization)
        worker.finishedNormalization.connect(self.sampleFinishedNormalization)
        worker.normalizationFailed.connect(self._onNormalizationFailed)
        worker.finishedNormalization.connect(
            lambda sid=sample_id: self._normalize_threads.pop(sid, None)
        )
        worker.normalizationFailed.connect(
            lambda sid, _msg: self._normalize_threads.pop(sid, None)
        )
        worker.start()
        self._normalize_threads[sample_id] = worker

    def _on_scale_analysis_complete(self, sample_id: int) -> None:
        """Rafraichit le sample en cache apres analyse des gammes.

        L'analyse a ecrit ses resultats directement en base (depuis son
        worker) : on recharge donc la fiche fraiche et on remplace
        l'ancienne dans le cache, puis on previent l'UI.
        """
        session = SessionLocal()
        try:
            inst = session.get(Sample, sample_id)
            if inst is None:
                return
            # Mettre a jour le cache memoire
            for i, samp in enumerate(self._samples):
                if samp.id == sample_id:
                    self._samples[i] = inst
                    break
        except SQLAlchemyError as exc:
            logger.info("[SampleService] _on_scale_analysis_complete DB error: %s", exc)
        finally:
            session.close()
        self.sampleScaleAnalyzed.emit(sample_id)

    def batch_analyze_missing(self) -> int:
        """Lance l'analyse de gamme pour tous les samples non analyses ou a backfill.

        Retourne le nombre de samples identifies (l'enfilage reel est asynchrone).
        Le os.path.isfile() est evite ici pour ne pas bloquer le thread principal —
        le worker scale_analysis_service ignore les fichiers introuvables de son cote.
        """
        return self._batch_analyze_candidates(self._samples)

    def batch_analyze_folder(self, folder: str) -> int:
        """Lance l'analyse de gamme uniquement pour les samples du dossier donne.

        Filtre sur os.path.dirname(path) == folder (comparaison normalisee).
        Utile quand l'utilisateur est sur l'onglet Dossiers et ne veut pas
        relancer toute la base de donnees.
        """
        if not folder:
            return self.batch_analyze_missing()
        folder_norm = os.path.normpath(folder)
        subset = [
            samp for samp in self._samples
            if os.path.normpath(os.path.dirname(getattr(samp, "path", "") or "")) == folder_norm
        ]
        return self._batch_analyze_candidates(subset)

    def _batch_analyze_candidates(self, samples) -> int:
        """Filtre les samples sans gamme et les enqueue en arriere-plan.

        Un sample est candidat s'il n'a jamais ete analyse OU si l'analyse
        date d'une version qui ne remplissait pas encore la gamme principale
        (backfill). La mise en file se fait dans un thread pour ne pas
        bloquer l'interface quand il y a des milliers de samples.
        """
        candidates = []
        for samp in samples:
            needs_analysis = getattr(samp, "analyzed_at", None) is None
            missing_primary_scale = not str(getattr(samp, "detected_scale_kind", "") or "").strip()
            if not needs_analysis and not missing_primary_scale:
                continue
            path = getattr(samp, "path", None) or ""
            if path:
                candidates.append((samp.id, path))

        count = len(candidates)
        logger.info("[SampleService] _batch_analyze_candidates: %d samples a enqueuer", count)

        import threading
        def _enqueue_all():
            for sid, p in candidates:
                self._scale_analysis.enqueue(sid, p)
        threading.Thread(target=_enqueue_all, daemon=True, name="scale-batch-enqueue").start()

        return count

    def _on_scale_analysis_failed(self, sample_id: int, reason: str) -> None:
        """Trace l'echec d'une analyse de gamme (sans bloquer le reste)."""
        logger.info("[SampleService] Scale analysis failed id=%s: %s", sample_id, reason)

    def shutdown(self) -> None:
        """Arret propre des services de fond (ScaleAnalysisService)."""
        for sample_id, (thread, _worker) in list(self._move_threads.items()):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(3000)
            except Exception:
                logger.exception("[SampleService] move thread shutdown impossible (%s)", sample_id)
        self._move_threads.clear()
        self._move_started_at.clear()
        try:
            self._scale_analysis.shutdown()
        except Exception:
            logger.exception("[SampleService] scale_analysis shutdown impossible")

    @staticmethod
    def _append_wav_files(first_path: str, second_path: str, out_path: str):
        """Colle physiquement deux WAV : out = first puis second, a la suite.

        Les deux fichiers doivent avoir la meme frequence et le meme nombre
        de canaux (sinon le resultat serait inaudible). La copie se fait par
        blocs de 8192 echantillons pour garder une memoire constante meme
        sur de tres longs enregistrements.
        """
        with sf.SoundFile(first_path, mode="r") as first, sf.SoundFile(second_path, mode="r") as second:
            if first.samplerate != second.samplerate:
                raise RuntimeError("Sample rate different entre les deux fichiers.")
            if first.channels != second.channels:
                raise RuntimeError("Nombre de canaux different entre les deux fichiers.")

            with sf.SoundFile(
                out_path,
                mode="w",
                samplerate=first.samplerate,
                channels=first.channels,
                subtype="PCM_16",
            ) as out:
                for src in (first, second):
                    while True:
                        chunk = src.read(
                            frames=8192,
                            dtype="float32",
                            always_2d=(first.channels > 1),
                        )
                        if chunk is None or len(chunk) == 0:
                            break
                        out.write(chunk)
