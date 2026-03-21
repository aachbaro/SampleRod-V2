"""
------------------------------------------------------------------------------
Sample Composer - Model (Composition en memoire)
------------------------------------------------------------------------------
Role
----
Ce module contient le "coeur" du Compositeur:
- une liste ordonnee de clips (slices) en memoire
- un format cible (sample rate + nb de canaux) qui sert de norme interne
- un rendu "preview" (audio concatene) mis en cache

Pourquoi un modele dedie ?
--------------------------
Le Compositeur est un outil UI mais son etat (clips + format + preview) doit:
- etre centralise (sinon chaque widget recalcule / duplique)
- etre observable (signals Qt -> UI se met a jour)
- etre testable (logique pure, sans UI)

Invariants (MVP)
----------------
- Le 1er clip definit le format cible: target_sr / target_channels.
- Tous les clips stockes dans le modele sont normalises vers ce format.
- L'audio est float32 (range idealement [-1, 1]).
- Mono: shape (n_samples,)
- Stereo: shape (n_samples, 2)

Notes sur la normalisation
--------------------------
On supporte deja (optionnel) la normalisation:
- Channels: mono<->stereo (duplication / moyenne).
- Sample rate: resample via scipy.signal.resample_poly si SciPy est dispo.
  Si SciPy n'est pas installe, on refuse les clips dont le SR differe.
------------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from fractions import Fraction
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("sample_composer_model")

try:
    # SciPy est optionnel: le compositeur fonctionne sans, mais refusera les SR differents.
    from scipy.signal import resample_poly  # type: ignore
except Exception:  # pragma: no cover - environment dependant
    resample_poly = None  # type: ignore[assignment]


def _as_float32_audio(audio: Any) -> np.ndarray:
    """Convertit en numpy float32 contigu (sans imposer la forme)."""
    arr = np.asarray(audio, dtype=np.float32)
    return np.ascontiguousarray(arr, dtype=np.float32)


def _normalize_audio_shape(audio: np.ndarray) -> np.ndarray:
    """
    Normalise la forme pour notre convention:
    - mono: (n,)
    - stereo: (n, 2)

    Robustesse: si on recoit du channel-first (2, n), on transpose.
    """
    if audio.ndim == 1:
        return audio

    if audio.ndim != 2:
        raise ValueError(f"Audio array must be 1D or 2D, got ndim={audio.ndim}.")

    # Heuristique: si shape (2, n_samples) on transpose -> (n_samples, 2).
    if audio.shape[0] in (1, 2) and audio.shape[1] > 2 and audio.shape[0] < audio.shape[1]:
        audio = audio.T

    if audio.shape[1] == 1:
        return audio[:, 0]

    if audio.shape[1] == 2:
        return audio

    raise ValueError(f"Unsupported channel count: shape={audio.shape}.")


def _infer_channels(audio: np.ndarray) -> int:
    if audio.ndim == 1:
        return 1
    return int(audio.shape[1])


def _convert_channels(audio: np.ndarray, target_channels: int) -> np.ndarray:
    """Convertit mono<->stereo. (MVP)"""
    if target_channels not in (1, 2):
        raise ValueError(f"target_channels must be 1 or 2, got {target_channels}.")

    channels = _infer_channels(audio)
    if channels == target_channels:
        # Uniformise: on garde mono en 1D.
        if target_channels == 1 and audio.ndim == 2:
            return audio[:, 0]
        return audio

    if channels == 1 and target_channels == 2:
        mono = audio if audio.ndim == 1 else audio[:, 0]
        return np.stack([mono, mono], axis=1)

    if channels == 2 and target_channels == 1:
        return audio.mean(axis=1)

    raise ValueError(f"Unsupported channel conversion: {channels} -> {target_channels}.")


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample (axis=0) avec SciPy si dispo, sinon erreur."""
    if orig_sr == target_sr:
        return audio

    if resample_poly is None:
        raise RuntimeError(
            "SciPy is not available: cannot resample audio. "
            "Install with `pip install scipy` or use matching sample rates."
        )

    if orig_sr <= 0 or target_sr <= 0:
        raise ValueError(f"Invalid sample rates: orig_sr={orig_sr}, target_sr={target_sr}.")

    # Ratio exact ou approximation raisonnable (ex: 44100->48000 = 160/147).
    frac = Fraction(target_sr, orig_sr).limit_denominator(1000)
    up, down = int(frac.numerator), int(frac.denominator)

    # resample_poly renvoie float64 -> on revient en float32.
    res = resample_poly(audio, up=up, down=down, axis=0)
    res = np.asarray(res, dtype=np.float32)
    res = np.ascontiguousarray(res, dtype=np.float32)
    return res


