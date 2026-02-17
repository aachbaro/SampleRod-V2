# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Modele ORM des samples (table Sample).
# - Contient les operations fichier associees (rename/delete/move).
#
# LIENS CLES
# - backend/services/sample_service.py
# - frontend/sample_gui/sample/sample_card.py
# -----------------------------------------------------------------------------
# backend/models/sample.py

# /backend/models/sample.py

import os
import wave
import shutil
import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, func
from sqlalchemy.exc import SQLAlchemyError
from backend.db import Base, SessionLocal
import logging
logger = logging.getLogger("sample")


class Sample(Base):
    """Classe représentant un sample audio dans la base de données."""
    __tablename__ = "samples"

    id         = Column(Integer, primary_key=True, index=True)
    path       = Column(String(200), nullable=False, unique=True)
    name       = Column(String(100), nullable=False)
    duration   = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False)

    def __init__(self, path: str):
        # Extraction métadonnées
        self.path       = path
        self.name       = self._extract_name()
        self.duration   = self._extract_duration()
        self.created_at = self._extract_creation_date()

        # Enregistrement en base
        session = SessionLocal()
        session.expire_on_commit = False
        try:
            session.add(self)
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            raise
        finally:
            session.close()
        
        logger.info(f"[Sample] Création de l'échantillon {self.name} ({self.id})")

    def delete(self):
        """
        Supprime le fichier physique (s’il existe) puis
        l’entrée Base (commit ou rollback en cas d’erreur).
        """
        # 1) Fichier
        if os.path.isfile(self.path):
            try:
                os.remove(self.path)
                logger.info(f"[Sample] Fichier {self.path} supprimé")
            except OSError as e:
                # if you want to log: logger.info(f"[Sample.delete] remove error: {e}")
                logger.info(f"[Sample] Impossible de supprimer le fichier {self.path}: {e}")
                pass  # on continue : on supprime au moins la base

        # 2) Base
        session = SessionLocal()
        try:
            # recharger l’instance attachée à la session
            inst = session.get(Sample, self.id)
            if inst:
                session.delete(inst)
                session.commit()
                logger.info(f"[Sample] Échantillon {self.name} ({self.id}) supprimé de la base de données")
        except SQLAlchemyError:
            session.rollback()
            logger.info(f"[Sample] Erreur lors de la suppression de l'échantillon {self.name} ({self.id})")
            raise
        finally:
            session.close()

    def rename(self, new_name: str):
        """
        Renomme le fichier (même extension), met à jour path & name,
        et commit les changements en base.
        """
        folder, old_filename = os.path.split(self.path)
        ext = os.path.splitext(old_filename)[1]
        new_filename = new_name.strip() + ext
        new_path = os.path.join(folder, new_filename)

        # 1) Fichier
        try:
            os.rename(self.path, new_path)
            logger.info(f"[Sample] Renommage de {self.path} en {new_path}")
        except OSError as e:
            logger.info(f"[Sample] Erreur de renommage de {self.path} en {new_path}: {e}")
            raise RuntimeError(f"Impossible de renommer {self.path} → {new_path}: {e}")
        

        # 2) Base
        session = SessionLocal()
        try:
            inst = session.get(Sample, self.id)
            inst.path = new_path
            inst.name = new_name.strip()
            session.commit()
            # Mettre à jour l’objet courant aussi
            self.path = new_path
            self.name = new_name.strip()
            logger.info(f"[Sample] Échantillon renommé en {self.name} ({self.id})")
        except SQLAlchemyError as e:
            logger.info(f"[Sample] Erreur lors du renommage de l'échantillon {self.name} ({self.id}): {e}")
            session.rollback()
            # tenter de restaurer l’ancien nom de fichier
            try:
                os.rename(new_path, self.path)
            except Exception:
                pass
            raise
        finally:
            session.close()

    def move_to(self, target_folder: str):
        """
        Déplace physiquement le fichier dans `target_folder` puis met à jour
        `path` en base. Conserve le même nom de fichier.
        """
        os.makedirs(target_folder, exist_ok=True)
        basename = os.path.basename(self.path)
        new_path = os.path.join(target_folder, basename)

        # 1) Fichier
        try:
            shutil.move(self.path, new_path)
            logger.info(f"[Sample] Déplacement de {self.path} vers {new_path}")
        except (OSError, shutil.Error) as e:
            logger.info(f"[Sample] Erreur de déplacement de {self.path} vers {new_path}: {e}")
            raise RuntimeError(f"Impossible de déplacer {self.path} → {new_path}: {e}")

        # 2) Base
        session = SessionLocal()
        try:
            inst = session.get(Sample, self.id)
            inst.path = new_path
            session.commit()
            self.path = new_path
            logger.info(f"[Sample] Échantillon déplacé vers {self.path} ({self.id})")
        except SQLAlchemyError:
            logger.info(f"[Sample] Erreur lors du déplacement de l'échantillon {self.name} ({self.id}) vers {new_path}")
            session.rollback()
            # tenter de remettre à l’ancien emplacement
            try:
                shutil.move(new_path, self.path)
            except Exception:
                pass
            raise
        finally:
            session.close()

    def _extract_name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def _extract_duration(self) -> float:
        with wave.open(self.path, 'rb') as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()

    def _extract_creation_date(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(os.path.getctime(self.path))

    def __repr__(self):
        return (
            f"<Sample id={self.id} name={self.name!r} "
            f"duration={self.duration:.2f}s created_at={self.created_at}>"
        )

    @staticmethod
    def get_next_id() -> int:
        """Renvoie MAX(id)+1 ou 1 si vide."""
        session = SessionLocal()
        try:
            max_id = session.query(func.max(Sample.id)).scalar()
            return (max_id or 0) + 1
        finally:
            session.close()