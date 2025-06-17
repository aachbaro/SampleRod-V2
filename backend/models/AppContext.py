# /backend/models/AppContext.py

from pathlib import Path
import sys
import logging
logger = logging.getLogger("AppContext")
sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.models.sample import Sample
# from backend.models.recorder import Recorder
from backend.models.SampleLibrary import SampleBank
import pygame
from backend.services.recorder_service import RecorderService
from backend.services.settings_service import SettingsService
from backend.services.sample_service import SampleService
from backend.services.sample_service import IntegrityCheckWorker
from backend.services.notification_service import NotificationService
from backend.services.directory_service import DirectoryService

class AppContext:
    """
    Classe de contexte pour l'application, contenant les services et l'état utilisateur.
    Cette classe est utilisée pour initialiser les services nécessaires à l'application.
    """
    def __init__(self):
        logger.info("Initialisation de AppContext...")

        self.notifications = NotificationService()

        self.settings = SettingsService(self)

        self.recorder = RecorderService(
            self.settings,
            sample_rate=44100,
            block_size=512
        )
        
        self.audio_player = AudioPlayer()

        self.sample_store = SampleService(self)



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

    def is_playing_sample(self, sample_id: int) -> bool:
        """Return True if the given sample is currently playing."""
        return self.is_playing and self.current_sample_id == sample_id

    def stop_playback(self):
        """Stop playback and release any loaded resources."""
        self.clear_audio()
