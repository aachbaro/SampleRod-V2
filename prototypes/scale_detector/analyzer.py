from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Iterable
import math
import warnings

import numpy as np

NOTE_NAMES: tuple[str, ...] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".wav",
        ".mp3",
        ".flac",
        ".ogg",
        ".aif",
        ".aiff",
        ".m4a",
    }
)


@dataclass(frozen=True)
class ScaleTemplate:
    slug: str
    label: str
    intervals: tuple[int, ...]


@dataclass(frozen=True)
class ScaleCandidate:
    tonic_index: int
    tonic: str
    scale_slug: str
    scale_label: str
    label: str
    score: float
    scale_fit: float
    tonic_fit: float
    in_scale_energy: float
    compactness: float
    active_overlap: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class DetectionResult:
    source_path: str | None
    kind: str
    label: str
    confidence: float
    dominant_note: str
    dominant_note_confidence: float
    active_notes: tuple[str, ...]
    pitch_classes: dict[str, float]
    candidates: tuple[ScaleCandidate, ...]
    sample_rate: int
    duration_s: float

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["active_notes"] = list(self.active_notes)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


SCALE_TEMPLATES: tuple[ScaleTemplate, ...] = (
    ScaleTemplate("major", "major", (0, 2, 4, 5, 7, 9, 11)),
    ScaleTemplate("natural_minor", "natural minor", (0, 2, 3, 5, 7, 8, 10)),
    ScaleTemplate("harmonic_minor", "harmonic minor", (0, 2, 3, 5, 7, 8, 11)),
    ScaleTemplate("melodic_minor", "melodic minor", (0, 2, 3, 5, 7, 9, 11)),
    ScaleTemplate("dorian", "dorian", (0, 2, 3, 5, 7, 9, 10)),
    ScaleTemplate("phrygian", "phrygian", (0, 1, 3, 5, 7, 8, 10)),
    ScaleTemplate("lydian", "lydian", (0, 2, 4, 6, 7, 9, 11)),
    ScaleTemplate("mixolydian", "mixolydian", (0, 2, 4, 5, 7, 9, 10)),
    ScaleTemplate("locrian", "locrian", (0, 1, 3, 5, 6, 8, 10)),
    ScaleTemplate("major_pentatonic", "major pentatonic", (0, 2, 4, 7, 9)),
    ScaleTemplate("minor_pentatonic", "minor pentatonic", (0, 3, 5, 7, 10)),
)


@lru_cache(maxsize=1)
def _require_librosa():
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return import_module("librosa")
    except ModuleNotFoundError as exc:
        missing = exc.name or "librosa"
        raise ModuleNotFoundError(
            "Audio analysis dependency missing "
            f"({missing}). Install project deps with "
            "`python -m pip install -r requirements.txt`."
        ) from exc


def get_analysis_dependency_error() -> str | None:
    try:
        _require_librosa()
    except ModuleNotFoundError as exc:
        return str(exc)
    return None


def analyze_file(path: str | Path, *, top_n: int = 5) -> DetectionResult:
    librosa = _require_librosa()
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    audio, sample_rate = librosa.load(str(source), sr=None, mono=True)
    return detect_scale_from_audio(audio, sample_rate, source_path=str(source), top_n=top_n)


