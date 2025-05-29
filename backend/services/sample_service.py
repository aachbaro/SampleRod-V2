from PyQt6.QtCore import QObject, pyqtSignal
from sqlalchemy.exc import SQLAlchemyError
from backend.db import SessionLocal
from backend.models.sample import Sample

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

    def __init__(self):
        super().__init__()
        print("[SampleService] Initialisation du service")
        # cache local de tous les échantillons
        self._samples = []
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
        except Exception as e:
            print(f"[SampleService] add error: {e}")
        # finally:
            # 5) Émission de la liste mise à jour
            # self.samplesChanged.emit(list(self._samples))

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