# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere l'affichage du waveform editor a l'interieur d'une SampleCard.
# - S'occupe du cycle de vie (creation, ajout au layout, nettoyage).
# - Centralise la logique de bascule UI (masquer/afficher playback).
# -----------------------------------------------------------------------------

from __future__ import annotations

from frontend.sample_gui.wave_form import WaveformWidget


class SampleCardWaveform:
    def __init__(self, card):
        self.card = card

    def toggle(self):
        c = self.card
        c.showWaveform = not c.showWaveform

        if c.showWaveform:
            self._hide_playback()
            try:
                c.app_context.audio_player.clear_audio()
            except Exception:
                pass

            c.wave_edition_widget = WaveformWidget(c.sample.path, c.app_context)
            c.wave_edition_widget.waveformSaved.connect(c.newSampleSaved)
            c.waveform_layout.addWidget(c.wave_edition_widget)
        else:
            self._show_playback()
            self._cleanup_waveform()

    def _hide_playback(self):
        c = self.card
        c.play_button.setVisible(False)
        c.playback_slider.setVisible(False)
        c.time_label.setVisible(False)

    def _show_playback(self):
        c = self.card
        c.play_button.setVisible(True)
        c.playback_slider.setVisible(True)
        c.time_label.setVisible(True)

    def _cleanup_waveform(self):
        c = self.card
        if not c.wave_edition_widget:
            return

        try:
            c.wave_edition_widget.stop_audio()
        except Exception:
            pass

        try:
            c.wave_edition_widget.timer.stop()
        except Exception:
            pass

        c.waveform_layout.removeWidget(c.wave_edition_widget)
        c.wave_edition_widget.deleteLater()
        c.wave_edition_widget = None
