# backend/services/recorder_service.py
# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service d'orchestration de l'enregistrement audio cote backend.
# - Intermediaire entre:
#   1) L'UI/les settings (PyQt6, signaux/slots)
#   2) Le worker d'enregistrement (processus separé via multiprocessing)
#   3) Le stockage/notification (SampleService + NotificationService)
#
# RESPONSABILITES PRINCIPALES
# - Ecouter les changements de configuration (retro, pre_seconds, device, sample_rate).
# - Envoyer des commandes au worker (start/stop/enable_retro/etc.).
# - Recevoir les reponses du worker (poll), mettre a jour l'etat,
#   et gerer la post-production (verifier silence, notifier, ajouter au store).
#
# FLUX GLOBAL
# UI -> RecorderService (signal/slot) -> cmd_queue -> recorder_worker (process)
# recorder_worker -> resp_queue -> RecorderService.poll -> UI/Stockage/Notifications
# -----------------------------------------------------------------------------
# PyQt6: QObject + decorateurs de slots pour recevoir les signaux
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal
# multiprocessing: worker d'enregistrement dans un process isole
import multiprocessing as mp
# Fonction worker qui effectue la capture audio
from backend.models.recorder_worker import recorder_worker
# Service des settings (source de verite des preferences)
from backend.services.settings_service import SettingsService
# Modele Sample (pas utilise ici directement, mais lie au flux de sauvegarde)
from backend.models.sample import Sample
# Typage des notifications pour l'UI
from backend.services.notification_service import NotificationType
import logging
# wave: lecture de WAV pour detecter un enregistrement silencieux
import wave
# os: suppression du fichier si enregistrement vide
import os
# Logger specifique au service d'enregistrement
logger = logging.getLogger("recorder_service")

