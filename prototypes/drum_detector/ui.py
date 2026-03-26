from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
from importlib import import_module
import json
import logging
import os
from pathlib import Path
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
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
)
from .preview import (
    DEFAULT_QUANTIZE_GRID_DIVISION,
    DEFAULT_QUANTIZE_STRENGTH,
    PREVIEW_MODE_PATTERN,
    PREVIEW_MODE_QUANTIZE,
    PREVIEW_MODE_RETIME,
    QUANTIZE_GRID_DIVISIONS,
    RetimedPreview,
    build_pattern_preview,
    build_retimed_preview,
    estimate_retimed_preview_duration,
    format_quantize_grid_label,
)
from .pattern_generator import (
    BreakPatternParams,
    GeneratedBreakPattern,
    estimate_pattern_effect_probabilities,
    estimate_pattern_family_probabilities,
    generate_break_pattern,
    reroll_break_pattern_step,
)

PREVIEW_OWNER_RETIME = "retime"
PREVIEW_OWNER_GENERATOR = "generator"
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
MAX_RECENT_FILES = 12
RECENT_FILES_SETTINGS_KEY = "recent_files"
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
        self._result: DrumDetectionResult | None = None
        self._suspend_hit_selection_sync = False
        self._loaded_audio_samples: np.ndarray | None = None
        self._loaded_audio_sample_rate: int | None = None
        self._loaded_audio_path: str | None = None
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
        self._marker_persist_timer = QTimer(self)
        self._marker_persist_timer.setSingleShot(True)
        self._marker_persist_timer.timeout.connect(self._persist_current_markers)
        self._preview_owner: str | None = None
        self._retime_live_changes_pending = False
        self._generator_live_changes_pending = False

        self._build_ui()
        self._build_waveform_shortcuts()
        self._apply_style()
        self._init_waveform_panel()
        self._restore_state()

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

        self.page_sections_splitter = QSplitter(Qt.Orientation.Vertical)
        self.page_sections_splitter.setChildrenCollapsible(False)
        self.page_sections_splitter.setHandleWidth(10)
        self._build_waveform_box(self.page_sections_splitter)
        self._build_result_boxes(self.page_sections_splitter)
        self.page_sections_splitter.setStretchFactor(0, 7)
        self.page_sections_splitter.setStretchFactor(1, 4)
        root.addWidget(self.page_sections_splitter, 1)

        root.insertWidget(0, title)
        root.insertWidget(1, subtitle)
        root.insertLayout(2, path_row)
        root.insertLayout(3, options_row)
        root.insertWidget(4, self.status_label)
        root.insertWidget(5, self.main_loading_bar)
        self._refresh_split_density_label(self.split_density_slider.value())

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

        self.hits_table = QTableWidget(0, 6)
        self.hits_table.setHorizontalHeaderLabels(("Hit", "Label", "Start", "End", "Conf", "Peak dB"))
        self.hits_table.verticalHeader().setVisible(False)
        self.hits_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hits_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.hits_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.hits_table.setAlternatingRowColors(True)
        self.hits_table.setWordWrap(False)
        self.hits_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.hits_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.hits_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.hits_table.setMinimumHeight(150)
        self.hits_table.setMinimumWidth(920)
        header = self.hits_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        for column in range(6):
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

        layout.addWidget(self.waveform_status_label)
        layout.addWidget(self.waveform_loading_bar)
        layout.addLayout(self.waveform_host)
        layout.addLayout(edit_row)
        layout.addWidget(self.waveform_edit_label)
        self._build_retime_controls(layout)
        self._build_generator_controls(layout)
        self.waveform_sections_splitter = QSplitter(Qt.Orientation.Vertical)
        self.waveform_sections_splitter.setChildrenCollapsible(False)
        self.waveform_sections_splitter.setHandleWidth(8)
        self.waveform_sections_splitter.addWidget(self.hits_panel)
        self.waveform_sections_splitter.addWidget(self.retime_box)
        self.waveform_sections_splitter.addWidget(self.generator_box)
        self.waveform_sections_splitter.setStretchFactor(0, 5)
        self.waveform_sections_splitter.setStretchFactor(1, 2)
        self.waveform_sections_splitter.setStretchFactor(2, 4)
        layout.addWidget(self.waveform_sections_splitter, 1)
        self.waveform_box.setMinimumHeight(420)
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
            shortcut.activated.connect(handler)
            self._waveform_shortcuts.append(shortcut)

    def _with_waveform(self, callback: Callable[[QWidget], None]) -> None:
        if self._waveform_widget is None:
            return
        callback(self._waveform_widget)

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

        self.generator_energy_slider, self.generator_energy_value = self._build_percent_slider(55)
        self.generator_kick_slider, self.generator_kick_value = self._build_percent_slider(60)
        self.generator_snare_slider, self.generator_snare_value = self._build_percent_slider(70)
        self.generator_hat_slider, self.generator_hat_value = self._build_percent_slider(60)
        self.generator_ghost_slider, self.generator_ghost_value = self._build_percent_slider(25)
        self.generator_fill_slider, self.generator_fill_value = self._build_percent_slider(35)
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
        self.generator_gate_slider, self.generator_gate_value = self._build_percent_slider(
            int(self._settings.value("generator_gate", 100, type=int))
        )
        self.generator_gate_slider.valueChanged.connect(self._on_generator_gate_changed)
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
        self.generator_velocity_slider, self.generator_velocity_value = self._build_percent_slider(50)
        self.generator_swing_slider, self.generator_swing_value = self._build_percent_slider(0)
        self.generator_anti_repeat_slider, self.generator_anti_repeat_value = self._build_percent_slider(60)
        self.generator_breath_slider, self.generator_breath_value = self._build_percent_slider(35)
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
            self.generator_gate_slider,
            self.generator_velocity_slider,
            self.generator_swing_slider,
            self.generator_anti_repeat_slider,
            self.generator_breath_slider,
            self.generator_position_fidelity_slider,
        ):
            slider.valueChanged.connect(self._refresh_generator_probability_preview)

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
        self.generator_effect_probability_table = QTableWidget(4, 3)
        self.generator_effect_probability_table.setHorizontalHeaderLabels(("Repeat", "Reverse", "K.Roll"))
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
        for column in range(3):
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
            "Seed de la derniere variation generee. Elle est informativa seulement: chaque clic sur Generate random en cree une nouvelle.",
            generator_seed_label,
        )

        grid.addWidget(generator_source_bpm_label, 0, 0)
        grid.addWidget(self.generator_detected_bpm_value, 0, 1)
        grid.addWidget(generator_target_bpm_label, 0, 2)
        grid.addWidget(self.generator_target_bpm_spin, 0, 3)
        grid.addWidget(generator_bars_label, 0, 4)
        grid.addWidget(self.generator_bars_spin, 0, 5)
        grid.addWidget(generator_seed_label, 0, 6)
        grid.addWidget(self.generator_seed_value, 0, 7)
        grid.addWidget(self.generator_generate_button, 0, 8)
        grid.addWidget(self.generator_play_button, 0, 9)
        grid.addWidget(self.generator_stop_button, 0, 10)
        grid.addWidget(self.generator_loop_button, 0, 11)

        grid.addWidget(self._build_generator_section_label("Groove Core"), 1, 0, 1, 12)
        self._add_generator_slider_row(grid, 2, "Energy", self.generator_energy_slider, self.generator_energy_value, "Kick", self.generator_kick_slider, self.generator_kick_value)
        self._add_generator_slider_row(grid, 3, "Snare", self.generator_snare_slider, self.generator_snare_value, "Hat", self.generator_hat_slider, self.generator_hat_value)
        self._add_generator_slider_row(grid, 4, "Ghost", self.generator_ghost_slider, self.generator_ghost_value, "Breath", self.generator_breath_slider, self.generator_breath_value)

        grid.addWidget(self._build_generator_section_label("Structure & Phrase"), 5, 0, 1, 12)
        self._add_generator_slider_row(grid, 6, "Fill", self.generator_fill_slider, self.generator_fill_value, "Sequences", self.generator_sequence_density_slider, self.generator_sequence_density_value)
        self._add_generator_slider_row(grid, 7, "Position", self.generator_position_fidelity_slider, self.generator_position_fidelity_value, "Anti-repeat", self.generator_anti_repeat_slider, self.generator_anti_repeat_value)
        grid.addWidget(self._build_generator_section_label("FX & Motion"), 8, 0, 1, 12)
        self._add_generator_slider_row(grid, 9, "Repeat dens.", self.generator_repeat_slider, self.generator_repeat_value, "Repeat len.", self.generator_repeat_length_slider, self.generator_repeat_length_value)
        self._add_generator_slider_row(grid, 10, "Repeat rate", self.generator_repeat_rate_slider, self.generator_repeat_rate_value, "Reverse", self.generator_reverse_slider, self.generator_reverse_value)
        self._add_generator_slider_row(grid, 11, "K.Roll dens.", self.generator_kick_roll_slider, self.generator_kick_roll_value, "K.Roll len.", self.generator_kick_roll_length_slider, self.generator_kick_roll_length_value)
        kick_roll_dyn_label = QLabel("K.Roll dyn.")
        kick_roll_dyn_tooltip = self._generator_parameter_tooltip("K.Roll dyn.")
        self._set_generator_widget_tooltip(
            kick_roll_dyn_tooltip,
            kick_roll_dyn_label,
            self.generator_kick_roll_contrast_slider,
            self.generator_kick_roll_contrast_value,
        )
        grid.addWidget(kick_roll_dyn_label, 12, 0)
        grid.addWidget(self.generator_kick_roll_contrast_slider, 12, 1, 1, 2)
        grid.addWidget(self._build_generator_section_label("Playback & Feel"), 13, 0, 1, 12)
        self._add_generator_slider_row(grid, 14, "Gate", self.generator_gate_slider, self.generator_gate_value, "Velocity", self.generator_velocity_slider, self.generator_velocity_value)
        self._add_generator_slider_row(grid, 15, "Swing", self.generator_swing_slider, self.generator_swing_value, "Breath", self.generator_breath_slider, self.generator_breath_value)

        sequence_max_label = QLabel("Seq max len")
        sequence_lock_label = QLabel("Seq role lock")
        self._set_generator_widget_tooltip(
            "Longueur max en nombre de hits d'une sequence candidate injectee en bloc.",
            sequence_max_label,
            self.generator_sequence_max_len_spin,
        )
        self._set_generator_widget_tooltip(
            "Si actif, chaque role de sequence reste dans sa zone naturelle: fills en fin de mesure, groove au milieu, etc.",
            sequence_lock_label,
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
        grid.addWidget(sequence_max_label, 16, 0)
        grid.addWidget(self.generator_sequence_max_len_spin, 16, 1)
        grid.addWidget(sequence_lock_label, 16, 3)
        grid.addWidget(self.generator_sequence_role_lock_check, 16, 4, 1, 2)
        grid.addWidget(self.generator_clear_anchors_button, 16, 7, 1, 2)
        grid.addWidget(self.generator_clear_locks_button, 16, 9, 1, 2)

        grid.addWidget(self.generator_probability_label, 17, 0, 1, 12)
        grid.addWidget(self.generator_probability_table, 18, 0, 1, 12)
        grid.addWidget(self.generator_effect_probability_label, 19, 0, 1, 12)
        grid.addWidget(self.generator_effect_probability_table, 20, 0, 1, 12)
        grid.addWidget(self.generator_loading_bar, 21, 0, 1, 12)
        grid.addWidget(self.generator_info_label, 22, 0, 1, 12)
        grid.addWidget(self.generator_sequence_table, 23, 0, 1, 12)
        grid.addWidget(self.generator_summary_label, 24, 0, 1, 12)
        grid.addWidget(self.generator_table, 25, 0, 1, 12)

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
            "Ligne d'ancrage rythmique + locks. Clique la ligne Anchor pour figer un type, la ligne Lock pour conserver le step, et le numero en haut pour ecouter la slice source de ce step. La ligne FX montre explicitement les repeats, reverse et kick rolls sur la timeline.",
            self.generator_sequence_table,
        )
        self._set_generator_widget_tooltip(
            "Apercu live des probabilites de placement du squelette. Ce sont les poids de base avant les ajustements de contexte, fills et sequences.",
            self.generator_probability_table,
            self.generator_probability_label,
        )
        self._set_generator_widget_tooltip(
            "Apercu heuristique des effets du generateur. Repeat montre ou des retriggers glitch ont le plus de chances d'apparaitre; Reverse montre ou une queue reverse a le plus de chances d'etre injectee; K.Roll montre ou une rafale de kicks a le plus de chances de demarrer puis de s'etaler sur la fenetre rythmique suivante.",
            self.generator_effect_probability_table,
            self.generator_effect_probability_label,
        )
        self._set_generator_widget_tooltip(
            "Seed de la derniere variation generee. Elle est informativa seulement: chaque clic sur Generate random en cree une nouvelle.",
            self.generator_seed_value,
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

    @staticmethod
    def _generator_parameter_tooltip(name: str) -> str:
        tooltips = {
            "Energy": "Macro globale. Monte la densite generale, ouvre un peu plus de hats/ghosts et rend les accents plus vivants.",
            "Kick": "Controle les kicks automatiques du squelette. A 0, le generateur n'en place pratiquement plus tout seul; une ancre peut toujours en forcer un.",
            "Snare": "Controle les snares/claps automatiques du squelette. A 0, les backbeats ne sont plus pousses automatiquement.",
            "Hat": "Controle le remplissage automatique des subdivisions par des hats. A 0, les steps intermediaires restent beaucoup plus vides.",
            "Ghost": "Controle les ghosts automatiques. A 0, ils disparaissent presque completement du squelette.",
            "Fill": "Genere davantage de fins de mesure en bloc: lift sur la fin du bar, drive juste avant le retour, puis release/resolution plus propre vers le 1 suivant.",
            "Sequences": "Dose l'utilisation de suites de hits extraites du break source. A 0%, le comportement reste purement atomique.",
            "Repeat": "Ajoute des retriggers rapides du meme hit a l'interieur d'un step, facon glitch. Plus haut = davantage de zones de repeat dans le pattern.",
            "Repeat dens.": "Controle combien de zones de repeat apparaissent dans le pattern. Plus haut = plus de zones glitch.",
            "Repeat len.": "Controle la longueur probable des zones de repeat sur la timeline. Bas = zones courtes, haut = zones plus longues sur plusieurs steps.",
            "Repeat rate": "Controle la vitesse probable des retriggers dans une zone de repeat. Bas = plutot x2, haut = plutot x4.",
            "Reverse": "Injecte des queues reverse apres certains kicks, snares ou claps. L'effet tombe surtout sur les subdivisions entre reperes rythmiques et reutilise la slice du hit juste avant.",
            "K.Roll dens.": "Controle la frequence des kick rolls. Ils demarrent directement sur les beats pairs du bar, puis etalent une petite rafale de kicks sur les steps suivants.",
            "K.Roll len.": "Controle la longueur probable des kick rolls. La V1 reste sur des longueurs paires et courtes, calees sur les fenetres 5-8 et 13-16.",
            "K.Roll dyn.": "Controle le niveau de velocite uniforme de toute la succession du roll, y compris le premier kick de depart.",
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

    def _build_generator_section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
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
        self.candidates_box.setMinimumHeight(200)
        self.json_box.setMinimumHeight(200)

        self.results_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.results_splitter.setChildrenCollapsible(False)
        self.results_splitter.setHandleWidth(8)
        self.results_splitter.addWidget(self.result_box)
        self.results_splitter.addWidget(self.candidates_box)
        self.results_splitter.addWidget(self.json_box)
        self.results_splitter.setStretchFactor(0, 3)
        self.results_splitter.setStretchFactor(1, 5)
        self.results_splitter.setStretchFactor(2, 4)
        results_panel_layout.addWidget(self.results_splitter)
        root.addWidget(self.results_panel)

    def _init_waveform_panel(self) -> None:
        try:
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
            self.waveform_status_label.setText(
                "Waveform editor SampleRod charge. Utilise ses controles pour ecouter le sample, "
                "selectionner une region pour la couper, rajouter des markers avec le bouton marker, "
                "cliquer un transient pour naviguer et lire directement, "
                "ou clic droit sur la waveform pour un split equilibre."
            )
        except Exception as exc:
            self._waveform_error = str(exc)
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
            QPushButton#LockButton { padding: 0; min-height: 32px; max-height: 32px; border-radius: 11px; background: #12171e; border: 1px solid #2f3948; }
            QPushButton#LockButton:hover { background: #18202a; border-color: #4e617a; }
            QPushButton#LockButton[generatorStepRole="beat"] { background: #18272e; border-color: #314c58; }
            QPushButton#LockButton[generatorStepRole="bar_start"] { background: #2a2114; border-color: #6a562b; }
            QPushButton#LockButton[lockActive="true"] { background: #2c241f; border-color: #d1a142; }
            QPushButton#LockButton[lockActive="true"][generatorStepRole="beat"] { background: #243239; }
            QPushButton#LockButton[lockActive="true"][generatorStepRole="bar_start"] { background: #3d311c; }
            QRadioButton#HitLabelRadio { spacing: 3px; padding: 0 2px; color: #9ba6ba; font-size: 10px; }
            QRadioButton#HitLabelRadio:checked { color: #eef1f6; font-weight: 700; }
            QRadioButton#HitLabelRadio::indicator { width: 11px; height: 11px; border-radius: 6px; border: 1px solid #54627a; background: #11151c; }
            QRadioButton#HitLabelRadio::indicator:hover { border-color: #7e90ad; }
            QRadioButton#HitLabelRadio::indicator:checked { border-color: #4bb6b7; background: #4bb6b7; }
            QRadioButton#HitLabelRadio::indicator:disabled { border-color: #36404f; background: #11151c; }
            QPushButton#PrimaryButton { background: #d1a142; color: #171a20; border-color: #d1a142; border-radius: 16px; font-weight: 700; }
            QPushButton#PrimaryButton:hover { background: #ddb257; border-color: #ddb257; }
            QPushButton#ToggleButton:checked { background: #4bb6b7; color: #101318; border-color: #4bb6b7; font-weight: 700; }
            QProgressBar { background: #101318; border: 1px solid #303644; border-radius: 10px; text-align: center; min-height: 18px; }
            QProgressBar::chunk { border-radius: 9px; background: #4bb6b7; }
            QProgressBar#LoadingBar { background: rgba(75, 182, 183, 0.08); border: 1px solid rgba(75, 182, 183, 0.18); border-radius: 3px; min-height: 6px; max-height: 6px; }
            QProgressBar#LoadingBar::chunk { border-radius: 3px; background: #4bb6b7; }
            QLabel#TitleLabel { font-weight: 700; }
            QLabel#ResultLabel { font-weight: 700; color: #f0c05a; }
            QLabel#StatusLabel { color: #9ba6ba; }
            QLabel#SectionLabel { color: #d7dfeb; font-weight: 700; letter-spacing: 0.06em; padding-top: 6px; }
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
        self._update_retimed_preview_state(None)
        self._populate_generated_pattern(None)
        self._refresh_generator_probability_preview()
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
            if label == hit.label:
                updated_hits.append(hit)
                continue
            updated_hits.append(
                replace(
                    hit,
                    label=label,
                    secondary_labels=(),
                    layer_score=0.0,
                    role=self._hit_role_for_label(label),
                )
            )

        return replace(result, transient_hits=tuple(updated_hits))

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
            return "mode retime"
        suffix = f"mode quantize {format_quantize_grid_label(self._quantize_grid_division())}"
        if include_strength:
            suffix += f" a {self._quantize_strength() * 100:.0f}%"
        return suffix

    def _default_generator_info_text(self) -> str:
        return (
            f"Chaque clic sur Generate random cree un nouveau pattern {self._generator_pattern_shape_text()} "
            "a partir des slices detectees. La ligne Anchor permet de figer quelques temps forts, "
            "puis de generer autour. Gate raccourcit la lecture des slices, Repeat cree des zones glitch avec retriggers, "
            "Reverse injecte des queues reverse apres certains kicks ou snares sur les subdivisions, "
            "et K.Roll construit de petites rafales de kicks sur plusieurs steps avec une velocite uniforme. "
            "Le transport ci-dessous est propre au generateur, avec son BPM cible et sa boucle."
        )

    def _refresh_generator_probability_preview(self) -> None:
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

        self.generator_probability_table.setRowCount(len(rows))
        self.generator_probability_table.setColumnCount(len(families))
        self.generator_probability_table.setHorizontalHeaderLabels([family_labels[family] for family in families])
        self.generator_probability_table.setVerticalHeaderLabels([row_labels[row] for row in rows])

        if self._result is None or not self._result.transient_hits:
            for row_index, row_name in enumerate(rows):
                for column_index, family in enumerate(families):
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(
                        f"{row_labels[row_name]} | {family_labels[family]}\nCharge un break analyse pour voir l'aperçu."
                    )
                    self.generator_probability_table.setItem(row_index, column_index, item)
            return

        preview = estimate_pattern_family_probabilities(
            self._result.transient_hits,
            self._generator_params(seed=1),
        )
        for row_index, row_name in enumerate(rows):
            weights = preview.rows.get(row_name, {})
            for column_index, family in enumerate(families):
                probability = float(weights.get(family, 0.0))
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

    def _refresh_generator_probability_preview(self) -> None:
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
        effects = ("repeat", "reverse", "kick_roll")
        effect_labels = {
            "repeat": "Repeat",
            "reverse": "Reverse",
            "kick_roll": "K.Roll",
        }

        self.generator_probability_table.setRowCount(len(rows))
        self.generator_probability_table.setColumnCount(len(families))
        self.generator_probability_table.setHorizontalHeaderLabels([family_labels[family] for family in families])
        self.generator_probability_table.setVerticalHeaderLabels([row_labels[row] for row in rows])
        self.generator_effect_probability_table.setRowCount(len(rows))
        self.generator_effect_probability_table.setColumnCount(len(effects))
        self.generator_effect_probability_table.setHorizontalHeaderLabels([effect_labels[effect] for effect in effects])
        self.generator_effect_probability_table.setVerticalHeaderLabels([row_labels[row] for row in rows])

        if self._result is None or not self._result.transient_hits:
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
        family_preview = estimate_pattern_family_probabilities(self._result.transient_hits, params)
        effect_preview = estimate_pattern_effect_probabilities(self._result.transient_hits, params)

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
                else:
                    item.setToolTip(
                        f"{row_labels[row_name]} | Kick roll\n"
                        f"Probabilite heuristique: {probability * 100.0:.1f}%\n"
                        "Estime la chance de declencher une petite rafale de kicks sur plusieurs steps a partir d'un kick deja pose."
                    )
                    if probability >= 0.32:
                        item.setBackground(QColor("#5a3617"))
                    elif probability >= 0.14:
                        item.setBackground(QColor("#412a19"))
                if probability <= 0.03:
                    item.setForeground(QColor("#8690a2"))
                self.generator_effect_probability_table.setItem(row_index, column_index, item)

    def _generator_pattern_shape_text(self) -> str:
        bars = int(self.generator_bars_spin.value()) if hasattr(self, "generator_bars_spin") else 1
        step_count = max(16, bars * 16)
        return f"{bars} bar{'s' if bars > 1 else ''} / {step_count} steps"

    def _preview_loop_enabled(self, owner: str | None) -> bool:
        if owner == PREVIEW_OWNER_GENERATOR:
            return bool(self.generator_loop_button.isChecked())
        return bool(self.retime_loop_button.isChecked())

    def _preview_info_label(self, owner: str | None) -> QLabel:
        if owner == PREVIEW_OWNER_GENERATOR:
            return self.generator_info_label
        return self.retime_info_label

    def _preview_loading_bar(self, owner: str | None) -> QProgressBar:
        if owner == PREVIEW_OWNER_GENERATOR:
            return self.generator_loading_bar
        return self.retime_loading_bar

    def _preview_owner_is_active(self, owner: str) -> bool:
        return bool(self._retimed_preview_playing and self._preview_owner == owner)

    @staticmethod
    def _preview_mode_summary(preview: RetimedPreview) -> str:
        if preview.mode == PREVIEW_MODE_PATTERN:
            return "mode pattern generator"
        if preview.mode != PREVIEW_MODE_QUANTIZE:
            return "mode retime"
        return (
            f"mode quantize {format_quantize_grid_label(preview.quantize_grid_division)} "
            f"a {preview.quantize_strength * 100:.0f}%"
        )

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
        self._worker.progressed.connect(self._on_analysis_progress)
        self._worker.preview_ready.connect(self._on_analysis_preview)
        self._worker.succeeded.connect(self._on_analysis_success)
        self._worker.failed.connect(self._on_analysis_failure)
        self._worker.finished.connect(self._on_analysis_finished)
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
            self.waveform_loading_bar.setVisible(False)
            self._waveform_loading = False
            self._refresh_control_states(self.status_label.text())
            return

        self._loaded_audio_samples = None
        self._loaded_audio_sample_rate = None
        self._loaded_audio_path = None
        self._waveform_loading = True
        self._waveform_load_token += 1
        token = self._waveform_load_token
        self.waveform_loading_bar.setVisible(True)
        self.waveform_status_label.setText("Chargement waveform en cours...")
        self.hits_summary_label.setText("Chargement audio en cours pour preparer la waveform.")
        self._refresh_control_states(f"Chargement du sample {resolved.name}...")

        worker = TaskWorker(lambda: self._create_waveform_load_result(resolved), self)
        self._waveform_loader = worker
        worker.succeeded.connect(lambda result, current_token=token: self._on_waveform_loaded(result, current_token))
        worker.failed.connect(lambda message, current_token=token: self._on_waveform_load_failed(message, current_token))
        worker.finished.connect(lambda current_token=token: self._on_waveform_load_finished(current_token))
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
        self.generator_target_bpm_spin.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_bars_spin.setEnabled(
            (not global_busy) and (not self._waveform_loading) and (not self._generator_busy)
        )
        self.generator_loop_button.setEnabled(
            (not self._dependency_error) and (not global_busy) and (not self._waveform_loading)
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
            self.generator_gate_slider,
            self.generator_velocity_slider,
            self.generator_swing_slider,
            self.generator_anti_repeat_slider,
            self.generator_breath_slider,
            self.generator_position_fidelity_slider,
            self.generator_sequence_density_slider,
        ):
            control.setEnabled((not global_busy) and (not self._waveform_loading) and (not self._generator_busy))
        self._refresh_generated_pattern_state()
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

    def _on_waveform_load_failed(self, message: str, token: int) -> None:
        if token != self._waveform_load_token:
            return
        self._loaded_audio_samples = None
        self._loaded_audio_sample_rate = None
        self._loaded_audio_path = None
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
        self._populate_candidates(result)
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
        for row, hit in enumerate(hits):
            counts[hit.label] = counts.get(hit.label, 0) + 1
            values = (
                str(hit.index),
                f"{hit.start_s:.3f}s",
                f"{hit.end_s:.3f}s",
                f"{hit.confidence:.2f}",
                f"{hit.peak_db:.1f}",
            )
            picker = self._build_hit_label_picker(hit, row=row)
            self.hits_table.setCellWidget(row, 1, picker)
            for column, value in enumerate(values):
                table_column = column if column == 0 else column + 1
                item = QTableWidgetItem(value)
                if table_column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.hits_table.setItem(row, table_column, item)

        summary = ", ".join(
            f"{label}:{count}" for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        )
        self.hits_summary_label.setText(f"{len(hits)} transient(s) detecte(s). Repartition: {summary}")
        self.hits_table.resizeColumnsToContents()
        self.hits_table.resizeRowsToContents()
        self._ensure_table_column_widths(self.hits_table, {0: 56, 1: 420, 2: 100, 3: 100, 4: 80, 5: 80})
        self._set_hit_label_edit_enabled(
            (not self._analysis_busy)
            and (not self._rebuild_busy)
            and (not self._waveform_loading)
            and (not self._generator_busy)
            and (not self._preview_busy)
            and result is not None
        )
        self.rebuild_markers_button.setEnabled(self._marker_rebuild_available())

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
            widget = self.hits_table.cellWidget(row, 1)
            if widget is None:
                continue
            for radio in widget.findChildren(QRadioButton):
                radio.setEnabled(bool(enabled))

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
        self._result = updated_result
        self._generated_pattern = None
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
        worker.succeeded.connect(lambda rebuilt, marker_count=len(marker_times): self._on_rebuild_success(rebuilt, marker_count))
        worker.failed.connect(self._on_rebuild_failure)
        worker.finished.connect(self._on_rebuild_finished)
        worker.start()

    def _on_target_bpm_changed(self, _value: float) -> None:
        if self._preview_owner_is_active(PREVIEW_OWNER_RETIME):
            self._retime_live_changes_pending = True
            self._refresh_active_retime_preview_message()
        elif not self._retimed_preview_playing:
            self._update_retimed_preview_state(self._result)
        self._refresh_generated_pattern_state()

    def _on_generator_target_bpm_changed(self, value: float) -> None:
        self._settings.setValue("generator_target_bpm", float(value))
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._generator_live_changes_pending = True
            if self._queue_live_generator_preview_refresh():
                self.generator_info_label.setText(
                    "Lecture pattern en cours. Nouveau tempo en cours d'application sur la boucle active."
                )
        self._refresh_generated_pattern_state()

    def _on_generator_gate_changed(self, value: int) -> None:
        self._settings.setValue("generator_gate", int(value))
        if self._preview_owner_is_active(PREVIEW_OWNER_GENERATOR):
            self._generator_live_changes_pending = True
            if self._queue_live_generator_preview_refresh():
                self.generator_info_label.setText(
                    "Lecture pattern en cours. Nouveau gate en cours d'application sur la boucle active."
                )
        self._refresh_generated_pattern_state()

    def _on_generator_bars_changed(self, value: int) -> None:
        self._settings.setValue("generator_bars", int(value))
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
        )

    def _generator_params(self, *, seed: int) -> BreakPatternParams:
        return BreakPatternParams(
            energy=self.generator_energy_slider.value() / 100.0,
            kick_weight=self.generator_kick_slider.value() / 100.0,
            snare_weight=self.generator_snare_slider.value() / 100.0,
            hat_density=self.generator_hat_slider.value() / 100.0,
            ghost_density=self.generator_ghost_slider.value() / 100.0,
            fill_strength=self.generator_fill_slider.value() / 100.0,
            repeat_density=self.generator_repeat_slider.value() / 100.0,
            repeat_span=self.generator_repeat_length_slider.value() / 100.0,
            repeat_rate=self.generator_repeat_rate_slider.value() / 100.0,
            reverse_density=self.generator_reverse_slider.value() / 100.0,
            kick_roll_density=self.generator_kick_roll_slider.value() / 100.0,
            kick_roll_span=self.generator_kick_roll_length_slider.value() / 100.0,
            kick_roll_contrast=self.generator_kick_roll_contrast_slider.value() / 100.0,
            gate=max(0.05, self.generator_gate_slider.value() / 100.0),
            position_fidelity=self.generator_position_fidelity_slider.value() / 100.0,
            sequence_density=self.generator_sequence_density_slider.value() / 100.0,
            sequence_max_len=int(self.generator_sequence_max_len_spin.value()),
            sequence_role_lock=bool(self.generator_sequence_role_lock_check.isChecked()),
            velocity_spread=self.generator_velocity_slider.value() / 100.0,
            swing=self.generator_swing_slider.value() / 100.0,
            anti_repeat=self.generator_anti_repeat_slider.value() / 100.0,
            breath_factor=self.generator_breath_slider.value() / 100.0,
            seed=int(seed),
            bars=int(self.generator_bars_spin.value()),
        )

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
        self._refresh_generator_anchor_button(step_index)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
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
        self._refresh_generator_lock_button(step)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
        self.generator_info_label.setText(
            f"Lock step {step}: {state}. Le prochain Generate random {'gardera' if state == 'on' else 'pourra modifier'} ce step."
        )

    def _clear_generator_anchors(self) -> None:
        if not self._generator_step_anchors:
            return
        self._generator_step_anchors.clear()
        for step_index in range(1, self.generator_sequence_table.columnCount() + 1):
            self._refresh_generator_anchor_button(step_index)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
        self.generator_info_label.setText("Toutes les ancres ont ete retirees.")

    def _clear_generator_locks(self) -> None:
        if not self._generator_locked_steps:
            return
        self._generator_locked_steps.clear()
        for step_index in range(1, self.generator_sequence_table.columnCount() + 1):
            self._refresh_generator_lock_button(step_index)
        self._refresh_generator_anchor_summary()
        self._refresh_generated_pattern_state()
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

    @classmethod
    def _generator_step_fx_text(cls, step) -> str:
        repeat_meta = cls._generator_repeat_metadata(step)
        reverse_active = cls._generator_step_is_reverse(step)
        kick_roll_meta = cls._generator_kick_roll_metadata(step)
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
        return " | ".join(parts) if parts else "-"

    @classmethod
    def _generator_step_fx_tooltip(cls, step) -> str:
        repeat_meta = cls._generator_repeat_metadata(step)
        reverse_active = cls._generator_step_is_reverse(step)
        kick_roll_meta = cls._generator_kick_roll_metadata(step)
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

    @classmethod
    def _generator_sequence_header_text(cls, step_index: int, step=None) -> str:
        base_text = str(int(step_index))
        if step is None:
            return base_text
        repeat_meta = cls._generator_repeat_metadata(step)
        kick_roll_meta = cls._generator_kick_roll_metadata(step)
        if not repeat_meta["zone"] and not kick_roll_meta["zone"]:
            return base_text
        if kick_roll_meta["zone"]:
            if kick_roll_meta["start"] and kick_roll_meta["end"]:
                return f"{{{base_text}}}"
            if kick_roll_meta["start"]:
                return f"{{{base_text}"
            if kick_roll_meta["end"]:
                return f"{base_text}}}"
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
        repeat_meta = {"repeat": False, "zone": False, "start": False, "end": False, "count": 1, "span": 1}
        kick_roll_meta = {"active": False, "zone": False, "start": False, "end": False, "high": False, "low": False, "span": 1}
        pattern_step = None
        if self._generated_pattern is not None and column < len(self._generated_pattern.steps):
            pattern_step = self._generated_pattern.steps[column]
            repeat_meta = self._generator_repeat_metadata(pattern_step)
            kick_roll_meta = self._generator_kick_roll_metadata(pattern_step)
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
        header_item = self.generator_sequence_table.horizontalHeaderItem(column)
        if header_item is not None:
            header_item.setText(self._generator_sequence_header_text(step_index, pattern_step))
            header_item.setBackground(background)
            header_item.setForeground(foreground)
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
            header_item.setToolTip(f"Step {step_index} | {role_label}{repeat_hint}{reverse_hint}{kick_roll_hint}")

        for row in range(2, min(6, self.generator_sequence_table.rowCount())):
            item = self.generator_sequence_table.item(row, column)
            if item is None:
                continue
            item.setBackground(background)
            item.setForeground(foreground)
            if row == 5:
                if pattern_step is not None and self._generator_step_is_reverse(pattern_step):
                    item.setBackground(self._blend_generator_colors(background, QColor("#6a2947"), 0.58))
                    item.setForeground(QColor("#ffe7ef"))
                elif kick_roll_meta["zone"] or kick_roll_meta["active"]:
                    item.setBackground(self._blend_generator_colors(background, QColor("#6e4525"), 0.52))
                    item.setForeground(QColor("#fff0dc"))
                elif repeat_meta["zone"] or repeat_meta["repeat"]:
                    item.setBackground(self._blend_generator_colors(background, QColor("#275241"), 0.5))
                    item.setForeground(QColor("#e3fff2"))

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

    def _generate_break_pattern(self) -> None:
        if self._result is None:
            QMessageBox.warning(self, "Analyse requise", "Analyse d'abord un break pour generer un pattern.")
            return
        if not self._result.transient_hits:
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
        params = self._generator_params(seed=seed)
        current_pattern = self._generated_pattern
        self._generator_busy = True
        self.generator_loading_bar.setVisible(True)
        self.generator_info_label.setText("Generation du pattern en cours...")
        self._refresh_control_states("Generation du pattern a partir du break courant...")
        worker = TaskWorker(
            lambda: generate_break_pattern(
                self._result.transient_hits,
                params,
                sequences=self._result.hit_sequences,
                anchors=self._generator_active_step_anchors(step_count=max(16, int(params.bars) * 16)),
            ),
            self,
        )
        self._generator_worker = worker
        worker.succeeded.connect(
            lambda pattern, previous=current_pattern: self._on_pattern_generated(
                self._merge_locked_generated_steps(pattern, previous)
            )
        )
        worker.failed.connect(self._on_pattern_generation_failed)
        worker.finished.connect(self._on_pattern_generation_finished)
        worker.start()

    def _reroll_generated_step(self, step_index: int) -> None:
        if self._result is None or self._generated_pattern is None:
            return
        if self._analysis_stale:
            QMessageBox.information(
                self,
                "Recalcul requis",
                "La waveform a ete modifiee. Relance d'abord un rebuild ou une analyse avant de reroll un step.",
            )
            return

        seed = int(secrets.randbelow(999_999_999) + 1)
        self._generator_busy = True
        self.generator_loading_bar.setVisible(True)
        self.generator_info_label.setText(f"Reroll du step {step_index} en cours...")
        self._refresh_control_states(f"Regeneration du step {step_index}...")
        current_pattern = self._generated_pattern
        worker = TaskWorker(
            lambda: reroll_break_pattern_step(
                self._result.transient_hits,
                current_pattern,
                int(step_index),
                seed=seed,
                sequences=self._result.hit_sequences,
                anchors=self._generator_active_step_anchors(step_count=current_pattern.step_count),
            ),
            self,
        )
        self._generator_worker = worker
        worker.succeeded.connect(
            lambda pattern, previous=current_pattern, ignored_step=int(step_index): self._on_pattern_generated(
                self._merge_locked_generated_steps(pattern, previous, ignore_step=ignored_step)
            )
        )
        worker.failed.connect(self._on_pattern_generation_failed)
        worker.finished.connect(self._on_pattern_generation_finished)
        worker.start()

    def _play_generated_pattern(self) -> None:
        if not self._generated_pattern_available():
            self._refresh_generated_pattern_state()
            return

        audio_snapshot = self._analysis_audio_snapshot()
        if audio_snapshot is None:
            QMessageBox.warning(self, "Audio indisponible", "Recharge d'abord la waveform avant de jouer le pattern.")
            return

        self._start_preview_build(
            lambda: build_pattern_preview(
                audio_snapshot[0],
                int(audio_snapshot[1]),
                self._generated_pattern,
                target_bpm=float(self.generator_target_bpm_spin.value()),
                gate=max(0.05, self.generator_gate_slider.value() / 100.0),
            ),
            owner=PREVIEW_OWNER_GENERATOR,
            info_text="Preparation de la lecture du pattern genere...",
            status_text="Preparation du playback pattern...",
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

        self._start_preview_build(
            lambda: build_pattern_preview(
                audio_snapshot[0],
                int(audio_snapshot[1]),
                self._generated_pattern,
                target_bpm=float(self.generator_target_bpm_spin.value()),
                gate=max(0.05, self.generator_gate_slider.value() / 100.0),
            ),
            owner=PREVIEW_OWNER_GENERATOR,
            info_text="Mise a jour live du pattern en cours...",
            status_text=self.status_label.text(),
        )
        return True

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

    def _estimate_retimed_preview_duration(self, result: DrumDetectionResult, target_bpm: float) -> float:
        source_bpm = self._effective_detected_bpm(result)
        return estimate_retimed_preview_duration(
            result.transient_hits,
            source_bpm=source_bpm,
            target_bpm=target_bpm,
            mode=self._preview_mode(),
            quantize_grid_division=self._quantize_grid_division(),
            quantize_strength=self._quantize_strength(),
        )

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

        self._retime_stream = sounddevice.OutputStream(
            samplerate=preview.sample_rate,
            channels=int(audio.shape[1]),
            dtype="float32",
            blocksize=0,
            latency="high",
            callback=callback,
        )
        self._retime_stream.start()
        self._retimed_preview = preview
        self._retimed_preview_playing = True
        self._preview_owner = owner
        if owner == PREVIEW_OWNER_GENERATOR:
            self._generator_live_changes_pending = False
        else:
            self._retime_live_changes_pending = False
        self._retime_visual_started_at = time.perf_counter()
        self._retime_visual_segment_index = -1
        self.retime_play_button.setEnabled(True)
        self.retime_stop_button.setEnabled(owner == PREVIEW_OWNER_RETIME)
        self.generator_stop_button.setEnabled(owner == PREVIEW_OWNER_GENERATOR)
        self._retime_stop_timer.stop()
        self._retime_visual_timer.start()
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
        else:
            self._refresh_active_retime_preview_message()

    def _stop_retimed_preview(self, *_args, update_status: bool = True) -> None:
        owner = self._preview_owner
        self._retime_stop_timer.stop()
        self._retime_visual_timer.stop()
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
        self.retime_stop_button.setEnabled(False)
        self.generator_stop_button.setEnabled(False)
        if owner == PREVIEW_OWNER_GENERATOR:
            self._refresh_generated_pattern_state()
        else:
            self._retime_live_changes_pending = False
            self._update_retimed_preview_state(self._result)
        if update_status:
            self._refresh_control_states(self.status_label.text())

    def _on_retimed_preview_finished(self) -> None:
        preview = self._retimed_preview
        owner = self._preview_owner
        self._retimed_preview_playing = False
        self._retime_visual_timer.stop()
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
        self.retime_stop_button.setEnabled(False)
        self.generator_stop_button.setEnabled(False)
        if preview is not None and owner == PREVIEW_OWNER_GENERATOR:
            self.generator_info_label.setText(
                f"Lecture pattern terminee. {preview.segment_count} evenement(s), "
                f"{preview.target_bpm:.1f} BPM."
            )
            self._refresh_generated_pattern_state()
        else:
            self._retime_live_changes_pending = False
            self._update_retimed_preview_state(self._result)

    def _stop_retimed_preview_for_waveform(self, *_args) -> None:
        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=True)

    def _start_preview_build(
        self,
        task: Callable[[], RetimedPreview],
        *,
        owner: str,
        info_text: str,
        status_text: str,
    ) -> None:
        if self._preview_busy:
            return
        self._preview_busy = True
        self._preview_loading_bar(owner).setVisible(True)
        self._refresh_control_states(status_text)
        self._preview_info_label(owner).setText(info_text)
        worker = TaskWorker(task, self)
        self._preview_worker = worker
        worker.succeeded.connect(lambda preview, preview_owner=owner: self._on_preview_build_success(preview_owner, preview))
        worker.failed.connect(lambda message, preview_owner=owner: self._on_preview_build_failure(preview_owner, message))
        worker.finished.connect(lambda preview_owner=owner: self._on_preview_build_finished(preview_owner))
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
            or self._waveform_widget is None
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

        elapsed_s = self._elapsed_preview_seconds()
        segment_index, source_position = self._locate_retimed_preview_source_position(elapsed_s)
        if segment_index is None:
            return

        if segment_index != self._retime_visual_segment_index:
            self._retime_visual_segment_index = segment_index
            self._select_retimed_preview_row(segment_index)

        if source_position is None:
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

    @staticmethod
    def _pattern_preview_step_duration_seconds(preview: RetimedPreview) -> float:
        return (60.0 / max(float(preview.target_bpm), 1e-6)) / 4.0

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

    def _sync_audio_state_from_waveform(self) -> bool:
        waveform_audio = self._waveform_audio_reference()
        if waveform_audio is None:
            return False
        audio, sample_rate = waveform_audio
        self._loaded_audio_samples = np.array(audio, dtype=np.float32, copy=True)
        self._loaded_audio_sample_rate = int(sample_rate)
        self._loaded_audio_path = self._current_resolved_path()
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

    def _on_pattern_generation_finished(self) -> None:
        self._generator_busy = False
        self.generator_loading_bar.setVisible(False)
        self._generator_worker = None
        self._refresh_control_states(self.status_label.text())
        self._maybe_close_after_background_tasks()

    def _running_workers(self) -> list[QThread]:
        return [
            worker
            for worker in (
                self._worker,
                self._waveform_loader,
                self._rebuild_worker,
                self._generator_worker,
                self._preview_worker,
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
