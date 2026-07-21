from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, QSettings, Signal

from .lab_artifact import LabArtifact, artifact_file_path, build_artifact_filename

ARTIFACT_MIME = "application/x-samplerod-artifact"


class LabArtifactStore(QObject):
    """Source de verite des artefacts produits par le Labo."""

    artifactUpserted = Signal(object)
    artifactRemoved = Signal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._settings = QSettings("SampleRod", "Main")
        self._artifacts: dict[str, LabArtifact] = {}

    def all_artifacts(self) -> list[LabArtifact]:
        return list(self._artifacts.values())

    def artifact(self, artifact_id: str) -> LabArtifact | None:
        return self._artifacts.get(str(artifact_id or ""))

    def resolve_path(self, artifact_id: str) -> str | None:
        artifact = self.artifact(artifact_id)
        path = artifact_file_path(artifact) if artifact is not None else ""
        if path and os.path.isfile(path):
            return path
        return None

    def upsert(self, artifact: LabArtifact) -> None:
        if artifact is None or not getattr(artifact, "artifact_id", ""):
            return
        self._artifacts[artifact.artifact_id] = artifact
        self.artifactUpserted.emit(artifact)

    def remove(self, artifact_id: str, delete_from_disk: bool = False) -> bool:
        artifact = self._artifacts.pop(str(artifact_id or ""), None)
        if artifact is None:
            return False

        self._stop_preview_if_needed(artifact)
        if delete_from_disk:
            self._delete_artifact_file(artifact)

        self.artifactRemoved.emit(artifact.artifact_id)
        return True

    def default_export_dir(self, artifact: LabArtifact) -> str:
        last_dir = self._settings.value("labo_last_artifact_dir", "", type=str)
        if isinstance(last_dir, str) and last_dir and os.path.isdir(last_dir):
            return last_dir

        source_folder = os.path.dirname(artifact.source_path or "")
        if source_folder and os.path.isdir(source_folder):
            return source_folder

        libraries = getattr(self.app_context.settings, "libraries", []) or []
        if libraries:
            path = getattr(sorted(libraries, key=lambda lib: lib.position)[0], "path", "")
            if path and os.path.isdir(path):
                return path

        return os.path.expanduser("~")

    def save_to_directory(self, artifact_id: str, target_dir: str) -> str | None:
        artifact = self.artifact(artifact_id)
        source_path = artifact_file_path(artifact) if artifact is not None else ""
        if artifact is None or not source_path or not os.path.isfile(source_path):
            return None

        target_dir = os.path.normpath(os.path.abspath(target_dir))
        if not os.path.isdir(target_dir):
            return None

        self._settings.setValue("labo_last_artifact_dir", target_dir)

        target_path = self._unique_target_path(
            target_dir,
            build_artifact_filename(artifact),
        )
        shutil.copy2(source_path, target_path)
        self.app_context.sample_store.add(target_path)

        artifact.persisted = True
        artifact.metadata["saved_path"] = target_path
        self.upsert(artifact)
        return target_path

    def attach_mime_data(self, mime: QMimeData, artifact_id: str) -> bool:
        artifact_id = str(artifact_id or "").strip()
        if mime is None or not artifact_id:
            return False
        mime.setData(ARTIFACT_MIME, artifact_id.encode("utf-8"))
        path = self.resolve_path(artifact_id)
        if path:
            from PySide6.QtCore import QUrl

            mime.setUrls([QUrl.fromLocalFile(path)])
        return True

    def artifact_ids_from_mime(self, mime: QMimeData) -> list[str]:
        if mime is None or not mime.hasFormat(ARTIFACT_MIME):
            return []
        try:
            raw = bytes(mime.data(ARTIFACT_MIME)).decode("utf-8", errors="ignore")
        except Exception:
            return []
        artifact_id = raw.strip()
        if not artifact_id:
            return []
        return [artifact_id]

    def paths_from_mime(self, mime: QMimeData) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for artifact_id in self.artifact_ids_from_mime(mime):
            path = self.resolve_path(artifact_id)
            if not path:
                continue
            normalized = os.path.normcase(os.path.normpath(path))
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(path)
        return paths

    @staticmethod
    def _unique_target_path(folder: str, filename: str) -> str:
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(folder, filename)
        if not os.path.exists(candidate):
            return candidate

        index = 2
        while True:
            candidate = os.path.join(folder, f"{base}_{index}{ext}")
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _stop_preview_if_needed(self, artifact: LabArtifact) -> None:
        path = artifact_file_path(artifact)
        if not path:
            return

        player = getattr(self.app_context, "audio_player", None)
        current_path = getattr(player, "current_sample_path", "") if player is not None else ""
        current = os.path.normcase(os.path.normpath(current_path or ""))
        target = os.path.normcase(os.path.normpath(path))
        if player is not None and current and current == target:
            try:
                player.clear_audio()
            except Exception:
                pass

    def _delete_artifact_file(self, artifact: LabArtifact) -> None:
        path = str(getattr(artifact, "temp_path", "") or "")
        if not path:
            return

        candidate = Path(path)
        if not candidate.is_file():
            return

        try:
            candidate.unlink()
        except OSError:
            pass


def ensure_lab_artifact_store(app_context, parent=None) -> LabArtifactStore:
    store = getattr(app_context, "lab_artifact_store", None)
    if isinstance(store, LabArtifactStore):
        return store

    store = LabArtifactStore(app_context, parent=parent)
    setattr(app_context, "lab_artifact_store", store)
    return store