# Service principal d'enregistrement, pilote le worker audio.
class RecorderService(QObject):
    """
    Service class to manage the recorder worker process.
    Maintenant hérite de QObject pour pouvoir recevoir les signaux Qt.
    """
    # Emis quand l'etat d'enregistrement change (True/False)
    recordingStateChanged = pyqtSignal(bool)

    def __init__(self, app_context, sample_rate, block_size):
        super().__init__()
        # Reference vers le contexte applicatif pour acceder aux autres services
        self.app_context = app_context
        # Raccourci vers le SettingsService (source de config)
        self.settingsService: SettingsService = app_context.settings

        # État initial récupéré depuis le SettingsService
        # Etat initial recupere depuis le SettingsService
        self.retro_enabled = self.settingsService.isRetroEnabled()
        self.pre_seconds   = self.settingsService.getPreSeconds()

        # Nom du device loopback initial (peut etre None)
        self.loopback_name = self.settingsService.loopback_device.name if self.settingsService.loopback_device else None

        # Abonnement aux signaux de changement de config
        self.settingsService.retroToggled.connect(self.onRetroToggled)
        self.settingsService.preSecondsChanged.connect(self.onPreSecondsChanged)
        self.settingsService.loopbackDeviceChanged.connect(self.onLoopbackDeviceChanged)
        self.settingsService.sampleRateChanged.connect(self.onSampleRateChanged)

        # Prépare le worker
        # Preparation du worker (processus isole) et de ses files de messages
        self.cmd_queue  = mp.Queue()
        self.resp_queue = mp.Queue()
        self.worker = mp.Process(
            target=recorder_worker,
            args=(
                self.cmd_queue,
                self.resp_queue,
                self.pre_seconds,
                sample_rate,
                block_size,
                self.loopback_name,
            ),
            daemon=True
        )
        # Etat local: enregistrement actif ou non
        self.is_recording = False
        # Meta runtime de prise: True si la prise en cours suit la precedente.
        self._current_take_sequential = False
        self._retro_refill_active = False
        # Demarrage du processus worker
        self.worker.start()
        # Si retro actif au demarrage, on l'active cote worker
        if self.retro_enabled:
            logger.info("RecorderService: rétro-enregistrement activé au démarrage")
            # Remettre le worker en mode retro
            self.cmd_queue.put(('enable_retro',))

    @pyqtSlot(bool)
    def onRetroToggled(self, enabled: bool):
        """Slot appelé à chaque fois qu’on active/désactive le rétro."""
        # Met a jour l'etat local et transmet l'ordre au worker
        logger.info("RecorderService: onRetroToggled called with signal: ", enabled)
        self.retro_enabled = enabled
        if enabled:
            logger.info("RecorderService: retro activé")
            self.cmd_queue.put(('enable_retro',))
        else:
            logger.info("RecorderService: retro désactivé")
            self.cmd_queue.put(('disable_retro',))

    @pyqtSlot(int)
    def onPreSecondsChanged(self, secs: int):
        """Slot appelé à chaque fois qu’on change la durée du buffer retro."""
        # Met a jour la valeur locale et notifie le worker
        self.pre_seconds = secs
        logger.info(f"RecorderService: retro buffer -> {secs}s")
        # si le worker supporte la modification à chaud :
        self.cmd_queue.put(('set_retro_time', secs))

    @pyqtSlot(object)
    def onLoopbackDeviceChanged(self, device):
        """Slot appelé quand on change le device loopback dans les settings."""
        # Met a jour le device actif cote service
        name = device.name if device else None
        self.loopback_name = name
        logger.info(f"RecorderService: changement de loopback → {name}")
        # on prévient le worker et on ré-active le rétro s’il l’était déjà
        # On previent le worker et on re-active le retro si besoin
        self.cmd_queue.put(('set_device', name))
        if self.retro_enabled:
            # remettre le worker en mode rétro
            self.cmd_queue.put(('enable_retro',))

    @pyqtSlot(int)
    def onSampleRateChanged(self, new_rate: int):
        """
        Slot appelé quand on modifie le sample rate dans les settings.
        On envoie la commande vers le worker pour qu’il redémarre 
        la capture au nouveau sample rate.
        """
        # self.cmd_q est la queue liée au worker (Queue pour ordres)
        logger.info(f"RecorderService: demande de changement de sample_rate → {new_rate}")
        self.cmd_queue.put(('set_sample_rate', new_rate))

    def record_button_clicked(self, selected_library, retro_time=None):
        """
        Handle record button click.
        Si on donne retro_time None, on utilise self.pre_seconds.
        """
        # Choisit le temps retro effectif (argument ou valeur par defaut)
        rt = retro_time if retro_time is not None else self.pre_seconds
        # Toggle: stop si enregistrement en cours, sinon start
        if self.is_recording:
            self.stop()
        else:
            self.start(selected_library, rt)

    def enable_retro(self):
        """Enable background retro recording."""
        # Active le mode retro dans le worker
        logger.info("RecorderService: enable_retro called")
        self.cmd_queue.put(('enable_retro',))

    def disable_retro(self):
        """Disable background retro recording."""
        # Desactive le mode retro dans le worker
        logger.info("RecorderService: disable_retro called")
        self.cmd_queue.put(('disable_retro',))

    def start(self, output_folder, retro_time):
        """Démarre l’enregistrement live."""
        # Guard: worker KO -> notification explicite
        try:
            if not self.worker.is_alive():
                logger.error("RecorderService: worker inactif (is_alive=False)")
                self.app_context.notifications.notify(
                    title="Enregistrement impossible",
                    message="Le worker d'enregistrement est inactif. Redémarre l'application.",
                    type=NotificationType.WARNING,
                )
                return
        except Exception:
            # Si l'état n'est pas accessible, on tente quand même
            pass

        logger.info(f"RecorderService: démarrage vers {output_folder} (retro={retro_time}s)")
        self._set_recording_state(True)
        self.cmd_queue.put(('start', output_folder, retro_time))

    def stop(self):
        """Arrête l’enregistrement."""
        logger.info("RecorderService: arrêt")
        self._set_recording_state(False)
        self.cmd_queue.put(('stop',))

    def shutdown(self, timeout=2):
        """Arrêt propre du worker."""
        logger.info("RecorderService: shutdown")
        # Demande l'arret du worker et attend un ACK
        self.cmd_queue.put(('shutdown',))
        try:
            msg, _ = self.resp_queue.get(timeout=timeout)
        except Exception:
            msg = None
        # Join avec timeout pour eviter un blocage indefini
        self.worker.join(timeout)
        return msg == 'shutdown_ack'

    def poll(self):
        """
        Poll non-bloquant des réponses du worker.
        Met à jour self.is_recording et self.retro_enabled.
        """
        # Accumule les messages "done" a renvoyer au caller
        others = []
        while True:
            try:
                msg, payload = self.resp_queue.get_nowait()
            except Exception:
                break

            # Lecture d'un message de statut
            if msg == 'started':
                # Le worker confirme le demarrage
                if isinstance(payload, dict):
                    self._current_take_sequential = bool(
                        payload.get("sequential_with_previous", False)
                    )
                else:
                    self._current_take_sequential = False
                self._set_recording_state(True)
            elif msg == 'stopped':
                # Le worker confirme l'arret
                self._set_recording_state(False)
            elif msg == 'retro_enabled':
                logger.info(f"RecorderService: retro_enabled -> {payload}")
                self.retro_enabled = payload
            elif msg == 'retro_refill_state':
                # Refill termine -> la normalisation differee peut etre relancee.
                self._retro_refill_active = bool(payload)
                if payload is False:
                    try:
                        self.app_context.sample_store.on_retro_refill_complete()
                    except Exception:
                        pass
            elif msg == 'done':
                # Un enregistrement vient d'etre finalise
                if isinstance(payload, dict):
                    path = payload.get("path")
                    sequential_with_previous = bool(
                        payload.get(
                            "sequential_with_previous",
                            self._current_take_sequential,
                        )
                    )
                else:
                    path = payload
                    sequential_with_previous = self._current_take_sequential
                if not path:
                    continue
                if self._is_wav_silent(path):
                    # Sequence vide : notification et pas de sauvegarde
                    self.app_context.notifications.notify(
                        title="Enregistrement annule",
                        message="Aucun son detecte : aucun fichier n'a ete cree.",
                        type=NotificationType.WARNING,
                    )
                    try:
                        # Supprime le fichier vide
                        os.remove(path)
                    except Exception:
                        pass
                else:
                    # Ajoute le sample au store applicatif
                    self.app_context.sample_store.add(
                        path,
                        from_recorder=True,
                        sequential_with_previous=sequential_with_previous,
                    )
                    # Cas race-condition: refill deja termine avant reception de "done".
                    if not self._retro_refill_active:
                        try:
                            self.app_context.sample_store.on_retro_refill_complete()
                        except Exception:
                            pass
                    others.append(('done', path))
            elif msg == 'done_error':
                logger.info(f"RecorderService: export WAV en erreur: {payload}")
                self.app_context.notifications.notify(
                    title="Enregistrement impossible",
                    message="Erreur pendant la finalisation du fichier audio.",
                    type=NotificationType.WARNING,
                )

        return others

    def _set_recording_state(self, value: bool):
        """Met a jour l'etat local et emet le signal si changement."""
        if self.is_recording != value:
            self.is_recording = value
            self.recordingStateChanged.emit(value)

    @staticmethod
    def _is_wav_silent(path: str) -> bool:
        """Return True if the WAV file contains only zeros."""
        try:
            # Lecture brute du contenu audio
            with wave.open(path, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
            # Si tous les octets sont a zero, on considere l'audio silencieux
            return all(b == 0 for b in frames)
        except Exception:
            # En cas d'erreur, on prefere ne pas bloquer l'usage
            return False
