from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout,
                             QVBoxLayout, QSpacerItem, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
import qtawesome as qta
import librosa

class WaveformWidget(QWidget):
    def __init__(self, parent=None, audio_file_path=None):
        super().__init__(parent)
        self.audio_file_path = audio_file_path
        self.init_ui(audio_file_path)

    def init_ui(self):
        self.load_audio_data(self.audio_file_path)

        if self.waveform_data is not None:
            # Vous pouvez maintenant utiliser self.waveform_data, self.sample_rate et self.duration
            print(f"Données de forme d'onde : {self.waveform_data[:10]}")
            print(f"Fréquence d'échantillonnage : {self.sample_rate} Hz")
            print(f"Durée : {self.duration:.2f} secondes")


        main_layout = QVBoxLayout(self)

        # Encadré pour la forme d'onde
        self.waveform_frame = QFrame()
        self.waveform_frame.setFixedHeight(150)
        self.waveform_frame.setFrameShape(QFrame.Shape.Box)
        self.waveform_frame.setFrameShadow(QFrame.Shadow.Sunken)
        self.waveform_frame.setStyleSheet("background-color: #333;")  # Couleur de fond sombre
        main_layout.addWidget(self.waveform_frame)

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
            self.waveform_data = y
            self.sample_rate = sr
            self.duration = librosa.get_duration(y=y, sr=sr)

            print(f"Fichier audio chargé : {audio_path}")
            print(f"Fréquence d'échantillonnage : {sr} Hz")
            print(f"Durée : {self.duration:.2f} secondes")

        except Exception as e:
            print(f"Erreur lors du chargement du fichier audio : {e}")
            self.waveform_data = None
            self.sample_rate = None
            self.duration = None