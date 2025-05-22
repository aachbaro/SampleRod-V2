from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
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
        # → attributs playback
        self.stream = None
        self.current_time = 0.0
        self.is_playing = False

        # → attributs sélection
        self.play_start = 0.0
        self.play_end   = 0.0 
        self.marker = None
        self.region = None
        self._dragging = False
        self._creating   = False
        self._press_x = 0.0

        # → attributs données
        self.waveform_data = None
        self.sample_rate = None
        self.duration = 0.0

        self._build_ui()
        self._load_audio(audio_file_path)

    def _build_ui(self):
        self.layout = QVBoxLayout(self)
        self.plot = pg.PlotWidget(viewBox=NoLeftDragViewBox())
        self.plot.setFixedHeight(150)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setBackground('#222')
        self.plot.hideAxis('left')
        self.plot.setMouseEnabled(x=True, y=False)
        self.layout.addWidget(self.plot)

        # boutons play / pause / stop
        h = QHBoxLayout()
        btns = [
            ('fa5s.play', self.toggle_playback),
            ('fa5s.pause', self.pause_audio),
            ('fa5s.stop', self.stop_and_reset)
        ]
        for ico, cb in btns:
            b = QPushButton(); b.setFixedSize(30,30)
            b.setIcon(qta.icon(ico, color='lightgray'))
            b.clicked.connect(cb)
            h.addWidget(b)
        self.layout.addLayout(h)

        # tête de lecture
        self.read_head = pg.InfiniteLine(angle=90, pen=pg.mkPen('r', width=2))
        self.plot.addItem(self.read_head)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_read_head)
        self.stop_timer_signal.connect(self.timer.stop)
        self.timer.start(50)

    def _load_audio(self, path):
        self.loader = WaveformLoaderThread(path)
        self.loader.waveformReady.connect(self.set_waveform_data)
        self.loader.start()

    def set_waveform_data(self, y, sr, dur):
        if y.size == 0 or sr == 0:
            print("[WaveformWidget] Fichier vide ou erreur de chargement")
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
        vb.scene().installEventFilter(self)

    def _zoom_or_pan(self, ev, **_):
        vb = self.plot.getViewBox()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            dx = -0.1 if ev.delta() > 0 else 0.1
            vb.translateBy(x=dx * self.duration, y=0)
        else:
            pg.ViewBox.wheelEvent(vb, ev)

    def eventFilter(self, source, event):
        # 1) Début de création de région ou simple clic hors-région
        if event.type() == QEvent.GraphicsSceneMousePress \
           and event.button() == Qt.MouseButton.LeftButton:

            pos     = self.plot.getViewBox().mapSceneToView(event.scenePos())
            press_x = float(np.clip(pos.x(), 0, self.duration))

            # Si on clique DANS la région existante, on LÂCHE le filtre
            if self.region:
                r0, r1 = self.region.getRegion()
                if r0 <= press_x <= r1:
                    # on laisse LinearRegionItem gérer ses propres drags
                    return False

                # sinon, clic en dehors → on supprime l'ancienne
                self.plot.removeItem(self.region)
                self.region = None

            if self.marker:
                self.plot.removeItem(self.marker)
                self.marker = None

            # … ici, on est sûr de créer une NOUVELLE région …
            self._dragging = True
            self._creating = True
            self._press_x  = press_x

            self.region = pg.LinearRegionItem(
                [press_x, press_x],
                movable=True,
                brush=pg.mkBrush(255,255,255,40),
                pen=pg.mkPen('c', width=1)
            )
            self.region.setBounds([0, self.duration])
            self.plot.addItem(self.region)
            return True        # on consomme l’événement

        # 2) Redimensionnement **durant** le drag de création
        elif event.type() == QEvent.GraphicsSceneMouseMove \
             and self._dragging and self._creating:

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
                self._set_marker(release_x)
            # sinon on garde la région telle quelle (handles actifs)
            return True

        # 4) tout le reste passe à la moulinette par défaut
        return False

    def _set_marker(self, x):
        # on détruit la région si elle existait
        if self.region:
            self.plot.removeItem(self.region)
            self.region = None

        # pose du marker
        self.play_start = x
        print(f"Région : début {self.play_start:.3f}s")
        if self.marker:
            self.plot.removeItem(self.marker)
        self.marker = pg.InfiniteLine(
            pos=x, angle=90,
            pen=pg.mkPen('b', width=1, style=Qt.PenStyle.DashLine)
        )
        self.plot.addItem(self.marker)

    def on_region_changed(self):
        """appelé après drag ou redimensionnement terminé"""
        start, end = self.region.getRegion()
        print(f"Région : début {start:.3f}s — fin {end:.3f}s")
        self.play_start = start
        self.play_end   = end
        print(f"Région : début {start:.3f}s — fin {end:.3f}s")

    # ----------------- PLAYBACK -----------------

    def toggle_playback(self):
        if self.is_playing:
            self.pause_audio()
        else:
            self.play_audio(self.play_start)

    def play_audio(self, start_time=0.0):
        if self.waveform_data is None:
            return
        self.start_sample = int(start_time * self.sample_rate)
        self.current_time = start_time
        self.is_playing = True
        self.timer.start(50)

        def callback(outdata, frames, time, status):
            if status:
                print(status)
            end = self.start_sample + frames
            chunk = self.waveform_data[self.start_sample:end]
            if len(chunk) < frames:
                outdata[:len(chunk),0] = chunk.astype('float32')
                outdata[len(chunk):,0] = 0
                self.is_playing = False
            else:
                outdata[:,0] = chunk.astype('float32')
            self.start_sample += frames
            self.current_time += frames / self.sample_rate

        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            callback=callback
        )
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

class NoLeftDragViewBox(pg.ViewBox):
    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.ignore()
        else:
            super().mouseDragEvent(ev, axis)
