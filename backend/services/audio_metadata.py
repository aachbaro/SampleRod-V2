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

_FFMPEG_MONO_RATE = 16000
_FFMPEG_CHUNK_BYTES = 65536
_FFMPEG_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_FFMPEG_UNSET = object()
_CACHED_FFMPEG_EXE: str | None | object = _FFMPEG_UNSET


class AudioMetadataError(RuntimeError):
    """Raised when an audio file cannot be probed or decoded."""


@dataclass(slots=True)
class AudioFileMetadata:
    path: str
    name: str
    duration: float
    created_at: dt.datetime
    rms_level: float | None = None


def normalize_audio_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def audio_path_key(path: str) -> str:
    return os.path.normcase(normalize_audio_path(path))


def is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def collect_audio_file_metadata(path: str, *, include_rms: bool = True) -> AudioFileMetadata:
    normalized_path = normalize_audio_path(path)
    if not os.path.isfile(normalized_path):
        raise AudioMetadataError(f"Fichier introuvable: {normalized_path}")
    if not is_audio_file(normalized_path):
        raise AudioMetadataError(f"Extension audio non prise en charge: {normalized_path}")

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
    return collect_audio_file_metadata(path, include_rms=False).duration


def _probe_with_soundfile(path: str, *, include_rms: bool) -> tuple[float | None, float | None]:
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
                chunk64 = np.asarray(chunk, dtype=np.float64)
                sum_squares += float(np.square(chunk64).sum())
                sample_count += int(chunk64.size)

            rms_level = math.sqrt(sum_squares / sample_count) if sample_count > 0 else 0.0
            return duration, rms_level
    except Exception:
        return None, None


def _probe_with_fallback(path: str, *, include_rms: bool) -> tuple[float | None, float | None]:
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

    if returncode != 0 and sample_count == 0:
        return None, None
    if sample_count <= 0:
        return None, None

    duration = float(sample_count / _FFMPEG_MONO_RATE)
    rms_level = math.sqrt(sum_squares / sample_count) if include_rms else None
    return duration, rms_level


def _resolve_ffmpeg_executable() -> str | None:
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
