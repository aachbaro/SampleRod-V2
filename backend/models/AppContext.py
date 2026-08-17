# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le "sac a dos" de l'application : AppContext cree, au demarrage, tous les
#   services (parametres, enregistrement, samples, captures, analyse...) et
#   les garde accessibles au meme endroit.
# - Toute l'interface recoit cet objet en parametre : quand un widget a besoin
#   d'une donnee ou d'une action, il passe par app_context.<service>.
# - Fournit aussi AudioPlayer, le petit lecteur audio partage (pygame) qui
#   sert a ecouter les samples dans toute l'application.
#
# CLASSES ET FONCTIONS (sommaire)
# - AppContext
#   - __init__()  : cree et connecte tous les services, dans l'ordre.
#   - shutdown()  : arrete proprement chaque service a la fermeture.
# - AudioPlayer (lecteur audio simple, base sur pygame.mixer.music)
#   - toggle_play()       : lit un sample / met en pause / reprend.
#   - seek_position()     : saute a une position precise dans le son.
#   - set_up_audio()      : charge un fichier audio en memoire.
#   - clear_audio()       : stoppe tout et libere le fichier (lock Windows).
#   - set_position()      : memorise la position de depart demandee.
#   - get_position()      : renvoie la position de lecture courante (ms).
#   - is_playing_sample() : dit si tel sample est en cours de lecture.
#   - stop_playback()     : arret complet (raccourci vers clear_audio).
#
# CE QUI RESTE A IMPLEMENTER (IDEES)
# - Centraliser plus d'initialisation (db, cache, jobs).
# - Gestion des erreurs de demarrage + retries.
# - Telemetrie et health check global.
#
# NOTES
# - AppContext.shutdown() doit etre appele a la fermeture de l'app
#   (c'est MainWindow.closeEvent qui s'en charge).
#
# LIENS CLES
# - app.py                  : cree AppContext au demarrage (etape 6).
# - backend/services/*      : les services instancies ici.
# - frontend/main_window.py : recoit AppContext et le distribue aux widgets.
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
from backend.services.reserve_mutation_service import ReserveMutationService
from backend.services.reserve_import_service import ReserveImportService
from backend.services.notification_service import NotificationService
from backend.services.directory_service import DirectoryService
from backend.services.remote_control_service import RemoteControlService
from backend.services.screenshot_service import ScreenshotService
from backend.services.drum_analysis_service import DrumAnalysisService
from backend.services.stem_separator_service import StemSeparatorService

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

        # Service d'enregistrement audio avec parametres fixes.
        # block_size=1024 (~23ms) : réduit les discontinuités WASAPI par rapport
        # à 512 (~11ms) en donnant plus de marge au scheduler Windows.
        self.recorder = RecorderService(
            self,
            sample_rate=44100,
            block_size=1024
        )
        
        # Lecteur audio local (pygame)
        self.audio_player = AudioPlayer()

        # Service de gestion des samples (stockage, import, etc.)
        self.sample_store = SampleService(self)
        self.reserve_mutations = ReserveMutationService(self)
        self.reserve_imports = ReserveImportService(self.sample_store)

        # Service de capture d'ecran (optionnel via settings)
        self.screenshots = ScreenshotService(self)

        # Service de stem separation (outil externe integre au labo)
        self.stem_separator = StemSeparatorService(self)
        self.drum_analysis = DrumAnalysisService(self)

        # Service de controle a distance : un petit serveur web local qui
        # permet de piloter SampleRod depuis un telephone ou un navigateur
        # (demarrer/arreter l'enregistrement, voir les samples...).
        # Il n'est cree et demarre que si l'option est activee dans les
        # parametres.
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
                # Abonnements : chaque fois qu'un evenement important se
                # produit (enregistrement demarre, sample ajoute/supprime/
                # renomme, capture d'ecran...), le serveur web en est informe
                # et le retransmet en direct aux navigateurs connectes (SSE).
                # Le drapeau _signals_hooked evite de s'abonner deux fois.
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
                        self.remote_control._signals_hooked = True
                except Exception:
                    pass
            except Exception:
                logger.exception("[AppContext] RemoteControlService: demarrage impossible")

    def shutdown(self):
        """Arrete proprement tous les services a la fermeture de l'application.

        Chaque arret est isole dans son propre try/except : si un service
        refuse de s'arreter, on le note dans les logs mais on continue
        d'arreter les autres (sinon l'application pourrait rester bloquee).
        Ordre : serveur web -> enregistreur -> traitements -> lecteur audio.
        """
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
            self.stem_separator.shutdown()
        except Exception:
            logger.exception("[AppContext] StemSeparatorService: shutdown impossible")

        try:
            self.drum_analysis.shutdown()
        except Exception:
            logger.exception("[AppContext] DrumAnalysisService: shutdown impossible")

        try:
            self.sample_store.shutdown()
        except Exception:
            logger.exception("[AppContext] SampleService: shutdown impossible")

        # 4) Libere le player
        try:
            self.audio_player.clear_audio()
        except Exception:
            logger.exception("[AppContext] AudioPlayer: clear impossible")



