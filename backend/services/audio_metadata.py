# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Boite a outils pour lire les INFORMATIONS d'un fichier audio sans le
#   modifier : duree, date de creation, volume moyen (RMS).
# - Deux strategies de lecture, essayees dans l'ordre :
#   1. soundfile (rapide, formats "ouverts" : wav, flac, ogg...) ;
#   2. ffmpeg en secours (formats proteges ou exotiques : mp3, m4a, wma...),
#     en decodant le son a la volee sans fichier intermediaire.
# - Definit aussi LA liste des extensions audio reconnues par l'application
#   (AUDIO_EXTENSIONS) et la maniere canonique d'ecrire un chemin de fichier.
#
# FONCTIONS (sommaire)
# - normalize_audio_path()       : chemin absolu et propre (comparable).
# - audio_path_key()             : cle de comparaison insensible a la casse.
# - is_audio_file()              : l'extension fait-elle partie des formats geres ?
# - collect_audio_file_metadata(): point d'entree principal -> AudioFileMetadata.
# - get_audio_duration()         : raccourci pour n'obtenir que la duree.
# - _probe_with_soundfile()      : lecture via soundfile (strategie 1).
# - _probe_with_fallback()       : lecture via ffmpeg (strategie 2).
# - _resolve_ffmpeg_executable() : trouve ffmpeg (via imageio_ffmpeg ou PATH).
#
# CLASSES
# - AudioMetadataError  : erreur levee quand un fichier est illisible.
# - AudioFileMetadata   : le resultat (chemin, nom, duree, date, volume RMS).
#
# LIENS CLES
# - backend/models/sample.py           : s'en sert a la creation d'un sample.
# - backend/models/integrity_worker.py : s'en sert pour verifier les durees.
# -----------------------------------------------------------------------------

from __future__ import annotations

import datetime as dt
import math
import os
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np
import soundfile as sf

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional runtime dependency
    imageio_ffmpeg = None


