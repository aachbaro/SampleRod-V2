# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Contexte global qui instancie et expose les services principaux.
# - Point d'entree pour le cycle de vie backend (start/stop).
# - Fournit un lecteur audio simple (pygame) partage dans l'app.
#
# CE QUI EST DEJA EN PLACE
# - Instanciation: SettingsService, RecorderService, SampleService, Notifications.
# - AudioPlayer base sur pygame.mixer.music.
# - RemoteControlService (serveur HTTP local) demarre au lancement si active.
#
# CE QUI RESTE A IMPLEMENTER (IDEES)
# - Centraliser plus d'initialisation (db, cache, jobs).
# - Gestion des erreurs de demarrage + retries.
# - Telemetrie et health check global.
#
# NOTES
# - AppContext.shutdown() doit etre appele a la fermeture de l'app.
# -----------------------------------------------------------------------------
# backend/models/AppContext.py

# Utilitaires de gestion de chemins
from pathlib import Path
# Acces a la configuration du runtime Python (sys.path, etc.)
import sys
# Acces aux variables d'environnement
import os
# Journalisation pour tracer l'etat de l'appli
import logging
# Logger nomme pour isoler les messages du contexte applicatif
logger = logging.getLogger("AppContext")
# Ajoute le dossier "backend" au sys.path pour garantir les imports locaux
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Modeles et services utilises par l'application.
from backend.models.sample import Sample
# from backend.models.recorder import Recorder
from backend.models.SampleLibrary import SampleBank
# Pygame sert a la lecture audio (mixer.music)
import pygame
from backend.services.recorder_service import RecorderService
from backend.services.settings_service import SettingsService
from backend.services.sample_service import SampleService
from backend.services.sample_service import IntegrityCheckWorker
from backend.services.notification_service import NotificationService
from backend.services.directory_service import DirectoryService
from backend.services.remote_control_service import RemoteControlService
from backend.services.screenshot_service import ScreenshotService

# Contexte global: instancie les services principaux de l'application.
class AppContext:
    """
    Classe de contexte pour l'application, contenant les services et l'état utilisateur.
    Cette classe est utilisée pour initialiser les services nécessaires à l'application.
    """
    def __init__(self):
        # Trace l'initialisation globale du contexte
        logger.info("Initialisation de AppContext...")

        # Service de notifications interne (UI/logs)
        self.notifications = NotificationService()

        # Service de parametres globaux (config utilisateur)
        self.settings = SettingsService(self)

        # Service d'enregistrement audio avec parametres fixes
        self.recorder = RecorderService(
            self,
            sample_rate=44100,
            block_size=512
        )
        
        # Lecteur audio local (pygame)
        self.audio_player = AudioPlayer()

        # Service de gestion des samples (stockage, import, etc.)
        self.sample_store = SampleService(self)

        # Service de capture d'ecran (optionnel via settings)
        self.screenshots = ScreenshotService(self)

        # Service de controle a distance (serveur HTTP local)
        self.remote_control = None
        enabled = self.settings.isRemoteControlEnabled()
        if enabled:
            port = self.settings.getRemoteControlPort()
            repo_root = Path(__file__).resolve().parents[2]
            ui_root = repo_root / "frontend" / "remote_ui"
            self.remote_control = RemoteControlService(
                app_context=self,
                host=os.getenv("REMOTE_CONTROL_HOST", "0.0.0.0"),
                port=port,
                allow_origin=os.getenv("REMOTE_CONTROL_CORS", "*"),
                auth_token=os.getenv("REMOTE_CONTROL_TOKEN"),
                ui_root=ui_root,
                auto_build_ui=True,
            )
            try:
                self.remote_control.start()
                # Pousse les changements d'etat du recorder via SSE
                try:
                    if not getattr(self.remote_control, "_signals_hooked", False):
                        self.recorder.recordingStateChanged.connect(
                            self.remote_control.push_status
                        )
                        self.sample_store.sampleAdded.connect(
                            self.remote_control.push_sample_added
                        )
                        self.sample_store.sampleDeleted.connect(
                            self.remote_control.push_sample_deleted
                        )
                        self.sample_store.sampleRenamed.connect(
                            self.remote_control.push_sample_renamed
                        )
                        self.settings.retroToggled.connect(
                            self.remote_control.push_status
                        )
                        self.settings.preSecondsChanged.connect(
                            self.remote_control.push_status
                        )
                        self.screenshots.screenshotAdded.connect(
                            self.remote_control.push_screenshot_added
                        )
                        self.screenshots.screenshotDeleted.connect(
                            self.remote_control.push_screenshot_deleted
                        )
                        self.screenshots.screenshotsChanged.connect(
                            self.remote_control.push_screenshots_changed
                        )
                        self.remote_control._signals_hooked = True
                except Exception:
                    pass
            except Exception:
                logger.exception("[AppContext] RemoteControlService: demarrage impossible")

    def shutdown(self):
        """Nettoie les ressources principales (serveur, recorder, audio)."""
        logger.info("[AppContext] Shutdown...")
        # 1) Arreter le serveur remote si actif
        if self.remote_control and self.remote_control.is_running:
            try:
                self.remote_control.stop()
            except Exception:
                logger.exception("[AppContext] RemoteControlService: stop impossible")

        # 2) Stop recorder + worker
        try:
            if self.recorder.is_recording:
                self.recorder.stop()
            self.recorder.shutdown()
        except Exception:
            logger.exception("[AppContext] RecorderService: shutdown impossible")

        # 3) Libere le player
        try:
            self.audio_player.clear_audio()
        except Exception:
            logger.exception("[AppContext] AudioPlayer: clear impossible")



