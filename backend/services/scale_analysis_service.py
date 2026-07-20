# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Analyse MUSICALE des samples : quelle est la note dominante ? dans quelle
#   gamme (Do majeur, La mineur...) le sample sonne-t-il ? avec quelles autres
#   gammes est-il compatible ? Ces infos servent ensuite a filtrer/assortir
#   les samples entre eux.
# - Fonctionne comme un guichet : les demandes s'empilent dans une file
#   d'attente, et UN SEUL thread de fond les traite une par une (l'analyse
#   est gourmande, en lancer plusieurs en parallele saturerait la machine).
# - Chaque resultat est ecrit directement en base (note, gamme, confiance,
#   gammes compatibles en JSON, date d'analyse), puis l'UI est prevenue.
# - Le calcul lui-meme vit dans prototypes/scale_detector/analyzer.py.
#
# CLASSES ET FONCTIONS (sommaire)
# - _ScaleAnalysisWorker (QThread)
#   - run()      : boucle infinie "prendre une tache -> l'analyser",
#                  jusqu'a reception du signal d'arret (None dans la file).
#   - _analyze() : analyse UN sample et ecrit le resultat en base.
#   - stop()     : demande l'arret (glisse un None dans la file).
# - ScaleAnalysisService (QObject) : la facade publique
#   - signaux : scaleAnalysisQueued / Started / Complete / Failed.
#   - enqueue()  : ajoute un sample a la file (non bloquant).
#   - shutdown() : arret propre du thread (attend 5 s max).
#   - _on_started/_on_complete/_on_failed : relais worker -> signaux publics.
#
# LIENS CLES
# - backend/services/sample_service.py    : remplit la file et ecoute les signaux.
# - backend/models/sample.py              : colonnes remplies par l'analyse.
# - prototypes/scale_detector/analyzer.py : l'algorithme de detection.
# -----------------------------------------------------------------------------

from __future__ import annotations

import datetime
import json
import logging
import queue

from PySide6.QtCore import QObject, QThread, Signal
from sqlalchemy.exc import SQLAlchemyError

from backend.db import SessionLocal
from backend.models.sample import Sample

logger = logging.getLogger("scale_analysis_service")

_TOP_N = 5  # nombre de gammes candidates a conserver


