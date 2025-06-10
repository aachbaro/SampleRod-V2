from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtCore import pyqtSignal

from backend.models.AppContext import AppContext
from backend.models.sample import Sample
from frontend.sample_gui.wave_form import WaveformWidget


class WaveformHandler:
    """Gère l'ouverture/fermeture du widget d'édition de forme d'onde."""

    waveformSaved = pyqtSignal(str)

    def __init__(self, sample: Sample, app_context: AppContext, playback_widget, parent_layout: QHBoxLayout):
        self.sample = sample
        self.app_context = app_context
        self.playback_widget = playback_widget
        self.layout = parent_layout
        self.wave_edition_widget = None
        self.show_waveform = False

    def toggle_waveform(self):
        self.show_waveform = not self.show_waveform

        if self.show_waveform:
            # Masquer la zone de lecture
            self.playback_widget.hide()
            try:
                self.app_context.audio_player.clear_audio()
            except Exception:
                pass

            self.wave_edition_widget = WaveformWidget(self.sample.path, self.app_context)
            self.wave_edition_widget.waveformSaved.connect(self.waveformSaved)
            self.layout.addWidget(self.wave_edition_widget)
        else:
            self.playback_widget.show()
            if self.wave_edition_widget:
                try:
                    self.wave_edition_widget.stop_audio()
                except Exception:
                    pass
                try:
                    self.wave_edition_widget.timer.stop()
                except Exception:
                    pass
                self.layout.removeWidget(self.wave_edition_widget)
                self.wave_edition_widget.deleteLater()
                self.wave_edition_widget = None

    def with_wave(self, fn):
        if self.wave_edition_widget:
            fn(self.wave_edition_widget)

