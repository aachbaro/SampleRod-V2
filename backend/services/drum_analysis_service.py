from __future__ import annotations

import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import soundfile as sf
from PySide6.QtCore import QObject, QThread, Signal

from backend.services.audio_metadata import is_audio_file, normalize_audio_path

logger = logging.getLogger("drum_analysis_service")

DEFAULT_SPLIT_DENSITY = 50.0
DEFAULT_QUANTIZE_GRID_DIVISION = 16
DEFAULT_QUANTIZE_STRENGTH = 0.7


@dataclass(frozen=True, slots=True)
class DrumSlice:
    index: int
    start_s: float
    end_s: float
    label: str
    confidence: float
    role: str
    rhythmic_position: str
    secondary_labels: tuple[str, ...] = ()
    layer_score: float = 0.0
    step_index: int | None = None
    preview_start_s: float | None = None
    preview_end_s: float | None = None


@dataclass(frozen=True, slots=True)
class DrumAnalysisResult:
    source_path: str
    label: str
    family: str
    form: str
    confidence: float
    duration_s: float
    sample_rate: int
    tempo_bpm: float
    pulse_score: float
    regularity: float
    onset_count: int
    split_density: float
    candidates: tuple[str, ...]
    slices: tuple[DrumSlice, ...]
    prototype_result: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DrumQuantizedPreview:
    source_path: str
    display_name: str
    temp_path: str
    duration_s: float
    sample_rate: int
    source_bpm: float
    target_bpm: float
    grid_division: int
    quantize_strength: float
    slices: tuple[DrumSlice, ...]


@lru_cache(maxsize=1)
def _load_analyzer_module():
    from prototypes.drum_detector import analyzer as analyzer_module

    return analyzer_module


@lru_cache(maxsize=1)
def _load_preview_module():
    from prototypes.drum_detector import preview as preview_module

    return preview_module


def drum_analysis_availability_error() -> str | None:
    try:
        analyzer = _load_analyzer_module()
        return analyzer.get_analysis_dependency_error()
    except Exception as exc:
        return str(exc)


def adapt_drum_detection_result(raw_result: Any, *, split_density: float) -> DrumAnalysisResult:
    source_path = normalize_audio_path(getattr(raw_result, "source_path", "") or "")
    transient_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
    slices = tuple(
        DrumSlice(
            index=int(getattr(hit, "index", idx)),
            start_s=float(getattr(hit, "start_s", 0.0)),
            end_s=float(getattr(hit, "end_s", 0.0)),
            label=str(getattr(hit, "label", "other") or "other"),
            confidence=float(getattr(hit, "confidence", 0.0) or 0.0),
            role=str(getattr(hit, "role", "other") or "other"),
            rhythmic_position=str(
                getattr(hit, "rhythmic_position", "subdivision") or "subdivision"
            ),
            secondary_labels=tuple(getattr(hit, "secondary_labels", ()) or ()),
            layer_score=float(getattr(hit, "layer_score", 0.0) or 0.0),
        )
        for idx, hit in enumerate(transient_hits, start=1)
    )
    candidates = tuple(
        str(getattr(candidate, "label", "") or "")
        for candidate in tuple(getattr(raw_result, "candidates", ()) or ())
        if str(getattr(candidate, "label", "") or "").strip()
    )
    return DrumAnalysisResult(
        source_path=source_path,
        label=str(getattr(raw_result, "label", "") or ""),
        family=str(getattr(raw_result, "family", "") or ""),
        form=str(getattr(raw_result, "form", "") or ""),
        confidence=float(getattr(raw_result, "confidence", 0.0) or 0.0),
        duration_s=float(getattr(raw_result, "duration_s", 0.0) or 0.0),
        sample_rate=int(getattr(raw_result, "sample_rate", 0) or 0),
        tempo_bpm=float(getattr(raw_result, "tempo_bpm", 0.0) or 0.0),
        pulse_score=float(getattr(raw_result, "pulse_score", 0.0) or 0.0),
        regularity=float(getattr(raw_result, "regularity", 0.0) or 0.0),
        onset_count=int(getattr(raw_result, "onset_count", len(slices)) or len(slices)),
        split_density=float(split_density),
        candidates=candidates,
        slices=slices,
        prototype_result=raw_result,
    )


def project_quantized_slices(
    result: DrumAnalysisResult,
    *,
    target_bpm: float,
    grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = DEFAULT_QUANTIZE_STRENGTH,
) -> tuple[DrumSlice, ...]:
    if not result.slices:
        return ()

    source_bpm = float(result.tempo_bpm or 0.0)
    if source_bpm <= 1.0 or float(target_bpm or 0.0) <= 1.0:
        return result.slices

    raw_result = result.prototype_result
    raw_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
    if len(raw_hits) < 2:
        return result.slices

    preview = _load_preview_module()
    schedule = tuple(
        preview.build_retimed_preview_schedule(
            raw_hits,
            source_bpm=source_bpm,
            target_bpm=float(target_bpm),
            mode=preview.PREVIEW_MODE_QUANTIZE,
            quantize_grid_division=int(grid_division),
            quantize_strength=float(quantize_strength),
        )
    )
    if not schedule:
        return result.slices

    projected: list[DrumSlice] = []
    for source_slice, scheduled in zip(result.slices, schedule):
        projected.append(
            replace(
                source_slice,
                step_index=getattr(scheduled, "step_index", None),
                preview_start_s=float(getattr(scheduled, "preview_start_s", 0.0)),
                preview_end_s=float(getattr(scheduled, "preview_end_s", 0.0)),
            )
        )
    if len(projected) < len(result.slices):
        projected.extend(result.slices[len(projected) :])
    return tuple(projected)


