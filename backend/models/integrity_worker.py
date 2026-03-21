# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Worker Qt (QThread) de coherence DB/FS.
# - Lance au demarrage pour verifier que chaque sample en base a son fichier
#   sur disque et que sa duree enregistree est correcte.
#
# SIGNAUX EMIS
# - fileMissing(int)           : l'entree DB est supprimee par SampleService
# - durationMismatch(int,float): la duree est corrigee en base
# -----------------------------------------------------------------------------

import os
import wave

from PySide6.QtCore import QThread, Signal

from backend.db import SessionLocal
from backend.models.sample import Sample
from backend.services.notification_service import NotificationType


class IntegrityCheckWorker(QThread):
    """Verifie que la DB et les fichiers sont coherents au demarrage."""

    durationMismatch = Signal(int, float)   # (sample_id, new_duration)
    fileMissing      = Signal(int)          # sample_id

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context

    def run(self):
        session = SessionLocal()
        try:
            samples = session.query(Sample).all()
            for samp in samples:
                sid  = samp.id
                path = samp.path

                # 1) Fichier manquant ?
                if not os.path.isfile(path):
                    self.fileMissing.emit(sid)
                    self.app_context.notifications.notify(
                        title="⚠️ Fichier manquant",
                        message=f"Pour sample #{sid}, entrée supprimée",
                        type=NotificationType.WARNING,
                    )
                    continue

                # 2) Verifier la vraie duree
                try:
                    with wave.open(path, "rb") as w:
                        real_dur = w.getnframes() / w.getframerate()
                except Exception:
                    continue

                # 3) Si ecart > 0.1s, corriger en DB
                if abs(real_dur - samp.duration) > 0.1:
                    session_inst = session.get(Sample, sid)
                    session_inst.duration = real_dur
                    session.commit()
                    self.durationMismatch.emit(sid, real_dur)
                    self.app_context.notifications.notify(
                        title="ℹ️ Durée corrigée",
                        message=f"Sample #{sid} → {real_dur:.1f}s",
                        type=NotificationType.INFO,
                    )
        finally:
            session.close()
