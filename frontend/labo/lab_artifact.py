from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

LabArtifactKind = Literal["slice", "current_file", "stem"]


@dataclass(slots=True)
class LabArtifact:
    artifact_id: str
    kind: LabArtifactKind
    display_name: str
    source_path: str
    temp_path: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    duration: float = 0.0
    persisted: bool = False
    origin: str = ""
    sample_rate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def artifact_kind_label(kind: LabArtifactKind) -> str:
    if kind == "slice":
        return "Slice"
    if kind == "stem":
        return "Stem"
    return "Fichier courant"


def artifact_status_label(artifact: LabArtifact) -> str:
    return "Persiste" if artifact.persisted else "Temporaire"


def artifact_duration_label(duration: float) -> str:
    return f"{float(duration or 0.0):.2f}s"


def build_artifact_filename(artifact: LabArtifact, extension: str = ".wav") -> str:
    base = artifact.display_name.strip() or artifact_kind_label(artifact.kind)
    sanitized = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else "_" for ch in base)
    sanitized = "_".join(sanitized.split())
    if not sanitized:
        sanitized = artifact_kind_label(artifact.kind).lower().replace(" ", "_")

    if not sanitized.lower().endswith(extension.lower()):
        sanitized = f"{sanitized}{extension}"

    return sanitized


def artifact_source_name(artifact: LabArtifact) -> str:
    return os.path.basename(artifact.source_path) or artifact.source_path


def artifact_file_path(artifact: LabArtifact) -> str:
    candidate = artifact.temp_path or artifact.source_path
    return os.path.normpath(os.path.abspath(candidate)) if candidate else ""
