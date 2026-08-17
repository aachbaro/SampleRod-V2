# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Worker de NORMALISATION audio : ramener le volume d'un fichier a un niveau
#   cible, sans deformer le son. Trois methodes disponibles :
#   * "peak" : on regarde le point le plus fort du son et on ajuste tout le
#     reste pour que ce pic atteigne la cible (rapide, basique) ;
#   * "rms"  : on ajuste le volume MOYEN du son (plus proche du ressenti) ;
#   * "lufs" : la mesure "broadcast" du volume percu (la plus fidele a
#     l'oreille humaine, utilisee par Spotify/YouTube), via pyloudnorm.
# - Tourne dans un fil separe (QThread) pour que l'interface reste fluide
#   pendant le calcul, et previent l'UI par signaux (debut / fin / echec).
#
# FONCTIONS ET CLASSE (sommaire)
# - _get_pyloudnorm()          : charge pyloudnorm une seule fois (optionnel).
# - _is_empty_audio()          : detecte un fichier audio vide.
# - _safe_peak_abs()           : pic maximal du signal, sans surprise (NaN...).
# - _apply_rms_normalization() : applique la normalisation par volume moyen.
# - NormalizeWorker (QThread)
#   - signaux : startedNormalization, finishedNormalization, normalizationFailed
#   - run() : lit le fichier, normalise selon le mode, reecrit le fichier
#             de facon sure (fichier temporaire + remplacement avec retries).
#
# LIENS CLES
# - backend/services/sample_service.py : cree et lance ce worker.
# - frontend/sample_gui/sample/sample_list_normalize.py : action cote UI.
# -----------------------------------------------------------------------------
# backend/models/normalize_worker.py

import os
import tempfile
import time
import numpy as np
import soundfile as sf
import logging
logger = logging.getLogger("normalize_worker")


def supports_in_place_normalization(path: str) -> bool:
    """Seul WAV est actuellement réécrit sans changer de conteneur."""
    return os.path.splitext(str(path or ""))[1].lower() == ".wav"

from PySide6.QtCore import QThread, Signal

# pyloudnorm (mesure LUFS) est une dependance optionnelle : on ne tente de la
# charger qu'une seule fois, et on memorise le resultat dans ces deux variables.
_PYLOUDNORM = None
_PYLOUDNORM_IMPORT_ATTEMPTED = False


def _get_pyloudnorm():
    """Charge la bibliotheque pyloudnorm (mesure LUFS) si elle est installee.

    Renvoie le module, ou None si indisponible — dans ce cas le worker se
    rabattra automatiquement sur la normalisation RMS. Le resultat est mis
    en cache : on ne paie le cout de l'import qu'une fois.
    """
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


def _is_empty_audio(data: np.ndarray) -> bool:
    """Vrai si le tableau audio ne contient aucun echantillon (fichier vide)."""
    array = np.asarray(data)
    return array.size == 0 or (array.ndim >= 1 and array.shape[0] == 0)


def _safe_peak_abs(data: np.ndarray) -> float:
    """Renvoie le pic maximal du signal (valeur absolue), de facon robuste.

    "Pic" = l'echantillon le plus fort du son, en valeur absolue (le signal
    audio oscille entre -1 et +1). Renvoie 0.0 pour un signal vide ou
    corrompu (valeurs infinies / NaN), plutot que de faire planter le calcul.
    """
    if _is_empty_audio(data):
        return 0.0
    peak = np.max(np.abs(data))
    if not np.isfinite(peak):
        return 0.0
    return float(peak)


def _apply_rms_normalization(data: np.ndarray, target_db: float) -> np.ndarray:
    """Ajuste le volume MOYEN (RMS) du signal pour atteindre target_db.

    Principe : on mesure le volume moyen actuel, on calcule l'ecart avec la
    cible, et on multiplie tout le signal par le gain correspondant.
    Garde-fous :
    - signal vide, silencieux ou corrompu -> renvoye tel quel ;
    - si le resultat depasse le maximum representable (1.0, ce qui ferait
      "craquer" le son), on le redescend juste sous la limite (0.999).
    """
    if _is_empty_audio(data):
        return data

    # Volume moyen par canal (racine de la moyenne des carres = RMS).
    rms_lin = np.sqrt(np.mean(np.square(data), axis=0))
    if np.size(rms_lin) == 0 or not np.all(np.isfinite(rms_lin)):
        return data

    # On se cale sur le canal le plus fort.
    rms_lin_max = float(np.max(rms_lin))
    if not np.isfinite(rms_lin_max) or rms_lin_max <= 0:
        return data

    # Conversion en decibels, calcul de l'ecart a la cible, puis application
    # du gain correspondant a tout le signal.
    current_rms_db = 20.0 * np.log10(rms_lin_max)
    gain_db = target_db - current_rms_db
    gain_lin = 10 ** (gain_db / 20.0)
    normalized = data * gain_lin

    # Anti-saturation : jamais au-dela de 0.999.
    pic_after = _safe_peak_abs(normalized)
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

        if not supports_in_place_normalization(self.file_path):
            message = (
                "Normalisation ignorée : la réécriture sûre est actuellement "
                "limitée aux fichiers WAV."
            )
            logger.warning("[NormalizeWorker] %s (%s)", message, self.file_path)
            self.normalizationFailed.emit(self.sample_id, message)
            return

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
        data = np.nan_to_num(data, copy=False, nan=0.0, posinf=0.0, neginf=0.0)

        if _is_empty_audio(data):
            message = "Fichier audio vide: normalisation ignoree."
            logger.warning("[NormalizeWorker] %s (%s)", message, self.file_path)
            self.normalizationFailed.emit(self.sample_id, message)
            return

        # 3) Application de la normalisation
        if self.mode == "peak":
            # Normalisation par pic (peak) : on amène le max absolu à target_db dBFS
            # target_db en dBFS : ex. -1 dB → lin_target = 10^(−1/20) ≈ 0.891
            pic = _safe_peak_abs(data)
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
                    max_after = _safe_peak_abs(data)
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
