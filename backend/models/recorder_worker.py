"""
------------------------------------------------------------------------------
recorder_worker.py — Capture audio loopback (architecture multi-thread)
------------------------------------------------------------------------------

Architecture
------------

    ┌─────────────────────────────────────────────────────────────┐
    │  Process isolé (mp.Process)                                 │
    │                                                             │
    │  ┌──────────────────┐   audio_ring   ┌────────────────────┐│
    │  │  _CaptureThread  │ ─────────────▶ │  Boucle principale ││
    │  │  (daemon)        │  deque         │  · retro buffer    ││
    │  │  mic.record()    │  lock-free     │  · live writer     ││
    │  │  en continu      │  (CPython GIL) │  · commandes       ││
    │  └──────────────────┘                └────────┬───────────┘│
    │                                               │            │
    │                                      ┌────────▼───────────┐│
    │                                      │  _ExportThread     ││
    │                                      │  (daemon)          ││
    │                                      │  finalise WAV      ││
    │                                      └────────────────────┘│
    └─────────────────────────────────────────────────────────────┘

Pourquoi ce découpage élimine les discontinuités
-------------------------------------------------
Avant : mic.record() bloquant ET traitement des commandes dans la même
boucle → si une commande prend quelques ms, l'appel suivant à record()
est en retard, le driver WASAPI a déjà rempli son ring buffer interne
→ frames perdues → SoundcardRuntimeWarning.

Après : _CaptureThread tourne en continu, ne fait RIEN d'autre que
record() + append dans audio_ring. Le driver WASAPI n'attend jamais.
La boucle principale lit audio_ring de façon asynchrone sans jamais
bloquer le thread de capture.

Interface externe (inchangée)
------------------------------
- cmd_q  : 'start', 'stop', 'enable_retro', 'disable_retro',
           'set_retro_time', 'set_device', 'set_sample_rate', 'shutdown'
- resp_q : 'started', 'stopped', 'done', 'done_error', 'retro_enabled',
           'retro_refill_state', 'shutdown_ack'
------------------------------------------------------------------------------
"""
from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
import warnings
from collections import deque

import numpy as np
import soundcard as sc
import soundfile as sf

from backend.models.sample import Sample
import logging

logger = logging.getLogger("recorder_worker")

# Filtre le warning soundcard en log propre (conservé pour visibilité)
try:
    from soundcard.mediafoundation import SoundcardRuntimeWarning as _SCW
except Exception:
    _SCW = None

if _SCW is not None:
    _orig_showwarning = warnings.showwarning

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        if category is _SCW:
            logger.warning("[audio] discontinuite signalée par le driver (buffer WASAPI).")
            return
        _orig_showwarning(message, category, filename, lineno, file, line)

    warnings.showwarning = _showwarning


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Taille max du ring buffer inter-threads (en blocs capturés).
# À 44 100 Hz / bloc 512 : 256 blocs ≈ 3 s — largement suffisant.
_AUDIO_RING_MAXBLOCKS = 256

# Durée de la pause active quand les deux queues sont vides (évite 100 % CPU).
_IDLE_SLEEP_S = 0.001  # 1 ms

# Backoff reconnexion device : initial, multiplicateur, maximum (secondes).
_RECONNECT_INIT_S = 0.5
_RECONNECT_MULT = 2.0
_RECONNECT_MAX_S = 5.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_unique_filename(folder: str, base: str, ext: str) -> str:
    """Retourne un nom de fichier qui n'existe pas encore dans *folder*."""
    name = f"{base}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, name)):
        name = f"{base}_{counter}{ext}"
        counter += 1
    return name


def _find_microphone(device_name: str | None):
    """Résolution du device loopback.

    Priorité :
    1. Correspondance exacte sur le nom donné.
    2. Loopback du speaker par défaut.
    3. Premier device loopback disponible.
    """
    mics = sc.all_microphones(include_loopback=True)

    if device_name:
        for m in mics:
            if m.name == device_name:
                return m

    try:
        speaker = sc.default_speaker()
        match = next((m for m in mics if speaker.name in m.name), None)
        if match:
            return match
    except Exception:
        pass

    if mics:
        return mics[0]

    raise RuntimeError("Aucun périphérique audio loopback disponible.")


# ---------------------------------------------------------------------------
# Thread de capture
# ---------------------------------------------------------------------------

