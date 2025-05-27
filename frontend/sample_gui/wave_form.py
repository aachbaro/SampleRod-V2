from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QMenu
)
from PyQt6.QtGui import QCursor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent, QThread
import pyqtgraph as pg
import numpy as np
import sounddevice as sd
import qtawesome as qta
import librosa
from backend.models.sample import Sample
from PyQt6.QtWidgets import QMessageBox, QInputDialog
import os, soundfile as sf
from backend.db import SessionLocal
from backend.models.sample import Sample as DBSample
import librosa
from backend.models.sample import Sample as SampleModel
from frontend.custom_widgets import SaveWaveformDialog



class WaveformLoaderThread(QThread):
    waveformReady = pyqtSignal(np.ndarray, int, float)
    def __init__(self, path):
        super().__init__()
        self.path = path
    def run(self):
        try:
            y, sr = librosa.load(self.path, sr=None)
            if y.size and np.max(np.abs(y)) > 0:
                y = y / np.max(np.abs(y))
            else:
                y = np.zeros_like(y)
            dur = librosa.get_duration(y=y, sr=sr)
            self.waveformReady.emit(y, sr, dur)
        except Exception as e:
            print(f"[WaveformLoaderThread] Erreur: {e}")
            self.waveformReady.emit(np.array([]), 0, 0.0)

class ContextMenuLinearRegionItem(pg.LinearRegionItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        )

    def contextMenuEvent(self, ev):

        start, end = self.getRegion()

        menu = QMenu()

        cut = menu.addAction("Cut   Ctrl + x")

        # place ici tes autres actions...


        # récupère la position globale du curseur
        global_pos = QCursor.pos()
        action = menu.exec(global_pos)

        if action is cut:
            # on appelle la méthode _cut_region sur le parent
            self._parent._cut_region(start, end)

        ev.accept()

class WaveformWidget(QWidget):
    stop_timer_signal = pyqtSignal()
    waveformSaved    = pyqtSignal(str)