AUDIO_EXTENSIONS = {
    ".aif",
    ".aiff",
    ".au",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

# Parametres du decodage ffmpeg de secours :
# - on decode en mono 16 kHz (suffisant pour mesurer duree et volume,
#   beaucoup plus leger que la qualite d'origine) ;
# - lecture par blocs de 64 Ko pour ne jamais charger tout le fichier ;
# - CREATE_NO_WINDOW : ne pas faire clignoter de console sous Windows.
_FFMPEG_MONO_RATE = 16000
_FFMPEG_CHUNK_BYTES = 65536
_FFMPEG_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Cache de l'emplacement de ffmpeg : _FFMPEG_UNSET = pas encore cherche,
# None = cherche mais introuvable, str = chemin trouve.
_FFMPEG_UNSET = object()
_CACHED_FFMPEG_EXE: str | None | object = _FFMPEG_UNSET


class AudioMetadataError(RuntimeError):
    """Raised when an audio file cannot be probed or decoded."""


@dataclass(slots=True)
class AudioFileMetadata:
    """Fiche d'identite d'un fichier audio : chemin, nom, duree, date, volume."""

    path: str
    name: str
    duration: float
    created_at: dt.datetime
    rms_level: float | None = None


def normalize_audio_path(path: str) -> str:
    """Transforme un chemin en sa forme absolue et propre.

    Deux ecritures differentes du meme fichier ("./son.wav" et
    "C:\\dossier\\son.wav") deviennent identiques : indispensable pour les
    comparaisons et la colonne unique en base.
    """
    return os.path.normpath(os.path.abspath(path))


def audio_path_key(path: str) -> str:
    """Cle de comparaison de chemins, insensible aux majuscules (Windows)."""
    return os.path.normcase(normalize_audio_path(path))


def is_audio_file(path: str) -> bool:
    """Vrai si l'extension du fichier fait partie des formats audio geres."""
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def collect_audio_file_metadata(path: str, *, include_rms: bool = True) -> AudioFileMetadata:
    """Lit la fiche d'identite complete d'un fichier audio.

    Essaie d'abord soundfile (rapide), puis ffmpeg si le format n'est pas
    supporte. Leve AudioMetadataError si le fichier est introuvable, d'un
    format inconnu, ou illisible par les deux methodes.
    include_rms=False permet de sauter le calcul du volume moyen
    (plus rapide, car il oblige a decoder tout le fichier).
    """
    normalized_path = normalize_audio_path(path)
    if not os.path.isfile(normalized_path):
        raise AudioMetadataError(f"Fichier introuvable: {normalized_path}")
    if not is_audio_file(normalized_path):
        raise AudioMetadataError(f"Extension audio non prise en charge: {normalized_path}")

    # Strategie 1 : soundfile ; strategie 2 : ffmpeg ; sinon : erreur.
    duration, rms_level = _probe_with_soundfile(normalized_path, include_rms=include_rms)
    if duration is None:
        duration, rms_level = _probe_with_fallback(normalized_path, include_rms=include_rms)
    if duration is None:
        raise AudioMetadataError(f"Impossible de lire les metadonnees audio: {normalized_path}")

    created_at = dt.datetime.fromtimestamp(os.path.getctime(normalized_path))
    return AudioFileMetadata(
        path=normalized_path,
        name=os.path.splitext(os.path.basename(normalized_path))[0],
        duration=float(duration),
        created_at=created_at,
        rms_level=None if rms_level is None else float(rms_level),
    )


def get_audio_duration(path: str) -> float:
    """Raccourci : duree du fichier en secondes, sans calcul de volume."""
    return collect_audio_file_metadata(path, include_rms=False).duration


def _probe_with_soundfile(path: str, *, include_rms: bool) -> tuple[float | None, float | None]:
    """Strategie 1 : lire duree (et volume RMS) via la bibliotheque soundfile.

    La duree est instantanee (elle est inscrite dans l'en-tete du fichier).
    Le volume RMS, lui, demande de parcourir tout le son : on le fait par
    blocs de 65536 echantillons pour garder une memoire constante, en
    accumulant la somme des carres (RMS = racine de la moyenne des carres).
    Renvoie (None, None) si soundfile ne sait pas lire ce format.
    """
    try:
        with sf.SoundFile(path, mode="r") as audio_file:
            samplerate = int(audio_file.samplerate or 0)
            frames = int(audio_file.frames or 0)
            duration = float(frames / samplerate) if samplerate > 0 else 0.0
            if not include_rms:
                return duration, None

            sum_squares = 0.0
            sample_count = 0
            while True:
                chunk = audio_file.read(frames=65536, dtype="float32", always_2d=True)
                if chunk is None or chunk.size == 0:
                    break
                # Calculs en float64 pour eviter les pertes de precision
                # quand on additionne des millions de petits nombres.
                chunk64 = np.asarray(chunk, dtype=np.float64)
                sum_squares += float(np.square(chunk64).sum())
                sample_count += int(chunk64.size)

            rms_level = math.sqrt(sum_squares / sample_count) if sample_count > 0 else 0.0
            return duration, rms_level
    except Exception:
        return None, None


def _probe_with_fallback(path: str, *, include_rms: bool) -> tuple[float | None, float | None]:
    """Strategie 2 : decoder le fichier avec ffmpeg (formats mp3, m4a, wma...).

    On demande a ffmpeg de convertir le son en flux brut mono 16 kHz envoye
    directement dans un tuyau (pas de fichier intermediaire). En comptant
    les echantillons recus, on deduit la duree ; en accumulant leurs carres,
    le volume RMS. Renvoie (None, None) si ffmpeg est absent ou echoue.
    """
    ffmpeg_exe = _resolve_ffmpeg_executable()
    if not ffmpeg_exe:
        return None, None

    command = [
        ffmpeg_exe,
        "-nostdin",
        "-v",
        "error",
        "-i",
        path,
        "-vn",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "1",
        "-ar",
        str(_FFMPEG_MONO_RATE),
        "-",
    ]

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_FFMPEG_CREATE_FLAGS,
        )
    except Exception:
        return None, None

    sum_squares = 0.0
    sample_count = 0
    try:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(_FFMPEG_CHUNK_BYTES)
            if not chunk:
                break
            samples = np.frombuffer(chunk, dtype=np.float32)
            if samples.size == 0:
                continue
            sample_count += int(samples.size)
            if include_rms:
                samples64 = samples.astype(np.float64, copy=False)
                sum_squares += float(np.square(samples64).sum())

        if process.stderr is not None:
            process.stderr.read()
        returncode = process.wait()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        return None, None

    # Si ffmpeg s'est plaint mais qu'on a quand meme recu de l'audio,
    # on garde le resultat (fichiers legerement corrompus mais lisibles).
    if returncode != 0 and sample_count == 0:
        return None, None
    if sample_count <= 0:
        return None, None

    # Duree = nombre d'echantillons recus / frequence demandee (16 kHz).
    duration = float(sample_count / _FFMPEG_MONO_RATE)
    rms_level = math.sqrt(sum_squares / sample_count) if include_rms else None
    return duration, rms_level


def _resolve_ffmpeg_executable() -> str | None:
    """Trouve l'executable ffmpeg, une seule fois (resultat mis en cache).

    Ordre de recherche : la copie embarquee par le paquet imageio_ffmpeg,
    puis un ffmpeg installe sur la machine (PATH). None si introuvable.
    """
    global _CACHED_FFMPEG_EXE

    if _CACHED_FFMPEG_EXE is not _FFMPEG_UNSET:
        if isinstance(_CACHED_FFMPEG_EXE, str):
            return _CACHED_FFMPEG_EXE
        return None

    candidate = None
    if imageio_ffmpeg is not None:
        try:
            candidate = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            candidate = None
    if not candidate:
        candidate = shutil.which("ffmpeg")

    if candidate:
        _CACHED_FFMPEG_EXE = candidate
        return candidate

    _CACHED_FFMPEG_EXE = None
    return None
