from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Callable, Iterable
import math
import warnings

import numpy as np

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
DEFAULT_SPLIT_DENSITY = 50.0


@dataclass(frozen=True)
class TransientHit:
    index: int
    start_s: float
    end_s: float
    label: str
    confidence: float
    peak_db: float
    low_ratio: float
    mid_ratio: float
    high_ratio: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DrumCandidate:
    label: str
    score: float
    details: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DrumDetectionResult:
    source_path: str | None
    label: str
    form: str
    family: str
    confidence: float
    loop_score: float
    drum_score: float
    break_score: float
    duration_s: float
    sample_rate: int
    tempo_bpm: float
    pulse_score: float
    regularity: float
    onset_count: int
    onset_density: float
    percussive_ratio: float
    harmonic_ratio: float
    decay_s: float
    spectral_centroid_hz: float
    spectral_flatness: float
    band_energies: dict[str, float]
    transient_hits: tuple[TransientHit, ...]
    candidates: tuple[DrumCandidate, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["transient_hits"] = [hit.to_dict() for hit in self.transient_hits]
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


@dataclass(frozen=True)
class DrumTransientPreview:
    source_path: str | None
    duration_s: float
    sample_rate: int
    onset_count: int
    tempo_bpm: float
    pulse_score: float
    regularity: float
    marker_times: tuple[float, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _FeatureVector:
    duration_s: float
    low_ratio: float
    mid_ratio: float
    high_ratio: float
    spectral_centroid_hz: float
    spectral_flatness: float
    zero_crossing_rate: float
    decay_s: float
    attack_score: float
    noise_score: float
    peak_db: float


@dataclass(frozen=True)
class _OnsetHint:
    time_s: float
    combined_strength: float
    low_strength: float
    mid_strength: float
    high_strength: float


@dataclass(frozen=True)
class _TransientProfile:
    low_ratio: float
    mid_ratio: float
    high_ratio: float
    energy_rise: float
    pre_level: float


@dataclass(frozen=True)
class _SplitDensityConfig:
    strong_delta: float
    detail_delta: float
    low_delta: float
    strong_wait: int
    detail_wait: int
    low_wait: int
    min_separation_s: float
    strength_floor: float
    peak_floor: float
    trailing_strength_floor: float
    trailing_peak_floor: float


_ONE_SHOT_DETAILS: dict[str, str] = {
    "kick": "grave, compact, attaque franche",
    "snare": "milieu du spectre, bruit/transient visibles",
    "clap": "mid/high, bruit court et sec",
    "closed_hat": "aigu, bruit court, decay bref",
    "open_hat": "aigu, bruit plus long",
    "crash": "aigu/bruite, queue longue",
    "tom": "grave-medium, plus tonal qu'un snare",
    "perc": "percussif, mais plus ambigu",
}


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


def analyze_file(
    path: str | Path,
    *,
    top_n: int = 5,
    split_density: float = DEFAULT_SPLIT_DENSITY,
) -> DrumDetectionResult:
    return analyze_file_with_preview(
        path,
        top_n=top_n,
        split_density=split_density,
        preview_callback=None,
    )


def analyze_file_with_preview(
    path: str | Path,
    *,
    top_n: int = 5,
    split_density: float = DEFAULT_SPLIT_DENSITY,
    preview_callback: Callable[[DrumTransientPreview], None] | None = None,
) -> DrumDetectionResult:
    librosa = _require_librosa()
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    audio, sample_rate = librosa.load(str(source), sr=None, mono=True)
    return analyze_audio_with_preview(
        audio,
        sample_rate,
        source_path=str(source),
        top_n=top_n,
        split_density=split_density,
        preview_callback=preview_callback,
    )


def analyze_file_from_markers(
    path: str | Path,
    marker_times: Iterable[float],
    *,
    top_n: int = 5,
) -> DrumDetectionResult:
    librosa = _require_librosa()
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    audio, sample_rate = librosa.load(str(source), sr=None, mono=True)
    return detect_drum_from_markers(
        audio,
        sample_rate,
        marker_times,
        source_path=str(source),
        top_n=top_n,
    )


def detect_drum_from_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    source_path: str | None = None,
    top_n: int = 5,
    split_density: float = DEFAULT_SPLIT_DENSITY,
) -> DrumDetectionResult:
    return analyze_audio_with_preview(
        audio,
        sample_rate,
        source_path=source_path,
        top_n=top_n,
        split_density=split_density,
        preview_callback=None,
    )


def analyze_audio_with_preview(
    audio: np.ndarray,
    sample_rate: int,
    *,
    source_path: str | None = None,
    top_n: int = 5,
    split_density: float = DEFAULT_SPLIT_DENSITY,
    preview_callback: Callable[[DrumTransientPreview], None] | None = None,
) -> DrumDetectionResult:
    signal = _prepare_audio(audio)
    duration_s = float(signal.size) / float(sample_rate)
    if signal.size < max(1024, sample_rate // 40):
        raise ValueError("Audio too short for a reliable drum detection")

    onset_signal = _analysis_onset_signal(signal)
    onset_times, onset_hints, pulse_score, tempo_bpm, regularity = _detect_onsets(
        onset_signal,
        sample_rate,
        duration_s,
        split_density=split_density,
    )
    if preview_callback is not None:
        preview_callback(
            DrumTransientPreview(
                source_path=source_path,
                duration_s=round(duration_s, 6),
                sample_rate=int(sample_rate),
                onset_count=int(onset_times.size),
                tempo_bpm=round(float(tempo_bpm), 4),
                pulse_score=round(float(pulse_score), 4),
                regularity=round(float(regularity), 4),
                marker_times=tuple(float(time_s) for time_s in onset_times.tolist()),
            )
        )
    return _build_detection_result(
        signal,
        sample_rate,
        onset_times=onset_times,
        onset_hints=onset_hints,
        pulse_score=pulse_score,
        tempo_bpm=tempo_bpm,
        regularity=regularity,
        source_path=source_path,
        top_n=top_n,
    )


def detect_drum_from_markers(
    audio: np.ndarray,
    sample_rate: int,
    marker_times: Iterable[float],
    *,
    source_path: str | None = None,
    top_n: int = 5,
) -> DrumDetectionResult:
    signal = _prepare_audio(audio)
    duration_s = float(signal.size) / float(sample_rate)
    if signal.size < max(1024, sample_rate // 40):
        raise ValueError("Audio too short for a reliable drum detection")

    onset_signal = _analysis_onset_signal(signal)
    onset_times = _sanitize_marker_times(marker_times, duration_s)
    if onset_times.size == 0:
        raise ValueError("Need at least one marker to rebuild the hit list")
    onset_hints, pulse_score, tempo_bpm = _manual_onset_context(onset_signal, sample_rate, onset_times)
    regularity = _regularity_score(onset_times)
    return _build_detection_result(
        signal,
        sample_rate,
        onset_times=onset_times,
        onset_hints=onset_hints,
        pulse_score=pulse_score,
        tempo_bpm=tempo_bpm,
        regularity=regularity,
        source_path=source_path,
        top_n=top_n,
        prepend_start_zero=False,
        keep_manual_segments=True,
    )


def _analysis_onset_signal(signal: np.ndarray) -> np.ndarray:
    harmonic, percussive = _harmonic_percussive(signal)
    return percussive if np.any(percussive) else signal


def _build_detection_result(
    signal: np.ndarray,
    sample_rate: int,
    *,
    onset_times: np.ndarray,
    onset_hints: list[_OnsetHint] | None,
    pulse_score: float,
    tempo_bpm: float,
    regularity: float,
    source_path: str | None,
    top_n: int,
    prepend_start_zero: bool = True,
    keep_manual_segments: bool = False,
) -> DrumDetectionResult:
    duration_s = float(signal.size) / float(sample_rate)
    harmonic, percussive = _harmonic_percussive(signal)
    total_energy = _energy(signal)
    harmonic_ratio = _safe_ratio(_energy(harmonic), total_energy)
    percussive_ratio = _safe_ratio(_energy(percussive), total_energy)

    global_features = _extract_features(signal, sample_rate)
    hits = _detect_transient_hits(
        signal,
        sample_rate,
        onset_times,
        onset_hints,
        prepend_start_zero=prepend_start_zero,
        keep_low_energy_segments=keep_manual_segments,
    )

    onset_count = len(hits)
    onset_density = float(onset_count / max(duration_s, 1e-6))
    loop_score = _loop_score(
        duration_s=duration_s,
        onset_count=onset_count,
        onset_density=onset_density,
        pulse_score=pulse_score,
        regularity=regularity,
        percussive_ratio=percussive_ratio,
    )
    form = "loop" if loop_score >= 0.54 and onset_count >= 3 else "one_shot"

    drum_score = _drum_score(
        percussive_ratio=percussive_ratio,
        harmonic_ratio=harmonic_ratio,
        onset_density=onset_density,
        noise_score=global_features.noise_score,
        attack_score=global_features.attack_score,
        low_ratio=global_features.low_ratio,
        decay_s=global_features.decay_s,
    )
    tonal_score = _tonal_score(
        harmonic_ratio=harmonic_ratio,
        percussive_ratio=percussive_ratio,
        noise_score=global_features.noise_score,
        onset_density=onset_density,
        decay_s=global_features.decay_s,
    )
    family = _choose_family(drum_score, tonal_score, global_features.noise_score)
    if (
        form == "one_shot"
        and global_features.decay_s <= 0.28
        and (
            global_features.low_ratio >= 0.72
            or (global_features.noise_score >= 0.42 and global_features.high_ratio >= 0.32)
            or global_features.attack_score >= 0.72
        )
    ):
        family = "drum"

    break_score = 0.0
    if family == "drum" and form == "one_shot":
        candidates = _rank_one_shot_candidates(global_features, top_n=top_n)
    elif family == "drum":
        candidates, break_score = _rank_loop_candidates(
            features=global_features,
            hits=hits,
            pulse_score=pulse_score,
            regularity=regularity,
            onset_density=onset_density,
            percussive_ratio=percussive_ratio,
            top_n=top_n,
        )
    else:
        candidates = _rank_non_drum_candidates(
            form=form,
            family=family,
            harmonic_ratio=harmonic_ratio,
            noise_score=global_features.noise_score,
            loop_score=loop_score,
            top_n=top_n,
        )

    if not candidates:
        raise ValueError("No drum candidates could be generated")

    primary = candidates[0]
    secondary_score = candidates[1].score if len(candidates) > 1 else 0.0
    confidence = _result_confidence(
        top_score=primary.score,
        margin=max(0.0, primary.score - secondary_score),
        drum_score=drum_score,
        loop_score=loop_score,
        break_score=break_score,
        family=family,
        form=form,
    )

    return DrumDetectionResult(
        source_path=source_path,
        label=primary.label,
        form=form,
        family=family,
        confidence=round(confidence, 4),
        loop_score=round(loop_score, 4),
        drum_score=round(drum_score, 4),
        break_score=round(break_score, 4),
        duration_s=round(duration_s, 4),
        sample_rate=int(sample_rate),
        tempo_bpm=round(tempo_bpm, 2),
        pulse_score=round(pulse_score, 4),
        regularity=round(regularity, 4),
        onset_count=onset_count,
        onset_density=round(onset_density, 4),
        percussive_ratio=round(percussive_ratio, 4),
        harmonic_ratio=round(harmonic_ratio, 4),
        decay_s=round(global_features.decay_s, 4),
        spectral_centroid_hz=round(global_features.spectral_centroid_hz, 2),
        spectral_flatness=round(global_features.spectral_flatness, 6),
        band_energies={
            "low": round(global_features.low_ratio, 6),
            "mid": round(global_features.mid_ratio, 6),
            "high": round(global_features.high_ratio, 6),
        },
        transient_hits=tuple(hits),
        candidates=tuple(candidates),
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
        axis = 0 if signal.shape[0] <= signal.shape[1] else 1
        signal = np.mean(signal, axis=axis)
    signal = np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak <= 1e-6:
        raise ValueError("Audio is silent or empty")
    return signal / peak


def _harmonic_percussive(signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    librosa = _require_librosa()
    try:
        harmonic, percussive = librosa.effects.hpss(signal)
        return harmonic.astype(np.float32), percussive.astype(np.float32)
    except Exception:
        return np.zeros_like(signal), signal


def _detect_onsets(
    signal: np.ndarray,
    sample_rate: int,
    duration_s: float,
    *,
    split_density: float = DEFAULT_SPLIT_DENSITY,
) -> tuple[np.ndarray, list[_OnsetHint], float, float, float]:
    librosa = _require_librosa()
    density = _split_density_config(split_density)
    hop_length = 128 if signal.size < sample_rate * 12 else 256
    onset_env = librosa.onset.onset_strength(
        y=signal,
        sr=sample_rate,
        hop_length=hop_length,
        aggregate=np.median,
    )

    low_env, mid_env, high_env = _band_onset_envelopes(signal, sample_rate, hop_length)
    onset_norm = _normalize_envelope(onset_env)
    low_norm = _normalize_envelope(low_env)
    mid_norm = _normalize_envelope(mid_env)
    high_norm = _normalize_envelope(high_env)

    combined_env = np.maximum.reduce(
        [
            (0.48 * onset_norm) + (0.22 * low_norm) + (0.15 * mid_norm) + (0.15 * high_norm),
            0.92 * high_norm,
            0.84 * low_norm,
        ]
    )

    strong_frames = librosa.util.peak_pick(
        combined_env,
        pre_max=2,
        post_max=2,
        pre_avg=4,
        post_avg=4,
        delta=density.strong_delta,
        wait=density.strong_wait,
    )
    detail_frames = librosa.util.peak_pick(
        np.maximum(high_norm, 0.78 * mid_norm),
        pre_max=1,
        post_max=1,
        pre_avg=2,
        post_avg=2,
        delta=density.detail_delta,
        wait=density.detail_wait,
    )
    low_frames = librosa.util.peak_pick(
        low_norm,
        pre_max=1,
        post_max=1,
        pre_avg=2,
        post_avg=2,
        delta=density.low_delta,
        wait=density.low_wait,
    )

    candidate_frames = np.unique(
        np.concatenate(
            (
                np.asarray(strong_frames, dtype=int),
                np.asarray(detail_frames, dtype=int),
                np.asarray(low_frames, dtype=int),
            )
        )
    )
    candidate_frames = candidate_frames[candidate_frames >= 0]

    strengths = {
        int(frame): float(
            max(
                combined_env[min(frame, combined_env.size - 1)],
                high_norm[min(frame, high_norm.size - 1)] * 0.95,
                low_norm[min(frame, low_norm.size - 1)] * 0.9,
            )
        )
        for frame in candidate_frames
    }

    candidate_times = librosa.frames_to_time(candidate_frames, sr=sample_rate, hop_length=hop_length)
    refined_times = [
        _refine_onset_time(signal, sample_rate, float(np.clip(time_s, 0.0, duration_s)))
        for time_s in candidate_times
    ]
    onset_times = np.asarray(
        _prune_onset_times(
            signal=signal,
            sample_rate=sample_rate,
            onset_times=refined_times,
            strengths=[strengths.get(int(frame), 0.0) for frame in candidate_frames],
            duration_s=duration_s,
            min_separation_s=density.min_separation_s,
            strength_floor=density.strength_floor,
            peak_floor=density.peak_floor,
            trailing_strength_floor=density.trailing_strength_floor,
            trailing_peak_floor=density.trailing_peak_floor,
        ),
        dtype=np.float32,
    )
    onset_hints = _build_onset_hints(
        onset_times=onset_times,
        sample_rate=sample_rate,
        hop_length=hop_length,
        combined_env=combined_env,
        low_env=low_norm,
        mid_env=mid_norm,
        high_env=high_norm,
    )
    pulse_score, tempo_bpm = _estimate_pulse(onset_env, sample_rate, hop_length)
    regularity = _regularity_score(onset_times)
    return onset_times, onset_hints, pulse_score, tempo_bpm, regularity


def _manual_onset_context(
    signal: np.ndarray,
    sample_rate: int,
    onset_times: np.ndarray,
) -> tuple[list[_OnsetHint], float, float]:
    librosa = _require_librosa()
    hop_length = 128 if signal.size < sample_rate * 12 else 256
    onset_env = librosa.onset.onset_strength(
        y=signal,
        sr=sample_rate,
        hop_length=hop_length,
        aggregate=np.median,
    )
    low_env, mid_env, high_env = _band_onset_envelopes(signal, sample_rate, hop_length)
    onset_norm = _normalize_envelope(onset_env)
    low_norm = _normalize_envelope(low_env)
    mid_norm = _normalize_envelope(mid_env)
    high_norm = _normalize_envelope(high_env)
    combined_env = np.maximum.reduce(
        [
            (0.48 * onset_norm) + (0.22 * low_norm) + (0.15 * mid_norm) + (0.15 * high_norm),
            0.92 * high_norm,
            0.84 * low_norm,
        ]
    )
    onset_hints = _build_onset_hints(
        onset_times=onset_times,
        sample_rate=sample_rate,
        hop_length=hop_length,
        combined_env=combined_env,
        low_env=low_norm,
        mid_env=mid_norm,
        high_env=high_norm,
    )
    pulse_score, tempo_bpm = _estimate_pulse(onset_env, sample_rate, hop_length)
    return onset_hints, pulse_score, tempo_bpm


def _sanitize_marker_times(marker_times: Iterable[float], duration_s: float) -> np.ndarray:
    sanitized: list[float] = []
    for raw_time in marker_times:
        try:
            time_s = float(raw_time)
        except (TypeError, ValueError):
            continue
        clipped = float(np.clip(time_s, 0.0, duration_s))
        if clipped >= duration_s:
            continue
        if sanitized and abs(clipped - sanitized[-1]) < 1e-4:
            continue
        sanitized.append(clipped)

    if not sanitized:
        return np.asarray([], dtype=np.float32)
    sanitized.sort()
    deduped: list[float] = []
    for time_s in sanitized:
        if deduped and abs(time_s - deduped[-1]) < 1e-4:
            continue
        deduped.append(time_s)
    return np.asarray(deduped, dtype=np.float32)


def _split_density_config(split_density: float) -> _SplitDensityConfig:
    try:
        density = float(split_density)
    except (TypeError, ValueError):
        density = DEFAULT_SPLIT_DENSITY
    density = float(np.clip(density, 0.0, 100.0))
    sensitivity = (density - 50.0) / 50.0

    return _SplitDensityConfig(
        strong_delta=float(np.clip(0.11 - (0.03 * sensitivity), 0.06, 0.18)),
        detail_delta=float(np.clip(0.15 - (0.04 * sensitivity), 0.08, 0.22)),
        low_delta=float(np.clip(0.14 - (0.035 * sensitivity), 0.08, 0.2)),
        strong_wait=max(1, int(round(2.0 - sensitivity))),
        detail_wait=max(1, int(round(1.0 - (0.4 * sensitivity)))),
        low_wait=max(1, int(round(1.0 - (0.4 * sensitivity)))),
        min_separation_s=float(np.clip(0.055 - (0.02 * sensitivity), 0.03, 0.085)),
        strength_floor=float(np.clip(0.12 - (0.04 * sensitivity), 0.07, 0.18)),
        peak_floor=float(np.clip(0.03 - (0.01 * sensitivity), 0.015, 0.05)),
        trailing_strength_floor=float(np.clip(0.16 - (0.05 * sensitivity), 0.1, 0.24)),
        trailing_peak_floor=float(np.clip(0.08 - (0.03 * sensitivity), 0.04, 0.12)),
    )


def _estimate_pulse(onset_env: np.ndarray, sample_rate: int, hop_length: int) -> tuple[float, float]:
    if onset_env.size < 4:
        return 0.0, 0.0

    centered = onset_env.astype(np.float32) - float(np.mean(onset_env))
    autocorr = np.correlate(centered, centered, mode="full")[centered.size - 1 :]
    if autocorr.size <= 1 or float(autocorr[0]) <= 1e-8:
        return 0.0, 0.0

    min_bpm = 70.0
    max_bpm = 190.0
    min_lag = max(1, int(round((60.0 / max_bpm) * sample_rate / hop_length)))
    max_lag = max(min_lag + 1, int(round((60.0 / min_bpm) * sample_rate / hop_length)))
    max_lag = min(max_lag, autocorr.size - 1)
    if max_lag <= min_lag:
        return 0.0, 0.0

    window = autocorr[min_lag : max_lag + 1]
    best_offset = int(np.argmax(window))
    best_lag = min_lag + best_offset
    pulse_score = float(np.clip(window[best_offset] / max(float(autocorr[0]), 1e-8), 0.0, 0.99))
    tempo_bpm = 60.0 * sample_rate / float(best_lag * hop_length)
    return pulse_score, tempo_bpm


def _band_onset_envelopes(
    signal: np.ndarray,
    sample_rate: int,
    hop_length: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    librosa = _require_librosa()
    n_fft = _safe_n_fft(signal.size, preferred=1024)
    stft = np.abs(librosa.stft(y=signal, n_fft=n_fft, hop_length=hop_length, center=True))
    if stft.shape[1] <= 1:
        zeros = np.zeros(max(1, stft.shape[1]), dtype=np.float32)
        return zeros, zeros, zeros

    flux = np.maximum(0.0, np.diff(np.log1p(stft), axis=1))
    flux = np.pad(flux, ((0, 0), (1, 0)))
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)

    def _band(mask: np.ndarray) -> np.ndarray:
        if not np.any(mask):
            return np.zeros(flux.shape[1], dtype=np.float32)
        return np.mean(flux[mask], axis=0).astype(np.float32)

    low = _band(freqs < 180.0)
    mid = _band((freqs >= 180.0) & (freqs < 2500.0))
    high = _band(freqs >= 2500.0)
    return low, mid, high


def _normalize_envelope(values: np.ndarray) -> np.ndarray:
    envelope = np.asarray(values, dtype=np.float32)
    if envelope.size == 0:
        return envelope
    envelope = np.maximum(envelope, 0.0)
    positive = envelope[envelope > 1e-8]
    if positive.size == 0:
        return np.zeros_like(envelope)
    scale = float(np.quantile(positive, 0.95))
    if scale <= 1e-8:
        scale = float(np.max(positive))
    if scale <= 1e-8:
        return np.zeros_like(envelope)
    return np.clip(envelope / scale, 0.0, 1.5)


def _build_onset_hints(
    *,
    onset_times: np.ndarray,
    sample_rate: int,
    hop_length: int,
    combined_env: np.ndarray,
    low_env: np.ndarray,
    mid_env: np.ndarray,
    high_env: np.ndarray,
) -> list[_OnsetHint]:
    hints: list[_OnsetHint] = []
    for time_s in onset_times.tolist():
        frame = int(np.clip(round((time_s * sample_rate) / float(hop_length)), 0, max(combined_env.size - 1, 0)))
        hints.append(
            _OnsetHint(
                time_s=float(time_s),
                combined_strength=float(combined_env[frame]) if combined_env.size else 0.0,
                low_strength=float(low_env[frame]) if low_env.size else 0.0,
                mid_strength=float(mid_env[frame]) if mid_env.size else 0.0,
                high_strength=float(high_env[frame]) if high_env.size else 0.0,
            )
        )
    return hints


def _refine_onset_time(signal: np.ndarray, sample_rate: int, time_s: float) -> float:
    center = int(np.clip(time_s * sample_rate, 0, max(signal.size - 1, 0)))
    search_radius = max(1, int(sample_rate * 0.02))
    start = max(0, center - search_radius)
    end = min(signal.size, center + search_radius)
    segment = np.abs(signal[start:end])
    if segment.size == 0:
        return float(time_s)

    derivative = np.diff(segment, prepend=segment[0])
    peak_index = int(np.argmax((0.65 * segment) + (0.35 * np.maximum(derivative, 0.0))))
    refined = (start + peak_index) / float(sample_rate)
    return float(min(time_s, refined))


def _prune_onset_times(
    *,
    signal: np.ndarray,
    sample_rate: int,
    onset_times: list[float],
    strengths: list[float],
    duration_s: float,
    min_separation_s: float = 0.055,
    strength_floor: float = 0.12,
    peak_floor: float = 0.03,
    trailing_strength_floor: float = 0.16,
    trailing_peak_floor: float = 0.08,
) -> list[float]:
    candidates = sorted(
        (
            (
                float(np.clip(time_s, 0.0, duration_s)),
                float(max(0.0, strength)),
                _local_peak(signal, sample_rate, float(np.clip(time_s, 0.0, duration_s))),
            )
            for time_s, strength in zip(onset_times, strengths)
        ),
        key=lambda item: item[0],
    )

    pruned: list[tuple[float, float, float]] = []
    for time_s, strength, local_peak in candidates:
        if strength < strength_floor and local_peak < peak_floor:
            continue
        if pruned and (time_s - pruned[-1][0]) < min_separation_s:
            previous = pruned[-1]
            previous_score = previous[1] + (0.4 * previous[2])
            current_score = strength + (0.4 * local_peak)
            if current_score > previous_score:
                pruned[-1] = (time_s, strength, local_peak)
            continue
        pruned.append((time_s, strength, local_peak))

    cleaned: list[float] = []
    for index, (time_s, strength, local_peak) in enumerate(pruned):
        next_gap = pruned[index + 1][0] - time_s if index + 1 < len(pruned) else duration_s - time_s
        if (
            index > 0
            and next_gap > 0.14
            and strength < trailing_strength_floor
            and local_peak < trailing_peak_floor
            and (time_s - pruned[index - 1][0]) < 0.18
        ):
            continue
        cleaned.append(time_s)

    if _local_peak(signal, sample_rate, 0.0) >= 0.12:
        if not cleaned or cleaned[0] > 0.03:
            cleaned.insert(0, 0.0)

    return cleaned


def _local_peak(signal: np.ndarray, sample_rate: int, time_s: float, *, window_s: float = 0.035) -> float:
    center = int(np.clip(time_s * sample_rate, 0, max(signal.size - 1, 0)))
    radius = max(1, int(window_s * sample_rate))
    start = max(0, center)
    end = min(signal.size, center + radius)
    if end <= start:
        return 0.0
    return float(np.max(np.abs(signal[start:end])))


def _regularity_score(onset_times: np.ndarray) -> float:
    if onset_times.size < 3:
        return 0.0
    intervals = np.diff(onset_times)
    mean_interval = float(np.mean(intervals))
    if mean_interval <= 1e-6:
        return 0.0
    deviation = float(np.std(intervals) / mean_interval)
    return float(np.clip(1.0 - deviation, 0.0, 0.99))


def _detect_transient_hits(
    signal: np.ndarray,
    sample_rate: int,
    onset_times: np.ndarray,
    onset_hints: list[_OnsetHint] | None = None,
    *,
    prepend_start_zero: bool = True,
    keep_low_energy_segments: bool = False,
) -> list[TransientHit]:
    duration_s = float(signal.size) / float(sample_rate)
    starts = onset_times.tolist() if onset_times.size else [0.0]
    if prepend_start_zero and starts and starts[0] > 0.035:
        starts.insert(0, 0.0)
    if not starts:
        starts = [0.0]

    hits: list[TransientHit] = []
    for index, start_s in enumerate(starts):
        hint = onset_hints[index] if onset_hints and index < len(onset_hints) else None
        end_s = starts[index + 1] if index + 1 < len(starts) else duration_s
        hit_end_s = max(end_s, min(duration_s, start_s + 0.035))
        start_index = int(max(0.0, start_s) * sample_rate)
        end_index = max(start_index + 1, int(hit_end_s * sample_rate))
        segment = signal[start_index:end_index]
        if segment.size == 0:
            continue
        if float(np.max(np.abs(segment))) <= (1e-5 if keep_low_energy_segments else 0.015):
            continue

        analysis_end_s = min(duration_s, start_s + min(0.18, max(0.08, (end_s - start_s) * 1.2)))
        analysis_end_index = max(start_index + 1, int(analysis_end_s * sample_rate))
        analysis_segment = signal[start_index:analysis_end_index]
        attack_end_index = max(start_index + 1, min(analysis_end_index, start_index + int(sample_rate * 0.08)))
        attack_segment = signal[start_index:attack_end_index]
        transient_profile = _measure_transient_profile(signal, sample_rate, float(start_s))

        body_features = _extract_features(analysis_segment, sample_rate)
        attack_features = _extract_features(attack_segment, sample_rate)
        candidates = _rank_hit_candidates(
            body_features,
            attack_features,
            hint=hint,
            profile=transient_profile,
            top_n=3,
        )
        primary = candidates[0]
        hits.append(
            TransientHit(
                index=index + 1,
                start_s=round(float(start_s), 4),
                end_s=round(float(hit_end_s), 4),
                label=primary.label,
                confidence=round(primary.score, 4),
                peak_db=round(body_features.peak_db, 2),
                low_ratio=round(body_features.low_ratio, 4),
                mid_ratio=round(body_features.mid_ratio, 4),
                high_ratio=round(body_features.high_ratio, 4),
            )
        )

    return hits


def _extract_features(signal: np.ndarray, sample_rate: int) -> _FeatureVector:
    librosa = _require_librosa()
    signal = _prepare_audio(signal)
    duration_s = float(signal.size) / float(sample_rate)
    n_fft = _safe_n_fft(signal.size, preferred=2048)
    hop_length = max(64, n_fft // 4)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"n_fft=.*too large for input signal of length=.*",
            category=UserWarning,
        )
        centroid = librosa.feature.spectral_centroid(
            y=signal,
            sr=sample_rate,
            n_fft=n_fft,
            hop_length=hop_length,
        )
        flatness = librosa.feature.spectral_flatness(
            y=signal,
            n_fft=n_fft,
            hop_length=hop_length,
        )
        zcr = librosa.feature.zero_crossing_rate(
            y=signal,
            frame_length=n_fft,
            hop_length=hop_length,
        )

    low_ratio, mid_ratio, high_ratio = _band_ratios(signal, sample_rate)
    decay_s, attack_score = _envelope_shape(signal, sample_rate)
    flatness_value = float(np.mean(flatness)) if flatness.size else 0.0
    zcr_value = float(np.mean(zcr)) if zcr.size else 0.0
    centroid_value = float(np.mean(centroid)) if centroid.size else 0.0
    noise_score = float(
        np.clip(
            (0.58 * np.sqrt(max(flatness_value, 0.0)))
            + (0.42 * np.clip(zcr_value / 0.24, 0.0, 1.0)),
            0.0,
            0.99,
        )
    )
    peak_db = 20.0 * math.log10(max(float(np.max(np.abs(signal))), 1e-5))

    return _FeatureVector(
        duration_s=duration_s,
        low_ratio=low_ratio,
        mid_ratio=mid_ratio,
        high_ratio=high_ratio,
        spectral_centroid_hz=centroid_value,
        spectral_flatness=flatness_value,
        zero_crossing_rate=zcr_value,
        decay_s=decay_s,
        attack_score=attack_score,
        noise_score=noise_score,
        peak_db=peak_db,
    )


def _band_ratios(signal: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    low, mid, high = _band_energies(signal, sample_rate)
    total = max(low + mid + high, 1e-8)
    return low / total, mid / total, high / total


def _band_energies(signal: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    windowed = signal * np.hanning(signal.size)
    spectrum = np.abs(np.fft.rfft(windowed)) ** 2
    freqs = np.fft.rfftfreq(signal.size, 1.0 / float(sample_rate))

    low = float(np.sum(spectrum[freqs < 180.0]))
    mid = float(np.sum(spectrum[(freqs >= 180.0) & (freqs < 2500.0)]))
    high = float(np.sum(spectrum[freqs >= 2500.0]))
    return low, mid, high


def _measure_transient_profile(signal: np.ndarray, sample_rate: int, time_s: float) -> _TransientProfile:
    center = int(np.clip(time_s * sample_rate, 0, max(signal.size - 1, 0)))
    pre_samples = max(16, int(sample_rate * 0.018))
    post_samples = max(32, int(sample_rate * 0.04))

    pre_start = max(0, center - pre_samples)
    pre_segment = signal[pre_start:center]
    post_end = min(signal.size, center + post_samples)
    post_segment = signal[center:post_end]

    if pre_segment.size < 16:
        pre_segment = np.zeros(32, dtype=np.float32)
    if post_segment.size < 16:
        post_segment = signal[max(0, center - 8) : min(signal.size, center + 24)]
    if post_segment.size < 16:
        return _TransientProfile(0.0, 0.0, 0.0, 0.0, 0.0)

    pre_low, pre_mid, pre_high = _band_energies(pre_segment, sample_rate)
    post_low, post_mid, post_high = _band_energies(post_segment, sample_rate)

    delta_low = max(post_low - (0.86 * pre_low), 0.0)
    delta_mid = max(post_mid - (0.78 * pre_mid), 0.0)
    delta_high = max(post_high - (0.68 * pre_high), 0.0)
    delta_total = max(delta_low + delta_mid + delta_high, 1e-8)

    pre_rms = float(np.sqrt(np.mean(np.square(pre_segment, dtype=np.float32)))) if pre_segment.size else 0.0
    post_rms = float(np.sqrt(np.mean(np.square(post_segment, dtype=np.float32)))) if post_segment.size else 0.0
    energy_rise = float(np.clip((post_rms - pre_rms) / max(post_rms, 1e-8), 0.0, 1.0))
    pre_level = float(np.clip(pre_rms / max(post_rms, 1e-8), 0.0, 1.0))

    return _TransientProfile(
        low_ratio=float(delta_low / delta_total),
        mid_ratio=float(delta_mid / delta_total),
        high_ratio=float(delta_high / delta_total),
        energy_rise=energy_rise,
        pre_level=pre_level,
    )


def _envelope_shape(signal: np.ndarray, sample_rate: int) -> tuple[float, float]:
    envelope = np.abs(signal)
    window = max(8, int(sample_rate * 0.003))
    if window > 1:
        kernel = np.ones(window, dtype=np.float32) / float(window)
        envelope = np.convolve(envelope, kernel, mode="same")

    peak_index = int(np.argmax(envelope))
    peak_value = float(envelope[peak_index]) if envelope.size else 0.0
    if peak_value <= 1e-8:
        return 0.0, 0.0

    baseline = float(np.mean(envelope[: max(1, min(peak_index, window * 2))])) if peak_index > 0 else 0.0
    attack_score = float(np.clip((peak_value - baseline) / max(peak_value, 1e-8), 0.0, 0.99))

    threshold = peak_value * 0.18
    tail = envelope[peak_index:]
    below = np.flatnonzero(tail <= threshold)
    decay_samples = int(below[0]) if below.size else max(0, tail.size - 1)
    decay_s = float(decay_samples) / float(sample_rate)
    return decay_s, attack_score


def _rank_one_shot_candidates(features: _FeatureVector, *, top_n: int) -> list[DrumCandidate]:
    centroid_norm = np.clip(features.spectral_centroid_hz / 7000.0, 0.0, 1.0)
    short_decay = _target_score(features.decay_s, target=0.07, width=0.12)
    medium_decay = _target_score(features.decay_s, target=0.22, width=0.2)
    long_decay = _target_score(features.decay_s, target=0.65, width=0.55)
    hat_decay = _target_score(features.decay_s, target=0.28, width=0.22)
    centroid_mid = _target_score(centroid_norm, target=0.34, width=0.22)
    centroid_high = _target_score(centroid_norm, target=0.82, width=0.22)
    tonal_hint = np.clip((1.0 - features.noise_score) * (features.low_ratio + features.mid_ratio), 0.0, 1.0)
    hat_mid_clean = np.clip(1.0 - (features.mid_ratio / 0.24), 0.0, 1.0)

    scores: dict[str, float] = {
        "kick": np.clip(
            (0.48 * features.low_ratio)
            + (0.14 * (1.0 - centroid_norm))
            + (0.12 * (1.0 - features.noise_score))
            + (0.14 * features.attack_score)
            + (0.12 * _target_score(features.decay_s, target=0.18, width=0.18)),
            0.0,
            0.99,
        ),
        "snare": np.clip(
            (0.26 * features.mid_ratio)
            + (0.12 * features.high_ratio)
            + (0.18 * features.noise_score)
            + (0.12 * features.attack_score)
            + (0.08 * centroid_mid)
            + (0.12 * (1.0 - features.low_ratio))
            + (0.12 * medium_decay)
            + (0.12 * short_decay),
            0.0,
            0.99,
        ),
        "clap": np.clip(
            (0.22 * features.mid_ratio)
            + (0.18 * features.high_ratio)
            + (0.18 * features.noise_score)
            + (0.16 * features.attack_score)
            + (0.14 * _target_score(features.decay_s, target=0.16, width=0.14))
            + (0.12 * (1.0 - features.low_ratio)),
            0.0,
            0.99,
        ),
        "closed_hat": np.clip(
            (0.28 * features.high_ratio)
            + (0.16 * features.noise_score)
            + (0.14 * centroid_high)
            + (0.18 * short_decay)
            + (0.12 * (1.0 - features.low_ratio)),
            0.0,
            0.99,
        ),
        "open_hat": np.clip(
            (0.28 * features.high_ratio)
            + (0.16 * features.noise_score)
            + (0.14 * centroid_high)
            + (0.18 * hat_decay)
            + (0.12 * features.attack_score)
            + (0.12 * hat_mid_clean),
            0.0,
            0.99,
        ),
        "crash": np.clip(
            (0.24 * features.high_ratio)
            + (0.16 * features.noise_score)
            + (0.12 * centroid_high)
            + (0.26 * long_decay)
            + (0.12 * _target_score(features.duration_s, target=0.9, width=0.7))
            + (0.1 * hat_mid_clean),
            0.0,
            0.99,
        ),
        "tom": np.clip(
            (0.24 * features.low_ratio)
            + (0.28 * features.mid_ratio)
            + (0.14 * tonal_hint)
            + (0.16 * medium_decay)
            + (0.08 * (1.0 - features.high_ratio))
            + (0.1 * (1.0 - features.noise_score)),
            0.0,
            0.99,
        ),
        "perc": np.clip(
            (0.24 * features.mid_ratio)
            + (0.16 * features.high_ratio)
            + (0.18 * features.attack_score)
            + (0.14 * features.noise_score)
            + (0.12 * _target_score(features.decay_s, target=0.12, width=0.24))
            + 0.12,
            0.0,
            0.99,
        ),
    }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [
        DrumCandidate(label=label, score=round(float(score), 4), details=_ONE_SHOT_DETAILS[label])
        for label, score in ranked[: max(1, top_n)]
    ]


def _rank_hit_candidates(
    body: _FeatureVector,
    attack: _FeatureVector,
    *,
    hint: _OnsetHint | None,
    profile: _TransientProfile | None,
    top_n: int,
) -> list[DrumCandidate]:
    body_centroid_norm = np.clip(body.spectral_centroid_hz / 7000.0, 0.0, 1.0)
    attack_centroid_norm = np.clip(attack.spectral_centroid_hz / 7000.0, 0.0, 1.0)
    short_decay = _target_score(body.decay_s, target=0.06, width=0.1)
    medium_decay = _target_score(body.decay_s, target=0.16, width=0.18)
    long_decay = _target_score(body.decay_s, target=0.45, width=0.4)
    hat_mid_clean = np.clip(1.0 - (attack.mid_ratio / 0.24), 0.0, 1.0)
    mid_focus = np.clip((attack.mid_ratio * 1.35) - (attack.low_ratio * 0.2), 0.0, 1.0)
    snare_mid_presence = np.clip((attack.mid_ratio + body.mid_ratio) / 0.46, 0.0, 1.0)
    hat_mid_penalty = np.clip((attack.mid_ratio + body.mid_ratio) / 0.42, 0.0, 1.0)
    onset_low = hint.low_strength if hint is not None else 0.0
    onset_mid = hint.mid_strength if hint is not None else 0.0
    onset_high = hint.high_strength if hint is not None else 0.0
    transient_low = profile.low_ratio if profile is not None else 0.0
    transient_mid = profile.mid_ratio if profile is not None else 0.0
    transient_high = profile.high_ratio if profile is not None else 0.0
    transient_rise = profile.energy_rise if profile is not None else 0.0
    transient_tail = profile.pre_level if profile is not None else 0.0

    scores: dict[str, float] = {
        "kick": np.clip(
            (0.36 * body.low_ratio)
            + (0.16 * _target_score(body.decay_s, target=0.13, width=0.14))
            + (0.12 * attack.low_ratio)
            + (0.1 * (1.0 - body_centroid_norm))
            + (0.1 * (1.0 - attack.noise_score))
            + (0.08 * body.attack_score)
            + (0.1 * onset_low)
            + (0.14 * transient_low)
            - (0.08 * onset_high),
            0.0,
            0.99,
        ),
        "snare": np.clip(
            (0.2 * mid_focus)
            + (0.16 * attack.high_ratio)
            + (0.18 * attack.noise_score)
            + (0.12 * medium_decay)
            + (0.1 * body.mid_ratio)
            + (0.1 * snare_mid_presence)
            + (0.1 * short_decay)
            + (0.08 * (1.0 - body.low_ratio))
            + (0.06 * _target_score(attack_centroid_norm, target=0.56, width=0.26))
            + (0.08 * onset_mid)
            + (0.04 * onset_high)
            + (0.08 * transient_mid)
            + (0.06 * transient_high),
            0.0,
            0.99,
        ),
        "clap": np.clip(
            (0.16 * mid_focus)
            + (0.2 * attack.high_ratio)
            + (0.18 * attack.noise_score)
            + (0.14 * short_decay)
            + (0.1 * body.attack_score)
            + (0.08 * snare_mid_presence)
            + (0.08 * hat_mid_clean)
            + (0.08 * (1.0 - body.low_ratio))
            + (0.06 * onset_mid)
            + (0.05 * onset_high)
            + (0.06 * transient_mid)
            + (0.08 * transient_high),
            0.0,
            0.99,
        ),
        "closed_hat": np.clip(
            (0.28 * attack.high_ratio)
            + (0.18 * attack.noise_score)
            + (0.16 * short_decay)
            + (0.14 * hat_mid_clean)
            + (0.12 * _target_score(attack_centroid_norm, target=0.82, width=0.22))
            + (0.06 * (1.0 - body.low_ratio))
            + (0.12 * onset_high)
            + (0.18 * transient_high)
            + (0.06 * transient_rise)
            - (0.12 * hat_mid_penalty)
            - (0.08 * transient_low),
            0.0,
            0.99,
        ),
        "open_hat": np.clip(
            (0.24 * attack.high_ratio)
            + (0.16 * attack.noise_score)
            + (0.14 * _target_score(body.decay_s, target=0.18, width=0.16))
            + (0.14 * hat_mid_clean)
            + (0.12 * _target_score(attack_centroid_norm, target=0.82, width=0.22))
            + (0.08 * body.attack_score)
            + (0.1 * onset_high)
            + (0.14 * transient_high)
            + (0.06 * transient_rise)
            - (0.1 * hat_mid_penalty)
            - (0.06 * transient_low),
            0.0,
            0.99,
        ),
        "crash": np.clip(
            (0.22 * attack.high_ratio)
            + (0.14 * attack.noise_score)
            + (0.2 * long_decay)
            + (0.12 * _target_score(body.duration_s, target=0.18, width=0.14))
            + (0.12 * hat_mid_clean)
            + (0.08 * _target_score(attack_centroid_norm, target=0.78, width=0.24))
            + (0.08 * onset_high)
            + (0.12 * transient_high)
            - (0.08 * hat_mid_penalty),
            0.0,
            0.99,
        ),
        "tom": np.clip(
            (0.22 * body.low_ratio)
            + (0.22 * body.mid_ratio)
            + (0.12 * _target_score(body.decay_s, target=0.16, width=0.16))
            + (0.1 * (1.0 - attack.noise_score))
            + (0.08 * attack.low_ratio)
            + (0.06 * (1.0 - body.high_ratio))
            + (0.06 * transient_low)
            + (0.04 * transient_mid),
            0.0,
            0.99,
        ),
        "perc": np.clip(
            (0.16 * body.mid_ratio)
            + (0.14 * attack.high_ratio)
            + (0.16 * body.attack_score)
            + (0.12 * attack.noise_score)
            + (0.12 * _target_score(body.decay_s, target=0.1, width=0.18))
            + (0.06 * transient_mid)
            + (0.06 * transient_high)
            + 0.12,
            0.0,
            0.99,
        ),
    }

    if transient_high >= 0.52 and onset_high >= max(onset_low * 1.15, 0.2):
        scores["closed_hat"] = float(np.clip(scores["closed_hat"] + 0.06, 0.0, 0.99))
        scores["open_hat"] = float(np.clip(scores["open_hat"] + 0.03, 0.0, 0.99))
        scores["kick"] = float(np.clip(scores["kick"] - 0.08, 0.0, 0.99))

    if transient_low >= 0.5 and transient_tail <= 0.55 and onset_low >= onset_high:
        scores["kick"] = float(np.clip(scores["kick"] + 0.05, 0.0, 0.99))
        scores["closed_hat"] = float(np.clip(scores["closed_hat"] - 0.04, 0.0, 0.99))

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [
        DrumCandidate(label=label, score=round(float(score), 4), details=_ONE_SHOT_DETAILS[label])
        for label, score in ranked[: max(1, top_n)]
    ]


def _rank_loop_candidates(
    *,
    features: _FeatureVector,
    hits: list[TransientHit],
    pulse_score: float,
    regularity: float,
    onset_density: float,
    percussive_ratio: float,
    top_n: int,
) -> tuple[list[DrumCandidate], float]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.label] = counts.get(hit.label, 0) + 1

    total_hits = max(len(hits), 1)
    kick_presence = 1.0 if counts.get("kick", 0) > 0 else 0.0
    snare_presence = 1.0 if counts.get("snare", 0) > 0 or counts.get("clap", 0) > 0 else 0.0
    hat_presence = 1.0 if sum(counts.get(label, 0) for label in ("closed_hat", "open_hat", "crash")) > 0 else 0.0
    hit_diversity = float(np.clip(len(counts) / max(min(total_hits, 4), 1), 0.0, 1.0))
    loop_energy = np.clip(onset_density / 8.0, 0.0, 1.0)

    break_score = float(
        np.clip(
            (0.24 * pulse_score)
            + (0.16 * regularity)
            + (0.18 * percussive_ratio)
            + (0.16 * loop_energy)
            + (0.12 * hit_diversity)
            + (0.08 * kick_presence)
            + (0.06 * snare_presence),
            0.0,
            0.99,
        )
    )
    top_loop_score = float(
        np.clip(
            (0.34 * features.high_ratio)
            + (0.22 * hat_presence)
            + (0.18 * pulse_score)
            + (0.14 * (1.0 - features.low_ratio))
            + (0.12 * (1.0 - kick_presence)),
            0.0,
            0.99,
        )
    )
    perc_loop_score = float(
        np.clip(
            (0.22 * features.mid_ratio)
            + (0.18 * features.high_ratio)
            + (0.18 * percussive_ratio)
            + (0.16 * hit_diversity)
            + (0.14 * (1.0 - kick_presence))
            + (0.12 * loop_energy),
            0.0,
            0.99,
        )
    )
    drum_loop_score = float(
        np.clip(
            (0.3 * percussive_ratio)
            + (0.22 * pulse_score)
            + (0.16 * regularity)
            + (0.14 * loop_energy)
            + (0.08 * kick_presence)
            + (0.1 * snare_presence),
            0.0,
            0.99,
        )
    )

    candidates = [
        DrumCandidate("break", round(break_score, 4), "plusieurs hits, pulsation credible, kick/snare presents"),
        DrumCandidate("drum_loop", round(drum_loop_score, 4), "loop percussive generaliste"),
        DrumCandidate("top_loop", round(top_loop_score, 4), "loop leger, surtout aigu / hats"),
        DrumCandidate("perc_loop", round(perc_loop_score, 4), "loop percussif sans pattern break tres net"),
    ]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[: max(1, top_n)], break_score


def _rank_non_drum_candidates(
    *,
    form: str,
    family: str,
    harmonic_ratio: float,
    noise_score: float,
    loop_score: float,
    top_n: int,
) -> list[DrumCandidate]:
    if family == "tonal":
        tonal_label = "tonal_loop" if form == "loop" else "tonal_one_shot"
        hybrid_label = "hybrid_loop" if form == "loop" else "hybrid_one_shot"
        fx_label = "fx_loop" if form == "loop" else "fx_one_shot"
        candidates = [
            DrumCandidate(tonal_label, round(float(np.clip(0.45 + (0.4 * harmonic_ratio) + (0.1 * (1.0 - noise_score)), 0.0, 0.99)), 4), "plutot tonal / harmonique"),
            DrumCandidate(hybrid_label, round(float(np.clip(0.28 + (0.2 * loop_score) + (0.2 * harmonic_ratio) + (0.15 * noise_score), 0.0, 0.99)), 4), "melange tonal et transient"),
            DrumCandidate(fx_label, round(float(np.clip(0.2 + (0.35 * noise_score), 0.0, 0.99)), 4), "plus bruit / texture que drum pur"),
        ]
    else:
        hybrid_label = "hybrid_loop" if form == "loop" else "hybrid_one_shot"
        fx_label = "fx_loop" if form == "loop" else "fx_one_shot"
        tonal_label = "tonal_loop" if form == "loop" else "tonal_one_shot"
        candidates = [
            DrumCandidate(hybrid_label, round(float(np.clip(0.34 + (0.26 * loop_score) + (0.16 * harmonic_ratio) + (0.16 * noise_score), 0.0, 0.99)), 4), "transient mais ambigu / layer"),
            DrumCandidate(fx_label, round(float(np.clip(0.24 + (0.32 * noise_score), 0.0, 0.99)), 4), "texture, sweep ou bruit percussif"),
            DrumCandidate(tonal_label, round(float(np.clip(0.18 + (0.25 * harmonic_ratio), 0.0, 0.99)), 4), "contenu harmonique present"),
        ]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[: max(1, top_n)]


def _loop_score(
    *,
    duration_s: float,
    onset_count: int,
    onset_density: float,
    pulse_score: float,
    regularity: float,
    percussive_ratio: float,
) -> float:
    duration_score = np.clip((duration_s - 0.55) / 1.2, 0.0, 1.0)
    onset_score = np.clip((onset_count - 1) / 7.0, 0.0, 1.0)
    density_score = np.clip(onset_density / 8.0, 0.0, 1.0)
    return float(
        np.clip(
            (0.24 * duration_score)
            + (0.2 * onset_score)
            + (0.16 * density_score)
            + (0.22 * pulse_score)
            + (0.1 * regularity)
            + (0.08 * percussive_ratio),
            0.0,
            0.99,
        )
    )


def _drum_score(
    *,
    percussive_ratio: float,
    harmonic_ratio: float,
    onset_density: float,
    noise_score: float,
    attack_score: float,
    low_ratio: float,
    decay_s: float,
) -> float:
    onset_score = np.clip(onset_density / 7.0, 0.0, 1.0)
    short_decay = _target_score(decay_s, target=0.18, width=0.22)
    return float(
        np.clip(
            (0.2 * percussive_ratio)
            + (0.16 * onset_score)
            + (0.14 * noise_score)
            + (0.22 * attack_score)
            + (0.18 * low_ratio)
            + (0.1 * short_decay)
            + (0.08 * (1.0 - harmonic_ratio)),
            0.0,
            0.99,
        )
    )


def _tonal_score(
    *,
    harmonic_ratio: float,
    percussive_ratio: float,
    noise_score: float,
    onset_density: float,
    decay_s: float,
) -> float:
    sustained = _target_score(decay_s, target=0.6, width=0.5)
    sparse_onsets = 1.0 - np.clip(onset_density / 5.0, 0.0, 1.0)
    return float(
        np.clip(
            (0.36 * harmonic_ratio)
            + (0.16 * (1.0 - percussive_ratio))
            + (0.16 * (1.0 - noise_score))
            + (0.18 * sparse_onsets)
            + (0.1 * sustained),
            0.0,
            0.99,
        )
    )


def _choose_family(drum_score: float, tonal_score: float, noise_score: float) -> str:
    if drum_score >= tonal_score + 0.05 and drum_score >= 0.4:
        return "drum"
    if tonal_score >= drum_score + 0.05 and tonal_score >= 0.36:
        return "tonal"
    if noise_score >= 0.55:
        return "fx"
    return "hybrid"


def _result_confidence(
    *,
    top_score: float,
    margin: float,
    drum_score: float,
    loop_score: float,
    break_score: float,
    family: str,
    form: str,
) -> float:
    base = 0.2 + (0.55 * top_score) + (0.55 * margin)
    if family == "drum":
        base += 0.1 * drum_score
        if form == "loop":
            base += 0.08 * max(loop_score, break_score)
    else:
        base += 0.05 * max(loop_score, 0.2)
    return float(np.clip(base, 0.0, 0.99))


def _target_score(value: float, *, target: float, width: float) -> float:
    if width <= 1e-8:
        return 0.0
    return float(np.clip(1.0 - (abs(value - target) / width), 0.0, 1.0))


def _safe_ratio(part: float, total: float) -> float:
    return float(part / max(total, 1e-8))


def _energy(signal: np.ndarray) -> float:
    return float(np.sum(np.asarray(signal, dtype=np.float32) ** 2))


def _next_pow2(value: int) -> int:
    return 1 << max(1, int(math.ceil(math.log2(max(value, 2)))))


def _safe_n_fft(num_samples: int, *, preferred: int) -> int:
    if num_samples <= 32:
        return 32
    upper = min(preferred, num_samples)
    power = 2 ** int(math.floor(math.log2(max(upper, 32))))
    return int(max(32, power))
