# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service de gestion des samples (CRUD + cache memoire).
# - Pont entre la base (SQLAlchemy), le systeme de fichiers et l'UI (Qt).
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

import soundfile as sf
from PySide6.QtCore import QObject, Signal
from sqlalchemy.exc import SQLAlchemyError

from backend.db import SessionLocal
from backend.models.integrity_worker import IntegrityCheckWorker
from backend.models.normalize_worker import NormalizeWorker
from backend.models.sample import Sample
from backend.services.audio_metadata import get_audio_duration, normalize_audio_path
from backend.services.notification_service import NotificationType
from backend.services.scale_analysis_service import ScaleAnalysisService

logger = logging.getLogger("sample_service")


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

    def __init__(self, app_context):
        super().__init__()
        logger.info("[SampleService] Initialisation du service")
        self._samples = []
        self._normalize_threads = {}
        self._concat_candidates: dict[int, int] = {}
        self._normalization_locked_ids: set[int] = set()
        self._last_recorded_sample_id: int | None = None
        self.app_context = app_context

        self._initialize_cache()

        self._integrity_worker = IntegrityCheckWorker(self.app_context)
        self._integrity_worker.fileMissing.connect(self._onMissingStateChanged)
        self._integrity_worker.durationMismatch.connect(self._onDurationMismatch)
        self._integrity_worker.start()

        self._scale_analysis = ScaleAnalysisService(self)
        self._scale_analysis.scaleAnalysisComplete.connect(self._on_scale_analysis_complete)
        self._scale_analysis.scaleAnalysisFailed.connect(self._on_scale_analysis_failed)

    def _initialize_cache(self):
        try:
            with SessionLocal() as session:
                self._samples = session.query(Sample).order_by(Sample.id).all()
        except SQLAlchemyError as exc:
            logger.info("[SampleService] init load error: %s", exc)
            self._samples = []
        finally:
            self.samplesChanged.emit(list(self._samples))

    def load_all(self):
        self._initialize_cache()

    def get_cached(self):
        return list(self._samples)

    def add(
        self,
        path: str,
        *,
        from_recorder: bool = False,
        sequential_with_previous: bool = False,
    ):
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
        samp = self._get(sample_id)
        if not samp:
            return
        try:
            samp.delete()
            self._cleanup_concat_state_for_deleted(sample_id)
            self._samples = [sample for sample in self._samples if sample.id != sample_id]
            self.app_context.notifications.notify(
                title="Sample supprime",
                message=f"{samp.name}",
                type=NotificationType.WARNING,
            )
            self.sampleDeleted.emit(sample_id)
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur suppression",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] delete error: %s", exc)
        finally:
            self.samplesChanged.emit(list(self._samples))

    def delete_by_path(self, file_path: str):
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
        samp = next((sample for sample in self._samples if sample.id == sample_id), None)
        if not samp:
            return
        old_name = samp.name
        old_path = samp.path

        player = self.app_context.audio_player
        if hasattr(player, "is_playing_sample") and player.is_playing_sample(sample_id):
            try:
                import pygame
                import time

                player.stop_playback()
                start = time.time()
                while pygame.mixer.music.get_busy():
                    if time.time() - start > 2:
                        raise RuntimeError("Impossible d'arreter la lecture")
                    time.sleep(0.05)
            except Exception as exc:
                self.app_context.notifications.notify(
                    title="Erreur arret lecture",
                    message=str(exc),
                    type=NotificationType.ERROR,
                )
                logger.info("[SampleService] rename stop playback error: %s", exc)
                return

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
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur renommage",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] rename error: %s", exc)
        finally:
            self.samplesChanged.emit(list(self._samples))

    def move(self, sample_id: int, target_folder: str):
        samp = next((sample for sample in self._samples if sample.id == sample_id), None)
        if not samp:
            return
        # Arrêter la lecture si ce sample est en cours — comme pour la suppression.
        player = self.app_context.audio_player
        if getattr(player, "current_sample_id", -1) == sample_id:
            try:
                player.clear_audio()
            except Exception:
                pass
        try:
            samp.move_to(target_folder)
            self.sampleMoved.emit(sample_id, target_folder)
            self.app_context.notifications.notify(
                title="Sample deplace",
                message=f"Vers {target_folder}",
                type=NotificationType.SUCCESS,
            )
        except Exception as exc:
            self.app_context.notifications.notify(
                title="Erreur deplacement",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            logger.info("[SampleService] move error: %s", exc)
        finally:
            self.samplesChanged.emit(list(self._samples))

    def updateDurationFromFile(self, file_path: str):
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
        return next((sample for sample in self._samples if sample.id == sample_id), None)

    def _onNormalizationFailed(self, sample_id: int, message: str):
        self.sampleNormalizationFailed.emit(sample_id, message)

    def _onDurationMismatch(self, sample_id: int, new_duration: float):
        samp = self._get(sample_id)
        if samp:
            samp.duration = new_duration
            self.sampleDurationChanged.emit(sample_id, new_duration)

    def _onMissingStateChanged(self, sample_id: int, missing: bool):
        samp = self._get(sample_id)
        if samp:
            samp.missing = bool(missing)
            self.samplesChanged.emit(list(self._samples))

    def mark_missing(self, sample_id: int, missing: bool = True):
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
        return sample_id in self._normalization_locked_ids

    def get_concat_previous_id(self, sample_id: int):
        return self._concat_candidates.get(sample_id)

    def on_retro_refill_complete(self):
        sid = self._last_recorded_sample_id
        if sid is None:
            return
        self._unlock_and_maybe_normalize(sid)

    def concat_with_previous(self, sample_id: int):
        prev_id = self._concat_candidates.get(sample_id)
        if not prev_id:
            return False
        cur = self._get(sample_id)
        prev = self._get(prev_id)
        if not cur or not prev:
            self.dismiss_concat(sample_id)
            return False

        player = self.app_context.audio_player
        if getattr(player, "current_sample_id", -1) in (sample_id, prev_id):
            try:
                player.clear_audio()
            except Exception:
                pass

        tmp_path = prev.path + ".concat_tmp.wav"
        try:
            self._append_wav_files(prev.path, cur.path, tmp_path)
            os.replace(tmp_path, prev.path)
            self.updateDurationFromFile(prev.path)

            if os.path.isfile(cur.path):
                os.remove(cur.path)
            with SessionLocal() as session:
                inst = session.get(Sample, sample_id)
                if inst:
                    session.delete(inst)
                    session.commit()

            self._samples = [sample for sample in self._samples if sample.id != sample_id]
            self.sampleDeleted.emit(sample_id)

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
        self._lock_normalization(sample_id)

        prev_id = self._last_recorded_sample_id
        if sequential_with_previous and prev_id and self._get(prev_id):
            self._concat_candidates[sample_id] = prev_id
            self.sampleConcatCandidateChanged.emit(sample_id, True, prev_id)
            self._lock_normalization(prev_id)

        self._last_recorded_sample_id = sample_id

    def _lock_normalization(self, sample_id: int):
        if sample_id not in self._normalization_locked_ids:
            self._normalization_locked_ids.add(sample_id)
            self.sampleNormalizationLockChanged.emit(sample_id, True)

    def _unlock_and_maybe_normalize(self, sample_id: int):
        if self._is_concat_linked(sample_id):
            return
        if sample_id in self._normalization_locked_ids:
            self._normalization_locked_ids.discard(sample_id)
            self.sampleNormalizationLockChanged.emit(sample_id, False)
        self._start_auto_normalization(sample_id)

    def _is_concat_linked(self, sample_id: int) -> bool:
        if sample_id in self._concat_candidates:
            return True
        return sample_id in self._concat_candidates.values()

    def _cleanup_concat_state_for_deleted(self, sample_id: int):
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
        """Rafraichit le sample en cache apres analyse des gammes."""
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

    def _on_scale_analysis_failed(self, sample_id: int, reason: str) -> None:
        logger.info("[SampleService] Scale analysis failed id=%s: %s", sample_id, reason)

    def shutdown(self) -> None:
        """Arret propre des services de fond (ScaleAnalysisService)."""
        try:
            self._scale_analysis.shutdown()
        except Exception:
            logger.exception("[SampleService] scale_analysis shutdown impossible")

    @staticmethod
    def _append_wav_files(first_path: str, second_path: str, out_path: str):
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
