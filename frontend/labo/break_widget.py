from __future__ import annotations

import os
import tempfile
import uuid

import pyqtgraph as pg
import soundfile as sf
from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from backend.services.drum_analysis_service import (
    DEFAULT_QUANTIZE_GRID_DIVISION,
    DEFAULT_QUANTIZE_STRENGTH,
    DEFAULT_SPLIT_DENSITY,
    DrumAnalysisResult,
    DrumQuantizedPreview,
    DrumSlice,
    drum_analysis_availability_error,
)
from frontend.sample_gui.wave_form import WaveformWidget
from frontend.sample_gui.waveform.waveform_plot_helpers import ContextMenuLinearRegionItem
from frontend.styles import theme

from .lab_artifact import LabArtifact
from .waveform_tool_dnd import has_supported_waveform_drop, resolve_waveform_drop_paths

# --------------------------------------------------------------------------- #
# Hit label constants
# --------------------------------------------------------------------------- #
MANUAL_HIT_LABEL_OPTIONS: tuple[str, ...] = (
    "kick", "kick_ghost", "snare", "snare_ghost",
    "snare_ruff", "clap", "closed_hat", "open_hat",
    "crash", "ride", "tom", "perc",
)
HIT_LABEL_SHORT: dict[str, str] = {
    "kick": "K",  "kick_ghost": "Kg", "snare": "S",  "snare_ghost": "Sg",
    "snare_ruff": "Rf", "clap": "C",  "closed_hat": "HC", "open_hat": "HO",
    "crash": "Cr", "ride": "Rd", "tom": "T",  "perc": "P",
}
HIT_LABEL_COLOR: dict[str, str] = {
    "kick": "#e05c5c",     "kick_ghost": "#c47878",
    "snare": "#e0a040",    "snare_ghost": "#c49060",  "snare_ruff": "#c4a070",
    "clap": "#d4b040",
    "closed_hat": "#4bb6b7", "open_hat": "#2ec4c5",
    "crash": "#9b6ee0",    "ride": "#7a5cb8",
    "tom": "#5ca0e0",      "perc": "#7abce0",
}


