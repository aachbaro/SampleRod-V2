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
        self.widget._render_request_mode = "artifact"
        self.widget._service.render_break_pattern(
            self.widget._analysis_result,
            self.widget._generated_pattern,
            target_bpm=float(self.widget.target_bpm_spin.value()),
            gate=max(0.05, float(self.widget.gate_slider.value()) / 100.0),
            mono_choke=bool(self.widget.mono_choke_check.isChecked()),
            tail_mode=str(self.widget.tail_mode_combo.currentData() or DEFAULT_PATTERN_TAIL_MODE),
        )

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

    def _on_pattern_render_failed(self, source_path: str, message: str) -> None:
        if source_path and not self.widget._matches_path(source_path):
            return
        self.widget._render_busy = False
        self.widget._render_request_mode = None
        self.widget._preview_request = None
        self.widget._refresh_actions()
        self.widget.statusChanged.emit(f"Rendu impossible: {message}")
