# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique d'analyse du BreakWidget.
# - Isole le lancement des workers du service, la propagation des marqueurs,
#   les callbacks de resultat et le remplissage auto des marqueurs.
#
# LIENS CLES
# - backend/services/drum_analysis_service.py : workers et types resultat.
# - frontend/labo/break/break_markers.py      : projection des marqueurs.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

import soundfile as sf
from PySide6.QtCore import QSettings as _QS

from backend.services.drum_analysis_service import (
    DEFAULT_SPLIT_DENSITY,
    DrumAnalysisResult,
    drum_analysis_availability_error,
)


class BreakAnalysisController:
    """Gere les analyses de decoupage et reclassification du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def _run_auto_split(self) -> None:
        if not self.widget._current_path:
            self.widget.status_label.setText("Charge un fichier avant de lancer le decoupage.")
            return
        error = drum_analysis_availability_error()
        if error:
            self.widget.status_label.setText(f"Analyse indisponible: {error}")
            return
        self.widget.split_button.setEnabled(False)
        self.widget.analyze_button.setEnabled(False)
        self.widget.status_label.setText("Detection des transients et estimation du BPM...")
        self.widget._break_service.analyze_file(
            self.widget._current_path,
            split_density=DEFAULT_SPLIT_DENSITY,
        )

    def _run_slice_analysis(self) -> None:
        markers = self._get_current_markers()
        if not markers:
            self.widget.status_label.setText("Aucun marqueur sur la waveform.")
            return
        if not self.widget._current_path or not os.path.isfile(self.widget._current_path):
            self.widget.status_label.setText("Aucun fichier charge.")
            return
        self.widget.analyze_button.setEnabled(False)
        self.widget.status_label.setText("Classification des hits depuis les marqueurs...")

        result = self.widget._analysis_result
        if result is None:
            try:
                info = sf.info(self.widget._current_path)
                duration_s = float(info.duration)
                sample_rate = int(info.samplerate)
            except Exception:
                duration_s = 0.0
                sample_rate = 44100
            result = DrumAnalysisResult(
                source_path=self.widget._current_path,
                label="unknown",
                family="unknown",
                form="unknown",
                confidence=0.0,
                duration_s=duration_s,
                sample_rate=sample_rate,
                tempo_bpm=0.0,
                pulse_score=0.0,
                regularity=0.0,
                onset_count=len(markers),
                split_density=DEFAULT_SPLIT_DENSITY,
                candidates=(),
                slices=(),
            )

        self.widget._break_service.reanalyze_from_markers(result, markers)

    def _get_current_markers(self) -> list[float]:
        w = self.widget._waveform_widget
        return list(getattr(w, "markers", []) or []) if w is not None else []

    def _has_valid_fill_interval(self) -> bool:
        w = self.widget._waveform_widget
        if w is None:
            return False
        start = getattr(w, "play_start", None)
        end = getattr(w, "play_end", None)
        if start is None or end is None:
            return False
        return (end - start) > 0.01

    def _run_fill_markers(self) -> None:
        w = self.widget._waveform_widget
        if w is None:
            return
        start = getattr(w, "play_start", None)
        end = getattr(w, "play_end", None)
        duration = getattr(w, "duration", None)
        if start is None or end is None or duration is None:
            return

        interval = end - start
        if interval <= 0.01:
            return

        replace = False
        settings = getattr(getattr(self.widget, "app_context", None), "settings", None)
        if settings is not None and hasattr(settings, "isFillMarkersReplace"):
            replace = settings.isFillMarkersReplace()
        else:
            replace = _QS("SampleRod", "Main").value(
                "waveform/fill_markers_replace", False, type=bool
            )

        tol = 1e-4
        existing = sorted(getattr(w, "markers", []) or [])

        targets = []
        t = end
        while t < duration - tol:
            targets.append(t)
            t += interval

        removed = []
        if replace:
            removed = [
                m for m in existing
                if end - tol < m < duration - tol
                and not any(abs(m - tgt) < tol for tgt in targets)
            ]

        added = [tgt for tgt in targets if not any(abs(m - tgt) < tol for m in existing)]

        if not added and not removed:
            return

        w._record_history = False
        try:
            for t in removed:
                w.remove_marker(t)
            for t in added:
                w.add_marker(t)
        finally:
            w._record_history = True

        w._push_history({"action": "fill_markers", "added": added, "removed": removed})
        self.widget._refresh_actions()

    def _on_analysis_started(self, path: str) -> None:
        if not self.widget._matches_path(path):
            return
        self.widget.status_label.setText("Analyse en cours...")

    def _apply_analysis_result(
        self,
        result: DrumAnalysisResult,
        *,
        status_message: str | None = None,
        persist: bool,
    ) -> None:
        self.widget._analysis_result = result
        if result.tempo_bpm > 1.0:
            self.widget.bpm_spin.blockSignals(True)
            self.widget.bpm_spin.setValue(float(result.tempo_bpm))
            self.widget.bpm_spin.blockSignals(False)
        self.widget._apply_markers_to_waveform(result)
        self.widget._rebuild_hits_table(result)
        self.widget._refresh_quantized_projection()
        self.widget.generator_panel.set_analysis_result(result)
        self.widget._update_header_meta()
        self.widget._update_slices_label()
        if persist:
            self.widget._break_service.cache_result(result)
        if status_message:
            self.widget.status_label.setText(status_message)
        self.widget._refresh_actions()

    def _on_analysis_finished(self, result: DrumAnalysisResult) -> None:
        if not self.widget._matches_path(result.source_path):
            return
        self._apply_analysis_result(result, persist=True)
        bpm_str = f" — BPM {result.tempo_bpm:.1f}" if result.tempo_bpm > 1.0 else ""
        self.widget.status_label.setText(
            f"{result.onset_count} slices{bpm_str}. "
            f"Ajuste les marqueurs si besoin, puis clique sur Analyser les slices."
        )
        self.widget._refresh_actions()

    def _on_analysis_failed(self, path: str, message: str) -> None:
        if path and not self.widget._matches_path(path):
            return
        self.widget.status_label.setText(f"Analyse impossible: {message}")
        self.widget._refresh_actions()
