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
# - PySide6, pyqtgraph, qtawesome
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSize, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QFrame,
    QWidget,
)
import pyqtgraph as pg
import qtawesome as qta

from ..marker_manager import MarkerListWidget
from .waveform_plot_helpers import add_plot_item_once


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
        self._icon_name = icon_name
        self._icon_color_normal = icon_color_normal
        self._icon_color_hover = icon_color_hover
        self._icon_normal = qta.icon(icon_name, color=self._icon_color_normal)
        self._icon_hover = qta.icon(icon_name, color=self._icon_color_hover)
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

        self._icon_normal = qta.icon(icon_name, color=self._icon_color_normal)
        self._icon_hover = qta.icon(icon_name, color=self._icon_color_hover)
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
        w = self.widget

        w.setObjectName("WaveformWidget")
        w.layout = QVBoxLayout(w)
        w.layout.setContentsMargins(6, 6, 6, 6)
        w.layout.setSpacing(0)

        # ----- Conteneur principal (tout l'editor est dans ce bloc)
        editor = QFrame()
        editor.setObjectName("WaveformEditor")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(10, 10, 10, 10)
        editor_layout.setSpacing(6)
        w.layout.addWidget(editor)

        # ----- Barre d'outils (en haut)
        # — Toolbar (compact)
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        toolbar_layout.addStretch()

        # Boutons petits pour save / undo / redo
        # Save
        w.save_button = HoverIconButton(
            "fa5s.save",
            size=24,
            icon_size=10,
            icon_color_normal="#E6E6E6",
            icon_color_hover="#1B1B1B",
        )
        w.save_button.setToolTip("Save waveform - ctrl + s")
        w.save_button.clicked.connect(w.onSaveClicked)
        toolbar_layout.addWidget(w.save_button)

        # Undo / Redo
        w.undo_button = HoverIconButton(
            "fa5s.undo",
            size=24,
            icon_size=10,
            icon_color_normal="#E0E0E0",
            icon_color_hover="#1B1B1B",
        )
        w.undo_button.setToolTip("Undo - ctrl + z")
        w.undo_button.clicked.connect(w.undo)
        toolbar_layout.addWidget(w.undo_button)

        w.redo_button = HoverIconButton(
            "fa5s.redo",
            size=24,
            icon_size=10,
            icon_color_normal="#E0E0E0",
            icon_color_hover="#1B1B1B",
        )
        w.redo_button.setToolTip("Redo - ctrl + shift + z")
        w.redo_button.clicked.connect(w.redo)
        toolbar_layout.addWidget(w.redo_button)

        editor_layout.addLayout(toolbar_layout)

        # ----- Waveform plot (zone centrale) + colonne markers (droite)
        # — Waveform plot
        plot_height = 158
        w.plot = pg.PlotWidget(viewBox=self.viewbox_cls())
        w.plot.setFixedHeight(plot_height)
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

        # Layout horizontal: waveform a gauche, colonne markers a droite.
        plot_row = QWidget()
        plot_row.setObjectName("WaveformPlotRow")
        plot_row_layout = QHBoxLayout(plot_row)
        plot_row_layout.setContentsMargins(0, 0, 0, 0)
        plot_row_layout.setSpacing(6)
        plot_row_layout.addWidget(w.plot, 1)

        # Colonne markers (fine, a droite).
        w.marker_list = MarkerListWidget(w)
        w.marker_list.setObjectName("MarkerList")
        w.marker_list.setFrameShape(QFrame.Shape.NoFrame)
        # La colonne doit "matcher" les boutons ronds (24px).
        # On affiche uniquement l'index numerique du marker (1,2,3...) en petit.
        w.marker_list.setFixedWidth(24)
        w.marker_list.setFixedHeight(plot_height)
        w.marker_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        w.marker_list.itemClicked.connect(w.on_marker_list_clicked)
        w.marker_list.itemDoubleClicked.connect(w.on_marker_list_double_clicked)
        w.marker_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Scrollbar cachee -> colonne plus clean (le wheel scroll fonctionne quand meme).
        w.marker_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        plot_row_layout.addWidget(w.marker_list, 0, alignment=Qt.AlignmentFlag.AlignTop)

        editor_layout.addWidget(plot_row)

        # ----- Barre de controles (play/pause/stop/loop + toggles)
        # — Contrôles
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        play_layout = QHBoxLayout()
        play_layout.setSpacing(6)

        # Play / Pause / Stop (taille + icones)
        w.play_button = HoverIconButton(
            "fa5s.play",
            size=24,
            icon_size=10,
            icon_color_normal="#EDEDED",
            icon_color_hover="#1B1B1B",
        )
        w.play_button.setProperty("role", "primary")
        w.play_button.clicked.connect(w.play_from_start)
        w.play_button.setToolTip("Play - ctrl + space")
        play_layout.addWidget(w.play_button)

        w.pause_button = HoverIconButton(
            "fa5s.pause",
            size=24,
            icon_size=10,
            icon_color_normal="#E0E0E0",
            icon_color_hover="#1B1B1B",
        )
        w.pause_button.clicked.connect(w.pause_or_resume)
        w.pause_button.setToolTip("Pause / Resume - space")
        play_layout.addWidget(w.pause_button)

        w.stop_button = HoverIconButton(
            "fa5s.stop",
            size=24,
            icon_size=10,
            icon_color_normal="#E0E0E0",
            icon_color_hover="#1B1B1B",
        )
        w.stop_button.clicked.connect(w.stop_and_reset)
        w.stop_button.setToolTip("Stop and Reset - alt + space")
        play_layout.addWidget(w.stop_button)

        # Loop: plus logique a cote des boutons de lecture
        w.loop_button = HoverIconButton(
            "fa5s.sync",
            size=24,
            icon_size=10,
            icon_color_normal="#D2D2D2",
            icon_color_hover="#1B1B1B",
        )
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
        w.marker_mode_button = HoverIconButton(
            "fa5s.map-marker-alt",
            size=24,
            icon_size=10,
            icon_color_normal="#D2D2D2",
            icon_color_hover="#1B1B1B",
        )
        w.marker_mode_button.setCheckable(True)
        w.marker_mode_button.setProperty("toggle", True)
        w.marker_mode_button.setToolTip("Marker Mode ON/OFF - ctrl + g")
        w.marker_mode_button.toggled.connect(w.toggle_marker_mode)
        toggles.addWidget(w.marker_mode_button)

        controls_layout.addLayout(toggles)
        editor_layout.addLayout(controls_layout)

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