# --------------------------------------------------------------------------- #
# Single-line hit row — clickable, draggable, compact radio buttons
# --------------------------------------------------------------------------- #
class _HitRow(QFrame):
    selected        = Signal(int)       # hit_index
    removeRequested = Signal(int)       # hit_index — double-click
    labelChanged    = Signal(int, str)  # hit_index, new_label
    dragStarted     = Signal()
    dragFinished    = Signal()

    def __init__(self, drum_slice: DrumSlice, source_path: str, parent=None):
        super().__init__(parent)
        self.drum_slice = drum_slice
        self._source_path = source_path
        self._drag_start_pos = None
        self._current_label = drum_slice.label
        self._build_ui()

    # ------------------------------------------------------------------ #
    # Layout: one compact horizontal line
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        self.setObjectName("BreakHitRow")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(8)

        # Drag grip hint
        grip = QLabel("⠿")
        grip.setObjectName("BreakHitGrip")
        grip.setFixedWidth(12)

        # Index
        idx = QLabel(f"{self.drum_slice.index:02d}")
        idx.setObjectName("BreakHitIndex")
        idx.setFixedWidth(22)
        idx.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Label badge (updates when radio changes)
        color = HIT_LABEL_COLOR.get(self._current_label, "#7abce0")
        self.badge = QLabel(self._current_label.replace("_", " "))
        self.badge.setObjectName("BreakHitBadge")
        self.badge.setFixedWidth(76)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_badge_color(color)

        # Time range
        dur = self.drum_slice.end_s - self.drum_slice.start_s
        time_lbl = QLabel(
            f"{self.drum_slice.start_s:.3f}s→{self.drum_slice.end_s:.3f}s"
            f"  <span style='color:#666'>{dur*1000:.0f}ms</span>"
        )
        time_lbl.setObjectName("BreakHitTime")
        time_lbl.setTextFormat(Qt.TextFormat.RichText)
        time_lbl.setFixedWidth(140)

        # Confidence
        conf_lbl = QLabel(f"{self.drum_slice.confidence:.2f}")
        conf_lbl.setObjectName("BreakHitConf")
        conf_lbl.setFixedWidth(34)
        conf_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Compact radio buttons — 12 labels in one horizontal strip
        radio_widget = QWidget()
        radio_widget.setObjectName("BreakHitRadios")
        radio_row = QHBoxLayout(radio_widget)
        radio_row.setContentsMargins(0, 0, 0, 0)
        radio_row.setSpacing(1)

        self._radio_group = QButtonGroup(self)
        for label in MANUAL_HIT_LABEL_OPTIONS:
            short = HIT_LABEL_SHORT.get(label, label[:2])
            rb = QRadioButton(short)
            rb.setObjectName("BreakHitRadio")
            rb.setChecked(label == self._current_label)
            rb.setToolTip(label.replace("_", " "))
            # Stop click from bubbling up to the row's selection logic
            rb.clicked.connect(lambda checked, lbl=label: self._on_radio(lbl))
            self._radio_group.addButton(rb)
            radio_row.addWidget(rb)

        row.addWidget(grip)
        row.addWidget(idx)
        row.addWidget(self.badge)
        row.addWidget(time_lbl)
        row.addWidget(conf_lbl)
        row.addStretch(1)
        row.addWidget(radio_widget)

    def _set_badge_color(self, color: str) -> None:
        self.badge.setStyleSheet(
            f"background: {color}22; color: {color}; border: 1px solid {color}55;"
            f"border-radius: 8px; padding: 2px 6px; font-size: 10px; font-weight: 700;"
        )

    # ------------------------------------------------------------------ #
    # Radio logic
    # ------------------------------------------------------------------ #
    def _on_radio(self, new_label: str) -> None:
        self._current_label = new_label
        color = HIT_LABEL_COLOR.get(new_label, "#7abce0")
        self.badge.setText(new_label.replace("_", " "))
        self._set_badge_color(color)
        self.labelChanged.emit(self.drum_slice.index, new_label)

    def get_label(self) -> str:
        return self._current_label

    # ------------------------------------------------------------------ #
    # Mouse: click to select, drag to extract
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_start_pos is not None:
                dist = (event.pos() - self._drag_start_pos).manhattanLength()
                if dist < QApplication.startDragDistance():
                    self.selected.emit(self.drum_slice.index)
            self._drag_start_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start_pos is not None:
            dist = (event.pos() - self._drag_start_pos).manhattanLength()
            if dist > QApplication.startDragDistance():
                self._drag_start_pos = None
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None  # cancel any pending drag
            self.removeRequested.emit(self.drum_slice.index)
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------ #
    # Drag: extract slice → temp WAV → QDrag with URL
    # ------------------------------------------------------------------ #
    def _start_drag(self) -> None:
        if not self._source_path or not os.path.isfile(self._source_path):
            return
        try:
            audio, sr = sf.read(self._source_path, dtype="float32", always_2d=False)
            s0 = int(self.drum_slice.start_s * sr)
            s1 = int(self.drum_slice.end_s * sr)
            segment = audio[s0:s1]
            if segment.size == 0:
                return
            source_name = os.path.splitext(os.path.basename(self._source_path))[0]
            label_slug = self._current_label
            fname = f"{label_slug}__{source_name}__{self.drum_slice.index:02d}.wav"
            fname = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in fname)
            temp_path = os.path.join(tempfile.gettempdir(), fname)
            sf.write(temp_path, segment, int(sr))
        except Exception:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(temp_path)])
        drag = QDrag(self)
        drag.setMimeData(mime)
        self.dragStarted.emit()
        drag.exec(Qt.DropAction.CopyAction)
        self.dragFinished.emit()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ------------------------------------------------------------------ #
    # Selection highlight
    # ------------------------------------------------------------------ #
    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


