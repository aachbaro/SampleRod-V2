# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Le moteur de l'onglet "Break" : tout ce qui touche a l'analyse de boucles
#   de batterie (breaks) passe par ici. Cinq capacites :
#   1. ANALYSER un fichier : detecter le tempo, decouper le break en "slices"
#      (un slice = un coup de batterie : kick, snare, hat...) ;
#   2. RE-ANALYSER a partir de marqueurs poses a la main par l'utilisateur ;
#   3. QUANTIZER : recaler les coups sur une grille rythmique a un tempo cible
#      et produire un apercu audio (fichier WAV temporaire) ;
#   4. GENERER un nouveau pattern de batterie a partir des coups detectes ;
#   5. RENDRE ce pattern en audio ecoutable.
# - Chaque operation tourne dans son propre QThread (worker) : l'interface
#   n'attend jamais, elle est prevenue par signaux (Started/Finished/Failed).
# - Les resultats d'analyse sont mis en CACHE (memoire + fichiers JSON dans
#   ~/.samplerod/break_cache) : re-ouvrir un break deja analyse est instantane.
#   Le cache est invalide si le fichier source a change (comparaison de date).
# - Le "vrai" calcul vit dans prototypes/drum_detector/ (analyzer, preview,
#   pattern_generator) ; ce service en est l'adaptateur cote application.
#
# CLASSES DE DONNEES (resultats transportes vers l'UI)
# - DrumSlice                 : un coup detecte (position, type, confiance...).
# - DrumAnalysisResult        : le bilan complet d'une analyse (tempo, slices...).
# - DrumQuantizedPreview      : apercu audio quantize (fichier temp + infos).
# - DrumGeneratedPatternResult: pattern genere (avant rendu audio).
# - DrumPatternRender         : pattern rendu en audio (fichier temp + infos).
#
# WORKERS (QThread, un par operation)
# - _DrumAnalysisWorker / _DrumReanalysisWorker / _DrumQuantizeWorker /
#   _DrumPatternGenerationWorker / _DrumPatternRenderWorker
#
# FONCTIONS ET SERVICE (sommaire)
# - _load_analyzer_module() etc.   : import paresseux des prototypes (lourds).
# - drum_analysis_availability_error() : les dependances sont-elles presentes ?
# - adapt_drum_detection_result()  : traduit le resultat brut du prototype
#                                    en DrumAnalysisResult "public".
# - project_quantized_slices()     : recalcule la position des slices apres
#                                    quantization (pour l'affichage).
# - _preview_temp_path() / _pattern_render_temp_path() : fichiers WAV temp.
# - DrumAnalysisService (QObject)  : la facade pour l'UI
#   - analyze_file()             : lance une analyse en arriere-plan.
#   - create_quantized_preview() : lance la fabrication d'un apercu quantize.
#   - quantized_slices()         : positions des slices apres quantization.
#   - create_break_pattern()     : lance la generation d'un pattern.
#   - render_break_pattern()     : lance le rendu audio d'un pattern.
#   - reanalyze_from_markers()   : relance l'analyse depuis marqueurs manuels.
#   - load_cached()/cache_result()/delete_cached() : gestion du cache.
#   - shutdown()                 : arrete proprement tous les workers.
#
# LIENS CLES
# - prototypes/drum_detector/*        : les algorithmes d'analyse eux-memes.
# - frontend/labo/break_widget.py     : l'interface de l'onglet Break.
# - frontend/labo/break_generator_panel.py : l'interface du generateur.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import soundfile as sf
from PySide6.QtCore import QObject, QThread, Signal

from backend.services.audio_metadata import is_audio_file, normalize_audio_path
from backend.services.temp_workspace import prune_temp_dir, temp_dir

logger = logging.getLogger("drum_analysis_service")

# Version du format de cache : incrementer ce numero invalide tous les
# caches existants (utile quand la structure des resultats change).
_CACHE_VERSION = 2

# Valeurs par defaut des reglages exposes a l'utilisateur :
# - split_density : sensibilite du decoupage (plus haut = plus de slices) ;
# - grid_division : finesse de la grille de quantization (16 = doubles-croches) ;
# - quantize_strength : 0 = positions d'origine, 1 = collees a la grille ;
# - target_bpm : tempo cible par defaut du generateur de breaks.
DEFAULT_SPLIT_DENSITY = 50.0
DEFAULT_QUANTIZE_GRID_DIVISION = 16
DEFAULT_QUANTIZE_STRENGTH = 0.7
DEFAULT_GENERATOR_TARGET_BPM = 140.0
# "tail_mode" : que faire de la fin d'un coup trop long pour sa case ?
# cut = couper net, reverse = jouer a l'envers, ping_pong = aller-retour.
PATTERN_TAIL_MODE_CUT = "cut"
PATTERN_TAIL_MODE_REVERSE = "reverse"
PATTERN_TAIL_MODE_PING_PONG = "ping_pong"
DEFAULT_PATTERN_TAIL_MODE = PATTERN_TAIL_MODE_CUT
PATTERN_TAIL_MODES: tuple[str, ...] = (
    PATTERN_TAIL_MODE_CUT,
    PATTERN_TAIL_MODE_REVERSE,
    PATTERN_TAIL_MODE_PING_PONG,
)


@dataclass(frozen=True, slots=True)
class DrumSlice:
    """Un coup de batterie detecte dans le break.

    start_s/end_s : position dans le fichier source (en secondes).
    label : type principal detecte (kick, snare, hat...), avec sa confidence
    (0 a 1) ; secondary_labels liste les autres types entendus en meme temps
    (coups superposes), layer_score mesurant cette superposition.
    role / rhythmic_position : place du coup dans le rythme (temps fort...).
    step_index / preview_* : position recalculee apres quantization
    (renseignee seulement sur les apercus quantizes).
    """

    index: int
    start_s: float
    end_s: float
    label: str
    confidence: float
    role: str
    rhythmic_position: str
    secondary_labels: tuple[str, ...] = ()
    layer_score: float = 0.0
    step_index: int | None = None
    preview_start_s: float | None = None
    preview_end_s: float | None = None


@dataclass(frozen=True, slots=True)
class DrumAnalysisResult:
    """Bilan complet de l'analyse d'un break, tel que l'UI le consomme.

    Contient le verdict (label/family/form + confidence), le tempo detecte
    (tempo_bpm) avec ses indices de fiabilite (pulse_score, regularity),
    et la liste des coups detectes (slices). prototype_result garde le
    resultat brut du prototype, necessaire aux operations suivantes
    (quantization, generation) mais jamais affiche tel quel.
    """

    source_path: str
    label: str
    family: str
    form: str
    confidence: float
    duration_s: float
    sample_rate: int
    tempo_bpm: float
    pulse_score: float
    regularity: float
    onset_count: int
    split_density: float
    candidates: tuple[str, ...]
    slices: tuple[DrumSlice, ...]
    prototype_result: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DrumQuantizedPreview:
    """Apercu audio d'un break recale sur la grille a un tempo cible.

    temp_path pointe vers le fichier WAV temporaire genere, pret a etre
    ecoute ou glisse ailleurs ; les autres champs decrivent les reglages
    utilises (tempo source/cible, grille, force de quantization).
    """

    source_path: str
    display_name: str
    temp_path: str
    duration_s: float
    sample_rate: int
    source_bpm: float
    target_bpm: float
    grid_division: int
    quantize_strength: float
    slices: tuple[DrumSlice, ...]


@dataclass(frozen=True, slots=True)
class DrumGeneratedPatternResult:
    """Pattern de batterie genere (la "partition"), avant son rendu audio."""

    source_path: str
    target_bpm: float
    use_hybrid: bool
    pattern: Any


