# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Responsable du rendu de la waveform (enveloppe) dans le PlotWidget.
# - Centralise la logique de recalcul en fonction du zoom/scroll.
# - Permet d'alleger wave_form.py en isolant le "renderer".
#
# CE QUI EST COUVERT
# - Recalcul de l'enveloppe pour la portion visible.
# - Support mono / stereo.
# - Redraw complet (waveform + markers + read head).
#
# RESPONSABILITES TECHNIQUES
# - Conversion "samples -> enveloppe" (min/max par bloc).
# - Mise a jour des courbes PyQtGraph.
# - Synchronisation de la tete de lecture.
#
# NON-OBJECTIFS
# - Playback audio (WaveformPlaybackController).
# - Gestes/interactions (WaveformInteractionsController).
# - Selection/cut/export (WaveformRegionController).
#
# DEPENDANCES
# - numpy
# - pyqtgraph
# -----------------------------------------------------------------------------

from __future__ import annotations

import numpy as np


def compute_envelope(
    segment: np.ndarray,
    *,
    sample_rate: int,
    start_index: int,
    end_index: int,
    width_px: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Calcule l'enveloppe (min/max) d'un segment audio et renvoie un polygon (x, y).

    - segment: tableau 1D
    - start_index/end_index: indices en samples correspondant au segment dans la timeline
    - width_px: largeur du plot en pixels (sert a definir le downsampling)
    """
    if segment is None or len(segment) == 0:
        return np.array([], dtype=np.float32), np.array([], dtype=np.float32)

    width = max(1, int(width_px))
    step = max(1, len(segment) // width)
    n_blocks = len(segment) // step
    if n_blocks <= 0:
        return np.array([], dtype=np.float32), np.array([], dtype=np.float32)

    seg = segment[: n_blocks * step].reshape(n_blocks, step)
    mins = seg.min(axis=1)
    maxs = seg.max(axis=1)

    xs = np.linspace(start_index / sample_rate, end_index / sample_rate, n_blocks)
    x_poly = np.concatenate([xs, xs[::-1]])
    y_poly = np.concatenate([maxs, mins[::-1]])
    return x_poly, y_poly


class WaveformRenderer:
    def __init__(self, widget):
        self.widget = widget

    def draw_waveform(self):
        """Recalcule l'enveloppe sur la portion actuellement visible."""
        w = self.widget
        vb = w.plot.getViewBox()
        x0, x1 = vb.viewRange()[0]
        self.on_view_range_changed(vb, (x0, x1))

    def on_view_range_changed(self, view_box, range):
        """Update the displayed envelope when the view range changes."""
        w = self.widget
        if w.waveform_data is None or w.sample_rate is None:
            return

        x0, x1 = range
        i0 = max(0, int(x0 * w.sample_rate))
        i1 = min(len(w.waveform_data), int(x1 * w.sample_rate))

        if w.is_stereo:
            # Pour chaque canal, on calcule min/max par bloc et on trace sur la courbe correspondante
            for idx, curve in enumerate((w.curve_left, w.curve_right)):
                segment = w.waveform_data[i0:i1, idx]
                if len(segment) == 0:
                    curve.setData([], [])
                    continue

                width = w.plot.width() or 800
                x_poly, y_poly = compute_envelope(
                    segment,
                    sample_rate=w.sample_rate,
                    start_index=i0,
                    end_index=i1,
                    width_px=width,
                )
                curve.setData(x_poly, y_poly)
        else:
            segment = w.waveform_data[i0:i1]
            if len(segment) == 0:
                w.curve.setData([], [])
                return

            width = w.plot.width() or 800
            x_poly, y_poly = compute_envelope(
                segment,
                sample_rate=w.sample_rate,
                start_index=i0,
                end_index=i1,
                width_px=width,
            )
            w.curve.setData(x_poly, y_poly)

        w.read_head.setPos(w.current_time)

    def redraw_all(self):
        w = self.widget
        self.draw_waveform()
        for line in w.marker_lines.values():
            w.plot.addItem(line)