class _ScaleAnalysisWorker(QThread):
    """Thread de fond qui depile et traite les samples en attente d'analyse."""

    analysisStarted = Signal(int, str)    # sample_id, path
    analysisComplete = Signal(int)   # sample_id
    analysisFailed = Signal(int, str)  # sample_id, error message

    def __init__(self, task_queue: queue.Queue, parent: QObject | None = None):
        super().__init__(parent)
        self._queue = task_queue
        self._running = True

    def stop(self):
        """Demande l'arret du thread.

        Le thread est peut-etre bloque en attente sur la file : on y glisse
        un None ("poison pill") pour le reveiller et le faire sortir.
        """
        self._running = False
        # Poison pill pour debloquer le get()
        self._queue.put(None)

    def run(self):
        """Boucle du thread : depile et analyse les samples un par un."""
        logger.info("[ScaleAnalysisWorker] Thread demarre")
        while self._running:
            item = self._queue.get()
            if item is None:
                break
            sample_id, path = item
            try:
                self._analyze(sample_id, path)
            except Exception as exc:
                logger.warning("[ScaleAnalysisWorker] Erreur inattendue id=%s: %s", sample_id, exc)
                self.analysisFailed.emit(sample_id, str(exc))
        logger.info("[ScaleAnalysisWorker] Thread arrete")

    def _analyze(self, sample_id: int, path: str) -> None:
        """Analyse un sample et enregistre le resultat en base.

        Chaque type d'echec (dependance absente, fichier introuvable, audio
        trop court/silencieux, erreur DB) emet analysisFailed avec un
        message clair, sans jamais faire tomber le thread : la file continue.
        """
        self.analysisStarted.emit(sample_id, path)
        logger.info("[ScaleAnalysisWorker] Debut analyse id=%s path=%s", sample_id, path)
        try:
            # Import local pour ne pas bloquer le demarrage si librosa est absent.
            from prototypes.scale_detector.analyzer import analyze_file  # noqa: PLC0415
        except ImportError as exc:
            logger.warning("[ScaleAnalysisWorker] Dependance manquante: %s", exc)
            self.analysisFailed.emit(sample_id, str(exc))
            return

        try:
            result = analyze_file(path, top_n=_TOP_N)
        except FileNotFoundError:
            logger.warning("[ScaleAnalysisWorker] Fichier introuvable id=%s path=%s", sample_id, path)
            self.analysisFailed.emit(sample_id, f"File not found: {path}")
            return
        except ValueError as exc:
            # Audio trop court / silencieux
            logger.info("[ScaleAnalysisWorker] Audio non analysable id=%s: %s", sample_id, exc)
            self.analysisFailed.emit(sample_id, str(exc))
            return
        except Exception as exc:
            logger.warning("[ScaleAnalysisWorker] Erreur analyse id=%s: %s", sample_id, exc)
            self.analysisFailed.emit(sample_id, str(exc))
            return

        # Extraction des resultats : note dominante, gamme principale
        # (label + type majeur/mineur), score de confiance, et la liste des
        # gammes compatibles convertie en JSON pour le stockage en base.
        dominant_note = result.dominant_note
        detected_scale_label = str(getattr(result, "label", "") or "").strip() or None
        detected_scale_kind = str(getattr(result, "kind", "") or "").strip() or None
        scale_confidence = float(result.confidence)
        compatible_scales_list = [c.label for c in result.candidates]
        compatible_scales_json = json.dumps(compatible_scales_list)

        # Ecriture en base
        session = SessionLocal()
        try:
            inst = session.get(Sample, sample_id)
            if inst is None:
                logger.warning("[ScaleAnalysisWorker] Sample id=%s introuvable en base", sample_id)
                return
            inst.dominant_note = dominant_note
            inst.detected_scale_label = detected_scale_label
            inst.detected_scale_kind = detected_scale_kind
            inst.scale_confidence = scale_confidence
            inst.compatible_scales = compatible_scales_json
            inst.analyzed_at = datetime.datetime.now()
            session.commit()
            logger.info(
                "[ScaleAnalysisWorker] Analyse enregistree id=%s note=%s label=%s kind=%s confidence=%.3f scales=%s",
                sample_id,
                dominant_note,
                detected_scale_label,
                detected_scale_kind,
                scale_confidence,
                compatible_scales_list,
            )
        except SQLAlchemyError as exc:
            session.rollback()
            logger.warning("[ScaleAnalysisWorker] Erreur DB id=%s: %s", sample_id, exc)
            self.analysisFailed.emit(sample_id, str(exc))
            return
        finally:
            session.close()

        self.analysisComplete.emit(sample_id)


class ScaleAnalysisService(QObject):
    """
    Service public: file d'attente + thread unique.

    Usage:
        service.enqueue(sample_id, path)
    """

    scaleAnalysisQueued = Signal(int, str)    # sample_id, path
    scaleAnalysisStarted = Signal(int, str)   # sample_id, path
    scaleAnalysisComplete = Signal(int)   # sample_id
    scaleAnalysisFailed = Signal(int, str)  # sample_id, reason

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._worker = _ScaleAnalysisWorker(self._queue, self)
        self._worker.analysisStarted.connect(self._on_started)
        self._worker.analysisComplete.connect(self._on_complete)
        self._worker.analysisFailed.connect(self._on_failed)
        self._worker.start()
        logger.info("[ScaleAnalysisService] Service demarre")

    def enqueue(self, sample_id: int, path: str) -> None:
        """Enfile un sample pour analyse. Non bloquant."""
        logger.info("[ScaleAnalysisService] Enqueue id=%s", sample_id)
        self.scaleAnalysisQueued.emit(sample_id, path)
        self._queue.put((sample_id, path))

    def shutdown(self) -> None:
        """Arret propre du thread de fond."""
        self._worker.stop()
        self._worker.wait(5000)

    def _on_complete(self, sample_id: int) -> None:
        self.scaleAnalysisComplete.emit(sample_id)

    def _on_started(self, sample_id: int, path: str) -> None:
        self.scaleAnalysisStarted.emit(sample_id, path)

    def _on_failed(self, sample_id: int, reason: str) -> None:
        self.scaleAnalysisFailed.emit(sample_id, reason)
