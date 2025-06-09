from PyQt6.QtCore import QObject, pyqtSignal
from sqlalchemy.exc import SQLAlchemyError
from backend.db import SessionLocal
from backend.models.sample import Sample
from backend.models.normalize_worker import NormalizeWorker

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