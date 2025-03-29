import pygame
import time
from PyQt6.QtWidgets import QApplication, QWidget, QSlider, QVBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEvent, QRect, QSize, pyqtSignal


class AudioPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.is_playing = False
        self.is_paused = False
        self.current_time = 0
        self.sample_duration = 0

    def play_audio(self, file_path):
        """ Démarre la lecture de l'audio """
        pygame.mixer.music.load(file_path)  # Charge le fichier audio
        pygame.mixer.music.play()  # Démarre la lecture
        self.is_playing = True
        self.is_paused = False
        self.sample_duration = pygame.mixer.Sound(file_path).get_length()  # Durée du fichier
        print(f"Lecture démarrée, durée : {self.sample_duration} secondes.")
        
    def set_position(self, position_seconds):
        """ Change la position de lecture """
        if self.is_playing:
            pygame.mixer.music.set_pos(position_seconds)  # Change la position de lecture en secondes
            print(f"Position changée à {position_seconds} secondes.")

    def get_position(self):
        """ Obtient la position actuelle en secondes """
        return pygame.mixer.music.get_pos() / 1000  # Renvoie la position en secondes


class AudioPlayerWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.audio_player = AudioPlayer()

        # Setup de l'interface graphique
        self.setWindowTitle("Audio Player")
        self.setGeometry(300, 300, 400, 100)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.setTickInterval(10)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)

        layout = QVBoxLayout()
        layout.addWidget(self.slider)
        self.setLayout(layout)

        # Connexion du slider à la méthode set_position
        self.slider.valueChanged.connect(self.slider_changed)

    def play_sample(self, file_path):
        """ Demande la lecture d'un sample """
        self.audio_player.play_audio(file_path)

    def slider_changed(self):
        """ Met à jour la position de la lecture lorsque le slider est déplacé """
        position = self.slider.value() / 1000  # Convertir la position du slider en secondes
        self.audio_player.set_position(position)

    def update_slider_position(self):
        """ Met à jour la position du slider pendant la lecture """
        if self.audio_player.is_playing:
            position = self.audio_player.get_position()
            slider_value = int((position / self.audio_player.sample_duration) * 1000)
            self.slider.setValue(slider_value)


# Exemple d'utilisation
if __name__ == "__main__":
    app = QApplication([])
    widget = AudioPlayerWidget()
    
    # Démarre la lecture d'un fichier audio
    widget.play_sample("/home/aachbaro/sgoinfre/sample2/SMPL_2025-03-25_19h00.16.wav")

    # Mise à jour périodique du slider pour suivre la position de lecture
    def update_position():
        widget.update_slider_position()
        QTimer.singleShot(100, update_position)  # Mise à jour toutes les 100ms

    update_position()

    widget.show()
    app.exec()