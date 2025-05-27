# /backend/models/sample.py

from sqlalchemy import Column, Integer, String, Float, DateTime, func
from backend.db import Base, SessionLocal
import os
import wave
import datetime

class Sample(Base):
    """Classe représentant un sample audio dans la base de données."""
    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String(200), nullable=False)
    name = Column(String(100), nullable=False)
    duration = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False)

    def __init__(self, path: str):
        self.path = path
        self.created_at = self.get_creation_date()
        self.duration = self.extract_data_from_wav()
        self.name = self.extract_name_from_path()

        print("Ajout du sample dans la base de données")
        session = SessionLocal()  # Ouvrir une session
        session.add(self)
        session.commit()
        session.close()
        print("Sample ajouté")

    def extract_name_from_path(self) -> str:
        """Extrait le nom du fichier depuis le chemin."""
        file_name = os.path.basename(self.path)
        return os.path.splitext(file_name)[0]

    def extract_data_from_wav(self) -> float:
        """Extrait la durée d'un fichier WAV."""
        with wave.open(self.path, 'rb') as wav_file:
            framerate = wav_file.getframerate()
            nframes = wav_file.getnframes()
            return nframes / framerate

    def get_creation_date(self) -> datetime.datetime:
        """Récupère la date de création du fichier."""
        return datetime.datetime.fromtimestamp(os.path.getctime(self.path))

    def __repr__(self):
        return f"<Sample(name={self.name}, duration={self.duration}, created_at={self.created_at})>"

    @staticmethod
    def get_all_samples():
        """
        Récupère tous les samples depuis la base de données, triés par date de création.
        """
        print("Récupération des samples depuis la base de données")
        with SessionLocal() as session:
            return session.query(Sample).order_by(Sample.created_at).all()

    @staticmethod
    def delete_sample(sample_id: int):
        """
        Supprime un échantillon de la base de données et du système de fichiers de manière sécurisée.
        Si le fichier n'existe pas dans le système de fichiers, il supprime seulement l'entrée de la base de données.
        
        :param sample_id: ID de l'échantillon à supprimer.
        """
        print(f"Tentative de suppression du sample avec ID {sample_id}")
        
        with SessionLocal() as session:
            session.expire_on_commit = False
            sample = session.query(Sample).filter_by(id=sample_id).first()
            if not sample:
                print(f"Sample avec ID {sample_id} introuvable dans la base de données.")
                return
            
            # Vérifier si le fichier existe dans le système
            if os.path.exists(sample.path):
                try:
                    os.remove(sample.path)
                    print(f"Fichier {sample.path} supprimé du système de fichiers.")
                except Exception as e:
                    print(f"Erreur lors de la suppression du fichier {sample.path}: {str(e)}")
            else:
                print(f"Fichier {sample.path} introuvable dans le système de fichiers. Suppression uniquement dans la base de données.")
            
            # Supprimer l'échantillon de la base de données
            try:
                session.delete(sample)
                session.commit()
                print(f"Sample avec ID {sample_id} supprimé de la base de données.")
            except Exception as e:
                session.rollback()
                print(f"Erreur lors de la suppression du sample dans la base de données: {str(e)}")

    @staticmethod
    def get_next_id():
        """
        Retourne l'id que prendra le prochain Sample (MAX(id) + 1).
        Si la table est vide, renvoie 1.
        """
        session = SessionLocal()
        try:
            max_id = session.query(func.max(Sample.id)).scalar()
            return (max_id or 0) + 1
        finally:
            session.close()
    
    # @staticmethod
    # def rename_sample(sample_id: int, new_name: str):
    #     """
    #     Renomme un échantillon dans la base de données et le système de fichiers.
    #     Si le fichier n'est pas trouvé dans le système, supprime l'échantillon de la base de données et lève une exception.
    #     """
    #     # Récupérer le sample par son id
    #     sample = Sample.query.get(sample_id)
    #     if not sample:
    #         raise Exception(f"Sample with ID {sample_id} not found in the database.")

    #     # Récupérer le répertoire du fichier existant
    #     file_directory = os.path.dirname(sample.path)
        
    #     # Créer le nouveau chemin avec le nouveau nom
    #     new_path = os.path.join(file_directory, new_name + os.path.splitext(sample.path)[1])  # Garder le même suffixe (ex: .wav)

    #     # Vérifier si le fichier existe dans le système
    #     if os.path.exists(sample.path):
    #         # Renommer le fichier dans le système
    #         os.rename(sample.path, new_path)
    #         # Mettre à jour le nom et le chemin dans la base de données
    #         sample.name = new_name
    #         sample.path = new_path
    #         db.session.commit()
    #     else:
    #         # Si le fichier n'est pas trouvé, supprimer l'échantillon de la base de données
    #         db.session.delete(sample)
    #         db.session.commit()
    #         raise Exception(f"File {sample.path} not found in the system. Sample has been deleted from the database.")
