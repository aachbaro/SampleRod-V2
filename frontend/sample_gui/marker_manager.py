from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem
import pyqtgraph as pg
import numpy as np
import bisect

class ClickableMarkerLine(pg.InfiniteLine):
    """Line capable of removing itself on double-click."""
    def __init__(self, parent_widget, t, **kwargs):
        super().__init__(pos=t, angle=90, **kwargs)
        self._parent_widget = parent_widget
        self._time = t

    def mouseDoubleClickEvent(self, ev):
        current_t = float(self.value())
        self._parent_widget.remove_marker(current_t)
        ev.accept()

class MarkerManager:
    def __init__(self, widget):
        self.widget = widget
        self.plot = widget.plot
        self.marker_list = widget.marker_list
        self.markers = []
        self.marker_lines = {}
        self.current_marker_idx = 0

    def refresh_marker_list(self):
        self.marker_list.clear()
        for i, t in enumerate(self.markers):
            item = QListWidgetItem(f"M{i+1} — {t:.3f}s")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.marker_list.addItem(item)

    def add_marker(self, t):
        t = float(np.clip(t, 0.0, self.widget.duration))
        print(f"Marker ajouté à {t:.3f}s")
        self.widget._push_history({"action": "add_marker", "time": t})
        bisect.insort(self.markers, t)
        self.refresh_marker_list()
        line = ClickableMarkerLine(parent_widget=self.widget, t=t, pen=pg.mkPen('y', width=2))
        line.setMovable(True)
        line.setZValue(10)
        line.old_pos = t
        line.sigPositionChanged.connect(lambda _, l=line: self.on_marker_moved(l))
        line.sigPositionChangeFinished.connect(lambda _, l=line: self.on_marker_move_finished(l))
        self.plot.addItem(line)
        self.marker_lines[t] = line

    def on_marker_moved(self, line):
        new_t = float(np.clip(line.value(), 0.0, self.widget.duration))
        line.setValue(new_t)
        old_t = next(t for t, ln in self.marker_lines.items() if ln is line)
        self.markers.remove(old_t)
        del self.marker_lines[old_t]
        bisect.insort(self.markers, new_t)
        self.marker_lines[new_t] = line
        self.refresh_marker_list()

    def on_marker_move_finished(self, line):
        old_t = getattr(line, 'old_pos', None)
        new_t = float(np.clip(line.value(), 0.0, self.widget.duration))
        print(f"Marker déplacé de {old_t:.3f}s → {new_t:.3f}s")
        self.widget._push_history({"action": "move_marker", "old": old_t, "new": new_t})
        line.old_pos = new_t

    def remove_marker(self, t):
        if t in self.markers:
            print(f"Marker supprimé à {t:.3f}s")
            self.widget._push_history({"action": "remove_marker", "time": t})
            idx = self.markers.index(t)
            self.markers.remove(t)
            line = self.marker_lines.pop(t)
            self.plot.removeItem(line)
            if not self.markers:
                self.current_marker_idx = 0
            else:
                if self.current_marker_idx > idx:
                    self.current_marker_idx -= 1
                self.current_marker_idx = min(self.current_marker_idx, len(self.markers)-1)
            self.refresh_marker_list()
