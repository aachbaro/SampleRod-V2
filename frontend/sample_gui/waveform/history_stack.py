class HistoryStack:
    """Simple undo/redo command history."""

    def __init__(self):
        self._commands = []
        self._index = -1

    def push(self, cmd: dict):
        """Append a command and discard any redo history."""
        del self._commands[self._index + 1 :]
        self._commands.append(cmd)
        self._index = len(self._commands) - 1

    def undo(self):
        if self._index < 0:
            return None
        cmd = self._commands[self._index]
        self._index -= 1
        return cmd

    def redo(self):
        if self._index + 1 >= len(self._commands):
            return None
        self._index += 1
        return self._commands[self._index]

    def __repr__(self):
        return f"HistoryStack(index={self._index}, cmds={self._commands})"
