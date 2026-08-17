"""
------------------------------------------------------------------------------
Directory Preview Controller
------------------------------------------------------------------------------
Role
----
Centralise la logique "preview" du Directory tool:
- Un seul item peut etre en lecture a la fois (play/pause).
- Synchronise l'etat visuel de la ligne (icone play/pause).
- Interagit avec l'audio_player partage (AppContext.audio_player).

Pourquoi l'extraire ?
---------------------
Le DirectoryWidget ne devrait pas contenir toute la logique de lecture.
En sortant ce comportement dans un controller:
- le widget devient plus simple (orchestration + UI)
- on reduit les risques de regressions lors des futurs refactors
- on peut reutiliser le meme pattern pour d'autres outils du Right Panel
  (ex: le Sample Composer aura aussi un "preview" du rendu concatene).
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Any
from backend.services.audio_metadata import normalize_audio_path

logger = logging.getLogger("directory_preview")


class DirectoryPreviewController:
    """
    Gere la lecture "preview" d'une liste de fichiers du DirectoryWidget.

    Hypotheses:
    - audio_player expose: is_playing, current_sample_id, clear_audio(), toggle_play(...)
    - item_widget expose: file_path (str) et set_playing(bool)
    """

    def __init__(
        self,
        audio_player: Any,
        duration_provider: Callable[[str], float],
    ):
        self._ap = audio_player
        self._get_duration = duration_provider

        self._current_widget: Optional[Any] = None
        self._current_sample_id: Optional[int] = None
        self._path_session_ids: dict[str, int] = {}
        self._next_session_id = -2

    # ------------------------------------------------------------------ public API
    def toggle(self, item_widget: Any) -> None:
        """
        Toggle play/pause sur l'item.

        Comportement:
        - si l'item est deja en lecture => stop
        - sinon => stop ce qui joue, puis demarre l'item
        """
        file_path = getattr(item_widget, "file_path", None)
        if not file_path:
            return

        normalized_path = normalize_audio_path(file_path)
        session_key = normalized_path.casefold()
        if session_key not in self._path_session_ids:
            self._path_session_ids[session_key] = self._next_session_id
            self._next_session_id -= 1
        sample_id = self._path_session_ids[session_key]
        duration = 0.0
        try:
            duration = float(self._get_duration(file_path))
        except Exception:
            duration = 0.0

        ap = self._ap

        # 1) Si c'est deja l'item courant en lecture -> on stoppe.
        if getattr(ap, "is_playing", False) and getattr(ap, "current_sample_id", None) == sample_id:
            self._stop_if_current_sample_playing()
            try:
                item_widget.set_playing(False)
            except Exception:
                pass
            self._current_widget = None
            self._current_sample_id = None
            return

        # 2) On stoppe tout ce qui joue pour demarrer ce preview (comportement historique).
        if getattr(ap, "is_playing", False):
            try:
                ap.clear_audio()
            except Exception:
                pass

        # 3) Etat visuel: l'ancien item (si encore la) repasse en "play".
        if self._current_widget is not None and self._current_widget is not item_widget:
            try:
                self._current_widget.set_playing(False)
            except Exception:
                pass

        # 4) Demarrage du nouveau preview.
        try:
            ap.toggle_play(sample_id, file_path, duration)
        except Exception as e:
            logger.info(f"[DirectoryPreview] toggle_play error: {e}")
            return

        try:
            item_widget.set_playing(True)
        except Exception:
            pass

        self._current_widget = item_widget
        self._current_sample_id = sample_id

    def on_widget_removed(self, item_widget: Any) -> None:
        """
        A appeler quand une ligne disparait (delete/move/refresh).

        Important: on evite de laisser un pointeur vers un widget Qt qui va etre
        detruit (sinon crash quand on essaye de set_playing plus tard).
        """
        if self._current_widget is not item_widget:
            return

        self._stop_if_current_sample_playing()
        self._current_widget = None
        self._current_sample_id = None

    def detach_current_widget(self) -> None:
        """
        A appeler avant de "reset" la liste (clear/rebuild).

        On stoppe seulement si l'audio_player est en train de jouer le sample
        demarre par ce controller, puis on oublie la reference au widget.
        """
        if self._current_widget is None:
            return
        self._stop_if_current_sample_playing()
        self._current_widget = None
        self._current_sample_id = None

    def is_current(self, item_widget: Any) -> bool:
        return self._current_widget is item_widget

    # ------------------------------------------------------------------ internals
    def _stop_if_current_sample_playing(self) -> None:
        """
        Stoppe l'audio seulement si le sample en cours correspond a notre preview.
        (Evite de couper une lecture demarree ailleurs dans l'app.)
        """
        ap = self._ap
        if self._current_sample_id is None:
            return
        if not getattr(ap, "is_playing", False):
            return
        if getattr(ap, "current_sample_id", None) != self._current_sample_id:
            return
        try:
            ap.clear_audio()
        except Exception:
            pass

