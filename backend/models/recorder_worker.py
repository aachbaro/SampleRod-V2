# backend/recorder_worker.py

import soundcard as sc
import soundfile as sf
import numpy as np
import os
import time
from datetime import datetime
from collections import deque
from backend.models.sample import Sample
import logging
logger = logging.getLogger("recorder_worker")


def _generate_unique_filename(folder: str, base_name: str, extension: str) -> str:
    """Return a filename that does not yet exist in *folder*.

    If ``base_name`` already exists, append ``_1``, ``_2``… before the
    extension until an unused name is found.
    """
    filename = f"{base_name}{extension}"
    counter = 1
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"{base_name}_{counter}{extension}"
        counter += 1
    return filename


def recorder_worker(cmd_q, resp_q, pre_seconds, sample_rate, block_size, initial_device_name=None):
    """
    Worker process pour la capture audio et le rétro-enregistrement.
    - cmd_q  : queue pour recevoir des commandes ('start', 'stop', 'enable_retro', 'set_device', etc.)
    - resp_q : queue pour envoyer des notifications ('started', 'stopped', 'done', 'retro_enabled', etc.)
    - pre_seconds  : nombre de secondes max pour buffer rétrospectif
    - sample_rate  : fréquence d'échantillonnage (Hz)
    - block_size   : nombre d'échantillons lus à chaque appel à mic.record()
    - initial_device_name : nom du device loopback à forcer (optionnel)
    """

    logger.info("recorder_worker: Démarrage du worker…")

    # ------- Fonction utilitaire interne pour (re)chercher et (re)ouvrir un microphone ----------
    def open_microphone(device_name):
        """
        Recherche dans la liste des microphones (boucle incluse) celui dont le nom correspond
        à device_name, sinon retombe sur le micro “par défaut” (loopback ou premier dispo).
        Puis ouvre le contexte .recorder(samplerate=sample_rate).
        """
        mics = sc.all_microphones(include_loopback=True)
        mic_info = None

        if device_name:
            # On cherche un micro dont le nom matche
            for m in mics:
                if m.name == device_name:
                    mic_info = m
                    break

        if mic_info is None:
            # Si non trouvé, on prend le micro loopback par défaut
            speaker = sc.default_speaker()
            mic_info = next((m for m in mics if speaker.name in m.name), None)

        # Si toujours rien, on prend le premier de la liste
        if mic_info is None and mics:
            mic_info = mics[0]

        if mic_info is None:
            raise RuntimeError("Aucun périphérique audio disponible pour l'enregistrement !")

        logger.info(f"recorder_worker: Ouverture du périphérique '{mic_info.name}'")
        # Ouvre et retourne l'objet Recorder
        return mic_info.recorder(samplerate=sample_rate), mic_info.name


    # ---------- Calcul du nombre de blocs pour le buffer rétrospectif ---------------
    maxlen = int(pre_seconds * sample_rate / block_size)

    # On stocke le nom du device souhaité (éventuellement modifié par set_device)
    selected_device_name = initial_device_name

    # Boucle “externe” pour gérer la réouverture du device en cas de set_device
    while True:
        try:
            # ---------------------------------------------------------------------------
            # 1) On (re)ouvre le device une première fois (ou après set_device)
            #    On récupère ici un contexte Recorder “blocant” sur mic.record(...)
            # ---------------------------------------------------------------------------
            recorder_obj, actual_name = open_microphone(selected_device_name)
            with recorder_obj as mic:
                selected_device_name = actual_name

                # Buffers pour rétro et live
                retro_buf = deque(maxlen=maxlen)
                live_buf = []
                is_recording = False
                retro_enabled = False
                output_folder = None
                retro_time = 0

                # 2) Boucle interne : on lit par blocs successifs
                while True:
                    # --- Lecture bloquante d'un bloc audio de taille block_size ---
                    data = mic.record(numframes=block_size)

                    # --- Si recording actif, stocke dans live_buf, sinon si retro activé, dans retro_buf ---
                    if is_recording:
                        live_buf.append(data)
                    elif retro_enabled:
                        retro_buf.append(data)

                    # --- Vérification “immédiate” des commandes sans pause artificielle ---
                    cmd = None
                    try:
                        cmd = cmd_q.get_nowait()
                    except Exception:
                        cmd = None

                    if cmd:
                        action = cmd[0]

                        # 2.a) Changer de device (on sort pour réinitialiser le with + open) ---
                        if action == 'set_device':
                            new_name = cmd[1]
                            logger.info(f"recorder_worker: Changement de device demandé → '{new_name}'")
                            selected_device_name = new_name
                            # On interrompt la boucle interne pour rouvrir le nouveau mic
                            break

                        # 2.b) Changer de sample rate → sortir pour ré-ouvrir
                        elif action == 'set_sample_rate':
                            new_rate = cmd[1]
                            logger.info(f"recorder_worker: Commande set_sample_rate → {new_rate} Hz")
                            # On met à jour sample_rate et maxlen
                            sample_rate = new_rate
                            maxlen = int(pre_seconds * sample_rate / block_size)
                            # On interrompt la boucle interne pour qu’on remonte dans la while externe
                            break

                        # 2.b) (Dé)activer rétro-enregistrement ---
                        elif action == 'enable_retro':
                            retro_enabled = True
                            resp_q.put(('retro_enabled', True))
                        elif action == 'disable_retro':
                            retro_enabled = False
                            retro_buf.clear()
                            resp_q.put(('retro_enabled', False))

                        # 2.c) Démarrer l’enregistrement live ---
                        elif action == 'start':
                            _, folder, rt = cmd
                            is_recording = True
                            live_buf = []
                            output_folder = folder
                            retro_time = rt
                            # Un retour immédiat pour signaler “started” au service
                            resp_q.put(('started', None))

                        # 2.d) Arrêter l’enregistrement live ---
                        elif action == 'stop' and is_recording:
                            is_recording = False
                            resp_q.put(('stopped', None))

                            # On récupère les derniers blocs rétro (si retro_time > 0)
                            blocks = int(retro_time * sample_rate / block_size)
                            if retro_time > 0:
                                pre = list(retro_buf)[-blocks:]
                            else:
                                pre = []

                            # Concaténation des blocs rétro + live
                            combined = pre + live_buf

                            # Génération d'un nom de fichier unique
                            next_id = Sample.get_next_id()
                            base = f"SMPL_{next_id:04d}"
                            filename = _generate_unique_filename(
                                output_folder, base, ".wav"
                            )
                            path = os.path.join(output_folder, filename)
                            os.makedirs(output_folder, exist_ok=True)

                            # Écriture du fichier WAV sur disque (toutes canaux empilés verticalement)
                            sf.write(path, np.vstack(combined), samplerate=sample_rate)

                            # On notifie le service principal que l'écriture est finie
                            resp_q.put(('done', path))

                            # On vide live_buf pour la prochaine session
                            live_buf = []

                        # 2.e) Modifier la durée du buffer rétrospectif à chaud ---
                        elif action == 'set_retro_time':
                            new_pre = cmd[1]
                            maxlen = int(new_pre * sample_rate / block_size)
                            retro_buf = deque(retro_buf, maxlen=maxlen)
                            logger.info(f"recorder_worker: Nouveau buffer rétro → {new_pre}s")

                        # 2.f) (Autres commandes éventuelles) ...
                        #     Par exemple : pause, ajustement du sample_rate, etc.

                    # (!) **Aucun time.sleep ici** : 
                    #     on laisse le blocage sur mic.record() gérer la temporisation  
                    #     et on relit immédiatement si aucune commande n’est disponible.

                # Fin du bloc “with mic”, si on sort c’est pour faire un set_device  
                # (on break), et on revient au while True externe pour rouvrir.
                # -----------------------------------------------------------------------

        except KeyboardInterrupt:
            # Si on reçoit shutdown (via un KeyboardInterrupt), on sort proprement
            break

        except Exception as e:
            # En cas d’erreur (déconnexion du device, exception Soundcard, etc.), on réessaie
            logger.info(f"recorder_worker: Erreur (réinitialisation du microphone) : {e}")
            time.sleep(0.5)
            # On retourne en début de while True pour retenter l’ouverture du mic
            continue

    # En sortie des deux boucles, on signale au service principal la fin
    resp_q.put(('shutdown_ack', None))
    logger.info("recorder_worker: Fermeture complète du worker.")
