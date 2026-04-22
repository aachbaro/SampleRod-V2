from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.services.directory_service import DirectoryAudioEntry
from frontend.styles import theme

ReserveSourceKind = Literal["filesystem", "history", "indexed"]

STATUS_NORMAL = "normal"
STATUS_NON_INDEXED = "non_indexed"
STATUS_NEEDS_ANALYSIS = "needs_analysis"
STATUS_MISSING = "missing"
STATUS_ALL = "all"

STATUS_ORDER = [
    STATUS_NORMAL,
    STATUS_NON_INDEXED,
    STATUS_NEEDS_ANALYSIS,
    STATUS_MISSING,
]

STATUS_LABELS = {
    STATUS_NORMAL: "Normal",
    STATUS_NON_INDEXED: "Non indexe",
    STATUS_NEEDS_ANALYSIS: "A analyser",
    STATUS_MISSING: "Fichier manquant",
}

STATUS_TONES = {
    STATUS_NORMAL: "neutral",
    STATUS_NON_INDEXED: "info",
    STATUS_NEEDS_ANALYSIS: "warning",
    STATUS_MISSING: "error",
}

SOURCE_LABELS = {
    "filesystem": "Dossiers",
    "history": "Historique",
    "indexed": "Indexe",
}


@dataclass(slots=True)
class ReserveEntry:
    source_kind: ReserveSourceKind
    path: str
    sample_id: int | None = None
    display_name: str = ""
    root_path: str | None = None
    folder_path: str | None = None
    duration: float | None = None
    rms_level: float | None = None
    status: str = STATUS_NORMAL
    needs_analysis: bool = False
    missing: bool = False
    indexed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def status_label(self) -> str:
        return reserve_status_label(self.status)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source_kind, self.source_kind)

    @property
    def folder_name(self) -> str:
        folder = self.folder_path or os.path.dirname(self.path)
        return os.path.basename(folder) or folder

    @property
    def root_name(self) -> str:
        if self.root_path:
            return os.path.basename(self.root_path) or self.root_path
        return self.source_label


def resolve_reserve_status(*, indexed: bool, missing: bool, needs_analysis: bool) -> str:
    if missing:
        return STATUS_MISSING
    if not indexed:
        return STATUS_NON_INDEXED
    if needs_analysis:
        return STATUS_NEEDS_ANALYSIS
    return STATUS_NORMAL


def reserve_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, STATUS_LABELS[STATUS_NORMAL])


def reserve_status_tone(status: str) -> str:
    return STATUS_TONES.get(status, STATUS_TONES[STATUS_NORMAL])


def reserve_status_badge_stylesheet(status: str) -> str:
    p = theme.manager.p
    tone = reserve_status_tone(status)
    fg = p.TEXT
    border = p.BORDER_LIGHT
    bg = p.BG_CARD
    if tone == "warning":
        fg = p.WARNING
        border = p.WARNING
    elif tone == "error":
        fg = p.ERROR
        border = p.ERROR
    elif tone == "info":
        fg = p.INFO
        border = p.INFO
    elif tone == "neutral":
        fg = p.TEXT_MUTED
        border = p.BORDER_LIGHT

    return (
        "QLabel {"
        f"color: {fg};"
        "font-size: 11px;"
        "font-weight: 600;"
        f"background: {bg};"
        f"border: 1px solid {border};"
        "border-radius: 10px;"
        "padding: 3px 8px;"
        "}"
    )


def apply_status_badge(label_widget, status: str) -> None:
    label_widget.setText(reserve_status_label(status))
    label_widget.setStyleSheet(reserve_status_badge_stylesheet(status))


def reserve_entry_matches_query(entry: ReserveEntry, query: str) -> bool:
    needle = " ".join((query or "").strip().lower().split())
    if not needle:
        return True

    haystack = " ".join(
        part.lower()
        for part in [
            entry.display_name,
            entry.path,
            entry.folder_path or "",
            entry.root_path or "",
            entry.source_label,
            entry.status_label,
        ]
        if part
    )
    return all(token in haystack for token in needle.split(" "))


def reserve_entry_matches_status(entry: ReserveEntry, status_filter: str) -> bool:
    if not status_filter or status_filter == STATUS_ALL:
        return True
    return entry.status == status_filter


def reserve_entry_from_sample(
    sample,
    *,
    source_kind: ReserveSourceKind,
    root_path: str | None = None,
    folder_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReserveEntry:
    path = getattr(sample, "path", "")
    missing = bool(getattr(sample, "missing", False))
    needs_analysis = bool(getattr(sample, "needs_analysis", False))
    return ReserveEntry(
        source_kind=source_kind,
        path=path,
        sample_id=int(getattr(sample, "id", 0)) if getattr(sample, "id", None) is not None else None,
        display_name=str(getattr(sample, "name", os.path.splitext(os.path.basename(path))[0])),
        root_path=root_path,
        folder_path=folder_path or os.path.dirname(path),
        duration=float(getattr(sample, "duration", 0.0) or 0.0),
        rms_level=(
            float(getattr(sample, "rms_level", 0.0))
            if getattr(sample, "rms_level", None) is not None
            else None
        ),
        status=resolve_reserve_status(indexed=True, missing=missing, needs_analysis=needs_analysis),
        needs_analysis=needs_analysis,
        missing=missing,
        indexed=True,
        metadata=dict(metadata or {}),
    )


def reserve_entry_from_directory(entry: DirectoryAudioEntry) -> ReserveEntry:
    return ReserveEntry(
        source_kind="filesystem",
        path=entry.path,
        sample_id=entry.sample_id,
        display_name=entry.name,
        folder_path=os.path.dirname(entry.path),
        duration=entry.duration,
        rms_level=entry.rms_level,
        status=resolve_reserve_status(
            indexed=entry.indexed,
            missing=entry.missing,
            needs_analysis=entry.needs_analysis,
        ),
        needs_analysis=bool(entry.needs_analysis),
        missing=bool(entry.missing),
        indexed=bool(entry.indexed),
        metadata={"directory_entry": entry},
    )
