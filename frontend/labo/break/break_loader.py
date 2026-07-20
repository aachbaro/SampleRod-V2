# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe le chargement de fichier et le cycle de vie de la waveform
#   dans le BreakWidget.
# - Isole l'ouverture de fichier, le remplacement du WaveformWidget et la
#   restauration d'une analyse depuis le cache.
#
# DEPENDANCES
# - frontend.sample_gui.wave_form.WaveformWidget
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from frontend.sample_gui.wave_form import WaveformWidget


class BreakLoaderController:
    """Gere le chargement de fichier et la waveform du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def open_file(self, path: str) -> bool:
        normalized = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(normalized):
            return False
        if self.widget._current_path == normalized and self.widget._waveform_widget is not None:
            return True
        self.widget._current_path = normalized
        self.widget.file_label.setText(os.path.basename(normalized))
        self.widget._clear_analysis()
        self.widget._update_header_meta()
        self.widget._pending_cached_result = self.widget._break_service.load_cached(normalized)
        self._replace_waveform(normalized)
        self.widget._refresh_actions()
        if self.widget._pending_cached_result is not None:
            self.widget.status_label.setText("Fichier charge. Restauration de l'analyse de break...")
        else:
            self.widget.status_label.setText(
                "Fichier charge. Lance le decoupage automatique pour detecter les transients."
            )
        return True

    def _replace_waveform(self, path: str) -> None:
        self._destroy_waveform()
        waveform = WaveformWidget(path, self.widget.app_context)
        waveform.setAcceptDrops(True)
        waveform.installEventFilter(self.widget)
        self.widget.waveform_layout.addWidget(waveform)
        self.widget._waveform_widget = waveform
        loader = getattr(waveform, "loader", None)
        if loader is not None:
            loader.finished.connect(self._on_waveform_loaded)
        else:
            self._on_waveform_loaded()

    def _destroy_waveform(self) -> None:
        if self.widget._waveform_widget is None:
            return
        for cleanup in ("removeEventFilter", "stop_audio"):
            try:
                getattr(self.widget._waveform_widget, cleanup)(self.widget) if cleanup == "removeEventFilter" else getattr(self.widget._waveform_widget, cleanup)()
            except Exception:
                pass
        try:
            self.widget._waveform_widget.timer.stop()
        except Exception:
            pass
        self.widget.waveform_layout.removeWidget(self.widget._waveform_widget)
        self.widget._waveform_widget.deleteLater()
        self.widget._waveform_widget = None

    def _on_waveform_loaded(self) -> None:
        pending = self.widget._pending_cached_result
        self.widget._pending_cached_result = None
        if pending is not None and self.widget._matches_path(pending.source_path):
            self.widget._apply_analysis_result(
                pending,
                status_message=(
                    f"Analyse restauree depuis le cache: {pending.onset_count} slice(s)"
                    f"{f' — BPM {pending.tempo_bpm:.1f}' if pending.tempo_bpm > 1.0 else ''}."
                ),
                persist=False,
            )
        self.widget._refresh_actions()

    def _waveform_ready(self) -> bool:
        w = self.widget._waveform_widget
        return bool(
            w is not None
            and getattr(w, "waveform_data", None) is not None
            and getattr(w, "sample_rate", None)
        )
