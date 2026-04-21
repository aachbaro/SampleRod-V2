# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Centralise la gestion des marqueurs pour WaveformWidget.
# - S'appuie sur MarkerManager pour la data + lines, et gere la UI associee.
# - Permet d'alleger wave_form.py en isolant la logique markers.
#
# CE QUI EST COUVERT
# - Ajout / suppression / deplacement de markers.
# - Rafraichissement de la liste de markers.
# - Interaction avec la liste (clic / double-clic).
# - Mode marker (toggle + icon).
# - Creation de line sans historique (undo cut).
#
# RESPONSABILITES TECHNIQUES
# - Synchroniser markers / marker_lines / liste.
# - Creer une region depuis un marker de liste (ContextMenuLinearRegionItem).
# - Mettre a jour play_start/play_end et read_head quand necessaire.
#
# NON-OBJECTIFS
# - Gestes souris globaux (WaveformInteractionsController).
# - Playback audio (WaveformPlaybackController).
# - Logique de selection/cut/export (WaveformRegionController).
#
# DEPENDANCES
# - PySide6 (Qt, QListWidgetItem)
# - pyqtgraph (InfiniteLine)
# - qtawesome (icones chargees par le UI builder)
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import bisect
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem
from .waveform_plot_helpers import add_plot_item_once

logger = logging.getLogger("waveform_markers")


class WaveformMarkersController:
    def __init__(self, widget, region_cls):
        self.widget = widget
        self.region_cls = region_cls

    def toggle_marker_mode(self, checked: bool):
        """Active/desactive le mode marqueurs."""
        w = self.widget
        w.marker_mode = checked
        # Synchronise l'etat visuel du bouton (utile pour les raccourcis clavier)
        if w.marker_mode_button.isChecked() != checked:
            w.marker_mode_button.setChecked(checked)
        # Feedback visuel: "allume" la colonne de markers
        marker_list = getattr(w, "marker_list", None)
        if marker_list is not None and hasattr(marker_list, "set_active_border"):
            try:
                marker_list.set_active_border(checked)
            except Exception:
                pass

    def add_marker(self, t: float):
        """Ajoute un marqueur et met a jour la liste."""
        w = self.widget
        # Securite : ne pas ajouter si un marker existe deja ici
        tol = 1e-6
        if any(abs(existing - t) < tol for existing in w.markers):
            return
        w.marker_manager.add_marker(t)
        self._refresh_marker_list()

    def on_marker_moved(self, line: pg.InfiniteLine):
        self.widget.marker_manager.on_marker_moved(line)

    def _on_marker_move_finished(self, line):
        self.widget.marker_manager.on_marker_move_finished(line)

    def remove_marker(self, t: float):
        """Supprime un marqueur et met a jour la liste."""
        w = self.widget
        w.marker_manager.remove_marker(t)
        self._refresh_marker_list()

    def on_marker_list_clicked(self, item: QListWidgetItem):
        w = self.widget
        payload = item.data(Qt.ItemDataRole.UserRole)
        t = payload.get("time") if isinstance(payload, dict) else payload
        # trouve l'indice exact
        idx = w.markers.index(t)
        w.current_marker_idx = idx
        # next bound
        if idx + 1 < len(w.markers):
            t2 = w.markers[idx + 1]
        else:
            t2 = w.duration

        # supprime l'ancienne region
        if w.region:
            w.plot.removeItem(w.region)

        # cree la nouvelle region
        w.region = self.region_cls(
            [t, t2],
            brush=pg.mkBrush(255, 255, 255, 40),
            pen=pg.mkPen("c", width=1),
        )
        w.region.setZValue(1)
        w.region.setBounds([0, w.duration])
        w.region.sigRegionChangeFinished.connect(w.on_region_changed)
        w.region._parent = w
        add_plot_item_once(w.plot, w.region)

        # mets a jour play_start / play_end et place la tete de lecture
        w.play_start, w.play_end = t, t2
        w.read_head.setPos(t)
        logger.info(f"Region mise a jour: {t:.3f}s -> {t2:.3f}s")

    def on_marker_list_double_clicked(self, item: QListWidgetItem):
        payload = item.data(Qt.ItemDataRole.UserRole)
        t = payload.get("time") if isinstance(payload, dict) else payload
        self.remove_marker(t)

    def _refresh_marker_list(self):
        w = self.widget
        w.marker_manager.refresh_marker_list()

    def _create_marker_line(self, t: float):
        """Cree la ligne d'un marker sans toucher a l'historique."""
        w = self.widget
        bisect.insort(w.markers, t)
        line = pg.InfiniteLine(pos=t, angle=90, pen=pg.mkPen("y", width=2))
        line.setMovable(True)
        line.old_pos = t
        line.sigPositionChanged.connect(lambda _, l=line: w.on_marker_moved(l))
        line.sigPositionChangeFinished.connect(lambda _, l=line: w._on_marker_move_finished(l))
        w.marker_lines[t] = line
