# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique de preview du generateur de break.
# - Isole le cache audio temporaire et la lecture en boucle via l'audio_player.
#
# LIENS CLES
# - backend/services/drum_analysis_service.py : rendu audio temporaire.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import soundfile as sf

from backend.services.drum_analysis_service import DEFAULT_PATTERN_TAIL_MODE
from backend.services.temp_workspace import prune_temp_dir, temp_dir


class BreakGeneratorPlaybackController:
    """Gere preview, cache audio et helpers de lecture du generateur."""

    def __init__(self, widget):
        self.widget = widget

    def _preview_pattern(self) -> None:
        if self._is_preview_playing():
            self._stop_preview()
            return
        self._queue_preview_request({"kind": "full"})

    def _preview_pattern_from_step(self, step_index: int) -> None:
        self._queue_preview_request(
            {"kind": "from_step", "step_index": int(step_index)},
            silence_message=f"Step {step_index}: rien a lire depuis ce point.",
        )

    def _preview_pattern_step(self, step_index: int) -> None:
        self._queue_preview_request(
            {"kind": "step_hit", "step_index": int(step_index)},
            silence_message=f"Step {step_index}: silence, aucun hit a lancer.",
        )

    def _preview_pattern_loop_range(self, start_step: int, end_step: int) -> None:
        first_step = int(start_step)
        last_step = int(end_step)
        start_step = int(min(first_step, last_step))
        end_step = int(max(first_step, last_step))
        self._queue_preview_request(
            {"kind": "loop_range", "start_step": start_step, "end_step": end_step},
            silence_message=f"Plage {start_step}-{end_step}: aucun contenu jouable.",
        )

    def _queue_preview_request(
        self,
        request: dict[str, Any],
        *,
        silence_message: str | None = None,
    ) -> None:
        if self.widget._generated_pattern is None:
            self.widget.statusChanged.emit("Genere d'abord un pattern pour le pre-ecouter.")
            return
        if self.widget._pattern_dirty:
            self.widget.statusChanged.emit(
                "Les reglages ont change. Regenerer le pattern avant le preview."
            )
            return
        if self.widget._render_busy or self.widget._analysis_result is None:
            return
        if silence_message and self._request_targets_silence(request):
            self.widget.statusChanged.emit(silence_message)
            return

        preview_signature = self._current_preview_signature()
        self.widget._preview_request = dict(request)
        if (
            preview_signature is not None
            and preview_signature == self.widget._preview_signature
            and self.widget._preview_temp_path
            and os.path.isfile(self.widget._preview_temp_path)
        ):
            message = self._start_requested_preview(
                self.widget._preview_temp_path,
                self.widget._preview_duration_s,
            )
            if message:
                self.widget.statusChanged.emit(message)
            return

        self.widget._render_request_mode = "preview"
        self.widget._service.render_break_pattern(
            self.widget._analysis_result,
            self.widget._generated_pattern,
            target_bpm=float(self.widget.target_bpm_spin.value()),
            gate=max(0.05, float(self.widget.gate_slider.value()) / 100.0),
            mono_choke=bool(self.widget.mono_choke_check.isChecked()),
            tail_mode=str(
                self.widget.tail_mode_combo.currentData() or DEFAULT_PATTERN_TAIL_MODE
            ),
        )

    def _start_requested_preview(self, path: str, duration_s: float) -> str:
        request = dict(self.widget._preview_request or {"kind": "full"})
        self.widget._preview_request = None
        # Memorise ce qui joue : un changement de BPM en cours de lecture doit
        # pouvoir relancer exactement le meme extrait au nouveau tempo.
        self.widget._active_preview_request = dict(request)
        return self._execute_preview_request(request, path, float(duration_s or 0.0))

    # ---------------------------------------------------------------------- #
    # BPM en direct pendant la lecture
    # Le BPM est CUIT dans le rendu : rejouer le meme fichier plus vite
    # pitcherait tout le break et ne correspondrait plus a ce que « Rendre
    # artefact » produirait. On re-rend donc au nouveau tempo, en laissant la
    # boucle en cours tourner jusqu'a ce que le nouveau clip soit pret.
    # ---------------------------------------------------------------------- #
    def _schedule_live_bpm_refresh(self) -> None:
        """Arme le re-rendu differe si (et seulement si) un preview tourne."""
        if not self._is_preview_playing():
            return
        if self.widget._generated_pattern is None or self.widget._pattern_dirty:
            return
        self.widget._live_bpm_timer.start()

    def _apply_live_bpm(self) -> None:
        """Relance le rendu du preview au BPM courant, sans couper le son."""
        if not self._is_preview_playing():
            self.widget._live_bpm_pending = False
            return
        if self.widget._generated_pattern is None or self.widget._analysis_result is None:
            self.widget._live_bpm_pending = False
            return
        if self.widget._render_busy:
            # Un rendu occupe le service (preview precedent ou artefact) :
            # on repassera a sa fin plutot que d'empiler les workers.
            self.widget._live_bpm_pending = True
            return

        self.widget._live_bpm_pending = False
        self.widget._preview_request = dict(
            self.widget._active_preview_request or {"kind": "full"}
        )
        self.widget._render_request_mode = "preview"
        self.widget._service.render_break_pattern(
            self.widget._analysis_result,
            self.widget._generated_pattern,
            target_bpm=float(self.widget.target_bpm_spin.value()),
            gate=max(0.05, float(self.widget.gate_slider.value()) / 100.0),
            mono_choke=bool(self.widget.mono_choke_check.isChecked()),
            tail_mode=str(
                self.widget.tail_mode_combo.currentData() or DEFAULT_PATTERN_TAIL_MODE
            ),
        )

    # ---------------------------------------------------------------------- #
    # Playhead facon sequenceur
    # pygame donne la position de lecture en ms ; on la convertit en numero de
    # step. Le clip joue n'est pas forcement le pattern entier (boucle sur une
    # plage, lecture depuis un step) : l'origine vient donc de la demande de
    # preview en cours.
    # ---------------------------------------------------------------------- #
    def _playhead_origin_step(self) -> int:
        request = self.widget._active_preview_request or {}
        kind = str(request.get("kind") or "full")
        if kind == "loop_range":
            return int(request.get("start_step") or 1)
        if kind in {"from_step", "step_hit"}:
            return int(request.get("step_index") or 1)
        return 1

    def _current_playhead_step(self) -> int | None:
        """Numero de step actuellement joue, ou None si rien ne tourne."""
        if not self._is_preview_playing():
            return None
        try:
            import pygame

            position_ms = pygame.mixer.music.get_pos()
        except Exception:
            return None
        if position_ms is None or position_ms < 0:
            return None

        target_bpm = max(1.0, float(self.widget.target_bpm_spin.value() or 1.0))
        step_duration_s = (60.0 / target_bpm) / 4.0
        if step_duration_s <= 0.0:
            return None

        elapsed_s = float(position_ms) / 1000.0
        # get_pos() ne repart pas de zero a chaque tour de boucle.
        clip_duration_s = float(self.widget._active_preview_clip_duration or 0.0)
        if clip_duration_s > 0.0:
            elapsed_s = elapsed_s % clip_duration_s

        offset = int(elapsed_s / step_duration_s)
        step = self._playhead_origin_step() + offset

        step_count = int(
            getattr(self.widget._generated_pattern, "step_count", 0) or 0
        )
        if step_count > 0 and step > step_count:
            return None
        return step

    def _refresh_playhead(self) -> None:
        self.widget.pattern.set_playhead_step(self._current_playhead_step())

    def _resume_pending_live_bpm(self) -> None:
        """Rejoue la derniere demande de BPM arrivee pendant un rendu."""
        if not self.widget._live_bpm_pending:
            return
        self.widget._live_bpm_pending = False
        self._schedule_live_bpm_refresh()

    def _execute_preview_request(
        self,
        request: dict[str, Any],
        path: str,
        duration_s: float,
    ) -> str:
        kind = str(request.get("kind") or "full")
        display_name = Path(path).stem

        if kind == "full":
            self._start_preview_clip(path, duration_s, loop=True)
            return (
                f"Preview en boucle: {display_name} a "
                f"{self.widget.target_bpm_spin.value():.1f} BPM."
            )

        if kind == "from_step":
            step_index = int(request.get("step_index") or 1)
            segment = self._build_segment_from_request(
                path,
                duration_s,
                request,
                suffix=f"from_{step_index}",
            )
            if segment is None:
                return f"Step {step_index}: impossible de preparer le preview."
            segment_path, segment_duration = segment
            self._start_preview_clip(segment_path, segment_duration, loop=True)
            return f"Preview du pattern depuis le step {step_index}."

        if kind == "step_hit":
            step_index = int(request.get("step_index") or 1)
            segment = self._build_segment_from_request(
                path,
                duration_s,
                request,
                suffix=f"step_{step_index}",
            )
            if segment is None:
                return f"Step {step_index}: impossible de preparer le hit."
            segment_path, segment_duration = segment
            self._start_preview_clip(segment_path, segment_duration, loop=False)
            return f"Hit du step {step_index}."

        if kind == "loop_range":
            start_step = int(request.get("start_step") or 1)
            end_step = int(request.get("end_step") or start_step)
            segment = self._build_segment_from_request(
                path,
                duration_s,
                request,
                suffix=f"loop_{start_step}_{end_step}",
            )
            if segment is None:
                return f"Steps {start_step}-{end_step}: impossible de preparer la boucle."
            segment_path, segment_duration = segment
            self._start_preview_clip(segment_path, segment_duration, loop=True)
            if start_step == end_step:
                return f"Boucle du step {start_step}."
            return f"Boucle des steps {start_step}-{end_step}."

        self._start_preview_clip(path, duration_s, loop=True)
        return f"Preview en boucle: {display_name}."

    def _request_targets_silence(self, request: dict[str, Any]) -> bool:
        pattern = self.widget._generated_pattern
        if pattern is None:
            return False
        steps = list(getattr(pattern, "steps", ()) or ())
        kind = str(request.get("kind") or "full")
        if kind == "step_hit":
            step_index = int(request.get("step_index") or 0)
            if 1 <= step_index <= len(steps):
                return str(getattr(steps[step_index - 1], "label", "silence") or "silence") == "silence"
        if kind == "from_step":
            step_index = int(request.get("step_index") or 1)
            window = steps[max(0, step_index - 1):]
            return bool(window) and all(
                str(getattr(step, "label", "silence") or "silence") == "silence"
                for step in window
            )
        if kind == "loop_range":
            start_step = int(request.get("start_step") or 1)
            end_step = int(request.get("end_step") or start_step)
            window = steps[max(0, start_step - 1): max(0, end_step)]
            return bool(window) and all(
                str(getattr(step, "label", "silence") or "silence") == "silence"
                for step in window
            )
        return False

    def _build_segment_from_request(
        self,
        path: str,
        duration_s: float,
        request: dict[str, Any],
        *,
        suffix: str,
    ) -> tuple[str, float] | None:
        bounds = self._segment_bounds_for_request(request, duration_s)
        if bounds is None:
            return None
        start_s, end_s = bounds
        return self._extract_preview_segment(path, start_s, end_s, suffix=suffix)

    def _segment_bounds_for_request(
        self,
        request: dict[str, Any],
        duration_s: float,
    ) -> tuple[float, float] | None:
        pattern = self.widget._generated_pattern
        if pattern is None:
            return None

        step_count = int(getattr(pattern, "step_count", 0) or 0)
        if step_count <= 0:
            return None

        total_duration_s = max(
            float(duration_s or 0.0),
            self._pattern_step_start_seconds(step_count + 1),
        )
        kind = str(request.get("kind") or "full")

        if kind == "from_step":
            step_index = int(request.get("step_index") or 1)
            start_s = self._pattern_step_start_seconds(step_index)
            end_s = total_duration_s
            return self._sanitize_segment_bounds(start_s, end_s, total_duration_s)

        if kind == "step_hit":
            step_index = int(request.get("step_index") or 1)
            start_s = self._pattern_step_start_seconds(step_index)
            end_s = self._pattern_step_start_seconds(step_index + 1)
            return self._sanitize_segment_bounds(start_s, end_s, total_duration_s)

        if kind == "loop_range":
            start_step = int(request.get("start_step") or 1)
            end_step = int(request.get("end_step") or start_step)
            start_s = self._pattern_step_start_seconds(start_step)
            end_s = (
                self._pattern_step_start_seconds(end_step + 1)
                if end_step < step_count
                else total_duration_s
            )
            return self._sanitize_segment_bounds(start_s, end_s, total_duration_s)

        return self._sanitize_segment_bounds(0.0, total_duration_s, total_duration_s)

    @staticmethod
    def _sanitize_segment_bounds(
        start_s: float,
        end_s: float,
        total_duration_s: float,
    ) -> tuple[float, float] | None:
        total = max(float(total_duration_s or 0.0), 0.0)
        start = max(0.0, min(float(start_s or 0.0), total))
        end = max(0.0, min(float(end_s or 0.0), total))
        if end <= start:
            end = min(total, start + 0.05)
        if end <= start:
            return None
        return start, end

    def _pattern_step_start_seconds(self, step_index: int) -> float:
        pattern = self.widget._generated_pattern
        if pattern is None:
            return 0.0
        target_bpm = max(1.0, float(self.widget.target_bpm_spin.value() or 1.0))
        step_duration_s = (60.0 / target_bpm) / 4.0
        zero_based = max(0, int(step_index) - 1)
        preview_start_s = float(zero_based) * float(step_duration_s)
        local_step = (zero_based % 16) + 1
        swing = float(getattr(pattern, "swing", 0.0) or 0.0)
        if local_step in {3, 7, 11, 15}:
            preview_start_s += max(0.0, min(swing, 1.0)) * (step_duration_s * 0.35)
        return max(0.0, preview_start_s)

    def _extract_preview_segment(
        self,
        path: str,
        start_s: float,
        end_s: float,
        *,
        suffix: str,
    ) -> tuple[str, float] | None:
        if not path or not os.path.isfile(path):
            return None
        data, sample_rate = sf.read(path, always_2d=True, dtype="float32")
        total_frames = int(len(data))
        if total_frames <= 0 or int(sample_rate or 0) <= 0:
            return None

        start_frame = max(0, min(int(round(start_s * sample_rate)), total_frames - 1))
        end_frame = max(0, min(int(round(end_s * sample_rate)), total_frames))
        if end_frame <= start_frame:
            end_frame = min(total_frames, start_frame + max(1, int(sample_rate * 0.05)))
        if end_frame <= start_frame:
            return None

        segment = data[start_frame:end_frame]
        if len(segment) <= 0:
            return None

        temp_root = temp_dir("break_pattern_segments")
        # Un segment est ecrit a chaque clic sur un step, chaque boucle de
        # plage et chaque export : sans menage, le dossier ne fait que croitre.
        # Le clip en cours de lecture est protege pour ne pas se faire couper.
        prune_temp_dir(
            "break_pattern_segments",
            keep_recent=30,
            protect=(self.widget._active_preview_path,),
        )
        source_stem = Path(path).stem or "pattern"
        segment_path = temp_root / f"{source_stem}_{suffix}_{uuid.uuid4().hex[:8]}.wav"
        sf.write(str(segment_path), segment, int(sample_rate))
        return str(segment_path), float(len(segment) / float(sample_rate))

    def _preview_sample_id_for_path(self, path: str) -> int:
        return hash(("break-generator-preview", path)) & 0x7FFFFFFF

    def _is_preview_playing(self) -> bool:
        if not self.widget._active_preview_path:
            return False
        player = self.widget.app_context.audio_player
        current = os.path.normcase(os.path.normpath(player.current_sample_path or ""))
        target = os.path.normcase(os.path.normpath(self.widget._active_preview_path))
        return bool(player.is_playing and not player.is_paused and current == target)

    def _start_preview_clip(self, path: str, duration_s: float, *, loop: bool) -> None:
        if not path or not os.path.isfile(path):
            return
        player = self.widget.app_context.audio_player
        sid = self._preview_sample_id_for_path(path)
        current = os.path.normcase(os.path.normpath(player.current_sample_path or ""))
        target = os.path.normcase(os.path.normpath(path))
        if player.is_playing and current and current != target:
            try:
                player.clear_audio()
            except Exception:
                pass

        player.clear_audio()
        player.set_up_audio(sid, path, float(duration_s or 0.0))
        import pygame

        pygame.mixer.music.play(-1 if loop else 0, 0)
        player.is_paused = False
        player.is_playing = True
        self.widget._preview_sample_id = sid
        self.widget._active_preview_path = path
        self.widget._active_preview_looping = bool(loop)
        # Duree du clip reellement joue : sert a replier get_pos() sur la
        # boucle pour situer le playhead.
        self.widget._active_preview_clip_duration = float(duration_s or 0.0)
        self.widget._playhead_timer.start()

    def _start_loop_preview(self, path: str, duration_s: float) -> None:
        self._start_preview_clip(path, duration_s, loop=True)

    def _stop_preview(self) -> None:
        if not self.widget._active_preview_path:
            return
        player = self.widget.app_context.audio_player
        current = os.path.normcase(os.path.normpath(player.current_sample_path or ""))
        target = os.path.normcase(os.path.normpath(self.widget._active_preview_path))
        if current == target or player.current_sample_id == self.widget._preview_sample_id:
            try:
                player.clear_audio()
            except Exception:
                pass
        self.widget._preview_sample_id = None
        self.widget._active_preview_path = ""
        self.widget._active_preview_looping = False
        self.widget._active_preview_request = None
        self.widget._active_preview_clip_duration = 0.0
        self.widget._live_bpm_pending = False
        self.widget._live_bpm_timer.stop()
        self.widget._playhead_timer.stop()
        self.widget.pattern.set_playhead_step(None)

    def _refresh_preview_button(self) -> None:
        if self._is_preview_playing():
            self.widget.preview_button.setText("Stop")
            self.widget.preview_button.setProperty(
                "looping", bool(self.widget._active_preview_looping)
            )
        else:
            self.widget.preview_button.setText("Preview")
            self.widget.preview_button.setProperty("looping", False)
        self.widget.preview_button.style().unpolish(self.widget.preview_button)
        self.widget.preview_button.style().polish(self.widget.preview_button)

    def _on_preview_settings_changed(self, *_args) -> None:
        self._clear_preview_cache(stop_if_playing=False)
        self.widget._refresh_actions()

    def _current_preview_signature(self) -> tuple[object, ...] | None:
        if self.widget._analysis_result is None or self.widget._generated_pattern is None:
            return None
        return (
            os.path.normcase(os.path.normpath(self.widget._analysis_result.source_path)),
            int(getattr(self.widget._generated_pattern, "seed", 0) or 0),
            int(getattr(self.widget._generated_pattern, "step_count", 0) or 0),
            int(getattr(self.widget._generated_pattern, "event_count", 0) or 0),
            round(float(self.widget.target_bpm_spin.value()), 4),
            round(float(self.widget.gate_slider.value()) / 100.0, 4),
            bool(self.widget.mono_choke_check.isChecked()),
            str(self.widget.tail_mode_combo.currentData() or DEFAULT_PATTERN_TAIL_MODE),
        )

    def _clear_preview_cache(self, *, stop_if_playing: bool) -> None:
        if stop_if_playing:
            self._stop_preview()
        self.widget._preview_signature = None
        self.widget._preview_temp_path = ""
        self.widget._preview_duration_s = 0.0
        self.widget._preview_request = None
