from sqlalchemy import Column, Integer, String
from sqlalchemy.sql import func
from backend.db import Base, SessionLocal
import os
from pathlib import Path
import logging
logger = logging.getLogger("SampleLibrary")

class SampleBank(Base):
    """Classe représentant une librairie de samples de l'utilisateur"""
    __tablename__ = "SampleBank"

    id = Column(Integer, primary_key=True)
    path = Column(String(200), nullable=False, unique=True)
    position = Column(Integer, nullable=False)

    def __init__(self, path: str):
        session = SessionLocal()
        session.expire_on_commit = False
        logger.info(f"Sample Bank: Initialisation avec {path}")

        path_resolved = str(Path(path).resolve())  # Conversion en chemin absolu

        # Vérification de l'existence et de la validité du chemin
        if not os.path.exists(path_resolved):
            raise ValueError("Le chemin spécifié n'existe pas.")
        if not os.path.isdir(path_resolved):
            raise ValueError("Le chemin spécifié n'est pas un dossier.")

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

        logger.info(f"Classe SampleBank: La librairie {self.path} a été ajoutée avec succès")

    def __repr__(self):
        return f"<SampleBank id={self.id}, position={self.position}, path={self.path}>"

    def to_dict(self):
        """
        Convertit l'instance en dictionnaire pour faciliter le transfert de données.
        """
        logger.info("SampleBank.to_dict")
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
        logger.info("Récupération des librairies depuis la base de données")
        with SessionLocal() as session:
            return session.query(SampleBank).order_by(SampleBank.position).all()
        
    @classmethod
    def delete_library(cls, library_id: int):
        """
        Supprime la librairie d'ID donné, et recalcule les positions
        pour que la suite reste continue (0,1,2,...).
        """
        with SessionLocal() as session:
            # 1) Récupère la librairie
            lib = session.query(cls).get(library_id)
            if not lib:
                raise ValueError(f"Library id={library_id} introuvable")

            deleted_pos = lib.position

            # 2) Supprime-la
            session.delete(lib)

            # 3) Décale la position de toutes celles après
            session.query(cls) \
                .filter(cls.position > deleted_pos) \
                .update({ cls.position: cls.position - 1 })

            # 4) Commit
            session.commit()

    @classmethod
    def reorder_libraries(cls, ordered_ids: list[int]):
        """
        Réordonne les SampleBank pour qu'elles aient
        les positions 0,1,2,… selon la liste d'IDs fournie.
        """
        with SessionLocal() as session:
            # On parcourt la liste d'IDs dans l'ordre désiré
            for new_pos, lib_id in enumerate(ordered_ids):
                session.query(cls) \
                       .filter(cls.id == lib_id) \
                       .update({ cls.position: new_pos })
            session.commit()