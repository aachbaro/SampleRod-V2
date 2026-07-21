# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Construit l'interface du WaveformWidget (layout + controls + plot).
# - Isole le code UI pour alleger wave_form.py.
# - Ne contient pas de logique audio ni d'interactions complexes.
#
# CE QUI EST COUVERT
# - Barre de sauvegarde + undo/redo.
# - Plot PyQtGraph (waveform) + read head + timer.
# - Boutons playback, loop, marker mode.
# - Liste des markers (MarkerListWidget).
#
# RESPONSABILITES TECHNIQUES
# - Instancier les widgets et brancher les callbacks du WaveformWidget.
# - Configurer le PlotWidget (axes, grille, viewbox, event filter).
#
# NON-OBJECTIFS
# - Playback audio (WaveformPlaybackController).
# - Gestes souris (WaveformInteractionsController).
# - Rendu d'enveloppe (WaveformRenderer).
#
# DEPENDANCES
# - PySide6, pyqtgraph
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSize, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QFrame,
    QSizePolicy,
    QWidget,
)
import pyqtgraph as pg

from frontend.ui import IconButton, themed_icon

from ..marker_manager import MarkerListWidget
from .waveform_plot_helpers import add_plot_item_once


_LEGACY_ICON_MAP = {
    "fa5s.save": "save",
    "fa5s.undo": "undo",
    "fa5s.redo": "redo",
    "fa5s.play": "player-play",
    "fa5s.pause": "player-pause",
    "fa5s.stop": "player-stop",
    "fa5s.sync": "repeat",
    "fa5s.map-marker-alt": "pin",
    "fa5s.times": "x",
    "fa5s.plus": "plus",
    "fa5s.trash-alt": "trash",
    "fa5s.check": "check",
    "fa5s.arrow-down": "chevron-down",
    "fa5s.times-circle": "x",
    "fa5s.bolt": "bolt",
    "mdi.waveform": "wave",
}


def _normalize_icon_name(icon_name: str) -> str:
    normalized = _LEGACY_ICON_MAP.get(icon_name, icon_name)
    return normalized or "x"


class HoverIconButton(QToolButton):
    """
    Bouton rond a icone avec effet hover doux.
    - icon_color_normal : couleur par defaut de l'icone
    - icon_color_hover  : couleur de l'icone quand la souris passe dessus
    - border_color      : couleur de la bordure du bouton
    Le background passe progressivement a blanc au hover, avec une animation.
    """
    def __init__(
        self,
        icon_name: str,
        size: int,
        icon_size: int,
        icon_color_normal: str,
        icon_color_hover: str,
        border_color: str = "#2A2A2A",
        border_color_hover: str = "#FFFFFF",
        bg_hover: "QColor | None" = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("iconOnly", True)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setContentsMargins(0, 0, 0, 0)
        self._radius = size // 2
        self._icon_name = _normalize_icon_name(icon_name)
        self._icon_color_normal = icon_color_normal
        self._icon_color_hover = icon_color_hover
        self._icon_normal = themed_icon(self._icon_name, icon_size, self._icon_color_normal)
        self._icon_hover = themed_icon(self._icon_name, icon_size, self._icon_color_hover)
        self._border_color_normal = border_color
        self._border_color_hover = border_color_hover
        self._border_color_current = border_color
        self._bg_normal = QColor(255, 255, 255, 0)
        self._bg_hover = bg_hover if bg_hover is not None else QColor(255, 255, 255, 255)
        self._current_bg = QColor(self._bg_normal)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.valueChanged.connect(self._apply_bg)
        self.setIcon(self._icon_normal)
        self.toggled.connect(self._on_toggled)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setAutoRaise(False)
        self._apply_style()

    def set_icon_pair(
        self,
        icon_name: str,
        icon_color_normal: str | None = None,
        icon_color_hover: str | None = None,
    ):
        """
        Met a jour l'icone (et optionnellement les couleurs) tout en gardant
        le comportement hover/checked coherent.
        """
        if icon_color_normal is not None:
            self._icon_color_normal = icon_color_normal
        if icon_color_hover is not None:
            self._icon_color_hover = icon_color_hover

        self._icon_name = _normalize_icon_name(icon_name)
        icon_px = self.iconSize().width() or 16
        self._icon_normal = themed_icon(self._icon_name, icon_px, self._icon_color_normal)
        self._icon_hover = themed_icon(self._icon_name, icon_px, self._icon_color_hover)
        self.setIcon(self._icon_hover if self.isChecked() else self._icon_normal)

    def enterEvent(self, ev):
        # Au hover: icone plus sombre + fond blanc (animation)
        if not self.isChecked():
            self.setIcon(self._icon_hover)
            self._border_color_current = self._border_color_hover
            self._animate(True)
            self._apply_style()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        # Quand la souris sort: retour au fond transparent + icone claire
        if not self.isChecked():
            self.setIcon(self._icon_normal)
            self._border_color_current = self._border_color_normal
            self._animate(False)
            self._apply_style()
        super().leaveEvent(ev)

    def _on_toggled(self, checked: bool):
        # Si le bouton est "toggle" (checkable), on force le style blanc
        if checked:
            self._current_bg = QColor(self._bg_hover)
            self.setIcon(self._icon_hover)
            self._border_color_current = self._border_color_hover
        else:
            self._current_bg = QColor(self._bg_normal)
            self.setIcon(self._icon_normal)
            self._border_color_current = self._border_color_normal
        self._apply_style()

    def _animate(self, hover: bool):
        self._anim.stop()
        start = self._current_bg
        end = self._bg_hover if hover else self._bg_normal
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def set_bg_hover(self, color: QColor):
        """Update hover background color (theme support)."""
        self._bg_hover = color

    def set_border_color(self, color: str):
        """Update normal border color (theme support)."""
        self._border_color_normal = color
        if self._border_color_current != self._border_color_hover:
            self._border_color_current = color
        self._apply_style()

    def update_colors(
        self,
        icon_color_normal: str | None = None,
        icon_color_hover: str | None = None,
        border_color: str | None = None,
    ):
        """Update theme colors without changing the icon shape."""
        if icon_color_normal is not None or icon_color_hover is not None:
            self.set_icon_pair(self._icon_name, icon_color_normal, icon_color_hover)
        if border_color is not None:
            self.set_border_color(border_color)

    def _apply_bg(self, color: QColor):
        self._current_bg = color
        self._apply_style()

    def _apply_style(self):
        # Applique le style (bordure + background + rayon)
        bg = self._current_bg if not self.isChecked() else self._bg_hover
        border = self._border_color_current
        rgba = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()})"
        self.setStyleSheet(
            "border: 1px solid %s; border-radius: %dpx; background: %s; padding: 0; margin: 0;"
            % (border, self._radius, rgba)
        )


