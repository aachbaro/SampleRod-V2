# backend/recorder_worker.py
import soundcard as sc
import soundfile as sf
import numpy as np
import os
import time
from datetime import datetime
from collections import deque
import multiprocessing as mp


def recorder_worker(cmd_q, resp_q, pre_seconds, sample_rate, block_size):
    """
    Worker process for audio capture and retro-recording.
    Listens on cmd_q for commands and writes WAV on 'stop'.
    """
    print("recorder_worker: Starting...")
    # Initialize loopback microphone
    mic = sc.get_microphone(
        id=str(sc.default_speaker().name),
        include_loopback=True
    ).recorder(samplerate=sample_rate)

    # Retro buffer
    maxlen = int(pre_seconds * sample_rate / block_size)
    retro_buf = deque(maxlen=maxlen)
    live_buf = []

    is_recording = False
    retro_enabled = False
    output_folder = None
    retro_time = 0

    # **Ouvre le recorder** — initialise _pending_chunk, etc.
    with mic:
        while True:
            # Capture audio block
            data = mic.record(numframes=block_size)
            if retro_enabled:
                retro_buf.append(data)
            if is_recording:
                live_buf.append(data)

            # Process commands non-blocking
            try:
                cmd = cmd_q.get_nowait()
            except Exception:
                cmd = None

            if cmd:
                action = cmd[0]

                if action == 'enable_retro':
                    retro_enabled = True
                    resp_q.put(('retro_enabled', True))

                elif action == 'disable_retro':
                    retro_enabled = False
                    retro_buf.clear()
                    resp_q.put(('retro_enabled', False))

                elif action == 'start':
                    print("recorder: start recording")
                    _, folder, rt = cmd
                    is_recording = True
                    live_buf = []
                    output_folder = folder
                    retro_time = rt
                    resp_q.put(('started', None))        # <-- envoi d’un ack

                elif action == 'stop' and is_recording:
                    print("recorder: stop recording")

                    # Stop recording
                    is_recording = False
                    resp_q.put(('stopped', None))     # <-- envoi d’un ack

                    # Combine retro + live
                    blocks = int(retro_time * sample_rate / block_size)
                    pre = list(retro_buf)[-blocks:] if retro_time > 0 else []
                    combined = pre + live_buf

                    # Build filename
                    ts = datetime.now().strftime("SMPL_%Y-%m-%d_%Hh%M.%S.wav")
                    path = os.path.join(output_folder, ts)
                    os.makedirs(output_folder, exist_ok=True)
                    # Write WAV
                    sf.write(path, np.vstack(combined), samplerate=sample_rate)
                    print(f"recorder: Audio saved in {path}.")

                    # Respond with result
                    resp_q.put(('done', path))

                    # Reset live buffer, keep retro buffer
                    live_buf = []
                elif action == 'shutdown':
                    break

            # Small sleep to reduce CPU
            time.sleep(0.001)

    # Clean exit
    resp_q.put(('shutdown_ack', None))
