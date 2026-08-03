# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique "region" de la WaveformWidget:
#   creation de selection, decoupe, undo/redo, export.
# - Isole les commandes d'edition pour alleger wave_form.py.
# - Est instancie par WaveformWidget et manipule son etat (region, markers, etc.).
#
# CE QUI EST COUVERT
# - Validation et sync de la selection (play_start / play_end).
# - Cut (decoupe) d'une region + mise a jour des markers.
# - Undo d'un cut via HistoryStack (delegue par le widget).
# - Export d'une region en nouveau WAV + ajout au SampleService.
# - Creation de region via Ctrl+double-clic entre markers.
# - Curseur visuel de depart (ligne bleue) quand il n'y a pas de region.
#
# RESPONSABILITES TECHNIQUES
# - Manipuler waveform_data (slicing / concat).
# - Maintenir la coherence visuelle: region, read head, markers, bounds.
# - Utiliser QMessageBox pour feedback utilisateur.
#
# NON-OBJECTIFS
# - Playback audio (WaveformPlaybackController).
# - Gestes souris (WaveformInteractionsController).
# - Gestion complete des marqueurs (MarkerManager).
#
# DEPENDANCES
# - numpy, pyqtgraph, soundfile
# - PySide6 (QMessageBox)
# - backend.models.sample.DBSample (id pour export)
#
# IDEES / TODO
# - Centraliser les commandes editables (Cut, Trim, Fade, Normalize).
# - Ajouter un mode "non destructif" (edition par references).
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import logging
import bisect
import pickle
import numpy as np
import pyqtgraph as pg
import soundfile as sf
from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QMessageBox

from .waveform_plot_helpers import add_plot_item_once

logger = logging.getLogger("waveform_region")