# ———————————————————————————————————————————————————— Initialisation ————————————————————————————————————————————————————

    def __init__(self, audio_file_path):
        super().__init__()
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
        self.markers = []            # liste triée de times (s)
        self.marker_lines = {}       # {time: InfiniteLine}
        self.current_marker_idx = 0

        # → données
        self.waveform_data = None
        self.sample_rate = None
        self.duration = 0.0

        # historique : liste de commandes, et indice courant (-1 = rien)
        self._history = []
        self._hist_index = -1
        self._record_history = True

        self._build_ui()
        self._load_audio(audio_file_path)

    def _build_ui(self):
        self.layout = QVBoxLayout(self)

        # — Save (enregistre l'état actuel de waveform_data)
        save_layout = QHBoxLayout()
        save_layout.addStretch()
        self.save_button = QPushButton()
        self.save_button.setIcon(qta.icon('fa5s.save', color='lightgray'))
        self.save_button.setToolTip("Save waveform")
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
        self.undo_button.setToolTip("Undo")
        self.undo_button.clicked.connect(self.undo)
        h_hist.addWidget(self.undo_button)
        # Redo
        self.redo_button = QPushButton()
        self.redo_button.setFixedSize(30, 30)
        self.redo_button.setIcon(qta.icon('fa5s.redo', color='lightgray'))
        self.redo_button.setToolTip("Redo")
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
        self.layout.addWidget(self.plot)

        # — Contrôles
        h = QHBoxLayout()
        for ico, cb, tip in [
            ('fa5s.play',  self.play_from_start, "Play"),
            ('fa5s.pause', self.pause_or_resume, "Pause / Resume"),
            ('fa5s.stop',  self.stop_and_reset,  "Stop and Reset")
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
        self.loop_button.setToolTip("Loop ON/OFF")
        h.addWidget(self.loop_button)

        # Marker Mode
        self.marker_mode_button = QPushButton(); self.marker_mode_button.setCheckable(True)
        self.marker_mode_button.setFixedSize(30,30)
        self.marker_mode_button.setIcon(qta.icon('fa5s.map-marker-alt', color='lightgray'))
        self.marker_mode_button.setToolTip("Marker Mode ON/OFF")
        self.marker_mode_button.toggled.connect(self.toggle_marker_mode)
        h.addWidget(self.marker_mode_button)

        self.layout.addLayout(h)

        # — Read head + timer
        self.read_head = pg.InfiniteLine(angle=90, pen=pg.mkPen('r', width=2))
        self.plot.addItem(self.read_head)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_read_head)
        self.stop_timer_signal.connect(self.timer.stop)
        self.timer.start(50)

        # — Liste des marqueurs
        self.marker_list = QListWidget()
        self.marker_list.itemClicked.connect(self.on_marker_list_clicked)
        self.marker_list.itemDoubleClicked.connect(self.on_marker_list_double_clicked)
        self.layout.addWidget(self.marker_list)

        # — Install filter une seule fois
        self.plot.getViewBox().scene().installEventFilter(self)

    def _load_audio(self, path):
        self.loader = WaveformLoaderThread(path)
        self.loader.waveformReady.connect(self.set_waveform_data)
        self.loader.start()

    def set_waveform_data(self, y, sr, dur):
        if y.size == 0 or sr == 0:
            print("[WaveformWidget] Fichier vide ou erreur")
            return
        self.waveform_data, self.sample_rate, self.duration = y, sr, dur
        vb = self.plot.getViewBox()
        vb.setLimits(xMin=0, xMax=dur, yMin=-1, yMax=1)
        self._redraw_all()

    def _draw_waveform(self):
        # 1) on vide la vue
        self.plot.clear()

        # 2) on trace la forme d’onde
        x = np.linspace(0, self.duration, len(self.waveform_data))
        self.plot.plot(x, self.waveform_data, pen=pg.mkPen('w', width=1))
        self.plot.setXRange(0, self.duration, padding=0)
        self.plot.setYRange(-1, 1, padding=0)

        # 3) on ré-initialise le comportement de la molette
        vb = self.plot.getViewBox()
        vb.setMenuEnabled(False)
        vb.wheelEvent = self._zoom_or_pan

        # 4) on remet toujours la tête de lecture
        # (même si elle a été supprimée par clear())
        self.plot.addItem(self.read_head)
        # et on la positionne où il faut
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
        t = float(np.clip(t, 0.0, self.duration))
        # —— LOG
        print(f"Marker ajouté à {t:.3f}s")
        # —— historique
        self._push_history({
            "action": "add_marker",
            "time": t
        })
        # —— insertion dans la liste triée
        import bisect
        bisect.insort(self.markers, t)
        self._refresh_marker_list()

        # —— création de la ligne draggable
        line = pg.InfiniteLine(pos=t, angle=90, pen=pg.mkPen('y', width=2))
        line.setMovable(True)
        line.setZValue(10)  # pour qu’il reste au-dessus de la région
        # on mémorise la position initiale
        line.old_pos = t
        # signaux pour update et fin de drag
        line.sigPositionChanged.connect(lambda _, l=line: self.on_marker_moved(l))
        line.sigPositionChangeFinished.connect(lambda _, l=line: self._on_marker_move_finished(l))
        self.plot.addItem(line)

        # —— on garde la référence
        self.marker_lines[t] = line

    def on_marker_moved(self, line: pg.InfiniteLine):
        """Quand on déplace un marker, on met à jour son temps et la liste."""
        # print("on marker_moved")
        # lit la nouvelle position et la recoupe aux bornes
        new_t = float(np.clip(line.value(), 0.0, self.duration))
        line.setValue(new_t)  # force la ligne à rester dans l’intervalle

        # retrouve l’ancien t
        old_t = next(t for t, ln in self.marker_lines.items() if ln is line)

        # remplace dans self.markers
        self.markers.remove(old_t)
        del self.marker_lines[old_t]

        import bisect
        bisect.insort(self.markers, new_t)
        self.marker_lines[new_t] = line

        # rafraîchit la liste
        self._refresh_marker_list()

    def _on_marker_move_finished(self, line):
        """Quand on a fini de déplacer un marqueur, on met à jour l'historique."""
        old_t = getattr(line, 'old_pos', None)
        new_t = float(np.clip(line.value(), 0.0, self.duration))
        print(f"Marker déplacé de {old_t:.3f}s → {new_t:.3f}s")
        # ici tu pushes dans l'historique :
        self._push_history({
            "action": "move_marker",
            "old": old_t,
            "new": new_t
        })
        # et tu mets à jour old_pos pour le prochain drag
        line.old_pos = new_t

    def remove_marker(self, t: float):
        """Supprime le marqueur à t, rafraîchit la liste et push dans l’historique."""
        if t in self.markers:
            # —— LOG
            print(f"Marker supprimé à {t:.3f}s")
            # —— historique
            self._push_history({
                "action": "remove_marker",
                "time": t
            })

            # —— détermine l’indice avant suppression
            idx = self.markers.index(t)

            # —— suppression des données
            self.markers.remove(t)
            line = self.marker_lines.pop(t)
            self.plot.removeItem(line)

            # —— recale current_marker_idx
            if not self.markers:
                self.current_marker_idx = 0
            else:
                # si on venait de supprimer un marqueur avant l’index courant, on décrémente
                if self.current_marker_idx > idx:
                    self.current_marker_idx -= 1
                # si on était sur le dernier élément qui a été supprimé, recale au nouveau dernier
                self.current_marker_idx = min(self.current_marker_idx, len(self.markers)-1)

            # —— mise à jour de la liste QtWidget
            self._refresh_marker_list()

    def on_marker_list_clicked(self, item: QListWidgetItem):
        t = item.data(Qt.ItemDataRole.UserRole)
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
        print(f"Région mise à jour: {t:.3f}s → {t2:.3f}s")

    def on_marker_list_double_clicked(self, item: QListWidgetItem):
        t = item.data(Qt.ItemDataRole.UserRole)
        self.remove_marker(t)

    def _refresh_marker_list(self):
        """Vide et remplit la QListWidget en ordre chronologique."""
        self.marker_list.clear()
        for i, t in enumerate(self.markers):
            item = QListWidgetItem(f"M{i+1} — {t:.3f}s")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.marker_list.addItem(item)