@dataclass(frozen=True, slots=True)
class DrumPatternRender:
    """Pattern genere transforme en audio ecoutable (fichier WAV temporaire).

    seed est le germe aleatoire du pattern : le meme seed redonne exactement
    le meme break, ce qui permet de le retrouver ou de le partager.
    """

    source_path: str
    display_name: str
    temp_path: str
    duration_s: float
    sample_rate: int
    target_bpm: float
    tail_mode: str
    seed: int
    bars: int
    pattern: Any


# Les trois modules du prototype (analyse, preview, generateur) sont lourds
# a importer (librosa, numpy...). On ne les charge donc qu'a la premiere
# utilisation, et une seule fois (lru_cache memorise le module charge).
@lru_cache(maxsize=1)
def _load_analyzer_module():
    """Charge (une seule fois) le module d'analyse du prototype."""
    from prototypes.drum_detector import analyzer as analyzer_module

    return analyzer_module


@lru_cache(maxsize=1)
def _load_preview_module():
    """Charge (une seule fois) le module de fabrication d'apercus audio."""
    from prototypes.drum_detector import preview as preview_module

    return preview_module


@lru_cache(maxsize=1)
def _load_pattern_generator_module():
    """Charge (une seule fois) le module generateur de patterns."""
    from prototypes.drum_detector import pattern_generator as pattern_generator_module

    return pattern_generator_module


def drum_analysis_availability_error() -> str | None:
    """Verifie que l'analyse de break est utilisable sur cette machine.

    Renvoie None si tout va bien, sinon un message d'erreur expliquant la
    dependance manquante (librosa non installe, etc.) que l'UI affiche
    a la place de l'onglet Break.
    """
    try:
        analyzer = _load_analyzer_module()
        return analyzer.get_analysis_dependency_error()
    except Exception as exc:
        return str(exc)


def adapt_drum_detection_result(raw_result: Any, *, split_density: float) -> DrumAnalysisResult:
    """Traduit le resultat brut du prototype en DrumAnalysisResult "public".

    Le prototype renvoie ses propres objets internes ; cette fonction les
    convertit champ par champ vers les classes de ce module, avec des
    valeurs par defaut sures (getattr + "or") pour tolerer les champs
    absents. Le resultat brut reste accessible via prototype_result.
    """
    source_path = normalize_audio_path(getattr(raw_result, "source_path", "") or "")
    transient_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
    slices = tuple(
        DrumSlice(
            index=int(getattr(hit, "index", idx)),
            start_s=float(getattr(hit, "start_s", 0.0)),
            end_s=float(getattr(hit, "end_s", 0.0)),
            label=str(getattr(hit, "label", "other") or "other"),
            confidence=float(getattr(hit, "confidence", 0.0) or 0.0),
            role=str(getattr(hit, "role", "other") or "other"),
            rhythmic_position=str(
                getattr(hit, "rhythmic_position", "subdivision") or "subdivision"
            ),
            secondary_labels=tuple(getattr(hit, "secondary_labels", ()) or ()),
            layer_score=float(getattr(hit, "layer_score", 0.0) or 0.0),
        )
        for idx, hit in enumerate(transient_hits, start=1)
    )
    candidates = tuple(
        str(getattr(candidate, "label", "") or "")
        for candidate in tuple(getattr(raw_result, "candidates", ()) or ())
        if str(getattr(candidate, "label", "") or "").strip()
    )
    return DrumAnalysisResult(
        source_path=source_path,
        label=str(getattr(raw_result, "label", "") or ""),
        family=str(getattr(raw_result, "family", "") or ""),
        form=str(getattr(raw_result, "form", "") or ""),
        confidence=float(getattr(raw_result, "confidence", 0.0) or 0.0),
        duration_s=float(getattr(raw_result, "duration_s", 0.0) or 0.0),
        sample_rate=int(getattr(raw_result, "sample_rate", 0) or 0),
        tempo_bpm=float(getattr(raw_result, "tempo_bpm", 0.0) or 0.0),
        pulse_score=float(getattr(raw_result, "pulse_score", 0.0) or 0.0),
        regularity=float(getattr(raw_result, "regularity", 0.0) or 0.0),
        onset_count=int(getattr(raw_result, "onset_count", len(slices)) or len(slices)),
        split_density=float(split_density),
        candidates=candidates,
        slices=slices,
        prototype_result=raw_result,
    )


def project_quantized_slices(
    result: DrumAnalysisResult,
    *,
    target_bpm: float,
    grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
    quantize_strength: float = DEFAULT_QUANTIZE_STRENGTH,
) -> tuple[DrumSlice, ...]:
    """Calcule ou ATTERRIRAIENT les slices apres quantization (sans audio).

    Sert a l'affichage : la forme d'onde de l'apercu quantize doit montrer
    les slices a leurs nouvelles positions. On demande au prototype le
    "planning" de re-timing, puis on copie ces nouvelles positions
    (step_index, preview_start_s/end_s) dans des copies des slices d'origine.
    En cas de donnees insuffisantes, renvoie les slices inchangees.
    """
    if not result.slices:
        return ()

    # Sans tempo source et cible valides, impossible de re-timer.
    source_bpm = float(result.tempo_bpm or 0.0)
    if source_bpm <= 1.0 or float(target_bpm or 0.0) <= 1.0:
        return result.slices

    raw_result = result.prototype_result
    raw_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
    if len(raw_hits) < 2:
        return result.slices

    preview = _load_preview_module()
    schedule = tuple(
        preview.build_retimed_preview_schedule(
            raw_hits,
            source_bpm=source_bpm,
            target_bpm=float(target_bpm),
            mode=preview.PREVIEW_MODE_QUANTIZE,
            quantize_grid_division=int(grid_division),
            quantize_strength=float(quantize_strength),
        )
    )
    if not schedule:
        return result.slices

    projected: list[DrumSlice] = []
    for source_slice, scheduled in zip(result.slices, schedule):
        projected.append(
            replace(
                source_slice,
                step_index=getattr(scheduled, "step_index", None),
                preview_start_s=float(getattr(scheduled, "preview_start_s", 0.0)),
                preview_end_s=float(getattr(scheduled, "preview_end_s", 0.0)),
            )
        )
    # Si le planning est plus court que la liste (cas limite), on complete
    # avec les slices d'origine pour ne rien perdre a l'affichage.
    if len(projected) < len(result.slices):
        projected.extend(result.slices[len(projected) :])
    return tuple(projected)


def _preview_temp_path(source_path: str, target_bpm: float) -> str:
    """Chemin d'un WAV temporaire pour un apercu quantize (nom unique)."""
    temp_root = temp_dir("break_preview")
    # Chaque apercu ecrit un fichier de plus : sans ce menage, le dossier
    # grossit indefiniment jusqu'au disque plein.
    prune_temp_dir("break_preview", keep_recent=10)
    stem = Path(source_path or "break").stem or "break"
    # Suffixe aleatoire : deux apercus du meme fichier ne s'ecrasent jamais.
    suffix = uuid.uuid4().hex[:8]
    filename = f"{stem}_quantized_{int(round(target_bpm))}bpm_{suffix}.wav"
    return str(temp_root / filename)


def _pattern_render_temp_path(source_path: str, target_bpm: float, seed: int) -> str:
    """Chemin d'un WAV temporaire pour un break genere (nom unique avec seed)."""
    temp_root = temp_dir("break_pattern")
    # Un rendu par Generate, par Preview et par changement de BPM en direct :
    # c'est le dossier qui grossit le plus vite, on le borne serre.
    prune_temp_dir("break_pattern", keep_recent=30)
    stem = Path(source_path or "break").stem or "break"
    suffix = uuid.uuid4().hex[:8]
    filename = (
        f"{stem}_break_seed_{int(seed)}_{int(round(target_bpm))}bpm_{suffix}.wav"
    )
    return str(temp_root / filename)


