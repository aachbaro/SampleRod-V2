from __future__ import annotations

from functools import lru_cache
from importlib import import_module
import json
import os
from pathlib import Path
import sys
import time
import warnings

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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .analyzer import AUDIO_EXTENSIONS, DetectionResult, analyze_file, get_analysis_dependency_error
from .note_segments import NoteSegment, detect_note_segments_file


@lru_cache(maxsize=1)
def _require_pygame():
    try:
        return import_module("pygame")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Preview audio dependency missing (pygame). "
            "Install project deps with `python -m pip install -r requirements.txt`."
        ) from exc


@lru_cache(maxsize=1)
def _require_soundfile():
    try:
        return import_module("soundfile")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Preview audio dependency missing (soundfile). "
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

    def __init__(self, path: str, top_n: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.top_n = top_n

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
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
                scale_result = analyze_file(self.path, top_n=self.top_n)

            if self.isInterruptionRequested():
                return

            note_segments: tuple[NoteSegment, ...] = ()
            note_segments_error: str | None = None
            try:
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
                    note_segments = detect_note_segments_file(self.path)
            except Exception as exc:
                note_segments_error = str(exc)

            if self.isInterruptionRequested():
                return

            self.succeeded.emit(
                {
                    "scale_result": scale_result,
                    "note_segments": note_segments,
                    "note_segments_error": note_segments_error,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class ScaleDetectorWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("SampleRod", "ScaleDetectorPrototype")
        self._dependency_error: str | None = None
        self._audio_error: str | None = None
        self._waveform_error: str | None = None
        self._audio_initialized = False
        self._preview_path: str | None = None
        self._preview_duration_s = 0.0
        self._playback_base_ms = 0
        self._playback_started_at_s: float | None = None
        self._preview_paused = False
        self._worker: AnalysisWorker | None = None
        self._waveform_widget: QWidget | None = None
        self._note_segments: list[NoteSegment] = []
        self._close_after_analysis = False

        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(150)
        self._playback_timer.timeout.connect(self._update_preview_progress)

        self._build_ui()
        self._apply_style()
        self._init_waveform_panel()
        self._restore_state()

    def _build_ui(self) -> None:
        self.setWindowTitle("SampleRod - Scale Detector Prototype")
        self.resize(1280, 960)
        self.setMinimumSize(1020, 760)
        self.setAcceptDrops(True)
        self.setFont(self._build_font(10))

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.page_scroll = QScrollArea(self)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        shell.addWidget(self.page_scroll)

        self.page_content = QWidget()
        self.page_content.setObjectName("ScaleDetectorPage")
        self.page_content.setMinimumWidth(1220)
        self.page_scroll.setWidget(self.page_content)

        root = QVBoxLayout(self.page_content)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("Detecteur de gamme - prototype")
        title.setObjectName("TitleLabel")
        title.setFont(self._build_font(16, bold=True))
        subtitle = QLabel(
            "Selectionne un sample audio, lance l'analyse, puis inspecte la waveform et les notes detectees."
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
        options_row.addStretch(1)

        self.status_label = QLabel("Pret.")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)

        self._build_preview_box(root)
        self._build_waveform_box(root)
        self._build_result_boxes(root)
        root.addStretch(1)

        root.insertWidget(0, title)
        root.insertWidget(1, subtitle)
        root.insertLayout(2, path_row)
        root.insertLayout(3, options_row)
        root.insertWidget(4, self.status_label)

    def _build_preview_box(self, root: QVBoxLayout) -> None:
        self.preview_box = QGroupBox("Preview audio (fallback)")
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setSpacing(10)

        preview_controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_preview_playback)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._stop_preview_playback)
        self.stop_button.setEnabled(False)
        self.preview_time_label = QLabel("00:00 / 00:00")
        self.preview_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        preview_controls.addWidget(self.play_button)
        preview_controls.addWidget(self.stop_button)
        preview_controls.addStretch(1)
        preview_controls.addWidget(self.preview_time_label)

        self.preview_status_label = QLabel(
            "Ce lecteur reste disponible seulement si le waveform editor ne charge pas."
        )
        self.preview_status_label.setObjectName("StatusLabel")
        self.preview_status_label.setWordWrap(True)
        self.preview_progress = QProgressBar()
        self.preview_progress.setRange(0, 1000)
        self.preview_progress.setValue(0)
        self.preview_progress.setTextVisible(False)

        preview_layout.addLayout(preview_controls)
        preview_layout.addWidget(self.preview_progress)
        preview_layout.addWidget(self.preview_status_label)
        root.addWidget(self.preview_box)

    def _build_waveform_box(self, root: QVBoxLayout) -> None:
        self.waveform_box = QGroupBox("Waveform / notes detectees")
        waveform_layout = QVBoxLayout(self.waveform_box)
        waveform_layout.setSpacing(10)

        self.waveform_status_label = QLabel(
            "Le waveform editor de SampleRod sera charge ici si les dependances UI sont disponibles."
        )
        self.waveform_status_label.setObjectName("StatusLabel")
        self.waveform_status_label.setWordWrap(True)

        self.waveform_host = QVBoxLayout()
        self.waveform_placeholder = QLabel(
            "Waveform editor indisponible pour le moment. "
            "Le proto restera utilisable avec la preview et les resultats textuels."
        )
        self.waveform_placeholder.setWordWrap(True)
        self.waveform_host.addWidget(self.waveform_placeholder)

        self.note_segments_summary_label = QLabel("Aucune note detectee pour le moment.")
        self.note_segments_summary_label.setObjectName("StatusLabel")
        self.note_segments_summary_label.setWordWrap(True)

        self.note_segments_table = QTableWidget(0, 7)
        self.note_segments_table.setHorizontalHeaderLabels(
            ("Seg", "Type", "Dominant", "Active notes", "Start", "End", "Conf")
        )
        self.note_segments_table.verticalHeader().setVisible(False)
        self.note_segments_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.note_segments_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.note_segments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.note_segments_table.setAlternatingRowColors(True)
        self.note_segments_table.setWordWrap(False)
        self.note_segments_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.note_segments_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.note_segments_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.note_segments_table.itemSelectionChanged.connect(self._on_note_segment_selected)
        self.note_segments_table.setMinimumHeight(220)
        self.note_segments_table.setMinimumWidth(980)
        note_header = self.note_segments_table.horizontalHeader()
        note_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        note_header.setStretchLastSection(False)
        note_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        note_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        note_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        note_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        note_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        note_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        note_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.note_segments_table.setColumnWidth(3, 320)

        waveform_layout.addWidget(self.waveform_status_label)
        waveform_layout.addLayout(self.waveform_host)
        waveform_layout.addWidget(self.note_segments_summary_label)
        waveform_layout.addWidget(self.note_segments_table)
        self.waveform_box.setMinimumHeight(470)
        root.addWidget(self.waveform_box)

    def _build_result_boxes(self, root: QVBoxLayout) -> None:
        self.result_box = QGroupBox("Resultat principal")
        result_layout = QGridLayout(self.result_box)
        result_layout.setHorizontalSpacing(18)
        result_layout.setVerticalSpacing(10)

        self.result_label = QLabel("Aucun sample charge")
        self.result_label.setObjectName("ResultLabel")
        self.result_label.setFont(self._build_font(20, bold=True))
        self.kind_label = QLabel("-")
        self.source_label = QLabel("-")
        self.source_label.setWordWrap(True)
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setFormat("0%")

        self.details_grid = QFormLayout()
        self.details_grid.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.dominant_value = QLabel("-")
        self.active_notes_value = QLabel("-")
        self.active_notes_value.setWordWrap(True)
        self.duration_value = QLabel("-")
        self.pitch_summary_value = QLabel("-")
        self.pitch_summary_value.setWordWrap(True)

        self.details_grid.addRow("Type", self.kind_label)
        self.details_grid.addRow("Confiance", self.confidence_bar)
        self.details_grid.addRow("Note dominante", self.dominant_value)
        self.details_grid.addRow("Notes actives", self.active_notes_value)
        self.details_grid.addRow("Duree / sample rate", self.duration_value)
        self.details_grid.addRow("Pitch classes", self.pitch_summary_value)

        result_layout.addWidget(self.result_label, 0, 0)
        result_layout.addWidget(self.source_label, 1, 0)
        result_layout.addLayout(self.details_grid, 2, 0)

        self.candidates_box = QGroupBox("Candidats")
        candidates_layout = QVBoxLayout(self.candidates_box)
        self.candidates_table = QTableWidget(0, 4)
        self.candidates_table.setHorizontalHeaderLabels(("Rang", "Candidat", "Score", "Notes"))
        self.candidates_table.verticalHeader().setVisible(False)
        self.candidates_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.candidates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.candidates_table.setAlternatingRowColors(True)
        self.candidates_table.setWordWrap(False)
        self.candidates_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.candidates_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.candidates_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.candidates_table.setMinimumHeight(240)
        self.candidates_table.setMinimumWidth(980)
        candidates_header = self.candidates_table.horizontalHeader()
        candidates_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        candidates_header.setStretchLastSection(False)
        candidates_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        candidates_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        candidates_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.candidates_table.setColumnWidth(1, 280)
        self.candidates_table.setColumnWidth(3, 420)
        candidates_layout.addWidget(self.candidates_table)

        self.json_box = QGroupBox("JSON brut")
        json_layout = QVBoxLayout(self.json_box)
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setPlaceholderText("Le resultat JSON apparaitra ici.")
        self.json_view.setMinimumHeight(280)
        json_layout.addWidget(self.json_view)

        root.addWidget(self.result_box)
        self.result_box.setMinimumHeight(240)
        self.candidates_box.setMinimumHeight(290)
        self.json_box.setMinimumHeight(320)
        root.addWidget(self.candidates_box)
        root.addWidget(self.json_box)

    def _init_waveform_panel(self) -> None:
        try:
            waveform_cls = _require_waveform_widget()
            waveform = waveform_cls(None, _PrototypeWaveformContext(), auto_load=False)
            waveform.allow_cut_export = False
            waveform.disable_marker_add = True
            try:
                waveform.timer.stop()
            except Exception:
                pass
            for name in (
                "save_button",
                "undo_button",
                "redo_button",
                "marker_mode_button",
            ):
                button = getattr(waveform, name, None)
                if button is not None:
                    button.setVisible(False)
            self._waveform_widget = waveform
            self.waveform_host.addWidget(waveform)
            self.waveform_placeholder.hide()
            self.preview_box.hide()
            self._stop_preview_playback()
            self.waveform_status_label.setText(
                "Waveform editor SampleRod charge. Utilise ses boutons play/pause/stop/loop "
                "pour ecouter le sample et naviguer sur la waveform."
            )
        except Exception as exc:
            self._waveform_error = str(exc)
            self.preview_box.show()
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
            QLineEdit, QPlainTextEdit, QTableWidget, QSpinBox { background: #101318; border: 1px solid #303644; border-radius: 10px; padding: 8px; selection-background-color: #4bb6b7; }
            QTableWidget { gridline-color: #2a303c; }
            QHeaderView::section { background: #222733; color: #eef1f6; border: none; border-bottom: 1px solid #303644; padding: 8px; }
            QPushButton { background: #2a3140; border: 1px solid #3c4659; border-radius: 10px; padding: 9px 14px; }
            QPushButton:hover { background: #333d4f; }
            QPushButton#PrimaryButton { background: #d1a142; color: #171a20; border-color: #d1a142; font-weight: 700; }
            QPushButton#PrimaryButton:hover { background: #ddb257; }
            QProgressBar { background: #101318; border: 1px solid #303644; border-radius: 10px; text-align: center; min-height: 18px; }
            QProgressBar::chunk { border-radius: 9px; background: #4bb6b7; }
            QLabel#TitleLabel { font-weight: 700; }
            QLabel#ResultLabel { font-weight: 700; color: #f0c05a; }
            QLabel#StatusLabel { color: #9ba6ba; }
            """
        )

    def _restore_state(self) -> None:
        last_path = self._settings.value("last_path", "", type=str)
        if last_path:
            self.path_input.setText(last_path)
            self._sync_preview_path(last_path)
            self._sync_waveform_path(last_path)
        self._sync_dependency_state()

    def _sync_dependency_state(self) -> None:
        self._dependency_error = get_analysis_dependency_error()
        if not self._dependency_error:
            return
        self.analyze_button.setEnabled(False)
        self.top_n_spin.setEnabled(False)
        self.status_label.setText(self._dependency_error)
        self.json_view.setPlainText(
            "Analyse indisponible tant que les dependances audio ne sont pas installees.\n\n"
            "Commande conseillee:\n"
            "python -m pip install -r requirements.txt"
        )

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

        self._stop_preview_playback()
        self._shutdown_audio_backend()
        if self._waveform_widget is not None:
            try:
                self._waveform_widget.stop_audio()
            except Exception:
                pass
        super().closeEvent(event)

    def _browse_file(self) -> None:
        start_dir = self._current_browse_dir()
        filter_text = "Audio (*.wav *.mp3 *.flac *.ogg *.aif *.aiff *.m4a)"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir un sample audio",
            start_dir,
            filter_text,
        )
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
        self.path_input.setText(path)
        resolved = Path(path).expanduser()
        self._settings.setValue("last_path", str(resolved))
        if resolved.exists():
            self._settings.setValue("last_dir", str(resolved.parent))
        self._sync_preview_path(str(resolved))
        self._sync_waveform_path(str(resolved))
        self._populate_note_segments(())
        self.status_label.setText("Sample selectionne. Clique sur Analyser.")

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
            QMessageBox.warning(
                self,
                "Format non supporte",
                "Selectionne un fichier audio supporte: wav, mp3, flac, ogg, aif, aiff, m4a.",
            )
            return

        if self._worker and self._worker.isRunning():
            return

        self._set_busy(True, f"Analyse en cours sur {source.name}...")
        self._worker = AnalysisWorker(str(source), int(self.top_n_spin.value()), self)
        self._worker.succeeded.connect(self._on_analysis_success)
        self._worker.failed.connect(self._on_analysis_failure)
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.start()

    def _sync_preview_path(self, path: str) -> None:
        resolved = Path(path).expanduser()
        self._stop_preview_playback()
        self._preview_path = str(resolved)
        self._preview_duration_s = self._read_audio_duration(resolved)
        self.preview_progress.setValue(0)
        self.preview_time_label.setText(self._format_time_pair(0, self._preview_duration_s))
        if not resolved.exists():
            self.preview_status_label.setText("Fichier introuvable.")
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            return
        if resolved.suffix.lower() not in AUDIO_EXTENSIONS:
            self.preview_status_label.setText("Format audio non supporte pour le preview.")
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            return
        if self._audio_error:
            self.preview_status_label.setText(self._audio_error)
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            return
        self.preview_status_label.setText(f"Pret a lire: {resolved.name}")
        self.play_button.setEnabled(True)
        self.play_button.setText("Play")
        self.stop_button.setEnabled(False)

    def _sync_waveform_path(self, path: str) -> None:
        resolved = Path(path).expanduser()
        if self._waveform_widget is None:
            self.waveform_status_label.setText(self._waveform_error or "Waveform editor indisponible.")
            return
        if not resolved.exists():
            self.waveform_status_label.setText("Fichier introuvable pour la waveform.")
            self._clear_waveform_markers()
            return
        if resolved.suffix.lower() not in AUDIO_EXTENSIONS:
            self.waveform_status_label.setText("Format audio non supporte pour la waveform.")
            self._clear_waveform_markers()
            return

        try:
            waveform_data, sample_rate, duration_s = self._load_audio_for_waveform(resolved)
            self._waveform_widget.audio_file_path = str(resolved)
            self._waveform_widget.set_waveform_data(waveform_data, sample_rate, duration_s)
            self._clear_waveform_markers()
            self.waveform_status_label.setText(
                "Waveform charge. Tu peux l'ecouter directement avec les controles du waveform, "
                "puis lancer l'analyse pour poser des markers."
            )
        except Exception as exc:
            self.waveform_status_label.setText(f"Chargement waveform impossible: {exc}")

    def _ensure_audio_backend(self) -> bool:
        if self._audio_error:
            return False
        if self._audio_initialized:
            return True
        try:
            pygame = _require_pygame()
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._audio_initialized = True
            return True
        except Exception as exc:
            self._audio_error = f"Preview audio indisponible: {exc}"
            self.preview_status_label.setText(self._audio_error)
            self.play_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            return False

    def _shutdown_audio_backend(self) -> None:
        if not self._audio_initialized:
            return
        try:
            pygame = _require_pygame()
            pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            pygame.mixer.quit()
        except Exception:
            pass
        self._audio_initialized = False

    def _toggle_preview_playback(self) -> None:
        if not self._preview_path:
            QMessageBox.warning(self, "Aucun sample", "Choisis d'abord un fichier audio.")
            return
        if not self._ensure_audio_backend():
            QMessageBox.warning(self, "Preview audio", self._audio_error or "Audio indisponible.")
            return

        try:
            pygame = _require_pygame()
            music = pygame.mixer.music
            if self._preview_paused:
                music.unpause()
                self._preview_paused = False
                self._playback_started_at_s = time.monotonic()
                self._playback_timer.start()
                self.play_button.setText("Pause")
                self.stop_button.setEnabled(True)
                self.preview_status_label.setText(f"Lecture: {Path(self._preview_path).name}")
                return

            if music.get_busy():
                self._pause_preview_playback()
                return

            music.load(self._preview_path)
            music.play()
            self._playback_base_ms = 0
            self._playback_started_at_s = time.monotonic()
            self._preview_paused = False
            self._playback_timer.start()
            self.play_button.setText("Pause")
            self.stop_button.setEnabled(True)
            self.preview_status_label.setText(f"Lecture: {Path(self._preview_path).name}")
            self._update_preview_progress()
        except Exception as exc:
            self.preview_status_label.setText(f"Impossible de lire le sample: {exc}")
            QMessageBox.critical(self, "Lecture impossible", str(exc))

    def _pause_preview_playback(self) -> None:
        if not self._audio_initialized:
            return
        try:
            pygame = _require_pygame()
            self._playback_base_ms = self._estimated_playback_ms()
            pygame.mixer.music.pause()
            self._preview_paused = True
            self._playback_started_at_s = None
            self._playback_timer.stop()
            self.play_button.setText("Resume")
            self.stop_button.setEnabled(True)
            self.preview_status_label.setText(f"Pause: {Path(self._preview_path).name}")
            self._update_preview_progress()
        except Exception as exc:
            self.preview_status_label.setText(f"Pause impossible: {exc}")

    def _stop_preview_playback(self) -> None:
        self._playback_timer.stop()
        if self._audio_initialized:
            try:
                pygame = _require_pygame()
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
            except Exception:
                pass
        self._playback_base_ms = 0
        self._playback_started_at_s = None
        self._preview_paused = False
        self.preview_progress.setValue(0)
        self.preview_time_label.setText(self._format_time_pair(0, self._preview_duration_s))
        self.play_button.setText("Play")
        has_preview = bool(self._preview_path) and not self._audio_error
        self.play_button.setEnabled(has_preview)
        self.stop_button.setEnabled(False)
        if self._preview_path:
            self.preview_status_label.setText(f"Pret a lire: {Path(self._preview_path).name}")

    def _estimated_playback_ms(self) -> int:
        if self._preview_paused or self._playback_started_at_s is None:
            return int(self._playback_base_ms)
        elapsed_ms = int((time.monotonic() - self._playback_started_at_s) * 1000)
        return int(self._playback_base_ms + elapsed_ms)

    def _update_preview_progress(self) -> None:
        current_ms = self._estimated_playback_ms()
        duration_ms = int(max(self._preview_duration_s, 0.0) * 1000)

        if duration_ms > 0:
            current_ms = min(current_ms, duration_ms)
            progress = int((current_ms / duration_ms) * 1000)
            self.preview_progress.setValue(progress)
        else:
            self.preview_progress.setValue(0)

        self.preview_time_label.setText(
            self._format_time_pair(current_ms / 1000.0, self._preview_duration_s)
        )

        if not self._audio_initialized or self._preview_paused:
            return

        try:
            pygame = _require_pygame()
            if not pygame.mixer.music.get_busy():
                self._stop_preview_playback()
        except Exception:
            self._stop_preview_playback()

    def _set_busy(self, busy: bool, status: str) -> None:
        self.path_input.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.analyze_button.setEnabled((not busy) and not self._dependency_error)
        self.top_n_spin.setEnabled((not busy) and not self._dependency_error)
        self.status_label.setText(status)

    def _on_analysis_success(self, payload: dict) -> None:
        result: DetectionResult = payload["scale_result"]
        note_segments = list(payload.get("note_segments") or [])
        note_segments_error = payload.get("note_segments_error")

        self._populate_result(result, note_segments, note_segments_error)
        self._populate_note_segments(note_segments)
        self._apply_note_segments_to_waveform(note_segments)

        if note_segments:
            self.status_label.setText(
                f"Analyse terminee. {len(note_segments)} segment(s) de note trouves."
            )
        elif note_segments_error:
            self.status_label.setText(
                "Analyse terminee, mais la segmentation de notes a echoue. "
                "Regarde le JSON pour le detail."
            )
        else:
            self.status_label.setText(
                "Analyse terminee. Aucune note stable n'a ete segmentee."
            )

    def _on_analysis_failure(self, message: str) -> None:
        self.status_label.setText(f"Echec de l'analyse: {message}")
        QMessageBox.critical(self, "Analyse impossible", message)

    def _on_analysis_finished(self) -> None:
        self._set_busy(False, self.status_label.text())
        self._worker = None
        if self._close_after_analysis:
            self._close_after_analysis = False
            QTimer.singleShot(0, self.close)

    def _populate_result(
        self,
        result: DetectionResult,
        note_segments: list[NoteSegment],
        note_segments_error: str | None,
    ) -> None:
        self.result_label.setText(result.label)
        self.kind_label.setText("Note" if result.kind == "note" else "Gamme")
        self.source_label.setText(result.source_path or "-")
        self.confidence_bar.setValue(int(round(result.confidence * 100)))
        self.confidence_bar.setFormat(f"{result.confidence * 100:.0f}%")
        self.dominant_value.setText(
            f"{result.dominant_note} ({result.dominant_note_confidence * 100:.0f}%)"
        )
        self.active_notes_value.setText(", ".join(result.active_notes) if result.active_notes else "-")
        self.duration_value.setText(f"{result.duration_s:.2f}s @ {result.sample_rate} Hz")
        self.pitch_summary_value.setText(self._format_pitch_summary(result))
        self._populate_candidates(result)
        self.json_view.setPlainText(
            json.dumps(
                {
                    "scale_result": result.to_dict(),
                    "note_segments": [segment.to_dict() for segment in note_segments],
                    "note_segments_error": note_segments_error,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    def _populate_candidates(self, result: DetectionResult) -> None:
        candidates = list(result.candidates)
        self.candidates_table.setRowCount(len(candidates))

        for row, candidate in enumerate(candidates):
            values = (
                str(row + 1),
                candidate.label,
                f"{candidate.score:.3f}",
                ", ".join(candidate.notes),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.candidates_table.setItem(row, column, item)

        self.candidates_table.resizeColumnsToContents()
        self._ensure_table_column_widths(
            self.candidates_table,
            {
                0: 56,
                1: 280,
                2: 92,
                3: 420,
            },
        )

    def _populate_note_segments(self, note_segments: list[NoteSegment] | tuple[NoteSegment, ...]) -> None:
        self._note_segments = list(note_segments)
        self.note_segments_table.clearSelection()
        self.note_segments_table.setRowCount(len(self._note_segments))

        if not self._note_segments:
            self.note_segments_summary_label.setText(
                "Aucune note segmentee. Le sample est peut-etre trop court, trop bruité, ou ambigu."
            )
            return

        mono_count = sum(1 for segment in self._note_segments if segment.kind == "mono")
        poly_count = sum(1 for segment in self._note_segments if segment.kind == "poly")
        for row, segment in enumerate(self._note_segments):
            values = (
                str(row + 1),
                segment.kind,
                segment.dominant_label,
                ", ".join(segment.active_notes) if segment.active_notes else segment.note,
                f"{segment.start_s:.3f}s",
                f"{segment.end_s:.3f}s",
                f"{segment.confidence:.2f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.note_segments_table.setItem(row, column, item)

        self.note_segments_summary_label.setText(
            f"{len(self._note_segments)} segment(s) detecte(s): "
            f"{mono_count} mono, {poly_count} poly. "
            "Clique une ligne pour selectionner la region correspondante."
        )
        self.note_segments_table.resizeColumnsToContents()
        self._ensure_table_column_widths(
            self.note_segments_table,
            {
                0: 56,
                1: 76,
                2: 130,
                3: 320,
                4: 100,
                5: 100,
                6: 80,
            },
        )

    def _on_note_segment_selected(self) -> None:
        row = self.note_segments_table.currentRow()
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
        except Exception:
            pass

    def _apply_note_segments_to_waveform(self, note_segments: list[NoteSegment]) -> None:
        if self._waveform_widget is None:
            return
        if getattr(self._waveform_widget, "waveform_data", None) is None:
            return

        self._clear_waveform_markers()
        if not note_segments:
            self.waveform_status_label.setText(
                "Waveform charge, mais aucune note stable n'a ete detectee pour poser des markers."
            )
            return

        self._waveform_widget._record_history = False
        try:
            for segment in note_segments:
                self._waveform_widget.add_marker(float(segment.start_s))
        finally:
            self._waveform_widget._record_history = True

        try:
            self._waveform_widget.history._commands = []
            self._waveform_widget.history._index = -1
        except Exception:
            pass

        marker_list = getattr(self._waveform_widget, "marker_list", None)
        if marker_list is not None:
            for row, segment in enumerate(note_segments):
                if row >= marker_list.count():
                    break
                item = marker_list.item(row)
                if item is None:
                    continue
                active_notes = ", ".join(segment.active_notes) if segment.active_notes else segment.note
                tooltip = (
                    f"{segment.kind.upper()} | dominant {segment.dominant_label} | "
                    f"notes {active_notes} | {segment.start_s:.3f}s -> {segment.end_s:.3f}s "
                    f"(conf {segment.confidence:.2f})"
                )
                item.setToolTip(tooltip)

        self.waveform_status_label.setText(
            f"{len(note_segments)} marker(s) poses sur la waveform. "
            "Clique dans la table ou sur la liste de markers pour naviguer."
        )

        if marker_list is not None and marker_list.count() > 0:
            first_item = marker_list.item(0)
            if first_item is not None:
                try:
                    self._waveform_widget.on_marker_list_clicked(first_item)
                except Exception:
                    pass

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
        except Exception:
            pass

        try:
            self._waveform_widget._refresh_marker_list()
        except Exception:
            pass

    def _format_pitch_summary(self, result: DetectionResult) -> str:
        strongest = sorted(
            result.pitch_classes.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        return " | ".join(f"{note}:{value:.2f}" for note, value in strongest)

    def _load_audio_for_waveform(self, path: Path):
        soundfile = _require_soundfile()
        samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
        if samples.shape[1] == 1:
            waveform_data = samples[:, 0]
        else:
            waveform_data = samples.T
        duration_s = float(samples.shape[0]) / float(sample_rate) if sample_rate else 0.0
        return waveform_data, int(sample_rate), duration_s

    def _read_audio_duration(self, path: Path) -> float:
        try:
            soundfile = _require_soundfile()
            info = soundfile.info(str(path))
            return float(info.duration or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _build_font(point_size: int, *, bold: bool = False) -> QFont:
        font = QFont()
        font.setPointSize(point_size)
        font.setBold(bold)
        return font

    @staticmethod
    def _ensure_table_column_widths(
        table: QTableWidget,
        minimums: dict[int, int],
    ) -> None:
        for column, minimum in minimums.items():
            table.setColumnWidth(column, max(table.columnWidth(column), minimum))

    @staticmethod
    def _format_time_pair(current_s: float, total_s: float) -> str:
        return f"{ScaleDetectorWindow._format_seconds(current_s)} / {ScaleDetectorWindow._format_seconds(total_s)}"

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        total = max(0, int(seconds))
        minutes, secs = divmod(total, 60)
        return f"{minutes:02d}:{secs:02d}"


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
        # SampleRod applique le theme tres tot pour eviter les warnings
        # QFont::setPointSize lors de la creation des widgets embarques.
        from frontend.styles import theme as _theme

        _theme.manager.apply()
    except Exception:
        pass

    return app


def launch_ui() -> int:
    app = _bootstrap_qt_app()
    window = ScaleDetectorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch_ui())
