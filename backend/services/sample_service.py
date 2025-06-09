from PyQt6.QtCore import QObject, pyqtSignal
from sqlalchemy.exc import SQLAlchemyError
from backend.db import SessionLocal
from backend.models.sample import Sample
from backend.models.normalize_worker import NormalizeWorker
from backend.services.notification_service import NotificationType

class SampleService(QObject):
    """
    Service Qt pour gérer les Samples avec cache en mémoire.
    - load_all()       : charge une fois et émet la liste complète
    - delete(id)       : supprime un sample (fichier + BD)
    - rename(id, name) : renomme un sample (fichier + BD)
    - move(id, folder) : déplace un sample (fichier + BD)
    Émet des signaux pour permettre à l’UI de se mettre à jour.
    """
    sampleAdded = pyqtSignal(int)            # émet l’ID du sample ajouté
    samplesChanged = pyqtSignal(list)        # émet la liste complète des Sample
    sampleDeleted  = pyqtSignal(int)         # émet l’ID supprimé
    sampleRenamed  = pyqtSignal(int, str)    # émet (ID, nouveau nom)
    sampleMoved    = pyqtSignal(int, str)    # émet (ID, nouveau dossier)
    sampleStartedNormalization  = pyqtSignal(int)      # émet l’ID du sample en cours de normalisation
    sampleFinishedNormalization = pyqtSignal(int)       # émet l’ID du sample normalisé
    sampleNormalizationFailed   = pyqtSignal(int, str)  # émet (ID, message d’erreur)
    sampleRemovedFromHistory = pyqtSignal(int)          # émet l’ID du sample retiré de l’historique

    def __init__(self, app_context):
        super().__init__()
        print("[SampleService] Initialisation du service")
        # cache local de tous les échantillons
        self._samples = []
        self._normalize_threads = {}
        self.app_context = app_context

        # chargement initial
        self._initialize_cache()

        # ─── Lancement du worker de cohérence ───
        # supprime automatiquement de la base les samples dont le fichier est manquant
        self._integrity_worker = IntegrityCheckWorker()
        # branchement : quand le worker détecte un fichier manquant, 
        # on retire directement l’entrée en base (sans toucher au fichier)
        self._integrity_worker.fileMissing.connect(self.removeFromHistory)
        # (optionnel) gérer les durations incohérentes
        self._integrity_worker.durationMismatch.connect(
            lambda sid, d: print(f"[Integrity] Durée corrigée for sample {sid} → {d:.2f}s")
        )
        self._integrity_worker.start()

    def _initialize_cache(self):
        """Charge les samples depuis la BDD et émet samplesChanged."""
        
        try:
            with SessionLocal() as session:
                self._samples = session.query(Sample).order_by(Sample.id).all()
        except SQLAlchemyError as e:
            print(f"[SampleService] init load error: {e}")
            self._samples = []
        finally:
            self.samplesChanged.emit(list(self._samples))

    def load_all(self):
        """Force le rechargement complet depuis la BDD et émet samplesChanged."""
        self._initialize_cache()

    def get_cached(self):
        """Retourne la liste courante en mémoire."""
        return list(self._samples)
    
    def add(self, path: str):
        """
        Crée un nouveau sample (FS + BD), met à jour le cache,
        et émet sampleAdded + samplesChanged.
        """
        try:
            # 1) Création via le modèle : enregistre le fichier et la BD
            new_sample = Sample(path)

            # Envoie d’une notification à l’utilisateur
            # On affiche le nom, la durée (arrondie à 1 décimale) et le chemin complet
            self.app_context.notifications.notify(
                title="📥 Nouveau sample ajouté",
                message=(
                    f"{new_sample.name} — {new_sample.duration:.1f}s\n"
                    f"Emplacement : {new_sample.path}"
                ),
                type=NotificationType.SUCCESS
            )
            # ─────────────

            # 2) Mise à jour du cache
            self._samples.append(new_sample)
            # 3) Optionnel : tri du cache par ID croissant
            self._samples.sort(key=lambda s: s.id)
            # 4) Émission du signal d'ajout
            self.sampleAdded.emit(new_sample.id)

            if self.app_context.settings.isAutoNormalizeEnabled():
                mode      = "lufs"
                target_db = self.app_context.settings.getNormalizationLevel()
                worker = NormalizeWorker(
                    sample_id=new_sample.id,
                    file_path=path,
                    mode=mode,
                    target_db=target_db
                )
                # on relaye directement sur nos signaux :
                worker.startedNormalization.connect(self.sampleStartedNormalization)
                worker.finishedNormalization.connect(self.sampleFinishedNormalization)
                worker.normalizationFailed .connect(self._onNormalizationFailed)
                worker.start()
                # on conserve la référence pour éviter que le thread ne soit détruit
                self._normalize_threads[new_sample.id] = worker


        except Exception as e:
            print(f"[SampleService] add error: {e}")
        finally:
            # 5) Émission de la liste mise à jour
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
            # 2) Suppression (FS + BD)
            samp.delete()
            # 3) Mise à jour du cache en mémoire
            self._samples = [s for s in self._samples if s.id != sample_id]
            # 4) Émission du signal de suppression pour l’UI
            self.sampleDeleted.emit(sample_id)
        except Exception as e:
            print(f"[SampleService] delete error: {e}")
        finally:
            # 5) Toujours ré-émettre la liste complète
            self.samplesChanged.emit(list(self._samples))

    def rename(self, sample_id: int, new_name: str):
        """
        Renomme le sample (FS + BD), met à jour le cache, et émet sampleRenamed + samplesChanged.
        """
        samp = next((s for s in self._samples if s.id == sample_id), None)
        if not samp:
            return
        try:
            samp.rename(new_name)
            samp.name = new_name
            # samp.path mis à jour dans samp.rename()
            self.sampleRenamed.emit(sample_id, new_name)
        except Exception as e:
            print(f"[SampleService] rename error: {e}")
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
        except Exception as e:
            print(f"[SampleService] move error: {e}")
        finally:
            self.samplesChanged.emit(list(self._samples))

    def _get(self, sample_id: int):
        """Retourne l’instance en cache ou None."""
        return next((s for s in self._samples if s.id == sample_id), None)
    
    def _onNormalizationFailed(self, sample_id: int, message: str):
        # Réémet le signal vers l’UI
        self.sampleNormalizationFailed.emit(sample_id, message)

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
            # 3) Mise à jour du cache en mémoire
            self._samples = [s for s in self._samples if s.id != sample_id]
            # 4) Signaux
            self.sampleRemovedFromHistory.emit(sample_id)
        except Exception as e:
            print(f"[SampleService] removeFromHistory error: {e}")
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

        # 1) Stopper la lecture si l’un des samples est en cours
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
                    print(f"[SampleService] Fichier {samp.path} supprimé")

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

            # 5) Émettre sampleDeleted pour chaque ID (pour fermer les waveforms)
            for sample_id in sample_ids:
                self.sampleDeleted.emit(sample_id)
        except Exception as e:
            print(f"[SampleService] bulkDelete error: {e}")
        finally:
            # 6) N’émettre qu’UN SEUL samplesChanged à la fin
            self.samplesChanged.emit(list(self._samples))




from PyQt6.QtCore import QThread, pyqtSignal
import os, wave

class IntegrityCheckWorker(QThread):
    """Vérifie que la DB et les fichiers sont cohérents."""
    durationMismatch = pyqtSignal(int, float)   # (sample_id, new_duration)
    fileMissing      = pyqtSignal(int)          # sample_id

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
        finally:
            session.close()