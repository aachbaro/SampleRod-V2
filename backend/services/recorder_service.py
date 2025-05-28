# backend/services/recorder_service.py
from PyQt6.QtCore import QObject, pyqtSlot
import multiprocessing as mp
from backend.models.recorder_worker import recorder_worker
from backend.services.settings_service import SettingsService

class RecorderService(QObject):
    """
    Service class to manage the recorder worker process.
    Maintenant hérite de QObject pour pouvoir recevoir les signaux Qt.
    """

    def __init__(self, settingsService: SettingsService, sample_rate, block_size):
        super().__init__()
        self.settingsService = settingsService

        # État initial récupéré depuis le SettingsService
        self.retro_enabled = self.settingsService.isRetroEnabled()
        self.pre_seconds   = self.settingsService.getPreSeconds()

        # On s'abonne aux signaux
        self.settingsService.retroToggled.connect(self.onRetroToggled)
        self.settingsService.preSecondsChanged.connect(self.onPreSecondsChanged)

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
                block_size
            ),
            daemon=True
        )
        self.is_recording = False
        self.worker.start()
        if self.retro_enabled:
            print("RecorderService: rétro-enregistrement activé au démarrage")
            self.cmd_queue.put(('enable_retro',))

    @pyqtSlot(bool)
    def onRetroToggled(self, enabled: bool):
        """Slot appelé à chaque fois qu’on active/désactive le rétro."""
        print("RecorderService: onRetroToggled called with signal: ", enabled)
        self.retro_enabled = enabled
        if enabled:
            print("RecorderService: retro activé")
            self.cmd_queue.put(('enable_retro',))
        else:
            print("RecorderService: retro désactivé")
            self.cmd_queue.put(('disable_retro',))

    @pyqtSlot(int)
    def onPreSecondsChanged(self, secs: int):
        """Slot appelé à chaque fois qu’on change la durée du buffer retro."""
        self.pre_seconds = secs
        print(f"RecorderService: retro buffer -> {secs}s")
        # si le worker supporte la modification à chaud :
        self.cmd_queue.put(('set_retro_time', secs))

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
        print("RecorderService: enable_retro called")
        self.cmd_queue.put(('enable_retro',))

    def disable_retro(self):
        """Disable background retro recording."""
        print("RecorderService: disable_retro called")
        self.cmd_queue.put(('disable_retro',))

    def start(self, output_folder, retro_time):
        """Démarre l’enregistrement live."""
        print(f"RecorderService: démarrage vers {output_folder} (retro={retro_time}s)")
        self.is_recording = True
        self.cmd_queue.put(('start', output_folder, retro_time))

    def stop(self):
        """Arrête l’enregistrement."""
        print("RecorderService: arrêt")
        self.is_recording = False
        self.cmd_queue.put(('stop',))

    def shutdown(self, timeout=2):
        """Arrêt propre du worker."""
        print("RecorderService: shutdown")
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
                print(f"RecorderService: retro_enabled -> {payload}")
                self.retro_enabled = payload
            elif msg == 'done':
                others.append(('done', payload))

        return others