def _normalized_cache_key(source_path: str) -> str:
    """Cle de cache d'un fichier : son chemin normalise (casse ignoree)."""
    return os.path.normcase(os.path.normpath(str(source_path or "")))


# Tolerance de recollement d'une correction manuelle a un hit re-analyse.
# Les positions bougent de quelques millisecondes quand on redecoupe : on
# retrouve le hit corrige par proximite temporelle, pas par index (les index
# sont renumerotes a chaque analyse).
MANUAL_LABEL_TOLERANCE_S = 0.025


# =============================================================================
# WORKERS — un QThread par operation lourde.
# Schema commun : __init__ memorise les parametres, run() fait le calcul dans
# le thread secondaire puis emet soit le signal "pret" avec le resultat, soit
# le signal "echec" avec un message. Aucun worker ne touche a l'interface.
# =============================================================================

class _DrumAnalysisWorker(QThread):
    """Analyse complete d'un fichier : tempo + decoupage en slices."""

    analysisReady = Signal(object)
    analysisFailed = Signal(str, str)

    def __init__(self, path: str, split_density: float, parent: QObject | None = None):
        super().__init__(parent)
        self._path = path
        self._split_density = float(split_density)

    def run(self) -> None:
        try:
            analyzer = _load_analyzer_module()
            raw_result = analyzer.analyze_file(
                self._path,
                split_density=self._split_density,
            )
            public_result = adapt_drum_detection_result(
                raw_result,
                split_density=self._split_density,
            )
            self.analysisReady.emit(public_result)
        except Exception as exc:
            logger.warning("[DrumAnalysisWorker] analyse impossible %s: %s", self._path, exc)
            self.analysisFailed.emit(self._path, str(exc))


class _DrumQuantizeWorker(QThread):
    """Fabrique l'apercu audio quantize : relit le fichier source, demande au
    prototype de re-timer chaque coup sur la grille au tempo cible, puis
    ecrit le resultat dans un WAV temporaire."""

    previewReady = Signal(object)
    previewFailed = Signal(str, str)

    def __init__(
        self,
        result: DrumAnalysisResult,
        *,
        target_bpm: float,
        grid_division: int,
        quantize_strength: float,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._result = result
        self._target_bpm = float(target_bpm)
        self._grid_division = int(grid_division)
        self._quantize_strength = float(quantize_strength)

    def run(self) -> None:
        source_path = self._result.source_path
        try:
            raw_result = self._result.prototype_result
            if raw_result is None:
                raise ValueError("Analyse brute indisponible pour la preview quantizee")
            raw_hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
            if len(raw_hits) < 2:
                raise ValueError("Il faut au moins deux slices pour preparer une preview quantizee")

            preview = _load_preview_module()
            source_bpm = float(self._result.tempo_bpm or 0.0)
            if source_bpm <= 1.0 or self._target_bpm <= 1.0:
                raise ValueError("Tempo source ou cible invalide")

            audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=False)
            quantized = preview.build_retimed_preview(
                audio,
                int(sample_rate),
                raw_hits,
                source_bpm=source_bpm,
                target_bpm=self._target_bpm,
                mode=preview.PREVIEW_MODE_QUANTIZE,
                quantize_grid_division=self._grid_division,
                quantize_strength=self._quantize_strength,
            )
            temp_path = _preview_temp_path(source_path, self._target_bpm)
            sf.write(temp_path, quantized.audio, int(quantized.sample_rate))

            preview_result = DrumQuantizedPreview(
                source_path=source_path,
                display_name=f"{Path(source_path).stem}_quantized_{int(round(self._target_bpm))}",
                temp_path=temp_path,
                duration_s=float(quantized.duration_s or 0.0),
                sample_rate=int(quantized.sample_rate),
                source_bpm=source_bpm,
                target_bpm=self._target_bpm,
                grid_division=self._grid_division,
                quantize_strength=self._quantize_strength,
                slices=project_quantized_slices(
                    self._result,
                    target_bpm=self._target_bpm,
                    grid_division=self._grid_division,
                    quantize_strength=self._quantize_strength,
                ),
            )
            self.previewReady.emit(preview_result)
        except Exception as exc:
            logger.warning("[DrumQuantizeWorker] preview impossible %s: %s", source_path, exc)
            self.previewFailed.emit(source_path, str(exc))


