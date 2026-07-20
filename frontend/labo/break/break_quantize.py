# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique de quantization du BreakWidget.
# - Isole la projection quantizee, le rendu preview/audio et la creation
#   d'artefacts issus du break recale.
#
# LIENS CLES
# - backend/services/drum_analysis_service.py : preview quantizee et slices.
# - frontend/labo/lab_artifact.py             : sortie vers le Labo.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import uuid

from backend.services.drum_analysis_service import (
    DEFAULT_QUANTIZE_GRID_DIVISION,
    DrumQuantizedPreview,
)
from frontend.labo.lab_artifact import LabArtifact


class BreakQuantizeController:
    """Gere les previews quantizees et les artefacts tempo du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def _on_quantize_started(self, path: str) -> None:
        if not self.widget._matches_path(path):
            return
        self.widget.status_label.setText("Preparation de la preview quantizee...")
        self.widget.quantize_button.setEnabled(False)
        self.widget.quantize_preview_button.setEnabled(False)

    def _on_quantize_finished(self, preview: DrumQuantizedPreview) -> None:
        if not self.widget._matches_path(preview.source_path):
            return
        signature = self._current_quantized_preview_signature()
        self.widget._quantized_preview_signature = signature
        self.widget._quantized_preview_path = preview.temp_path
        self.widget._quantized_preview_duration_s = float(preview.duration_s or 0.0)
        mode = self.widget._quantize_request_mode or "artifact"
        self.widget._quantize_request_mode = None
        if mode == "preview":
            self.widget.status_label.setText(
                f"Preview tempo prete: {preview.display_name} a {preview.target_bpm:.1f} BPM."
            )
            self.widget._toggle_audio_preview(preview.temp_path, float(preview.duration_s or 0.0))
        else:
            artifact = LabArtifact(
                artifact_id=uuid.uuid4().hex,
                kind="break_preview",
                display_name=preview.display_name,
                source_path=preview.source_path,
                temp_path=preview.temp_path,
                duration=float(preview.duration_s),
                persisted=False,
                origin="break_quantize_preview",
                sample_rate=int(preview.sample_rate),
                metadata={
                    "target_bpm": preview.target_bpm,
                    "source_bpm": preview.source_bpm,
                    "grid_division": preview.grid_division,
                    "quantize_strength": preview.quantize_strength,
                },
            )
            self.widget.status_label.setText(f"Preview quantizee prete: {preview.display_name}")
            self.widget.artifactCreated.emit(artifact)
        self.widget._refresh_actions()

    def _on_quantize_failed(self, path: str, message: str) -> None:
        if path and not self.widget._matches_path(path):
            return
        self.widget._quantize_request_mode = None
        self.widget.status_label.setText(f"Preview quantizee impossible: {message}")
        self.widget._refresh_actions()

    def _current_quantized_preview_signature(self) -> tuple[object, ...] | None:
        if not self.widget._current_path or self.widget._analysis_result is None:
            return None
        return (
            os.path.normcase(os.path.normpath(self.widget._current_path)),
            round(float(self.widget.bpm_spin.value()), 4),
            int(self.widget.grid_combo.currentData() or DEFAULT_QUANTIZE_GRID_DIVISION),
            round(float(self.widget.strength_slider.value()) / 100.0, 4),
        )

    def _on_strength_changed(self, value: int) -> None:
        self.widget.strength_value.setText(f"{int(value)}%")

    def _refresh_quantized_projection(self, *_args) -> None:
        if self.widget._analysis_result is None:
            self.widget._quantized_slices = ()
            self.widget._refresh_actions()
            return
        self.widget._quantized_slices = self.widget._break_service.quantized_slices(
            self.widget._analysis_result,
            target_bpm=float(self.widget.bpm_spin.value()),
            grid_division=int(
                self.widget.grid_combo.currentData() or DEFAULT_QUANTIZE_GRID_DIVISION
            ),
            quantize_strength=float(self.widget.strength_slider.value()) / 100.0,
        )
        self.widget._refresh_actions()

    def _create_quantized_preview(self) -> None:
        if self.widget._analysis_result is None:
            return
        self.widget._quantize_request_mode = "artifact"
        self.widget._break_service.create_quantized_preview(
            self.widget._analysis_result,
            target_bpm=float(self.widget.bpm_spin.value()),
            grid_division=int(
                self.widget.grid_combo.currentData() or DEFAULT_QUANTIZE_GRID_DIVISION
            ),
            quantize_strength=float(self.widget.strength_slider.value()) / 100.0,
        )

    def _preview_quantized_break(self) -> None:
        if self.widget._analysis_result is None:
            return
        signature = self._current_quantized_preview_signature()
        if (
            signature is not None
            and signature == self.widget._quantized_preview_signature
            and self.widget._quantized_preview_path
            and os.path.isfile(self.widget._quantized_preview_path)
        ):
            self.widget._toggle_audio_preview(
                self.widget._quantized_preview_path,
                self.widget._quantized_preview_duration_s,
            )
            return
        self.widget._quantize_request_mode = "preview"
        self.widget._break_service.create_quantized_preview(
            self.widget._analysis_result,
            target_bpm=float(self.widget.bpm_spin.value()),
            grid_division=int(
                self.widget.grid_combo.currentData() or DEFAULT_QUANTIZE_GRID_DIVISION
            ),
            quantize_strength=float(self.widget.strength_slider.value()) / 100.0,
        )
