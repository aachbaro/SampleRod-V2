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
            y, sr = librosa.load(self.path, sr=None)
            if y.size and np.max(np.abs(y)) > 0:
                y = y / np.max(np.abs(y))
            else:
                y = np.zeros_like(y)
            dur = librosa.get_duration(y=y, sr=sr)
            self.waveformReady.emit(y, sr, dur)
        except Exception as e:
            print(f"[WaveformLoaderThread] Erreur: {e}")
            self.waveformReady.emit(np.array([]), 0, 0.0)
