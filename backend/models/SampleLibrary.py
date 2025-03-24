from sqlalchemy import Column, Integer, String
from sqlalchemy.sql import func
from backend.db import Base, SessionLocal
import os
from pathlib import Path

class SampleBank(Base):
    """Classe représentant une librairie de samples de l'utilisateur"""
    __tablename__ = "SampleBank"

    id = Column(Integer, primary_key=True)
    path = Column(String(200), nullable=False, unique=True)
    position = Column(Integer, nullable=False)

    def __init__(self, path: str):
        session = SessionLocal()
        session.expire_on_commit = False
        print(f"Sample Bank: Initialisation avec {path}")

        path_resolved = str(Path(path).resolve())  # Conversion en chemin absolu

        # Vérification de l'existence et de la validité du chemin
        if not os.path.exists(path_resolved):
            raise ValueError("Le chemin spécifié n'existe pas.")
        if not os.path.isdir(path_resolved):
            raise ValueError("Le chemin spécifié n'est pas un dossier.")

        # Ouverture de la session pour les requêtes SQLAlchemy
        # Vérification de l'existence dans la base de données
        existing_library = session.query(SampleBank).filter_by(path=path_resolved).first()
        if existing_library:
            raise ValueError("Cette librairie existe déjà dans la base de données.")

        self.path = path_resolved

        # Déterminer la position maximale
        max_position = session.query(func.max(SampleBank.position)).scalar()
        self.position = 0 if max_position is None else max_position + 1

        session.add(self)
        session.commit()
        session.close()

        print(f"Classe SampleBank: La librairie {self.path} a été ajoutée avec succès")

    def __repr__(self):
        return f"<SampleBank id={self.id}, position={self.position}, path={self.path}>"

    def to_dict(self):
        """
        Convertit l'instance en dictionnaire pour faciliter le transfert de données.
        """
        print("SampleBank.to_dict")
        return {
            'id': self.id,
            'path': self.path,
            'position': self.position,
        }

    @staticmethod
    def get_all_libraries():
        """
        Récupère toutes les instances de SampleBank depuis la base de données,
        triées par position.
        """
        print("Récupération des librairies depuis la base de données")
        with SessionLocal() as session:
            return session.query(SampleBank).order_by(SampleBank.position).all()
    
    # @staticmethod
    # def add_sample_library(path: str):
    #     path_resolved = str(Path(path).resolve())
    #     if not os.path.exists(path_resolved):
    #         raise ValueError("Le chemin spécifié n'existe pas.")
    #     if not os.path.isdir(path_resolved):
    #         raise ValueError("Le chemin spécifié n'est pas un dossier.")
        
    #     with SessionLocal() as session:
    #         existing_library = session.query(SampleBank).filter_by(path=path_resolved).first()
    #         if existing_library:
    #             raise ValueError("Cette librairie existe déjà dans la base de données.")
            
    #         # Crée et ajoute la librairie
    #         new_library = SampleBank(path=path_resolved)
    #         session.add(new_library)
    #         session.commit()
            
    #     return new_library

    # @staticmethod
    # def delete_library_by_id(library_id):
    #     """
    #     Supprime une librairie de la base de données à partir de son ID, puis
    #     réaffecte les positions pour que l'ordre reste séquentiel.
    #     """
    #     print(f"SampleBank: Tentative de suppression de la librairie avec ID {library_id}")
    #     library = SampleBank.query.get(library_id)
    #     if not library:
    #         raise ValueError("La librairie spécifiée n'existe pas dans la base de données.")

    #     db.session.delete(library)
    #     db.session.commit()
    #     print(f"SampleBank: Librairie avec ID {library_id} supprimée avec succès.")

    #     # Réaffecte les positions pour que l'ordre reste séquentiel
    #     SampleBank.reassign_positions()

    # @staticmethod
    # def reassign_positions():
    #     """
    #     Réaffecte les positions de toutes les librairies de façon séquentielle
    #     (0, 1, 2, ...).
    #     """
    #     libraries = SampleBank.query.order_by(SampleBank.position).all()
    #     for index, lib in enumerate(libraries):
    #         lib.position = index
    #     db.session.commit()
    #     print("Positions réaffectées avec succès.")

    # @staticmethod
    # def update_positions(new_order):
    #     """
    #     Met à jour les positions des librairies en fonction d'une nouvelle commande.
    #     :param new_order: Liste d'IDs dans l'ordre souhaité.
    #     """
    #     for pos, lib_id in enumerate(new_order):
    #         library = SampleBank.query.get(lib_id)
    #         if library:
    #             library.position = pos
    #     db.session.commit()
    #     print("Positions mises à jour avec succès.")