def _preview_temp_path(source_path: str, target_bpm: float) -> str:
    temp_root = Path(tempfile.gettempdir()) / "SampleRod" / "break_preview"
    temp_root.mkdir(parents=True, exist_ok=True)
    stem = Path(source_path or "break").stem or "break"
    suffix = uuid.uuid4().hex[:8]
    filename = f"{stem}_quantized_{int(round(target_bpm))}bpm_{suffix}.wav"
    return str(temp_root / filename)


class _DrumAnalysisWorker(QThread):
    analysisReady = Signal(object)
    analysisFailed = Signal(str, str)

    def __init__(self, path: str, split_density: float, parent: QObject | None = None):
        super().__init__(parent)
        self._path = path
        self._split_density = float(split_density)

    def run(self) -> None:
        try:
            analyzer = _load_analyzer_module()
            raw_result = analyzer.analyze_file(
                self._path,
                split_density=self._split_density,
            )
            public_result = adapt_drum_detection_result(
                raw_result,
                split_density=self._split_density,
            )
            self.analysisReady.emit(public_result)
        except Exception as exc:
            logger.warning("[DrumAnalysisWorker] analyse impossible %s: %s", self._path, exc)
            self.analysisFailed.emit(self._path, str(exc))


class _DrumQuantizeWorker(QThread):
    previewReady = Signal(object)
    previewFailed = Signal(str, str)

    def __init__(
        self,
        result: DrumAnalysisResult,
        *,
        target_bpm: float,
        grid_division: int,
        quantize_strength: float,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._result = result
        self._target_bpm = float(target_bpm)
        self._grid_division = int(grid_division)
        self._quantize_strength = float(quantize_strength)

    def run(self) -> None:
        source_path = self._result.source_path
        try:
            raw_result = self._result.prototype_result
            if raw_result is None:
                raise ValueError("Analyse brute indisponible pour la preview quantizee")
            raw_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
            if len(raw_hits) < 2:
                raise ValueError("Il faut au moins deux slices pour preparer une preview quantizee")

            preview = _load_preview_module()
            source_bpm = float(self._result.tempo_bpm or 0.0)
            if source_bpm <= 1.0 or self._target_bpm <= 1.0:
                raise ValueError("Tempo source ou cible invalide")

            audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=False)
            quantized = preview.build_retimed_preview(
                audio,
                int(sample_rate),
                raw_hits,
                source_bpm=source_bpm,
                target_bpm=self._target_bpm,
                mode=preview.PREVIEW_MODE_QUANTIZE,
                quantize_grid_division=self._grid_division,
                quantize_strength=self._quantize_strength,
            )
            temp_path = _preview_temp_path(source_path, self._target_bpm)
            sf.write(temp_path, quantized.audio, int(quantized.sample_rate))

            preview_result = DrumQuantizedPreview(
                source_path=source_path,
                display_name=f"{Path(source_path).stem}_quantized_{int(round(self._target_bpm))}",
                temp_path=temp_path,
                duration_s=float(quantized.duration_s or 0.0),
                sample_rate=int(quantized.sample_rate),
                source_bpm=source_bpm,
                target_bpm=self._target_bpm,
                grid_division=self._grid_division,
                quantize_strength=self._quantize_strength,
                slices=project_quantized_slices(
                    self._result,
                    target_bpm=self._target_bpm,
                    grid_division=self._grid_division,
                    quantize_strength=self._quantize_strength,
                ),
            )
            self.previewReady.emit(preview_result)
        except Exception as exc:
            logger.warning("[DrumQuantizeWorker] preview impossible %s: %s", source_path, exc)
            self.previewFailed.emit(source_path, str(exc))


class _DrumReanalysisWorker(QThread):
    """Relance la detection de types a partir de markers manuels."""
    analysisReady = Signal(object)
    analysisFailed = Signal(str, str)

    def __init__(
        self,
        result: DrumAnalysisResult,
        marker_times: list[float],
        parent=None,
    ):
        super().__init__(parent)
        self._result = result
        self._marker_times = list(marker_times)

    def run(self) -> None:
        source_path = self._result.source_path
        try:
            analyzer = _load_analyzer_module()
            audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=False)
            raw_result = analyzer.detect_drum_from_markers(
                audio,
                int(sample_rate),
                self._marker_times,
                source_path=source_path,
            )
            public_result = adapt_drum_detection_result(
                raw_result,
                split_density=self._result.split_density,
            )
            self.analysisReady.emit(public_result)
        except Exception as exc:
            logger.warning("[DrumReanalysisWorker] reanalyse impossible %s: %s", source_path, exc)
            self.analysisFailed.emit(source_path, str(exc))


