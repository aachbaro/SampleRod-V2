# /backend/models/User.py

from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.models.sample import Sample
from backend.models.recorder import Recorder
from backend.models.SampleLibrary import SampleBank
from backend.models.Settings import Settings
from backend.db import SessionLocal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, pyqtSignal, QObject

class User:
    def __init__(self):
        print("Initialisation du User")
        session = SessionLocal()
        self.settings = session.query(Settings).first()
        if not self.settings:
            self.settings = Settings(retro_recording_enabled=False, pre_recording_seconds=0)
            session.add(self.settings)
            session.commit()

        self.libraries = SampleBank.get_all_libraries()

        self.recorder = Recorder(self.settings)  # Maintenant, settings est bien lié à une session
        print("User: Settings:", self.settings.to_dict())
        
        self.audio_player = AudioPlayer()

        if self.settings.retro_recording_enabled:
            self.recorder.bac_rec_activated()

    def play_sample(self, file_path):
        """ Demande la lecture d'un sample """
        self.audio_player.play_sample(file_path)


class AudioPlayer:
    playbackFinished = pyqtSignal(int)

    def __init__(self):
        self.player = QMediaPlayer()
        self.signals = AudioPlayerSignals()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self.handlePositionChanged)

        self.current_sample_id = None
        self.current_time = 0  # Position en millisecondes
        self.current_sample_duration = 0
        self.current_sample_path = None

    def toggle_play(self, sample_id, file_path, sample_duration):
        """ Joue un nouveau sample, en arrêtant le précédent si nécessaire """

        # Si on clique sur le même sample et qu'il est en lecture, on le met en pause
        if self.current_sample_id == sample_id:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.current_time = self.player.position()  # Sauvegarde du temps
                self.player.pause()
                return False
            else:
                # Reprise de la lecture à la position précédente
                self.player.setPosition(self.current_time)
                self.player.play()
                return True
        
        # Sinon, on joue un nouveau sample
        self.current_sample_id = sample_id
        self.current_sample_duration = sample_duration * 1000
        self.current_time = 0  # On reset la position
        self.current_sample_path = file_path

        self.player.stop()  # On arrête le précédent sample
        self.player.setSource(QUrl.fromLocalFile(file_path))  # On charge le nouveau sample
        self.player.play()  # On joue

        return True
    
    def handlePositionChanged(self, position):
        print(f"Media Status: {position} / {self.current_sample_duration}")  # Affiche tous les statuts reçus
        if position == self.current_sample_duration:
            print("sample end")
            self.signals.playbackFinished.emit(self.current_sample_id)
            self.player.stop()  # On arrête le précédent sample
            self.player.setSource(QUrl.fromLocalFile(self.current_sample_path))

class AudioPlayerSignals(QObject):
    playbackFinished = pyqtSignal(int)
