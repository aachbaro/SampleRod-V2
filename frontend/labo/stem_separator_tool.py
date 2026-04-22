from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.services.audio_metadata import collect_audio_file_metadata, normalize_audio_path
from frontend.styles import theme

from .audio_drop import has_supported_audio_drop, resolve_audio_drop_paths
from .lab_artifact import LabArtifact


class StemSeparatorToolWidget(QWidget):
    artifactCreated = Signal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.service = self.app_context.stem_separator
        self._qs = QSettings("SampleRod", "Main")
        self._drop_active = False
        self._pending_count = 0
        self._current_source = ""
        self._build_ui()
        self._restore_settings()
        self._bind_signals()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("StemToolRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)

        self.title_label = QLabel("Stem Separation")
        self.title_label.setObjectName("StemToolTitle")

        self.subtitle_label = QLabel(
            "Depose une matiere sonore dans la zone du haut. Elle est separee, puis les stems descendent dans les artefacts."
        )
        self.subtitle_label.setObjectName("StemToolSubtitle")
        self.subtitle_label.setWordWrap(True)

        header.addWidget(self.title_label)
        header.addWidget(self.subtitle_label)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("StemToolCombo")
        for model in self.service.available_models:
            self.model_combo.addItem(model, model)

        self.output_button = QPushButton("Dossier de travail...")
        self.output_button.setObjectName("StemToolAction")
        self.output_button.clicked.connect(self._choose_workspace_dir)

        self.output_label = QLabel("")
        self.output_label.setObjectName("StemToolOutput")
        self.output_label.setWordWrap(True)

        self.cancel_button = QPushButton("Annuler le courant")
        self.cancel_button.setObjectName("StemToolAction")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.service.cancel_current)

        controls.addWidget(self.model_combo, 0)
        controls.addWidget(self.output_button, 0)
        controls.addWidget(self.output_label, 1)
        controls.addWidget(self.cancel_button, 0)

        self.status_label = QLabel("Preparation du stem separator...")
        self.status_label.setObjectName("StemToolStatus")
        self.status_label.setWordWrap(True)

        self.drop_zone = QWidget()
        self.drop_zone.setObjectName("StemToolDropZone")
        self.drop_zone.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.installEventFilter(self)

        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(18, 18, 18, 18)
        drop_layout.setSpacing(6)

        self.drop_title = QLabel("Zone de decantation")
        self.drop_title.setObjectName("StemToolDropTitle")

        self.drop_help = QLabel(
            "Glisse un sample depuis la Reserve ou un fichier audio externe ici pour lancer la separation."
        )
        self.drop_help.setObjectName("StemToolDropHelp")
        self.drop_help.setWordWrap(True)

        drop_layout.addWidget(self.drop_title)
        drop_layout.addWidget(self.drop_help)
        drop_layout.addStretch(1)

        layout.addLayout(header)
        layout.addLayout(controls)
        layout.addWidget(self.status_label)
        layout.addWidget(self.drop_zone, 1)

        self._apply_styles()

    def _bind_signals(self) -> None:
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.service.statusChanged.connect(self._set_status)
        self.service.initialized.connect(self._on_initialized)
        self.service.fileStarted.connect(self._on_file_started)
        self.service.fileFinished.connect(self._on_file_finished)
        self.service.fileFailed.connect(self._on_file_failed)
        self.service.queueIdle.connect(self._on_queue_idle)

    def enqueue_paths(self, paths: list[str]) -> int:
        count = self.service.enqueue_paths(paths)
        if count > 0:
            self._pending_count += count
            self._refresh_status()
        return count

    def eventFilter(self, watched, event):
        event_type = event.type()
        if watched is self.drop_zone:
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

    def _restore_settings(self) -> None:
        saved_model = self._qs.value("labo_stem_model", self.service.model_name, type=str)
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index) == saved_model:
                self.model_combo.setCurrentIndex(index)
                break

        workspace_dir = self._qs.value("labo_stem_workspace_dir", "", type=str)
        if not workspace_dir or not os.path.isdir(workspace_dir):
            workspace_dir = os.path.join(tempfile.gettempdir(), "SampleRod", "stem_workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        self._set_workspace_dir(workspace_dir)
        self._refresh_status()

    def _choose_workspace_dir(self) -> None:
        start_dir = self.service.output_dir or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier de travail des stems", start_dir)
        if folder:
            self._set_workspace_dir(folder)
            self._set_status("Dossier de travail mis a jour.")

    def _set_workspace_dir(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        os.makedirs(normalized, exist_ok=True)
        self.service.set_output_dir(normalized)
        self._qs.setValue("labo_stem_workspace_dir", normalized)
        self.output_label.setText(normalized)
        self.output_label.setToolTip(normalized)

    def _on_model_changed(self, _index: int) -> None:
        model = self.model_combo.currentData()
        if not model:
            return
        self.service.set_model(str(model))
        self._qs.setValue("labo_stem_model", str(model))
        self._refresh_status()

    def _on_initialized(self, ok: bool, message: str) -> None:
        if not ok:
            self.cancel_button.setEnabled(False)
        self._set_status(message)

    def _on_file_started(self, path: str) -> None:
        self._current_source = path
        self.cancel_button.setEnabled(True)
        self._refresh_status()

    def _on_file_finished(self, source_path: str, stem_dir: str) -> None:
        self._current_source = ""
        self._pending_count = max(0, self._pending_count - 1)
        self.cancel_button.setEnabled(self._pending_count > 0)
        self._emit_stem_artifacts(source_path, stem_dir)
        self._refresh_status(extra=f"Stems prets pour {Path(source_path).name}")

    def _on_file_failed(self, source_path: str, _message: str) -> None:
        self._current_source = ""
        self._pending_count = max(0, self._pending_count - 1)
        self.cancel_button.setEnabled(self._pending_count > 0)
        self._refresh_status(extra=f"Echec sur {Path(source_path).name}")

    def _on_queue_idle(self) -> None:
        self._current_source = ""
        self.cancel_button.setEnabled(False)
        self._refresh_status()

    def _emit_stem_artifacts(self, source_path: str, stem_dir: str) -> None:
        source_path = normalize_audio_path(source_path)
        stem_dir = normalize_audio_path(stem_dir)
        for stem_file in sorted(Path(stem_dir).glob("*.wav")):
            stem_path = normalize_audio_path(str(stem_file))
            try:
                metadata = collect_audio_file_metadata(stem_path, include_rms=False)
                duration = float(metadata.duration or 0.0)
            except Exception:
                duration = 0.0
            artifact = LabArtifact(
                artifact_id=f"stem::{stem_path}",
                kind="stem",
                display_name=f"{stem_file.stem} ({Path(source_path).stem})",
                source_path=source_path,
                temp_path=stem_path,
                duration=duration,
                persisted=False,
                origin="stem_separation",
                metadata={
                    "stem_name": stem_file.stem,
                    "workspace_dir": stem_dir,
                },
            )
            self.artifactCreated.emit(artifact)

    def _handle_drag_enter(self, event) -> bool:
        mime = event.mimeData()
        if not has_supported_audio_drop(mime):
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
        return self._handle_drag_enter(event)

    def _handle_drag_leave(self, event) -> bool:
        self._set_drop_active(False)
        event.accept()
        return True

    def _handle_drop(self, event) -> bool:
        paths = self._paths_from_mime(event.mimeData())
        self._set_drop_active(False)
        if not paths:
            return False
        count = self.enqueue_paths(paths)
        if count <= 0:
            return False
        event.acceptProposedAction()
        return True

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_audio_drop_paths(
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
        self.drop_zone.setProperty("dropActive", active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self._refresh_status()

    def _refresh_status(self, *, extra: str = "") -> None:
        if extra:
            self.status_label.setText(extra)
            return
        if not self.service.is_available():
            self.status_label.setText(self.service.availability_error() or "Stem separator indisponible.")
            return
        if self._drop_active:
            self.status_label.setText("Depose le fichier pour le faire descendre vers les artefacts.")
            return
        if self._current_source:
            self.status_label.setText(
                f"Separation en cours: {Path(self._current_source).name} | En attente: {self._pending_count}"
            )
            return
        if self._pending_count > 0:
            self.status_label.setText(f"En attente: {self._pending_count} fichier(s).")
            return
        workspace = self.service.output_dir or "(aucun dossier)"
        self.status_label.setText(f"Pret. Les stems temporaires tombent dans: {workspace}")

    def _set_status(self, text: str) -> None:
        if text:
            self.status_label.setText(text)

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#StemToolRoot {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#StemToolTitle {{
                color: {p.TEXT};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#StemToolSubtitle,
            QLabel#StemToolOutput,
            QLabel#StemToolStatus,
            QLabel#StemToolDropHelp {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#StemToolDropTitle {{
                color: {p.TEXT};
                font-size: 14px;
                font-weight: 700;
            }}
            QWidget#StemToolDropZone {{
                background: {p.BG_CARD};
                border: 1px dashed {p.BORDER_LIGHT};
                border-radius: 12px;
            }}
            QWidget#StemToolDropZone[dropActive="true"] {{
                border-color: {p.INFO};
                background: {p.BG_HOVER};
            }}
            QPushButton#StemToolAction,
            QComboBox#StemToolCombo {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QPushButton#StemToolAction:hover,
            QComboBox#StemToolCombo:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#StemToolAction:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER_LIGHT};
            }}
            """
        )
