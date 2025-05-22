# backend/services/recorder_service.py
import multiprocessing as mp
import time
from backend.models.recorder_worker import recorder_worker

class RecorderService:
    """
    Service class to manage the recorder worker process.
    Provides methods to enable/disable retro, start/stop recording,
    and polls for responses.
    """
    def __init__(self, pre_seconds, sample_rate, block_size):
        self.cmd_queue = mp.Queue()
        self.resp_queue = mp.Queue()
        self.worker = mp.Process(
            target=recorder_worker,
            args=(
                self.cmd_queue,
                self.resp_queue,
                pre_seconds,
                sample_rate,
                block_size
            ),
            daemon=True
        )
        self.is_recording = False
        self.retro_enabled = False
        self.worker.start()

    def enable_retro(self):
        """Enable background retro recording."""
        self.cmd_queue.put(('enable_retro',))

    def disable_retro(self):
        """Disable background retro recording."""
        self.cmd_queue.put(('disable_retro',))

    def record_button_clicked(self, selected_library, retro_time):
        """
        Handle record button click.
        If recording, stop it. If not, start recording.
        """
        print(f"record_button_clicked: {selected_library}, retro_time: {retro_time}")
        if self.is_recording:
            self.stop()
        else:
            # Start recording with the selected library
            self.start(selected_library, retro_time)

    def start(self, output_folder, retro_time):
        """
        Start live recording with given output folder and retro time (seconds).
        """
        self.is_recording = True
        self.cmd_queue.put(('start', output_folder, retro_time))

    def stop(self):
        """Stop recording and return filepath when done."""
        self.is_recording = False
        self.cmd_queue.put(('stop',))
        # # Wait for worker to respond with done message
        # msg, payload = self.resp_queue.get()
        # if msg == 'done':
        #     print(f"recorder_service: Audio saved in {payload}.")
        #     return payload
        # return None

    def shutdown(self, timeout=2):
        """Shut down the worker process cleanly."""
        self.cmd_queue.put(('shutdown',))
        # Optionally wait for ack
        try:
            msg, _ = self.resp_queue.get(timeout=timeout)
        except Exception:
            msg = None
        self.worker.join(timeout)
        return msg == 'shutdown_ack'

    def poll(self):
        """
        Non-blocking poll for any response messages.
        Met à jour `is_recording` et `retro_enabled`, 
        retourne la liste des autres messages (notamment 'done').
        """
        others = []
        while True:
            try:
                msg, payload = self.resp_queue.get_nowait()
            except Exception:
                break
            print(f"recorder_service: poll: {msg}, {payload}")

            if msg == 'started':
                print("recorder_service: started receveid from worker.")
                self.is_recording = True
            elif msg == 'stopped':
                print("recorder_service: stopped receveid from worker.")
                self.is_recording = False
            elif msg == 'retro_enabled':
                self.retro_enabled = payload
            elif msg == 'done':
                print("recorder_service: done receveid from worker.")
                others.append(('done', payload))
        return others
