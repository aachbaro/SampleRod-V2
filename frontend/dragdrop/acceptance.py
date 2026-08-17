from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DropVisualState(str, Enum):
    NORMAL = "normal"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    HOVER = "hover"


class DropAction(str, Enum):
    OPEN = "open"
    LOAD_BREAK = "load_break"
    IMPORT_AS_SOURCE = "import_as_source"
    CREATE_ARTIFACT = "create_artifact"
    SEPARATE_STEMS = "separate_stems"
    ADD_TO_COMPOSITION = "add_to_composition"
    MOVE_TO_BIN = "move_to_bin"
    ADD_TO_MIX = "add_to_mix"
    COPY_TO_DIRECTORY = "copy_to_directory"


@dataclass(frozen=True, slots=True)
class DropAcceptance:
    accepted: bool
    action: DropAction | str = ""
    label: str = ""
    reason: str = ""

    @classmethod
    def accept(cls, action: DropAction | str, label: str) -> "DropAcceptance":
        return cls(True, action=action, label=label)

    @classmethod
    def reject(cls, reason: str = "") -> "DropAcceptance":
        return cls(False, reason=reason)
