from __future__ import annotations

import atexit
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from dataclasses import dataclass, field, replace
from functools import lru_cache
import hashlib
from importlib import import_module
import json
import logging
import multiprocessing as mp
from multiprocessing import shared_memory
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import secrets
import sys
import time
from typing import Callable
import warnings

import numpy as np

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
if os.getenv("SAMPLEROD_DISABLE_SCALE", "0") != "1":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .analyzer import (
    AUDIO_EXTENSIONS,
    DEFAULT_SPLIT_DENSITY,
    MAX_SEQUENCE_HIT_COUNT,
    DrumCandidate,
    DrumDetectionResult,
    DrumTransientPreview,
    HitSequence,
    HitSequenceEvent,
    TransientHit,
    analyze_audio_with_preview,
    analyze_file_with_preview,
    detect_drum_from_markers,
    get_analysis_dependency_error,
    requantize_detection_result,
)
from .preview import (
    DEFAULT_QUANTIZE_GRID_DIVISION,
    DEFAULT_QUANTIZE_STRENGTH,
    PREVIEW_MODE_PATTERN,
    PREVIEW_MODE_QUANTIZE,
    PREVIEW_MODE_RETIME,
    PATTERN_STEM_NAMES,
    QUANTIZE_GRID_DIVISIONS,
    RetimedPreview,
    RetimedPreviewSegment,
    build_pattern_preview,
    build_retimed_preview,
    build_retimed_preview_schedule,
    estimate_retimed_preview_duration,
    format_quantize_grid_label,
)
from .pattern_generator import (
    BreakPatternParams,
    FILL_STYLE_AUTO,
    FILL_STYLE_LABELS,
    FILL_STYLE_OPTIONS,
    FillDecision,
    GeneratedBreakPattern,
    GeneratedPatternStep,
    PIPELINE_PASS_ORDER,
    PipelineState,
    STRETCH_TICKS_PER_STEP,
    StretchRetrigger,
    TOGGLEABLE_PIPELINE_PASSES,
    UserMotif,
    apply_anchor_reapply,
    apply_fill_pass,
    apply_ghost_pass,
    apply_kick_roll_pass,
    apply_pitch_pass,
    apply_repeat_pass,
    apply_resolution_pass,
    apply_reverse_pass,
    apply_snare_stretch_pass,
    apply_velocity_pass,
    estimate_pattern_effect_probabilities,
    estimate_pattern_family_probabilities,
    estimate_user_motif_effective_probability,
    generate_break_pattern,
    generate_break_pattern_debug,
    generate_break_pattern_for_mode,
    generate_break_pattern_hybrid,
    generate_break_skeleton_only,
    reroll_break_pattern_step,
)

PREVIEW_OWNER_RETIME = "retime"
PREVIEW_OWNER_GENERATOR = "generator"
PREVIEW_OWNER_LIVE = "live"
LIVE_SLOT_NAMES: tuple[str, str] = ("A", "B")
LIVE_STEM_NAMES: tuple[str, ...] = PATTERN_STEM_NAMES
LIVE_EFFECT_NAMES: tuple[str, ...] = ("gain", "lowpass", "highpass", "distortion", "bitcrush", "stutter", "gate")
LIVE_EFFECT_LABELS: dict[str, str] = {
    "gain": "Gain",
    "lowpass": "Lowpass",
    "highpass": "Highpass",
    "distortion": "Distortion",
    "bitcrush": "Bitcrush",
    "stutter": "Stutter",
    "gate": "Gate",
}
LIVE_EFFECT_DEFAULTS: dict[str, float | int | bool] = {
    "gain": 1.0,
    "lowpass": 0.0,
    "highpass": 0.0,
    "distortion": 0.0,
    "bitcrush": 16,
    "stutter": False,
    "gate": 1.0,
}
MAIN_TAB_ANALYZE = "analyze"
MAIN_TAB_PREVIEW = "preview"
MAIN_TAB_GENERATOR = "generator"
MAIN_TAB_LIVE = "live"
MAIN_TAB_SAVED = "saved"
MAIN_TAB_INSPECTOR = "inspector"
MANUAL_HIT_LABEL_OPTIONS: tuple[str, ...] = (
    "kick",
    "kick_ghost",
    "snare",
    "snare_ghost",
    "snare_ruff",
    "clap",
    "closed_hat",
    "open_hat",
    "crash",
    "ride",
    "tom",
    "perc",
)
HIT_LABEL_SHORT_TEXT: dict[str, str] = {
    "kick": "K",
    "kick_ghost": "Kg",
    "snare": "S",
    "snare_ghost": "Sg",
    "snare_ruff": "Rf",
    "clap": "C",
    "closed_hat": "HC",
    "open_hat": "HO",
    "crash": "Cr",
    "ride": "Rd",
    "tom": "T",
    "perc": "P",
}
HITS_TABLE_COLUMN_HIT = 0
HITS_TABLE_COLUMN_POOL = 1
HITS_TABLE_COLUMN_LABEL = 2
HITS_TABLE_COLUMN_START = 3
HITS_TABLE_COLUMN_END = 4
HITS_TABLE_COLUMN_CONF = 5
HITS_TABLE_COLUMN_PEAK = 6
MAX_RECENT_FILES = 12
RECENT_FILES_SETTINGS_KEY = "recent_files"
RENDER_WAV_LAST_DIR_SETTINGS_KEY = "last_render_wav_dir"
USER_MOTIF_PROJECT_FILE = ".drum_detector_user_motifs.json"
SAVED_PATTERN_PROJECT_FILE = ".drum_detector_saved_patterns.json"
GENERATOR_MODE_CLASSIC = "classic"
GENERATOR_MODE_HYBRID = "hybrid"
GENERATOR_MODE_LABELS: dict[str, str] = {
    GENERATOR_MODE_CLASSIC: "Classic",
    GENERATOR_MODE_HYBRID: "Hybrid",
}
GENERATION_PROFILE_SAFE = "safe"
GENERATION_PROFILE_MUSICAL = "musical"
GENERATION_PROFILE_DESTRUCTIVE = "destructive"
GENERATION_PROFILE_LABELS: dict[str, str] = {
    GENERATION_PROFILE_SAFE: "Safe",
    GENERATION_PROFILE_MUSICAL: "Musical",
    GENERATION_PROFILE_DESTRUCTIVE: "Destructive",
}
GENERATOR_PIPELINE_PASS_LABELS: dict[str, str] = {
    "skeleton": "Skeleton",
    "ghost_pass": "Ghost",
    "fill_pass": "Fill",
    "resolution_pass": "Resolution",
    "kick_roll_pass": "Kick Roll",
    "repeat_pass": "Repeat",
    "reverse_pass": "Reverse",
    "snare_stretch_pass": "Snare Stretch",
    "velocity_pass": "Velocity",
    "pitch_pass": "Pitch",
    "anchor_reapply": "Anchor Reapply",
}
GENERATOR_VIEW_MODE_BASIC = "basic"
GENERATOR_VIEW_MODE_ADVANCED = "advanced"
GENERATOR_VIEW_MODE_LABELS: dict[str, str] = {
    GENERATOR_VIEW_MODE_BASIC: "Basic",
    GENERATOR_VIEW_MODE_ADVANCED: "Advanced",
}
GENERATOR_DISPLAY_PRESET_BALANCED = "balanced"
GENERATOR_DISPLAY_PRESET_PERFORMANCE = "performance"
GENERATOR_DISPLAY_PRESET_INSPECTOR = "inspector"
GENERATOR_DISPLAY_PRESET_LABELS: dict[str, str] = {
    GENERATOR_DISPLAY_PRESET_BALANCED: "Balanced",
    GENERATOR_DISPLAY_PRESET_PERFORMANCE: "Performance",
    GENERATOR_DISPLAY_PRESET_INSPECTOR: "Inspector",
}
PITCH_MODE_OPTIONS: tuple[str, ...] = ("off", "random", "sequence", "curve")
PITCH_SCOPE_OPTIONS: tuple[str, ...] = ("snare", "snare+clap", "all_pillar", "all")
PITCH_SCALE_OPTIONS: tuple[str, ...] = ("chromatic", "minor", "major", "pentatonic", "diminished")
PITCH_CURVE_OPTIONS: tuple[str, ...] = ("up", "down", "bell", "inv_bell")
PITCH_RATE_OPTIONS: tuple[str, ...] = ("every_hit", "every_2", "every_bar")
SNARE_STRETCH_VEL_CURVE_OPTIONS: tuple[str, ...] = ("flat", "decay", "crescendo", "random")
PITCH_NOTE_NAMES: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
USER_MOTIF_STEP_ORDER: tuple[str | None, ...] = (
    None,
    "kick",
    "snare",
    "hat",
    "ghost",
    "silence",
)
USER_MOTIF_ROLE_OPTIONS: tuple[str, ...] = ("groove", "fill", "cadence", "anticipation")
USER_MOTIF_DOMINANT_TYPE_OPTIONS: tuple[str, ...] = ("kick", "snare", "hat", "ghost", "mixed")
GENERATOR_STEP_ANCHOR_ORDER: tuple[str | None, ...] = (
    None,
    "kick",
    "snare",
    "clap",
    "hat",
    "ghost",
    "other",
    "silence",
)
GENERATOR_STEP_ANCHOR_SHORT_LABELS: dict[str | None, str] = {
    None: "·",
    "kick": "K",
    "snare": "S",
    "clap": "C",
    "hat": "H",
    "ghost": "G",
    "other": "O",
    "silence": "-",
}
GENERATOR_STEP_ANCHOR_LABELS: dict[str | None, str] = {
    None: "auto",
    "kick": "kick",
    "snare": "snare",
    "clap": "clap",
    "hat": "hat",
    "ghost": "ghost",
    "other": "other",
    "silence": "silence",
}


@lru_cache(maxsize=1)
def _require_soundfile():
    try:
        return import_module("soundfile")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Waveform dependency missing (soundfile). "
            "Install project deps with `python -m pip install -r requirements.txt`."
        ) from exc


@lru_cache(maxsize=1)
def _require_sounddevice():
    try:
        return import_module("sounddevice")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Preview playback dependency missing (sounddevice). "
            "Install project deps with `python -m pip install -r requirements.txt`."
        ) from exc


@lru_cache(maxsize=1)
def _require_waveform_widget():
    try:
        module = import_module("frontend.sample_gui.wave_form")
        return getattr(module, "WaveformWidget")
    except Exception as exc:
        raise RuntimeError(f"SampleRod waveform editor unavailable: {exc}") from exc


@lru_cache(maxsize=1)
def _optional_qtawesome():
    try:
        return import_module("qtawesome")
    except ModuleNotFoundError:
        return None


def _copy_preview_frames(
    outdata: np.ndarray,
    audio: np.ndarray,
    cursor: int,
    *,
    loop_enabled: bool,
) -> tuple[int, int, bool]:
    frames = int(outdata.shape[0]) if outdata.ndim >= 1 else 0
    total_frames = int(audio.shape[0]) if audio.ndim == 2 else 0
    if frames <= 0 or total_frames <= 0:
        outdata.fill(0)
        return 0, 0, True

    local_cursor = max(0, int(cursor))
    if loop_enabled:
        local_cursor %= total_frames
        write_pos = 0
        remaining = frames
        while remaining > 0:
            chunk = min(remaining, total_frames - local_cursor)
            outdata[write_pos : write_pos + chunk, :] = audio[local_cursor : local_cursor + chunk, :]
            write_pos += chunk
            remaining -= chunk
            local_cursor += chunk
            if local_cursor >= total_frames:
                local_cursor = 0
        return local_cursor, frames, False

    outdata.fill(0)
    if local_cursor >= total_frames:
        return max(total_frames - 1, 0), 0, True

    count = min(frames, total_frames - local_cursor)
    if count > 0:
        outdata[:count, :] = audio[local_cursor : local_cursor + count, :]
    local_cursor += count
    should_stop = count < frames or local_cursor >= total_frames
    return local_cursor, count, should_stop


@lru_cache(maxsize=1)
def _pattern_generation_process_pool() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))


def _set_background_process_priority() -> None:
    try:
        if sys.platform.startswith("win"):
            import ctypes

            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
            return
        os.nice(10)
    except Exception:
        return


@lru_cache(maxsize=1)
def _live_generation_process_pool() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=1,
        mp_context=mp.get_context("spawn"),
        initializer=_set_background_process_priority,
    )


def _process_pool_allowed() -> bool:
    override = os.getenv("SAMPLEROD_ENABLE_PROCESS_POOL")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return not sys.platform.startswith("win")


def _live_process_pool_allowed() -> bool:
    override = os.getenv("SAMPLEROD_ENABLE_LIVE_PROCESS_POOL")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return True


def _shutdown_pattern_generation_process_pool() -> None:
    cache_clear = getattr(_pattern_generation_process_pool, "cache_clear", None)
    cache_info = getattr(_pattern_generation_process_pool, "cache_info", None)
    if cache_clear is None or cache_info is None:
        return
    if cache_info().currsize <= 0:
        return
    executor = _pattern_generation_process_pool()
    executor.shutdown(wait=False, cancel_futures=True)
    cache_clear()


atexit.register(_shutdown_pattern_generation_process_pool)


def _shutdown_live_generation_process_pool() -> None:
    cache_clear = getattr(_live_generation_process_pool, "cache_clear", None)
    cache_info = getattr(_live_generation_process_pool, "cache_info", None)
    if cache_clear is None or cache_info is None:
        return
    if cache_info().currsize <= 0:
        return
    executor = _live_generation_process_pool()
    executor.shutdown(wait=False, cancel_futures=True)
    cache_clear()


atexit.register(_shutdown_live_generation_process_pool)


def _build_group_loop_cache_from_loop_stems(
    loop_stems: dict[str, np.ndarray],
    grouped_stem_names: tuple[tuple[str, ...], ...],
) -> dict[tuple[str, ...], np.ndarray]:
    group_loop_cache: dict[tuple[str, ...], np.ndarray] = {}
    for stem_names in grouped_stem_names:
        if len(stem_names) <= 1:
            continue
        group_audio: np.ndarray | None = None
        for stem_name in stem_names:
            stem_audio = loop_stems.get(stem_name)
            if stem_audio is None or stem_audio.shape[0] <= 0:
                continue
            if group_audio is None:
                group_audio = np.asarray(stem_audio, dtype=np.float32)
            else:
                group_audio = group_audio + np.asarray(stem_audio, dtype=np.float32)
        if group_audio is not None:
            group_loop_cache[tuple(stem_names)] = np.ascontiguousarray(group_audio, dtype=np.float32)
    return group_loop_cache


def _shared_audio_view(
    shared_name: str,
    shared_shape: tuple[int, ...],
) -> tuple[shared_memory.SharedMemory, np.ndarray]:
    handle = shared_memory.SharedMemory(name=str(shared_name))
    array = np.ndarray(tuple(int(dim) for dim in shared_shape), dtype=np.float32, buffer=handle.buf)
    return handle, array


def _build_pattern_preview_process_task(
    samples: np.ndarray,
    sample_rate: int,
    pattern: GeneratedBreakPattern,
    *,
    target_bpm: float,
    gate: float,
    mono_choke: bool,
) -> RetimedPreview:
    return build_pattern_preview(
        samples,
        int(sample_rate),
        pattern,
        target_bpm=float(target_bpm),
        gate=float(gate),
        mono_choke=bool(mono_choke),
    )


def _build_live_pattern_preview_process_task(
    samples: np.ndarray | None,
    sample_rate: int,
    pattern: GeneratedBreakPattern,
    *,
    target_bpm: float,
    gate: float,
    mono_choke: bool,
    grouped_stem_names: tuple[tuple[str, ...], ...] = (),
    shared_audio_name: str | None = None,
    shared_audio_shape: tuple[int, ...] | None = None,
) -> tuple[RetimedPreview, dict[tuple[str, ...], np.ndarray]]:
    shared_handle = None
    try:
        if shared_audio_name and shared_audio_shape:
            shared_handle, process_samples = _shared_audio_view(shared_audio_name, shared_audio_shape)
        elif samples is not None:
            process_samples = np.asarray(samples, dtype=np.float32)
        else:
            raise ValueError("Live preview task missing audio samples")
        preview = build_pattern_preview(
            process_samples,
            int(sample_rate),
            pattern,
            target_bpm=float(target_bpm),
            gate=float(gate),
            mono_choke=bool(mono_choke),
        )
    finally:
        if shared_handle is not None:
            shared_handle.close()
    group_loop_cache = _build_group_loop_cache_from_loop_stems(
        dict(preview.loop_stems),
        grouped_stem_names,
    )
    return preview, group_loop_cache


def _generate_live_slot_preview_process_task(
    hits: tuple[TransientHit, ...],
    params: BreakPatternParams,
    *,
    sequences: tuple[HitSequence, ...],
    anchors: dict[int, str],
    use_hybrid: bool,
    user_motifs: tuple[UserMotif, ...],
    samples: np.ndarray | None,
    sample_rate: int,
    target_bpm: float,
    gate: float,
    mono_choke: bool,
    grouped_stem_names: tuple[tuple[str, ...], ...] = (),
    shared_audio_name: str | None = None,
    shared_audio_shape: tuple[int, ...] | None = None,
) -> tuple[int, BreakPatternParams, GeneratedBreakPattern, RetimedPreview, dict[tuple[str, ...], np.ndarray]]:
    pattern = generate_break_pattern_for_mode(
        hits,
        params,
        sequences=sequences,
        anchors=anchors,
        use_hybrid=bool(use_hybrid),
        user_motifs=user_motifs,
    )
    shared_handle = None
    try:
        if shared_audio_name and shared_audio_shape:
            shared_handle, process_samples = _shared_audio_view(shared_audio_name, shared_audio_shape)
        elif samples is not None:
            process_samples = np.asarray(samples, dtype=np.float32)
        else:
            raise ValueError("Live slot task missing audio samples")
        preview = build_pattern_preview(
            process_samples,
            int(sample_rate),
            pattern,
            target_bpm=float(target_bpm),
            gate=float(gate),
            mono_choke=bool(mono_choke),
        )
    finally:
        if shared_handle is not None:
            shared_handle.close()
    group_loop_cache = _build_group_loop_cache_from_loop_stems(
        dict(preview.loop_stems),
        grouped_stem_names,
    )
    return int(pattern.seed), params, pattern, preview, group_loop_cache


class _PrototypeWaveformContext:
    """Minimal context placeholder for embedding the SampleRod waveform widget."""

    class _SampleStore:
        def add(self, _path: str) -> None:
            return

        def updateDurationFromFile(self, _path: str) -> None:
            return

    class _Notifications:
        def notify(self, **_kwargs) -> None:
            return

    def __init__(self) -> None:
        self.sample_store = self._SampleStore()
        self.notifications = self._Notifications()


@dataclass(frozen=True)
class WaveformLoadResult:
    path: str
    samples: np.ndarray
    waveform_data: np.ndarray
    sample_rate: int
    duration_s: float


@dataclass
class PatternSlot:
    pattern: GeneratedBreakPattern | None = None
    params: BreakPatternParams | None = None
    seed: int | None = None
    mode: str = "classic"
    status: str = "stale"
    stems: dict[str, np.ndarray] = field(default_factory=dict)
    loop_stems: dict[str, np.ndarray] = field(default_factory=dict)
    group_loop_cache: dict[tuple[str, ...], np.ndarray] = field(default_factory=dict)
    preview: RetimedPreview | None = None


@dataclass(frozen=True)
class SavedPatternSnapshot:
    snapshot_id: str
    title: str
    created_at: str
    source_path: str | None
    origin: str
    mode: str
    target_bpm: float
    detected_bpm_factor: float
    anchors: dict[int, str] = field(default_factory=dict)
    locked_steps: tuple[int, ...] = ()
    result_payload: dict[str, object] = field(default_factory=dict)
    pattern_payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "title": str(self.title),
            "created_at": str(self.created_at),
            "source_path": None if self.source_path is None else str(self.source_path),
            "origin": str(self.origin),
            "mode": str(self.mode),
            "target_bpm": float(self.target_bpm),
            "detected_bpm_factor": float(self.detected_bpm_factor),
            "anchors": {str(step): str(anchor) for step, anchor in self.anchors.items()},
            "locked_steps": [int(step) for step in self.locked_steps],
            "result_payload": dict(self.result_payload),
            "pattern_payload": dict(self.pattern_payload),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SavedPatternSnapshot":
        raw_anchors = payload.get("anchors", {}) or {}
        anchors: dict[int, str] = {}
        if isinstance(raw_anchors, dict):
            for step, anchor in raw_anchors.items():
                try:
                    anchors[int(step)] = str(anchor)
                except Exception:
                    continue
        raw_locked_steps = payload.get("locked_steps", ()) or ()
        locked_steps: list[int] = []
        if isinstance(raw_locked_steps, (list, tuple)):
            for step in raw_locked_steps:
                try:
                    locked_steps.append(int(step))
                except Exception:
                    continue
        return cls(
            snapshot_id=str(payload.get("snapshot_id", "") or ""),
            title=str(payload.get("title", "") or "Saved break"),
            created_at=str(payload.get("created_at", "") or ""),
            source_path=str(payload.get("source_path", "") or "") or None,
            origin=str(payload.get("origin", "") or "generator"),
            mode=str(payload.get("mode", "") or GENERATOR_MODE_CLASSIC),
            target_bpm=float(payload.get("target_bpm", 120.0) or 120.0),
            detected_bpm_factor=float(payload.get("detected_bpm_factor", 1.0) or 1.0),
            anchors=anchors,
            locked_steps=tuple(sorted(set(locked_steps))),
            result_payload=dict(payload.get("result_payload", {}) or {}),
            pattern_payload=dict(payload.get("pattern_payload", {}) or {}),
        )


@dataclass(frozen=True)
class LiveStemMixConfig:
    stem_names: tuple[str, ...] = ()
    state_key: str = ""
    gain: float = 1.0
    apply_lowpass: bool = False
    apply_highpass: bool = False
    apply_distortion: bool = False
    apply_bitcrush: bool = False
    apply_gate: bool = False
    apply_stutter: bool = True


@dataclass(frozen=True)
class LiveMixPlan:
    stems: tuple[LiveStemMixConfig, ...] = ()
    lowpass_hz: float = 0.0
    highpass_hz: float = 0.0
    distortion_drive: float = 0.0
    distortion_tone: float = 0.0
    distortion_mix: float = 0.0
    bit_depth: int = 16
    gate_ratio: float = 1.0


class ToggleSection(QWidget):
    def __init__(self, title: str, *, expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.toggle_button = QToolButton(self)
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.setText(str(title))
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle_button.toggled.connect(self._on_toggled)
        layout.addWidget(self.toggle_button)

        self.body = QWidget(self)
        self.body.setObjectName("SectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 0, 0)
        self.body_layout.setSpacing(8)
        self.body.setVisible(bool(expanded))
        layout.addWidget(self.body)

    def _on_toggled(self, checked: bool) -> None:
        self.body.setVisible(bool(checked))
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def setExpanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(bool(expanded))

    def isExpanded(self) -> bool:
        return bool(self.toggle_button.isChecked())


class NoWheelTabBar(QTabBar):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class RetimePreviewPatternWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RetimePreviewPatternWidget")
        self.setMinimumHeight(156)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._segments: tuple[RetimedPreviewSegment, ...] = ()
        self._scaled_starts: tuple[float, ...] = ()
        self._preview_starts: tuple[float, ...] = ()
        self._duration_s = 0.0
        self._target_bpm = 120.0
        self._mode = PREVIEW_MODE_RETIME
        self._grid_division: int | None = None
        self._quantize_strength = 0.0
        self._active_segment_index: int | None = None
        self._message = (
            "Le preview pattern montrera ici les placements source et relus. "
            "En mode quantize, les traits de grille aident a lire ce qui est recale."
        )
        self.setToolTip(
            "Vue compacte du preview: ligne Source = placements retimes avant quantize, "
            "ligne Preview = placements relus. Les connecteurs montrent le deplacement vers la grille."
        )

    @property
    def segment_count(self) -> int:
        return len(self._segments)

    @property
    def active_segment_index(self) -> int | None:
        return self._active_segment_index

    def clear_preview(self, message: str | None = None) -> None:
        self._segments = ()
        self._scaled_starts = ()
        self._preview_starts = ()
        self._duration_s = 0.0
        self._target_bpm = 120.0
        self._mode = PREVIEW_MODE_RETIME
        self._grid_division = None
        self._quantize_strength = 0.0
        self._active_segment_index = None
        self._message = (
            str(message).strip()
            if message is not None and str(message).strip()
            else "Le preview pattern apparaitra ici quand une preview retime/quantize sera disponible."
        )
        self.update()

    def set_preview_data(
        self,
        segments: tuple[RetimedPreviewSegment, ...] | list[RetimedPreviewSegment],
        *,
        source_bpm: float,
        target_bpm: float,
        duration_s: float,
        mode: str,
        grid_division: int | None,
        quantize_strength: float,
    ) -> None:
        ordered_segments = tuple(segments)
        if not ordered_segments:
            self.clear_preview()
            return
        resolved_source_bpm = max(float(source_bpm), 1e-6)
        resolved_target_bpm = max(float(target_bpm), 1e-6)
        speed_ratio = float(resolved_source_bpm / resolved_target_bpm)
        base_source_start = float(ordered_segments[0].source_start_s)
        self._segments = ordered_segments
        self._scaled_starts = tuple(
            max(0.0, (float(segment.source_start_s) - base_source_start) * speed_ratio)
            for segment in ordered_segments
        )
        self._preview_starts = tuple(float(segment.preview_start_s) for segment in ordered_segments)
        last_preview_end = max(float(segment.preview_end_s) for segment in ordered_segments)
        last_scaled_start = max(self._scaled_starts) if self._scaled_starts else 0.0
        self._duration_s = max(float(duration_s), last_preview_end, last_scaled_start + 0.05, 0.1)
        self._target_bpm = resolved_target_bpm
        self._mode = PREVIEW_MODE_QUANTIZE if mode == PREVIEW_MODE_QUANTIZE else PREVIEW_MODE_RETIME
        self._grid_division = int(grid_division) if grid_division is not None else None
        self._quantize_strength = float(np.clip(quantize_strength, 0.0, 1.0))
        if self._active_segment_index is not None and self._active_segment_index >= len(self._segments):
            self._active_segment_index = None
        self._message = ""
        self.update()

    def set_active_segment(self, index: int | None) -> None:
        resolved_index: int | None = None
        if index is not None:
            try:
                candidate = int(index)
            except (TypeError, ValueError):
                candidate = -1
            if 0 <= candidate < len(self._segments):
                resolved_index = candidate
        if resolved_index == self._active_segment_index:
            return
        self._active_segment_index = resolved_index
        self.update()

    def _time_to_x(self, time_s: float, timeline_left: int, timeline_width: int) -> float:
        if timeline_width <= 1:
            return float(timeline_left)
        ratio = float(np.clip(float(time_s) / max(self._duration_s, 1e-6), 0.0, 1.0))
        return float(timeline_left) + (ratio * float(max(timeline_width - 1, 1)))

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(outer, QColor("#111723"))
        painter.setPen(QPen(QColor("#243044"), 1))
        painter.drawRoundedRect(outer, 10, 10)

        if not self._segments:
            painter.setPen(QColor("#8e9ab0"))
            painter.drawText(
                outer.adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._message,
            )
            return

        content = outer.adjusted(12, 12, -12, -12)
        label_width = 42
        timeline_rect = content.adjusted(label_width, 18, 0, -8)
        if timeline_rect.width() <= 16 or timeline_rect.height() <= 16:
            return

        source_y = int(timeline_rect.top() + (timeline_rect.height() * 0.30))
        preview_y = int(timeline_rect.top() + (timeline_rect.height() * 0.72))

        painter.setPen(QColor("#95a2bb"))
        painter.drawText(content.left(), source_y + 5, "Src")
        painter.drawText(content.left(), preview_y + 5, "Out")

        header_text = "Retime flow"
        if self._mode == PREVIEW_MODE_QUANTIZE:
            header_text = (
                f"Quantize {format_quantize_grid_label(self._grid_division)}  "
                f"{self._quantize_strength * 100:.0f}%"
            )
        painter.setPen(QColor("#c6d1e3"))
        painter.drawText(timeline_rect.left(), content.top() + 2, header_text)

        lane_pen = QPen(QColor("#314054"), 1)
        painter.setPen(lane_pen)
        painter.drawLine(timeline_rect.left(), source_y, timeline_rect.right(), source_y)
        painter.drawLine(timeline_rect.left(), preview_y, timeline_rect.right(), preview_y)

        grid_division = (
            self._grid_division if self._grid_division in QUANTIZE_GRID_DIVISIONS else DEFAULT_QUANTIZE_GRID_DIVISION
        )
        beat_duration_s = 60.0 / max(self._target_bpm, 1e-6)
        grid_step_s = beat_duration_s * (4.0 / float(grid_division))
        beat_every = max(1, int(round(float(grid_division) / 4.0)))
        if grid_step_s > 1e-6:
            line_count = int(np.ceil(self._duration_s / grid_step_s)) + 1
            for grid_index in range(max(line_count, 2)):
                current_time = min(float(grid_index) * grid_step_s, self._duration_s)
                x = int(round(self._time_to_x(current_time, timeline_rect.left(), timeline_rect.width())))
                if grid_index % beat_every == 0:
                    pen = QPen(QColor("#35506f"), 1.4)
                else:
                    pen = QPen(QColor("#253345"), 1)
                painter.setPen(pen)
                painter.drawLine(x, timeline_rect.top() + 10, x, timeline_rect.bottom())

        show_labels = len(self._segments) <= 24
        source_color = QColor("#79aef7")
        preview_color = QColor("#e0ad4f") if self._mode == PREVIEW_MODE_QUANTIZE else QColor("#64d0b4")
        connector_color = QColor("#54749f")
        active_color = QColor("#f5d86b")

        for index, segment in enumerate(self._segments):
            source_x = self._time_to_x(self._scaled_starts[index], timeline_rect.left(), timeline_rect.width())
            preview_x = self._time_to_x(self._preview_starts[index], timeline_rect.left(), timeline_rect.width())
            is_active = index == self._active_segment_index
            moved = abs(preview_x - source_x) >= 0.75

            connector_pen = QPen(active_color if is_active else connector_color, 2.2 if is_active else 1.2)
            painter.setPen(connector_pen)
            painter.drawLine(int(round(source_x)), source_y, int(round(preview_x)), preview_y)

            source_radius = 5 if is_active else 4
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(active_color if is_active else source_color)
            painter.drawEllipse(
                int(round(source_x - source_radius)),
                int(round(source_y - source_radius)),
                source_radius * 2,
                source_radius * 2,
            )

            short_label = HIT_LABEL_SHORT_TEXT.get(str(segment.label).strip().lower(), str(segment.label)[:2].upper())
            label_width = 22 if len(short_label) <= 1 else 28
            label_height = 16
            preview_rect_left = int(round(preview_x - (label_width / 2)))
            preview_rect_top = int(round(preview_y - (label_height / 2)))
            fill_color = active_color if is_active else preview_color
            if self._mode == PREVIEW_MODE_QUANTIZE and moved and not is_active:
                fill_color = QColor("#f0b45a")
            painter.setBrush(fill_color)
            painter.setPen(QPen(QColor("#0f1520"), 1))
            painter.drawRoundedRect(preview_rect_left, preview_rect_top, label_width, label_height, 4, 4)

            if show_labels:
                painter.setPen(QColor("#0f1520") if is_active else QColor("#172030"))
                painter.drawText(
                    preview_rect_left,
                    preview_rect_top,
                    label_width,
                    label_height,
                    Qt.AlignmentFlag.AlignCenter,
                    short_label,
                )


class TaskWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task = task
        self.finished.connect(self.deleteLater)

    def run(self) -> None:
        try:
            result = self._task()
            if self.isInterruptionRequested():
                return
            self.succeeded.emit(result)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(str(exc))


class ProcessTaskWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        task: Callable[..., object],
        *args: object,
        kwargs: dict[str, object] | None = None,
        executor_getter: Callable[[], ProcessPoolExecutor] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._args = args
        self._kwargs = dict(kwargs or {})
        self._executor_getter = executor_getter or _pattern_generation_process_pool
        self.finished.connect(self.deleteLater)

    def run(self) -> None:
        future = None
        try:
            future = self._executor_getter().submit(self._task, *self._args, **self._kwargs)
            while True:
                if self.isInterruptionRequested():
                    future.cancel()
                    return
                try:
                    result = future.result(timeout=0.1)
                    break
                except TimeoutError:
                    continue
            if self.isInterruptionRequested():
                return
            self.succeeded.emit(result)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(str(exc))


class FileDropLineEdit(QLineEdit):
    fileDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _extract_audio_path(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        path = _extract_audio_path(event.mimeData())
        if not path:
            super().dropEvent(event)
            return
        self.setText(path)
        self.fileDropped.emit(path)
        event.acceptProposedAction()


class AnalysisWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progressed = Signal(str)
    preview_ready = Signal(object)

    def __init__(
        self,
        path: str,
        top_n: int,
        split_density: float,
        *,
        audio: np.ndarray | None = None,
        sample_rate: int | None = None,
        source_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.top_n = top_n
        self.split_density = split_density
        self.audio = None if audio is None else np.array(audio, dtype=np.float32, copy=True)
        self.sample_rate = int(sample_rate or 0)
        self.source_path = source_path

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            self.progressed.emit("Chargement audio et detection initiale des transients...")
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"n_fft=.*too large for input signal of length=.*",
                    category=UserWarning,
                )
                warnings.filterwarnings(
                    "ignore",
                    message=r"Trying to estimate tuning from empty frequency set\.",
                    category=UserWarning,
                )
                def _handle_preview(preview: DrumTransientPreview) -> None:
                    if self.isInterruptionRequested():
                        return
                    self.preview_ready.emit(preview)
                    self.progressed.emit(
                        f"{preview.onset_count} transient(s) reperes, classification detaillee en cours..."
                    )

                if self.audio is not None and self.sample_rate > 0:
                    result = analyze_audio_with_preview(
                        self.audio,
                        self.sample_rate,
                        source_path=self.source_path or self.path,
                        top_n=self.top_n,
                        split_density=self.split_density,
                        preview_callback=_handle_preview,
                    )
                else:
                    result = analyze_file_with_preview(
                        self.path,
                        top_n=self.top_n,
                        split_density=self.split_density,
                        preview_callback=_handle_preview,
                    )
            if self.isInterruptionRequested():
                return
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class DrumDetectorWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("SampleRod", "DrumDetectorPrototype")
        self._dependency_error: str | None = None
        self._waveform_error: str | None = None
        self._waveform_widget: QWidget | None = None
        self._waveform_panel_init_requested = False
        self._worker: AnalysisWorker | None = None
        self._waveform_loader: TaskWorker | None = None
        self._rebuild_worker: TaskWorker | None = None
        self._generator_worker: TaskWorker | None = None
        self._preview_worker: TaskWorker | None = None
        self._close_after_background_tasks = False
        self._analysis_busy = False
        self._waveform_loading = False
        self._rebuild_busy = False
        self._generator_busy = False
        self._preview_busy = False
        self._analysis_stale = False
        self._suspend_marker_persistence = False
        self._generator_step_anchors: dict[int, str] = {}
        self._generator_locked_steps: set[int] = set()
        self._generator_user_motifs: list[UserMotif] = []
        self._saved_pattern_snapshots: list[SavedPatternSnapshot] = []
        self._saved_pattern_selected_id: str | None = None
        self._pending_saved_snapshot_restore: SavedPatternSnapshot | None = None
        self._generator_motif_editor_steps: list[str | None] = [None] * 8
        self._generator_motif_dominant_dirty = False
        self._result: DrumDetectionResult | None = None
        self._suspend_hit_selection_sync = False
        self._loaded_audio_samples: np.ndarray | None = None
        self._loaded_audio_sample_rate: int | None = None
        self._loaded_audio_path: str | None = None
        self._live_audio_shared_memory: shared_memory.SharedMemory | None = None
        self._live_audio_shared_shape: tuple[int, ...] | None = None
        self._live_audio_shared_sample_rate: int | None = None
        self._retained_live_audio_shared_memories: list[shared_memory.SharedMemory] = []
        self._waveform_load_token = 0
        self._retimed_preview: RetimedPreview | None = None
        self._retimed_preview_playing = False
        self._generated_pattern: GeneratedBreakPattern | None = None
        self._retime_stop_timer = QTimer(self)
        self._retime_stop_timer.setSingleShot(True)
        self._retime_stop_timer.timeout.connect(self._on_retimed_preview_finished)
        self._retime_visual_timer = QTimer(self)
        self._retime_visual_timer.setInterval(20)
        self._retime_visual_timer.timeout.connect(self._update_retimed_preview_visual)
        self._retime_visual_started_at = 0.0
        self._retime_visual_segment_index = -1
        self._retime_stream = None
        self._retime_stream_audio: np.ndarray | None = None
        self._retime_stream_cursor = 0
        self._retime_stream_frames_played = 0
        self._retime_stream_total_frames = 0
        self._retime_stream_loop_enabled = False
        self._retime_underflow_log_at = 0.0
        self._generator_probability_refresh_timer = QTimer(self)
        self._generator_probability_refresh_timer.setSingleShot(True)
        self._generator_probability_refresh_timer.setInterval(120)
        self._generator_probability_refresh_timer.timeout.connect(self._flush_generator_probability_preview_refresh)
        self._generator_probability_refresh_pending = False
        self._generator_live_refresh_timer = QTimer(self)
        self._generator_live_refresh_timer.setSingleShot(True)
        self._generator_live_refresh_timer.setInterval(90)
        self._generator_live_refresh_timer.timeout.connect(self._flush_live_generator_preview_refresh)
        self._generator_structure_revision = 0
        self._generator_pipeline_state: PipelineState | None = None
        self._marker_persist_timer = QTimer(self)
        self._marker_persist_timer.setSingleShot(True)
        self._marker_persist_timer.timeout.connect(self._persist_current_markers)
        self._preview_owner: str | None = None
        self._retime_live_changes_pending = False
        self._generator_live_changes_pending = False
        self._generator_gate_preview_pending = False
        self._active_generator_param_slider_ids: set[int] = set()
        self._generator_bulk_param_update = False
        self._live_mode_enabled = bool(self._settings.value("live_mode_enabled", False, type=bool))
        self._live_slots: dict[str, PatternSlot] = {slot_name: PatternSlot() for slot_name in LIVE_SLOT_NAMES}
        self._live_slot_workers: dict[str, QThread | None] = {slot_name: None for slot_name in LIVE_SLOT_NAMES}
        self._live_slot_tokens: dict[str, int] = {slot_name: 0 for slot_name in LIVE_SLOT_NAMES}
        self._live_active_slot = "A"
        self._live_view_slot = "A"
        self._live_pending_switch_slot: str | None = None
        self._live_switch_ready = False
        self._live_switch_ui_refresh_pending = False
        self._live_target_bpm_value = 120.0
        self._live_generation_counter = 0
        self._live_stem_enabled: dict[str, bool] = {stem_name: True for stem_name in LIVE_STEM_NAMES}
        self._live_effect_values: dict[str, float | int | bool] = dict(LIVE_EFFECT_DEFAULTS)
        self._live_effect_targets: dict[str, dict[str, bool]] = {
            effect_name: {stem_name: True for stem_name in LIVE_STEM_NAMES} for effect_name in LIVE_EFFECT_NAMES
        }
        self._live_distortion_drive = 0.0
        self._live_distortion_tone = 0.0
        self._live_distortion_mix = 0.0
        self._live_mix_plan = LiveMixPlan()
        self._live_lowpass_state: dict[str, np.ndarray] = {}
        self._live_highpass_state: dict[str, np.ndarray] = {}
        self._live_gate_envelope_cache: dict[tuple[int, int, int, int, int], np.ndarray] = {}
        self._live_stutter_positions_cache_key: tuple[int, int, int, int, int] | None = None
        self._live_stutter_positions_cache: np.ndarray | None = None
        self._live_stutter_pressed = False
        self._live_stutter_hold_start_frame = 0
        self._live_shortcuts: list[QShortcut] = []
        self._tab_navigation_shortcuts: list[QShortcut] = []
        self._live_pending_flash_on = False
        self._live_pending_flash_timer = QTimer(self)
        self._live_pending_flash_timer.setInterval(360)
        self._live_pending_flash_timer.timeout.connect(self._toggle_live_pending_flash)
        self._live_compact_highlight_slot: str | None = None
        self._live_compact_highlight_step: int | None = None
        self._live_slot_compact_signatures: dict[str, tuple[object, ...] | None] = {}
        self._ui_callback_queue: SimpleQueue = SimpleQueue()
        self._ui_callback_timer = QTimer(self)
        self._ui_callback_timer.setInterval(16)
        self._ui_callback_timer.timeout.connect(self._drain_ui_callback_queue)
        self._ui_callback_timer.start()
        self._generator_tab_refresh_pending = False
        self._live_tab_refresh_pending = False
        self._inspector_tab_refresh_pending = False

        self._build_ui()
        self._build_waveform_shortcuts()
        self._build_live_shortcuts()
        self._build_tab_navigation_shortcuts()
        self._apply_style()
        self._schedule_waveform_panel_init()
        self._restore_state()
        if hasattr(self, "generator_target_bpm_spin"):
            self._live_target_bpm_value = max(float(self.generator_target_bpm_spin.value()), 1e-6)

    def _dispatch_ui_callback(self, callback: Callable[[], None]) -> None:
        if QThread.currentThread() is self.thread():
            callback()
            return
        self._ui_callback_queue.put(callback)

    def _drain_ui_callback_queue(self) -> None:
        while True:
            try:
                callback = self._ui_callback_queue.get_nowait()
            except Empty:
                break
            if not callable(callback):
                continue
            try:
                callback()
            except Exception:
                logging.getLogger(__name__).exception("UI callback execution failed")

    def _build_ui(self) -> None:
        self.setWindowTitle("SampleRod - Drum Detector Prototype")
        self.resize(1280, 960)
        self.setMinimumSize(1040, 760)
        self.setAcceptDrops(True)
        self.setFont(self._build_font(10))

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.page_scroll = QScrollArea(self)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        shell.addWidget(self.page_scroll)

        self.page_content = QWidget()
        self.page_content.setMinimumWidth(980)
        self.page_scroll.setWidget(self.page_content)

        root = QVBoxLayout(self.page_content)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("Detecteur drum / break - prototype")
        title.setObjectName("TitleLabel")
        title.setFont(self._build_font(16, bold=True))
        subtitle = QLabel(
            "Selectionne un sample, ecoute-le dans la waveform, puis inspecte la detection one-shot / loop, "
            "le label principal et les markers de transients."
        )
        subtitle.setWordWrap(True)

        path_row = QHBoxLayout()
        self.path_input = FileDropLineEdit()
        self.path_input.setPlaceholderText("Choisir un sample .wav / .mp3 / .flac ou glisser-deposer ici")
        self.path_input.returnPressed.connect(self._start_analysis)
        self.path_input.fileDropped.connect(self._handle_path_selected)

        self.recent_files_combo = QComboBox()
        self.recent_files_combo.addItem("Recents", None)
        self.recent_files_combo.setMinimumWidth(240)
        self.recent_files_combo.setToolTip("Rouvrir rapidement un sample charge precedemment")
        self.recent_files_combo.activated.connect(self._on_recent_file_selected)

        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self._browse_file)
        self._configure_icon_button(
            self.browse_button,
            QStyle.StandardPixmap.SP_DialogOpenButton,
            "Choisir un fichier audio",
            qtawesome_name="fa5s.folder-open",
        )

        self.analyze_button = QPushButton("Analyser")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(self._start_analysis)
        self._set_button_icon(
            self.analyze_button,
            QStyle.StandardPixmap.SP_MediaPlay,
            qtawesome_name="fa5s.wave-square",
            color="#171a20",
        )
        self.analyze_button.setToolTip("Lancer l'analyse du sample charge")

        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(self.recent_files_combo)
        path_row.addWidget(self.browse_button)
        path_row.addWidget(self.analyze_button)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Top candidats:"))
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(1, 12)
        self.top_n_spin.setValue(5)
        options_row.addWidget(self.top_n_spin)
        options_row.addSpacing(12)
        options_row.addWidget(QLabel("Decoupage initial:"))
        self.split_density_slider = QSlider(Qt.Orientation.Horizontal)
        self.split_density_slider.setRange(0, 100)
        self.split_density_slider.setSingleStep(5)
        self.split_density_slider.setPageStep(10)
        self.split_density_slider.setFixedWidth(170)
        self.split_density_slider.setValue(int(round(DEFAULT_SPLIT_DENSITY)))
        self.split_density_slider.valueChanged.connect(self._on_split_density_changed)
        options_row.addWidget(self.split_density_slider)
        self.split_density_value = QLabel()
        self.split_density_value.setMinimumWidth(128)
        options_row.addWidget(self.split_density_value)
        options_row.addStretch(1)

        self.status_label = QLabel("Pret.")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self._reserve_label_height(self.status_label, lines=2)
        self.main_loading_bar = self._build_loading_bar()

        self.main_tabs = QTabWidget(self.page_content)
        self.main_tabs.setTabBar(NoWheelTabBar(self.main_tabs))
        self.main_tabs.setDocumentMode(True)
        self._main_tab_pages: dict[str, QWidget] = {}
        self._main_tab_layouts: dict[str, QVBoxLayout] = {}
        for key, label in (
            (MAIN_TAB_ANALYZE, "Analyze / Waveform"),
            (MAIN_TAB_PREVIEW, "Preview"),
            (MAIN_TAB_GENERATOR, "Generator"),
            (MAIN_TAB_LIVE, "Live"),
            (MAIN_TAB_SAVED, "Saved"),
            (MAIN_TAB_INSPECTOR, "Inspector"),
        ):
            page = QWidget(self.main_tabs)
            page.setProperty("mainTabKey", key)
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            self._main_tab_pages[key] = page
            self._main_tab_layouts[key] = layout
            self.main_tabs.addTab(page, label)
        self._main_tab_layouts[MAIN_TAB_ANALYZE].addWidget(
            self._build_tab_intro(
                "Charge un sample, travaille la waveform, coupe, replace les markers et controle les hits detectes."
            )
        )
        self._main_tab_layouts[MAIN_TAB_PREVIEW].addWidget(
            self._build_tab_intro(
                "Ecoute le break source en retime ou quantize sans melanger cette etape avec le generateur."
            )
        )
        self._main_tab_layouts[MAIN_TAB_GENERATOR].addWidget(
            self._build_tab_intro(
                "Regle la structure, les sequences, les FX et la grille principale du pattern genere."
            )
        )
        self._main_tab_layouts[MAIN_TAB_LIVE].addWidget(
            self._build_tab_intro(
                "Pilote les slots A/B, les stems et les callback FX pour la performance live."
            )
        )
        self._main_tab_layouts[MAIN_TAB_SAVED].addWidget(
            self._build_tab_intro(
                "Retrouve des snapshots de breaks deja sauvegardes, recharge-les dans le generateur et exporte-les en WAV."
            )
        )
        self._main_tab_layouts[MAIN_TAB_INSPECTOR].addWidget(
            self._build_tab_intro(
                "Lis les details de detection, les candidats, le JSON brut et les apercus heuristiques sans polluer le workflow principal."
            )
        )
        self.analyze_source_box = QGroupBox("Source / analyse")
        analyze_source_layout = QVBoxLayout(self.analyze_source_box)
        analyze_source_layout.setSpacing(10)
        analyze_source_layout.addWidget(title)
        analyze_source_layout.addWidget(subtitle)
        analyze_source_layout.addLayout(path_row)
        analyze_source_layout.addLayout(options_row)
        analyze_source_layout.addWidget(self.status_label)
        analyze_source_layout.addWidget(self.main_loading_bar)
        self._main_tab_layouts[MAIN_TAB_ANALYZE].addWidget(self.analyze_source_box)

        self._build_waveform_box(self._main_tab_layouts[MAIN_TAB_ANALYZE])
        self._build_retime_controls(self._main_tab_layouts[MAIN_TAB_PREVIEW])
        self._build_generator_controls(self._main_tab_layouts[MAIN_TAB_GENERATOR])
        self._build_saved_patterns_tab(self._main_tab_layouts[MAIN_TAB_SAVED])
        self._build_result_boxes(self._main_tab_layouts[MAIN_TAB_INSPECTOR])
        self._main_tab_layouts[MAIN_TAB_PREVIEW].addWidget(self.retime_box)
        self._main_tab_layouts[MAIN_TAB_GENERATOR].addWidget(self.generator_box)
        self._main_tab_layouts[MAIN_TAB_LIVE].addWidget(self.generator_live_section)
        self._main_tab_layouts[MAIN_TAB_SAVED].addWidget(self.saved_patterns_box)
        self._main_tab_layouts[MAIN_TAB_INSPECTOR].addWidget(self.generator_probability_section)
        self._main_tab_layouts[MAIN_TAB_INSPECTOR].addWidget(self.generator_pattern_details_section)
        for layout in self._main_tab_layouts.values():
            layout.addStretch(1)

        self.main_tabs.currentChanged.connect(self._on_main_tab_changed)
        root.addWidget(self.main_tabs, 1)
        self._refresh_split_density_label(self.split_density_slider.value())

    def _build_tab_intro(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("StatusLabel")
        label.setWordWrap(True)
        label.setContentsMargins(2, 0, 2, 0)
        return label

    def _current_main_tab_key(self) -> str:
        if not hasattr(self, "main_tabs"):
            return MAIN_TAB_ANALYZE
        current_page = self.main_tabs.currentWidget()
        if current_page is None:
            return MAIN_TAB_ANALYZE
        return str(current_page.property("mainTabKey") or MAIN_TAB_ANALYZE)

    def _main_tab_is_visible(self, *keys: str) -> bool:
        if not hasattr(self, "main_tabs"):
            return True
        return self._current_main_tab_key() in {str(key) for key in keys}

    def _on_main_tab_changed(self, _index: int) -> None:
        current_key = self._current_main_tab_key()
        if self._generator_tab_refresh_pending and current_key == MAIN_TAB_GENERATOR:
            self._generator_tab_refresh_pending = False
            self._populate_generated_pattern(
                self._live_display_pattern() if self._live_mode_enabled else self._generated_pattern
            )
        if self._live_tab_refresh_pending and current_key == MAIN_TAB_LIVE:
            self._live_tab_refresh_pending = False
            self._refresh_live_mode_ui_now()
        if self._inspector_tab_refresh_pending and current_key == MAIN_TAB_INSPECTOR and self._result is not None:
            self._inspector_tab_refresh_pending = False
            self._populate_result_now(self._result)
            self._refresh_generator_probability_preview_now(force=True)
    def _build_waveform_box(self, root: QVBoxLayout) -> None:
        self.waveform_box = QGroupBox("Waveform / transients")
        layout = QVBoxLayout(self.waveform_box)
        layout.setSpacing(10)

        self.waveform_status_label = QLabel(
            "Le waveform editor de SampleRod sera charge ici si les dependances UI sont disponibles."
        )
        self.waveform_status_label.setObjectName("StatusLabel")
        self.waveform_status_label.setWordWrap(True)
        self._reserve_label_height(self.waveform_status_label, lines=3)
        self.waveform_loading_bar = self._build_loading_bar()

        self.waveform_host = QVBoxLayout()
        self.waveform_placeholder = QLabel(
            "Waveform editor indisponible pour le moment. "
            "Le proto restera utilisable pour l'analyse textuelle."
        )
        self.waveform_placeholder.setWordWrap(True)
        self.waveform_host.addWidget(self.waveform_placeholder)

        waveform_playback_row = QHBoxLayout()
        self.waveform_play_button = QPushButton("Play waveform")
        self.waveform_play_button.clicked.connect(self._play_waveform_from_start)
        self._set_button_icon(
            self.waveform_play_button,
            QStyle.StandardPixmap.SP_MediaPlay,
            qtawesome_name="fa5s.play",
        )
        self.waveform_pause_button = QPushButton("Pause waveform")
        self.waveform_pause_button.clicked.connect(self._pause_or_resume_waveform)
        self._set_button_icon(
            self.waveform_pause_button,
            QStyle.StandardPixmap.SP_MediaPause,
            qtawesome_name="fa5s.pause",
        )
        self.waveform_stop_button = QPushButton("Stop waveform")
        self.waveform_stop_button.clicked.connect(self._stop_and_reset_waveform)
        self._set_button_icon(
            self.waveform_stop_button,
            QStyle.StandardPixmap.SP_MediaStop,
            qtawesome_name="fa5s.stop",
        )
        self.waveform_loop_toggle_button = QPushButton("Loop waveform")
        self.waveform_loop_toggle_button.setObjectName("ToggleButton")
        self.waveform_loop_toggle_button.setCheckable(True)
        self.waveform_loop_toggle_button.toggled.connect(self._set_waveform_loop_enabled)
        self.waveform_loop_toggle_button.setToolTip(
            "Loop ON/OFF pour la waveform. Raccourci SampleRod: Ctrl+L."
        )
        for button in (
            self.waveform_play_button,
            self.waveform_pause_button,
            self.waveform_stop_button,
            self.waveform_loop_toggle_button,
        ):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            waveform_playback_row.addWidget(button)
        waveform_playback_row.addStretch(1)

        self.waveform_playback_label = QLabel(
            "Waveform: Ctrl+Space = play from start, Space = pause/resume, Alt+Space = stop, Ctrl+L = loop."
        )
        self.waveform_playback_label.setObjectName("StatusLabel")
        self.waveform_playback_label.setWordWrap(True)
        self._reserve_label_height(self.waveform_playback_label, lines=2)

        self.hits_summary_label = QLabel("Aucun transient detecte pour le moment.")
        self.hits_summary_label.setObjectName("StatusLabel")
        self.hits_summary_label.setWordWrap(True)
        self._reserve_label_height(self.hits_summary_label, lines=2)

        edit_row = QHBoxLayout()
        self.cut_selection_button = QPushButton("Cut selection")
        self.cut_selection_button.clicked.connect(self._cut_waveform_selection)
        self.undo_edit_button = QPushButton("Undo edit")
        self.undo_edit_button.clicked.connect(self._undo_waveform_edit)
        self._configure_icon_button(
            self.undo_edit_button,
            QStyle.StandardPixmap.SP_ArrowBack,
            "Annuler la derniere coupe ou edition de waveform",
            qtawesome_name="fa5s.undo-alt",
        )
        self.redo_edit_button = QPushButton("Redo edit")
        self.redo_edit_button.clicked.connect(self._redo_waveform_edit)
        self._configure_icon_button(
            self.redo_edit_button,
            QStyle.StandardPixmap.SP_ArrowForward,
            "Retablir l'edition de waveform annulee",
            qtawesome_name="fa5s.redo-alt",
        )
        edit_row.addWidget(self.cut_selection_button)
        edit_row.addWidget(self.undo_edit_button)
        edit_row.addWidget(self.redo_edit_button)
        edit_row.addStretch(1)

        self.waveform_edit_label = QLabel(
            "Selectionne une region en glissant sur la waveform, puis coupe-la ici pour simplifier le break "
            "avant de relancer l'analyse. Undo / redo restent disponibles sur les edits."
        )
        self.waveform_edit_label.setObjectName("StatusLabel")
        self.waveform_edit_label.setWordWrap(True)
        self._reserve_label_height(self.waveform_edit_label, lines=2)

        self.rebuild_markers_button = QPushButton("Rebuild Hits From Markers")
        self.rebuild_markers_button.clicked.connect(self._rebuild_hits_from_markers)
        self.rebuild_markers_button.setEnabled(False)
        self._set_button_icon(
            self.rebuild_markers_button,
            QStyle.StandardPixmap.SP_BrowserReload,
            qtawesome_name="fa5s.sync-alt",
        )
        self.rebuild_markers_button.setToolTip(
            "Reconstruire la liste de hits a partir des markers actuellement poses dans la waveform"
        )

        self.rebuild_markers_label = QLabel(
            "Tu peux ajouter, deplacer ou supprimer des markers dans la waveform, puis reconstruire la liste de transients."
        )
        self.rebuild_markers_label.setObjectName("StatusLabel")
        self.rebuild_markers_label.setWordWrap(True)
        self._reserve_label_height(self.rebuild_markers_label, lines=2)

        self.hits_table = QTableWidget(0, 7)
        self.hits_table.setHorizontalHeaderLabels(("Hit", "Pool", "Label", "Start", "End", "Conf", "Peak dB"))
        self.hits_table.verticalHeader().setVisible(False)
        self.hits_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hits_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.hits_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.hits_table.setAlternatingRowColors(True)
        self.hits_table.setWordWrap(False)
        self.hits_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.hits_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.hits_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.hits_table.setMinimumHeight(320)
        self.hits_table.setMinimumWidth(920)
        header = self.hits_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        for column in range(7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.hits_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.hits_table.itemClicked.connect(self._on_hit_clicked)
        self.hits_table.itemSelectionChanged.connect(self._on_hit_selected)
        self.hits_table.itemDoubleClicked.connect(self._on_hit_double_clicked)

        self.hits_panel = QGroupBox("Hits detectes")
        hits_layout = QVBoxLayout(self.hits_panel)
        hits_layout.setSpacing(8)
        hits_layout.addWidget(self.hits_summary_label)
        hits_layout.addWidget(self.rebuild_markers_button)
        hits_layout.addWidget(self.rebuild_markers_label)
        hits_layout.addWidget(self.hits_table)
        self.hits_panel.setMinimumHeight(400)

        waveform_top = QWidget(self.waveform_box)
        waveform_top_layout = QVBoxLayout(waveform_top)
        waveform_top_layout.setContentsMargins(0, 0, 0, 0)
        waveform_top_layout.setSpacing(8)
        waveform_top_layout.addWidget(self.waveform_status_label)
        waveform_top_layout.addWidget(self.waveform_loading_bar)
        waveform_top_layout.addLayout(self.waveform_host)
        waveform_top_layout.addLayout(waveform_playback_row)
        waveform_top_layout.addWidget(self.waveform_playback_label)
        waveform_top_layout.addLayout(edit_row)
        waveform_top_layout.addWidget(self.waveform_edit_label)

        self.waveform_splitter = QSplitter(Qt.Orientation.Vertical, self.waveform_box)
        self.waveform_splitter.setChildrenCollapsible(False)
        self.waveform_splitter.addWidget(waveform_top)
        self.waveform_splitter.addWidget(self.hits_panel)
        self.waveform_splitter.setStretchFactor(0, 3)
        self.waveform_splitter.setStretchFactor(1, 2)
        self.waveform_splitter.setSizes([520, 420])

        layout.addWidget(self.waveform_splitter, 1)
        self.waveform_box.setMinimumHeight(780)
        self._sync_waveform_playback_controls()
        root.addWidget(self.waveform_box)

    def _build_waveform_shortcuts(self) -> None:
        self._waveform_shortcuts: list[QShortcut] = []
        for sequence, handler in [
            ("Ctrl+X", lambda: self._with_waveform(lambda waveform: waveform._on_cut_shortcut())),
            ("Ctrl+Z", lambda: self._with_waveform(lambda waveform: waveform.undo())),
            ("Ctrl+Shift+Z", lambda: self._with_waveform(lambda waveform: waveform.redo())),
            ("Ctrl+L", lambda: self._with_waveform(lambda waveform: waveform.loop_button.toggle())),
            ("Ctrl+G", lambda: self._with_waveform(lambda waveform: waveform.toggle_marker_mode(not waveform.marker_mode))),
            ("Space", lambda: self._with_waveform(lambda waveform: waveform.pause_or_resume())),
            ("Ctrl+Space", lambda: self._with_waveform(lambda waveform: waveform.play_from_start())),
            ("Alt+Space", lambda: self._with_waveform(lambda waveform: waveform.stop_and_reset())),
            ("Ctrl+E", lambda: self._with_waveform(lambda waveform: waveform._on_export_shortcut())),
            ("Ctrl+Shift+G", lambda: self._with_waveform(lambda waveform: waveform.add_markers_to_region())),
        ]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda current_handler=handler: self._dispatch_waveform_shortcut(current_handler))
            self._waveform_shortcuts.append(shortcut)

    def _build_live_shortcuts(self) -> None:
        self._live_shortcuts = []
        for sequence, handler in [
            ("Space", self._switch_live_slots_next_cycle),
            ("D", lambda: self._duplicate_live_slot(self._live_active_slot, self._inactive_live_slot_name())),
            ("R", lambda: self._generate_live_slot(self._inactive_live_slot_name())),
            ("1", lambda: self._toggle_live_stem("kick")),
            ("2", lambda: self._toggle_live_stem("snare")),
            ("3", lambda: self._toggle_live_stem("hat")),
            ("4", lambda: self._toggle_live_stem("ghost")),
            ("5", lambda: self._toggle_live_stem("clap")),
            ("6", lambda: self._toggle_live_stem("repeat")),
            ("7", lambda: self._toggle_live_stem("reverse")),
            ("8", lambda: self._toggle_live_stem("roll")),
            ("9", lambda: self._toggle_live_stem("stretch")),
            ("0", lambda: self._toggle_live_stem("other")),
        ]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda current_handler=handler: self._dispatch_live_shortcut(current_handler))
            shortcut.setEnabled(False)
            self._live_shortcuts.append(shortcut)

    def _build_tab_navigation_shortcuts(self) -> None:
        self._tab_navigation_shortcuts = []
        for sequence, direction in [("Ctrl+Tab", 1), ("Ctrl+Shift+Tab", -1)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda current_direction=direction: self._cycle_main_tabs(current_direction)
            )
            self._tab_navigation_shortcuts.append(shortcut)

    def _cycle_main_tabs(self, direction: int) -> None:
        if not hasattr(self, "main_tabs"):
            return
        count = int(self.main_tabs.count())
        if count <= 1:
            return
        current_index = max(int(self.main_tabs.currentIndex()), 0)
        next_index = (current_index + int(direction)) % count
        self.main_tabs.setCurrentIndex(next_index)

    def _dispatch_live_shortcut(self, handler: Callable[[], None]) -> None:
        if not self._live_mode_enabled:
            return
        if self._waveform_focus_active():
            return
        handler()

    def _dispatch_waveform_shortcut(self, handler: Callable[[], None]) -> None:
        if self._waveform_widget is None:
            return
        if self._live_mode_enabled and not self._waveform_focus_active():
            return
        handler()

    def _set_waveform_shortcuts_enabled(self, enabled: bool) -> None:
        for shortcut in getattr(self, "_waveform_shortcuts", ()):
            shortcut.setEnabled(bool(enabled))

    def _set_live_shortcuts_enabled(self, enabled: bool) -> None:
        for shortcut in getattr(self, "_live_shortcuts", ()):
            shortcut.setEnabled(bool(enabled))

    def keyPressEvent(self, event) -> None:
        if (
            self._live_mode_enabled
            and event.key() == Qt.Key.Key_G
            and not event.isAutoRepeat()
        ):
            self._on_live_stutter_pressed()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if (
            self._live_mode_enabled
            and event.key() == Qt.Key.Key_G
            and not event.isAutoRepeat()
        ):
            self._on_live_stutter_released()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _with_waveform(self, callback: Callable[[QWidget], None]) -> None:
        if self._waveform_widget is None:
            return
        callback(self._waveform_widget)

    def _waveform_focus_active(self) -> bool:
        if self._waveform_widget is None:
            return False
        focus_widget = QApplication.focusWidget()
        current = focus_widget
        while current is not None:
            if current is self._waveform_widget:
                return True
            current = current.parentWidget()
        return False

    def _play_waveform_from_start(self) -> None:
        self._with_waveform(lambda waveform: waveform.play_from_start())

    def _pause_or_resume_waveform(self) -> None:
        self._with_waveform(lambda waveform: waveform.pause_or_resume())

    def _stop_and_reset_waveform(self) -> None:
        self._with_waveform(lambda waveform: waveform.stop_and_reset())

    def _set_waveform_loop_enabled(self, checked: bool) -> None:
        def _apply_loop(waveform) -> None:
            loop_button = getattr(waveform, "loop_button", None)
            if loop_button is not None and hasattr(loop_button, "isChecked") and hasattr(loop_button, "setChecked"):
                try:
                    if bool(loop_button.isChecked()) != bool(checked):
                        loop_button.setChecked(bool(checked))
                        return
                except Exception:
                    pass
            waveform.toggle_loop(bool(checked))

        self._with_waveform(_apply_loop)

    def _sync_waveform_playback_controls(self) -> None:
        waveform_available = self._waveform_widget is not None
        for button in (
            getattr(self, "waveform_play_button", None),
            getattr(self, "waveform_pause_button", None),
            getattr(self, "waveform_stop_button", None),
            getattr(self, "waveform_loop_toggle_button", None),
        ):
            if button is not None:
                button.setEnabled(waveform_available)
        if not waveform_available or not hasattr(self, "waveform_loop_toggle_button"):
            return
        checked = False
        loop_button = getattr(self._waveform_widget, "loop_button", None)
        if loop_button is not None and hasattr(loop_button, "isChecked"):
            try:
                checked = bool(loop_button.isChecked())
            except Exception:
                checked = False
        self.waveform_loop_toggle_button.blockSignals(True)
        self.waveform_loop_toggle_button.setChecked(checked)
        self.waveform_loop_toggle_button.blockSignals(False)

    def _build_retime_controls(self, layout: QVBoxLayout) -> None:
        self.retime_box = QGroupBox("Break retime preview")
        grid = QGridLayout(self.retime_box)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.detected_bpm_value = QLabel("-")
        self.detected_bpm_factor_combo = QComboBox()
        for label, factor in (("x0.5", 0.5), ("x1", 1.0), ("x2", 2.0), ("x4", 4.0)):
            self.detected_bpm_factor_combo.addItem(label, factor)
        saved_factor = float(self._settings.value("detected_bpm_factor", 1.0, type=float))
        self._set_detected_bpm_factor(saved_factor)
        self.detected_bpm_factor_combo.currentIndexChanged.connect(self._on_detected_bpm_factor_changed)
        self.target_bpm_spin = QDoubleSpinBox()
        self.target_bpm_spin.setRange(30.0, 400.0)
        self.target_bpm_spin.setDecimals(1)
        self.target_bpm_spin.setSingleStep(1.0)
        self.target_bpm_spin.setValue(120.0)
        self.target_bpm_spin.valueChanged.connect(self._on_target_bpm_changed)
        self.preview_mode_combo = QComboBox()
        self.preview_mode_combo.addItem("Retime", PREVIEW_MODE_RETIME)
        self.preview_mode_combo.addItem("Quantize", PREVIEW_MODE_QUANTIZE)
        saved_preview_mode = self._settings.value("preview_mode", PREVIEW_MODE_RETIME, type=str)
        self._set_preview_mode(saved_preview_mode)
        self.preview_mode_combo.currentIndexChanged.connect(self._on_preview_mode_changed)
        self.quantize_grid_combo = QComboBox()
        for grid_division in QUANTIZE_GRID_DIVISIONS:
            self.quantize_grid_combo.addItem(format_quantize_grid_label(grid_division), grid_division)
        saved_quantize_grid = self._settings.value(
            "quantize_grid_division",
            DEFAULT_QUANTIZE_GRID_DIVISION,
            type=int,
        )
        self._set_quantize_grid_division(saved_quantize_grid)
        self.quantize_grid_combo.currentIndexChanged.connect(self._on_quantize_grid_changed)
        self.quantize_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.quantize_strength_slider.setRange(0, 100)
        self.quantize_strength_slider.setSingleStep(5)
        self.quantize_strength_slider.setPageStep(10)
        self.quantize_strength_slider.setFixedWidth(140)
        saved_quantize_strength = self._settings.value(
            "quantize_strength_percent",
            int(round(DEFAULT_QUANTIZE_STRENGTH * 100.0)),
            type=int,
        )
        self.quantize_strength_slider.setValue(int(np.clip(saved_quantize_strength, 0, 100)))
        self.quantize_strength_slider.valueChanged.connect(self._on_quantize_strength_changed)
        self.quantize_strength_value = QLabel()
        self.quantize_strength_value.setMinimumWidth(52)
        self._refresh_quantize_strength_label(self.quantize_strength_slider.value())

        self.retime_play_button = QPushButton("Play retimed")
        self.retime_play_button.clicked.connect(self._play_retimed_preview)
        self._configure_icon_button(
            self.retime_play_button,
            QStyle.StandardPixmap.SP_MediaPlay,
            "Jouer la preview retimee avec les reglages courants",
            qtawesome_name="fa5s.play",
        )
        self.retime_stop_button = QPushButton("Stop retimed")
        self.retime_stop_button.clicked.connect(self._stop_retimed_preview)
        self._configure_icon_button(
            self.retime_stop_button,
            QStyle.StandardPixmap.SP_MediaStop,
            "Arreter la preview retimee",
            qtawesome_name="fa5s.stop",
        )
        self.retime_loop_button = QPushButton("Loop retimed")
        self.retime_loop_button.setObjectName("ToggleButton")
        self.retime_loop_button.setCheckable(True)
        self.retime_loop_button.setChecked(self._settings.value("retime_loop_enabled", False, type=bool))
        self.retime_loop_button.toggled.connect(self._on_retime_loop_toggled)
        self._configure_icon_button(
            self.retime_loop_button,
            QStyle.StandardPixmap.SP_BrowserReload,
            "Boucler la preview retimee",
            qtawesome_name="fa5s.redo-alt",
        )

        self.retime_info_label = QLabel(
            "Analyse un break avec au moins deux transients pour entendre une relecture des segments a un autre BPM, "
            "avec tete de lecture synchronisee sur la waveform."
        )
        self.retime_info_label.setObjectName("StatusLabel")
        self.retime_info_label.setWordWrap(True)
        self._reserve_label_height(self.retime_info_label, lines=2)
        self.retime_loading_bar = self._build_loading_bar()
        self.retime_pattern_preview = RetimePreviewPatternWidget(self.retime_box)
        self.retime_pattern_preview.clear_preview(
            "Le preview pattern montrera ici les placements source et relus. "
            "Passe en quantize pour voir ce que la grille recale."
        )

        grid.addWidget(QLabel("BPM detecte"), 0, 0)
        grid.addWidget(self.detected_bpm_value, 0, 1)
        grid.addWidget(QLabel("Facteur"), 0, 2)
        grid.addWidget(self.detected_bpm_factor_combo, 0, 3)
        grid.addWidget(QLabel("BPM cible"), 0, 4)
        grid.addWidget(self.target_bpm_spin, 0, 5)
        grid.addWidget(QLabel("Mode"), 0, 6)
        grid.addWidget(self.preview_mode_combo, 0, 7)
        grid.addWidget(self.retime_play_button, 0, 8)
        grid.addWidget(self.retime_stop_button, 0, 9)
        grid.addWidget(self.retime_loop_button, 0, 10)
        grid.addWidget(QLabel("Grid"), 1, 0)
        grid.addWidget(self.quantize_grid_combo, 1, 1)
        grid.addWidget(QLabel("Strength"), 1, 2)
        grid.addWidget(self.quantize_strength_slider, 1, 3, 1, 2)
        grid.addWidget(self.quantize_strength_value, 1, 5)
        grid.addWidget(self.retime_info_label, 2, 0, 1, 11)
        grid.addWidget(self.retime_loading_bar, 3, 0, 1, 11)
        grid.addWidget(self.retime_pattern_preview, 4, 0, 1, 11)

        self._sync_quantize_controls_state()

    def _build_generator_controls(self, layout: QVBoxLayout) -> None:
        self.generator_box = QGroupBox("Random break generator")
        grid = QGridLayout(self.generator_box)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.generator_detected_bpm_value = QLabel("-")
        self.generator_target_bpm_spin = QDoubleSpinBox()
        self.generator_target_bpm_spin.setRange(30.0, 400.0)
        self.generator_target_bpm_spin.setDecimals(1)
        self.generator_target_bpm_spin.setSingleStep(1.0)
        self.generator_target_bpm_spin.setValue(
            float(self._settings.value("generator_target_bpm", 120.0, type=float))
        )
        self.generator_target_bpm_spin.valueChanged.connect(self._on_generator_target_bpm_changed)
        self.generator_bars_spin = QSpinBox()
        self.generator_bars_spin.setRange(1, 4)
        self.generator_bars_spin.setValue(int(self._settings.value("generator_bars", 1, type=int)))
        self.generator_bars_spin.valueChanged.connect(self._on_generator_bars_changed)
        self.generator_mode_combo = QComboBox()
        self.generator_mode_combo.addItem("Classic", GENERATOR_MODE_CLASSIC)
        self.generator_mode_combo.addItem("Hybrid", GENERATOR_MODE_HYBRID)
        saved_generator_mode = str(
            self._settings.value("generator_mode", GENERATOR_MODE_CLASSIC, type=str) or GENERATOR_MODE_CLASSIC
        ).strip().lower()
        saved_mode_index = self.generator_mode_combo.findData(saved_generator_mode)
        self.generator_mode_combo.setCurrentIndex(saved_mode_index if saved_mode_index >= 0 else 0)
        self.generator_mode_combo.currentIndexChanged.connect(self._on_generator_mode_changed)
        self.generator_profile_combo = QComboBox()
        for profile_key, profile_label in GENERATION_PROFILE_LABELS.items():
            self.generator_profile_combo.addItem(profile_label, profile_key)
        saved_profile = str(
            self._settings.value("generator_profile", GENERATION_PROFILE_MUSICAL, type=str)
            or GENERATION_PROFILE_MUSICAL
        ).strip().lower()
        saved_profile_index = self.generator_profile_combo.findData(saved_profile)
        self.generator_profile_combo.setCurrentIndex(saved_profile_index if saved_profile_index >= 0 else 0)
        self.generator_profile_combo.currentIndexChanged.connect(self._on_generator_profile_changed)
        self.generator_view_mode_combo = QComboBox()
        for mode_key, mode_label in GENERATOR_VIEW_MODE_LABELS.items():
            self.generator_view_mode_combo.addItem(mode_label, mode_key)
        saved_view_mode = str(
            self._settings.value("generator_view_mode", GENERATOR_VIEW_MODE_ADVANCED, type=str)
            or GENERATOR_VIEW_MODE_ADVANCED
        ).strip().lower()
        saved_view_mode_index = self.generator_view_mode_combo.findData(saved_view_mode)
        self.generator_view_mode_combo.setCurrentIndex(saved_view_mode_index if saved_view_mode_index >= 0 else 0)
        self.generator_view_mode_combo.setMinimumWidth(108)
        self.generator_view_mode_combo.currentIndexChanged.connect(self._on_generator_view_mode_changed)
        self.generator_display_preset_combo = QComboBox()
        for preset_key, preset_label in GENERATOR_DISPLAY_PRESET_LABELS.items():
            self.generator_display_preset_combo.addItem(preset_label, preset_key)
        saved_display_preset = str(
            self._settings.value("generator_display_preset", GENERATOR_DISPLAY_PRESET_BALANCED, type=str)
            or GENERATOR_DISPLAY_PRESET_BALANCED
        ).strip().lower()
        saved_display_preset_index = self.generator_display_preset_combo.findData(saved_display_preset)
        self.generator_display_preset_combo.setCurrentIndex(
            saved_display_preset_index if saved_display_preset_index >= 0 else 0
        )
        self.generator_display_preset_combo.setMinimumWidth(124)
        self.generator_display_preset_combo.currentIndexChanged.connect(self._on_generator_display_preset_changed)
        self.generator_seed_value = QLabel("auto")
        self.generator_seed_value.setObjectName("StatusLabel")
        self.generator_seed_value.setMinimumWidth(96)
        self.generator_clear_anchors_button = QPushButton("Clear anchors")
        self.generator_clear_locks_button = QPushButton("Clear locks")
        self.generator_clear_anchors_button.clicked.connect(self._clear_generator_anchors)
        self.generator_clear_locks_button.clicked.connect(self._clear_generator_locks)
        self.generator_generate_button = QPushButton("Generate random")
        self.generator_generate_button.clicked.connect(self._generate_break_pattern)
        self._set_button_icon(
            self.generator_generate_button,
            QStyle.StandardPixmap.SP_BrowserReload,
            qtawesome_name="fa5s.random",
        )
        self.generator_generate_button.setToolTip(
            "Generer un nouveau pattern aleatoire avec les parametres courants"
        )
        self.generator_randomize_params_button = QPushButton("Randomize params")
        self.generator_randomize_params_button.clicked.connect(self._randomize_generator_params)
        self._set_button_icon(
            self.generator_randomize_params_button,
            QStyle.StandardPixmap.SP_BrowserReload,
            qtawesome_name="fa5s.dice",
        )
        self.generator_randomize_params_button.setToolTip(
            "Randomiser les reglages creatifs du generateur sans toucher au BPM, aux bars, aux anchors ni aux locks."
        )
        self.generator_play_button = QPushButton("Play generated")
        self.generator_play_button.clicked.connect(self._play_generated_pattern)
        self.generator_play_button.setEnabled(False)
        self._configure_icon_button(
            self.generator_play_button,
            QStyle.StandardPixmap.SP_MediaPlay,
            "Jouer le pattern genere courant",
            qtawesome_name="fa5s.play",
        )
        self.generator_stop_button = QPushButton("Stop generated")
        self.generator_stop_button.clicked.connect(self._stop_generated_pattern)
        self.generator_stop_button.setEnabled(False)
        self._configure_icon_button(
            self.generator_stop_button,
            QStyle.StandardPixmap.SP_MediaStop,
            "Arreter la lecture du pattern genere",
            qtawesome_name="fa5s.stop",
        )
        self.generator_loop_button = QPushButton("Loop generated")
        self.generator_loop_button.setObjectName("ToggleButton")
        self.generator_loop_button.setCheckable(True)
        self.generator_loop_button.setChecked(self._settings.value("generator_loop_enabled", False, type=bool))
        self.generator_loop_button.toggled.connect(self._on_generator_loop_toggled)
        self._configure_icon_button(
            self.generator_loop_button,
            QStyle.StandardPixmap.SP_BrowserReload,
            "Boucler la lecture du pattern genere",
            qtawesome_name="fa5s.redo-alt",
        )
        self.generator_live_mode_button = QPushButton("Live mode")
        self.generator_live_mode_button.setObjectName("ToggleButton")
        self.generator_live_mode_button.setCheckable(True)
        self.generator_live_mode_button.setChecked(self._live_mode_enabled)
        self.generator_live_mode_button.toggled.connect(self._on_live_mode_toggled)
        self._configure_icon_button(
            self.generator_live_mode_button,
            QStyle.StandardPixmap.SP_MediaSeekForward,
            "Afficher le mode live A/B avec stems separes et FX callback",
            qtawesome_name="fa5s.broadcast-tower",
        )
        self.generator_save_snapshot_button = QToolButton(self.generator_box)
        self.generator_save_snapshot_button.setText("★")
        self.generator_save_snapshot_button.setToolTip(
            "Sauvegarder ce break genere pour le retrouver plus tard dans l'onglet Saved."
        )
        self.generator_save_snapshot_button.clicked.connect(self._save_generated_pattern_snapshot)
        self.generator_save_snapshot_button.setAutoRaise(True)
        self.generator_save_snapshot_button.setMinimumWidth(30)
        self.generator_render_wav_button = QPushButton("Render WAV")
        self.generator_render_wav_button.clicked.connect(self._render_generated_pattern_to_wav)
        self._configure_icon_button(
            self.generator_render_wav_button,
            QStyle.StandardPixmap.SP_DialogSaveButton,
            "Exporter le break genere courant en WAV sur une seule loop exacte.",
            qtawesome_name="fa5s.file-audio",
        )

        self.generator_energy_slider, self.generator_energy_value = self._build_percent_slider(
            int(self._settings.value("generator_energy", 55, type=int))
        )
        self.generator_energy_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_energy", int(value))
        )
        self.generator_kick_slider, self.generator_kick_value = self._build_percent_slider(
            int(self._settings.value("generator_kick_weight", 60, type=int))
        )
        self.generator_kick_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_kick_weight", int(value))
        )
        self.generator_snare_slider, self.generator_snare_value = self._build_percent_slider(
            int(self._settings.value("generator_snare_weight", 70, type=int))
        )
        self.generator_snare_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_snare_weight", int(value))
        )
        self.generator_hat_slider, self.generator_hat_value = self._build_percent_slider(
            int(self._settings.value("generator_hat_density", 60, type=int))
        )
        self.generator_hat_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_hat_density", int(value))
        )
        self.generator_ghost_slider, self.generator_ghost_value = self._build_percent_slider(
            int(self._settings.value("generator_ghost_density", 25, type=int))
        )
        self.generator_ghost_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_ghost_density", int(value))
        )
        self.generator_ghost_slider.valueChanged.connect(self._refresh_generator_ghost_ui)
        self.generator_synth_ghost_enabled_check = QCheckBox("Synth fallback")
        self.generator_synth_ghost_enabled_check.setChecked(
            self._settings.value("generator_synth_ghost_enabled", True, type=bool)
        )
        self.generator_synth_ghost_enabled_check.toggled.connect(
            lambda checked: self._settings.setValue("generator_synth_ghost_enabled", bool(checked))
        )
        self.generator_synth_ghost_enabled_check.toggled.connect(self._refresh_generator_ghost_ui)

        self.generator_ghost_vel_min_slider, self.generator_ghost_vel_min_value = self._build_scaled_slider(
            int(self._settings.value("generator_ghost_vel_min", 20, type=int)),
            minimum=0,
            maximum=60,
            scale=100.0,
            decimals=2,
        )
        self.generator_ghost_vel_min_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_ghost_vel_min", int(value))
        )
        self.generator_ghost_vel_max_slider, self.generator_ghost_vel_max_value = self._build_scaled_slider(
            int(self._settings.value("generator_ghost_vel_max", 45, type=int)),
            minimum=0,
            maximum=60,
            scale=100.0,
            decimals=2,
        )
        self.generator_ghost_vel_max_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_ghost_vel_max", int(value))
        )
        self.generator_ghost_pitch_min_slider, self.generator_ghost_pitch_min_value = self._build_scaled_slider(
            int(self._settings.value("generator_ghost_pitch_min", 0, type=int)),
            minimum=-20,
            maximum=20,
            scale=10.0,
            decimals=1,
            suffix=" st",
            signed=True,
        )
        self.generator_ghost_pitch_min_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_ghost_pitch_min", int(value))
        )
        self.generator_ghost_pitch_max_slider, self.generator_ghost_pitch_max_value = self._build_scaled_slider(
            int(self._settings.value("generator_ghost_pitch_max", 0, type=int)),
            minimum=-20,
            maximum=20,
            scale=10.0,
            decimals=1,
            suffix=" st",
            signed=True,
        )
        self.generator_ghost_pitch_max_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_ghost_pitch_max", int(value))
        )
        self.generator_ghost_gate_slider, self.generator_ghost_gate_value = self._build_scaled_slider(
            int(self._settings.value("generator_ghost_gate", 0, type=int)),
            minimum=0,
            maximum=100,
            scale=100.0,
            decimals=2,
        )
        self.generator_ghost_gate_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_ghost_gate", int(value))
        )
        self.generator_fill_slider, self.generator_fill_value = self._build_percent_slider(
            int(self._settings.value("generator_fill_strength", 35, type=int))
        )
        self.generator_fill_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_fill_strength", int(value))
        )
        self.generator_fill_style_combo = QComboBox()
        for fill_style in FILL_STYLE_OPTIONS:
            self.generator_fill_style_combo.addItem(FILL_STYLE_LABELS.get(fill_style, str(fill_style).title()), fill_style)
        saved_fill_style = str(
            self._settings.value("generator_fill_style", FILL_STYLE_AUTO, type=str) or FILL_STYLE_AUTO
        ).strip().lower()
        fill_style_index = self.generator_fill_style_combo.findData(saved_fill_style)
        self.generator_fill_style_combo.setCurrentIndex(fill_style_index if fill_style_index >= 0 else 0)
        self.generator_fill_style_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue(
                "generator_fill_style",
                str(self.generator_fill_style_combo.currentData() or FILL_STYLE_AUTO),
            )
        )
        self.generator_fill_style_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)
        self.generator_fill_style_combo.currentIndexChanged.connect(self._refresh_generator_fill_style_label)
        self.generator_fill_current_label = QLabel("Auto")
        self.generator_fill_current_label.setObjectName("StatusLabel")
        self.generator_repeat_slider, self.generator_repeat_value = self._build_percent_slider(
            int(self._settings.value("generator_repeat_density", 0, type=int))
        )
        self.generator_repeat_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_repeat_density", int(value))
        )
        self.generator_repeat_length_slider, self.generator_repeat_length_value = self._build_percent_slider(
            int(self._settings.value("generator_repeat_span", 15, type=int))
        )
        self.generator_repeat_length_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_repeat_span", int(value))
        )
        self.generator_repeat_rate_slider, self.generator_repeat_rate_value = self._build_percent_slider(
            int(self._settings.value("generator_repeat_rate", 35, type=int))
        )
        self.generator_repeat_rate_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_repeat_rate", int(value))
        )
        self.generator_reverse_slider, self.generator_reverse_value = self._build_percent_slider(
            int(self._settings.value("generator_reverse_density", 0, type=int))
        )
        self.generator_reverse_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_reverse_density", int(value))
        )
        self.generator_kick_roll_slider, self.generator_kick_roll_value = self._build_percent_slider(
            int(self._settings.value("generator_kick_roll_density", 0, type=int))
        )
        self.generator_kick_roll_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_kick_roll_density", int(value))
        )
        self.generator_kick_roll_length_slider, self.generator_kick_roll_length_value = self._build_percent_slider(
            int(self._settings.value("generator_kick_roll_span", 20, type=int))
        )
        self.generator_kick_roll_length_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_kick_roll_span", int(value))
        )
        self.generator_kick_roll_contrast_slider, self.generator_kick_roll_contrast_value = self._build_percent_slider(
            int(self._settings.value("generator_kick_roll_contrast", 55, type=int))
        )
        self.generator_kick_roll_contrast_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_kick_roll_contrast", int(value))
        )
        self.generator_snare_stretch_slider, self.generator_snare_stretch_value = self._build_percent_slider(
            int(self._settings.value("generator_snare_stretch_density", 0, type=int))
        )
        self.generator_snare_stretch_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_snare_stretch_density", int(value))
        )
        self.generator_snare_stretch_length_slider, self.generator_snare_stretch_length_value = self._build_percent_slider(
            int(self._settings.value("generator_snare_stretch_span", 35, type=int))
        )
        self.generator_snare_stretch_length_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_snare_stretch_span", int(value))
        )
        self.generator_snare_stretch_amount_slider, self.generator_snare_stretch_amount_value = self._build_percent_slider(
            int(self._settings.value("generator_snare_stretch_amount", 80, type=int))
        )
        self.generator_snare_stretch_amount_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_snare_stretch_amount", int(value))
        )
        self.generator_snare_stretch_curve_combo = QComboBox()
        for option in SNARE_STRETCH_VEL_CURVE_OPTIONS:
            self.generator_snare_stretch_curve_combo.addItem(option.replace("_", " ").capitalize(), option)
        saved_stretch_curve = str(
            self._settings.value("generator_snare_stretch_vel_curve", "decay", type=str) or "decay"
        ).strip().lower()
        stretch_curve_index = self.generator_snare_stretch_curve_combo.findData(saved_stretch_curve)
        self.generator_snare_stretch_curve_combo.setCurrentIndex(stretch_curve_index if stretch_curve_index >= 0 else 1)
        self.generator_snare_stretch_curve_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue(
                "generator_snare_stretch_vel_curve",
                str(self.generator_snare_stretch_curve_combo.currentData() or "decay"),
            )
        )
        self.generator_gate_slider, self.generator_gate_value = self._build_percent_slider(
            int(self._settings.value("generator_gate", 100, type=int))
        )
        self.generator_gate_slider.valueChanged.connect(self._on_generator_gate_changed)
        self.generator_mono_choke_check = QCheckBox("Mono choke")
        self.generator_mono_choke_check.setChecked(
            bool(self._settings.value("generator_mono_choke", False, type=bool))
        )
        self.generator_mono_choke_check.toggled.connect(self._on_generator_mono_choke_toggled)
        self.generator_position_fidelity_slider, self.generator_position_fidelity_value = self._build_percent_slider(
            int(self._settings.value("generator_position_fidelity", 0, type=int))
        )
        self.generator_position_fidelity_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_position_fidelity", int(value))
        )
        self.generator_sequence_density_slider, self.generator_sequence_density_value = self._build_percent_slider(
            int(self._settings.value("generator_sequence_density", 0, type=int))
        )
        self.generator_sequence_density_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_sequence_density", int(value))
        )
        self.generator_motif_density_slider, self.generator_motif_density_value = self._build_percent_slider(
            int(self._settings.value("generator_motif_density", 0, type=int))
        )
        self.generator_motif_density_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_motif_density", int(value))
        )
        self.generator_velocity_slider, self.generator_velocity_value = self._build_percent_slider(
            int(self._settings.value("generator_velocity_spread", 50, type=int))
        )
        self.generator_velocity_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_velocity_spread", int(value))
        )
        self.generator_swing_slider, self.generator_swing_value = self._build_percent_slider(
            int(self._settings.value("generator_swing", 0, type=int))
        )
        self.generator_swing_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_swing", int(value))
        )
        self.generator_anti_repeat_slider, self.generator_anti_repeat_value = self._build_percent_slider(
            int(self._settings.value("generator_anti_repeat", 60, type=int))
        )
        self.generator_anti_repeat_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_anti_repeat", int(value))
        )
        self.generator_breath_slider, self.generator_breath_value = self._build_percent_slider(
            int(self._settings.value("generator_breath_factor", 35, type=int))
        )
        self.generator_breath_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_breath_factor", int(value))
        )
        self.generator_sequence_max_len_spin = QSpinBox()
        self.generator_sequence_max_len_spin.setRange(2, MAX_SEQUENCE_HIT_COUNT)
        self.generator_sequence_max_len_spin.setValue(
            int(self._settings.value("generator_sequence_max_len", 4, type=int))
        )
        self.generator_sequence_max_len_spin.valueChanged.connect(
            lambda value: self._settings.setValue("generator_sequence_max_len", int(value))
        )
        self.generator_sequence_role_lock_check = QCheckBox("Role lock")
        self.generator_sequence_role_lock_check.setChecked(
            self._settings.value("generator_sequence_role_lock", True, type=bool)
        )
        self.generator_sequence_role_lock_check.toggled.connect(
            lambda checked: self._settings.setValue("generator_sequence_role_lock", bool(checked))
        )
        self.generator_pitch_mode_combo = QComboBox()
        for option in PITCH_MODE_OPTIONS:
            self.generator_pitch_mode_combo.addItem(option.replace("_", " ").title(), option)
        saved_pitch_mode = str(self._settings.value("generator_pitch_mode", "off", type=str) or "off").strip().lower()
        pitch_mode_index = self.generator_pitch_mode_combo.findData(saved_pitch_mode)
        self.generator_pitch_mode_combo.setCurrentIndex(pitch_mode_index if pitch_mode_index >= 0 else 0)
        self.generator_pitch_mode_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue("generator_pitch_mode", str(self.generator_pitch_mode_combo.currentData() or "off"))
        )
        self.generator_pitch_mode_combo.currentIndexChanged.connect(self._refresh_generator_pitch_ui)
        self.generator_pitch_mode_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_scope_combo = QComboBox()
        for option in PITCH_SCOPE_OPTIONS:
            self.generator_pitch_scope_combo.addItem(option.replace("_", " ").capitalize(), option)
        saved_pitch_scope = str(self._settings.value("generator_pitch_scope", "snare", type=str) or "snare").strip().lower()
        pitch_scope_index = self.generator_pitch_scope_combo.findData(saved_pitch_scope)
        self.generator_pitch_scope_combo.setCurrentIndex(pitch_scope_index if pitch_scope_index >= 0 else 0)
        self.generator_pitch_scope_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue("generator_pitch_scope", str(self.generator_pitch_scope_combo.currentData() or "snare"))
        )
        self.generator_pitch_scope_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_scale_combo = QComboBox()
        for option in PITCH_SCALE_OPTIONS:
            self.generator_pitch_scale_combo.addItem(option.capitalize(), option)
        saved_pitch_scale = str(self._settings.value("generator_pitch_scale", "chromatic", type=str) or "chromatic").strip().lower()
        pitch_scale_index = self.generator_pitch_scale_combo.findData(saved_pitch_scale)
        self.generator_pitch_scale_combo.setCurrentIndex(pitch_scale_index if pitch_scale_index >= 0 else 0)
        self.generator_pitch_scale_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue("generator_pitch_scale", str(self.generator_pitch_scale_combo.currentData() or "chromatic"))
        )
        self.generator_pitch_scale_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_root_slider = QSlider(Qt.Orientation.Horizontal)
        self.generator_pitch_root_slider.setRange(0, 11)
        self.generator_pitch_root_slider.setSingleStep(1)
        self.generator_pitch_root_slider.setPageStep(1)
        self.generator_pitch_root_slider.setFixedWidth(168)
        self.generator_pitch_root_slider.setValue(int(np.clip(self._settings.value("generator_pitch_root", 0, type=int), 0, 11)))
        self.generator_pitch_root_value = QLabel(self._pitch_root_note_name(self.generator_pitch_root_slider.value()))
        self.generator_pitch_root_value.setMinimumWidth(34)
        self.generator_pitch_root_slider.valueChanged.connect(
            lambda value: self.generator_pitch_root_value.setText(self._pitch_root_note_name(int(value)))
        )
        self.generator_pitch_root_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_pitch_root", int(value))
        )
        self.generator_pitch_root_slider.valueChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_amount_slider, self.generator_pitch_amount_value = self._build_percent_slider(
            int(self._settings.value("generator_pitch_amount", 100, type=int))
        )
        self.generator_pitch_amount_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_pitch_amount", int(value))
        )

        self.generator_pitch_range_min_slider, self.generator_pitch_range_min_value = self._build_signed_slider(
            int(self._settings.value("generator_pitch_range_min", -12, type=int))
        )
        self.generator_pitch_range_min_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_pitch_range_min", int(value))
        )
        self.generator_pitch_range_max_slider, self.generator_pitch_range_max_value = self._build_signed_slider(
            int(self._settings.value("generator_pitch_range_max", 12, type=int))
        )
        self.generator_pitch_range_max_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_pitch_range_max", int(value))
        )

        self.generator_pitch_rate_combo = QComboBox()
        for option in PITCH_RATE_OPTIONS:
            self.generator_pitch_rate_combo.addItem(option.replace("_", " ").capitalize(), option)
        saved_pitch_rate = str(self._settings.value("generator_pitch_rate", "every_hit", type=str) or "every_hit").strip().lower()
        pitch_rate_index = self.generator_pitch_rate_combo.findData(saved_pitch_rate)
        self.generator_pitch_rate_combo.setCurrentIndex(pitch_rate_index if pitch_rate_index >= 0 else 0)
        self.generator_pitch_rate_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue("generator_pitch_rate", str(self.generator_pitch_rate_combo.currentData() or "every_hit"))
        )
        self.generator_pitch_rate_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_sequence_input = QLineEdit()
        self.generator_pitch_sequence_input.setPlaceholderText("0, 3, -2, 7")
        self.generator_pitch_sequence_input.setText(
            str(self._settings.value("generator_pitch_sequence", "0, 3, -2, 7", type=str) or "0, 3, -2, 7")
        )
        self.generator_pitch_sequence_input.textChanged.connect(
            lambda text: self._settings.setValue("generator_pitch_sequence", str(text))
        )
        self.generator_pitch_sequence_input.textChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_curve_combo = QComboBox()
        for option in PITCH_CURVE_OPTIONS:
            self.generator_pitch_curve_combo.addItem(option.replace("_", " ").capitalize(), option)
        saved_pitch_curve = str(self._settings.value("generator_pitch_curve", "up", type=str) or "up").strip().lower()
        pitch_curve_index = self.generator_pitch_curve_combo.findData(saved_pitch_curve)
        self.generator_pitch_curve_combo.setCurrentIndex(pitch_curve_index if pitch_curve_index >= 0 else 0)
        self.generator_pitch_curve_combo.currentIndexChanged.connect(
            lambda: self._settings.setValue("generator_pitch_curve", str(self.generator_pitch_curve_combo.currentData() or "up"))
        )
        self.generator_pitch_curve_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)

        self.generator_pitch_curve_min_slider, self.generator_pitch_curve_min_value = self._build_signed_slider(
            int(self._settings.value("generator_pitch_curve_min", -7, type=int))
        )
        self.generator_pitch_curve_min_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_pitch_curve_min", int(value))
        )
        self.generator_pitch_curve_max_slider, self.generator_pitch_curve_max_value = self._build_signed_slider(
            int(self._settings.value("generator_pitch_curve_max", 7, type=int))
        )
        self.generator_pitch_curve_max_slider.valueChanged.connect(
            lambda value: self._settings.setValue("generator_pitch_curve_max", int(value))
        )

        for slider in (
            self.generator_energy_slider,
            self.generator_kick_slider,
            self.generator_snare_slider,
            self.generator_hat_slider,
            self.generator_ghost_slider,
            self.generator_fill_slider,
            self.generator_sequence_density_slider,
            self.generator_repeat_slider,
            self.generator_repeat_length_slider,
            self.generator_repeat_rate_slider,
            self.generator_reverse_slider,
            self.generator_kick_roll_slider,
            self.generator_kick_roll_length_slider,
            self.generator_kick_roll_contrast_slider,
            self.generator_snare_stretch_slider,
            self.generator_snare_stretch_length_slider,
            self.generator_snare_stretch_amount_slider,
            self.generator_gate_slider,
            self.generator_velocity_slider,
            self.generator_swing_slider,
            self.generator_anti_repeat_slider,
            self.generator_breath_slider,
            self.generator_position_fidelity_slider,
            self.generator_motif_density_slider,
            self.generator_pitch_amount_slider,
            self.generator_pitch_root_slider,
            self.generator_pitch_range_min_slider,
            self.generator_pitch_range_max_slider,
            self.generator_pitch_curve_min_slider,
            self.generator_pitch_curve_max_slider,
        ):
            slider.valueChanged.connect(self._refresh_generator_probability_preview)
            slider.sliderPressed.connect(self._on_generator_param_slider_pressed)
            slider.sliderReleased.connect(self._on_generator_param_slider_released)
        self.generator_snare_stretch_curve_combo.currentIndexChanged.connect(self._refresh_generator_probability_preview)

        self.generator_motif_name_input = QLineEdit()
        self.generator_motif_name_input.setPlaceholderText("Nom du motif")
        self.generator_motif_length_spin = QSpinBox()
        self.generator_motif_length_spin.setRange(2, 8)
        self.generator_motif_length_spin.setValue(4)
        self.generator_motif_length_spin.valueChanged.connect(self._on_generator_motif_length_changed)
        self.generator_motif_base_prob_slider, self.generator_motif_base_prob_value = self._build_percent_slider(60)
        self.generator_motif_base_prob_slider.valueChanged.connect(self._refresh_generator_user_motif_table)
        self.generator_motif_base_prob_slider.valueChanged.connect(self._refresh_generator_motif_editor_effective_label)
        self.generator_motif_role_combo = QComboBox()
        for role in USER_MOTIF_ROLE_OPTIONS:
            self.generator_motif_role_combo.addItem(role.capitalize(), role)
        self.generator_motif_role_combo.currentIndexChanged.connect(self._refresh_generator_user_motif_table)
        self.generator_motif_role_combo.currentIndexChanged.connect(self._refresh_generator_motif_editor_effective_label)
        self.generator_motif_dominant_combo = QComboBox()
        for dominant_type in USER_MOTIF_DOMINANT_TYPE_OPTIONS:
            label = "Mixed" if dominant_type == "mixed" else dominant_type.capitalize()
            self.generator_motif_dominant_combo.addItem(label, dominant_type)
        self.generator_motif_dominant_combo.currentIndexChanged.connect(self._on_generator_motif_dominant_changed)
        self.generator_motif_inferred_label = QLabel("Infer: mixed")
        self.generator_motif_inferred_label.setObjectName("StatusLabel")
        self.generator_motif_effective_label = QLabel("Eff.: 0%")
        self.generator_motif_effective_label.setObjectName("StatusLabel")
        self.generator_motif_save_button = QPushButton("Save")
        self.generator_motif_save_button.clicked.connect(self._save_generator_user_motif)
        self._set_button_icon(
            self.generator_motif_save_button,
            QStyle.StandardPixmap.SP_DialogSaveButton,
            qtawesome_name="fa5s.save",
        )
        self.generator_motif_editor_buttons = []
        self.generator_motif_editor_box = QGroupBox("Add sequence")
        motif_editor_layout = QGridLayout(self.generator_motif_editor_box)
        motif_editor_layout.setHorizontalSpacing(8)
        motif_editor_layout.setVerticalSpacing(6)
        motif_editor_layout.addWidget(QLabel("Pattern"), 0, 0)
        motif_steps_row = QHBoxLayout()
        motif_steps_row.setSpacing(6)
        for step_index in range(8):
            button = QPushButton("·")
            button.setObjectName("AnchorButton")
            button.setFixedWidth(40)
            button.clicked.connect(
                lambda _checked=False, current_step=int(step_index): self._on_generator_motif_editor_step_clicked(current_step)
            )
            self.generator_motif_editor_buttons.append(button)
            motif_steps_row.addWidget(button)
        motif_editor_layout.addLayout(motif_steps_row, 0, 1, 1, 5)
        motif_editor_layout.addWidget(QLabel("Len"), 1, 0)
        motif_editor_layout.addWidget(self.generator_motif_length_spin, 1, 1)
        motif_editor_layout.addWidget(QLabel("Name"), 1, 2)
        motif_editor_layout.addWidget(self.generator_motif_name_input, 1, 3, 1, 3)
        motif_editor_layout.addWidget(QLabel("Base prob"), 2, 0)
        motif_editor_layout.addWidget(self.generator_motif_base_prob_slider, 2, 1, 1, 2)
        motif_editor_layout.addWidget(self.generator_motif_base_prob_value, 2, 3)
        motif_editor_layout.addWidget(QLabel("Role"), 2, 4)
        motif_editor_layout.addWidget(self.generator_motif_role_combo, 2, 5)
        motif_editor_layout.addWidget(QLabel("Dominant"), 3, 0)
        motif_editor_layout.addWidget(self.generator_motif_dominant_combo, 3, 1)
        motif_editor_layout.addWidget(self.generator_motif_inferred_label, 3, 2)
        motif_editor_layout.addWidget(self.generator_motif_effective_label, 3, 3)
        motif_editor_layout.addWidget(self.generator_motif_save_button, 3, 5)

        self.generator_saved_motifs_box = QGroupBox("User motifs")
        motif_list_layout = QVBoxLayout(self.generator_saved_motifs_box)
        self.generator_saved_motifs_label = QLabel("Aucun motif utilisateur sauvegarde pour ce projet.")
        self.generator_saved_motifs_label.setObjectName("StatusLabel")
        self.generator_saved_motifs_label.setWordWrap(True)
        self.generator_saved_motifs_table = QTableWidget(0, 7)
        self.generator_saved_motifs_table.setHorizontalHeaderLabels(("Name", "Steps", "Role", "Type", "Base", "Eff.", "Delete"))
        self.generator_saved_motifs_table.verticalHeader().setVisible(False)
        self.generator_saved_motifs_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.generator_saved_motifs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.generator_saved_motifs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generator_saved_motifs_table.setAlternatingRowColors(True)
        self.generator_saved_motifs_table.setMinimumHeight(170)
        motif_header = self.generator_saved_motifs_table.horizontalHeader()
        motif_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        motif_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        motif_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 5, 6):
            motif_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        motif_list_layout.addWidget(self.generator_saved_motifs_label)
        motif_list_layout.addWidget(self.generator_saved_motifs_table)

        self.generator_info_label = QLabel(self._default_generator_info_text())
        self.generator_info_label.setObjectName("StatusLabel")
        self.generator_info_label.setWordWrap(True)
        self._reserve_label_height(self.generator_info_label, lines=2)
        self.generator_loading_bar = self._build_loading_bar()
        self.generator_probability_label = QLabel(
            "Base placement preview. Cette table montre les probabilites du squelette avant fills, sequences, kick rolls, retriggers repeat, reverse et contexte local."
        )
        self.generator_probability_label.setObjectName("StatusLabel")
        self.generator_probability_label.setWordWrap(True)
        self._reserve_label_height(self.generator_probability_label, lines=2)
        self.generator_summary_label = QLabel("Aucun pattern genere pour le moment.")
        self.generator_summary_label.setObjectName("StatusLabel")
        self.generator_summary_label.setWordWrap(True)
        self._reserve_label_height(self.generator_summary_label, lines=2)
        self.generator_probability_table = QTableWidget(4, 6)
        self.generator_probability_table.setHorizontalHeaderLabels(("Kick", "Snare", "Hat", "Ghost", "Other", "Sil"))
        self.generator_probability_table.setVerticalHeaderLabels(("Downbeat", "Backbeat", "Offbeat", "Subdivision"))
        self.generator_probability_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.generator_probability_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.generator_probability_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generator_probability_table.setAlternatingRowColors(False)
        self.generator_probability_table.setWordWrap(False)
        self.generator_probability_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.generator_probability_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.generator_probability_table.setMinimumHeight(152)
        probability_header = self.generator_probability_table.horizontalHeader()
        probability_header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        for column in range(6):
            probability_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        probability_vertical_header = self.generator_probability_table.verticalHeader()
        probability_vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        probability_vertical_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.generator_effect_probability_label = QLabel("Apercu FX")
        self.generator_effect_probability_label.setObjectName("StatusLabel")
        self.generator_effect_probability_table = QTableWidget(4, 5)
        self.generator_effect_probability_table.setHorizontalHeaderLabels(("Repeat", "Reverse", "K.Roll", "Snr.Str", "Pitch"))
        self.generator_effect_probability_table.setVerticalHeaderLabels(("Downbeat", "Backbeat", "Offbeat", "Subdivision"))
        self.generator_effect_probability_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.generator_effect_probability_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.generator_effect_probability_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generator_effect_probability_table.setAlternatingRowColors(False)
        self.generator_effect_probability_table.setWordWrap(False)
        self.generator_effect_probability_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.generator_effect_probability_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.generator_effect_probability_table.setMinimumHeight(152)
        effect_header = self.generator_effect_probability_table.horizontalHeader()
        effect_header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        for column in range(5):
            effect_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        effect_vertical_header = self.generator_effect_probability_table.verticalHeader()
        effect_vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        effect_vertical_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.generator_table = QTableWidget(0, 5)
        self.generator_table.setHorizontalHeaderLabels(("Step", "Event", "Vel", "Source", "Tags"))
        self.generator_table.verticalHeader().setVisible(False)
        self.generator_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.generator_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.generator_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.generator_table.setAlternatingRowColors(True)
        self.generator_table.setWordWrap(False)
        self.generator_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.generator_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.generator_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.generator_table.setMinimumHeight(110)
        generator_header = self.generator_table.horizontalHeader()
        generator_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        generator_header.setStretchLastSection(False)
        for column in range(5):
            generator_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        self.generator_sequence_table = QTableWidget(7, 16)
        self.generator_sequence_table.setHorizontalHeaderLabels([str(index) for index in range(1, 17)])
        self.generator_sequence_table.setVerticalHeaderLabels(("Anchor", "Lock", "Event", "Vel", "Source", "FX", "Reroll"))
        self.generator_sequence_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectColumns)
        self.generator_sequence_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.generator_sequence_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.generator_sequence_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.generator_sequence_table.setAlternatingRowColors(False)
        self.generator_sequence_table.setWordWrap(True)
        self.generator_sequence_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.generator_sequence_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.generator_sequence_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.generator_sequence_table.setMinimumHeight(392)
        self.generator_sequence_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.generator_sequence_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.generator_sequence_table.cellClicked.connect(self._on_generator_sequence_cell_clicked)
        sequence_header = self.generator_sequence_table.horizontalHeader()
        sequence_header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        sequence_header.sectionClicked.connect(self._on_generator_sequence_header_clicked)
        for column in range(16):
            sequence_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        sequence_vertical_header = self.generator_sequence_table.verticalHeader()
        sequence_vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        sequence_vertical_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        generator_source_bpm_label = QLabel("BPM source")
        generator_target_bpm_label = QLabel("BPM cible")
        generator_bars_label = QLabel("Bars")
        generator_mode_label = QLabel("Mode")
        generator_profile_label = QLabel("Profile")
        generator_view_mode_label = QLabel("View")
        generator_display_preset_label = QLabel("Preset")
        generator_seed_label = QLabel("Derniere seed")
        self._set_generator_widget_tooltip(
            "Tempo estime du break source. C'est la base rythmique qui sert a recaler le pattern genere.",
            generator_source_bpm_label,
        )
        self._set_generator_widget_tooltip(
            "Tempo de lecture du pattern genere. Le pattern garde les slices d'origine mais les declenche selon ce BPM.",
            generator_target_bpm_label,
        )
        self._set_generator_widget_tooltip(
            "Nombre de mesures a generer. 1 bar = 16 steps, 2 bars = 32 steps, etc.",
            generator_bars_label,
        )
        self._set_generator_widget_tooltip(
            "Classic garde le comportement historique. Hybrid pose d'abord des motifs utilisateur comme squelette temporaire, puis laisse le generateur remplir autour.",
            generator_mode_label,
            self.generator_mode_combo,
        )
        self._set_generator_widget_tooltip(
            "Safe limite les collisions entre passes. Musical garde une phrase lisible avec des FX encore vivants. Destructive laisse plus de reecritures et de chaos breakcore.",
            generator_profile_label,
            self.generator_profile_combo,
        )
        self._set_generator_widget_tooltip(
            "Basic garde les controles essentiels du generateur. Advanced reaffiche surtout les panneaux d'inspection, les motifs et les options plus fines.",
            generator_view_mode_label,
            self.generator_view_mode_combo,
        )
        self._set_generator_widget_tooltip(
            "Presets d'affichage pour passer vite d'une vue equilibree a une vue performance ou inspection, sans changer le son.",
            generator_display_preset_label,
            self.generator_display_preset_combo,
        )
        self._set_generator_widget_tooltip(
            "Seed de la derniere variation generee. Elle est informativa seulement: chaque clic sur Generate random en cree une nouvelle.",
            generator_seed_label,
        )

        grid.addWidget(generator_source_bpm_label, 0, 0)
        grid.addWidget(self.generator_detected_bpm_value, 0, 1)
        grid.addWidget(generator_target_bpm_label, 0, 2)
        grid.addWidget(self.generator_target_bpm_spin, 0, 3)
        grid.addWidget(generator_bars_label, 0, 4)
        grid.addWidget(self.generator_bars_spin, 0, 5)
        grid.addWidget(generator_mode_label, 0, 6)
        grid.addWidget(self.generator_mode_combo, 0, 7)
        grid.addWidget(generator_seed_label, 0, 8)
        grid.addWidget(self.generator_seed_value, 0, 9)
        grid.addWidget(self.generator_generate_button, 0, 10)
        grid.addWidget(self.generator_randomize_params_button, 0, 11)
        grid.addWidget(self.generator_play_button, 0, 12)
        grid.addWidget(self.generator_stop_button, 0, 13)
        grid.addWidget(self.generator_loop_button, 0, 14)
        grid.addWidget(self.generator_live_mode_button, 0, 15)
        grid.addWidget(self.generator_save_snapshot_button, 0, 16)
        grid.addWidget(self.generator_render_wav_button, 0, 17)
        grid.addWidget(generator_view_mode_label, 0, 16)
        grid.addWidget(self.generator_view_mode_combo, 0, 17)
        grid.addWidget(generator_display_preset_label, 0, 18)
        grid.addWidget(self.generator_display_preset_combo, 0, 19)
        grid.addWidget(generator_profile_label, 0, 20)
        grid.addWidget(self.generator_profile_combo, 0, 21)

        grid.addWidget(self._build_generator_section_label("Groove Core", tone="core"), 1, 0, 1, 12)
        self._add_generator_slider_row(grid, 2, "Energy", self.generator_energy_slider, self.generator_energy_value, "Kick", self.generator_kick_slider, self.generator_kick_value)
        self._add_generator_slider_row(grid, 3, "Snare", self.generator_snare_slider, self.generator_snare_value, "Hat", self.generator_hat_slider, self.generator_hat_value)
        self._add_generator_slider_row(grid, 4, "Ghost", self.generator_ghost_slider, self.generator_ghost_value, "Breath", self.generator_breath_slider, self.generator_breath_value)

        self.generator_ghost_synthesis_box = QGroupBox("Ghost synthesis")
        ghost_synthesis_layout = QGridLayout(self.generator_ghost_synthesis_box)
        ghost_synthesis_layout.setHorizontalSpacing(8)
        ghost_synthesis_layout.setVerticalSpacing(6)
        ghost_synthesis_layout.addWidget(self.generator_synth_ghost_enabled_check, 0, 0, 1, 4)
        ghost_synthesis_layout.addWidget(QLabel("Vel min"), 1, 0)
        ghost_synthesis_layout.addWidget(self.generator_ghost_vel_min_slider, 1, 1, 1, 2)
        ghost_synthesis_layout.addWidget(self.generator_ghost_vel_min_value, 1, 3)
        ghost_synthesis_layout.addWidget(QLabel("Vel max"), 1, 4)
        ghost_synthesis_layout.addWidget(self.generator_ghost_vel_max_slider, 1, 5, 1, 2)
        ghost_synthesis_layout.addWidget(self.generator_ghost_vel_max_value, 1, 7)
        ghost_synthesis_layout.addWidget(QLabel("Pitch min"), 2, 0)
        ghost_synthesis_layout.addWidget(self.generator_ghost_pitch_min_slider, 2, 1, 1, 2)
        ghost_synthesis_layout.addWidget(self.generator_ghost_pitch_min_value, 2, 3)
        ghost_synthesis_layout.addWidget(QLabel("Pitch max"), 2, 4)
        ghost_synthesis_layout.addWidget(self.generator_ghost_pitch_max_slider, 2, 5, 1, 2)
        ghost_synthesis_layout.addWidget(self.generator_ghost_pitch_max_value, 2, 7)
        ghost_synthesis_layout.addWidget(QLabel("Gate"), 3, 0)
        ghost_synthesis_layout.addWidget(self.generator_ghost_gate_slider, 3, 1, 1, 2)
        ghost_synthesis_layout.addWidget(self.generator_ghost_gate_value, 3, 3)
        grid.addWidget(self.generator_ghost_synthesis_box, 5, 0, 1, 12)

        grid.addWidget(self._build_generator_section_label("Structure & Phrase", tone="structure"), 6, 0, 1, 12)
        self._add_generator_slider_row(grid, 7, "Fill", self.generator_fill_slider, self.generator_fill_value, "Sequences", self.generator_sequence_density_slider, self.generator_sequence_density_value)
        generator_fill_style_label = QLabel("Fill style")
        self._set_generator_widget_tooltip(
            "Auto laisse le generateur choisir un type de fill compatible. Un style explicite force ce type comme point de depart, meme si la zone reste plus courte quand Fill est bas.",
            generator_fill_style_label,
            self.generator_fill_style_combo,
            self.generator_fill_current_label,
        )
        grid.addWidget(generator_fill_style_label, 7, 12)
        grid.addWidget(self.generator_fill_style_combo, 7, 13, 1, 3)
        grid.addWidget(self.generator_fill_current_label, 7, 16, 1, 6)
        self._add_generator_slider_row(grid, 8, "Position", self.generator_position_fidelity_slider, self.generator_position_fidelity_value, "Motifs", self.generator_motif_density_slider, self.generator_motif_density_value)
        grid.addWidget(self._build_generator_section_label("FX & Motion", tone="motion"), 9, 0, 1, 12)
        self._add_generator_slider_row(grid, 10, "Repeat dens.", self.generator_repeat_slider, self.generator_repeat_value, "Repeat len.", self.generator_repeat_length_slider, self.generator_repeat_length_value)
        self._add_generator_slider_row(grid, 11, "Repeat rate", self.generator_repeat_rate_slider, self.generator_repeat_rate_value, "Reverse", self.generator_reverse_slider, self.generator_reverse_value)
        self._add_generator_slider_row(grid, 12, "K.Roll dens.", self.generator_kick_roll_slider, self.generator_kick_roll_value, "K.Roll len.", self.generator_kick_roll_length_slider, self.generator_kick_roll_length_value)
        kick_roll_dyn_label = QLabel("K.Roll dyn.")
        kick_roll_dyn_tooltip = self._generator_parameter_tooltip("K.Roll dyn.")
        self._set_generator_widget_tooltip(
            kick_roll_dyn_tooltip,
            kick_roll_dyn_label,
            self.generator_kick_roll_contrast_slider,
            self.generator_kick_roll_contrast_value,
        )
        grid.addWidget(kick_roll_dyn_label, 13, 0)
        grid.addWidget(self.generator_kick_roll_contrast_slider, 13, 1, 1, 2)
        self._add_generator_slider_row(grid, 14, "Snr.Str dens.", self.generator_snare_stretch_slider, self.generator_snare_stretch_value, "Snr.Str len.", self.generator_snare_stretch_length_slider, self.generator_snare_stretch_length_value)
        snare_stretch_curve_label = QLabel("Snr.Str curve")
        snare_stretch_curve_tooltip = self._generator_parameter_tooltip("Snr.Str curve")
        self._set_generator_widget_tooltip(
            snare_stretch_curve_tooltip,
            snare_stretch_curve_label,
            self.generator_snare_stretch_curve_combo,
        )
        self._add_generator_slider_row(grid, 15, "Snr.Str amt.", self.generator_snare_stretch_amount_slider, self.generator_snare_stretch_amount_value, "Gate", self.generator_gate_slider, self.generator_gate_value)
        grid.addWidget(snare_stretch_curve_label, 15, 8)
        grid.addWidget(self.generator_snare_stretch_curve_combo, 15, 9, 1, 2)
        self._set_generator_widget_tooltip(
            "Lecture mono globale: chaque nouveau hit coupe immediatement la queue du precedent, "
            "quel que soit son type. S'applique au pattern, aux previews retime/quantize et au live.",
            self.generator_mono_choke_check,
        )
        grid.addWidget(self.generator_mono_choke_check, 15, 11, 1, 4)
        grid.addWidget(self._build_generator_section_label("Playback & Feel", tone="playback"), 16, 0, 1, 12)
        self._add_generator_slider_row(grid, 17, "Velocity", self.generator_velocity_slider, self.generator_velocity_value, "Swing", self.generator_swing_slider, self.generator_swing_value)
        self._add_generator_slider_row(grid, 18, "Anti-repeat", self.generator_anti_repeat_slider, self.generator_anti_repeat_value, "Breath", self.generator_breath_slider, self.generator_breath_value)

        self.generator_sequence_max_label = QLabel("Seq max len")
        self.generator_sequence_role_lock_label = QLabel("Seq role lock")
        self._set_generator_widget_tooltip(
            "Longueur max en nombre de hits d'une sequence candidate injectee en bloc.",
            self.generator_sequence_max_label,
            self.generator_sequence_max_len_spin,
        )
        self._set_generator_widget_tooltip(
            "Si actif, chaque role de sequence reste dans sa zone naturelle: fills en fin de mesure, groove au milieu, etc.",
            self.generator_sequence_role_lock_label,
            self.generator_sequence_role_lock_check,
        )
        self._set_generator_widget_tooltip(
            "Retire toutes les ancres posees sur la ligne Anchor.",
            self.generator_clear_anchors_button,
        )
        self._set_generator_widget_tooltip(
            "Retire tous les locks step par step. Le prochain Generate random pourra a nouveau tout modifier.",
            self.generator_clear_locks_button,
        )
        grid.addWidget(self.generator_sequence_max_label, 19, 0)
        grid.addWidget(self.generator_sequence_max_len_spin, 19, 1)
        grid.addWidget(self.generator_sequence_role_lock_label, 19, 3)
        grid.addWidget(self.generator_sequence_role_lock_check, 19, 4, 1, 2)
        grid.addWidget(self.generator_clear_anchors_button, 19, 7, 1, 2)
        grid.addWidget(self.generator_clear_locks_button, 19, 9, 1, 2)

        self.generator_pitch_box = QGroupBox("Pitch")
        pitch_layout = QGridLayout(self.generator_pitch_box)
        pitch_layout.setHorizontalSpacing(8)
        pitch_layout.setVerticalSpacing(6)
        self.generator_pitch_sequence_label = QLabel("Sequence")
        self.generator_pitch_curve_label = QLabel("Curve")
        self.generator_pitch_curve_range_label = QLabel("Curve range")
        pitch_layout.addWidget(QLabel("Mode"), 0, 0)
        pitch_layout.addWidget(self.generator_pitch_mode_combo, 0, 1)
        pitch_layout.addWidget(QLabel("Scope"), 0, 2)
        pitch_layout.addWidget(self.generator_pitch_scope_combo, 0, 3)
        pitch_layout.addWidget(QLabel("Scale"), 0, 4)
        pitch_layout.addWidget(self.generator_pitch_scale_combo, 0, 5)
        pitch_layout.addWidget(QLabel("Root"), 1, 0)
        pitch_layout.addWidget(self.generator_pitch_root_slider, 1, 1, 1, 2)
        pitch_layout.addWidget(self.generator_pitch_root_value, 1, 3)
        pitch_layout.addWidget(QLabel("Amount"), 1, 4)
        pitch_layout.addWidget(self.generator_pitch_amount_slider, 1, 5, 1, 2)
        pitch_layout.addWidget(self.generator_pitch_amount_value, 1, 7)
        pitch_layout.addWidget(QLabel("Range min"), 2, 0)
        pitch_layout.addWidget(self.generator_pitch_range_min_slider, 2, 1, 1, 2)
        pitch_layout.addWidget(self.generator_pitch_range_min_value, 2, 3)
        pitch_layout.addWidget(QLabel("Range max"), 2, 4)
        pitch_layout.addWidget(self.generator_pitch_range_max_slider, 2, 5, 1, 2)
        pitch_layout.addWidget(self.generator_pitch_range_max_value, 2, 7)
        pitch_layout.addWidget(QLabel("Rate"), 3, 0)
        pitch_layout.addWidget(self.generator_pitch_rate_combo, 3, 1)
        pitch_layout.addWidget(self.generator_pitch_sequence_label, 3, 2)
        pitch_layout.addWidget(self.generator_pitch_sequence_input, 3, 3, 1, 5)
        pitch_layout.addWidget(self.generator_pitch_curve_label, 4, 0)
        pitch_layout.addWidget(self.generator_pitch_curve_combo, 4, 1)
        pitch_layout.addWidget(self.generator_pitch_curve_range_label, 4, 2)
        pitch_layout.addWidget(self.generator_pitch_curve_min_slider, 4, 3, 1, 2)
        pitch_layout.addWidget(self.generator_pitch_curve_min_value, 4, 5)
        pitch_layout.addWidget(self.generator_pitch_curve_max_slider, 4, 6)
        pitch_layout.addWidget(self.generator_pitch_curve_max_value, 4, 7)
        grid.addWidget(self.generator_pitch_box, 20, 0, 1, 12)
        self.generator_live_box = self._build_live_mode_box()
        self.generator_live_section = ToggleSection("Live performance", expanded=False)
        self.generator_live_section.body_layout.addWidget(self.generator_live_box)

        self.generator_probability_section = ToggleSection("Probability & FX preview", expanded=False)
        self.generator_probability_section.body_layout.addWidget(self.generator_probability_label)
        self.generator_probability_section.body_layout.addWidget(self.generator_probability_table)
        self.generator_probability_section.body_layout.addWidget(self.generator_effect_probability_label)
        self.generator_probability_section.body_layout.addWidget(self.generator_effect_probability_table)

        grid.addWidget(self.generator_loading_bar, 21, 0, 1, 12)
        grid.addWidget(self.generator_info_label, 22, 0, 1, 12)
        grid.addWidget(self.generator_summary_label, 23, 0, 1, 12)
        grid.addWidget(self.generator_sequence_table, 24, 0, 1, 12)

        self.generator_pattern_details_section = ToggleSection("Step list & source details", expanded=False)
        self.generator_pattern_details_section.body_layout.addWidget(self.generator_table)

        self.generator_pipeline_section = self._build_generator_pipeline_section()
        grid.addWidget(self.generator_pipeline_section, 25, 0, 1, 12)

        self.generator_motifs_section = ToggleSection("User motifs", expanded=True)
        self.generator_motifs_section.body_layout.addWidget(self.generator_motif_editor_box)
        self.generator_motifs_section.body_layout.addWidget(self.generator_saved_motifs_box)
        grid.addWidget(self.generator_motifs_section, 26, 0, 1, 12)

        self._set_generator_widget_tooltip(
            "Tempo estime du break source. C'est la base rythmique qui sert a recaler le pattern genere.",
            self.generator_detected_bpm_value,
        )
        self._set_generator_widget_tooltip(
            "Tempo de lecture du pattern genere. Le pattern garde les slices d'origine mais les declenche selon ce BPM.",
            self.generator_target_bpm_spin,
        )
        self._set_generator_widget_tooltip(
            "Nombre de mesures a generer. La grille au-dessus s'adapte a ce nombre de steps.",
            self.generator_bars_spin,
        )
        self._set_generator_widget_tooltip(
            "Densite globale des motifs utilisateur en mode Hybrid. A 0, le mode Hybrid retombe presque sur le comportement Classic.",
            self.generator_motif_density_slider,
            self.generator_motif_density_value,
        )
        self._set_generator_widget_tooltip(
            "Randomise les reglages creatifs du generateur sans toucher au tempo, au nombre de mesures, aux ancres ni aux locks.",
            self.generator_randomize_params_button,
        )
        self._set_generator_widget_tooltip(
            "Fallback explicite pour fabriquer des ghosts a partir des snares quand le break source n'offre pas assez de vrais snare_ghost / kick_ghost.",
            self.generator_ghost_synthesis_box,
        )
        self._set_generator_widget_tooltip(
            self._generator_parameter_tooltip("Synth fallback"),
            self.generator_synth_ghost_enabled_check,
        )
        self._set_generator_widget_tooltip(
            self._generator_parameter_tooltip("Ghost vel min"),
            self.generator_ghost_vel_min_slider,
            self.generator_ghost_vel_min_value,
        )
        self._set_generator_widget_tooltip(
            self._generator_parameter_tooltip("Ghost vel max"),
            self.generator_ghost_vel_max_slider,
            self.generator_ghost_vel_max_value,
        )
        self._set_generator_widget_tooltip(
            self._generator_parameter_tooltip("Ghost pitch min"),
            self.generator_ghost_pitch_min_slider,
            self.generator_ghost_pitch_min_value,
        )
        self._set_generator_widget_tooltip(
            self._generator_parameter_tooltip("Ghost pitch max"),
            self.generator_ghost_pitch_max_slider,
            self.generator_ghost_pitch_max_value,
        )
        self._set_generator_widget_tooltip(
            self._generator_parameter_tooltip("Ghost gate"),
            self.generator_ghost_gate_slider,
            self.generator_ghost_gate_value,
        )
        self._set_generator_widget_tooltip(
            "Ligne d'ancrage rythmique + locks. Clique la ligne Anchor pour figer un type, la ligne Lock pour conserver le step, et le numero en haut pour ecouter la slice source de ce step. La ligne FX montre explicitement les repeats, reverse, kick rolls et retriggers expo de snare sur la timeline.",
            self.generator_sequence_table,
        )
        self._set_generator_widget_tooltip(
            "Apercu live des probabilites de placement du squelette. Ce sont les poids de base avant les ajustements de contexte, fills et sequences.",
            self.generator_probability_table,
            self.generator_probability_label,
        )
        self._set_generator_widget_tooltip(
            "Apercu heuristique des effets du generateur. Repeat montre ou des retriggers glitch ont le plus de chances d'apparaitre; Reverse montre ou une queue reverse a le plus de chances d'etre injectee; K.Roll montre ou une rafale de kicks a le plus de chances de demarrer puis de s'etaler sur la fenetre rythmique suivante; Snr.Str montre ou un retrigger expo de snare a le plus de chances d'occuper la fenetre jusqu'au repere suivant; Pitch montre ou les hits cibles ont le plus de chances de recevoir un mouvement de pitch.",
            self.generator_effect_probability_table,
            self.generator_effect_probability_label,
        )
        self._set_generator_widget_tooltip(
            "Seed de la derniere variation generee. Elle est informativa seulement: chaque clic sur Generate random en cree une nouvelle.",
            self.generator_seed_value,
        )
        self._set_generator_widget_tooltip(
            "Editeur rapide de motif utilisateur. Clique les cellules pour definir kick/snare/hat/ghost/silence/trou, puis sauvegarde le motif pour le projet courant.",
            self.generator_motif_editor_box,
        )
        self._set_generator_widget_tooltip(
            "Motifs utilisateur sauvegardes pour le projet courant, avec leur probabilite effective estimee selon les reglages courants.",
            self.generator_saved_motifs_box,
            self.generator_saved_motifs_table,
        )
        self._set_generator_widget_tooltip(
            "Mode de mouvement de pitch applique aux hits cibles du pattern genere. Random tire des intervalles, Sequence boucle sur une liste explicite, Curve suit une courbe au sein d'une rafale ou mesure.",
            self.generator_pitch_box,
            self.generator_pitch_mode_combo,
        )
        self._set_generator_widget_tooltip(
            "Choisit quels hits peuvent recevoir un mouvement de pitch: seulement les snares, snares+claps, tous les piliers, ou tous les hits.",
            self.generator_pitch_scope_combo,
        )
        self._set_generator_widget_tooltip(
            "Contraint les valeurs de pitch disponibles a une gamme. Chromatic laisse tout passer; les autres modes arrondissent vers les degres autorises autour de la note racine.",
            self.generator_pitch_scale_combo,
            self.generator_pitch_root_slider,
            self.generator_pitch_root_value,
        )
        self._set_generator_widget_tooltip(
            "Dose l'intensite globale du mouvement de pitch sans changer les autres reglages. 0% = aucun pitch, 100% = pleine amplitude.",
            self.generator_pitch_amount_slider,
            self.generator_pitch_amount_value,
        )
        self._set_generator_widget_tooltip(
            "Borne basse du pitch pour les modes Random et Curve.",
            self.generator_pitch_range_min_slider,
            self.generator_pitch_range_min_value,
        )
        self._set_generator_widget_tooltip(
            "Borne haute du pitch pour les modes Random et Curve.",
            self.generator_pitch_range_max_slider,
            self.generator_pitch_range_max_value,
        )
        self._set_generator_widget_tooltip(
            "Definit a quelle vitesse le pitch change entre les hits cibles: chaque hit, tous les deux hits, ou une valeur par bar.",
            self.generator_pitch_rate_combo,
        )
        self._set_generator_widget_tooltip(
            "Liste explicite de demi-tons en mode Sequence. Exemple: 0, 3, -2, 7.",
            self.generator_pitch_sequence_input,
            self.generator_pitch_sequence_label,
        )
        self._set_generator_widget_tooltip(
            "Forme de la courbe de pitch en mode Curve.",
            self.generator_pitch_curve_combo,
            self.generator_pitch_curve_label,
        )
        self._set_generator_widget_tooltip(
            "Amplitude min/max de la courbe de pitch en mode Curve.",
            self.generator_pitch_curve_min_slider,
            self.generator_pitch_curve_min_value,
            self.generator_pitch_curve_max_slider,
            self.generator_pitch_curve_max_value,
            self.generator_pitch_curve_range_label,
        )
        self._set_generator_widget_tooltip(
            "Genere une nouvelle variation aleatoire avec les reglages courants. Meme reglages, nouvelle seed a chaque clic.",
            self.generator_generate_button,
        )
        self._set_generator_widget_tooltip(
            "Prepare et lit le pattern genere avec le transport du generateur.",
            self.generator_play_button,
        )
        self._set_generator_widget_tooltip(
            "Arrete uniquement la lecture du pattern genere.",
            self.generator_stop_button,
        )
        self._set_generator_widget_tooltip(
            "Relance le pattern genere en boucle avec le BPM cible du generateur.",
            self.generator_loop_button,
        )
        self._refresh_generator_motif_editor_buttons()
        self._refresh_generator_motif_editor_dominant()
        self._refresh_generator_ghost_ui()
        self._refresh_generator_pitch_ui()
        self._refresh_generator_mode_ui()

    def _build_percent_slider(self, value: int) -> tuple[QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setFixedWidth(168)
        slider.setValue(int(np.clip(value, 0, 100)))
        label = QLabel(f"{int(np.clip(value, 0, 100))}%")
        label.setVisible(False)
        slider.valueChanged.connect(lambda current, target=label: target.setText(f"{int(np.clip(current, 0, 100))}%"))
        return slider, label

    def _build_signed_slider(
        self,
        value: int,
        *,
        minimum: int = -24,
        maximum: int = 24,
        suffix: str = " st",
    ) -> tuple[QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(minimum), int(maximum))
        slider.setSingleStep(1)
        slider.setPageStep(4)
        slider.setFixedWidth(168)
        slider.setValue(int(np.clip(value, minimum, maximum)))
        label = QLabel(self._format_signed_value(slider.value(), suffix=suffix))
        label.setMinimumWidth(52)
        slider.valueChanged.connect(
            lambda current, target=label, text_suffix=str(suffix): target.setText(
                self._format_signed_value(int(current), suffix=text_suffix)
            )
        )
        return slider, label

    def _build_scaled_slider(
        self,
        value: int,
        *,
        minimum: int,
        maximum: int,
        scale: float,
        decimals: int = 2,
        suffix: str = "",
        signed: bool = False,
    ) -> tuple[QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(minimum), int(maximum))
        slider.setSingleStep(1)
        slider.setPageStep(max(1, int(round(abs(scale)))))
        slider.setFixedWidth(168)
        slider.setValue(int(np.clip(value, minimum, maximum)))
        label = QLabel(
            self._format_scaled_value(
                float(slider.value()) / float(scale),
                decimals=decimals,
                suffix=suffix,
                signed=signed,
            )
        )
        label.setMinimumWidth(52)
        slider.valueChanged.connect(
            lambda current, target=label, slider_scale=float(scale), slider_decimals=int(decimals), text_suffix=str(suffix), use_signed=bool(signed): target.setText(
                self._format_scaled_value(
                    float(current) / slider_scale,
                    decimals=slider_decimals,
                    suffix=text_suffix,
                    signed=use_signed,
                )
            )
        )
        return slider, label

    def _build_live_mode_box(self) -> QGroupBox:
        box = QGroupBox("Live mode")
        layout = QVBoxLayout(box)
        layout.setSpacing(10)

        self.live_mode_info_label = QLabel(
            "Mode live A/B. Le slot actif joue en boucle, le slot inactif peut etre regenere en arriere-plan, "
            "puis le switch se fait proprement au retour sur le step 1."
        )
        self.live_mode_info_label.setObjectName("StatusLabel")
        self.live_mode_info_label.setWordWrap(True)
        layout.addWidget(self.live_mode_info_label)

        self.live_slot_boxes: dict[str, QGroupBox] = {}
        self.live_slot_status_labels: dict[str, QLabel] = {}
        self.live_slot_seed_labels: dict[str, QLabel] = {}
        self.live_slot_param_labels: dict[str, QLabel] = {}
        self.live_slot_generate_buttons: dict[str, QPushButton] = {}
        self.live_slot_view_buttons: dict[str, QPushButton] = {}
        self.live_slot_save_buttons: dict[str, QToolButton] = {}
        self.live_slot_pattern_tables: dict[str, QTableWidget] = {}

        slot_row = QHBoxLayout()
        slot_row.setSpacing(10)
        for slot_name in LIVE_SLOT_NAMES:
            slot_box = QGroupBox(f"Slot {slot_name}")
            slot_layout = QVBoxLayout(slot_box)
            slot_layout.setSpacing(6)
            status_label = QLabel("○ stale")
            status_label.setObjectName("StatusLabel")
            seed_label = QLabel("Seed: -")
            seed_label.setObjectName("StatusLabel")
            params_label = QLabel("Energy -, Mode -, Bars -")
            params_label.setObjectName("StatusLabel")
            params_label.setWordWrap(True)
            generate_button = QPushButton(f"Generate {slot_name}")
            generate_button.clicked.connect(
                lambda _checked=False, current_slot=str(slot_name): self._generate_live_slot(current_slot)
            )
            self._configure_icon_button(
                generate_button,
                QStyle.StandardPixmap.SP_BrowserReload,
                f"Generer le slot {slot_name} avec les reglages courants",
                qtawesome_name="fa5s.redo-alt",
            )
            view_button = QPushButton(f"Show {slot_name}")
            view_button.setCheckable(True)
            view_button.clicked.connect(
                lambda checked=False, current_slot=str(slot_name): self._select_live_view_slot(current_slot)
            )
            save_button = QToolButton(slot_box)
            save_button.setText("★")
            save_button.setToolTip(
                f"Sauvegarder le slot {slot_name} pour le retrouver plus tard dans l'onglet Saved."
            )
            save_button.setAutoRaise(True)
            save_button.clicked.connect(
                lambda _checked=False, current_slot=str(slot_name): self._save_live_slot_snapshot(current_slot)
            )
            compact_label = QLabel("Pattern simplifie / Ancres / Locks")
            compact_label.setObjectName("StatusLabel")
            compact_label.setWordWrap(True)
            compact_table = QTableWidget(3, 16)
            compact_table.setObjectName("LiveSlotPatternTable")
            compact_table.setHorizontalHeaderLabels([str(index) for index in range(1, 17)])
            compact_table.setVerticalHeaderLabels(("Evt 1", "Anc 1", "Lock 1"))
            compact_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            compact_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            compact_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            compact_table.setAlternatingRowColors(False)
            compact_table.setWordWrap(False)
            compact_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            compact_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            compact_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            compact_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            compact_table.setMinimumHeight(168)
            compact_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            compact_header = compact_table.horizontalHeader()
            compact_header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
            compact_table.cellClicked.connect(
                lambda row, column, current_slot=str(slot_name): self._on_live_slot_compact_cell_clicked(
                    current_slot, row, column
                )
            )
            for column in range(16):
                compact_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            slot_layout.addWidget(status_label)
            slot_layout.addWidget(seed_label)
            slot_layout.addWidget(params_label)
            action_row = QHBoxLayout()
            action_row.setSpacing(6)
            action_row.addWidget(generate_button, 1)
            action_row.addWidget(view_button)
            action_row.addWidget(save_button)
            slot_layout.addLayout(action_row)
            slot_layout.addWidget(compact_label)
            slot_layout.addWidget(compact_table)
            slot_layout.addStretch(1)
            slot_row.addWidget(slot_box, 1)
            self.live_slot_boxes[slot_name] = slot_box
            self.live_slot_status_labels[slot_name] = status_label
            self.live_slot_seed_labels[slot_name] = seed_label
            self.live_slot_param_labels[slot_name] = params_label
            self.live_slot_generate_buttons[slot_name] = generate_button
            self.live_slot_view_buttons[slot_name] = view_button
            self.live_slot_save_buttons[slot_name] = save_button
            self.live_slot_pattern_tables[slot_name] = compact_table

        control_box = QGroupBox("A/B")
        control_layout = QVBoxLayout(control_box)
        control_layout.setSpacing(6)
        bpm_row = QHBoxLayout()
        bpm_row.setSpacing(6)
        bpm_label = QLabel("Live BPM")
        self.live_target_bpm_spin = QDoubleSpinBox()
        self.live_target_bpm_spin.setRange(30.0, 400.0)
        self.live_target_bpm_spin.setDecimals(1)
        self.live_target_bpm_spin.setSingleStep(1.0)
        self.live_target_bpm_spin.setValue(float(self.generator_target_bpm_spin.value()))
        self.live_target_bpm_spin.setToolTip(
            "Tempo global du mode live. Ce controle reste synchronise avec le BPM cible du generateur."
        )
        self.live_target_bpm_spin.valueChanged.connect(self._on_live_target_bpm_changed)
        bpm_row.addWidget(bpm_label)
        bpm_row.addWidget(self.live_target_bpm_spin, 1)
        self.live_play_button = QPushButton("Play active")
        self.live_play_button.clicked.connect(self._play_live_active_slot)
        self._configure_icon_button(
            self.live_play_button,
            QStyle.StandardPixmap.SP_MediaPlay,
            "Jouer le slot actif en mode live",
            qtawesome_name="fa5s.play",
        )
        self.live_stop_button = QPushButton("Stop live")
        self.live_stop_button.clicked.connect(self._stop_live_playback)
        self._configure_icon_button(
            self.live_stop_button,
            QStyle.StandardPixmap.SP_MediaStop,
            "Arreter la lecture live",
            qtawesome_name="fa5s.stop",
        )
        self.live_switch_button = QPushButton("Switch next")
        self.live_switch_button.clicked.connect(self._switch_live_slots_next_cycle)
        self._configure_icon_button(
            self.live_switch_button,
            QStyle.StandardPixmap.SP_MediaSkipForward,
            "Programmer le switch vers l'autre slot au prochain step 1",
            qtawesome_name="fa5s.exchange-alt",
        )
        self.live_duplicate_a_to_b_button = QPushButton("Duplicate A→B")
        self.live_duplicate_a_to_b_button.clicked.connect(lambda: self._duplicate_live_slot("A", "B"))
        self.live_duplicate_b_to_a_button = QPushButton("Duplicate B→A")
        self.live_duplicate_b_to_a_button.clicked.connect(lambda: self._duplicate_live_slot("B", "A"))
        self.live_pending_switch_label = QLabel("No switch pending")
        self.live_pending_switch_label.setObjectName("StatusLabel")
        control_layout.addLayout(bpm_row)
        control_layout.addWidget(self.live_play_button)
        control_layout.addWidget(self.live_stop_button)
        control_layout.addWidget(self.live_switch_button)
        control_layout.addWidget(self.live_duplicate_a_to_b_button)
        control_layout.addWidget(self.live_duplicate_b_to_a_button)
        control_layout.addWidget(self.live_pending_switch_label)
        control_layout.addStretch(1)
        slot_row.insertWidget(1, control_box)
        layout.addLayout(slot_row)

        self.live_stems_box = QGroupBox("Stems")
        stems_layout = QGridLayout(self.live_stems_box)
        stems_layout.setHorizontalSpacing(6)
        stems_layout.setVerticalSpacing(6)
        self.live_stems_all_button = QPushButton("All")
        self.live_stems_all_button.setObjectName("LiveActionButton")
        self.live_stems_all_button.clicked.connect(lambda: self._set_all_live_stems(True))
        self.live_stems_none_button = QPushButton("None")
        self.live_stems_none_button.setObjectName("LiveActionButton")
        self.live_stems_none_button.clicked.connect(lambda: self._set_all_live_stems(False))
        stems_layout.addWidget(self.live_stems_all_button, 0, 0)
        stems_layout.addWidget(self.live_stems_none_button, 0, 1)
        self.live_stem_buttons: dict[str, QPushButton] = {}
        for index, stem_name in enumerate(LIVE_STEM_NAMES):
            button = QPushButton(stem_name)
            button.setObjectName("LiveStemToggle")
            button.setCheckable(True)
            button.setChecked(True)
            button.clicked.connect(
                lambda checked=False, current_stem=str(stem_name): self._toggle_live_stem(current_stem)
            )
            self.live_stem_buttons[stem_name] = button
            stems_layout.addWidget(button, 0 if index < 5 else 1, (index % 5) + 2)
        self.live_stems_section = ToggleSection("Stem mutes", expanded=False)
        self.live_stems_section.body_layout.addWidget(self.live_stems_box)
        layout.addWidget(self.live_stems_section)

        self.live_fx_box = QGroupBox("Live FX")
        fx_layout = QGridLayout(self.live_fx_box)
        fx_layout.setHorizontalSpacing(6)
        fx_layout.setVerticalSpacing(6)
        self.live_effect_controls: dict[str, QWidget] = {}
        self.live_effect_value_labels: dict[str, QLabel] = {}
        self.live_effect_target_buttons: dict[str, dict[str, QPushButton]] = {}
        self.live_effect_all_buttons: dict[str, QPushButton] = {}

        fx_layout.addWidget(QLabel("FX"), 0, 0)
        fx_layout.addWidget(QLabel("Control"), 0, 1, 1, 2)
        fx_layout.addWidget(QLabel("All"), 0, 3)
        for offset, stem_name in enumerate(LIVE_STEM_NAMES, start=4):
            fx_layout.addWidget(QLabel(self._live_stem_short_label(stem_name)), 0, offset)

        gain_slider, gain_value = self._build_scaled_slider(100, minimum=0, maximum=200, scale=100.0, decimals=2)
        gain_slider.valueChanged.connect(lambda value: self._set_live_effect_value("gain", float(value) / 100.0))
        self._add_live_effect_row(fx_layout, 1, "gain", gain_slider, gain_value)

        lowpass_slider, lowpass_value = self._build_scaled_slider(0, minimum=0, maximum=20000, scale=1.0, decimals=0)
        lowpass_slider.valueChanged.connect(lambda value: self._set_live_effect_value("lowpass", float(value)))
        self._add_live_effect_row(fx_layout, 2, "lowpass", lowpass_slider, lowpass_value)

        highpass_slider, highpass_value = self._build_scaled_slider(0, minimum=0, maximum=12000, scale=1.0, decimals=0)
        highpass_slider.valueChanged.connect(lambda value: self._set_live_effect_value("highpass", float(value)))
        self._add_live_effect_row(fx_layout, 3, "highpass", highpass_slider, highpass_value)

        distortion_control = self._build_live_distortion_control()
        distortion_value = QLabel(self._live_effect_value_text("distortion"))
        distortion_value.setMinimumWidth(96)
        self._add_live_effect_row(fx_layout, 4, "distortion", distortion_control, distortion_value)

        bitcrush_slider = QSlider(Qt.Orientation.Horizontal)
        bitcrush_slider.setRange(2, 16)
        bitcrush_slider.setValue(16)
        bitcrush_slider.setFixedWidth(168)
        bitcrush_value = QLabel("16")
        bitcrush_value.setMinimumWidth(36)
        bitcrush_slider.valueChanged.connect(lambda value: bitcrush_value.setText(str(int(value))))
        bitcrush_slider.valueChanged.connect(lambda value: self._set_live_effect_value("bitcrush", int(value)))
        self._add_live_effect_row(fx_layout, 5, "bitcrush", bitcrush_slider, bitcrush_value)

        stutter_button = QPushButton("Hold")
        stutter_button.setObjectName("LiveActionButton")
        stutter_button.pressed.connect(self._on_live_stutter_pressed)
        stutter_button.released.connect(self._on_live_stutter_released)
        stutter_value = QLabel("off")
        stutter_value.setMinimumWidth(36)
        self._add_live_effect_row(fx_layout, 6, "stutter", stutter_button, stutter_value)

        gate_slider, gate_value = self._build_scaled_slider(100, minimum=0, maximum=100, scale=100.0, decimals=2)
        gate_slider.valueChanged.connect(lambda value: self._set_live_effect_value("gate", float(value) / 100.0))
        self._add_live_effect_row(fx_layout, 7, "gate", gate_slider, gate_value)

        self.live_fx_section = ToggleSection("Callback FX", expanded=True)
        self.live_fx_section.body_layout.addWidget(self.live_fx_box)
        live_render_row = QHBoxLayout()
        live_render_row.setSpacing(6)
        self.live_quick_render_button = QPushButton("Quick Render active")
        self.live_quick_render_button.clicked.connect(self._quick_render_live_active_slot)
        self._configure_icon_button(
            self.live_quick_render_button,
            QStyle.StandardPixmap.SP_DialogSaveButton,
            "Exporter directement le slot live actif vers le dernier dossier WAV utilise, sans boite de dialogue.",
        )
        live_render_row.addWidget(self.live_quick_render_button)
        live_render_row.addStretch(1)
        self.live_fx_section.body_layout.addLayout(live_render_row)
        layout.addWidget(self.live_fx_section)
        box.setVisible(bool(self._live_mode_enabled))
        return box

    def _add_live_effect_row(
        self,
        layout: QGridLayout,
        row: int,
        effect_name: str,
        control: QWidget,
        value_label: QLabel,
    ) -> None:
        layout.addWidget(QLabel(LIVE_EFFECT_LABELS.get(effect_name, effect_name.title())), row, 0)
        layout.addWidget(control, row, 1)
        layout.addWidget(value_label, row, 2)
        all_button = QPushButton("All")
        all_button.setObjectName("LiveActionButton")
        all_button.clicked.connect(
            lambda _checked=False, current_effect=str(effect_name): self._set_live_effect_targets(current_effect, True)
        )
        layout.addWidget(all_button, row, 3)
        self.live_effect_controls[effect_name] = control
        self.live_effect_value_labels[effect_name] = value_label
        self.live_effect_all_buttons[effect_name] = all_button
        target_buttons: dict[str, QPushButton] = {}
        for column_offset, stem_name in enumerate(LIVE_STEM_NAMES, start=4):
            button = QPushButton(self._live_stem_short_label(stem_name))
            button.setObjectName("LiveFxTargetToggle")
            button.setCheckable(True)
            button.setChecked(True)
            button.setFixedWidth(34)
            button.clicked.connect(
                lambda checked=False, current_effect=str(effect_name), current_stem=str(stem_name): self._toggle_live_effect_target(
                    current_effect,
                    current_stem,
                )
            )
            target_buttons[stem_name] = button
            layout.addWidget(button, row, column_offset)
        self.live_effect_target_buttons[effect_name] = target_buttons

    def _build_live_distortion_control(self) -> QWidget:
        container = QWidget(self.live_fx_box)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        def _make_slider(*, minimum: int, maximum: int, value: int) -> QSlider:
            slider = QSlider(Qt.Orientation.Horizontal, container)
            slider.setRange(int(minimum), int(maximum))
            slider.setSingleStep(1)
            slider.setPageStep(max(1, int((maximum - minimum) / 8)))
            slider.setFixedWidth(64)
            slider.setValue(int(np.clip(value, minimum, maximum)))
            return slider

        self.live_distortion_drive_slider = _make_slider(minimum=0, maximum=100, value=0)
        self.live_distortion_tone_slider = _make_slider(minimum=-100, maximum=100, value=0)
        self.live_distortion_mix_slider = _make_slider(minimum=0, maximum=100, value=0)

        self.live_distortion_drive_slider.valueChanged.connect(
            lambda value: self._set_live_distortion_param("drive", float(value) / 100.0)
        )
        self.live_distortion_tone_slider.valueChanged.connect(
            lambda value: self._set_live_distortion_param("tone", float(value) / 100.0)
        )
        self.live_distortion_mix_slider.valueChanged.connect(
            lambda value: self._set_live_distortion_param("mix", float(value) / 100.0)
        )

        for label_text, slider in (
            ("Drv", self.live_distortion_drive_slider),
            ("Tone", self.live_distortion_tone_slider),
            ("Mix", self.live_distortion_mix_slider),
        ):
            label = QLabel(label_text, container)
            label.setObjectName("StatusLabel")
            layout.addWidget(label)
            layout.addWidget(slider)
        layout.addStretch(1)
        return container

    @staticmethod
    def _live_stem_short_label(stem_name: str) -> str:
        return {
            "kick": "K",
            "snare": "S",
            "hat": "H",
            "ghost": "G",
            "clap": "C",
            "repeat": "Rp",
            "reverse": "Rv",
            "roll": "Ro",
            "stretch": "St",
            "other": "O",
        }.get(stem_name, stem_name[:2].title())

    @staticmethod
    def _format_signed_value(value: int | float, *, suffix: str = "") -> str:
        numeric_value = float(value)
        if abs(numeric_value - round(numeric_value)) <= 1e-6:
            text = f"{int(round(numeric_value)):+d}"
        else:
            text = f"{numeric_value:+.1f}"
        return f"{text}{suffix}"

    @staticmethod
    def _format_scaled_value(
        value: int | float,
        *,
        decimals: int = 2,
        suffix: str = "",
        signed: bool = False,
    ) -> str:
        numeric_value = float(value)
        precision = max(0, int(decimals))
        text = f"{numeric_value:+.{precision}f}" if signed else f"{numeric_value:.{precision}f}"
        return f"{text}{suffix}"

    @staticmethod
    def _pitch_root_note_name(root: int) -> str:
        return PITCH_NOTE_NAMES[int(root) % len(PITCH_NOTE_NAMES)]

    @staticmethod
    def _generator_parameter_tooltip(name: str) -> str:
        tooltips = {
            "Energy": "Macro globale. Monte la densite generale, ouvre un peu plus de hats/ghosts et rend les accents plus vivants.",
            "Kick": "Controle les kicks automatiques du squelette. A 0, le generateur n'en place pratiquement plus tout seul; une ancre peut toujours en forcer un.",
            "Snare": "Controle les snares/claps automatiques du squelette. A 0, les backbeats ne sont plus pousses automatiquement.",
            "Hat": "Controle le remplissage automatique des subdivisions par des hats. A 0, les steps intermediaires restent beaucoup plus vides.",
            "Ghost": "Controle les ghosts automatiques. A 0, ils disparaissent presque completement du squelette.",
            "Synth fallback": "Quand les vrais snare_ghost / kick_ghost manquent, reutilise une snare normale avec moins de velocite, un petit decalage de pitch optionnel et une queue plus courte.",
            "Ghost vel min": "Borne basse du ratio de velocite applique aux ghosts synthetiques derives d'une snare normale.",
            "Ghost vel max": "Borne haute du ratio de velocite applique aux ghosts synthetiques derives d'une snare normale.",
            "Ghost pitch min": "Borne basse du petit pitch shift applique aux ghosts synthetiques. A 0, le timbre reste identique.",
            "Ghost pitch max": "Borne haute du petit pitch shift applique aux ghosts synthetiques. Serre pour rester subtil.",
            "Ghost gate": "Raccourcit la slice des ghosts synthetiques. 0 = pas de gate supplementaire, 1 = longueur source complete.",
            "Fill": "Genere davantage de fins de mesure en bloc: lift sur la fin du bar, drive juste avant le retour, puis release/resolution plus propre vers le 1 suivant.",
            "Sequences": "Dose l'utilisation de suites de hits extraites du break source. A 0%, le comportement reste purement atomique.",
            "Motifs": "Densite globale des motifs utilisateur en mode Hybrid. Plus haut = davantage de squelettes partiels poses avant le remplissage du generateur.",
            "Repeat": "Ajoute des retriggers rapides du meme hit a l'interieur d'un step, facon glitch. Plus haut = davantage de zones de repeat dans le pattern.",
            "Repeat dens.": "Controle combien de zones de repeat apparaissent dans le pattern. Plus haut = plus de zones glitch.",
            "Repeat len.": "Controle la longueur probable des zones de repeat sur la timeline. Bas = zones courtes, haut = zones plus longues sur plusieurs steps.",
            "Repeat rate": "Controle la vitesse probable des retriggers dans une zone de repeat. Bas = plutot x2, haut = plutot x4.",
            "Reverse": "Injecte des queues reverse apres certains kicks, snares ou claps. L'effet tombe surtout sur les subdivisions entre reperes rythmiques et reutilise la slice du hit juste avant.",
            "K.Roll dens.": "Controle la frequence des kick rolls. Ils demarrent directement sur les beats pairs du bar, puis etalent une petite rafale de kicks sur les steps suivants.",
            "K.Roll len.": "Controle la longueur probable des kick rolls. La V1 reste sur des longueurs paires et courtes, calees sur les fenetres 5-8 et 13-16.",
            "K.Roll dyn.": "Controle le niveau de velocite uniforme de toute la succession du roll, y compris le premier kick de depart.",
            "Snr.Str dens.": "Controle la frequence des zones de retrigger exponentiel sur les snares, claps et ruffs.",
            "Snr.Str len.": "Controle la longueur cible de la zone de retrigger, de 2 a 16 steps. Plus haut = la zone peut couvrir une portion beaucoup plus longue du bar.",
            "Snr.Str amt.": "Controle la vitesse de resserrement exponentiel. Bas = acceleration douce, haut = fin de zone tres compacte et tres glitch.",
            "Snr.Str curve": "Controle la courbe de velocite des retriggers: stable, descendante, montante ou aleatoire.",
            "Gate": "Raccourcit globalement la longueur jouee des slices du pattern. 100% = longueur source, plus bas = queues plus courtes et plus d'air entre les hits.",
            "Velocity": "Elargit l'ecart de dynamique entre les hits. Plus haut = pattern moins plat, plus humain.",
            "Swing": "Decale legerement une partie des subdivisions pour donner un groove plus shuffle et moins droit.",
            "Anti-repeat": "Penalise les repetitions immediates de la meme famille de slice, surtout les hats trop mecaniques.",
            "Breath": "Reserve plus ou moins d'air entre les coups. Plus haut = plus de silences et de respiration apres les zones denses.",
            "Position": "Respecte davantage la position rythmique d'origine des slices. Plus haut = un hit downbeat tend a rester sur un downbeat, etc.",
        }
        return tooltips.get(name, "")

    @staticmethod
    def _set_generator_widget_tooltip(text: str, *widgets: QWidget) -> None:
        if not text:
            return
        for widget in widgets:
            if widget is not None:
                widget.setToolTip(text)

    def _build_generator_section_label(self, text: str, *, tone: str = "neutral") -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        label.setProperty("sectionTone", str(tone))
        label.setFont(self._build_font(11, bold=True))
        return label

    def _set_button_icon(
        self,
        button: QPushButton,
        icon: QStyle.StandardPixmap,
        *,
        qtawesome_name: str | None = None,
        color: str = "#d7dfeb",
    ) -> None:
        qta = _optional_qtawesome()
        if qta is not None and qtawesome_name:
            try:
                button.setIcon(qta.icon(qtawesome_name, color=color))
                return
            except Exception:
                pass
        button.setIcon(self.style().standardIcon(icon))

    def _configure_icon_button(
        self,
        button: QPushButton,
        icon: QStyle.StandardPixmap,
        tooltip: str,
        *,
        width: int = 38,
        qtawesome_name: str | None = None,
        color: str = "#d7dfeb",
    ) -> None:
        self._set_button_icon(button, icon, qtawesome_name=qtawesome_name, color=color)
        button.setIconSize(QSize(16, 16))
        button.setText("")
        button.setToolTip(tooltip)
        button.setFixedSize(width, width)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setObjectName("IconButton" if button.objectName() != "ToggleButton" else "ToggleButton")

    @staticmethod
    def _reserve_label_height(label: QLabel, *, lines: int) -> None:
        metrics = label.fontMetrics()
        label.setMinimumHeight((metrics.lineSpacing() * max(lines, 1)) + 4)

    @staticmethod
    def _build_loading_bar() -> QProgressBar:
        bar = QProgressBar()
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        policy.setRetainSizeWhenHidden(True)
        bar.setSizePolicy(policy)
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setObjectName("LoadingBar")
        bar.setVisible(False)
        bar.setFixedHeight(6)
        return bar

    def _add_generator_slider_row(
        self,
        grid: QGridLayout,
        row: int,
        left_name: str,
        left_slider: QSlider,
        left_value: QLabel,
        right_name: str,
        right_slider: QSlider,
        right_value: QLabel,
    ) -> None:
        left_label = QLabel(left_name)
        right_label = QLabel(right_name)
        left_tooltip = self._generator_parameter_tooltip(left_name)
        right_tooltip = self._generator_parameter_tooltip(right_name)
        self._set_generator_widget_tooltip(left_tooltip, left_label, left_slider, left_value)
        self._set_generator_widget_tooltip(right_tooltip, right_label, right_slider, right_value)
        grid.addWidget(left_label, row, 0)
        grid.addWidget(left_slider, row, 1, 1, 2)
        grid.addWidget(right_label, row, 3)
        grid.addWidget(right_slider, row, 4, 1, 2)

    def _build_result_boxes(self, root: QVBoxLayout) -> None:
        self.results_panel = QWidget()
        results_panel_layout = QVBoxLayout(self.results_panel)
        results_panel_layout.setContentsMargins(0, 0, 0, 0)
        results_panel_layout.setSpacing(0)

        self.result_box = QGroupBox("Resultat principal")
        result_layout = QGridLayout(self.result_box)
        result_layout.setHorizontalSpacing(18)
        result_layout.setVerticalSpacing(10)

        self.result_label = QLabel("Aucun sample charge")
        self.result_label.setObjectName("ResultLabel")
        self.result_label.setFont(self._build_font(20, bold=True))
        self.family_label = QLabel("-")
        self.form_label = QLabel("-")
        self.source_label = QLabel("-")
        self.source_label.setWordWrap(True)
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setFormat("0%")
        self.debug_report_button = QPushButton("Debug report")
        self.debug_report_button.clicked.connect(self._open_generation_debug_report)
        self._configure_icon_button(
            self.debug_report_button,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "Regenerer un rapport texte complet du pipeline du generateur avec les reglages visibles dans l'UI.",
            qtawesome_name="fa5s.bug",
        )

        details = QFormLayout()
        details.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.groove_value = QLabel("-")
        self.tempo_value = QLabel("-")
        self.energy_value = QLabel("-")
        self.band_value = QLabel("-")
        self.band_value.setWordWrap(True)
        self.transient_value = QLabel("-")
        self.transient_value.setWordWrap(True)

        details.addRow("Famille", self.family_label)
        details.addRow("Forme", self.form_label)
        details.addRow("Confiance", self.confidence_bar)
        details.addRow("Groove", self.groove_value)
        details.addRow("Tempo / regularite", self.tempo_value)
        details.addRow("Energie", self.energy_value)
        details.addRow("Spectre", self.band_value)
        details.addRow("Transients", self.transient_value)

        result_layout.addWidget(self.result_label, 0, 0)
        result_layout.addWidget(self.source_label, 1, 0)
        result_layout.addLayout(details, 2, 0)
        result_layout.addWidget(self.debug_report_button, 0, 1, 1, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.candidates_box = QGroupBox("Candidats")
        candidates_layout = QVBoxLayout(self.candidates_box)
        self.candidates_table = QTableWidget(0, 4)
        self.candidates_table.setHorizontalHeaderLabels(("Rang", "Label", "Score", "Details"))
        self.candidates_table.verticalHeader().setVisible(False)
        self.candidates_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.candidates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.candidates_table.setAlternatingRowColors(True)
        self.candidates_table.setWordWrap(False)
        self.candidates_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.candidates_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.candidates_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.candidates_table.setMinimumHeight(140)
        self.candidates_table.setMinimumWidth(720)
        candidates_header = self.candidates_table.horizontalHeader()
        candidates_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        candidates_header.setStretchLastSection(False)
        candidates_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        candidates_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.candidates_table.setColumnWidth(1, 220)
        self.candidates_table.setColumnWidth(3, 520)
        candidates_layout.addWidget(self.candidates_table)

        self.json_box = QGroupBox("JSON brut")
        json_layout = QVBoxLayout(self.json_box)
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setPlaceholderText("Le resultat JSON apparaitra ici.")
        self.json_view.setMinimumHeight(160)
        json_layout.addWidget(self.json_view)

        self.result_box.setMinimumHeight(200)
        self.candidates_box.setMinimumHeight(180)
        self.json_box.setMinimumHeight(160)

        self.candidates_section = ToggleSection("Candidates", expanded=True)
        self.candidates_section.body_layout.addWidget(self.candidates_box)
        self.json_section = ToggleSection("Raw JSON", expanded=False)
        self.json_section.body_layout.addWidget(self.json_box)

        self.results_side_panel = QWidget()
        side_layout = QVBoxLayout(self.results_side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(10)
        side_layout.addWidget(self.candidates_section)
        side_layout.addWidget(self.json_section)
        side_layout.addStretch(1)

        self.results_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.results_splitter.setChildrenCollapsible(False)
        self.results_splitter.setHandleWidth(8)
        self.results_splitter.addWidget(self.result_box)
        self.results_splitter.addWidget(self.results_side_panel)
        self.results_splitter.setStretchFactor(0, 3)
        self.results_splitter.setStretchFactor(1, 5)
        results_panel_layout.addWidget(self.results_splitter)
        root.addWidget(self.results_panel)

    def _schedule_waveform_panel_init(self) -> None:
        if self._waveform_widget is not None or self._waveform_panel_init_requested:
            return
        self._waveform_panel_init_requested = True
        self.waveform_status_label.setText(
            "Chargement differe du waveform editor SampleRod..."
        )
        self.waveform_placeholder.setText(
            "Le waveform editor SampleRod sera charge apres l'ouverture de la fenetre.\n\n"
            "L'import peut prendre quelques secondes selon la machine."
        )
        QTimer.singleShot(0, self._init_waveform_panel)

    def _init_waveform_panel(self) -> None:
        self._waveform_panel_init_requested = False
        if self._waveform_widget is not None:
            return
        try:
            self._waveform_error = None
            self.waveform_status_label.setText("Chargement du waveform editor SampleRod...")
            logging.getLogger("waveform_playback").setLevel(logging.ERROR)
            waveform_cls = _require_waveform_widget()
            waveform = waveform_cls(None, _PrototypeWaveformContext(), auto_load=False)
            waveform.allow_cut_export = True
            waveform.disable_marker_add = False
            waveform.plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            waveform.plot.customContextMenuRequested.connect(self._show_waveform_context_menu)
            for name in ("save_button",):
                button = getattr(waveform, name, None)
                if button is not None:
                    button.setVisible(False)
            for name in ("play_button", "pause_button", "stop_button"):
                button = getattr(waveform, name, None)
                if button is not None:
                    button.clicked.connect(self._stop_retimed_preview_for_waveform)
            self._install_waveform_edit_hooks(waveform)
            self._install_waveform_marker_hooks(waveform)
            self._waveform_widget = waveform
            self.waveform_host.addWidget(waveform)
            self.waveform_placeholder.hide()
            self._sync_waveform_playback_controls()
            self.waveform_status_label.setText(
                "Waveform editor SampleRod charge. Utilise ses controles pour ecouter le sample, "
                "selectionner une region pour la couper, rajouter des markers avec le bouton marker, "
                "cliquer un transient pour naviguer et lire directement, "
                "ou clic droit sur la waveform pour un split equilibre."
            )
            pending_path = self._loaded_audio_path or self.path_input.text().strip() or None
            if pending_path and not self._waveform_loading:
                self.waveform_status_label.setText(
                    "Waveform editor charge. Synchronisation du sample en cours..."
                )
                QTimer.singleShot(0, lambda current_path=str(pending_path): self._sync_waveform_path(current_path))
        except Exception as exc:
            self._waveform_error = str(exc)
            self._sync_waveform_playback_controls()
            self.waveform_status_label.setText(self._waveform_error)
            self.waveform_placeholder.setText(
                "Le vrai waveform editor n'a pas pu etre charge.\n\n"
                f"{self._waveform_error}"
            )

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { background: #171a20; color: #eef1f6; }
            QGroupBox { border: 1px solid #303644; border-radius: 12px; margin-top: 10px; padding: 12px; font-weight: 600; background: #1d212a; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
            QLineEdit, QPlainTextEdit, QTableWidget, QSpinBox, QDoubleSpinBox { background: #101318; border: 1px solid #303644; border-radius: 10px; padding: 8px; selection-background-color: #4bb6b7; }
            QTableWidget { gridline-color: #2a303c; }
            QHeaderView::section { background: #222733; color: #eef1f6; border: none; border-bottom: 1px solid #303644; padding: 8px; }
            QPushButton { background: #242c38; border: 1px solid #3a4559; border-radius: 14px; padding: 10px 16px; font-weight: 600; }
            QPushButton:hover { background: #2b3443; border-color: #54627a; }
            QPushButton:pressed { background: #1b212b; border-color: #44516a; }
            QPushButton:disabled { color: #6e7788; background: #1e232c; border-color: #2d3442; }
            QPushButton#IconButton, QPushButton#ToggleButton { padding: 0; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; border-radius: 20px; background: #1c222b; border: 1px solid #49586f; }
            QPushButton#IconButton:hover, QPushButton#ToggleButton:hover { background: #242d39; border-color: #6c7d99; }
            QPushButton#IconButton:pressed, QPushButton#ToggleButton:pressed { background: #161b22; border-color: #5b6982; }
            QPushButton#IconButton[generatorStepRole="beat"] { background: #21343c; border-color: #33515c; }
            QPushButton#IconButton[generatorStepRole="beat"]:hover { background: #28404a; }
            QPushButton#IconButton[generatorStepRole="bar_start"] { background: #382c19; border-color: #7d6430; }
            QPushButton#IconButton[generatorStepRole="bar_start"]:hover { background: #463620; }
            QPushButton#AnchorButton { padding: 0; min-height: 32px; max-height: 32px; border-radius: 11px; background: #141920; border: 1px solid #334154; font-weight: 700; }
            QPushButton#AnchorButton:hover { background: #1a212b; border-color: #5b6f8c; }
            QPushButton#AnchorButton[generatorStepRole="beat"] { background: #1b2c34; border-color: #34535f; }
            QPushButton#AnchorButton[generatorStepRole="bar_start"] { background: #332816; border-color: #7b6230; }
            QPushButton#AnchorButton[anchorActive="true"] { color: #f0c05a; border-color: #d1a142; background: #2a2220; }
            QPushButton#AnchorButton[anchorActive="true"][generatorStepRole="beat"] { background: #24363b; }
            QPushButton#AnchorButton[anchorActive="true"][generatorStepRole="bar_start"] { background: #43331d; }
            QPushButton#AnchorButton[anchorKind="silence"][anchorActive="true"] { color: #a9b4c7; border-color: #70839d; background: #1d232d; }
            QPushButton#AnchorButton[compact="true"] { min-height: 24px; max-height: 24px; border-radius: 8px; font-size: 10px; padding: 0; }
            QPushButton#LockButton { padding: 0; min-height: 32px; max-height: 32px; border-radius: 11px; background: #12171e; border: 1px solid #2f3948; }
            QPushButton#LockButton:hover { background: #18202a; border-color: #4e617a; }
            QPushButton#LockButton[generatorStepRole="beat"] { background: #18272e; border-color: #314c58; }
            QPushButton#LockButton[generatorStepRole="bar_start"] { background: #2a2114; border-color: #6a562b; }
            QPushButton#LockButton[lockActive="true"] { background: #2c241f; border-color: #d1a142; }
            QPushButton#LockButton[lockActive="true"][generatorStepRole="beat"] { background: #243239; }
            QPushButton#LockButton[lockActive="true"][generatorStepRole="bar_start"] { background: #3d311c; }
            QPushButton#LockButton[compact="true"] { min-height: 24px; max-height: 24px; border-radius: 8px; padding: 0; }
            QTableWidget#LiveSlotPatternTable { background: #131821; border: 1px solid #2f3948; border-radius: 10px; gridline-color: #252c38; }
            QRadioButton#HitLabelRadio { spacing: 3px; padding: 0 2px; color: #9ba6ba; font-size: 10px; }
            QRadioButton#HitLabelRadio:checked { color: #eef1f6; font-weight: 700; }
            QRadioButton#HitLabelRadio::indicator { width: 11px; height: 11px; border-radius: 6px; border: 1px solid #54627a; background: #11151c; }
            QRadioButton#HitLabelRadio::indicator:hover { border-color: #7e90ad; }
            QRadioButton#HitLabelRadio::indicator:checked { border-color: #4bb6b7; background: #4bb6b7; }
            QRadioButton#HitLabelRadio::indicator:disabled { border-color: #36404f; background: #11151c; }
            QPushButton#PrimaryButton { background: #d1a142; color: #171a20; border-color: #d1a142; border-radius: 16px; font-weight: 700; }
            QPushButton#PrimaryButton:hover { background: #ddb257; border-color: #ddb257; }
            QPushButton#ToggleButton:checked { background: #4bb6b7; color: #101318; border-color: #4bb6b7; font-weight: 700; }
            QPushButton#LiveActionButton { padding: 8px 12px; border-radius: 12px; }
            QPushButton#LiveStemToggle { min-width: 68px; border-radius: 12px; background: #141920; border: 1px solid #2f3948; color: #738094; }
            QPushButton#LiveStemToggle:hover { border-color: #5a6b84; background: #1a2029; }
            QPushButton#LiveStemToggle:checked { background: rgba(75, 182, 183, 0.18); border-color: #4bb6b7; color: #dff8f5; font-weight: 700; }
            QPushButton#LiveStemToggle:pressed { background: #10151b; }
            QPushButton#LiveFxTargetToggle { padding: 6px 0; min-width: 34px; max-width: 34px; border-radius: 10px; background: #12171e; border: 1px solid #2d3542; color: #647084; }
            QPushButton#LiveFxTargetToggle:hover { border-color: #5c697d; background: #171d25; }
            QPushButton#LiveFxTargetToggle:checked { background: rgba(209, 161, 66, 0.18); border-color: #d1a142; color: #f6e2b7; font-weight: 700; }
            QPushButton#LiveFxTargetToggle:pressed { background: #0f141a; }
            QGroupBox[liveSlotState="stale"] { border-color: #303644; background: #1d212a; color: #aeb8c8; }
            QGroupBox[liveSlotState="ready"] { border-color: #6f88b8; background: #1d2430; color: #e5edf8; }
            QGroupBox[liveSlotState="generating"] { border-color: #5e78d6; background: #1b2336; color: #d9e5ff; }
            QGroupBox[liveSlotState="playing"] { border-color: #4bb6b7; background: #17292c; color: #dcfbf8; }
            QGroupBox[liveSlotPending="true"][liveSlotFlash="true"] { border-color: #f0c05a; background: #2b2417; color: #fff0c9; }
            QGroupBox[liveSlotPending="true"][liveSlotFlash="false"] { border-color: #7a5f24; background: #231f17; color: #f0e1ba; }
            QToolButton#SectionToggle { background: #151a21; border: 1px solid #2d3542; border-radius: 10px; padding: 8px 10px; font-weight: 700; text-align: left; color: #dbe3f0; }
            QToolButton#SectionToggle:hover { background: #1a2029; border-color: #45546a; }
            QWidget#SectionBody { background: transparent; }
            QProgressBar { background: #101318; border: 1px solid #303644; border-radius: 10px; text-align: center; min-height: 18px; }
            QProgressBar::chunk { border-radius: 9px; background: #4bb6b7; }
            QProgressBar#LoadingBar { background: rgba(75, 182, 183, 0.08); border: 1px solid rgba(75, 182, 183, 0.18); border-radius: 3px; min-height: 6px; max-height: 6px; }
            QProgressBar#LoadingBar::chunk { border-radius: 3px; background: #4bb6b7; }
            QLabel#TitleLabel { font-weight: 700; }
            QLabel#ResultLabel { font-weight: 700; color: #f0c05a; }
            QLabel#StatusLabel { color: #9ba6ba; }
            QLabel#SectionLabel { color: #d7dfeb; font-weight: 700; letter-spacing: 0.06em; padding: 6px 10px; border-radius: 10px; border: 1px solid #303644; background: #1a2029; }
            QLabel#SectionLabel[sectionTone="core"] { color: #c8f2ee; background: rgba(75, 182, 183, 0.12); border-color: rgba(75, 182, 183, 0.38); }
            QLabel#SectionLabel[sectionTone="structure"] { color: #f4ddb1; background: rgba(209, 161, 66, 0.13); border-color: rgba(209, 161, 66, 0.42); }
            QLabel#SectionLabel[sectionTone="motion"] { color: #f2c9d4; background: rgba(205, 109, 141, 0.13); border-color: rgba(205, 109, 141, 0.42); }
            QLabel#SectionLabel[sectionTone="playback"] { color: #c9dcff; background: rgba(110, 154, 236, 0.14); border-color: rgba(110, 154, 236, 0.42); }
            """
        )

    def _restore_state(self) -> None:
        last_path = self._settings.value("last_path", "", type=str)
        split_density = self._settings.value("split_density", int(round(DEFAULT_SPLIT_DENSITY)), type=int)
        self.split_density_slider.setValue(int(np.clip(split_density, 0, 100)))
        if last_path:
            self._push_recent_file(last_path)
        self._refresh_recent_files_combo(last_path or None)
        if last_path:
            self.path_input.setText(last_path)
            self._sync_waveform_path(last_path)
        self._generator_locked_steps.clear()
        self._generator_user_motifs = self._load_generator_user_motifs()
        self._saved_pattern_snapshots = self._load_saved_pattern_snapshots()
        self._update_retimed_preview_state(None)
        self._populate_generated_pattern(None)
        self._refresh_generator_probability_preview()
        self._refresh_generator_user_motif_table()
        self._refresh_saved_pattern_table()
        self._refresh_generator_mode_ui()
        self._apply_generator_display_preset(self._generator_display_preset(), persist=False)
        self._rebuild_live_mix_plan()
        self._refresh_live_mode_visibility()
        self._set_waveform_shortcuts_enabled(True)
        self._set_live_shortcuts_enabled(self._live_mode_enabled)
        self._refresh_live_mode_ui()
        self._refresh_generated_pattern_state()
        self._sync_dependency_state()
        self._refresh_control_states(self.status_label.text())

    @staticmethod
    def _normalize_recent_file_path(path: str | None) -> str | None:
        if not path:
            return None
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            try:
                return str(Path(path).expanduser())
            except Exception:
                return str(path).strip() or None

    @staticmethod
    def _recent_file_label(path: str) -> str:
        candidate = Path(path)
        name = candidate.name or path
        parent = candidate.parent.name
        if parent:
            return f"{name} ({parent})"
        return name

    def _recent_files(self) -> list[str]:
        raw_paths = self._settings.value(RECENT_FILES_SETTINGS_KEY, "[]", type=str)
        payload: object = raw_paths
        if isinstance(raw_paths, str):
            try:
                payload = json.loads(raw_paths)
            except Exception:
                payload = []
        if not isinstance(payload, list):
            payload = []
        deduped: list[str] = []
        for entry in payload:
            normalized = self._normalize_recent_file_path(str(entry))
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped[:MAX_RECENT_FILES]

    def _store_recent_files(self, paths: list[str]) -> list[str]:
        deduped: list[str] = []
        for path in paths:
            normalized = self._normalize_recent_file_path(path)
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        trimmed = deduped[:MAX_RECENT_FILES]
        self._settings.setValue(RECENT_FILES_SETTINGS_KEY, json.dumps(trimmed, ensure_ascii=False))
        return trimmed

    def _push_recent_file(self, path: str | None) -> list[str]:
        normalized = self._normalize_recent_file_path(path)
        if not normalized:
            return self._recent_files()
        existing = [entry for entry in self._recent_files() if entry != normalized]
        return self._store_recent_files([normalized, *existing])

    def _refresh_recent_files_combo(self, selected_path: str | None = None) -> None:
        selected = self._normalize_recent_file_path(selected_path or self.path_input.text().strip())
        recent_paths = self._recent_files()
        previous_state = self.recent_files_combo.blockSignals(True)
        try:
            self.recent_files_combo.clear()
            self.recent_files_combo.addItem("Recents", None)
            for path in recent_paths:
                index = self.recent_files_combo.count()
                self.recent_files_combo.addItem(self._recent_file_label(path), path)
                self.recent_files_combo.setItemData(index, path, Qt.ItemDataRole.ToolTipRole)
            selected_index = 0
            if selected:
                selected_index = self.recent_files_combo.findData(selected)
                if selected_index < 0:
                    selected_index = 0
            self.recent_files_combo.setCurrentIndex(selected_index)
        finally:
            self.recent_files_combo.blockSignals(previous_state)

    @staticmethod
    def _marker_store_key_for_path(path: str | None) -> str | None:
        if not path:
            return None
        try:
            resolved = str(Path(path).expanduser().resolve())
        except Exception:
            resolved = str(Path(path).expanduser())
        digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
        return f"saved_markers/{digest}"

    @staticmethod
    def _marker_store_metadata_for_path(path: str | None) -> dict | None:
        if not path:
            return None
        try:
            resolved_path = Path(path).expanduser().resolve()
        except Exception:
            resolved_path = Path(path).expanduser()
        payload: dict[str, object] = {"path": str(resolved_path)}
        try:
            stat = resolved_path.stat()
        except Exception:
            payload["size"] = None
            payload["mtime_ns"] = None
        else:
            payload["size"] = int(stat.st_size)
            payload["mtime_ns"] = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
        return payload

    @staticmethod
    def _hit_labels_store_key_for_path(path: str | None) -> str | None:
        if not path:
            return None
        try:
            resolved = str(Path(path).expanduser().resolve())
        except Exception:
            resolved = str(Path(path).expanduser())
        digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
        return f"saved_hit_labels/{digest}"

    @staticmethod
    def _hit_analysis_store_key_for_path(path: str | None) -> str | None:
        if not path:
            return None
        try:
            resolved = str(Path(path).expanduser().resolve())
        except Exception:
            resolved = str(Path(path).expanduser())
        digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
        return f"saved_hit_analysis/{digest}"

    @staticmethod
    def _hit_signature_payload(hit) -> dict[str, object]:
        return {
            "start_s": float(hit.start_s),
            "end_s": float(hit.end_s),
            "label": str(hit.label),
            "generator_enabled": bool(getattr(hit, "generator_enabled", True)),
        }

    def _persist_hit_labels_for_result(self, result: DrumDetectionResult | None) -> bool:
        if result is None:
            return False
        path = result.source_path or self._loaded_audio_path or self.path_input.text().strip()
        key = self._hit_labels_store_key_for_path(path)
        metadata = self._marker_store_metadata_for_path(path)
        if key is None or metadata is None:
            return False
        payload = {
            "metadata": metadata,
            "hits": [self._hit_signature_payload(hit) for hit in result.transient_hits],
        }
        self._settings.setValue(key, json.dumps(payload, ensure_ascii=False))
        return True

    def _persist_detection_result(self, result: DrumDetectionResult | None) -> bool:
        if result is None:
            return False
        path = result.source_path or self._loaded_audio_path or self.path_input.text().strip()
        key = self._hit_analysis_store_key_for_path(path)
        metadata = self._marker_store_metadata_for_path(path)
        if key is None or metadata is None:
            return False
        payload = {
            "metadata": metadata,
            "result": result.to_dict(),
        }
        self._settings.setValue(key, json.dumps(payload, ensure_ascii=False))
        return True

    @staticmethod
    def _transient_hit_from_payload(payload: dict[str, object]) -> TransientHit:
        return TransientHit(
            index=int(payload.get("index", 0)),
            start_s=float(payload.get("start_s", 0.0)),
            end_s=float(payload.get("end_s", 0.0)),
            label=str(payload.get("label", "silence")),
            confidence=float(payload.get("confidence", 0.0)),
            peak_db=float(payload.get("peak_db", 0.0)),
            low_ratio=float(payload.get("low_ratio", 0.0)),
            mid_ratio=float(payload.get("mid_ratio", 0.0)),
            high_ratio=float(payload.get("high_ratio", 0.0)),
            secondary_labels=tuple(str(value) for value in payload.get("secondary_labels", ()) or ()),
            layer_score=float(payload.get("layer_score", 0.0)),
            role=str(payload.get("role", "other")),
            rhythmic_position=str(payload.get("rhythmic_position", "subdivision")),
            generator_enabled=bool(payload.get("generator_enabled", True)),
        )

    @staticmethod
    def _drum_candidate_from_payload(payload: dict[str, object]) -> DrumCandidate:
        return DrumCandidate(
            label=str(payload.get("label", "")),
            score=float(payload.get("score", 0.0)),
            details=str(payload.get("details", "")),
        )

    @staticmethod
    def _hit_sequence_event_from_payload(payload: dict[str, object]) -> HitSequenceEvent:
        return HitSequenceEvent(
            order=int(payload.get("order", 0)),
            hit_index=int(payload.get("hit_index", 0)),
            label=str(payload.get("label", "")),
            role=str(payload.get("role", "other")),
            start_offset_steps=int(payload.get("start_offset_steps", 0)),
            interval_steps=int(payload.get("interval_steps", 0)),
            velocity_ratio=float(payload.get("velocity_ratio", 1.0)),
            source_start_s=float(payload.get("source_start_s", 0.0)),
            source_end_s=float(payload.get("source_end_s", 0.0)),
            secondary_labels=tuple(str(value) for value in payload.get("secondary_labels", ()) or ()),
            layer_score=float(payload.get("layer_score", 0.0)),
            rhythmic_position=str(payload.get("rhythmic_position", "subdivision")),
        )

    @classmethod
    def _hit_sequence_from_payload(cls, payload: dict[str, object]) -> HitSequence:
        raw_events = payload.get("events", ()) or ()
        events = tuple(
            cls._hit_sequence_event_from_payload(event)
            for event in raw_events
            if isinstance(event, dict)
        )
        return HitSequence(
            index=int(payload.get("index", 0)),
            role=str(payload.get("role", "groove")),
            hit_count=int(payload.get("hit_count", len(events))),
            total_steps=int(payload.get("total_steps", 1)),
            source_start_s=float(payload.get("source_start_s", 0.0)),
            source_end_s=float(payload.get("source_end_s", 0.0)),
            start_step_hint=int(payload.get("start_step_hint", 1)),
            end_step_hint=int(payload.get("end_step_hint", 1)),
            labels=tuple(str(value) for value in payload.get("labels", ()) or ()),
            events=events,
        )

    @classmethod
    def _detection_result_from_payload(cls, payload: dict[str, object]) -> DrumDetectionResult:
        raw_hits = payload.get("transient_hits", ()) or ()
        raw_candidates = payload.get("candidates", ()) or ()
        raw_sequences = payload.get("hit_sequences", ()) or ()
        return DrumDetectionResult(
            source_path=str(payload.get("source_path") or "") or None,
            label=str(payload.get("label", "")),
            form=str(payload.get("form", "")),
            family=str(payload.get("family", "")),
            confidence=float(payload.get("confidence", 0.0)),
            loop_score=float(payload.get("loop_score", 0.0)),
            drum_score=float(payload.get("drum_score", 0.0)),
            break_score=float(payload.get("break_score", 0.0)),
            duration_s=float(payload.get("duration_s", 0.0)),
            sample_rate=int(payload.get("sample_rate", 0)),
            tempo_bpm=float(payload.get("tempo_bpm", 0.0)),
            pulse_score=float(payload.get("pulse_score", 0.0)),
            regularity=float(payload.get("regularity", 0.0)),
            onset_count=int(payload.get("onset_count", 0)),
            onset_density=float(payload.get("onset_density", 0.0)),
            percussive_ratio=float(payload.get("percussive_ratio", 0.0)),
            harmonic_ratio=float(payload.get("harmonic_ratio", 0.0)),
            decay_s=float(payload.get("decay_s", 0.0)),
            spectral_centroid_hz=float(payload.get("spectral_centroid_hz", 0.0)),
            spectral_flatness=float(payload.get("spectral_flatness", 0.0)),
            band_energies={
                str(key): float(value)
                for key, value in dict(payload.get("band_energies", {}) or {}).items()
            },
            transient_hits=tuple(
                cls._transient_hit_from_payload(hit)
                for hit in raw_hits
                if isinstance(hit, dict)
            ),
            candidates=tuple(
                cls._drum_candidate_from_payload(candidate)
                for candidate in raw_candidates
                if isinstance(candidate, dict)
            ),
            hit_sequences=tuple(
                cls._hit_sequence_from_payload(sequence)
                for sequence in raw_sequences
                if isinstance(sequence, dict)
            ),
        )

    @staticmethod
    def _stretch_retrigger_from_payload(payload: dict[str, object]) -> StretchRetrigger:
        return StretchRetrigger(
            slice_source=None,
            offset_ticks=int(payload.get("offset_ticks", 0)),
            step_index=int(payload.get("step_index", 0)),
            sub_step_offset=int(payload.get("sub_step_offset", 0)),
            velocity=float(payload.get("velocity", 0.0)),
        )

    @staticmethod
    def _fill_decision_from_payload(payload: dict[str, object]) -> FillDecision:
        return FillDecision(
            active=bool(payload.get("active", False)),
            fill_type=str(payload.get("fill_type", "ghost_hat") or "ghost_hat"),
            zone_start=int(payload.get("zone_start", 13) or 13),
            zone_end=int(payload.get("zone_end", 16) or 16),
            source=str(payload.get("source", "generated") or "generated"),
        )

    @classmethod
    def _pattern_params_from_payload(cls, payload: dict[str, object]) -> BreakPatternParams:
        defaults = BreakPatternParams()
        raw_user_motifs = payload.get("user_motifs", ()) or ()
        user_motifs = [
            UserMotif.from_dict(entry)
            for entry in raw_user_motifs
            if isinstance(entry, dict)
        ]
        raw_fill_weights = payload.get("fill_type_weights")
        fill_type_weights: dict[str, float] | None = None
        if isinstance(raw_fill_weights, dict):
            fill_type_weights = {}
            for key, value in raw_fill_weights.items():
                try:
                    fill_type_weights[str(key)] = float(value)
                except Exception:
                    continue
            if not fill_type_weights:
                fill_type_weights = None
        def _float_pair(key: str, default: tuple[float, float]) -> tuple[float, float]:
            raw_value = payload.get(key, default)
            if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
                try:
                    return (float(raw_value[0]), float(raw_value[1]))
                except Exception:
                    return default
            return default

        def _float_list(key: str, default: list[float]) -> list[float]:
            raw_value = payload.get(key, default)
            if not isinstance(raw_value, (list, tuple)):
                return [*default]
            values: list[float] = []
            for entry in raw_value:
                try:
                    values.append(float(entry))
                except Exception:
                    continue
            return values or [*default]

        def _str_tuple(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
            raw_value = payload.get(key, default)
            if not isinstance(raw_value, (list, tuple)):
                return default
            values = tuple(str(entry) for entry in raw_value if str(entry).strip())
            return values or default

        return BreakPatternParams(
            energy=float(payload.get("energy", defaults.energy) or defaults.energy),
            kick_weight=float(payload.get("kick_weight", defaults.kick_weight) or defaults.kick_weight),
            snare_weight=float(payload.get("snare_weight", defaults.snare_weight) or defaults.snare_weight),
            hat_density=float(payload.get("hat_density", defaults.hat_density) or defaults.hat_density),
            ghost_density=float(payload.get("ghost_density", defaults.ghost_density) or defaults.ghost_density),
            synth_ghost_enabled=bool(payload.get("synth_ghost_enabled", defaults.synth_ghost_enabled)),
            ghost_vel_range=_float_pair("ghost_vel_range", defaults.ghost_vel_range),
            ghost_pitch_range=_float_pair("ghost_pitch_range", defaults.ghost_pitch_range),
            ghost_gate_ratio=float(payload.get("ghost_gate_ratio", defaults.ghost_gate_ratio) or defaults.ghost_gate_ratio),
            fill_strength=float(payload.get("fill_strength", defaults.fill_strength) or defaults.fill_strength),
            fill_type_weights=fill_type_weights,
            repeat_density=float(payload.get("repeat_density", defaults.repeat_density) or defaults.repeat_density),
            repeat_span=float(payload.get("repeat_span", defaults.repeat_span) or defaults.repeat_span),
            repeat_rate=float(payload.get("repeat_rate", defaults.repeat_rate) or defaults.repeat_rate),
            reverse_density=float(payload.get("reverse_density", defaults.reverse_density) or defaults.reverse_density),
            kick_roll_density=float(payload.get("kick_roll_density", defaults.kick_roll_density) or defaults.kick_roll_density),
            kick_roll_span=float(payload.get("kick_roll_span", defaults.kick_roll_span) or defaults.kick_roll_span),
            kick_roll_contrast=float(payload.get("kick_roll_contrast", defaults.kick_roll_contrast) or defaults.kick_roll_contrast),
            snare_stretch_density=float(payload.get("snare_stretch_density", defaults.snare_stretch_density) or defaults.snare_stretch_density),
            snare_stretch_span=float(payload.get("snare_stretch_span", defaults.snare_stretch_span) or defaults.snare_stretch_span),
            snare_stretch_amount=float(payload.get("snare_stretch_amount", defaults.snare_stretch_amount) or defaults.snare_stretch_amount),
            snare_stretch_vel_curve=str(payload.get("snare_stretch_vel_curve", defaults.snare_stretch_vel_curve) or defaults.snare_stretch_vel_curve),
            pitch_mode=str(payload.get("pitch_mode", defaults.pitch_mode) or defaults.pitch_mode),
            pitch_scope=str(payload.get("pitch_scope", defaults.pitch_scope) or defaults.pitch_scope),
            pitch_scale=str(payload.get("pitch_scale", defaults.pitch_scale) or defaults.pitch_scale),
            pitch_root=int(payload.get("pitch_root", defaults.pitch_root) or defaults.pitch_root),
            pitch_range=_float_pair("pitch_range", defaults.pitch_range),
            pitch_sequence=_float_list("pitch_sequence", defaults.pitch_sequence),
            pitch_curve=str(payload.get("pitch_curve", defaults.pitch_curve) or defaults.pitch_curve),
            pitch_curve_range=_float_pair("pitch_curve_range", defaults.pitch_curve_range),
            pitch_rate=str(payload.get("pitch_rate", defaults.pitch_rate) or defaults.pitch_rate),
            pitch_amount=float(payload.get("pitch_amount", defaults.pitch_amount) or defaults.pitch_amount),
            gate=float(payload.get("gate", defaults.gate) or defaults.gate),
            mono_choke=bool(payload.get("mono_choke", defaults.mono_choke)),
            velocity_spread=float(payload.get("velocity_spread", defaults.velocity_spread) or defaults.velocity_spread),
            swing=float(payload.get("swing", defaults.swing) or defaults.swing),
            anti_repeat=float(payload.get("anti_repeat", defaults.anti_repeat) or defaults.anti_repeat),
            breath_factor=float(payload.get("breath_factor", defaults.breath_factor) or defaults.breath_factor),
            position_fidelity=float(payload.get("position_fidelity", defaults.position_fidelity) or defaults.position_fidelity),
            sequence_density=float(payload.get("sequence_density", defaults.sequence_density) or defaults.sequence_density),
            sequence_max_len=int(payload.get("sequence_max_len", defaults.sequence_max_len) or defaults.sequence_max_len),
            sequence_role_lock=bool(payload.get("sequence_role_lock", defaults.sequence_role_lock)),
            user_motifs=user_motifs,
            motif_density=float(payload.get("motif_density", defaults.motif_density) or defaults.motif_density),
            generation_profile=str(payload.get("generation_profile", defaults.generation_profile) or defaults.generation_profile),
            enabled_passes=_str_tuple("enabled_passes", defaults.enabled_passes),
            seed=int(payload.get("seed", defaults.seed) or defaults.seed),
            bars=int(payload.get("bars", defaults.bars) or defaults.bars),
        )

    @classmethod
    def _generated_pattern_step_from_payload(cls, payload: dict[str, object]) -> GeneratedPatternStep:
        raw_retriggers = payload.get("stretch_retriggers", ()) or ()
        retriggers = tuple(
            cls._stretch_retrigger_from_payload(entry)
            for entry in raw_retriggers
            if isinstance(entry, dict)
        )
        return GeneratedPatternStep(
            step_index=int(payload.get("step_index", 0)),
            label=str(payload.get("label", "silence") or "silence"),
            velocity=int(payload.get("velocity", 0) or 0),
            source_hit_index=(
                None
                if payload.get("source_hit_index", None) is None
                else int(payload.get("source_hit_index"))
            ),
            source_label=str(payload.get("source_label", "") or "") or None,
            source_start_s=(
                None if payload.get("source_start_s", None) is None else float(payload.get("source_start_s"))
            ),
            source_end_s=(
                None if payload.get("source_end_s", None) is None else float(payload.get("source_end_s"))
            ),
            tags=tuple(str(tag) for tag in (payload.get("tags", ()) or ())),
            relative_velocity_ratio=(
                None
                if payload.get("relative_velocity_ratio", None) is None
                else float(payload.get("relative_velocity_ratio"))
            ),
            source_sequence_index=(
                None
                if payload.get("source_sequence_index", None) is None
                else int(payload.get("source_sequence_index"))
            ),
            source_sequence_role=str(payload.get("source_sequence_role", "") or "") or None,
            pitch_shift=float(payload.get("pitch_shift", 0.0) or 0.0),
            is_synthetic_ghost=bool(payload.get("is_synthetic_ghost", False)),
            ghost_vel_ratio=float(payload.get("ghost_vel_ratio", 1.0) or 1.0),
            ghost_pitch_offset=float(payload.get("ghost_pitch_offset", 0.0) or 0.0),
            ghost_gate_ratio=float(payload.get("ghost_gate_ratio", 0.0) or 0.0),
            stretch_retriggers=retriggers,
        )

    @classmethod
    def _generated_break_pattern_from_payload(cls, payload: dict[str, object]) -> GeneratedBreakPattern:
        raw_steps = payload.get("steps", ()) or ()
        raw_fill_decisions = payload.get("fill_decisions", ()) or ()
        raw_metrics = payload.get("metrics", {}) or {}
        return GeneratedBreakPattern(
            bars=int(payload.get("bars", 1) or 1),
            step_count=int(payload.get("step_count", 16) or 16),
            seed=int(payload.get("seed", 1) or 1),
            swing=float(payload.get("swing", 0.0) or 0.0),
            params=cls._pattern_params_from_payload(dict(payload.get("params", {}) or {})),
            event_count=int(payload.get("event_count", 0) or 0),
            summary=str(payload.get("summary", "") or ""),
            steps=tuple(
                cls._generated_pattern_step_from_payload(entry)
                for entry in raw_steps
                if isinstance(entry, dict)
            ),
            fill_decisions=tuple(
                cls._fill_decision_from_payload(entry)
                for entry in raw_fill_decisions
                if isinstance(entry, dict)
            ),
            metrics={str(key): float(value) for key, value in dict(raw_metrics).items()},
        )

    @staticmethod
    def _detection_result_matches_marker_times(
        result: DrumDetectionResult,
        marker_times: list[float] | None,
        *,
        tolerance_s: float = 0.0025,
    ) -> bool:
        if not marker_times:
            return True
        hit_times = [float(hit.start_s) for hit in result.transient_hits]
        if len(hit_times) != len(marker_times):
            return False
        return all(abs(float(hit_time) - float(marker_time)) <= tolerance_s for hit_time, marker_time in zip(hit_times, marker_times))

    def _restore_persisted_detection_result_for_path(
        self,
        path: str | None,
        *,
        marker_times: list[float] | None = None,
    ) -> DrumDetectionResult | None:
        key = self._hit_analysis_store_key_for_path(path)
        metadata = self._marker_store_metadata_for_path(path)
        if key is None or metadata is None:
            return None

        raw_payload = self._settings.value(key, "", type=str)
        if not raw_payload:
            return None
        try:
            payload = json.loads(raw_payload)
        except Exception:
            return None

        stored_metadata = payload.get("metadata")
        stored_result = payload.get("result")
        if not isinstance(stored_metadata, dict) or stored_metadata != metadata or not isinstance(stored_result, dict):
            return None

        try:
            result = self._detection_result_from_payload(stored_result)
        except Exception:
            return None
        if not self._detection_result_matches_marker_times(result, marker_times):
            return None
        return result

    def _restore_persisted_detection_result_for_loaded_audio(
        self,
        path: str | None,
        *,
        preserve_existing_markers: bool,
    ) -> bool:
        restored = self._restore_persisted_detection_result_for_path(
            path,
            marker_times=self._current_marker_times(),
        )
        if restored is None:
            return False
        self._analysis_stale = False
        self._result = restored
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._generator_locked_steps.clear()
        self._populate_result(restored)
        self._populate_hits(restored)
        self._apply_hits_to_waveform(restored, preserve_existing=preserve_existing_markers)
        self._update_retimed_preview_state(restored, reset_target=True)
        self._populate_generated_pattern(None)
        self._refresh_generated_pattern_state()
        self._refresh_control_states(
            f"Analyse des hits restauree pour {Path(path).name if path else 'ce break'}."
        )
        return True

    def _apply_persisted_hit_labels(self, result: DrumDetectionResult) -> DrumDetectionResult:
        path = result.source_path or self._loaded_audio_path or self.path_input.text().strip()
        key = self._hit_labels_store_key_for_path(path)
        metadata = self._marker_store_metadata_for_path(path)
        if key is None or metadata is None:
            return result

        raw_payload = self._settings.value(key, "", type=str)
        if not raw_payload:
            return result
        try:
            payload = json.loads(raw_payload)
        except Exception:
            return result

        stored_metadata = payload.get("metadata")
        stored_hits = payload.get("hits")
        if not isinstance(stored_metadata, dict) or stored_metadata != metadata or not isinstance(stored_hits, list):
            return result

        remaining_indices = set(range(len(stored_hits)))
        tolerance_s = 0.035
        updated_hits = []
        for hit in result.transient_hits:
            best_index: int | None = None
            best_distance = float("inf")
            for candidate_index in list(remaining_indices):
                candidate = stored_hits[candidate_index]
                if not isinstance(candidate, dict):
                    continue
                label = str(candidate.get("label", ""))
                if label not in MANUAL_HIT_LABEL_OPTIONS:
                    continue
                try:
                    start_s = float(candidate.get("start_s", -1.0))
                    end_s = float(candidate.get("end_s", -1.0))
                except (TypeError, ValueError):
                    continue
                start_delta = abs(start_s - float(hit.start_s))
                end_delta = abs(end_s - float(hit.end_s))
                if start_delta > tolerance_s or end_delta > tolerance_s:
                    continue
                distance = start_delta + end_delta
                if distance < best_distance:
                    best_distance = distance
                    best_index = candidate_index

            if best_index is None:
                updated_hits.append(hit)
                continue

            remaining_indices.discard(best_index)
            label = str(stored_hits[best_index].get("label", hit.label))
            generator_enabled = bool(stored_hits[best_index].get("generator_enabled", getattr(hit, "generator_enabled", True)))
            if label == hit.label and generator_enabled == getattr(hit, "generator_enabled", True):
                updated_hits.append(hit)
                continue
            updated_hits.append(
                replace(
                    hit,
                    label=label,
                    secondary_labels=(),
                    layer_score=0.0,
                    role=self._hit_role_for_label(label),
                    generator_enabled=generator_enabled,
                )
            )

        updated_result = replace(result, transient_hits=tuple(updated_hits))
        return self._refresh_result_sequences_from_hits(updated_result)

    @staticmethod
    def _refresh_result_sequences_from_hits(result: DrumDetectionResult) -> DrumDetectionResult:
        try:
            return requantize_detection_result(result, tempo_bpm=float(result.tempo_bpm))
        except Exception:
            return result

    @staticmethod
    def _normalize_marker_times(marker_times: list[float], *, duration: float | None = None) -> list[float]:
        normalized: list[float] = []
        upper_bound = float(duration) if duration is not None else None
        for raw_value in marker_times:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(value):
                continue
            if upper_bound is not None:
                value = float(np.clip(value, 0.0, upper_bound))
            if normalized and abs(normalized[-1] - value) < 1e-6:
                continue
            normalized.append(value)
        return normalized

    def _persist_marker_times_for_path(self, path: str | None, marker_times: list[float]) -> bool:
        key = self._marker_store_key_for_path(path)
        payload = self._marker_store_metadata_for_path(path)
        if not key or payload is None:
            return False
        payload["markers"] = self._normalize_marker_times(marker_times)
        self._settings.setValue(key, json.dumps(payload, ensure_ascii=False))
        return True

    def _load_persisted_marker_times_for_path(self, path: str | None) -> list[float]:
        key = self._marker_store_key_for_path(path)
        metadata = self._marker_store_metadata_for_path(path)
        if not key or metadata is None:
            return []
        raw_payload = self._settings.value(key, "", type=str)
        if not raw_payload:
            return []
        try:
            payload = json.loads(raw_payload)
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []
        if str(payload.get("path", "")) != str(metadata.get("path", "")):
            return []
        expected_size = metadata.get("size")
        expected_mtime = metadata.get("mtime_ns")
        if payload.get("size") != expected_size or payload.get("mtime_ns") != expected_mtime:
            return []
        marker_values = payload.get("markers")
        if not isinstance(marker_values, list):
            return []
        return self._normalize_marker_times(marker_values)

    def _schedule_marker_persist(self) -> None:
        if self._suspend_marker_persistence:
            return
        self._marker_persist_timer.start(250)

    def _persist_current_markers(self, *, force: bool = False) -> None:
        if self._suspend_marker_persistence and not force:
            return
        self._marker_persist_timer.stop()
        path = self._current_resolved_path() or self._loaded_audio_path
        if not path:
            return
        self._persist_marker_times_for_path(path, self._current_marker_times())

    def _restore_persisted_markers_for_path(self, path: str | None) -> bool:
        if self._waveform_widget is None:
            return False
        duration = float(getattr(self._waveform_widget, "duration", 0.0) or 0.0)
        marker_times = self._normalize_marker_times(
            self._load_persisted_marker_times_for_path(path),
            duration=duration if duration > 0.0 else None,
        )
        if not marker_times:
            return False
        self._replace_waveform_markers(marker_times)
        return True

    def _sync_dependency_state(self) -> None:
        self._dependency_error = get_analysis_dependency_error()
        self.retime_loop_button.setEnabled(not bool(self._dependency_error))
        self.generator_loop_button.setEnabled(not bool(self._dependency_error))
        if self._dependency_error:
            self.analyze_button.setEnabled(False)
            self.top_n_spin.setEnabled(False)
            self.split_density_slider.setEnabled(False)
            self.rebuild_markers_button.setEnabled(False)
            self.status_label.setText(self._dependency_error)
            self.json_view.setPlainText(
                "Analyse indisponible tant que les dependances audio ne sont pas installees.\n\n"
                "Commande conseillee:\n"
                "python -m pip install -r requirements.txt"
            )
            self.retime_play_button.setEnabled(False)
            self.retime_stop_button.setEnabled(False)
            self.detected_bpm_factor_combo.setEnabled(False)
            self.target_bpm_spin.setEnabled(False)
            self.retime_loop_button.setEnabled(False)
            self.preview_mode_combo.setEnabled(False)
            self.quantize_grid_combo.setEnabled(False)
            self.quantize_strength_slider.setEnabled(False)
            self.quantize_strength_value.setEnabled(False)
            self.generator_generate_button.setEnabled(False)
            self.generator_play_button.setEnabled(False)
            self.generator_stop_button.setEnabled(False)
            self.generator_target_bpm_spin.setEnabled(False)
            if hasattr(self, "live_target_bpm_spin"):
                self.live_target_bpm_spin.setEnabled(False)
            self.generator_bars_spin.setEnabled(False)
            self.generator_loop_button.setEnabled(False)
        self._refresh_control_states(self.status_label.text())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _extract_audio_path(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        path = _extract_audio_path(event.mimeData())
        if not path:
            super().dropEvent(event)
            return
        self._handle_path_selected(path)
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        workers = self._running_workers()
        if workers:
            self._close_after_background_tasks = True
            for worker in workers:
                worker.requestInterruption()
            _shutdown_pattern_generation_process_pool()
            _shutdown_live_generation_process_pool()
            self._clear_live_audio_shared_buffer(retain_if_busy=False)
            self._release_retained_live_audio_shared_memories(force=True)
            self._refresh_control_states(
                "Des taches tournent encore en arriere-plan. La fenetre se fermera des qu'elles auront fini."
            )
            event.ignore()
            return

        self._persist_current_markers(force=True)
        self._stop_retimed_preview(update_status=False)
        if self._waveform_widget is not None:
            try:
                self._waveform_widget.stop_audio()
            except Exception:
                pass
        self._clear_live_audio_shared_buffer(retain_if_busy=False)
        self._release_retained_live_audio_shared_memories(force=True)
        _shutdown_pattern_generation_process_pool()
        _shutdown_live_generation_process_pool()
        super().closeEvent(event)

    def _browse_file(self) -> None:
        start_dir = self._current_browse_dir()
        filter_text = "Audio (*.wav *.mp3 *.flac *.ogg *.aif *.aiff *.m4a)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Choisir un sample audio", start_dir, filter_text)
        if file_path:
            self._handle_path_selected(file_path)

    def _current_browse_dir(self) -> str:
        current_path = self.path_input.text().strip()
        if current_path:
            current = Path(current_path).expanduser()
            if current.is_file():
                return str(current.parent)
            if current.is_dir():
                return str(current)
        return self._settings.value("last_dir", str(Path.home()), type=str)

    def _handle_path_selected(self, path: str) -> None:
        self._persist_current_markers(force=True)
        self._stop_retimed_preview(update_status=False)
        normalized_path = self._normalize_recent_file_path(path) or str(Path(path).expanduser())
        self.path_input.setText(normalized_path)
        resolved = Path(normalized_path).expanduser()
        self._settings.setValue("last_path", str(resolved))
        self._push_recent_file(normalized_path)
        self._refresh_recent_files_combo(normalized_path)
        if resolved.exists():
            self._settings.setValue("last_dir", str(resolved.parent))
        self._analysis_stale = False
        self._result = None
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._generator_locked_steps.clear()
        self._loaded_audio_samples = None
        self._loaded_audio_sample_rate = None
        self._loaded_audio_path = None
        self._populate_hits(None)
        self._update_retimed_preview_state(None)
        self._populate_generated_pattern(None)
        self._refresh_generated_pattern_state()
        self.rebuild_markers_label.setText(
            "Tu peux ajouter, deplacer ou supprimer des markers dans la waveform, puis reconstruire la liste de transients."
        )
        self._schedule_waveform_panel_init()
        self._sync_waveform_path(str(resolved))
        self._refresh_control_states("Sample selectionne. Chargement waveform en cours...")

    def _on_recent_file_selected(self, index: int) -> None:
        if index <= 0:
            return
        selected_path = self.recent_files_combo.itemData(index)
        if not selected_path:
            return
        self._handle_path_selected(str(selected_path))

    def _on_split_density_changed(self, value: int) -> None:
        self._settings.setValue("split_density", int(value))
        self._refresh_split_density_label(value)

    def _refresh_split_density_label(self, value: int) -> None:
        if value <= 30:
            mode = "leger"
        elif value >= 70:
            mode = "dense"
        else:
            mode = "equilibre"
        self.split_density_value.setText(f"{value}% ({mode})")

    def _set_detected_bpm_factor(self, factor: float) -> None:
        target_factor = min((0.5, 1.0, 2.0, 4.0), key=lambda candidate: abs(candidate - factor))
        index = self.detected_bpm_factor_combo.findData(target_factor)
        if index < 0:
            index = 1
        self.detected_bpm_factor_combo.setCurrentIndex(index)

    def _detected_bpm_factor(self) -> float:
        factor = self.detected_bpm_factor_combo.currentData()
        try:
            return float(factor)
        except (TypeError, ValueError):
            return 1.0

    def _effective_detected_bpm(self, result: DrumDetectionResult | None) -> float:
        if result is None:
            return 0.0
        return float(result.tempo_bpm) * self._detected_bpm_factor()

    def _effective_generator_result(self, result: DrumDetectionResult | None) -> DrumDetectionResult | None:
        if result is None:
            return None
        effective_bpm = self._effective_detected_bpm(result)
        effective_result = result
        if effective_bpm <= 1.0:
            return self._filter_result_for_generator(result)
        if abs(float(result.tempo_bpm) - float(effective_bpm)) > 1e-6:
            effective_result = requantize_detection_result(result, tempo_bpm=effective_bpm)
        return self._filter_result_for_generator(effective_result)

    @staticmethod
    def _filter_result_for_generator(result: DrumDetectionResult) -> DrumDetectionResult:
        active_hits = tuple(hit for hit in result.transient_hits if bool(getattr(hit, "generator_enabled", True)))
        if len(active_hits) == len(result.transient_hits):
            return result
        active_hit_indices = {int(hit.index) for hit in active_hits}
        active_sequences = tuple(
            sequence
            for sequence in result.hit_sequences
            if sequence.events
            and all(int(event.hit_index) in active_hit_indices for event in sequence.events)
        )
        duration_s = max(float(result.duration_s), 1e-6)
        return replace(
            result,
            transient_hits=active_hits,
            hit_sequences=active_sequences,
            onset_count=len(active_hits),
            onset_density=float(len(active_hits) / duration_s),
        )

    def _set_preview_mode(self, mode: str) -> None:
        index = self.preview_mode_combo.findData(
            PREVIEW_MODE_QUANTIZE if str(mode).lower() == PREVIEW_MODE_QUANTIZE else PREVIEW_MODE_RETIME
        )
        if index < 0:
            index = 0
        self.preview_mode_combo.setCurrentIndex(index)

    def _preview_mode(self) -> str:
        mode = self.preview_mode_combo.currentData()
        return PREVIEW_MODE_QUANTIZE if mode == PREVIEW_MODE_QUANTIZE else PREVIEW_MODE_RETIME

    def _set_quantize_grid_division(self, grid_division: int) -> None:
        try:
            target_grid = int(grid_division)
        except (TypeError, ValueError):
            target_grid = DEFAULT_QUANTIZE_GRID_DIVISION
        index = self.quantize_grid_combo.findData(target_grid)
        if index < 0:
            index = self.quantize_grid_combo.findData(DEFAULT_QUANTIZE_GRID_DIVISION)
        if index < 0:
            index = 0
        self.quantize_grid_combo.setCurrentIndex(index)

    def _quantize_grid_division(self) -> int:
        value = self.quantize_grid_combo.currentData()
        try:
            grid_division = int(value)
        except (TypeError, ValueError):
            grid_division = DEFAULT_QUANTIZE_GRID_DIVISION
        return grid_division if grid_division in QUANTIZE_GRID_DIVISIONS else DEFAULT_QUANTIZE_GRID_DIVISION

    def _quantize_strength(self) -> float:
        return float(np.clip(self.quantize_strength_slider.value() / 100.0, 0.0, 1.0))

    def _refresh_quantize_strength_label(self, value: int) -> None:
        self.quantize_strength_value.setText(f"{int(np.clip(value, 0, 100))}%")

    def _sync_quantize_controls_state(self) -> None:
        quantize_enabled = self._preview_mode() == PREVIEW_MODE_QUANTIZE and not bool(self._dependency_error)
        if self._analysis_busy or self._rebuild_busy or self._waveform_loading or self._preview_busy or self._analysis_stale:
            quantize_enabled = False
        self.quantize_grid_combo.setEnabled(quantize_enabled)
        self.quantize_strength_slider.setEnabled(quantize_enabled)
        self.quantize_strength_value.setEnabled(quantize_enabled)

    def _preview_mode_suffix(self, *, include_strength: bool = True) -> str:
        if self._preview_mode() != PREVIEW_MODE_QUANTIZE:
            suffix = "mode retime"
            if self._generator_mono_choke_enabled():
                suffix += " + mono choke"
            return suffix
        suffix = f"mode quantize {format_quantize_grid_label(self._quantize_grid_division())}"
        if include_strength:
            suffix += f" a {self._quantize_strength() * 100:.0f}%"
        if self._generator_mono_choke_enabled():
            suffix += " + mono choke"
        return suffix

    def _default_generator_info_text(self) -> str:
        return (
            f"Chaque clic sur Generate random cree un nouveau pattern {self._generator_pattern_shape_text()} "
            "a partir des slices detectees. La ligne Anchor permet de figer quelques temps forts puis de generer autour. "
            "La colonne Pool dans la liste des hits permet d'exclure certaines slices du generateur sans les supprimer de l'analyse. "
            "Gate raccourcit la lecture des slices, Repeat cree des zones glitch avec retriggers, "
            "Mono choke force une lecture globale mono ou chaque nouveau hit coupe le precedent, "
            "Reverse injecte des queues reverse apres certains kicks ou snares sur les subdivisions, "
            "K.Roll construit de petites rafales de kicks sur plusieurs steps avec une velocite uniforme, "
            "et Snr.Str transforme certains snares ou claps en retriggers exponentiels sur une zone configurable. "
            "Le mode Hybrid peut aussi poser des motifs utilisateur comme squelette temporaire avant le remplissage. "
            "Le transport ci-dessous est propre au generateur, avec son BPM cible et sa boucle."
        )

    def _pipeline_pass_enabled_setting_key(self, pass_name: str) -> str:
        return f"generator_pipeline_enabled/{str(pass_name)}"

    def _build_generator_pipeline_section(self) -> ToggleSection:
        section = ToggleSection("Manual pipeline", expanded=True)
        self.generator_pipeline_checkboxes: dict[str, QCheckBox] = {}
        self.generator_pipeline_status_labels: dict[str, QLabel] = {}
        self.generator_pipeline_run_buttons: dict[str, QPushButton] = {}
        self.generator_pipeline_rollback_buttons: dict[str, QPushButton] = {}

        for pass_name in PIPELINE_PASS_ORDER:
            row = QWidget(section)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            checkbox = QCheckBox(GENERATOR_PIPELINE_PASS_LABELS.get(pass_name, pass_name), row)
            if pass_name == "skeleton":
                checkbox.setChecked(True)
                checkbox.setEnabled(False)
            else:
                enabled = bool(self._settings.value(self._pipeline_pass_enabled_setting_key(pass_name), True, type=bool))
                checkbox.setChecked(enabled)
                checkbox.toggled.connect(
                    lambda checked, current_pass=pass_name: self._on_generator_pipeline_pass_toggled(current_pass, checked)
                )

            status_label = QLabel("pending", row)
            status_label.setObjectName("StatusLabel")
            status_label.setMinimumWidth(72)
            run_button = QPushButton("Run", row)
            rollback_button = QPushButton("Rollback", row)
            run_button.clicked.connect(lambda _checked=False, current_pass=pass_name: self._run_generator_pipeline_pass(current_pass))
            rollback_button.clicked.connect(
                lambda _checked=False, current_pass=pass_name: self._rollback_generator_pipeline_pass(current_pass)
            )

            row_layout.addWidget(checkbox, 1)
            row_layout.addWidget(status_label, 0)
            row_layout.addWidget(run_button, 0)
            row_layout.addWidget(rollback_button, 0)

            self.generator_pipeline_checkboxes[pass_name] = checkbox
            self.generator_pipeline_status_labels[pass_name] = status_label
            self.generator_pipeline_run_buttons[pass_name] = run_button
            self.generator_pipeline_rollback_buttons[pass_name] = rollback_button
            section.body_layout.addWidget(row)

        button_row = QWidget(section)
        button_row_layout = QHBoxLayout(button_row)
        button_row_layout.setContentsMargins(0, 4, 0, 0)
        button_row_layout.setSpacing(8)
        self.generator_pipeline_run_all_button = QPushButton("Run all enabled", button_row)
        self.generator_pipeline_regen_button = QPushButton("Regenerate skeleton", button_row)
        self.generator_pipeline_export_button = QPushButton("Export debug report", button_row)
        self.generator_pipeline_run_all_button.clicked.connect(self._run_all_enabled_generator_pipeline_passes)
        self.generator_pipeline_regen_button.clicked.connect(self._regenerate_generator_pipeline_skeleton)
        self.generator_pipeline_export_button.clicked.connect(self._export_generator_pipeline_debug_report)
        button_row_layout.addWidget(self.generator_pipeline_run_all_button, 0)
        button_row_layout.addWidget(self.generator_pipeline_regen_button, 0)
        button_row_layout.addWidget(self.generator_pipeline_export_button, 0)
        button_row_layout.addStretch(1)
        section.body_layout.addWidget(button_row)
        return section

    def _generator_enabled_passes(self) -> tuple[str, ...]:
        if not hasattr(self, "generator_pipeline_checkboxes"):
            return tuple(TOGGLEABLE_PIPELINE_PASSES)
        return tuple(
            pass_name
            for pass_name in TOGGLEABLE_PIPELINE_PASSES
            if bool(self.generator_pipeline_checkboxes.get(pass_name) and self.generator_pipeline_checkboxes[pass_name].isChecked())
        )

    def _on_generator_pipeline_pass_toggled(self, pass_name: str, checked: bool) -> None:
        if pass_name not in TOGGLEABLE_PIPELINE_PASSES:
            return
        self._settings.setValue(self._pipeline_pass_enabled_setting_key(pass_name), bool(checked))
        if self._generator_pipeline_state is not None:
            self._generator_pipeline_state.params = replace(
                self._generator_pipeline_state.params,
                enabled_passes=self._generator_enabled_passes(),
            )
        self._refresh_generator_pipeline_ui()

    def _generator_pipeline_pass_has_snapshot(self, pass_name: str) -> bool:
        if self._generator_pipeline_state is None:
            return False
        return any(name == str(pass_name) for name, _pattern in self._generator_pipeline_state.snapshots)

    def _generator_pipeline_pass_logged(self, pass_name: str) -> bool:
        state = self._generator_pipeline_state
        if state is None:
            return False
        return any(
            entry.passe == str(pass_name)
            for entries in state.log.steps.values()
            for entry in entries
        )

    def _clear_generator_pipeline_state(self) -> None:
        self._generator_pipeline_state = None
        self._refresh_generator_pipeline_ui()

    def _apply_generator_pattern_update(
        self,
        pattern: GeneratedBreakPattern,
        *,
        status_text: str,
        info_text: str | None = None,
    ) -> None:
        generator_playing = self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
        self._generated_pattern = pattern
        self._generator_live_changes_pending = generator_playing
        self._populate_generated_pattern(pattern)
        if generator_playing and self._queue_live_generator_preview_refresh():
            if info_text:
                self.generator_info_label.setText(info_text)
            self._refresh_control_states(status_text)
            return
        self._refresh_generated_pattern_state()
        if info_text:
            self.generator_info_label.setText(info_text)
        self._refresh_control_states(status_text)

    def _generator_pipeline_source_result(self) -> DrumDetectionResult | None:
        if self._result is None:
            QMessageBox.warning(self, "Analyse requise", "Analyse d'abord un break avant d'utiliser le pipeline manuel.")
            return None
        source_result = self._effective_generator_result(self._result)
        if source_result is None or not source_result.transient_hits:
            QMessageBox.warning(self, "Transients manquants", "Le break courant ne contient aucun transient exploitable.")
            return None
        if self._analysis_stale:
            QMessageBox.information(
                self,
                "Recalcul requis",
                "La waveform a ete modifiee. Relance d'abord un rebuild ou une analyse avant d'utiliser le pipeline manuel.",
            )
            return None
        return source_result

    def _generator_pipeline_seed(self) -> int:
        if self._generator_pipeline_state is not None:
            return int(self._generator_pipeline_state.current.seed)
        if self._generated_pattern is not None:
            return int(self._generated_pattern.seed)
        seed_text = str(self.generator_seed_value.text() or "").strip()
        if seed_text.isdigit():
            return max(1, int(seed_text))
        return int(secrets.randbelow(999_999_999) + 1)

    def _regenerate_generator_pipeline_skeleton(self) -> bool:
        source_result = self._generator_pipeline_source_result()
        if source_result is None:
            return False

        seed = self._generator_pipeline_seed()
        params = self._generator_params(seed=seed)
        use_hybrid = self._generator_mode() == GENERATOR_MODE_HYBRID
        active_anchors = self._generator_active_step_anchors(step_count=max(16, int(params.bars) * 16))
        state = generate_break_skeleton_only(
            list(source_result.transient_hits),
            list(source_result.hit_sequences),
            params,
            anchors=active_anchors,
            use_hybrid=use_hybrid,
            user_motifs=self._generator_user_motifs,
        )
        self._generator_pipeline_state = state
        self._apply_generator_pattern_update(
            state.current,
            status_text="Skeleton de generation regenere.",
            info_text="Pipeline manuel: skeleton regenere sans passes tardives.",
        )
        self._refresh_generator_pipeline_ui()
        return True

    def _ensure_generator_pipeline_state(self) -> bool:
        if self._generator_pipeline_state is not None:
            return True
        return self._regenerate_generator_pipeline_skeleton()

    def _run_generator_pipeline_pass(self, pass_name: str) -> None:
        if pass_name == "skeleton":
            self._regenerate_generator_pipeline_skeleton()
            return
        if not self._ensure_generator_pipeline_state():
            return
        state = self._generator_pipeline_state
        if state is None:
            return

        pass_functions: dict[str, Callable[..., GeneratedBreakPattern]] = {
            "ghost_pass": apply_ghost_pass,
            "fill_pass": apply_fill_pass,
            "resolution_pass": apply_resolution_pass,
            "kick_roll_pass": apply_kick_roll_pass,
            "repeat_pass": apply_repeat_pass,
            "reverse_pass": apply_reverse_pass,
            "snare_stretch_pass": apply_snare_stretch_pass,
            "velocity_pass": apply_velocity_pass,
            "pitch_pass": apply_pitch_pass,
            "anchor_reapply": apply_anchor_reapply,
        }
        pass_function = pass_functions.get(pass_name)
        if pass_function is None:
            return

        current_params = self._generator_params(seed=int(state.current.seed))
        current_anchors = self._generator_active_step_anchors(step_count=int(state.current.step_count))
        state.params = replace(
            current_params,
            enabled_passes=self._generator_enabled_passes(),
        )
        state.anchors = dict(current_anchors)
        state.snapshot(pass_name)
        try:
            updated_pattern = pass_function(
                state.current,
                list(state.hits),
                state.params,
                log=state.log,
                anchors=current_anchors,
            )
        except Exception as exc:
            state.rollback_to(pass_name)
            QMessageBox.warning(self, "Pipeline manuel impossible", str(exc))
            self._refresh_generator_pipeline_ui()
            return

        state.current = updated_pattern
        state.params = updated_pattern.params
        self._apply_generator_pattern_update(
            updated_pattern,
            status_text=f"Passe {GENERATOR_PIPELINE_PASS_LABELS.get(pass_name, pass_name)} appliquee.",
            info_text=f"Pipeline manuel: {GENERATOR_PIPELINE_PASS_LABELS.get(pass_name, pass_name)} appliquee.",
        )
        self._refresh_generator_pipeline_ui()

    def _rollback_generator_pipeline_pass(self, pass_name: str) -> None:
        state = self._generator_pipeline_state
        if state is None:
            return
        if not state.rollback_to(pass_name):
            return
        self._apply_generator_pattern_update(
            state.current,
            status_text=f"Rollback {GENERATOR_PIPELINE_PASS_LABELS.get(pass_name, pass_name)}.",
            info_text=f"Pipeline manuel: retour a l'etat avant {GENERATOR_PIPELINE_PASS_LABELS.get(pass_name, pass_name)}.",
        )
        self._refresh_generator_pipeline_ui()

    def _run_all_enabled_generator_pipeline_passes(self) -> None:
        if not self._ensure_generator_pipeline_state():
            return
        state = self._generator_pipeline_state
        if state is None:
            return
        state.rollback_to("skeleton")
        current_params = self._generator_params(seed=int(state.current.seed))
        current_anchors = self._generator_active_step_anchors(step_count=int(state.current.step_count))
        state.params = replace(
            current_params,
            enabled_passes=self._generator_enabled_passes(),
        )
        state.anchors = dict(current_anchors)
        enabled_passes = set(self._generator_enabled_passes())
        pass_functions: dict[str, Callable[..., GeneratedBreakPattern]] = {
            "ghost_pass": apply_ghost_pass,
            "fill_pass": apply_fill_pass,
            "resolution_pass": apply_resolution_pass,
            "kick_roll_pass": apply_kick_roll_pass,
            "repeat_pass": apply_repeat_pass,
            "reverse_pass": apply_reverse_pass,
            "snare_stretch_pass": apply_snare_stretch_pass,
            "velocity_pass": apply_velocity_pass,
            "pitch_pass": apply_pitch_pass,
            "anchor_reapply": apply_anchor_reapply,
        }

        try:
            for pass_name in PIPELINE_PASS_ORDER:
                if pass_name == "skeleton" or pass_name not in enabled_passes:
                    continue
                pass_function = pass_functions.get(pass_name)
                if pass_function is None:
                    continue
                state.snapshot(pass_name)
                state.current = pass_function(
                    state.current,
                    list(state.hits),
                    state.params,
                    log=state.log,
                    anchors=current_anchors,
                )
                state.params = state.current.params
        except Exception as exc:
            QMessageBox.warning(self, "Pipeline manuel impossible", str(exc))
            self._refresh_generator_pipeline_ui()
            return

        self._apply_generator_pattern_update(
            state.current,
            status_text="Toutes les passes actives ont ete appliquees au skeleton courant.",
            info_text="Pipeline manuel: toutes les passes actives ont ete appliquees.",
        )
        self._refresh_generator_pipeline_ui()

    def _export_generator_pipeline_debug_report(self) -> None:
        state = self._generator_pipeline_state
        if state is None:
            QMessageBox.information(
                self,
                "Pipeline requis",
                "Regeneres d'abord un skeleton ou applique une passe manuelle avant d'exporter le debug report courant.",
            )
            return
        self._show_generation_debug_report_dialog(state.log.report(), seed=int(state.current.seed))

    def _refresh_generator_pipeline_ui(self) -> None:
        advanced_mode = self._generator_view_mode() == GENERATOR_VIEW_MODE_ADVANCED
        visible = advanced_mode and (not self._live_mode_enabled)
        base_enabled = (
            visible
            and (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
        )
        if hasattr(self, "generator_pipeline_section"):
            self.generator_pipeline_section.setVisible(visible)
        if not hasattr(self, "generator_pipeline_checkboxes"):
            return

        has_state = self._generator_pipeline_state is not None
        for pass_name in PIPELINE_PASS_ORDER:
            checkbox = self.generator_pipeline_checkboxes.get(pass_name)
            run_button = self.generator_pipeline_run_buttons.get(pass_name)
            rollback_button = self.generator_pipeline_rollback_buttons.get(pass_name)
            status_label = self.generator_pipeline_status_labels.get(pass_name)
            if checkbox is not None and pass_name != "skeleton":
                checkbox.setEnabled(base_enabled)
            if run_button is not None:
                if pass_name == "skeleton":
                    run_button.setEnabled(base_enabled and self._result is not None and (not self._analysis_stale))
                else:
                    run_button.setEnabled(base_enabled and (has_state or self._result is not None) and (not self._analysis_stale))
            if rollback_button is not None:
                rollback_button.setEnabled(base_enabled and has_state and self._generator_pipeline_pass_has_snapshot(pass_name))
            if status_label is not None:
                if not has_state:
                    status_label.setText("auto")
                elif pass_name == "skeleton":
                    status_label.setText("base")
                elif self._generator_pipeline_pass_logged(pass_name):
                    status_label.setText("applied")
                elif self._generator_pipeline_pass_has_snapshot(pass_name):
                    status_label.setText("snap")
                else:
                    status_label.setText("pending")

        if hasattr(self, "generator_pipeline_run_all_button"):
            self.generator_pipeline_run_all_button.setEnabled(base_enabled and self._result is not None and (not self._analysis_stale))
        if hasattr(self, "generator_pipeline_regen_button"):
            self.generator_pipeline_regen_button.setEnabled(base_enabled and self._result is not None and (not self._analysis_stale))
        if hasattr(self, "generator_pipeline_export_button"):
            self.generator_pipeline_export_button.setEnabled(base_enabled and has_state)

    def _generator_mode(self) -> str:
        current_mode = self.generator_mode_combo.currentData()
        return current_mode if current_mode in GENERATOR_MODE_LABELS else GENERATOR_MODE_CLASSIC

    def _generator_profile(self) -> str:
        current_profile = self.generator_profile_combo.currentData()
        return current_profile if current_profile in GENERATION_PROFILE_LABELS else GENERATION_PROFILE_MUSICAL

    def _motif_project_storage_path(self) -> Path:
        return Path.cwd() / USER_MOTIF_PROJECT_FILE

    def _load_generator_user_motifs(self) -> list[UserMotif]:
        storage_path = self._motif_project_storage_path()
        if not storage_path.exists():
            return []
        try:
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        raw_motifs = payload.get("user_motifs", ()) if isinstance(payload, dict) else payload
        if not isinstance(raw_motifs, list):
            return []
        motifs: list[UserMotif] = []
        for entry in raw_motifs:
            if not isinstance(entry, dict):
                continue
            try:
                motifs.append(UserMotif.from_dict(entry))
            except Exception:
                continue
        return motifs

    def _persist_generator_user_motifs(self) -> bool:
        storage_path = self._motif_project_storage_path()
        payload = {
            "user_motifs": [motif.to_dict() for motif in self._generator_user_motifs],
        }
        try:
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception:
            return False

    def _saved_pattern_storage_path(self) -> Path:
        return Path.cwd() / SAVED_PATTERN_PROJECT_FILE

    def _load_saved_pattern_snapshots(self) -> list[SavedPatternSnapshot]:
        storage_path = self._saved_pattern_storage_path()
        if not storage_path.exists():
            return []
        try:
            payload = json.loads(storage_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        raw_snapshots = payload.get("saved_patterns", ()) if isinstance(payload, dict) else payload
        if not isinstance(raw_snapshots, list):
            return []
        snapshots: list[SavedPatternSnapshot] = []
        for entry in raw_snapshots:
            if not isinstance(entry, dict):
                continue
            try:
                snapshot = SavedPatternSnapshot.from_dict(entry)
            except Exception:
                continue
            if snapshot.snapshot_id and snapshot.pattern_payload and snapshot.result_payload:
                snapshots.append(snapshot)
        return snapshots

    def _persist_saved_pattern_snapshots(self) -> bool:
        storage_path = self._saved_pattern_storage_path()
        payload = {
            "saved_patterns": [snapshot.to_dict() for snapshot in self._saved_pattern_snapshots],
        }
        try:
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception:
            return False

    @staticmethod
    def _saved_pattern_origin_label(origin: str) -> str:
        normalized = str(origin or "generator").strip().lower()
        if normalized == "generator":
            return "Generator"
        if normalized.startswith("live:"):
            return f"Live {normalized.split(':', 1)[1].upper()}"
        return normalized.title()

    @staticmethod
    def _saved_pattern_source_label(source_path: str | None) -> str:
        if not source_path:
            return "-"
        try:
            return Path(source_path).name or str(source_path)
        except Exception:
            return str(source_path)

    def _build_saved_pattern_snapshot(
        self,
        *,
        pattern: GeneratedBreakPattern,
        result: DrumDetectionResult,
        origin: str,
        mode: str,
        target_bpm: float,
    ) -> SavedPatternSnapshot:
        source_path = result.source_path or self._loaded_audio_path or self._current_resolved_path()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        source_label = self._saved_pattern_source_label(source_path)
        title = f"{source_label} | seed {int(pattern.seed)} | {timestamp}"
        return SavedPatternSnapshot(
            snapshot_id=secrets.token_hex(8),
            title=title,
            created_at=timestamp,
            source_path=source_path,
            origin=str(origin),
            mode=str(mode or GENERATOR_MODE_CLASSIC),
            target_bpm=float(target_bpm),
            detected_bpm_factor=float(self._detected_bpm_factor()),
            anchors=self._generator_active_step_anchors(step_count=int(pattern.step_count)),
            locked_steps=self._generator_active_locked_steps(step_count=int(pattern.step_count)),
            result_payload=result.to_dict(),
            pattern_payload=pattern.to_dict(),
        )

    def _refresh_saved_pattern_table(self, *, selected_id: str | None = None) -> None:
        if not hasattr(self, "saved_patterns_table"):
            return
        target_id = selected_id if selected_id is not None else self._saved_pattern_selected_id
        self.saved_patterns_table.setRowCount(len(self._saved_pattern_snapshots))
        row_to_select = -1
        for row, snapshot in enumerate(self._saved_pattern_snapshots):
            values = (
                snapshot.title,
                self._saved_pattern_origin_label(snapshot.origin),
                self._saved_pattern_source_label(snapshot.source_path),
                str(int(dict(snapshot.pattern_payload).get("seed", 0) or 0)),
                str(int(dict(snapshot.pattern_payload).get("bars", 0) or 0)),
                snapshot.created_at,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, snapshot.snapshot_id)
                if column in {1, 3, 4, 5}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.saved_patterns_table.setItem(row, column, item)
            if snapshot.snapshot_id == target_id:
                row_to_select = row
        self.saved_patterns_table.resizeRowsToContents()
        self._ensure_table_column_widths(self.saved_patterns_table, {0: 280, 1: 100, 2: 140, 3: 80, 4: 60, 5: 150})
        if row_to_select >= 0:
            self.saved_patterns_table.selectRow(row_to_select)
        elif self._saved_pattern_snapshots:
            self.saved_patterns_table.selectRow(0)
        else:
            self._saved_pattern_selected_id = None
        self._on_saved_pattern_selection_changed()

    def _selected_saved_pattern_snapshot(self) -> SavedPatternSnapshot | None:
        if not hasattr(self, "saved_patterns_table"):
            return None
        row = int(self.saved_patterns_table.currentRow())
        if row < 0 or row >= len(self._saved_pattern_snapshots):
            return None
        item = self.saved_patterns_table.item(row, 0)
        if item is None:
            return None
        snapshot_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        for snapshot in self._saved_pattern_snapshots:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        return self._saved_pattern_snapshots[row]

    def _on_saved_pattern_selection_changed(self) -> None:
        snapshot = self._selected_saved_pattern_snapshot()
        self._saved_pattern_selected_id = None if snapshot is None else snapshot.snapshot_id
        selected = snapshot is not None
        if hasattr(self, "saved_patterns_open_button"):
            self.saved_patterns_open_button.setEnabled(selected)
        if hasattr(self, "saved_patterns_delete_button"):
            self.saved_patterns_delete_button.setEnabled(selected)
        if hasattr(self, "saved_patterns_render_button"):
            self.saved_patterns_render_button.setEnabled(selected)
        if not hasattr(self, "saved_patterns_info_label"):
            return
        if snapshot is None:
            self.saved_patterns_info_label.setText(
                "Aucun break sauvegarde pour le projet courant. Clique sur l'etoile du Generator ou d'un slot Live pour en garder un."
            )
            return
        source_path = snapshot.source_path or "-"
        source_exists = bool(snapshot.source_path and Path(snapshot.source_path).exists())
        bars = int(dict(snapshot.pattern_payload).get("bars", 0) or 0)
        seed = int(dict(snapshot.pattern_payload).get("seed", 0) or 0)
        self.saved_patterns_info_label.setText(
            f"{snapshot.title}. Origine: {self._saved_pattern_origin_label(snapshot.origin)} | "
            f"BPM {float(snapshot.target_bpm):.1f} | Bars {bars} | Seed {seed} | "
            f"Source: {source_path}{'' if source_exists else ' (audio introuvable pour lecture/rendu)'}."
        )

    def _insert_saved_pattern_snapshot(self, snapshot: SavedPatternSnapshot) -> bool:
        self._saved_pattern_snapshots = [snapshot, *self._saved_pattern_snapshots]
        if not self._persist_saved_pattern_snapshots():
            self._saved_pattern_snapshots = [entry for entry in self._saved_pattern_snapshots if entry.snapshot_id != snapshot.snapshot_id]
            QMessageBox.warning(
                self,
                "Sauvegarde impossible",
                f"Impossible d'ecrire {self._saved_pattern_storage_path().name}.",
            )
            return False
        self._refresh_saved_pattern_table(selected_id=snapshot.snapshot_id)
        return True

    def _save_generated_pattern_snapshot(self) -> None:
        if self._result is None or self._generated_pattern is None:
            QMessageBox.information(
                self,
                "Break manquant",
                "Genere d'abord un pattern avant de le sauvegarder.",
            )
            return
        snapshot = self._build_saved_pattern_snapshot(
            pattern=self._generated_pattern,
            result=self._result,
            origin="generator",
            mode=self._generator_mode(),
            target_bpm=float(self.generator_target_bpm_spin.value()),
        )
        if not self._insert_saved_pattern_snapshot(snapshot):
            return
        self.generator_info_label.setText(
            f"Break sauvegarde dans {self._saved_pattern_storage_path().name}. Retrouve-le dans l'onglet Saved."
        )

    def _save_live_slot_snapshot(self, slot_name: str) -> None:
        slot = self._live_slots.get(str(slot_name))
        if self._result is None or slot is None or slot.pattern is None:
            QMessageBox.information(
                self,
                "Slot vide",
                f"Le slot {slot_name} n'a pas encore de pattern a sauvegarder.",
            )
            return
        target_bpm = (
            float(slot.preview.target_bpm)
            if slot.preview is not None
            else float(self.generator_target_bpm_spin.value())
        )
        snapshot = self._build_saved_pattern_snapshot(
            pattern=slot.pattern,
            result=self._result,
            origin=f"live:{str(slot_name).upper()}",
            mode=str(slot.mode or GENERATOR_MODE_CLASSIC),
            target_bpm=target_bpm,
        )
        if not self._insert_saved_pattern_snapshot(snapshot):
            return
        self._refresh_control_states(f"Slot {slot_name} sauvegarde dans l'onglet Saved.")

    def _delete_selected_saved_pattern(self) -> None:
        snapshot = self._selected_saved_pattern_snapshot()
        if snapshot is None:
            return
        self._saved_pattern_snapshots = [
            entry for entry in self._saved_pattern_snapshots if entry.snapshot_id != snapshot.snapshot_id
        ]
        if not self._persist_saved_pattern_snapshots():
            self._saved_pattern_snapshots = self._load_saved_pattern_snapshots()
            self._refresh_saved_pattern_table(selected_id=self._saved_pattern_selected_id)
            QMessageBox.warning(
                self,
                "Suppression impossible",
                f"Impossible de mettre a jour {self._saved_pattern_storage_path().name}.",
            )
            return
        self._refresh_saved_pattern_table()

    @staticmethod
    def _safe_export_stem(text: str) -> str:
        allowed = []
        for character in str(text or "generated_break"):
            if character.isalnum() or character in {"-", "_"}:
                allowed.append(character)
            elif character in {" ", "."}:
                allowed.append("_")
        stem = "".join(allowed).strip("_")
        return stem or "generated_break"

    def _default_pattern_render_path(
        self,
        *,
        pattern: GeneratedBreakPattern,
        source_path: str | None,
        title: str | None = None,
    ) -> Path:
        base_name = self._safe_export_stem(title or self._saved_pattern_source_label(source_path))
        return self._pattern_render_browse_dir(source_path) / f"{base_name}_seed_{int(pattern.seed)}.wav"

    def _pattern_render_browse_dir(self, source_path: str | None = None) -> Path:
        stored_dir = self._settings.value(RENDER_WAV_LAST_DIR_SETTINGS_KEY, "", type=str)
        if stored_dir:
            return Path(stored_dir).expanduser()
        normalized_source = self._normalize_recent_file_path(source_path)
        if normalized_source:
            candidate = Path(normalized_source).expanduser()
            if candidate.exists():
                return candidate.parent if candidate.is_file() else candidate
        return Path(self._current_browse_dir()).expanduser()

    def _remember_pattern_render_path(self, output_path: str | Path) -> None:
        destination = Path(output_path).expanduser()
        target_dir = destination.parent if destination.suffix else destination
        self._settings.setValue(RENDER_WAV_LAST_DIR_SETTINGS_KEY, str(target_dir))

    @staticmethod
    def _next_available_render_path(preferred_path: Path) -> Path:
        candidate = Path(preferred_path)
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        parent = candidate.parent
        index = 2
        while True:
            alternate = parent / f"{stem}_{index}{suffix}"
            if not alternate.exists():
                return alternate
            index += 1

    def _audio_snapshot_for_source_path(self, source_path: str | None) -> tuple[np.ndarray, int] | None:
        normalized_source = self._normalize_recent_file_path(source_path)
        loaded_source = self._normalize_recent_file_path(self._loaded_audio_path)
        if (
            normalized_source is not None
            and loaded_source is not None
            and normalized_source == loaded_source
            and self._loaded_audio_samples is not None
            and self._loaded_audio_sample_rate
        ):
            return (
                np.array(self._loaded_audio_samples, dtype=np.float32, copy=True),
                int(self._loaded_audio_sample_rate),
            )
        if normalized_source is not None and Path(normalized_source).exists():
            samples, _waveform_data, sample_rate, _duration_s = self._load_audio_for_waveform(Path(normalized_source))
            return np.array(samples, dtype=np.float32, copy=True), int(sample_rate)
        if (
            source_path is None
            and self._loaded_audio_samples is not None
            and self._loaded_audio_sample_rate
        ):
            return (
                np.array(self._loaded_audio_samples, dtype=np.float32, copy=True),
                int(self._loaded_audio_sample_rate),
            )
        return None

    def _render_pattern_to_wav_file(
        self,
        pattern: GeneratedBreakPattern,
        *,
        source_path: str | None,
        target_bpm: float,
        output_path: Path,
        gate: float,
        mono_choke: bool,
    ) -> RetimedPreview:
        audio_snapshot = self._audio_snapshot_for_source_path(source_path)
        if audio_snapshot is None:
            raise ValueError("Source audio introuvable. Recharge le break original ou remets le fichier source a sa place.")
        preview = build_pattern_preview(
            audio_snapshot[0],
            int(audio_snapshot[1]),
            pattern,
            target_bpm=float(target_bpm),
            gate=float(gate),
            mono_choke=bool(mono_choke),
        )
        export_audio = preview.loop_audio if preview.loop_audio is not None else preview.audio
        soundfile = _require_soundfile()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(output_path), export_audio, int(preview.sample_rate), subtype="PCM_16")
        return preview

    def _render_generated_pattern_to_wav(self) -> None:
        if self._generated_pattern is None:
            QMessageBox.information(self, "Pattern manquant", "Genere ou recharge d'abord un break avant de l'exporter.")
            return
        source_path = None if self._result is None else self._result.source_path
        default_path = self._default_pattern_render_path(
            pattern=self._generated_pattern,
            source_path=source_path,
        )
        save_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Render generated break",
            str(default_path),
            "Wave files (*.wav);;All files (*.*)",
        )
        if not save_path:
            return
        try:
            preview = self._render_pattern_to_wav_file(
                self._generated_pattern,
                source_path=source_path,
                target_bpm=float(self.generator_target_bpm_spin.value()),
                output_path=Path(save_path),
                gate=max(0.05, float(self.generator_gate_slider.value()) / 100.0),
                mono_choke=self._generator_mono_choke_enabled(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Render impossible", str(exc))
            return
        self._remember_pattern_render_path(save_path)
        self.generator_info_label.setText(
            f"Render WAV exporte dans {Path(save_path).name} ({preview.loop_duration_s:.2f}s, une loop exacte)."
        )

    def _render_selected_saved_pattern_to_wav(self) -> None:
        snapshot = self._selected_saved_pattern_snapshot()
        if snapshot is None:
            return
        try:
            pattern = self._generated_break_pattern_from_payload(snapshot.pattern_payload)
        except Exception as exc:
            QMessageBox.warning(self, "Snapshot invalide", str(exc))
            return
        default_path = self._default_pattern_render_path(
            pattern=pattern,
            source_path=snapshot.source_path,
            title=snapshot.title,
        )
        save_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Render saved break",
            str(default_path),
            "Wave files (*.wav);;All files (*.*)",
        )
        if not save_path:
            return
        try:
            preview = self._render_pattern_to_wav_file(
                pattern,
                source_path=snapshot.source_path,
                target_bpm=float(snapshot.target_bpm),
                output_path=Path(save_path),
                gate=max(0.05, float(pattern.params.gate)),
                mono_choke=bool(pattern.params.mono_choke),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Render impossible", str(exc))
            return
        self._remember_pattern_render_path(save_path)
        self.saved_patterns_info_label.setText(
            f"Render WAV exporte dans {Path(save_path).name} ({preview.loop_duration_s:.2f}s, une loop exacte)."
        )

    def _quick_render_live_active_slot(self) -> None:
        active_slot_name = str(self._live_active_slot)
        slot = self._live_slots.get(active_slot_name)
        if slot is None or slot.pattern is None:
            QMessageBox.information(self, "Slot actif vide", "Le slot actif n'a pas encore de break a exporter.")
            return
        source_path = None if self._result is None else self._result.source_path
        preferred_path = self._default_pattern_render_path(
            pattern=slot.pattern,
            source_path=source_path,
            title=f"{self._saved_pattern_source_label(source_path)}_live_slot_{active_slot_name}",
        )
        output_path = self._next_available_render_path(preferred_path)
        target_bpm = self._effective_preview_target_bpm(slot.preview)
        try:
            preview = self._render_pattern_to_wav_file(
                slot.pattern,
                source_path=source_path,
                target_bpm=float(target_bpm),
                output_path=output_path,
                gate=max(0.05, float(slot.pattern.params.gate)),
                mono_choke=bool(slot.pattern.params.mono_choke),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Render live impossible", str(exc))
            return
        self._remember_pattern_render_path(output_path)
        self.live_mode_info_label.setText(
            f"Slot {active_slot_name} exporte dans {output_path.name} ({preview.loop_duration_s:.2f}s, dossier memorise)."
        )

    @staticmethod
    def _set_combo_current_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _apply_generator_params_to_controls(
        self,
        params: BreakPatternParams,
        *,
        mode: str,
        target_bpm: float,
        detected_bpm_factor: float,
    ) -> None:
        self._generator_bulk_param_update = True
        try:
            self.detected_bpm_factor_combo.blockSignals(True)
            self._set_detected_bpm_factor(float(detected_bpm_factor))
            self.detected_bpm_factor_combo.blockSignals(False)
            self._settings.setValue("detected_bpm_factor", float(self._detected_bpm_factor()))
            self.generator_target_bpm_spin.blockSignals(True)
            self.generator_target_bpm_spin.setValue(float(target_bpm))
            self.generator_target_bpm_spin.blockSignals(False)
            self._settings.setValue("generator_target_bpm", float(target_bpm))
            if hasattr(self, "live_target_bpm_spin"):
                self.live_target_bpm_spin.blockSignals(True)
                self.live_target_bpm_spin.setValue(float(target_bpm))
                self.live_target_bpm_spin.blockSignals(False)
            self._live_target_bpm_value = max(float(target_bpm), 1e-6)
            self.generator_bars_spin.blockSignals(True)
            self.generator_bars_spin.setValue(max(1, int(params.bars)))
            self.generator_bars_spin.blockSignals(False)
            self._settings.setValue("generator_bars", max(1, int(params.bars)))
            self._set_combo_current_data(self.generator_mode_combo, str(mode or GENERATOR_MODE_CLASSIC))
            self._set_combo_current_data(self.generator_profile_combo, str(params.generation_profile))
            self.generator_energy_slider.setValue(int(round(float(params.energy) * 100.0)))
            self.generator_kick_slider.setValue(int(round(float(params.kick_weight) * 100.0)))
            self.generator_snare_slider.setValue(int(round(float(params.snare_weight) * 100.0)))
            self.generator_hat_slider.setValue(int(round(float(params.hat_density) * 100.0)))
            self.generator_ghost_slider.setValue(int(round(float(params.ghost_density) * 100.0)))
            self.generator_synth_ghost_enabled_check.setChecked(bool(params.synth_ghost_enabled))
            self.generator_ghost_vel_min_slider.setValue(int(round(float(params.ghost_vel_range[0]) * 100.0)))
            self.generator_ghost_vel_max_slider.setValue(int(round(float(params.ghost_vel_range[1]) * 100.0)))
            self.generator_ghost_pitch_min_slider.setValue(int(round(float(params.ghost_pitch_range[0]) * 10.0)))
            self.generator_ghost_pitch_max_slider.setValue(int(round(float(params.ghost_pitch_range[1]) * 10.0)))
            self.generator_ghost_gate_slider.setValue(int(round(float(params.ghost_gate_ratio) * 100.0)))
            self.generator_fill_slider.setValue(int(round(float(params.fill_strength) * 100.0)))
            forced_fill_style = FILL_STYLE_AUTO
            if params.fill_type_weights and len(params.fill_type_weights) == 1:
                forced_fill_style = next(iter(params.fill_type_weights.keys()))
            self._set_combo_current_data(self.generator_fill_style_combo, forced_fill_style)
            self.generator_repeat_slider.setValue(int(round(float(params.repeat_density) * 100.0)))
            self.generator_repeat_length_slider.setValue(int(round(float(params.repeat_span) * 100.0)))
            self.generator_repeat_rate_slider.setValue(int(round(float(params.repeat_rate) * 100.0)))
            self.generator_reverse_slider.setValue(int(round(float(params.reverse_density) * 100.0)))
            self.generator_kick_roll_slider.setValue(int(round(float(params.kick_roll_density) * 100.0)))
            self.generator_kick_roll_length_slider.setValue(int(round(float(params.kick_roll_span) * 100.0)))
            self.generator_kick_roll_contrast_slider.setValue(int(round(float(params.kick_roll_contrast) * 100.0)))
            self.generator_snare_stretch_slider.setValue(int(round(float(params.snare_stretch_density) * 100.0)))
            self.generator_snare_stretch_length_slider.setValue(int(round(float(params.snare_stretch_span) * 100.0)))
            self.generator_snare_stretch_amount_slider.setValue(int(round(float(params.snare_stretch_amount) * 100.0)))
            self._set_combo_current_data(self.generator_snare_stretch_curve_combo, str(params.snare_stretch_vel_curve))
            self.generator_gate_slider.setValue(int(round(float(params.gate) * 100.0)))
            self.generator_mono_choke_check.setChecked(bool(params.mono_choke))
            self.generator_position_fidelity_slider.setValue(int(round(float(params.position_fidelity) * 100.0)))
            self.generator_sequence_density_slider.setValue(int(round(float(params.sequence_density) * 100.0)))
            self.generator_motif_density_slider.setValue(int(round(float(params.motif_density) * 100.0)))
            self.generator_velocity_slider.setValue(int(round(float(params.velocity_spread) * 100.0)))
            self.generator_swing_slider.setValue(int(round(float(params.swing) * 100.0)))
            self.generator_anti_repeat_slider.setValue(int(round(float(params.anti_repeat) * 100.0)))
            self.generator_breath_slider.setValue(int(round(float(params.breath_factor) * 100.0)))
            self.generator_sequence_max_len_spin.setValue(max(2, int(params.sequence_max_len)))
            self.generator_sequence_role_lock_check.setChecked(bool(params.sequence_role_lock))
            self._set_combo_current_data(self.generator_pitch_mode_combo, str(params.pitch_mode))
            self._set_combo_current_data(self.generator_pitch_scope_combo, str(params.pitch_scope))
            self._set_combo_current_data(self.generator_pitch_scale_combo, str(params.pitch_scale))
            self.generator_pitch_root_slider.setValue(int(params.pitch_root))
            self.generator_pitch_amount_slider.setValue(int(round(float(params.pitch_amount) * 100.0)))
            self.generator_pitch_range_min_slider.setValue(int(round(float(params.pitch_range[0]))))
            self.generator_pitch_range_max_slider.setValue(int(round(float(params.pitch_range[1]))))
            self._set_combo_current_data(self.generator_pitch_rate_combo, str(params.pitch_rate))
            self.generator_pitch_sequence_input.setText(", ".join(f"{value:g}" for value in params.pitch_sequence))
            self._set_combo_current_data(self.generator_pitch_curve_combo, str(params.pitch_curve))
            self.generator_pitch_curve_min_slider.setValue(int(round(float(params.pitch_curve_range[0]))))
            self.generator_pitch_curve_max_slider.setValue(int(round(float(params.pitch_curve_range[1]))))
            if hasattr(self, "generator_pipeline_checkboxes"):
                enabled_passes = set(str(entry) for entry in params.enabled_passes)
                for pass_name, checkbox in self.generator_pipeline_checkboxes.items():
                    checkbox.setChecked(pass_name in enabled_passes)
        finally:
            self._generator_bulk_param_update = False
        self._refresh_generator_mode_ui()
        self._refresh_generator_fill_style_label()
        self._refresh_generator_pitch_ui()
        self._refresh_generator_ghost_ui()
        self._refresh_generator_probability_preview()

    def _apply_saved_pattern_snapshot(self, snapshot: SavedPatternSnapshot) -> None:
        try:
            restored_result = self._detection_result_from_payload(snapshot.result_payload)
            restored_pattern = self._generated_break_pattern_from_payload(snapshot.pattern_payload)
        except Exception as exc:
            QMessageBox.warning(self, "Snapshot invalide", str(exc))
            return

        normalized_source = self._normalize_recent_file_path(snapshot.source_path)
        if normalized_source:
            self.path_input.setText(normalized_source)
            self._push_recent_file(normalized_source)
            self._refresh_recent_files_combo(normalized_source)
            self._settings.setValue("last_path", normalized_source)
            self._settings.setValue("last_dir", str(Path(normalized_source).expanduser().parent))

        self._stop_retimed_preview(update_status=False)
        self._analysis_stale = False
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._generator_step_anchors = {
            int(step): str(anchor)
            for step, anchor in snapshot.anchors.items()
            if str(anchor) in GENERATOR_STEP_ANCHOR_LABELS
        }
        self._generator_locked_steps = {int(step) for step in snapshot.locked_steps}
        self._apply_generator_params_to_controls(
            restored_pattern.params,
            mode=snapshot.mode,
            target_bpm=float(snapshot.target_bpm),
            detected_bpm_factor=float(snapshot.detected_bpm_factor),
        )
        self._result = restored_result
        self._generated_pattern = restored_pattern
        self._populate_result(restored_result)
        self._populate_hits(restored_result)
        self._apply_hits_to_waveform(restored_result, preserve_existing=False)
        self._update_retimed_preview_state(restored_result)
        self._populate_generated_pattern(restored_pattern)
        self._refresh_saved_pattern_table(selected_id=snapshot.snapshot_id)
        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentWidget(self._main_tab_pages[MAIN_TAB_GENERATOR])
        normalized_source = self._normalize_recent_file_path(snapshot.source_path)
        audio_available = bool(
            (
                normalized_source is not None
                and (
                    (
                        self._normalize_recent_file_path(self._loaded_audio_path) == normalized_source
                        and self._loaded_audio_samples is not None
                        and self._loaded_audio_sample_rate
                    )
                    or Path(normalized_source).exists()
                )
            )
            or (
                snapshot.source_path is None
                and self._loaded_audio_samples is not None
                and self._loaded_audio_sample_rate
            )
        )
        source_note = (
            ""
            if audio_available
            else " Recharge l'audio source si tu veux le relire ou rerender."
        )
        self._refresh_control_states(
            f"Snapshot recharge: {snapshot.title}.{source_note}"
        )

    def _open_selected_saved_pattern(self) -> None:
        snapshot = self._selected_saved_pattern_snapshot()
        if snapshot is None:
            return
        normalized_source = self._normalize_recent_file_path(snapshot.source_path)
        loaded_source = self._normalize_recent_file_path(self._loaded_audio_path)
        if (
            normalized_source is not None
            and Path(normalized_source).exists()
            and (
                loaded_source != normalized_source
                or self._loaded_audio_samples is None
                or not self._loaded_audio_sample_rate
            )
        ):
            self._pending_saved_snapshot_restore = snapshot
            self._handle_path_selected(normalized_source)
            self.saved_patterns_info_label.setText(
                f"Chargement de {snapshot.title} en cours. Le snapshot sera reapplique des que le break source sera pret."
            )
            return
        self._pending_saved_snapshot_restore = None
        self._apply_saved_pattern_snapshot(snapshot)

    def _generator_motif_steps_preview_text(self, steps: list[str | None]) -> str:
        parts: list[str] = []
        for step in steps:
            if step is None:
                parts.append("·")
            else:
                parts.append(GENERATOR_STEP_ANCHOR_SHORT_LABELS.get(step, str(step)[:1].upper()))
        return " ".join(parts)

    def _current_generator_motif_editor_steps(self) -> list[str | None]:
        length = int(self.generator_motif_length_spin.value())
        return [self._generator_motif_editor_steps[index] for index in range(length)]

    def _current_generator_editor_motif(self) -> UserMotif | None:
        steps = self._current_generator_motif_editor_steps()
        if not any(step is not None for step in steps):
            return None
        dominant_type = str(self.generator_motif_dominant_combo.currentData() or "mixed")
        if not self._generator_motif_dominant_dirty:
            dominant_type = self._infer_generator_motif_dominant()
        return UserMotif(
            steps=[*steps],
            base_prob=float(self.generator_motif_base_prob_slider.value() / 100.0),
            role=str(self.generator_motif_role_combo.currentData() or "groove"),
            dominant_type=dominant_type,
            name=self.generator_motif_name_input.text().strip() or "Motif",
        )

    def _infer_generator_motif_dominant(self) -> str:
        steps = self._current_generator_motif_editor_steps()
        counts = {"kick": 0, "snare": 0, "hat": 0, "ghost": 0}
        for step in steps:
            if step in counts:
                counts[str(step)] += 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] <= 0:
            return "mixed"
        if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
            return "mixed"
        return str(ranked[0][0])

    def _refresh_generator_motif_editor_dominant(self) -> None:
        inferred = self._infer_generator_motif_dominant()
        self.generator_motif_inferred_label.setText(f"Infer: {'Mixed' if inferred == 'mixed' else inferred}")
        if not self._generator_motif_dominant_dirty:
            previous_state = self.generator_motif_dominant_combo.blockSignals(True)
            try:
                inferred_index = self.generator_motif_dominant_combo.findData(inferred)
                if inferred_index >= 0:
                    self.generator_motif_dominant_combo.setCurrentIndex(inferred_index)
            finally:
                self.generator_motif_dominant_combo.blockSignals(previous_state)
        self._refresh_generator_motif_editor_effective_label()

    def _refresh_generator_motif_editor_effective_label(self) -> None:
        motif = self._current_generator_editor_motif()
        if motif is None:
            self.generator_motif_effective_label.setText("Eff.: 0%")
            self.generator_motif_effective_label.setToolTip("Ajoute au moins un step explicite pour estimer la probabilite du motif.")
            return
        effective_probability = self._effective_generator_user_motif_probability(motif)
        self.generator_motif_effective_label.setText(f"Eff.: {int(round(effective_probability * 100.0))}%")
        self.generator_motif_effective_label.setToolTip(
            "Probabilite effective avec les reglages courants, apres modulation par "
            "Motifs, type dominant, energie, anti-repeat, fill et position."
        )

    def _refresh_generator_motif_editor_buttons(self) -> None:
        active_length = int(self.generator_motif_length_spin.value())
        for index, button in enumerate(self.generator_motif_editor_buttons):
            active = index < active_length
            value = self._generator_motif_editor_steps[index] if active else None
            button.setVisible(True)
            button.setEnabled(active)
            button.setText("·" if value is None else GENERATOR_STEP_ANCHOR_SHORT_LABELS.get(value, str(value)[:1].upper()))
            button.setProperty("anchorActive", bool(value))
            button.setProperty("anchorKind", "auto" if value is None else value)
            button.style().unpolish(button)
            button.style().polish(button)
            button.setToolTip(
                f"Step {index + 1} du motif utilisateur: {GENERATOR_STEP_ANCHOR_LABELS.get(value, 'trou') if value is not None else 'trou'}.\n"
                "Clique pour cycler kick / snare / hat / ghost / silence / trou."
            )

    def _generator_pitch_mode(self) -> str:
        return str(self.generator_pitch_mode_combo.currentData() or "off").strip().lower()

    def _generator_view_mode(self) -> str:
        return str(self.generator_view_mode_combo.currentData() or GENERATOR_VIEW_MODE_ADVANCED).strip().lower()

    def _generator_display_preset(self) -> str:
        return str(
            self.generator_display_preset_combo.currentData() or GENERATOR_DISPLAY_PRESET_BALANCED
        ).strip().lower()

    def _on_generator_view_mode_changed(self) -> None:
        self._settings.setValue("generator_view_mode", self._generator_view_mode())
        self._refresh_generator_ux_mode()
        self._refresh_generator_pitch_ui()
        self._refresh_generator_ghost_ui()

    def _on_generator_display_preset_changed(self) -> None:
        self._apply_generator_display_preset(self._generator_display_preset(), persist=True)

    def _apply_generator_display_preset(self, preset: str | None, *, persist: bool = True) -> None:
        normalized_preset = str(preset or GENERATOR_DISPLAY_PRESET_BALANCED).strip().lower()
        if normalized_preset not in GENERATOR_DISPLAY_PRESET_LABELS:
            normalized_preset = GENERATOR_DISPLAY_PRESET_BALANCED
        if persist:
            self._settings.setValue("generator_display_preset", normalized_preset)

        results_sizes = {
            GENERATOR_DISPLAY_PRESET_BALANCED: [760, 420],
            GENERATOR_DISPLAY_PRESET_PERFORMANCE: [860, 260],
            GENERATOR_DISPLAY_PRESET_INSPECTOR: [620, 560],
        }
        if hasattr(self, "results_splitter"):
            self.results_splitter.setSizes(results_sizes[normalized_preset])

        candidates_expanded = normalized_preset != GENERATOR_DISPLAY_PRESET_PERFORMANCE
        json_expanded = normalized_preset == GENERATOR_DISPLAY_PRESET_INSPECTOR
        probability_expanded = normalized_preset == GENERATOR_DISPLAY_PRESET_INSPECTOR
        details_expanded = normalized_preset == GENERATOR_DISPLAY_PRESET_INSPECTOR
        pipeline_expanded = normalized_preset != GENERATOR_DISPLAY_PRESET_PERFORMANCE
        motifs_expanded = normalized_preset != GENERATOR_DISPLAY_PRESET_PERFORMANCE
        live_expanded = normalized_preset != GENERATOR_DISPLAY_PRESET_BALANCED
        live_stems_expanded = normalized_preset == GENERATOR_DISPLAY_PRESET_INSPECTOR
        live_fx_expanded = normalized_preset != GENERATOR_DISPLAY_PRESET_BALANCED

        if hasattr(self, "candidates_section"):
            self.candidates_section.setExpanded(candidates_expanded)
        if hasattr(self, "json_section"):
            self.json_section.setExpanded(json_expanded)
        if hasattr(self, "generator_probability_section"):
            self.generator_probability_section.setExpanded(probability_expanded)
        if hasattr(self, "generator_pattern_details_section"):
            self.generator_pattern_details_section.setExpanded(details_expanded)
        if hasattr(self, "generator_pipeline_section"):
            self.generator_pipeline_section.setExpanded(pipeline_expanded)
        if hasattr(self, "generator_motifs_section"):
            self.generator_motifs_section.setExpanded(motifs_expanded)
        if hasattr(self, "generator_live_section"):
            self.generator_live_section.setExpanded(live_expanded)
        if hasattr(self, "live_stems_section"):
            self.live_stems_section.setExpanded(live_stems_expanded)
        if hasattr(self, "live_fx_section"):
            self.live_fx_section.setExpanded(live_fx_expanded)

    def _refresh_generator_ux_mode(self) -> None:
        advanced_mode = self._generator_view_mode() == GENERATOR_VIEW_MODE_ADVANCED
        hybrid_mode = self._generator_mode() == GENERATOR_MODE_HYBRID
        advanced_details_visible = advanced_mode
        motifs_visible = hybrid_mode

        if hasattr(self, "generator_probability_section"):
            self.generator_probability_section.setVisible(advanced_details_visible)
        for widget_name in (
            "generator_probability_label",
            "generator_probability_table",
            "generator_effect_probability_label",
            "generator_effect_probability_table",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setVisible(advanced_details_visible)
        if hasattr(self, "generator_pattern_details_section"):
            self.generator_pattern_details_section.setVisible(advanced_details_visible)
        if hasattr(self, "generator_table"):
            self.generator_table.setVisible(advanced_details_visible)
        if hasattr(self, "generator_sequence_max_label"):
            self.generator_sequence_max_label.setVisible(True)
        if hasattr(self, "generator_sequence_max_len_spin"):
            self.generator_sequence_max_len_spin.setVisible(True)
        if hasattr(self, "generator_sequence_role_lock_label"):
            self.generator_sequence_role_lock_label.setVisible(True)
        if hasattr(self, "generator_sequence_role_lock_check"):
            self.generator_sequence_role_lock_check.setVisible(True)
        if hasattr(self, "generator_motif_editor_box"):
            self.generator_motif_editor_box.setVisible(motifs_visible)
        if hasattr(self, "generator_saved_motifs_box"):
            self.generator_saved_motifs_box.setVisible(motifs_visible)
        if hasattr(self, "generator_motifs_section"):
            self.generator_motifs_section.setVisible(motifs_visible)
        if hasattr(self, "generator_pipeline_section"):
            self.generator_pipeline_section.setVisible(advanced_mode and (not self._live_mode_enabled))
        if hasattr(self, "generator_sequence_table"):
            self.generator_sequence_table.setVisible(True)
        if hasattr(self, "generator_summary_label"):
            self.generator_summary_label.setVisible(True)
        self._refresh_generator_pipeline_ui()

    def _parsed_generator_pitch_sequence(self) -> list[float]:
        raw_text = self.generator_pitch_sequence_input.text().strip()
        if not raw_text:
            return []
        values: list[float] = []
        for chunk in raw_text.split(","):
            token = chunk.strip()
            if not token:
                continue
            try:
                values.append(float(np.clip(float(token), -24.0, 24.0)))
            except ValueError:
                continue
        return values

    def _refresh_generator_pitch_ui(self) -> None:
        mode = self._generator_pitch_mode()
        active = mode != "off"
        any_busy = bool(
            getattr(self, "_analysis_busy", False)
            or getattr(self, "_preview_busy", False)
            or getattr(self, "_waveform_loading", False)
            or getattr(self, "_generator_busy", False)
        )
        sequence_visible = mode == "sequence"
        curve_visible = mode == "curve"
        random_like = mode == "random"

        self.generator_pitch_box.setVisible(True)

        for widget in (
            self.generator_pitch_scope_combo,
            self.generator_pitch_scale_combo,
            self.generator_pitch_root_slider,
            self.generator_pitch_root_value,
            self.generator_pitch_amount_slider,
            self.generator_pitch_amount_value,
            self.generator_pitch_rate_combo,
        ):
            widget.setEnabled(active and (not any_busy))

        for widget in (
            self.generator_pitch_range_min_slider,
            self.generator_pitch_range_min_value,
            self.generator_pitch_range_max_slider,
            self.generator_pitch_range_max_value,
        ):
            widget.setEnabled(random_like and (not any_busy))

        self.generator_pitch_sequence_label.setVisible(sequence_visible)
        self.generator_pitch_sequence_input.setVisible(sequence_visible)
        self.generator_pitch_sequence_input.setEnabled(sequence_visible and (not any_busy))

        self.generator_pitch_curve_label.setVisible(curve_visible)
        self.generator_pitch_curve_combo.setVisible(curve_visible)
        self.generator_pitch_curve_range_label.setVisible(curve_visible)
        self.generator_pitch_curve_min_slider.setVisible(curve_visible)
        self.generator_pitch_curve_min_value.setVisible(curve_visible)
        self.generator_pitch_curve_max_slider.setVisible(curve_visible)
        self.generator_pitch_curve_max_value.setVisible(curve_visible)
        for widget in (
            self.generator_pitch_curve_combo,
            self.generator_pitch_curve_min_slider,
            self.generator_pitch_curve_min_value,
            self.generator_pitch_curve_max_slider,
            self.generator_pitch_curve_max_value,
        ):
            widget.setEnabled(curve_visible and (not any_busy))

    def _refresh_generator_ghost_ui(self) -> None:
        visible = int(self.generator_ghost_slider.value()) > 0
        any_busy = bool(
            getattr(self, "_analysis_busy", False)
            or getattr(self, "_preview_busy", False)
            or getattr(self, "_waveform_loading", False)
            or getattr(self, "_generator_busy", False)
        )
        synth_enabled = bool(self.generator_synth_ghost_enabled_check.isChecked())
        self.generator_ghost_synthesis_box.setVisible(visible)
        self.generator_synth_ghost_enabled_check.setEnabled(visible and (not any_busy))
        for widget in (
            self.generator_ghost_vel_min_slider,
            self.generator_ghost_vel_min_value,
            self.generator_ghost_vel_max_slider,
            self.generator_ghost_vel_max_value,
            self.generator_ghost_pitch_min_slider,
            self.generator_ghost_pitch_min_value,
            self.generator_ghost_pitch_max_slider,
            self.generator_ghost_pitch_max_value,
            self.generator_ghost_gate_slider,
            self.generator_ghost_gate_value,
        ):
            widget.setEnabled(visible and synth_enabled and (not any_busy))

    def _refresh_generator_mode_ui(self) -> None:
        hybrid_mode = self._generator_mode() == GENERATOR_MODE_HYBRID
        self.generator_motif_save_button.setEnabled(hybrid_mode and (not self._generator_busy))
        waveform_loading = bool(getattr(self, "_waveform_loading", False))
        self.generator_motif_density_slider.setEnabled(hybrid_mode and (not self._generator_busy) and (not waveform_loading))
        self.generator_motif_density_value.setEnabled(hybrid_mode)
        self._refresh_live_mode_visibility()
        self._refresh_generator_ux_mode()
        self._refresh_generator_pitch_ui()
        self._refresh_generator_ghost_ui()

    def _effective_generator_user_motif_probability(self, motif: UserMotif) -> float:
        params = self._generator_params(seed=1)
        return float(np.clip(estimate_user_motif_effective_probability(motif, params), 0.0, 1.0))

    def _build_saved_motif_probability_widget(self, row: int, motif: UserMotif) -> QWidget:
        container = QWidget(self.generator_saved_motifs_table)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        slider = QSlider(Qt.Orientation.Horizontal, container)
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setValue(int(round(float(motif.base_prob) * 100.0)))
        slider.setToolTip("Probabilite de base du motif utilisateur. Elle est ensuite modulee par les reglages actifs.")
        slider.valueChanged.connect(
            lambda value, current_row=int(row): self._on_saved_generator_motif_probability_changed(current_row, value)
        )

        label = QLabel(f"{int(round(float(motif.base_prob) * 100.0))}%", container)
        label.setObjectName("StatusLabel")
        label.setMinimumWidth(38)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(lambda value, target=label: target.setText(f"{int(np.clip(value, 0, 100))}%"))

        layout.addWidget(slider, 1)
        layout.addWidget(label)
        return container

    def _on_saved_generator_motif_probability_changed(self, row: int, value: int) -> None:
        if row < 0 or row >= len(self._generator_user_motifs):
            return
        motif = self._generator_user_motifs[row]
        normalized_value = float(np.clip(int(value), 0, 100)) / 100.0
        if abs(float(motif.base_prob) - normalized_value) <= 1e-6:
            return
        self._generator_user_motifs[row] = replace(motif, base_prob=normalized_value)
        self._persist_generator_user_motifs()
        self._refresh_generator_user_motif_table()
        self.generator_info_label.setText(
            f"Probabilite du motif utilisateur '{motif.name}' mise a jour a {int(round(normalized_value * 100.0))}%."
        )

    def _refresh_generator_user_motif_table(self) -> None:
        if not hasattr(self, "generator_saved_motifs_table"):
            return
        motifs = list(self._generator_user_motifs)
        self.generator_saved_motifs_table.setRowCount(len(motifs))
        self.generator_saved_motifs_label.setText(
            f"{len(motifs)} motif(s) utilisateur pour {self._motif_project_storage_path().name}."
            if motifs
            else "Aucun motif utilisateur sauvegarde pour ce projet."
        )
        for row, motif in enumerate(motifs):
            effective_probability = self._effective_generator_user_motif_probability(motif)
            values_by_column = {
                0: motif.name,
                1: self._generator_motif_steps_preview_text(list(motif.steps)),
                2: motif.role,
                3: motif.dominant_type,
                5: f"{int(round(effective_probability * 100.0))}%",
            }
            for column, value in values_by_column.items():
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if column >= 2 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.generator_saved_motifs_table.setItem(row, column, item)
            self.generator_saved_motifs_table.setCellWidget(row, 4, self._build_saved_motif_probability_widget(row, motif))
            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(lambda _checked=False, current_row=int(row): self._delete_generator_user_motif(current_row))
            self.generator_saved_motifs_table.setCellWidget(row, 6, delete_button)

    def _clear_generator_motif_editor(self) -> None:
        self._generator_motif_editor_steps = [None] * 8
        self._generator_motif_dominant_dirty = False
        self.generator_motif_name_input.clear()
        self.generator_motif_length_spin.setValue(4)
        self.generator_motif_base_prob_slider.setValue(60)
        role_index = self.generator_motif_role_combo.findData("groove")
        if role_index >= 0:
            self.generator_motif_role_combo.setCurrentIndex(role_index)
        self._refresh_generator_motif_editor_buttons()
        self._refresh_generator_motif_editor_dominant()

    def _on_generator_mode_changed(self) -> None:
        self._settings.setValue("generator_mode", self._generator_mode())
        self._refresh_generator_mode_ui()
        self._refresh_generator_user_motif_table()
        self._refresh_generator_anchor_summary()

    def _on_generator_profile_changed(self) -> None:
        self._settings.setValue("generator_profile", self._generator_profile())
        self._refresh_generated_pattern_state()

    def _randomize_generator_params(self, *, rng: np.random.Generator | None = None) -> None:
        if self._analysis_busy or self._rebuild_busy or self._waveform_loading or self._generator_busy:
            return
        if rng is None:
            rng = np.random.default_rng(int(secrets.randbelow(2_147_483_647) + 1))

        def _random_percent(minimum: int = 0, maximum: int = 100) -> int:
            return int(rng.integers(int(minimum), int(maximum) + 1))

        def _random_signed(minimum: int, maximum: int) -> int:
            return int(rng.integers(int(minimum), int(maximum) + 1))

        def _random_range_pair(minimum: int, maximum: int, *, min_span: int = 0) -> tuple[int, int]:
            first = _random_signed(minimum, maximum)
            second = _random_signed(minimum, maximum)
            low, high = sorted((int(first), int(second)))
            if min_span > 0 and high - low < int(min_span):
                high = min(int(maximum), low + int(min_span))
                if high - low < int(min_span):
                    low = max(int(minimum), high - int(min_span))
            return int(low), int(high)

        def _random_pitch_sequence_text() -> str:
            sequence_length = int(rng.integers(2, 6))
            values = [str(_random_signed(-12, 12)) for _ in range(sequence_length)]
            return ", ".join(values)

        def _choose_combo(combo: QComboBox, options: tuple[str, ...]) -> None:
            chosen = str(rng.choice(np.asarray(options, dtype=object)))
            index = combo.findData(chosen)
            if index >= 0:
                combo.setCurrentIndex(index)

        ghost_vel_min, ghost_vel_max = _random_range_pair(0, 60, min_span=8)
        ghost_pitch_min, ghost_pitch_max = _random_range_pair(-20, 20, min_span=4)
        pitch_min, pitch_max = _random_range_pair(-24, 24, min_span=6)
        curve_min, curve_max = _random_range_pair(-12, 12, min_span=4)

        self._generator_bulk_param_update = True
        try:
            self.generator_energy_slider.setValue(_random_percent(20, 95))
            self.generator_kick_slider.setValue(_random_percent(0, 100))
            self.generator_snare_slider.setValue(_random_percent(0, 100))
            self.generator_hat_slider.setValue(_random_percent(0, 100))
            self.generator_ghost_slider.setValue(_random_percent(0, 85))
            self.generator_fill_slider.setValue(_random_percent(0, 100))
            self.generator_repeat_slider.setValue(_random_percent(0, 100))
            self.generator_repeat_length_slider.setValue(_random_percent(0, 100))
            self.generator_repeat_rate_slider.setValue(_random_percent(0, 100))
            self.generator_reverse_slider.setValue(_random_percent(0, 100))
            self.generator_kick_roll_slider.setValue(_random_percent(0, 100))
            self.generator_kick_roll_length_slider.setValue(_random_percent(0, 100))
            self.generator_kick_roll_contrast_slider.setValue(_random_percent(15, 100))
            self.generator_snare_stretch_slider.setValue(_random_percent(0, 100))
            self.generator_snare_stretch_length_slider.setValue(_random_percent(0, 100))
            self.generator_snare_stretch_amount_slider.setValue(_random_percent(0, 100))
            _choose_combo(self.generator_snare_stretch_curve_combo, SNARE_STRETCH_VEL_CURVE_OPTIONS)
            self.generator_gate_slider.setValue(_random_percent(35, 100))
            self.generator_position_fidelity_slider.setValue(_random_percent(0, 100))
            self.generator_sequence_density_slider.setValue(_random_percent(0, 100))
            self.generator_motif_density_slider.setValue(_random_percent(0, 100))
            self.generator_velocity_slider.setValue(_random_percent(10, 100))
            self.generator_swing_slider.setValue(_random_percent(0, 100))
            self.generator_anti_repeat_slider.setValue(_random_percent(0, 100))
            self.generator_breath_slider.setValue(_random_percent(0, 100))
            self.generator_sequence_max_len_spin.setValue(int(rng.integers(2, MAX_SEQUENCE_HIT_COUNT + 1)))
            self.generator_sequence_role_lock_check.setChecked(bool(rng.integers(0, 2)))

            self.generator_synth_ghost_enabled_check.setChecked(bool(rng.integers(0, 2)))
            self.generator_ghost_vel_min_slider.setValue(ghost_vel_min)
            self.generator_ghost_vel_max_slider.setValue(ghost_vel_max)
            self.generator_ghost_pitch_min_slider.setValue(ghost_pitch_min)
            self.generator_ghost_pitch_max_slider.setValue(ghost_pitch_max)
            self.generator_ghost_gate_slider.setValue(_random_percent(0, 100))

            if self._generator_user_motifs:
                _choose_combo(self.generator_mode_combo, (GENERATOR_MODE_CLASSIC, GENERATOR_MODE_HYBRID))

            _choose_combo(self.generator_pitch_mode_combo, PITCH_MODE_OPTIONS)
            _choose_combo(self.generator_pitch_scope_combo, PITCH_SCOPE_OPTIONS)
            _choose_combo(self.generator_pitch_scale_combo, PITCH_SCALE_OPTIONS)
            _choose_combo(self.generator_pitch_rate_combo, PITCH_RATE_OPTIONS)
            _choose_combo(self.generator_pitch_curve_combo, PITCH_CURVE_OPTIONS)
            self.generator_pitch_root_slider.setValue(int(rng.integers(0, 12)))
            self.generator_pitch_amount_slider.setValue(_random_percent(0, 100))
            self.generator_pitch_range_min_slider.setValue(pitch_min)
            self.generator_pitch_range_max_slider.setValue(pitch_max)
            self.generator_pitch_sequence_input.setText(_random_pitch_sequence_text())
            self.generator_pitch_curve_min_slider.setValue(curve_min)
            self.generator_pitch_curve_max_slider.setValue(curve_max)
        finally:
            self._generator_bulk_param_update = False

        self._refresh_generator_mode_ui()
        self._refresh_generator_probability_preview()
        self._refresh_generated_pattern_state()
        self._refresh_control_states("Parametres du generateur randomises.")

    def _on_generator_motif_length_changed(self) -> None:
        active_length = int(self.generator_motif_length_spin.value())
        for index in range(active_length, len(self._generator_motif_editor_steps)):
            self._generator_motif_editor_steps[index] = None
        self._refresh_generator_motif_editor_buttons()
        self._refresh_generator_motif_editor_dominant()
        self._refresh_generator_user_motif_table()

    def _on_generator_motif_dominant_changed(self) -> None:
        self._generator_motif_dominant_dirty = True
        self._refresh_generator_motif_editor_effective_label()
        self._refresh_generator_user_motif_table()

    def _on_generator_motif_editor_step_clicked(self, step_index: int) -> None:
        if step_index < 0 or step_index >= int(self.generator_motif_length_spin.value()):
            return
        current = self._generator_motif_editor_steps[step_index]
        current_index = USER_MOTIF_STEP_ORDER.index(current) if current in USER_MOTIF_STEP_ORDER else 0
        next_value = USER_MOTIF_STEP_ORDER[(current_index + 1) % len(USER_MOTIF_STEP_ORDER)]
        self._generator_motif_editor_steps[step_index] = next_value
        self._refresh_generator_motif_editor_buttons()
        self._refresh_generator_motif_editor_dominant()
        self._refresh_generator_user_motif_table()

    def _save_generator_user_motif(self) -> None:
        motif = self._current_generator_editor_motif()
        if motif is None:
            QMessageBox.information(self, "Motif vide", "Ajoute au moins un step explicite avant de sauvegarder le motif.")
            return
        motif = replace(
            motif,
            name=self.generator_motif_name_input.text().strip() or f"Motif {len(self._generator_user_motifs) + 1}",
        )
        self._generator_user_motifs.append(motif)
        self._persist_generator_user_motifs()
        self._refresh_generator_user_motif_table()
        self._clear_generator_motif_editor()
        self.generator_info_label.setText(f"Motif utilisateur '{motif.name}' sauvegarde pour le projet courant.")

    def _delete_generator_user_motif(self, row: int) -> None:
        if row < 0 or row >= len(self._generator_user_motifs):
            return
        motif = self._generator_user_motifs.pop(row)
        self._persist_generator_user_motifs()
        self._refresh_generator_user_motif_table()
        self.generator_info_label.setText(f"Motif utilisateur '{motif.name}' supprime.")

    def _generator_param_slider_dragging(self) -> bool:
        return bool(self._active_generator_param_slider_ids)

    def _on_generator_param_slider_pressed(self) -> None:
        sender = self.sender()
        if isinstance(sender, QSlider):
            self._active_generator_param_slider_ids.add(id(sender))
        if self._generator_probability_refresh_timer.isActive():
            self._generator_probability_refresh_timer.stop()

    def _on_generator_param_slider_released(self) -> None:
        sender = self.sender()
        if isinstance(sender, QSlider):
            self._active_generator_param_slider_ids.discard(id(sender))
        if self._generator_param_slider_dragging():
            return
        if self._generator_gate_preview_pending:
            if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
                self._generator_live_changes_pending = True
                self._schedule_live_generator_preview_refresh()
                self._refresh_generated_pattern_state()
            self._generator_gate_preview_pending = False
        if self._generator_probability_refresh_pending:
            self._generator_probability_refresh_pending = False
            self._flush_generator_probability_preview_refresh()

    def _flush_generator_probability_preview_refresh(self) -> None:
        if getattr(self, "_generator_bulk_param_update", False):
            return
        if self._generator_param_slider_dragging():
            self._generator_probability_refresh_pending = True
            return
        if self._generator_probability_refresh_timer.isActive():
            self._generator_probability_refresh_timer.stop()
        self._refresh_generator_probability_preview_now()

    def _refresh_generator_probability_preview(self) -> None:
        if getattr(self, "_generator_bulk_param_update", False):
            return
        sender = self.sender()
        if isinstance(sender, QSlider) and sender.isSliderDown():
            self._generator_probability_refresh_pending = True
            return
        if self._generator_param_slider_dragging():
            self._generator_probability_refresh_pending = True
            return
        if isinstance(sender, QLineEdit) and sender.hasFocus():
            self._generator_probability_refresh_timer.start()
            return
        self._generator_probability_refresh_pending = False
        self._flush_generator_probability_preview_refresh()

    def _refresh_generator_probability_preview_now(self, *, force: bool = False) -> None:
        if getattr(self, "_generator_bulk_param_update", False):
            return
        if not force and not self._main_tab_is_visible(MAIN_TAB_INSPECTOR):
            self._inspector_tab_refresh_pending = True
            self._refresh_generator_user_motif_table()
            return
        rows = ("downbeat", "backbeat", "offbeat", "subdivision")
        row_labels = {
            "downbeat": "Downbeat",
            "backbeat": "Backbeat",
            "offbeat": "Offbeat",
            "subdivision": "Subdivision",
        }
        families = ("kick", "snare", "hat", "ghost", "other", "silence")
        family_labels = {
            "kick": "Kick",
            "snare": "Snare",
            "hat": "Hat",
            "ghost": "Ghost",
            "other": "Other",
            "silence": "Sil",
        }
        effects = ("repeat", "reverse", "kick_roll", "snare_stretch", "pitch")
        effect_labels = {
            "repeat": "Repeat",
            "reverse": "Reverse",
            "kick_roll": "K.Roll",
            "snare_stretch": "Snr.Str",
            "pitch": "Pitch",
        }
        tables = (self.generator_probability_table, self.generator_effect_probability_table)
        for table in tables:
            table.setUpdatesEnabled(False)
        try:
            self.generator_probability_table.setRowCount(len(rows))
            self.generator_probability_table.setColumnCount(len(families))
            self.generator_probability_table.setHorizontalHeaderLabels([family_labels[family] for family in families])
            self.generator_probability_table.setVerticalHeaderLabels([row_labels[row] for row in rows])
            self.generator_effect_probability_table.setRowCount(len(rows))
            self.generator_effect_probability_table.setColumnCount(len(effects))
            self.generator_effect_probability_table.setHorizontalHeaderLabels([effect_labels[effect] for effect in effects])
            self.generator_effect_probability_table.setVerticalHeaderLabels([row_labels[row] for row in rows])

            source_result = self._effective_generator_result(self._result)
            if source_result is None or not source_result.transient_hits:
                for row_index, row_name in enumerate(rows):
                    for column_index, family in enumerate(families):
                        item = QTableWidgetItem("-")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setToolTip(
                            f"{row_labels[row_name]} | {family_labels[family]}\nCharge un break analyse pour voir l'apercu."
                        )
                        self.generator_probability_table.setItem(row_index, column_index, item)
                    for column_index, effect in enumerate(effects):
                        item = QTableWidgetItem("-")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        item.setToolTip(
                            f"{row_labels[row_name]} | {effect_labels[effect]}\nCharge un break analyse pour voir l'apercu."
                        )
                        self.generator_effect_probability_table.setItem(row_index, column_index, item)
                return

            params = self._generator_params(seed=1)
            family_preview = estimate_pattern_family_probabilities(source_result.transient_hits, params)
            effect_preview = estimate_pattern_effect_probabilities(source_result.transient_hits, params)

            for row_index, row_name in enumerate(rows):
                family_weights = family_preview.rows.get(row_name, {})
                for column_index, family in enumerate(families):
                    probability = float(family_weights.get(family, 0.0))
                    item = QTableWidgetItem(f"{int(round(probability * 100.0))}%")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(
                        f"{row_labels[row_name]} | {family_labels[family]}\n"
                        f"Probabilite de base: {probability * 100.0:.1f}%\n"
                        "Apercu avant contexte local, sequences et fills."
                    )
                    if probability >= 0.5:
                        item.setBackground(QColor("#2b3d2f"))
                    elif probability >= 0.25:
                        item.setBackground(QColor("#263545"))
                    elif probability <= 0.05:
                        item.setForeground(QColor("#8690a2"))
                    self.generator_probability_table.setItem(row_index, column_index, item)

                effect_weights = effect_preview.rows.get(row_name, {})
                for column_index, effect in enumerate(effects):
                    probability = float(effect_weights.get(effect, 0.0))
                    item = QTableWidgetItem(f"{int(round(probability * 100.0))}%")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if effect == "repeat":
                        item.setToolTip(
                            f"{row_labels[row_name]} | Repeat\n"
                            f"Probabilite heuristique: {probability * 100.0:.1f}%\n"
                            "Estime la chance de voir apparaitre une zone de retrigger glitch sur cette classe de position."
                        )
                        if probability >= 0.45:
                            item.setBackground(QColor("#1f4330"))
                        elif probability >= 0.2:
                            item.setBackground(QColor("#20312a"))
                    elif effect == "reverse":
                        item.setToolTip(
                            f"{row_labels[row_name]} | Reverse\n"
                            f"Probabilite heuristique: {probability * 100.0:.1f}%\n"
                            "Estime la chance d'injecter une queue reverse apres un kick, snare ou clap sur cette classe de position."
                        )
                        if probability >= 0.3:
                            item.setBackground(QColor("#4d2437"))
                        elif probability >= 0.12:
                            item.setBackground(QColor("#35202b"))
                    elif effect == "kick_roll":
                        item.setToolTip(
                            f"{row_labels[row_name]} | Kick roll\n"
                            f"Probabilite heuristique: {probability * 100.0:.1f}%\n"
                            "Estime la chance de declencher une petite rafale de kicks sur plusieurs steps a partir d'un point de depart compatible."
                        )
                        if probability >= 0.32:
                            item.setBackground(QColor("#5a3617"))
                        elif probability >= 0.14:
                            item.setBackground(QColor("#412a19"))
                    elif effect == "snare_stretch":
                        item.setToolTip(
                            f"{row_labels[row_name]} | Snare retrigger\n"
                            f"Probabilite heuristique: {probability * 100.0:.1f}%\n"
                            "Estime la chance de transformer un snare, clap ou ruff en zone de retrigger exponentiel sur plusieurs steps."
                        )
                        if probability >= 0.32:
                            item.setBackground(QColor("#2c2f63"))
                        elif probability >= 0.14:
                            item.setBackground(QColor("#23284b"))
                    else:
                        item.setToolTip(
                            f"{row_labels[row_name]} | Pitch\n"
                            f"Probabilite heuristique: {probability * 100.0:.1f}%\n"
                            "Estime la chance qu'un hit cible recoive un mouvement de pitch selon le mode, la portee et l'intensite courants."
                        )
                        if probability >= 0.32:
                            item.setBackground(QColor("#314a2f"))
                        elif probability >= 0.14:
                            item.setBackground(QColor("#273728"))
                    if probability <= 0.03:
                        item.setForeground(QColor("#8690a2"))
                    self.generator_effect_probability_table.setItem(row_index, column_index, item)
        finally:
            for table in tables:
                table.setUpdatesEnabled(True)
        self._refresh_generator_user_motif_table()

    def _generator_pattern_shape_text(self) -> str:
        bars = int(self.generator_bars_spin.value()) if hasattr(self, "generator_bars_spin") else 1
        step_count = max(16, bars * 16)
        return f"{bars} bar{'s' if bars > 1 else ''} / {step_count} steps"

    def _preview_loop_enabled(self, owner: str | None) -> bool:
        if owner == PREVIEW_OWNER_LIVE:
            return True
        if owner == PREVIEW_OWNER_GENERATOR:
            return bool(self.generator_loop_button.isChecked())
        return bool(self.retime_loop_button.isChecked())

    def _preview_info_label(self, owner: str | None) -> QLabel:
        if owner == PREVIEW_OWNER_LIVE:
            return self.live_mode_info_label
        if owner == PREVIEW_OWNER_GENERATOR:
            return self.generator_info_label
        return self.retime_info_label

    def _preview_loading_bar(self, owner: str | None) -> QProgressBar:
        if owner == PREVIEW_OWNER_LIVE:
            return self.generator_loading_bar
        if owner == PREVIEW_OWNER_GENERATOR:
            return self.generator_loading_bar
        return self.retime_loading_bar

    def _preview_owner_is_active(self, owner: str) -> bool:
        return bool(self._retimed_preview_playing and self._preview_owner == owner)

    @staticmethod
    def _preview_mode_summary(preview: RetimedPreview) -> str:
        if preview.mode == PREVIEW_MODE_PATTERN:
            summary = "mode pattern generator"
        elif preview.mode != PREVIEW_MODE_QUANTIZE:
            summary = "mode retime"
        else:
            summary = (
            f"mode quantize {format_quantize_grid_label(preview.quantize_grid_division)} "
            f"a {preview.quantize_strength * 100:.0f}%"
            )
        if bool(getattr(preview, "mono_choke", False)):
            summary += " + mono choke"
        return summary

    @staticmethod
    def _preview_playback_label(preview: RetimedPreview, *, looping: bool, restarted: bool = False) -> str:
        if preview.mode == PREVIEW_MODE_PATTERN:
            if looping and restarted:
                return "Lecture pattern en boucle relancee"
            if looping:
                return "Lecture pattern en boucle"
            return "Lecture pattern en cours"
        if preview.mode == PREVIEW_MODE_QUANTIZE:
            if looping and restarted:
                return "Lecture quantizee en boucle relancee"
            if looping:
                return "Lecture quantizee en boucle"
            return "Lecture quantizee en cours"
        if looping and restarted:
            return "Lecture retimee en boucle relancee"
        if looping:
            return "Lecture retimee en boucle"
        return "Lecture retimee en cours"

    def _on_preview_mode_changed(self, _index: int) -> None:
        self._settings.setValue("preview_mode", self._preview_mode())
        self._sync_quantize_controls_state()

    def _build_saved_patterns_tab(self, layout: QVBoxLayout) -> None:
        self.saved_patterns_box = QGroupBox("Saved breaks")
        saved_layout = QVBoxLayout(self.saved_patterns_box)
        saved_layout.setSpacing(10)

        self.saved_patterns_info_label = QLabel(
            "Aucun break sauvegarde pour le projet courant. Clique sur l'etoile du Generator ou d'un slot Live pour en garder un."
        )
        self.saved_patterns_info_label.setObjectName("StatusLabel")
        self.saved_patterns_info_label.setWordWrap(True)
        self._reserve_label_height(self.saved_patterns_info_label, lines=2)

        self.saved_patterns_table = QTableWidget(0, 6)
        self.saved_patterns_table.setHorizontalHeaderLabels(("Name", "Origin", "Source", "Seed", "Bars", "Saved"))
        self.saved_patterns_table.verticalHeader().setVisible(False)
        self.saved_patterns_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.saved_patterns_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.saved_patterns_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.saved_patterns_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.saved_patterns_table.setAlternatingRowColors(True)
        self.saved_patterns_table.setMinimumHeight(260)
        saved_header = self.saved_patterns_table.horizontalHeader()
        saved_header.setStretchLastSection(False)
        for column in range(self.saved_patterns_table.columnCount()):
            mode = QHeaderView.ResizeMode.Stretch if column in {0, 2, 5} else QHeaderView.ResizeMode.ResizeToContents
            saved_header.setSectionResizeMode(column, mode)
        self.saved_patterns_table.itemSelectionChanged.connect(self._on_saved_pattern_selection_changed)
        self.saved_patterns_table.cellDoubleClicked.connect(
            lambda _row, _column: self._open_selected_saved_pattern()
        )

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.saved_patterns_open_button = QPushButton("Open in Generator")
        self.saved_patterns_open_button.clicked.connect(self._open_selected_saved_pattern)
        self._configure_icon_button(
            self.saved_patterns_open_button,
            QStyle.StandardPixmap.SP_ArrowForward,
            "Recharger ce snapshot dans le generateur et retrouver exactement ce break.",
            qtawesome_name="fa5s.folder-open",
        )
        self.saved_patterns_render_button = QPushButton("Render WAV")
        self.saved_patterns_render_button.clicked.connect(self._render_selected_saved_pattern_to_wav)
        self._configure_icon_button(
            self.saved_patterns_render_button,
            QStyle.StandardPixmap.SP_DialogSaveButton,
            "Exporter le snapshot selectionne en WAV sur une seule loop exacte.",
            qtawesome_name="fa5s.file-audio",
        )
        self.saved_patterns_delete_button = QPushButton("Delete")
        self.saved_patterns_delete_button.clicked.connect(self._delete_selected_saved_pattern)
        self._configure_icon_button(
            self.saved_patterns_delete_button,
            QStyle.StandardPixmap.SP_TrashIcon,
            "Supprimer ce snapshot sauvegarde du projet courant.",
            qtawesome_name="fa5s.trash",
        )
        button_row.addWidget(self.saved_patterns_open_button)
        button_row.addWidget(self.saved_patterns_render_button)
        button_row.addWidget(self.saved_patterns_delete_button)
        button_row.addStretch(1)

        saved_layout.addWidget(self.saved_patterns_info_label)
        saved_layout.addWidget(self.saved_patterns_table)
        saved_layout.addLayout(button_row)
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._stop_retimed_preview(update_status=False)
        self._update_retimed_preview_state(self._result)

    def _on_quantize_grid_changed(self, _index: int) -> None:
        self._settings.setValue("quantize_grid_division", self._quantize_grid_division())
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._stop_retimed_preview(update_status=False)
        self._update_retimed_preview_state(self._result)

    def _on_quantize_strength_changed(self, value: int) -> None:
        self._settings.setValue("quantize_strength_percent", int(np.clip(value, 0, 100)))
        self._refresh_quantize_strength_label(value)
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._stop_retimed_preview(update_status=False)
        self._update_retimed_preview_state(self._result)

    def _on_detected_bpm_factor_changed(self, _index: int) -> None:
        self._settings.setValue("detected_bpm_factor", self._detected_bpm_factor())
        self._refresh_tempo_display()
        self._refresh_detected_bpm_labels()

        generator_changed = False
        if self._result is not None:
            _, generator_changed = self._sync_target_bpm_spins_from_detected(self._result)

        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._retime_live_changes_pending = True
            self._refresh_active_retime_preview_message()
        elif not self._retimed_preview_playing:
            self._update_retimed_preview_state(self._result, reset_target=False)

        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR) and generator_changed:
            self._generator_live_changes_pending = True

        self._refresh_generated_pattern_state()

    def _retime_loop_enabled(self) -> bool:
        return bool(self.retime_loop_button.isChecked())

    def _on_retime_loop_toggled(self, enabled: bool) -> None:
        self._settings.setValue("retime_loop_enabled", bool(enabled))
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._retime_stream_loop_enabled = bool(enabled)
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME) and self._retimed_preview is not None:
            status = "activee" if enabled else "desactivee a la fin du cycle courant"
            self.retime_info_label.setText(
                f"{self._preview_playback_label(self._retimed_preview, looping=self._retime_loop_enabled())}: "
                f"{self._retimed_preview.source_bpm:.1f} -> "
                f"{self._retimed_preview.target_bpm:.1f} BPM, {self._retimed_preview.segment_count} segments, "
                f"{self._retimed_preview.duration_s:.2f}s, {self._preview_mode_summary(self._retimed_preview)}. "
                f"Boucle {status}."
            )
            return
        self._update_retimed_preview_state(self._result)

    def _generator_loop_enabled(self) -> bool:
        return bool(self.generator_loop_button.isChecked())

    def _on_generator_loop_toggled(self, enabled: bool) -> None:
        self._settings.setValue("generator_loop_enabled", bool(enabled))
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._retime_stream_loop_enabled = bool(enabled)
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR) and self._retimed_preview is not None:
            status = "activee" if enabled else "desactivee a la fin du cycle courant"
            self.generator_info_label.setText(
                f"{self._preview_playback_label(self._retimed_preview, looping=self._generator_loop_enabled())}: "
                f"{self._retimed_preview.segment_count} evenement(s), "
                f"{self._retimed_preview.target_bpm:.1f} BPM, {self._retimed_preview.duration_s:.2f}s. "
                f"Boucle {status}."
            )
            return
        self._refresh_generated_pattern_state()

    def _start_analysis(self) -> None:
        if self._dependency_error:
            QMessageBox.warning(self, "Dependance manquante", self._dependency_error)
            return
        path = self.path_input.text().strip()
        if not path:
            QMessageBox.warning(self, "Aucun sample", "Choisis d'abord un fichier audio.")
            return

        source = Path(path).expanduser()
        if not source.exists():
            QMessageBox.warning(self, "Fichier introuvable", f"Le fichier suivant est introuvable:\n{source}")
            return
        if source.suffix.lower() not in AUDIO_EXTENSIONS:
            QMessageBox.warning(self, "Format non supporte", "Selectionne un fichier audio supporte.")
            return
        if self._analysis_busy or self._rebuild_busy:
            return
        if self._waveform_loading:
            QMessageBox.information(
                self,
                "Chargement en cours",
                "Attends que la waveform finisse de charger avant de lancer l'analyse.",
            )
            return

        self._persist_current_markers(force=True)
        self._stop_retimed_preview(update_status=False)
        if self._waveform_widget is not None and getattr(self._waveform_widget, "waveform_data", None) is not None:
            self._clear_waveform_markers()
            self.waveform_status_label.setText(
                "Analyse en cours... detection initiale des transients pour poser les premiers markers."
            )
        self.hits_summary_label.setText("Analyse en cours... premiere passe transients en preparation.")
        self.rebuild_markers_label.setText(
            "Analyse en cours. Les markers provisoires apparaitront des la premiere passe de transients."
        )
        audio_snapshot = self._analysis_audio_snapshot()
        self._analysis_busy = True
        self._analysis_stale = False
        self.main_loading_bar.setVisible(True)
        self._refresh_control_states(f"Analyse en cours sur {source.name}...")
        self._worker = AnalysisWorker(
            str(source),
            int(self.top_n_spin.value()),
            float(self.split_density_slider.value()),
            audio=audio_snapshot[0] if audio_snapshot is not None else None,
            sample_rate=audio_snapshot[1] if audio_snapshot is not None else None,
            source_path=str(source),
            parent=self,
        )
        self._worker.progressed.connect(
            lambda message: self._dispatch_ui_callback(lambda: self._on_analysis_progress(message))
        )
        self._worker.preview_ready.connect(
            lambda preview: self._dispatch_ui_callback(lambda: self._on_analysis_preview(preview))
        )
        self._worker.succeeded.connect(
            lambda result: self._dispatch_ui_callback(lambda: self._on_analysis_success(result))
        )
        self._worker.failed.connect(
            lambda message: self._dispatch_ui_callback(lambda: self._on_analysis_failure(message))
        )
        self._worker.finished.connect(
            lambda: self._dispatch_ui_callback(self._on_analysis_finished)
        )
        self._worker.start()

    def _sync_waveform_path(self, path: str) -> None:
        resolved = Path(path).expanduser()
        if self._waveform_loader and self._waveform_loader.isRunning():
            self._waveform_loader.requestInterruption()
        self._waveform_loader = None
        if not resolved.exists():
            self.waveform_status_label.setText("Fichier introuvable pour la waveform.")
            self._clear_waveform_markers()
            self._loaded_audio_samples = None
            self._loaded_audio_sample_rate = None
            self._loaded_audio_path = None
            self._clear_live_audio_shared_buffer()
            self.waveform_loading_bar.setVisible(False)
            self._waveform_loading = False
            self._refresh_control_states(self.status_label.text())
            return
        if resolved.suffix.lower() not in AUDIO_EXTENSIONS:
            self.waveform_status_label.setText("Format audio non supporte pour la waveform.")
            self._clear_waveform_markers()
            self._loaded_audio_samples = None
            self._loaded_audio_sample_rate = None
            self._loaded_audio_path = None
            self._clear_live_audio_shared_buffer()
            self.waveform_loading_bar.setVisible(False)
            self._waveform_loading = False
            self._refresh_control_states(self.status_label.text())
            return

        self._loaded_audio_samples = None
        self._loaded_audio_sample_rate = None
        self._loaded_audio_path = None
        self._clear_live_audio_shared_buffer()
        self._waveform_loading = True
        self._waveform_load_token += 1
        token = self._waveform_load_token
        self.waveform_loading_bar.setVisible(True)
        self.waveform_status_label.setText("Chargement waveform en cours...")
        self.hits_summary_label.setText("Chargement audio en cours pour preparer la waveform.")
        self._refresh_control_states(f"Chargement du sample {resolved.name}...")

        worker = TaskWorker(lambda: self._create_waveform_load_result(resolved), self)
        self._waveform_loader = worker
        worker.succeeded.connect(
            lambda result, current_token=token: self._dispatch_ui_callback(
                lambda: self._on_waveform_loaded(result, current_token)
            )
        )
        worker.failed.connect(
            lambda message, current_token=token: self._dispatch_ui_callback(
                lambda: self._on_waveform_load_failed(message, current_token)
            )
        )
        worker.finished.connect(
            lambda current_token=token: self._dispatch_ui_callback(
                lambda: self._on_waveform_load_finished(current_token)
            )
        )
        worker.start()

    def _refresh_control_states(self, status: str | None = None) -> None:
        if status is not None:
            self.status_label.setText(status)

        global_busy = self._analysis_busy or self._rebuild_busy
        any_busy = global_busy or self._waveform_loading or self._generator_busy or self._preview_busy

        self.main_loading_bar.setVisible(global_busy)
        self.path_input.setEnabled(not global_busy and not self._waveform_loading)
        self.recent_files_combo.setEnabled(
            self.recent_files_combo.count() > 1 and (not global_busy) and (not self._waveform_loading)
        )
        self.browse_button.setEnabled(not global_busy and not self._waveform_loading)
        self.analyze_button.setEnabled((not self._dependency_error) and (not global_busy) and (not self._waveform_loading))
        self.top_n_spin.setEnabled((not self._dependency_error) and (not global_busy) and (not self._waveform_loading))
        self.split_density_slider.setEnabled(
            (not self._dependency_error) and (not global_busy) and (not self._waveform_loading)
        )

        waveform_ready = bool(
            self._waveform_widget is not None and getattr(self._waveform_widget, "waveform_data", None) is not None
        )
        edit_ready = waveform_ready and not any_busy
        self.cut_selection_button.setEnabled(edit_ready)
        self.undo_edit_button.setEnabled(edit_ready)
        self.redo_edit_button.setEnabled(edit_ready)
        self._set_hit_label_edit_enabled((not any_busy) and self._result is not None)
        self._set_hit_pool_edit_enabled((not global_busy) and (not self._waveform_loading) and (not self._generator_busy) and self._result is not None)

        retime_ready = (
            (not global_busy)
            and (not self._waveform_loading)
            and (not self._preview_busy)
            and self._retimed_preview_available()
        )
        self.retime_play_button.setEnabled(retime_ready)
        self.retime_stop_button.setEnabled(
            (not self._preview_busy) and self._preview_owner_is_active(PREVIEW_OWNER_RETIME)
        )
        self.detected_bpm_factor_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._preview_busy) and self._result is not None
        )
        self.target_bpm_spin.setEnabled(retime_ready)
        self.preview_mode_combo.setEnabled(
            (not self._dependency_error)
            and (not global_busy)
            and (not self._waveform_loading)
            and (not self._preview_busy)
            and (not self._analysis_stale)
        )
        self.retime_loop_button.setEnabled(
            (not self._dependency_error) and (not global_busy) and (not self._waveform_loading)
        )
        self._sync_quantize_controls_state()

        self.generator_generate_button.setEnabled(
            (not global_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._analysis_stale)
            and self._result is not None
        )
        self.generator_randomize_params_button.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_target_bpm_spin.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        if hasattr(self, "live_target_bpm_spin"):
            self.live_target_bpm_spin.setEnabled(
                (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
            )
        self.generator_bars_spin.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_mode_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_profile_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_live_mode_button.setEnabled((not global_busy) and (not self._waveform_loading))
        self.generator_pitch_mode_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_pitch_scope_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_pitch_scale_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_pitch_rate_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_pitch_sequence_input.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_pitch_curve_combo.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_loop_button.setEnabled(
            (not self._dependency_error) and (not global_busy) and (not self._waveform_loading)
        )
        if hasattr(self, "generator_save_snapshot_button"):
            self.generator_save_snapshot_button.setEnabled(
                (not global_busy)
                and (not self._waveform_loading)
                and (not self._generator_busy)
                and (not self._analysis_stale)
                and self._result is not None
                and self._generated_pattern is not None
            )
        if hasattr(self, "generator_render_wav_button"):
            self.generator_render_wav_button.setEnabled(
                (not global_busy)
                and (not self._waveform_loading)
                and (not self._generator_busy)
                and self._generated_pattern is not None
            )
        if hasattr(self, "debug_report_button"):
            self.debug_report_button.setEnabled(
                (not global_busy)
                and (not self._waveform_loading)
                and (not self._generator_busy)
                and (not self._analysis_stale)
                and self._result is not None
            )
        self._set_generator_sequence_structure_enabled(
            (not global_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._analysis_stale)
        )
        self._set_generator_sequence_reroll_enabled(
            (not global_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._preview_busy)
            and (not self._analysis_stale)
            and self._generated_pattern is not None
        )
        for control in (
            self.generator_energy_slider,
            self.generator_kick_slider,
            self.generator_snare_slider,
            self.generator_hat_slider,
            self.generator_ghost_slider,
            self.generator_fill_slider,
            self.generator_repeat_slider,
            self.generator_repeat_length_slider,
            self.generator_repeat_rate_slider,
            self.generator_reverse_slider,
            self.generator_kick_roll_slider,
            self.generator_kick_roll_length_slider,
            self.generator_kick_roll_contrast_slider,
            self.generator_snare_stretch_slider,
            self.generator_snare_stretch_length_slider,
            self.generator_snare_stretch_amount_slider,
            self.generator_snare_stretch_curve_combo,
            self.generator_gate_slider,
            self.generator_mono_choke_check,
            self.generator_velocity_slider,
            self.generator_swing_slider,
            self.generator_anti_repeat_slider,
            self.generator_breath_slider,
            self.generator_position_fidelity_slider,
            self.generator_sequence_density_slider,
        ):
            control.setEnabled((not global_busy) and (not self._waveform_loading) and (not self._generator_busy))
        hybrid_editor_enabled = (
            self._generator_mode() == GENERATOR_MODE_HYBRID
            and (not global_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
        )
        self.generator_motif_density_slider.setEnabled(hybrid_editor_enabled)
        self.generator_motif_density_value.setEnabled(self._generator_mode() == GENERATOR_MODE_HYBRID)
        self.generator_motif_name_input.setEnabled(hybrid_editor_enabled)
        self.generator_motif_length_spin.setEnabled(hybrid_editor_enabled)
        self.generator_motif_base_prob_slider.setEnabled(hybrid_editor_enabled)
        self.generator_motif_role_combo.setEnabled(hybrid_editor_enabled)
        self.generator_motif_dominant_combo.setEnabled(hybrid_editor_enabled)
        self.generator_motif_save_button.setEnabled(hybrid_editor_enabled)
        for index, button in enumerate(getattr(self, "generator_motif_editor_buttons", ())):
            button.setEnabled(hybrid_editor_enabled and index < int(self.generator_motif_length_spin.value()))
        self._refresh_generator_ghost_ui()
        self._refresh_generator_pitch_ui()
        self._refresh_generated_pattern_state()
        self._refresh_generator_pipeline_ui()
        self._refresh_live_mode_ui()
        self._on_saved_pattern_selection_changed()
        self.rebuild_markers_button.setEnabled(
            (not global_busy) and (not self._waveform_loading) and self._marker_rebuild_available()
        )

    def _on_analysis_progress(self, message: str) -> None:
        if self._analysis_busy:
            self._refresh_control_states(message)

    def _on_analysis_preview(self, preview: DrumTransientPreview) -> None:
        marker_times = [float(time_s) for time_s in preview.marker_times]
        if marker_times:
            self._apply_preview_markers_to_waveform(marker_times, preview)
            tempo_hint = f" tempo approx {preview.tempo_bpm:.1f} bpm." if preview.tempo_bpm > 1.0 else ""
            self.hits_summary_label.setText(
                f"Premiere passe: {preview.onset_count} marker(s) provisoire(s) detecte(s), labels en cours.{tempo_hint}"
            )
            self.rebuild_markers_label.setText(
                "Premiere passe terminee. Les markers provisoires sont visibles; la classification finale continue."
            )
        else:
            self.hits_summary_label.setText(
                "Premiere passe terminee, mais aucun transient provisoire n'a ete trouve pour le moment."
            )

    def _on_analysis_success(self, result: DrumDetectionResult) -> None:
        result = self._apply_persisted_hit_labels(result)
        self._analysis_stale = False
        self._result = result
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._generator_locked_steps.clear()
        self._persist_detection_result(result)
        self._populate_result(result)
        self._populate_hits(result)
        self._apply_hits_to_waveform(result)
        self._update_retimed_preview_state(result, reset_target=True)
        self._populate_generated_pattern(None)
        self._refresh_generated_pattern_state()
        self.rebuild_markers_label.setText(
            "Tu peux maintenant ajouter, deplacer ou supprimer des markers dans la waveform, puis cliquer sur Rebuild Hits From Markers."
        )
        self.status_label.setText(
            f"Analyse terminee. {result.label} ({result.family} / {result.form}) avec {result.onset_count} transient(s)."
        )

    def _on_analysis_failure(self, message: str) -> None:
        self._stop_retimed_preview(update_status=False)
        self.status_label.setText(f"Echec de l'analyse: {message}")
        QMessageBox.critical(self, "Analyse impossible", message)

    def _on_analysis_finished(self) -> None:
        self._analysis_busy = False
        self.main_loading_bar.setVisible(False)
        self._refresh_control_states(self.status_label.text())
        self._worker = None
        self._maybe_close_after_background_tasks()

    def _create_waveform_load_result(self, path: Path) -> WaveformLoadResult:
        samples, waveform_data, sample_rate, duration_s = self._load_audio_for_waveform(path)
        return WaveformLoadResult(
            path=str(path.resolve()),
            samples=samples,
            waveform_data=waveform_data,
            sample_rate=sample_rate,
            duration_s=duration_s,
        )

    def _on_waveform_loaded(self, result: WaveformLoadResult, token: int) -> None:
        if token != self._waveform_load_token:
            return
        self._loaded_audio_samples = result.samples
        self._loaded_audio_sample_rate = result.sample_rate
        self._loaded_audio_path = result.path
        self._sync_live_audio_shared_buffer()
        if self._waveform_widget is None:
            self.waveform_status_label.setText(
                self._waveform_error or "Waveform editor indisponible, mais l'audio est charge pour l'analyse."
            )
            self.hits_summary_label.setText("Audio charge pour l'analyse, mais waveform editor indisponible.")
            return
        self._waveform_widget.audio_file_path = result.path
        self._waveform_widget.set_waveform_data(result.waveform_data, result.sample_rate, result.duration_s)
        self._clear_waveform_markers()
        restored_markers = self._restore_persisted_markers_for_path(result.path)
        restored_analysis = self._restore_persisted_detection_result_for_loaded_audio(
            result.path,
            preserve_existing_markers=restored_markers,
        )
        if restored_analysis:
            self.waveform_status_label.setText(
                "Waveform chargee. L'analyse et les labels sauvegardes pour ce break ont ete restaures automatiquement."
            )
            self.hits_summary_label.setText(
                "Analyse restauree. Tu peux ecouter, regenerer, ou ajuster les markers puis rebuild si besoin."
            )
            self.rebuild_markers_label.setText(
                "Analyse restauree depuis la session precedente. Tu peux retravailler les markers ou repartir directement sur la generation."
            )
        elif restored_markers:
            self.waveform_status_label.setText(
                "Waveform chargee. Les markers sauvegardes pour ce break ont ete restaures automatiquement."
            )
            self.hits_summary_label.setText(
                "Markers restaures. Tu peux relancer directement Rebuild Hits From Markers ou affiner le decoupage."
            )
            self.rebuild_markers_label.setText(
                "Markers restaures depuis la session precedente. Rebuild Hits From Markers reutilisera ce decoupage."
            )
        else:
            self.waveform_status_label.setText(
                "Waveform chargee. Tu peux l'ecouter, selectionner une region a couper, puis analyser l'audio courant."
            )
            self.hits_summary_label.setText("Waveform prete. Lance l'analyse quand tu veux.")

        pending_snapshot = self._pending_saved_snapshot_restore
        if pending_snapshot is not None:
            pending_source = self._normalize_recent_file_path(pending_snapshot.source_path)
            current_source = self._normalize_recent_file_path(result.path)
            if pending_source is None or pending_source == current_source:
                self._pending_saved_snapshot_restore = None
                self._apply_saved_pattern_snapshot(pending_snapshot)

    def _on_waveform_load_failed(self, message: str, token: int) -> None:
        if token != self._waveform_load_token:
            return
        self._loaded_audio_samples = None
        self._loaded_audio_sample_rate = None
        self._loaded_audio_path = None
        self._clear_live_audio_shared_buffer()
        if self._pending_saved_snapshot_restore is not None:
            pending_title = self._pending_saved_snapshot_restore.title
            self._pending_saved_snapshot_restore = None
            self.saved_patterns_info_label.setText(
                f"Impossible de recharger {pending_title}: {message}"
            )
        self.waveform_status_label.setText(f"Chargement waveform impossible: {message}")
        self.hits_summary_label.setText("Le chargement audio a echoue avant l'analyse.")
        self._refresh_control_states(f"Chargement waveform impossible: {message}")

    def _on_waveform_load_finished(self, token: int) -> None:
        if token != self._waveform_load_token:
            return
        self._waveform_loading = False
        self.waveform_loading_bar.setVisible(False)
        self._waveform_loader = None
        self._refresh_control_states(self.status_label.text())
        self._maybe_close_after_background_tasks()

    def _populate_result(self, result: DrumDetectionResult) -> None:
        if not self._main_tab_is_visible(MAIN_TAB_INSPECTOR):
            self._inspector_tab_refresh_pending = True
            return
        self._populate_result_now(result)

    def _populate_result_now(self, result: DrumDetectionResult) -> None:
        self.result_label.setText(result.label)
        self.family_label.setText(result.family)
        self.form_label.setText(result.form)
        self.source_label.setText(result.source_path or "-")
        self.confidence_bar.setValue(int(round(result.confidence * 100)))
        self.confidence_bar.setFormat(f"{result.confidence * 100:.0f}%")
        self.groove_value.setText(f"break {result.break_score:.2f} | loop {result.loop_score:.2f}")
        self._refresh_tempo_display()
        self.energy_value.setText(
            f"drum {result.drum_score:.2f} | perc {result.percussive_ratio:.2f} | harm {result.harmonic_ratio:.2f}"
        )
        self.band_value.setText(
            f"low {result.band_energies['low']:.2f} | mid {result.band_energies['mid']:.2f} | "
            f"high {result.band_energies['high']:.2f} | decay {result.decay_s:.2f}s"
        )
        labels = ", ".join(hit.label for hit in result.transient_hits[:8]) or "-"
        self.transient_value.setText(f"{result.onset_count} hit(s): {labels}")
        self._populate_candidates_now(result)
        self.json_view.setPlainText(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    def _refresh_tempo_display(self) -> None:
        if self._result is None:
            self.tempo_value.setText("-")
            return
        raw_bpm = float(self._result.tempo_bpm)
        factor = self._detected_bpm_factor()
        effective_bpm = raw_bpm * factor
        if abs(factor - 1.0) < 1e-6:
            self.tempo_value.setText(f"{raw_bpm:.1f} bpm | regularite {self._result.regularity:.2f}")
            return
        self.tempo_value.setText(
            f"{effective_bpm:.1f} bpm effectif ({raw_bpm:.1f} x {factor:g}) | regularite {self._result.regularity:.2f}"
        )

    def _refresh_detected_bpm_labels(self) -> None:
        if self._result is None:
            self.detected_bpm_value.setText("-")
            self.generator_detected_bpm_value.setText("-")
            return

        raw_bpm = float(self._result.tempo_bpm)
        detected_bpm = self._effective_detected_bpm(self._result)
        factor = self._detected_bpm_factor()
        if raw_bpm > 1.0:
            if abs(factor - 1.0) < 1e-6:
                text = f"{detected_bpm:.1f} BPM"
            else:
                text = f"{detected_bpm:.1f} BPM ({raw_bpm:.1f} x {factor:g})"
        else:
            text = "tempo indisponible"
        self.detected_bpm_value.setText(text)
        self.generator_detected_bpm_value.setText(text)

    def _sync_target_bpm_spins_from_detected(self, result: DrumDetectionResult) -> tuple[bool, bool]:
        detected_bpm = self._effective_detected_bpm(result)
        if detected_bpm <= 1.0:
            return False, False

        retime_changed = False
        clamped = float(np.clip(detected_bpm, self.target_bpm_spin.minimum(), self.target_bpm_spin.maximum()))
        previous = float(self.target_bpm_spin.value())
        if abs(previous - clamped) > 0.25:
            self.target_bpm_spin.blockSignals(True)
            self.target_bpm_spin.setValue(clamped)
            self.target_bpm_spin.blockSignals(False)
            retime_changed = True

        generator_changed = False
        generator_clamped = float(
            np.clip(detected_bpm, self.generator_target_bpm_spin.minimum(), self.generator_target_bpm_spin.maximum())
        )
        generator_previous = float(self.generator_target_bpm_spin.value())
        if abs(generator_previous - generator_clamped) > 0.25:
            self.generator_target_bpm_spin.blockSignals(True)
            self.generator_target_bpm_spin.setValue(generator_clamped)
            self.generator_target_bpm_spin.blockSignals(False)
            generator_changed = True

        return retime_changed, generator_changed

    def _refresh_active_retime_preview_message(self) -> bool:
        if not self._preview_owner_is_active(PREVIEW_OWNER_RETIME) or self._retimed_preview is None:
            return False

        if self._retime_live_changes_pending:
            self.retime_info_label.setText(
                "Lecture actuelle conserve encore l'ancienne version. "
                "Les nouveaux reglages de tempo sont prets; clique sur Play retimed quand tu veux les appliquer."
            )
            return True

        preview = self._retimed_preview
        self.retime_info_label.setText(
            f"{self._preview_playback_label(preview, looping=self._retime_loop_enabled())}: "
            f"{preview.source_bpm:.1f} -> {preview.target_bpm:.1f} BPM, "
            f"{preview.segment_count} segments, {preview.duration_s:.2f}s, {self._preview_mode_summary(preview)}. "
            "La tete de lecture suit le segment declenche sur la waveform."
        )
        return True

    def _populate_candidates(self, result: DrumDetectionResult) -> None:
        if not self._main_tab_is_visible(MAIN_TAB_INSPECTOR):
            self._inspector_tab_refresh_pending = True
            return
        self._populate_candidates_now(result)

    def _populate_candidates_now(self, result: DrumDetectionResult) -> None:
        self.candidates_table.setRowCount(len(result.candidates))
        for row, candidate in enumerate(result.candidates):
            values = (str(row + 1), candidate.label, f"{candidate.score:.3f}", candidate.details)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.candidates_table.setItem(row, column, item)
        self.candidates_table.resizeColumnsToContents()
        self._ensure_table_column_widths(self.candidates_table, {0: 56, 1: 220, 2: 90, 3: 520})

    def _populate_hits(self, result: DrumDetectionResult | None) -> None:
        hits = list(result.transient_hits) if result else []
        self.hits_table.clearSelection()
        self.hits_table.setRowCount(len(hits))
        if not hits:
            self.hits_summary_label.setText("Aucun transient detecte pour le moment.")
            self.rebuild_markers_button.setEnabled(False)
            return

        counts: dict[str, int] = {}
        active_count = 0
        for row, hit in enumerate(hits):
            counts[hit.label] = counts.get(hit.label, 0) + 1
            if bool(getattr(hit, "generator_enabled", True)):
                active_count += 1
            values = (
                str(hit.index),
                f"{hit.start_s:.3f}s",
                f"{hit.end_s:.3f}s",
                f"{hit.confidence:.2f}",
                f"{hit.peak_db:.1f}",
            )
            pool_toggle = self._build_hit_pool_toggle(hit, row=row)
            picker = self._build_hit_label_picker(hit, row=row)
            self.hits_table.setCellWidget(row, HITS_TABLE_COLUMN_POOL, pool_toggle)
            self.hits_table.setCellWidget(row, HITS_TABLE_COLUMN_LABEL, picker)
            for column, value in enumerate(values):
                table_column = HITS_TABLE_COLUMN_HIT if column == 0 else column + 2
                item = QTableWidgetItem(value)
                if table_column == HITS_TABLE_COLUMN_HIT:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not bool(getattr(hit, "generator_enabled", True)):
                    item.setForeground(QColor("#7f8898"))
                    item.setToolTip(
                        f"Hit #{hit.index} exclu des pools du generateur.\n"
                        "Il reste visible et jouable dans la waveform, mais le break generator ne l'utilisera pas."
                    )
                self.hits_table.setItem(row, table_column, item)

        summary = ", ".join(
            f"{label}:{count}" for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        )
        muted_count = max(0, len(hits) - active_count)
        if muted_count > 0:
            self.hits_summary_label.setText(
                f"{len(hits)} transient(s) detecte(s). Repartition: {summary}. "
                f"Pools actifs: {active_count}/{len(hits)} ({muted_count} mute(s))."
            )
        else:
            self.hits_summary_label.setText(f"{len(hits)} transient(s) detecte(s). Repartition: {summary}")
        self.hits_table.resizeColumnsToContents()
        self.hits_table.resizeRowsToContents()
        self._ensure_table_column_widths(
            self.hits_table,
            {
                HITS_TABLE_COLUMN_HIT: 56,
                HITS_TABLE_COLUMN_POOL: 84,
                HITS_TABLE_COLUMN_LABEL: 420,
                HITS_TABLE_COLUMN_START: 100,
                HITS_TABLE_COLUMN_END: 100,
                HITS_TABLE_COLUMN_CONF: 80,
                HITS_TABLE_COLUMN_PEAK: 80,
            },
        )
        self._set_hit_label_edit_enabled(
            (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._preview_busy)
            and result is not None
        )
        self._set_hit_pool_edit_enabled(
            (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and result is not None
        )
        self.rebuild_markers_button.setEnabled(self._marker_rebuild_available())

    def _build_hit_pool_toggle(self, hit, *, row: int) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toggle = QCheckBox("Use")
        toggle.setChecked(bool(getattr(hit, "generator_enabled", True)))
        toggle.setProperty("hitIndex", int(hit.index))
        toggle.setToolTip(
            f"Hit #{hit.index}\n"
            f"{'Inclus' if bool(getattr(hit, 'generator_enabled', True)) else 'Exclu'} des pools du generateur.\n"
            "Decoche pour garder ce hit dans l'analyse et la waveform, mais l'enlever du break generator."
        )
        toggle.toggled.connect(
            lambda checked, hit_index=hit.index, target_row=row: self._on_hit_pool_toggled(
                int(target_row),
                int(hit_index),
                bool(checked),
            )
        )
        layout.addWidget(toggle)
        return host

    def _on_hit_pool_toggled(self, row: int, hit_index: int, enabled: bool) -> None:
        if 0 <= row < self.hits_table.rowCount() and self.hits_table.currentRow() != row:
            self._suspend_hit_selection_sync = True
            try:
                self.hits_table.selectRow(row)
            finally:
                self._suspend_hit_selection_sync = False
        self._on_hit_generator_enabled_changed(hit_index, enabled)

    def _build_hit_label_picker(self, hit, *, row: int) -> QWidget:
        host = QWidget()
        layout = QGridLayout(host)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)
        group = QButtonGroup(host)
        group.setExclusive(True)
        secondary_hint = ", ".join(hit.secondary_labels) if getattr(hit, "secondary_labels", ()) else "-"
        for index, label in enumerate(MANUAL_HIT_LABEL_OPTIONS):
            radio = QRadioButton(HIT_LABEL_SHORT_TEXT.get(label, label[:2].title()))
            radio.setObjectName("HitLabelRadio")
            radio.setChecked(label == hit.label)
            radio.setProperty("hitIndex", int(hit.index))
            radio.setProperty("hitLabel", label)
            radio.setToolTip(
                f"{self._display_hit_label(label)}\n"
                f"Hit #{hit.index} | role {getattr(hit, 'role', 'other')} | layers {secondary_hint}"
            )
            radio.clicked.connect(
                lambda checked, hit_index=hit.index, target_label=label, target_row=row: self._on_hit_label_radio_clicked(
                    int(target_row),
                    int(hit_index),
                    str(target_label),
                    bool(checked),
                )
            )
            group.addButton(radio)
            layout.addWidget(radio, index // 6, index % 6)
        return host

    def _on_hit_label_radio_clicked(self, row: int, hit_index: int, new_label: str, checked: bool) -> None:
        if not checked:
            return
        if 0 <= row < self.hits_table.rowCount() and self.hits_table.currentRow() != row:
            self._suspend_hit_selection_sync = True
            try:
                self.hits_table.selectRow(row)
            finally:
                self._suspend_hit_selection_sync = False
        self._on_hit_label_changed(hit_index, new_label)

    @staticmethod
    def _display_hit_label(label: str) -> str:
        display = {
            "kick_ghost": "kick ghost",
            "closed_hat": "closed hat",
            "open_hat": "open hat",
            "snare_ghost": "snare ghost",
            "snare_ruff": "snare ruff",
        }
        return display.get(label, label)

    def _set_hit_label_edit_enabled(self, enabled: bool) -> None:
        for row in range(self.hits_table.rowCount()):
            widget = self.hits_table.cellWidget(row, HITS_TABLE_COLUMN_LABEL)
            if widget is None:
                continue
            for radio in widget.findChildren(QRadioButton):
                radio.setEnabled(bool(enabled))

    def _set_hit_pool_edit_enabled(self, enabled: bool) -> None:
        for row in range(self.hits_table.rowCount()):
            widget = self.hits_table.cellWidget(row, HITS_TABLE_COLUMN_POOL)
            if widget is None:
                continue
            for checkbox in widget.findChildren(QCheckBox):
                checkbox.setEnabled(bool(enabled))

    def _on_hit_generator_enabled_changed(self, hit_index: int, generator_enabled: bool) -> None:
        if self._result is None:
            return

        selected_row = next(
            (row for row, hit in enumerate(self._result.transient_hits) if int(hit.index) == int(hit_index)),
            self.hits_table.currentRow(),
        )
        current_hit = next((hit for hit in self._result.transient_hits if int(hit.index) == int(hit_index)), None)
        if current_hit is None or bool(getattr(current_hit, "generator_enabled", True)) == bool(generator_enabled):
            return

        updated_hits = tuple(
            replace(hit, generator_enabled=bool(generator_enabled))
            if int(hit.index) == int(hit_index)
            else hit
            for hit in self._result.transient_hits
        )
        updated_result = replace(self._result, transient_hits=updated_hits)
        updated_result = self._refresh_result_sequences_from_hits(updated_result)
        self._result = updated_result
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._persist_hit_labels_for_result(updated_result)
        self._persist_detection_result(updated_result)

        self._populate_result(updated_result)
        self._populate_hits(updated_result)
        if 0 <= selected_row < self.hits_table.rowCount():
            self.hits_table.selectRow(selected_row)
        self._apply_hits_to_waveform(updated_result, preserve_existing=True)
        self._update_retimed_preview_state(updated_result)
        self._populate_generated_pattern(None)
        self._refresh_generated_pattern_state()
        state_text = "inclus" if generator_enabled else "retire"
        self._refresh_control_states(
            f"Hit #{hit_index} {state_text} des pools du generateur. Le pattern genere a ete reinitialise."
        )

    def _on_hit_label_changed(self, hit_index: int, new_label: str) -> None:
        if self._result is None or new_label not in MANUAL_HIT_LABEL_OPTIONS:
            return

        selected_row = next(
            (row for row, hit in enumerate(self._result.transient_hits) if int(hit.index) == int(hit_index)),
            self.hits_table.currentRow(),
        )
        current_hit = next((hit for hit in self._result.transient_hits if int(hit.index) == int(hit_index)), None)
        if current_hit is None or current_hit.label == new_label:
            return

        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=False)

        updated_hits = tuple(
            replace(hit, label=new_label, secondary_labels=(), layer_score=0.0, role=self._hit_role_for_label(new_label))
            if int(hit.index) == int(hit_index)
            else hit
            for hit in self._result.transient_hits
        )
        updated_result = replace(self._result, transient_hits=updated_hits)
        updated_result = self._refresh_result_sequences_from_hits(updated_result)
        self._result = updated_result
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._persist_hit_labels_for_result(updated_result)
        self._persist_detection_result(updated_result)

        self._populate_result(updated_result)
        self._populate_hits(updated_result)
        if 0 <= selected_row < self.hits_table.rowCount():
            self.hits_table.selectRow(selected_row)
        self._apply_hits_to_waveform(updated_result, preserve_existing=True)
        self._update_retimed_preview_state(updated_result)
        self._populate_generated_pattern(None)
        self._refresh_generated_pattern_state()
        self._refresh_control_states(
            f"Hit #{hit_index} relabelise en {new_label}. Le pattern genere a ete reinitialise."
        )

    @staticmethod
    def _hit_role_for_label(label: str) -> str:
        if label in {"kick", "snare", "clap"}:
            return "pillar"
        if label in {"closed_hat", "ride"}:
            return "texture"
        if label == "open_hat":
            return "accent"
        if label == "crash":
            return "punctuation"
        if label in {"kick_ghost", "snare_ghost"}:
            return "tension"
        if label in {"snare_ruff", "tom", "perc"}:
            return "fill"
        return "other"

    def _rebuild_hits_from_markers(self) -> None:
        if not self._marker_rebuild_available():
            QMessageBox.warning(
                self,
                "Markers indisponibles",
                "Charge un sample et lance d'abord une analyse pour reconstruire les hits depuis les markers.",
            )
            return

        marker_times = self._current_marker_times()
        self._stop_retimed_preview(update_status=False)
        if self._waveform_widget is not None:
            try:
                self._waveform_widget.stop_audio()
            except Exception:
                pass

        audio_snapshot = self._analysis_audio_snapshot()
        if audio_snapshot is None:
            QMessageBox.warning(self, "Audio indisponible", "Recharge d'abord la waveform avant de relancer le rebuild.")
            return

        self._rebuild_busy = True
        self.main_loading_bar.setVisible(True)
        self.waveform_loading_bar.setVisible(True)
        self.rebuild_markers_label.setText("Reanalyse depuis les markers en cours...")
        self._refresh_control_states("Reanalyse depuis les markers en cours...")
        worker = TaskWorker(
            lambda: detect_drum_from_markers(
                audio_snapshot[0],
                int(audio_snapshot[1]),
                marker_times,
                source_path=self._result.source_path if self._result else self.path_input.text().strip() or None,
                top_n=int(self.top_n_spin.value()),
            ),
            self,
        )
        self._rebuild_worker = worker
        worker.succeeded.connect(
            lambda rebuilt, marker_count=len(marker_times): self._dispatch_ui_callback(
                lambda: self._on_rebuild_success(rebuilt, marker_count)
            )
        )
        worker.failed.connect(
            lambda message: self._dispatch_ui_callback(lambda: self._on_rebuild_failure(message))
        )
        worker.finished.connect(
            lambda: self._dispatch_ui_callback(self._on_rebuild_finished)
        )
        worker.start()

    def _on_target_bpm_changed(self, _value: float) -> None:
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._retime_live_changes_pending = True
            self._refresh_active_retime_preview_message()
        elif not self._retimed_preview_playing:
            self._update_retimed_preview_state(self._result)
        self._refresh_generated_pattern_state()

    def _on_generator_target_bpm_changed(self, value: float) -> None:
        self._live_target_bpm_value = max(float(value), 1e-6)
        if hasattr(self, "live_target_bpm_spin"):
            current_live_value = float(self.live_target_bpm_spin.value())
            if not np.isclose(current_live_value, float(value), atol=0.05):
                self.live_target_bpm_spin.blockSignals(True)
                self.live_target_bpm_spin.setValue(float(value))
                self.live_target_bpm_spin.blockSignals(False)
        self._settings.setValue("generator_target_bpm", float(value))
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._generator_live_changes_pending = True
            self._schedule_live_generator_preview_refresh()
            self.generator_info_label.setText(
                "Lecture pattern en cours. L'ancienne version reste en lecture pendant que le nouveau tempo "
                "s'applique sur la boucle active."
            )
        if self._live_mode_enabled:
            self._live_gate_envelope_cache.clear()
            self._live_stutter_positions_cache_key = None
            self._live_stutter_positions_cache = None
            rebuilt_slots = self._rebuild_live_slot_previews_for_target_bpm(
                include_active=not self._preview_owner_is_active(PREVIEW_OWNER_LIVE)
            )
            self._refresh_live_mode_ui()
            if self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
                if rebuilt_slots:
                    self._refresh_control_states(
                        f"Mode live: slot(s) inactif(s) en rebuild pour {float(value):.1f} BPM. "
                        "Le slot actif garde son tempo actuel jusqu'au prochain switch."
                    )
                else:
                    self._refresh_control_states(
                        f"Mode live: le slot actif garde son tempo actuel. "
                        f"Regenerer ou switcher appliquera {float(value):.1f} BPM sans repitch."
                    )
            elif rebuilt_slots:
                self._refresh_control_states(
                    f"Mode live: slot(s) en rebuild pour {float(value):.1f} BPM."
                )

    def _on_live_target_bpm_changed(self, value: float) -> None:
        if not hasattr(self, "generator_target_bpm_spin"):
            self._live_target_bpm_value = max(float(value), 1e-6)
            return
        current_generator_value = float(self.generator_target_bpm_spin.value())
        if np.isclose(current_generator_value, float(value), atol=0.05):
            self._live_target_bpm_value = max(float(value), 1e-6)
            return
        self.generator_target_bpm_spin.setValue(float(value))
        self._refresh_generated_pattern_state()

    def _on_generator_gate_changed(self, value: int) -> None:
        self._settings.setValue("generator_gate", int(value))
        slider_dragging = bool(self.generator_gate_slider.isSliderDown() or self._generator_param_slider_dragging())
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._generator_live_changes_pending = True
            if slider_dragging:
                self._generator_gate_preview_pending = True
                self.generator_info_label.setText(
                    "Lecture pattern en cours. Nouveau gate en attente; il sera applique au relachement du slider."
                )
            else:
                self._generator_gate_preview_pending = False
                self._schedule_live_generator_preview_refresh()
                self.generator_info_label.setText(
                    "Lecture pattern en cours. Nouveau gate en cours d'application sur la boucle active."
                )
        if slider_dragging:
            self._generator_probability_refresh_pending = True
            return
        self._refresh_generated_pattern_state()

    def _on_generator_mono_choke_toggled(self, enabled: bool) -> None:
        self._settings.setValue("generator_mono_choke", bool(enabled))
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._stop_retimed_preview(update_status=False)
        self._update_retimed_preview_state(self._result)

        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._generator_live_changes_pending = True
            self._schedule_live_generator_preview_refresh()
            self.generator_info_label.setText(
                "Lecture pattern en cours. Le mode Mono choke global est en cours d'application sur la boucle active."
            )

        if self._live_mode_enabled and any(slot.preview is not None for slot in self._live_slots.values()):
            rebuilt_slots = self._rebuild_live_slot_previews_for_target_bpm(include_active=True)
            if rebuilt_slots and self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
                self.status_label.setText(
                    "Mode Mono choke global applique en live aux slots: " + ", ".join(rebuilt_slots)
                )

        self._refresh_generated_pattern_state()

    def _on_generator_bars_changed(self, value: int) -> None:
        self._settings.setValue("generator_bars", int(value))
        self._mark_generator_structure_changed()
        if self._generated_pattern is None:
            self._populate_generated_pattern(None)
        else:
            self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()

    def _build_preview_for_current_settings(
        self,
        result: DrumDetectionResult,
        samples: np.ndarray,
        sample_rate: int,
    ) -> RetimedPreview:
        return build_retimed_preview(
            samples,
            sample_rate,
            result.transient_hits,
            source_bpm=self._effective_detected_bpm(result),
            target_bpm=float(self.target_bpm_spin.value()),
            mode=self._preview_mode(),
            quantize_grid_division=self._quantize_grid_division(),
            quantize_strength=self._quantize_strength(),
            mono_choke=self._generator_mono_choke_enabled(),
        )

    def _generator_mono_choke_enabled(self) -> bool:
        return bool(getattr(self, "generator_mono_choke_check", None) and self.generator_mono_choke_check.isChecked())

    def _generator_fill_style(self) -> str:
        return str(self.generator_fill_style_combo.currentData() or FILL_STYLE_AUTO)

    def _generator_fill_type_weights(self) -> dict[str, float] | None:
        fill_style = self._generator_fill_style()
        if fill_style == FILL_STYLE_AUTO:
            return None
        return {fill_style: 1.0}

    def _refresh_generator_fill_style_label(self, pattern: GeneratedBreakPattern | None = None) -> None:
        if not hasattr(self, "generator_fill_current_label"):
            return
        fill_style = self._generator_fill_style()
        active_pattern = pattern if pattern is not None else self._generated_pattern
        if fill_style != FILL_STYLE_AUTO:
            self.generator_fill_current_label.setText(
                f"Force: {FILL_STYLE_LABELS.get(fill_style, fill_style.title())}"
            )
            return
        if active_pattern is None or not getattr(active_pattern, "fill_decisions", ()):
            self.generator_fill_current_label.setText("Auto")
            return
        active_fills = [
            (
                bar_index + 1,
                decision,
            )
            for bar_index, decision in enumerate(getattr(active_pattern, "fill_decisions", ()))
            if bool(getattr(decision, "active", False))
        ]
        if not active_fills:
            self.generator_fill_current_label.setText("Auto: none")
            return
        summary = " | ".join(
            f"B{bar_index}:{FILL_STYLE_LABELS.get(str(decision.fill_type), str(decision.fill_type).title())}"
            for bar_index, decision in active_fills[:3]
        )
        if len(active_fills) > 3:
            summary = f"{summary} | ..."
        self.generator_fill_current_label.setText(f"Auto current: {summary}")

    def _generator_params(self, *, seed: int) -> BreakPatternParams:
        return BreakPatternParams(
            energy=self.generator_energy_slider.value() / 100.0,
            kick_weight=self.generator_kick_slider.value() / 100.0,
            snare_weight=self.generator_snare_slider.value() / 100.0,
            hat_density=self.generator_hat_slider.value() / 100.0,
            ghost_density=self.generator_ghost_slider.value() / 100.0,
            synth_ghost_enabled=bool(self.generator_synth_ghost_enabled_check.isChecked()),
            ghost_vel_range=(
                float(self.generator_ghost_vel_min_slider.value()) / 100.0,
                float(self.generator_ghost_vel_max_slider.value()) / 100.0,
            ),
            ghost_pitch_range=(
                float(self.generator_ghost_pitch_min_slider.value()) / 10.0,
                float(self.generator_ghost_pitch_max_slider.value()) / 10.0,
            ),
            ghost_gate_ratio=float(self.generator_ghost_gate_slider.value()) / 100.0,
            fill_strength=self.generator_fill_slider.value() / 100.0,
            fill_type_weights=self._generator_fill_type_weights(),
            repeat_density=self.generator_repeat_slider.value() / 100.0,
            repeat_span=self.generator_repeat_length_slider.value() / 100.0,
            repeat_rate=self.generator_repeat_rate_slider.value() / 100.0,
            reverse_density=self.generator_reverse_slider.value() / 100.0,
            kick_roll_density=self.generator_kick_roll_slider.value() / 100.0,
            kick_roll_span=self.generator_kick_roll_length_slider.value() / 100.0,
            kick_roll_contrast=self.generator_kick_roll_contrast_slider.value() / 100.0,
            snare_stretch_density=self.generator_snare_stretch_slider.value() / 100.0,
            snare_stretch_span=self.generator_snare_stretch_length_slider.value() / 100.0,
            snare_stretch_amount=self.generator_snare_stretch_amount_slider.value() / 100.0,
            snare_stretch_vel_curve=str(self.generator_snare_stretch_curve_combo.currentData() or "decay"),
            pitch_mode=self._generator_pitch_mode(),
            pitch_scope=str(self.generator_pitch_scope_combo.currentData() or "snare"),
            pitch_scale=str(self.generator_pitch_scale_combo.currentData() or "chromatic"),
            pitch_root=int(self.generator_pitch_root_slider.value()),
            pitch_range=(
                float(self.generator_pitch_range_min_slider.value()),
                float(self.generator_pitch_range_max_slider.value()),
            ),
            pitch_sequence=self._parsed_generator_pitch_sequence(),
            pitch_curve=str(self.generator_pitch_curve_combo.currentData() or "up"),
            pitch_curve_range=(
                float(self.generator_pitch_curve_min_slider.value()),
                float(self.generator_pitch_curve_max_slider.value()),
            ),
            pitch_rate=str(self.generator_pitch_rate_combo.currentData() or "every_hit"),
            pitch_amount=self.generator_pitch_amount_slider.value() / 100.0,
            gate=max(0.05, self.generator_gate_slider.value() / 100.0),
            mono_choke=self._generator_mono_choke_enabled(),
            position_fidelity=self.generator_position_fidelity_slider.value() / 100.0,
            sequence_density=self.generator_sequence_density_slider.value() / 100.0,
            sequence_max_len=int(self.generator_sequence_max_len_spin.value()),
            sequence_role_lock=bool(self.generator_sequence_role_lock_check.isChecked()),
            user_motifs=[*self._generator_user_motifs],
            motif_density=self.generator_motif_density_slider.value() / 100.0,
            generation_profile=self._generator_profile(),
            enabled_passes=self._generator_enabled_passes(),
            velocity_spread=self.generator_velocity_slider.value() / 100.0,
            swing=self.generator_swing_slider.value() / 100.0,
            anti_repeat=self.generator_anti_repeat_slider.value() / 100.0,
            breath_factor=self.generator_breath_slider.value() / 100.0,
            seed=int(seed),
            bars=int(self.generator_bars_spin.value()),
        )

    def _inactive_live_slot_name(self) -> str:
        return "B" if self._live_active_slot == "A" else "A"

    def _select_live_view_slot(self, slot_name: str) -> None:
        normalized_slot = str(slot_name).strip().upper()
        if normalized_slot not in LIVE_SLOT_NAMES:
            return
        self._live_view_slot = normalized_slot
        for current_slot, button in getattr(self, "live_slot_view_buttons", {}).items():
            if button is not None:
                button.setChecked(str(current_slot).strip().upper() == normalized_slot)
        self._refresh_live_mode_ui()
        self._refresh_generated_pattern_state()

    def _live_display_slot_name(self) -> str:
        slot_name = str(self._live_view_slot or self._live_active_slot).strip().upper()
        if slot_name not in LIVE_SLOT_NAMES:
            return self._live_active_slot
        return slot_name

    def _live_display_pattern(self) -> GeneratedBreakPattern | None:
        slot = self._live_slots.get(self._live_display_slot_name())
        if slot is None:
            return None
        return slot.pattern

    def _live_slot_is_ready(self, slot_name: str) -> bool:
        slot = self._live_slots.get(str(slot_name))
        return bool(slot is not None and slot.preview is not None and slot.pattern is not None and slot.loop_stems)

    def _live_playable_slot_name(self) -> str | None:
        if self._live_slot_is_ready(self._live_active_slot):
            return self._live_active_slot
        inactive = self._inactive_live_slot_name()
        if self._live_slot_is_ready(inactive):
            return inactive
        return None

    def _on_live_mode_toggled(self, enabled: bool) -> None:
        self._live_mode_enabled = bool(enabled)
        self._settings.setValue("live_mode_enabled", self._live_mode_enabled)
        self._refresh_live_mode_visibility()
        self._set_waveform_shortcuts_enabled(True)
        self._set_live_shortcuts_enabled(self._live_mode_enabled)
        if not self._live_mode_enabled and self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            self._stop_retimed_preview(update_status=False)
        self._populate_generated_pattern(self._live_display_pattern() if self._live_mode_enabled else self._generated_pattern)
        self._refresh_live_mode_ui()
        self._refresh_control_states(self.status_label.text())

    def _refresh_live_mode_visibility(self) -> None:
        enabled = bool(self._live_mode_enabled)
        if hasattr(self, "generator_live_box"):
            self.generator_live_box.setVisible(enabled)
        if hasattr(self, "generator_live_section"):
            self.generator_live_section.setVisible(enabled)
        self._refresh_generator_ux_mode()

    def _refresh_live_mode_ui(self) -> None:
        if not self._main_tab_is_visible(MAIN_TAB_LIVE):
            self._live_tab_refresh_pending = True
            self._sync_live_pending_flash_timer(False)
            if self._live_mode_enabled:
                self._populate_generated_pattern(self._live_display_pattern())
            return
        self._live_tab_refresh_pending = False
        self._refresh_live_mode_ui_now()

    def _sync_live_slot_visual_properties(self, slot_name: str, *, state: str, pending: bool) -> None:
        slot_box = self.live_slot_boxes.get(slot_name)
        if slot_box is None:
            return
        pending_value = "true" if pending else "false"
        flash_value = "true" if (pending and self._live_pending_flash_on) else "false"
        if slot_box.property("liveSlotState") != state:
            slot_box.setProperty("liveSlotState", state)
        if slot_box.property("liveSlotPending") != pending_value:
            slot_box.setProperty("liveSlotPending", pending_value)
        if slot_box.property("liveSlotFlash") != flash_value:
            slot_box.setProperty("liveSlotFlash", flash_value)
        slot_box.style().unpolish(slot_box)
        slot_box.style().polish(slot_box)
        slot_box.update()

    def _sync_live_pending_flash_timer(self, enabled: bool) -> None:
        should_run = bool(enabled and self._live_mode_enabled)
        if not should_run:
            if self._live_pending_flash_timer.isActive():
                self._live_pending_flash_timer.stop()
            if self._live_pending_flash_on:
                self._live_pending_flash_on = False
            return
        if not self._live_pending_flash_timer.isActive():
            self._live_pending_flash_on = True
            self._live_pending_flash_timer.start()

    def _toggle_live_pending_flash(self) -> None:
        if not self._live_pending_switch_slot:
            self._sync_live_pending_flash_timer(False)
            return
        self._live_pending_flash_on = not self._live_pending_flash_on
        pending_slot = self._live_pending_switch_slot
        slot = self._live_slots.get(pending_slot)
        if slot is None:
            return
        visual_state = "playing" if (self._preview_owner_is_active(PREVIEW_OWNER_LIVE) and pending_slot == self._live_active_slot) else str(slot.status or "stale")
        self._sync_live_slot_visual_properties(pending_slot, state=visual_state, pending=True)

    def _refresh_live_mode_ui_now(self) -> None:
        if not hasattr(self, "generator_live_box"):
            return
        self._refresh_live_mode_visibility()
        pending = self._live_pending_switch_slot
        pending_text = f"Pending switch → Slot {pending}" if pending else "No switch pending"
        if hasattr(self, "live_pending_switch_label"):
            self.live_pending_switch_label.setText(pending_text)

        live_playing = self._preview_owner_is_active(PREVIEW_OWNER_LIVE)
        any_busy = self._analysis_busy or self._rebuild_busy or self._waveform_loading or self._preview_busy
        for slot_name in LIVE_SLOT_NAMES:
            slot = self._live_slots[slot_name]
            slot_box = self.live_slot_boxes.get(slot_name)
            status_label = self.live_slot_status_labels.get(slot_name)
            seed_label = self.live_slot_seed_labels.get(slot_name)
            params_label = self.live_slot_param_labels.get(slot_name)
            generate_button = self.live_slot_generate_buttons.get(slot_name)
            view_button = self.live_slot_view_buttons.get(slot_name)
            save_button = self.live_slot_save_buttons.get(slot_name)
            if slot_box is not None:
                suffix = " · Active" if slot_name == self._live_active_slot else ""
                if pending == slot_name:
                    suffix = f"{suffix} · Next".strip()
                if slot_name == self._live_display_slot_name():
                    suffix = f"{suffix} · View".strip()
                slot_box.setTitle(f"Slot {slot_name}{suffix}")
            if status_label is not None:
                if live_playing and slot_name == self._live_active_slot:
                    status_text = "▶ playing"
                    visual_state = "playing"
                elif slot.status == "generating":
                    status_text = "⟳ generating"
                    visual_state = "generating"
                elif slot.status == "ready":
                    status_text = "● ready"
                    visual_state = "ready"
                else:
                    status_text = "○ stale"
                    visual_state = "stale"
                status_label.setText(status_text)
            else:
                if live_playing and slot_name == self._live_active_slot:
                    visual_state = "playing"
                elif slot.status == "generating":
                    visual_state = "generating"
                elif slot.status == "ready":
                    visual_state = "ready"
                else:
                    visual_state = "stale"
            self._sync_live_slot_visual_properties(slot_name, state=visual_state, pending=(pending == slot_name))
            if seed_label is not None:
                seed_label.setText(f"Seed: {'-' if slot.seed is None else int(slot.seed)}")
            if params_label is not None:
                if slot.params is None:
                    params_label.setText("Energy -, Mode -, Bars -")
                else:
                    params_label.setText(
                        f"Energy {slot.params.energy:.2f} · {GENERATOR_MODE_LABELS.get(slot.mode, 'Classic')} · Bars {slot.params.bars}"
                    )
            signature = self._live_slot_compact_signature(slot_name)
            if self._live_slot_compact_signatures.get(slot_name) != signature:
                self._populate_live_slot_compact_table(slot_name)
                self._live_slot_compact_signatures[slot_name] = signature
            if generate_button is not None:
                generate_button.setEnabled(
                    self._live_mode_enabled
                    and (not any_busy)
                    and (not live_playing or slot_name != self._live_active_slot)
                    and self._result is not None
                    and (self._live_slot_workers.get(slot_name) is None or not self._live_slot_workers[slot_name].isRunning())
                    and (not self._analysis_stale)
                )
            if view_button is not None:
                view_button.setChecked(slot_name == self._live_display_slot_name())
                view_button.setEnabled(self._live_mode_enabled)
            if save_button is not None:
                save_button.setEnabled(
                    self._live_mode_enabled
                    and (not any_busy)
                    and slot.pattern is not None
                    and self._result is not None
                    and (not self._analysis_stale)
                )

        if hasattr(self, "live_play_button"):
            self.live_play_button.setEnabled(
                self._live_mode_enabled
                and (self._live_playable_slot_name() is not None)
                and (not self._analysis_busy)
                and (not self._waveform_loading)
                and (not self._preview_busy or live_playing)
            )
        if hasattr(self, "live_stop_button"):
            self.live_stop_button.setEnabled(live_playing)
        if hasattr(self, "live_switch_button"):
            target = self._inactive_live_slot_name()
            self.live_switch_button.setEnabled(
                self._live_mode_enabled
                and (
                    (not live_playing and self._live_slot_is_ready(target))
                    or (live_playing and self._live_slot_is_ready(target))
                )
            )
        if hasattr(self, "live_duplicate_a_to_b_button"):
            self.live_duplicate_a_to_b_button.setEnabled(
                self._live_mode_enabled and self._live_slots["A"].params is not None and not any_busy
            )
        if hasattr(self, "live_duplicate_b_to_a_button"):
            self.live_duplicate_b_to_a_button.setEnabled(
                self._live_mode_enabled and self._live_slots["B"].params is not None and not any_busy
            )
        if hasattr(self, "live_quick_render_button"):
            active_slot = self._live_slots.get(self._live_active_slot)
            self.live_quick_render_button.setEnabled(
                self._live_mode_enabled
                and (not any_busy)
                and (not self._analysis_stale)
                and active_slot is not None
                and active_slot.pattern is not None
                and self._result is not None
            )

        if hasattr(self, "live_stem_buttons"):
            self._sync_live_stem_toggle_state()

        for effect_name in getattr(self, "live_effect_value_labels", {}).keys():
            self._sync_live_effect_row(effect_name)

        if hasattr(self, "live_mode_info_label"):
            if live_playing:
                active = self._live_active_slot
                slot = self._live_slots[active]
                if slot.preview is not None and slot.pattern is not None:
                    next_text = f" Pending switch → {pending}." if pending else ""
                    live_target_bpm = self._effective_preview_target_bpm(slot.preview)
                    self.live_mode_info_label.setText(
                        f"Live slot {active} en lecture: {slot.pattern.event_count} evenement(s), "
                        f"{slot.pattern.step_count} steps, {live_target_bpm:.1f} BPM.{next_text}"
                    )
            elif pending:
                self.live_mode_info_label.setText(
                    f"Mode live arme. Slot {pending} attend le prochain demarrage ou switch."
                )
        self._sync_live_pending_flash_timer(bool(pending))
        if self._live_mode_enabled:
            self._populate_generated_pattern(self._live_display_pattern())

    def _sync_live_stem_toggle_state(self, stem_name: str | None = None) -> None:
        if not hasattr(self, "live_stem_buttons"):
            return
        stem_names = LIVE_STEM_NAMES if stem_name is None else (stem_name,)
        for current_stem in stem_names:
            button = self.live_stem_buttons.get(current_stem)
            if button is None:
                continue
            active = bool(self._live_stem_enabled.get(current_stem, True))
            button.setChecked(active)
            button.setToolTip(
                f"Stem {current_stem}: {'actif dans le mix live' if active else 'mute dans le mix live'}."
            )

    def _sync_live_effect_row(self, effect_name: str) -> None:
        value_label = getattr(self, "live_effect_value_labels", {}).get(effect_name)
        if value_label is not None:
            value_label.setText(self._live_effect_value_text(effect_name))
        targets = self._live_effect_targets.get(effect_name, {})
        for stem_name, button in getattr(self, "live_effect_target_buttons", {}).get(effect_name, {}).items():
            active = bool(targets.get(stem_name, True))
            button.setChecked(active)
            button.setToolTip(
                f"{LIVE_EFFECT_LABELS.get(effect_name, effect_name.title())} {'actif' if active else 'desactive'} sur {stem_name}."
            )
        all_button = getattr(self, "live_effect_all_buttons", {}).get(effect_name)
        if all_button is not None:
            active_count = sum(1 for stem_name in LIVE_STEM_NAMES if bool(targets.get(stem_name, True)))
            all_button.setText("All" if active_count == len(LIVE_STEM_NAMES) else f"{active_count}/{len(LIVE_STEM_NAMES)}")
            all_button.setToolTip(
                f"Active {LIVE_EFFECT_LABELS.get(effect_name, effect_name.title())} sur tous les stems."
            )

    def _rebuild_live_mix_plan(self) -> None:
        gain_value = float(self._live_effect_values.get("gain", LIVE_EFFECT_DEFAULTS["gain"]) or LIVE_EFFECT_DEFAULTS["gain"])
        lowpass_hz = max(0.0, float(self._live_effect_values.get("lowpass", LIVE_EFFECT_DEFAULTS["lowpass"]) or 0.0))
        highpass_hz = max(0.0, float(self._live_effect_values.get("highpass", LIVE_EFFECT_DEFAULTS["highpass"]) or 0.0))
        distortion_drive = float(np.clip(self._live_distortion_drive, 0.0, 1.0))
        distortion_tone = float(np.clip(self._live_distortion_tone, -1.0, 1.0))
        distortion_mix = float(np.clip(self._live_distortion_mix, 0.0, 1.0))
        bit_depth = int(np.clip(int(self._live_effect_values.get("bitcrush", LIVE_EFFECT_DEFAULTS["bitcrush"]) or 16), 2, 16))
        gate_ratio = float(np.clip(float(self._live_effect_values.get("gate", LIVE_EFFECT_DEFAULTS["gate"]) or 1.0), 0.0, 1.0))
        grouped_stems: dict[tuple[float, bool, bool, bool, bool, bool, bool], list[str]] = {}
        for stem_name in LIVE_STEM_NAMES:
            if not self._live_stem_enabled.get(stem_name, True):
                continue
            config_key = (
                gain_value if self._live_effect_targets.get("gain", {}).get(stem_name, True) else 1.0,
                lowpass_hz > 0.0 and self._live_effect_targets.get("lowpass", {}).get(stem_name, True),
                highpass_hz > 0.0 and self._live_effect_targets.get("highpass", {}).get(stem_name, True),
                distortion_mix > 0.001
                and distortion_drive > 0.001
                and self._live_effect_targets.get("distortion", {}).get(stem_name, True),
                bit_depth < 16 and self._live_effect_targets.get("bitcrush", {}).get(stem_name, True),
                gate_ratio < 0.999 and self._live_effect_targets.get("gate", {}).get(stem_name, True),
                self._live_effect_targets.get("stutter", {}).get(stem_name, True),
            )
            grouped_stems.setdefault(config_key, []).append(stem_name)
        stem_configs: list[LiveStemMixConfig] = []
        for group_index, (config_key, stem_names) in enumerate(grouped_stems.items(), start=1):
            gain, apply_lowpass, apply_highpass, apply_distortion, apply_bitcrush, apply_gate, apply_stutter = config_key
            ordered_names = tuple(stem_names)
            stem_configs.append(
                LiveStemMixConfig(
                    stem_names=ordered_names,
                    state_key=f"group_{group_index}_{'_'.join(ordered_names)}",
                    gain=float(gain),
                    apply_lowpass=bool(apply_lowpass),
                    apply_highpass=bool(apply_highpass),
                    apply_distortion=bool(apply_distortion),
                    apply_bitcrush=bool(apply_bitcrush),
                    apply_gate=bool(apply_gate),
                    apply_stutter=bool(apply_stutter),
                )
            )
        self._live_mix_plan = LiveMixPlan(
            stems=tuple(stem_configs),
            lowpass_hz=lowpass_hz,
            highpass_hz=highpass_hz,
            distortion_drive=distortion_drive,
            distortion_tone=distortion_tone,
            distortion_mix=distortion_mix,
            bit_depth=bit_depth,
            gate_ratio=gate_ratio,
        )
        self._clear_live_group_loop_cache()
        self._prewarm_live_group_loop_cache()

    def _set_all_live_stems(self, enabled: bool) -> None:
        for stem_name in LIVE_STEM_NAMES:
            self._live_stem_enabled[stem_name] = bool(enabled)
        self._reset_live_filter_state()
        self._rebuild_live_mix_plan()
        self._sync_live_stem_toggle_state()

    def _toggle_live_stem(self, stem_name: str) -> None:
        current = bool(self._live_stem_enabled.get(stem_name, True))
        self._live_stem_enabled[stem_name] = not current
        self._reset_live_filter_state()
        self._rebuild_live_mix_plan()
        self._sync_live_stem_toggle_state(stem_name)

    def _set_live_effect_targets(self, effect_name: str, enabled: bool) -> None:
        for stem_name in LIVE_STEM_NAMES:
            self._live_effect_targets.setdefault(effect_name, {})[stem_name] = bool(enabled)
        if effect_name in {"lowpass", "highpass"}:
            self._reset_live_filter_state()
        self._rebuild_live_mix_plan()
        self._sync_live_effect_row(effect_name)

    def _toggle_live_effect_target(self, effect_name: str, stem_name: str) -> None:
        targets = self._live_effect_targets.setdefault(effect_name, {name: True for name in LIVE_STEM_NAMES})
        targets[stem_name] = not bool(targets.get(stem_name, True))
        if effect_name in {"lowpass", "highpass"}:
            self._reset_live_filter_state()
        self._rebuild_live_mix_plan()
        self._sync_live_effect_row(effect_name)

    def _set_live_effect_value(self, effect_name: str, value: float | int | bool) -> None:
        self._live_effect_values[effect_name] = value
        if effect_name in {"lowpass", "highpass"} and float(value or 0.0) <= 0.0:
            self._reset_live_filter_state()
        if effect_name == "gate":
            self._live_gate_envelope_cache.clear()
        if effect_name == "stutter":
            self._live_stutter_positions_cache_key = None
            self._live_stutter_positions_cache = None
        self._rebuild_live_mix_plan()
        self._sync_live_effect_row(effect_name)

    def _set_live_distortion_param(self, parameter_name: str, value: float) -> None:
        normalized_name = str(parameter_name).strip().lower()
        if normalized_name == "drive":
            self._live_distortion_drive = float(np.clip(value, 0.0, 1.0))
            self._live_effect_values["distortion"] = self._live_distortion_drive
        elif normalized_name == "tone":
            self._live_distortion_tone = float(np.clip(value, -1.0, 1.0))
        elif normalized_name == "mix":
            self._live_distortion_mix = float(np.clip(value, 0.0, 1.0))
        else:
            return
        self._rebuild_live_mix_plan()
        self._sync_live_effect_row("distortion")

    def _live_effect_value_text(self, effect_name: str) -> str:
        value = self._live_effect_values.get(effect_name, LIVE_EFFECT_DEFAULTS.get(effect_name))
        if effect_name == "gain":
            return f"{float(value):.2f}"
        if effect_name in {"lowpass", "highpass"}:
            numeric = float(value or 0.0)
            return "off" if numeric <= 0.0 else f"{int(round(numeric))} Hz"
        if effect_name == "distortion":
            return (
                f"D {self._live_distortion_drive:.2f} "
                f"T {self._live_distortion_tone:+.2f} "
                f"M {self._live_distortion_mix:.2f}"
            )
        if effect_name == "bitcrush":
            numeric = int(value or 16)
            return "off" if numeric >= 16 else f"{numeric} bit"
        if effect_name == "gate":
            return f"{float(value):.2f}"
        if effect_name == "stutter":
            return "on" if bool(value) else "off"
        return str(value)

    def _generate_live_slot(
        self,
        slot_name: str,
        *,
        params: BreakPatternParams | None = None,
        seed: int | None = None,
        mode: str | None = None,
    ) -> None:
        if not self._live_mode_enabled:
            self.generator_live_mode_button.setChecked(True)
        if self._result is None:
            QMessageBox.warning(self, "Analyse requise", "Analyse d'abord un break avant d'utiliser le mode live.")
            return
        source_result = self._effective_generator_result(self._result)
        if source_result is None or not source_result.transient_hits:
            QMessageBox.warning(self, "Transients manquants", "Le break courant ne contient aucun transient exploitable.")
            return
        if self._analysis_stale:
            QMessageBox.information(
                self,
                "Recalcul requis",
                "La waveform a ete modifiee. Relance d'abord un rebuild ou une analyse avant de generer un slot live.",
            )
            return
        if self._preview_owner_is_active(PREVIEW_OWNER_LIVE) and slot_name == self._live_active_slot:
            QMessageBox.information(
                self,
                "Slot actif",
                "Le slot actif joue deja. Regenere plutot le slot inactif, puis switche au prochain step 1.",
            )
            return

        resolved_mode = str(mode or self._generator_mode() or GENERATOR_MODE_CLASSIC)
        resolved_seed = int(seed) if seed is not None else int(secrets.randbelow(999_999_999) + 1)
        resolved_params = replace(params, seed=resolved_seed) if params is not None else self._generator_params(seed=resolved_seed)
        self._live_generation_counter += 1
        token = self._live_generation_counter
        self._live_slot_tokens[slot_name] = token
        slot = self._live_slots[slot_name]
        slot.status = "generating"
        slot.params = resolved_params
        slot.seed = resolved_seed
        slot.mode = resolved_mode
        self._refresh_live_mode_ui()
        self._refresh_control_states(f"Generation live du slot {slot_name} en cours...")

        source_hits = tuple(source_result.transient_hits)
        source_sequences = tuple(source_result.hit_sequences)
        active_anchors = dict(self._generator_active_step_anchors(step_count=max(16, int(resolved_params.bars) * 16)))
        use_hybrid = resolved_mode == GENERATOR_MODE_HYBRID
        use_process_pool = _live_process_pool_allowed()
        shared_audio_spec = self._live_audio_shared_spec() if use_process_pool else None
        audio_snapshot: tuple[np.ndarray, int] | None = None
        if shared_audio_spec is None:
            audio_snapshot = self._analysis_audio_snapshot()
            if audio_snapshot is None:
                QMessageBox.warning(self, "Audio indisponible", "Recharge d'abord la waveform avant de generer un slot live.")
                return
        audio_samples = None if shared_audio_spec is not None else np.array(audio_snapshot[0], copy=True)
        audio_sample_rate = int(shared_audio_spec[2] if shared_audio_spec is not None else audio_snapshot[1])

        live_slot_kwargs = {
            "sequences": source_sequences,
            "anchors": active_anchors,
            "use_hybrid": bool(use_hybrid),
            "user_motifs": tuple(self._generator_user_motifs),
            "samples": audio_samples,
            "sample_rate": audio_sample_rate,
            "target_bpm": float(self.generator_target_bpm_spin.value()),
            "gate": max(0.05, self.generator_gate_slider.value() / 100.0),
            "mono_choke": self._generator_mono_choke_enabled(),
            "grouped_stem_names": self._live_grouped_stem_names(),
            "shared_audio_name": None if shared_audio_spec is None else shared_audio_spec[0],
            "shared_audio_shape": None if shared_audio_spec is None else shared_audio_spec[1],
        }
        if use_process_pool:
            worker = ProcessTaskWorker(
                _generate_live_slot_preview_process_task,
                source_hits,
                resolved_params,
                kwargs=live_slot_kwargs,
                executor_getter=_live_generation_process_pool,
                parent=self,
            )
        else:
            worker = TaskWorker(
                lambda: _generate_live_slot_preview_process_task(
                    source_hits,
                    resolved_params,
                    **live_slot_kwargs,
                ),
                self,
            )
        self._live_slot_workers[slot_name] = worker
        worker.succeeded.connect(
            lambda payload, current_slot=str(slot_name), current_token=int(token): self._dispatch_ui_callback(
                lambda: self._on_live_slot_pattern_ready(
                    current_slot,
                    current_token,
                    payload,
                )
            )
        )
        worker.failed.connect(
            lambda message, current_slot=str(slot_name), current_token=int(token): self._dispatch_ui_callback(
                lambda: self._on_live_slot_generation_failed(
                    current_slot,
                    current_token,
                    message,
                )
            )
        )
        worker.finished.connect(
            lambda current_slot=str(slot_name), current_token=int(token): self._dispatch_ui_callback(
                lambda: self._on_live_slot_generation_finished(current_slot, current_token)
            )
        )
        worker.start()

    def _on_live_slot_pattern_ready(
        self,
        slot_name: str,
        token: int,
        payload: tuple[
            int,
            BreakPatternParams,
            GeneratedBreakPattern,
            RetimedPreview,
            dict[tuple[str, ...], np.ndarray],
        ],
    ) -> None:
        if self._live_slot_tokens.get(slot_name) != int(token):
            return
        seed, params, pattern, preview, group_loop_cache = payload
        normalized_preview_audio = self._normalize_preview_audio(preview.audio)
        normalized_loop_audio = self._normalize_preview_audio(preview.loop_audio if preview.loop_audio is not None else preview.audio)
        stems = {
            stem_name: self._normalize_preview_audio(preview.stems.get(stem_name, preview.audio * 0.0))
            for stem_name in LIVE_STEM_NAMES
        }
        loop_stems = {
            stem_name: self._normalize_preview_audio(
                preview.loop_stems.get(stem_name, preview.loop_audio if preview.loop_audio is not None else preview.audio * 0.0)
            )
            for stem_name in LIVE_STEM_NAMES
        }
        slot = self._live_slots[slot_name]
        slot.pattern = pattern
        slot.params = params
        slot.seed = int(seed)
        slot.preview = replace(
            preview,
            audio=normalized_preview_audio,
            loop_audio=normalized_loop_audio,
            stems=stems,
            loop_stems=loop_stems,
        )
        slot.stems = stems
        slot.loop_stems = loop_stems
        slot.group_loop_cache = {
            tuple(stem_names): self._normalize_preview_audio(group_audio)
            for stem_names, group_audio in group_loop_cache.items()
        }
        slot.status = "ready"
        if self._preview_owner_is_active(PREVIEW_OWNER_LIVE) and slot_name == self._live_active_slot:
            slot.status = "playing"
        self._refresh_live_mode_ui()
        self._refresh_control_states(
            f"Slot {slot_name} pret: {pattern.event_count} evenement(s), seed {seed}."
        )

    def _on_live_slot_generation_failed(self, slot_name: str, token: int, message: str) -> None:
        if self._live_slot_tokens.get(slot_name) != int(token):
            return
        slot = self._live_slots[slot_name]
        slot.status = "stale"
        self._refresh_live_mode_ui()
        QMessageBox.warning(self, "Generation live impossible", message)
        self._refresh_control_states(f"Generation live impossible pour le slot {slot_name}: {message}")

    def _on_live_slot_generation_finished(self, slot_name: str, token: int) -> None:
        worker = self._live_slot_workers.get(slot_name)
        if worker is not None and not worker.isRunning():
            self._live_slot_workers[slot_name] = None
        self._release_retained_live_audio_shared_memories()
        if self._live_slot_tokens.get(slot_name) != int(token):
            return
        self._refresh_live_mode_ui()
        self._refresh_control_states(self.status_label.text())
        self._maybe_close_after_background_tasks()

    def _duplicate_live_slot(self, source_slot: str, target_slot: str) -> None:
        source = self._live_slots.get(source_slot)
        if source is None or source.params is None or source.seed is None:
            QMessageBox.information(
                self,
                "Duplication impossible",
                f"Le slot {source_slot} n'a encore aucun pattern pret a dupliquer.",
            )
            return
        duplicated_params = replace(source.params, seed=int(source.seed))
        self._generate_live_slot(
            target_slot,
            params=duplicated_params,
            seed=int(source.seed),
            mode=str(source.mode or GENERATOR_MODE_CLASSIC),
        )
        self._refresh_control_states(f"Duplication {source_slot}→{target_slot} en cours...")

    def _switch_live_slots_next_cycle(self) -> None:
        target = self._inactive_live_slot_name()
        if not self._live_slot_is_ready(target):
            QMessageBox.information(
                self,
                "Switch impossible",
                f"Le slot {target} n'est pas encore pret. Genere-le d'abord.",
            )
            return
        if not self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            self._live_active_slot = target
            self._live_pending_switch_slot = None
            self._refresh_live_mode_ui()
            self._refresh_control_states(f"Slot actif bascule sur {target}.")
            return
        self._live_pending_switch_slot = target
        self._refresh_live_mode_ui()
        self._refresh_control_states(f"Switch live arme: slot {target} prendra la main au prochain step 1.")

    def _play_live_active_slot(self) -> None:
        slot_name = self._live_playable_slot_name()
        if slot_name is None:
            QMessageBox.information(
                self,
                "Slot manquant",
                "Genere d'abord au moins un slot live avant de lancer la lecture.",
            )
            return
        self._live_active_slot = slot_name
        self._live_pending_switch_slot = None
        preview = self._live_slots[slot_name].preview
        if preview is None:
            return
        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=False)
        self._reset_live_filter_state()
        self._start_retimed_preview_playback(preview, owner=PREVIEW_OWNER_LIVE)
        self._refresh_live_mode_ui()

    def _rebuild_live_slot_previews_for_target_bpm(self, *, include_active: bool) -> tuple[str, ...]:
        use_process_pool = _live_process_pool_allowed()
        shared_audio_spec = self._live_audio_shared_spec() if use_process_pool else None
        audio_snapshot = None if shared_audio_spec is not None else self._analysis_audio_snapshot()
        if shared_audio_spec is None and audio_snapshot is None:
            return ()
        rebuilt_slots: list[str] = []
        for slot_name in LIVE_SLOT_NAMES:
            slot = self._live_slots.get(slot_name)
            if slot is None or slot.pattern is None or slot.preview is None:
                continue
            if self._live_slot_workers.get(slot_name) is not None and self._live_slot_workers[slot_name].isRunning():
                continue
            if (
                self._preview_owner_is_active(PREVIEW_OWNER_LIVE)
                and slot_name == self._live_active_slot
                and not include_active
            ):
                continue
            self._rebuild_live_slot_preview(
                slot_name,
                samples=None if audio_snapshot is None else np.array(audio_snapshot[0], dtype=np.float32, copy=True),
                sample_rate=int(shared_audio_spec[2] if shared_audio_spec is not None else audio_snapshot[1]),
                shared_audio_name=None if shared_audio_spec is None else shared_audio_spec[0],
                shared_audio_shape=None if shared_audio_spec is None else shared_audio_spec[1],
            )
            rebuilt_slots.append(slot_name)
        return tuple(rebuilt_slots)

    def _rebuild_live_slot_preview(
        self,
        slot_name: str,
        *,
        samples: np.ndarray | None,
        sample_rate: int,
        shared_audio_name: str | None = None,
        shared_audio_shape: tuple[int, ...] | None = None,
    ) -> None:
        slot = self._live_slots.get(slot_name)
        if slot is None or slot.pattern is None:
            return
        self._live_generation_counter += 1
        token = self._live_generation_counter
        self._live_slot_tokens[slot_name] = token
        slot.status = "generating"
        pattern = slot.pattern
        target_bpm = float(self.generator_target_bpm_spin.value())
        gate = max(0.05, self.generator_gate_slider.value() / 100.0)
        mono_choke = self._generator_mono_choke_enabled()
        live_preview_kwargs = {
            "target_bpm": target_bpm,
            "gate": gate,
            "mono_choke": mono_choke,
            "grouped_stem_names": self._live_grouped_stem_names(),
            "shared_audio_name": shared_audio_name,
            "shared_audio_shape": shared_audio_shape,
        }
        if _live_process_pool_allowed():
            worker = ProcessTaskWorker(
                _build_live_pattern_preview_process_task,
                None if samples is None else np.array(samples, dtype=np.float32, copy=True),
                int(sample_rate),
                pattern,
                kwargs=live_preview_kwargs,
                executor_getter=_live_generation_process_pool,
                parent=self,
            )
        else:
            worker = TaskWorker(
                lambda: _build_live_pattern_preview_process_task(
                    None if samples is None else np.array(samples, dtype=np.float32, copy=True),
                    int(sample_rate),
                    pattern,
                    **live_preview_kwargs,
                ),
                self,
            )
        self._live_slot_workers[slot_name] = worker
        worker.succeeded.connect(
            lambda preview, current_slot=str(slot_name), current_token=int(token): self._dispatch_ui_callback(
                lambda: self._on_live_slot_preview_rebuilt(current_slot, current_token, preview)
            )
        )
        worker.failed.connect(
            lambda message, current_slot=str(slot_name), current_token=int(token): self._dispatch_ui_callback(
                lambda: self._on_live_slot_generation_failed(current_slot, current_token, message)
            )
        )
        worker.finished.connect(
            lambda current_slot=str(slot_name), current_token=int(token): self._dispatch_ui_callback(
                lambda: self._on_live_slot_generation_finished(current_slot, current_token)
            )
        )
        worker.start()

    def _on_live_slot_preview_rebuilt(
        self,
        slot_name: str,
        token: int,
        payload: tuple[RetimedPreview, dict[tuple[str, ...], np.ndarray]],
    ) -> None:
        if self._live_slot_tokens.get(slot_name) != int(token):
            return
        preview, group_loop_cache = payload
        slot = self._live_slots[slot_name]
        normalized_preview_audio = self._normalize_preview_audio(preview.audio)
        normalized_loop_audio = self._normalize_preview_audio(
            preview.loop_audio if preview.loop_audio is not None else preview.audio
        )
        stems = {
            stem_name: self._normalize_preview_audio(preview.stems.get(stem_name, preview.audio * 0.0))
            for stem_name in LIVE_STEM_NAMES
        }
        loop_stems = {
            stem_name: self._normalize_preview_audio(
                preview.loop_stems.get(
                    stem_name,
                    preview.loop_audio if preview.loop_audio is not None else preview.audio * 0.0,
                )
            )
            for stem_name in LIVE_STEM_NAMES
        }
        slot.preview = replace(
            preview,
            audio=normalized_preview_audio,
            loop_audio=normalized_loop_audio,
            stems=stems,
            loop_stems=loop_stems,
        )
        slot.stems = stems
        slot.loop_stems = loop_stems
        slot.group_loop_cache = {
            tuple(stem_names): self._normalize_preview_audio(group_audio)
            for stem_names, group_audio in group_loop_cache.items()
        }
        if self._preview_owner_is_active(PREVIEW_OWNER_LIVE) and slot_name == self._live_active_slot:
            slot.status = "playing"
            self._retimed_preview = slot.preview
        else:
            slot.status = "ready"
        self._refresh_live_mode_ui()
        self._refresh_control_states(
            f"Slot {slot_name} recale a {float(preview.target_bpm):.1f} BPM sans repitch."
        )

    def _stop_live_playback(self) -> None:
        if self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            self._stop_retimed_preview(update_status=True)

    def _on_live_stutter_pressed(self) -> None:
        self._live_stutter_pressed = True
        self._live_effect_values["stutter"] = True
        self._capture_live_stutter_anchor()
        self._sync_live_effect_row("stutter")

    def _on_live_stutter_released(self) -> None:
        self._live_stutter_pressed = False
        self._live_effect_values["stutter"] = False
        self._sync_live_effect_row("stutter")

    def _capture_live_stutter_anchor(self) -> None:
        if not self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            return
        slot = self._live_slots.get(self._live_active_slot)
        if slot is None or slot.preview is None or slot.pattern is None:
            return
        source_step_frames = self._live_source_step_frame_count(slot)
        if source_step_frames <= 0:
            return
        cursor = float(self._retime_stream_cursor)
        self._live_stutter_hold_start_frame = int((cursor // float(source_step_frames)) * float(source_step_frames))
        self._live_stutter_positions_cache_key = None
        self._live_stutter_positions_cache = None

    def _live_step_frame_count(self) -> int:
        slot = self._live_slots.get(self._live_active_slot)
        if slot is None or slot.pattern is None or slot.preview is None:
            return 0
        return self._live_source_step_frame_count(slot)

    def _live_target_bpm(self) -> float:
        return max(float(getattr(self, "_live_target_bpm_value", 120.0)), 1e-6)

    def _effective_preview_target_bpm(self, preview: RetimedPreview | None) -> float:
        if preview is None:
            return self._live_target_bpm()
        return max(float(preview.target_bpm), 1e-6)

    def _live_playback_rate(self, slot: PatternSlot) -> float:
        return 1.0

    def _live_source_step_frame_count(self, slot: PatternSlot) -> int:
        preview = slot.preview
        pattern = slot.pattern
        if preview is None or pattern is None or pattern.step_count <= 0:
            return 0
        total_frames = int(next(iter(slot.loop_stems.values())).shape[0]) if slot.loop_stems else 0
        if total_frames <= 0:
            playback_audio = preview.loop_audio if preview.loop_audio is not None else preview.audio
            total_frames = int(self._normalize_preview_audio(playback_audio).shape[0])
        if total_frames <= 0:
            return 0
        return max(1, int(round(total_frames / float(pattern.step_count))))

    def _live_grouped_stem_names(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(config.stem_names)
            for config in self._live_mix_plan.stems
            if len(config.stem_names) > 1
        )

    def _prewarm_live_group_loop_cache(self, slot_name: str | None = None) -> None:
        if not self._live_mode_enabled:
            return
        grouped_stem_names = [config.stem_names for config in self._live_mix_plan.stems if len(config.stem_names) > 1]
        if not grouped_stem_names:
            return
        target_slot_names = LIVE_SLOT_NAMES if slot_name is None else (str(slot_name),)
        for current_slot_name in target_slot_names:
            slot = self._live_slots.get(current_slot_name)
            if slot is None or slot.preview is None or not slot.loop_stems:
                continue
            for stem_names in grouped_stem_names:
                self._live_group_loop_audio(slot, stem_names)

    def _clear_live_group_loop_cache(self, slot_name: str | None = None) -> None:
        target_slot_names = LIVE_SLOT_NAMES if slot_name is None else (str(slot_name),)
        for current_slot_name in target_slot_names:
            slot = self._live_slots.get(current_slot_name)
            if slot is None:
                continue
            slot.group_loop_cache.clear()

    def _live_group_loop_audio(self, slot: PatternSlot, stem_names: tuple[str, ...]) -> np.ndarray | None:
        if not stem_names:
            return None
        if len(stem_names) == 1:
            return slot.loop_stems.get(stem_names[0])
        cached = slot.group_loop_cache.get(stem_names)
        if cached is not None:
            return cached
        group_audio: np.ndarray | None = None
        for stem_name in stem_names:
            stem_audio = slot.loop_stems.get(stem_name)
            if stem_audio is None or stem_audio.shape[0] <= 0:
                continue
            if group_audio is None:
                group_audio = stem_audio.astype(np.float32, copy=True)
            else:
                group_audio += stem_audio
        if group_audio is None:
            return None
        slot.group_loop_cache[stem_names] = group_audio
        return group_audio

    def _reset_live_filter_state(self, stem_name: str | None = None) -> None:
        if stem_name is None:
            self._live_lowpass_state.clear()
            self._live_highpass_state.clear()
            self._live_gate_envelope_cache.clear()
            self._live_stutter_positions_cache_key = None
            self._live_stutter_positions_cache = None
            return
        self._live_lowpass_state.pop(stem_name, None)
        self._live_highpass_state.pop(stem_name, None)

    def _reset_live_slots(self) -> None:
        if self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            self._stop_retimed_preview(update_status=False)
        for slot_name, worker in self._live_slot_workers.items():
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
            self._live_slot_workers[slot_name] = None
            self._live_slot_tokens[slot_name] += 1
            self._live_slots[slot_name] = PatternSlot()
        self._live_active_slot = "A"
        self._live_view_slot = "A"
        self._live_pending_switch_slot = None
        self._live_stutter_pressed = False
        self._live_slot_compact_signatures.clear()
        self._reset_live_filter_state()
        self._refresh_live_mode_ui()

    def _should_use_process_pattern_generation(self) -> bool:
        return bool(
            _process_pool_allowed()
            and (
            self._generator_mode() == GENERATOR_MODE_HYBRID
            or self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
            or self._preview_owner_is_active(PREVIEW_OWNER_RETIME)
            or self._preview_owner_is_active(PREVIEW_OWNER_LIVE)
            )
        )

    def _live_slot_preview_step_count(self, slot_name: str) -> int:
        slot = self._live_slots.get(str(slot_name))
        if slot is not None:
            if slot.pattern is not None and int(slot.pattern.step_count) > 0:
                return int(slot.pattern.step_count)
            if slot.params is not None and int(slot.params.bars) > 0:
                return max(16, int(slot.params.bars) * 16)
        return max(16, int(self.generator_bars_spin.value()) * 16)

    def _mark_generator_structure_changed(self) -> None:
        self._generator_structure_revision += 1
        self._live_slot_compact_signatures.clear()

    def _live_slot_compact_signature(self, slot_name: str) -> tuple[object, ...]:
        slot = self._live_slots.get(str(slot_name))
        step_count = self._live_slot_preview_step_count(str(slot_name))
        pattern_id = id(slot.pattern) if slot is not None and slot.pattern is not None else None
        bars = int(slot.params.bars) if slot is not None and slot.params is not None else max(1, step_count // 16)
        return (
            pattern_id,
            int(step_count),
            int(bars),
            int(self._generator_structure_revision),
        )

    def _live_slot_compact_structure_enabled(self) -> bool:
        return bool(
            self._live_mode_enabled
            and (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._analysis_stale)
        )

    def _live_slot_pattern_step(self, slot_name: str, step_index: int) -> GeneratedPatternStep | None:
        slot = self._live_slots.get(str(slot_name))
        if slot is None or slot.pattern is None:
            return None
        steps = tuple(slot.pattern.steps)
        zero_based = int(step_index) - 1
        if 0 <= zero_based < len(steps):
            candidate = steps[zero_based]
            if int(getattr(candidate, "step_index", step_index)) == int(step_index):
                return candidate
        for candidate in steps:
            if int(getattr(candidate, "step_index", 0)) == int(step_index):
                return candidate
        return None

    def _set_live_slot_compact_header_item(
        self,
        table: QTableWidget,
        column: int,
        *,
        highlighted: bool,
    ) -> None:
        header_item = table.horizontalHeaderItem(int(column))
        if header_item is None:
            header_item = QTableWidgetItem()
            table.setHorizontalHeaderItem(int(column), header_item)
        header_item.setText(self._live_slot_compact_header_text(int(column) + 1, highlighted=highlighted))
        header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if highlighted:
            header_item.setBackground(QColor("#d9eff4"))
            header_item.setForeground(QColor("#101318"))
        else:
            header_item.setBackground(QColor("#1e2430"))
            header_item.setForeground(QColor("#eef1f6"))

    def _set_live_slot_compact_step_items(
        self,
        slot_name: str,
        step_index: int,
        *,
        highlighted: bool,
        structure_enabled: bool | None = None,
    ) -> None:
        table = self.live_slot_pattern_tables.get(str(slot_name))
        if table is None:
            return
        normalized_step_index = int(step_index)
        if normalized_step_index <= 0:
            return
        row_group = (normalized_step_index - 1) // 16
        column = (normalized_step_index - 1) % 16
        event_row = row_group * 3
        anchor_row = event_row + 1
        lock_row = event_row + 2
        if lock_row >= table.rowCount() or column >= table.columnCount():
            return
        if structure_enabled is None:
            structure_enabled = self._live_slot_compact_structure_enabled()
        step = self._live_slot_pattern_step(str(slot_name), normalized_step_index)
        short_text, label = self._live_slot_compact_step_text(step)
        anchor = self._generator_anchor_for_step(normalized_step_index)
        locked = self._generator_step_locked(normalized_step_index)
        background = self._live_slot_compact_step_background(label)
        if anchor is not None:
            background = self._blend_generator_colors(background, QColor("#6e4525"), 0.42)
        if locked:
            background = self._blend_generator_colors(background, QColor("#d1a142"), 0.24)
        if highlighted:
            background = self._blend_generator_colors(background, QColor("#eff7ff"), 0.42)
        display_text = f"▶{short_text}" if highlighted else short_text
        item = table.item(event_row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(event_row, column, item)
        item.setText(display_text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(QColor("#ffffff") if highlighted else self._live_slot_compact_step_color(label))
        item.setBackground(background)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setToolTip(
            f"Step {normalized_step_index} | "
            f"{'silence' if step is None or step.label == 'silence' else str(step.label)}"
            f"\nAnchor: {GENERATOR_STEP_ANCHOR_LABELS.get(anchor, 'auto')}"
            f"\nLock: {'on' if locked else 'off'}"
        )
        anchor_item = self._live_slot_compact_anchor_item(normalized_step_index, highlighted=highlighted)
        lock_item = self._live_slot_compact_lock_item(normalized_step_index, highlighted=highlighted)
        if not structure_enabled:
            anchor_item.setFlags(Qt.ItemFlag.NoItemFlags)
            lock_item.setFlags(Qt.ItemFlag.NoItemFlags)
        table.setItem(anchor_row, column, anchor_item)
        table.setItem(lock_row, column, lock_item)

    def _live_current_playback_step_index(self) -> int | None:
        if not self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            return None
        slot = self._live_slots.get(self._live_active_slot)
        if slot is None or slot.pattern is None or slot.preview is None or int(slot.pattern.step_count) <= 0:
            return None
        step_frames = self._live_source_step_frame_count(slot)
        if step_frames <= 0:
            return None
        total_frames = int(self._retime_stream_total_frames)
        if total_frames <= 0 and slot.loop_stems:
            total_frames = int(next(iter(slot.loop_stems.values())).shape[0])
        cursor = float(self._retime_stream_cursor)
        if total_frames > 0:
            cursor %= float(total_frames)
        step_index = int(cursor // float(step_frames)) + 1
        return int(np.clip(step_index, 1, max(1, int(slot.pattern.step_count))))

    def _update_live_compact_playback_highlight_from_stream(self) -> None:
        if not self._main_tab_is_visible(MAIN_TAB_LIVE):
            return
        if not self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            self._set_live_compact_playback_highlight(None, None)
            return
        step_index = self._live_current_playback_step_index()
        if step_index is None:
            self._set_live_compact_playback_highlight(None, None)
            return
        self._set_live_compact_playback_highlight(self._live_active_slot, step_index)

    @staticmethod
    def _live_slot_compact_step_text(step: GeneratedPatternStep | None) -> tuple[str, str]:
        if step is None or step.label == "silence":
            return "·", "silence"
        label = str(step.label or "other")
        return HIT_LABEL_SHORT_TEXT.get(label, label[:2].upper()), label

    @staticmethod
    def _live_slot_compact_step_color(label: str) -> QColor:
        normalized = str(label or "silence")
        if normalized == "silence":
            return QColor("#5f6d82")
        if normalized.startswith("kick"):
            return QColor("#72e6d1")
        if normalized in {"snare", "snare_ghost", "snare_ruff", "clap"}:
            return QColor("#f1c26a")
        if "hat" in normalized or normalized in {"ride", "crash"}:
            return QColor("#8cb7ff")
        return QColor("#d5dde9")

    @staticmethod
    def _live_slot_compact_step_background(label: str) -> QColor:
        normalized = str(label or "silence")
        if normalized == "silence":
            return QColor("#161b24")
        if normalized.startswith("kick"):
            return QColor("#1d3b38")
        if normalized in {"snare", "snare_ghost", "snare_ruff", "clap"}:
            return QColor("#3b301d")
        if "hat" in normalized or normalized in {"ride", "crash"}:
            return QColor("#1f2f46")
        if normalized in {"tom", "perc"}:
            return QColor("#243726")
        return QColor("#262c36")

    @staticmethod
    def _live_slot_compact_header_text(step_number: int, *, highlighted: bool) -> str:
        return f"▶{int(step_number)}" if highlighted else str(int(step_number))

    def _live_slot_compact_anchor_item(self, step_index: int, *, highlighted: bool = False) -> QTableWidgetItem:
        anchor = self._generator_anchor_for_step(step_index)
        background, foreground, _role_text = self._generator_step_palette(step_index)
        if anchor is not None:
            overlay = QColor("#70839d") if anchor == "silence" else QColor("#6e4525")
            background = self._blend_generator_colors(background, overlay, 0.55 if anchor == "silence" else 0.5)
            foreground = QColor("#dbe4f2") if anchor == "silence" else QColor("#ffe3ac")
        if highlighted:
            background = self._blend_generator_colors(background, QColor("#eff7ff"), 0.24)
            foreground = QColor("#ffffff")
        item = QTableWidgetItem(GENERATOR_STEP_ANCHOR_SHORT_LABELS.get(anchor, "·"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(foreground)
        item.setBackground(background)
        item.setToolTip(self._generator_anchor_button_tooltip(step_index, anchor))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _live_slot_compact_lock_item(self, step_index: int, *, highlighted: bool = False) -> QTableWidgetItem:
        locked = self._generator_step_locked(step_index)
        background, foreground, _role_text = self._generator_step_palette(step_index)
        background = self._blend_generator_colors(background, QColor("#1d2430"), 0.35)
        text = "·"
        if locked:
            background = self._blend_generator_colors(background, QColor("#d1a142"), 0.42)
            foreground = QColor("#fff0c9")
            text = "L"
        if highlighted:
            background = self._blend_generator_colors(background, QColor("#eff7ff"), 0.24)
            foreground = QColor("#ffffff")
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(foreground)
        item.setBackground(background)
        item.setToolTip(
            f"Step {step_index} | {'verrouille' if locked else 'non verrouille'}\n"
            "Clique pour verrouiller ou deverrouiller ce step."
        )
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _on_live_slot_compact_cell_clicked(self, _slot_name: str, row: int, column: int) -> None:
        if column < 0:
            return
        step_index = ((row // 3) * 16) + int(column) + 1
        row_kind = int(row) % 3
        if row_kind == 1:
            self._on_generator_anchor_step_clicked(step_index)
            return
        if row_kind == 2:
            self._on_generator_lock_step_clicked(step_index)
            return
        self._focus_generated_step(step_index, autoplay=False)

    def _set_live_compact_playback_highlight(self, slot_name: str | None, step_index: int | None) -> None:
        normalized_slot = str(slot_name) if slot_name is not None else None
        normalized_step = int(step_index) if step_index is not None else None
        previous_slot = self._live_compact_highlight_slot
        previous_step = self._live_compact_highlight_step
        if previous_slot == normalized_slot and previous_step == normalized_step:
            return
        self._live_compact_highlight_slot = normalized_slot
        self._live_compact_highlight_step = normalized_step
        previous_column = ((int(previous_step) - 1) % 16) if previous_step is not None else None
        current_column = ((int(normalized_step) - 1) % 16) if normalized_step is not None else None
        structure_enabled = self._live_slot_compact_structure_enabled()
        if previous_slot is not None and previous_step is not None:
            self._set_live_slot_compact_step_items(
                previous_slot,
                previous_step,
                highlighted=False,
                structure_enabled=structure_enabled,
            )
            if previous_column is not None and (previous_slot != normalized_slot or previous_column != current_column):
                previous_table = self.live_slot_pattern_tables.get(previous_slot)
                if previous_table is not None:
                    self._set_live_slot_compact_header_item(previous_table, previous_column, highlighted=False)
        if normalized_slot is not None and normalized_step is not None:
            current_table = self.live_slot_pattern_tables.get(normalized_slot)
            if current_table is not None:
                if current_column is not None:
                    self._set_live_slot_compact_header_item(current_table, current_column, highlighted=True)
                self._set_live_slot_compact_step_items(
                    normalized_slot,
                    normalized_step,
                    highlighted=True,
                    structure_enabled=structure_enabled,
                )

    def _populate_live_slot_compact_table(self, slot_name: str) -> None:
        table = self.live_slot_pattern_tables.get(str(slot_name))
        if table is None:
            return
        step_count = self._live_slot_preview_step_count(str(slot_name))
        bars = max(1, int(np.ceil(float(step_count) / 16.0)))
        structure_enabled = self._live_slot_compact_structure_enabled()
        table.clearContents()
        table.setColumnCount(16)
        table.setRowCount(bars * 3)
        highlighted_step = (
            int(self._live_compact_highlight_step)
            if self._live_compact_highlight_slot == str(slot_name) and self._live_compact_highlight_step is not None
            else None
        )
        highlighted_local_step = ((highlighted_step - 1) % 16) if highlighted_step is not None else None
        table.setHorizontalHeaderLabels([str(index) for index in range(1, 17)])
        vertical_labels: list[str] = []
        for bar_index in range(bars):
            vertical_labels.extend((f"Evt {bar_index + 1}", f"Anc {bar_index + 1}", f"Lock {bar_index + 1}"))
            for column in range(16):
                step_index = bar_index * 16 + column + 1
                event_row = bar_index * 3
                anchor_row = event_row + 1
                lock_row = event_row + 2
                if step_index > step_count:
                    blank_item = QTableWidgetItem("")
                    blank_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    table.setItem(event_row, column, blank_item)
                    table.setItem(anchor_row, column, QTableWidgetItem(""))
                    table.setItem(lock_row, column, QTableWidgetItem(""))
                    continue
                self._set_live_slot_compact_step_items(
                    str(slot_name),
                    step_index,
                    highlighted=(highlighted_step == step_index),
                    structure_enabled=structure_enabled,
                )
                continue
                step = pattern_steps.get(step_index)
                short_text, label = self._live_slot_compact_step_text(step)
                anchor = self._generator_anchor_for_step(step_index)
                locked = self._generator_step_locked(step_index)
                background = self._live_slot_compact_step_background(label)
                if anchor is not None:
                    background = self._blend_generator_colors(background, QColor("#6e4525"), 0.42)
                if locked:
                    background = self._blend_generator_colors(background, QColor("#d1a142"), 0.24)
                if highlighted_step == step_index:
                    background = self._blend_generator_colors(background, QColor("#eff7ff"), 0.42)
                display_text = f"▶{short_text}" if highlighted_step == step_index else short_text
                item = QTableWidgetItem(display_text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor("#ffffff") if highlighted_step == step_index else self._live_slot_compact_step_color(label))
                item.setBackground(background)
                item.setToolTip(
                    f"Step {step_index} | {'silence' if step is None or step.label == 'silence' else str(step.label)}"
                    f"\nAnchor: {GENERATOR_STEP_ANCHOR_LABELS.get(anchor, 'auto')}"
                    f"\nLock: {'on' if locked else 'off'}"
                )
                table.setItem(event_row, column, item)
                anchor_item = self._live_slot_compact_anchor_item(step_index, highlighted=highlighted_step == step_index)
                lock_item = self._live_slot_compact_lock_item(step_index, highlighted=highlighted_step == step_index)
                if not structure_enabled:
                    anchor_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    lock_item.setFlags(Qt.ItemFlag.NoItemFlags)
                table.setItem(anchor_row, column, anchor_item)
                table.setItem(lock_row, column, lock_item)
        table.setVerticalHeaderLabels(vertical_labels)
        for bar_index in range(bars):
            event_row = bar_index * 3
            table.setRowHeight(event_row, 26)
            table.setRowHeight(event_row + 1, 22)
            table.setRowHeight(event_row + 2, 22)
        for column in range(16):
            self._set_live_slot_compact_header_item(
                table,
                column,
                highlighted=(highlighted_local_step == column),
            )
            continue
            header_item = table.horizontalHeaderItem(column)
            if header_item is None:
                continue
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if highlighted_local_step == (column + 1):
                header_item.setBackground(QColor("#d9eff4"))
                header_item.setForeground(QColor("#101318"))
            else:
                header_item.setBackground(QColor("#1e2430"))
                header_item.setForeground(QColor("#eef1f6"))
        content_height = int(table.horizontalHeader().height()) + int(table.verticalHeader().length()) + (table.frameWidth() * 2) + 8
        target_height = max(168, content_height)
        table.setMinimumHeight(target_height)
        table.setMaximumHeight(target_height)

    def _generator_active_step_anchors(self, *, step_count: int | None = None) -> dict[int, str]:
        limit = int(step_count) if step_count is not None else max(16, int(self.generator_bars_spin.value()) * 16)
        return {
            int(step_index): str(anchor)
            for step_index, anchor in self._generator_step_anchors.items()
            if 1 <= int(step_index) <= int(limit) and anchor in GENERATOR_STEP_ANCHOR_LABELS
        }

    def _generator_anchor_summary_text(self, *, step_count: int | None = None) -> str:
        anchors = self._generator_active_step_anchors(step_count=step_count)
        if not anchors:
            return "Ancres: aucune."
        preview = [
            f"{step}:{GENERATOR_STEP_ANCHOR_LABELS.get(anchor, anchor)}"
            for step, anchor in sorted(anchors.items())
        ]
        if len(preview) > 10:
            preview = [*preview[:10], "..."]
        return f"Ancres: {', '.join(preview)}."

    def _generator_active_locked_steps(self, *, step_count: int | None = None) -> tuple[int, ...]:
        limit = int(step_count) if step_count is not None else max(16, int(self.generator_bars_spin.value()) * 16)
        return tuple(sorted(step for step in self._generator_locked_steps if 1 <= int(step) <= int(limit)))

    def _generator_lock_summary_text(self, *, step_count: int | None = None) -> str:
        locked_steps = self._generator_active_locked_steps(step_count=step_count)
        if not locked_steps:
            return "Locks: aucun."
        preview = [str(step) for step in locked_steps[:12]]
        if len(locked_steps) > 12:
            preview.append("...")
        return f"Locks: {', '.join(preview)}."

    def _generator_anchor_for_step(self, step_index: int) -> str | None:
        return self._generator_step_anchors.get(int(step_index))

    def _generator_step_locked(self, step_index: int) -> bool:
        return int(step_index) in self._generator_locked_steps

    def _cycle_generator_anchor_for_step(self, step_index: int) -> str | None:
        current = self._generator_anchor_for_step(step_index)
        try:
            current_index = GENERATOR_STEP_ANCHOR_ORDER.index(current)
        except ValueError:
            current_index = 0
        next_anchor = GENERATOR_STEP_ANCHOR_ORDER[(current_index + 1) % len(GENERATOR_STEP_ANCHOR_ORDER)]
        if next_anchor is None:
            self._generator_step_anchors.pop(int(step_index), None)
        else:
            self._generator_step_anchors[int(step_index)] = str(next_anchor)
        return next_anchor

    def _generator_anchor_button_tooltip(self, step_index: int, anchor: str | None) -> str:
        current = GENERATOR_STEP_ANCHOR_LABELS.get(anchor, "auto")
        return (
            f"Step {step_index} | anchor {current}\n"
            "Clique pour cycler: auto -> kick -> snare -> clap -> hat -> ghost -> other -> silence.\n"
            "Cette ancre est appliquee au prochain Generate random ou au reroll de ce step."
        )

    def _build_generator_anchor_button(self, step_index: int) -> QPushButton:
        button = QPushButton()
        button.setObjectName("AnchorButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setMinimumHeight(32)
        button.setMaximumHeight(32)
        button.clicked.connect(lambda _checked=False, current_step=int(step_index): self._on_generator_anchor_step_clicked(current_step))
        self._update_generator_anchor_button(button, int(step_index))
        return button

    def _update_generator_anchor_button(self, button: QPushButton, step_index: int) -> None:
        anchor = self._generator_anchor_for_step(step_index)
        button.setText(GENERATOR_STEP_ANCHOR_SHORT_LABELS.get(anchor, "·"))
        button.setToolTip(self._generator_anchor_button_tooltip(step_index, anchor))
        button.setProperty("generatorStepRole", self._generator_step_role(step_index))
        button.setProperty("anchorActive", bool(anchor))
        button.setProperty("anchorKind", "auto" if anchor is None else anchor)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _refresh_generator_anchor_button(self, step_index: int) -> None:
        if step_index < 1:
            return
        column = int(step_index) - 1
        if column < 0 or column >= self.generator_sequence_table.columnCount():
            return
        button = self.generator_sequence_table.cellWidget(0, column)
        if isinstance(button, QPushButton):
            self._update_generator_anchor_button(button, int(step_index))

    def _build_generator_lock_button(self, step_index: int) -> QPushButton:
        button = QPushButton()
        button.setObjectName("LockButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setIconSize(QSize(14, 14))
        button.setMinimumHeight(32)
        button.setMaximumHeight(32)
        button.clicked.connect(lambda _checked=False, current_step=int(step_index): self._on_generator_lock_step_clicked(current_step))
        self._update_generator_lock_button(button, int(step_index))
        return button

    def _update_generator_lock_button(self, button: QPushButton, step_index: int) -> None:
        locked = self._generator_step_locked(step_index)
        self._set_button_icon(
            button,
            QStyle.StandardPixmap.SP_MessageBoxWarning,
            qtawesome_name="fa5s.lock" if locked else "fa5s.unlock",
            color="#f0c05a" if locked else "#8fa0bb",
        )
        button.setText("")
        button.setToolTip(
            f"Step {step_index} | {'verrouille' if locked else 'non verrouille'}\n"
            "Clique pour verrouiller ou deverrouiller ce step. Un step locke garde son contenu au prochain Generate random."
        )
        button.setProperty("generatorStepRole", self._generator_step_role(step_index))
        button.setProperty("lockActive", locked)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _refresh_generator_lock_button(self, step_index: int) -> None:
        if step_index < 1:
            return
        column = int(step_index) - 1
        if column < 0 or column >= self.generator_sequence_table.columnCount():
            return
        button = self.generator_sequence_table.cellWidget(1, column)
        if isinstance(button, QPushButton):
            self._update_generator_lock_button(button, int(step_index))

    def _refresh_generator_anchor_summary(self) -> None:
        pattern = self._generated_pattern
        step_count = int(pattern.step_count) if pattern is not None else max(16, int(self.generator_bars_spin.value()) * 16)
        if pattern is None:
            self.generator_summary_label.setText(
                f"Aucun pattern genere pour le moment. Prochaine generation: {self._generator_pattern_shape_text()}. "
                f"{self._generator_anchor_summary_text(step_count=step_count)} "
                f"{self._generator_lock_summary_text(step_count=step_count)}"
            )
            return
        self.generator_summary_label.setText(
            f"Pattern genere: {pattern.event_count} evenement(s) sur {pattern.bars} bar{'s' if pattern.bars > 1 else ''}. "
            f"Repartition: {pattern.summary}. {self._generator_anchor_summary_text(step_count=pattern.step_count)} "
            f"{self._generator_lock_summary_text(step_count=pattern.step_count)}"
        )

    def _on_generator_anchor_step_clicked(self, step_index: int) -> None:
        anchor = self._cycle_generator_anchor_for_step(step_index)
        self._mark_generator_structure_changed()
        self._refresh_generator_anchor_button(step_index)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
        self._refresh_live_mode_ui()
        anchor_text = GENERATOR_STEP_ANCHOR_LABELS.get(anchor, "auto")
        if self._generated_pattern is None:
            self.generator_info_label.setText(
                f"Anchor step {step_index}: {anchor_text}. Regle quelques temps forts, puis clique sur Generate random."
            )
        else:
            self.generator_info_label.setText(
                f"Anchor step {step_index}: {anchor_text}. Clique sur Generate random pour reconstruire tout le pattern, "
                f"ou reroll ce step pour l'appliquer localement."
            )

    def _on_generator_lock_step_clicked(self, step_index: int) -> None:
        step = int(step_index)
        if step in self._generator_locked_steps:
            self._generator_locked_steps.discard(step)
            state = "off"
        else:
            self._generator_locked_steps.add(step)
            state = "on"
        self._mark_generator_structure_changed()
        self._refresh_generator_lock_button(step)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
        self._refresh_live_mode_ui()
        self.generator_info_label.setText(
            f"Lock step {step}: {state}. Le prochain Generate random {'gardera' if state == 'on' else 'pourra modifier'} ce step."
        )

    def _clear_generator_anchors(self) -> None:
        if not self._generator_step_anchors:
            return
        self._generator_step_anchors.clear()
        self._mark_generator_structure_changed()
        for step_index in range(1, self.generator_sequence_table.columnCount() + 1):
            self._refresh_generator_anchor_button(step_index)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
        self._refresh_live_mode_ui()
        self.generator_info_label.setText("Toutes les ancres ont ete retirees.")

    def _clear_generator_locks(self) -> None:
        if not self._generator_locked_steps:
            return
        self._generator_locked_steps.clear()
        self._mark_generator_structure_changed()
        for step_index in range(1, self.generator_sequence_table.columnCount() + 1):
            self._refresh_generator_lock_button(step_index)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
        self._refresh_live_mode_ui()
        self.generator_info_label.setText("Tous les locks ont ete retires.")

    def _generated_pattern_available(self) -> bool:
        return bool(
            (not self._analysis_stale)
            and self._generated_pattern is not None
            and self._loaded_audio_samples is not None
            and self._loaded_audio_sample_rate
            and self._generated_pattern.event_count > 0
        )

    def _set_generator_sequence_reroll_enabled(self, enabled: bool) -> None:
        for column in range(self.generator_sequence_table.columnCount()):
            button = self.generator_sequence_table.cellWidget(6, column)
            if isinstance(button, QPushButton):
                button.setEnabled(bool(enabled))

    def _set_generator_sequence_structure_enabled(self, enabled: bool) -> None:
        for row in (0, 1):
            for column in range(self.generator_sequence_table.columnCount()):
                button = self.generator_sequence_table.cellWidget(row, column)
                if isinstance(button, QPushButton):
                    button.setEnabled(bool(enabled))
        self.generator_clear_anchors_button.setEnabled(bool(enabled))
        self.generator_clear_locks_button.setEnabled(bool(enabled))

    def _refresh_generated_pattern_state(self) -> None:
        self._refresh_generator_fill_style_label()
        self._refresh_generator_probability_preview()
        available = (
            self._generated_pattern_available()
            and (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._preview_busy)
        )
        self.generator_play_button.setEnabled(available)
        self.generator_stop_button.setEnabled(
            (not self._preview_busy) and self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
        )
        if self._preview_busy and self.generator_loading_bar.isVisible():
            return
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR) and self._retimed_preview is not None:
            self.generator_seed_value.setText(
                str(self._generated_pattern.seed) if self._generated_pattern is not None else "auto"
            )
            if self._generator_live_changes_pending:
                self.generator_info_label.setText(
                    "Lecture actuelle conserve encore l'ancienne version. "
                    "Les nouveaux changements sont prets; clique sur Play generated quand tu veux les appliquer."
                )
                return
            self.generator_info_label.setText(
                f"{self._preview_playback_label(self._retimed_preview, looping=self._generator_loop_enabled())}: "
                f"{self._retimed_preview.segment_count} evenement(s), "
                f"{self._retimed_preview.target_bpm:.1f} BPM, {self._retimed_preview.duration_s:.2f}s."
            )
            return
        if self._generator_busy:
            self.generator_info_label.setText("Generation du pattern en cours...")
            return
        if self._analysis_stale:
            self.generator_info_label.setText(
                "La waveform ou les markers ont change. Rebuild ou relance l'analyse avant de generer / relire un pattern."
            )
            return
        if self._generated_pattern is None:
            self.generator_seed_value.setText("auto")
            self.generator_info_label.setText(self._default_generator_info_text())
            return
        self.generator_seed_value.setText(str(self._generated_pattern.seed))
        self.generator_info_label.setText(
            f"Pattern pret: {self._generated_pattern.event_count} evenement(s) sur {self._generated_pattern.step_count} steps "
            f"({self._generated_pattern.bars} bar{'s' if self._generated_pattern.bars > 1 else ''}), "
            f"lecture a {self.generator_target_bpm_spin.value():.1f} BPM. "
            f"Derniere seed {self._generated_pattern.seed} gardee en lecture seule pour reproduire cette variation si besoin."
        )

    def _populate_generated_pattern(self, pattern: GeneratedBreakPattern | None) -> None:
        if not self._main_tab_is_visible(MAIN_TAB_ANALYZE, MAIN_TAB_GENERATOR):
            self._generator_tab_refresh_pending = True
            self._refresh_generator_anchor_summary()
            return
        self._generator_tab_refresh_pending = False
        self._refresh_generator_fill_style_label(pattern)
        steps = list(pattern.steps) if pattern is not None else []
        self._populate_generated_sequence(pattern)
        self.generator_table.setRowCount(len(steps))
        if not steps:
            self._refresh_generator_anchor_summary()
            return
        for row, step in enumerate(steps):
            source_text = self._generator_step_source_text(step)
            values = (
                str(step.step_index),
                step.label,
                "-" if step.label == "silence" else str(step.velocity),
                source_text,
                ", ".join(step.tags) if step.tags else "-",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.generator_table.setItem(row, column, item)
        self.generator_table.resizeColumnsToContents()
        self._ensure_table_column_widths(self.generator_table, {0: 56, 1: 150, 2: 70, 3: 72, 4: 220})
        self._refresh_generator_anchor_summary()

    def _populate_generated_sequence(self, pattern: GeneratedBreakPattern | None) -> None:
        step_count = max(16, int(pattern.step_count)) if pattern is not None else max(16, int(self.generator_bars_spin.value()) * 16)
        self.generator_sequence_table.clearSelection()
        self.generator_sequence_table.setRowCount(7)
        self.generator_sequence_table.setColumnCount(step_count)
        self.generator_sequence_table.setHorizontalHeaderLabels([str(index) for index in range(1, step_count + 1)])
        self.generator_sequence_table.setVerticalHeaderLabels(("Anchor", "Lock", "Event", "Vel", "Source", "FX", "Reroll"))
        sequence_header = self.generator_sequence_table.horizontalHeader()
        for column in range(step_count):
            sequence_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

        if pattern is None:
            for column in range(step_count):
                self.generator_sequence_table.setCellWidget(0, column, self._build_generator_anchor_button(column + 1))
                self.generator_sequence_table.setCellWidget(1, column, self._build_generator_lock_button(column + 1))
                for row, placeholder in enumerate(("-", "-", "-", "-"), start=2):
                    item = QTableWidgetItem(placeholder)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.generator_sequence_table.setItem(row, column, item)
                button = QPushButton("Reroll")
                self._configure_icon_button(
                    button,
                    QStyle.StandardPixmap.SP_BrowserReload,
                    "Regenerer ce step",
                    width=34,
                    qtawesome_name="fa5s.redo-alt",
                )
                button.setEnabled(False)
                self.generator_sequence_table.setCellWidget(6, column, button)
                self._style_generator_sequence_column(column)
            return

        for column, step in enumerate(pattern.steps):
            self.generator_sequence_table.setCellWidget(0, column, self._build_generator_anchor_button(step.step_index))
            self.generator_sequence_table.setCellWidget(1, column, self._build_generator_lock_button(step.step_index))
            source_text = self._generator_step_source_text(step)
            row_values = (
                self._generator_step_label(step.label),
                "-" if step.label == "silence" else str(step.velocity),
                source_text,
                self._generator_step_fx_text(step),
            )
            tooltip = (
                f"Step {step.step_index}\n"
                f"Event: {step.label}\n"
                f"Velocity: {'-' if step.label == 'silence' else step.velocity}\n"
                f"Source: {source_text if source_text != '-' else '-'}"
                f"{'' if step.source_label is None else f' ({step.source_label})'}\n"
                f"FX: {self._generator_step_fx_tooltip(step)}\n"
                f"Tags: {', '.join(step.tags) if step.tags else '-'}"
            )
            for row, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(tooltip)
                self.generator_sequence_table.setItem(row + 2, column, item)
            button = QPushButton("Reroll")
            self._configure_icon_button(
                button,
                QStyle.StandardPixmap.SP_BrowserReload,
                f"Regenerer uniquement le step {step.step_index} avec les reglages courants",
                width=34,
                qtawesome_name="fa5s.redo-alt",
            )
            button.setToolTip(
                f"Regenerer uniquement le step {step.step_index} avec les reglages courants, en gardant le reste du pattern."
            )
            button.clicked.connect(lambda _checked=False, current_step=step.step_index: self._reroll_generated_step(current_step))
            self.generator_sequence_table.setCellWidget(6, column, button)
            self._style_generator_sequence_column(column)

    @staticmethod
    def _generator_step_source_text(step) -> str:
        if getattr(step, "source_hit_index", None) is None:
            return "-"
        return str(int(step.source_hit_index))

    @staticmethod
    def _generator_step_label(label: str) -> str:
        labels = {
            "kick_ghost": "Kick G",
            "closed_hat": "Hat C",
            "open_hat": "Hat O",
            "ghost_snare": "Ghost",
            "snare_ghost": "Snr G",
            "snare_ruff": "Ruff",
            "ride": "Ride",
            "silence": "-",
        }
        return labels.get(label, label.title())

    @staticmethod
    def _generator_step_pitch_shift(step) -> float:
        try:
            return float(getattr(step, "pitch_shift", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _generator_pitch_fx_text(cls, pitch_shift: float) -> str:
        if abs(float(pitch_shift)) <= 1e-6:
            return ""
        rounded = round(float(pitch_shift), 1)
        if abs(rounded - round(rounded)) <= 1e-6:
            return f"Pch {int(round(rounded)):+d}"
        return f"Pch {rounded:+.1f}"

    @classmethod
    def _generator_step_fx_text(cls, step) -> str:
        repeat_meta = cls._generator_repeat_metadata(step)
        reverse_active = cls._generator_step_is_reverse(step)
        kick_roll_meta = cls._generator_kick_roll_metadata(step)
        snare_stretch_meta = cls._generator_snare_stretch_metadata(step)
        pitch_shift = cls._generator_step_pitch_shift(step)
        parts: list[str] = []
        if repeat_meta["repeat"]:
            parts.append(f"Rpt x{int(repeat_meta['count'])}")
        if reverse_active:
            reverse_from = next(
                (
                    str(tag).removeprefix("reverse_from_")
                    for tag in getattr(step, "tags", ())
                    if str(tag).startswith("reverse_from_")
                ),
                "",
            )
            suffix = {
                "kick": "K",
                "snare": "S",
                "clap": "C",
            }.get(reverse_from, reverse_from[:1].upper() if reverse_from else "")
            parts.append(f"Rev<-{suffix}" if suffix else "Rev")
        if kick_roll_meta["active"]:
            parts.append(f"KRoll {int(kick_roll_meta['span'])}")
        stretch_points = cls._generator_snare_stretch_points_text(step, snare_stretch_meta)
        if stretch_points:
            parts.append(stretch_points)
        pitch_text = cls._generator_pitch_fx_text(pitch_shift)
        if pitch_text:
            parts.append(pitch_text)
        return " | ".join(parts) if parts else "-"

    @classmethod
    def _generator_step_fx_tooltip(cls, step) -> str:
        repeat_meta = cls._generator_repeat_metadata(step)
        reverse_active = cls._generator_step_is_reverse(step)
        kick_roll_meta = cls._generator_kick_roll_metadata(step)
        snare_stretch_meta = cls._generator_snare_stretch_metadata(step)
        pitch_shift = cls._generator_step_pitch_shift(step)
        parts: list[str] = []
        if repeat_meta["repeat"]:
            if repeat_meta["zone"]:
                parts.append(f"repeat zone x{int(repeat_meta['count'])} sur {int(repeat_meta['span'])} step(s)")
            else:
                parts.append(f"repeat x{int(repeat_meta['count'])}")
        if reverse_active:
            reverse_from = next(
                (
                    str(tag).removeprefix("reverse_from_")
                    for tag in getattr(step, "tags", ())
                    if str(tag).startswith("reverse_from_")
                ),
                "",
            )
            if reverse_from:
                parts.append(f"reverse tail depuis {reverse_from}")
            else:
                parts.append("reverse tail")
        if kick_roll_meta["active"]:
            if kick_roll_meta["zone"]:
                parts.append(f"kick roll sur {int(kick_roll_meta['span'])} step(s)")
            else:
                parts.append("kick roll")
        if snare_stretch_meta["zone"]:
            parts.append(
                "retrigger expo "
                f"x{int(snare_stretch_meta['span'])} "
                f"a {int(round(float(snare_stretch_meta['amount']) * 100.0))}% "
                f"curve {snare_stretch_meta['curve']} "
                f"({int(snare_stretch_meta['retrigger_count'])} hit(s))"
            )
        if abs(pitch_shift) > 1e-6:
            parts.append(f"pitch shift {pitch_shift:+.1f} demi-ton(s)")
        return ", ".join(parts) if parts else "-"

    @staticmethod
    def _generator_step_role(step_index: int) -> str:
        if step_index <= 0:
            return "subdivision"
        if (step_index - 1) % 16 == 0:
            return "bar_start"
        if (step_index - 1) % 4 == 0:
            return "beat"
        return "subdivision"

    @classmethod
    def _generator_step_palette(cls, step_index: int) -> tuple[QColor, QColor, str]:
        role = cls._generator_step_role(step_index)
        if role == "bar_start":
            return QColor("#382c19"), QColor("#f0c05a"), "Debut de mesure"
        if role == "beat":
            return QColor("#21343c"), QColor("#eef1f6"), "Temps fort"
        return QColor("#101318"), QColor("#cbd3df"), "Subdivision"

    @staticmethod
    def _blend_generator_colors(base: QColor, overlay: QColor, amount: float) -> QColor:
        mix = float(np.clip(amount, 0.0, 1.0))
        return QColor(
            int(round(base.red() + ((overlay.red() - base.red()) * mix))),
            int(round(base.green() + ((overlay.green() - base.green()) * mix))),
            int(round(base.blue() + ((overlay.blue() - base.blue()) * mix))),
        )

    @staticmethod
    def _generator_fill_metadata(step) -> dict[str, object]:
        raw_tags = getattr(step, "tags", ())
        if not isinstance(raw_tags, (tuple, list, set, frozenset)):
            raw_tags = ()
        tags = tuple(raw_tags)
        reserved = "fill_reserved_zone" in tags
        pending = "fill_pending" in tags
        active = "fill" in tags
        fill_type = next(
            (
                str(tag).removeprefix("fill_type_")
                for tag in tags
                if str(tag).startswith("fill_type_")
            ),
            "",
        )
        source = next(
            (
                str(tag).removeprefix("fill_source_")
                for tag in tags
                if str(tag).startswith("fill_source_")
            ),
            "generated",
        )
        start = "fill_reserved_zone_start" in tags
        end = "fill_reserved_zone_end" in tags
        zone_start = next(
            (
                int(str(tag).removeprefix("fill_zone_start_"))
                for tag in tags
                if str(tag).startswith("fill_zone_start_")
            ),
            16,
        )
        zone_end = next(
            (
                int(str(tag).removeprefix("fill_zone_end_"))
                for tag in tags
                if str(tag).startswith("fill_zone_end_")
            ),
            16,
        )
        return {
            "reserved": reserved,
            "pending": pending,
            "active": active,
            "type": fill_type,
            "source": source,
            "start": start,
            "end": end,
            "zone_start": zone_start,
            "zone_end": zone_end,
        }

    @staticmethod
    def _generator_repeat_metadata(step) -> dict[str, int | bool]:
        raw_tags = getattr(step, "tags", ())
        if not isinstance(raw_tags, (tuple, list, set, frozenset)):
            raw_tags = ()
        tags = tuple(raw_tags)
        repeat_active = "repeat" in tags
        zone_active = "repeat_zone" in tags
        zone_start = "repeat_zone_start" in tags
        zone_end = "repeat_zone_end" in tags
        repeat_count = 1
        zone_span = 1
        for tag in tags:
            text = str(tag)
            if text.startswith("repeat_count_"):
                try:
                    repeat_count = max(1, int(text.removeprefix("repeat_count_")))
                except ValueError:
                    repeat_count = 1
            elif text.startswith("repeat_zone_span_"):
                try:
                    zone_span = max(1, int(text.removeprefix("repeat_zone_span_")))
                except ValueError:
                    zone_span = 1
        return {
            "repeat": repeat_active,
            "zone": zone_active,
            "start": zone_start,
            "end": zone_end,
            "count": repeat_count,
            "span": zone_span,
        }

    @staticmethod
    def _generator_step_is_reverse(step) -> bool:
        raw_tags = getattr(step, "tags", ())
        if not isinstance(raw_tags, (tuple, list, set, frozenset)):
            return False
        return "reverse" in set(raw_tags)

    @staticmethod
    def _generator_kick_roll_metadata(step) -> dict[str, int | bool]:
        raw_tags = getattr(step, "tags", ())
        if not isinstance(raw_tags, (tuple, list, set, frozenset)):
            raw_tags = ()
        tags = tuple(raw_tags)
        active = "kick_roll" in tags
        zone = "kick_roll_zone" in tags
        zone_start = "kick_roll_zone_start" in tags
        zone_end = "kick_roll_zone_end" in tags
        high = "kick_roll_hi" in tags
        low = "kick_roll_lo" in tags
        zone_span = 1
        for tag in tags:
            text = str(tag)
            if text.startswith("kick_roll_zone_span_"):
                try:
                    zone_span = max(1, int(text.removeprefix("kick_roll_zone_span_")))
                except ValueError:
                    zone_span = 1
        return {
            "active": active,
            "zone": zone,
            "start": zone_start,
            "end": zone_end,
            "high": high,
            "low": low,
            "span": zone_span,
        }

    @staticmethod
    def _generator_snare_stretch_metadata(step) -> dict[str, int | float | bool]:
        raw_tags = getattr(step, "tags", ())
        if not isinstance(raw_tags, (tuple, list, set, frozenset)):
            raw_tags = ()
        tags = tuple(raw_tags)
        active = "snare_stretch" in tags
        tail = "snare_stretch_tail" in tags or "snare_stretch_hold" in tags
        zone = "snare_stretch_zone" in tags
        zone_start = "snare_stretch_zone_start" in tags
        zone_end = "snare_stretch_zone_end" in tags
        span = 1
        amount = 0.0
        curve = "decay"
        for tag in tags:
            text = str(tag)
            if text.startswith("snare_stretch_zone_span_"):
                try:
                    span = max(1, int(text.removeprefix("snare_stretch_zone_span_")))
                except ValueError:
                    span = 1
            elif text.startswith("snare_stretch_amount_"):
                try:
                    amount = float(np.clip(int(text.removeprefix("snare_stretch_amount_")) / 100.0, 0.0, 1.0))
                except ValueError:
                    amount = 0.0
            elif text.startswith("snare_stretch_curve_"):
                curve = str(text.removeprefix("snare_stretch_curve_") or "decay")
        retriggers = DrumDetectorWindow._generator_step_stretch_retriggers(step)
        local_retriggers = sum(
            1 for retrigger in retriggers if int(getattr(retrigger, "step_index", -1)) == int(getattr(step, "step_index", -2))
        )
        return {
            "active": active,
            "tail": tail,
            "zone": zone,
            "start": zone_start,
            "end": zone_end,
            "span": span,
            "amount": amount,
            "curve": curve,
            "retrigger_count": len(retriggers),
            "local_retrigger_count": int(local_retriggers),
        }

    @staticmethod
    def _generator_step_stretch_retriggers(step) -> tuple[object, ...]:
        raw_retriggers = getattr(step, "stretch_retriggers", ())
        if not isinstance(raw_retriggers, (tuple, list)):
            return ()
        return tuple(raw_retriggers)

    @classmethod
    def _generator_snare_stretch_points_text(cls, step, meta: dict[str, int | float | bool] | None = None) -> str:
        resolved_meta = meta or cls._generator_snare_stretch_metadata(step)
        if not bool(resolved_meta.get("zone")):
            return ""
        retriggers = cls._generator_step_stretch_retriggers(step)
        local_step_index = int(getattr(step, "step_index", 0))
        local_offsets = [
            int(getattr(retrigger, "sub_step_offset", 0))
            for retrigger in retriggers
            if int(getattr(retrigger, "step_index", -1)) == local_step_index
        ]
        if not local_offsets:
            return "~"
        bucket_count = 5
        buckets = [False] * bucket_count
        for offset in local_offsets:
            bucket = int(
                np.clip(
                    round((float(offset) / float(max(1, STRETCH_TICKS_PER_STEP - 1))) * float(bucket_count - 1)),
                    0,
                    bucket_count - 1,
                )
            )
            buckets[bucket] = True
        return "".join("." if filled else " " for filled in buckets).rstrip() or "."

    @classmethod
    def _generator_sequence_header_text(cls, step_index: int, step=None) -> str:
        base_text = str(int(step_index))
        if step is None:
            return base_text
        repeat_meta = cls._generator_repeat_metadata(step)
        kick_roll_meta = cls._generator_kick_roll_metadata(step)
        snare_stretch_meta = cls._generator_snare_stretch_metadata(step)
        if not repeat_meta["zone"] and not kick_roll_meta["zone"] and not snare_stretch_meta["zone"]:
            return base_text
        if kick_roll_meta["zone"]:
            if kick_roll_meta["start"] and kick_roll_meta["end"]:
                return f"{{{base_text}}}"
            if kick_roll_meta["start"]:
                return f"{{{base_text}"
            if kick_roll_meta["end"]:
                return f"{base_text}}}"
        if snare_stretch_meta["zone"]:
            if snare_stretch_meta["start"] and snare_stretch_meta["end"]:
                return f"<{base_text}>"
            if snare_stretch_meta["start"]:
                return f"<{base_text}"
            if snare_stretch_meta["end"]:
                return f"{base_text}>"
        if repeat_meta["start"] and repeat_meta["end"]:
            return f"[{base_text}]"
        if repeat_meta["start"]:
            return f"[{base_text}"
        if repeat_meta["end"]:
            return f"{base_text}]"
        return base_text

    def _style_generator_sequence_column(self, column: int) -> None:
        step_index = column + 1
        background, foreground, role_label = self._generator_step_palette(step_index)
        fill_meta = {
            "reserved": False,
            "pending": False,
            "active": False,
            "type": "",
            "source": "generated",
            "start": False,
            "end": False,
            "zone_start": 16,
            "zone_end": 16,
        }
        repeat_meta = {"repeat": False, "zone": False, "start": False, "end": False, "count": 1, "span": 1}
        kick_roll_meta = {"active": False, "zone": False, "start": False, "end": False, "high": False, "low": False, "span": 1}
        snare_stretch_meta = {"active": False, "tail": False, "zone": False, "start": False, "end": False, "span": 1, "amount": 0.0}
        pitch_shift = 0.0
        pattern_step = None
        if self._generated_pattern is not None and column < len(self._generated_pattern.steps):
            pattern_step = self._generated_pattern.steps[column]
            fill_meta = self._generator_fill_metadata(pattern_step)
            repeat_meta = self._generator_repeat_metadata(pattern_step)
            kick_roll_meta = self._generator_kick_roll_metadata(pattern_step)
            snare_stretch_meta = self._generator_snare_stretch_metadata(pattern_step)
            pitch_shift = self._generator_step_pitch_shift(pattern_step)
            if fill_meta["reserved"]:
                fill_overlay = QColor("#5c4321") if bool(fill_meta["pending"]) else QColor("#7a5633")
                fill_amount = 0.28 if bool(fill_meta["pending"]) else 0.34
                background = self._blend_generator_colors(background, fill_overlay, fill_amount)
            if repeat_meta["zone"]:
                background = self._blend_generator_colors(background, QColor("#264338"), 0.42)
            elif repeat_meta["repeat"]:
                background = self._blend_generator_colors(background, QColor("#20362c"), 0.28)
            if self._generator_step_is_reverse(pattern_step):
                background = self._blend_generator_colors(background, QColor("#4d2437"), 0.32)
            if kick_roll_meta["zone"]:
                background = self._blend_generator_colors(background, QColor("#5a3617"), 0.36)
            elif kick_roll_meta["active"]:
                background = self._blend_generator_colors(background, QColor("#4a2f1d"), 0.28)
            if snare_stretch_meta["zone"]:
                background = self._blend_generator_colors(background, QColor("#28346d"), 0.28)
            elif snare_stretch_meta["active"]:
                background = self._blend_generator_colors(background, QColor("#28346d"), 0.34)
            if abs(pitch_shift) > 1e-6:
                background = self._blend_generator_colors(background, QColor("#284b31"), 0.22)
        header_item = self.generator_sequence_table.horizontalHeaderItem(column)
        if header_item is not None:
            header_item.setText(self._generator_sequence_header_text(step_index, pattern_step))
            header_item.setBackground(background)
            header_item.setForeground(foreground)
            fill_hint = ""
            if fill_meta["reserved"]:
                fill_label = FILL_STYLE_LABELS.get(str(fill_meta["type"]), str(fill_meta["type"]).title())
                fill_shape = f"{int(fill_meta['zone_start'])}-{int(fill_meta['zone_end'])}"
                fill_state = "reserve" if bool(fill_meta["pending"]) else "actif"
                if fill_meta["start"] and fill_meta["end"]:
                    fill_hint = f" | Fill {fill_state} complet ({fill_label}, {fill_shape}, {fill_meta['source']})"
                elif fill_meta["start"]:
                    fill_hint = f" | Debut fill {fill_state} ({fill_label}, {fill_shape}, {fill_meta['source']})"
                elif fill_meta["end"]:
                    fill_hint = f" | Fin fill {fill_state} ({fill_label}, {fill_shape}, {fill_meta['source']})"
                else:
                    fill_hint = f" | Fill {fill_state} ({fill_label}, {fill_shape}, {fill_meta['source']})"
            repeat_hint = ""
            if repeat_meta["zone"]:
                zone_shape = f"x{repeat_meta['count']} sur {repeat_meta['span']} step(s)"
                if repeat_meta["start"] and repeat_meta["end"]:
                    repeat_hint = f" | Repeat zone complete ({zone_shape})"
                elif repeat_meta["start"]:
                    repeat_hint = f" | Debut repeat ({zone_shape})"
                elif repeat_meta["end"]:
                    repeat_hint = f" | Fin repeat ({zone_shape})"
                else:
                    repeat_hint = f" | Repeat zone ({zone_shape})"
            elif repeat_meta["repeat"]:
                repeat_hint = f" | Repeat x{repeat_meta['count']}"
            reverse_hint = ""
            if pattern_step is not None and self._generator_step_is_reverse(pattern_step):
                reverse_hint = " | Reverse tail"
            kick_roll_hint = ""
            if kick_roll_meta["zone"]:
                zone_shape = f"{kick_roll_meta['span']} step(s)"
                if kick_roll_meta["start"] and kick_roll_meta["end"]:
                    kick_roll_hint = f" | Kick roll complet ({zone_shape})"
                elif kick_roll_meta["start"]:
                    kick_roll_hint = f" | Debut kick roll ({zone_shape})"
                elif kick_roll_meta["end"]:
                    kick_roll_hint = f" | Fin kick roll ({zone_shape})"
                else:
                    kick_roll_hint = f" | Kick roll ({zone_shape})"
            elif kick_roll_meta["active"]:
                kick_roll_hint = " | Kick roll"
            snare_stretch_hint = ""
            if snare_stretch_meta["zone"]:
                zone_shape = f"x{int(snare_stretch_meta['span'])}"
                zone_amount = int(round(float(snare_stretch_meta["amount"]) * 100.0))
                curve = str(snare_stretch_meta.get("curve", "decay"))
                retrigger_count = int(snare_stretch_meta.get("retrigger_count", 0))
                if snare_stretch_meta["start"] and snare_stretch_meta["end"]:
                    snare_stretch_hint = (
                        f" | Retrigger expo complet ({zone_shape} a {zone_amount}% / {curve} / {retrigger_count} hits)"
                    )
                elif snare_stretch_meta["start"]:
                    snare_stretch_hint = (
                        f" | Debut retrigger expo ({zone_shape} a {zone_amount}% / {curve} / {retrigger_count} hits)"
                    )
                elif snare_stretch_meta["end"]:
                    snare_stretch_hint = (
                        f" | Fin retrigger expo ({zone_shape} a {zone_amount}% / {curve} / {retrigger_count} hits)"
                    )
                elif snare_stretch_meta["tail"]:
                    snare_stretch_hint = f" | Queue retrigger expo ({zone_shape})"
                else:
                    snare_stretch_hint = (
                        f" | Retrigger expo ({zone_shape} a {zone_amount}% / {curve} / {retrigger_count} hits)"
                    )
            pitch_hint = ""
            if abs(pitch_shift) > 1e-6:
                pitch_hint = f" | {self._generator_pitch_fx_text(pitch_shift)}"
            header_item.setToolTip(
                f"Step {step_index} | {role_label}{fill_hint}{repeat_hint}{reverse_hint}{kick_roll_hint}{snare_stretch_hint}{pitch_hint}"
            )

        for row in range(2, min(6, self.generator_sequence_table.rowCount())):
            item = self.generator_sequence_table.item(row, column)
            if item is None:
                continue
            item.setBackground(background)
            item.setForeground(foreground)
            if row == 5:
                if bool(fill_meta["reserved"]) and bool(fill_meta["pending"]):
                    item.setBackground(self._blend_generator_colors(background, QColor("#7b5b25"), 0.56))
                    item.setForeground(QColor("#fff2db"))
                elif bool(fill_meta["reserved"]) and bool(fill_meta["active"]):
                    item.setBackground(self._blend_generator_colors(background, QColor("#8a6132"), 0.52))
                    item.setForeground(QColor("#fff2e5"))
                elif pattern_step is not None and self._generator_step_is_reverse(pattern_step):
                    item.setBackground(self._blend_generator_colors(background, QColor("#6a2947"), 0.58))
                    item.setForeground(QColor("#ffe7ef"))
                elif kick_roll_meta["zone"] or kick_roll_meta["active"]:
                    item.setBackground(self._blend_generator_colors(background, QColor("#6e4525"), 0.52))
                    item.setForeground(QColor("#fff0dc"))
                elif snare_stretch_meta["active"]:
                    item.setBackground(self._blend_generator_colors(background, QColor("#33408a"), 0.56))
                    item.setForeground(QColor("#eef0ff"))
                elif snare_stretch_meta["tail"] or snare_stretch_meta["zone"]:
                    item.setBackground(self._blend_generator_colors(background, QColor("#2c3c77"), 0.44))
                    item.setForeground(QColor("#e8ecff"))
                elif repeat_meta["zone"] or repeat_meta["repeat"]:
                    item.setBackground(self._blend_generator_colors(background, QColor("#275241"), 0.5))
                    item.setForeground(QColor("#e3fff2"))
                elif abs(pitch_shift) > 1e-6:
                    item.setBackground(self._blend_generator_colors(background, QColor("#2f5f35"), 0.48))
                    item.setForeground(QColor("#eaffee"))

        anchor_button = self.generator_sequence_table.cellWidget(0, column)
        if isinstance(anchor_button, QPushButton):
            self._update_generator_anchor_button(anchor_button, step_index)

        lock_button = self.generator_sequence_table.cellWidget(1, column)
        if isinstance(lock_button, QPushButton):
            self._update_generator_lock_button(lock_button, step_index)

        button = self.generator_sequence_table.cellWidget(6, column)
        if isinstance(button, QPushButton):
            button.setProperty("generatorStepRole", self._generator_step_role(step_index))
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    @staticmethod
    def _summarize_generated_pattern_steps(steps) -> tuple[int, str]:
        event_count = sum(1 for step in steps if step.label != "silence")
        counts: dict[str, int] = {}
        for step in steps:
            if step.label == "silence":
                continue
            counts[step.label] = counts.get(step.label, 0) + 1
        summary = ", ".join(
            f"{label}:{count}" for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        )
        return event_count, (summary or "silence only")

    def _merge_locked_generated_steps(
        self,
        pattern: GeneratedBreakPattern,
        previous_pattern: GeneratedBreakPattern | None,
        *,
        ignore_step: int | None = None,
    ) -> GeneratedBreakPattern:
        if previous_pattern is None or not self._generator_locked_steps:
            return pattern

        previous_steps = {int(step.step_index): step for step in previous_pattern.steps}
        merged_steps = []
        changed = False
        ignored = int(ignore_step) if ignore_step is not None else None
        for step in pattern.steps:
            step_number = int(step.step_index)
            if step_number == ignored or step_number not in self._generator_locked_steps:
                merged_steps.append(step)
                continue
            previous_step = previous_steps.get(step_number)
            if previous_step is None:
                merged_steps.append(step)
                continue
            merged_steps.append(previous_step)
            changed = True

        if not changed:
            return pattern

        event_count, summary = self._summarize_generated_pattern_steps(tuple(merged_steps))
        return replace(
            pattern,
            steps=tuple(merged_steps),
            event_count=int(event_count),
            summary=str(summary),
        )

    def _current_generator_seed_for_debug(self) -> int:
        if self._generated_pattern is not None:
            return int(self._generated_pattern.seed)
        seed_text = str(self.generator_seed_value.text() or "").strip()
        if seed_text.isdigit():
            return max(1, int(seed_text))
        return 1

    def _open_generation_debug_report(self) -> None:
        if self._result is None:
            QMessageBox.warning(self, "Analyse requise", "Analyse d'abord un break avant d'exporter un rapport debug.")
            return
        source_result = self._effective_generator_result(self._result)
        if source_result is None or not source_result.transient_hits:
            QMessageBox.warning(self, "Transients manquants", "Le break courant ne contient aucun transient exploitable.")
            return
        if self._analysis_stale:
            QMessageBox.information(
                self,
                "Recalcul requis",
                "La waveform a ete modifiee. Relance d'abord un rebuild ou une analyse avant d'exporter un rapport debug.",
            )
            return

        seed = self._current_generator_seed_for_debug()
        params = self._generator_params(seed=seed)
        use_hybrid = self._generator_mode() == GENERATOR_MODE_HYBRID
        active_anchors = self._generator_active_step_anchors(step_count=max(16, int(params.bars) * 16))
        target_bpm = float(self.generator_target_bpm_spin.value())
        self._generator_busy = True
        self.generator_loading_bar.setVisible(True)
        self.generator_info_label.setText("Generation du rapport debug en cours...")
        self._refresh_control_states("Construction du rapport debug de generation...")
        if self._should_use_process_pattern_generation():
            worker = ProcessTaskWorker(
                generate_break_pattern_debug,
                tuple(source_result.transient_hits),
                params,
                kwargs={
                    "sequences": tuple(source_result.hit_sequences),
                    "anchors": dict(active_anchors),
                    "use_hybrid": bool(use_hybrid),
                    "user_motifs": tuple(self._generator_user_motifs),
                    "target_bpm": target_bpm,
                },
                parent=self,
            )
        else:
            generate_task = lambda: generate_break_pattern_debug(
                source_result.transient_hits,
                params,
                sequences=source_result.hit_sequences,
                anchors=active_anchors,
                use_hybrid=use_hybrid,
                user_motifs=self._generator_user_motifs,
                target_bpm=target_bpm,
            )
            worker = TaskWorker(generate_task, self)
        self._generator_worker = worker
        worker.succeeded.connect(
            lambda payload, current_seed=seed: self._dispatch_ui_callback(
                lambda: self._on_generation_debug_report_ready(payload, current_seed)
            )
        )
        worker.failed.connect(
            lambda message: self._dispatch_ui_callback(lambda: self._on_generation_debug_report_failed(message))
        )
        worker.finished.connect(
            lambda: self._dispatch_ui_callback(self._on_pattern_generation_finished)
        )
        worker.start()

    def _generate_break_pattern(self) -> None:
        if self._result is None:
            QMessageBox.warning(self, "Analyse requise", "Analyse d'abord un break pour generer un pattern.")
            return
        source_result = self._effective_generator_result(self._result)
        if source_result is None or not source_result.transient_hits:
            QMessageBox.warning(self, "Transients manquants", "Le break courant ne contient aucun transient exploitable.")
            return

        if self._analysis_stale:
            QMessageBox.information(
                self,
                "Recalcul requis",
                "La waveform a ete modifiee. Relance d'abord un rebuild ou une analyse avant de generer un pattern.",
            )
            return

        seed = int(secrets.randbelow(999_999_999) + 1)
        self._clear_generator_pipeline_state()
        params = self._generator_params(seed=seed)
        current_pattern = self._generated_pattern
        use_hybrid = self._generator_mode() == GENERATOR_MODE_HYBRID
        active_anchors = self._generator_active_step_anchors(step_count=max(16, int(params.bars) * 16))
        self._generator_busy = True
        self.generator_loading_bar.setVisible(True)
        self.generator_info_label.setText("Generation du pattern en cours...")
        self._refresh_control_states("Generation du pattern a partir du break courant...")
        if self._should_use_process_pattern_generation():
            worker = ProcessTaskWorker(
                generate_break_pattern_for_mode,
                tuple(source_result.transient_hits),
                params,
                kwargs={
                    "sequences": tuple(source_result.hit_sequences),
                    "anchors": dict(active_anchors),
                    "use_hybrid": bool(use_hybrid),
                    "user_motifs": tuple(self._generator_user_motifs),
                },
                parent=self,
            )
        else:
            if use_hybrid:
                generate_task = lambda: generate_break_pattern_hybrid(
                    source_result.transient_hits,
                    params,
                    sequences=source_result.hit_sequences,
                    anchors=active_anchors,
                    user_motifs=self._generator_user_motifs,
                )
            else:
                generate_task = lambda: generate_break_pattern(
                    source_result.transient_hits,
                    params,
                    sequences=source_result.hit_sequences,
                    anchors=active_anchors,
                )
            worker = TaskWorker(generate_task, self)
        self._generator_worker = worker
        worker.succeeded.connect(
            lambda pattern, previous=current_pattern: self._dispatch_ui_callback(
                lambda: self._on_pattern_generated(
                    self._merge_locked_generated_steps(pattern, previous)
                )
            )
        )
        worker.failed.connect(
            lambda message: self._dispatch_ui_callback(lambda: self._on_pattern_generation_failed(message))
        )
        worker.finished.connect(
            lambda: self._dispatch_ui_callback(self._on_pattern_generation_finished)
        )
        worker.start()

    def _reroll_generated_step(self, step_index: int) -> None:
        if self._result is None or self._generated_pattern is None:
            return
        source_result = self._effective_generator_result(self._result)
        if source_result is None or not source_result.transient_hits:
            return
        if self._analysis_stale:
            QMessageBox.information(
                self,
                "Recalcul requis",
                "La waveform a ete modifiee. Relance d'abord un rebuild ou une analyse avant de reroll un step.",
            )
            return

        seed = int(secrets.randbelow(999_999_999) + 1)
        self._clear_generator_pipeline_state()
        self._generator_busy = True
        self.generator_loading_bar.setVisible(True)
        self.generator_info_label.setText(f"Reroll du step {step_index} en cours...")
        self._refresh_control_states(f"Regeneration du step {step_index}...")
        current_pattern = self._generated_pattern
        active_anchors = self._generator_active_step_anchors(step_count=current_pattern.step_count)
        if self._should_use_process_pattern_generation():
            worker = ProcessTaskWorker(
                reroll_break_pattern_step,
                tuple(source_result.transient_hits),
                current_pattern,
                int(step_index),
                kwargs={
                    "seed": seed,
                    "sequences": tuple(source_result.hit_sequences),
                    "anchors": dict(active_anchors),
                },
                parent=self,
            )
        else:
            worker = TaskWorker(
                lambda: reroll_break_pattern_step(
                    source_result.transient_hits,
                    current_pattern,
                    int(step_index),
                    seed=seed,
                    sequences=source_result.hit_sequences,
                    anchors=active_anchors,
                ),
                self,
            )
        self._generator_worker = worker
        worker.succeeded.connect(
            lambda pattern, previous=current_pattern, ignored_step=int(step_index): self._dispatch_ui_callback(
                lambda: self._on_pattern_generated(
                    self._merge_locked_generated_steps(pattern, previous, ignore_step=ignored_step)
                )
            )
        )
        worker.failed.connect(
            lambda message: self._dispatch_ui_callback(lambda: self._on_pattern_generation_failed(message))
        )
        worker.finished.connect(
            lambda: self._dispatch_ui_callback(self._on_pattern_generation_finished)
        )
        worker.start()

    def _play_generated_pattern(self) -> None:
        if not self._generated_pattern_available():
            self._refresh_generated_pattern_state()
            return

        audio_snapshot = self._analysis_audio_snapshot()
        if audio_snapshot is None:
            QMessageBox.warning(self, "Audio indisponible", "Recharge d'abord la waveform avant de jouer le pattern.")
            return

        self._start_generator_pattern_preview_build(
            owner=PREVIEW_OWNER_GENERATOR,
            info_text="Preparation de la lecture du pattern genere...",
            status_text="Preparation du playback pattern...",
            samples=np.array(audio_snapshot[0], copy=True),
            sample_rate=int(audio_snapshot[1]),
        )
        self._generator_live_changes_pending = False

    def _stop_generated_pattern(self) -> None:
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._stop_retimed_preview(update_status=True)

    def _queue_live_generator_preview_refresh(self) -> bool:
        if (
            not self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
            or self._generated_pattern is None
            or self._preview_busy
        ):
            return False

        audio_snapshot = self._analysis_audio_snapshot()
        if audio_snapshot is None:
            return False

        self._start_generator_pattern_preview_build(
            owner=PREVIEW_OWNER_GENERATOR,
            info_text="Mise a jour live du pattern en cours...",
            status_text=self.status_label.text(),
            samples=np.array(audio_snapshot[0], copy=True),
            sample_rate=int(audio_snapshot[1]),
        )
        return True

    def _schedule_live_generator_preview_refresh(self) -> None:
        if (
            not self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
            or self._generated_pattern is None
        ):
            return
        self._generator_live_refresh_timer.start()

    def _flush_live_generator_preview_refresh(self) -> None:
        if not self._generator_live_changes_pending:
            return
        self._queue_live_generator_preview_refresh()

    def _start_generator_pattern_preview_build(
        self,
        *,
        owner: str,
        info_text: str,
        status_text: str,
        samples: np.ndarray,
        sample_rate: int,
    ) -> None:
        if self._generated_pattern is None:
            return
        target_bpm = float(self.generator_target_bpm_spin.value())
        gate = max(0.05, self.generator_gate_slider.value() / 100.0)
        mono_choke = self._generator_mono_choke_enabled()
        if self._should_use_process_pattern_generation():
            self._start_preview_build(
                owner=owner,
                info_text=info_text,
                status_text=status_text,
                process_task=_build_pattern_preview_process_task,
                process_args=(samples, int(sample_rate), self._generated_pattern),
                process_kwargs={"target_bpm": target_bpm, "gate": gate, "mono_choke": mono_choke},
            )
            return
        self._start_preview_build(
            lambda: build_pattern_preview(
                samples,
                int(sample_rate),
                self._generated_pattern,
                target_bpm=target_bpm,
                gate=gate,
                mono_choke=mono_choke,
            ),
            owner=owner,
            info_text=info_text,
            status_text=status_text,
        )

    def _retimed_preview_available(self) -> bool:
        return bool(
            (not self._analysis_stale)
            and self._result is not None
            and self._loaded_audio_samples is not None
            and self._loaded_audio_sample_rate
            and self._effective_detected_bpm(self._result) > 1.0
            and len(self._result.transient_hits) >= 2
        )

    def _marker_rebuild_available(self) -> bool:
        marker_times = self._current_marker_times()
        return bool(
            self._loaded_audio_samples is not None
            and self._loaded_audio_sample_rate
            and self._waveform_widget is not None
            and marker_times
        )

    def _current_marker_times(self) -> list[float]:
        if self._waveform_widget is None:
            return []
        markers = getattr(self._waveform_widget, "markers", None)
        if not markers:
            return []
        return [float(time_s) for time_s in markers]

    def _update_retimed_preview_state(self, result: DrumDetectionResult | None, *, reset_target: bool = False) -> None:
        self._retimed_preview = None
        self._retime_visual_segment_index = -1
        self._result = result

        if result is None:
            self.detected_bpm_value.setText("-")
            self.generator_detected_bpm_value.setText("-")
            self.retime_play_button.setEnabled(False)
            self.retime_stop_button.setEnabled(False)
            self.detected_bpm_factor_combo.setEnabled(False)
            self.target_bpm_spin.setEnabled(False)
            self._sync_quantize_controls_state()
            self.retime_info_label.setText(
                "Analyse un break avec au moins deux transients pour entendre une relecture des segments a un autre BPM, "
                "avec tete de lecture synchronisee sur la waveform."
            )
            self._refresh_retime_pattern_preview()
            return

        raw_bpm = float(result.tempo_bpm)
        detected_bpm = self._effective_detected_bpm(result)
        self.detected_bpm_factor_combo.setEnabled(
            (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._preview_busy)
        )
        self._refresh_detected_bpm_labels()

        if self._analysis_stale:
            self.retime_play_button.setEnabled(False)
            self.retime_stop_button.setEnabled(self._preview_owner_is_active(PREVIEW_OWNER_RETIME))
            self.target_bpm_spin.setEnabled(False)
            self._sync_quantize_controls_state()
            self.retime_info_label.setText(
                "La waveform / les markers ont change. Rebuild Hits From Markers ou Analyser doit etre relance avant la preview."
            )
            self._refresh_retime_pattern_preview()
            return

        if detected_bpm > 1.0 and reset_target:
            self._sync_target_bpm_spins_from_detected(result)

        available = (
            self._retimed_preview_available()
            and (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._preview_busy)
        )
        self.retime_play_button.setEnabled(available)
        self.retime_stop_button.setEnabled(self._preview_owner_is_active(PREVIEW_OWNER_RETIME))
        self.target_bpm_spin.setEnabled(available)
        self._sync_quantize_controls_state()

        if not available:
            if detected_bpm <= 1.0:
                self.retime_info_label.setText("Tempo detecte insuffisant pour construire une preview retimee.")
            elif self._loaded_audio_samples is None:
                self.retime_info_label.setText("Recharge la waveform pour activer la preview retimee.")
            else:
                self.retime_info_label.setText("Il faut au moins deux transients pour construire la preview retimee.")
            self._refresh_retime_pattern_preview()
            return

        estimated_duration = self._estimate_retimed_preview_duration(result, float(self.target_bpm_spin.value()))
        ratio = detected_bpm / max(float(self.target_bpm_spin.value()), 1e-6)
        loop_hint = " Boucle activee." if self._retime_loop_enabled() else ""
        mode_hint = f" {self._preview_mode_suffix()}."
        self.retime_info_label.setText(
            f"Preview segmentee prete: {detected_bpm:.1f} -> {self.target_bpm_spin.value():.1f} BPM "
            f"(ratio {ratio:.2f}x, duree approx {estimated_duration:.2f}s). "
            f"La tete de lecture suivra le segment actif.{mode_hint}{loop_hint}"
        )
        self._refresh_retime_pattern_preview()

    def _estimate_retimed_preview_duration(self, result: DrumDetectionResult, target_bpm: float) -> float:
        source_bpm = self._effective_detected_bpm(result)
        return estimate_retimed_preview_duration(
            result.transient_hits,
            source_bpm=source_bpm,
            target_bpm=target_bpm,
            mode=self._preview_mode(),
            quantize_grid_division=self._quantize_grid_division(),
            quantize_strength=self._quantize_strength(),
            mono_choke=self._generator_mono_choke_enabled(),
        )

    def _refresh_retime_pattern_preview(self) -> None:
        if not hasattr(self, "retime_pattern_preview"):
            return

        preview = self._retimed_preview
        if (
            preview is not None
            and preview.mode != PREVIEW_MODE_PATTERN
            and self._preview_owner_is_active(PREVIEW_OWNER_RETIME)
        ):
            self.retime_pattern_preview.set_preview_data(
                preview.segments,
                source_bpm=float(preview.source_bpm),
                target_bpm=float(preview.target_bpm),
                duration_s=float(preview.duration_s),
                mode=str(preview.mode),
                grid_division=preview.quantize_grid_division,
                quantize_strength=float(preview.quantize_strength),
            )
            self.retime_pattern_preview.set_active_segment(self._retime_visual_segment_index)
            return

        result = self._result
        if result is None:
            self.retime_pattern_preview.clear_preview(
                "Analyse un break avec au moins deux transients pour voir ici le flow source et sa version relue."
            )
            return
        if self._analysis_stale:
            self.retime_pattern_preview.clear_preview(
                "Les markers ont change. Rebuild Hits From Markers ou Analyser doit etre relance avant de relire le quantize."
            )
            return

        source_bpm = self._effective_detected_bpm(result)
        target_bpm = float(self.target_bpm_spin.value()) if hasattr(self, "target_bpm_spin") else 120.0
        schedule = build_retimed_preview_schedule(
            result.transient_hits,
            source_bpm=source_bpm,
            target_bpm=target_bpm,
            mode=self._preview_mode(),
            quantize_grid_division=self._quantize_grid_division(),
            quantize_strength=self._quantize_strength(),
            mono_choke=self._generator_mono_choke_enabled(),
        )
        if not schedule:
            self.retime_pattern_preview.clear_preview(
                "Il faut au moins deux transients et un tempo detecte exploitable pour visualiser le preview."
            )
            return

        duration_s = max(float(segment.preview_end_s) for segment in schedule)
        self.retime_pattern_preview.set_preview_data(
            schedule,
            source_bpm=source_bpm,
            target_bpm=target_bpm,
            duration_s=duration_s,
            mode=self._preview_mode(),
            grid_division=self._quantize_grid_division() if self._preview_mode() == PREVIEW_MODE_QUANTIZE else None,
            quantize_strength=self._quantize_strength(),
        )
        self.retime_pattern_preview.set_active_segment(None)

    def _play_retimed_preview(self) -> None:
        if not self._retimed_preview_available() or self._result is None:
            self._update_retimed_preview_state(self._result)
            return

        audio_snapshot = self._analysis_audio_snapshot()
        if audio_snapshot is None:
            QMessageBox.warning(self, "Audio indisponible", "Recharge d'abord la waveform avant de preparer la preview.")
            return

        self._start_preview_build(
            lambda: self._build_preview_for_current_settings(self._result, audio_snapshot[0], int(audio_snapshot[1])),
            owner=PREVIEW_OWNER_RETIME,
            info_text="Preparation de la preview retimee...",
            status_text="Preparation de la preview retimee...",
        )

    def _start_retimed_preview_playback(
        self,
        preview: RetimedPreview,
        *,
        owner: str = PREVIEW_OWNER_RETIME,
        sounddevice=None,
        loop_restart: bool = False,
    ) -> None:
        if sounddevice is None:
            sounddevice = _require_sounddevice()
        loop_enabled = self._preview_loop_enabled(owner)
        playback_audio = preview.loop_audio if loop_enabled and preview.loop_audio is not None else preview.audio
        audio = self._normalize_preview_audio(playback_audio)
        total_frames = int(audio.shape[0])
        if total_frames <= 0:
            raise ValueError("Preview audio buffer is empty")

        self._retime_stream_audio = audio
        self._retime_stream_cursor = 0
        self._retime_stream_frames_played = 0
        self._retime_stream_total_frames = total_frames
        self._retime_stream_loop_enabled = loop_enabled
        self._retime_underflow_log_at = 0.0

        def callback(outdata, frames, _time_info, status):
            if status.output_underflow:
                now = time.perf_counter()
                if (now - self._retime_underflow_log_at) >= 0.75:
                    self._retime_underflow_log_at = now
                    logging.getLogger("drum_preview_playback").warning("Underflow audio detecte")

            if owner == PREVIEW_OWNER_LIVE:
                should_stop = self._fill_live_preview_buffer(outdata)
                if should_stop:
                    raise sounddevice.CallbackStop()
                return

            current_audio = self._retime_stream_audio
            total_frames = int(self._retime_stream_total_frames)
            if current_audio is None or total_frames <= 0:
                outdata.fill(0)
                raise sounddevice.CallbackStop()

            cursor = self._retime_stream_cursor
            loop_enabled = bool(self._retime_stream_loop_enabled)
            if cursor >= total_frames:
                cursor = cursor % total_frames if loop_enabled else max(total_frames - 1, 0)
                self._retime_stream_cursor = int(cursor)

            new_cursor, frames_written, should_stop = _copy_preview_frames(
                outdata,
                current_audio,
                cursor,
                loop_enabled=loop_enabled,
            )
            self._retime_stream_cursor = int(new_cursor)
            self._retime_stream_frames_played += int(frames_written)
            if should_stop:
                raise sounddevice.CallbackStop()

        resolved_blocksize = 2048 if owner == PREVIEW_OWNER_LIVE else (1024 if owner == PREVIEW_OWNER_GENERATOR else 0)
        self._retime_stream = sounddevice.OutputStream(
            samplerate=preview.sample_rate,
            channels=int(audio.shape[1]),
            dtype="float32",
            blocksize=resolved_blocksize,
            latency="high",
            callback=callback,
        )
        self._retime_stream.start()
        self._retimed_preview = preview
        self._retimed_preview_playing = True
        self._preview_owner = owner
        if owner == PREVIEW_OWNER_GENERATOR:
            self._generator_live_changes_pending = False
            self._set_live_compact_playback_highlight(None, None)
        elif owner == PREVIEW_OWNER_LIVE:
            for slot_name, slot in self._live_slots.items():
                if slot.preview is None:
                    slot.status = "stale"
                elif slot_name == self._live_active_slot:
                    slot.status = "playing"
                else:
                    slot.status = "ready"
            self._live_pending_switch_slot = None
            self._refresh_live_mode_ui()
            self._set_live_compact_playback_highlight(self._live_active_slot, 1)
        else:
            self._retime_live_changes_pending = False
            self._set_live_compact_playback_highlight(None, None)
        self._retime_visual_started_at = time.perf_counter()
        self._retime_visual_segment_index = -1
        self.retime_play_button.setEnabled(True)
        self.retime_stop_button.setEnabled(owner == PREVIEW_OWNER_RETIME)
        self.generator_stop_button.setEnabled(owner == PREVIEW_OWNER_GENERATOR)
        self._retime_stop_timer.stop()
        self._retime_visual_timer.setInterval(45 if owner == PREVIEW_OWNER_LIVE else 20)
        self._retime_visual_timer.start()
        self._refresh_retime_pattern_preview()
        self._update_retimed_preview_visual()
        mode = self._preview_playback_label(
            preview,
            looping=loop_enabled,
            restarted=loop_restart and loop_enabled,
        )
        if owner == PREVIEW_OWNER_GENERATOR:
            self.generator_info_label.setText(
                f"{mode}: {preview.segment_count} evenement(s), {preview.target_bpm:.1f} BPM, "
                f"{preview.duration_s:.2f}s. La tete de lecture suit la slice relue sur la waveform."
            )
        elif owner == PREVIEW_OWNER_LIVE:
            live_target_bpm = self._effective_preview_target_bpm(preview)
            self.live_mode_info_label.setText(
                f"{mode}: slot {self._live_active_slot}, {preview.segment_count} evenement(s), "
                f"{live_target_bpm:.1f} BPM, stems live actifs."
            )
        else:
            self._refresh_active_retime_preview_message()

    def _fill_live_preview_buffer(self, outdata: np.ndarray) -> bool:
        frames = int(outdata.shape[0]) if outdata.ndim >= 1 else 0
        if frames <= 0:
            outdata.fill(0)
            return False

        slot = self._live_slots.get(self._live_active_slot)
        if slot is None or slot.preview is None or not slot.loop_stems:
            outdata.fill(0)
            return True

        current_total_frames = int(self._retime_stream_total_frames)
        if current_total_frames <= 0:
            current_total_frames = int(next(iter(slot.loop_stems.values())).shape[0])
            self._retime_stream_total_frames = current_total_frames
        if current_total_frames <= 0:
            outdata.fill(0)
            return True

        cursor = float(self._retime_stream_cursor) % float(current_total_frames)
        write_pos = 0
        outdata.fill(0)
        while write_pos < frames:
            slot = self._live_slots.get(self._live_active_slot)
            if slot is None or slot.preview is None or not slot.loop_stems:
                break
            current_total_frames = int(next(iter(slot.loop_stems.values())).shape[0])
            if current_total_frames <= 0:
                break
            playback_rate = self._live_playback_rate(slot)
            remaining_frames = frames - write_pos
            distance_to_wrap = max(0.0, float(current_total_frames) - cursor)
            frames_until_wrap = max(1, int(np.floor(max(distance_to_wrap - 1e-6, 0.0) / playback_rate)) + 1)
            chunk = min(remaining_frames, frames_until_wrap)
            outdata[write_pos : write_pos + chunk, :] = self._mix_live_stem_chunk(slot, cursor, chunk)
            write_pos += chunk
            cursor += float(chunk) * playback_rate
            self._retime_stream_frames_played += int(chunk)
            if cursor >= float(current_total_frames):
                cursor %= float(current_total_frames)
                if self._live_pending_switch_slot and self._live_slot_is_ready(self._live_pending_switch_slot):
                    self._commit_live_slot_switch(defer_ui_refresh=True)
                    slot = self._live_slots.get(self._live_active_slot)
                    if slot is not None and slot.loop_stems:
                        current_total_frames = int(next(iter(slot.loop_stems.values())).shape[0])
                        cursor %= max(float(current_total_frames), 1.0)
        self._retime_stream_cursor = float(cursor)
        return False

    def _mix_live_stem_chunk(self, slot: PatternSlot, start_frame: float, frame_count: int) -> np.ndarray:
        preview = slot.preview
        if preview is None or frame_count <= 0:
            return np.zeros((0, 1), dtype=np.float32)
        sample_rate = int(preview.sample_rate)
        total_frames = int(next(iter(slot.loop_stems.values())).shape[0]) if slot.loop_stems else 0
        if total_frames <= 0:
            return np.zeros((frame_count, 1), dtype=np.float32)
        channel_count = int(next(iter(slot.loop_stems.values())).shape[1])
        mixed = np.zeros((frame_count, channel_count), dtype=np.float32)
        step_frames = max(1, self._live_step_frame_count())
        source_step_frames = max(1, self._live_source_step_frame_count(slot))
        playback_rate = self._live_playback_rate(slot)
        mix_plan = self._live_mix_plan
        gate_envelope: np.ndarray | None = None
        stutter_positions: np.ndarray | None = None
        if self._live_stutter_pressed:
            stutter_positions = self._live_stutter_positions(
                frame_count,
                source_step_frames,
                total_frames,
                playback_rate=playback_rate,
            )
        for stem_config in mix_plan.stems:
            group_audio = self._live_group_loop_audio(slot, stem_config.stem_names)
            if group_audio is None or group_audio.shape[0] <= 0:
                continue
            copy_required = (
                stem_config.gain != 1.0
                or stem_config.apply_lowpass
                or stem_config.apply_highpass
                or stem_config.apply_bitcrush
                or stem_config.apply_gate
            )
            grouped_chunk = self._read_live_stem_chunk(
                group_audio,
                start_frame,
                frame_count,
                source_step_frames,
                total_frames,
                playback_rate=playback_rate,
                apply_stutter=self._live_stutter_pressed and stem_config.apply_stutter,
                copy_chunk=copy_required,
                stutter_positions=stutter_positions if stem_config.apply_stutter else None,
            )
            if grouped_chunk.size == 0:
                continue
            if stem_config.gain != 1.0:
                grouped_chunk *= np.float32(stem_config.gain)
            if stem_config.apply_distortion:
                grouped_chunk = self._apply_live_distortion(
                    grouped_chunk,
                    drive=mix_plan.distortion_drive,
                    tone=mix_plan.distortion_tone,
                    mix=mix_plan.distortion_mix,
                )
            if stem_config.apply_lowpass:
                grouped_chunk = self._apply_live_lowpass(
                    stem_config.state_key,
                    grouped_chunk,
                    sample_rate=sample_rate,
                    cutoff_hz=mix_plan.lowpass_hz,
                )
            if stem_config.apply_highpass:
                grouped_chunk = self._apply_live_highpass(
                    stem_config.state_key,
                    grouped_chunk,
                    sample_rate=sample_rate,
                    cutoff_hz=mix_plan.highpass_hz,
                )
            if stem_config.apply_bitcrush:
                grouped_chunk = self._apply_live_bitcrush(grouped_chunk, mix_plan.bit_depth)
            if stem_config.apply_gate:
                if gate_envelope is None:
                    gate_envelope = self._live_gate_envelope(
                        start_frame,
                        frame_count,
                        step_frames,
                        total_frames,
                        mix_plan.gate_ratio,
                    )
                grouped_chunk *= gate_envelope[:, np.newaxis]
            mixed += grouped_chunk
        return np.clip(mixed, -1.0, 1.0).astype(np.float32, copy=False)

    def _read_live_stem_chunk(
        self,
        stem_audio: np.ndarray,
        start_frame: float,
        frame_count: int,
        source_step_frames: int,
        total_frames: int,
        *,
        playback_rate: float,
        apply_stutter: bool,
        copy_chunk: bool,
        stutter_positions: np.ndarray | None = None,
    ) -> np.ndarray:
        if apply_stutter and source_step_frames > 0:
            positions = (
                stutter_positions
                if stutter_positions is not None
                else self._live_stutter_positions(
                    frame_count,
                    source_step_frames,
                    total_frames,
                    playback_rate=playback_rate,
                )
            )
            return self._sample_live_audio_positions(stem_audio, positions)
        normalized_rate = max(float(playback_rate), 1e-6)
        normalized_start = float(start_frame) % max(float(total_frames), 1.0)
        if (
            abs(normalized_rate - 1.0) <= 1e-6
            and abs(normalized_start - round(normalized_start)) <= 1e-6
        ):
            start_index = int(round(normalized_start)) % max(int(total_frames), 1)
            end_frame = start_index + int(frame_count)
            if end_frame <= stem_audio.shape[0]:
                if copy_chunk:
                    return stem_audio[start_index:end_frame].astype(np.float32, copy=True)
                return stem_audio[start_index:end_frame].astype(np.float32, copy=False)
        positions = (normalized_start + (np.arange(frame_count, dtype=np.float64) * normalized_rate)) % max(float(total_frames), 1.0)
        return self._sample_live_audio_positions(stem_audio, positions)

    def _sample_live_audio_positions(self, stem_audio: np.ndarray, positions: np.ndarray) -> np.ndarray:
        if stem_audio.size == 0 or positions.size == 0:
            channel_count = int(stem_audio.shape[1]) if stem_audio.ndim == 2 else 1
            return np.zeros((int(positions.size), channel_count), dtype=np.float32)
        total_frames = int(stem_audio.shape[0])
        base = np.floor(positions).astype(np.int64) % max(total_frames, 1)
        next_base = (base + 1) % max(total_frames, 1)
        fractions = (positions - np.floor(positions)).astype(np.float32)[:, np.newaxis]
        current = stem_audio[base].astype(np.float32, copy=True)
        if np.any(fractions > 1e-6):
            next_chunk = stem_audio[next_base].astype(np.float32, copy=False)
            current = (current * (1.0 - fractions)) + (next_chunk * fractions)
        return current.astype(np.float32, copy=False)

    def _live_stutter_positions(
        self,
        frame_count: int,
        source_step_frames: int,
        total_frames: int,
        *,
        playback_rate: float,
    ) -> np.ndarray:
        resolved_step_frames = max(1, int(source_step_frames))
        resolved_total_frames = max(1, int(total_frames))
        resolved_rate = max(float(playback_rate), 1e-6)
        cache_key = (
            int(self._live_stutter_hold_start_frame),
            int(frame_count),
            resolved_step_frames,
            resolved_total_frames,
            int(round(resolved_rate * 1000.0)),
        )
        if self._live_stutter_positions_cache_key == cache_key and self._live_stutter_positions_cache is not None:
            return self._live_stutter_positions_cache
        positions = (
            float(self._live_stutter_hold_start_frame)
            + np.mod(np.arange(frame_count, dtype=np.float64) * resolved_rate, float(resolved_step_frames))
        )
        positions %= float(resolved_total_frames)
        self._live_stutter_positions_cache_key = cache_key
        self._live_stutter_positions_cache = positions
        return positions

    def _live_gate_envelope(
        self,
        start_frame: int,
        frame_count: int,
        step_frames: int,
        total_frames: int,
        gate_ratio: float,
    ) -> np.ndarray:
        resolved_step_frames = max(1, int(step_frames))
        resolved_total_frames = max(1, int(total_frames))
        resolved_gate_ratio = float(np.clip(gate_ratio, 0.0, 1.0))
        cache_key = (
            int(start_frame) % resolved_step_frames,
            int(frame_count),
            resolved_step_frames,
            resolved_total_frames,
            int(round(resolved_gate_ratio * 1000.0)),
        )
        cached = self._live_gate_envelope_cache.get(cache_key)
        if cached is not None:
            return cached
        positions = (start_frame + np.arange(frame_count, dtype=np.float32)) % max(float(total_frames), 1.0)
        phase = np.mod(positions, float(step_frames))
        gate_end = float(step_frames) * resolved_gate_ratio
        release = max(1.0, float(step_frames) * 0.08)
        envelope = np.ones(frame_count, dtype=np.float32)
        hard_cut = phase >= gate_end
        envelope[hard_cut] = 0.0
        soft_mask = (phase >= max(0.0, gate_end - release)) & (phase < gate_end)
        if np.any(soft_mask):
            soft_phase = (phase[soft_mask] - max(0.0, gate_end - release)) / max(release, 1e-6)
            envelope[soft_mask] = np.clip(1.0 - soft_phase, 0.0, 1.0)
        if len(self._live_gate_envelope_cache) >= 128:
            self._live_gate_envelope_cache.clear()
        self._live_gate_envelope_cache[cache_key] = envelope
        return envelope

    def _apply_live_lowpass(self, state_key: str, chunk: np.ndarray, *, sample_rate: int, cutoff_hz: float) -> np.ndarray:
        if chunk.size == 0 or cutoff_hz <= 0.0 or sample_rate <= 0:
            return chunk
        alpha = float(np.exp(-2.0 * np.pi * float(cutoff_hz) / float(sample_rate)))
        previous = self._live_lowpass_state.get(state_key)
        filtered, state = self._apply_exponential_lowpass_blockwise(chunk, alpha=alpha, initial=previous)
        self._live_lowpass_state[state_key] = state
        return filtered

    def _apply_live_highpass(self, state_key: str, chunk: np.ndarray, *, sample_rate: int, cutoff_hz: float) -> np.ndarray:
        if chunk.size == 0 or cutoff_hz <= 0.0 or sample_rate <= 0:
            return chunk
        alpha = float(np.exp(-2.0 * np.pi * float(cutoff_hz) / float(sample_rate)))
        previous = self._live_highpass_state.get(state_key)
        lowpassed, state = self._apply_exponential_lowpass_blockwise(chunk, alpha=alpha, initial=previous)
        self._live_highpass_state[state_key] = state
        return (chunk - lowpassed).astype(np.float32, copy=False)

    @staticmethod
    def _apply_live_distortion(chunk: np.ndarray, *, drive: float, tone: float, mix: float) -> np.ndarray:
        if chunk.size == 0:
            return chunk
        resolved_drive = float(np.clip(drive, 0.0, 1.0))
        resolved_tone = float(np.clip(tone, -1.0, 1.0))
        resolved_mix = float(np.clip(mix, 0.0, 1.0))
        if resolved_drive <= 1e-4 or resolved_mix <= 1e-4:
            return chunk
        source = np.asarray(chunk, dtype=np.float32)
        pregain = np.float32(1.0 + (resolved_drive * resolved_drive * 24.0))
        bias = np.float32(resolved_tone * 0.18)
        wet_input = (source * pregain) + bias
        soft = np.tanh(wet_input)
        folded = np.sin(np.clip(wet_input, -np.pi, np.pi))
        shape = np.float32(0.15 + (resolved_drive * 0.85))
        wet = (soft * (1.0 - shape)) + (folded * shape)
        wet = np.clip(wet - (bias * 0.35), -1.0, 1.0)
        gamma = np.float32(np.interp(resolved_tone, (-1.0, 1.0), (1.65, 0.75)))
        wet = np.sign(wet) * np.power(np.clip(np.abs(wet), 0.0, 1.0), gamma)
        trim = np.float32(1.0 / (1.0 + (resolved_drive * 0.9)))
        wet *= trim
        mixed = (source * (1.0 - resolved_mix)) + (wet.astype(np.float32, copy=False) * resolved_mix)
        return np.clip(mixed, -1.0, 1.0).astype(np.float32, copy=False)

    @staticmethod
    def _apply_exponential_lowpass_blockwise(
        chunk: np.ndarray,
        *,
        alpha: float,
        initial: np.ndarray | None,
        block_size: int = 64,
    ) -> tuple[np.ndarray, np.ndarray]:
        if chunk.size == 0:
            channel_count = int(chunk.shape[1]) if chunk.ndim == 2 else 1
            return chunk.astype(np.float32, copy=False), np.zeros(channel_count, dtype=np.float32)
        if alpha <= 1e-5:
            last = chunk[-1].astype(np.float32, copy=False)
            return chunk.astype(np.float32, copy=False), last
        previous = np.zeros(chunk.shape[1], dtype=np.float64) if initial is None else np.asarray(initial, dtype=np.float64)
        if previous.shape[0] != chunk.shape[1]:
            previous = np.zeros(chunk.shape[1], dtype=np.float64)
        beta = float(1.0 - alpha)
        source = np.asarray(chunk, dtype=np.float64)
        filtered = np.empty_like(source)
        for start in range(0, source.shape[0], max(1, int(block_size))):
            block = source[start : start + max(1, int(block_size))]
            length = block.shape[0]
            powers = np.power(alpha, np.arange(1, length + 1, dtype=np.float64))[:, np.newaxis]
            cumulative = np.cumsum((beta * block) / powers, axis=0)
            block_output = powers * (previous[np.newaxis, :] + cumulative)
            filtered[start : start + length] = block_output
            previous = block_output[-1]
        return filtered.astype(np.float32, copy=False), previous.astype(np.float32, copy=False)

    @staticmethod
    def _apply_live_bitcrush(chunk: np.ndarray, bit_depth: int) -> np.ndarray:
        if chunk.size == 0:
            return chunk
        resolved_depth = int(np.clip(int(bit_depth), 2, 16))
        if resolved_depth >= 16:
            return chunk
        levels = float((2 ** resolved_depth) - 1)
        normalized = np.clip((chunk + 1.0) * 0.5, 0.0, 1.0)
        crushed = np.round(normalized * levels) / levels
        return ((crushed * 2.0) - 1.0).astype(np.float32, copy=False)

    def _queue_live_slot_switch_ui_refresh(self) -> None:
        if self._live_switch_ui_refresh_pending:
            return
        self._live_switch_ui_refresh_pending = True
        self._ui_callback_queue.put(self._apply_live_slot_switch_ui_refresh)

    def _apply_live_slot_switch_ui_refresh(self) -> None:
        self._live_switch_ui_refresh_pending = False
        active_slot = self._live_slots.get(self._live_active_slot)
        self._retimed_preview = active_slot.preview if active_slot is not None else None
        self._retime_visual_segment_index = -1
        self._refresh_live_mode_ui()

    def _commit_live_slot_switch(self, *, defer_ui_refresh: bool = False) -> bool:
        target = self._live_pending_switch_slot
        if not target or not self._live_slot_is_ready(target):
            return False
        previous = self._live_active_slot
        if previous != target and self._live_slots[previous].preview is not None:
            self._live_slots[previous].status = "ready"
        self._live_active_slot = target
        self._live_pending_switch_slot = None
        active_slot = self._live_slots[target]
        active_slot.status = "playing"
        if active_slot.preview is not None:
            playback_audio = active_slot.preview.loop_audio if active_slot.preview.loop_audio is not None else active_slot.preview.audio
            self._retime_stream_audio = self._normalize_preview_audio(playback_audio)
            self._retime_stream_total_frames = int(self._retime_stream_audio.shape[0])
        self._retime_stream_cursor = 0
        self._retime_stream_frames_played = 0
        self._retime_stream_loop_enabled = True
        self._reset_live_filter_state()
        if defer_ui_refresh:
            self._queue_live_slot_switch_ui_refresh()
        else:
            self._apply_live_slot_switch_ui_refresh()
        return True

    def _stop_retimed_preview(self, *_args, update_status: bool = True) -> None:
        owner = self._preview_owner
        self._generator_live_refresh_timer.stop()
        self._retime_stop_timer.stop()
        self._retime_visual_timer.stop()
        self._retime_visual_timer.setInterval(20)
        if self._retime_stream is not None:
            try:
                if getattr(self._retime_stream, "active", False):
                    self._retime_stream.stop()
            except Exception:
                pass
            try:
                self._retime_stream.close()
            except Exception:
                pass
            self._retime_stream = None
        self._retimed_preview_playing = False
        self._retime_visual_started_at = 0.0
        self._retime_visual_segment_index = -1
        self._retime_stream_audio = None
        self._retime_stream_cursor = 0
        self._retime_stream_frames_played = 0
        self._retime_stream_total_frames = 0
        self._retime_stream_loop_enabled = False
        self._retime_underflow_log_at = 0.0
        self._preview_owner = None
        self._live_stutter_pressed = False
        self._set_live_compact_playback_highlight(None, None)
        if hasattr(self, "retime_pattern_preview"):
            self.retime_pattern_preview.set_active_segment(None)
        self.retime_stop_button.setEnabled(False)
        self.generator_stop_button.setEnabled(False)
        if owner == PREVIEW_OWNER_GENERATOR:
            self._refresh_generated_pattern_state()
        elif owner == PREVIEW_OWNER_LIVE:
            for slot_name, slot in self._live_slots.items():
                if slot.preview is not None:
                    slot.status = "ready"
                else:
                    slot.status = "stale"
            self._live_pending_switch_slot = None
            self._reset_live_filter_state()
            self._refresh_live_mode_ui()
        else:
            self._retime_live_changes_pending = False
            self._update_retimed_preview_state(self._result)
        if update_status:
            self._refresh_control_states(self.status_label.text())

    def _on_retimed_preview_finished(self) -> None:
        preview = self._retimed_preview
        owner = self._preview_owner
        self._generator_live_refresh_timer.stop()
        self._retimed_preview_playing = False
        self._retime_visual_timer.stop()
        self._retime_visual_timer.setInterval(20)
        self._retime_visual_started_at = 0.0
        self._retime_visual_segment_index = -1
        self._retime_stream = None
        self._retime_stream_audio = None
        self._retime_stream_cursor = 0
        self._retime_stream_frames_played = 0
        self._retime_stream_total_frames = 0
        self._retime_stream_loop_enabled = False
        self._retime_underflow_log_at = 0.0
        self._preview_owner = None
        self._live_stutter_pressed = False
        self._set_live_compact_playback_highlight(None, None)
        self.retime_stop_button.setEnabled(False)
        self.generator_stop_button.setEnabled(False)
        if preview is not None and owner == PREVIEW_OWNER_GENERATOR:
            self.generator_info_label.setText(
                f"Lecture pattern terminee. {preview.segment_count} evenement(s), "
                f"{preview.target_bpm:.1f} BPM."
            )
            self._refresh_generated_pattern_state()
        elif preview is not None and owner == PREVIEW_OWNER_LIVE:
            for slot_name, slot in self._live_slots.items():
                if slot.preview is not None:
                    slot.status = "ready"
                else:
                    slot.status = "stale"
            self._live_pending_switch_slot = None
            self._reset_live_filter_state()
            self._refresh_live_mode_ui()
        else:
            self._retime_live_changes_pending = False
            self._update_retimed_preview_state(self._result)

    def _stop_retimed_preview_for_waveform(self, *_args) -> None:
        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=True)

    def _start_preview_build(
        self,
        task: Callable[[], RetimedPreview] | None = None,
        *,
        owner: str,
        info_text: str,
        status_text: str,
        process_task: Callable[..., RetimedPreview] | None = None,
        process_args: tuple[object, ...] = (),
        process_kwargs: dict[str, object] | None = None,
    ) -> None:
        if self._preview_busy:
            return
        self._preview_busy = True
        self._preview_loading_bar(owner).setVisible(True)
        self._refresh_control_states(status_text)
        self._preview_info_label(owner).setText(info_text)
        if process_task is not None and _process_pool_allowed():
            worker = ProcessTaskWorker(
                process_task,
                *process_args,
                kwargs=dict(process_kwargs or {}),
                parent=self,
            )
        elif process_task is not None:
            worker = TaskWorker(
                lambda: process_task(*process_args, **dict(process_kwargs or {})),
                self,
            )
        elif task is not None:
            worker = TaskWorker(task, self)
        else:
            self._preview_busy = False
            self._preview_loading_bar(owner).setVisible(False)
            raise ValueError("A preview build task must be provided")
        self._preview_worker = worker
        worker.succeeded.connect(
            lambda preview, preview_owner=owner: self._dispatch_ui_callback(
                lambda: self._on_preview_build_success(preview_owner, preview)
            )
        )
        worker.failed.connect(
            lambda message, preview_owner=owner: self._dispatch_ui_callback(
                lambda: self._on_preview_build_failure(preview_owner, message)
            )
        )
        worker.finished.connect(
            lambda preview_owner=owner: self._dispatch_ui_callback(
                lambda: self._on_preview_build_finished(preview_owner)
            )
        )
        worker.start()

    def _hot_swap_active_preview(self, owner: str, preview: RetimedPreview) -> bool:
        if (
            not self._preview_owner_is_active(owner)
            or self._retimed_preview is None
            or self._retime_stream is None
            or not getattr(self._retime_stream, "active", False)
        ):
            return False
        if preview.sample_rate != self._retimed_preview.sample_rate:
            return False

        loop_enabled = self._preview_loop_enabled(owner)
        playback_audio = preview.loop_audio if loop_enabled and preview.loop_audio is not None else preview.audio
        audio = self._normalize_preview_audio(playback_audio)
        total_frames = int(audio.shape[0])
        if total_frames <= 0:
            return False

        elapsed_s = self._elapsed_preview_seconds()
        frame_position = int(round(elapsed_s * float(preview.sample_rate)))
        if loop_enabled:
            frame_position %= total_frames
        else:
            frame_position = int(np.clip(frame_position, 0, max(total_frames - 1, 0)))

        self._retime_stream_audio = audio
        self._retime_stream_total_frames = total_frames
        self._retime_stream_loop_enabled = loop_enabled
        self._retime_stream_cursor = frame_position
        self._retime_stream_frames_played = frame_position
        self._retimed_preview = preview
        self._retime_visual_segment_index = -1
        if owner == PREVIEW_OWNER_GENERATOR:
            self._generator_live_changes_pending = False
            self.generator_info_label.setText(
                f"Lecture pattern mise a jour en direct: {preview.segment_count} evenement(s), "
                f"{preview.target_bpm:.1f} BPM, {preview.duration_s:.2f}s."
            )
        else:
            self._retime_live_changes_pending = False
            self._refresh_active_retime_preview_message()
        self._refresh_retime_pattern_preview()
        self._update_retimed_preview_visual()
        return True

    def _on_preview_build_success(self, owner: str, preview: RetimedPreview) -> None:
        try:
            if self._hot_swap_active_preview(owner, preview):
                self._refresh_control_states("Lecture mise a jour en direct.")
                return
            sounddevice = _require_sounddevice()
            self._stop_retimed_preview(update_status=False)
            if self._waveform_widget is not None:
                try:
                    self._waveform_widget.stop_audio()
                except Exception:
                    pass
            self._start_retimed_preview_playback(preview, owner=owner, sounddevice=sounddevice)
            self._refresh_control_states("Preview preparee, lecture en cours.")
        except Exception as exc:
            self._retimed_preview_playing = False
            self._preview_owner = None
            self._retime_visual_timer.stop()
            self.retime_stop_button.setEnabled(False)
            self.generator_stop_button.setEnabled(False)
            self._preview_info_label(owner).setText(f"Preview impossible: {exc}")
            QMessageBox.warning(self, "Preview impossible", str(exc))

    def _on_preview_build_failure(self, owner: str, message: str) -> None:
        self._preview_info_label(owner).setText(f"Preparation preview impossible: {message}")
        QMessageBox.warning(self, "Preview impossible", message)

    def _on_preview_build_finished(self, owner: str) -> None:
        self._preview_busy = False
        self._preview_loading_bar(owner).setVisible(False)
        self._preview_worker = None
        if (
            owner == PREVIEW_OWNER_GENERATOR
            and self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
            and self._generator_live_changes_pending
            and self._generated_pattern is not None
            and self._queue_live_generator_preview_refresh()
        ):
            return
        self._refresh_control_states(self.status_label.text())
        self._maybe_close_after_background_tasks()

    def _update_retimed_preview_visual(self) -> None:
        if (
            not self._retimed_preview_playing
            or self._retimed_preview is None
            or (
                not self._retimed_preview.segments
                and not (
                    self._retimed_preview.mode == PREVIEW_MODE_PATTERN
                    and self._retimed_preview.pattern is not None
                    and self._retimed_preview.pattern.steps
                )
            )
        ):
            return

        if self._retime_stream is not None and not getattr(self._retime_stream, "active", False):
            self._on_retimed_preview_finished()
            return

        if self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
            self._update_live_compact_playback_highlight_from_stream()
            if not self._main_tab_is_visible(MAIN_TAB_ANALYZE, MAIN_TAB_GENERATOR):
                return

        elapsed_s = self._elapsed_preview_seconds()
        segment_index, source_position = self._locate_retimed_preview_source_position(elapsed_s)
        if segment_index is None:
            if hasattr(self, "retime_pattern_preview"):
                self.retime_pattern_preview.set_active_segment(None)
            return

        if hasattr(self, "retime_pattern_preview"):
            self.retime_pattern_preview.set_active_segment(segment_index)

        if segment_index != self._retime_visual_segment_index:
            self._retime_visual_segment_index = segment_index
            self._select_retimed_preview_row(segment_index)

        if source_position is None:
            return

        if self._waveform_widget is None or not self._main_tab_is_visible(MAIN_TAB_ANALYZE):
            return

        try:
            self._waveform_widget.read_head.setPos(float(source_position))
        except Exception:
            pass

    def _locate_retimed_preview_source_position(self, elapsed_s: float) -> tuple[int | None, float | None]:
        if self._retimed_preview is None:
            return None, None
        if self._retimed_preview.mode == PREVIEW_MODE_PATTERN and self._retimed_preview.pattern is not None:
            return self._locate_pattern_preview_source_position(elapsed_s)
        if not self._retimed_preview.segments:
            return None, None

        active_index: int | None = None
        active_segment = None
        for index, segment in enumerate(self._retimed_preview.segments):
            if segment.preview_start_s <= elapsed_s <= segment.preview_end_s:
                active_index = index
                active_segment = segment

        if active_segment is None:
            last_index = len(self._retimed_preview.segments) - 1
            last_segment = self._retimed_preview.segments[last_index]
            if elapsed_s >= last_segment.preview_end_s:
                return last_index, float(last_segment.source_end_s)
            return 0, float(self._retimed_preview.segments[0].source_start_s)

        offset_s = max(0.0, elapsed_s - active_segment.preview_start_s)
        source_position = min(active_segment.source_end_s, active_segment.source_start_s + offset_s)
        return active_index, float(source_position)

    def _locate_pattern_preview_source_position(self, elapsed_s: float) -> tuple[int | None, float | None]:
        if self._retimed_preview is None or self._retimed_preview.pattern is None:
            return None, None

        steps = tuple(self._retimed_preview.pattern.steps)
        if not steps:
            return None, None

        step_starts = [
            self._pattern_preview_step_start_seconds(step.step_index, self._retimed_preview)
            for step in steps
        ]
        cycle_end_s = max(
            float(self._retimed_preview.loop_duration_s),
            step_starts[-1] + self._pattern_preview_step_duration_seconds(self._retimed_preview),
        )

        active_row = len(steps) - 1
        for index, start_s in enumerate(step_starts):
            next_start_s = step_starts[index + 1] if index + 1 < len(step_starts) else cycle_end_s
            if start_s <= elapsed_s < next_start_s or (index == len(step_starts) - 1 and elapsed_s <= cycle_end_s):
                active_row = index
                break

        active_step = steps[active_row]
        if (
            active_step.label == "silence"
            or active_step.source_start_s is None
            or active_step.source_end_s is None
        ):
            return active_row, None

        offset_s = max(0.0, elapsed_s - step_starts[active_row])
        source_start_s = float(active_step.source_start_s)
        source_end_s = max(float(active_step.source_end_s), source_start_s)
        source_position = min(source_end_s, source_start_s + offset_s)
        return active_row, float(source_position)

    def _select_retimed_preview_row(self, row: int) -> None:
        if row < 0 or self._retimed_preview is None:
            return
        if self._retimed_preview.mode == PREVIEW_MODE_PATTERN and self._retimed_preview.pattern is not None:
            target_row = max(0, min(int(row), self.generator_table.rowCount() - 1))
            if self._preview_owner_is_active(PREVIEW_OWNER_LIVE):
                self._set_live_compact_playback_highlight(self._live_active_slot, target_row + 1)
                if not self._main_tab_is_visible(MAIN_TAB_GENERATOR):
                    return
            if target_row < self.generator_sequence_table.columnCount():
                self.generator_sequence_table.selectColumn(target_row)
            if target_row >= self.generator_table.rowCount():
                return
            self.generator_table.selectRow(target_row)
            return
        if row >= len(self._retimed_preview.segments):
            return
        segment = self._retimed_preview.segments[row]
        if row >= self.hits_table.rowCount():
            return
        self._suspend_hit_selection_sync = True
        try:
            self.hits_table.selectRow(row)
        finally:
            self._suspend_hit_selection_sync = False
        self._focus_hit_row(row, autoplay=False)

    def _pattern_preview_step_duration_seconds(self, preview: RetimedPreview) -> float:
        return (60.0 / self._effective_preview_target_bpm(preview)) / 4.0

    def _pattern_preview_step_start_seconds(self, step_index: int, preview: RetimedPreview) -> float:
        step_duration_s = self._pattern_preview_step_duration_seconds(preview)
        zero_based = max(0, int(step_index) - 1)
        preview_start_s = float(zero_based) * float(step_duration_s)
        local_step = (zero_based % 16) + 1
        swing = 0.0
        if preview.pattern is not None:
            swing = float(np.clip(preview.pattern.swing, 0.0, 1.0))
        if local_step in {3, 7, 11, 15}:
            preview_start_s += swing * (step_duration_s * 0.35)
        return max(0.0, preview_start_s)

    def _on_generator_sequence_cell_clicked(self, _row: int, column: int) -> None:
        self._focus_generated_step(column + 1, autoplay=False)

    def _on_generator_sequence_header_clicked(self, column: int) -> None:
        self._focus_generated_step(column + 1, autoplay=True)

    def _focus_generated_step(self, step_index: int, *, autoplay: bool) -> None:
        column = int(step_index) - 1
        if column < 0:
            return
        if column < self.generator_sequence_table.columnCount():
            self.generator_sequence_table.selectColumn(column)
        if column < self.generator_table.rowCount():
            self.generator_table.selectRow(column)

        pattern = self._generated_pattern
        result = self._result
        if pattern is None or result is None:
            return
        if step_index < 1 or step_index > len(pattern.steps):
            return

        step = pattern.steps[step_index - 1]
        if step.label == "silence" or step.source_hit_index is None:
            if autoplay:
                self.generator_info_label.setText(f"Step {step_index}: silence, rien a jouer sur la waveform.")
            return

        target_row = next(
            (row for row, hit in enumerate(result.transient_hits) if int(hit.index) == int(step.source_hit_index)),
            -1,
        )
        if target_row < 0:
            return
        self._focus_hit_row(target_row, autoplay=autoplay)

    def _on_hit_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row() if item is not None else self.hits_table.currentRow()
        self._focus_hit_row(row, autoplay=True)

    def _on_hit_selected(self) -> None:
        if self._suspend_hit_selection_sync:
            return
        self._focus_hit_row(self.hits_table.currentRow(), autoplay=False)

    def _on_hit_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row() if item is not None else self.hits_table.currentRow()
        if row >= 0 and self.hits_table.currentRow() != row:
            self._suspend_hit_selection_sync = True
            try:
                self.hits_table.selectRow(row)
            finally:
                self._suspend_hit_selection_sync = False
        self._focus_hit_row(row, autoplay=False)

    def _focus_hit_row(self, row: int, *, autoplay: bool) -> None:
        if row < 0 or self._waveform_widget is None:
            return
        marker_list = getattr(self._waveform_widget, "marker_list", None)
        if marker_list is None or row >= marker_list.count():
            return
        item = marker_list.item(row)
        if item is None:
            return
        try:
            self._waveform_widget.on_marker_list_clicked(item)
            self._center_waveform_on_marker_item(item)
            if autoplay:
                self._waveform_widget.play_from_start()
        except Exception:
            pass

    def _center_waveform_on_marker_item(self, item) -> None:
        if self._waveform_widget is None or item is None:
            return

        payload = item.data(Qt.ItemDataRole.UserRole)
        marker_time = payload.get("time") if isinstance(payload, dict) else None
        if marker_time is None:
            return

        try:
            marker_time = float(marker_time)
        except (TypeError, ValueError):
            return

        plot = getattr(self._waveform_widget, "plot", None)
        duration = float(getattr(self._waveform_widget, "duration", 0.0) or 0.0)
        if plot is None or duration <= 0.0:
            return

        try:
            view_box = plot.getViewBox()
            x_range = view_box.viewRange()[0]
            visible_span = float(x_range[1] - x_range[0])
        except Exception:
            visible_span = duration

        if not np.isfinite(visible_span) or visible_span <= 0.0:
            visible_span = duration
        visible_span = float(np.clip(visible_span, min(0.05, duration), duration))

        half_span = visible_span / 2.0
        max_start = max(0.0, duration - visible_span)
        start = float(np.clip(marker_time - half_span, 0.0, max_start))
        end = min(duration, start + visible_span)
        start = max(0.0, end - visible_span)

        try:
            plot.setXRange(start, end, padding=0)
        except Exception:
            pass

    def _apply_preview_markers_to_waveform(
        self,
        marker_times: list[float],
        preview: DrumTransientPreview,
    ) -> None:
        if self._waveform_widget is None or getattr(self._waveform_widget, "waveform_data", None) is None:
            return
        self._clear_waveform_markers()
        if not marker_times:
            self.waveform_status_label.setText("Premiere passe terminee, mais aucun marker provisoire n'a ete pose.")
            return

        self._suspend_marker_persistence = True
        self._waveform_widget._record_history = False
        try:
            for marker_time in marker_times:
                self._waveform_widget.add_marker(float(marker_time))
        finally:
            self._waveform_widget._record_history = True
            self._suspend_marker_persistence = False

        marker_list = getattr(self._waveform_widget, "marker_list", None)
        if marker_list is not None:
            for row, marker_time in enumerate(marker_times):
                if row >= marker_list.count():
                    break
                item = marker_list.item(row)
                if item is None:
                    continue
                item.setToolTip(f"Transient provisoire | {marker_time:.3f}s")

        tempo_hint = f" | tempo approx {preview.tempo_bpm:.1f} bpm" if preview.tempo_bpm > 1.0 else ""
        self.waveform_status_label.setText(
            f"{len(marker_times)} marker(s) provisoire(s) poses sur la waveform{tempo_hint}. "
            "Analyse detaillee toujours en cours..."
        )

    def _apply_hits_to_waveform(self, result: DrumDetectionResult, *, preserve_existing: bool = False) -> None:
        if self._waveform_widget is None or getattr(self._waveform_widget, "waveform_data", None) is None:
            return
        if not result.transient_hits:
            self._clear_waveform_markers()
            self.waveform_status_label.setText("Waveform chargee, mais aucun transient exploitable n'a ete trouve.")
            return

        existing_markers = self._current_marker_times()
        should_rebuild_markers = (
            not preserve_existing
            or len(existing_markers) != len(result.transient_hits)
        )

        if should_rebuild_markers:
            self._clear_waveform_markers()
            self._suspend_marker_persistence = True
            self._waveform_widget._record_history = False
            try:
                for hit in result.transient_hits:
                    self._waveform_widget.add_marker(float(hit.start_s))
            finally:
                self._waveform_widget._record_history = True
                self._suspend_marker_persistence = False
        else:
            try:
                self._waveform_widget._refresh_marker_list()
            except Exception:
                should_rebuild_markers = True
                self._clear_waveform_markers()
                self._suspend_marker_persistence = True
                self._waveform_widget._record_history = False
                try:
                    for hit in result.transient_hits:
                        self._waveform_widget.add_marker(float(hit.start_s))
                finally:
                    self._waveform_widget._record_history = True
                    self._suspend_marker_persistence = False

        marker_list = getattr(self._waveform_widget, "marker_list", None)
        if marker_list is not None:
            for row, hit in enumerate(result.transient_hits):
                if row >= marker_list.count():
                    break
                item = marker_list.item(row)
                if item is None:
                    continue
                secondary = ", ".join(hit.secondary_labels) if getattr(hit, "secondary_labels", ()) else "-"
                item.setToolTip(
                    f"{hit.label} | {hit.start_s:.3f}s -> {hit.end_s:.3f}s | "
                    f"conf {hit.confidence:.2f} | peak {hit.peak_db:.1f} dB | "
                    f"role {getattr(hit, 'role', 'other')} | layers {secondary}"
                )

        self.waveform_status_label.setText(
            f"{len(result.transient_hits)} marker(s) poses sur la waveform. "
            + (
                "Markers manuels preserves et liste des transients mise a jour."
                if preserve_existing and not should_rebuild_markers
                else "Simple clic dans la table = navigation + lecture directe. Selection + Cut = edition audio."
            )
        )
        self._persist_marker_times_for_path(self._current_resolved_path() or self._loaded_audio_path, self._current_marker_times())

    def _clear_waveform_markers(self) -> None:
        if self._waveform_widget is None:
            return
        try:
            self._waveform_widget.stop_audio()
        except Exception:
            pass
        try:
            region = getattr(self._waveform_widget, "region", None)
            if region is not None:
                self._waveform_widget.plot.removeItem(region)
                self._waveform_widget.region = None
        except Exception:
            pass
        try:
            for line in list(self._waveform_widget.marker_lines.values()):
                self._waveform_widget.plot.removeItem(line)
        except Exception:
            pass

        self._waveform_widget.markers = []
        self._waveform_widget.marker_lines = {}
        self._waveform_widget.current_marker_idx = 0
        self._waveform_widget.play_start = 0.0
        self._waveform_widget.play_end = 0.0
        try:
            self._waveform_widget.read_head.setPos(0.0)
            self._waveform_widget._refresh_marker_list()
        except Exception:
            pass

    def _load_audio_for_waveform(self, path: Path):
        soundfile = _require_soundfile()
        samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
        if samples.shape[1] == 1:
            waveform_data = samples[:, 0]
        else:
            waveform_data = samples.T
        duration_s = float(samples.shape[0]) / float(sample_rate) if sample_rate else 0.0
        return samples.astype(np.float32, copy=False), waveform_data, int(sample_rate), duration_s

    @staticmethod
    def _ensure_table_column_widths(table: QTableWidget, minimums: dict[int, int]) -> None:
        for column, minimum in minimums.items():
            table.setColumnWidth(column, max(table.columnWidth(column), minimum))

    @staticmethod
    def _build_font(point_size: int, *, bold: bool = False) -> QFont:
        font = QFont()
        font.setPointSize(point_size)
        font.setBold(bold)
        return font

    @staticmethod
    def _normalize_preview_audio(audio: np.ndarray) -> np.ndarray:
        normalized = np.asarray(audio, dtype=np.float32)
        if normalized.ndim == 1:
            normalized = normalized[:, np.newaxis]
        elif normalized.ndim == 2 and normalized.shape[0] <= 8 and normalized.shape[1] > normalized.shape[0]:
            normalized = normalized.T
        if normalized.ndim != 2 or normalized.shape[0] <= 0 or normalized.shape[1] <= 0:
            raise ValueError("Preview audio buffer has an invalid shape")
        return np.ascontiguousarray(normalized)

    def _elapsed_preview_seconds(self) -> float:
        if self._retimed_preview is None:
            return 0.0
        if self._retimed_preview.sample_rate <= 0 or self._retime_stream_frames_played <= 0:
            return 0.0
        elapsed_s = float(self._retime_stream_frames_played) / float(self._retimed_preview.sample_rate)
        if (
            self._preview_owner_is_active(PREVIEW_OWNER_LIVE)
            and self._retimed_preview.pattern is not None
            and self._retimed_preview.pattern.step_count > 0
        ):
            cycle_duration_s = (
                float(self._retimed_preview.pattern.step_count)
                * self._pattern_preview_step_duration_seconds(self._retimed_preview)
            )
        else:
            cycle_duration_s = (
                self._retimed_preview.loop_duration_s
                if self._retime_stream_loop_enabled and self._retimed_preview.loop_duration_s > 0.0
                else self._retimed_preview.duration_s
            )
        if cycle_duration_s > 0.0 and (
            self._retime_stream_loop_enabled or self._retime_stream_frames_played > self._retime_stream_total_frames
        ):
            elapsed_s %= cycle_duration_s
        return min(elapsed_s, cycle_duration_s)

    def _install_waveform_edit_hooks(self, waveform) -> None:
        original_cut = waveform._cut_region
        original_undo = waveform.undo
        original_redo = waveform.redo

        def cut_and_sync(start, end):
            original_cut(start, end)
            self._after_waveform_edit(
                "Selection coupee. Rebuild Hits From Markers ou Analyser pour recalculer les slices."
            )

        def undo_and_sync():
            original_undo()
            self._after_waveform_edit(
                "Undo applique sur la waveform. Relance un rebuild si tu veux rafraichir les transients."
            )

        def redo_and_sync():
            original_redo()
            self._after_waveform_edit(
                "Redo applique sur la waveform. Relance un rebuild si tu veux rafraichir les transients."
            )

        waveform._cut_region = cut_and_sync
        waveform.undo = undo_and_sync
        waveform.redo = redo_and_sync

        for name, handler in (("undo_button", waveform.undo), ("redo_button", waveform.redo)):
            button = getattr(waveform, name, None)
            if button is None:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    button.clicked.disconnect()
            except Exception:
                pass
            button.clicked.connect(handler)

    def _install_waveform_marker_hooks(self, waveform) -> None:
        original_add_marker = waveform.add_marker
        original_remove_marker = waveform.remove_marker
        original_move_finished = waveform._on_marker_move_finished

        def add_marker_and_sync(time_s):
            original_add_marker(time_s)
            self._schedule_marker_persist()

        def remove_marker_and_sync(time_s):
            original_remove_marker(time_s)
            self._schedule_marker_persist()

        def move_finished_and_sync(line):
            original_move_finished(line)
            self._schedule_marker_persist()

        waveform.add_marker = add_marker_and_sync
        waveform.remove_marker = remove_marker_and_sync
        waveform._on_marker_move_finished = move_finished_and_sync

    def _show_waveform_context_menu(self, pos) -> None:
        if self._waveform_widget is None:
            return
        plot = getattr(self._waveform_widget, "plot", None)
        if plot is None:
            return

        menu = QMenu(self)
        split_action = menu.addAction("Split sample equally...")
        split_action.setEnabled(self._can_split_waveform_evenly())
        action = menu.exec(plot.mapToGlobal(pos))
        if action is split_action:
            self._split_waveform_equally()

    def _can_split_waveform_evenly(self) -> bool:
        if self._waveform_widget is None:
            return False
        waveform_data = getattr(self._waveform_widget, "waveform_data", None)
        duration = float(getattr(self._waveform_widget, "duration", 0.0) or 0.0)
        return waveform_data is not None and duration > 0.0

    def _replace_waveform_markers(self, marker_times: list[float]) -> None:
        if self._waveform_widget is None:
            return

        self._clear_waveform_markers()
        self._suspend_marker_persistence = True
        self._waveform_widget._record_history = False
        try:
            for marker_time in marker_times:
                self._waveform_widget.add_marker(float(marker_time))
        finally:
            self._waveform_widget._record_history = True
            self._suspend_marker_persistence = False

        try:
            self._waveform_widget._refresh_marker_list()
        except Exception:
            pass

    def _after_waveform_marker_layout_change(self, status: str) -> None:
        self._stop_retimed_preview(update_status=False)
        if self._waveform_widget is not None:
            try:
                self._waveform_widget.stop_audio()
            except Exception:
                pass
        self._analysis_stale = self._result is not None
        self._generated_pattern = None
        self._reset_live_slots()
        self._populate_generated_pattern(None)
        self.waveform_status_label.setText(
            "Markers redistribues sur la waveform. Relance un rebuild ou une analyse pour recalculer les hits."
        )
        self.rebuild_markers_label.setText(
            "Decoupage equilibre applique. Les markers visibles sont a jour, mais la liste de transients doit etre rebuild/analysee."
        )
        if self._result is not None:
            self.hits_summary_label.setText(
                "Markers modifies. Les hits affiches peuvent etre perimes tant que tu n'as pas relance un rebuild ou une analyse."
            )
        self._persist_current_markers(force=True)
        self._update_retimed_preview_state(self._result)
        self._refresh_generated_pattern_state()
        self._refresh_control_states(status)

    def _split_waveform_equally(self) -> None:
        if not self._can_split_waveform_evenly():
            QMessageBox.information(
                self,
                "Waveform indisponible",
                "Charge d'abord un sample avec une waveform valide pour le decouper.",
            )
            return

        duration = float(getattr(self._waveform_widget, "duration", 0.0) or 0.0)
        current_markers = self._current_marker_times()
        default_slices = int(np.clip((len(current_markers) + 1) if current_markers else 4, 2, 64))
        slice_count, accepted = QInputDialog.getInt(
            self,
            "Split sample equally",
            "Nombre de slices :",
            default_slices,
            2,
            128,
            1,
        )
        if not accepted:
            return

        marker_times = [
            float(time_s)
            for time_s in np.linspace(0.0, duration, int(slice_count) + 1, endpoint=True)[1:-1]
            if 0.0 < float(time_s) < duration
        ]
        self._replace_waveform_markers(marker_times)
        self._after_waveform_marker_layout_change(
            f"Split sample applique: {slice_count} slices regulieres sur {duration:.2f}s."
        )

    def _current_resolved_path(self) -> str | None:
        raw_path = self.path_input.text().strip()
        if not raw_path:
            return None
        try:
            return str(Path(raw_path).expanduser().resolve())
        except Exception:
            return str(Path(raw_path).expanduser())

    def _waveform_audio_reference(self) -> tuple[np.ndarray, int] | None:
        if self._waveform_widget is None:
            return None
        waveform_data = getattr(self._waveform_widget, "waveform_data", None)
        sample_rate = int(getattr(self._waveform_widget, "sample_rate", 0) or 0)
        widget_path = getattr(self._waveform_widget, "audio_file_path", None)
        current_path = self._current_resolved_path()
        if waveform_data is None or sample_rate <= 0 or not widget_path or not current_path:
            return None
        try:
            resolved_widget_path = str(Path(widget_path).expanduser().resolve())
        except Exception:
            resolved_widget_path = str(widget_path)
        if resolved_widget_path != current_path:
            return None
        return np.asarray(waveform_data, dtype=np.float32), sample_rate

    def _analysis_audio_snapshot(self) -> tuple[np.ndarray, int] | None:
        waveform_audio = self._waveform_audio_reference()
        if waveform_audio is not None:
            audio, sample_rate = waveform_audio
            return np.array(audio, dtype=np.float32, copy=True), int(sample_rate)
        if self._loaded_audio_samples is None or not self._loaded_audio_sample_rate:
            return None
        return (
            np.array(self._loaded_audio_samples, dtype=np.float32, copy=True),
            int(self._loaded_audio_sample_rate),
        )

    def _retain_live_audio_shared_memory(self, handle: shared_memory.SharedMemory | None) -> None:
        if handle is not None:
            self._retained_live_audio_shared_memories.append(handle)

    def _release_retained_live_audio_shared_memories(self, *, force: bool = False) -> None:
        if not force and any(worker is not None and worker.isRunning() for worker in self._live_slot_workers.values()):
            return
        retained = self._retained_live_audio_shared_memories
        self._retained_live_audio_shared_memories = []
        for handle in retained:
            try:
                handle.close()
            except Exception:
                pass

    def _clear_live_audio_shared_buffer(self, *, retain_if_busy: bool = True) -> None:
        handle = self._live_audio_shared_memory
        self._live_audio_shared_memory = None
        self._live_audio_shared_shape = None
        self._live_audio_shared_sample_rate = None
        if handle is None:
            return
        if retain_if_busy and any(worker is not None and worker.isRunning() for worker in self._live_slot_workers.values()):
            self._retain_live_audio_shared_memory(handle)
            return
        try:
            handle.close()
        except Exception:
            pass

    def _sync_live_audio_shared_buffer(self) -> None:
        if self._loaded_audio_samples is None or not self._loaded_audio_sample_rate:
            self._clear_live_audio_shared_buffer()
            return
        samples = np.ascontiguousarray(np.asarray(self._loaded_audio_samples, dtype=np.float32))
        if samples.size <= 0:
            self._clear_live_audio_shared_buffer()
            return
        current = self._live_audio_shared_memory
        if current is None or self._live_audio_shared_shape != tuple(samples.shape):
            self._clear_live_audio_shared_buffer()
            current = shared_memory.SharedMemory(create=True, size=int(samples.nbytes))
            self._live_audio_shared_memory = current
            self._live_audio_shared_shape = tuple(int(dim) for dim in samples.shape)
        shared_array = np.ndarray(tuple(int(dim) for dim in samples.shape), dtype=np.float32, buffer=current.buf)
        shared_array[...] = samples
        self._live_audio_shared_sample_rate = int(self._loaded_audio_sample_rate)

    def _live_audio_shared_spec(self) -> tuple[str, tuple[int, ...], int] | None:
        handle = self._live_audio_shared_memory
        shape = self._live_audio_shared_shape
        sample_rate = self._live_audio_shared_sample_rate
        if handle is None or shape is None or not sample_rate:
            return None
        return handle.name, tuple(int(dim) for dim in shape), int(sample_rate)

    def _sync_audio_state_from_waveform(self) -> bool:
        waveform_audio = self._waveform_audio_reference()
        if waveform_audio is None:
            return False
        audio, sample_rate = waveform_audio
        self._loaded_audio_samples = np.array(audio, dtype=np.float32, copy=True)
        self._loaded_audio_sample_rate = int(sample_rate)
        self._loaded_audio_path = self._current_resolved_path()
        self._sync_live_audio_shared_buffer()
        return True

    def _after_waveform_edit(self, status: str) -> None:
        self._stop_retimed_preview(update_status=False)
        if self._waveform_widget is not None:
            try:
                self._waveform_widget.stop_audio()
            except Exception:
                pass
        self._sync_audio_state_from_waveform()
        self._analysis_stale = self._result is not None
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._populate_generated_pattern(None)
        self.waveform_status_label.setText(
            "Waveform editee. La prochaine analyse / reanalyse utilisera bien l'audio courant, cuts inclus."
        )
        self.rebuild_markers_label.setText(
            "Waveform modifiee. Les markers visibles ont suivi l'edition, mais la liste de transients doit etre rebuild/analysee."
        )
        if self._result is not None:
            self.hits_summary_label.setText(
                "Waveform editee. Les hits affiches peuvent etre perimes tant que tu n'as pas relance un rebuild ou une analyse."
            )
        self._persist_current_markers(force=True)
        self._update_retimed_preview_state(self._result)
        self._refresh_generated_pattern_state()
        self._refresh_control_states(status)

    def _cut_waveform_selection(self) -> None:
        if self._waveform_widget is None or getattr(self._waveform_widget, "region", None) is None:
            QMessageBox.information(
                self,
                "Selection requise",
                "Glisse d'abord sur la waveform pour creer une region a couper.",
            )
            return
        start, end = self._waveform_widget.region.getRegion()
        if end <= start:
            QMessageBox.information(self, "Selection vide", "La region selectionnee est vide.")
            return
        self._waveform_widget._cut_region(float(start), float(end))

    def _undo_waveform_edit(self) -> None:
        if self._waveform_widget is None:
            return
        self._waveform_widget.undo()

    def _redo_waveform_edit(self) -> None:
        if self._waveform_widget is None:
            return
        self._waveform_widget.redo()

    def _on_rebuild_success(self, rebuilt: DrumDetectionResult, marker_count: int) -> None:
        rebuilt = self._apply_persisted_hit_labels(rebuilt)
        self._analysis_stale = False
        self._result = rebuilt
        self._generated_pattern = None
        self._clear_generator_pipeline_state()
        self._reset_live_slots()
        self._generator_locked_steps.clear()
        self._persist_detection_result(rebuilt)
        self._populate_result(rebuilt)
        self._populate_hits(rebuilt)
        self._apply_hits_to_waveform(rebuilt, preserve_existing=True)
        self._update_retimed_preview_state(rebuilt)
        self._populate_generated_pattern(None)
        self._refresh_generated_pattern_state()
        self.rebuild_markers_label.setText(
            f"Reanalyse depuis {marker_count} marker(s): {rebuilt.onset_count} transient(s) reconstruits."
        )
        self._refresh_control_states(
            f"Liste des transients reconstruite depuis les markers. {rebuilt.label} ({rebuilt.form})."
        )

    def _on_rebuild_failure(self, message: str) -> None:
        QMessageBox.warning(self, "Reanalyse impossible", message)
        self.rebuild_markers_label.setText(f"Reanalyse depuis markers impossible: {message}")
        self._refresh_control_states(f"Reanalyse depuis markers impossible: {message}")

    def _on_rebuild_finished(self) -> None:
        self._rebuild_busy = False
        self.waveform_loading_bar.setVisible(False)
        self.main_loading_bar.setVisible(self._analysis_busy)
        self._rebuild_worker = None
        self._refresh_control_states(self.status_label.text())
        self._maybe_close_after_background_tasks()

    def _on_pattern_generated(self, pattern: GeneratedBreakPattern) -> None:
        generator_playing = self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR)
        self._generated_pattern = pattern
        self._generator_live_changes_pending = generator_playing
        self._populate_generated_pattern(pattern)
        if generator_playing and self._queue_live_generator_preview_refresh():
            self.generator_info_label.setText(
                f"Lecture pattern en cours. Variation du stepper en cours d'application sur {pattern.step_count} steps."
            )
            self._refresh_control_states(
                f"Pattern regenere: {pattern.event_count} evenement(s), mise a jour live en cours."
            )
            return
        self._refresh_generated_pattern_state()
        self._refresh_control_states(
            f"Pattern genere a partir du break: {pattern.event_count} evenement(s), nouvelle variation prete."
        )

    def _on_pattern_generation_failed(self, message: str) -> None:
        self.generator_info_label.setText(f"Generation impossible: {message}")
        QMessageBox.warning(self, "Generation impossible", message)
        self._refresh_control_states(f"Generation du pattern impossible: {message}")

    def _on_generation_debug_report_failed(self, message: str) -> None:
        self.generator_info_label.setText(f"Rapport debug impossible: {message}")
        QMessageBox.warning(self, "Rapport debug impossible", message)
        self._refresh_control_states(f"Rapport debug impossible: {message}")

    def _on_generation_debug_report_ready(
        self,
        payload: tuple[GeneratedBreakPattern, str] | object,
        seed: int,
    ) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._on_generation_debug_report_failed("Retour debug invalide.")
            return
        _pattern, report = payload
        if not isinstance(report, str):
            self._on_generation_debug_report_failed("Rapport debug invalide.")
            return
        self.generator_info_label.setText(
            f"Rapport debug regenere pour la seed {int(seed)} avec le profil {GENERATION_PROFILE_LABELS.get(self._generator_profile(), 'Musical')}."
        )
        self._show_generation_debug_report_dialog(report, seed=int(seed))
        self._refresh_control_states(f"Rapport debug pret pour la seed {int(seed)}.")

    def _show_generation_debug_report_dialog(self, report: str, *, seed: int) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Debug report - seed {int(seed)}")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        text_view = QPlainTextEdit(dialog)
        text_view.setReadOnly(True)
        text_view.setPlainText(report)
        text_view.setMinimumSize(QSize(920, 680))
        layout.addWidget(text_view, 1)

        button_row = QHBoxLayout()
        copy_button = QPushButton("Copy", dialog)
        save_button = QPushButton("Save .txt", dialog)
        close_button = QPushButton("Close", dialog)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(report))

        def _save_report() -> None:
            default_path = Path.cwd() / f"break_generation_report_seed_{int(seed)}.txt"
            save_path, _selected_filter = QFileDialog.getSaveFileName(
                self,
                "Save debug report",
                str(default_path),
                "Text files (*.txt);;All files (*.*)",
            )
            if not save_path:
                return
            try:
                Path(save_path).write_text(report, encoding="utf-8")
                self.generator_info_label.setText(f"Rapport debug sauvegarde dans {Path(save_path).name}.")
            except Exception as exc:
                QMessageBox.warning(self, "Sauvegarde impossible", str(exc))

        save_button.clicked.connect(_save_report)
        close_button.clicked.connect(dialog.accept)
        button_row.addStretch(1)
        button_row.addWidget(copy_button)
        button_row.addWidget(save_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)
        dialog.resize(1000, 760)
        dialog.exec()

    def _on_pattern_generation_finished(self) -> None:
        self._generator_busy = False
        self.generator_loading_bar.setVisible(False)
        self._generator_worker = None
        self._refresh_control_states(self.status_label.text())
        self._maybe_close_after_background_tasks()

    def _running_workers(self) -> list[QThread]:
        live_workers = [worker for worker in self._live_slot_workers.values() if worker is not None]
        return [
            worker
            for worker in (
                self._worker,
                self._waveform_loader,
                self._rebuild_worker,
                self._generator_worker,
                self._preview_worker,
                *live_workers,
            )
            if worker is not None and worker.isRunning()
        ]

    def _maybe_close_after_background_tasks(self) -> None:
        if self._close_after_background_tasks and not self._running_workers():
            self._close_after_background_tasks = False
            QTimer.singleShot(0, self.close)


def _extract_audio_path(mime_data) -> str | None:
    if not mime_data.hasUrls():
        return None
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        local_path = url.toLocalFile()
        if Path(local_path).suffix.lower() in AUDIO_EXTENSIONS:
            return local_path
    return None


def _bootstrap_qt_app() -> QApplication:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.ole32.OleInitialize(0)
        except Exception:
            pass

    app = QApplication.instance() or QApplication(sys.argv)
    try:
        from frontend.styles import theme as _theme

        _theme.manager.apply()
    except Exception:
        pass
    return app


def launch_ui() -> int:
    app = _bootstrap_qt_app()
    window = DrumDetectorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch_ui())
