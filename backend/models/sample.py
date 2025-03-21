# /backend/models/sample.py

import numpy as np
import wave
import os
import datetime
import base64
from . import db

class Sample(db.Model):
    """A class that stores data about a sample."""
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)


    def __init__(self, path: str):
        self.path = path
        self.created_at = self.get_creation_date()
        self.duration = self.extract_data_from_wav()
        self.name = self.extract_name_from_path()

        print("ajout du sample dans la base de donnee")
        db.session.add(self)
        db.session.commit()
        print("sample ajoute")

    def extract_name_from_path(self) -> str:
        """Extracts the name of the sample from its path."""
        file_name = os.path.basename(self.path)  # Cross-platform compatibility
        return os.path.splitext(file_name)[0]  # Remove the extension

    def extract_data_from_wav(self):
        """Extracts frame data and duration from a WAV file."""
        with wave.open(self.path, 'rb') as wav_file:
            framerate = wav_file.getframerate()
            nframes = wav_file.getnframes()
            duration = nframes / framerate
        return duration  # Store as binary data

    def get_creation_date(self) -> str:
        """Returns the creation date of the sample in the desired format."""
        creation_time = os.path.getctime(self.path)
        creation_time = datetime.datetime.fromtimestamp(creation_time)
        return creation_time

    def __repr__(self):
        return f"name: {self.path}\nduration: {self.duration}\ncreation date: {self.created_at}"
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.path,
            'length': self.duration,
            'date': self.created_at,
        }
    
    @staticmethod
    def get_all_samples():
        """
        Récupère toutes les instances de SampleBank depuis la base de données.
        """
        print("Récupération des samples depuis la base de données")
        return Sample.query.all()
    
    @staticmethod
    def rename_sample(sample_id: int, new_name: str):
        """
        Renomme un échantillon dans la base de données et le système de fichiers.
        Si le fichier n'est pas trouvé dans le système, supprime l'échantillon de la base de données et lève une exception.
        """
        # Récupérer le sample par son id
        sample = Sample.query.get(sample_id)
        if not sample:
            raise Exception(f"Sample with ID {sample_id} not found in the database.")

        # Récupérer le répertoire du fichier existant
        file_directory = os.path.dirname(sample.path)
        
        # Créer le nouveau chemin avec le nouveau nom
        new_path = os.path.join(file_directory, new_name + os.path.splitext(sample.path)[1])  # Garder le même suffixe (ex: .wav)

        # Vérifier si le fichier existe dans le système
        if os.path.exists(sample.path):
            # Renommer le fichier dans le système
            os.rename(sample.path, new_path)
            # Mettre à jour le nom et le chemin dans la base de données
            sample.name = new_name
            sample.path = new_path
            db.session.commit()
        else:
            # Si le fichier n'est pas trouvé, supprimer l'échantillon de la base de données
            db.session.delete(sample)
            db.session.commit()
            raise Exception(f"File {sample.path} not found in the system. Sample has been deleted from the database.")

    @staticmethod
    def delete_sample(sample_id: int):
        """
        Supprime un échantillon de la base de données et du système de fichiers de manière sécurisée.
        Si le fichier n'existe pas dans le système de fichiers, il supprime seulement l'entrée de la base de données.
        
        :param sample_id: ID de l'échantillon à supprimer.
        """
        print(f"Tentative de suppression du sample avec ID {sample_id}")

        # Récupérer l'échantillon par son ID
        sample = Sample.query.get(sample_id)
        if not sample:
            raise Exception(f"Sample avec ID {sample_id} introuvable dans la base de données.")

        # Vérifier si le fichier existe dans le système
        if os.path.exists(sample.path):
            try:
                # Supprimer le fichier du système
                os.remove(sample.path)
                print(f"Fichier {sample.path} supprimé du système de fichiers.")
            except Exception as e:
                raise Exception(f"Erreur lors de la suppression du fichier {sample.path}: {str(e)}")
        else:
            print(f"Fichier {sample.path} introuvable dans le système de fichiers. Suppression uniquement dans la base de données.")

        # Supprimer l'échantillon de la base de données
        try:
            db.session.delete(sample)
            db.session.commit()
            print(f"Sample avec ID {sample_id} supprimé de la base de données.")
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Erreur lors de la suppression du sample dans la base de données: {str(e)}")