# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Thread de chargement et reduction de waveform en fond.
# - Retourne des donnees pretes a afficher sans bloquer l'UI.
#
# LIENS CLES
# - frontend/sample_gui/wave_form.py
# - frontend/sample_gui/waveform/waveform_renderer.py
# -----------------------------------------------------------------------------
# frontend/sample_gui/waveform/waveform_loader.py

from PyQt6.QtCore import QThread, pyqtSignal
import numpy as np
import librosa
import logging
logger = logging.getLogger("waveform_loader")

class WaveformLoaderThread(QThread):
    """Background thread loading a waveform from disk."""

    waveformReady = pyqtSignal(np.ndarray, int, float)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            # Charger la waveform en stéréo (mono=False)
            # y aura la forme (n_channels, n_samples) plutôt que (n_samples,)
            y, sr = librosa.load(self.path, sr=None, mono=False)
            dur = librosa.get_duration(y=y, sr=sr)
            self.waveformReady.emit(y, sr, dur)
        except Exception as e:
            logger.info(f"[WaveformLoaderThread] Erreur: {e}")
            self.waveformReady.emit(np.array([]), 0, 0.0)