class _CaptureThread(threading.Thread):
    """Thread dédié exclusivement à mic.record() → audio_ring.

    Responsabilité unique : capturer les blocs audio le plus vite possible
    et les déposer dans audio_ring. Aucune logique métier ici.

    Utilise collections.deque (maxlen) : si la boucle principale est en
    retard, les blocs les plus anciens sont écrasés silencieusement
    (comportement attendu pour la capture continue).
    """

    def __init__(
        self,
        mic_info,
        sample_rate: int,
        block_size: int,
        audio_ring: deque,
        stop_event: threading.Event,
        error_event: threading.Event,
    ):
        super().__init__(name="SampleRod-Capture", daemon=True)
        self._mic_info = mic_info
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._audio_ring = audio_ring
        self._stop = stop_event
        self._error = error_event

    def run(self) -> None:
        logger.info(
            "[capture] Démarrage sur '%s' @ %d Hz / bloc %d",
            self._mic_info.name, self._sample_rate, self._block_size,
        )
        try:
            with self._mic_info.recorder(samplerate=self._sample_rate) as mic:
                while not self._stop.is_set():
                    data = mic.record(numframes=self._block_size)
                    # append() est atomique sous le GIL CPython
                    self._audio_ring.append(data)
        except Exception as exc:
            if not self._stop.is_set():
                logger.error("[capture] Erreur inattendue : %s", exc)
                self._error.set()
        finally:
            logger.info("[capture] Thread terminé.")


# ---------------------------------------------------------------------------
# Thread d'export asynchrone
# ---------------------------------------------------------------------------

