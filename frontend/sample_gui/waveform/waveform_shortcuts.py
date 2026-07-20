# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Centralise les raccourcis clavier / actions rapides du WaveformWidget.
# - Isole les petites actions "glue" pour alleger wave_form.py.
#
# CE QUI EST COUVERT
# - Cut sur region courante.
# - Export de la region courante.
# - Ajout de marqueurs aux bords de la region.
#
# RESPONSABILITES TECHNIQUES
# - Verifier la presence d'une region avant d'executer l'action.
# - Deleguer aux controllers ou methodes du widget.
#
# NON-OBJECTIFS
# - Gestion des regions (WaveformRegionController).
# - Save/export (WaveformSaveController).
# - MarkerManager (WaveformMarkersController).
# -----------------------------------------------------------------------------

from __future__ import annotations


class WaveformShortcutsController:
    """Regroupe les actions declenchees par raccourcis (cut, export, ajout de markers)."""

    def __init__(self, widget):
        self.widget = widget

    def on_cut_shortcut(self):
        """Callback du raccourci : coupe la region selectionnee si elle existe."""
        w = self.widget
        if hasattr(w, "region") and w.region is not None:
            start, end = w.region.getRegion()
            w._cut_region(start, end)

    def on_export_shortcut(self):
        """Callback du raccourci : exporte la region selectionnee si elle existe."""
        w = self.widget
        if hasattr(w, "region") and w.region is not None:
            w.save_controller.on_export_shortcut()

    def add_markers_to_region(self):
        """
        Place deux marqueurs aux bords de la selection (LinearRegionItem).
        Si la selection est vide (end == start), ne place qu'un seul marqueur a start.
        """
        w = self.widget
        if not hasattr(w, "region") or w.region is None:
            return

        start, end = w.region.getRegion()
        # Si la largeur est positive, on place deux marqueurs :
        if end > start:
            w.add_marker(start)
            w.add_marker(end)
        else:
            # Selection nulle -> un seul marqueur
            w.add_marker(start)
