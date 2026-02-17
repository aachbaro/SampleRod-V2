# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service de gestion des dossiers/samples cote backend.
# - Liste, deplace, supprime et prepare les actions DnD de fichiers.
#
# LIENS CLES
# - frontend/right_panel/directory/directory_widget.py
# - backend/services/sample_service.py
# -----------------------------------------------------------------------------
# backend/services/directory_service.py

import os
import shutil
import pickle
import numpy as np
import soundfile as sf
import logging
logger = logging.getLogger("directory_service")

from PyQt6.QtCore import QMimeData
from backend.services.sample_service import SampleService

class DirectoryService:
    """Service utilitaire pour importer des fichiers dans un dossier."""

    def __init__(self, sample_service: SampleService):
        # sample_service correspond au même store que celui utilisé
        # par le WaveformWidget (méthode .add())
        self.sample_store = sample_service
        logger.info("[DirectoryService] Initialisation du service")

    def list_samples(self, folder: str) -> list[str]:
        """Return list of file names inside folder."""
        if not os.path.isdir(folder):
            logger.info(f"[DirectoryService] Dossier introuvable: {folder}")
            return []
        files = sorted(
            f for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
        )
        logger.info(f"[DirectoryService] {len(files)} fichiers listés dans {folder}")
        return files

    def handle_drop(self, folder: str, mime: QMimeData) -> None:
        """Handle drop event with custom MIME data."""
        logger.info(f"[DirectoryService] Dépôt dans {folder}")
        os.makedirs(folder, exist_ok=True)

        for fmt in ("application/x-sample-slice-data", "application/x-sample-card"):
            if not mime.hasFormat(fmt):
                continue

            # Essaie de dépickle
            try:
                payload = pickle.loads(bytes(mime.data(fmt)))
            except Exception:
                payload = None

            # Si c'est un dict picklé, on traite slice ou sample
            if isinstance(payload, dict):
                if "audio_data" in payload:
                    logger.info("[DirectoryService] Sauvegarde d'une slice depuis le drag&drop")
                    self._save_slice(folder, payload)
                elif "sample_id" in payload:
                    logger.info("[DirectoryService] Copie d'un sample depuis le drag&drop")
                    self._copy_sample(folder, payload["sample_id"])
                return  # on sort après traitement

            # Fallback : anciens formats texte (chemins)
            data = bytes(mime.data(fmt)).decode(errors="ignore")
            for line in filter(None, data.splitlines()):
                src = line.strip()
                if os.path.isfile(src):
                    dst = os.path.join(folder, os.path.basename(src))
                    try:
                        shutil.copy(src, dst)
                        # Création de l'entrée en base identique à l'export Waveform
                        self.sample_store.add(dst)
                        logger.info(f"[DirectoryService] Fichier copié {src} -> {dst}")
                    except Exception:
                        pass

    # ------------------------------------------------------------------ utils
    def _save_slice(self, folder: str, payload: dict):
        arr = np.asarray(payload.get("audio_data"), dtype="float32")
        sr = int(payload.get("sample_rate", 44100))
        name = payload.get("name", "slice")
        if not name.lower().endswith(".wav"):
            name += ".wav"
        dest = os.path.join(folder, name)

        # Évite les doublons
        base, ext = os.path.splitext(dest)
        idx = 1
        while os.path.exists(dest):
            dest = f"{base}_{idx}{ext}"
            idx += 1

        try:
            sf.write(dest, arr, sr)
            # Ajout en base pour le nouveau fichier
            self.sample_store.add(dest)
            logger.info(f"[DirectoryService] Slice enregistrée : {dest}")
        except Exception as e:
            logger.info(f"[DirectoryService] save slice error: {e}")

    def _copy_sample(self, folder: str, sample_id: int):
        sample = self.sample_store._get(sample_id)
        if not sample:
            return
        src = sample.path
        dest = os.path.join(folder, os.path.basename(src))

        # Évite les doublons
        base, ext = os.path.splitext(dest)
        idx = 1
        while os.path.exists(dest):
            dest = f"{base}_{idx}{ext}"
            idx += 1

        try:
            shutil.copy(src, dest)
            # Ajout en base pour le fichier copié
            self.sample_store.add(dest)
            logger.info(f"[DirectoryService] Sample copié : {src} -> {dest}")
        except Exception as e:
            logger.info(f"[DirectoryService] copy sample error: {e}")