class DrumAnalysisService(QObject):
    analysisStarted = Signal(str)
    analysisFinished = Signal(object)
    analysisFailed = Signal(str, str)
    reanalysisStarted = Signal(str)
    reanalysisFinished = Signal(object)
    reanalysisFailed = Signal(str, str)
    quantizeStarted = Signal(str)
    quantizeFinished = Signal(object)
    quantizeFailed = Signal(str, str)
    statusChanged = Signal(str)

    def __init__(self, app_context) -> None:
        super().__init__()
        self.app_context = app_context
        self._analysis_workers: set[QThread] = set()
        self._reanalysis_workers: set[QThread] = set()
        self._quantize_workers: set[QThread] = set()

    def analyze_file(self, path: str, *, split_density: float = DEFAULT_SPLIT_DENSITY) -> bool:
        normalized = normalize_audio_path(path)
        if not normalized or not os.path.isfile(normalized):
            self.analysisFailed.emit(normalized, "Fichier introuvable")
            return False
        if not is_audio_file(normalized):
            self.analysisFailed.emit(normalized, "Format audio non supporte")
            return False

        worker = _DrumAnalysisWorker(normalized, split_density, self)
        self._analysis_workers.add(worker)
        worker.analysisReady.connect(self.analysisFinished.emit)
        worker.analysisFailed.connect(self.analysisFailed.emit)
        worker.finished.connect(lambda: self._analysis_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.analysisStarted.emit(normalized)
        self.statusChanged.emit(f"Analyse break en cours: {Path(normalized).name}")
        worker.start()
        return True

    def create_quantized_preview(
        self,
        result: DrumAnalysisResult | None,
        *,
        target_bpm: float,
        grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
        quantize_strength: float = DEFAULT_QUANTIZE_STRENGTH,
    ) -> bool:
        if result is None:
            self.quantizeFailed.emit("", "Aucune analyse disponible")
            return False
        if not result.source_path or not os.path.isfile(result.source_path):
            self.quantizeFailed.emit(result.source_path, "Fichier source introuvable")
            return False

        worker = _DrumQuantizeWorker(
            result,
            target_bpm=float(target_bpm),
            grid_division=int(grid_division),
            quantize_strength=float(quantize_strength),
            parent=self,
        )
        self._quantize_workers.add(worker)
        worker.previewReady.connect(self.quantizeFinished.emit)
        worker.previewFailed.connect(self.quantizeFailed.emit)
        worker.finished.connect(lambda: self._quantize_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.quantizeStarted.emit(result.source_path)
        self.statusChanged.emit(
            f"Preparation de la preview quantizee: {Path(result.source_path).name}"
        )
        worker.start()
        return True

    def quantized_slices(
        self,
        result: DrumAnalysisResult | None,
        *,
        target_bpm: float,
        grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
        quantize_strength: float = DEFAULT_QUANTIZE_STRENGTH,
    ) -> tuple[DrumSlice, ...]:
        if result is None:
            return ()
        try:
            return project_quantized_slices(
                result,
                target_bpm=target_bpm,
                grid_division=grid_division,
                quantize_strength=quantize_strength,
            )
        except Exception as exc:
            logger.info("[DrumAnalysisService] projection quantizee impossible: %s", exc)
            return result.slices

    def reanalyze_from_markers(
        self,
        result: DrumAnalysisResult,
        marker_times: list[float],
    ) -> bool:
        """Relance la detection a partir de positions de markers manuels."""
        if not result.source_path or not os.path.isfile(result.source_path):
            self.reanalysisFailed.emit(result.source_path or "", "Fichier source introuvable")
            return False
        if not marker_times:
            self.reanalysisFailed.emit(result.source_path, "Aucun marker fourni")
            return False

        worker = _DrumReanalysisWorker(result, marker_times, self)
        self._reanalysis_workers.add(worker)
        worker.analysisReady.connect(self.reanalysisFinished.emit)
        worker.analysisReady.connect(self.analysisFinished.emit)   # alias pour l'UI
        worker.analysisFailed.connect(self.reanalysisFailed.emit)
        worker.finished.connect(lambda: self._reanalysis_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.reanalysisStarted.emit(result.source_path)
        self.statusChanged.emit(f"Re-analyse depuis markers: {Path(result.source_path).name}")
        worker.start()
        return True

    def shutdown(self) -> None:
        workers = list(self._analysis_workers) + list(self._reanalysis_workers) + list(self._quantize_workers)
        self._analysis_workers.clear()
        self._reanalysis_workers.clear()
        self._quantize_workers.clear()
        for worker in workers:
            try:
                worker.requestInterruption()
            except Exception:
                pass
            try:
                worker.wait(2000)
            except Exception:
                logger.info("[DrumAnalysisService] arret worker impossible")
