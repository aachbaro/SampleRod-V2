from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QMenu
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
        self.loop_enabled  = False # → boucle de lecture

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
            ('fa5s.play',  self.play_from_start),    # toujours lancer depuis play_start
            ('fa5s.pause', self.pause_or_resume),    # toggler pause / reprise
            ('fa5s.stop',  self.stop_and_reset)
        ]
        for ico, cb in btns:
            b = QPushButton(); b.setFixedSize(30,30)
            b.setIcon(qta.icon(ico, color='lightgray'))
            b.clicked.connect(cb)   # cb est maintenant play_from_start ou pause_or_resume
            h.addWidget(b)

        # ← Nouveau bouton Loop
        self.loop_button = QPushButton()
        self.loop_button.setCheckable(True)
        self.loop_button.setFixedSize(30,30)
        self.loop_button.setIcon(qta.icon('fa5s.sync', color='lightgray'))
        self.loop_button.setToolTip("Loop ON/OFF")
        self.loop_button.toggled.connect(self.toggle_loop)
        h.addWidget(self.loop_button)
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

            self.region = pg.LinearRegionItem([press_x, press_x],
                                            brush=pg.mkBrush(255,255,255,40),
                                            pen=pg.mkPen('c', width=1))
            self.region.setBounds([0, self.duration])
            self.region.sigRegionChanged.connect(self.on_region_changed)
            self.region.sigRegionChangeFinished.connect(self.on_region_changed)
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

    # ----------------- PLAYBACK -----------------

    def toggle_loop(self, checked: bool):
        self.loop_enabled = checked
        color = 'lightgreen' if checked else 'lightgray'
        self.loop_button.setIcon(qta.icon('fa5s.sync', color=color))

    def play_from_start(self):
        """Lance la lecture depuis play_start, même si on était déjà en pause ou stop."""
        # arrête tout ancien flux
        self.stop_audio()
        # relance depuis la borne de début
        self.play_audio(self.play_start)

    def pause_or_resume(self):
        """Pause si on joue, ou reprend depuis current_time si on est en pause."""
        if self.is_playing:
            # mettre en pause : stoppe et garde current_time intact
            if self.stream:
                self.stream.stop()
            self.timer.stop()
            self.is_playing = False
        else:
            # reprise : ouvre un nouveau stream depuis current_time
            self.play_audio(self.current_time)

    def play_audio(self, start_time=0.0):
        if self.waveform_data is None:
            return

        # position de départ à partir de start_time (pour pause / reprise)
        self.start_sample = int(start_time * self.sample_rate)
        self.current_time = start_time
        self.is_playing   = True
        self.timer.start(50)

        def callback(outdata, frames, time_info, status):
            if status:
                print(status)
            buf = np.zeros(frames, dtype='float32')
            idx = 0

            # À chaque boucle, récupère les bornes dynamiques
            loop_start = getattr(self, '_loop_start_sample', 0)
            loop_end   = getattr(self, '_loop_end_sample', len(self.waveform_data))

            # si pas de région fixe on boucle sur tout le sample
            if loop_end <= loop_start:
                loop_end = len(self.waveform_data)

            while idx < frames:
                # si on dépasse la borne de fin
                if self.start_sample >= loop_end:
                    if not self.loop_enabled:
                        self.is_playing = False
                        break
                    # reboucle
                    self.start_sample = loop_start

                remaining = loop_end - self.start_sample
                to_read = min(frames - idx, remaining)
                chunk = self.waveform_data[self.start_sample:self.start_sample + to_read]
                buf[idx:idx+to_read] = chunk.astype('float32')
                idx               += to_read
                self.start_sample += to_read

            outdata[:,0] = buf
            self.current_time = self.start_sample / self.sample_rate

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


class StretchOnlyRegion(pg.LinearRegionItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # stocke une référence aux poignées
        self.handles = [h for h in self.lines if isinstance(h, pg.SegmentROI)]
        # sous PyQtGraph >= 0.12, ce sont des QGraphicsRectItem
        # mais on peut simplement récupérer self.lines (deux segments verts)

    def mouseDragEvent(self, ev):
        # si on vient de cliquer, on vérifie si c'était sur un handle
        if ev.isStart():
            scene_pos = ev.scenePos()
            # pour chaque ligne-poignée, test si la souris est dessus
            for line in self.lines:
                pts = line.mapToScene(line.boundingRect()).toList()
                if line.mapFromScene(scene_pos) in line.mapFromScene(scene_pos):
                    # si sur un handle, on laisse PyQtGraph faire le resizing
                    super().mouseDragEvent(ev)
                    return
            # sinon, on ignore le drag pour la zone entière
            ev.ignore()
        else:
            # si on est déjà en train de dragger (drag move / end), on laisse faire
            super().mouseDragEvent(ev)