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

from PySide6.QtCore import QThread, Signal
import numpy as np
import soundfile as sf
import logging
logger = logging.getLogger("waveform_loader")


class WaveformLoaderThread(QThread):
    """Thread de chargement de waveform en arrière-plan.

    Utilise soundfile directement (libsndfile, pur C, pas de COM/MF) pour
    éviter les warnings Qt de cross-thread créés par audioread/MediaFoundation
    quand librosa utilise son backend Windows.
    """

    waveformReady = Signal(np.ndarray, int, float)

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        # deleteLater() à la fin pour que Qt détruise l'objet dans le bon thread
        self.finished.connect(self.deleteLater)

    def run(self):
        """Charge le fichier audio et emet waveformReady(y, sr, dur)."""
        try:
            # soundfile retourne (frames, channels) ou (frames,) en mono
            y, sr = sf.read(self.path, dtype="float32", always_2d=True)
            # On transpose en (channels, frames) pour rester compatible avec
            # l'ancien format librosa (n_channels, n_samples)
            y = y.T
            dur = y.shape[-1] / sr if sr > 0 else 0.0
            self.waveformReady.emit(y, sr, dur)
        except Exception as e:
            logger.warning("[WaveformLoaderThread] Erreur chargement '%s': %s", self.path, e)
            self.waveformReady.emit(np.array([]), 0, 0.0)
