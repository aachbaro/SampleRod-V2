from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout,
                             QVBoxLayout, QSpacerItem, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
import qtawesome as qta
import librosa
import pyqtgraph as pg
import numpy as np

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt
import librosa
import pyqtgraph as pg
import numpy as np
import sounddevice as sd

import os
# os.environ["SDL_AUDIODRIVER"] = "pulseaudio"

import sounddevice as sd
# sd.default.device = "pulse"

class WaveformWidget(QWidget):
    stop_timer_signal = pyqtSignal()

    def __init__(self, audio_file_path):
        super().__init__()
        self.audio_file_path = audio_file_path
        self.stream = None
        self.current_time = 0
        self.play_start = 0
        self.play_end = 0
        self.is_playing = False
        self.start_marker = None
        self.init_ui()

    def init_ui(self):
        """Initialise l'interface utilisateur et charge l'audio."""
        self.load_audio_data(self.audio_file_path)

        self.layout = QVBoxLayout(self)

        # Création du widget de tracé
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setFixedHeight(150)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setBackground('#222')  # Fond sombre
        vb = self.plot_widget.getViewBox()
        vb.setMouseEnabled(x=True, y=False)  # Zoom seulement sur X
        vb.setLimits(xMin=0, xMax=self.duration, yMin=-1, yMax=1)
        self.plot_widget.hideAxis('left')
        self.layout.addWidget(self.plot_widget)

        if self.waveform_data is not None:
            self.print_wave_form()

        # Boutons de zoom
        btn_layout = QHBoxLayout()
        # BOUTON PLAY
        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.setToolTip("Lire")
        self.play_button.clicked.connect(self.toggle_playback)
        btn_layout.addWidget(self.play_button)

        # BOUTON PAUSE
        self.pause_button = QPushButton()
        self.pause_button.setFixedSize(30, 30)
        self.pause_button.setIcon(qta.icon('fa5s.pause', color='lightgray'))
        self.pause_button.setToolTip("Pause")
        self.pause_button.clicked.connect(self.pause_audio)
        btn_layout.addWidget(self.pause_button)

        # BOUTON STOP
        self.stop_button = QPushButton()
        self.stop_button.setFixedSize(30, 30)
        self.stop_button.setIcon(qta.icon('fa5s.stop', color='lightgray'))
        self.stop_button.setToolTip("Stop")
        self.stop_button.clicked.connect(self.stop_and_reset)
        btn_layout.addWidget(self.stop_button)

        self.layout.addLayout(btn_layout)

        # Tête de lecture (ligne infinie qui se déplace)
        self.read_head = pg.InfiniteLine(angle=90, pen=pg.mkPen('r', width=2))
        self.plot_widget.addItem(self.read_head)

        # Timer pour mettre à jour la position de la tête de lecture
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_read_head)
        self.stop_timer_signal.connect(self.timer.stop)

        self.timer.start(50)  # Mettre à jour toutes les 50ms

        self.current_time = 0  # Temps actuel de lecture


    def load_audio_data(self, audio_path):
        """Charge les données audio et les prépare pour l'affichage."""
        try:
            y, sr = librosa.load(audio_path, sr=None)  # Garder le sample rate d'origine
            y = y / np.max(np.abs(y))  # Normaliser entre -1 et 1
            self.waveform_data = y
            self.sample_rate = sr
            self.duration = librosa.get_duration(y=y, sr=sr)
            print(f"Fichier chargé: {audio_path}, Durée: {self.duration:.2f}s")
            print(f"{y.shape}")
        except Exception as e:
            print(f"Erreur de chargement: {e}")
            self.waveform_data = None
            self.sample_rate = None
            self.duration = None

    def print_wave_form(self):
        self.x_axis = np.linspace(0, self.duration, len(self.waveform_data))
        self.plot_item = self.plot_widget.plot(self.x_axis, self.waveform_data, pen=pg.mkPen('w', width=1))
        self.plot_widget.setXRange(0, self.duration, padding=0)
        self.plot_widget.setYRange(-1, 1, padding=0)

        self.plot_widget.getViewBox().wheelEvent = self.zoom_or_pan
        self.plot_widget.scene().sigMouseClicked.connect(self.on_waveform_click)

        # Ajoute la zone de sélection (par défaut, rien de sélectionné)
        self.selection_region = pg.LinearRegionItem([1, 2])  # Intervalle de départ par défaut
        self.selection_region.setZValue(10)  # Au-dessus des autres éléments
        self.selection_region.setBrush(pg.mkBrush(255, 255, 255, 40))  # Couleur semi-transparente
        self.selection_region.setMovable(True)
        self.selection_region.setBounds([0, self.duration])  # Limiter aux bords du son
        self.plot_widget.addItem(self.selection_region)

        self.selection_region.sigRegionChanged.connect(self.on_selection_changed)

    def zoom_or_pan(self, event, **kwargs):  # <-- Capture les arguments non attendus
        """Gère le zoom normal et le déplacement latéral avec Shift."""
        vb = self.plot_widget.getViewBox()

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Shift pressé → déplacement horizontal
            delta_x = -0.1 if event.delta() > 0 else 0.1  # Gauche/Droite
            vb.translateBy(x=delta_x * self.duration, y=0)
        else:
            # Appel du comportement par défaut de PyQtGraph
            pg.ViewBox.wheelEvent(vb, event)

    def on_waveform_click(self, event):
        """Place la tête de lecture à la position cliquée et met à jour la lecture."""
        pos = event.scenePos()
        data_pos = self.plot_widget.getViewBox().mapSceneToView(pos)
        audio_position = data_pos.x()

        # Clamp la valeur pour ne pas sortir du signal
        audio_position = max(0, min(audio_position, self.duration))
        self.play_start = audio_position
        sample_index = int(audio_position * self.sample_rate)

        # Supprime le marqueur précédent s’il existe
        if self.start_marker is not None:
            self.plot_widget.removeItem(self.start_marker)

        # Crée un nouveau marqueur vertical bleu
        self.start_marker = pg.InfiniteLine(pos=audio_position, angle=90, pen=pg.mkPen('b', width=1, style=Qt.PenStyle.DashLine))
        self.plot_widget.addItem(self.start_marker)


