# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget principal d'edition/lecture de waveform pour un sample.
# - Concentre l'interaction utilisateur (selection, markers, playback, export).
# - Sert de "mini DAW" pour couper, marquer, lire et exporter des segments.
#
# CE QUI EST DEJA EN PLACE
# - Chargement async de la waveform (WaveformLoaderThread).
# - Affichage waveform + tete de lecture (read head).
# - Selection par region (LinearRegionItem) + markers (add/remove/move).
# - Mode marker (toggle) et gestion de la liste de markers.
# - Playback audio avec loop, pause, stop, play from start.
# - Export d'une region en nouveau WAV + ajout au SampleService.
# - Historique d'actions (undo/redo) via HistoryStack.
# - Drag & drop de segments (slice drag).
#
# GESTES / INTERACTIONS IMPORTANTES
# - Clic gauche: creer/ajuster une region.
# - Maj + glisse: deplacer la region.
# - Ctrl + double-clic: creer region rapide.
# - Mode marker: clic gauche -> poser un marker.
# - Clic molette: placer la tete + jouer depuis ce point.
# - Raccourcis: play/pause/stop, undo/redo, export, etc.
#
# RESPONSABILITES TECHNIQUES
# - Maintenir play_start / play_end et la selection courante.
# - Synchroniser l'etat de lecture (timer + stream).
# - Traduire les actions UI en modifications de waveform_data.
# - Assurer la coherence entre visuel (plot) et donnees.
#
# CE QUI RESTE A FAIRE (IDEES)
# - Refonte UI (barre d'outils, densite, meilleure hierarchie).
# - Clic molette / gestures coherents avec le reste de l'app.
# - Edition non destructive / versions.
# - Metriques (RMS, peak, LUFS) et overlays.
#
# NOTES
# - Ce fichier est long car il centralise: UI + logique audio + interactions.
# - Si besoin, on peut le separer (controller/renderer/commands).
# -----------------------------------------------------------------------------
# frontend/sample_gui/wave_form.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidgetItem, QMenu, QMessageBox
)
import logging
logger = logging.getLogger("wave_form")

from PyQt6.QtGui import QCursor, QMouseEvent, QDrag
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent, QMimeData
import pyqtgraph as pg
import numpy as np
import qtawesome as qta
import librosa

import os
import soundfile as sf
from backend.models.sample import Sample as DBSample

from frontend.custom_widgets import SaveWaveformDialog
from backend.models.AppContext import AppContext
from backend.services.notification_service import NotificationType
import bisect
import pickle

from .marker_manager import MarkerManager, MarkerListWidget
from .waveform.waveform_loader import WaveformLoaderThread
from .waveform.waveform_loader import WaveformLoaderThread
from .waveform.history_stack import HistoryStack
from .waveform.waveform_playback import WaveformPlaybackController

class ContextMenuLinearRegionItem(pg.LinearRegionItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        )

    def contextMenuEvent(self, ev):

        start, end = self.getRegion()

        menu = QMenu()

        cut = menu.                 addAction("Cut                      Ctrl + X")
        export = menu.              addAction("Export Selection         Ctrl + E")
        drag_act = menu.            addAction("Drag Selection")
        add_markers_action = menu.  addAction("Add markers at edges     Ctrl + Shift + G")

        # place ici tes autres actions...


        # récupère la position globale du curseur
        global_pos = QCursor.pos()
        action = menu.exec(global_pos)

        if action is cut:
            # on appelle la méthode _cut_region sur le parent
            self._parent._cut_region(start, end)

        elif action is export:
            # on appelle la méthode _export_region sur le parent (n’écrase pas la waveform en mémoire)
            self._parent._export_region(start, end)
        elif action is drag_act:
            self._parent.start_slice_drag(start, end)
        elif action is add_markers_action:
            # on ajoute des marqueurs aux bords de la région
            if end > start:
                self._parent.add_marker(start)
                self._parent.add_marker(end)
            else:
                # si la région est quasiment nulle, on place un seul marker
                self._parent.add_marker(start)
        

        ev.accept()

class WaveformWidget(QWidget):
    stop_timer_signal = pyqtSignal()
    waveformSaved    = pyqtSignal(str)
    positionUpdated = pyqtSignal(float)

