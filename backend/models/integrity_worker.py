# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - "Inspecteur" lance au demarrage, dans un fil d'execution separe (QThread)
#   pour ne pas ralentir l'ouverture de l'application.
# - Compare ce que dit la base de donnees avec la realite du disque dur :
#   * un sample dont le fichier a disparu est marque "missing" (et inversement,
#     un fichier revenu est de-marque) ;
#   * une duree en base qui ne correspond plus au fichier reel est corrigee
#     (ex : le fichier a ete edite par un autre logiciel).
# - Previent le reste de l'application par signaux Qt + notifications.
#
# CLASSE ET FONCTIONS (sommaire)
# - IntegrityCheckWorker (QThread)
#   - signaux : durationMismatch(id, duree), fileMissing(id, manquant)
#   - run() : parcourt tous les samples et applique les verifications.
#
# LIENS CLES
# - backend/services/sample_service.py : lance ce worker au demarrage.
# - backend/models/sample.py           : la table verifiee.
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
        """Parcourt tous les samples et verifie fichier present + duree exacte.

        Cette methode s'execute dans le thread secondaire (c'est Qt qui
        l'appelle quand on fait worker.start()). Pour chaque sample :
        1. le fichier existe-t-il encore ? sinon -> marque "missing" ;
        2. s'il etait marque manquant mais est revenu -> on retire la marque ;
        3. la duree stockee correspond-elle au fichier (a 0,1 s pres) ?
           sinon -> on corrige la base et on previent l'interface.
        """
        session = SessionLocal()
        try:
            samples = session.query(Sample).all()
            for samp in samples:
                sid = samp.id
                path = samp.path

                # Cas 1 : le fichier a disparu du disque.
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

                # Cas 2 : le fichier etait marque manquant mais est revenu
                # (disque externe rebranche, fichier restaure...).
                session_inst = session.get(Sample, sid)
                if session_inst and bool(session_inst.missing):
                    session_inst.missing = False
                    session.commit()
                    self.fileMissing.emit(sid, False)

                # Cas 3 : verification de la duree reelle du fichier.
                try:
                    real_dur = get_audio_duration(path)
                except Exception:
                    # Fichier illisible : on passe au suivant sans bloquer.
                    continue

                # Tolerance de 0,1 s pour eviter de "corriger" des ecarts
                # d'arrondi sans importance.
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
