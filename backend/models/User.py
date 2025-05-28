# /backend/models/User.py

from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.models.sample import Sample
# from backend.models.recorder import Recorder
from backend.models.SampleLibrary import SampleBank
from backend.models.Settings import Settings
from backend.db import SessionLocal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, pyqtSignal, QObject
import pygame
from backend.services.recorder_service import RecorderService

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

        self.recorder = RecorderService(
            pre_seconds=self.settings.pre_recording_seconds,
            sample_rate=44100,
            block_size=512
        )
        print("User: Settings:", self.settings.to_dict())
        
        self.audio_player = AudioPlayer()

        if self.settings.retro_recording_enabled:
            self.recorder.enable_retro()

    def play_sample(self, file_path):
        """ Demande la lecture d'un sample """
        self.audio_player.play_sample(file_path)

    def enable_retro(self):    self.recorder.enable_retro()
    def disable_retro(self):   self.recorder.disable_retro()
    def start_record(self, folder, retro_time): return self.recorder.start(folder, retro_time)
    def stop_record(self):      return self.recorder.stop()
    def shutdown_recorder(self): return self.recorder.shutdown()

class AudioPlayer:

    def __init__(self):
        pygame.mixer.init()
        # self.player.positionChanged.connect(self.handlePositionChanged)

        self.current_sample_id = -1
        self.current_time = 0  # Position en millisecondes
        self.current_sample_duration = -1
        self.current_sample_path = None
        self.last_set_pos = 0
        self.is_playing = False
        self.is_paused = False

    def toggle_play(self, sample_id, file_path, sample_duration):
        """ Joue un nouveau sample, en arrêtant le précédent si nécessaire """

        if self.current_sample_id == sample_id:
            if self.is_playing and self.is_paused:
                pygame.mixer.music.unpause()  # Démarre la lecture
                self.is_paused = False
                return True
            elif self.is_playing and not self.is_paused:
                self.is_paused = True
                pygame.mixer.music.pause()
                return False
        self.clear_audio()
        self.set_up_audio(sample_id, file_path, sample_duration)
        pygame.mixer.music.play(0, 0)
        self.is_paused = False
        self.is_playing = True
        return True
    
    def seek_position(self, sample_id, file_path, sample_duration, position):
        if self.current_sample_id != sample_id:
            self.clear_audio()
            self.set_up_audio(sample_id, file_path, sample_duration)
            self.set_position(position)
            pygame.mixer.music.play(0, self.last_set_pos)
            self.is_playing = True
            self.is_paused = False
            return True
        elif self.is_paused:
            self.set_position(position)
            pygame.mixer.music.stop()
            pygame.mixer.music.play(0, self.last_set_pos)
            pygame.mixer.music.pause()
            self.is_paused = True
            self.is_playing = True
            return False
        else :
            pygame.mixer.music.stop()
            self.set_position(position)
            pygame.mixer.music.play(0, self.last_set_pos)
            self.is_paused = False
            self.is_playing = True
            return True 

    def set_up_audio(self, sample_id, file_path, sample_duration):
        self.current_sample_id = sample_id
        self.current_sample_duration = sample_duration
        self.current_sample_path = file_path
        self.last_set_pos = 0
        self.is_paused = False
        self.is_playing = False
        pygame.mixer.music.load(self.current_sample_path)
        return self.current_sample_id
    
    def clear_audio(self):
        """Stoppe la lecture et décharge le fichier pour libérer le lock Windows."""
        # 1) Stoppe la lecture
        pygame.mixer.music.stop()

        # 2) Décharge le fichier de la mémoire (pygame >= 2.1)
        try:
            pygame.mixer.music.unload()
        except Exception:
            # si la version de pygame ne supporte pas unload(), on ignore
            pass

        # 3) Réinitialisation de l'état interne
        self.current_sample_id = -1
        self.current_sample_duration = -1
        self.current_sample_path = None
        self.is_playing = False
        self.is_paused = False
        self.last_set_pos = 0
        return 0
    
    def set_position(self, position_seconds):
        """ Change la position de lecture """
        position_seconds = round(position_seconds / 1000)
        self.last_set_pos = position_seconds

    def get_position(self):
        """ Obtient la position actuelle en secondes """
        pos = (pygame.mixer.music.get_pos())
        if pos == -1:
            self.clear_audio()
            return pos
        pos += self.last_set_pos * 1000
        return pos
