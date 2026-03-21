# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service de gestion des samples (CRUD + cache memoire).
# - Pont entre la base (SQLAlchemy), le systeme de fichiers et l'UI (Qt).
#
# RESPONSABILITES PRINCIPALES
# - Maintenir un cache en memoire des Sample.
# - Emettre des signaux Qt pour synchroniser l'UI.
# - Orchestrer les operations fichier + base (add/delete/rename/move).
# - Lancer la normalisation audio et verifier la coherence des donnees.
#
# FLUX GLOBAL
# UI -> SampleService -> (FS + DB) -> signaux Qt -> UI
# -----------------------------------------------------------------------------
# Qt: base QObject + signaux pour notifier l'UI
from PySide6.QtCore import QObject, Signal
# SQLAlchemy: gestion des erreurs DB
from sqlalchemy.exc import SQLAlchemyError
# Acces a la session DB
from backend.db import SessionLocal
# Modele Sample (logique fichier + DB)
from backend.models.sample import Sample
# Worker de normalisation audio
from backend.models.normalize_worker import NormalizeWorker
# Types de notifications UI
from backend.services.notification_service import NotificationType
# OS: operations sur fichiers (rename/delete/etc.)
import os
# wave: lecture d'en-tetes WAV pour la duree
import wave
import soundfile as sf
# Logging pour tracer les operations
import logging
# Logger specifique au service
logger = logging.getLogger("sample_service")

