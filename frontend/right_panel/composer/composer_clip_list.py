"""
------------------------------------------------------------------------------
Sample Composer - Clip List Widget (DnD + reorder)
------------------------------------------------------------------------------
Role
----
QListWidget specialise pour le Compositeur:
- accepte les drops externes "slice" (depuis MarkerManager)
- permet le reorder interne (drag & drop entre items)
- notifie le parent via signals Python (Qt)

Pourquoi un widget dedie ?
--------------------------
On veut un comportement DnD propre sans surcharger ComposerWidget:
- isoler la logique dragEnter/dragMove/drop
- garder ComposerWidget concentre sur "modele + rendu preview"
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, QPropertyAnimation
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QListWidget,
    QWidget,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QGraphicsOpacityEffect,
)

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton
from frontend.styles import theme
from .composer_dnd import has_slice, has_sample_card, parse_slice_mime, parse_sample_card_mime

logger = logging.getLogger("sample_composer_clip_list")


class ComposerClipListWidget(QListWidget):
    sliceDropped = Signal(object)  # dict payload normalise
    sampleCardDropped = Signal(object)  # dict payload (sample_id)
    orderChanged = Signal(object)  # list[int] clip_ids

    def __init__(self, parent=None):
        super().__init__(parent)
        logger.info("[ComposerClipList] Initialisation DnD (start)")
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        # DragDrop: permet a la fois les drops externes (Copy) et le reorder interne (Move).
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        logger.info("[ComposerClipList] DnD list ready (acceptDrops=True, dragEnabled=True)")

        # Pour un widget "colonne", on ne veut pas de focus outline.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event):
        if has_slice(event.mimeData()) or has_sample_card(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if has_slice(event.mimeData()) or has_sample_card(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        # Drop externe: slice depuis MarkerManager.
        if has_slice(event.mimeData()):
            try:
                payload = parse_slice_mime(event.mimeData())
            except Exception:
                logger.exception("[Composer] Invalid slice drop")
                event.ignore()
                return

            self.sliceDropped.emit(payload)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        # Drop externe: sample card
        if has_sample_card(event.mimeData()):
            try:
                payload = parse_sample_card_mime(event.mimeData())
            except Exception:
                logger.exception("[Composer] Invalid sample-card drop")
                event.ignore()
                return

            self.sampleCardDropped.emit(payload)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        # Drop interne (reorder):
        super().dropEvent(event)
        self._emit_order_changed()

    # ------------------------------------------------------------------ helpers
    def _emit_order_changed(self) -> None:
        ids: list[int] = []
        for i in range(self.count()):
            item = self.item(i)
            try:
                cid = int(item.data(Qt.ItemDataRole.UserRole))
            except Exception:
                continue
            ids.append(cid)
        self.orderChanged.emit(ids)


class ComposerClipRow(QWidget):
    """
    Row custom affichee dans la liste:
    - label (texte du clip)
    - bouton play (lecture du segment)
    - bouton delete (retire la slice du compositeur)
    """

    playRequested = Signal(int)
    silenceRequested = Signal(int)
    removeRequested = Signal(int)
    clicked = Signal()

    def __init__(self, clip_id: int, label: str, parent=None):
        super().__init__(parent)
        # ------------------------------------------------------------------
        # DIMENSIONS / "TAILLE DE CARTE"
        # - setMinimumHeight(...) : hauteur mini de la row (impacte la rondeur).
        # - Marges du layout : padding interne (haut/bas/gauche/droite).
        # - Spacing : espace entre label et boutons.
        # ------------------------------------------------------------------
        self.clip_id = int(clip_id)
        self.setObjectName("ComposerClipRow")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(32)
        # Permet au QSS (background/border) de s'appliquer correctement.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._hovered = False

        layout = QHBoxLayout(self)
        # Marges/spacing calques sur DirectoryRow pour un rendu identique.
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # ------------------------------------------------------------------
        # CONTENU TEXTE
        # - QLabel : texte visible.
        # - MinimumWidth(0) : permet l'elipsis automatique si besoin.
        # ------------------------------------------------------------------
        self.label = QLabel(label)
        self.label.setObjectName("ComposerClipLabel")
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.label.setMinimumWidth(0)
        # Laisse les clics passer au row (pour selectionner l'item).
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # ------------------------------------------------------------------
        # ZONE ACTIONS (BOUTONS)
        # - actions_wrap : conteneur des boutons a droite.
        # - play / silence / delete : actions visibles au survol.
        # ------------------------------------------------------------------
        self.actions_wrap = QWidget(self)
        actions_layout = QHBoxLayout(self.actions_wrap)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        p = theme.manager.p
        self.play_btn = HoverIconButton(
            "fa5s.play",
            size=24,
            icon_size=10,
            icon_color_normal=p.TEXT_MUTED,
            icon_color_hover=p.BG_DARK,
            parent=self.actions_wrap,
        )
        self.play_btn.setToolTip("Lire ce segment")

        self.silence_btn = HoverIconButton(
            "fa5s.plus",
            size=24,
            icon_size=10,
            icon_color_normal=p.TEXT_MUTED,
            icon_color_hover=p.BG_DARK,
            parent=self.actions_wrap,
        )
        self.silence_btn.setToolTip("Ajouter 1s de silence après ce segment")

        self.delete_btn = HoverIconButton(
            "fa5s.trash-alt",
            size=24,
            icon_size=10,
            icon_color_normal=p.ERROR,
            icon_color_hover=p.BG_DARK,
            parent=self.actions_wrap,
        )
        self.delete_btn.setToolTip("Supprimer ce segment")

        actions_layout.addWidget(self.play_btn)
        actions_layout.addWidget(self.silence_btn)
        actions_layout.addWidget(self.delete_btn)

        layout.addWidget(self.label, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.actions_wrap, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ------------------------------------------------------------------
        # VISIBILITE / ANIMATION (HOVER)
        # - Opacite 0 -> boutons caches.
        # - Animation courte pour l'apparition au survol.
        # ------------------------------------------------------------------
        self._actions_fx = QGraphicsOpacityEffect(self.actions_wrap)
        self._actions_fx.setOpacity(0.0)
        self.actions_wrap.setGraphicsEffect(self._actions_fx)
        self.play_btn.setEnabled(False)
        self.silence_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self._actions_anim = QPropertyAnimation(self._actions_fx, b"opacity", self)
        self._actions_anim.setDuration(140)

        self.play_btn.clicked.connect(lambda: self.playRequested.emit(self.clip_id))
        self.silence_btn.clicked.connect(lambda: self.silenceRequested.emit(self.clip_id))
        self.delete_btn.clicked.connect(lambda: self.removeRequested.emit(self.clip_id))

        theme.manager.themeChanged.connect(lambda _: self._restyle_buttons())

    # ------------------------------------------------------------------ restyle
    def _restyle_buttons(self) -> None:
        p = theme.manager.p
        self.play_btn.update_colors(p.TEXT_MUTED, p.BG_DARK)
        self.silence_btn.update_colors(p.TEXT_MUTED, p.BG_DARK)
        self.delete_btn.update_colors(p.ERROR, p.BG_DARK)
        self.update()

    # ------------------------------------------------------------------ state
    def set_selected(self, selected: bool) -> None:
        # Flag "selected" pilote la couleur de fond dans paintEvent.
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    # ------------------------------------------------------------------ events
    def mousePressEvent(self, event):
        # Le clic sur la row notifie le parent pour selectionner l'item.
        self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        # Survol: boutons visibles + repaint pour le pill.
        self._hovered = True
        self.update()
        self._set_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        # Sortie: boutons caches + repaint pour le pill.
        self._hovered = False
        self.update()
        self._set_actions_visible(False)
        super().leaveEvent(event)

    def _set_actions_visible(self, visible: bool) -> None:
        self._actions_anim.stop()
        self._actions_anim.setStartValue(self._actions_fx.opacity())
        self._actions_anim.setEndValue(1.0 if visible else 0.0)
        self._actions_anim.start()
        self.play_btn.setEnabled(visible)
        self.silence_btn.setEnabled(visible)
        self.delete_btn.setEnabled(visible)

    def paintEvent(self, event):
        """
        Dessin manuel pour garantir un rendu "pill" (coins parfaitement ronds)
        quel que soit le moteur QSS/Qt.
        """
        # ------------------------------------------------------------------
        # RENDU "PILL"
        # - radius = hauteur / 2 => capsule parfaite.
        # - Couleurs dependant de l'etat (hover / selected).
        # ------------------------------------------------------------------
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2.0

        # Couleurs (harmonisees avec composer_ui.py)
        bg = QColor(0, 0, 0, 0)  # transparent
        border = QColor(0, 0, 0, 0)
        p = theme.manager.p
        if self.property("selected"):
            bg = QColor(p.BG_CARD)
            border = QColor(p.BORDER)
        elif self._hovered:
            bg = QColor(p.BG_HOVER)
            border = QColor(p.BORDER_LIGHT)

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, radius, radius)
