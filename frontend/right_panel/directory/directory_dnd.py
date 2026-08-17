"""
------------------------------------------------------------------------------
Directory Drag & Drop Helpers
------------------------------------------------------------------------------
Role
----
Centralise la logique DnD du "Directory tool" (Right Panel):
- Quels MIME types on accepte (slice / sample).
- Comment on traite un drop (delegation a DirectoryService + refresh UI).

Pourquoi un module dedie ?
--------------------------
Dans le code initial, la logique etait dupliquee entre:
- DirectoryWidget (parent)
- DirectoryListWidget (liste)

En centralisant ici, on garde:
- un comportement unique
- des logs coherents
- une base reutilisable quand on ajoutera d'autres outils (ex: Sample Composer)
  qui acceptent les memes MIME types.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QMimeData

from frontend.right_panel.composer.composer_dnd import has_audio_file_urls
from frontend.dragdrop.codec import PAYLOAD_MIME
from frontend.labo.artifact_store import ARTIFACT_MIME

logger = logging.getLogger("directory_dnd")

# MIME types custom utilises dans l'app (payload pickle cote source).
MIME_SAMPLE_SLICE_DATA = "application/x-sample-slice-data"
MIME_SAMPLE_CARD = "application/x-sample-card"


def accepts(mime: QMimeData) -> bool:
    """Retourne True si le mime contient un format supporte par l'import Directory."""
    return bool(
        mime.hasFormat(MIME_SAMPLE_SLICE_DATA)
        or mime.hasFormat(MIME_SAMPLE_CARD)
        or mime.hasFormat(PAYLOAD_MIME)
        or mime.hasFormat(ARTIFACT_MIME)
        or has_audio_file_urls(mime)
    )


def handle_drop(directory_widget: Any, mime: QMimeData) -> bool:
    """
    Traite un drop sur le DirectoryWidget.

    On attend que directory_widget expose:
    - current_dir: str
    - service.handle_drop(folder: str, mime: QMimeData)
    - refresh_list()

    Retourne True si le drop a ete traite, False sinon.
    """
    current_dir = getattr(directory_widget, "current_dir", "") or ""
    if not current_dir:
        logger.info("[DirectoryDnD] drop ignore (aucun dossier choisi)")
        return False

    if not accepts(mime):
        logger.info("[DirectoryDnD] drop refuse (mime non supporte)")
        return False

    # Ignore les drops depuis le même dossier (évite les copies/doublons inutiles)
    if mime.hasUrls():
        import os as _os
        same_folder_urls = [
            url for url in mime.urls()
            if url.isLocalFile() and _os.path.normpath(_os.path.dirname(url.toLocalFile()))
            == _os.path.normpath(current_dir)
        ]
        if same_folder_urls and len(same_folder_urls) == len([u for u in mime.urls() if u.isLocalFile()]):
            logger.info("[DirectoryDnD] drop ignore (source dans le meme dossier)")
            return False

    logger.info("[DirectoryDnD] drop accepte")
    try:
        directory_widget.service.handle_drop(current_dir, mime)
    except Exception as e:
        logger.info(f"[DirectoryDnD] handle_drop error: {e}")
        return False

    try:
        directory_widget.refresh_list()
    except Exception:
        pass

    return True
