# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Ecoute les signaux du sample_store et applique les mises a jour incrementales
#   sur le DirectoryWidget sans recharger toute la liste.
# - Extrait pour garder DirectoryWidget lisible (UI + navigation uniquement).
#
# Signaux observes :
#   sampleRenamed(id, old_path, new_path) -> update_row()
#   sampleDeleted(id)                     -> _remove_row()
#   sampleMoved(id, target_folder)        -> _add_row() ou _remove_row()
#   sampleScaleAnalyzed(id)               -> refresh_list() debounce
#
# Debounce gamme :
#   Quand plusieurs fichiers sont analyses en rafale, un QTimer de 300 ms
#   groupe tous les evenements en un seul refresh_list().
#
# LIENS CLES
# - frontend/right_panel/directory/directory_widget.py : widget cible
# - backend/models/SampleLibrary.py                    : signaux sources
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import logging
from time import perf_counter
from typing import Any

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger("directory_store_sync")

# Delai de debounce pour les refreshs declenches par l'analyse de gamme.
# Plusieurs analyses peuvent se terminer en rafale : on attend que la
# derniere soit arrivee avant de reconstruire la liste (ms).
_SCALE_REFRESH_DEBOUNCE_MS = 300


class DirectoryStoreSync(QObject):
    """Synchronise le DirectoryWidget avec les signaux du sample_store.

    Instance parente du DirectoryWidget : quand le widget est detruit,
    Qt coupe les connexions automatiquement (pas besoin de disconnect manuel).
    """

    def __init__(self, directory_widget: Any, sample_store: Any):
        super().__init__(directory_widget)
        self._w = directory_widget
        self._store = sample_store

        # Timer de debounce pour grouper les refresh_list() en rafale.
        # Sans ca, analyser 50 fichiers d'un coup = 50 refresh_list() successifs
        # sur le thread principal => not responding.
        self._scale_refresh_timer = QTimer(self)
        self._scale_refresh_timer.setSingleShot(True)
        self._scale_refresh_timer.setInterval(_SCALE_REFRESH_DEBOUNCE_MS)
        self._scale_refresh_timer.timeout.connect(self._do_scale_refresh)

        # Connexions directes aux signaux du store.
        try:
            self._store.sampleRenamed.connect(self.on_sample_renamed)
            self._store.sampleDeleted.connect(self.on_sample_deleted)
            self._store.sampleMoved.connect(self.on_sample_moved)
            self._store.sampleScaleAnalyzed.connect(self.on_sample_scale_analyzed)
        except Exception as e:
            logger.info(f"[DirectoryStoreSync] connect error: {e}")

    # ------------------------------------------------------------------ slots

    def on_sample_renamed(self, sample_id: int, old_path: str, new_path: str):
        """Slot : met a jour la ligne si l'ancien fichier etait dans le dossier courant."""
        # Ne s'applique que si l'ancien fichier etait dans le dossier courant.
        if os.path.dirname(old_path) != getattr(self._w, "current_dir", None):
            return
        try:
            self._w._update_row(sample_id, new_path)
            self._schedule_status_refresh()
        except Exception:
            pass

    def on_sample_deleted(self, sample_id: int):
        """Slot : supprime la ligne correspondante de la liste."""
        start = perf_counter()
        try:
            self._w._remove_row(sample_id)
            self._schedule_status_refresh()
        except Exception:
            pass
        logger.info(
            "[DirectoryStoreSync][Perf] on_sample_deleted sample=%s current_dir=%s rows=%s total=%.1fms",
            sample_id,
            getattr(self._w, "current_dir", ""),
            getattr(getattr(self._w, "list_widget", None), "count", lambda: -1)(),
            (perf_counter() - start) * 1000.0,
        )

    def on_sample_moved(self, sample_id: int, target_folder: str):
        """Slot : ajoute la ligne si le sample arrive dans ce dossier, la retire sinon."""
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

    def on_sample_scale_analyzed(self, sample_id: int):
        """Slot : programme un refresh debounce si le sample est dans le dossier courant."""
        # Verifier que le sample est bien dans le dossier courant
        # avant de programmer un refresh (evite les refreshs inutiles).
        try:
            cached = self._store.get_cached()
        except Exception:
            cached = []

        sample = next((s for s in cached if getattr(s, "id", None) == sample_id), None)
        if sample is None:
            return

        sample_path = getattr(sample, "path", "") or ""
        current_dir = getattr(self._w, "current_dir", None)
        if os.path.dirname(sample_path) != current_dir:
            return

        # Debounce : repart le timer a chaque analyse. Un seul refresh_list()
        # sera declenche _SCALE_REFRESH_DEBOUNCE_MS ms apres la derniere analyse.
        self._scale_refresh_timer.start()

    def _do_scale_refresh(self) -> None:
        """Appele par le timer de debounce — un seul refresh_list() pour toute la rafale."""
        try:
            self._w.refresh_list()
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