class SampleService(QObject):
    """
    Service Qt pour gérer les Samples avec cache en mémoire.
    - load_all()       : charge une fois et émet la liste complète
    - delete(id)       : supprime un sample (fichier + BD)
    - rename(id, name) : renomme un sample (fichier + BD)
    - move(id, folder) : déplace un sample (fichier + BD)
    Émet des signaux pour permettre à l’UI de se mettre à jour.
    """
    # Signaux emis pour que l'UI se mette a jour sans recharger tout le cache
    sampleAdded = Signal(int)            # émet l’ID du sample ajouté
    samplesChanged = Signal(list)        # émet la liste complète des Sample
    sampleDeleted  = Signal(int)         # émet l’ID supprimé
    # Emis après un renommage. Fournit l'ID du sample, l'ancien chemin complet
    # et le nouveau chemin complet pour permettre la mise à jour de toutes les
    # vues sans avoir à recharger la liste complète.
    sampleRenamed  = Signal(int, str, str)    # émet (ID, ancien chemin, nouveau chemin)
    sampleMoved    = Signal(int, str)    # émet (ID, nouveau dossier)
    sampleDurationChanged = Signal(int, float)  # émet (ID, nouvelle durée)
    sampleStartedNormalization  = Signal(int)      # émet l’ID du sample en cours de normalisation
    sampleFinishedNormalization = Signal(int)       # émet l’ID du sample normalisé
    sampleNormalizationFailed   = Signal(int, str)  # émet (ID, message d’erreur)
    sampleRemovedFromHistory = Signal(int)          # émet l’ID du sample retiré de l’historique

    # Runtime only: indique si un sample courant peut etre concatene avec son precedent
    sampleConcatCandidateChanged = Signal(
        int, bool, object
    )  # (sample_id, enabled, prev_id|None)
    # Verrou temporaire de normalisation (pendant la fenetre de decision de concat)
    sampleNormalizationLockChanged = Signal(int, bool)  # (sample_id, locked)
    def __init__(self, app_context):
        super().__init__()
        # Initialisation du service et du cache
        logger.info("[SampleService] Initialisation du service")
        # Cache local des samples charges depuis la DB
        self._samples = []
        # References vers les workers de normalisation (evite GC)
        self._normalize_threads = {}
        # Runtime only: sample courant -> sample precedent a concatener
        self._concat_candidates: dict[int, int] = {}
        # IDs en attente de normalisation (fenetre refill / decision concat)
        self._normalization_locked_ids: set[int] = set()
        # Dernier sample cree par RecorderService (pour liberer a la fin du refill)
        self._last_recorded_sample_id: int | None = None
        # Acces aux autres services (notifications, settings, audio player, etc.)
        self.app_context = app_context

        # Chargement initial depuis la DB
        self._initialize_cache()

        # Lancement du worker de coherence (verif DB/FS)
        # Worker de coherence: verifie fichiers manquants et durees incoherentes
        self._integrity_worker = IntegrityCheckWorker(self.app_context)
        self._integrity_worker.fileMissing.connect(self.removeFromHistory)
        # Si la duree est incoherente, on corrige en base
        self._integrity_worker.durationMismatch.connect(self._onDurationMismatch)
        self._integrity_worker.start()

    def _initialize_cache(self):
        """Charge les samples depuis la BDD et émet samplesChanged."""
        
        # Lecture DB dans un contexte session gere
        try:
            with SessionLocal() as session:
                self._samples = session.query(Sample).order_by(Sample.id).all()
        except SQLAlchemyError as e:
            logger.info(f"[SampleService] init load error: {e}")
            self._samples = []
        finally:
            self.samplesChanged.emit(list(self._samples))

    def load_all(self):
        """Force le rechargement complet depuis la BDD et émet samplesChanged."""
        self._initialize_cache()

    def get_cached(self):
        """Retourne la liste courante en mémoire."""
        # Retourne une copie pour eviter les modifications externes
        return list(self._samples)

    def add(
        self,
        path: str,
        *,
        from_recorder: bool = False,
        sequential_with_previous: bool = False,
    ):
        """
        Cree un nouveau sample (FS + BD), met a jour le cache, puis gere
        la normalisation auto.

        Args:
            path: chemin du wav.
            from_recorder: True si le sample vient du RecorderService.
            sequential_with_previous: True si la prise a demarre avant refill
                complet du buffer retro (candidate a concat avec la precedente).
        Returns:
            Sample | None
        """
        new_sample = None
        try:
            # 1) Creation via le modele : enregistre fichier + base
            new_sample = Sample(path)

            # 2) Notification utilisateur
            self.app_context.notifications.notify(
                title="Nouveau sample ajoute",
                message=(
                    f"{new_sample.name} - {new_sample.duration:.1f}s\n"
                    f"Emplacement : {new_sample.path}"
                ),
                type=NotificationType.SUCCESS,
            )

            # 3) Cache + signal d'ajout
            self._samples.append(new_sample)
            self._samples.sort(key=lambda s: s.id)
            self.sampleAdded.emit(new_sample.id)

            # 4) Flux de normalisation
            if from_recorder:
                self._register_recorded_sample(
                    new_sample.id,
                    sequential_with_previous=sequential_with_previous,
                )
            else:
                self._start_auto_normalization(new_sample.id)

            return new_sample
        except Exception as e:
            logger.info(f"[SampleService] add error: {e}")
            return None
        finally:
            # 5) Re-emission de la liste
            self.samplesChanged.emit(list(self._samples))

    def delete(self, sample_id: int):
        """
        Supprime fichier + entrée BD, met à jour le cache, et émet sampleDeleted + samplesChanged.
        """
        # 1) Récupère l'instance dans le cache
        samp = self._get(sample_id)
        if not samp:
            return
        try:
            # Suppression fichier + DB via le modele
            samp.delete()
            self._cleanup_concat_state_for_deleted(sample_id)
            # 2) Mise à jour du cache : on enlève l'objet supprimé
            self._samples = [
                s for s in self._samples
                if s.id != sample_id
            ]
            # ▶ Succès
            self.app_context.notifications.notify(
                title="⚠️ Sample supprimé",
                message=f"{samp.name}",
                type=NotificationType.WARNING
            )
            self.sampleDeleted.emit(sample_id)
        except Exception as e:
            logger.info(f"[SampleService] delete error: {e}")
            # ▶ Erreur lors de la suppression
            self.app_context.notifications.notify(
                title="❌ Erreur suppression",
                message=str(e),
                type=NotificationType.ERROR
            )
            logger.info(f"[SampleService] delete error: {e}")
        finally:
            self.samplesChanged.emit(list(self._samples))

    def delete_by_path(self, file_path: str):
        """Supprime un fichier par son chemin et nettoie la BDD si nécessaire."""
        # Cas 1: si le sample est deja en cache, on passe par delete()
        samp = next((s for s in self._samples if s.path == file_path), None)
        if samp:
            self.delete(samp.id)
            return True, None

        import os
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                self.app_context.notifications.notify(
                    title="⚠️ Sample supprimé",
                    message=os.path.basename(file_path),
                    type=NotificationType.WARNING,
                )
                return True, None
            raise FileNotFoundError(file_path)
        except Exception as e:
            logger.info(f"[SampleService] delete_by_path error: {e}")
            self.app_context.notifications.notify(
                title="❌ Erreur suppression",
                message=str(e),
                type=NotificationType.ERROR,
            )
            return False, str(e)

    def delete_record_by_path(self, path: str) -> bool:
        """
        Supprime uniquement l'enregistrement en base pour un chemin donné sans
        toucher au fichier sur disque. Retourne ``True`` si un enregistrement a
        été supprimé.
        """
        # Supprime seulement l'entree DB sans toucher au fichier
        session = SessionLocal()
        try:
            sample = session.query(Sample).filter_by(path=path).one_or_none()
            if not sample:
                return False
            sample_id = sample.id
            session.delete(sample)
            session.commit()
            self._cleanup_concat_state_for_deleted(sample_id)
            # Mise à jour du cache local
            self._samples = [s for s in self._samples if s.path != path]
            # Rafraîchit l'UI
            self.samplesChanged.emit(list(self._samples))
            return True
        except SQLAlchemyError as e:
            session.rollback()
            logger.info(f"[SampleService] delete_record_by_path error: {e}")
            return False
        finally:
            session.close()

    def rename_by_path(self, file_path: str, new_name: str):
        """Renomme un fichier par son chemin et met à jour la BDD si besoin."""
        samp = next((s for s in self._samples if s.path == file_path), None)
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
                    title="✅ Sample renommé",
                    message=f"{old_name} → {new_name}",
                    type=NotificationType.SUCCESS,
                )
                return True, None
            except Exception as e:
                self.app_context.notifications.notify(
                    title="❌ Erreur renommage",
                    message=str(e),
                    type=NotificationType.ERROR,
                )
                logger.info(f"[SampleService] rename_by_path error: {e}")
                return False, str(e)
            finally:
                self.samplesChanged.emit(list(self._samples))

        folder = os.path.dirname(file_path)
        old_basename = os.path.basename(file_path)
        ext = os.path.splitext(old_basename)[1]
        new_filename = new_name.strip() + ext
        new_path = os.path.join(folder, new_filename)
        try:
            os.rename(file_path, new_path)
            self.app_context.notifications.notify(
                title="✅ Fichier renommé",
                message=f"{old_basename} → {new_filename}",
                type=NotificationType.SUCCESS,
            )
            return True, None
        except Exception as e:
            self.app_context.notifications.notify(
                title="❌ Erreur renommage",
                message=str(e),
                type=NotificationType.ERROR,
            )
            logger.info(f"[SampleService] rename_by_path error: {e}")
            return False, str(e)

    def rename(self, sample_id: int, new_name: str):
        """
        Renomme le sample (FS + BD), met à jour le cache, et émet sampleRenamed + samplesChanged.
        """
        # Renommage par ID: utilise le cache
        samp = next((s for s in self._samples if s.id == sample_id), None)
        if not samp:
            return
        old_name = samp.name
        old_path = samp.path
        # Securite: arreter la lecture si le sample est en cours
        player = self.app_context.audio_player
        if hasattr(player, "is_playing_sample") and player.is_playing_sample(sample_id):
            try:
                player.stop_playback()
                import time, pygame
                t0 = time.time()
                while pygame.mixer.music.get_busy():
                    if time.time() - t0 > 2:
                        raise RuntimeError("Impossible d'arrêter la lecture")
                    time.sleep(0.05)
            except Exception as e:
                self.app_context.notifications.notify(
                    title="❌ Erreur arrêt lecture",
                    message=str(e),
                    type=NotificationType.ERROR
                )
                logger.info(f"[SampleService] rename stop playback error: {e}")
                return
        try:
            samp.rename(new_name)
            samp.name = new_name
            new_path = samp.path
            self.sampleRenamed.emit(sample_id, old_path, new_path)
            self.app_context.notifications.notify(
                title="✅ Sample renommé",
                message=f"{old_name} → {new_name}",
                type=NotificationType.SUCCESS
            )
        except Exception as e:
            self.app_context.notifications.notify(
                title="❌ Erreur renommage",
                message=str(e),
                type=NotificationType.ERROR
            )
            logger.info(f"[SampleService] rename error: {e}")
        finally:
            self.samplesChanged.emit(list(self._samples))

    def move(self, sample_id: int, target_folder: str):
        """
        Déplace le sample (FS + BD), met à jour le cache, et émet sampleMoved + samplesChanged.
        """
        samp = next((s for s in self._samples if s.id == sample_id), None)
        if not samp:
            return
        try:
            samp.move_to(target_folder)
            # samp.path mis à jour dans samp.move_to()
            self.sampleMoved.emit(sample_id, target_folder)
            # ▶ Succès
            self.app_context.notifications.notify(
                title="✅ Sample déplacé",
                message=f"Vers {target_folder}",
                type=NotificationType.SUCCESS
            )
        except Exception as e:
            # ▶ Erreur
            self.app_context.notifications.notify(
                title="❌ Erreur déplacement",
                message=str(e),
                type=NotificationType.ERROR
            )
            logger.info(f"[SampleService] move error: {e}")
        finally:
            self.samplesChanged.emit(list(self._samples))

    def updateDurationFromFile(self, file_path: str):
        """Recalcul la durée d'un fichier et met à jour la base et le cache."""
        samp = next((s for s in self._samples if s.path == file_path), None)
        if not samp:
            return
        try:
            with wave.open(file_path, 'rb') as w:
                new_duration = w.getnframes() / w.getframerate()
        except Exception as e:
            logger.info(f"[SampleService] updateDurationFromFile error: {e}")
            return

        session = SessionLocal()
        try:
            inst = session.get(Sample, samp.id)
            if inst:
                inst.duration = new_duration
                session.commit()
            samp.duration = new_duration
            self.sampleDurationChanged.emit(samp.id, new_duration)
        except SQLAlchemyError as e:
            session.rollback()
            logger.info(f"[SampleService] updateDurationFromFile DB error: {e}")
        finally:
            session.close()

    def _get(self, sample_id: int):
        """Retourne l’instance en cache ou None."""
        # Helper: recherche en cache
        return next((s for s in self._samples if s.id == sample_id), None)

    def _onNormalizationFailed(self, sample_id: int, message: str):
        # Réémet le signal vers l’UI
        # Reemet le signal vers l'UI
        self.sampleNormalizationFailed.emit(sample_id, message)

    def _onDurationMismatch(self, sample_id: int, new_duration: float):
        samp = self._get(sample_id)
        if samp:
            samp.duration = new_duration
            self.sampleDurationChanged.emit(sample_id, new_duration)

    def removeFromHistory(self, sample_id: int):
        """
        Supprime l’entrée en base pour `sample_id` sans toucher au fichier,
        met à jour le cache et émet sampleRemovedFromHistory + samplesChanged.
        """
        # 1) Récupère l’instance dans le cache
        samp = self._get(sample_id)
        if not samp:
            return
        try:
            # 2) Supprime seulement l’entrée BD
            session = SessionLocal()
            inst = session.get(Sample, sample_id)
            if inst:
                session.delete(inst)
                session.commit()
            session.close()
            self._cleanup_concat_state_for_deleted(sample_id)
            # 3) Mise à jour du cache en mémoire
            self._samples = [s for s in self._samples if s.id != sample_id]
            # 4) Signaux
            self.sampleRemovedFromHistory.emit(sample_id)
            self.app_context.notifications.notify(
                title="ℹ️ Historique mis à jour",
                message="Sample retiré de l’historique",
                type=NotificationType.INFO
            )
        except Exception as e:
            # ▶ Erreur
            self.app_context.notifications.notify(
                title="❌ Erreur historique",
                message=str(e),
                type=NotificationType.ERROR
            )
            logger.info(f"[SampleService] removeFromHistory error: {e}")
        finally:
            # Toujours ré-émission de la liste
            self.samplesChanged.emit(list(self._samples))

    def bulkDelete(self, sample_ids: list[int]):
        """
        Supprime plusieurs samples (FS + BD) en une seule transaction,
        met à jour le cache et émet sampleDeleted pour chaque ID puis samplesChanged.
        """
        import os
        from backend.db import SessionLocal

        # Stoppe la lecture si un des samples est en cours
        current = self.app_context.audio_player.current_sample_id
        if current in sample_ids:
            try:
                self.app_context.audio_player.clear_audio()
            except Exception:
                pass

        try:
            # 2) Suppression physique des fichiers
            for samp in [s for s in self._samples if s.id in sample_ids]:
                if os.path.isfile(samp.path):
                    os.remove(samp.path)
                    logger.info(f"[SampleService] Fichier {samp.path} supprimé")

            # 3) Suppression en base dans une seule session
            session = SessionLocal()
            for sample_id in sample_ids:
                inst = session.get(Sample, sample_id)
                if inst:
                    session.delete(inst)
            session.commit()
            session.close()

            # 4) Mise à jour du cache
            self._samples = [s for s in self._samples if s.id not in sample_ids]

            for sample_id in sample_ids:
                self._cleanup_concat_state_for_deleted(sample_id)
            # 5) Émettre sampleDeleted pour chaque ID (pour fermer les waveforms)
            for sample_id in sample_ids:
                self.sampleDeleted.emit(sample_id)
        except Exception as e:
            logger.info(f"[SampleService] bulkDelete error: {e}")
        finally:
            # 6) N’émettre qu’UN SEUL samplesChanged à la fin
            self.samplesChanged.emit(list(self._samples))


    # ------------------------------------------------------------------ Concat / Auto-normalize (runtime)
    def is_normalization_locked(self, sample_id: int) -> bool:
        return sample_id in self._normalization_locked_ids

    def get_concat_previous_id(self, sample_id: int):
        return self._concat_candidates.get(sample_id)

    def on_retro_refill_complete(self):
        """
        Appele par RecorderService quand le buffer retro est re-rempli.
        Cela libere la normalisation auto du dernier sample enregistre, sauf
        s'il est implique dans une concat en attente.
        """
        sid = self._last_recorded_sample_id
        if sid is None:
            return
        self._unlock_and_maybe_normalize(sid)

    def concat_with_previous(self, sample_id: int):
        """
        Concatene `sample_id` a la fin de son sample precedent, puis supprime
        le sample courant.
        """
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

            # Supprime l'ancien sample "courant" (fichier + DB)
            if os.path.isfile(cur.path):
                os.remove(cur.path)
            with SessionLocal() as session:
                inst = session.get(Sample, sample_id)
                if inst:
                    session.delete(inst)
                    session.commit()

            # Cache + UI
            self._samples = [s for s in self._samples if s.id != sample_id]
            self.sampleDeleted.emit(sample_id)

            # Nettoie le lien courant, puis rewire les enfants eventuels vers prev_id.
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

            # Le sample fusionne est normalise une seule fois, si plus de concat en attente.
            self._unlock_and_maybe_normalize(prev_id)

            self.app_context.notifications.notify(
                title="Samples concatenes",
                message=f"{cur.name} ajoute a la fin de {prev.name}",
                type=NotificationType.SUCCESS,
            )
            self.samplesChanged.emit(list(self._samples))
            return True
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            logger.info(f"[SampleService] concat_with_previous error: {e}")
            self.app_context.notifications.notify(
                title="Erreur concatenation",
                message=str(e),
                type=NotificationType.ERROR,
            )
            return False

    def dismiss_concat(self, sample_id: int):
        """
        Refuse la concat pour ce sample, puis relance la normalisation auto
        pour les deux samples concernes (si activee).
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
        # Chaque sample enregistre attend la fin de la fenetre refill avant normalisation.
        self._lock_normalization(sample_id)

        prev_id = self._last_recorded_sample_id
        if sequential_with_previous and prev_id and self._get(prev_id):
            self._concat_candidates[sample_id] = prev_id
            self.sampleConcatCandidateChanged.emit(sample_id, True, prev_id)
            # Le precedent aussi reste verrouille tant que la decision n'est pas prise.
            self._lock_normalization(prev_id)

        self._last_recorded_sample_id = sample_id

    def _lock_normalization(self, sample_id: int):
        if sample_id not in self._normalization_locked_ids:
            self._normalization_locked_ids.add(sample_id)
            self.sampleNormalizationLockChanged.emit(sample_id, True)

    def _unlock_and_maybe_normalize(self, sample_id: int):
        # Ne libere pas si le sample est encore implique dans une concat en attente.
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
        # Supprime un lien ou sample_id est "courant".
        if sample_id in self._concat_candidates:
            parent_id = self._concat_candidates.pop(sample_id, None)
            self.sampleConcatCandidateChanged.emit(sample_id, False, None)
            # Si on supprime le "deuxieme" sample, le precedent peut etre libere
            # et normalise (sauf s'il est encore implique ailleurs).
            if parent_id is not None:
                self._unlock_and_maybe_normalize(parent_id)

        # Supprime les liens ou sample_id est "precedent".
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

        mode = "lufs"
        target_db = self.app_context.settings.getNormalizationLevel()
        worker = NormalizeWorker(
            sample_id=sample_id,
            file_path=samp.path,
            mode=mode,
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

# -----------------------------------------------------------------------------
# Worker de coherence DB/FS (thread Qt)
# -----------------------------------------------------------------------------
from PySide6.QtCore import QThread, Signal
import os, wave

class IntegrityCheckWorker(QThread):
    """Vérifie que la DB et les fichiers sont cohérents."""
    durationMismatch = Signal(int, float)   # (sample_id, new_duration)
    fileMissing      = Signal(int)          # sample_id

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context

    def run(self):
        session = SessionLocal()
        try:
            samples = session.query(Sample).all()
            for samp in samples:
                sid = samp.id
                path = samp.path
                # 1) Fichier manquant ?
                if not os.path.isfile(path):
                    self.fileMissing.emit(sid)
                    # ▶ Notification warning
                    self.app_context.notifications.notify(
                        title="⚠️ Fichier manquant",
                        message=f"Pour sample #{sid}, entrée supprimée",
                        type=NotificationType.WARNING
                    )
                    continue

                # 2) Vérifier la vraie durée
                try:
                    with wave.open(path, 'rb') as w:
                        real_dur = w.getnframes() / w.getframerate()
                except Exception:
                    continue

                # 3) Si écart > 0.1s, on corrige en DB
                if abs(real_dur - samp.duration) > 0.1:
                    session_inst = session.get(Sample, sid)
                    session_inst.duration = real_dur
                    session.commit()
                    self.durationMismatch.emit(sid, real_dur)
                    # ▶ Notification info
                    self.app_context.notifications.notify(
                        title="ℹ️ Durée corrigée",
                        message=f"Sample #{sid} → {real_dur:.1f}s",
                        type=NotificationType.INFO
                    )
        finally:
            session.close()
