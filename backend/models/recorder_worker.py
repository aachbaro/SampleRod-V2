# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Worker d'enregistrement audio execute dans un processus separe.
# - Capture l'audio (loopback) et gere le buffer retro (pre-record).
# - Recoit des commandes via une queue et renvoie des events via une autre.
#
# ENTREE / SORTIE
# - cmd_q (Queue): commandes entrantes depuis RecorderService
#   ('start', 'stop', 'enable_retro', 'disable_retro',
#    'set_retro_time', 'set_device', 'set_sample_rate', 'shutdown')
# - resp_q (Queue): reponses sortantes vers RecorderService
#   ('started', 'stopped', 'done', 'retro_enabled', 'shutdown_ack')
#
# FLUX GLOBAL
# RecorderService -> cmd_q -> recorder_worker (process) -> resp_q -> RecorderService
# Le worker tourne en boucle:
# - capture bloc par bloc
# - alimente un buffer retro (deque)
# - stocke le live dans un buffer temporaire pendant l'enregistrement
#
# RESPONSABILITES PRINCIPALES
# - Ouvrir le device audio (loopback) et reinitialiser si besoin.
# - Gerer la taille du buffer retro (pre_seconds + sample_rate + block_size).
# - Assembler "retro + live" au moment du stop puis ecrire le fichier WAV.
#
# NOTES
# - Le retro_time (selection courante) doit rester <= pre_seconds (taille max).
# - En cas de changement de sample_rate, on recalcule la taille du buffer.
# - Le worker ne touche pas a l'UI; il renvoie uniquement des events.
#
# IDEES / TODO
# - Ajouter une gestion d'erreurs plus fine (reconnexion device).
# - Supporter plusieurs canaux et selection canal.
# - Ajouter des niveaux (VU meter) pour monitoring temps reel.
# -----------------------------------------------------------------------------
# backend/models/recorder_worker.py

import soundcard as sc
import warnings
try:
    from soundcard.mediafoundation import SoundcardRuntimeWarning
except Exception:  # pragma: no cover - platform dependent
    SoundcardRuntimeWarning = None
import soundfile as sf
import numpy as np
import os
import time
import tempfile
from datetime import datetime
from collections import deque
from backend.models.sample import Sample
import logging
logger = logging.getLogger("recorder_worker")

# Custom warning formatting for dev: keep it spammy but cleaner in logs
if SoundcardRuntimeWarning is not None:
    _orig_showwarning = warnings.showwarning

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        if category is SoundcardRuntimeWarning:
            logger.warning(
                "[audio] discontinuite dans le flux d'enregistrement (buffer)."
            )
            return
        _orig_showwarning(message, category, filename, lineno, file, line)

    warnings.showwarning = _showwarning


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
                live_writer = None
                live_temp_path = None
                live_blocks_written = 0
                is_recording = False
                retro_enabled = False
                output_folder = None
                retro_time = 0

                # 2) Boucle interne : on lit par blocs successifs
                while True:
                    # --- Lecture bloquante d'un bloc audio de taille block_size ---
                    data = mic.record(numframes=block_size)

                    # --- Si recording actif, ecrit vers le fichier live temporaire.
                    # --- Sinon, si retro actif, stocke dans retro_buf.
                    if is_recording:
                        if live_writer is None:
                            channels = data.shape[1] if data.ndim > 1 else 1
                            os.makedirs(output_folder, exist_ok=True)
                            tmp = tempfile.NamedTemporaryFile(
                                prefix="._samplerod_live_",
                                suffix=".wav",
                                dir=output_folder,
                                delete=False,
                            )
                            live_temp_path = tmp.name
                            tmp.close()
                            live_writer = sf.SoundFile(
                                live_temp_path,
                                mode="w",
                                samplerate=sample_rate,
                                channels=channels,
                                subtype="PCM_16",
                            )
                        live_writer.write(data)
                        live_blocks_written += 1
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
                            if live_writer is not None:
                                live_writer.close()
                                live_writer = None
                            if live_temp_path and os.path.exists(live_temp_path):
                                try:
                                    os.remove(live_temp_path)
                                except Exception:
                                    pass
                            live_temp_path = None
                            live_blocks_written = 0
                            output_folder = folder
                            retro_time = rt
                            # Un retour immédiat pour signaler “started” au service
                            resp_q.put(('started', None))

                        # 2.d) Arrêter l’enregistrement live ---
                        elif action == 'stop' and is_recording:
                            is_recording = False
                            resp_q.put(('stopped', None))
                            if live_writer is not None:
                                live_writer.close()
                                live_writer = None

                            # On récupère les derniers blocs rétro (si retro_time > 0)
                            blocks = int(retro_time * sample_rate / block_size)
                            if retro_time > 0:
                                pre = list(retro_buf)[-blocks:]
                            else:
                                pre = []
                            # Presence audio
                            has_pre = len(pre) > 0
                            has_live = (
                                live_temp_path is not None
                                and live_blocks_written > 0
                                and os.path.exists(live_temp_path)
                            )

                            # Stop immediat sans donnees: ecrit un bloc silencieux minimal
                            if not has_pre and not has_live:
                                pre = [np.zeros_like(data)]
                                has_pre = True

                            # Generation d'un nom de fichier unique
                            next_id = Sample.get_next_id()
                            base = f"SMPL_{next_id:04d}"
                            filename = _generate_unique_filename(
                                output_folder, base, ".wav"
                            )
                            path = os.path.join(output_folder, filename)
                            os.makedirs(output_folder, exist_ok=True)

                            # Ecriture finale en streaming: retro (RAM) + live temp (disque)
                            if has_pre:
                                out_channels = pre[0].shape[1] if pre[0].ndim > 1 else 1
                            else:
                                out_channels = sf.info(live_temp_path).channels

                            with sf.SoundFile(
                                path,
                                mode="w",
                                samplerate=sample_rate,
                                channels=out_channels,
                                subtype="PCM_16",
                            ) as out:
                                for block in pre:
                                    out.write(block)

                                if has_live:
                                    with sf.SoundFile(live_temp_path, mode="r") as src:
                                        while True:
                                            chunk = src.read(
                                                frames=block_size * 16,
                                                dtype="float32",
                                                always_2d=(out_channels > 1),
                                            )
                                            if chunk is None or len(chunk) == 0:
                                                break
                                            out.write(chunk)

                            # On notifie le service principal que l'ecriture est finie
                            resp_q.put(('done', path))

                            # Cleanup du fichier live temporaire
                            if live_temp_path and os.path.exists(live_temp_path):
                                try:
                                    os.remove(live_temp_path)
                                except Exception:
                                    pass
                            live_temp_path = None
                            live_blocks_written = 0

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