# =============================================================================
# AudioPlayer — lecteur audio minimaliste partage par toute l'application.
#
# Il repose sur pygame.mixer.music, qui ne sait lire qu'UN fichier a la fois :
# c'est voulu, cliquer sur un sample arrete automatiquement le precedent.
# Particularite de pygame : get_pos() donne le temps ecoule depuis le dernier
# play(), pas la position absolue dans le fichier. Le lecteur memorise donc
# la position de depart (last_set_pos) pour recalculer la vraie position.
# =============================================================================
class AudioPlayer:
    """Lecteur audio simple : un seul son a la fois, play/pause/seek."""

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
        """Joue, met en pause ou reprend un sample selon la situation.

        - Si on clique sur le sample DEJA charge : bascule pause/reprise.
        - Si on clique sur un AUTRE sample : on arrete tout, on charge le
          nouveau fichier et on le lit depuis le debut.
        Renvoie True si le son joue apres l'appel, False s'il est en pause
        (l'interface s'en sert pour afficher l'icone play ou pause).
        """
        # Cas 1 : meme sample -> on bascule entre pause et reprise.
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
        # Cas 2 : nouveau sample -> on nettoie l'ancien et on recharge.
        self.clear_audio()
        self.set_up_audio(sample_id, file_path, sample_duration)
        # Lecture depuis le debut
        pygame.mixer.music.play(0, 0)
        self.is_paused = False
        self.is_playing = True
        return True

    def seek_position(self, sample_id, file_path, sample_duration, position):
        """Saute a une position donnee (en ms) dans un sample.

        Utilise quand l'utilisateur clique sur la forme d'onde pour ecouter
        a partir d'un endroit precis. Trois cas geres : sample different
        (recharger puis sauter), sample en pause (sauter mais rester en
        pause), sample en lecture (sauter et continuer a jouer).
        """
        # Cas 1 : le sample demande n'est pas celui charge -> recharger.
        if self.current_sample_id != sample_id:
            self.clear_audio()
            self.set_up_audio(sample_id, file_path, sample_duration)
            self.set_position(position)
            pygame.mixer.music.play(0, self.last_set_pos)
            self.is_playing = True
            self.is_paused = False
            return True
        # Cas 2 : sample en pause -> on repositionne puis on remet en pause
        # (pygame n'a pas de "seek en pause", on triche : stop/play/pause).
        elif self.is_paused:
            self.set_position(position)
            pygame.mixer.music.stop()
            pygame.mixer.music.play(0, self.last_set_pos)
            pygame.mixer.music.pause()
            self.is_paused = True
            self.is_playing = True
            return False
        # Cas 3 : lecture en cours -> on repositionne et on relance.
        else :
            pygame.mixer.music.stop()
            self.set_position(position)
            pygame.mixer.music.play(0, self.last_set_pos)
            self.is_paused = False
            self.is_playing = True
            return True 

    def set_up_audio(self, sample_id, file_path, sample_duration):
        """Charge un fichier audio dans le lecteur et memorise ses infos."""
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
        """Memorise la position de depart demandee (recue en ms).

        Ne deplace pas la lecture par elle-meme : c'est l'appelant qui
        relance play() a partir de cette position (voir seek_position).
        """
        # L'entree est en ms, pygame attend des secondes
        position_seconds = round(position_seconds / 1000)
        self.last_set_pos = position_seconds

    def get_position(self):
        """Renvoie la position de lecture courante en millisecondes.

        pygame ne connait que le temps ecoule depuis le dernier play() :
        on y ajoute la position de depart memorisee (last_set_pos) pour
        obtenir la position reelle dans le fichier. Renvoie -1 quand la
        lecture est terminee (et nettoie alors le lecteur).
        """
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