def detect_scale_from_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    source_path: str | None = None,
    top_n: int = 5,
) -> DetectionResult:
    signal = _prepare_audio(audio)
    duration_s = float(signal.size) / float(sample_rate)
    if signal.size < max(2048, sample_rate // 4):
        raise ValueError("Audio too short for a reliable detection")

    trimmed = _trim_signal(signal, sample_rate)
    harmonic = _harmonic_component(trimmed)
    hop_length = 512 if harmonic.size < sample_rate * 20 else 1024
    tuning = _estimate_tuning(harmonic, sample_rate)
    chroma = _build_chroma(harmonic, sample_rate, hop_length, tuning)
    profile, edge_profile = _summarize_chroma(chroma, harmonic, sample_rate, hop_length)
    active_indices = _active_pitch_classes(profile)
    dominant_index = int(np.argmax(profile))
    dominant_confidence = _note_confidence(profile, dominant_index)
    candidates = _rank_candidates(profile, edge_profile, active_indices, top_n=top_n)

    if not candidates:
        raise ValueError("No scale candidates could be generated")

    primary = candidates[0]
    secondary_score = candidates[1].score if len(candidates) > 1 else 0.0
    margin = max(0.0, primary.score - secondary_score)
    kind = "note" if len(active_indices) <= 2 else "scale"
    confidence = _result_confidence(kind, dominant_confidence, primary.score, margin)
    label = NOTE_NAMES[dominant_index] if kind == "note" else primary.label

    return DetectionResult(
        source_path=source_path,
        kind=kind,
        label=label,
        confidence=round(confidence, 4),
        dominant_note=NOTE_NAMES[dominant_index],
        dominant_note_confidence=round(dominant_confidence, 4),
        active_notes=tuple(NOTE_NAMES[index] for index in active_indices),
        pitch_classes={name: round(float(value), 6) for name, value in zip(NOTE_NAMES, profile)},
        candidates=tuple(candidates),
        sample_rate=int(sample_rate),
        duration_s=round(duration_s, 4),
    )


def iter_audio_files(target: str | Path, *, recursive: bool = False) -> Iterable[Path]:
    root = Path(target).expanduser().resolve()
    if root.is_file():
        if root.suffix.lower() in AUDIO_EXTENSIONS:
            yield root
        return

    glob_pattern = "**/*" if recursive else "*"
    for path in sorted(root.glob(glob_pattern)):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            yield path


def _prepare_audio(audio: np.ndarray) -> np.ndarray:
    signal = np.asarray(audio, dtype=np.float32)
    if signal.ndim == 2:
        # Accept either (channels, samples) or (samples, channels).
        axis = 0 if signal.shape[0] <= signal.shape[1] else 1
        signal = np.mean(signal, axis=axis)
    signal = np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak <= 1e-6:
        raise ValueError("Audio is silent or empty")
    return signal / peak


def _trim_signal(signal: np.ndarray, sample_rate: int) -> np.ndarray:
    librosa = _require_librosa()
    trimmed, _ = librosa.effects.trim(signal, top_db=35)
    minimum_length = max(1024, sample_rate // 5)
    return trimmed if trimmed.size >= minimum_length else signal


def _harmonic_component(signal: np.ndarray) -> np.ndarray:
    librosa = _require_librosa()
    try:
        return librosa.effects.harmonic(signal, margin=6.0)
    except Exception:
        return signal


def _estimate_tuning(signal: np.ndarray, sample_rate: int) -> float:
    librosa = _require_librosa()
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Trying to estimate tuning from empty frequency set\.",
                category=UserWarning,
            )
            return float(librosa.estimate_tuning(y=signal, sr=sample_rate))
    except Exception:
        return 0.0


def _build_chroma(
    signal: np.ndarray,
    sample_rate: int,
    hop_length: int,
    tuning: float,
) -> np.ndarray:
    librosa = _require_librosa()
    try:
        return librosa.feature.chroma_cqt(
            y=signal,
            sr=sample_rate,
            hop_length=hop_length,
            bins_per_octave=36,
            n_chroma=12,
            tuning=tuning,
        )
    except Exception:
        return librosa.feature.chroma_stft(
            y=signal,
            sr=sample_rate,
            hop_length=hop_length,
            n_fft=4096,
            tuning=tuning,
        )


def _summarize_chroma(
    chroma: np.ndarray,
    signal: np.ndarray,
    sample_rate: int,
    hop_length: int,
) -> tuple[np.ndarray, np.ndarray]:
    librosa = _require_librosa()
    rms = librosa.feature.rms(
        y=signal,
        frame_length=min(4096, max(2048, signal.size)),
        hop_length=hop_length,
    ).reshape(-1)

    frame_count = min(chroma.shape[1], rms.shape[0])
    if frame_count <= 0:
        raise ValueError("Could not compute chroma frames")

    chroma = chroma[:, :frame_count]
    rms = rms[:frame_count]

    positive = rms[rms > 1e-8]
    if positive.size:
        threshold = float(np.quantile(positive, 0.25))
        active_mask = rms >= threshold
    else:
        active_mask = np.ones(frame_count, dtype=bool)

    weights = rms.copy()
    weights[~active_mask] = 0.0
    if float(np.sum(weights)) <= 1e-8:
        weights = np.ones(frame_count, dtype=np.float32)

    profile = np.average(chroma, axis=1, weights=weights)
    profile = _l1_normalize(profile)

    active_frames = np.flatnonzero(active_mask)
    if active_frames.size == 0:
        active_frames = np.arange(frame_count)

    edge_count = max(1, int(math.ceil(active_frames.size * 0.18)))
    edge_indices = np.unique(
        np.concatenate((active_frames[:edge_count], active_frames[-edge_count:]))
    )
    edge_weights = rms[edge_indices]
    if float(np.sum(edge_weights)) <= 1e-8:
        edge_weights = np.ones(edge_indices.size, dtype=np.float32)

    edge_profile = np.average(chroma[:, edge_indices], axis=1, weights=edge_weights)
    edge_profile = _l1_normalize(edge_profile)
    return profile, edge_profile


def _active_pitch_classes(profile: np.ndarray) -> np.ndarray:
    threshold = max(float(np.max(profile)) * 0.32, 0.075)
    active = np.flatnonzero(profile >= threshold)
    if active.size == 0:
        active = np.array([int(np.argmax(profile))], dtype=int)
    return active.astype(int)


def _rank_candidates(
    profile: np.ndarray,
    edge_profile: np.ndarray,
    active_indices: np.ndarray,
    *,
    top_n: int,
) -> list[ScaleCandidate]:
    active_mask = np.zeros(12, dtype=bool)
    active_mask[active_indices] = True
    unit_profile = _l2_normalize(profile)
    candidates: list[ScaleCandidate] = []

    for template in SCALE_TEMPLATES:
        template_mask = np.zeros(12, dtype=np.float32)
        template_mask[list(template.intervals)] = 1.0

        for tonic in range(12):
            rotated = np.roll(template_mask, tonic)
            rotated_bool = rotated > 0
            scale_fit = float(np.dot(unit_profile, _l2_normalize(rotated)))
            in_scale_energy = float(np.sum(profile[rotated_bool]))
            tonic_fit = float((0.3 * profile[tonic]) + (0.7 * edge_profile[tonic]))
            overlap_count = int(np.sum(active_mask & rotated_bool))
            active_overlap = float(overlap_count / max(int(np.sum(active_mask)), 1))
            compactness = float(overlap_count / max(int(np.sum(rotated_bool)), 1))
            score = (
                (0.45 * scale_fit)
                + (0.2 * in_scale_energy)
                + (0.2 * tonic_fit)
                + (0.1 * compactness)
                + (0.05 * active_overlap)
            )

            notes = tuple(NOTE_NAMES[(tonic + interval) % 12] for interval in template.intervals)
            candidates.append(
                ScaleCandidate(
                    tonic_index=tonic,
                    tonic=NOTE_NAMES[tonic],
                    scale_slug=template.slug,
                    scale_label=template.label,
                    label=f"{NOTE_NAMES[tonic]} {template.label}",
                    score=round(score, 6),
                    scale_fit=round(scale_fit, 6),
                    tonic_fit=round(tonic_fit, 6),
                    in_scale_energy=round(in_scale_energy, 6),
                    compactness=round(compactness, 6),
                    active_overlap=round(active_overlap, 6),
                    notes=notes,
                )
            )

    candidates.sort(
        key=lambda candidate: (
            candidate.score,
            candidate.tonic_fit,
            candidate.in_scale_energy,
        ),
        reverse=True,
    )
    return candidates[: max(1, top_n)]


def _note_confidence(profile: np.ndarray, dominant_index: int) -> float:
    dominant = float(profile[dominant_index])
    ordered = np.sort(profile)
    runner_up = float(ordered[-2]) if ordered.size > 1 else 0.0
    return max(0.0, min(0.99, 0.25 + dominant + (dominant - runner_up)))


def _result_confidence(
    kind: str,
    dominant_confidence: float,
    primary_score: float,
    score_margin: float,
) -> float:
    if kind == "note":
        return max(0.0, min(0.99, 0.35 + (0.7 * dominant_confidence)))
    return max(0.0, min(0.99, 0.2 + (0.65 * primary_score) + (1.3 * score_margin)))


def _l1_normalize(values: np.ndarray) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    total = float(np.sum(vector))
    if total <= 1e-8:
        return np.zeros_like(vector)
    return vector / total


def _l2_normalize(values: np.ndarray) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        return np.zeros_like(vector)
    return vector / norm