# ——————————————————————————————————————— region et dash     ——————————————————————————————————————————————————————

    def _set_marker(self, x):
        # on détruit la région si elle existait
        if self.region:
            self.plot.removeItem(self.region)
            self.region = None

        # pose du marker
        self.play_start = x
        self._loop_start_sample = int(x * self.sample_rate)
        print(f"Région : début {self.play_start:.3f}s")
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
        # print(f"Région : début {start:.3f}s — fin {end:.3f}s")

    def eventFilter(self, source, event):
        vb = self.plot.getViewBox()

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

            print("Fin du drag")

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

# —————————————————————————————————————————————————————— Playback ——————————————————————————————————————————————————————

    def play_from_start(self):
        self.stop_audio()
        if self.marker_mode and self.markers:
            # recale l’indice pour ne jamais sortir de bornes
            self.current_marker_idx = min(self.current_marker_idx, len(self.markers)-1)
            t = self.markers[self.current_marker_idx]
        else:
            t = self.play_start
        self.play_audio(t)

    def pause_or_resume(self):
        """Toggle pause/reprise."""
        if self.is_playing:
            if self.stream:
                self.stream.stop()
            self.timer.stop()
            self.is_playing = False
        else:
            # reprend depuis current_time
            self.play_audio(self.current_time)

    def play_audio(self, start_time=0.0):
        if self.waveform_data is None:
            return
        self.start_sample = int(start_time * self.sample_rate)
        self.current_time = start_time
        self.is_playing   = True
        self.timer.start(50)

        def callback(outdata, frames, time_info, status):
            # Sorte de silence par défaut
            buf = np.zeros((frames,), dtype='float32')
            idx = 0

            # — calcul des bornes en samples
            if self.marker_mode and self.markers:
                self.current_marker_idx = min(self.current_marker_idx, len(self.markers)-1)
                ms = self.markers[self.current_marker_idx]
                region_start = int(ms * self.sample_rate)
                if self.current_marker_idx + 1 < len(self.markers):
                    region_end = int(self.markers[self.current_marker_idx + 1] * self.sample_rate)
                else:
                    region_end = len(self.waveform_data)
            else:
                region_start = int(self.play_start * self.sample_rate)
                region_end = int(self.play_end * self.sample_rate) if self.play_end > self.play_start else len(self.waveform_data)

            # si la région est vide, on renvoie du silence et on stoppe
            if region_end <= region_start:
                outdata[:, 0] = buf
                self.is_playing = False
                return

            # position de lecture actuelle
            read_pos = self.start_sample

            # — playback + loop
            while idx < frames:
                # si on dépasse la fin de la région
                if read_pos >= region_end:
                    if not self.loop_enabled:
                        self.is_playing = False
                        break
                    read_pos = region_start

                # combien d’échantillons restent dans la région
                remaining = region_end - read_pos
                # on ne lit jamais plus que frames-idx ni que remaining
                to_read = min(frames - idx, remaining)

                # extrait le chunk et en calcule la vraie longueur
                chunk = self.waveform_data[read_pos:read_pos + to_read].astype('float32')
                n = chunk.shape[0]
                if n == 0:
                    break  # plus rien à jouer

                # copie exactement n échantillons dans le buffer
                buf[idx:idx + n] = chunk
                idx += n
                read_pos += n

            # on met à jour la position de lecture
            self.start_sample = read_pos

            # on renvoie le buffer et on met à jour current_time
            outdata[:, 0] = buf
            self.current_time = self.start_sample / self.sample_rate

        self.stream = sd.OutputStream(samplerate=self.sample_rate,
                                      channels=1,
                                      callback=callback)
        self.stream.start()

    def pause_audio(self):
        if self.stream and self.is_playing:
            self.stream.stop()
            self.timer.stop()
            self.is_playing = False
        elif not self.is_playing:
            self.play_audio(self.current_time)

    def stop_and_reset(self):
        self.stop_audio()
        self.current_time = self.play_start
        self.read_head.setPos(self.play_start)

    def stop_audio(self):
        if self.stream:
            try:
                if getattr(self.stream, 'active', False):
                    self.stream.stop()
            except Exception as e:
                print(f"[WaveformWidget] Erreur stop: {e}")
            try:
                self.stream.close()
            except Exception as e:
                print(f"[WaveformWidget] Erreur close: {e}")
            finally:
                self.stream = None
        self.is_playing = False
        self.stop_timer_signal.emit()

    def update_read_head(self):
        if self.is_playing:
            self.read_head.setPos(self.current_time)
        else:
            # nettoyage en cas de fin de lecture dans le callback
            self.stop_audio()

    def toggle_loop(self, checked: bool):
        """Active/désactive le mode boucle."""
        self.loop_enabled = checked
        color = 'lightgreen' if checked else 'lightgray'
        self.loop_button.setIcon(qta.icon('fa5s.sync', color=color))
    