class _DrumPatternGenerationWorker(QThread):
    """Genere un nouveau pattern de batterie (la "partition", pas l'audio)
    a partir des coups detectes et des parametres choisis par l'utilisateur.
    use_hybrid active la variante qui reutilise des sequences entieres du
    break d'origine en plus des coups isoles."""

    patternReady = Signal(object)
    patternFailed = Signal(str, str)

    def __init__(
        self,
        result: DrumAnalysisResult,
        params_payload: dict[str, Any],
        *,
        target_bpm: float,
        use_hybrid: bool,
        anchors: dict[int, str] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._result = result
        self._params_payload = dict(params_payload)
        self._target_bpm = float(target_bpm)
        self._use_hybrid = bool(use_hybrid)
        self._anchors = {
            int(step_index): str(anchor)
            for step_index, anchor in dict(anchors or {}).items()
            if str(anchor or "").strip()
        }

    def run(self) -> None:
        source_path = self._result.source_path
        try:
            raw_result = self._result.prototype_result
            if raw_result is None:
                raise ValueError("Analyse brute indisponible pour la generation du pattern")

            pattern_generator = _load_pattern_generator_module()
            raw_user_motifs = self._params_payload.get("user_motifs") or []
            if raw_user_motifs:
                converted: list = []
                for m in raw_user_motifs:
                    if isinstance(m, dict):
                        try:
                            converted.append(pattern_generator.UserMotif.from_dict(m))
                        except Exception:
                            pass
                    else:
                        converted.append(m)
                payload = {**self._params_payload, "user_motifs": converted}
            else:
                payload = self._params_payload
            params = pattern_generator.BreakPatternParams(**payload)
            hits = tuple(getattr(raw_result, "transient_hits", ()) or ())
            sequences = tuple(getattr(raw_result, "hit_sequences", ()) or ())
            if not hits:
                raise ValueError("Aucun hit disponible pour generer un pattern")

            pattern = pattern_generator.generate_break_pattern_for_mode(
                hits,
                params,
                sequences=sequences,
                use_hybrid=self._use_hybrid,
                anchors=self._anchors,
            )
            self.patternReady.emit(
                DrumGeneratedPatternResult(
                    source_path=source_path,
                    target_bpm=self._target_bpm,
                    use_hybrid=self._use_hybrid,
                    pattern=pattern,
                )
            )
        except Exception as exc:
            logger.warning("[DrumPatternGenerationWorker] generation impossible %s: %s", source_path, exc)
            self.patternFailed.emit(source_path, str(exc))


class _DrumPatternRenderWorker(QThread):
    """Transforme un pattern genere en audio ecoutable : decoupe les coups
    dans le fichier source, les place au bon moment, applique les options
    (gate = duree des coups, mono_choke = un seul son a la fois,
    tail_mode = sort des fins de coups) et ecrit un WAV temporaire."""

    renderReady = Signal(object)
    renderFailed = Signal(str, str)

    def __init__(
        self,
        result: DrumAnalysisResult,
        pattern: Any,
        *,
        target_bpm: float,
        gate: float,
        mono_choke: bool,
        tail_mode: str,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._result = result
        self._pattern = pattern
        self._target_bpm = float(target_bpm)
        self._gate = float(gate)
        self._mono_choke = bool(mono_choke)
        self._tail_mode = str(tail_mode or DEFAULT_PATTERN_TAIL_MODE)

    def run(self) -> None:
        source_path = self._result.source_path
        try:
            if self._pattern is None:
                raise ValueError("Aucun pattern a rendre")
            if self._target_bpm <= 1.0:
                raise ValueError("Tempo cible invalide")

            preview_module = _load_preview_module()
            audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=False)
            rendered = preview_module.build_pattern_preview(
                audio,
                int(sample_rate),
                self._pattern,
                target_bpm=self._target_bpm,
                gate=self._gate,
                mono_choke=self._mono_choke,
                tail_mode=self._tail_mode,
            )

            seed = int(getattr(self._pattern, "seed", 0) or 0)
            bars = int(getattr(self._pattern, "bars", 1) or 1)
            temp_path = _pattern_render_temp_path(source_path, self._target_bpm, seed)
            sf.write(temp_path, rendered.audio, int(rendered.sample_rate))
            stem = Path(source_path).stem or "break"
            display_name = f"{stem}_break_seed_{seed}_{int(round(self._target_bpm))}bpm"
            self.renderReady.emit(
                DrumPatternRender(
                    source_path=source_path,
                    display_name=display_name,
                    temp_path=temp_path,
                    duration_s=float(rendered.duration_s or 0.0),
                    sample_rate=int(rendered.sample_rate),
                    target_bpm=self._target_bpm,
                    tail_mode=self._tail_mode,
                    seed=seed,
                    bars=bars,
                    pattern=self._pattern,
                )
            )
        except Exception as exc:
            logger.warning("[DrumPatternRenderWorker] rendu impossible %s: %s", source_path, exc)
            self.renderFailed.emit(source_path, str(exc))


class _DrumReanalysisWorker(QThread):
    """Relance la detection de types a partir de markers manuels.

    Quand l'utilisateur corrige le decoupage en deplacant/ajoutant des
    marqueurs sur la forme d'onde, on refait l'identification des coups
    (kick/snare/hat...) en utilisant SES positions plutot que celles
    detectees automatiquement.
    """

    analysisReady = Signal(object)
    analysisFailed = Signal(str, str)

    def __init__(
        self,
        result: DrumAnalysisResult,
        marker_times: list[float],
        parent=None,
    ):
        super().__init__(parent)
        self._result = result
        self._marker_times = list(marker_times)

    def run(self) -> None:
        source_path = self._result.source_path
        try:
            analyzer = _load_analyzer_module()
            audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=False)
            raw_result = analyzer.detect_drum_from_markers(
                audio,
                int(sample_rate),
                self._marker_times,
                source_path=source_path,
            )
            public_result = adapt_drum_detection_result(
                raw_result,
                split_density=self._result.split_density,
            )
            self.analysisReady.emit(public_result)
        except Exception as exc:
            logger.warning("[DrumReanalysisWorker] reanalyse impossible %s: %s", source_path, exc)
            self.analysisFailed.emit(source_path, str(exc))


