# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe le rendu audio exporte par le generateur de break.
# - Isole la creation de LabArtifact et les callbacks du service de rendu.
#
# LIENS CLES
# - frontend/labo/lab_artifact.py : artefact emis vers le Labo.
# -----------------------------------------------------------------------------

from __future__ import annotations

import uuid

from backend.services.drum_analysis_service import DEFAULT_PATTERN_TAIL_MODE
from frontend.labo.lab_artifact import LabArtifact


class BreakGeneratorExportController:
    """Gere le rendu audio final du generateur et sa conversion en artefact."""

    def __init__(self, widget):
        self.widget = widget

    def _render_pattern_artifact(self) -> None:
        if self.widget._generated_pattern is None:
            self.widget.statusChanged.emit("Genere d'abord un pattern avant le rendu.")
            return
        if self.widget._pattern_dirty:
            self.widget.statusChanged.emit("Les reglages ont change. Regenerer le pattern avant le rendu.")
            return
        if self.widget._render_busy or self.widget._analysis_result is None:
            return
        # L'artefact prime : on annule un eventuel re-rendu de preview arme par
        # un changement de BPM, sinon il repasserait derriere et relancerait un
        # worker pour rien.
        self.widget._live_bpm_timer.stop()
        self.widget._live_bpm_pending = False
        self.widget._render_request_mode = "artifact"
        self.widget._service.render_break_pattern(
            self.widget._analysis_result,
            self.widget._generated_pattern,
            target_bpm=float(self.widget.target_bpm_spin.value()),
            gate=max(0.05, float(self.widget.gate_slider.value()) / 100.0),
            mono_choke=bool(self.widget.mono_choke_check.isChecked()),
            tail_mode=str(self.widget.tail_mode_combo.currentData() or DEFAULT_PATTERN_TAIL_MODE),
        )

    def _render_range_artifact(self, start_step: int, end_step: int) -> None:
        """Exporte UNE PLAGE de steps en artefact.

        Le rendu porte toujours sur le pattern complet (c'est ce que sait faire
        le service) ; la plage est ensuite decoupee dans le fichier rendu, avec
        exactement le meme calcul de bornes que la preview en boucle — pour que
        ce qu'on a entendu soit ce qu'on exporte.
        """
        if self.widget._generated_pattern is None:
            self.widget.statusChanged.emit("Genere d'abord un pattern avant le rendu.")
            return
        if self.widget._pattern_dirty:
            self.widget.statusChanged.emit(
                "Les reglages ont change. Regenerer le pattern avant le rendu."
            )
            return
        if self.widget._render_busy or self.widget._analysis_result is None:
            return
        self.widget._live_bpm_timer.stop()
        self.widget._live_bpm_pending = False
        self.widget._artifact_range = (int(start_step), int(end_step))
        self.widget._render_request_mode = "artifact_range"
        self.widget._service.render_break_pattern(
            self.widget._analysis_result,
            self.widget._generated_pattern,
            target_bpm=float(self.widget.target_bpm_spin.value()),
            gate=max(0.05, float(self.widget.gate_slider.value()) / 100.0),
            mono_choke=bool(self.widget.mono_choke_check.isChecked()),
            tail_mode=str(self.widget.tail_mode_combo.currentData() or DEFAULT_PATTERN_TAIL_MODE),
        )

    def _emit_range_artifact(self, payload) -> None:
        """Decoupe la plage demandee dans le rendu et l'emet en artefact."""
        step_range = self.widget._artifact_range
        self.widget._artifact_range = None
        if step_range is None:
            return
        start_step, end_step = step_range
        segment = self.widget.playback._build_segment_from_request(
            payload.temp_path,
            float(payload.duration_s or 0.0),
            {"kind": "loop_range", "start_step": start_step, "end_step": end_step},
            suffix=f"range_{start_step}_{end_step}",
        )
        if segment is None:
            self.widget.statusChanged.emit(
                f"Steps {start_step}-{end_step}: extraction impossible pour l'artefact."
            )
            return
        segment_path, segment_duration = segment
        span = (
            f"step {start_step}" if start_step == end_step else f"steps {start_step}-{end_step}"
        )
        display_name = f"{payload.display_name} [{span}]"
        artifact = LabArtifact(
            artifact_id=uuid.uuid4().hex,
            kind="break_pattern",
            display_name=display_name,
            source_path=payload.source_path,
            temp_path=segment_path,
            duration=float(segment_duration),
            persisted=False,
            origin="break_generator",
            operation="render_break_pattern_range",
            sample_rate=int(payload.sample_rate),
            metadata={
                "target_bpm": payload.target_bpm,
                "tail_mode": payload.tail_mode,
                "seed": payload.seed,
                "bars": payload.bars,
                "start_step": int(start_step),
                "end_step": int(end_step),
            },
        )
        self.widget.artifactCreated.emit(artifact)
        self.widget.statusChanged.emit(f"Artefact genere: {display_name}")

    def _on_pattern_render_started(self, source_path: str) -> None:
        if not self.widget._matches_path(source_path):
            return
        self.widget._render_busy = True
        self.widget._refresh_actions()
        self.widget.statusChanged.emit("Preparation du rendu du break...")

    def _on_pattern_rendered(self, payload) -> None:
        if not self.widget._matches_path(payload.source_path):
            return
        self.widget._render_busy = False
        self.widget._preview_signature = self.widget._current_preview_signature()
        self.widget._preview_temp_path = payload.temp_path
        self.widget._preview_duration_s = float(payload.duration_s or 0.0)
        self.widget._refresh_actions()

        if self.widget._render_request_mode == "preview":
            message = self.widget._start_requested_preview(
                payload.temp_path,
                float(payload.duration_s or 0.0),
            )
            self.widget.statusChanged.emit(message)
        elif self.widget._render_request_mode == "artifact_range":
            self._emit_range_artifact(payload)
        else:
            artifact = LabArtifact(
                artifact_id=uuid.uuid4().hex,
                kind="break_pattern",
                display_name=payload.display_name,
                source_path=payload.source_path,
                temp_path=payload.temp_path,
                duration=float(payload.duration_s),
                persisted=False,
                origin="break_generator",
                operation="render_break_pattern",
                sample_rate=int(payload.sample_rate),
                metadata={
                    "target_bpm": payload.target_bpm,
                    "tail_mode": payload.tail_mode,
                    "seed": payload.seed,
                    "bars": payload.bars,
                    "event_count": int(getattr(payload.pattern, "event_count", 0) or 0),
                },
            )
            self.widget.artifactCreated.emit(artifact)
            self.widget.statusChanged.emit(f"Artefact genere: {payload.display_name}")
        self.widget._render_request_mode = None
        # Un BPM a bouge pendant ce rendu : on rattrape maintenant que le
        # service est libre.
        self.widget._resume_pending_live_bpm()

    def _on_pattern_render_failed(self, source_path: str, message: str) -> None:
        if source_path and not self.widget._matches_path(source_path):
            return
        self.widget._render_busy = False
        self.widget._render_request_mode = None
        self.widget._preview_request = None
        self.widget._artifact_range = None
        self.widget._live_bpm_pending = False
        self.widget._refresh_actions()
        self.widget.statusChanged.emit(f"Rendu impossible: {message}")
