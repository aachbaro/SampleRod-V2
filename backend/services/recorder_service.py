# backend/services/recorder_service.py
from PyQt6.QtCore import QObject, pyqtSlot
import multiprocessing as mp
from backend.models.recorder_worker import recorder_worker
from backend.services.settings_service import SettingsService
from backend.models.sample import Sample
from backend.services.notification_service import NotificationType
import logging
import wave
import os
logger = logging.getLogger("recorder_service")

class RecorderService(QObject):
    """
    Service class to manage the recorder worker process.
    Maintenant hérite de QObject pour pouvoir recevoir les signaux Qt.
    """

    def __init__(self, app_context, sample_rate, block_size):
        super().__init__()
        self.app_context = app_context
        self.settingsService: SettingsService = app_context.settings

        # État initial récupéré depuis le SettingsService
        self.retro_enabled = self.settingsService.isRetroEnabled()
        self.pre_seconds   = self.settingsService.getPreSeconds()

        # nom du device loopback initial
        self.loopback_name = self.settingsService.loopback_device.name if self.settingsService.loopback_device else None

        # On s'abonne aux signaux
        self.settingsService.retroToggled.connect(self.onRetroToggled)
        self.settingsService.preSecondsChanged.connect(self.onPreSecondsChanged)
        self.settingsService.loopbackDeviceChanged.connect(self.onLoopbackDeviceChanged)
        self.settingsService.sampleRateChanged.connect(self.onSampleRateChanged)

        # Prépare le worker
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
        self.is_recording = False
        self.worker.start()
        if self.retro_enabled:
            logger.info("RecorderService: rétro-enregistrement activé au démarrage")
            self.cmd_queue.put(('enable_retro',))

    @pyqtSlot(bool)
    def onRetroToggled(self, enabled: bool):
        """Slot appelé à chaque fois qu’on active/désactive le rétro."""
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
        self.pre_seconds = secs
        logger.info(f"RecorderService: retro buffer -> {secs}s")
        # si le worker supporte la modification à chaud :
        self.cmd_queue.put(('set_retro_time', secs))

    @pyqtSlot(object)
    def onLoopbackDeviceChanged(self, device):
        """Slot appelé quand on change le device loopback dans les settings."""
        name = device.name if device else None
        self.loopback_name = name
        logger.info(f"RecorderService: changement de loopback → {name}")
        # on prévient le worker et on ré-active le rétro s’il l’était déjà
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
        rt = retro_time if retro_time is not None else self.pre_seconds
        if self.is_recording:
            self.stop()
        else:
            self.start(selected_library, rt)

    def enable_retro(self):
        """Enable background retro recording."""
        logger.info("RecorderService: enable_retro called")
        self.cmd_queue.put(('enable_retro',))

    def disable_retro(self):
        """Disable background retro recording."""
        logger.info("RecorderService: disable_retro called")
        self.cmd_queue.put(('disable_retro',))

    def start(self, output_folder, retro_time):
        """Démarre l’enregistrement live."""
        logger.info(f"RecorderService: démarrage vers {output_folder} (retro={retro_time}s)")
        self.is_recording = True
        self.cmd_queue.put(('start', output_folder, retro_time))

    def stop(self):
        """Arrête l’enregistrement."""
        logger.info("RecorderService: arrêt")
        self.is_recording = False
        self.cmd_queue.put(('stop',))

    def shutdown(self, timeout=2):
        """Arrêt propre du worker."""
        logger.info("RecorderService: shutdown")
        self.cmd_queue.put(('shutdown',))
        try:
            msg, _ = self.resp_queue.get(timeout=timeout)
        except Exception:
            msg = None
        self.worker.join(timeout)
        return msg == 'shutdown_ack'

    def poll(self):
        """
        Poll non-bloquant des réponses du worker.
        Met à jour self.is_recording et self.retro_enabled.
        """
        others = []
        while True:
            try:
                msg, payload = self.resp_queue.get_nowait()
            except Exception:
                break

            if msg == 'started':
                self.is_recording = True
            elif msg == 'stopped':
                self.is_recording = False
            elif msg == 'retro_enabled':
                logger.info(f"RecorderService: retro_enabled -> {payload}")
                self.retro_enabled = payload
            elif msg == 'done':
                path = payload
                if self._is_wav_silent(path):
                    # ▶ Sequence vide : notification et pas de sauvegarde
                    self.app_context.notifications.notify(
                        title="Enregistrement annulé",
                        message="Aucun son détecté : aucun fichier n’a été créé.",
                        type=NotificationType.WARNING,
                    )
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                else:
                    self.app_context.sample_store.add(path)
                    others.append(('done', path))

        return others

    @staticmethod
    def _is_wav_silent(path: str) -> bool:
        """Return True if the WAV file contains only zeros."""
        try:
            with wave.open(path, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
            return all(b == 0 for b in frames)
        except Exception:
            return False
