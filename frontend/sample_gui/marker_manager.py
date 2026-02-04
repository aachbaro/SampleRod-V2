from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from PyQt6.QtGui import QDrag
import pyqtgraph as pg
import numpy as np
import bisect
import pickle
import os
import logging
logger = logging.getLogger("marker_manager")

class MarkerListWidget(QListWidget):
    """List displaying markers and serving as drag source for slices."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setDragEnabled(True)

    def wheelEvent(self, event):
        """
        Important UX:
        - La liste de markers vit souvent dans un parent scrollable (SampleList).
        - Quand on arrive en haut/bas, Qt peut relayer le wheelEvent au parent,
          ce qui fait "scroller la liste de samples" alors qu'on est sur les markers.

        Ici on laisse QListWidget gerer le scroll interne, mais on accepte toujours
        l'event pour bloquer la propagation au parent.
        """
        super().wheelEvent(event)
        event.accept()

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return

        # Récupération des données
        audio = payload.get("audio_data")
        sr    = payload.get("sample_rate")
        name  = payload.get("name")

        # 1) Pour afficher la forme générale du tableau
        print(f"[DEBUG] Slice '{name}': shape={audio.shape}, dtype={audio.dtype}, sample_rate={sr}")

        # 2) Pour afficher les premières valeurs seulement (évite trop de logs)
        print("  valeurs audio sample[0:10] =", audio[:10])

        # 3) Si vraiment tu veux tout imprimer (attention, ça peut être énorme) :
        # print(audio)

        # --- puis ton drag d’origine ---
        mime = QMimeData()
        mime.setData(
            "application/x-sample-slice-data",
            pickle.dumps({
                "audio_data": audio,
                "sample_rate": sr,
                "name": name,
            })
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

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
        sr = self.widget.sample_rate or 44100
        data = self.widget.waveform_data
        name = os.path.basename(self.widget.audio_file_path)
        for i, t in enumerate(self.markers):
            end_t = self.markers[i + 1] if i + 1 < len(self.markers) else self.widget.duration
            s0 = int(t * sr)
            s1 = int(end_t * sr)
            slice_array = data[s0:s1].astype("float32") if data is not None else np.array([], dtype="float32")
            duration = end_t - t
            item = QListWidgetItem(f"M{i+1} — {t:.3f}s ({duration:.2f}s)")
            payload = {
                "time": t,
                "audio_data": slice_array,
                "sample_rate": sr,
                "name": name,
            }
            item.setData(Qt.ItemDataRole.UserRole, payload)
            self.marker_list.addItem(item)

    def add_marker(self, t):
        t = float(np.clip(t, 0.0, self.widget.duration))
        logger.info(f"Marker ajouté à {t:.3f}s")
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
        logger.info(f"Marker déplacé de {old_t:.3f}s → {new_t:.3f}s")
        self.widget._push_history({"action": "move_marker", "old": old_t, "new": new_t})
        line.old_pos = new_t

    def remove_marker(self, t):
        if t in self.markers:
            logger.info(f"Marker supprimé à {t:.3f}s")
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