# —————————————————————————————————————————————————————— HISTORY ——————————————————————————————————————————————————————
    def _push_history(self, cmd: dict):
        """Ajouter une commande à l'historique, invalide tout redo possible."""
        if not self._record_history:
            return
        del self._history[self._hist_index+1:]
        self._history.append(cmd)
        self._hist_index += 1

        # DEBUG
        print("=== Historique des commandes ===")
        for i, c in enumerate(self._history):
            marker = " <-" if i == self._hist_index else ""
            print(f"  [{i}] {c!r}{marker}")
        print("================================")

    def undo(self):
        if self._hist_index < 0:
            return
        cmd = self._history[self._hist_index]
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

        self._hist_index -= 1
        self._record_history = True
        print("=== Historique des commandes ===")
        for i, c in enumerate(self._history):
            marker = " <-" if i == self._hist_index else ""
            print(f"  [{i}] {c!r}{marker}")
        print("================================")

    def redo(self):
        if self._hist_index + 1 >= len(self._history):
            return
        self._hist_index += 1
        cmd = self._history[self._hist_index]
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

        print("=== Historique des commandes ===")
        for i, c in enumerate(self._history):
            marker = " <-" if i == self._hist_index else ""
            print(f"  [{i}] {c!r}{marker}")
        print("================================")

# ———————————————————————————————————————————————————————— Save / export ——————————————————————————————————————————————

    def onSaveClicked(self):
        """
        Ouvre un dialog Overwrite / Save as copy, écrit le WAV
        et met à jour la base si overwrite, ou crée un nouveau sample si copy.
        """
        from PyQt6.QtWidgets import QMessageBox, QInputDialog
        import os, soundfile as sf
        from backend.db import SessionLocal
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

        # mise à jour de la DB
        session = SessionLocal()
        try:
            if overwrite:
                samp = session.query(DBSample).filter_by(path=orig).first()
                if samp:
                    samp.duration   = self.duration
                    samp.created_at = samp.get_creation_date()
                    session.commit()
                    QMessageBox.information(self, "Enregistré", f"Fichier écrasé :\n{target}")
            else:
                DBSample(target)
                QMessageBox.information(self, "Enregistré", f"Copie sauvegardée :\n{target}")
        finally:
            session.close()

        self.waveformSaved.emit(target)


class NoLeftDragViewBox(pg.ViewBox):
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)

