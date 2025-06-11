from PyQt6.QtCore import QThread, pyqtSignal
import numpy as np
import librosa

class WaveformLoaderThread(QThread):
    """Background thread loading a waveform from disk."""

    waveformReady = pyqtSignal(np.ndarray, int, float)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            # Load the waveform without altering the original amplitude so
            # that playback and saving keep the exact same data as on disk.
            y, sr = librosa.load(self.path, sr=None)
            dur = librosa.get_duration(y=y, sr=sr)
            self.waveformReady.emit(y, sr, dur)
        except Exception as e:
            print(f"[WaveformLoaderThread] Erreur: {e}")
            self.waveformReady.emit(np.array([]), 0, 0.0)
