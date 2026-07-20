# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Decrit la table "samples" : chaque ligne represente UN fichier audio connu
#   de l'application (chemin, nom, duree, date, resultats d'analyse...).
# - Regle d'or de ce fichier : le disque d'abord, la base ensuite. Chaque
#   operation (supprimer, renommer, deplacer) agit sur le fichier physique
#   PUIS met a jour la base ; en cas d'echec en base, le fichier est remis
#   dans son etat d'origine (rollback) pour que les deux restent synchros.
#
# CLASSE ET FONCTIONS (sommaire)
# - Sample (une ligne de la table = un fichier audio)
#   - colonnes principales : id, path, name, duration, created_at, missing
#     (fichier introuvable sur le disque), rms_level (volume moyen)
#   - colonnes d'analyse musicale : dominant_note (note dominante),
#     detected_scale_label/kind (gamme detectee), scale_confidence,
#     compatible_scales (gammes compatibles, stockees en JSON)
#   - __init__()        : lit les metadonnees du fichier et l'enregistre en base.
#   - delete()          : supprime le fichier du disque puis la ligne en base.
#   - rename()          : renomme le fichier puis met a jour la base.
#   - move_to()         : deplace le fichier dans un autre dossier.
#   - needs_analysis    : dit si le sample attend encore son analyse de gamme.
#   - get_next_id()     : prochain identifiant disponible.
#
# LIENS CLES
# - backend/services/sample_service.py   : service qui gere le cache des samples.
# - backend/services/audio_metadata.py   : lecture duree / volume / date.
# - frontend/sample_gui/sample/sample_card.py : la carte qui affiche un sample.
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
    detected_scale_label = Column(String(64), nullable=True)
    detected_scale_kind = Column(String(16), nullable=True)
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
        detected_scale_label: str | None = None,
        detected_scale_kind: str | None = None,
        scale_confidence: float | None = None,
        compatible_scales: str | None = None,
    ):
        """Enregistre un nouveau sample en base a partir d'un chemin de fichier.

        Les informations non fournies (duree, date de creation, volume RMS)
        sont lues directement dans le fichier audio. Le nom affiche est
        deduit du nom de fichier, sans son extension.
        """
        normalized_path = normalize_audio_path(path)
        # On ne va lire le fichier que si une info nous manque (et on ne
        # calcule pas le volume d'un fichier marque comme introuvable).
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
        self.detected_scale_label = detected_scale_label
        self.detected_scale_kind = detected_scale_kind
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
        """Supprime le fichier physique puis l'entree en base.

        Si le fichier ne peut pas etre efface (deja absent, verrouille par
        un autre programme...), on le note dans les logs mais on supprime
        quand meme la ligne en base : le sample disparait de l'application.
        """
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
        """Renomme le fichier sur le disque, puis met a jour la base.

        L'extension (.wav, .mp3...) est conservee automatiquement :
        l'utilisateur ne tape que le nouveau nom. Si la mise a jour en base
        echoue, le fichier est renomme en sens inverse pour annuler.
        """
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
            # La base a refuse : on remet le fichier a son ancien nom pour
            # que disque et base restent d'accord.
            try:
                os.rename(new_path, self.path)
            except Exception:
                pass
            logger.info("[Sample] Erreur lors du renommage de %s (%s)", self.name, self.id)
            raise
        finally:
            session.close()

    def move_to(self, target_folder: str):
        """Deplace le fichier dans `target_folder` puis met a jour la base.

        Utilise par le glisser-deposer vers un dossier de librairie. Le
        dossier cible est cree s'il n'existe pas. Comme pour rename(), un
        echec en base annule le deplacement physique.
        """
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
        """Vrai si le sample attend encore son analyse musicale (gamme/note).

        Un sample doit etre analyse s'il n'a jamais ete analyse
        (analyzed_at vide) et que son fichier est bien present sur le disque.
        """
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
