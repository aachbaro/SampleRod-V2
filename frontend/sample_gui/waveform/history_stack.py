# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Pile undo/redo minimale pour les actions waveform.
# - Stocke les commandes et gere les transitions d'etat utilisateur.
#
# LIENS CLES
# - frontend/sample_gui/waveform/waveform_history.py
# - frontend/sample_gui/wave_form.py
# -----------------------------------------------------------------------------
# frontend/sample_gui/waveform/history_stack.py

class HistoryStack:
    """Simple undo/redo command history."""

    def __init__(self, max_commands: int = 128):
        self._commands = []
        self._index = -1
        self._max_commands = max(1, int(max_commands))
        import logging
        self.logger = logging.getLogger("history_stack")

    def push(self, cmd: dict):
        """Append a command and discard any redo history."""
        del self._commands[self._index + 1 :]
        self._commands.append(cmd)
        overflow = len(self._commands) - self._max_commands
        if overflow > 0:
            del self._commands[:overflow]
        self._index = len(self._commands) - 1
        self.logger.info(f"[HistoryStack] push -> {cmd}")

    def undo(self):
        if self._index < 0:
            return None
        cmd = self._commands[self._index]
        self._index -= 1
        self.logger.info(f"[HistoryStack] undo -> {cmd}")
        return cmd

    def redo(self):
        if self._index + 1 >= len(self._commands):
            return None
        self._index += 1
        cmd = self._commands[self._index]
        self.logger.info(f"[HistoryStack] redo -> {cmd}")
        return cmd

    def __repr__(self):
        return f"HistoryStack(index={self._index}, cmds={self._commands})"
