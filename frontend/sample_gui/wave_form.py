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
        self.is_playing = False
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
        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.setToolTip("Lire")
        self.play_button.clicked.connect(self.toggle_playback)
        btn_layout.addWidget(self.play_button)

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
        """Affiche la position dans l'audio lorsque la forme d'onde est cliquée."""
        pos = event.scenePos()
        data_pos = self.plot_widget.getViewBox().mapSceneToView(pos)
        audio_position = data_pos.x()

        # Convertir la position en un index dans waveform_data
        sample_index = int(audio_position * self.sample_rate)  # Position en échantillons
        sample_value = self.waveform_data[sample_index] if 0 <= sample_index < len(self.waveform_data) else None

        print(f"Position dans l'audio : {audio_position:.2f} secondes")
        print(f"Index dans waveform_data : {sample_index} / {len(self.waveform_data)}")
        print(f"Valeur de l'échantillon à cet index : {sample_value}")


# ------------------------------------------------------------- PLAYBACK LOGIC

    def toggle_playback(self):
        if self.is_playing:
            self.stop_audio()
        else:
            self.play_audio()

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

        self.stream = sd.OutputStream(samplerate=self.sample_rate, channels=2, callback=callback)
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