# ------------------------------------------------------------- PLAYBACK LOGIC

    def toggle_playback(self):
        """Joue le sample depuis self.play_start"""
        self.stop_audio()
        self.play_audio(start_time=self.play_start)

    def play_audio(self, start_time=0):
        if self.waveform_data is None:
            return
        self.start_sample = int(start_time * self.sample_rate)  # Stocke start_sample comme un attribut
        self.current_time = start_time
        self.is_playing = True
        self.timer.start(50)

        def callback(outdata, frames, time, status):
            if status:
                print(status)
            end_sample = self.start_sample + frames  # Utilisation correcte de self.start_sample
            chunk = self.waveform_data[self.start_sample:end_sample]
            if len(chunk) < frames:
                outdata[:len(chunk), 0] = chunk.astype('float32')
                outdata[len(chunk):, 0] = 0
                self.stop_audio()
            else:
                outdata[:, 0] = chunk.astype('float32')
            self.start_sample += frames  # Mise à jour correcte
            self.current_time += frames / self.sample_rate

        self.stream = sd.OutputStream(samplerate=self.sample_rate, channels=1, callback=callback)
        self.stream.start()

    def stop_audio(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.is_playing = False
        self.stop_timer_signal.emit()

    def update_read_head(self):
        if self.is_playing:
            self.read_head.setPos(self.current_time)

    def pause_audio(self):
        """Pause ou reprend depuis self.current_time"""
        if self.stream is not None and self.is_playing:
            # Pause
            self.stream.stop()
            self.is_playing = False
            self.timer.stop()
        elif not self.is_playing:
            # Reprise
            self.play_audio(start_time=self.current_time)

    def stop_and_reset(self):
        """Stoppe l'audio et remet à zéro"""
        self.stop_audio()
        self.current_time = self.play_start
        self.read_head.setPos(self.play_start)

    def on_selection_changed(self):
        region = self.selection_region.getRegion()
        print(f"Région sélectionnée : {region[0]:.2f}s à {region[1]:.2f}s")
        # Tu peux stocker les valeurs comme:
        self.selection_start = region[0]
        self.selection_end = region[1]

