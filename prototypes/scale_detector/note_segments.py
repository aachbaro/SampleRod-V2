from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .analyzer import (
    NOTE_NAMES,
    _harmonic_component,
    _l1_normalize,
    _prepare_audio,
    _require_librosa,
)


@dataclass(frozen=True)
class NoteSegment:
    start_s: float
    end_s: float
    label: str
    kind: str
    dominant_label: str
    note: str
    octave: int
    midi: int
    hz: float
    confidence: float
    voiced_ratio: float
    active_notes: tuple[str, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["active_notes"] = list(self.active_notes)
        return payload


def detect_note_segments_file(
    path: str | Path,
    *,
    min_segment_s: float = 0.08,
) -> tuple[NoteSegment, ...]:
    librosa = _require_librosa()
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    audio, sample_rate = librosa.load(str(source), sr=None, mono=True)
    return detect_note_segments(audio, sample_rate, min_segment_s=min_segment_s)


def detect_note_segments(
    audio: np.ndarray,
    sample_rate: int,
    *,
    min_segment_s: float = 0.08,
) -> tuple[NoteSegment, ...]:
    librosa = _require_librosa()
    signal = _prepare_audio(audio)
    if signal.size < max(2048, sample_rate // 8):
        return ()

    harmonic = _harmonic_component(signal)
    hop_length = 256 if signal.size < sample_rate * 12 else 512
    duration_s = float(signal.size) / float(sample_rate)

    onset_env = librosa.onset.onset_strength(
        y=harmonic,
        sr=sample_rate,
        hop_length=hop_length,
        aggregate=np.median,
    )
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sample_rate,
        hop_length=hop_length,
        units="frames",
        backtrack=True,
        pre_max=3,
        post_max=3,
        pre_avg=3,
        post_avg=5,
        delta=0.12,
        wait=2,
    )

    f0, _, voiced_prob = librosa.pyin(
        harmonic,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sample_rate,
        hop_length=hop_length,
        frame_length=2048,
    )
    frame_times = librosa.times_like(f0, sr=sample_rate, hop_length=hop_length)
    onset_times = librosa.frames_to_time(onset_frames, sr=sample_rate, hop_length=hop_length)
    pitch_change_times = _pitch_change_boundaries(f0, frame_times)
    boundaries = _build_boundaries(
        np.concatenate((np.asarray(onset_times), np.asarray(pitch_change_times))),
        duration_s,
    )

    raw_segments: list[NoteSegment] = []
    for start_s, end_s in zip(boundaries[:-1], boundaries[1:]):
        if end_s - start_s < 0.035:
            continue

        frame_mask = (frame_times >= start_s) & (
            frame_times <= end_s if end_s >= duration_s - 1e-6 else frame_times < end_s
        )
        frame_indices = np.flatnonzero(frame_mask)
        if frame_indices.size == 0:
            continue

        segment = signal[int(start_s * sample_rate) : max(int(end_s * sample_rate), int(start_s * sample_rate) + 1)]
        if segment.size == 0:
            continue

        harmonic_segment = _harmonic_component(segment)
        chroma_profile = _segment_chroma_profile(harmonic_segment, sample_rate)
        active_indices = _active_pitch_classes(chroma_profile)
        active_notes = tuple(NOTE_NAMES[index] for index in active_indices)
        dominant_pc = int(np.argmax(chroma_profile)) if np.any(chroma_profile) else 0
        strongest = float(np.max(chroma_profile)) if np.any(chroma_profile) else 0.0
        second = float(np.partition(chroma_profile, -2)[-2]) if chroma_profile.size > 1 else 0.0

        segment_peak = float(np.max(np.abs(segment)))
        voiced_hz = f0[frame_indices]
        voiced_hz = voiced_hz[~np.isnan(voiced_hz)]
        voiced_ratio = float(voiced_hz.size / frame_indices.size)

        if voiced_hz.size == 0 and segment_peak < 0.05:
            continue

        if voiced_hz.size == 0 and len(active_indices) == 0:
            continue

        if voiced_hz.size == 0 or voiced_ratio < 0.18:
            if segment_peak < 0.05:
                continue
            midi_values = np.array([], dtype=np.float32)
            midi = dominant_pc
            note_name = NOTE_NAMES[dominant_pc]
            octave = -1
            pitch_spread = 1.0
            stability = 0.0
            dominant_hz = 0.0
        else:
            midi_values = librosa.hz_to_midi(voiced_hz)
            median_midi = float(np.median(midi_values))
            midi = int(round(median_midi))
            note_name = NOTE_NAMES[midi % 12]
            octave = (midi // 12) - 1
            pitch_spread = float(np.std(midi_values))
            stability = max(0.0, 1.0 - min(pitch_spread / 0.75, 1.0))
            dominant_hz = float(np.median(voiced_hz))

        if voiced_prob is not None:
            probs = voiced_prob[frame_indices]
            probs = probs[~np.isnan(probs)]
            mean_prob = float(np.mean(probs)) if probs.size else 0.0
        else:
            mean_prob = 0.0

        kind = _classify_segment(
            chroma_profile,
            active_indices,
            voiced_ratio=voiced_ratio,
            pitch_spread=pitch_spread,
        )
        dominant_label = note_name if octave < 0 else f"{note_name}{octave}"
        label = dominant_label if kind == "mono" else "+".join(active_notes[:4])
        chroma_focus = float(np.sum(chroma_profile[active_indices[:4]])) if len(active_indices) else strongest
        confidence = max(
            0.0,
            min(
                0.99,
                0.16
                + (0.28 * voiced_ratio)
                + (0.2 * mean_prob)
                + (0.14 * stability)
                + (0.16 * chroma_focus)
                + (0.08 * max(0.0, second)),
            ),
        )
        raw_segments.append(
            NoteSegment(
                start_s=round(float(start_s), 4),
                end_s=round(float(end_s), 4),
                label=label,
                kind=kind,
                dominant_label=dominant_label,
                note=note_name,
                octave=octave,
                midi=midi,
                hz=round(dominant_hz, 4),
                confidence=round(confidence, 4),
                voiced_ratio=round(voiced_ratio, 4),
                active_notes=active_notes,
            )
        )

    merged = _merge_adjacent_segments(raw_segments)
    filtered = [segment for segment in merged if (segment.end_s - segment.start_s) >= min_segment_s]
    if filtered:
        return tuple(filtered)
    return tuple(merged[:1]) if merged else ()


def _build_boundaries(onset_times: np.ndarray, duration_s: float) -> list[float]:
    boundaries = [0.0]
    for time_s in np.asarray(onset_times, dtype=np.float32):
        value = float(np.clip(time_s, 0.0, duration_s))
        if value <= 0.0:
            continue
        if abs(value - boundaries[-1]) < 0.03:
            continue
        boundaries.append(value)
    if duration_s - boundaries[-1] > 1e-6:
        boundaries.append(duration_s)
    if len(boundaries) == 1:
        boundaries.append(duration_s)
    return boundaries


def _pitch_change_boundaries(
    f0: np.ndarray,
    frame_times: np.ndarray,
    *,
    min_run_frames: int = 3,
) -> list[float]:
    librosa = _require_librosa()
    if f0.size == 0:
        return []

    rounded_midi = np.full(f0.shape, np.nan, dtype=np.float32)
    valid = ~np.isnan(f0)
    if np.any(valid):
        rounded_midi[valid] = np.round(librosa.hz_to_midi(f0[valid]))

    changes: list[float] = []
    previous_note: int | None = None
    index = 0
    while index < rounded_midi.size:
        if np.isnan(rounded_midi[index]):
            index += 1
            continue

        note = int(rounded_midi[index])
        run_start = index
        while (
            index + 1 < rounded_midi.size
            and not np.isnan(rounded_midi[index + 1])
            and int(rounded_midi[index + 1]) == note
        ):
            index += 1
        run_end = index
        run_length = run_end - run_start + 1

        if previous_note is not None and note != previous_note and run_length >= min_run_frames:
            changes.append(float(frame_times[run_start]))

        previous_note = note
        index += 1

    return changes


def _segment_chroma_profile(segment: np.ndarray, sample_rate: int) -> np.ndarray:
    librosa = _require_librosa()
    if segment.size == 0:
        return np.zeros(12, dtype=np.float32)

    hop_length = 128 if segment.size < sample_rate * 3 else 256
    try:
        chroma = librosa.feature.chroma_cqt(
            y=segment,
            sr=sample_rate,
            hop_length=hop_length,
            bins_per_octave=36,
            n_chroma=12,
        )
    except Exception:
        chroma = librosa.feature.chroma_stft(
            y=segment,
            sr=sample_rate,
            hop_length=hop_length,
            n_fft=_safe_n_fft(segment.size, preferred=4096),
        )

    rms = librosa.feature.rms(
        y=segment,
        frame_length=min(2048, max(512, segment.size)),
        hop_length=hop_length,
    ).reshape(-1)
    frame_count = min(chroma.shape[1], rms.shape[0])
    if frame_count <= 0:
        return np.zeros(12, dtype=np.float32)

    chroma = chroma[:, :frame_count]
    rms = rms[:frame_count]
    weights = rms if float(np.sum(rms)) > 1e-8 else np.ones(frame_count, dtype=np.float32)
    profile = np.average(chroma, axis=1, weights=weights)
    return _l1_normalize(profile)


def _safe_n_fft(num_samples: int, *, preferred: int) -> int:
    if num_samples <= 32:
        return 32
    upper = min(preferred, num_samples)
    power = 2 ** int(np.floor(np.log2(max(upper, 32))))
    return int(max(32, power))


def _active_pitch_classes(profile: np.ndarray) -> np.ndarray:
    if profile.size == 0 or float(np.max(profile)) <= 1e-8:
        return np.array([], dtype=int)

    strongest = float(np.max(profile))
    threshold = max(0.14, strongest * 0.55)
    active = np.flatnonzero(profile >= threshold).astype(int)
    if active.size == 0:
        return np.array([int(np.argmax(profile))], dtype=int)
    return np.array(sorted(active.tolist()), dtype=int)


def _classify_segment(
    profile: np.ndarray,
    active_indices: np.ndarray,
    *,
    voiced_ratio: float,
    pitch_spread: float,
) -> str:
    if active_indices.size <= 1:
        return "mono"

    ordered = np.sort(profile)
    strongest = float(ordered[-1]) if ordered.size else 0.0
    second = float(ordered[-2]) if ordered.size > 1 else 0.0
    top3 = float(np.sum(ordered[-3:])) if ordered.size >= 3 else float(np.sum(ordered))

    if active_indices.size >= 3 and top3 >= 0.7:
        return "poly"
    if second >= max(0.18, strongest * 0.72) and (voiced_ratio < 0.78 or pitch_spread > 0.35):
        return "poly"
    if active_indices.size >= 2 and second >= 0.22 and strongest <= 0.52:
        return "poly"
    return "mono"


def _merge_adjacent_segments(
    segments: list[NoteSegment],
    *,
    max_gap_s: float = 0.05,
) -> list[NoteSegment]:
    if not segments:
        return []

    merged = [segments[0]]
    for segment in segments[1:]:
        previous = merged[-1]
        gap = float(segment.start_s - previous.end_s)
        if (
            previous.kind == segment.kind
            and previous.active_notes == segment.active_notes
            and previous.dominant_label == segment.dominant_label
            and gap <= max_gap_s
        ):
            previous_duration = max(0.001, previous.end_s - previous.start_s)
            current_duration = max(0.001, segment.end_s - segment.start_s)
            total_duration = previous_duration + current_duration
            merged[-1] = NoteSegment(
                start_s=previous.start_s,
                end_s=segment.end_s,
                label=previous.label,
                kind=previous.kind,
                dominant_label=previous.dominant_label,
                note=previous.note,
                octave=previous.octave,
                midi=previous.midi,
                hz=round(
                    ((previous.hz * previous_duration) + (segment.hz * current_duration)) / total_duration,
                    4,
                ),
                confidence=round(
                    ((previous.confidence * previous_duration) + (segment.confidence * current_duration))
                    / total_duration,
                    4,
                ),
                voiced_ratio=round(
                    ((previous.voiced_ratio * previous_duration) + (segment.voiced_ratio * current_duration))
                    / total_duration,
                    4,
                ),
                active_notes=previous.active_notes,
            )
            continue
        merged.append(segment)
    return merged
