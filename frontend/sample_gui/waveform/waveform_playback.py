# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Controleur audio pour la lecture de la waveform.
# - Isole la gestion du stream sounddevice et le suivi de la tete de lecture.
# - Est instancie par WaveformWidget pour separer UI et playback.
#
# CE QUI EST COUVERT
# - Play / pause / resume / stop / reset.
# - Lecture d'une selection (play_start / play_end).
# - Boucle (loop) sur la region selectionnee.
# - Mise a jour de la tete de lecture via timer + callback audio.
#
# RESPONSABILITES TECHNIQUES
# - Creer et piloter un OutputStream sounddevice.
# - Copier les buffers audio (mono/stereo) vers la sortie.
# - Gerer la fin de lecture et l'etat is_playing.
# - Emmettre positionUpdated pour synchroniser le visuel.
#
# NON-OBJECTIFS
# - Aucune logique d'interactions souris/clavier.
# - Pas de rendu graphique (delegue au widget).
#
# DEPENDANCES
# - sounddevice (stream audio)
# - numpy (buffering, slicing)
# - qtawesome (mise a jour de l'icone loop)
#
# IDEES / TODO
# - Fade in/out pour eviter les clicks en debut/fin.
# - Crossfade propre en mode loop.
# - Choix du device audio / gestion d'erreurs robuste.
# - Monitoring du niveau (VU / peak) pendant lecture.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import numpy as np
import sounddevice as sd
import qtawesome as qta

logger = logging.getLogger("waveform_playback")


class WaveformPlaybackController:
    def __init__(self, widget):
        self.widget = widget

    def play_from_start(self):
        self.stop_audio()
        # Respect current selection
        t = self.widget.play_start
        self.play_audio(t)

    def pause_or_resume(self):
        """Toggle pause/reprise."""
        w = self.widget
        if w.is_playing:
            if w.stream:
                w.stream.stop()
            w.timer.stop()
            w.is_playing = False
        else:
            end_pos = w.play_end if w.play_end > w.play_start else w.duration
            if w.current_time >= end_pos:
                w.current_time = w.play_start
            self.play_audio(w.current_time)

    def play_audio(self, start_time: float = 0.0):
        w = self.widget
        if w.waveform_data is None:
            return

        # position de depart en echantillons
        w.start_sample = int(start_time * w.sample_rate)
        w.current_time = start_time
        w.is_playing = True
        w.timer.start(50)

        def callback(outdata, frames, time_info, status):
            if status.output_underflow:
                logger.warning("Underflow audio detecte")

            region_start = int(w.play_start * w.sample_rate)
            region_end = int(w.play_end * w.sample_rate) if w.play_end > w.play_start else len(w.waveform_data)

            if region_end <= region_start:
                outdata.fill(0)
                w.is_playing = False
                raise sd.CallbackStop()

            st = w.start_sample

            if w.loop_enabled:
                length = region_end - region_start
                idxs = (np.arange(st, st + frames) - region_start) % length + region_start
                chunk = w.waveform_data[idxs]

                if chunk.ndim == 1:
                    chunk = np.repeat(chunk[:, np.newaxis], outdata.shape[1], axis=1)

                outdata[:chunk.shape[0], :] = chunk
                w.start_sample = region_start + ((st + frames - region_start) % length)
                w.current_time = w.start_sample / w.sample_rate
                w.positionUpdated.emit(w.current_time)
                return

            remaining = region_end - st
            if remaining <= 0:
                raise sd.CallbackStop()

            n = min(frames, remaining)
            segment = w.waveform_data[st:st + n]
            if segment.ndim == 1:
                segment = np.repeat(segment[:, np.newaxis], outdata.shape[1], axis=1)
            outdata[:n, :] = segment

            w.start_sample = st + n
            w.current_time = w.start_sample / w.sample_rate
            w.positionUpdated.emit(w.current_time)

            if n < frames:
                raise sd.CallbackStop()

            if not w.loop_enabled and w.start_sample >= region_end:
                w.is_playing = False
                raise sd.CallbackStop()

        n_channels = 2 if getattr(w, "is_stereo", False) else 1
        w.stream = sd.OutputStream(
            samplerate=w.sample_rate,
            channels=n_channels,
            dtype="float32",
            blocksize=1024,
            latency="low",
            callback=callback,
        )
        w.stream.start()

    def pause_audio(self):
        w = self.widget
        if w.stream and w.is_playing:
            w.stream.stop()
            w.timer.stop()
            w.is_playing = False
        elif not w.is_playing:
            self.play_audio(w.current_time)

    def stop_and_reset(self):
        w = self.widget
        self.stop_audio()
        w.current_time = w.play_start
        w.read_head.setPos(w.play_start)

    def stop_audio(self):
        w = self.widget
        if w.stream:
            try:
                if getattr(w.stream, "active", False):
                    w.stream.stop()
            except Exception as e:
                logger.info(f"[WaveformWidget] Erreur stop: {e}")
            try:
                w.stream.close()
            except Exception as e:
                logger.info(f"[WaveformWidget] Erreur close: {e}")
            finally:
                w.stream = None
        w.is_playing = False
        w.stop_timer_signal.emit()

    def update_read_head(self):
        w = self.widget
        if w.is_playing:
            w.read_head.setPos(w.current_time)
        else:
            self.stop_audio()
            w.current_time = w.play_start
            w.read_head.setPos(w.play_start)

    def toggle_loop(self, checked: bool):
        """Active/desactive le mode boucle."""
        w = self.widget
        w.loop_enabled = checked
        color = "lightgreen" if checked else "lightgray"
        w.loop_button.setIcon(qta.icon("fa5s.sync", color=color))
