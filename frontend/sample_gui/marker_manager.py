# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gestionnaire UI de la liste de markers/slices affichee dans le WaveformWidget.
# - Chaque item represente une "coupe" dans la waveform (segment audio).
# - Gere selection, reorder interne et drag-and-drop vers le Compositeur.
#
# CLASSES PRINCIPALES
# - MarkerListWidget       : QListWidget specialise (drag source vers Compositeur)
# - MarkerItemWidget       : row custom (label + bouton delete, hover-reveal)
#
# FONCTIONS CLES
# - add_marker(label, start, end, audio, sr)  : ajoute un segment
# - remove_marker(idx)                        : retire un segment
# - clear_markers()                           : vide la liste
# - get_markers()                             : retourne la liste ordonnee
# - _start_drag()                             : MIME "application/x-sample-slice-data"
#
# LIENS CLES
# - frontend/sample_gui/wave_form.py                      : WaveformWidget (parent)
# - frontend/right_panel/composer/composer_widget.py       : recepteur des drags
# - frontend/right_panel/composer/composer_dnd.py          : decode MIME_SAMPLE_SLICE
# -----------------------------------------------------------------------------

from PySide6.QtCore import Qt, QMimeData, QEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu
from PySide6.QtGui import QDrag
import pyqtgraph as pg
import numpy as np
import bisect
import pickle
import os
import logging
from .waveform.waveform_plot_helpers import add_plot_item_once
logger = logging.getLogger("marker_manager")

_ROLE_TYPE = Qt.ItemDataRole.UserRole + 1   # "selection" | "marker"

class MarkerListWidget(QListWidget):
    """List displaying markers and serving as drag source for slices."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setDragEnabled(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu_requested)

    def _on_context_menu_requested(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        row_type = item.data(_ROLE_TYPE)
        if row_type == "selection":
            menu = QMenu(self)
            stem_action = menu.addAction("Envoyer au separateur de stems")
            action = menu.exec(self.mapToGlobal(pos))
            if action is stem_action:
                if hasattr(self.editor, "send_selection_to_stem_separator"):
                    self.editor.send_selection_to_stem_separator()

    def wheelEvent(self, event):
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

        logger.info("[MarkerManager] drag start (name=%s, sr=%s)", name, sr)
        try:
            logger.debug(
                "[MarkerManager] slice details shape=%s dtype=%s",
                getattr(audio, "shape", None),
                getattr(audio, "dtype", None),
            )
        except Exception:
            pass

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
        result = drag.exec(Qt.DropAction.CopyAction)
        logger.info("[MarkerManager] drag end (result=%s)", result)

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

    def _build_selection_item(self):
        """Construit le QListWidgetItem de selection courante (None si pas de region)."""
        w = self.widget
        region = getattr(w, "region", None)
        if region is None:
            return None
        start, end = region.getRegion()
        if end <= start:
            return None
        duration = end - start
        sr = w.sample_rate or 44100
        data = w.waveform_data
        s0 = int(start * sr)
        s1 = int(end * sr)
        slice_array = data[s0:s1].astype("float32") if data is not None else np.array([], dtype="float32")
        base_name = os.path.basename(w.audio_file_path or "selection")

        item = QListWidgetItem(f"▸ Selection  {start:.2f}s → {end:.2f}s  ({duration:.2f}s)")
        item.setToolTip(
            f"Selection courante: {start:.3f}s → {end:.3f}s ({duration:.3f}s)\n"
            "Glisse pour creer un artefact • Clic droit pour envoyer aux stems"
        )
        item.setData(Qt.ItemDataRole.UserRole, {
            "time": start,
            "end_time": end,
            "audio_data": slice_array,
            "sample_rate": sr,
            "name": base_name,
        })
        item.setData(_ROLE_TYPE, "selection")
        return item

    def refresh_marker_list(self):
        self.marker_list.clear()

        sel_item = self._build_selection_item()
        if sel_item is not None:
            self.marker_list.addItem(sel_item)

        # Lignes de markers
        sr = self.widget.sample_rate or 44100
        data = self.widget.waveform_data
        name = os.path.basename(self.widget.audio_file_path or "")
        for i, t in enumerate(self.markers):
            end_t = self.markers[i + 1] if i + 1 < len(self.markers) else self.widget.duration
            s0 = int(t * sr)
            s1 = int(end_t * sr)
            slice_array = data[s0:s1].astype("float32") if data is not None else np.array([], dtype="float32")
            duration = end_t - t
            item = QListWidgetItem(f"M{i+1}  {t:.2f}s → {end_t:.2f}s  ({duration:.2f}s)")
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setToolTip(f"Marker {i+1}: {t:.3f}s → {end_t:.3f}s ({duration:.3f}s)\nDouble-clic pour supprimer")
            payload = {
                "time": t,
                "audio_data": slice_array,
                "sample_rate": sr,
                "name": name,
            }
            item.setData(Qt.ItemDataRole.UserRole, payload)
            item.setData(_ROLE_TYPE, "marker")
            self.marker_list.addItem(item)

        self.marker_list.setVisible(self.marker_list.count() > 0)

    def refresh_selection_row(self):
        """
        Met a jour uniquement la ligne de selection sans reconstruire les markers.
        Rapide, peut etre appele a chaque changement de region (drag de handle).
        """
        ml = self.marker_list
        # Trouve et supprime les eventuelles lignes de selection existantes
        rows_to_remove = []
        for i in range(ml.count()):
            if ml.item(i).data(_ROLE_TYPE) == "selection":
                rows_to_remove.append(i)
        for i in reversed(rows_to_remove):
            ml.takeItem(i)

        # Reconstruit la ligne de selection et l'insere en tete
        sel_item = self._build_selection_item()
        if sel_item is not None:
            ml.insertItem(0, sel_item)

        ml.setVisible(ml.count() > 0)

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
        add_plot_item_once(self.plot, line)
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
