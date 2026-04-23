# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Analyse les gammes compatibles d'un sample en arriere-plan (QThread).
# - Appelle le detecteur de gammes (prototypes/scale_detector/analyzer.py).
# - Ecrit les resultats en base (dominant_note, scale_confidence, compatible_scales).
# - Emet scaleAnalysisComplete(sample_id) quand c'est termine.
#
# LIENS CLES
# - backend/services/sample_service.py  (enqueue_scale_analysis)
# - backend/models/sample.py            (dominant_note, scale_confidence, compatible_scales)
# - prototypes/scale_detector/analyzer.py
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

    analysisComplete = Signal(int)   # sample_id
    analysisFailed = Signal(int, str)  # sample_id, error message

    def __init__(self, task_queue: queue.Queue, parent: QObject | None = None):
        super().__init__(parent)
        self._queue = task_queue
        self._running = True

    def stop(self):
        self._running = False
        # Poison pill pour debloquer le get()
        self._queue.put(None)

    def run(self):
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

        dominant_note = result.dominant_note
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
            inst.scale_confidence = scale_confidence
            inst.compatible_scales = compatible_scales_json
            inst.analyzed_at = datetime.datetime.now()
            session.commit()
            logger.info(
                "[ScaleAnalysisWorker] Analyse enregistree id=%s note=%s confidence=%.3f scales=%s",
                sample_id, dominant_note, scale_confidence, compatible_scales_list,
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

    scaleAnalysisComplete = Signal(int)   # sample_id
    scaleAnalysisFailed = Signal(int, str)  # sample_id, reason

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._worker = _ScaleAnalysisWorker(self._queue, self)
        self._worker.analysisComplete.connect(self._on_complete)
        self._worker.analysisFailed.connect(self._on_failed)
        self._worker.start()
        logger.info("[ScaleAnalysisService] Service demarre")

    def enqueue(self, sample_id: int, path: str) -> None:
        """Enfile un sample pour analyse. Non bloquant."""
        logger.info("[ScaleAnalysisService] Enqueue id=%s", sample_id)
        self._queue.put((sample_id, path))

    def shutdown(self) -> None:
        """Arret propre du thread de fond."""
        self._worker.stop()
        self._worker.wait(5000)

    def _on_complete(self, sample_id: int) -> None:
        self.scaleAnalysisComplete.emit(sample_id)

    def _on_failed(self, sample_id: int, reason: str) -> None:
        self.scaleAnalysisFailed.emit(sample_id, reason)