# ———————————————————————————————————————————————————— Initialisation ————————————————————————————————————————————————————

    def __init__(self, audio_file_path, app_context: AppContext):
        super().__init__()

        self.app_context = app_context
        self.audio_file_path = audio_file_path
        # → playback
        self.stream = None
        self.current_time = 0.0
        self.is_playing = False
        self.loop_enabled = False


        # → sélection de région (clic‐drag)
        self.play_start = 0.0
        self.play_end   = 0.0 
        self.region = None
        self.marker = None
        self._dragging = False
        self._creating = False
        self._press_x  = 0.0
        self._shifting = False            # mode “déplacement” activé
        self._shift_press_x = 0.0         # position d’appui en secondes
        self._orig_region = (0.0, 0.0)    # bornes initiales de la région

        # → marqueurs (clic en mode marker)
        self.marker_mode = False

        # → données
        self.waveform_data = None
        self.sample_rate = None
        self.duration = 0.0
        self.is_stereo = False

        # historique des actions
        self.history = HistoryStack()
        self._record_history = True

        # construction de l'UI (définit notamment self.plot)
        self._build_ui()
        self.playback = WaveformPlaybackController(self)
        # gestion des marqueurs via un composant dédié, APRES avoir défini self.plot
        self.marker_manager = MarkerManager(self)
        # affichage initial de la liste de marqueurs
        if not self.marker_manager.markers:
            self.marker_list.hide()
        else:
            self.marker_list.show()
        self._load_audio(audio_file_path)
        self.positionUpdated.connect(lambda t: self.read_head.setPos(t))

    # --- accès simplifiés aux données du MarkerManager
    @property
    def markers(self):
        return self.marker_manager.markers

    @markers.setter
    def markers(self, value):
        self.marker_manager.markers = value

    @property
    def marker_lines(self):
        return self.marker_manager.marker_lines

    @marker_lines.setter
    def marker_lines(self, value):
        self.marker_manager.marker_lines = value

    @property
    def current_marker_idx(self):
        return self.marker_manager.current_marker_idx

    @current_marker_idx.setter
    def current_marker_idx(self, value):
        self.marker_manager.current_marker_idx = value



    def _build_ui(self):
        self.layout = QVBoxLayout(self)

        # — Save (enregistre l'état actuel de waveform_data)
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        self.save_button = QPushButton()
        self.save_button.setIcon(qta.icon('fa5s.save', color='lightgray'))
        self.save_button.setToolTip("Save waveform - ctrl + s")
        self.save_button.setFixedSize(30,30)
        self.save_button.clicked.connect(self.onSaveClicked)
        save_layout.addWidget(self.save_button)
        self.layout.addLayout(save_layout)

        # — Undo / Redo au-dessus de la waveform
        h_hist = QHBoxLayout()
        # Undo
        self.undo_button = QPushButton()
        self.undo_button.setFixedSize(30, 30)
        self.undo_button.setIcon(qta.icon('fa5s.undo', color='lightgray'))
        self.undo_button.setToolTip("Undo - ctrl + z")
        self.undo_button.clicked.connect(self.undo)
        h_hist.addWidget(self.undo_button)
        # Redo
        self.redo_button = QPushButton()
        self.redo_button.setFixedSize(30, 30)
        self.redo_button.setIcon(qta.icon('fa5s.redo', color='lightgray'))
        self.redo_button.setToolTip("Redo - ctrl + shift + z")
        self.redo_button.clicked.connect(self.redo)
        h_hist.addWidget(self.redo_button)

        # on ajoute la barre d'historique avant la waveform
        self.layout.addLayout(h_hist)

        # — Waveform plot
        self.plot = pg.PlotWidget(viewBox=NoLeftDragViewBox())
        self.plot.setFixedHeight(150)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setBackground('#222')
        self.plot.hideAxis('left')
        self.plot.setMouseEnabled(x=True, y=False)

        # Courbes pour chaque canal (gauche et droite)
        self.curve_left  = pg.PlotDataItem(pen=pg.mkPen('w', width=1))
        self.curve_right = pg.PlotDataItem(pen=pg.mkPen('#DAA520', width=1))
        self.plot.addItem(self.curve_right)
        self.plot.addItem(self.curve_left)

        # Pour compatibilité mono, conserver self.curve
        self.curve = pg.PlotDataItem(pen=pg.mkPen('w', width=1))
        self.plot.addItem(self.curve)

        # recalcule l'enveloppe lorsqu'on zoome ou qu'on pan
        vb = self.plot.getViewBox()
        vb.sigXRangeChanged.connect(self._on_view_range_changed)

        self.layout.addWidget(self.plot)

        # — Contrôles
        h = QHBoxLayout()
        for ico, cb, tip in [
            ('fa5s.play',  self.play_from_start, "Play - ctrl + space"),
            ('fa5s.pause', self.pause_or_resume, "Pause / Resume - space"),
            ('fa5s.stop',  self.stop_and_reset,  "Stop and Reset - alt + space"),
        ]:
            b = QPushButton()
            b.setFixedSize(30,30)
            b.setIcon(qta.icon(ico, color='lightgray'))
            b.clicked.connect(cb)
            b.setToolTip(tip)                # ← on ajoute le tooltip ici
            h.addWidget(b)

        # Loop
        self.loop_button = QPushButton(); self.loop_button.setCheckable(True)
        self.loop_button.setFixedSize(30,30)
        self.loop_button.setIcon(qta.icon('fa5s.sync', color='lightgray'))
        self.loop_button.toggled.connect(self.toggle_loop)
        self.loop_button.setToolTip("Loop ON/OF - ctrl + l")
        h.addWidget(self.loop_button)
        self.loop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Marker Mode
        self.marker_mode_button = QPushButton(); self.marker_mode_button.setCheckable(True)
        self.marker_mode_button.setFixedSize(30,30)
        self.marker_mode_button.setIcon(qta.icon('fa5s.map-marker-alt', color='lightgray'))
        self.marker_mode_button.setToolTip("Marker Mode ON/OFF - ctrl + g")
        self.marker_mode_button.toggled.connect(self.toggle_marker_mode)
        h.addWidget(self.marker_mode_button)

        self.layout.addLayout(h)

        # — Read head + timer
        self.read_head = pg.InfiniteLine(angle=90, pen=pg.mkPen('r', width=2))
        self.plot.addItem(self.read_head)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_read_head)
        self.stop_timer_signal.connect(self.timer.stop)
        self.timer.start(5)

        # — Liste des marqueurs (on gère la visibilité PLUS TARD, après instanciation de marker_manager)
        self.marker_list = MarkerListWidget(self)
        self.marker_list.itemClicked.connect(self.on_marker_list_clicked)
        self.marker_list.itemDoubleClicked.connect(self.on_marker_list_double_clicked)
        self.layout.addWidget(self.marker_list)


        # — Install filter une seule fois
        self.plot.getViewBox().scene().installEventFilter(self)

        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setStyleSheet("""
            WaveformWidget[focused="true"] {
                border: 2px solid #2979ff;
            }
            WaveformWidget[focused="false"] {
                border: 1px solid #ccc;
            }
        """)

    def _load_audio(self, path):
        self.loader = WaveformLoaderThread(path)
        self.loader.waveformReady.connect(self.set_waveform_data)
        self.loader.start()

    def set_waveform_data(self, y, sr, dur):
        # y.shape == (n_samples,) en mono ou (n_channels, n_samples) en stéréo
        if y.ndim == 2:
            # Transposer pour obtenir (n_samples, 2)
            y = y.T
            self.is_stereo = True
        else:
            self.is_stereo = False

        self.waveform_data = y.astype('float32', order='C')
        self.sample_rate   = sr
        self.duration      = dur

    # **Verrouille désormais les limites X/Y du ViewBox** sur la durée réelle
        vb = self.plot.getViewBox()
        vb.setMenuEnabled(False)
        vb.wheelEvent = self._zoom_or_pan
        vb.setLimits(
            xMin=0,          # plage horizontale
            xMax=self.duration,
            yMin=-1,         # amplitude fixe
            yMax=1,
            minXRange=0.01,  # zoom horizontal autorisé
            maxXRange=self.duration,
            minYRange=2,     # bloque la hauteur à (1 - -1) = 2
            maxYRange=2
        )

        # calcul initial de l'enveloppe sur toute la durée
        self.plot.setXRange(0, self.duration, padding=0)
        self._draw_waveform()

    def _draw_waveform(self):
        """Recalcule l'enveloppe sur la portion actuellement visible."""
        vb = self.plot.getViewBox()
        x0, x1 = vb.viewRange()[0]
        self._on_view_range_changed(vb, (x0, x1))

    def _on_view_range_changed(self, view_box, range):
        """Update the displayed envelope when the view range changes."""
        if self.waveform_data is None or self.sample_rate is None:
            return

        x0, x1 = range
        i0 = max(0, int(x0 * self.sample_rate))
        i1 = min(len(self.waveform_data), int(x1 * self.sample_rate))

        if self.is_stereo:
            # Pour chaque canal, on calcule min/max par bloc et on trace sur la courbe correspondante
            for idx, curve in enumerate((self.curve_left, self.curve_right)):
                segment = self.waveform_data[i0:i1, idx]
                if len(segment) == 0:
                    curve.setData([], [])
                    continue

                width    = self.plot.width() or 800
                step     = max(1, len(segment) // width)
                n_blocks = len(segment) // step
                seg      = segment[: n_blocks * step].reshape(n_blocks, step)
                mins     = seg.min(axis=1)
                maxs     = seg.max(axis=1)
                xs       = np.linspace(i0 / self.sample_rate, i1 / self.sample_rate, n_blocks)

                X_poly = np.concatenate([xs, xs[::-1]])
                Y_poly = np.concatenate([maxs, mins[::-1]])
                curve.setData(X_poly, Y_poly)
        else:
            segment = self.waveform_data[i0:i1]
            if len(segment) == 0:
                self.curve.setData([], [])
                return

            width    = self.plot.width() or 800
            step     = max(1, len(segment) // width)
            n_blocks = len(segment) // step
            seg      = segment[: n_blocks * step].reshape(n_blocks, step)
            mins     = seg.min(axis=1)
            maxs     = seg.max(axis=1)
            xs       = np.linspace(i0 / self.sample_rate, i1 / self.sample_rate, n_blocks)

            X_poly = np.concatenate([xs, xs[::-1]])
            Y_poly = np.concatenate([maxs, mins[::-1]])
            self.curve.setData(X_poly, Y_poly)
        self.read_head.setPos(self.current_time)

    def _redraw_all(self):
        self._draw_waveform()
        for line in self.marker_lines.values():
            self.plot.addItem(line)

# ———————————————————————————————————————————————————— Navigation   -————————————————————————————————————————————————————

    def _zoom_or_pan(self, ev, **_):
        vb = self.plot.getViewBox()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            dx = -0.1 if ev.delta()>0 else 0.1
            vb.translateBy(x=dx*self.duration, y=0)
        else:
            pg.ViewBox.wheelEvent(vb, ev)

    def toggle_marker_mode(self, checked: bool):
        """Active/désactive le mode marqueurs."""
        self.marker_mode = checked
        c = 'lightgreen' if checked else 'lightgray'
        self.marker_mode_button.setIcon(qta.icon('fa5s.map-marker-alt', color=c))

# ——————————————————————————————————————————————————— Marqueurs —————————————————————————————————————————————————————

    def add_marker(self, t: float):
        """Ajoute un marqueur et met à jour la liste."""
        # Sécurité : ne pas ajouter si un marker existe déjà ici
        # (on compare avec une petite tolérance pour les floats)
        tol = 1e-6
        if any(abs(existing - t) < tol for existing in self.markers):
            return
        self.marker_manager.add_marker(t)
        self._refresh_marker_list()

    def on_marker_moved(self, line: pg.InfiniteLine):
        self.marker_manager.on_marker_moved(line)

    def _on_marker_move_finished(self, line):
        self.marker_manager.on_marker_move_finished(line)

    def remove_marker(self, t: float):
        """Supprime un marqueur et met à jour la liste."""
        self.marker_manager.remove_marker(t)
        # on rafraîchit et on masque la liste si nécessaire
        self._refresh_marker_list()

    def on_marker_list_clicked(self, item: QListWidgetItem):
        payload = item.data(Qt.ItemDataRole.UserRole)
        t = payload.get("time") if isinstance(payload, dict) else payload
        # trouve l'indice exact
        idx = self.markers.index(t)
        self.current_marker_idx = idx
        # next bound
        if idx+1 < len(self.markers):
            t2 = self.markers[idx+1]
        else:
            t2 = self.duration

        # supprime l'ancienne région
        if self.region:
            self.plot.removeItem(self.region)
        # crée la nouvelle région
        self.region = ContextMenuLinearRegionItem([t, t2],
                                          brush=pg.mkBrush(255,255,255,40),
                                          pen=pg.mkPen('c', width=1))
        self.region.setZValue(1) 
        self.region.setBounds([0, self.duration])
        # self.region.sigContextMenuRequested.connect(self._on_region_context_menu)
        self.region.sigRegionChangeFinished.connect(self.on_region_changed)
        self.region._parent = self
        self.plot.addItem(self.region)

        # mets à jour play_start / play_end et place la tête de lecture
        self.play_start, self.play_end = t, t2
        self.read_head.setPos(t)
        logger.info(f"Région mise à jour: {t:.3f}s → {t2:.3f}s")

    def on_marker_list_double_clicked(self, item: QListWidgetItem):
        payload = item.data(Qt.ItemDataRole.UserRole)
        t = payload.get("time") if isinstance(payload, dict) else payload
        self.remove_marker(t)

    def _refresh_marker_list(self):
        self.marker_manager.refresh_marker_list()
        # montrer/cacher automatiquement selon qu'il y a des marqueurs
        if self.marker_manager.markers:
            self.marker_list.show()
        else:
            self.marker_list.hide()

# ——————————————————————————————————————— region et dash     ——————————————————————————————————————————————————————

    def _set_marker(self, x):
        # on détruit la région si elle existait
        if self.region:
            self.plot.removeItem(self.region)
            self.region = None

        # pose du marker (visuel uniquement — ne modifie plus play_start/play_end)
        logger.info(f"Marqueur placé à {x:.3f}s")
        if self.marker:
            self.plot.removeItem(self.marker)
        self.marker = pg.InfiniteLine(
            pos=x, angle=90,
            pen=pg.mkPen('b', width=1, style=Qt.PenStyle.DashLine)
        )
        self.plot.addItem(self.marker)

    def on_region_changed(self):
        if not self.region:
            return
        start, end = self.region.getRegion()
        # CLAMP des deux bornes
        start = max(0.0, min(start, self.duration))
        end   = max(start, min(end,   self.duration))
        # remet à jour la région côté visuel
        self.region.setRegion([start, end])
        self.play_start, self.play_end = start, end
        # logger.info(f"Région : début {start:.3f}s — fin {end:.3f}s")

    def eventFilter(self, source, event):
        vb = self.plot.getViewBox()

        # --- 0) Clic molette: place la selection + lance la lecture
        if event.type() == QEvent.GraphicsSceneMousePress \
        and event.button() == Qt.MouseButton.MiddleButton:
            if self.waveform_data is None or self.duration is None:
                return False
            pos = event.scenePos()
            t = float(np.clip(vb.mapSceneToView(pos).x(), 0, self.duration))
            # Visuel: poser un marqueur unique
            self._set_marker(t)
            # Selection logique + tete de lecture
            self.play_start = t
            self.play_end = t
            self.current_time = t
            self.read_head.setPos(t)
            # Lecture immediatement (comme clic gauche + ctrl+space)
            self.play_from_start()
            return True

        # --- 0) En mode marker, Ctrl+clic simple → sélection de la région ---
        if self.marker_mode \
           and event.type() == QEvent.GraphicsSceneMousePress \
           and event.button() == Qt.MouseButton.LeftButton \
           and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):

            logger.info("Ctrl+clic simple en mode marker")
            pos = event.scenePos()
            # Si on a cliqué sur un marker existant, on laisse InfiniteLine gérer
            for line in self.marker_lines.values():
                if line.sceneBoundingRect().contains(pos):
                    return False

            # Sinon, on crée la région comme avec Ctrl+double-clic en mode non-marker
            self._handle_ctrl_double_click(vb, event)
            return True


        # 1) Ctrl + double-clic → délégation à la méthode dédiée

        if (event.type() == QEvent.GraphicsSceneMouseDoubleClick and
            event.button() == Qt.MouseButton.LeftButton and
            (event.modifiers() & Qt.KeyboardModifier.ControlModifier)):

            logger.info("Ctrl+double-clic détecté")
            # Si on a cliqué sur un marqueur, on le laisse gérer (suppression)
            pos = event.scenePos()
            for line in self.marker_lines.values():
                if line.sceneBoundingRect().contains(pos):
                    return False

            # Sinon, on appelle la nouvelle méthode
            self._handle_ctrl_double_click(vb, event)
            return True

        # 0) Maj + clic gauche DANS le corps (pas sur les handles) → début du déplacement
        if event.type() == QEvent.GraphicsSceneMousePress \
        and event.button() == Qt.MouseButton.LeftButton \
        and event.modifiers() & Qt.KeyboardModifier.ShiftModifier \
        and self.region:

            pos = event.scenePos()
            # handles
            line0, line1 = self.region.lines
            scene_h0 = line0.mapToScene(line0.boundingRect()).boundingRect().center().x()
            scene_h1 = line1.mapToScene(line1.boundingRect()).boundingRect().center().x()
            tol = 5
            if abs(pos.x() - scene_h0) < tol or abs(pos.x() - scene_h1) < tol:
                # on est sur un handle → pas notre cas
                return False

            # on est bien dans le corps de la région
            self._shifting = True
            # coordonnée de départ (en secondes)
            self._shift_press_x = float(vb.mapSceneToView(pos).x())
            # bornes d’origine
            self._orig_region = tuple(self.region.getRegion())
            return True

        # 1) déplacement pendant Maj+glissé
        if event.type() == QEvent.GraphicsSceneMouseMove \
        and self._shifting:

            pos = event.scenePos()
            x = float(vb.mapSceneToView(pos).x())
            dx = x - self._shift_press_x

            start0, end0 = self._orig_region
            length = end0 - start0
            # clamp pour rester dans [0, duration]
            new_start = max(0.0, min(start0 + dx, self.duration - length))
            new_end   = new_start + length

            self.region.setRegion([new_start, new_end])
            # mets à jour play_start/play_end sans déclencher création
            self.play_start, self.play_end = new_start, new_end
            return True

        # 2) fin du déplacement
        if event.type() == QEvent.GraphicsSceneMouseRelease \
        and event.button() == Qt.MouseButton.LeftButton \
        and self._shifting:

            self._shifting = False
            # ici, tu peux pousser dans l'historique si tu veux
            # self._push_history({...})
            return True

        if event.type() in (QEvent.GraphicsSceneMousePress,
                            QEvent.GraphicsSceneMouseMove,
                            QEvent.GraphicsSceneMouseRelease):
            pos = event.scenePos()
            # si on clique ou drag sur un marker, on ne filtre pas l'événement
            for line in self.marker_lines.values():
                if line.sceneBoundingRect().contains(pos):
                    return False

        # 1) En mode marker, on intercepte seulement les clics hors des lignes existantes
        if self.marker_mode:
            if event.type() == QEvent.GraphicsSceneMousePress \
               and event.button() == Qt.MouseButton.LeftButton:
                pos = event.scenePos()
                # si on a cliqué SUR un marker existant, on laisse InfiniteLine gérer le drag
                for line in self.marker_lines.values():
                    if line.sceneBoundingRect().contains(pos):
                        return False
                # sinon, on créé un nouveau marker
                t = float(np.clip(vb.mapSceneToView(pos).x(), 0, self.duration))
                self.add_marker(t)
                return True
            return False

        # 2) Sinon, on est en mode region : clic-drag → création/redimensionnement
        if event.type() == QEvent.GraphicsSceneMousePress \
        and event.button() == Qt.MouseButton.LeftButton:

            pos_scene = event.scenePos()
            vb = self.plot.getViewBox()
            data_x = vb.mapSceneToView(pos_scene).x()
            press_x = float(np.clip(data_x, 0, self.duration))

            # Si on a déjà une région...
            if self.region:
                r0, r1 = self.region.getRegion()

                # On calcule la position en pixels des deux handles
                line0, line1 = self.region.lines
                # boundingRect en coords locales, puis centre, puis en scene
                scene_handle0 = line0.mapToScene(line0.boundingRect()).boundingRect().center().x()
                scene_handle1 = line1.mapToScene(line1.boundingRect()).boundingRect().center().x()
                tol = 5  # tolérance en pixels

                # Si clic SUR un handle (gauche OU droit), on laisse LinearRegionItem gérer le resize
                if abs(pos_scene.x() - scene_handle0) < tol or abs(pos_scene.x() - scene_handle1) < tol:
                    return False

                # Sinon (clic dans le body), on SUPPRIME l'ancienne région
                self.plot.removeItem(self.region)
                self.region = None
                self._dragging = False
                self._creating = False

                # et on supprime aussi le marker (au cas où)
            if self.marker:
                self.plot.removeItem(self.marker)
                self.marker = None

            # À partir d'ici, on sait qu'il n'y a plus de région → on crée une nouvelle
            self._dragging = True
            self._creating = True
            self._press_x = press_x

            self.region = ContextMenuLinearRegionItem([press_x, press_x],
                                            brush=pg.mkBrush(255,255,255,40),
                                            pen=pg.mkPen('c', width=1))
            self.region.setBounds([0, self.duration])
            self.region.sigRegionChanged.connect(self.on_region_changed)
            self.region.sigRegionChangeFinished.connect(self.on_region_changed)
            # self.region.sigContextMenuRequested.connect(self._on_region_context_menu)
            self.region._parent = self
            self.plot.addItem(self.region)
            return True

        # 2) Redimensionnement **durant** le drag de création
        elif event.type() == QEvent.GraphicsSceneMouseMove \
            and self._dragging and self._creating \
            and self.region is not None:

            pos = self.plot.getViewBox().mapSceneToView(event.scenePos())
            x   = float(np.clip(pos.x(), 0, self.duration))
            self.region.setRegion([min(self._press_x, x),
                                max(self._press_x, x)])
            return True

        # 3) Fin du drag (Release) → région validée ou simple clic
        elif event.type() == QEvent.GraphicsSceneMouseRelease \
             and event.button() == Qt.MouseButton.LeftButton \
             and self._creating:

            logger.info("Fin du drag")

            pos       = self.plot.getViewBox().mapSceneToView(event.scenePos())
            release_x = float(np.clip(pos.x(), 0, self.duration))
            self._dragging = False
            self._creating = False
            self.on_region_changed()

            # si c’était un clic « sans drag »: on détruit la mini-région et pose un marker
            if abs(release_x - self._press_x) < 1e-3:
                self.plot.removeItem(self.region)
                self.region = None
                self._dragging = False
                self._creating = False
                self._set_marker(release_x)
            # sinon on garde la région telle quelle (handles actifs)
            return True

        # 4) tout le reste passe à la moulinette par défaut
        return False

    # —————————————————————————————————— menu contextuel region ——————————————————————————————————

    def _cut_region(self, start, end):
        removed, removed_markers, shift = self._do_cut(start, end)
        # on enregistre l’action pour undo/redo
        self._push_history({
            "action":"cut",
            "start":start,
            "removed_samples":removed,
            "removed_markers":removed_markers,
            "shift":shift
        })

    def _do_cut(self, start, end):
        """Coupe la zone [start,end], supprime les markers dedans et décale les suivants."""
        s0, s1 = int(start*self.sample_rate), int(end*self.sample_rate)
        shift = end - start

        # 1) découpe samples
        removed = self.waveform_data[s0:s1].copy()
        self.waveform_data = np.concatenate([
            self.waveform_data[:s0],
            self.waveform_data[s1:]
        ])
        self.duration = len(self.waveform_data)/self.sample_rate
        vb = self.plot.getViewBox()
        vb.setLimits(xMin=0, xMax=self.duration, yMin=-1, yMax=1)
        self.plot.setXRange(0, self.duration, padding=0)

        # 2) supprime visuel et interne les markers dans [start,end]
        to_remove = [t for t in self.markers if start <= t <= end]
        for t in to_remove:
            line = self.marker_lines.pop(t)
            self.plot.removeItem(line)
            self.markers.remove(t)

        # 3) décale tous les markers > start
        new_markers, new_lines = [], {}
        for t, line in list(self.marker_lines.items()):
            if t > start:
                nt = t - shift
                line.setPos(nt)
                new_markers.append(nt)
                new_lines[nt] = line
            else:
                new_markers.append(t)
                new_lines[t] = line
        self.markers = sorted(new_markers)
        self.marker_lines = new_lines

        if self.current_marker_idx >= len(self.markers):
            # si plus aucun marker, on remet à 0
            self.current_marker_idx = max(0, len(self.markers) - 1)

        self._refresh_marker_list()

        # 4) redraw complet
        self._redraw_all()
        self.read_head.setPos(0.0)

        self.current_time = 0.0
        self.play_start  = 0.0
        self.play_end    = self.duration
        return removed, to_remove, shift

    def _undo_cut(self, cmd):
        """Restaure un cut précédemment effectué."""
        start = cmd["start"]
        s0 = int(start*self.sample_rate)
        removed, removed_markers, shift = cmd["removed_samples"], cmd["removed_markers"], cmd["shift"]

        # 1) recolle les samples
        self.waveform_data = np.concatenate([
            self.waveform_data[:s0],
            removed,
            self.waveform_data[s0:]
        ])
        self.duration = len(self.waveform_data)/self.sample_rate
        vb = self.plot.getViewBox()
        vb.setLimits(xMin=0, xMax=self.duration, yMin=-1, yMax=1)
        self.plot.setXRange(0, self.duration, padding=0)

        # 2) décale en arrière tous les markers > start
        new_markers, new_lines = [], {}
        for t, line in list(self.marker_lines.items()):
            if t > start:
                rt = t + shift
                line.setPos(rt)
                new_markers.append(rt)
                new_lines[rt] = line
            else:
                new_markers.append(t)
                new_lines[t] = line
        self.markers = sorted(new_markers)
        self.marker_lines = new_lines

        # 3) recrée **sans history** les markers qu’on avait supprimés
        for t in removed_markers:
            self._create_marker_line(t)

        self._refresh_marker_list()

        # 4) redraw
        self._redraw_all()
        self.read_head.setPos(start)

    def _create_marker_line(self, t):
        """Créer la ligne d’un marker sans touch­er à l’historique."""
        import bisect
        bisect.insort(self.markers, t)
        line = pg.InfiniteLine(pos=t, angle=90, pen=pg.mkPen('y', width=2))
        line.setMovable(True)
        line.old_pos = t
        line.sigPositionChanged.connect(lambda _, l=line: self.on_marker_moved(l))
        line.sigPositionChangeFinished.connect(lambda _, l=line: self._on_marker_move_finished(l))
        self.marker_lines[t] = line

    def _export_region(self, start, end):
        """
        Exporte la portion [start, end] dans un nouveau fichier WAV
        et l’ajoute à la base via SampleService.
        Ne modifie pas la waveform en mémoire.
        """
        # 1) Calcul des indices d’échantillons
        s0 = int(start * self.sample_rate)
        s1 = int(end   * self.sample_rate)
        if s1 <= s0:
            QMessageBox.warning(self, "Export impossible", "La sélection est vide.")
            return

        # 2) Extraction du segment
        segment = self.waveform_data[s0:s1].astype('float32')

        # 3) Génération d’un nom de fichier unique
        #    => on place le nouveau fichier dans le même dossier que l’original
        orig_path = self.audio_file_path
        folder    = os.path.dirname(orig_path)
        next_id   = DBSample.get_next_id()
        ext       = os.path.splitext(orig_path)[1] or ".wav"
        new_name  = f"SMPL_{next_id:04d}{ext}"
        target    = os.path.join(folder, new_name)

        try:
            # 4) Écriture du WAV
            sf.write(target, segment, self.sample_rate)
        except Exception as e:
            QMessageBox.critical(self, "Erreur Export", f"Impossible d’écrire '{target}':\n{e}")
            return

        # 5) On prévient SampleService pour qu’il crée l’entrée DB et émette le signal
        self.app_context.sample_store.add(target)

        QMessageBox.information(self, "Export réussi", f"Segment exporté dans :\n{target}")

    def start_slice_drag(self, start: float, end: float):
        """Initie un glisser-déposer pour la portion [start,end]."""
        s0 = int(start * self.sample_rate)
        s1 = int(end * self.sample_rate)
        if s1 <= s0:
            return
        array = self.waveform_data[s0:s1].astype("float32")
        name = os.path.basename(self.audio_file_path)
        mime = QMimeData()
        payload = {
            "audio_data": array,
            "sample_rate": self.sample_rate,
            "name": name,
        }
        mime.setData(
            "application/x-sample-slice-data",
            pickle.dumps(payload),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

# —————————————————————————————————————————————————————— Playback ——————————————————————————————————————————————————————

    # ------------------------------------------------------------------ Playback (delegue au controller)
    def play_from_start(self):
        self.playback.play_from_start()

    def pause_or_resume(self):
        self.playback.pause_or_resume()

    def play_audio(self, start_time: float = 0.0):
        self.playback.play_audio(start_time)

    def pause_audio(self):
        self.playback.pause_audio()

    def stop_and_reset(self):
        self.playback.stop_and_reset()

    def stop_audio(self):
        self.playback.stop_audio()

    def update_read_head(self):
        self.playback.update_read_head()

    def toggle_loop(self, checked: bool):
        self.playback.toggle_loop(checked)

    def _push_history(self, cmd: dict):
        """Record a command for undo/redo."""
        if not self._record_history:
            return
        self.history.push(cmd)
        self._debug_history()

    def undo(self):
        cmd = self.history.undo()
        if cmd is None:
            return
        self._record_history = False

        if cmd['action'] == 'add_marker':
            self.remove_marker(cmd['time'])

        elif cmd["action"]=="cut":
            self._undo_cut(cmd)

        elif cmd['action'] == 'remove_marker':
            self.add_marker(cmd['time'])

        elif cmd['action'] == 'move_marker':
            line = self.marker_lines[cmd['new']]
            line.setValue(cmd['old'])
            self.on_marker_moved(line)

        self._record_history = True
        self._debug_history()

    def redo(self):
        cmd = self.history.redo()
        if cmd is None:
            return
        self._record_history = False

        if cmd['action'] == 'add_marker':
            self.add_marker(cmd['time'])

        elif cmd["action"]=="cut":
            # on refait exactement le même cut
            self._do_cut(cmd["start"], cmd["start"]+cmd["shift"])

        elif cmd['action'] == 'remove_marker':
            self.remove_marker(cmd['time'])

        elif cmd['action'] == 'move_marker':
            line = self.marker_lines[cmd['old']]
            line.setValue(cmd['new'])
            self.on_marker_moved(line)

        self._record_history = True
        self._debug_history()

    def _debug_history(self):
        logger.info("=== Historique des commandes ===")
        logger.info(self.history)
        logger.info("================================")

# —————————————————————————————————————————————— Save / export ——————————————————————————————————————————————

    def onSaveClicked(self):
        """
        Ouvre un dialog Overwrite / Save as copy, écrit le WAV
        et met à jour la base si overwrite, ou crée un nouveau sample si copy.
        """
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        import os, soundfile as sf
        from backend.models.sample import Sample as DBSample
        import librosa

        # 1) Choix Overwrite vs Copy
        orig = self.audio_file_path
        folder = os.path.dirname(orig)
        ext    = os.path.splitext(orig)[1]
        default_name = f"SMPL_{DBSample.get_next_id():04d}"

        dlg = SaveWaveformDialog(self, default_name)
        overwrite, new_name = dlg.choice()
        if overwrite is None:
            return  # utilisateur a annulé

        if overwrite:
            target = orig
        else:
            target = os.path.join(folder, new_name + ext)

        try:
            sf.write(target, self.waveform_data, self.sample_rate)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))
            return

        svc = self.app_context.sample_store

        if overwrite:
            # recalculer la durée et mettre à jour le service uniquement pour ce fichier
            svc.updateDurationFromFile(target)
            # Notification when the file is saved over the original
            self.app_context.notifications.notify(
                title="✅ Fichier sauvegardé",
                message=os.path.basename(target),
                type=NotificationType.SUCCESS,
            )
        else:
            # création d’un nouveau sample (FS+BD) via SampleService.add()
            svc.add(target)