def _start_export_thread(
    export_q: queue.Queue,
    resp_q,
    block_size: int,
) -> threading.Thread:
    """Lance le thread qui finalise les fichiers WAV en arrière-plan."""

    def _loop() -> None:
        while True:
            job = export_q.get()
            if job is None:
                export_q.task_done()
                break

            path: str = job["path"]
            pre: list = job.get("pre", [])
            live_temp_path: str | None = job.get("live_temp_path")
            live_blocks_written: int = int(job.get("live_blocks_written", 0))
            out_sr: int = int(job["sample_rate"])
            sequential: bool = bool(job.get("sequential_with_previous", False))

            try:
                has_pre = bool(pre)
                has_live = (
                    live_temp_path is not None
                    and live_blocks_written > 0
                    and os.path.exists(live_temp_path)
                )

                if has_pre:
                    out_ch = pre[0].shape[1] if pre[0].ndim > 1 else 1
                elif has_live:
                    out_ch = sf.info(live_temp_path).channels
                else:
                    out_ch = 2

                with sf.SoundFile(
                    path, mode="w",
                    samplerate=out_sr,
                    channels=out_ch,
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
                                    always_2d=(out_ch > 1),
                                )
                                if not len(chunk):
                                    break
                                out.write(chunk)

                resp_q.put(("done", {
                    "path": path,
                    "sequential_with_previous": sequential,
                }))

            except Exception as exc:
                logger.exception("[export] Erreur WAV (%s) : %s", path, exc)
                try:
                    os.remove(path)
                except Exception:
                    pass
                resp_q.put(("done_error", str(exc)))

            finally:
                if live_temp_path and os.path.exists(live_temp_path):
                    try:
                        os.remove(live_temp_path)
                    except Exception:
                        pass
                export_q.task_done()

    t = threading.Thread(target=_loop, name="SampleRod-Export", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Worker principal
# ---------------------------------------------------------------------------

def recorder_worker(
    cmd_q,
    resp_q,
    pre_seconds: int,
    sample_rate: int,
    block_size: int,
    initial_device_name: str | None = None,
) -> None:
    """Point d'entrée du processus isolé de capture audio.

    Parameters
    ----------
    cmd_q               Queue de commandes (depuis RecorderService).
    resp_q              Queue de réponses (vers RecorderService).
    pre_seconds         Taille max du buffer rétro en secondes.
    sample_rate         Fréquence d'échantillonnage (Hz).
    block_size          Taille des blocs capturés (samples).
    initial_device_name Nom du device loopback à utiliser au démarrage.
    """
    logger.info("[worker] Démarrage (sample_rate=%d, block_size=%d).", sample_rate, block_size)

    # --- Thread d'export asynchrone -----------------------------------------
    export_q: queue.Queue = queue.Queue()
    export_thread = _start_export_thread(export_q, resp_q, block_size)

    # --- État de session -----------------------------------------------------
    retro_buf: deque = deque()
    live_writer: sf.SoundFile | None = None
    live_temp_path: str | None = None
    live_blocks_written: int = 0
    is_recording: bool = False
    retro_enabled: bool = False
    output_folder: str | None = None
    retro_time: float = 0.0
    retro_refill_active: bool = False
    retro_refill_target_blocks: int = 0
    current_take_sequential: bool = False

    selected_device_name: str | None = initial_device_name
    reconnect_delay: float = _RECONNECT_INIT_S

    def _maxlen() -> int:
        return max(1, int(pre_seconds * sample_rate / block_size))

    def _open_capture():
        """Démarre _CaptureThread sur le device courant."""
        mic_info = _find_microphone(selected_device_name)
        ring: deque = deque(maxlen=_AUDIO_RING_MAXBLOCKS)
        stop_evt = threading.Event()
        err_evt = threading.Event()
        ct = _CaptureThread(mic_info, sample_rate, block_size, ring, stop_evt, err_evt)
        ct.start()
        return ct, ring, stop_evt, err_evt, mic_info.name

    def _stop_capture(ct: _CaptureThread, stop_evt: threading.Event) -> None:
        stop_evt.set()
        ct.join(timeout=max(0.5, block_size / sample_rate * 4))
        if ct.is_alive():
            logger.warning("[worker] Thread de capture toujours actif après timeout.")

    def _close_live_writer() -> None:
        nonlocal live_writer
        if live_writer is not None:
            try:
                live_writer.close()
            except Exception:
                pass
            live_writer = None

    # =========================================================================
    # Boucle externe : reconnexion device
    # =========================================================================
    while True:
        try:
            capture_thread, audio_ring, stop_capture, capture_error, actual_name = _open_capture()
            selected_device_name = actual_name
            reconnect_delay = _RECONNECT_INIT_S
            logger.info("[worker] Capture active sur '%s'.", actual_name)
        except Exception as exc:
            logger.error("[worker] Ouverture device impossible : %s — retry dans %.1fs.", exc, reconnect_delay)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * _RECONNECT_MULT, _RECONNECT_MAX_S)
            continue

        # =====================================================================
        # Boucle interne : traitement audio + commandes
        # =====================================================================
        shutdown_requested = False
        reopen_device = False

        while True:

            # --- Erreur dans le thread de capture → reconnexion --------------
            if capture_error.is_set():
                logger.warning("[worker] Erreur de capture — reconnexion dans %.1fs.", reconnect_delay)
                _stop_capture(capture_thread, stop_capture)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * _RECONNECT_MULT, _RECONNECT_MAX_S)
                reopen_device = True
                break

            # --- Drainer le ring buffer audio --------------------------------
            had_audio = False
            while True:
                try:
                    data = audio_ring.popleft()
                except IndexError:
                    break  # ring vide

                had_audio = True

                if is_recording:
                    # Ouverture lazy du fichier temporaire au premier bloc
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
                            live_temp_path, mode="w",
                            samplerate=sample_rate,
                            channels=channels,
                            subtype="PCM_16",
                        )
                    live_writer.write(data)
                    live_blocks_written += 1

                elif retro_enabled:
                    retro_buf.append(data)
                    if (
                        retro_refill_active
                        and retro_refill_target_blocks > 0
                        and len(retro_buf) >= retro_refill_target_blocks
                    ):
                        retro_refill_active = False
                        retro_refill_target_blocks = 0
                        resp_q.put(("retro_refill_state", False))

            # --- Traitement des commandes ------------------------------------
            had_cmd = False
            try:
                cmd = cmd_q.get_nowait()
            except Exception:
                cmd = None

            if cmd:
                had_cmd = True
                action = cmd[0]

                # ── Arrêt propre ────────────────────────────────────────────
                if action == "shutdown":
                    shutdown_requested = True
                    break

                # ── Changement de device → redémarre la capture ─────────────
                elif action == "set_device":
                    new_name = cmd[1]
                    logger.info("[worker] set_device → '%s'.", new_name)
                    selected_device_name = new_name
                    _stop_capture(capture_thread, stop_capture)
                    reopen_device = True
                    break

                # ── Changement de sample rate → redémarre la capture ────────
                elif action == "set_sample_rate":
                    new_rate = int(cmd[1])
                    logger.info("[worker] set_sample_rate → %d Hz.", new_rate)
                    sample_rate = new_rate
                    retro_buf = deque(maxlen=_maxlen())  # invalide l'ancien buffer
                    _stop_capture(capture_thread, stop_capture)
                    reopen_device = True
                    break

                # ── Rétro-enregistrement ─────────────────────────────────────
                elif action == "enable_retro":
                    retro_buf = deque(maxlen=_maxlen())
                    retro_enabled = True
                    resp_q.put(("retro_enabled", True))

                elif action == "disable_retro":
                    retro_enabled = False
                    retro_buf.clear()
                    retro_refill_active = False
                    retro_refill_target_blocks = 0
                    current_take_sequential = False
                    resp_q.put(("retro_refill_state", False))
                    resp_q.put(("retro_enabled", False))

                # ── Démarrer l'enregistrement live ───────────────────────────
                elif action == "start":
                    _, folder, rt = cmd
                    requested_blocks = int(max(0, rt) * sample_rate / block_size)
                    current_take_sequential = retro_refill_active and requested_blocks > 0
                    is_recording = True
                    _close_live_writer()
                    live_temp_path = None
                    live_blocks_written = 0
                    output_folder = folder
                    retro_time = rt
                    resp_q.put(("started", {"sequential_with_previous": current_take_sequential}))

                # ── Arrêter l'enregistrement live ────────────────────────────
                elif action == "stop" and is_recording:
                    is_recording = False
                    resp_q.put(("stopped", None))
                    _close_live_writer()

                    blocks = int(retro_time * sample_rate / block_size)
                    pre = list(retro_buf)[-blocks:] if blocks > 0 else []
                    has_pre = bool(pre)
                    has_live = (
                        live_temp_path is not None
                        and live_blocks_written > 0
                        and os.path.exists(live_temp_path)
                    )

                    # Fenêtre de refill rétro
                    if retro_enabled and blocks > 0:
                        retro_refill_active = True
                        retro_refill_target_blocks = blocks
                        resp_q.put(("retro_refill_state", True))
                    else:
                        retro_refill_active = False
                        retro_refill_target_blocks = 0
                        resp_q.put(("retro_refill_state", False))

                    # Bloc silencieux minimal si vraiment rien capturé
                    if not has_pre and not has_live:
                        channels = 2  # stéréo par défaut
                        pre = [np.zeros((block_size, channels), dtype="float32")]
                        has_pre = True

                    # Génération du nom de fichier
                    next_id = Sample.get_next_id()
                    filename = _generate_unique_filename(
                        output_folder, f"SMPL_{next_id:04d}", ".wav"
                    )
                    path = os.path.join(output_folder, filename)
                    os.makedirs(output_folder, exist_ok=True)

                    # Délégation asynchrone de l'export
                    export_q.put({
                        "path": path,
                        "pre": pre,
                        "live_temp_path": live_temp_path if has_live else None,
                        "live_blocks_written": live_blocks_written,
                        "sample_rate": sample_rate,
                        "sequential_with_previous": current_take_sequential,
                    })

                    if not has_live and live_temp_path and os.path.exists(live_temp_path):
                        try:
                            os.remove(live_temp_path)
                        except Exception:
                            pass

                    live_temp_path = None
                    live_blocks_written = 0
                    retro_buf.clear()

                # ── Modifier la durée du buffer rétro à chaud ────────────────
                elif action == "set_retro_time":
                    new_pre = cmd[1]
                    pre_seconds = new_pre
                    retro_buf = deque(retro_buf, maxlen=_maxlen())
                    logger.info("[worker] set_retro_time → %ss.", new_pre)

            # --- Pause quand inactif (évite busy-wait à 100 % CPU) ----------
            if not had_audio and not had_cmd:
                time.sleep(_IDLE_SLEEP_S)

        # =====================================================================
        # Sortie de la boucle interne
        # =====================================================================
        if shutdown_requested:
            _stop_capture(capture_thread, stop_capture)
            break

        if not reopen_device:
            # Sortie inattendue → reconnexion
            logger.warning("[worker] Sortie inattendue de la boucle interne — reconnexion.")
            _stop_capture(capture_thread, stop_capture)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * _RECONNECT_MULT, _RECONNECT_MAX_S)

    # =========================================================================
    # Arrêt complet
    # =========================================================================
    _close_live_writer()
    try:
        export_q.put(None)
        export_thread.join(timeout=5.0)
    except Exception:
        pass
    resp_q.put(("shutdown_ack", None))
    logger.info("[worker] Arrêt complet.")
