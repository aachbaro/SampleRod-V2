from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib import import_module
import math
from typing import Sequence
import warnings

import numpy as np

from .analyzer import TransientHit
from .pattern_generator import GeneratedBreakPattern, STRETCH_TICKS_PER_STEP


PREVIEW_MODE_RETIME = "retime"
PREVIEW_MODE_QUANTIZE = "quantize"
PREVIEW_MODE_PATTERN = "pattern"
QUANTIZE_GRID_DIVISIONS: tuple[int, ...] = (8, 16, 32)
DEFAULT_QUANTIZE_GRID_DIVISION = 16
DEFAULT_QUANTIZE_STRENGTH = 0.7
_GRID_LABELS = {8: "1/8", 16: "1/16", 32: "1/32"}
PATTERN_STEM_NAMES: tuple[str, ...] = (
    "kick",
    "snare",
    "hat",
    "ghost",
    "clap",
    "repeat",
    "reverse",
    "roll",
    "stretch",
    "other",
)


@lru_cache(maxsize=1)
def _require_librosa():
    try:
        return import_module("librosa")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Pitch movement dependency missing (librosa). "
            "Install project deps with `python -m pip install -r requirements.txt`."
        ) from exc


@dataclass(frozen=True)
class RetimedPreviewSegment:
    index: int
    source_start_s: float
    source_end_s: float
    preview_start_s: float
    preview_end_s: float
    label: str
    step_index: int | None = None
    source_index: int | None = None
    velocity: int | None = None
    stem: str | None = None


@dataclass(frozen=True)
class RetimedPreview:
    audio: np.ndarray
    loop_audio: np.ndarray | None
    sample_rate: int
    source_bpm: float
    target_bpm: float
    speed_ratio: float
    duration_s: float
    loop_duration_s: float
    segment_count: int
    segments: tuple[RetimedPreviewSegment, ...]
    mode: str = PREVIEW_MODE_RETIME
    quantize_grid_division: int | None = None
    quantize_strength: float = 0.0
    pattern: GeneratedBreakPattern | None = None
    stems: dict[str, np.ndarray] = field(default_factory=dict)
    loop_stems: dict[str, np.ndarray] = field(default_factory=dict)
    mono_choke: bool = False


@dataclass
class _RenderedPreviewEvent:
    start_frame: int
    segment: np.ndarray
    stem: str | None = None