# Lecteur audio minimaliste base sur pygame.mixer.music
class AudioPlayer:

    def __init__(self):
        # Initialise le mixer pygame avant toute lecture
        pygame.mixer.init()
        # self.player.positionChanged.connect(self.handlePositionChanged)

        # Identifiant du sample en cours
        self.current_sample_id = -1
        # Temps courant (ms) - variable de suivi potentiel
        self.current_time = 0  # Position en millisecondes
        # Duree du sample charge
        self.current_sample_duration = -1
        # Chemin du fichier audio charge
        self.current_sample_path = None
        # Derniere position fixee (en secondes)
        self.last_set_pos = 0
        # Etat lecture / pause
        self.is_playing = False
        self.is_paused = False

    def toggle_play(self, sample_id, file_path, sample_duration):
        # Si on reclique le meme sample, on toggle pause/reprise.
        """ Joue un nouveau sample, en arrêtant le précédent si nécessaire """

        if self.current_sample_id == sample_id:
            if self.is_playing and self.is_paused:
                # Reprendre la lecture
                pygame.mixer.music.unpause()  # Démarre la lecture
                self.is_paused = False
                return True
            elif self.is_playing and not self.is_paused:
                # Mettre en pause
                self.is_paused = True
                pygame.mixer.music.pause()
                return False
        # Si c'est un nouveau sample, on nettoie et on recharge.
        self.clear_audio()
        self.set_up_audio(sample_id, file_path, sample_duration)
        # Lecture depuis le debut
        pygame.mixer.music.play(0, 0)
        self.is_paused = False
        self.is_playing = True
        return True
    
    def seek_position(self, sample_id, file_path, sample_duration, position):
        # Si le sample est different, on recharge puis on seek.
        if self.current_sample_id != sample_id:
            self.clear_audio()
            self.set_up_audio(sample_id, file_path, sample_duration)
            self.set_position(position)
            pygame.mixer.music.play(0, self.last_set_pos)
            self.is_playing = True
            self.is_paused = False
            return True
        # Si le sample est en pause, on repositionne puis on repause.
        elif self.is_paused:
            self.set_position(position)
            pygame.mixer.music.stop()
            pygame.mixer.music.play(0, self.last_set_pos)
            pygame.mixer.music.pause()
            self.is_paused = True
            self.is_playing = True
            return False
        # En lecture active, on repositionne et on relance.
        else :
            pygame.mixer.music.stop()
            self.set_position(position)
            pygame.mixer.music.play(0, self.last_set_pos)
            self.is_paused = False
            self.is_playing = True
            return True 

    def set_up_audio(self, sample_id, file_path, sample_duration):
        # Memorise les metadonnees du sample
        self.current_sample_id = sample_id
        self.current_sample_duration = sample_duration
        self.current_sample_path = file_path
        self.last_set_pos = 0
        self.is_paused = False
        self.is_playing = False
        # Charge le fichier dans le mixer pygame
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
        # Remise a zero de tous les champs de suivi
        self.current_sample_id = -1
        self.current_sample_duration = -1
        self.current_sample_path = None
        self.is_playing = False
        self.is_paused = False
        self.last_set_pos = 0
        return 0
    
    def set_position(self, position_seconds):
        """ Change la position de lecture """
        # L'entree est en ms, pygame attend des secondes
        position_seconds = round(position_seconds / 1000)
        self.last_set_pos = position_seconds

    def get_position(self):
        """ Obtient la position actuelle en secondes """
        # get_pos retourne le temps ecoule depuis le dernier play()
        pos = (pygame.mixer.music.get_pos())
        if pos == -1:
            # -1 signifie lecture terminee ou invalide
            self.clear_audio()
            return pos
        # Ajout de la position de depart (en secondes -> ms)
        pos += self.last_set_pos * 1000
        return pos

    def is_playing_sample(self, sample_id: int) -> bool:
        """Return True if the given sample is currently playing."""
        # Verifie que le bon sample est actif et en lecture
        return self.is_playing and self.current_sample_id == sample_id

    def stop_playback(self):
        """Stop playback and release any loaded resources."""
        # Arret complet et liberation des ressources chargees
        self.clear_audio()
