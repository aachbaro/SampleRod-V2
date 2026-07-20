# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Centralise l'historique des actions (undo/redo) de la WaveformWidget.
# - Isole la logique de replay des commandes pour alleger wave_form.py.
#
# CE QUI EST COUVERT
# - Push de commandes dans HistoryStack.
# - Undo / redo pour les actions: add/remove/move marker, cut region, fill_markers.
# - Logs de debug pour visualiser l'historique.
#
# RESPONSABILITES TECHNIQUES
# - Geler l'enregistrement pendant l'application d'un undo/redo.
# - Rejouer les actions en appelant les methodes du widget.
#
# NON-OBJECTIFS
# - Rendu (WaveformRenderer).
# - Playback audio (WaveformPlaybackController).
# - Interactions souris (WaveformInteractionsController).
#
# DEPENDANCES
# - logging
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging

logger = logging.getLogger("waveform_history")


class WaveformHistoryController:
    """Deleguant undo/redo : pousse les commandes dans HistoryStack et les rejoue."""

    def __init__(self, widget):
        self.widget = widget

    def push_history(self, cmd: dict):
        """Record a command for undo/redo."""
        w = self.widget
        if not w._record_history:
            return
        w.history.push(cmd)
        self._debug_history()

    def undo(self):
        """Rejoue le dernier undo: gele l'enregistrement pendant l'application."""
        w = self.widget
        cmd = w.history.undo()
        if cmd is None:
            return
        w._record_history = False

        if cmd["action"] == "add_marker":
            w.remove_marker(cmd["time"])

        elif cmd["action"] == "cut":
            w._undo_cut(cmd)

        elif cmd["action"] == "remove_marker":
            w.add_marker(cmd["time"])

        elif cmd["action"] == "move_marker":
            line = w.marker_lines[cmd["new"]]
            line.setValue(cmd["old"])
            w.on_marker_moved(line)

        elif cmd["action"] == "fill_markers":
            # Defaire : supprimer les markers ajoutes, restaurer ceux supprimes
            for t in cmd.get("added", []):
                w.remove_marker(t)
            for t in cmd.get("removed", []):
                w.add_marker(t)

        w._record_history = True
        self._debug_history()

    def redo(self):
        """Rejoue la derniere action annulee: gele l'enregistrement pendant l'application."""
        w = self.widget
        cmd = w.history.redo()
        if cmd is None:
            return
        w._record_history = False

        if cmd["action"] == "add_marker":
            w.add_marker(cmd["time"])

        elif cmd["action"] == "cut":
            # on refait exactement le meme cut
            w._do_cut(cmd["start"], cmd["start"] + cmd["shift"])

        elif cmd["action"] == "remove_marker":
            w.remove_marker(cmd["time"])

        elif cmd["action"] == "move_marker":
            line = w.marker_lines[cmd["old"]]
            line.setValue(cmd["new"])
            w.on_marker_moved(line)

        elif cmd["action"] == "fill_markers":
            # Refaire : supprimer ceux qui avaient ete retires, ajouter ceux places
            for t in cmd.get("removed", []):
                w.remove_marker(t)
            for t in cmd.get("added", []):
                w.add_marker(t)

        w._record_history = True
        self._debug_history()

    def _debug_history(self):
        w = self.widget
        logger.info("=== Historique des commandes ===")
        logger.info(w.history)
        logger.info("================================")