# --------------------------------------------------------------------------- #
# Main widget
# --------------------------------------------------------------------------- #
class BreakWidget(QWidget):
    """Standalone break analysis tab: drop → decoupage → analyse → hits + quantize."""

    artifactCreated = Signal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._break_service = app_context.drum_analysis
        self._current_path: str | None = None
        self._waveform_widget: WaveformWidget | None = None
        self._drop_active = False
        self._analysis_result: DrumAnalysisResult | None = None
        self._hit_rows: list[_HitRow] = []
        self._selected_hit_index: int | None = None
        self._quantized_slices: tuple[DrumSlice, ...] = ()
        self._internal_drag_active = False
        self._build_ui()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    # ---------------------------------------------------------------------- #
    # UI construction
    # ---------------------------------------------------------------------- #
    def _build_ui(self) -> None:
        self.setObjectName("BreakRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Top pane: header + waveform ----
        top_pane = QWidget()
        top_layout = QVBoxLayout(top_pane)
        top_layout.setContentsMargins(0, 8, 0, 8)
        top_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        self.title_label = QLabel("Break")
        self.title_label.setObjectName("BreakTitle")

        self.file_label = QLabel("Aucun fichier charge")
        self.file_label.setObjectName("BreakFileLabel")
        self.file_label.setWordWrap(True)

        title_col.addWidget(self.title_label)
        title_col.addWidget(self.file_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.split_button = QPushButton("Decoupage automatique")
        self.split_button.setObjectName("BreakAction")
        self.split_button.setToolTip("Detecte les transients et place les marqueurs.")
        self.split_button.clicked.connect(self._run_auto_split)

        self.analyze_button = QPushButton("Analyser les slices")
        self.analyze_button.setObjectName("BreakAction")
        self.analyze_button.setToolTip("Classifie chaque hit selon les marqueurs actuels.")
        self.analyze_button.clicked.connect(self._run_slice_analysis)

        btn_row.addWidget(self.split_button)
        btn_row.addWidget(self.analyze_button)

        header.addLayout(title_col, 1)
        header.addLayout(btn_row, 0)

        self.status_label = QLabel("Depose un break dans la zone waveform pour commencer.")
        self.status_label.setObjectName("BreakStatus")
        self.status_label.setWordWrap(True)

        self.waveform_host = QWidget()
        self.waveform_host.setObjectName("BreakWaveformHost")
        self.waveform_host.setAcceptDrops(True)
        self.waveform_host.installEventFilter(self)
        self.waveform_layout = QVBoxLayout(self.waveform_host)
        self.waveform_layout.setContentsMargins(0, 0, 0, 0)
        self.waveform_layout.setSpacing(0)
        self.waveform_host.setMinimumHeight(150)

        top_layout.addLayout(header)
        top_layout.addWidget(self.status_label)
        top_layout.addWidget(self.waveform_host, 1)

        # ---- Bottom pane: hits list + quantize ----
        bottom_pane = QWidget()
        bottom_layout = QVBoxLayout(bottom_pane)
        bottom_layout.setContentsMargins(0, 0, 0, 8)
        bottom_layout.setSpacing(4)

        self.hits_scroll = QScrollArea()
        self.hits_scroll.setObjectName("BreakHitsScroll")
        self.hits_scroll.setWidgetResizable(True)
        self.hits_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.hits_container = QWidget()
        self.hits_container.setObjectName("BreakHitsContainer")
        self.hits_vbox = QVBoxLayout(self.hits_container)
        self.hits_vbox.setContentsMargins(4, 4, 4, 4)
        self.hits_vbox.setSpacing(2)
        self.hits_vbox.addStretch(1)

        self.hits_scroll.setWidget(self.hits_container)

        # Quantize bar
        quant_frame = QFrame()
        quant_frame.setObjectName("BreakQuantFrame")
        quant_frame.setFrameShape(QFrame.Shape.NoFrame)
        quant_layout = QHBoxLayout(quant_frame)
        quant_layout.setContentsMargins(8, 6, 8, 6)
        quant_layout.setSpacing(10)

        self.bpm_label = QLabel("BPM cible")
        self.bpm_label.setObjectName("BreakFieldLabel")

        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setObjectName("BreakSpin")
        self.bpm_spin.setRange(40.0, 220.0)
        self.bpm_spin.setDecimals(1)
        self.bpm_spin.setSingleStep(1.0)
        self.bpm_spin.setValue(120.0)
        self.bpm_spin.valueChanged.connect(self._refresh_quantized_projection)

        self.grid_label = QLabel("Grille")
        self.grid_label.setObjectName("BreakFieldLabel")

        self.grid_combo = QComboBox()
        self.grid_combo.setObjectName("BreakCombo")
        self.grid_combo.addItem("1/8", 8)
        self.grid_combo.addItem("1/16", 16)
        self.grid_combo.addItem("1/32", 32)
        idx = self.grid_combo.findData(DEFAULT_QUANTIZE_GRID_DIVISION)
        if idx >= 0:
            self.grid_combo.setCurrentIndex(idx)
        self.grid_combo.currentIndexChanged.connect(self._refresh_quantized_projection)

        self.strength_label = QLabel("Force")
        self.strength_label.setObjectName("BreakFieldLabel")

        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setObjectName("BreakSlider")
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(int(round(DEFAULT_QUANTIZE_STRENGTH * 100)))
        self.strength_slider.setFixedWidth(110)
        self.strength_slider.valueChanged.connect(self._on_strength_changed)
        self.strength_slider.valueChanged.connect(self._refresh_quantized_projection)

        self.strength_value = QLabel(f"{int(round(DEFAULT_QUANTIZE_STRENGTH * 100))}%")
        self.strength_value.setObjectName("BreakFieldValue")

        self.quantize_button = QPushButton("Creer preview quantizee")
        self.quantize_button.setObjectName("BreakAction")
        self.quantize_button.clicked.connect(self._create_quantized_preview)

        quant_layout.addWidget(self.bpm_label)
        quant_layout.addWidget(self.bpm_spin)
        quant_layout.addWidget(self.grid_label)
        quant_layout.addWidget(self.grid_combo)
        quant_layout.addWidget(self.strength_label)
        quant_layout.addWidget(self.strength_slider)
        quant_layout.addWidget(self.strength_value)
        quant_layout.addStretch(1)
        quant_layout.addWidget(self.quantize_button)

        bottom_layout.addWidget(self.hits_scroll, 1)
        bottom_layout.addWidget(quant_frame)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("BreakSplitter")
        self.splitter.addWidget(top_pane)
        self.splitter.addWidget(bottom_pane)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([300, 260])
        self.splitter.setChildrenCollapsible(False)

        root.addWidget(self.splitter, 1)

        self._apply_styles()
        self._refresh_actions()

    def _bind_signals(self) -> None:
        svc = self._break_service
        svc.analysisStarted.connect(self._on_analysis_started)
        svc.analysisFinished.connect(self._on_analysis_finished)
        svc.analysisFailed.connect(self._on_analysis_failed)
        svc.quantizeStarted.connect(self._on_quantize_started)
        svc.quantizeFinished.connect(self._on_quantize_finished)
        svc.quantizeFailed.connect(self._on_quantize_failed)

    # ---------------------------------------------------------------------- #
    # File loading
    # ---------------------------------------------------------------------- #
    def open_file(self, path: str) -> bool:
        normalized = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(normalized):
            return False
        if self._current_path == normalized and self._waveform_widget is not None:
            return True
        self._current_path = normalized
        self.file_label.setText(os.path.basename(normalized))
        self._clear_analysis()
        self._replace_waveform(normalized)
        self._refresh_actions()
        self.status_label.setText(
            "Fichier charge. Lance le decoupage automatique pour detecter les transients."
        )
        return True

    def _replace_waveform(self, path: str) -> None:
        self._destroy_waveform()
        waveform = WaveformWidget(path, self.app_context)
        waveform.setAcceptDrops(True)
        waveform.installEventFilter(self)
        self.waveform_layout.addWidget(waveform)
        self._waveform_widget = waveform
        loader = getattr(waveform, "loader", None)
        if loader is not None:
            loader.finished.connect(self._on_waveform_loaded)
        else:
            self._on_waveform_loaded()

    def _destroy_waveform(self) -> None:
        if self._waveform_widget is None:
            return
        for cleanup in ("removeEventFilter", "stop_audio"):
            try:
                getattr(self._waveform_widget, cleanup)(self) if cleanup == "removeEventFilter" else getattr(self._waveform_widget, cleanup)()
            except Exception:
                pass
        try:
            self._waveform_widget.timer.stop()
        except Exception:
            pass
        self.waveform_layout.removeWidget(self._waveform_widget)
        self._waveform_widget.deleteLater()
        self._waveform_widget = None

    def _on_waveform_loaded(self) -> None:
        self._refresh_actions()

    def _waveform_ready(self) -> bool:
        w = self._waveform_widget
        return bool(
            w is not None
            and getattr(w, "waveform_data", None) is not None
            and getattr(w, "sample_rate", None)
        )

    # ---------------------------------------------------------------------- #
    # Analysis
    # ---------------------------------------------------------------------- #
    def _run_auto_split(self) -> None:
        if not self._current_path:
            self.status_label.setText("Charge un fichier avant de lancer le decoupage.")
            return
        error = drum_analysis_availability_error()
        if error:
            self.status_label.setText(f"Analyse indisponible: {error}")
            return
        self.split_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText("Detection des transients et estimation du BPM...")
        self._break_service.analyze_file(self._current_path, split_density=DEFAULT_SPLIT_DENSITY)

    def _run_slice_analysis(self) -> None:
        if self._analysis_result is None:
            self.status_label.setText("Lance d'abord le decoupage automatique.")
            return
        markers = self._get_current_markers()
        if not markers:
            self.status_label.setText("Aucun marqueur sur la waveform.")
            return
        self.analyze_button.setEnabled(False)
        self.status_label.setText("Classification des hits depuis les marqueurs...")
        self._break_service.reanalyze_from_markers(self._analysis_result, markers)

    def _get_current_markers(self) -> list[float]:
        w = self._waveform_widget
        return list(getattr(w, "markers", []) or []) if w is not None else []

    # ---------------------------------------------------------------------- #
    # Service callbacks
    # ---------------------------------------------------------------------- #
    def _on_analysis_started(self, path: str) -> None:
        if not self._matches_path(path):
            return
        self.status_label.setText("Analyse en cours...")

    def _on_analysis_finished(self, result: DrumAnalysisResult) -> None:
        if not self._matches_path(result.source_path):
            return
        self._analysis_result = result
        if result.tempo_bpm > 1.0:
            self.bpm_spin.blockSignals(True)
            self.bpm_spin.setValue(float(result.tempo_bpm))
            self.bpm_spin.blockSignals(False)
        self._apply_markers_to_waveform(result)
        self._rebuild_hits_table(result)
        self._refresh_quantized_projection()
        bpm_str = f" — BPM {result.tempo_bpm:.1f}" if result.tempo_bpm > 1.0 else ""
        self.status_label.setText(
            f"{result.onset_count} slices{bpm_str}. "
            f"Ajuste les marqueurs si besoin, puis clique sur Analyser les slices."
        )
        self._refresh_actions()

    def _on_analysis_failed(self, path: str, message: str) -> None:
        if path and not self._matches_path(path):
            return
        self.status_label.setText(f"Analyse impossible: {message}")
        self._refresh_actions()

    def _on_quantize_started(self, path: str) -> None:
        if not self._matches_path(path):
            return
        self.status_label.setText("Preparation de la preview quantizee...")
        self.quantize_button.setEnabled(False)

    def _on_quantize_finished(self, preview: DrumQuantizedPreview) -> None:
        if not self._matches_path(preview.source_path):
            return
        artifact = LabArtifact(
            artifact_id=uuid.uuid4().hex,
            kind="break_preview",
            display_name=preview.display_name,
            source_path=preview.source_path,
            temp_path=preview.temp_path,
            duration=float(preview.duration_s),
            persisted=False,
            origin="break_quantize_preview",
            sample_rate=int(preview.sample_rate),
            metadata={
                "target_bpm": preview.target_bpm,
                "source_bpm": preview.source_bpm,
                "grid_division": preview.grid_division,
                "quantize_strength": preview.quantize_strength,
            },
        )
        self.status_label.setText(f"Preview quantizee prete: {preview.display_name}")
        self.artifactCreated.emit(artifact)
        self._refresh_actions()

    def _on_quantize_failed(self, path: str, message: str) -> None:
        if path and not self._matches_path(path):
            return
        self.status_label.setText(f"Preview quantizee impossible: {message}")
        self._refresh_actions()

    def _matches_path(self, path: str | None) -> bool:
        if not path or not self._current_path:
            return False
        return (
            os.path.normcase(os.path.normpath(self._current_path))
            == os.path.normcase(os.path.normpath(path))
        )

    # ---------------------------------------------------------------------- #
    # Waveform marker helpers
    # ---------------------------------------------------------------------- #
    def _apply_markers_to_waveform(self, result: DrumAnalysisResult) -> None:
        w = self._waveform_widget
        if w is None or getattr(w, "waveform_data", None) is None:
            return
        self._clear_waveform_markers()
        if not result.slices:
            return
        w._record_history = False
        try:
            for s in result.slices:
                w.add_marker(float(s.start_s))
        finally:
            w._record_history = True

    def _clear_waveform_markers(self) -> None:
        w = self._waveform_widget
        if w is None:
            return
        try:
            w.stop_audio()
        except Exception:
            pass
        try:
            if w.region is not None:
                w.plot.removeItem(w.region)
                w.region = None
        except Exception:
            pass
        try:
            for line in list(w.marker_lines.values()):
                w.plot.removeItem(line)
        except Exception:
            pass
        w.markers = []
        w.marker_lines = {}
        w.current_marker_idx = 0
        w.play_start = 0.0
        w.play_end = 0.0
        try:
            w.read_head.setPos(0.0)
            w._refresh_marker_list()
        except Exception:
            pass

    # ---------------------------------------------------------------------- #
    # Hit selection: center waveform + set region + play
    # ---------------------------------------------------------------------- #
    def _on_hit_selected(self, hit_index: int) -> None:
        # Highlight row
        self._selected_hit_index = hit_index
        for row in self._hit_rows:
            row.set_selected(row.drum_slice.index == hit_index)

        # Find the slice
        if self._analysis_result is None:
            return
        ds = next(
            (s for s in self._analysis_result.slices if s.index == hit_index), None
        )
        if ds is None:
            return

        start_s = float(ds.start_s)
        end_s = float(ds.end_s)
        w = self._waveform_widget
        if w is None:
            return

        # Set selection region
        try:
            if w.region is not None:
                w.plot.removeItem(w.region)
                w.region = None
        except Exception:
            pass
        try:
            region = ContextMenuLinearRegionItem(
                [start_s, end_s],
                brush=pg.mkBrush(255, 255, 255, 35),
                pen=pg.mkPen("#4bb6b7", width=1),
            )
            region.setZValue(1)
            region.setBounds([0, float(w.duration or end_s)])
            region.sigRegionChangeFinished.connect(w.on_region_changed)
            region._parent = w
            w.plot.addItem(region)
            w.region = region
        except Exception:
            pass

        # Center view on the hit with padding
        padding = max(0.08, (end_s - start_s) * 0.6)
        try:
            w.plot.setXRange(
                max(0.0, start_s - padding),
                min(float(w.duration or end_s + padding), end_s + padding),
                padding=0,
            )
        except Exception:
            pass

        # Play the hit
        try:
            w.play_start = start_s
            w.play_end = end_s
            w.read_head.setPos(start_s)
            w.play_audio(start_s)
        except Exception:
            pass

    # ---------------------------------------------------------------------- #
    # Hits table
    # ---------------------------------------------------------------------- #
    def _rebuild_hits_table(self, result: DrumAnalysisResult) -> None:
        self._clear_hits_table()
        self._selected_hit_index = None
        for ds in result.slices:
            row = _HitRow(ds, self._current_path or "", self.hits_container)
            row.selected.connect(self._on_hit_selected)
            row.removeRequested.connect(self._on_hit_remove_requested)
            row.labelChanged.connect(self._on_hit_label_changed)
            row.dragStarted.connect(lambda: setattr(self, "_internal_drag_active", True))
            row.dragFinished.connect(lambda: setattr(self, "_internal_drag_active", False))
            self._hit_rows.append(row)
            self.hits_vbox.insertWidget(self.hits_vbox.count() - 1, row)

    def _clear_hits_table(self) -> None:
        for row in self._hit_rows:
            self.hits_vbox.removeWidget(row)
            row.deleteLater()
        self._hit_rows = []

    def _on_hit_label_changed(self, hit_index: int, new_label: str) -> None:
        pass  # Future: persist overrides

    def _on_hit_remove_requested(self, hit_index: int) -> None:
        """Double-click: retire le marqueur du hit et supprime la row de la liste."""
        if self._analysis_result is None:
            return
        ds = next(
            (s for s in self._analysis_result.slices if s.index == hit_index), None
        )
        if ds is None:
            return
        # Retire le marqueur de la waveform
        w = self._waveform_widget
        if w is not None:
            try:
                w.remove_marker(float(ds.start_s))
            except Exception:
                pass
        # Retire la row de la liste
        row = next((r for r in self._hit_rows if r.drum_slice.index == hit_index), None)
        if row is not None:
            self._hit_rows.remove(row)
            self.hits_vbox.removeWidget(row)
            row.deleteLater()
            if self._selected_hit_index == hit_index:
                self._selected_hit_index = None

    def _clear_analysis(self) -> None:
        self._analysis_result = None
        self._quantized_slices = ()
        self._selected_hit_index = None
        self._clear_hits_table()
        self._refresh_actions()

    # ---------------------------------------------------------------------- #
    # Quantize
    # ---------------------------------------------------------------------- #
    def _on_strength_changed(self, value: int) -> None:
        self.strength_value.setText(f"{int(value)}%")

    def _refresh_quantized_projection(self, *_args) -> None:
        if self._analysis_result is None:
            self._quantized_slices = ()
            self._refresh_actions()
            return
        self._quantized_slices = self._break_service.quantized_slices(
            self._analysis_result,
            target_bpm=float(self.bpm_spin.value()),
            grid_division=int(self.grid_combo.currentData() or DEFAULT_QUANTIZE_GRID_DIVISION),
            quantize_strength=float(self.strength_slider.value()) / 100.0,
        )
        self._refresh_actions()

    def _create_quantized_preview(self) -> None:
        if self._analysis_result is None:
            return
        self._break_service.create_quantized_preview(
            self._analysis_result,
            target_bpm=float(self.bpm_spin.value()),
            grid_division=int(self.grid_combo.currentData() or DEFAULT_QUANTIZE_GRID_DIVISION),
            quantize_strength=float(self.strength_slider.value()) / 100.0,
        )

    # ---------------------------------------------------------------------- #
    # Actions state
    # ---------------------------------------------------------------------- #
    def _refresh_actions(self) -> None:
        has_path = bool(self._current_path)
        ready = self._waveform_ready()
        analyzed = self._analysis_result is not None
        self.split_button.setEnabled(has_path and ready)
        self.analyze_button.setEnabled(analyzed and bool(self._get_current_markers()))
        self.bpm_spin.setEnabled(analyzed)
        self.grid_combo.setEnabled(analyzed)
        self.strength_slider.setEnabled(analyzed)
        self.quantize_button.setEnabled(analyzed and len(self._quantized_slices) >= 2)

    # ---------------------------------------------------------------------- #
    # Drag and drop (file into widget)
    # ---------------------------------------------------------------------- #
    def eventFilter(self, watched, event):
        etype = event.type()
        if etype == QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if etype == QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if etype == QEvent.Type.DragLeave:
            return self._handle_drag_leave(event)
        if etype == QEvent.Type.Drop:
            return self._handle_drop(event)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if not self._handle_drag_enter(event):
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if not self._handle_drag_move(event):
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        if not self._handle_drag_leave(event):
            super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not self._handle_drop(event):
            super().dropEvent(event)

    def _handle_drag_enter(self, event) -> bool:
        if self._internal_drag_active:
            return False
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime) or not self._paths_from_mime(mime):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_move(self, event) -> bool:
        if self._internal_drag_active:
            return False
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime) or not self._paths_from_mime(mime):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_leave(self, event) -> bool:
        self._set_drop_active(False)
        event.accept()
        return True

    def _handle_drop(self, event) -> bool:
        if self._internal_drag_active:
            self._set_drop_active(False)
            return False
        paths = self._paths_from_mime(event.mimeData())
        self._set_drop_active(False)
        if not paths:
            return False
        opened = any(self.open_file(p) for p in paths)
        if not opened:
            return False
        event.acceptProposedAction()
        self.setFocus()
        return True

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_waveform_drop_paths(
            mime, sample_path_lookup=self._path_for_sample_id
        )

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        samples = self.app_context.sample_store.get_cached()
        s = next((x for x in samples if int(getattr(x, "id", -1)) == int(sample_id)), None)
        path = getattr(s, "path", "") if s is not None else ""
        return str(path or "") or None

    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        self.waveform_host.setProperty("dropActive", active)
        self.waveform_host.style().unpolish(self.waveform_host)
        self.waveform_host.style().polish(self.waveform_host)
        if active:
            self.status_label.setText("Depose le fichier ici pour l'analyser.")
        elif self._current_path is None:
            self.status_label.setText("Depose un break dans la zone waveform pour commencer.")

    # ---------------------------------------------------------------------- #
    # Styles
    # ---------------------------------------------------------------------- #
    def _apply_styles(self) -> None:
        p = theme.manager.p
        accent = getattr(p, "ACCENT", p.INFO)
        self.setStyleSheet(
            f"""
            QWidget#BreakRoot {{
                background: {p.BG_MEDIUM};
            }}
            QWidget#BreakWaveformHost {{
                background: transparent;
                border: 1px dashed {p.BORDER};
                border-radius: 8px;
            }}
            QWidget#BreakWaveformHost[dropActive="true"] {{
                background: {p.BG_CARD};
                border-color: {p.INFO};
            }}
            QLabel#BreakTitle {{
                color: {p.TEXT};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#BreakFileLabel,
            QLabel#BreakStatus,
            QLabel#BreakFieldLabel,
            QLabel#BreakFieldValue,
            QLabel#BreakHitTime,
            QLabel#BreakHitConf {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#BreakHitGrip {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            QLabel#BreakHitIndex {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
            }}
            QPushButton#BreakAction {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton#BreakAction:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#BreakAction:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER};
            }}
            QFrame#BreakHitRow {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 7px;
            }}
            QFrame#BreakHitRow:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QFrame#BreakHitRow[selected="true"] {{
                background: {p.BG_HOVER};
                border-color: {accent};
            }}
            QFrame#BreakQuantFrame {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QScrollArea#BreakHitsScroll {{
                background: transparent;
                border: none;
            }}
            QWidget#BreakHitsContainer {{
                background: transparent;
            }}
            QWidget#BreakHitRadios {{
                background: transparent;
            }}
            QRadioButton#BreakHitRadio {{
                color: {p.TEXT_MUTED};
                font-size: 9px;
                spacing: 1px;
                padding: 0 1px;
            }}
            QRadioButton#BreakHitRadio:checked {{
                color: {p.TEXT};
                font-weight: 700;
            }}
            QRadioButton#BreakHitRadio::indicator {{
                width: 9px;
                height: 9px;
                border-radius: 5px;
                border: 1px solid {p.BORDER_LIGHT};
                background: {p.BG_MEDIUM};
            }}
            QRadioButton#BreakHitRadio::indicator:hover {{
                border-color: {p.TEXT_MUTED};
            }}
            QRadioButton#BreakHitRadio::indicator:checked {{
                background: {accent};
                border-color: {accent};
            }}
            QComboBox#BreakCombo,
            QDoubleSpinBox#BreakSpin {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 3px 7px;
                min-height: 26px;
            }}
            QSlider#BreakSlider::groove:horizontal {{
                background: {p.BORDER};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider#BreakSlider::handle:horizontal {{
                background: {p.TEXT};
                width: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }}
            QSplitter#BreakSplitter::handle:vertical {{
                height: 5px;
                background: transparent;
            }}
            QSplitter#BreakSplitter::handle:vertical:hover {{
                background: {p.BORDER_LIGHT};
            }}
            """
        )
