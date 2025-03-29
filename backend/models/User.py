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
import pygame

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

    def __init__(self):
        pygame.mixer.init()
        # self.player.positionChanged.connect(self.handlePositionChanged)

        self.current_sample_id = -1
        self.current_time = 0  # Position en millisecondes
        self.current_sample_duration = -1
        self.current_sample_path = None
        self.is_playing = False
        self.is_paused = False

    def toggle_play(self, sample_id, file_path, sample_duration):
        """ Joue un nouveau sample, en arrêtant le précédent si nécessaire """

        if self.current_sample_id == sample_id:
            if self.is_playing and self.is_paused:
                pygame.mixer.music.unpause()  # Démarre la lecture
                self.is_playing = True
                self.is_paused = False
                return True
            elif self.is_playing and not self.is_paused:
                self.is_paused = True
                pygame.mixer.music.pause()
                print("Lecture audio en pause.")
                return False
        self.clear_audio()
        self.set_up_audio(sample_id, file_path, sample_duration)
        pygame.mixer.music.play()
        self.is_paused = False
        self.is_playing = True
        return True
    
    # def seek_position(self, sample_id, file_path, sample_duration, position):
    #     print("seek audio and play", position)
    #     if self.current_sample_id != sample_id:
    #         self.clear_audio()
    #         self.set_up_audio(sample_id, file_path, sample_duration)
    #     if self.player.seekable:
    #         self.player.setPosition(position)
    #     else:
    #         print("Le média n'est pas seekable.")
    #     self.current_time = position
    #     print(self.player.position())
    #     if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
    #         return True
    #     return False

    def set_up_audio(self, sample_id, file_path, sample_duration):
        print("Changing disk")
        self.current_sample_id = sample_id
        self.current_sample_duration = sample_duration * 1000
        self.current_sample_path = file_path
        self.current_time = 0
        self.is_paused = False
        self.is_playing = False
        pygame.mixer.music.load(self.current_sample_path)
        return self.current_sample_id
    
    def clear_audio(self):
        print("Throwing disk away")
        print(self.current_sample_id, self.current_sample_duration)
        pygame.mixer.music.stop()
        self.current_sample_id = -1
        self.current_sample_duration = -1
        self.current_sample_path = None
        self.is_playing = False
        self.is_paused = False
        return 0
    
    def set_position(self, position_seconds):
        """ Change la position de lecture """
        if self.is_playing:
            pygame.mixer.music.set_pos(position_seconds)  # Change la position de lecture en secondes
            print(f"Position changée à {position_seconds} secondes.")

    def get_position(self):
        """ Obtient la position actuelle en secondes """
        pos = (pygame.mixer.music.get_pos())
        print(pos)
        if pos == -1:
            self.clear_audio()
        return pos

    
    def handlePositionChanged(self, position):
        # print(f"Media Status: {position} / {self.current_sample_duration}")  # Affiche tous les statuts reçus
        if self.current_sample_id:
            self.signals.positionChanged.emit(self.current_sample_id, position, (int)(self.current_sample_duration))
        if position == self.current_sample_duration:
            self.clear_audio()




# class AudioPlayer:

#     def __init__(self):
#         self.player = QMediaPlayer()
#         self.signals = AudioPlayerSignals()
#         self.audio_output = QAudioOutput()
#         self.player.setAudioOutput(self.audio_output)
#         self.player.positionChanged.connect(self.handlePositionChanged)

#         self.current_sample_id = -1
#         self.current_time = 0  # Position en millisecondes
#         self.current_sample_duration = -1
#         self.current_sample_path = None

#     def toggle_play(self, sample_id, file_path, sample_duration):
#         """ Joue un nouveau sample, en arrêtant le précédent si nécessaire """

#         if self.current_sample_id == sample_id:
#             if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
#                 self.current_time = self.player.position()
#                 self.player.pause()
#                 return False
#             else:
#                 self.player.setPosition(self.current_time)
#                 print(self.player.position())
#                 self.player.play()
#                 return True
        
#         self.clear_audio()
#         self.set_up_audio(sample_id, file_path, sample_duration)
#         print(self.player.position())
#         self.player.play()
#         return True
    
#     def seek_position(self, sample_id, file_path, sample_duration, position):
#         print("seek audio and play", position)
#         if self.current_sample_id != sample_id:
#             self.clear_audio()
#             self.set_up_audio(sample_id, file_path, sample_duration)
#         if self.player.seekable:
#             self.player.setPosition(position)
#         else:
#             print("Le média n'est pas seekable.")
#         self.current_time = position
#         print(self.player.position())
#         if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
#             return True
#         return False

#     def set_up_audio(self, sample_id, file_path, sample_duration):
#         print("Changing disk")
#         self.current_sample_id = sample_id
#         self.current_sample_duration = sample_duration * 1000
#         self.current_sample_path = file_path
#         self.current_time = 0
#         self.player.setSource(QUrl.fromLocalFile(file_path))
#         return self.current_sample_id
    
#     def clear_audio(self):
#         print("Throwing disk away")
#         print(self.current_sample_id, self.current_sample_duration)
#         self.signals.positionChanged.emit(self.current_sample_id, (int)(self.current_sample_duration), (int)(self.current_sample_duration))
#         self.player.stop()
#         self.player.setSource(QUrl())
#         self.current_sample_id = -1
#         self.current_sample_duration = -1
#         self.current_sample_path = None
#         return 0

    
#     def handlePositionChanged(self, position):
#         # print(f"Media Status: {position} / {self.current_sample_duration}")  # Affiche tous les statuts reçus
#         if self.current_sample_id:
#             self.signals.positionChanged.emit(self.current_sample_id, position, (int)(self.current_sample_duration))
#         if position == self.current_sample_duration:
#             self.clear_audio()
        

# class AudioPlayerSignals(QObject):
#     positionChanged = pyqtSignal(int, int, int)
