# backend/models/normalize_worker.py

import os
import numpy as np
import soundfile as sf
import logging
logger = logging.getLogger("normalize_worker")

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import pyloudnorm as pyln
    _PYLOUDNORM_AVAILABLE = True
except ImportError:
    _PYLOUDNORM_AVAILABLE = False


class NormalizeWorker(QThread):
    """
    QThread chargé de normaliser un fichier audio sans bloquer l’interface.

    - Émet un signal startedNormalization(sample_id) au début du traitement.
    - Émet un signal finishedNormalization(sample_id) à la fin du traitement (fichier réécrit).
    """

    startedNormalization = pyqtSignal(int)
    finishedNormalization = pyqtSignal(int)
    normalizationFailed  = pyqtSignal(int, str)

    def __init__(self, sample_id: int, file_path: str,
                 mode: str = "lufs", target_db: float = -16.0):
        """
        :param sample_id: Identifiant du Sample (pour notifier UI)
        :param file_path: Chemin du fichier WAV à normaliser
        :param mode:      "peak", "rms" ou "lufs"
        :param target_db: Valeur cible en dB
                           - si mode=="peak", c’est un dBFS (ex. -1.0)
                           - si mode=="rms", c’est un RMS en dBFS (ex. -18.0)
                           - si mode=="lufs", c’est une cible LUFS (ex. -16.0)
        """
        super().__init__()
        self.sample_id = sample_id
        self.file_path = file_path
        self.mode = mode.lower()
        self.target_db = target_db

    def run(self):
        """
        Méthode invoquée dans le thread parallèle :
        1) Signale le démarrage
        2) Charge le fichier audio
        3) Applique la normalisation selon self.mode
        4) Écrase le fichier avec le résultat
        5) Signale la fin
        """
        logger.info(f"[NormalizeWorker] Démarrage de la normalisation pour {self.file_path} (mode={self.mode}, target_db={self.target_db})")
        # 1) Envoi du signal de démarrage
        self.startedNormalization.emit(self.sample_id)

        # 2) Chargement du fichier WAV (float32) ; shape = (n_samples,) ou (n_samples, n_channels)
        try:
            data, sr = sf.read(self.file_path, dtype="float32")
        except Exception as e:
            logger.info(f"[NormalizeWorker] Erreur lors de la lecture de {self.file_path}: {e}")
            # On émet tout de même le signal de fin pour éviter que la carte UI reste bloquée
            self.finishedNormalization.emit(self.sample_id)
            return

        # Si mono (1D), on force en 2D pour un traitement uniforme
        if data.ndim == 1:
            data = data[:, np.newaxis]  # (n_samples, 1)

        # 3) Application de la normalisation
        if self.mode == "peak":
            # Normalisation par pic (peak) : on amène le max absolu à target_db dBFS
            # target_db en dBFS : ex. -1 dB → lin_target = 10^(−1/20) ≈ 0.891
            pic = np.max(np.abs(data))
            if pic > 0:
                lin_target = 10 ** (self.target_db / 20.0)
                gain = lin_target / pic
                data = data * gain
            # Si pic == 0, fichier silencieux : on laisse tel quel

        elif self.mode == "rms":
            # Normalisation RMS : on calcule le niveau RMS actuel en dBFS
            # puis on applique un gain pour atteindre target_db (ex. -18 dBFS)
            rms_lin = np.sqrt(np.mean(np.square(data), axis=0))
            # rms_lin est un vecteur par canal ; on prend le maximum pour garder le même gain
            rms_lin_max = np.max(rms_lin)
            if rms_lin_max > 0:
                current_rms_db = 20.0 * np.log10(rms_lin_max)
                gain_db = self.target_db - current_rms_db
                gain_lin = 10 ** (gain_db / 20.0)
                data = data * gain_lin
                # Vérification du pic après normalisation RMS pour éviter clipping
                pic_after = np.max(np.abs(data))
                if pic_after > 0.999:
                    data = data * (0.999 / pic_after)
            # Sinon, signal muet : on laisse tel quel

        elif self.mode == "lufs":
            # Si pyloudnorm est disponible, on fait de la normalisation LUFS
            if _PYLOUDNORM_AVAILABLE:
                try:
                    # 1) mesure du loudness
                    meter = pyln.Meter(sr)
                    loudness = meter.integrated_loudness(data.astype("float64"))

                    # 2) normalisation LUFS « brute »
                    normalized = pyln.normalize.loudness(
                        data.astype("float64"), loudness, self.target_db
                    ).astype("float32")

                    # 3) headroom (−0,5 dB) 
                    headroom_factor = 10 ** (-0.5 / 20.0)
                    data = normalized * headroom_factor

                    # 4) si malgré le headroom on dépasse 1.0, on recalcule au plus juste
                    max_after = np.max(np.abs(data))
                    if max_after >= 1.0:
                        data = data * (0.999 / max_after)

                except Exception as e:
                    logger.info(f"[NormalizeWorker] Erreur LUFS pour {self.file_path}: {e}")
                    # Fallback en RMS
                    rms_lin = np.sqrt(np.mean(np.square(data), axis=0))
                    rms_lin_max = np.max(rms_lin)
                    if rms_lin_max > 0:
                        current_rms_db = 20.0 * np.log10(rms_lin_max)
                        gain_db = self.target_db - current_rms_db
                        gain_lin = 10 ** (gain_db / 20.0)
                        data = data * gain_lin
                        pic_after = np.max(np.abs(data))
                        if pic_after > 0.999:
                            data = data * (0.999 / pic_after)
            else:
                # pyloudnorm non installé : on passe en mode RMS
                rms_lin = np.sqrt(np.mean(np.square(data), axis=0))
                rms_lin_max = np.max(rms_lin)
                if rms_lin_max > 0:
                    current_rms_db = 20.0 * np.log10(rms_lin_max)
                    gain_db = self.target_db - current_rms_db
                    gain_lin = 10 ** (gain_db / 20.0)
                    data = data * gain_lin
                    pic_after = np.max(np.abs(data))
                    if pic_after > 0.999:
                        data = data * (0.999 / pic_after)

        else:
            # Mode inconnu : on ne fait rien
            logger.info(f"[NormalizeWorker] Mode inconnu '{self.mode}' pour {self.file_path}")

        # 4) Réécriture du fichier WAV normalisé (écrase l’original)
        try:
            sf.write(self.file_path, data, sr)
            logger.info(f"[NormalizeWorker] Normalisation terminée pour {self.file_path}")
            self.finishedNormalization.emit(self.sample_id)
        except Exception as e:
            err = f"Écriture impossible : {e}"
            logger.info(f"[NormalizeWorker] {err}")
            self.normalizationFailed.emit(self.sample_id, err)

        # 5) Signal de fin de normalisation
        self.finishedNormalization.emit(self.sample_id)