def build_retimed_preview(
    samples: np.ndarray,
    sample_rate: int,
    hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str = PREVIEW_MODE_RETIME,
    quantize_grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = 0.0,
    fade_in_ms: float = 0.75,
    fade_out_ms: float = 5.0,
    mono_choke: bool = False,
) -> RetimedPreview:
    if sample_rate <= 0:
        raise ValueError("Sample rate must be strictly positive")
    if source_bpm <= 1.0 or target_bpm <= 1.0:
        raise ValueError("Source and target BPM must be strictly positive")

    ordered_hits = sorted(hits, key=lambda hit: float(hit.start_s))
    if len(ordered_hits) < 2:
        raise ValueError("Need at least two transient hits to build a retimed preview")

    normalized, was_mono = _normalize_audio_shape(samples)
    if normalized.size == 0:
        raise ValueError("Audio buffer is empty")

    resolved_mode = _resolve_preview_mode(mode)
    resolved_grid = _resolve_quantize_grid_division(quantize_grid_division)
    resolved_strength = _resolve_quantize_strength(quantize_strength)
    speed_ratio = float(source_bpm / target_bpm)
    channel_count = normalized.shape[1]
    segment_schedule = _build_segment_schedule(
        ordered_hits,
        source_bpm=source_bpm,
        target_bpm=target_bpm,
        mode=resolved_mode,
        quantize_grid_division=resolved_grid,
        quantize_strength=resolved_strength,
        mono_choke=bool(mono_choke),
    )

    rendered_segments: list[_RenderedPreviewEvent] = []
    output_length = 0
    for hit, scheduled_segment in zip(ordered_hits, segment_schedule):
        start_time = float(scheduled_segment.source_start_s)
        end_time = float(scheduled_segment.source_end_s)
        start_index = int(np.clip(round(start_time * sample_rate), 0, max(normalized.shape[0] - 1, 0)))
        end_index = int(np.clip(round(end_time * sample_rate), start_index + 1, normalized.shape[0]))
        if end_index <= start_index:
            continue

        segment = normalized[start_index:end_index].copy()
        _apply_edge_fades(
            segment,
            sample_rate=sample_rate,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

        new_start = int(round(float(scheduled_segment.preview_start_s) * sample_rate))
        rendered_segments.append(_RenderedPreviewEvent(start_frame=new_start, segment=segment))
        output_length = max(output_length, new_start + segment.shape[0])

    if not rendered_segments or output_length <= 0:
        raise ValueError("Could not build a retimed preview from the detected hits")

    if bool(mono_choke):
        segment_schedule, rendered_segments = _apply_global_mono_choke(
            segment_schedule,
            rendered_segments,
            sample_rate=sample_rate,
        )
        output_length = max(
            (event.start_frame + int(event.segment.shape[0]) for event in rendered_segments),
            default=0,
        )
        if output_length <= 0:
            raise ValueError("Could not build a retimed preview from the detected hits")

    output = np.zeros((output_length, channel_count), dtype=np.float32)
    for event in rendered_segments:
        new_end = min(output.shape[0], event.start_frame + event.segment.shape[0])
        output[event.start_frame:new_end] += event.segment[: new_end - event.start_frame]

    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0.98:
        output *= np.float32(0.98 / peak)

    restored = output[:, 0] if was_mono else output
    duration_s = float(output.shape[0]) / float(sample_rate)
    source_duration_s = float(normalized.shape[0]) / float(sample_rate)
    loop_duration_s = max(
        source_duration_s * speed_ratio,
        max(float(segment.preview_start_s) for segment in segment_schedule) + (1.0 / float(sample_rate)),
    )
    loop_audio = _build_loop_audio(output, sample_rate=sample_rate, loop_duration_s=loop_duration_s, was_mono=was_mono)
    return RetimedPreview(
        audio=restored.astype(np.float32, copy=False),
        loop_audio=loop_audio,
        sample_rate=int(sample_rate),
        source_bpm=float(source_bpm),
        target_bpm=float(target_bpm),
        speed_ratio=speed_ratio,
        duration_s=duration_s,
        loop_duration_s=loop_duration_s,
        segment_count=len(rendered_segments),
        segments=tuple(segment_schedule),
        mode=resolved_mode,
        quantize_grid_division=resolved_grid if resolved_mode == PREVIEW_MODE_QUANTIZE else None,
        quantize_strength=resolved_strength if resolved_mode == PREVIEW_MODE_QUANTIZE else 0.0,
        pattern=None,
        mono_choke=bool(mono_choke),
    )


def estimate_retimed_preview_duration(
    hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str = PREVIEW_MODE_RETIME,
    quantize_grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = 0.0,
    mono_choke: bool = False,
) -> float:
    if source_bpm <= 1.0 or target_bpm <= 1.0:
        return 0.0
    ordered_hits = sorted(hits, key=lambda hit: float(hit.start_s))
    if len(ordered_hits) < 2:
        return 0.0
    segment_schedule = _build_segment_schedule(
        ordered_hits,
        source_bpm=source_bpm,
        target_bpm=target_bpm,
        mode=mode,
        quantize_grid_division=quantize_grid_division,
        quantize_strength=quantize_strength,
        mono_choke=bool(mono_choke),
    )
    if not segment_schedule:
        return 0.0
    return max(float(segment.preview_end_s) for segment in segment_schedule)


def build_retimed_preview_schedule(
    hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str = PREVIEW_MODE_RETIME,
    quantize_grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = 0.0,
    mono_choke: bool = False,
) -> tuple[RetimedPreviewSegment, ...]:
    if source_bpm <= 1.0 or target_bpm <= 1.0:
        return ()
    ordered_hits = sorted(hits, key=lambda hit: float(hit.start_s))
    if len(ordered_hits) < 2:
        return ()
    return tuple(
        _build_segment_schedule(
            ordered_hits,
            source_bpm=source_bpm,
            target_bpm=target_bpm,
            mode=mode,
            quantize_grid_division=quantize_grid_division,
            quantize_strength=quantize_strength,
            mono_choke=bool(mono_choke),
        )
    )


def format_quantize_grid_label(grid_division: int | None) -> str:
    if grid_division is None:
        return "-"
    return _GRID_LABELS.get(int(grid_division), f"1/{int(grid_division)}")


def build_pattern_preview(
    samples: np.ndarray,
    sample_rate: int,
    pattern: GeneratedBreakPattern,
    *,
    target_bpm: float,
    gate: float | None = None,
    fade_in_ms: float = 0.75,
    fade_out_ms: float = 5.0,
    mono_choke: bool | None = None,
) -> RetimedPreview:
    if sample_rate <= 0:
        raise ValueError("Sample rate must be strictly positive")
    if target_bpm <= 1.0:
        raise ValueError("Target BPM must be strictly positive")

    normalized, was_mono = _normalize_audio_shape(samples)
    if normalized.size == 0:
        raise ValueError("Audio buffer is empty")

    scheduled_segments: list[RetimedPreviewSegment] = []
    rendered_segments: list[_RenderedPreviewEvent] = []
    step_duration_s = (60.0 / float(target_bpm)) / 4.0
    pattern_gate = getattr(getattr(pattern, "params", None), "gate", 1.0)
    raw_gate = pattern_gate if gate is None else gate
    try:
        resolved_gate = float(np.clip(float(raw_gate), 0.05, 1.0))
    except (TypeError, ValueError):
        resolved_gate = 1.0
    raw_mono_choke = getattr(getattr(pattern, "params", None), "mono_choke", False)
    resolved_mono_choke = bool(raw_mono_choke) if mono_choke is None else bool(mono_choke)
    channel_count = normalized.shape[1]
    output_length = 0

    for row_index, step in enumerate(pattern.steps, start=1):
        if step.source_start_s is None or step.source_end_s is None or step.label == "silence":
            continue
        stretch_meta = _pattern_step_snare_stretch_metadata(step)
        stretch_retriggers = _pattern_step_stretch_retriggers(step)
        ghost_meta = _pattern_step_synthetic_ghost_metadata(step)
        repeat_count = 1 if stretch_meta["active"] else _pattern_step_repeat_count(step)
        reverse_step = False if stretch_meta["active"] else _pattern_step_is_reverse(step)
        start_time = float(step.source_start_s)
        end_time = max(float(step.source_end_s), start_time + 0.012)
        effective_duration_s = end_time - start_time
        if (not stretch_meta["active"]) and resolved_gate < 0.999:
            effective_duration_s = max(0.012, effective_duration_s * resolved_gate)
        if repeat_count > 1:
            retrigger_interval_s = step_duration_s / float(repeat_count)
            effective_duration_s = min(effective_duration_s, max(0.012, retrigger_interval_s * 0.82))
        if reverse_step:
            reverse_slot_s = step_duration_s / float(max(1, repeat_count))
            effective_duration_s = min(effective_duration_s, max(0.012, reverse_slot_s * 0.98))
        end_time = min(end_time, start_time + effective_duration_s)
        start_index = int(np.clip(round(start_time * sample_rate), 0, max(normalized.shape[0] - 1, 0)))
        end_index = int(np.clip(round(end_time * sample_rate), start_index + 1, normalized.shape[0]))
        if end_index <= start_index:
            continue

        preview_start_s = _pattern_step_start_seconds(
            step.step_index,
            step_duration_s=step_duration_s,
            swing=pattern.swing,
        )
        combined_pitch_shift = _pattern_step_pitch_shift(step) + float(ghost_meta["pitch_offset"])
        if stretch_meta["active"] and stretch_retriggers:
            ordered_retriggers = tuple(
                sorted(
                    stretch_retriggers,
                    key=lambda retrigger: (
                        int(getattr(retrigger, "offset_ticks", 0)),
                        int(getattr(retrigger, "step_index", step.step_index)),
                    ),
                )
            )
            zone_total_ticks = max(
                1,
                int(max(2, int(stretch_meta["span"]))) * int(STRETCH_TICKS_PER_STEP),
            )
            for retrigger_index, retrigger in enumerate(ordered_retriggers):
                source_hit = getattr(retrigger, "slice_source", None)
                trigger_start_time = float(getattr(source_hit, "start_s", start_time))
                trigger_end_time = max(
                    float(getattr(source_hit, "end_s", end_time)),
                    trigger_start_time + 0.012,
                )
                current_offset_ticks = int(np.clip(int(getattr(retrigger, "offset_ticks", 0)), 0, zone_total_ticks))
                next_offset_ticks = zone_total_ticks
                if retrigger_index + 1 < len(ordered_retriggers):
                    next_offset_ticks = int(
                        np.clip(
                            int(getattr(ordered_retriggers[retrigger_index + 1], "offset_ticks", zone_total_ticks)),
                            current_offset_ticks + 1,
                            zone_total_ticks,
                        )
                    )
                play_duration_s = (
                    float(max(1, next_offset_ticks - current_offset_ticks))
                    / float(STRETCH_TICKS_PER_STEP)
                ) * step_duration_s
                trigger_end_time = min(trigger_end_time, trigger_start_time + max(0.006, play_duration_s * 0.98))
                trigger_start_index = int(np.clip(round(trigger_start_time * sample_rate), 0, max(normalized.shape[0] - 1, 0)))
                trigger_end_index = int(np.clip(round(trigger_end_time * sample_rate), trigger_start_index + 1, normalized.shape[0]))
                if trigger_end_index <= trigger_start_index:
                    continue
                segment = normalized[trigger_start_index:trigger_end_index].copy()
                if abs(combined_pitch_shift) > 1e-6:
                    segment = _pitch_shift_audio_segment(
                        segment,
                        sample_rate=sample_rate,
                        pitch_shift=combined_pitch_shift,
                    )
                if bool(ghost_meta["active"]) and 0.0 < float(ghost_meta["gate_ratio"]) < 1.0:
                    gated_length = int(round(segment.shape[0] * float(ghost_meta["gate_ratio"])))
                    gated_length = int(np.clip(gated_length, 1, max(1, segment.shape[0])))
                    segment = segment[:gated_length].copy()
                gain = float(np.clip(float(getattr(retrigger, "velocity", step.velocity or 0)) / 100.0, 0.12, 1.27))
                if bool(ghost_meta["active"]):
                    gain *= float(ghost_meta["vel_ratio"])
                segment *= np.float32(gain)
                _apply_edge_fades(
                    segment,
                    sample_rate=sample_rate,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                )
                retrigger_offset_s = (
                    float(current_offset_ticks)
                    / float(STRETCH_TICKS_PER_STEP)
                ) * step_duration_s
                retrigger_preview_start_s = preview_start_s + retrigger_offset_s
                retrigger_preview_end_s = retrigger_preview_start_s + (float(segment.shape[0]) / float(sample_rate))
                stem_name = "stretch"
                scheduled_segments.append(
                    RetimedPreviewSegment(
                        index=len(scheduled_segments) + 1,
                        source_start_s=trigger_start_time,
                        source_end_s=trigger_end_time,
                        preview_start_s=retrigger_preview_start_s,
                        preview_end_s=retrigger_preview_end_s,
                        label=str(getattr(source_hit, "label", step.label) or step.label),
                        step_index=int(getattr(retrigger, "step_index", step.step_index)),
                        source_index=getattr(source_hit, "index", step.source_hit_index),
                        velocity=int(round(float(getattr(retrigger, "velocity", step.velocity or 0)))),
                        stem=stem_name,
                    )
                )
                new_start = int(round(retrigger_preview_start_s * sample_rate))
                rendered_segments.append(_RenderedPreviewEvent(start_frame=new_start, segment=segment, stem=stem_name))
                output_length = max(output_length, new_start + segment.shape[0])
            continue

        repeat_interval_s = step_duration_s / float(repeat_count)
        for repeat_index in range(repeat_count):
            segment = normalized[start_index:end_index].copy()
            if abs(combined_pitch_shift) > 1e-6:
                segment = _pitch_shift_audio_segment(
                    segment,
                    sample_rate=sample_rate,
                    pitch_shift=combined_pitch_shift,
                )
            ghost_gate_ratio = float(ghost_meta["gate_ratio"])
            if bool(ghost_meta["active"]) and 0.0 < ghost_gate_ratio < 1.0:
                gated_length = int(round(segment.shape[0] * ghost_gate_ratio))
                gated_length = int(np.clip(gated_length, 1, max(1, segment.shape[0])))
                segment = segment[:gated_length].copy()
            if stretch_meta["active"]:
                stretch_slot_s = step_duration_s * float(max(2, int(stretch_meta["span"])))
                target_duration_s = _lerp(
                    effective_duration_s,
                    max(effective_duration_s, stretch_slot_s * 0.985),
                    float(stretch_meta["amount"]),
                )
                target_duration_s = float(
                    np.clip(
                        target_duration_s,
                        effective_duration_s,
                        max(effective_duration_s, stretch_slot_s * 0.985),
                    )
                )
                target_length = max(segment.shape[0], int(round(target_duration_s * sample_rate)))
                segment = _glitch_stretch_audio_segment(segment, target_length, float(stretch_meta["amount"]))
            if reverse_step:
                segment = np.flip(segment, axis=0)
            gain = float(np.clip(step.velocity / 100.0, 0.12, 1.2)) if step.velocity is not None else 1.0
            gain *= _pattern_repeat_gain(repeat_index, repeat_count)
            if bool(ghost_meta["active"]):
                gain *= float(ghost_meta["vel_ratio"])
            segment *= np.float32(gain)
            _apply_edge_fades(
                segment,
                sample_rate=sample_rate,
                fade_in_ms=fade_in_ms,
                fade_out_ms=fade_out_ms,
            )

            repeated_preview_start_s = preview_start_s + (float(repeat_index) * repeat_interval_s)
            repeated_preview_end_s = repeated_preview_start_s + (float(segment.shape[0]) / float(sample_rate))
            stem_name = _pattern_step_stem_name(step, stretch_active=bool(stretch_meta["active"]))
            scheduled_segments.append(
                RetimedPreviewSegment(
                    index=len(scheduled_segments) + 1,
                    source_start_s=start_time,
                    source_end_s=end_time,
                    preview_start_s=repeated_preview_start_s,
                    preview_end_s=repeated_preview_end_s,
                    label=step.label,
                    step_index=step.step_index,
                    source_index=step.source_hit_index,
                    velocity=int(
                        round(
                            (step.velocity or 0)
                            * _pattern_repeat_gain(repeat_index, repeat_count)
                            * (float(ghost_meta["vel_ratio"]) if bool(ghost_meta["active"]) else 1.0)
                        )
                    ),
                    stem=stem_name,
                )
            )
            new_start = int(round(repeated_preview_start_s * sample_rate))
            rendered_segments.append(_RenderedPreviewEvent(start_frame=new_start, segment=segment, stem=stem_name))
            output_length = max(output_length, new_start + segment.shape[0])

    if not rendered_segments or output_length <= 0:
        raise ValueError("Need at least one generated event with a valid source slice to build a preview")

    if resolved_mono_choke:
        scheduled_segments, rendered_segments = _apply_global_mono_choke(
            scheduled_segments,
            rendered_segments,
            sample_rate=sample_rate,
        )
        output_length = max(
            (event.start_frame + int(event.segment.shape[0]) for event in rendered_segments),
            default=0,
        )
        if output_length <= 0:
            raise ValueError("Need at least one generated event with a valid source slice to build a preview")

    stem_buffers = {
        stem_name: np.zeros((output_length, channel_count), dtype=np.float32) for stem_name in PATTERN_STEM_NAMES
    }
    output = np.zeros((output_length, channel_count), dtype=np.float32)
    for event in rendered_segments:
        stem_name = event.stem or "other"
        new_end = min(output.shape[0], event.start_frame + event.segment.shape[0])
        cropped = event.segment[: new_end - event.start_frame]
        output[event.start_frame:new_end] += cropped
        stem_buffers[stem_name][event.start_frame:new_end] += cropped

    peak = float(np.max(np.abs(output))) if output.size else 0.0
    if peak > 0.98:
        peak_gain = np.float32(0.98 / peak)
        output *= peak_gain
        for stem_name in PATTERN_STEM_NAMES:
            stem_buffers[stem_name] *= peak_gain

    restored = output[:, 0] if was_mono else output
    restored_stems = {
        stem_name: stem_buffer[:, 0] if was_mono else stem_buffer
        for stem_name, stem_buffer in stem_buffers.items()
    }
    duration_s = float(output.shape[0]) / float(sample_rate)
    loop_duration_s = float(pattern.step_count) * float(step_duration_s)
    loop_audio = _build_loop_audio(output, sample_rate=sample_rate, loop_duration_s=loop_duration_s, was_mono=was_mono)
    loop_stems = {
        stem_name: _build_loop_audio(
            stem_buffers[stem_name],
            sample_rate=sample_rate,
            loop_duration_s=loop_duration_s,
            was_mono=was_mono,
        )
        for stem_name in PATTERN_STEM_NAMES
    }
    return RetimedPreview(
        audio=restored.astype(np.float32, copy=False),
        loop_audio=loop_audio,
        sample_rate=int(sample_rate),
        source_bpm=float(target_bpm),
        target_bpm=float(target_bpm),
        speed_ratio=1.0,
        duration_s=duration_s,
        loop_duration_s=loop_duration_s,
        segment_count=len(scheduled_segments),
        segments=tuple(scheduled_segments),
        mode=PREVIEW_MODE_PATTERN,
        quantize_grid_division=None,
        quantize_strength=0.0,
        pattern=pattern,
        stems={stem_name: buffer.astype(np.float32, copy=False) for stem_name, buffer in restored_stems.items()},
        loop_stems={
            stem_name: buffer.astype(np.float32, copy=False) if buffer is not None else np.zeros(0, dtype=np.float32)
            for stem_name, buffer in loop_stems.items()
        },
        mono_choke=bool(resolved_mono_choke),
    )


def _build_segment_schedule(
    ordered_hits: Sequence[TransientHit],
    *,
    source_bpm: float,
    target_bpm: float,
    mode: str,
    quantize_grid_division: int,
    quantize_strength: float,
    mono_choke: bool = False,
) -> list[RetimedPreviewSegment]:
    resolved_mode = _resolve_preview_mode(mode)
    resolved_grid = _resolve_quantize_grid_division(quantize_grid_division)
    resolved_strength = _resolve_quantize_strength(quantize_strength)
    speed_ratio = float(source_bpm / target_bpm)
    base_time = float(ordered_hits[0].start_s)
    schedule: list[RetimedPreviewSegment] = []

    for index, hit in enumerate(ordered_hits, start=1):
        start_time = float(hit.start_s)
        end_time = max(float(hit.end_s), start_time + 0.012)
        segment_duration_s = end_time - start_time
        scaled_start_s = max(0.0, (start_time - base_time) * speed_ratio)
        preview_start_s = scaled_start_s
        if resolved_mode == PREVIEW_MODE_QUANTIZE:
            preview_start_s = _quantize_preview_start(
                scaled_start_s,
                target_bpm=target_bpm,
                grid_division=resolved_grid,
                strength=resolved_strength,
            )
        preview_end_s = preview_start_s + segment_duration_s
        schedule.append(
            RetimedPreviewSegment(
                index=index,
                source_start_s=start_time,
                source_end_s=end_time,
                preview_start_s=preview_start_s,
                preview_end_s=preview_end_s,
                label=hit.label,
            )
        )
    if bool(mono_choke):
        schedule, _ = _apply_global_mono_choke(schedule, None, sample_rate=None)
    return schedule


def _apply_global_mono_choke(
    schedule: Sequence[RetimedPreviewSegment],
    rendered_segments: Sequence[_RenderedPreviewEvent] | None,
    *,
    sample_rate: int | None,
) -> tuple[list[RetimedPreviewSegment], list[_RenderedPreviewEvent] | None]:
    if len(schedule) <= 1:
        return list(schedule), None if rendered_segments is None else list(rendered_segments)

    updated_schedule = list(schedule)
    updated_rendered = None if rendered_segments is None else list(rendered_segments)
    if updated_rendered is not None and len(updated_rendered) != len(updated_schedule):
        raise ValueError("Rendered preview events must align with scheduled segments")

    sample_rate_value = int(sample_rate) if sample_rate is not None else 0
    if updated_rendered is None:
        start_times = [float(segment.preview_start_s) for segment in updated_schedule]
        effective_end_times = [float(segment.preview_end_s) for segment in updated_schedule]
        ordered_indices = sorted(range(len(updated_schedule)), key=lambda idx: (start_times[idx], idx))
        for position, current_index in enumerate(ordered_indices[:-1]):
            next_index = ordered_indices[position + 1]
            next_start_s = start_times[next_index]
            current_start_s = start_times[current_index]
            current_end_s = effective_end_times[current_index]
            if next_start_s <= current_start_s or next_start_s >= current_end_s:
                continue
            effective_end_times[current_index] = next_start_s

        for index, segment in enumerate(updated_schedule):
            new_preview_end_s = max(float(segment.preview_start_s), effective_end_times[index])
            new_source_end_s = min(
                float(segment.source_end_s),
                float(segment.source_start_s) + max(0.0, new_preview_end_s - float(segment.preview_start_s)),
            )
            updated_schedule[index] = replace(
                segment,
                source_end_s=max(float(segment.source_start_s), new_source_end_s),
                preview_end_s=new_preview_end_s,
            )
        return updated_schedule, None

    if sample_rate_value <= 0:
        raise ValueError("Sample rate must be strictly positive when rendered preview events are provided")

    start_frames: list[int] = []
    end_frames: list[int] = []
    for index, segment in enumerate(updated_schedule):
        start_frame = int(updated_rendered[index].start_frame)
        end_frame = start_frame + int(updated_rendered[index].segment.shape[0])
        start_frames.append(start_frame)
        end_frames.append(max(start_frame, end_frame))

    ordered_indices = sorted(range(len(updated_schedule)), key=lambda idx: (start_frames[idx], idx))
    effective_end_frames = list(end_frames)
    for position, current_index in enumerate(ordered_indices[:-1]):
        next_index = ordered_indices[position + 1]
        next_start_frame = start_frames[next_index]
        current_start_frame = start_frames[current_index]
        current_end_frame = effective_end_frames[current_index]
        if next_start_frame <= current_start_frame or next_start_frame >= current_end_frame:
            continue
        effective_end_frames[current_index] = next_start_frame

    for index, segment in enumerate(updated_schedule):
        start_frame = start_frames[index]
        end_frame = effective_end_frames[index]
        if end_frame <= start_frame:
            continue
        duration_frames = end_frame - start_frame
        if updated_rendered is not None and duration_frames < int(updated_rendered[index].segment.shape[0]):
            updated_rendered[index] = _RenderedPreviewEvent(
                start_frame=updated_rendered[index].start_frame,
                segment=updated_rendered[index].segment[:duration_frames].copy(),
                stem=updated_rendered[index].stem,
            )
        if sample_rate_value > 0:
            new_preview_end_s = float(start_frame + duration_frames) / float(sample_rate_value)
        else:
            new_preview_end_s = float(segment.preview_end_s)
        new_source_end_s = min(float(segment.source_end_s), float(segment.source_start_s) + max(0.0, new_preview_end_s - float(segment.preview_start_s)))
        updated_schedule[index] = replace(
            segment,
            source_end_s=max(float(segment.source_start_s), new_source_end_s),
            preview_end_s=max(float(segment.preview_start_s), new_preview_end_s),
        )
    return updated_schedule, updated_rendered


def _pattern_step_repeat_count(step: object) -> int:
    tags = _pattern_step_tags(step)
    if not tags:
        return 1
    for tag in tags:
        text = str(tag)
        if not text.startswith("repeat_count_"):
            continue
        try:
            return max(1, int(text.removeprefix("repeat_count_")))
        except ValueError:
            return 1
    return 1


def _pattern_step_is_reverse(step: object) -> bool:
    return "reverse" in _pattern_step_tags(step)


def _pattern_step_pitch_shift(step: object) -> float:
    try:
        return float(getattr(step, "pitch_shift", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pattern_step_stem_name(step: object, *, stretch_active: bool = False) -> str:
    if stretch_active:
        return "stretch"
    if _pattern_step_repeat_count(step) > 1:
        return "repeat"
    if _pattern_step_is_reverse(step):
        return "reverse"
    tags = _pattern_step_tags(step)
    if "kick_roll" in tags or "kick_roll_fill" in tags:
        return "roll"
    if bool(getattr(step, "is_synthetic_ghost", False)) or str(getattr(step, "label", "")) in {
        "snare_ghost",
        "kick_ghost",
        "ghost_snare",
    }:
        return "ghost"
    label = str(getattr(step, "label", "") or "").strip().lower()
    if label == "kick":
        return "kick"
    if label in {"snare", "snare_ruff"}:
        return "snare"
    if label == "clap":
        return "clap"
    if label in {"closed_hat", "open_hat", "ride", "crash"}:
        return "hat"
    return "other"


def _pattern_step_synthetic_ghost_metadata(step: object) -> dict[str, float | bool]:
    raw_active = getattr(step, "is_synthetic_ghost", False)
    active = bool(raw_active) if isinstance(raw_active, (bool, int, float, np.bool_, np.integer, np.floating)) else False

    raw_vel_ratio = getattr(step, "ghost_vel_ratio", 1.0)
    vel_ratio = float(raw_vel_ratio) if isinstance(raw_vel_ratio, (int, float, np.integer, np.floating)) else 1.0

    raw_pitch_offset = getattr(step, "ghost_pitch_offset", 0.0)
    pitch_offset = (
        float(raw_pitch_offset)
        if isinstance(raw_pitch_offset, (int, float, np.integer, np.floating))
        else 0.0
    )

    raw_gate_ratio = getattr(step, "ghost_gate_ratio", 0.0)
    gate_ratio = float(raw_gate_ratio) if isinstance(raw_gate_ratio, (int, float, np.integer, np.floating)) else 0.0
    return {
        "active": active,
        "vel_ratio": float(np.clip(vel_ratio, 0.0, 1.0)),
        "pitch_offset": pitch_offset,
        "gate_ratio": float(np.clip(gate_ratio, 0.0, 1.0)),
    }


def _pattern_step_snare_stretch_metadata(step: object) -> dict[str, float | int | bool]:
    tags = _pattern_step_tags(step)
    active = "snare_stretch" in tags
    tail = "snare_stretch_tail" in tags or "snare_stretch_hold" in tags
    zone = "snare_stretch_zone" in tags
    zone_start = "snare_stretch_zone_start" in tags
    zone_end = "snare_stretch_zone_end" in tags
    span = 1
    amount = 0.0
    curve = "decay"
    for tag in tags:
        if tag.startswith("snare_stretch_zone_span_"):
            try:
                span = max(1, int(tag.removeprefix("snare_stretch_zone_span_")))
            except ValueError:
                span = 1
        elif tag.startswith("snare_stretch_amount_"):
            try:
                amount = float(np.clip(int(tag.removeprefix("snare_stretch_amount_")) / 100.0, 0.0, 1.0))
            except ValueError:
                amount = 0.0
        elif tag.startswith("snare_stretch_curve_"):
            curve = str(tag.removeprefix("snare_stretch_curve_") or "decay")
    return {
        "active": active,
        "tail": tail,
        "zone": zone,
        "start": zone_start,
        "end": zone_end,
        "span": span,
        "amount": amount,
        "curve": curve,
    }


def _pattern_step_tags(step: object) -> tuple[str, ...]:
    raw_tags = getattr(step, "tags", ())
    if not isinstance(raw_tags, (tuple, list, set, frozenset)):
        return ()
    return tuple(str(tag) for tag in raw_tags)


def _pattern_step_stretch_retriggers(step: object) -> tuple[object, ...]:
    raw_retriggers = getattr(step, "stretch_retriggers", ())
    if not isinstance(raw_retriggers, (tuple, list)):
        return ()
    return tuple(raw_retriggers)


def _pattern_repeat_gain(repeat_index: int, repeat_count: int) -> float:
    if repeat_count <= 1:
        return 1.0
    if repeat_count == 2:
        return 1.0 if repeat_index == 0 else 0.82
    decay = 1.0 - (0.14 * float(repeat_index))
    return float(np.clip(decay, 0.48, 1.0))


def _glitch_stretch_audio_segment(segment: np.ndarray, target_length: int, amount: float) -> np.ndarray:
    if target_length <= 0 or segment.size == 0:
        return segment
    if segment.shape[0] == target_length:
        return segment
    if segment.shape[0] >= target_length:
        return segment[:target_length].copy()
    if segment.shape[0] == 1:
        return np.repeat(segment, int(target_length), axis=0)

    resolved_amount = float(np.clip(float(amount), 0.0, 1.0))
    source_length = int(segment.shape[0])
    attack_length = int(
        np.clip(
            round(_lerp(source_length * 0.18, source_length * 0.08, resolved_amount)),
            6,
            max(6, min(max(6, source_length - 4), max(6, source_length // 3))),
        )
    )
    attack_length = int(np.clip(attack_length, 1, max(1, source_length - 4)))
    attack = segment[:attack_length].copy()
    tail_source = segment[attack_length:].copy()
    if tail_source.shape[0] < 8:
        fallback_start = max(1, min(source_length - 1, source_length // 3))
        attack = segment[:fallback_start].copy()
        tail_source = segment[fallback_start:].copy()
    if tail_source.size == 0:
        return np.repeat(segment[-1:, :], int(target_length), axis=0)

    target_tail_length = max(0, int(target_length) - attack.shape[0])
    if target_tail_length <= 0:
        return attack[: int(target_length)].copy()

    tail = _glitch_tail_audio_segment(tail_source, target_tail_length, resolved_amount)
    return _concatenate_with_crossfade(attack, tail)


def _pitch_shift_audio_segment(
    segment: np.ndarray,
    *,
    sample_rate: int,
    pitch_shift: float,
) -> np.ndarray:
    if abs(float(pitch_shift)) <= 1e-6 or segment.size == 0:
        return segment
    segment_length = int(segment.shape[0]) if segment.ndim >= 1 else 0
    stft_kwargs = _safe_pitch_shift_stft_kwargs(segment_length)
    if not stft_kwargs:
        return segment
    librosa = _require_librosa()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"n_fft=.*too large for input signal of length=.*",
            category=UserWarning,
        )
        if segment.ndim == 1:
            shifted = librosa.effects.pitch_shift(
                segment.astype(np.float32, copy=False),
                sr=int(sample_rate),
                n_steps=float(pitch_shift),
                **stft_kwargs,
            )
            return np.asarray(shifted, dtype=np.float32)

        shifted_channels = [
            np.asarray(
                librosa.effects.pitch_shift(
                    segment[:, channel].astype(np.float32, copy=False),
                    sr=int(sample_rate),
                    n_steps=float(pitch_shift),
                    **stft_kwargs,
                ),
                dtype=np.float32,
            )
            for channel in range(segment.shape[1])
        ]
    if not shifted_channels:
        return segment
    target_length = min(channel.shape[0] for channel in shifted_channels)
    if target_length <= 0:
        return np.zeros((0, segment.shape[1]), dtype=np.float32)
    return np.column_stack([channel[:target_length] for channel in shifted_channels]).astype(np.float32, copy=False)


def _safe_pitch_shift_stft_kwargs(segment_length: int) -> dict[str, int]:
    if int(segment_length) < 32:
        return {}
    upper = min(2048, int(segment_length))
    n_fft = 2 ** int(math.floor(math.log2(max(upper, 2))))
    n_fft = int(max(32, min(n_fft, upper)))
    hop_length = int(max(1, min(n_fft - 1, n_fft // 4)))
    return {
        "n_fft": n_fft,
        "win_length": n_fft,
        "hop_length": hop_length,
    }


def _glitch_tail_audio_segment(segment: np.ndarray, target_length: int, amount: float) -> np.ndarray:
    if target_length <= 0 or segment.size == 0:
        return np.zeros((max(0, int(target_length)), segment.shape[1] if segment.ndim == 2 else 1), dtype=np.float32)
    if segment.shape[0] == target_length:
        return segment.copy()
    if segment.shape[0] >= target_length:
        return segment[:target_length].copy()
    if segment.shape[0] == 1:
        return np.repeat(segment, int(target_length), axis=0)

    source_length = int(segment.shape[0])
    grain_length = int(
        np.clip(
            round(_lerp(source_length * 0.34, source_length * 0.11, amount)),
            10,
            max(10, min(source_length, int(target_length))),
        )
    )
    if grain_length >= source_length:
        grain_length = max(10, min(source_length, max(10, source_length // 2)))
    hop_length = max(1, int(round(grain_length * _lerp(0.7, 0.22, amount))))
    source_stride = max(1, int(round(grain_length * _lerp(0.18, 0.04, amount))))
    jitter = int(round(grain_length * _lerp(0.04, 0.32, amount)))

    max_start = max(0, source_length - grain_length)
    if grain_length <= 2:
        window = np.ones(grain_length, dtype=np.float32)
    else:
        window = np.hanning(grain_length).astype(np.float32)
        window = np.clip((window * np.float32(0.88)) + np.float32(0.12), 0.0, 1.0)

    stretched = np.zeros((int(target_length), segment.shape[1]), dtype=np.float32)
    weights = np.zeros((int(target_length), 1), dtype=np.float32)
    rng_seed = (
        (source_length * 1315423911)
        ^ (int(target_length) * 2654435761)
        ^ int(round(float(amount) * 1000.0))
    ) & 0xFFFFFFFF
    rng = np.random.default_rng(int(rng_seed))
    grain_index = 0
    output_start = 0
    source_position = 0.0
    freeze_threshold = _lerp(0.58, 0.26, amount)
    tail_falloff = np.linspace(1.0, _lerp(0.84, 0.62, amount), num=int(target_length), dtype=np.float32)[:, np.newaxis]

    while output_start < int(target_length):
        jitter_offset = int(rng.integers(-jitter, jitter + 1)) if jitter > 0 else 0
        source_start = int(np.clip(round(source_position) + jitter_offset, 0, max_start))
        source_end = min(source_start + grain_length, source_length)
        grain = segment[source_start:source_end]
        if grain.shape[0] < grain_length:
            padded = np.zeros((grain_length, segment.shape[1]), dtype=np.float32)
            padded[: grain.shape[0]] = grain
            grain = padded
        if amount >= 0.72 and (grain_index % 5) == 3:
            grain = np.flip(grain, axis=0)

        chunk_length = min(grain_length, int(target_length) - output_start)
        window_slice = window[:chunk_length, np.newaxis]
        stretched[output_start : output_start + chunk_length] += grain[:chunk_length] * window_slice
        weights[output_start : output_start + chunk_length] += window_slice
        output_start += hop_length
        grain_index += 1
        if max_start > 0:
            source_position = min(float(max_start), source_position + float(source_stride))
            if source_position >= (float(max_start) * freeze_threshold):
                freeze_start = float(max_start) * _lerp(0.42, 0.78, amount)
                source_position = max(freeze_start, source_position - float(source_stride * _lerp(0.18, 0.52, amount)))

    np.divide(stretched, np.maximum(weights, 1e-6), out=stretched)
    stretched *= tail_falloff
    return stretched


def _concatenate_with_crossfade(head: np.ndarray, tail: np.ndarray) -> np.ndarray:
    if head.size == 0:
        return tail
    if tail.size == 0:
        return head
    crossfade = min(int(head.shape[0] // 4), int(tail.shape[0] // 4), 64)
    if crossfade <= 1:
        return np.concatenate((head, tail), axis=0)
    fade = np.linspace(0.0, 1.0, num=int(crossfade), dtype=np.float32)[:, np.newaxis]
    blended = (head[-crossfade:] * (1.0 - fade)) + (tail[:crossfade] * fade)
    return np.concatenate((head[:-crossfade], blended, tail[crossfade:]), axis=0)


def _resolve_preview_mode(mode: str) -> str:
    value = str(mode).lower()
    if value == PREVIEW_MODE_QUANTIZE:
        return PREVIEW_MODE_QUANTIZE
    if value == PREVIEW_MODE_PATTERN:
        return PREVIEW_MODE_PATTERN
    return PREVIEW_MODE_RETIME


def _resolve_quantize_grid_division(grid_division: int) -> int:
    try:
        value = int(grid_division)
    except (TypeError, ValueError):
        return DEFAULT_QUANTIZE_GRID_DIVISION
    if value in QUANTIZE_GRID_DIVISIONS:
        return value
    return DEFAULT_QUANTIZE_GRID_DIVISION


def _resolve_quantize_strength(strength: float) -> float:
    try:
        value = float(strength)
    except (TypeError, ValueError):
        return 0.0
    return float(np.clip(value, 0.0, 1.0))


def _quantize_preview_start(
    scaled_start_s: float,
    *,
    target_bpm: float,
    grid_division: int,
    strength: float,
) -> float:
    if target_bpm <= 1.0:
        return scaled_start_s
    beat_duration_s = 60.0 / float(target_bpm)
    grid_step_s = beat_duration_s * (4.0 / float(grid_division))
    if grid_step_s <= 1e-9:
        return scaled_start_s
    nearest_grid_index = np.floor((scaled_start_s / grid_step_s) + 0.5)
    quantized_start_s = max(0.0, float(nearest_grid_index * grid_step_s))
    return max(0.0, scaled_start_s + ((quantized_start_s - scaled_start_s) * strength))


def _pattern_step_start_seconds(step_index: int, *, step_duration_s: float, swing: float) -> float:
    zero_based = max(0, int(step_index) - 1)
    preview_start_s = float(zero_based) * float(step_duration_s)
    local_step = (zero_based % 16) + 1
    if local_step in {3, 7, 11, 15}:
        preview_start_s += float(np.clip(swing, 0.0, 1.0)) * (step_duration_s * 0.35)
    return max(0.0, preview_start_s)


def _normalize_audio_shape(samples: np.ndarray) -> tuple[np.ndarray, bool]:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        return audio[:, np.newaxis], True
    if audio.ndim != 2:
        raise ValueError("Audio samples must be mono or multi-channel")

    if audio.shape[0] <= 8 and audio.shape[1] > audio.shape[0]:
        audio = audio.T
    if audio.shape[1] <= 0:
        raise ValueError("Audio buffer has no channels")
    return audio, bool(audio.shape[1] == 1)


def _build_loop_audio(
    output: np.ndarray,
    *,
    sample_rate: int,
    loop_duration_s: float,
    was_mono: bool,
) -> np.ndarray | None:
    if output.ndim != 2 or output.shape[0] <= 0 or sample_rate <= 0:
        return None
    loop_frames = int(round(max(loop_duration_s, 1.0 / float(sample_rate)) * float(sample_rate)))
    if loop_frames <= 0:
        return None

    loop_buffer = np.zeros((loop_frames, output.shape[1]), dtype=np.float32)
    copy_frames = min(loop_frames, output.shape[0])
    loop_buffer[:copy_frames] = output[:copy_frames]

    if output.shape[0] > loop_frames:
        tail = output[loop_frames:]
        for index in range(tail.shape[0]):
            loop_buffer[index % loop_frames] += tail[index]

    peak = float(np.max(np.abs(loop_buffer))) if loop_buffer.size else 0.0
    if peak > 0.98:
        loop_buffer *= np.float32(0.98 / peak)

    if was_mono:
        return loop_buffer[:, 0].astype(np.float32, copy=False)
    return loop_buffer.astype(np.float32, copy=False)


def _apply_edge_fades(
    segment: np.ndarray,
    *,
    sample_rate: int,
    fade_in_ms: float,
    fade_out_ms: float,
) -> None:
    if segment.ndim != 2 or segment.shape[0] <= 2:
        return

    fade_in = int(round(sample_rate * max(fade_in_ms, 0.0) / 1000.0))
    fade_out = int(round(sample_rate * max(fade_out_ms, 0.0) / 1000.0))
    max_fade = max(1, segment.shape[0] // 3)
    fade_in = min(fade_in, max_fade)
    fade_out = min(fade_out, max_fade)

    if fade_in > 1:
        ramp_in = np.linspace(0.0, 1.0, fade_in, endpoint=True, dtype=np.float32)[:, np.newaxis]
        segment[:fade_in] *= ramp_in
    if fade_out > 1:
        ramp_out = np.linspace(1.0, 0.0, fade_out, endpoint=True, dtype=np.float32)[:, np.newaxis]
        segment[-fade_out:] *= ramp_out


def _lerp(start: float, end: float, amount: float) -> float:
    return float(start + ((end - start) * np.clip(amount, 0.0, 1.0)))
