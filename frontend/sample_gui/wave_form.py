from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout,
                             QVBoxLayout, QSpacerItem, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, QTimer
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


class WaveformWidget(QWidget):
    def __init__(self, audio_file_path):
        super().__init__()
        self.audio_file_path = audio_file_path
        self.aff_start = 0
        self.aff_end = 0
        self.canvas_width = 0
        self.init_ui()

    def init_ui(self):
        """Initialise l'interface utilisateur et charge l'audio."""
        self.load_audio_data(self.audio_file_path)

        self.layout = QVBoxLayout(self)

        # Création du widget de tracé
        self.plot_widget = pg.PlotWidget()
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

        self.layout.addLayout(btn_layout)


    def load_audio_data(self, audio_path):
        """Charge les données audio et les prépare pour l'affichage."""
        try:
            y, sr = librosa.load(audio_path, sr=None)  # Garder le sample rate d'origine
            y = y / np.max(np.abs(y))  # Normaliser entre -1 et 1
            self.waveform_data = y
            self.sample_rate = sr
            self.duration = librosa.get_duration(y=y, sr=sr)
            print(f"Fichier chargé: {audio_path}, Durée: {self.duration:.2f}s")
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

    def zoom_or_pan(self, event):
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