# backend/recorder_worker.py

import soundcard as sc
import soundfile as sf
import numpy as np
import os
import time
from datetime import datetime
from collections import deque
from backend.models.sample import Sample

def recorder_worker(cmd_q, resp_q, pre_seconds, sample_rate, block_size):
    """
    Worker process for audio capture and retro-recording.
    Listens on cmd_q for commands and writes WAV on 'stop'.
    """
    print("recorder_worker: Starting...")

    # Nombre de blocs pour le buffer rétrospectif
    maxlen = int(pre_seconds * sample_rate / block_size)

    while True:
        try:
            # 1) On récupère la liste de tous les "microphones" WASAPI (incluant loopback)
            mics = sc.all_microphones(include_loopback=True)

            # 2) On tente de prendre en priorité celui qui correspond au haut-parleur par défaut
            speaker = sc.default_speaker()
            mic_info = next(
                (m for m in mics if speaker.name in m.name),
                mics[0]  # fallback si on ne trouve pas
            )
            print(f"recorder_worker: Opening mic '{mic_info.name}'")

            # 3) On ouvre un contexte d'enregistrement qui se ferme proprement
            with mic_info.recorder(samplerate=sample_rate) as mic:
                retro_buf = deque(maxlen=maxlen)
                live_buf = []
                is_recording = False
                retro_enabled = False
                output_folder = None
                retro_time = 0

                while True:
                    # --- capture d'un bloc audio
                    data = mic.record(numframes=block_size)

                    # --- enregistrement live si demandé
                    if is_recording:
                        live_buf.append(data)
                    # --- gestion du buffer rétrospectif
                    elif retro_enabled:
                        retro_buf.append(data)
                    # --- traitement non bloquant des commandes
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
                            _, folder, rt = cmd
                            is_recording = True
                            live_buf = []
                            output_folder = folder
                            retro_time = rt
                            resp_q.put(('started', None))
                        elif action == 'stop' and is_recording:
                            is_recording = False
                            resp_q.put(('stopped', None))

                            # on compile rétro + live
                            blocks = int(retro_time * sample_rate / block_size)
                            pre = list(retro_buf)[-blocks:] if retro_time > 0 else []
                            combined = pre + live_buf

                            # écriture WAV
                            next_id = Sample.get_next_id()
                            filename = f"SMPL_{next_id:04d}.wav"
                            path = os.path.join(output_folder, filename)
                            os.makedirs(output_folder, exist_ok=True)
                            sf.write(path, np.vstack(combined), samplerate=sample_rate)
                            resp_q.put(('done', path))

                            live_buf = []
                        elif action == 'shutdown':
                            raise KeyboardInterrupt()

                    time.sleep(0.001)

        except KeyboardInterrupt:
            # shutdown demandé, on sort des deux boucles
            break

        except Exception as e:
            # en cas d'erreur (ex. déconnexion de périphérique), on ré-essaie
            print(f"recorder_worker: Error, reinitializing mic: {e}")
            time.sleep(0.5)
            continue

    resp_q.put(('shutdown_ack', None))
