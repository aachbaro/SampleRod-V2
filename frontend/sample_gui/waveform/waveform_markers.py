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
from .waveform_grid import grid_marker_times, merge_grid_markers
from .waveform_grid_session import GridSession, GridSettings
from .waveform_plot_helpers import add_plot_item_once

logger = logging.getLogger("waveform_markers")


class WaveformMarkersController:
    """Ajoute/supprime les markers et synchronise la liste, le plot et le MarkerManager."""

    def __init__(self, widget, region_cls):
        self.widget = widget
        self.region_cls = region_cls
        # Grille en cours de reglage (voir waveform_grid_session.py).
        self.grid_session = GridSession()

    def toggle_marker_mode(self, checked: bool):
        """Active/desactive le mode marqueurs."""
        w = self.widget
        w.marker_mode = checked
        # Synchronise l'etat visuel du bouton (utile pour les raccourcis clavier)
        if w.marker_mode_button.isChecked() != checked:
            w.marker_mode_button.setChecked(checked)

    def add_marker(self, t: float):
        """Ajoute un marqueur et met a jour la liste."""
        w = self.widget
        # Securite : ne pas ajouter si un marker existe deja ici
        tol = 1e-6
        if any(abs(existing - t) < tol for existing in w.markers):
            return
        # add_marker rafraichit deja la liste : un second appel ici doublait
        # le cout de chaque pose.
        w.marker_manager.add_marker(t)
        # Signale seulement les poses MANUELLES : les batchs programmatiques
        # (projection d'une analyse, restauration de session) desactivent
        # l'historique et n'ont pas a declencher de re-decoupage.
        if getattr(w, "_record_history", True):
            w.markerAdded.emit(float(t))

    def on_marker_moved(self, line: pg.InfiniteLine):
        self.widget.marker_manager.on_marker_moved(line)

    def _on_marker_move_finished(self, line):
        self.widget.marker_manager.on_marker_move_finished(line)

    def grid_origin_s(self) -> float:
        """Point de depart du decoupage au tempo.

        Priorite au marqueur qui precede (ou porte) la tete de lecture : c'est
        le geste naturel — on pose un marqueur sur le premier temps, puis on
        extrapole. A defaut, le debut de la selection, sinon zero.
        """
        w = self.widget
        cursor = float(getattr(w, "play_start", 0.0) or 0.0)
        markers = sorted(float(value) for value in (getattr(w, "markers", None) or []))
        previous = [value for value in markers if value <= cursor + 1e-6]
        if previous:
            return previous[-1]
        return max(0.0, cursor)

    def apply_tempo_grid(self, bpm: float, steps_per_slice: int) -> int:
        """Pose une grille de marqueurs au tempo. Retourne le nombre ajoute.

        Les marqueurs deja presents sont conserves : la grille vient s'ajouter
        (sans doublon), on ne detruit pas un decoupage manuel existant.
        """
        w = self.widget
        duration = float(getattr(w, "duration", 0.0) or 0.0)
        if duration <= 0.0:
            return 0
        origin = self.grid_origin_s()
        grid = grid_marker_times(
            origin_s=origin,
            bpm=float(bpm),
            steps_per_slice=int(steps_per_slice),
            duration_s=duration,
        )
        if not grid:
            return 0

        existing = sorted(float(value) for value in (getattr(w, "markers", None) or []))
        existing_set = set(existing)
        merged = merge_grid_markers(existing, grid)
        added = [value for value in merged if value not in existing_set]
        if not added:
            return 0

        # Un seul bloc d'historique : annuler doit retirer toute la grille,
        # pas un marqueur a la fois. Et une seule reconstruction de liste :
        # sans la pose groupee, 200 marqueurs = 200 rebuilds = plusieurs
        # secondes de gel.
        w._record_history = False
        try:
            with w.marker_manager.batch_updates():
                for value in added:
                    self.add_marker(float(value))
        finally:
            w._record_history = True
        w._push_history({"action": "tempo_grid", "added": added})
        return len(added)

    # -- Grille en direct ----------------------------------------------------

    def start_grid_session(self, settings: GridSettings) -> int:
        """Ouvre une session de reglage et pose la premiere grille."""
        w = self.widget
        session = self.grid_session
        session.origin_s = self.grid_origin_s()
        session.duration_s = float(getattr(w, "duration", 0.0) or 0.0)
        times = session.planned_times(settings)
        if not times:
            return 0
        placed = self._place_grid(times)
        session.opened(placed, settings)
        logger.info(
            "Grille en direct: %s marqueur(s) (%.2f BPM, %s steps, decalage %.3fs)",
            len(placed), settings.bpm, settings.steps_per_slice, settings.offset_s,
        )
        return len(placed)

    def update_grid_session(self, settings: GridSettings) -> int:
        """Applique de nouveaux reglages a la grille en cours.

        Deux chemins : si seul le decalage bouge, on TRANSLATE les lignes
        existantes (~26 ms sur 213 marqueurs, donc utilisable au drag) ; sinon
        on re-pose la grille (~270 ms, reserve a la validation d'un champ).
        """
        session = self.grid_session
        if not session.active:
            return self.start_grid_session(settings)

        if session.is_offset_only(settings):
            delta = session.offset_delta(settings)
            if abs(delta) < 1e-9:
                return len(session.owned)
            # La translation rapide ne vaut que si la grille garde le meme
            # nombre de marqueurs. Aux extremes du slider, un marqueur sort du
            # fichier ou un autre y rentre : la translation seule le perdrait
            # sans jamais le rendre, on repose donc franchement.
            if len(session.planned_times(settings)) == len(session.owned):
                moved = self.widget.marker_manager.shift_markers(session.owned, delta)
                session.moved(moved, settings)
                return len(moved)

        self._clear_grid_markers()
        times = session.planned_times(settings)
        placed = self._place_grid(times) if times else []
        session.moved(placed, settings)
        return len(placed)

    def commit_grid_session(self) -> int:
        """Fige la grille : elle devient du decoupage ordinaire."""
        session = self.grid_session
        count = len(session.owned)
        if count:
            self.widget._push_history(
                {"action": "tempo_grid", "added": list(session.owned)}
            )
            logger.info("Grille validee: %s marqueur(s) conserves", count)
        session.closed()
        return count

    def cancel_grid_session(self) -> None:
        """Abandonne la grille : on retire tout ce qu'elle avait pose."""
        session = self.grid_session
        if session.active and session.owned:
            self._clear_grid_markers()
            logger.info("Grille annulee")
        session.closed()

    def _place_grid(self, times) -> list[float]:
        """Pose une serie de marqueurs sans historique ni journal par unite."""
        w = self.widget
        existing = set(float(value) for value in (getattr(w, "markers", None) or []))
        placed: list[float] = []
        w._record_history = False
        try:
            with w.marker_manager.batch_updates():
                for value in times:
                    if any(abs(value - kept) <= 1e-6 for kept in existing):
                        continue
                    self.add_marker(float(value))
                    existing.add(float(value))
                    placed.append(float(value))
        finally:
            w._record_history = True
        return placed

    def _clear_grid_markers(self) -> None:
        """Retire uniquement les marqueurs poses par la grille."""
        w = self.widget
        w._record_history = False
        try:
            with w.marker_manager.batch_updates():
                for value in self.grid_session.owned:
                    if value in w.markers:
                        w.marker_manager.remove_marker(float(value))
        finally:
            w._record_history = True

    def remove_marker(self, t: float):
        """Supprime un marqueur et met a jour la liste."""
        w = self.widget
        w.marker_manager.remove_marker(t)
        self._refresh_marker_list()

    def on_marker_list_clicked(self, item: QListWidgetItem):
        """Cree une region entre le marker clique et le suivant, place la tete de lecture."""
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
        # Affiche immediatement la ligne de selection dans la liste
        mm = getattr(w, "marker_manager", None)
        if mm is not None:
            try:
                mm.refresh_selection_row()
            except Exception:
                pass

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