@dataclass(slots=True)
class ComposerClip:
    clip_id: int
    label: str
    audio: np.ndarray  # float32 (n,) mono or (n,2) stereo
    sr: int
    channels: int
    duration_s: float
    source: dict[str, Any]


class ComposerModel(QObject):
    """
    Modele Qt pour le compositeur.

    API a garder simple:
    - add_slice(...) / remove_clip(...) / clear()
    - reorder_by_ids([...])
    - render_preview() (audio concatene + metadata)
    """

    changed = Signal()
    clipsChanged = Signal()
    previewChanged = Signal()
    formatChanged = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.target_sr: int | None = None
        self.target_channels: int | None = None

        self._clips: list[ComposerClip] = []
        self._next_clip_id = 1

        self._preview_dirty = True
        self._preview_audio: np.ndarray | None = None

    # --------------------------------------------------------------------- state
    @property
    def clips(self) -> list[ComposerClip]:
        # On expose une copie shallow pour eviter les modifs silencieuses.
        return list(self._clips)

    def is_empty(self) -> bool:
        return len(self._clips) == 0

    def total_duration_s(self) -> float:
        return float(sum(c.duration_s for c in self._clips))

    # --------------------------------------------------------------------- actions
    def clear(self) -> None:
        if not self._clips and self.target_sr is None and self.target_channels is None:
            return

        self._clips.clear()
        self.target_sr = None
        self.target_channels = None
        self._preview_dirty = True
        self._preview_audio = None

        self.formatChanged.emit()
        self.clipsChanged.emit()
        self.previewChanged.emit()
        self.changed.emit()

    def add_slice(
        self,
        *,
        audio: Any,
        sample_rate: int,
        label: str,
        source: dict[str, Any] | None = None,
    ) -> ComposerClip:
        """
        Ajoute un clip a partir d'un slice (numpy array + sr).
        Normalise automatiquement au format cible.
        """
        if source is None:
            source = {}

        raw = _as_float32_audio(audio)
        raw = _normalize_audio_shape(raw)

        clip_sr = int(sample_rate) if sample_rate else 0
        if clip_sr <= 0:
            raise ValueError(f"Invalid sample_rate: {sample_rate!r}.")

        # Init format cible sur le 1er clip.
        if self.target_sr is None or self.target_channels is None:
            self.target_sr = clip_sr
            self.target_channels = _infer_channels(raw)
            self.formatChanged.emit()

        assert self.target_sr is not None and self.target_channels is not None

        # Normalisation: SR puis channels (ou l'inverse, ca n'a pas d'importance ici).
        norm = _resample(raw, clip_sr, self.target_sr)
        norm = _convert_channels(norm, self.target_channels)

        # Calcul metadonnees
        channels = _infer_channels(norm)
        n_samples = int(norm.shape[0])
        duration_s = n_samples / float(self.target_sr)

        clip = ComposerClip(
            clip_id=self._next_clip_id,
            label=str(label) if label else f"clip_{self._next_clip_id}",
            audio=norm,
            sr=self.target_sr,
            channels=channels,
            duration_s=float(duration_s),
            source=dict(source),
        )
        self._next_clip_id += 1

        self._clips.append(clip)
        self._preview_dirty = True

        self.clipsChanged.emit()
        self.previewChanged.emit()
        self.changed.emit()
        return clip

    def insert_silence_after(self, clip_id: int, duration_s: float = 1.0) -> ComposerClip:
        """
        Insere un segment de silence apres un clip existant.
        """
        if self.target_sr is None or self.target_channels is None:
            raise ValueError("Format cible non defini (aucun clip).")

        try:
            idx = next(i for i, c in enumerate(self._clips) if c.clip_id == clip_id)
        except StopIteration as e:
            raise ValueError(f"Clip introuvable: {clip_id}") from e

        dur = max(0.0, float(duration_s))
        n_samples = max(1, int(dur * self.target_sr))
        if self.target_channels == 1:
            audio = np.zeros((n_samples,), dtype=np.float32)
        else:
            audio = np.zeros((n_samples, self.target_channels), dtype=np.float32)

        clip = ComposerClip(
            clip_id=self._next_clip_id,
            label=f"silence {dur:.0f}s",
            audio=audio,
            sr=int(self.target_sr),
            channels=int(self.target_channels),
            duration_s=float(n_samples / float(self.target_sr)),
            source={"type": "silence", "duration_s": dur},
        )
        self._next_clip_id += 1

        self._clips.insert(idx + 1, clip)
        self._preview_dirty = True

        self.clipsChanged.emit()
        self.previewChanged.emit()
        self.changed.emit()
        return clip

    def remove_clip(self, clip_id: int) -> None:
        before = len(self._clips)
        self._clips = [c for c in self._clips if c.clip_id != clip_id]
        if len(self._clips) == before:
            return

        # Si on supprime le dernier clip, on reset le format (MVP).
        if not self._clips:
            self.target_sr = None
            self.target_channels = None
            self.formatChanged.emit()

        self._preview_dirty = True
        self.clipsChanged.emit()
        self.previewChanged.emit()
        self.changed.emit()

    def reorder_by_ids(self, ordered_ids: list[int]) -> None:
        """
        Reordonne la liste selon l'ordre donne par la vue (QListWidget).
        """
        if not ordered_ids:
            return

        id_to_clip = {c.clip_id: c for c in self._clips}
        new_list: list[ComposerClip] = []
        for cid in ordered_ids:
            clip = id_to_clip.get(cid)
            if clip is not None:
                new_list.append(clip)

        # Si quelque chose a ete oublie (liste incomplete), on append a la fin.
        remaining = [c for c in self._clips if c.clip_id not in set(ordered_ids)]
        new_list.extend(remaining)

        if [c.clip_id for c in new_list] == [c.clip_id for c in self._clips]:
            return

        self._clips = new_list
        self._preview_dirty = True
        self.clipsChanged.emit()
        self.previewChanged.emit()
        self.changed.emit()

    # --------------------------------------------------------------------- preview
    def render_preview(self) -> tuple[np.ndarray, int, int]:
        """
        Renvoie (audio_concat, sr, channels).
        Le rendu est mis en cache et recalcul uniquement si "dirty".
        """
        if self._preview_dirty:
            self._preview_audio = self._compute_preview()
            self._preview_dirty = False

        sr = int(self.target_sr or 0)
        ch = int(self.target_channels or 0)
        audio = self._preview_audio
        if audio is None:
            audio = np.array([], dtype=np.float32)
        return audio, sr, ch

    def _compute_preview(self) -> np.ndarray:
        if not self._clips:
            return np.array([], dtype=np.float32)

        # Concat axis 0.
        first = self._clips[0].audio
        if first.ndim == 1:
            return np.concatenate([c.audio for c in self._clips], axis=0).astype(np.float32, copy=False)

        return np.concatenate([c.audio for c in self._clips], axis=0).astype(np.float32, copy=False)
