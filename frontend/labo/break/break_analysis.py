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
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QSettings as _QS

from backend.services.temp_workspace import prune_temp_dir, temp_dir

from backend.services.drum_analysis_service import (
    DEFAULT_SPLIT_DENSITY,
    DrumAnalysisResult,
    drum_analysis_availability_error,
)


class BreakAnalysisController:
    """Gere les analyses de decoupage et reclassification du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    # ---------------------------------------------------------------------- #
    # Source analysee
    # Les editions de waveform (coupe, coller...) ne vivent qu'EN MEMOIRE : le
    # fichier sur disque reste l'original. Or l'analyse, la quantize, le rendu
    # du pattern et le drag d'une slice relisent tous l'audio depuis le chemin
    # source. Sans materialisation, couper la moitie d'un break sortait donc
    # des slices situees hors de ce qu'on voit.
    # ---------------------------------------------------------------------- #
    def _resolve_working_path(self) -> str:
        """Chemin a analyser : le fichier courant, ou un WAV temporaire qui
        contient exactement l'audio affiche si la waveform a ete editee."""
        current = self.widget._current_path or ""
        working = self.widget._working_path or current
        if not current:
            return ""
        buffer_info = self._waveform_buffer()
        if buffer_info is None:
            return working
        audio, sample_rate = buffer_info
        if self._path_matches_buffer(working, audio, sample_rate):
            return working
        materialized = self._write_edited_source(audio, sample_rate)
        if materialized:
            self.widget._working_path = materialized
            return materialized
        return working

    def _waveform_buffer(self) -> tuple[np.ndarray, int] | None:
        """Audio actuellement affiche, et son taux d'echantillonnage.

        `WaveformWidget.set_waveform_data` range deja les donnees en
        (n_samples,) ou (n_samples, channels) — c'est exactement ce que
        soundfile attend, il n'y a rien a transposer.
        """
        w = self.widget._waveform_widget
        data = getattr(w, "waveform_data", None) if w is not None else None
        sample_rate = int(getattr(w, "sample_rate", 0) or 0) if w is not None else 0
        if data is None or sample_rate <= 0 or getattr(data, "size", 0) == 0:
            return None
        return data, sample_rate

    @staticmethod
    def _path_matches_buffer(path: str, audio: np.ndarray, sample_rate: int) -> bool:
        """Le fichier contient-il deja exactement cet audio ?"""
        if not path or not os.path.isfile(path):
            return False
        try:
            info = sf.info(path)
        except Exception:
            return False
        frames = int(audio.shape[0])
        channels = int(audio.shape[1]) if audio.ndim > 1 else 1
        return (
            int(info.frames) == frames
            and int(info.samplerate) == int(sample_rate)
            and int(info.channels) == channels
        )

    def _write_edited_source(self, audio: np.ndarray, sample_rate: int) -> str:
        """Ecrit l'audio affiche dans un WAV temporaire reutilisable."""
        source = self.widget._current_path or "break"
        root = temp_dir("break_edits")
        prune_temp_dir("break_edits", keep_recent=10, protect=(self.widget._working_path,))
        stem = Path(source).stem or "break"
        safe_stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)[:40]
        frames = int(audio.shape[0])
        target = root / f"{safe_stem}__{frames}_{int(sample_rate)}.wav"
        try:
            # float32 explicite : ce fichier n'est pas qu'un intermediaire
            # d'analyse, il alimente aussi la quantize, le rendu du pattern et
            # le drag des slices. Le defaut WAV (16 bits) degraderait la
            # matiere que l'utilisateur exporte ensuite.
            sf.write(str(target), audio, int(sample_rate), subtype="FLOAT")
        except Exception:
            self.widget.status_label.setText(
                "Impossible de materialiser la waveform editee : analyse sur le fichier d'origine."
            )
            return ""
        return str(target)

    def _run_auto_split(self) -> None:
        if not self.widget._current_path:
            self.widget.status_label.setText("Charge un fichier avant de lancer le decoupage.")
            return
        error = drum_analysis_availability_error()
        if error:
            self.widget.status_label.setText(f"Analyse indisponible: {error}")
            return
        working = self._resolve_working_path()
        if not working:
            return
        self.widget.split_button.setEnabled(False)
        self.widget.analyze_button.setEnabled(False)
        self.widget.status_label.setText("Detection des transients et estimation du BPM...")
        self.widget._break_service.analyze_file(
            working,
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
        working = self._resolve_working_path()
        if not working:
            return
        self.widget.analyze_button.setEnabled(False)
        self.widget.status_label.setText("Classification des hits depuis les marqueurs...")

        result = self.widget._analysis_result
        if result is not None and not self.widget._matches_path(result.source_path):
            # La waveform vient d'etre editee : le resultat precedent decrit un
            # autre audio, on repart d'une coquille sur la nouvelle source.
            result = None
        if result is None:
            try:
                info = sf.info(working)
                duration_s = float(info.duration)
                sample_rate = int(info.samplerate)
            except Exception:
                duration_s = 0.0
                sample_rate = 44100
            result = DrumAnalysisResult(
                source_path=working,
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
        # Une analyse re-classe tous les hits : on repose par-dessus les
        # corrections de classe faites a la main sur ce fichier, sinon chaque
        # redecoupage les effacerait.
        result = self.widget._break_service.apply_manual_labels(result)
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
        restored = self._restored_manual_label_count(result)
        restored_str = (
            f" {restored} correction(s) de classe restauree(s)." if restored else ""
        )
        self.widget.status_label.setText(
            f"{result.onset_count} slices{bpm_str}.{restored_str} "
            f"Ajuste les marqueurs si besoin, puis clique sur Analyser les slices."
        )
        self.widget._refresh_actions()

    def _restored_manual_label_count(self, analysed: DrumAnalysisResult) -> int:
        """Combien de hits portent une classe corrigee a la main, apres analyse."""
        overrides = self.widget._break_service.load_manual_labels(analysed.source_path)
        if not overrides:
            return 0
        applied = self.widget._analysis_result
        if applied is None:
            return 0
        return sum(
            1
            for original, patched in zip(analysed.slices, applied.slices)
            if original.label != patched.label
        )

    def _on_analysis_failed(self, path: str, message: str) -> None:
        if path and not self.widget._matches_path(path):
            return
        self.widget.status_label.setText(f"Analyse impossible: {message}")
        self.widget._refresh_actions()
