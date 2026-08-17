from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReserveCapabilities:
    """Description pure des actions proposées par l'UI; aucune mutation."""

    can_preview: bool
    can_drag: bool
    can_rename: bool
    can_move: bool
    can_delete: bool
    can_unindex: bool
    can_analyze: bool
    can_open_waveform: bool
    has_database_record: bool


def reserve_capabilities_for(entry) -> ReserveCapabilities:
    if entry is None:
        return ReserveCapabilities(*(False,) * 9)

    has_path = bool(str(getattr(entry, "path", "") or "").strip())
    missing = bool(getattr(entry, "missing", False))
    indexed = bool(getattr(entry, "indexed", False))
    sample_id = getattr(entry, "sample_id", None)
    has_record = indexed or sample_id is not None
    available = has_path and not missing

    return ReserveCapabilities(
        can_preview=available,
        can_drag=available,
        can_rename=available,
        can_move=available,
        # Préserve l'action actuelle sur un Sample manquant : elle retire sa
        # fiche même si le fichier physique a déjà disparu.
        can_delete=has_path,
        can_unindex=has_record,
        can_analyze=has_record and available,
        can_open_waveform=available,
        has_database_record=has_record,
    )
