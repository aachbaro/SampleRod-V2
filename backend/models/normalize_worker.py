# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Worker Qt dedie a la normalisation audio en arriere-plan.
# - Evite de bloquer l'UI pendant les traitements LUFS/peak.
#
# LIENS CLES
# - backend/services/sample_service.py
# - frontend/sample_gui/sample/sample_list_normalize.py
# -----------------------------------------------------------------------------
# backend/models/normalize_worker.py

# backend/models/normalize_worker.py

import os
import tempfile
import time
import numpy as np
import soundfile as sf
import logging
logger = logging.getLogger("normalize_worker")

from PySide6.QtCore import QThread, Signal

_PYLOUDNORM = None
_PYLOUDNORM_IMPORT_ATTEMPTED = False


def _get_pyloudnorm():
    global _PYLOUDNORM
    global _PYLOUDNORM_IMPORT_ATTEMPTED

    if _PYLOUDNORM_IMPORT_ATTEMPTED:
        return _PYLOUDNORM

    _PYLOUDNORM_IMPORT_ATTEMPTED = True
    try:
        import pyloudnorm as pyln
    except Exception as exc:
        logger.warning("[NormalizeWorker] pyloudnorm indisponible, fallback RMS: %s", exc)
        _PYLOUDNORM = None
        return None

    _PYLOUDNORM = pyln
    return _PYLOUDNORM


def _apply_rms_normalization(data: np.ndarray, target_db: float) -> np.ndarray:
    rms_lin = np.sqrt(np.mean(np.square(data), axis=0))
    rms_lin_max = np.max(rms_lin)
    if rms_lin_max <= 0:
        return data

    current_rms_db = 20.0 * np.log10(rms_lin_max)
    gain_db = target_db - current_rms_db
    gain_lin = 10 ** (gain_db / 20.0)
    normalized = data * gain_lin

    pic_after = np.max(np.abs(normalized))
    if pic_after > 0.999:
        normalized = normalized * (0.999 / pic_after)
    return normalized


class NormalizeWorker(QThread):
    """
    QThread chargé de normaliser un fichier audio sans bloquer l’interface.

    - Émet un signal startedNormalization(sample_id) au début du traitement.
    - Émet un signal finishedNormalization(sample_id) à la fin du traitement (fichier réécrit).
    """

    startedNormalization = Signal(int)
    finishedNormalization = Signal(int)
    normalizationFailed  = Signal(int, str)

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
            data = _apply_rms_normalization(data, self.target_db)

        elif self.mode == "lufs":
            pyln = _get_pyloudnorm()
            # Si pyloudnorm est disponible, on fait de la normalisation LUFS
            if pyln is not None:
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
                    data = _apply_rms_normalization(data, self.target_db)
            else:
                # pyloudnorm non installé : on passe en mode RMS
                data = _apply_rms_normalization(data, self.target_db)

        else:
            # Mode inconnu : on ne fait rien
            logger.info(f"[NormalizeWorker] Mode inconnu '{self.mode}' pour {self.file_path}")

        # 4) Réécriture du fichier WAV normalisé (écrase l'original).
#
        # Sur Windows, écrire directement sur le fichier original échoue si un
        # autre handle l'a ouvert (pygame mixer, WaveformLoaderThread, etc.).
        # Pattern sûr : écrire dans un fichier temp du même dossier, puis
        # os.replace() avec retries courts pour absorber les locks temporaires.
        folder = os.path.dirname(self.file_path)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix='.wav', dir=folder)
            os.close(fd)
            sf.write(tmp_path, data, sr)
        except Exception as e:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            err = f'Ecriture impossible : {e}'
            logger.error('[NormalizeWorker] %s', err)
            self.normalizationFailed.emit(self.sample_id, err)
            return

        # os.replace() peut echouer si la cible est encore verrouillee :
        # on retente jusqu'a 5 fois avec un delai croissant (50 -> 400 ms).
        replaced = False
        delay = 0.05
        for attempt in range(5):
            try:
                os.replace(tmp_path, self.file_path)
                replaced = True
                break
            except OSError:
                if attempt < 4:
                    time.sleep(delay)
                    delay *= 2

        if not replaced:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            err = 'Fichier verrouille par un autre processus (pygame / lecteur actif ?)'
            logger.error('[NormalizeWorker] %s', err)
            self.normalizationFailed.emit(self.sample_id, err)
            return

        logger.info('[NormalizeWorker] Normalisation terminee pour %s', self.file_path)
        self.finishedNormalization.emit(self.sample_id)
