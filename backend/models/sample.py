# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Modele ORM des samples (table Sample).
# - Contient les operations fichier associees (rename/delete/move).
#
# LIENS CLES
# - backend/services/sample_service.py
# - frontend/sample_gui/sample/sample_card.py
# -----------------------------------------------------------------------------

from __future__ import annotations

import datetime
import logging
import os
import shutil

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func
from sqlalchemy.exc import SQLAlchemyError

from backend.db import Base, SessionLocal
from backend.services.audio_metadata import collect_audio_file_metadata, normalize_audio_path

logger = logging.getLogger("sample")


class Sample(Base):
    """Classe representant un sample audio dans la base de donnees."""

    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String(200), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    duration = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False)
    missing = Column(Boolean, nullable=False, default=False, server_default="0")
    rms_level = Column(Float, nullable=True)
    analyzed_at = Column(DateTime, nullable=True)
    dominant_note = Column(String(4), nullable=True)
    scale_confidence = Column(Float, nullable=True)
    compatible_scales = Column(Text, nullable=True)  # JSON array of scale label strings

    def __init__(
        self,
        path: str,
        *,
        duration: float | None = None,
        created_at: datetime.datetime | None = None,
        rms_level: float | None = None,
        missing: bool = False,
        analyzed_at: datetime.datetime | None = None,
        dominant_note: str | None = None,
        scale_confidence: float | None = None,
        compatible_scales: str | None = None,
    ):
        normalized_path = normalize_audio_path(path)
        include_rms = rms_level is None and not missing
        metadata = None
        if duration is None or created_at is None or include_rms:
            metadata = collect_audio_file_metadata(normalized_path, include_rms=include_rms)

        self.path = normalized_path
        self.name = os.path.splitext(os.path.basename(normalized_path))[0]
        self.duration = float(duration if duration is not None else metadata.duration)
        self.created_at = created_at or metadata.created_at
        self.missing = bool(missing)
        self.rms_level = rms_level if rms_level is not None else metadata.rms_level
        self.analyzed_at = analyzed_at
        self.dominant_note = dominant_note
        self.scale_confidence = scale_confidence
        self.compatible_scales = compatible_scales

        session = SessionLocal()
        session.expire_on_commit = False
        try:
            session.add(self)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            raise
        finally:
            session.close()

        logger.info("[Sample] Creation de l'echantillon %s (%s)", self.name, self.id)

    def delete(self):
        """Supprime le fichier physique puis l'entree en base."""
        if os.path.isfile(self.path):
            try:
                os.remove(self.path)
                logger.info("[Sample] Fichier %s supprime", self.path)
            except OSError as exc:
                logger.info("[Sample] Impossible de supprimer le fichier %s: %s", self.path, exc)

        session = SessionLocal()
        try:
            inst = session.get(Sample, self.id)
            if inst:
                session.delete(inst)
                session.commit()
                logger.info("[Sample] Echantillon %s (%s) supprime", self.name, self.id)
        except SQLAlchemyError:
            session.rollback()
            logger.info("[Sample] Erreur lors de la suppression de %s (%s)", self.name, self.id)
            raise
        finally:
            session.close()

    def rename(self, new_name: str):
        """Renomme le fichier, puis met a jour le chemin et le nom en base."""
        folder, old_filename = os.path.split(self.path)
        ext = os.path.splitext(old_filename)[1]
        new_filename = new_name.strip() + ext
        new_path = normalize_audio_path(os.path.join(folder, new_filename))

        try:
            os.rename(self.path, new_path)
            logger.info("[Sample] Renommage de %s en %s", self.path, new_path)
        except OSError as exc:
            logger.info("[Sample] Erreur de renommage de %s en %s: %s", self.path, new_path, exc)
            raise RuntimeError(f"Impossible de renommer {self.path} -> {new_path}: {exc}")

        session = SessionLocal()
        try:
            inst = session.get(Sample, self.id)
            inst.path = new_path
            inst.name = new_name.strip()
            session.commit()
            self.path = new_path
            self.name = new_name.strip()
            logger.info("[Sample] Echantillon renomme en %s (%s)", self.name, self.id)
        except SQLAlchemyError:
            session.rollback()
            try:
                os.rename(new_path, self.path)
            except Exception:
                pass
            logger.info("[Sample] Erreur lors du renommage de %s (%s)", self.name, self.id)
            raise
        finally:
            session.close()

    def move_to(self, target_folder: str):
        """Deplace physiquement le fichier dans `target_folder` puis met a jour la base."""
        os.makedirs(target_folder, exist_ok=True)
        basename = os.path.basename(self.path)
        new_path = normalize_audio_path(os.path.join(target_folder, basename))

        try:
            shutil.move(self.path, new_path)
            logger.info("[Sample] Deplacement de %s vers %s", self.path, new_path)
        except (OSError, shutil.Error) as exc:
            logger.info("[Sample] Erreur de deplacement de %s vers %s: %s", self.path, new_path, exc)
            raise RuntimeError(f"Impossible de deplacer {self.path} -> {new_path}: {exc}")

        session = SessionLocal()
        try:
            inst = session.get(Sample, self.id)
            inst.path = new_path
            session.commit()
            self.path = new_path
            logger.info("[Sample] Echantillon deplace vers %s (%s)", self.path, self.id)
        except SQLAlchemyError:
            session.rollback()
            try:
                shutil.move(new_path, self.path)
            except Exception:
                pass
            logger.info("[Sample] Erreur lors du deplacement de %s (%s)", self.name, self.id)
            raise
        finally:
            session.close()

    @property
    def needs_analysis(self) -> bool:
        return not bool(self.missing) and self.analyzed_at is None

    def __repr__(self):
        return (
            f"<Sample id={self.id} name={self.name!r} duration={self.duration:.2f}s "
            f"missing={self.missing} created_at={self.created_at}>"
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
