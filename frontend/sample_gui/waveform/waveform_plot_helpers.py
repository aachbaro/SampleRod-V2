# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe des composants PyQtGraph utilitaires pour la waveform:
#   - Region avec menu contextuel.
#   - ViewBox qui bloque le drag gauche.
#
# CE QUI EST COUVERT
# - ContextMenuLinearRegionItem: actions Cut / Export / Markers.
# - NoLeftDragViewBox: empêche le drag gauche (réserve le geste à la sélection).
#
# RESPONSABILITES TECHNIQUES
# - Déléguer au parent widget les actions de menu (via _parent).
# - Protéger l'UX: drag gauche utilisé pour la sélection, pas pour le pan.
#
# DEPENDANCES
# - PySide6 (Qt, QMenu, QCursor)
# - pyqtgraph
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu
import pyqtgraph as pg


def add_plot_item_once(plot, item, ignore_bounds: bool = False) -> None:
    """Ajoute un item au plot seulement s'il n'y est pas deja.

    `ignore_bounds=True` exclut l'item du calcul d'auto-range de la vue. C'est
    ce qu'il faut pour les lignes de marqueurs : verticales et infinies, elles
    n'ont aucune etendue a cadrer. Sans ce drapeau, pyqtgraph reparcourt les
    bornes de TOUS les items a chaque ajout — poser 200 marqueurs devenait
    quadratique et gelait l'interface plusieurs secondes.
    """
    if plot is None or item is None:
        return
    plot_item = getattr(plot, "plotItem", plot)
    try:
        existing_items = getattr(plot_item, "items", None)
        if existing_items is not None and item in existing_items:
            return
    except Exception:
        pass
    if ignore_bounds:
        try:
            plot.addItem(item, ignoreBounds=True)
            return
        except TypeError:
            # Backend sans ce parametre : on retombe sur l'ajout simple.
            pass
    plot.addItem(item)


class ContextMenuLinearRegionItem(pg.LinearRegionItem):
    """Region de selection avec menu contextuel (Cut, Export, Markers, Stems)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        )

    def contextMenuEvent(self, ev):
        start, end = self.getRegion()
        interval = end - start

        menu = QMenu()

        cut = menu.addAction("Cut                      Ctrl + X")
        export = menu.addAction("Export Selection         Ctrl + E")
        add_markers_action = menu.addAction("Add markers at edges     Ctrl + Shift + G")
        menu.addSeparator()
        fill_action = menu.addAction("Propager l'intervalle jusqu'a la fin  ↦")
        fill_action.setEnabled(interval > 0.01)
        menu.addSeparator()
        stem_action = menu.addAction("Envoyer au separateur de stems")

        global_pos = QCursor.pos()
        action = menu.exec(global_pos)

        if action is cut:
            self._parent._cut_region(start, end)
        elif action is export:
            self._parent._export_region(start, end)
        elif action is add_markers_action:
            if end > start:
                self._parent.add_marker(start)
                self._parent.add_marker(end)
            else:
                self._parent.add_marker(start)
        elif action is fill_action:
            if hasattr(self._parent, "fill_markers_from_region"):
                self._parent.fill_markers_from_region()
        elif action is stem_action:
            if hasattr(self._parent, "send_selection_to_stem_separator"):
                self._parent.send_selection_to_stem_separator()

        ev.accept()


class NoLeftDragViewBox(pg.ViewBox):
    """Empêche le drag gauche (réservé à la sélection)."""
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)
