from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from frontend.labo.artifact_store import ensure_lab_artifact_store
from frontend.labo.artifact_tray import ArtifactTrayWidget
from frontend.labo.lab_artifact import artifact_file_path


class ArtifactModule(QWidget):
    """Navigateur d'artefacts pour l'atelier modulaire."""

    openPathsRequested = Signal(list)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.artifact_store = ensure_lab_artifact_store(app_context, self)
        self._build_ui()
        self._bind_signals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tray = ArtifactTrayWidget(self.app_context)
        self.tray.set_artifacts(self.artifact_store.all_artifacts())
        layout.addWidget(self.tray, 1)

    def _bind_signals(self) -> None:
        self.artifact_store.artifactUpserted.connect(self.tray.upsert_artifact)
        self.artifact_store.artifactRemoved.connect(self.tray.remove_artifact)
        self.tray.saveArtifactRequested.connect(self._save_artifact)
        self.tray.openArtifactRequested.connect(self._open_artifact)
        self.tray.removeArtifactRequested.connect(self.artifact_store.remove)

    def _save_artifact(self, artifact_id: str) -> None:
        artifact = self.artifact_store.artifact(artifact_id)
        if artifact is None:
            return

        target_dir = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier pour l'artefact",
            self.artifact_store.default_export_dir(artifact),
        )
        if target_dir:
            self.artifact_store.save_to_directory(artifact_id, target_dir)

    def _open_artifact(self, artifact_id: str) -> None:
        artifact = self.artifact_store.artifact(artifact_id)
        path = artifact_file_path(artifact) if artifact is not None else ""
        if path and os.path.isfile(path):
            self.openPathsRequested.emit([path])
