from __future__ import annotations

import os
import tempfile
import uuid

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from frontend.sample_gui.wave_form import WaveformWidget
from frontend.styles import theme

from .lab_artifact import LabArtifact
from .waveform_tool_dnd import has_supported_waveform_drop, resolve_waveform_drop_paths


class WaveformToolWidget(QWidget):
    artifactCreated = Signal(object)
    separationRequested = Signal(list)   # liste de chemins → stem separator

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._current_path: str | None = None
        self._waveform_widget: WaveformWidget | None = None
        self._drop_active = False
        self._build_ui()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("WaveformToolRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        self.title_label = QLabel("Waveform")
        self.title_label.setObjectName("WaveformToolTitle")

        self.subtitle_label = QLabel("Edition et capture de matiere a partir du fichier courant.")
        self.subtitle_label.setObjectName("WaveformToolSubtitle")
        self.subtitle_label.setWordWrap(True)

        self.current_file_label = QLabel("Aucun fichier charge")
        self.current_file_label.setObjectName("WaveformToolCurrentFile")
        self.current_file_label.setWordWrap(True)

        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        title_box.addWidget(self.current_file_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self.slice_button = QPushButton("Creer une slice")
        self.slice_button.setObjectName("WaveformToolAction")
        self.slice_button.clicked.connect(self.create_selection_artifact)

        self.current_file_button = QPushButton("Capturer le fichier courant")
        self.current_file_button.setObjectName("WaveformToolAction")
        self.current_file_button.clicked.connect(self.create_current_file_artifact)

        actions.addWidget(self.slice_button)
        actions.addWidget(self.current_file_button)

        header.addLayout(title_box, 1)
        header.addLayout(actions, 0)

        self.info_label = QLabel("Selectionne une matiere depuis la Reserve pour l'ouvrir ici.")
        self.info_label.setObjectName("WaveformToolInfo")
        self.info_label.setWordWrap(True)

        self.waveform_host = QWidget()
        self.waveform_host.setObjectName("WaveformToolHost")
        self.waveform_host.setAcceptDrops(True)
        self.waveform_host.installEventFilter(self)
        self.waveform_layout = QVBoxLayout(self.waveform_host)
        self.waveform_layout.setContentsMargins(0, 0, 0, 0)
        self.waveform_layout.setSpacing(0)

        layout.addLayout(header)
        layout.addWidget(self.info_label)
        layout.addWidget(self.waveform_host, 1)

        self._apply_styles()
        self._refresh_actions()

    def open_file(self, path: str) -> bool:
        normalized = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(normalized):
            return False
        if self._current_path == normalized and self._waveform_widget is not None:
            self.setFocus()
            return True

        self._current_path = normalized
        self.current_file_label.setText(normalized)
        self._refresh_info_message()
        self._replace_waveform_widget(normalized)
        self._refresh_actions()
        return True

    def current_path(self) -> str | None:
        return self._current_path

    def create_selection_artifact(self) -> None:
        waveform = self._waveform_widget
        if waveform is None or waveform.waveform_data is None or waveform.sample_rate is None:
            self._show_warning("Le waveform n'est pas encore pret.")
            return

        bounds = self._selection_bounds()
        if bounds is None:
            self._show_warning("Aucune selection exploitable. Cree une region ou utilise les markers.")
            return

        start_time, end_time = bounds
        audio = self._extract_segment(start_time, end_time)
        if audio.size == 0:
            self._show_warning("La slice est vide.")
            return

        base_name = os.path.splitext(os.path.basename(self._current_path or "slice"))[0]
        display_name = f"{base_name}_slice_{start_time:.2f}_{end_time:.2f}"
        temp_path = self._write_temp_snapshot(audio, int(waveform.sample_rate), display_name)
        artifact = LabArtifact(
            artifact_id=uuid.uuid4().hex,
            kind="slice",
            display_name=display_name,
            source_path=self._current_path or "",
            temp_path=temp_path,
            start_time=float(start_time),
            end_time=float(end_time),
            duration=float(end_time - start_time),
            persisted=False,
            origin="waveform_selection",
            sample_rate=int(waveform.sample_rate),
        )
        self.info_label.setText(f"Artefact cree: {display_name}")
        self.artifactCreated.emit(artifact)

    def create_current_file_artifact(self) -> None:
        waveform = self._waveform_widget
        if waveform is None or waveform.waveform_data is None or waveform.sample_rate is None:
            self._show_warning("Le waveform n'est pas encore pret.")
            return

        audio = np.asarray(waveform.waveform_data, dtype="float32").copy()
        duration = float(waveform.duration or 0.0)
        base_name = os.path.splitext(os.path.basename(self._current_path or "current_file"))[0]
        display_name = f"{base_name}_current"
        temp_path = self._write_temp_snapshot(audio, int(waveform.sample_rate), display_name)
        artifact = LabArtifact(
            artifact_id=uuid.uuid4().hex,
            kind="current_file",
            display_name=display_name,
            source_path=self._current_path or "",
            temp_path=temp_path,
            duration=duration,
            persisted=False,
            origin="waveform_current_file",
            sample_rate=int(waveform.sample_rate),
        )
        self.info_label.setText(f"Artefact cree: {display_name}")
        self.artifactCreated.emit(artifact)

    def _replace_waveform_widget(self, path: str) -> None:
        self._destroy_waveform_widget()

        waveform = WaveformWidget(path, self.app_context)
        waveform.setAcceptDrops(True)
        waveform.installEventFilter(self)
        waveform.separationRequested.connect(
            lambda p: self.separationRequested.emit([p])
        )
        self.waveform_layout.addWidget(waveform)
        self._waveform_widget = waveform

        loader = getattr(waveform, "loader", None)
        if loader is not None:
            loader.finished.connect(self._on_waveform_loaded)
        else:
            self._on_waveform_loaded()

    def _destroy_waveform_widget(self) -> None:
        if self._waveform_widget is None:
            return
        try:
            self._waveform_widget.removeEventFilter(self)
        except Exception:
            pass
        try:
            self._waveform_widget.stop_audio()
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
        self._refresh_info_message()
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        ready = bool(
            self._waveform_widget is not None
            and getattr(self._waveform_widget, "waveform_data", None) is not None
            and getattr(self._waveform_widget, "sample_rate", None)
        )
        self.slice_button.setEnabled(bool(self._current_path) and ready)
        self.current_file_button.setEnabled(bool(self._current_path) and ready)

    def _selection_bounds(self) -> tuple[float, float] | None:
        waveform = self._waveform_widget
        if waveform is None:
            return None
        region = getattr(waveform, "region", None)
        if region is not None:
            start, end = region.getRegion()
            if end > start:
                return float(start), float(end)

        markers = list(getattr(waveform, "markers", []) or [])
        if not markers:
            return None

        idx = int(getattr(waveform, "current_marker_idx", 0) or 0)
        idx = max(0, min(idx, len(markers) - 1))
        start = float(markers[idx])
        end = float(markers[idx + 1]) if idx + 1 < len(markers) else float(waveform.duration or 0.0)
        if end <= start:
            return None
        return start, end

    def _extract_segment(self, start_time: float, end_time: float):
        waveform = self._waveform_widget
        if waveform is None or waveform.waveform_data is None or waveform.sample_rate is None:
            return np.array([], dtype="float32")

        start_sample = int(float(start_time) * float(waveform.sample_rate))
        end_sample = int(float(end_time) * float(waveform.sample_rate))
        data = np.asarray(waveform.waveform_data)
        return data[start_sample:end_sample].astype("float32").copy()

    def _write_temp_snapshot(self, audio, sample_rate: int, display_name: str) -> str:
        filename = f"samplerod_{display_name}_{uuid.uuid4().hex[:8]}.wav"
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        sf.write(temp_path, audio, int(sample_rate))
        return temp_path

    def _show_warning(self, message: str) -> None:
        self.info_label.setText(message)
        QMessageBox.warning(self, "Waveform", message)

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if event_type == QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if event_type == QEvent.Type.DragLeave:
            return self._handle_drag_leave(event)
        if event_type == QEvent.Type.Drop:
            return self._handle_drop(event)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if self._handle_drag_enter(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._handle_drag_move(event):
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        if self._handle_drag_leave(event):
            return
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._handle_drop(event):
            return
        super().dropEvent(event)

    def _handle_drag_enter(self, event) -> bool:
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime):
            self._set_drop_active(False)
            return False
        paths = self._paths_from_mime(mime)
        if not paths:
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_move(self, event) -> bool:
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime):
            self._set_drop_active(False)
            return False
        paths = self._paths_from_mime(mime)
        if not paths:
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
        paths = self._paths_from_mime(event.mimeData())
        self._set_drop_active(False)
        if not paths:
            return False
        opened = any(self.open_file(path) for path in paths)
        if not opened:
            return False
        event.acceptProposedAction()
        self.setFocus()
        return True

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_waveform_drop_paths(
            mime,
            sample_path_lookup=self._path_for_sample_id,
        )

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        samples = self.app_context.sample_store.get_cached()
        sample = next((item for item in samples if int(getattr(item, "id", -1)) == int(sample_id)), None)
        path = getattr(sample, "path", "") if sample is not None else ""
        return str(path or "") or None

    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        self.waveform_host.setProperty("dropActive", active)
        self.waveform_host.style().unpolish(self.waveform_host)
        self.waveform_host.style().polish(self.waveform_host)
        self._refresh_info_message()

    def _refresh_info_message(self) -> None:
        if self._drop_active:
            self.info_label.setText("Depose un fichier ou un sample de la Reserve pour l'ouvrir ici.")
            return
        ready = bool(
            self._waveform_widget is not None
            and getattr(self._waveform_widget, "waveform_data", None) is not None
            and getattr(self._waveform_widget, "sample_rate", None)
        )
        if self._current_path is None:
            self.info_label.setText("Selectionne une matiere depuis la Reserve pour l'ouvrir ici.")
        elif ready:
            self.info_label.setText("Le fichier est pret. Cree une slice ou capture l'etat courant.")
        else:
            self.info_label.setText("Chargement du waveform...")

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#WaveformToolRoot {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QWidget#WaveformToolHost {{
                background: transparent;
                border: 1px dashed transparent;
                border-radius: 10px;
            }}
            QWidget#WaveformToolHost[dropActive="true"] {{
                background: {p.BG_CARD};
                border-color: {p.INFO};
            }}
            QLabel#WaveformToolTitle {{
                color: {p.TEXT};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#WaveformToolSubtitle,
            QLabel#WaveformToolCurrentFile,
            QLabel#WaveformToolInfo {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QPushButton#WaveformToolAction {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QPushButton#WaveformToolAction:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#WaveformToolAction:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER_LIGHT};
            }}
            """
        )
