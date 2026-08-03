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
# - PySide6 (Qt)
# -----------------------------------------------------------------------------

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt


# Part de la fenetre visible parcourue a chaque cran de molette. Un dixieme
# garde des reperes a l'ecran d'un cran a l'autre : on suit ou on en est.
PAN_FRACTION = 0.1


def pan_step_s(view_span_s: float, forward: bool, fraction: float = PAN_FRACTION) -> float:
    """Deplacement horizontal d'un cran de molette, en secondes.

    Le pas suit la FENETRE VISIBLE, pas la duree du fichier : c'est le seul
    reglage qui donne la meme sensation a tous les niveaux de zoom. Un pas fixe
    calcule sur la duree totale devient absurde des qu'on zoome — sur un
    fichier de 30 s ramene a une fenetre de 0,5 s, un cran sautait 3 s, soit
    six fenetres d'un coup.
    """
    span = float(view_span_s or 0.0)
    if span <= 0.0:
        return 0.0
    step = span * float(fraction)
    return step if forward else -step


class WaveformNavigationController:
    """Configure le ViewBox et gere le zoom/pan horizontal de la waveform."""

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
        """Shift+molette = pan horizontal; molette seule = zoom (delegue a pyqtgraph)."""
        w = self.widget
        vb = w.plot.getViewBox()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            vb.translateBy(x=self.pan_step(vb, forward=ev.delta() <= 0), y=0)
        else:
            pg.ViewBox.wheelEvent(vb, ev)

    def pan_step(self, view_box=None, *, forward: bool) -> float:
        """Pas de defilement lateral, cale sur la fenetre actuellement visible."""
        vb = view_box or self.widget.plot.getViewBox()
        try:
            (x0, x1), _ = vb.viewRange()
            span = float(x1) - float(x0)
        except Exception:
            # Vue pas encore etablie : on retombe sur la duree du fichier.
            span = float(getattr(self.widget, "duration", 0.0) or 0.0)
        return pan_step_s(span, forward)
