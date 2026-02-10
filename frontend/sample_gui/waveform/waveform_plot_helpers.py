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
# - PyQt6 (Qt, QMenu, QCursor)
# - pyqtgraph
# -----------------------------------------------------------------------------

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QMenu
import pyqtgraph as pg


class ContextMenuLinearRegionItem(pg.LinearRegionItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        )

    def contextMenuEvent(self, ev):
        start, end = self.getRegion()

        menu = QMenu()

        cut = menu.addAction("Cut                      Ctrl + X")
        export = menu.addAction("Export Selection         Ctrl + E")
        add_markers_action = menu.addAction("Add markers at edges     Ctrl + Shift + G")

        # place ici tes autres actions...

        # récupère la position globale du curseur
        global_pos = QCursor.pos()
        action = menu.exec(global_pos)

        if action is cut:
            # on appelle la méthode _cut_region sur le parent
            self._parent._cut_region(start, end)

        elif action is export:
            # on appelle la méthode _export_region sur le parent (n’écrase pas la waveform en mémoire)
            self._parent._export_region(start, end)
        elif action is add_markers_action:
            # on ajoute des marqueurs aux bords de la région
            if end > start:
                self._parent.add_marker(start)
                self._parent.add_marker(end)
            else:
                # si la région est quasiment nulle, on place un seul marker
                self._parent.add_marker(start)

        ev.accept()


class NoLeftDragViewBox(pg.ViewBox):
    """Empêche le drag gauche (réservé à la sélection)."""
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)