# ——————————————————————————————————————— Keycontrol ——————————————————————————————————————————————

    def _on_cut_shortcut(self):
        """Callback du raccourci : coupe la région sélectionnée si elle existe."""
        if hasattr(self, 'region') and self.region is not None:
            start, end = self.region.getRegion()
            self._cut_region(start, end)

    def _on_export_shortcut(self):
        """Callback du raccourci : exporte la région sélectionnée si elle existe."""
        if hasattr(self, 'region') and self.region is not None:
            start, end = self.region.getRegion()
            self._export_region(start, end)

    def add_markers_to_region(self):
        """
        Place deux marqueurs aux bords de la sélection (LinearRegionItem).
        Si la sélection est vide (end == start), ne place qu'un seul marqueur à start.
        """
        if not hasattr(self, "region") or self.region is None:
            return

        start, end = self.region.getRegion()
        # Si la largeur est positive, on place deux marqueurs :
        if end > start:
            self.add_marker(start)
            self.add_marker(end)
        else:
            # Sélection nulle → un seul marqueur
            self.add_marker(start)

    def _handle_ctrl_double_click(self, view_box, event):
        """
        Crée une région entre le marqueur immédiatement à gauche et
        celui immédiatement à droite du point cliqué.
        Si aucun marqueur à gauche : start=0.0
        Si aucun marqueur à droite : end=self.duration
        """
        pos = event.scenePos()
        x = float(np.clip(view_box.mapSceneToView(pos).x(), 0.0, self.duration))

        # Cas où il n'y a aucun marqueur
        if not self.markers:
            t_left = 0.0
            t_right = self.duration

        else:
            # Recherche de l'indice du premier marqueur >= x
            idx = bisect.bisect_left(self.markers, x)

            # Détermine le marqueur de gauche ou 0.0 si aucun
            if idx > 0:
                t_left = self.markers[idx - 1]
            else:
                t_left = 0.0

            # Détermine le marqueur de droite ou duration si aucun
            if idx < len(self.markers):
                t_right = self.markers[idx]
            else:
                t_right = self.duration

            # Si x tombe exactement sur un marqueur, on peut
            # choisir de créer la région entre ce marqueur et le suivant,
            # ou simplement ignorer. Ici, on fait entre le marqueur et le suivant.
            if idx < len(self.markers) and abs(x - self.markers[idx]) < 1e-6:
                # idx est le marqueur « droite » = x
                # on décale t_left pour que ce ne soit pas x→x
                if idx > 0:
                    t_left = self.markers[idx - 1]
                else:
                    t_left = 0.0
                # t_right reste self.markers[idx] (= x)
            # Si x est au-delà du dernier marqueur, on tombe dans la logique « else » ci-dessus

        # Supprime l’ancienne région si elle existe
        if self.region:
            self.plot.removeItem(self.region)
            self.region = None

        # Crée la nouvelle région
        self.region = ContextMenuLinearRegionItem([t_left, t_right],
                                                  brush=pg.mkBrush(255,255,255,40),
                                                  pen=pg.mkPen('c', width=1))
        self.region.setZValue(1)
        self.region.setBounds([0, self.duration])
        self.region.sigRegionChangeFinished.connect(self.on_region_changed)
        self.region._parent = self
        self.plot.addItem(self.region)

        # Met à jour play_start/play_end et positionne la tête
        self.play_start, self.play_end = t_left, t_right
        self.read_head.setPos(t_left)
        logger.info(f"Région créée par Ctrl+double-clic : {t_left:.3f}s → {t_right:.3f}s")


class NoLeftDragViewBox(pg.ViewBox):
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)
