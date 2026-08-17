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
from contextlib import contextmanager
from .waveform.waveform_plot_helpers import add_plot_item_once
from frontend.dragdrop import (
    AudioSelection, DragItem, DragKind, DragPayload, DragProvenance,
    MaterialOperation, MaterialStatus,
    attach_payload, drag_preview_pixmap, drag_session,
)
logger = logging.getLogger("marker_manager")

_ROLE_TYPE = Qt.ItemDataRole.UserRole + 1   # "selection" | "marker"


def materialize_slice_payload(payload, waveform_data):
    """Complete un payload de slice avec son audio, a la demande.

    POURQUOI : les items de la liste ne portent que les bornes (`s0`/`s1`).
    Decouper l'audio pour les 200 items d'une grille couterait une recopie
    integrale du fichier a chaque rafraichissement, alors qu'un seul item est
    reellement glisse. On ne materialise donc qu'au moment du drag.
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("audio_data") is not None:
        return payload
    resolved = dict(payload)
    s0 = int(payload.get("s0", 0) or 0)
    s1 = int(payload.get("s1", 0) or 0)
    if waveform_data is not None and s1 > s0:
        resolved["audio_data"] = waveform_data[s0:s1].astype("float32")
    else:
        resolved["audio_data"] = np.array([], dtype="float32")
    return resolved

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

        # L'audio n'est decoupe qu'ici : les items ne portent que leurs bornes.
        payload = materialize_slice_payload(
            payload, getattr(self.editor, "waveform_data", None)
        )
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
        start = float(payload.get("time") or 0.0)
        end = float(payload.get("end_time") or start + (len(audio) / float(sr or 1)))
        descriptor = DragPayload(
            kind=DragKind.AUDIO_SELECTION,
            items=(DragItem(display_name=str(name or "Slice"), duration=max(0.0, end - start)),),
            source_id="marker-list",
            source_module="waveform",
            selection=AudioSelection(
                start, end,
                str(getattr(self.editor, "audio_file_path", "") or ""),
                int(sr) if sr else None,
            ),
            status=MaterialStatus.DERIVED,
            provenance=DragProvenance(
                str(getattr(self.editor, "audio_file_path", "") or ""),
                MaterialOperation.SELECTION,
            ),
        )
        attach_payload(mime, descriptor)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(drag_preview_pixmap(descriptor))
        with drag_session(descriptor):
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
        # Pose groupee : voir batch_updates().
        self._batch_depth = 0
        self._batch_dirty = False

    def selection_payload(self, materialize: bool = True):
        """Payload de la selection courante, ou None s'il n'y a pas de region.

        Format commun a la liste de marqueurs ET au drag lance directement
        depuis la waveform : les deux gestes doivent produire exactement la
        meme slice.
        """
        w = self.widget
        region = getattr(w, "region", None)
        if region is None:
            return None
        start, end = region.getRegion()
        if end <= start:
            return None
        sr = w.sample_rate or 44100
        data = w.waveform_data
        s0 = int(start * sr)
        s1 = int(end * sr)
        payload = {
            "time": float(start),
            "end_time": float(end),
            "s0": s0,
            "s1": s1,
            "audio_data": None,
            "sample_rate": sr,
            "name": os.path.basename(w.audio_file_path or "selection"),
        }
        # Les appelants externes veulent l'audio tout de suite ; la ligne de
        # liste, elle, se contente des bornes (voir _build_selection_item).
        return materialize_slice_payload(payload, data) if materialize else payload

    def _build_selection_item(self):
        """Construit le QListWidgetItem de selection courante (None si pas de region)."""
        payload = self.selection_payload(materialize=False)
        if payload is None:
            return None
        start = payload["time"]
        end = payload["end_time"]
        duration = end - start

        item = QListWidgetItem(f"▸ Selection  {start:.2f}s → {end:.2f}s  ({duration:.2f}s)")
        item.setToolTip(
            f"Selection courante: {start:.3f}s → {end:.3f}s ({duration:.3f}s)\n"
            "Glisse pour creer un artefact • Clic droit pour envoyer aux stems"
        )
        item.setData(Qt.ItemDataRole.UserRole, payload)
        item.setData(_ROLE_TYPE, "selection")
        return item

    def refresh_marker_list(self):
        # Pose groupee en cours : on ne reconstruit qu'une fois, a la sortie.
        if self._batch_depth > 0:
            self._batch_dirty = True
            return

        self.marker_list.setUpdatesEnabled(False)
        try:
            self.marker_list.clear()

            sel_item = self._build_selection_item()
            if sel_item is not None:
                self.marker_list.addItem(sel_item)

            # Lignes de markers. On ne stocke QUE les bornes : decouper l'audio
            # ici couterait une recopie integrale du fichier a chaque appel,
            # pour des tranches que personne ne lit tant qu'on ne glisse pas.
            sr = self.widget.sample_rate or 44100
            name = os.path.basename(self.widget.audio_file_path or "")
            for i, t in enumerate(self.markers):
                end_t = self.markers[i + 1] if i + 1 < len(self.markers) else self.widget.duration
                duration = end_t - t
                item = QListWidgetItem(f"M{i+1}  {t:.2f}s → {end_t:.2f}s  ({duration:.2f}s)")
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setToolTip(f"Marker {i+1}: {t:.3f}s → {end_t:.3f}s ({duration:.3f}s)\nDouble-clic pour supprimer")
                payload = {
                    "time": t,
                    "s0": int(t * sr),
                    "s1": int(end_t * sr),
                    "audio_data": None,
                    "sample_rate": sr,
                    "name": name,
                }
                item.setData(Qt.ItemDataRole.UserRole, payload)
                item.setData(_ROLE_TYPE, "marker")
                self.marker_list.addItem(item)
        finally:
            self.marker_list.setUpdatesEnabled(True)

        self.marker_list.setVisible(self.marker_list.count() > 0)

    @contextmanager
    def batch_updates(self):
        """Suspend les rafraichissements de liste pendant une pose groupee.

        Sans cela, poser une grille de 200 marqueurs reconstruit la liste 200
        fois — le geste prenait plusieurs secondes. On reconstruit une fois,
        a la fin.
        """
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth <= 0 and self._batch_dirty:
                self._batch_dirty = False
                self.refresh_marker_list()

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
        # Une ligne de journal par marqueur noie le fichier (et coute une
        # ecriture disque) quand on pose une grille : en pose groupee, c'est
        # l'appelant qui journalise le total.
        if self._batch_depth <= 0:
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
        # ignore_bounds : une ligne verticale infinie n'a pas d'etendue a
        # cadrer, et l'inclure rendait la pose de grille quadratique.
        add_plot_item_once(self.plot, line, ignore_bounds=True)
        self.marker_lines[t] = line

    def on_marker_moved(self, line):
        new_t = float(np.clip(line.value(), 0.0, self.widget.duration))
        line.setValue(new_t)
        # La ligne connait sa propre position (old_pos) : la retrouver par un
        # scan du dictionnaire coutait O(n) a chaque pixel de drag, ce qui se
        # sentait des qu'une grille dense etait posee.
        old_t = getattr(line, "old_pos", None)
        if old_t not in self.marker_lines or self.marker_lines[old_t] is not line:
            old_t = next(
                (t for t, ln in self.marker_lines.items() if ln is line), None
            )
        if old_t is None:
            return
        if old_t in self.markers:
            self.markers.remove(old_t)
        del self.marker_lines[old_t]
        bisect.insort(self.markers, new_t)
        self.marker_lines[new_t] = line
        line.old_pos = new_t
        self.refresh_marker_list()

    def shift_markers(self, times, delta: float) -> list:
        """Translate en bloc un ensemble de marqueurs de `delta` secondes.

        Sert au reglage live du point de depart d'une grille : on deplace les
        lignes existantes au lieu de les detruire et recreer. Les signaux des
        lignes sont muselees le temps de l'operation — sinon chaque ligne
        declencherait on_marker_moved, donc une reconstruction de liste par
        marqueur.
        """
        duration = float(getattr(self.widget, "duration", 0.0) or 0.0)
        targets = {float(t) for t in (times or ())}
        if not targets or not delta:
            return []
        moved = []
        for old_t in sorted(targets):
            line = self.marker_lines.get(old_t)
            if line is None:
                continue
            new_t = old_t + delta
            # Hors du fichier : on RETIRE au lieu de rabattre sur la borne.
            # Rabattre empilerait plusieurs marqueurs sur 0 et laisserait des
            # lignes orphelines dans le plot — visible depuis que la grille
            # s'etend jusqu'au debut de l'enregistrement.
            if new_t < 0.0 or new_t > duration:
                self.plot.removeItem(line)
                del self.marker_lines[old_t]
                if old_t in self.markers:
                    self.markers.remove(old_t)
                continue
            new_t = float(new_t)
            blocked = line.blockSignals(True)
            try:
                line.setValue(new_t)
            finally:
                line.blockSignals(blocked)
            line.old_pos = new_t
            del self.marker_lines[old_t]
            self.marker_lines[new_t] = line
            if old_t in self.markers:
                self.markers.remove(old_t)
            bisect.insort(self.markers, new_t)
            moved.append(new_t)
        self.refresh_marker_list()
        return moved

    def on_marker_move_finished(self, line):
        old_t = getattr(line, 'old_pos', None)
        new_t = float(np.clip(line.value(), 0.0, self.widget.duration))
        logger.info(f"Marker déplacé de {old_t:.3f}s → {new_t:.3f}s")
        self.widget._push_history({"action": "move_marker", "old": old_t, "new": new_t})
        line.old_pos = new_t
        # Le decoupage suit le marqueur : l'outil Break recale la slice
        # concernee au lieu de garder l'ancienne position.
        if old_t is not None and abs(float(old_t) - new_t) > 1e-9:
            self.widget.markerMoved.emit(float(old_t), new_t)

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
