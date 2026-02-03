# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere le zoom/pan et les limites du ViewBox pour la waveform.
# - Isole la logique "navigation" pour alleger wave_form.py.
#
# CE QUI EST COUVERT
# - Configuration des limites X/Y du ViewBox.
# - Zoom horizontal standard + pan horizontal (Shift + molette).
#
# RESPONSABILITES TECHNIQUES
# - Appliquer les bornes selon la duree du sample.
# - Router l'event molette vers la logique de navigation.
#
# NON-OBJECTIFS
# - Rendu (WaveformRenderer).
# - Interactions complexes (WaveformInteractionsController).
#
# DEPENDANCES
# - pyqtgraph
# - PyQt6 (Qt)
# -----------------------------------------------------------------------------

from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt


class WaveformNavigationController:
    def __init__(self, widget):
        self.widget = widget

    def configure_viewbox(self, view_box=None):
        """Configure les limites et le handler de molette."""
        w = self.widget
        vb = view_box or w.plot.getViewBox()
        vb.setMenuEnabled(False)
        vb.wheelEvent = self.zoom_or_pan
        vb.setLimits(
            xMin=0,          # plage horizontale
            xMax=w.duration,
            yMin=-1,         # amplitude fixe
            yMax=1,
            minXRange=0.01,  # zoom horizontal autorise
            maxXRange=w.duration,
            minYRange=2,     # bloque la hauteur a (1 - -1) = 2
            maxYRange=2,
        )

    def zoom_or_pan(self, ev, **_):
        w = self.widget
        vb = w.plot.getViewBox()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            dx = -0.1 if ev.delta() > 0 else 0.1
            vb.translateBy(x=dx * w.duration, y=0)
        else:
            pg.ViewBox.wheelEvent(vb, ev)
