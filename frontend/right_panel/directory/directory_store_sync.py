"""
------------------------------------------------------------------------------
Directory Store Sync
------------------------------------------------------------------------------
Role
----
Ecoute les signaux du sample_store (SampleService) et maintient la liste du
DirectoryWidget synchronisee, sans recharger toute l'UI en permanence.

Signaux observes (SampleService)
--------------------------------
- sampleRenamed(id, old_path, new_path)
- sampleDeleted(id)
- sampleMoved(id, target_folder)

Pourquoi l'extraire ?
---------------------
Le DirectoryWidget a deja plusieurs responsabilites (UI + refresh + preview).
En sortant la synchronisation "store -> UI" dans un composant dedie:
- le widget redevient plus lisible
- on garde un endroit unique pour les mises a jour incrementales
- on peut tester/ajuster ces regles sans toucher au layout UI

Implementation
--------------
On implemente ceci comme un QObject parented au DirectoryWidget:
si le widget disparait, Qt coupe les connexions automatiquement.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import logging
from typing import Any

from PySide6.QtCore import QObject

logger = logging.getLogger("directory_store_sync")


class DirectoryStoreSync(QObject):
    def __init__(self, directory_widget: Any, sample_store: Any):
        super().__init__(directory_widget)
        self._w = directory_widget
        self._store = sample_store

        # Connexions directes aux signaux du store.
        try:
            self._store.sampleRenamed.connect(self.on_sample_renamed)
            self._store.sampleDeleted.connect(self.on_sample_deleted)
            self._store.sampleMoved.connect(self.on_sample_moved)
        except Exception as e:
            logger.info(f"[DirectoryStoreSync] connect error: {e}")

    # ------------------------------------------------------------------ slots
    def on_sample_renamed(self, sample_id: int, old_path: str, new_path: str):
        # Ne s'applique que si l'ancien fichier etait dans le dossier courant.
        if os.path.dirname(old_path) != getattr(self._w, "current_dir", None):
            return
        try:
            self._w._update_row(sample_id, new_path)
            self._schedule_status_refresh()
        except Exception:
            pass

    def on_sample_deleted(self, sample_id: int):
        try:
            self._w._remove_row(sample_id)
            self._schedule_status_refresh()
        except Exception:
            pass

    def on_sample_moved(self, sample_id: int, target_folder: str):
        # On recupere la nouvelle info depuis le cache du store.
        try:
            cached = self._store.get_cached()
        except Exception:
            cached = []

        sample = next((s for s in cached if getattr(s, "id", None) == sample_id), None)
        if not sample:
            return

        new_path = getattr(sample, "path", "")
        if not new_path:
            return

        current_dir = getattr(self._w, "current_dir", None)
        in_list = sample_id in getattr(self._w, "_items_by_id", {})

        if target_folder == current_dir:
            if in_list:
                try:
                    self._w._update_row(sample_id, new_path)
                    self._schedule_status_refresh()
                except Exception:
                    pass
            else:
                try:
                    self._w._add_row(new_path, sample_id)
                    self._schedule_status_refresh()
                except Exception:
                    pass
        else:
            if in_list:
                try:
                    self._w._remove_row(sample_id)
                    self._schedule_status_refresh()
                except Exception:
                    pass

    def _schedule_status_refresh(self):
        scheduler = getattr(self._w, "schedule_index_status_refresh", None)
        if callable(scheduler):
            scheduler()
            return
        try:
            self._w._refresh_index_status()
        except Exception:
            pass