class WaveformRegionController:
    """Gere la selection, le cut, l'export et le curseur de depart de la waveform."""

    def __init__(self, widget, region_cls):
        self.widget = widget
        self.region_cls = region_cls

    def _stop_playback_for_edit(self):
        """Stoppe la lecture et remet is_playing/start_sample a zero avant une edition."""
        w = self.widget
        if hasattr(w, "stop_audio"):
            try:
                w.stop_audio()
            except Exception as exc:
                logger.info(f"[WaveformRegion] Erreur stop playback avant edition: {exc}")
        w.is_playing = False
        if hasattr(w, "start_sample"):
            w.start_sample = 0

    def on_region_changed(self):
        """Clamp et synchronise play_start/play_end quand l'utilisateur deplace la region."""
        w = self.widget
        if not w.region:
            return
        start, end = w.region.getRegion()
        # Clamp des bornes
        start = max(0.0, min(start, w.duration))
        end = max(start, min(end, w.duration))
        # Maj visuelle + variables de lecture
        w.region.setRegion([start, end])
        w.play_start, w.play_end = start, end
        # Met a jour la ligne de selection dans la liste de markers (rapide, sans rebuild)
        mm = getattr(w, "marker_manager", None)
        if mm is not None:
            try:
                mm.refresh_selection_row()
            except Exception:
                pass

    def _cut_region(self, start, end):
        w = self.widget
        removed, removed_markers, shift = self._do_cut(start, end)
        # Enregistre l'action pour undo/redo
        w._push_history({
            "action": "cut",
            "start": start,
            "removed_samples": removed,
            "removed_markers": removed_markers,
            "shift": shift,
        })

    def _do_cut(self, start, end):
        """Coupe la zone [start,end], supprime les markers dedans et decale les suivants."""
        w = self.widget
        self._stop_playback_for_edit()
        s0, s1 = int(start * w.sample_rate), int(end * w.sample_rate)
        shift = end - start

        # 1) Decoupe des samples
        removed = w.waveform_data[s0:s1].copy()
        w.waveform_data = np.concatenate([
            w.waveform_data[:s0],
            w.waveform_data[s1:],
        ])
        w.duration = len(w.waveform_data) / w.sample_rate
        vb = w.plot.getViewBox()
        vb.setLimits(xMin=0, xMax=w.duration, yMin=-1, yMax=1)
        w.plot.setXRange(0, w.duration, padding=0)

        # 2) Supprime visuel et interne les markers dans [start,end]
        to_remove = [t for t in w.markers if start <= t <= end]
        for t in to_remove:
            line = w.marker_lines.pop(t)
            w.plot.removeItem(line)
            w.markers.remove(t)

        # 3) Decale tous les markers > start
        new_markers, new_lines = [], {}
        for t, line in list(w.marker_lines.items()):
            if t > start:
                nt = t - shift
                line.setPos(nt)
                new_markers.append(nt)
                new_lines[nt] = line
            else:
                new_markers.append(t)
                new_lines[t] = line
        w.markers = sorted(new_markers)
        w.marker_lines = new_lines

        if w.current_marker_idx >= len(w.markers):
            # si plus aucun marker, on remet a 0
            w.current_marker_idx = max(0, len(w.markers) - 1)

        w._refresh_marker_list()

        # 4) redraw complet
        w._redraw_all()
        w.read_head.setPos(0.0)

        w.current_time = 0.0
        w.play_start = 0.0
        w.play_end = w.duration
        return removed, to_remove, shift

    def _undo_cut(self, cmd):
        """Restaure un cut precedent."""
        w = self.widget
        self._stop_playback_for_edit()
        start = cmd["start"]
        s0 = int(start * w.sample_rate)
        removed = cmd["removed_samples"]
        removed_markers = cmd["removed_markers"]
        shift = cmd["shift"]

        # 1) Recolle les samples
        w.waveform_data = np.concatenate([
            w.waveform_data[:s0],
            removed,
            w.waveform_data[s0:],
        ])
        w.duration = len(w.waveform_data) / w.sample_rate
        vb = w.plot.getViewBox()
        vb.setLimits(xMin=0, xMax=w.duration, yMin=-1, yMax=1)
        w.plot.setXRange(0, w.duration, padding=0)

        # 2) Decale en arriere tous les markers > start
        new_markers, new_lines = [], {}
        for t, line in list(w.marker_lines.items()):
            if t > start:
                rt = t + shift
                line.setPos(rt)
                new_markers.append(rt)
                new_lines[rt] = line
            else:
                new_markers.append(t)
                new_lines[t] = line
        w.markers = sorted(new_markers)
        w.marker_lines = new_lines

        # 3) Recree sans history les markers supprimes
        for t in removed_markers:
            w._create_marker_line(t)

        w._refresh_marker_list()

        # 4) redraw
        w._redraw_all()
        w.read_head.setPos(start)

    def _export_region(self, start, end):
        """
        Exporte la portion [start, end] dans un nouveau fichier WAV
        et l'ajoute a la base via SampleService.
        Ne modifie pas la waveform en memoire.
        """
        w = self.widget
        # 1) Calcul des indices d'echantillons
        s0 = int(start * w.sample_rate)
        s1 = int(end * w.sample_rate)
        if s1 <= s0:
            QMessageBox.warning(w, "Export impossible", "La selection est vide.")
            return

        # 2) Extraction du segment
        segment = w.waveform_data[s0:s1].astype("float32")

        # 3) Generation d'un nom de fichier unique
        orig_path = w.audio_file_path
        folder = os.path.dirname(orig_path)
        from backend.models.sample import Sample as DBSample

        next_id = DBSample.get_next_id()
        ext = os.path.splitext(orig_path)[1] or ".wav"
        new_name = f"SMPL_{next_id:04d}{ext}"
        target = os.path.join(folder, new_name)

        try:
            # 4) Ecriture du WAV
            sf.write(target, segment, w.sample_rate)
        except Exception as e:
            QMessageBox.critical(w, "Erreur Export", f"Impossible d'ecrire '{target}':\n{e}")
            return

        # 5) Previent SampleService pour creer l'entree DB et emettre le signal
        w.app_context.sample_store.add(target)

        QMessageBox.information(w, "Export reussi", f"Segment exporte dans :\n{target}")

    def _handle_ctrl_double_click(self, view_box, event):
        """
        Cree une region entre le marqueur immediatement a gauche et
        celui immediatement a droite du point clique.
        Si aucun marqueur a gauche : start=0.0
        Si aucun marqueur a droite : end=duration
        """
        w = self.widget
        pos = event.scenePos()
        x = float(np.clip(view_box.mapSceneToView(pos).x(), 0.0, w.duration))

        # Cas ou il n'y a aucun marqueur
        if not w.markers:
            t_left = 0.0
            t_right = w.duration
        else:
            # Recherche de l'indice du premier marqueur >= x
            idx = bisect.bisect_left(w.markers, x)

            # Determine le marqueur de gauche ou 0.0 si aucun
            if idx > 0:
                t_left = w.markers[idx - 1]
            else:
                t_left = 0.0

            # Determine le marqueur de droite ou duration si aucun
            if idx < len(w.markers):
                t_right = w.markers[idx]
            else:
                t_right = w.duration

            # Si x tombe exactement sur un marqueur, on cree
            # la region entre ce marqueur et le precedent.
            if idx < len(w.markers) and abs(x - w.markers[idx]) < 1e-6:
                if idx > 0:
                    t_left = w.markers[idx - 1]
                else:
                    t_left = 0.0

        # Supprime l'ancienne region si elle existe
        if w.region:
            w.plot.removeItem(w.region)
            w.region = None

        # Cree la nouvelle region
        w.region = self.region_cls([t_left, t_right],
                                   brush=pg.mkBrush(255, 255, 255, 40),
                                   pen=pg.mkPen("c", width=1))
        w.region.setZValue(1)
        w.region.setBounds([0, w.duration])
        w.region.sigRegionChangeFinished.connect(w.on_region_changed)
        w.region._parent = w
        add_plot_item_once(w.plot, w.region)

        # Met a jour play_start/play_end et positionne la tete
        w.play_start, w.play_end = t_left, t_right
        w.read_head.setPos(t_left)
        logger.info(f"Region creee par Ctrl+double-clic : {t_left:.3f}s -> {t_right:.3f}s")
        # Affiche immediatement la ligne de selection dans la liste
        mm = getattr(w, "marker_manager", None)
        if mm is not None:
            try:
                mm.refresh_selection_row()
            except Exception:
                pass

    def arm_selection_drag(self, scene_pos) -> None:
        """Prepare un drag de la selection qui vient d'etre creee.

        Apres un Ctrl+double-clic, si l'utilisateur garde le bouton enfonce et
        deplace la souris, on part en drag de la slice — le meme geste que
        depuis la liste de marqueurs, sans avoir a y retourner.
        """
        self.widget._selection_drag_armed = True
        self.widget._selection_drag_origin = scene_pos

    def disarm_selection_drag(self) -> None:
        self.widget._selection_drag_armed = False
        self.widget._selection_drag_origin = None

    def maybe_start_selection_drag(self, scene_pos) -> bool:
        """Demarre le drag si le curseur a assez bouge depuis l'armement."""
        w = self.widget
        if not getattr(w, "_selection_drag_armed", False):
            return False
        origin = getattr(w, "_selection_drag_origin", None)
        if origin is None:
            return False
        moved = (scene_pos - origin).manhattanLength()
        if moved < QApplication.startDragDistance():
            return False
        self.disarm_selection_drag()
        return self.start_selection_drag()

    def start_selection_drag(self) -> bool:
        """Lance le QDrag de la selection courante (MIME slice du Labo)."""
        w = self.widget
        manager = getattr(w, "marker_manager", None)
        if manager is None:
            return False
        payload = manager.selection_payload()
        if payload is None:
            return False
        audio = payload.get("audio_data")
        if audio is None or getattr(audio, "size", 0) == 0:
            return False

        mime = QMimeData()
        mime.setData(
            "application/x-sample-slice-data",
            pickle.dumps(
                {
                    "audio_data": audio,
                    "sample_rate": payload.get("sample_rate"),
                    "name": payload.get("name"),
                }
            ),
        )
        drag = QDrag(w)
        drag.setMimeData(mime)
        logger.info(
            "Drag de selection depuis la waveform : %.3fs -> %.3fs",
            float(payload.get("time") or 0.0),
            float(payload.get("end_time") or 0.0),
        )
        drag.exec(Qt.DropAction.CopyAction)
        return True

    def _set_play_start_cursor(self, x: float):
        """Place un curseur visuel de depart (annule la region si besoin)."""
        w = self.widget
        # on detruit la region si elle existait
        if w.region:
            w.plot.removeItem(w.region)
            w.region = None

        # Place le curseur de depart (ligne bleue)
        x = float(x)
        if w.play_start_cursor is not None:
            w.plot.removeItem(w.play_start_cursor)
            w.play_start_cursor = None

        w.play_start_cursor = pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen('b', width=2))
        add_plot_item_once(w.plot, w.play_start_cursor)
        w.play_start = x
        w.play_end = x
        w.read_head.setPos(x)
        logger.info(f"Curseur de depart place a {x:.3f}s")
