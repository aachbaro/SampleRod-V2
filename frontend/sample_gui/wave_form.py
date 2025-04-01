from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout,
                             QVBoxLayout, QSpacerItem, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
import qtawesome as qta
import librosa
import pyqtgraph as pg
import numpy as np


class WaveformWidget(QWidget):
    def __init__(self, audio_file_path=None):
        super().__init__()
        self.audio_file_path = audio_file_path
        self.init_ui()

    def init_ui(self):
        self.load_audio_data(self.audio_file_path)

        if self.waveform_data is not None:
            # Vous pouvez maintenant utiliser self.waveform_data, self.sample_rate et self.duration
            print(f"Données de forme d'onde : {self.waveform_data[:10]}")
            print(f"Fréquence d'échantillonnage : {self.sample_rate} Hz")
            print(f"Durée : {self.duration:.2f} secondes")

            # Créer un tableau vide
            self.empty_waveform = np.zeros_like(self.waveform_data)
            self.display_empty = False


        main_layout = QVBoxLayout(self)

        # Encadré pour la forme d'onde
        self.waveform_frame = QFrame()
        self.waveform_frame.setFixedHeight(150)
        self.waveform_frame.setFrameShape(QFrame.Shape.Box)
        self.waveform_frame.setFrameShadow(QFrame.Shadow.Sunken)
        self.waveform_frame.setStyleSheet("background-color: #333;")  # Couleur de fond sombre
        main_layout.addWidget(self.waveform_frame)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')  # Arrière-plan blanc
        main_layout.addWidget(self.plot_widget)

        if self.waveform_data is not None:
            self.plot_item = self.plot_widget.plot(self.waveform_data)  # stocke l'objet PlotItem
            # Définir la plage de l'axe X
            total_samples = int(self.duration * self.sample_rate)
            self.plot_widget.getViewBox().setXRange(0, total_samples)

            # Masquer les axes et la grille
            self.plot_widget.hideAxis('bottom')
            self.plot_widget.hideAxis('left')
            self.plot_widget.showGrid(x=False, y=False)

            # Supprimer les marges
            self.plot_widget.setContentsMargins(0, 0, 0, 0)
            self.plot_widget.setYRange(min(self.waveform_data), max(self.waveform_data))
            self.plot_widget.getViewBox().setAutoVisible(y=True)

            # Timer pour réafficher la forme d'onde
            # self.timer = QTimer(self)
            # self.timer.timeout.connect(self.update_plot)
            # self.timer.start(100)

        # Layout pour les boutons de gestion
        button_layout = QHBoxLayout()

        # Boutons de gestion (exemple)
        self.zoom_in_button = QPushButton()
        self.zoom_in_button.setIcon(qta.icon('fa5s.search-plus', color='lightgray'))
        button_layout.addWidget(self.zoom_in_button)

        self.zoom_out_button = QPushButton()
        self.zoom_out_button.setIcon(qta.icon('fa5s.search-minus', color='lightgray'))
        button_layout.addWidget(self.zoom_out_button)

        self.cut_button = QPushButton()
        self.cut_button.setIcon(qta.icon('fa5s.cut', color='lightgray'))
        button_layout.addWidget(self.cut_button)

        self.play_selection_button = QPushButton()
        self.play_selection_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        button_layout.addWidget(self.play_selection_button)

        main_layout.addLayout(button_layout)

        # Style général du widget
        self.setStyleSheet("""
            QWidget {
                background-color: #222;
                color: #ffffff;
            }
        """)
        print(self.get_waveform_frame_size())

    def get_waveform_frame_size(self):
        """Récupère la taille du widget waveform_frame."""
        return self.waveform_frame.size()

    def load_audio_data(self, audio_path):
        """
        Charge les données audio à partir d'un fichier et les stocke dans des attributs self.

        Args:
            audio_path (str): Chemin du fichier audio.
        """
        try:
            # Charger le fichier audio avec Librosa
            y, sr = librosa.load(audio_path)

            # Stocker les données utiles dans des attributs self
            self.waveform_data = y[:20]
            self.sample_rate = sr
            print("len wfd", len(self.waveform_data))
            self.duration = librosa.get_duration(y=y, sr=sr)

            print(f"Fichier audio chargé : {audio_path}")
            print(f"Fréquence d'échantillonnage : {sr} Hz")
            print(f"Durée : {self.duration:.2f} secondes")

        except Exception as e:
            print(f"Erreur lors du chargement du fichier audio : {e}")
            self.waveform_data = None
            self.sample_rate = None
            self.duration = None
    
    def update_plot(self):
        """Met à jour le tracé avec les données de forme d'onde."""
        print("updplot")
        if self.waveform_data is not None:
            if self.display_empty:
                self.plot_item.setData(self.empty_waveform)
            else:
                self.plot_item.setData(self.waveform_data)
            self.display_empty = not self.display_empty