from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent, QThread
import pyqtgraph as pg
import numpy as np
import sounddevice as sd
import qtawesome as qta
import librosa

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

class WaveformWidget(QWidget):
    stop_timer_signal = pyqtSignal()

    def __init__(self, audio_file_path):
        super().__init__()
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

        # → marqueurs (clic en mode marker)
        self.marker_mode = False
        self.markers = []            # liste triée de times (s)
        self.marker_lines = {}       # {time: InfiniteLine}
        self.current_marker_idx = 0

        # → données
        self.waveform_data = None
        self.sample_rate = None
        self.duration = 0.0

        self._build_ui()
        self._load_audio(audio_file_path)

    def _build_ui(self):
        self.layout = QVBoxLayout(self)

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
        for ico, cb in [
            ('fa5s.play',  self.play_from_start),
            ('fa5s.pause', self.pause_or_resume),
            ('fa5s.stop',  self.stop_and_reset)
        ]:
            b = QPushButton(); b.setFixedSize(30,30)
            b.setIcon(qta.icon(ico, color='lightgray'))
            b.clicked.connect(cb)
            h.addWidget(b)

        # Loop
        self.loop_button = QPushButton(); self.loop_button.setCheckable(True)
        self.loop_button.setFixedSize(30,30)
        self.loop_button.setIcon(qta.icon('fa5s.sync', color='lightgray'))
        self.loop_button.toggled.connect(self.toggle_loop)
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
        self._draw_waveform()

    def _draw_waveform(self):
        x = np.linspace(0, self.duration, len(self.waveform_data))
        self.plot.plot(x, self.waveform_data, pen=pg.mkPen('w', width=1))
        self.plot.setXRange(0, self.duration, padding=0)
        self.plot.setYRange(-1, 1, padding=0)
        vb = self.plot.getViewBox()
        vb.wheelEvent = self._zoom_or_pan

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

    def add_marker(self, t: float):
        """Pose un marqueur à t (en secondes)."""
        import bisect
        bisect.insort(self.markers, t)
        # Qt List
        item = QListWidgetItem(f"M{len(self.markers)} — {t:.3f}s")
        item.setData(Qt.ItemDataRole.UserRole, t)
        self.marker_list.addItem(item)
        # Plot line
        line = pg.InfiniteLine(pos=t, angle=90, pen=pg.mkPen('y', width=2))
        self.plot.addItem(line)
        self.marker_lines[t] = line

    def remove_marker(self, t: float):
        """Supprime le marqueur à t."""
        if t in self.markers:
            idx = self.markers.index(t)
            self.markers.pop(idx)
            line = self.marker_lines.pop(t)
            self.plot.removeItem(line)
            # Qt ListItem
            items = self.marker_list.findItems(f"M{idx+1} — {t:.3f}s", Qt.MatchExactly)
            if items:
                self.marker_list.takeItem(self.marker_list.row(items[0]))

    def on_marker_list_clicked(self, item: QListWidgetItem):
        t_item = item.data(Qt.ItemDataRole.UserRole)
        # recherche de l'index du marqueur le plus proche
        idx = min(range(len(self.markers)), key=lambda i: abs(self.markers[i] - t_item))
        self.current_marker_idx = idx
        self.read_head.setPos(self.markers[idx])

    def on_marker_list_double_clicked(self, item: QListWidgetItem):
        t = item.data(Qt.ItemDataRole.UserRole)
        self.remove_marker(t)

    def eventFilter(self, source, event):
        vb = self.plot.getViewBox()

        # 1) Si on est en mode marker, on gère uniquement les clics simples
        if self.marker_mode:
            if event.type() == QEvent.GraphicsSceneMousePress and event.button() == Qt.MouseButton.LeftButton:
                pos = vb.mapSceneToView(event.scenePos()).x()
                t = float(np.clip(pos, 0, self.duration))
                self.add_marker(t)
                return True
            else:
                # on laisse le reste passer au ViewBox (panning, zoom, etc.)
                return False

        # 2) Sinon, on est en mode region : clic-drag → création/redimensionnement
        if event.type() == QEvent.GraphicsSceneMousePress and event.button() == Qt.MouseButton.LeftButton:
            pos = vb.mapSceneToView(event.scenePos()).x()
            self._press_x = float(np.clip(pos, 0, self.duration))
            self._dragging = True
            # supprime ancienne région et marqueur
            if self.region:
                self.plot.removeItem(self.region)
            if hasattr(self, 'marker') and self.marker:
                self.plot.removeItem(self.marker)
            # crée une mini-région [x, x]
            self.region = pg.LinearRegionItem([self._press_x, self._press_x],
                                              brush=pg.mkBrush(255,255,255,40),
                                              pen=pg.mkPen('c', width=1))
            self.region.setBounds([0, self.duration])
            self.region.sigRegionChangeFinished.connect(self.on_region_changed)
            self.plot.addItem(self.region)
            return True

        elif event.type() == QEvent.GraphicsSceneMouseMove and self._dragging and self.region:
            pos = vb.mapSceneToView(event.scenePos()).x()
            x = float(np.clip(pos, 0, self.duration))
            self.region.setRegion([min(self._press_x, x), max(self._press_x, x)])
            return True

        elif event.type() == QEvent.GraphicsSceneMouseRelease and event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            # si c’était un simple clic (pas de vrai drag), on vire la région et on pose un marker
            start, end = self.region.getRegion()
            if abs(end - start) < 1e-3:
                self.plot.removeItem(self.region)
                self.region = None
                self._set_marker(start)
            else:
                # on garde la région et on met à jour play_start / play_end
                self.on_region_changed()
            return True

        # 3) tout le reste → laisser PyQtGraph gérer (zoom/pan right-click, etc.)
        return False

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
        self.play_start = start
        self.play_end   = end
        # stocke aussi en samples
        self._loop_start_sample = int(start * self.sample_rate)
        self._loop_end_sample   = int(end   * self.sample_rate)
        print(f"Région : début {start:.3f}s — fin {end:.3f}s")

    # ——————————————————————————————————————————————————————
    #   PLAYBACK (région ou markers selon mode)
    # ——————————————————————————————————————————————————————

    # ----------------- PLAY / PAUSE helper methods -----------------

    def play_from_start(self):
        """Lance la lecture depuis play_start (ou depuis le marqueur courant si en mode marker)."""
        self.stop_audio()
        if self.marker_mode and self.markers:
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
            # … même code que précédemment …
            buf = np.zeros(frames, dtype='float32')
            idx = 0

            # bornes dynamiques
            if self.marker_mode and self.markers:
                # début = marker courant
                ms = self.markers[self.current_marker_idx]
                start = int(ms * self.sample_rate)
                # fin = suivant ou fin totale
                if self.current_marker_idx+1 < len(self.markers):
                    me = int(self.markers[self.current_marker_idx+1]*self.sample_rate)
                else:
                    me = len(self.waveform_data)
            else:
                start = int(self.play_start * self.sample_rate)
                me    = int(self.play_end * self.sample_rate) if self.play_end>self.play_start else len(self.waveform_data)

            # playback + loop
            while idx < frames:
                if self.start_sample >= me:
                    if not self.loop_enabled:
                        self.is_playing = False
                        break
                    self.start_sample = start
                remaining = me - self.start_sample
                to_read = min(frames-idx, remaining)
                chunk = self.waveform_data[self.start_sample:self.start_sample+to_read]
                buf[idx:idx+to_read] = chunk.astype('float32')
                idx += to_read
                self.start_sample += to_read

            outdata[:,0] = buf
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

class NoLeftDragViewBox(pg.ViewBox):
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)