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
# - PyQt6 (Qt, QListWidgetItem)
# - pyqtgraph (InfiniteLine)
# - qtawesome (icones chargees par le UI builder)
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import bisect
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup
from PyQt6.QtWidgets import QListWidgetItem, QGraphicsOpacityEffect

logger = logging.getLogger("waveform_markers")


class WaveformMarkersController:
    def __init__(self, widget, region_cls):
        self.widget = widget
        self.region_cls = region_cls
        # Animation douce de la liste de markers (show/hide) pour eviter:
        # - un gros "jump" de layout quand le 1er marker est ajoute
        # - une liste qui prend trop de place verticale
        self._marker_list_max_height = 92
        self._marker_list_target_visible = False
        self._marker_list_opacity_effect: QGraphicsOpacityEffect | None = None
        self._marker_list_height_anim: QPropertyAnimation | None = None
        self._marker_list_opacity_anim: QPropertyAnimation | None = None
        self._marker_list_anim_group: QParallelAnimationGroup | None = None
        self._setup_marker_list_animation()

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
        w.plot.addItem(w.region)

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
        # montrer/cacher automatiquement selon qu'il y a des marqueurs
        self._set_marker_list_visible(bool(w.marker_manager.markers), animated=True)

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

    # ------------------------------------------------------------------
    # Marker list (UI): hauteur limitee + transition douce
    # ------------------------------------------------------------------

    def _setup_marker_list_animation(self):
        """
        Configure la liste de markers pour:
        - etre compacte (hauteur max)
        - apparaitre/disparaitre en douceur (height + opacity)

        Note: c'est volontairement ici (controller markers) car c'est lie
        a la presence/absence de markers, et ca permet d'animer l'expansion
        de la SampleCard de maniere naturelle.
        """
        w = self.widget
        marker_list = getattr(w, "marker_list", None)
        if marker_list is None:
            return

        # Etat initial: invisible, "plie" a 0px.
        marker_list.setMinimumHeight(0)
        marker_list.setMaximumHeight(0)
        marker_list.setVisible(False)

        # Effet d'opacite (fade)
        self._marker_list_opacity_effect = QGraphicsOpacityEffect(marker_list)
        self._marker_list_opacity_effect.setOpacity(0.0)
        marker_list.setGraphicsEffect(self._marker_list_opacity_effect)

        # Animations (hauteur + opacite)
        self._marker_list_height_anim = QPropertyAnimation(marker_list, b"maximumHeight", marker_list)
        self._marker_list_height_anim.setDuration(160)
        self._marker_list_height_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._marker_list_opacity_anim = QPropertyAnimation(self._marker_list_opacity_effect, b"opacity", marker_list)
        self._marker_list_opacity_anim.setDuration(160)
        self._marker_list_opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._marker_list_anim_group = QParallelAnimationGroup(marker_list)
        self._marker_list_anim_group.addAnimation(self._marker_list_height_anim)
        self._marker_list_anim_group.addAnimation(self._marker_list_opacity_anim)
        self._marker_list_anim_group.finished.connect(self._on_marker_list_anim_finished)

    def _set_marker_list_visible(self, visible: bool, *, animated: bool):
        w = self.widget
        marker_list = getattr(w, "marker_list", None)
        if marker_list is None:
            return

        # Fallback "simple" si l'animation n'est pas disponible.
        if not self._marker_list_anim_group or not self._marker_list_height_anim or not self._marker_list_opacity_anim:
            marker_list.setVisible(visible)
            return

        # Etat deja OK -> rien a faire.
        if visible and marker_list.isVisible() and marker_list.maximumHeight() == self._marker_list_max_height:
            return
        if (not visible) and (not marker_list.isVisible() or marker_list.maximumHeight() == 0):
            marker_list.setVisible(False)
            marker_list.setMaximumHeight(0)
            if self._marker_list_opacity_effect:
                self._marker_list_opacity_effect.setOpacity(0.0)
            return

        self._marker_list_target_visible = visible
        self._marker_list_anim_group.stop()

        # On garde visible pendant l'animation, puis on cache a la fin.
        marker_list.setVisible(True)

        start_h = marker_list.maximumHeight()
        start_op = self._marker_list_opacity_effect.opacity() if self._marker_list_opacity_effect else 1.0
        end_h = self._marker_list_max_height if visible else 0
        end_op = 1.0 if visible else 0.0

        if not animated:
            marker_list.setMaximumHeight(end_h)
            if self._marker_list_opacity_effect:
                self._marker_list_opacity_effect.setOpacity(end_op)
            marker_list.setVisible(visible)
            return

        self._marker_list_height_anim.setStartValue(start_h)
        self._marker_list_height_anim.setEndValue(end_h)
        self._marker_list_opacity_anim.setStartValue(start_op)
        self._marker_list_opacity_anim.setEndValue(end_op)
        self._marker_list_anim_group.start()

    def _on_marker_list_anim_finished(self):
        w = self.widget
        marker_list = getattr(w, "marker_list", None)
        if marker_list is None:
            return

        if self._marker_list_target_visible:
            marker_list.setVisible(True)
            marker_list.setMaximumHeight(self._marker_list_max_height)
            if self._marker_list_opacity_effect:
                self._marker_list_opacity_effect.setOpacity(1.0)
        else:
            marker_list.setVisible(False)
            marker_list.setMaximumHeight(0)
            if self._marker_list_opacity_effect:
                self._marker_list_opacity_effect.setOpacity(0.0)
