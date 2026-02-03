# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget principal d'edition/lecture de waveform pour un sample.
# - Concentre l'interaction utilisateur (selection, markers, playback, export).
# - Sert de "mini DAW" pour couper, marquer, lire et exporter des segments.
# - Orchestration generale: instancie les controllers playback/interactions.
#
# CE QUI EST DEJA EN PLACE
# - Chargement async de la waveform (WaveformLoaderThread).
# - Affichage waveform + tete de lecture (read head).
# - Selection par region (LinearRegionItem) + markers (add/remove/move).
# - Mode marker (toggle) et gestion de la liste de markers.
# - Playback audio avec loop, pause, stop, play from start.
# - Playback/gestes/region extraits en controllers:
#   - WaveformPlaybackController (audio)
#   - WaveformInteractionsController (events)
#   - WaveformRegionController (selection, cut, export)
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
# - Brancher les controllers (playback / interactions) au widget.
#
# CE QUI RESTE A FAIRE (IDEES)
# - Refonte UI (barre d'outils, densite, meilleure hierarchie).
# - Clic molette / gestures coherents avec le reste de l'app.
# - Edition non destructive / versions.
# - Metriques (RMS, peak, LUFS) et overlays.
# - Continuer la decoupe (renderer/commands) pour alleger ce fichier.
#
# NOTES
# - Ce fichier est long car il centralise: UI + logique audio + interactions.
# - La logique audio et interactions a ete extraite, mais le coeur reste dense.
# - Si besoin, on peut pousser la separation (controller/renderer/commands).
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

import os

from frontend.custom_widgets import SaveWaveformDialog
from backend.models.AppContext import AppContext
from backend.services.notification_service import NotificationType
import pickle

from .marker_manager import MarkerManager, MarkerListWidget
from .waveform.waveform_loader import WaveformLoaderThread
from .waveform.history_stack import HistoryStack
from .waveform.waveform_interactions import WaveformInteractionsController
from .waveform.waveform_playback import WaveformPlaybackController
from .waveform.waveform_region import WaveformRegionController

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
        self.region_controller = WaveformRegionController(self, ContextMenuLinearRegionItem)
        self.playback = WaveformPlaybackController(self)
        self.interactions = WaveformInteractionsController(self, ContextMenuLinearRegionItem)
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
        self.region_controller.on_region_changed()

    def eventFilter(self, source, event):
        return self.interactions.eventFilter(source, event)


    def _cut_region(self, start, end):
        self.region_controller._cut_region(start, end)

    def _do_cut(self, start, end):
        return self.region_controller._do_cut(start, end)

    def _undo_cut(self, cmd):
        self.region_controller._undo_cut(cmd)

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
        self.region_controller._export_region(start, end)

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
        self.region_controller._handle_ctrl_double_click(view_box, event)


class NoLeftDragViewBox(pg.ViewBox):
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)
