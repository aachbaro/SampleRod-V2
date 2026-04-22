# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Worker Qt (QThread) de coherence DB/FS.
# - Verifie au demarrage que chaque sample en base existe encore sur disque et
#   que sa duree correspond bien au fichier reel.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal

from backend.db import SessionLocal
from backend.models.sample import Sample
from backend.services.audio_metadata import get_audio_duration
from backend.services.notification_service import NotificationType


class IntegrityCheckWorker(QThread):
    """Verifie que la DB et les fichiers sont coherents au demarrage."""

    durationMismatch = Signal(int, float)
    fileMissing = Signal(int, bool)

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context

    def run(self):
        session = SessionLocal()
        try:
            samples = session.query(Sample).all()
            for samp in samples:
                sid = samp.id
                path = samp.path

                if not os.path.isfile(path):
                    session_inst = session.get(Sample, sid)
                    if session_inst and not bool(session_inst.missing):
                        session_inst.missing = True
                        session.commit()
                    self.fileMissing.emit(sid, True)
                    self.app_context.notifications.notify(
                        title="Fichier manquant",
                        message=f"Sample #{sid} marque comme manquant",
                        type=NotificationType.WARNING,
                        popup=False,
                    )
                    continue

                session_inst = session.get(Sample, sid)
                if session_inst and bool(session_inst.missing):
                    session_inst.missing = False
                    session.commit()
                    self.fileMissing.emit(sid, False)

                try:
                    real_dur = get_audio_duration(path)
                except Exception:
                    continue

                if abs(real_dur - float(samp.duration or 0.0)) > 0.1:
                    session_inst = session.get(Sample, sid)
                    if session_inst:
                        session_inst.duration = real_dur
                        session.commit()
                    self.durationMismatch.emit(sid, real_dur)
                    self.app_context.notifications.notify(
                        title="Duree corrigee",
                        message=f"Sample #{sid} -> {real_dur:.1f}s",
                        type=NotificationType.INFO,
                        popup=False,
                    )
        finally:
            session.close()