class WaveformUIBuilder:
    """
    Construit toute l'UI du WaveformWidget.
    Pour modifier l'apparence:
    - tailles / couleurs des boutons: ici dans build()
    - styles globaux: feuille de style en bas
    - hauteur du plot: w.plot.setFixedHeight(...)
    """
    def __init__(self, widget, viewbox_cls):
        self.widget = widget
        self.viewbox_cls = viewbox_cls

    def build(self):
        """Construit l'ensemble de l'UI (toolbar, plot, controles, liste markers).

        Attache sur le widget: plot, curve, curve_left, curve_right, read_head,
        timer, save_button, undo_button, redo_button, play_button, pause_button,
        stop_button, loop_button, marker_mode_button, marker_list.
        """
        w = self.widget

        w.setObjectName("WaveformWidget")
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        w.layout = QVBoxLayout(w)
        w.layout.setContentsMargins(0, 0, 0, 0)
        w.layout.setSpacing(0)

        # ----- Conteneur principal (tout l'editor est dans ce bloc)
        editor = QFrame()
        editor.setObjectName("WaveformEditor")
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(6, 2, 6, 2)
        editor_layout.setSpacing(2)
        w.layout.addWidget(editor, 0, Qt.AlignmentFlag.AlignTop)

        # ----- Barre d'outils (en haut)
        # — Toolbar (compact)
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(6)

        toolbar_layout.addStretch()

        # Boutons petits pour save / undo / redo
        w.save_button = IconButton("save", tooltip="Sauvegarder le waveform - Ctrl+S", size="s")
        w.save_button.setToolTip("Save waveform - ctrl + s")
        w.save_button.clicked.connect(w.onSaveClicked)
        toolbar_layout.addWidget(w.save_button)

        w.undo_button = IconButton("undo", tooltip="Annuler - Ctrl+Z", size="s")
        w.undo_button.setToolTip("Undo - ctrl + z")
        w.undo_button.clicked.connect(w.undo)
        toolbar_layout.addWidget(w.undo_button)

        w.redo_button = IconButton("redo", tooltip="Rétablir - Ctrl+Shift+Z", size="s")
        w.redo_button.setToolTip("Redo - ctrl + shift + z")
        w.redo_button.clicked.connect(w.redo)
        toolbar_layout.addWidget(w.redo_button)

        editor_layout.addLayout(toolbar_layout)

        # ----- Waveform plot (zone centrale)
        w.plot = pg.PlotWidget(viewBox=self.viewbox_cls())
        w.plot.setFixedHeight(150)
        w.plot.showGrid(x=True, y=True, alpha=0.15)
        w.plot.setBackground("#1B1B1B")
        w.plot.hideAxis("left")
        w.plot.setMouseEnabled(x=True, y=False)

        # Courbes pour chaque canal (gauche et droite)
        w.curve_left = pg.PlotDataItem(pen=pg.mkPen("#E6E6E6", width=1))
        w.curve_right = pg.PlotDataItem(pen=pg.mkPen("#DAA520", width=1))
        add_plot_item_once(w.plot, w.curve_right)
        add_plot_item_once(w.plot, w.curve_left)

        # Pour compatibilité mono, conserver self.curve
        w.curve = pg.PlotDataItem(pen=pg.mkPen("#E6E6E6", width=1))
        add_plot_item_once(w.plot, w.curve)

        # recalcule l'enveloppe lorsqu'on zoome ou qu'on pan
        vb = w.plot.getViewBox()
        vb.sigXRangeChanged.connect(w._on_view_range_changed)

        editor_layout.addWidget(w.plot)

        # ----- Barre de controles (play/pause/stop/loop + toggles)
        # — Contrôles
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        play_layout = QHBoxLayout()
        play_layout.setSpacing(6)

        # Play / Pause / Stop (taille + icones)
        w.play_button = IconButton(
            "player-play",
            tooltip="Lire depuis le début - Ctrl+Espace",
            size="s",
            variant="primary",
        )
        w.play_button.clicked.connect(w.play_from_start)
        w.play_button.setToolTip("Play - ctrl + space")
        play_layout.addWidget(w.play_button)

        w.pause_button = IconButton("player-pause", tooltip="Pause / reprise - Espace", size="s")
        w.pause_button.clicked.connect(w.pause_or_resume)
        w.pause_button.setToolTip("Pause / Resume - space")
        play_layout.addWidget(w.pause_button)

        w.stop_button = IconButton("player-stop", tooltip="Stop et retour au début - Alt+Espace", size="s")
        w.stop_button.clicked.connect(w.stop_and_reset)
        w.stop_button.setToolTip("Stop and Reset - alt + space")
        play_layout.addWidget(w.stop_button)

        # Loop: plus logique a cote des boutons de lecture
        w.loop_button = IconButton("repeat", tooltip="Activer / désactiver la boucle - Ctrl+L", size="s")
        w.loop_button.setCheckable(True)
        w.loop_button.setProperty("toggle", True)
        w.loop_button.toggled.connect(w.toggle_loop)
        w.loop_button.setToolTip("Loop ON/OF - ctrl + l")
        play_layout.addWidget(w.loop_button)
        w.loop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        controls_layout.addLayout(play_layout)
        controls_layout.addStretch()

        # Toggles (Marker Mode)
        toggles = QHBoxLayout()
        toggles.setSpacing(6)

        # Marker Mode
        w.marker_mode_button = IconButton("pin", tooltip="Mode marqueurs - Ctrl+G", size="s")
        w.marker_mode_button.setCheckable(True)
        w.marker_mode_button.setProperty("toggle", True)
        w.marker_mode_button.setToolTip("Marker Mode ON/OFF - ctrl + g")
        w.marker_mode_button.toggled.connect(w.toggle_marker_mode)
        toggles.addWidget(w.marker_mode_button)

        controls_layout.addLayout(toggles)
        editor_layout.addLayout(controls_layout)

        # ----- Liste de markers (pleine largeur, sous les controles)
        w.marker_list = MarkerListWidget(w)
        w.marker_list.setObjectName("MarkerList")
        w.marker_list.setFrameShape(QFrame.Shape.NoFrame)
        w.marker_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        w.marker_list.setMaximumHeight(120)
        w.marker_list.setMinimumHeight(0)
        w.marker_list.setSizeAdjustPolicy(w.marker_list.SizeAdjustPolicy.AdjustToContents)
        w.marker_list.itemClicked.connect(w.on_marker_list_clicked)
        w.marker_list.itemDoubleClicked.connect(w.on_marker_list_double_clicked)
        w.marker_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.marker_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        w.marker_list.setVisible(False)
        editor_layout.addWidget(w.marker_list)

        # ----- Read head + timer (logic audio)
        # — Read head + timer
        w.read_head = pg.InfiniteLine(angle=90, pen=pg.mkPen("r", width=2))
        add_plot_item_once(w.plot, w.read_head)
        w.timer = QTimer(w)
        w.timer.timeout.connect(w.update_read_head)
        w.stop_timer_signal.connect(w.timer.stop)
        w.timer.start(5)

        # ----- EventFilter pour les interactions (clic / drag / raccourcis)
        # — Install filter une seule fois
        w.plot.getViewBox().scene().installEventFilter(w)

        # ----- Styles globaux de l'editor
        w.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Styles globaux via `frontend/styles/theme.qss`
