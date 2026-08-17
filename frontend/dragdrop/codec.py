from __future__ import annotations

import json
import os

from PySide6.QtCore import QMimeData

from .payload import (
    DragItem, DragKind, DragPayload, DragProvenance,
    MaterialOperation, MaterialStatus,
)

PAYLOAD_MIME = "application/x-samplerod-drag-v1"


def attach_payload(mime: QMimeData, payload: DragPayload) -> None:
    """Ajoute le descripteur sans retirer URLs, NumPy ou anciens MIME."""
    encoded = json.dumps(payload.to_dict(), ensure_ascii=False, separators=(",", ":"))
    mime.setData(PAYLOAD_MIME, encoded.encode("utf-8"))


def payload_from_mime(mime: QMimeData | None) -> DragPayload | None:
    if mime is None:
        return None
    if mime.hasFormat(PAYLOAD_MIME):
        try:
            raw = json.loads(bytes(mime.data(PAYLOAD_MIME)).decode("utf-8"))
            if isinstance(raw, dict):
                return DragPayload.from_dict(raw)
        except Exception:
            return None
    # Adaptateur sans effet de bord pour les drags externes/anciens : les URLs
    # suffisent a fournir un langage visuel minimal.
    if mime.hasUrls():
        items = []
        for url in mime.urls():
            path = url.toLocalFile()
            if path:
                items.append(DragItem(path=path, display_name=os.path.basename(path)))
        if items:
            kind = DragKind.MULTIPLE_AUDIO if len(items) > 1 else DragKind.AUDIO_FILE
            return DragPayload(
                kind=kind,
                items=tuple(items),
                source_id="external",
                status=MaterialStatus.SOURCE,
                provenance=DragProvenance(
                    source_path=items[0].path if len(items) == 1 else "",
                    operation=MaterialOperation.IMPORT,
                ),
            )
    return None