class DrumAnalysisService(QObject):
    """Facade de l'analyse de breaks pour l'interface.

    Chaque methode publique suit le meme schema :
    1. verifier les pre-requis (fichier present, analyse disponible...) ;
    2. creer le worker adequat et connecter ses signaux aux signaux du
       service (que l'UI ecoute) ;
    3. garder le worker dans un set le temps qu'il tourne (sinon Python le
       detruirait en plein travail), puis le liberer a la fin (deleteLater) ;
    4. demarrer le worker et rendre la main immediatement (renvoie True si
       le travail a bien ete lance).
    """

    analysisStarted = Signal(str)
    analysisFinished = Signal(object)
    analysisFailed = Signal(str, str)
    reanalysisStarted = Signal(str)
    reanalysisFinished = Signal(object)
    reanalysisFailed = Signal(str, str)
    quantizeStarted = Signal(str)
    quantizeFinished = Signal(object)
    quantizeFailed = Signal(str, str)
    patternGenerationStarted = Signal(str)
    patternGenerated = Signal(object)
    patternGenerationFailed = Signal(str, str)
    patternRenderStarted = Signal(str)
    patternRendered = Signal(object)
    patternRenderFailed = Signal(str, str)
    statusChanged = Signal(str)

    def __init__(self, app_context) -> None:
        super().__init__()
        self.app_context = app_context
        self._analysis_workers: set[QThread] = set()
        self._reanalysis_workers: set[QThread] = set()
        self._quantize_workers: set[QThread] = set()
        self._pattern_generation_workers: set[QThread] = set()
        self._pattern_render_workers: set[QThread] = set()
        self._analysis_cache_memory: dict[str, tuple[int | None, DrumAnalysisResult]] = {}

    def analyze_file(self, path: str, *, split_density: float = DEFAULT_SPLIT_DENSITY) -> bool:
        """Lance l'analyse d'un fichier en arriere-plan (tempo + slices)."""
        normalized = normalize_audio_path(path)
        if not normalized or not os.path.isfile(normalized):
            self.analysisFailed.emit(normalized, "Fichier introuvable")
            return False
        if not is_audio_file(normalized):
            self.analysisFailed.emit(normalized, "Format audio non supporte")
            return False

        worker = _DrumAnalysisWorker(normalized, split_density, self)
        self._analysis_workers.add(worker)
        worker.analysisReady.connect(self.analysisFinished.emit)
        worker.analysisFailed.connect(self.analysisFailed.emit)
        worker.finished.connect(lambda: self._analysis_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.analysisStarted.emit(normalized)
        self.statusChanged.emit(f"Analyse break en cours: {Path(normalized).name}")
        worker.start()
        return True

    def create_quantized_preview(
        self,
        result: DrumAnalysisResult | None,
        *,
        target_bpm: float,
        grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
        quantize_strength: float = DEFAULT_QUANTIZE_STRENGTH,
    ) -> bool:
        """Lance la fabrication d'un apercu audio quantize en arriere-plan."""
        if result is None:
            self.quantizeFailed.emit("", "Aucune analyse disponible")
            return False
        if not result.source_path or not os.path.isfile(result.source_path):
            self.quantizeFailed.emit(result.source_path, "Fichier source introuvable")
            return False

        worker = _DrumQuantizeWorker(
            result,
            target_bpm=float(target_bpm),
            grid_division=int(grid_division),
            quantize_strength=float(quantize_strength),
            parent=self,
        )
        self._quantize_workers.add(worker)
        worker.previewReady.connect(self.quantizeFinished.emit)
        worker.previewFailed.connect(self.quantizeFailed.emit)
        worker.finished.connect(lambda: self._quantize_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.quantizeStarted.emit(result.source_path)
        self.statusChanged.emit(
            f"Preparation de la preview quantizee: {Path(result.source_path).name}"
        )
        worker.start()
        return True

    def quantized_slices(
        self,
        result: DrumAnalysisResult | None,
        *,
        target_bpm: float,
        grid_division: int = DEFAULT_QUANTIZE_GRID_DIVISION,
        quantize_strength: float = DEFAULT_QUANTIZE_STRENGTH,
    ) -> tuple[DrumSlice, ...]:
        """Positions des slices apres quantization (calcul immediat, pour l'UI)."""
        if result is None:
            return ()
        try:
            return project_quantized_slices(
                result,
                target_bpm=target_bpm,
                grid_division=grid_division,
                quantize_strength=quantize_strength,
            )
        except Exception as exc:
            logger.info("[DrumAnalysisService] projection quantizee impossible: %s", exc)
            return result.slices

    def create_break_pattern(
        self,
        result: DrumAnalysisResult | None,
        params_payload: dict[str, Any] | None,
        *,
        target_bpm: float = DEFAULT_GENERATOR_TARGET_BPM,
        use_hybrid: bool = False,
        anchors: dict[int, str] | None = None,
    ) -> bool:
        """Lance la generation d'un nouveau pattern de break en arriere-plan."""
        if result is None:
            self.patternGenerationFailed.emit("", "Aucune analyse disponible")
            return False
        if not result.source_path or not os.path.isfile(result.source_path):
            self.patternGenerationFailed.emit(result.source_path, "Fichier source introuvable")
            return False

        worker = _DrumPatternGenerationWorker(
            result,
            params_payload or {},
            target_bpm=float(target_bpm),
            use_hybrid=bool(use_hybrid),
            anchors=anchors,
            parent=self,
        )
        self._pattern_generation_workers.add(worker)
        worker.patternReady.connect(self.patternGenerated.emit)
        worker.patternFailed.connect(self.patternGenerationFailed.emit)
        worker.finished.connect(lambda: self._pattern_generation_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.patternGenerationStarted.emit(result.source_path)
        self.statusChanged.emit(f"Generation du break: {Path(result.source_path).name}")
        worker.start()
        return True

    def render_break_pattern(
        self,
        result: DrumAnalysisResult | None,
        pattern: Any,
        *,
        target_bpm: float,
        gate: float = 1.0,
        mono_choke: bool = False,
        tail_mode: str = DEFAULT_PATTERN_TAIL_MODE,
    ) -> bool:
        """Lance le rendu audio d'un pattern genere en arriere-plan."""
        if result is None:
            self.patternRenderFailed.emit("", "Aucune analyse disponible")
            return False
        if pattern is None:
            self.patternRenderFailed.emit(result.source_path, "Aucun pattern genere")
            return False
        if not result.source_path or not os.path.isfile(result.source_path):
            self.patternRenderFailed.emit(result.source_path, "Fichier source introuvable")
            return False

        worker = _DrumPatternRenderWorker(
            result,
            pattern,
            target_bpm=float(target_bpm),
            gate=float(gate),
            mono_choke=bool(mono_choke),
            tail_mode=str(tail_mode or DEFAULT_PATTERN_TAIL_MODE),
            parent=self,
        )
        self._pattern_render_workers.add(worker)
        worker.renderReady.connect(self.patternRendered.emit)
        worker.renderFailed.connect(self.patternRenderFailed.emit)
        worker.finished.connect(lambda: self._pattern_render_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.patternRenderStarted.emit(result.source_path)
        self.statusChanged.emit(f"Rendu du break genere: {Path(result.source_path).name}")
        worker.start()
        return True

    def reanalyze_from_markers(
        self,
        result: DrumAnalysisResult,
        marker_times: list[float],
    ) -> bool:
        """Relance la detection a partir de positions de markers manuels."""
        if not result.source_path or not os.path.isfile(result.source_path):
            self.reanalysisFailed.emit(result.source_path or "", "Fichier source introuvable")
            return False
        if not marker_times:
            self.reanalysisFailed.emit(result.source_path, "Aucun marker fourni")
            return False

        worker = _DrumReanalysisWorker(result, marker_times, self)
        self._reanalysis_workers.add(worker)
        worker.analysisReady.connect(self.reanalysisFinished.emit)
        worker.analysisReady.connect(self.analysisFinished.emit)   # alias pour l'UI
        worker.analysisFailed.connect(self.reanalysisFailed.emit)
        worker.finished.connect(lambda: self._reanalysis_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.reanalysisStarted.emit(result.source_path)
        self.statusChanged.emit(f"Re-analyse depuis markers: {Path(result.source_path).name}")
        worker.start()
        return True

    # ---------------------------------------------------------------------- #
    # Cache disque / memoire
    # L'analyse d'un break prend plusieurs secondes : on garde donc les
    # resultats a deux niveaux :
    # - en MEMOIRE (dictionnaire) pour la session en cours ;
    # - sur DISQUE (fichiers JSON dans ~/.samplerod/break_cache) pour les
    #   sessions suivantes.
    # Chaque entree memorise la date de modification (mtime) du fichier
    # source : si le fichier a change depuis, le cache est jete.
    # ---------------------------------------------------------------------- #
    @property
    def _cache_dir(self) -> Path:
        """Dossier du cache disque (dans le profil utilisateur)."""
        return Path.home() / ".samplerod" / "break_cache"

    def _cache_path(self, source_path: str) -> Path:
        """Fichier JSON de cache d'un fichier source donne.

        Le nom est un condense (hash SHA-256 tronque) du chemin : valable
        quel que soit le nom du fichier, sans caracteres interdits.
        """
        key = hashlib.sha256(_normalized_cache_key(source_path).encode()).hexdigest()[:20]
        return self._cache_dir / f"{key}.json"

    def _source_mtime(self, source_path: str) -> int | None:
        """Date de derniere modification du fichier source (None si illisible)."""
        try:
            return int(os.path.getmtime(source_path))
        except Exception:
            return None

    def _memory_cache_get(self, source_path: str) -> DrumAnalysisResult | None:
        """Cherche un resultat en cache memoire, en verifiant sa fraicheur."""
        key = _normalized_cache_key(source_path)
        cached = self._analysis_cache_memory.get(key)
        if cached is None:
            return None
        cached_mtime, cached_result = cached
        current_mtime = self._source_mtime(source_path)
        # Si le fichier a ete modifie depuis l'analyse, le cache est perime.
        if cached_mtime is not None and current_mtime is not None and cached_mtime != current_mtime:
            self._analysis_cache_memory.pop(key, None)
            return None
        return cached_result

    def _memory_cache_put(self, result: DrumAnalysisResult) -> None:
        """Range un resultat dans le cache memoire (avec la date du fichier)."""
        source_path = normalize_audio_path(result.source_path)
        if not source_path:
            return
        key = _normalized_cache_key(source_path)
        self._analysis_cache_memory[key] = (self._source_mtime(source_path), result)

    def _memory_cache_delete(self, source_path: str) -> None:
        """Retire un fichier du cache memoire."""
        self._analysis_cache_memory.pop(_normalized_cache_key(source_path), None)

    def _result_to_dict(self, result: DrumAnalysisResult) -> dict:
        """Prepare un resultat pour l'ecriture JSON (cache disque).

        Le resultat brut du prototype n'est pas serialisable tel quel : on
        le convertit via sa methode to_dict() et on le range sous la cle
        "_prototype" pour pouvoir le reconstruire au rechargement.
        """
        d = dataclasses.asdict(result)
        d.pop("prototype_result", None)
        raw_result = getattr(result, "prototype_result", None)
        if raw_result is not None and hasattr(raw_result, "to_dict"):
            try:
                d["_prototype"] = raw_result.to_dict()
            except Exception:
                logger.info("[DrumAnalysisService] export prototype_result impossible")
        return d

    def _raw_result_from_dict(self, payload: dict[str, Any]) -> Any:
        """Reconstruit le resultat brut du prototype depuis le JSON du cache.

        Operation inverse de _result_to_dict : recree un a un les objets
        internes du prototype (TransientHit, DrumCandidate, HitSequence...)
        avec des valeurs par defaut sures pour chaque champ manquant.
        """
        analyzer = _load_analyzer_module()
        transient_hits = tuple(
            analyzer.TransientHit(
                index=int(hit["index"]),
                start_s=float(hit["start_s"]),
                end_s=float(hit["end_s"]),
                label=str(hit.get("label", "other") or "other"),
                confidence=float(hit.get("confidence", 0.0) or 0.0),
                peak_db=float(hit.get("peak_db", 0.0) or 0.0),
                low_ratio=float(hit.get("low_ratio", 0.0) or 0.0),
                mid_ratio=float(hit.get("mid_ratio", 0.0) or 0.0),
                high_ratio=float(hit.get("high_ratio", 0.0) or 0.0),
                secondary_labels=tuple(hit.get("secondary_labels", ()) or ()),
                layer_score=float(hit.get("layer_score", 0.0) or 0.0),
                role=str(hit.get("role", "other") or "other"),
                rhythmic_position=str(hit.get("rhythmic_position", "subdivision") or "subdivision"),
                generator_enabled=bool(hit.get("generator_enabled", True)),
            )
            for hit in payload.get("transient_hits", ()) or ()
        )
        candidates = tuple(
            analyzer.DrumCandidate(
                label=str(candidate.get("label", "") or ""),
                score=float(candidate.get("score", 0.0) or 0.0),
                details=str(candidate.get("details", "") or ""),
            )
            for candidate in payload.get("candidates", ()) or ()
        )
        sequences = tuple(
            analyzer.HitSequence(
                index=int(sequence.get("index", 0) or 0),
                role=str(sequence.get("role", "groove") or "groove"),
                hit_count=int(sequence.get("hit_count", 0) or 0),
                total_steps=int(sequence.get("total_steps", 0) or 0),
                source_start_s=float(sequence.get("source_start_s", 0.0) or 0.0),
                source_end_s=float(sequence.get("source_end_s", 0.0) or 0.0),
                start_step_hint=int(sequence.get("start_step_hint", 1) or 1),
                end_step_hint=int(sequence.get("end_step_hint", 1) or 1),
                labels=tuple(sequence.get("labels", ()) or ()),
                events=tuple(
                    analyzer.HitSequenceEvent(
                        order=int(event.get("order", 0) or 0),
                        hit_index=int(event.get("hit_index", 0) or 0),
                        label=str(event.get("label", "other") or "other"),
                        role=str(event.get("role", "other") or "other"),
                        start_offset_steps=int(event.get("start_offset_steps", 0) or 0),
                        interval_steps=int(event.get("interval_steps", 0) or 0),
                        velocity_ratio=float(event.get("velocity_ratio", 0.0) or 0.0),
                        source_start_s=float(event.get("source_start_s", 0.0) or 0.0),
                        source_end_s=float(event.get("source_end_s", 0.0) or 0.0),
                        secondary_labels=tuple(event.get("secondary_labels", ()) or ()),
                        layer_score=float(event.get("layer_score", 0.0) or 0.0),
                        rhythmic_position=str(
                            event.get("rhythmic_position", "subdivision") or "subdivision"
                        ),
                    )
                    for event in sequence.get("events", ()) or ()
                ),
            )
            for sequence in payload.get("hit_sequences", ()) or ()
        )
        return analyzer.DrumDetectionResult(
            source_path=payload.get("source_path"),
            label=str(payload.get("label", "") or ""),
            form=str(payload.get("form", "") or ""),
            family=str(payload.get("family", "") or ""),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            loop_score=float(payload.get("loop_score", 0.0) or 0.0),
            drum_score=float(payload.get("drum_score", 0.0) or 0.0),
            break_score=float(payload.get("break_score", 0.0) or 0.0),
            duration_s=float(payload.get("duration_s", 0.0) or 0.0),
            sample_rate=int(payload.get("sample_rate", 0) or 0),
            tempo_bpm=float(payload.get("tempo_bpm", 0.0) or 0.0),
            pulse_score=float(payload.get("pulse_score", 0.0) or 0.0),
            regularity=float(payload.get("regularity", 0.0) or 0.0),
            onset_count=int(payload.get("onset_count", len(transient_hits)) or len(transient_hits)),
            onset_density=float(payload.get("onset_density", 0.0) or 0.0),
            percussive_ratio=float(payload.get("percussive_ratio", 0.0) or 0.0),
            harmonic_ratio=float(payload.get("harmonic_ratio", 0.0) or 0.0),
            decay_s=float(payload.get("decay_s", 0.0) or 0.0),
            spectral_centroid_hz=float(payload.get("spectral_centroid_hz", 0.0) or 0.0),
            spectral_flatness=float(payload.get("spectral_flatness", 0.0) or 0.0),
            band_energies=dict(payload.get("band_energies", {}) or {}),
            transient_hits=transient_hits,
            candidates=candidates,
            hit_sequences=sequences,
        )

    def _result_from_dict(self, d: dict) -> DrumAnalysisResult:
        """Reconstruit un DrumAnalysisResult complet depuis le JSON du cache."""
        slices = tuple(
            DrumSlice(
                index=int(s["index"]),
                start_s=float(s["start_s"]),
                end_s=float(s["end_s"]),
                label=str(s.get("label", "other")),
                confidence=float(s.get("confidence", 0.0)),
                role=str(s.get("role", "other")),
                rhythmic_position=str(s.get("rhythmic_position", "subdivision")),
                secondary_labels=tuple(s.get("secondary_labels", [])),
                layer_score=float(s.get("layer_score", 0.0)),
                step_index=s.get("step_index"),
                preview_start_s=s.get("preview_start_s"),
                preview_end_s=s.get("preview_end_s"),
            )
            for s in d.get("slices", [])
        )
        return DrumAnalysisResult(
            source_path=d["source_path"],
            label=d.get("label", ""),
            family=d.get("family", ""),
            form=d.get("form", ""),
            confidence=d.get("confidence", 0.0),
            duration_s=d.get("duration_s", 0.0),
            sample_rate=d.get("sample_rate", 44100),
            tempo_bpm=d.get("tempo_bpm", 0.0),
            pulse_score=d.get("pulse_score", 0.0),
            regularity=d.get("regularity", 0.0),
            onset_count=d.get("onset_count", len(slices)),
            split_density=d.get("split_density", DEFAULT_SPLIT_DENSITY),
            candidates=tuple(d.get("candidates", [])),
            slices=slices,
            prototype_result=(
                self._raw_result_from_dict(d["_prototype"])
                if isinstance(d.get("_prototype"), dict)
                else None
            ),
        )

    def load_cached(self, source_path: str) -> DrumAnalysisResult | None:
        """Charge le resultat en cache pour ce fichier, ou None.

        Ordre de recherche : cache memoire (instantane), puis cache disque.
        Le cache disque est ignore et supprime si sa version est ancienne ou
        si le fichier source a ete modifie depuis (comparaison de mtime).
        """
        memory_hit = self._memory_cache_get(source_path)
        if memory_hit is not None:
            return memory_hit
        try:
            cache_file = self._cache_path(source_path)
            if not cache_file.exists():
                return None
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if data.get("_version") != _CACHE_VERSION:
                return None
            stored_mtime = data.get("_mtime")
            if stored_mtime is not None:
                try:
                    actual_mtime = int(os.path.getmtime(source_path))
                    if actual_mtime != int(stored_mtime):
                        logger.info("Break cache invalide (mtime change): %s", source_path)
                        cache_file.unlink(missing_ok=True)
                        self._memory_cache_delete(source_path)
                        return None
                except Exception:
                    pass
            result = self._result_from_dict(data)
            self._memory_cache_put(result)
            return result
        except Exception:
            logger.warning("Break cache lecture impossible: %s", source_path, exc_info=True)
            return None

    def cache_result(self, result: DrumAnalysisResult) -> None:
        """Persiste le résultat d'analyse sur disque (écrase si déjà présent)."""
        try:
            self._memory_cache_put(result)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            d = self._result_to_dict(result)
            d["_version"] = _CACHE_VERSION
            mtime = self._source_mtime(result.source_path)
            if mtime is not None:
                d["_mtime"] = mtime
            self._cache_path(result.source_path).write_text(
                json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.warning("Break cache ecriture impossible", exc_info=True)

    def delete_cached(self, source_path: str) -> None:
        """Supprime l'entrée de cache pour ce fichier."""
        try:
            self._memory_cache_delete(source_path)
            self._cache_path(source_path).unlink(missing_ok=True)
        except Exception:
            pass

    # ---------------------------------------------------------------------- #
    # Editions incrementales de la liste de slices
    # Relancer une analyse complete pour un seul marqueur coute plusieurs
    # secondes : ces deux operations modifient le decoupage en place.
    # ---------------------------------------------------------------------- #
    def merge_slice_into_previous(
        self,
        result: DrumAnalysisResult,
        slice_index: int,
    ) -> DrumAnalysisResult | None:
        """Supprime une slice en la FUSIONNANT avec celle qui la precede.

        La slice retiree n'ouvre pas un trou : la precedente s'etend jusqu'a la
        fin de celle qu'on enleve et garde sa classe. C'est le geste « ce coup
        n'aurait pas du etre coupe en deux ».

        La toute premiere slice n'a pas de precedente : elle est alors fusionnee
        avec la suivante, qui recule son debut. Retourne None si l'index est
        inconnu ou s'il ne reste qu'une slice.
        """
        slices = list(result.slices)
        if len(slices) < 2:
            return None
        position = next(
            (i for i, item in enumerate(slices) if int(item.index) == int(slice_index)),
            None,
        )
        if position is None:
            return None

        removed = slices.pop(position)
        if position > 0:
            target = position - 1
            slices[target] = replace(slices[target], end_s=float(removed.end_s))
        else:
            slices[0] = replace(slices[0], start_s=float(removed.start_s))
        return self._rebuilt_with_slices(result, slices)

    def split_slice_at(
        self,
        result: DrumAnalysisResult,
        position_s: float,
        *,
        source_path: str | None = None,
    ) -> DrumAnalysisResult | None:
        """Coupe la slice qui contient `position_s` et reclasse les deux moities.

        Sert quand l'utilisateur pose un marqueur : la nouvelle slice arrive a
        sa place dans la liste et recoit un type detecte, sans re-analyser tout
        le break. Retourne None si la position ne coupe aucune slice ou si la
        classification echoue.
        """
        slices = list(result.slices)
        if not slices:
            return None
        position_s = float(position_s)
        host = next(
            (
                i
                for i, item in enumerate(slices)
                if float(item.start_s) < position_s < float(item.end_s)
            ),
            None,
        )
        if host is None:
            return None
        original = slices[host]
        # Deux moities trop courtes ne donneraient rien d'exploitable.
        if (position_s - float(original.start_s)) < 0.005 or (float(original.end_s) - position_s) < 0.005:
            return None

        audio_path = source_path or result.source_path
        try:
            audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
        except Exception:
            logger.warning("Split slice: audio illisible (%s)", audio_path, exc_info=True)
            return None

        halves = (
            (float(original.start_s), position_s),
            (position_s, float(original.end_s)),
        )
        classified: list[DrumSlice] = []
        analyzer = _load_analyzer_module()
        for offset, (start_s, end_s) in enumerate(halves):
            try:
                hit = analyzer.classify_segment(audio, int(sample_rate), start_s, end_s)
            except Exception:
                logger.info("Split slice: classification impossible sur [%s, %s]", start_s, end_s)
                return None
            classified.append(
                replace(
                    original,
                    index=int(original.index) + offset,
                    start_s=float(start_s),
                    end_s=float(end_s),
                    label=str(hit.label),
                    confidence=float(hit.confidence),
                    role=str(hit.role),
                    rhythmic_position=str(hit.rhythmic_position),
                    secondary_labels=tuple(hit.secondary_labels),
                    layer_score=float(hit.layer_score),
                )
            )

        slices[host : host + 1] = classified
        return self._rebuilt_with_slices(result, slices)

    def move_slice_boundary(
        self,
        result: DrumAnalysisResult,
        from_s: float,
        to_s: float,
        *,
        source_path: str | None = None,
        tolerance_s: float = 0.005,
    ) -> DrumAnalysisResult | None:
        """Deplace une frontiere de slice et reclasse les deux slices touchees.

        Un marqueur est la frontiere entre deux slices : le bouger change la
        fin de celle de gauche ET le debut de celle de droite. Sans ca, la
        selection jouee depuis la liste restait sur l'ancien decoupage.
        Retourne None si aucune frontiere ne correspond ou si le deplacement
        ecraserait une slice voisine.
        """
        slices = list(result.slices)
        if not slices:
            return None
        from_s = float(from_s)
        to_s = float(to_s)

        right = next(
            (i for i, item in enumerate(slices) if abs(float(item.start_s) - from_s) <= tolerance_s),
            None,
        )
        left = next(
            (i for i, item in enumerate(slices) if abs(float(item.end_s) - from_s) <= tolerance_s),
            None,
        )
        if right is None and left is None:
            return None

        # La nouvelle frontiere doit rester dans le territoire des deux slices
        # concernees, sinon on detruirait leurs voisines.
        lower = float(slices[left].start_s) if left is not None else 0.0
        upper = float(slices[right].end_s) if right is not None else float(slices[left].end_s)
        if not (lower + 0.005 <= to_s <= upper - 0.005):
            return None

        touched: list[int] = []
        if left is not None:
            slices[left] = replace(slices[left], end_s=to_s)
            touched.append(left)
        if right is not None:
            slices[right] = replace(slices[right], start_s=to_s)
            touched.append(right)

        audio_path = source_path or result.source_path
        try:
            audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=False)
        except Exception:
            logger.warning("Move boundary: audio illisible (%s)", audio_path, exc_info=True)
            audio = None
            sample_rate = 0

        if audio is not None:
            analyzer = _load_analyzer_module()
            for position in touched:
                item = slices[position]
                try:
                    hit = analyzer.classify_segment(
                        audio, int(sample_rate), float(item.start_s), float(item.end_s)
                    )
                except Exception:
                    # Le contour est corrige meme si la reclassification echoue.
                    continue
                slices[position] = replace(
                    item,
                    label=str(hit.label),
                    confidence=float(hit.confidence),
                    role=str(hit.role),
                    rhythmic_position=str(hit.rhythmic_position),
                    secondary_labels=tuple(hit.secondary_labels),
                    layer_score=float(hit.layer_score),
                )

        return self._rebuilt_with_slices(result, slices)

    def _rebuilt_with_slices(
        self,
        result: DrumAnalysisResult,
        slices: list[DrumSlice],
    ) -> DrumAnalysisResult:
        """Renumerote les slices et resynchronise les hits du prototype.

        Le generateur lit `prototype_result.transient_hits` : sans cette
        resynchronisation, il continuerait a voir l'ancien decoupage.
        """
        normalized = tuple(
            replace(drum_slice, index=index)
            for index, drum_slice in enumerate(slices, start=1)
        )
        raw_result = getattr(result, "prototype_result", None)
        updated_raw = raw_result
        if raw_result is not None:
            try:
                analyzer = _load_analyzer_module()
                hits = tuple(
                    analyzer.TransientHit(
                        index=int(drum_slice.index),
                        start_s=float(drum_slice.start_s),
                        end_s=float(drum_slice.end_s),
                        label=str(drum_slice.label),
                        confidence=float(drum_slice.confidence),
                        peak_db=self._peak_db_for(raw_result, drum_slice),
                        low_ratio=0.0,
                        mid_ratio=0.0,
                        high_ratio=0.0,
                        secondary_labels=tuple(drum_slice.secondary_labels),
                        layer_score=float(drum_slice.layer_score),
                        role=str(drum_slice.role),
                        rhythmic_position=str(drum_slice.rhythmic_position),
                    )
                    for drum_slice in normalized
                )
                updated_raw = replace(
                    raw_result,
                    onset_count=len(hits),
                    transient_hits=hits,
                    hit_sequences=(),
                )
            except Exception:
                logger.info("[DrumAnalysisService] prototype non resynchronise apres edition")
                updated_raw = raw_result
        return replace(
            result,
            onset_count=len(normalized),
            slices=normalized,
            prototype_result=updated_raw,
        )

    @staticmethod
    def _peak_db_for(raw_result: Any, drum_slice: DrumSlice) -> float:
        """Reprend le niveau mesure du hit d'origine le plus proche."""
        best = 0.0
        best_delta = 0.05
        for hit in tuple(getattr(raw_result, "transient_hits", ()) or ()):
            delta = abs(float(hit.start_s) - float(drum_slice.start_s))
            if delta <= best_delta:
                best = float(hit.peak_db)
                best_delta = delta
        return best

    # ---------------------------------------------------------------------- #
    # Corrections manuelles de classification
    # Une analyse re-classe TOUS les hits : sans ce calque, chaque re-analyse
    # (ou chaque redecoupage) effacait les corrections faites a la main.
    # On les stocke donc a part du cache d'analyse — ce sont des donnees
    # utilisateur, pas un resultat derive — et on les re-applique apres
    # chaque analyse.
    # Cle = position de depart du hit (en secondes), et pas son index :
    # les index sont renumerotes des qu'on ajoute ou retire un marqueur.
    # ---------------------------------------------------------------------- #
    @property
    def _manual_labels_dir(self) -> Path:
        return Path.home() / ".samplerod" / "break_labels"

    def _manual_labels_path(self, source_path: str) -> Path:
        key = hashlib.sha256(_normalized_cache_key(source_path).encode()).hexdigest()[:20]
        return self._manual_labels_dir / f"{key}.json"

    def load_manual_labels(self, source_path: str) -> dict[float, str]:
        """Corrections de classe enregistrees pour ce fichier : {start_s: label}."""
        if not source_path:
            return {}
        try:
            path = self._manual_labels_path(source_path)
            if not path.exists():
                return {}
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Break labels lecture impossible: %s", source_path, exc_info=True)
            return {}
        overrides: dict[float, str] = {}
        for entry in payload.get("overrides", ()) or ():
            try:
                overrides[float(entry["start_s"])] = str(entry["label"])
            except (KeyError, TypeError, ValueError):
                continue
        return overrides

    def _save_manual_labels(self, source_path: str, overrides: dict[float, str]) -> None:
        try:
            path = self._manual_labels_path(source_path)
            if not overrides:
                path.unlink(missing_ok=True)
                return
            self._manual_labels_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "source_path": source_path,
                "overrides": [
                    {"start_s": round(float(start_s), 6), "label": str(label)}
                    for start_s, label in sorted(overrides.items())
                ],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("Break labels ecriture impossible: %s", source_path, exc_info=True)

    def set_manual_label(self, source_path: str, start_s: float, label: str) -> None:
        """Memorise (et persiste) la correction de classe d'un hit."""
        if not source_path:
            return
        overrides = self.load_manual_labels(source_path)
        # Remplace une correction deja posee sur le meme hit plutot que d'en
        # empiler une seconde a quelques millisecondes d'ecart.
        existing = self._nearest_override_key(overrides, float(start_s))
        if existing is not None:
            overrides.pop(existing)
        overrides[float(start_s)] = str(label)
        self._save_manual_labels(source_path, overrides)

    def drop_manual_label(self, source_path: str, start_s: float) -> None:
        """Oublie la correction posee sur ce hit (hit supprime, par exemple)."""
        if not source_path:
            return
        overrides = self.load_manual_labels(source_path)
        key = self._nearest_override_key(overrides, float(start_s))
        if key is None:
            return
        overrides.pop(key)
        self._save_manual_labels(source_path, overrides)

    def clear_manual_labels(self, source_path: str) -> None:
        """Oublie toutes les corrections de classe de ce fichier."""
        self._save_manual_labels(source_path, {})

    @staticmethod
    def _nearest_override_key(overrides: dict[float, str], start_s: float) -> float | None:
        """Correction posee sur ce hit, a la tolerance pres (None sinon)."""
        best_key: float | None = None
        best_delta = MANUAL_LABEL_TOLERANCE_S
        for key in overrides:
            delta = abs(float(key) - float(start_s))
            if delta <= best_delta:
                best_key = key
                best_delta = delta
        return best_key

    def apply_manual_labels(self, result: DrumAnalysisResult) -> DrumAnalysisResult:
        """Repose les corrections manuelles par-dessus un resultat d'analyse.

        Appele apres chaque analyse : les slices ET les hits du prototype
        (que lit le generateur) recoivent la classe choisie par l'utilisateur.
        Retourne le resultat inchange s'il n'y a rien a appliquer.
        """
        if result is None:
            return result
        overrides = self.load_manual_labels(result.source_path)
        if not overrides:
            return result

        changed = False
        patched_slices = []
        for drum_slice in result.slices:
            key = self._nearest_override_key(overrides, float(drum_slice.start_s))
            label = overrides[key] if key is not None else None
            if label is None or label == drum_slice.label:
                patched_slices.append(drum_slice)
                continue
            patched_slices.append(replace(drum_slice, label=label))
            changed = True

        raw_result = getattr(result, "prototype_result", None)
        patched_raw = raw_result
        if raw_result is not None:
            try:
                patched_hits = []
                for raw_hit in tuple(getattr(raw_result, "transient_hits", ()) or ()):
                    key = self._nearest_override_key(overrides, float(raw_hit.start_s))
                    label = overrides[key] if key is not None else None
                    if label is None or label == raw_hit.label:
                        patched_hits.append(raw_hit)
                        continue
                    patched_hits.append(replace(raw_hit, label=label))
                    changed = True
                patched_raw = replace(raw_result, transient_hits=tuple(patched_hits))
            except Exception:
                logger.info("[DrumAnalysisService] corrections non appliquees au prototype")
                patched_raw = raw_result

        if not changed:
            return result
        return replace(result, slices=tuple(patched_slices), prototype_result=patched_raw)

    def shutdown(self) -> None:
        """Arrete tous les workers encore actifs (appele a la fermeture).

        On demande poliment l'interruption puis on attend chaque worker au
        maximum 2 secondes : l'application ne doit pas rester bloquee par
        une analyse en cours.
        """
        workers = (
            list(self._analysis_workers)
            + list(self._reanalysis_workers)
            + list(self._quantize_workers)
            + list(self._pattern_generation_workers)
            + list(self._pattern_render_workers)
        )
        self._analysis_workers.clear()
        self._reanalysis_workers.clear()
        self._quantize_workers.clear()
        self._pattern_generation_workers.clear()
        self._pattern_render_workers.clear()
        self._analysis_cache_memory.clear()
        for worker in workers:
            try:
                worker.requestInterruption()
            except Exception:
                pass
            try:
                worker.wait(2000)
            except Exception:
                logger.info("[DrumAnalysisService] arret worker impossible")
