# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe les helpers de pose/nettoyage de marqueurs dans le BreakWidget.
# - Isole la synchronisation entre les slices detectees et la waveform.
# -----------------------------------------------------------------------------

from __future__ import annotations


class BreakMarkersController:
    """Gere les marqueurs de la waveform pour l'outil Break."""

    def __init__(self, widget):
        self.widget = widget

    def _apply_markers_to_waveform(self, result) -> None:
        w = self.widget._waveform_widget
        if w is None or getattr(w, "waveform_data", None) is None:
            return
        self._clear_waveform_markers()
        if not result.slices:
            return
        w._record_history = False
        try:
            for s in result.slices:
                w.add_marker(float(s.start_s))
        finally:
            w._record_history = True

    def set_markers(self, markers: list[float]) -> None:
        """Pose une liste de marqueurs manuels sur la waveform courante."""
        w = self.widget._waveform_widget
        if w is None or getattr(w, "waveform_data", None) is None:
            return

        duration = float(getattr(w, "duration", 0.0) or 0.0)
        cleaned: list[float] = []
        seen: set[float] = set()
        for marker in markers or []:
            try:
                value = float(marker)
            except (TypeError, ValueError):
                continue
            if value < 0.0 or (duration > 0.0 and value >= duration):
                continue
            key = round(value, 6)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(value)

        cleaned.sort()
        self._clear_waveform_markers()
        if not cleaned:
            return

        w._record_history = False
        try:
            for marker in cleaned:
                w.add_marker(float(marker))
        finally:
            w._record_history = True

    def _clear_waveform_markers(self) -> None:
        w = self.widget._waveform_widget
        if w is None:
            return
        try:
            w.stop_audio()
        except Exception:
            pass
        try:
            if w.region is not None:
                w.plot.removeItem(w.region)
                w.region = None
        except Exception:
            pass
        try:
            for line in list(w.marker_lines.values()):
                w.plot.removeItem(line)
        except Exception:
            pass
        w.markers = []
        w.marker_lines = {}
        w.current_marker_idx = 0
        w.play_start = 0.0
        w.play_end = 0.0
        try:
            w.read_head.setPos(0.0)
            w._refresh_marker_list()
        except Exception:
            pass
