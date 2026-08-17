from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DragKind(str, Enum):
    AUDIO_FILE = "audio_file"
    AUDIO_SELECTION = "audio_selection"
    STEM = "stem"
    ARTIFACT = "artifact"
    MULTIPLE_AUDIO = "multiple_audio_files"


class MaterialStatus(str, Enum):
    SOURCE = "source"
    DERIVED = "derived"
    ARTIFACT = "artifact"


class MaterialOperation(str, Enum):
    SELECTION = "selection"
    STEM_SEPARATION = "stem_separation"
    BREAK_EXTRACTION = "break_extraction"
    COMPOSITION = "composition"
    IMPORT = "import"
    MIX = "mix"
    ARTIFACT_CREATION = "artifact_creation"


@dataclass(frozen=True, slots=True)
class DragProvenance:
    source_path: str = ""
    operation: MaterialOperation | None = None


@dataclass(frozen=True, slots=True)
class AudioSelection:
    start_seconds: float
    end_seconds: float
    source_path: str = ""
    sample_rate: int | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass(frozen=True, slots=True)
class DragItem:
    item_id: str = ""
    path: str = ""
    display_name: str = ""
    duration: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DragPayload:
    kind: DragKind
    items: tuple[DragItem, ...]
    source_id: str = ""
    source_module: str = ""
    selection: AudioSelection | None = None
    status: MaterialStatus | None = None
    provenance: DragProvenance | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        # Compatibilite des payloads v1 crees avant l'ajout du statut. Les
        # sources connues de l'application le renseignent explicitement.
        if self.status is None:
            object.__setattr__(self, "status", infer_material_status(self.kind))

    @property
    def is_multiple(self) -> bool:
        return len(self.items) > 1 or self.kind == DragKind.MULTIPLE_AUDIO

    @property
    def display_name(self) -> str:
        if self.is_multiple:
            return f"{len(self.items)} fichiers audio"
        return self.items[0].display_name if self.items else "Audio"

    @property
    def duration(self) -> float | None:
        if self.selection is not None:
            return self.selection.duration
        values = [item.duration for item in self.items if item.duration is not None]
        return sum(values) if values else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "kind": self.kind.value,
            "items": [asdict(item) for item in self.items],
            "source_id": self.source_id,
            "source_module": self.source_module,
            "selection": asdict(self.selection) if self.selection else None,
            "status": self.status.value if self.status else None,
            "provenance": _provenance_to_dict(self.provenance),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DragPayload":
        if int(raw.get("version", 0)) != 1:
            raise ValueError("Version de DragPayload non supportee")
        kind = DragKind(str(raw["kind"]))
        items = tuple(
            DragItem(
                item_id=str(item.get("item_id", "")),
                path=str(item.get("path", "")),
                display_name=str(item.get("display_name", "")),
                duration=float(item["duration"]) if item.get("duration") is not None else None,
                metadata=dict(item.get("metadata") or {}),
            )
            for item in (raw.get("items") or []) if isinstance(item, dict)
        )
        selection_raw = raw.get("selection")
        selection = None
        if isinstance(selection_raw, dict):
            selection = AudioSelection(
                start_seconds=float(selection_raw.get("start_seconds", 0.0)),
                end_seconds=float(selection_raw.get("end_seconds", 0.0)),
                source_path=str(selection_raw.get("source_path", "")),
                sample_rate=int(selection_raw["sample_rate"])
                if selection_raw.get("sample_rate") is not None else None,
            )
        status_raw = raw.get("status")
        status = MaterialStatus(str(status_raw)) if status_raw else None
        provenance_raw = raw.get("provenance")
        provenance = None
        if isinstance(provenance_raw, dict):
            operation_raw = provenance_raw.get("operation")
            provenance = DragProvenance(
                source_path=str(provenance_raw.get("source_path", "")),
                operation=MaterialOperation(str(operation_raw)) if operation_raw else None,
            )
        return cls(
            kind=kind, items=items, source_id=str(raw.get("source_id", "")),
            source_module=str(raw.get("source_module", "")), selection=selection,
            status=status, provenance=provenance,
            metadata=dict(raw.get("metadata") or {}), version=1,
        )


def infer_material_status(kind: DragKind) -> MaterialStatus:
    """Fallback de compatibilite ; les producteurs connus sont explicites."""
    if kind is DragKind.ARTIFACT:
        return MaterialStatus.ARTIFACT
    if kind in (DragKind.AUDIO_SELECTION, DragKind.STEM):
        return MaterialStatus.DERIVED
    return MaterialStatus.SOURCE


def source_promotion_metadata(payload: DragPayload) -> dict[str, Any]:
    """Provenance légère d'une nouvelle SOURCE créée depuis un dérivé."""
    provenance: dict[str, Any] = {
        "previous_status": payload.status.value if payload.status else "",
        "previous_kind": payload.kind.value,
        "operation": MaterialOperation.IMPORT.value,
        "source_path": (
            payload.provenance.source_path if payload.provenance
            else payload.selection.source_path if payload.selection else ""
        ),
    }
    if payload.selection is not None:
        provenance["start_seconds"] = payload.selection.start_seconds
        provenance["end_seconds"] = payload.selection.end_seconds
    return {
        "material_status": MaterialStatus.SOURCE.value,
        "provenance": provenance,
    }


def _provenance_to_dict(provenance: DragProvenance | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return {
        "source_path": provenance.source_path,
        "operation": provenance.operation.value if provenance.operation else None,
    }
