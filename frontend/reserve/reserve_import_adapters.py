from __future__ import annotations

import os

from backend.services.audio_metadata import normalize_audio_path

from backend.services.reserve_import_service import (
    ReserveCopyPolicy,
    ReserveImportRequest,
    ReserveReimportPolicy,
)
from frontend.dragdrop import payload_from_mime
from frontend.labo.audio_drop import resolve_audio_drop_paths
from frontend.labo.artifact_store import ARTIFACT_MIME

MIME_SAMPLE_SLICE_DATA = "application/x-sample-slice-data"
MIME_SAMPLE_CARD = "application/x-sample-card"


def import_request_from_mime(
    mime,
    *,
    sample_path_lookup,
    artifact_path_lookup=None,
    destination: str | None = None,
    reimport: bool = False,
) -> ReserveImportRequest:
    """Décode les MIME modernes et historiques sans décider de l'import."""
    payload = payload_from_mime(mime)
    try:
        paths = resolve_audio_drop_paths(
            mime,
            sample_path_lookup=sample_path_lookup,
            artifact_path_lookup=artifact_path_lookup,
        )
    except Exception:
        paths = []
    if not paths and payload is not None:
        paths = [
            normalize_audio_path(item.path)
            for item in payload.items
            if item.path and os.path.isfile(normalize_audio_path(item.path))
        ]
    if not paths:
        # Très ancien adaptateur : certains MIME maison contenaient seulement
        # une liste UTF-8 de chemins, un par ligne.
        for mime_type in (MIME_SAMPLE_SLICE_DATA, MIME_SAMPLE_CARD):
            if not mime.hasFormat(mime_type):
                continue
            try:
                lines = bytes(mime.data(mime_type)).decode("utf-8").splitlines()
            except Exception:
                lines = []
            paths.extend(
                normalize_audio_path(line.strip())
                for line in lines
                if line.strip() and os.path.isfile(normalize_audio_path(line.strip()))
            )
    provenance = {}
    if payload is not None:
        if payload.provenance is not None:
            provenance["source_path"] = payload.provenance.source_path
            provenance["operation"] = (
                payload.provenance.operation.value if payload.provenance.operation else ""
            )
        if payload.selection is not None:
            provenance.setdefault("source_path", payload.selection.source_path)
            provenance["start_seconds"] = payload.selection.start_seconds
            provenance["end_seconds"] = payload.selection.end_seconds
    status = payload.status.value if payload and payload.status else "source"
    kind = payload.kind.value if payload else "audio_file"
    if payload is None and mime.hasFormat(MIME_SAMPLE_SLICE_DATA):
        status, kind = "derived", "audio_selection"
    elif payload is None and mime.hasFormat(ARTIFACT_MIME):
        status, kind = "artifact", "artifact"
    elif payload is None and mime.hasFormat(MIME_SAMPLE_CARD):
        status, kind = "source", "audio_file"
    return ReserveImportRequest(
        paths=tuple(paths),
        status=status,
        operation="import",
        kind=kind,
        provenance=provenance,
        destination=destination,
        copy_policy=ReserveCopyPolicy.COPY if destination else ReserveCopyPolicy.IN_PLACE,
        reimport_policy=(
            ReserveReimportPolicy.REINDEX if reimport else ReserveReimportPolicy.SKIP
        ),
    )
