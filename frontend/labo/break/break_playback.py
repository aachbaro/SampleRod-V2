# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique de lecture audio du BreakWidget.
# - Isole les helpers de preview quantize et de verification de chemin.
#
# CE QUI EST COUVERT
# - Stop de la preview tempo partagee.
# - Toggle preview d'un fichier temporaire via l'audio_player.
# - Verification du fichier actuellement charge.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path


class BreakPlaybackController:
    """Gere la lecture audio partagee du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def _get_tp_mode(self) -> str:
        """Returns the current tempo playback mode: 'loop', 'once', 'reverse', 'ping-pong'."""
        if getattr(self.widget, "_tp_pp_btn", None) and self.widget._tp_pp_btn.isChecked():
            return "ping-pong"
        if getattr(self.widget, "_tp_rev_btn", None) and self.widget._tp_rev_btn.isChecked():
            return "reverse"
        if getattr(self.widget, "_tp_once_btn", None) and self.widget._tp_once_btn.isChecked():
            return "once"
        return "loop"

    def _build_mode_audio(self, path: str, mode: str) -> tuple[str, float] | None:
        """Creates a processed audio file for reverse/ping-pong. Returns (path, duration_s) or None."""
        try:
            import numpy as np
            import soundfile as sf

            data, sr = sf.read(path, always_2d=True, dtype="float32")
            if len(data) == 0 or sr <= 0:
                return None
            rev = data[::-1].copy()
            out_data = rev if mode == "reverse" else np.concatenate([data, rev], axis=0)
            temp_dir = Path(tempfile.gettempdir()) / "SampleRod" / "break_tempo_mode"
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = str(temp_dir / f"{Path(path).stem}_{mode}_{uuid.uuid4().hex[:8]}.wav")
            sf.write(out_path, out_data, sr)
            return out_path, float(len(out_data)) / float(sr)
        except Exception:
            return None

    def _stop_tempo_preview(self) -> None:
        active = getattr(self.widget, "_tp_active_play_path", "") or self.widget._quantized_preview_path
        if not active:
            return
        player = self.widget.app_context.audio_player
        current = os.path.normcase(os.path.normpath(player.current_sample_path or ""))
        target = os.path.normcase(os.path.normpath(active))
        if current == target:
            try:
                player.clear_audio()
            except Exception:
                pass
        self.widget._tp_active_play_path = ""

    def _toggle_audio_preview(self, path: str, duration_s: float) -> None:
        if not path or not os.path.isfile(path):
            return

        mode = self._get_tp_mode()
        play_path = path
        play_duration = float(duration_s or 0.0)

        if mode in ("reverse", "ping-pong"):
            result = self._build_mode_audio(path, mode)
            if result is not None:
                play_path, play_duration = result

        player = self.widget.app_context.audio_player
        active = getattr(self.widget, "_tp_active_play_path", "")

        # Same processed file already playing → toggle pause/resume
        if (
            active
            and os.path.normcase(os.path.normpath(active))
            == os.path.normcase(os.path.normpath(play_path))
            and player.is_playing
        ):
            if player.is_paused:
                import pygame
                pygame.mixer.music.unpause()
                player.is_paused = False
            else:
                import pygame
                pygame.mixer.music.pause()
                player.is_paused = True
            return

        # New file/mode → stop current and start fresh
        if player.is_playing:
            try:
                player.clear_audio()
            except Exception:
                pass

        import pygame

        loop = mode in ("loop", "reverse", "ping-pong")
        sample_id = hash(("break-preview-tp", play_path)) & 0x7FFFFFFF
        player.set_up_audio(sample_id, play_path, play_duration)
        pygame.mixer.music.play(-1 if loop else 0, 0)
        player.is_paused = False
        player.is_playing = True
        self.widget._tp_active_play_path = play_path

    def _matches_path(self, path: str | None) -> bool:
        if not path or not self.widget._current_path:
            return False
        return (
            os.path.normcase(os.path.normpath(self.widget._current_path))
            == os.path.normcase(os.path.normpath(path))
        )
