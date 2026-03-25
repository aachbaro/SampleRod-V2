from __future__ import annotations

from functools import lru_cache
from importlib import import_module
import json
import logging
import os
from pathlib import Path
import sys
import time
import warnings

import numpy as np

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
if os.getenv("SAMPLEROD_DISABLE_SCALE", "0") != "1":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .analyzer import (
    AUDIO_EXTENSIONS,
    DEFAULT_SPLIT_DENSITY,
    DrumDetectionResult,
    DrumTransientPreview,
    analyze_file_with_preview,
    detect_drum_from_markers,
    get_analysis_dependency_error,
)
from .preview import RetimedPreview, build_retimed_preview


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


class _PrototypeWaveformContext:
    """Minimal context placeholder for embedding the SampleRod waveform widget."""


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.top_n = top_n
        self.split_density = split_density

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
        self._close_after_analysis = False
        self._result: DrumDetectionResult | None = None
        self._suspend_hit_selection_sync = False
        self._loaded_audio_samples: np.ndarray | None = None
        self._loaded_audio_sample_rate: int | None = None
        self._retimed_preview: RetimedPreview | None = None
        self._retimed_preview_playing = False
        self._retime_stop_timer = QTimer(self)
        self._retime_stop_timer.setSingleShot(True)
        self._retime_stop_timer.timeout.connect(self._on_retimed_preview_finished)
        self._retime_visual_timer = QTimer(self)
        self._retime_visual_timer.setInterval(20)
        self._retime_visual_timer.timeout.connect(self._update_retimed_preview_visual)
        self._retime_visual_started_at = 0.0
        self._retime_visual_segment_index = -1

        self._build_ui()
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
        self.page_content.setMinimumWidth(1220)
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

        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self._browse_file)

        self.analyze_button = QPushButton("Analyser")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(self._start_analysis)

        path_row.addWidget(self.path_input, 1)
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

        self._build_waveform_box(root)
        self._build_result_boxes(root)
        root.addStretch(1)

        root.insertWidget(0, title)
        root.insertWidget(1, subtitle)
        root.insertLayout(2, path_row)
        root.insertLayout(3, options_row)
        root.insertWidget(4, self.status_label)
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

        self.rebuild_markers_button = QPushButton("Rebuild Hits From Markers")
        self.rebuild_markers_button.clicked.connect(self._rebuild_hits_from_markers)
        self.rebuild_markers_button.setEnabled(False)

        self.rebuild_markers_label = QLabel(
            "Tu peux ajouter, deplacer ou supprimer des markers dans la waveform, puis reconstruire la liste de transients."
        )
        self.rebuild_markers_label.setObjectName("StatusLabel")
        self.rebuild_markers_label.setWordWrap(True)

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
        self.hits_table.setMinimumHeight(220)
        self.hits_table.setMinimumWidth(920)
        header = self.hits_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        for column in range(6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.hits_table.itemSelectionChanged.connect(self._on_hit_selected)
        self.hits_table.itemDoubleClicked.connect(self._on_hit_double_clicked)

        layout.addWidget(self.waveform_status_label)
        layout.addLayout(self.waveform_host)
        layout.addWidget(self.hits_summary_label)
        layout.addWidget(self.rebuild_markers_button)
        layout.addWidget(self.rebuild_markers_label)
        layout.addWidget(self.hits_table)
        self._build_retime_controls(layout)
        self.waveform_box.setMinimumHeight(500)
        root.addWidget(self.waveform_box)

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

        self.retime_play_button = QPushButton("Play retimed")
        self.retime_play_button.clicked.connect(self._play_retimed_preview)
        self.retime_stop_button = QPushButton("Stop retimed")
        self.retime_stop_button.clicked.connect(self._stop_retimed_preview)
        self.retime_loop_button = QPushButton("Loop retimed")
        self.retime_loop_button.setObjectName("ToggleButton")
        self.retime_loop_button.setCheckable(True)
        self.retime_loop_button.setChecked(self._settings.value("retime_loop_enabled", False, type=bool))
        self.retime_loop_button.toggled.connect(self._on_retime_loop_toggled)

        self.retime_info_label = QLabel(
            "Analyse un break avec au moins deux transients pour entendre une relecture des segments a un autre BPM, "
            "avec tete de lecture synchronisee sur la waveform."
        )
        self.retime_info_label.setObjectName("StatusLabel")
        self.retime_info_label.setWordWrap(True)

        grid.addWidget(QLabel("BPM detecte"), 0, 0)
        grid.addWidget(self.detected_bpm_value, 0, 1)
        grid.addWidget(QLabel("Facteur"), 0, 2)
        grid.addWidget(self.detected_bpm_factor_combo, 0, 3)
        grid.addWidget(QLabel("BPM cible"), 0, 4)
        grid.addWidget(self.target_bpm_spin, 0, 5)
        grid.addWidget(self.retime_play_button, 0, 6)
        grid.addWidget(self.retime_stop_button, 0, 7)
        grid.addWidget(self.retime_loop_button, 0, 8)
        grid.addWidget(self.retime_info_label, 1, 0, 1, 9)

        layout.addWidget(self.retime_box)

    def _build_result_boxes(self, root: QVBoxLayout) -> None:
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
        self.candidates_table.setMinimumHeight(230)
        self.candidates_table.setMinimumWidth(980)
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
        self.json_view.setMinimumHeight(280)
        json_layout.addWidget(self.json_view)

        self.result_box.setMinimumHeight(250)
        self.candidates_box.setMinimumHeight(290)
        self.json_box.setMinimumHeight(320)
        root.addWidget(self.result_box)
        root.addWidget(self.candidates_box)
        root.addWidget(self.json_box)

    def _init_waveform_panel(self) -> None:
        try:
            logging.getLogger("waveform_playback").setLevel(logging.ERROR)
            waveform_cls = _require_waveform_widget()
            waveform = waveform_cls(None, _PrototypeWaveformContext(), auto_load=False)
            waveform.allow_cut_export = False
            waveform.disable_marker_add = False
            for name in ("save_button", "undo_button", "redo_button"):
                button = getattr(waveform, name, None)
                if button is not None:
                    button.setVisible(False)
            for name in ("play_button", "pause_button", "stop_button"):
                button = getattr(waveform, name, None)
                if button is not None:
                    button.clicked.connect(self._stop_retimed_preview_for_waveform)
            self._waveform_widget = waveform
            self.waveform_host.addWidget(waveform)
            self.waveform_placeholder.hide()
            self.waveform_status_label.setText(
                "Waveform editor SampleRod charge. Utilise ses controles pour ecouter le sample, "
                "rajouter des markers avec le bouton marker, cliquer un transient pour naviguer, "
                "ou double-cliquer dans la table pour lire directement."
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
            QPushButton { background: #2a3140; border: 1px solid #3c4659; border-radius: 10px; padding: 9px 14px; }
            QPushButton:hover { background: #333d4f; }
            QPushButton#PrimaryButton { background: #d1a142; color: #171a20; border-color: #d1a142; font-weight: 700; }
            QPushButton#PrimaryButton:hover { background: #ddb257; }
            QPushButton#ToggleButton:checked { background: #4bb6b7; color: #101318; border-color: #4bb6b7; font-weight: 700; }
            QProgressBar { background: #101318; border: 1px solid #303644; border-radius: 10px; text-align: center; min-height: 18px; }
            QProgressBar::chunk { border-radius: 9px; background: #4bb6b7; }
            QLabel#TitleLabel { font-weight: 700; }
            QLabel#ResultLabel { font-weight: 700; color: #f0c05a; }
            QLabel#StatusLabel { color: #9ba6ba; }
            """
        )

    def _restore_state(self) -> None:
        last_path = self._settings.value("last_path", "", type=str)
        split_density = self._settings.value("split_density", int(round(DEFAULT_SPLIT_DENSITY)), type=int)
        self.split_density_slider.setValue(int(np.clip(split_density, 0, 100)))
        if last_path:
            self.path_input.setText(last_path)
            self._sync_waveform_path(last_path)
        self._update_retimed_preview_state(None)
        self._sync_dependency_state()

    def _sync_dependency_state(self) -> None:
        self._dependency_error = get_analysis_dependency_error()
        self.retime_loop_button.setEnabled(not bool(self._dependency_error))
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
        if self._worker and self._worker.isRunning():
            self._close_after_analysis = True
            self._worker.requestInterruption()
            self._set_busy(True, "Analyse encore en cours. La fenetre se fermera des que le worker aura fini.")
            event.ignore()
            return

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
        self._stop_retimed_preview(update_status=False)
        self.path_input.setText(path)
        resolved = Path(path).expanduser()
        self._settings.setValue("last_path", str(resolved))
        if resolved.exists():
            self._settings.setValue("last_dir", str(resolved.parent))
        self._sync_waveform_path(str(resolved))
        self._result = None
        self._populate_hits(None)
        self._update_retimed_preview_state(None)
        self.rebuild_markers_label.setText(
            "Tu peux ajouter, deplacer ou supprimer des markers dans la waveform, puis reconstruire la liste de transients."
        )
        self.status_label.setText("Sample selectionne. Clique sur Analyser.")

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

    def _on_detected_bpm_factor_changed(self, _index: int) -> None:
        self._settings.setValue("detected_bpm_factor", self._detected_bpm_factor())
        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=False)
        self._refresh_tempo_display()
        self._update_retimed_preview_state(self._result, reset_target=True)

    def _retime_loop_enabled(self) -> bool:
        return bool(self.retime_loop_button.isChecked())

    def _on_retime_loop_toggled(self, enabled: bool) -> None:
        self._settings.setValue("retime_loop_enabled", bool(enabled))
        if self._retimed_preview_playing and self._retimed_preview is not None:
            status = "activee" if enabled else "desactivee a la fin du cycle courant"
            self.retime_info_label.setText(
                f"Lecture retimee en cours: {self._retimed_preview.source_bpm:.1f} -> "
                f"{self._retimed_preview.target_bpm:.1f} BPM, {self._retimed_preview.segment_count} segments, "
                f"{self._retimed_preview.duration_s:.2f}s. Boucle {status}."
            )
            return
        self._update_retimed_preview_state(self._result)

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
        if self._worker and self._worker.isRunning():
            return

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
        self._set_busy(True, f"Analyse en cours sur {source.name}...")
        self._worker = AnalysisWorker(
            str(source),
            int(self.top_n_spin.value()),
            float(self.split_density_slider.value()),
            self,
        )
        self._worker.progressed.connect(self._on_analysis_progress)
        self._worker.preview_ready.connect(self._on_analysis_preview)
        self._worker.succeeded.connect(self._on_analysis_success)
        self._worker.failed.connect(self._on_analysis_failure)
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.start()

    def _sync_waveform_path(self, path: str) -> None:
        resolved = Path(path).expanduser()
        if not resolved.exists():
            self.waveform_status_label.setText("Fichier introuvable pour la waveform.")
            self._clear_waveform_markers()
            self._loaded_audio_samples = None
            self._loaded_audio_sample_rate = None
            return
        if resolved.suffix.lower() not in AUDIO_EXTENSIONS:
            self.waveform_status_label.setText("Format audio non supporte pour la waveform.")
            self._clear_waveform_markers()
            self._loaded_audio_samples = None
            self._loaded_audio_sample_rate = None
            return

        try:
            samples, waveform_data, sample_rate, duration_s = self._load_audio_for_waveform(resolved)
            self._loaded_audio_samples = samples
            self._loaded_audio_sample_rate = sample_rate
            if self._waveform_widget is None:
                self.waveform_status_label.setText(
                    self._waveform_error or "Waveform editor indisponible, mais l'audio est charge pour l'analyse."
                )
                return
            self._waveform_widget.audio_file_path = str(resolved)
            self._waveform_widget.set_waveform_data(waveform_data, sample_rate, duration_s)
            self._clear_waveform_markers()
            self.waveform_status_label.setText(
                "Waveform charge. Tu peux l'ecouter directement avec ses controles, puis lancer l'analyse."
            )
        except Exception as exc:
            self._loaded_audio_samples = None
            self._loaded_audio_sample_rate = None
            self.waveform_status_label.setText(f"Chargement waveform impossible: {exc}")

    def _set_busy(self, busy: bool, status: str) -> None:
        self.path_input.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.analyze_button.setEnabled((not busy) and not self._dependency_error)
        self.top_n_spin.setEnabled((not busy) and not self._dependency_error)
        self.split_density_slider.setEnabled((not busy) and not self._dependency_error)
        retime_ready = (not busy) and self._retimed_preview_available()
        self.retime_play_button.setEnabled(retime_ready)
        self.retime_stop_button.setEnabled((not busy) and self._retimed_preview_playing)
        self.detected_bpm_factor_combo.setEnabled((not busy) and self._result is not None)
        self.target_bpm_spin.setEnabled((not busy) and self._retimed_preview_available())
        self.rebuild_markers_button.setEnabled((not busy) and self._marker_rebuild_available())
        self.status_label.setText(status)

    def _on_analysis_progress(self, message: str) -> None:
        if self._worker and self._worker.isRunning():
            self.status_label.setText(message)

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
        self._result = result
        self._populate_result(result)
        self._populate_hits(result)
        self._apply_hits_to_waveform(result)
        self._update_retimed_preview_state(result, reset_target=True)
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
        self._set_busy(False, self.status_label.text())
        self._worker = None
        if self._close_after_analysis:
            self._close_after_analysis = False
            QTimer.singleShot(0, self.close)

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
                hit.label,
                f"{hit.start_s:.3f}s",
                f"{hit.end_s:.3f}s",
                f"{hit.confidence:.2f}",
                f"{hit.peak_db:.1f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.hits_table.setItem(row, column, item)

        summary = ", ".join(
            f"{label}:{count}" for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        )
        self.hits_summary_label.setText(f"{len(hits)} transient(s) detecte(s). Repartition: {summary}")
        self.hits_table.resizeColumnsToContents()
        self._ensure_table_column_widths(self.hits_table, {0: 56, 1: 160, 2: 100, 3: 100, 4: 80, 5: 80})
        self.rebuild_markers_button.setEnabled(self._marker_rebuild_available())

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

        try:
            rebuilt = detect_drum_from_markers(
                self._loaded_audio_samples,
                int(self._loaded_audio_sample_rate or 0),
                marker_times,
                source_path=self._result.source_path if self._result else self.path_input.text().strip() or None,
                top_n=int(self.top_n_spin.value()),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Reanalyse impossible", str(exc))
            self.rebuild_markers_label.setText(f"Reanalyse depuis markers impossible: {exc}")
            return

        self._result = rebuilt
        self._populate_result(rebuilt)
        self._populate_hits(rebuilt)
        self._apply_hits_to_waveform(rebuilt, preserve_existing=True)
        self._update_retimed_preview_state(rebuilt)
        self.rebuild_markers_label.setText(
            f"Reanalyse depuis {len(marker_times)} marker(s): {rebuilt.onset_count} transient(s) reconstruits."
        )
        self.status_label.setText(
            f"Liste des transients reconstruite depuis les markers. {rebuilt.label} ({rebuilt.form})."
        )

    def _on_target_bpm_changed(self, _value: float) -> None:
        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=False)
        self._update_retimed_preview_state(self._result)

    def _retimed_preview_available(self) -> bool:
        return bool(
            self._result is not None
            and self._loaded_audio_samples is not None
            and self._loaded_audio_sample_rate
            and self._effective_detected_bpm(self._result) > 1.0
            and len(self._result.transient_hits) >= 2
        )

    def _marker_rebuild_available(self) -> bool:
        marker_times = self._current_marker_times()
        return bool(
            self._result is not None
            and self._loaded_audio_samples is not None
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
            self.retime_play_button.setEnabled(False)
            self.retime_stop_button.setEnabled(False)
            self.detected_bpm_factor_combo.setEnabled(False)
            self.target_bpm_spin.setEnabled(False)
            self.retime_info_label.setText(
                "Analyse un break avec au moins deux transients pour entendre une relecture des segments a un autre BPM, "
                "avec tete de lecture synchronisee sur la waveform."
            )
            return

        raw_bpm = float(result.tempo_bpm)
        detected_bpm = self._effective_detected_bpm(result)
        factor = self._detected_bpm_factor()
        self.detected_bpm_factor_combo.setEnabled(not bool(self._worker and self._worker.isRunning()))
        if raw_bpm > 1.0:
            if abs(factor - 1.0) < 1e-6:
                self.detected_bpm_value.setText(f"{detected_bpm:.1f} BPM")
            else:
                self.detected_bpm_value.setText(f"{detected_bpm:.1f} BPM ({raw_bpm:.1f} x {factor:g})")
        else:
            self.detected_bpm_value.setText("tempo indisponible")

        if detected_bpm > 1.0 and reset_target:
            clamped = float(np.clip(detected_bpm, self.target_bpm_spin.minimum(), self.target_bpm_spin.maximum()))
            previous = float(self.target_bpm_spin.value())
            if abs(previous - clamped) > 0.25:
                self.target_bpm_spin.blockSignals(True)
                self.target_bpm_spin.setValue(clamped)
                self.target_bpm_spin.blockSignals(False)

        available = self._retimed_preview_available() and not bool(self._worker and self._worker.isRunning())
        self.retime_play_button.setEnabled(available)
        self.retime_stop_button.setEnabled(self._retimed_preview_playing)
        self.target_bpm_spin.setEnabled(available)

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
        self.retime_info_label.setText(
            f"Preview segmentee prete: {detected_bpm:.1f} -> {self.target_bpm_spin.value():.1f} BPM "
            f"(ratio {ratio:.2f}x, duree approx {estimated_duration:.2f}s). "
            f"La tete de lecture suivra le segment actif.{loop_hint}"
        )

    def _estimate_retimed_preview_duration(self, result: DrumDetectionResult, target_bpm: float) -> float:
        hits = list(result.transient_hits)
        source_bpm = self._effective_detected_bpm(result)
        if len(hits) < 2 or source_bpm <= 1.0 or target_bpm <= 1.0:
            return 0.0
        base_start = float(hits[0].start_s)
        last_hit = hits[-1]
        last_offset = max(0.0, float(last_hit.start_s) - base_start)
        last_length = max(0.012, float(last_hit.end_s) - float(last_hit.start_s))
        ratio = float(source_bpm / target_bpm)
        return max(0.0, (last_offset * ratio) + last_length)

    def _play_retimed_preview(self) -> None:
        if not self._retimed_preview_available() or self._result is None:
            self._update_retimed_preview_state(self._result)
            return

        try:
            preview = build_retimed_preview(
                self._loaded_audio_samples,
                int(self._loaded_audio_sample_rate or 0),
                self._result.transient_hits,
                source_bpm=self._effective_detected_bpm(self._result),
                target_bpm=float(self.target_bpm_spin.value()),
            )
            sounddevice = _require_sounddevice()
            self._stop_retimed_preview(update_status=False)
            if self._waveform_widget is not None:
                try:
                    self._waveform_widget.stop_audio()
                except Exception:
                    pass
            self._start_retimed_preview_playback(preview, sounddevice=sounddevice)
        except Exception as exc:
            self._retimed_preview_playing = False
            self._retime_visual_timer.stop()
            self.retime_stop_button.setEnabled(False)
            self.retime_info_label.setText(f"Preview retimee impossible: {exc}")
            QMessageBox.warning(self, "Preview retimee impossible", str(exc))

    def _start_retimed_preview_playback(
        self,
        preview: RetimedPreview,
        *,
        sounddevice=None,
        loop_restart: bool = False,
    ) -> None:
        if sounddevice is None:
            sounddevice = _require_sounddevice()
        sounddevice.play(preview.audio, preview.sample_rate, blocking=False)
        self._retimed_preview = preview
        self._retimed_preview_playing = True
        self._retime_visual_started_at = time.perf_counter()
        self._retime_visual_segment_index = -1
        self.retime_play_button.setEnabled(True)
        self.retime_stop_button.setEnabled(True)
        self._retime_stop_timer.start(max(1, int((preview.duration_s + 0.05) * 1000.0)))
        self._retime_visual_timer.start()
        self._update_retimed_preview_visual()
        mode = "Lecture retimee en boucle" if self._retime_loop_enabled() else "Lecture retimee en cours"
        if loop_restart and self._retime_loop_enabled():
            mode = "Lecture retimee en boucle relancee"
        self.retime_info_label.setText(
            f"{mode}: {preview.source_bpm:.1f} -> {preview.target_bpm:.1f} BPM, "
            f"{preview.segment_count} segments, {preview.duration_s:.2f}s. "
            "La tete de lecture suit le segment declenche sur la waveform."
        )

    def _stop_retimed_preview(self, *_args, update_status: bool = True) -> None:
        self._retime_stop_timer.stop()
        self._retime_visual_timer.stop()
        try:
            sounddevice = _require_sounddevice()
            sounddevice.stop()
        except Exception:
            pass
        self._retimed_preview_playing = False
        self._retime_visual_started_at = 0.0
        self._retime_visual_segment_index = -1
        self.retime_stop_button.setEnabled(False)
        if update_status:
            self._update_retimed_preview_state(self._result)

    def _on_retimed_preview_finished(self) -> None:
        preview = self._retimed_preview
        self._retimed_preview_playing = False
        self._retime_visual_timer.stop()
        self._retime_visual_started_at = 0.0
        self._retime_visual_segment_index = -1
        self.retime_stop_button.setEnabled(False)
        if preview is not None and self._retime_loop_enabled():
            try:
                self._start_retimed_preview_playback(preview, loop_restart=True)
                return
            except Exception as exc:
                self.retime_info_label.setText(f"Boucle retimee interrompue: {exc}")
                QMessageBox.warning(self, "Boucle retimee interrompue", str(exc))
        if preview is not None:
            self.retime_info_label.setText(
                f"Preview terminee. {preview.source_bpm:.1f} -> "
                f"{preview.target_bpm:.1f} BPM."
            )
        else:
            self._update_retimed_preview_state(self._result)

    def _stop_retimed_preview_for_waveform(self, *_args) -> None:
        if self._retimed_preview_playing:
            self._stop_retimed_preview(update_status=True)

    def _update_retimed_preview_visual(self) -> None:
        if (
            not self._retimed_preview_playing
            or self._retimed_preview is None
            or self._waveform_widget is None
            or not self._retimed_preview.segments
        ):
            return

        elapsed_s = max(0.0, time.perf_counter() - self._retime_visual_started_at)
        segment_index, source_position = self._locate_retimed_preview_source_position(elapsed_s)
        if segment_index is None or source_position is None:
            return

        if segment_index != self._retime_visual_segment_index:
            self._retime_visual_segment_index = segment_index
            self._select_retimed_preview_row(segment_index)

        try:
            self._waveform_widget.read_head.setPos(float(source_position))
        except Exception:
            pass

    def _locate_retimed_preview_source_position(self, elapsed_s: float) -> tuple[int | None, float | None]:
        if self._retimed_preview is None or not self._retimed_preview.segments:
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

    def _select_retimed_preview_row(self, row: int) -> None:
        if row < 0 or row >= self.hits_table.rowCount():
            return
        self._suspend_hit_selection_sync = True
        try:
            self.hits_table.selectRow(row)
        finally:
            self._suspend_hit_selection_sync = False
        self._focus_hit_row(row, autoplay=False)

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
        self._focus_hit_row(row, autoplay=True)

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
            if autoplay:
                self._waveform_widget.play_from_start()
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

        self._waveform_widget._record_history = False
        try:
            for marker_time in marker_times:
                self._waveform_widget.add_marker(float(marker_time))
        finally:
            self._waveform_widget._record_history = True

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

            self._waveform_widget._record_history = False
            try:
                for hit in result.transient_hits:
                    self._waveform_widget.add_marker(float(hit.start_s))
            finally:
                self._waveform_widget._record_history = True
        else:
            try:
                self._waveform_widget._refresh_marker_list()
            except Exception:
                should_rebuild_markers = True
                self._clear_waveform_markers()
                self._waveform_widget._record_history = False
                try:
                    for hit in result.transient_hits:
                        self._waveform_widget.add_marker(float(hit.start_s))
                finally:
                    self._waveform_widget._record_history = True

        marker_list = getattr(self._waveform_widget, "marker_list", None)
        if marker_list is not None:
            for row, hit in enumerate(result.transient_hits):
                if row >= marker_list.count():
                    break
                item = marker_list.item(row)
                if item is None:
                    continue
                item.setToolTip(
                    f"{hit.label} | {hit.start_s:.3f}s -> {hit.end_s:.3f}s | "
                    f"conf {hit.confidence:.2f} | peak {hit.peak_db:.1f} dB"
                )

        self.waveform_status_label.setText(
            f"{len(result.transient_hits)} marker(s) poses sur la waveform. "
            + (
                "Markers manuels preserves et liste des transients mise a jour."
                if preserve_existing and not should_rebuild_markers
                else "Simple clic dans la table = navigation, double-clic = lecture directe."
            )
        )

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
