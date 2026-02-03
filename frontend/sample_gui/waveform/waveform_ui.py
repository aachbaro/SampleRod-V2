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
# - PyQt6, pyqtgraph, qtawesome
# -----------------------------------------------------------------------------

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton
import pyqtgraph as pg
import qtawesome as qta

from ..marker_manager import MarkerListWidget


class WaveformUIBuilder:
    def __init__(self, widget, viewbox_cls):
        self.widget = widget
        self.viewbox_cls = viewbox_cls

    def build(self):
        w = self.widget

        w.layout = QVBoxLayout(w)

        # — Save (enregistre l'état actuel de waveform_data)
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        w.save_button = QPushButton()
        w.save_button.setIcon(qta.icon("fa5s.save", color="lightgray"))
        w.save_button.setToolTip("Save waveform - ctrl + s")
        w.save_button.setFixedSize(30, 30)
        w.save_button.clicked.connect(w.onSaveClicked)
        save_layout.addWidget(w.save_button)
        w.layout.addLayout(save_layout)

        # — Undo / Redo au-dessus de la waveform
        h_hist = QHBoxLayout()
        # Undo
        w.undo_button = QPushButton()
        w.undo_button.setFixedSize(30, 30)
        w.undo_button.setIcon(qta.icon("fa5s.undo", color="lightgray"))
        w.undo_button.setToolTip("Undo - ctrl + z")
        w.undo_button.clicked.connect(w.undo)
        h_hist.addWidget(w.undo_button)
        # Redo
        w.redo_button = QPushButton()
        w.redo_button.setFixedSize(30, 30)
        w.redo_button.setIcon(qta.icon("fa5s.redo", color="lightgray"))
        w.redo_button.setToolTip("Redo - ctrl + shift + z")
        w.redo_button.clicked.connect(w.redo)
        h_hist.addWidget(w.redo_button)

        # on ajoute la barre d'historique avant la waveform
        w.layout.addLayout(h_hist)

        # — Waveform plot
        w.plot = pg.PlotWidget(viewBox=self.viewbox_cls())
        w.plot.setFixedHeight(150)
        w.plot.showGrid(x=True, y=True, alpha=0.3)
        w.plot.setBackground("#222")
        w.plot.hideAxis("left")
        w.plot.setMouseEnabled(x=True, y=False)

        # Courbes pour chaque canal (gauche et droite)
        w.curve_left = pg.PlotDataItem(pen=pg.mkPen("w", width=1))
        w.curve_right = pg.PlotDataItem(pen=pg.mkPen("#DAA520", width=1))
        w.plot.addItem(w.curve_right)
        w.plot.addItem(w.curve_left)

        # Pour compatibilité mono, conserver self.curve
        w.curve = pg.PlotDataItem(pen=pg.mkPen("w", width=1))
        w.plot.addItem(w.curve)

        # recalcule l'enveloppe lorsqu'on zoome ou qu'on pan
        vb = w.plot.getViewBox()
        vb.sigXRangeChanged.connect(w._on_view_range_changed)

        w.layout.addWidget(w.plot)

        # — Contrôles
        h = QHBoxLayout()
        for ico, cb, tip in [
            ("fa5s.play", w.play_from_start, "Play - ctrl + space"),
            ("fa5s.pause", w.pause_or_resume, "Pause / Resume - space"),
            ("fa5s.stop", w.stop_and_reset, "Stop and Reset - alt + space"),
        ]:
            b = QPushButton()
            b.setFixedSize(30, 30)
            b.setIcon(qta.icon(ico, color="lightgray"))
            b.clicked.connect(cb)
            b.setToolTip(tip)
            h.addWidget(b)

        # Loop
        w.loop_button = QPushButton()
        w.loop_button.setCheckable(True)
        w.loop_button.setFixedSize(30, 30)
        w.loop_button.setIcon(qta.icon("fa5s.sync", color="lightgray"))
        w.loop_button.toggled.connect(w.toggle_loop)
        w.loop_button.setToolTip("Loop ON/OF - ctrl + l")
        h.addWidget(w.loop_button)
        w.loop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Marker Mode
        w.marker_mode_button = QPushButton()
        w.marker_mode_button.setCheckable(True)
        w.marker_mode_button.setFixedSize(30, 30)
        w.marker_mode_button.setIcon(qta.icon("fa5s.map-marker-alt", color="lightgray"))
        w.marker_mode_button.setToolTip("Marker Mode ON/OFF - ctrl + g")
        w.marker_mode_button.toggled.connect(w.toggle_marker_mode)
        h.addWidget(w.marker_mode_button)

        w.layout.addLayout(h)

        # — Read head + timer
        w.read_head = pg.InfiniteLine(angle=90, pen=pg.mkPen("r", width=2))
        w.plot.addItem(w.read_head)
        w.timer = QTimer(w)
        w.timer.timeout.connect(w.update_read_head)
        w.stop_timer_signal.connect(w.timer.stop)
        w.timer.start(5)

        # — Liste des marqueurs (visibilité gérée après instanciation de marker_manager)
        w.marker_list = MarkerListWidget(w)
        w.marker_list.itemClicked.connect(w.on_marker_list_clicked)
        w.marker_list.itemDoubleClicked.connect(w.on_marker_list_double_clicked)
        w.layout.addWidget(w.marker_list)

        # — Install filter une seule fois
        w.plot.getViewBox().scene().installEventFilter(w)

        w.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        w.setStyleSheet("""
            WaveformWidget[focused="true"] {
                border: 2px solid #2979ff;
            }
            WaveformWidget[focused="false"] {
                border: 1px solid #ccc;
            }
        """)
