from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Iterable, Mapping

import numpy as np

from .analyzer import MAX_SEQUENCE_HIT_COUNT, HitSequence, HitSequenceEvent, TransientHit


@dataclass(frozen=True)
class BreakPatternParams:
    energy: float = 0.55
    kick_weight: float = 0.6
    snare_weight: float = 0.7
    hat_density: float = 0.6
    ghost_density: float = 0.25
    fill_strength: float = 0.35
    repeat_density: float = 0.0
    repeat_span: float = 0.15
    repeat_rate: float = 0.35
    reverse_density: float = 0.0
    kick_roll_density: float = 0.0
    kick_roll_span: float = 0.2
    kick_roll_contrast: float = 0.55
    snare_stretch_density: float = 0.0
    snare_stretch_span: float = 0.35
    snare_stretch_amount: float = 0.8
    gate: float = 1.0
    velocity_spread: float = 0.5
    swing: float = 0.0
    anti_repeat: float = 0.6
    breath_factor: float = 0.35
    position_fidelity: float = 0.0
    sequence_density: float = 0.0
    sequence_max_len: int = 4
    sequence_role_lock: bool = True
    user_motifs: list["UserMotif"] = field(default_factory=list)
    motif_density: float = 0.0
    seed: int = 1
    bars: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UserMotif:
    steps: list[str | None] = field(default_factory=list)
    base_prob: float = 0.0
    role: str = "groove"
    dominant_type: str = "mixed"
    name: str = "Motif"

    def to_dict(self) -> dict:
        return {
            "steps": [step if step is None else str(step) for step in self.steps],
            "base_prob": float(self.base_prob),
            "role": str(self.role),
            "dominant_type": str(self.dominant_type),
            "name": str(self.name),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "UserMotif":
        raw_steps = payload.get("steps", ()) if isinstance(payload, Mapping) else ()
        if not isinstance(raw_steps, (list, tuple)):
            raw_steps = ()
        steps = _normalize_user_motif_steps(raw_steps)
        return cls(
            steps=steps,
            base_prob=float(np.clip(float(payload.get("base_prob", 0.0) or 0.0), 0.0, 1.0)),
            role=_normalize_user_motif_role(str(payload.get("role", "groove") or "groove")),
            dominant_type=_normalize_user_motif_dominant_type(
                str(payload.get("dominant_type", "") or ""),
                steps=steps,
            ),
            name=str(payload.get("name", "Motif") or "Motif").strip() or "Motif",
        )


@dataclass(frozen=True)
class GeneratedPatternStep:
    step_index: int
    label: str
    velocity: int
    source_hit_index: int | None
    source_label: str | None
    source_start_s: float | None
    source_end_s: float | None
    tags: tuple[str, ...] = ()
    relative_velocity_ratio: float | None = None
    source_sequence_index: int | None = None
    source_sequence_role: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GeneratedBreakPattern:
    bars: int
    step_count: int
    seed: int
    swing: float
    params: BreakPatternParams
    event_count: int
    summary: str
    steps: tuple[GeneratedPatternStep, ...]
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["params"] = self.params.to_dict()
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


@dataclass(frozen=True)
class PlacementProbabilityPreview:
    rows: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            row_name: {family: float(weight) for family, weight in weights.items()}
            for row_name, weights in self.rows.items()
        }


@dataclass(frozen=True)
class _ResolvedPatternParams:
    kick_weight: float
    snare_weight: float
    hat_density: float
    ghost_density: float
    fill_strength: float
    repeat_density: float
    repeat_span: float
    repeat_rate: float
    reverse_density: float
    kick_roll_density: float
    kick_roll_span: float
    kick_roll_contrast: float
    snare_stretch_density: float
    snare_stretch_span: float
    snare_stretch_amount: float
    gate: float
    velocity_spread: float
    swing: float
    anti_repeat: float
    breath_factor: float
    position_fidelity: float
    sequence_density: float
    sequence_max_len: int
    sequence_role_lock: bool
    motif_density: float


@dataclass(frozen=True)
class _PatternPools:
    all_hits: tuple[TransientHit, ...]
    by_label: dict[str, tuple[TransientHit, ...]]
    kick: tuple[TransientHit, ...]
    kick_ghost: tuple[TransientHit, ...]
    snare: tuple[TransientHit, ...]
    clap: tuple[TransientHit, ...]
    snare_ghost: tuple[TransientHit, ...]
    snare_ruff: tuple[TransientHit, ...]
    ride: tuple[TransientHit, ...]
    snareish: tuple[TransientHit, ...]
    hatish: tuple[TransientHit, ...]
    otherish: tuple[TransientHit, ...]


@dataclass(frozen=True)
class _SequencePools:
    all_sequences: tuple[HitSequence, ...]
    groove: tuple[HitSequence, ...]
    anticipation: tuple[HitSequence, ...]
    fill: tuple[HitSequence, ...]
    cadence: tuple[HitSequence, ...]


@dataclass(frozen=True)
class _HybridMotifPlacement:
    motif: UserMotif
    start_step_index: int
    consumed_steps: int
    effective_probability: float
    applied_anchors: tuple[tuple[int, str], ...]
    first_event_step_index: int | None = None


_STRONG_STEPS = {1, 9}
_BACKBEAT_STEPS = {5, 13}
_OFFBEAT_STEPS = {3, 7, 11, 15}
_FILL_STEPS = {15, 16}
_RHYTHMIC_TAGS = frozenset({"strong", "backbeat", "offbeat", "subdivision", "phrase_end"})
_POST_MUTATION_TAGS = frozenset({"fill", "resolution", "repeat", "reverse", "kick_roll", "snare_stretch", "snare_stretch_tail"})
_STRUCTURAL_PROTECTION_TAGS = frozenset({"sequence", "anchor"})
_RHYTHMIC_POSITION_RANK = {
    "subdivision": 0,
    "offbeat": 1,
    "backbeat": 2,
    "downbeat": 3,
}
_SUPPORTED_STEP_ANCHORS = frozenset({"kick", "snare", "clap", "hat", "ghost", "other", "silence"})
_USER_MOTIF_STEP_VALUES = frozenset({"kick", "snare", "hat", "ghost", "silence"})
_USER_MOTIF_ROLES = frozenset({"groove", "fill", "cadence", "anticipation"})
_USER_MOTIF_DOMINANT_TYPES = frozenset({"kick", "snare", "hat", "ghost", "mixed"})
_REVERSE_TRIGGER_LABELS = frozenset({"kick", "snare", "clap"})
_KICK_ROLL_TRIGGER_LABELS = frozenset({"kick", "kick_ghost"})
_SNARE_STRETCH_TRIGGER_LABELS = frozenset({"snare", "clap", "snare_ruff"})
_STEP_ANCHOR_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    "kick": ("kick", "kick_ghost"),
    "snare": ("snare", "clap", "snare_ruff"),
    "clap": ("clap", "snare"),
    "hat": ("closed_hat", "open_hat", "ride", "crash"),
    "ghost": ("snare_ghost", "kick_ghost", "snare_ruff"),
    "other": ("perc", "tom", "open_hat", "crash", "ride", "clap"),
    "silence": ("silence",),
}
_VELOCITY_RANGES: dict[str, tuple[int, int]] = {
    "kick": (95, 8),
    "kick_ghost": (42, 14),
    "snare": (90, 12),
    "snare_ghost": (35, 15),
    "snare_ruff": (58, 18),
    "clap": (88, 10),
    "closed_hat": (65, 20),
    "open_hat": (78, 12),
    "crash": (84, 10),
    "ride": (72, 14),
    "ghost_snare": (35, 15),
    "tom": (80, 12),
    "perc": (72, 14),
}


def _rhythmic_position_for_step_index(step_index: int) -> str:
    local_step = ((int(step_index) - 1) % 16) + 1
    if local_step in _STRONG_STEPS:
        return "downbeat"
    if local_step in _BACKBEAT_STEPS:
        return "backbeat"
    if local_step in _OFFBEAT_STEPS:
        return "offbeat"
    return "subdivision"


def _rhythmic_position_bias(
    source_position: str | None,
    target_position: str | None,
    fidelity: float,
) -> float:
    resolved_fidelity = float(np.clip(fidelity, 0.0, 1.0))
    if resolved_fidelity <= 0.0 or not source_position or not target_position:
        return 1.0

    source_rank = _RHYTHMIC_POSITION_RANK.get(str(source_position), 0)
    target_rank = _RHYTHMIC_POSITION_RANK.get(str(target_position), 0)
    distance = abs(source_rank - target_rank)
    if distance == 0:
        return _lerp(1.0, 3.5, resolved_fidelity)
    if distance == 1:
        return _lerp(1.0, 0.55, resolved_fidelity)
    if distance == 2:
        return _lerp(1.0, 0.22, resolved_fidelity)
    return _lerp(1.0, 0.08, resolved_fidelity)


def generate_break_pattern(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    ordered_hits = tuple(sorted(hits, key=lambda hit: (float(hit.start_s), int(hit.index))))
    pools = _build_pools(ordered_hits)
    sequence_pools = _build_sequence_pools(tuple(sequences or ()), max_hit_count=resolved_params.sequence_max_len)
    step_count = max(16, int(max(1, effective_params.bars) * 16))
    normalized_anchors = _normalize_step_anchors(anchors, step_count=step_count)
    rng = np.random.default_rng(int(effective_params.seed))

    generated_steps: list[GeneratedPatternStep] = []
    step_index = 1
    while step_index <= step_count:
        sequence = _pick_sequence_for_step(
            step_index,
            generated_steps,
            sequence_pools,
            pools,
            resolved_params,
            rng,
            anchors=normalized_anchors,
        )
        if sequence is not None:
            generated_steps.extend(_sequence_block_steps(step_index, sequence, anchors=normalized_anchors))
            step_index += int(sequence.total_steps)
            continue
        anchor = normalized_anchors.get(step_index)
        if anchor is not None:
            generated_steps.append(_select_anchored_step_event(step_index, anchor, generated_steps, pools, resolved_params, rng))
            step_index += 1
            continue
        family_weights = _step_family_weights(step_index, generated_steps, pools, resolved_params)
        family = _weighted_choice(family_weights, rng)
        generated_steps.append(_select_step_event(step_index, family, generated_steps, pools, resolved_params, rng))
        step_index += 1

    _inject_ghost_notes(generated_steps, pools, resolved_params, rng)
    _apply_fill_blocks(generated_steps, pools, resolved_params, rng)
    _apply_bar_start_resolutions(generated_steps, pools, resolved_params, rng)
    _apply_kick_rolls(generated_steps, pools, resolved_params, rng, anchors=normalized_anchors)
    _apply_repeat_blocks(generated_steps, resolved_params, rng, anchors=normalized_anchors)
    _enforce_step_anchors(generated_steps, normalized_anchors, pools, resolved_params, rng)
    _apply_snare_stretches(generated_steps, resolved_params, rng, anchors=normalized_anchors)
    _apply_reverse_steps(generated_steps, resolved_params, rng, anchors=normalized_anchors)
    finalized = [_finalize_step_velocity(step, generated_steps, resolved_params, rng) for step in generated_steps]
    return _build_generated_pattern(tuple(finalized), effective_params, resolved_params)


def generate_break_pattern_hybrid(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    user_motifs: Iterable[UserMotif] | None = None,
) -> GeneratedBreakPattern:
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    normalized_motifs = _normalize_user_motifs(
        tuple(user_motifs) if user_motifs is not None else tuple(effective_params.user_motifs)
    )
    if resolved_params.motif_density <= 1e-6 or not normalized_motifs:
        return generate_break_pattern(hits, effective_params, sequences=sequences, anchors=anchors)

    step_count = max(16, int(max(1, effective_params.bars) * 16))
    normalized_anchors = _normalize_step_anchors(anchors, step_count=step_count)
    rng = np.random.default_rng(int(effective_params.seed))
    motif_anchors, _placements = _build_hybrid_motif_anchors(
        normalized_motifs,
        effective_params,
        resolved_params,
        step_count=step_count,
        manual_anchors=normalized_anchors,
        rng=rng,
    )
    combined_anchors = {**motif_anchors, **normalized_anchors}
    hybrid_params = replace(
        effective_params,
        user_motifs=[*normalized_motifs],
    )
    return generate_break_pattern(
        hits,
        hybrid_params,
        sequences=sequences,
        anchors=combined_anchors,
    )


def generate_break_pattern_for_mode(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    use_hybrid: bool = False,
    user_motifs: Iterable[UserMotif] | None = None,
) -> GeneratedBreakPattern:
    if bool(use_hybrid):
        return generate_break_pattern_hybrid(
            hits,
            params,
            sequences=sequences,
            anchors=anchors,
            user_motifs=user_motifs,
        )
    return generate_break_pattern(
        hits,
        params,
        sequences=sequences,
        anchors=anchors,
    )


def reroll_break_pattern_step(
    hits: Iterable[TransientHit],
    pattern: GeneratedBreakPattern,
    step_index: int,
    *,
    seed: int | None = None,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    if step_index < 1 or step_index > int(pattern.step_count):
        raise ValueError("Step index out of range for generated pattern")

    reroll_params = replace(pattern.params, seed=int(seed if seed is not None else pattern.params.seed))
    resolved_params = _resolve_params(reroll_params)
    ordered_hits = tuple(sorted(hits, key=lambda hit: (float(hit.start_s), int(hit.index))))
    pools = _build_pools(ordered_hits)
    sequence_pools = _build_sequence_pools(tuple(sequences or ()), max_hit_count=resolved_params.sequence_max_len)
    normalized_anchors = _normalize_step_anchors(anchors, step_count=int(pattern.step_count))
    rng = np.random.default_rng(int(reroll_params.seed))

    updated_steps = list(pattern.steps)
    previous_steps = updated_steps[: step_index - 1]
    sequence = _pick_sequence_for_step(
        step_index,
        previous_steps,
        sequence_pools,
        pools,
        resolved_params,
        rng,
        anchors=normalized_anchors,
    )
    if sequence is not None:
        rerolled_block = _sequence_block_steps(step_index, sequence, anchors=normalized_anchors)
        rerolled = rerolled_block[0]
    elif normalized_anchors.get(step_index) is not None:
        rerolled = _select_anchored_step_event(
            step_index,
            str(normalized_anchors.get(step_index)),
            previous_steps,
            pools,
            resolved_params,
            rng,
        )
    else:
        family_weights = _step_family_weights(step_index, previous_steps, pools, resolved_params)
        family = _weighted_choice(family_weights, rng)
        rerolled = _select_step_event(step_index, family, previous_steps, pools, resolved_params, rng)

    context_for_velocity = updated_steps.copy()
    context_for_velocity[step_index - 1] = rerolled
    rerolled = _finalize_step_velocity(rerolled, context_for_velocity, resolved_params, rng)
    previous_step = updated_steps[step_index - 2] if step_index > 1 else None
    rerolled = _maybe_reverse_step(
        rerolled,
        resolved_params,
        rng,
        previous_step=previous_step,
        anchors=normalized_anchors,
    )
    updated_steps[step_index - 1] = rerolled
    return _build_generated_pattern(tuple(updated_steps), reroll_params, resolved_params)


def _resolve_params(params: BreakPatternParams) -> _ResolvedPatternParams:
    energy = float(np.clip(params.energy, 0.0, 1.0))
    return _ResolvedPatternParams(
        kick_weight=_scaled_density_control(params.kick_weight, energy, low_scale=0.9, high_scale=1.1),
        snare_weight=_scaled_density_control(params.snare_weight, energy, low_scale=0.9, high_scale=1.1),
        hat_density=_scaled_density_control(params.hat_density, energy, low_scale=0.65, high_scale=1.35),
        ghost_density=_scaled_density_control(params.ghost_density, energy, low_scale=0.4, high_scale=1.55),
        fill_strength=_scaled_density_control(params.fill_strength, energy, low_scale=0.55, high_scale=1.45),
        repeat_density=_scaled_density_control(params.repeat_density, energy, low_scale=0.8, high_scale=1.2),
        repeat_span=float(np.clip(params.repeat_span, 0.0, 1.0)),
        repeat_rate=float(np.clip(params.repeat_rate, 0.0, 1.0)),
        reverse_density=_scaled_density_control(params.reverse_density, energy, low_scale=0.75, high_scale=1.25),
        kick_roll_density=_scaled_density_control(params.kick_roll_density, energy, low_scale=0.72, high_scale=1.35),
        kick_roll_span=float(np.clip(params.kick_roll_span, 0.0, 1.0)),
        kick_roll_contrast=float(np.clip(params.kick_roll_contrast, 0.0, 1.0)),
        snare_stretch_density=_scaled_density_control(
            params.snare_stretch_density,
            energy,
            low_scale=0.72,
            high_scale=1.32,
        ),
        snare_stretch_span=float(np.clip(params.snare_stretch_span, 0.0, 1.0)),
        snare_stretch_amount=float(np.clip(params.snare_stretch_amount, 0.0, 1.0)),
        gate=float(np.clip(params.gate, 0.05, 1.0)),
        velocity_spread=float(np.clip((0.7 * params.velocity_spread) + (0.3 * _lerp(0.15, 0.95, energy)), 0.0, 1.0)),
        swing=float(np.clip(params.swing, 0.0, 1.0)),
        anti_repeat=float(np.clip(params.anti_repeat, 0.0, 1.0)),
        breath_factor=float(np.clip(float(params.breath_factor) * _lerp(1.2, 0.45, energy), 0.0, 1.0)),
        position_fidelity=float(np.clip(params.position_fidelity, 0.0, 1.0)),
        sequence_density=float(np.clip(params.sequence_density, 0.0, 1.0)),
        sequence_max_len=int(np.clip(params.sequence_max_len, 2, MAX_SEQUENCE_HIT_COUNT)),
        sequence_role_lock=bool(params.sequence_role_lock),
        motif_density=float(np.clip(params.motif_density, 0.0, 1.0)),
    )


def _scaled_density_control(
    value: float,
    energy: float,
    *,
    low_scale: float,
    high_scale: float,
    curve: float = 1.0,
) -> float:
    normalized = float(np.clip(value, 0.0, 1.0))
    shaped = float(np.power(normalized, curve))
    return float(np.clip(shaped * _lerp(low_scale, high_scale, energy), 0.0, 1.0))


def _build_pools(hits: tuple[TransientHit, ...]) -> _PatternPools:
    by_label: dict[str, list[TransientHit]] = {}
    for hit in hits:
        by_label.setdefault(hit.label, []).append(hit)
    grouped = {label: tuple(items) for label, items in by_label.items()}
    kick = tuple((*grouped.get("kick", ()), *grouped.get("kick_ghost", ())))
    kick_ghost = grouped.get("kick_ghost", ())
    snare = grouped.get("snare", ())
    clap = grouped.get("clap", ())
    snare_ghost = grouped.get("snare_ghost", ())
    snare_ruff = grouped.get("snare_ruff", ())
    ride = grouped.get("ride", ())
    snareish = tuple((*snare, *clap, *snare_ruff))
    hatish = tuple(
        item
        for label in ("closed_hat", "open_hat", "crash", "ride")
        for item in grouped.get(label, ())
    )
    otherish = tuple(
        item
        for label in ("perc", "tom", "open_hat", "crash", "clap", "snare_ruff", "ride")
        for item in grouped.get(label, ())
    )
    return _PatternPools(
        all_hits=hits,
        by_label=grouped,
        kick=kick,
        kick_ghost=kick_ghost,
        snare=snare,
        clap=clap,
        snare_ghost=snare_ghost,
        snare_ruff=snare_ruff,
        ride=ride,
        snareish=snareish,
        hatish=hatish,
        otherish=otherish,
    )


def _build_sequence_pools(
    sequences: tuple[HitSequence, ...],
    *,
    max_hit_count: int,
) -> _SequencePools:
    filtered = tuple(
        sequence
        for sequence in sequences
        if 2 <= int(sequence.hit_count) <= int(max_hit_count) and int(sequence.total_steps) >= 1
    )
    return _SequencePools(
        all_sequences=filtered,
        groove=tuple(sequence for sequence in filtered if sequence.role == "groove"),
        anticipation=tuple(sequence for sequence in filtered if sequence.role == "anticipation"),
        fill=tuple(sequence for sequence in filtered if sequence.role == "fill"),
        cadence=tuple(sequence for sequence in filtered if sequence.role == "cadence"),
    )


def _normalize_anchor_value(anchor: str | None) -> str | None:
    if anchor is None:
        return None
    normalized = str(anchor).strip().lower().replace(" ", "_")
    if normalized in {"", "auto", "none"}:
        return None
    if normalized in _SUPPORTED_STEP_ANCHORS:
        return normalized
    if normalized in {"closed_hat", "open_hat", "ride", "crash"}:
        return "hat"
    if normalized in {"snare_ghost", "kick_ghost", "ghost_snare"}:
        return "ghost"
    if normalized in {"tom", "perc"}:
        return "other"
    return None


def _normalize_step_anchors(
    anchors: Mapping[int, str | None] | None,
    *,
    step_count: int,
) -> dict[int, str]:
    normalized: dict[int, str] = {}
    if not anchors:
        return normalized
    for raw_step_index, raw_anchor in anchors.items():
        try:
            step_index = int(raw_step_index)
        except (TypeError, ValueError):
            continue
        if step_index < 1 or step_index > int(step_count):
            continue
        anchor = _normalize_anchor_value(raw_anchor)
        if anchor is None:
            continue
        normalized[step_index] = anchor
    return normalized


def _normalize_user_motif_role(role: str | None) -> str:
    normalized = str(role or "groove").strip().lower().replace(" ", "_")
    return normalized if normalized in _USER_MOTIF_ROLES else "groove"


def _normalize_user_motif_steps(raw_steps: Iterable[str | None]) -> list[str | None]:
    normalized: list[str | None] = []
    for raw_step in tuple(raw_steps)[:8]:
        if raw_step is None:
            normalized.append(None)
            continue
        anchor = _normalize_anchor_value(str(raw_step))
        if anchor in _USER_MOTIF_STEP_VALUES:
            normalized.append(anchor)
        elif anchor == "clap":
            normalized.append("snare")
        else:
            normalized.append(None)
    while len(normalized) < 2:
        normalized.append(None)
    return normalized[:8]


def _infer_user_motif_dominant_type(steps: Iterable[str | None]) -> str:
    counts = {"kick": 0, "snare": 0, "hat": 0, "ghost": 0}
    for step in steps:
        if step in counts:
            counts[str(step)] += 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return "mixed"
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return "mixed"
    return str(ranked[0][0])


def _normalize_user_motif_dominant_type(
    dominant_type: str | None,
    *,
    steps: Iterable[str | None],
) -> str:
    normalized = str(dominant_type or "").strip().lower().replace(" ", "_")
    if normalized in _USER_MOTIF_DOMINANT_TYPES:
        return normalized
    return _infer_user_motif_dominant_type(steps)


def _normalize_user_motifs(user_motifs: Iterable[UserMotif] | None) -> tuple[UserMotif, ...]:
    normalized: list[UserMotif] = []
    if not user_motifs:
        return ()
    for raw_motif in user_motifs:
        if not isinstance(raw_motif, UserMotif):
            continue
        steps = _normalize_user_motif_steps(raw_motif.steps)
        if not any(step is not None for step in steps):
            continue
        normalized.append(
            UserMotif(
                steps=steps,
                base_prob=float(np.clip(raw_motif.base_prob, 0.0, 1.0)),
                role=_normalize_user_motif_role(raw_motif.role),
                dominant_type=_normalize_user_motif_dominant_type(raw_motif.dominant_type, steps=steps),
                name=str(raw_motif.name or "Motif").strip() or "Motif",
            )
        )
    return tuple(normalized)


def _user_motif_identity(motif: UserMotif) -> str:
    steps = ",".join(step or "_" for step in motif.steps)
    return f"{motif.name}|{motif.role}|{motif.dominant_type}|{steps}"


def _user_motif_first_event_offset(motif: UserMotif) -> int | None:
    for offset, step in enumerate(motif.steps):
        if step not in {None, "silence"}:
            return int(offset)
    for offset, step in enumerate(motif.steps):
        if step is not None:
            return int(offset)
    return None


def _user_motif_relevant_type_scale(motif: UserMotif, params: _ResolvedPatternParams) -> float:
    direct_scale = {
        "kick": params.kick_weight,
        "snare": params.snare_weight,
        "hat": params.hat_density,
        "ghost": params.ghost_density,
    }
    if motif.dominant_type in direct_scale:
        return float(direct_scale[motif.dominant_type])

    relevant_values: list[float] = []
    for step in motif.steps:
        if step == "kick":
            relevant_values.append(float(params.kick_weight))
        elif step == "snare":
            relevant_values.append(float(params.snare_weight))
        elif step == "hat":
            relevant_values.append(float(params.hat_density))
        elif step == "ghost":
            relevant_values.append(float(params.ghost_density))
    if relevant_values:
        return float(np.mean(relevant_values))
    return float(np.mean((params.kick_weight, params.snare_weight, params.hat_density, params.ghost_density)))


def _user_motif_preferred_position(motif: UserMotif) -> str | None:
    first_offset = _user_motif_first_event_offset(motif)
    first_step = None if first_offset is None else motif.steps[first_offset]
    if first_step == "kick":
        return "downbeat"
    if first_step == "snare":
        return "backbeat"
    if first_step == "hat":
        return "offbeat"
    if first_step == "ghost":
        return "subdivision"
    if motif.role == "fill":
        return "subdivision"
    if motif.role == "anticipation":
        return "offbeat"
    if motif.role == "cadence":
        return "downbeat"
    return "backbeat"


def _user_motif_role_allows_start(motif: UserMotif, start_step_index: int, *, step_count: int) -> bool:
    motif_length = len(motif.steps)
    if motif_length < 2:
        return False
    end_step_index = int(start_step_index) + motif_length - 1
    if end_step_index > int(step_count):
        return False
    if ((int(start_step_index) - 1) // 16) != ((end_step_index - 1) // 16):
        return False

    local_start = ((int(start_step_index) - 1) % 16) + 1
    local_end = ((end_step_index - 1) % 16) + 1
    first_event_offset = _user_motif_first_event_offset(motif)
    first_event_step = int(start_step_index) if first_event_offset is None else int(start_step_index) + int(first_event_offset)
    first_event_position = _rhythmic_position_for_step_index(first_event_step)

    if motif.role == "groove":
        return local_start <= 12 and local_end <= 12
    if motif.role == "fill":
        return local_start >= 13 and local_end <= 16
    if motif.role == "cadence":
        return local_start in _STRONG_STEPS
    if motif.role == "anticipation":
        return first_event_position in {"offbeat", "subdivision"}
    return True


def _user_motif_effective_probability(
    motif: UserMotif,
    params: BreakPatternParams,
    resolved_params: _ResolvedPatternParams,
    *,
    start_step_index: int,
    previous_measure_repeat: bool,
) -> float:
    probability = float(np.clip(motif.base_prob, 0.0, 1.0))
    probability *= float(resolved_params.motif_density)
    probability *= _user_motif_relevant_type_scale(motif, resolved_params)

    if previous_measure_repeat:
        probability *= _lerp(1.0, 0.28, resolved_params.anti_repeat)

    if float(params.energy) > 0.6:
        energy_boost = (float(params.energy) - 0.6) / 0.4
        probability *= _lerp(1.0, 1.45, float(np.clip(energy_boost, 0.0, 1.0)))

    if motif.role == "fill":
        local_start = ((int(start_step_index) - 1) % 16) + 1
        if local_start >= 13:
            probability *= _lerp(1.0, 1.55, resolved_params.fill_strength)

    preferred_position = _user_motif_preferred_position(motif)
    first_event_offset = _user_motif_first_event_offset(motif)
    if first_event_offset is not None:
        target_position = _rhythmic_position_for_step_index(int(start_step_index) + int(first_event_offset))
    else:
        target_position = _rhythmic_position_for_step_index(start_step_index)
    probability *= _rhythmic_position_bias(preferred_position, target_position, resolved_params.position_fidelity)
    return float(np.clip(probability, 0.0, 1.0))


def _prepare_hybrid_motif_candidate(
    motif: UserMotif,
    *,
    start_step_index: int,
    step_count: int,
    manual_anchors: Mapping[int, str],
    placed_anchors: Mapping[int, str],
    params: BreakPatternParams,
    resolved_params: _ResolvedPatternParams,
    previous_measure_repeat: bool,
) -> _HybridMotifPlacement | None:
    if not _user_motif_role_allows_start(motif, start_step_index, step_count=step_count):
        return None

    effective_probability = _user_motif_effective_probability(
        motif,
        params,
        resolved_params,
        start_step_index=start_step_index,
        previous_measure_repeat=previous_measure_repeat,
    )
    if effective_probability <= 1e-6:
        return None

    applied_anchors: list[tuple[int, str]] = []
    consumed_steps = 0
    for offset, raw_step in enumerate(motif.steps):
        target_step_index = int(start_step_index) + int(offset)
        if target_step_index > int(step_count):
            break
        if target_step_index in placed_anchors:
            break
        if target_step_index in manual_anchors:
            break
        step_anchor = _normalize_anchor_value(raw_step)
        if step_anchor in _USER_MOTIF_STEP_VALUES:
            applied_anchors.append((target_step_index, step_anchor))
        consumed_steps = offset + 1

    if consumed_steps <= 0 or not applied_anchors:
        return None
    first_event_offset = _user_motif_first_event_offset(motif)
    first_event_step_index = None if first_event_offset is None else int(start_step_index) + int(first_event_offset)
    return _HybridMotifPlacement(
        motif=motif,
        start_step_index=int(start_step_index),
        consumed_steps=int(consumed_steps),
        effective_probability=float(effective_probability),
        applied_anchors=tuple(applied_anchors),
        first_event_step_index=first_event_step_index,
    )


def _build_hybrid_motif_anchors(
    user_motifs: tuple[UserMotif, ...],
    params: BreakPatternParams,
    resolved_params: _ResolvedPatternParams,
    *,
    step_count: int,
    manual_anchors: Mapping[int, str],
    rng: np.random.Generator,
) -> tuple[dict[int, str], tuple[_HybridMotifPlacement, ...]]:
    placed_anchors: dict[int, str] = {}
    placements: list[_HybridMotifPlacement] = []
    if resolved_params.motif_density <= 1e-6 or not user_motifs:
        return placed_anchors, ()

    previous_measure_motifs: set[str] = set()
    bar_count = max(1, int(step_count) // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        bar_end = min(int(step_count), bar_start + 15)
        cursor = bar_start
        current_measure_motifs: set[str] = set()

        while cursor <= bar_end:
            if cursor in placed_anchors:
                cursor += 1
                continue

            candidates: list[_HybridMotifPlacement] = []
            for motif in user_motifs:
                candidate = _prepare_hybrid_motif_candidate(
                    motif,
                    start_step_index=cursor,
                    step_count=step_count,
                    manual_anchors=manual_anchors,
                    placed_anchors=placed_anchors,
                    params=params,
                    resolved_params=resolved_params,
                    previous_measure_repeat=_user_motif_identity(motif) in previous_measure_motifs,
                )
                if candidate is not None:
                    candidates.append(candidate)

            if not candidates:
                cursor += 1
                continue

            trigger_probability = 1.0
            for candidate in candidates:
                trigger_probability *= 1.0 - float(np.clip(candidate.effective_probability, 0.0, 0.97))
            trigger_probability = 1.0 - trigger_probability
            if float(rng.random()) > float(np.clip(trigger_probability, 0.0, 1.0)):
                cursor += 1
                continue

            weights = np.asarray([candidate.effective_probability for candidate in candidates], dtype=np.float64)
            weights /= float(np.sum(weights))
            chosen_index = int(rng.choice(np.arange(len(candidates), dtype=np.int32), p=weights))
            chosen = candidates[chosen_index]
            for step_index, anchor in chosen.applied_anchors:
                if int(step_index) not in manual_anchors:
                    placed_anchors[int(step_index)] = str(anchor)
            placements.append(chosen)
            current_measure_motifs.add(_user_motif_identity(chosen.motif))
            cursor += max(1, int(chosen.consumed_steps))

        previous_measure_motifs = current_measure_motifs

    return placed_anchors, tuple(placements)


def estimate_user_motif_effective_probability(
    motif: UserMotif,
    params: BreakPatternParams | None = None,
) -> float:
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    normalized_motifs = _normalize_user_motifs((motif,))
    if not normalized_motifs:
        return 0.0
    normalized_motif = normalized_motifs[0]
    best = 0.0
    for start_step_index in range(1, 17):
        if not _user_motif_role_allows_start(normalized_motif, start_step_index, step_count=16):
            continue
        best = max(
            best,
            _user_motif_effective_probability(
                normalized_motif,
                effective_params,
                resolved_params,
                start_step_index=start_step_index,
                previous_measure_repeat=False,
            ),
        )
    return float(np.clip(best, 0.0, 1.0))


def estimate_pattern_family_probabilities(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
) -> PlacementProbabilityPreview:
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    ordered_hits = tuple(sorted(hits, key=lambda hit: (float(hit.start_s), int(hit.index))))
    pools = _build_pools(ordered_hits)
    preview_rows = {
        "downbeat": _normalized_family_weights(_step_family_weights(1, [], pools, resolved_params)),
        "backbeat": _normalized_family_weights(_step_family_weights(5, [], pools, resolved_params)),
        "offbeat": _normalized_family_weights(_step_family_weights(3, [], pools, resolved_params)),
        "subdivision": _normalized_family_weights(_step_family_weights(2, [], pools, resolved_params)),
    }
    return PlacementProbabilityPreview(rows=preview_rows)


def estimate_pattern_effect_probabilities(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
) -> PlacementProbabilityPreview:
    family_preview = estimate_pattern_family_probabilities(hits, params)
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    rows = {
        "downbeat": _estimate_effect_row_probability(
            row_name="downbeat",
            family_preview=family_preview,
            params=resolved_params,
        ),
        "backbeat": _estimate_effect_row_probability(
            row_name="backbeat",
            family_preview=family_preview,
            params=resolved_params,
        ),
        "offbeat": _estimate_effect_row_probability(
            row_name="offbeat",
            family_preview=family_preview,
            params=resolved_params,
        ),
        "subdivision": _estimate_effect_row_probability(
            row_name="subdivision",
            family_preview=family_preview,
            params=resolved_params,
        ),
    }
    return PlacementProbabilityPreview(rows=rows)


def _normalized_family_weights(weights: Mapping[str, float]) -> dict[str, float]:
    normalized = {family: max(0.0, float(weight)) for family, weight in weights.items()}
    total = float(sum(normalized.values()))
    if total <= 1e-9:
        return {family: 0.0 for family in ("kick", "snare", "hat", "ghost", "other", "silence")}
    return {
        family: float(normalized.get(family, 0.0) / total)
        for family in ("kick", "snare", "hat", "ghost", "other", "silence")
    }


def _step_family_weights(
    step_index: int,
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
) -> dict[str, float]:
    local_step = ((step_index - 1) % 16) + 1
    if local_step in _STRONG_STEPS:
        weights = {
            "kick": 1.42 * params.kick_weight,
            "snare": 0.38 * params.snare_weight,
            "hat": 0.18 * params.hat_density,
            "ghost": 0.1 * params.ghost_density,
            "silence": 0.07 + (0.26 * params.breath_factor),
            "other": 0.06,
        }
    elif local_step in _BACKBEAT_STEPS:
        weights = {
            "snare": 1.26 * params.snare_weight,
            "kick": 0.24 * params.kick_weight,
            "hat": 0.16 * params.hat_density,
            "ghost": 0.14 * params.ghost_density,
            "silence": 0.08 + (0.24 * params.breath_factor),
            "other": 0.10,
        }
    elif local_step in _OFFBEAT_STEPS:
        weights = {
            "hat": 1.1 * params.hat_density,
            "ghost": 0.58 * params.ghost_density,
            "kick": 0.22 * params.kick_weight,
            "snare": 0.18 * params.snare_weight,
            "silence": 0.1 + (0.34 * params.breath_factor),
            "other": 0.10,
        }
    else:
        weights = {
            "hat": 0.72 * params.hat_density,
            "ghost": 0.32 * params.ghost_density,
            "silence": 0.16 + (0.58 * params.breath_factor),
            "other": 0.15,
        }

    previous_dense = sum(1 for step in steps[-2:] if step.label != "silence")
    if previous_dense >= 2:
        weights["silence"] = weights.get("silence", 0.0) * (1.0 + (0.55 * params.breath_factor))
        weights["hat"] = weights.get("hat", 0.0) * 1.06

    previous = steps[-1] if steps else None
    if previous is not None and previous.label == "kick":
        weights["silence"] = weights.get("silence", 0.0) * (1.0 + (0.7 * params.breath_factor))
        weights["hat"] = weights.get("hat", 0.0) * 1.14
        weights["ghost"] = weights.get("ghost", 0.0) * 1.08
        weights["kick"] = weights.get("kick", 0.0) * 0.72
        weights["snare"] = weights.get("snare", 0.0) * 0.84

    if local_step in _BACKBEAT_STEPS and not any(step.label in {"snare", "clap"} for step in steps[-4:]):
        weights["snare"] = weights.get("snare", 0.0) * (1.45 + (0.55 * params.snare_weight))

    if local_step == 15:
        weights["other"] = weights.get("other", 0.0) * (1.0 + (1.5 * params.fill_strength))
        weights["hat"] = weights.get("hat", 0.0) * (1.0 + (0.65 * params.fill_strength))
        weights["silence"] = weights.get("silence", 0.0) * max(0.5, 1.0 - (0.45 * params.fill_strength))
    elif local_step == 16:
        if params.fill_strength >= 0.45:
            weights["other"] = weights.get("other", 0.0) * (1.2 + (1.8 * params.fill_strength))
            weights["snare"] = weights.get("snare", 0.0) * (1.0 + (0.8 * params.fill_strength))
            weights["silence"] = weights.get("silence", 0.0) * max(0.35, 1.0 - (0.6 * params.fill_strength))
        else:
            weights["silence"] = weights.get("silence", 0.0) * (1.02 + (0.4 * params.breath_factor))
            weights["hat"] = weights.get("hat", 0.0) * 1.08
            weights["kick"] = weights.get("kick", 0.0) * 0.78

    previous_label = previous.label if previous is not None else ""
    if previous_label in {
        "kick",
        "kick_ghost",
        "snare",
        "snare_ghost",
        "snare_ruff",
        "clap",
        "closed_hat",
        "open_hat",
        "crash",
        "ride",
        "ghost_snare",
        "perc",
        "tom",
    }:
        family = _event_family(previous_label)
        penalty = 1.0 - (0.45 * params.anti_repeat)
        if family == "hat":
            penalty = 1.0 - (0.65 * params.anti_repeat)
        weights[family] = weights.get(family, 0.0) * max(0.15, penalty)

    availability = {
        "kick": bool(pools.kick),
        "snare": bool(pools.snareish),
        "hat": bool(pools.hatish),
        "ghost": bool(pools.snare_ghost or pools.kick_ghost or pools.snareish or pools.kick),
        "other": bool(pools.otherish or pools.hatish),
        "silence": True,
    }
    for family, available in availability.items():
        if not available:
            weights[family] = 0.0

    if availability["kick"] and local_step in _STRONG_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.1 + (0.12 * params.breath_factor))
    elif availability["snare"] and local_step in _BACKBEAT_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.11 + (0.14 * params.breath_factor))
    elif availability["hat"] and local_step in _OFFBEAT_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.13 + (0.18 * params.breath_factor))
    return weights


def _estimate_effect_row_probability(
    *,
    row_name: str,
    family_preview: PlacementProbabilityPreview,
    params: _ResolvedPatternParams,
) -> dict[str, float]:
    step_indices = _preview_step_indices_for_row(row_name)
    if not step_indices:
        return {"repeat": 0.0, "reverse": 0.0, "kick_roll": 0.0, "snare_stretch": 0.0}

    repeat_scores: list[float] = []
    reverse_scores: list[float] = []
    kick_roll_scores: list[float] = []
    snare_stretch_scores: list[float] = []
    row_weights = family_preview.rows.get(row_name, {})
    for step_index in step_indices:
        repeat_score = 0.0
        for family, probability in row_weights.items():
            if probability <= 1e-6:
                continue
            preview_step = _preview_step_from_family(step_index, family)
            normalized_weight = float(np.clip(_repeat_glitch_weight(preview_step, step_index=step_index) / 1.35, 0.0, 1.0))
            repeat_score += float(probability) * normalized_weight
        repeat_scores.append(float(np.clip(params.repeat_density * repeat_score * 0.92, 0.0, 1.0)))

        reverse_score = 0.0
        if _rhythmic_position_for_step_index(step_index) == "subdivision":
            previous_row = _row_name_for_step_index(step_index - 1)
            previous_weights = family_preview.rows.get(previous_row, {})
            for previous_family, previous_probability in previous_weights.items():
                if previous_probability <= 1e-6:
                    continue
                trigger_step = _preview_step_from_family(step_index - 1, previous_family)
                for current_family, current_probability in row_weights.items():
                    if current_probability <= 1e-6:
                        continue
                    target_step = _preview_step_from_family(step_index, current_family)
                    normalized_weight = float(
                        np.clip(
                            _reverse_transition_weight(trigger_step, target_step, step_index=step_index) / 1.32,
                            0.0,
                            1.0,
                        )
                    )
                    reverse_score += float(previous_probability) * float(current_probability) * normalized_weight
        reverse_scores.append(float(np.clip(params.reverse_density * reverse_score * 0.98, 0.0, 1.0)))

        kick_roll_score = 0.0
        local_step = ((int(step_index) - 1) % 16) + 1

        def _kick_roll_trigger_preview_score(trigger_weights: Mapping[str, float]) -> float:
            trigger_kick = float(trigger_weights.get("kick", 0.0))
            trigger_snareish = float(trigger_weights.get("snare", 0.0))
            trigger_hatish = float(trigger_weights.get("hat", 0.0))
            trigger_ghost = float(trigger_weights.get("ghost", 0.0))
            trigger_other = float(trigger_weights.get("other", 0.0))
            trigger_silence = float(trigger_weights.get("silence", 0.0))
            trigger_drive = (
                (1.1 * trigger_kick)
                + (_lerp(0.18, 0.92, params.kick_roll_density) * trigger_snareish)
                + (_lerp(0.12, 0.72, params.kick_roll_density) * trigger_hatish)
                + (_lerp(0.1, 0.68, params.kick_roll_density) * trigger_ghost)
                + (_lerp(0.08, 0.6, params.kick_roll_density) * trigger_other)
                + (_lerp(0.04, 0.42, params.kick_roll_density) * trigger_silence)
            )
            kick_bias = _lerp(0.28, 1.0, params.kick_weight)
            return float(np.clip(trigger_drive * kick_bias * _lerp(0.42, 1.2, params.kick_roll_density), 0.0, 1.0))

        if local_step in _BACKBEAT_STEPS:
            kick_roll_score = _kick_roll_trigger_preview_score(row_weights)
        elif local_step in {6, 14}:
            trigger_row = family_preview.rows.get("backbeat", {})
            kick_roll_score = _kick_roll_trigger_preview_score(trigger_row) * 0.92
        elif local_step in {7, 15}:
            trigger_row = family_preview.rows.get("backbeat", {})
            kick_roll_score = _kick_roll_trigger_preview_score(trigger_row) * 1.0
        elif local_step in {8, 16}:
            trigger_row = family_preview.rows.get("backbeat", {})
            kick_roll_score = _kick_roll_trigger_preview_score(trigger_row) * _lerp(0.48, 0.86, params.kick_roll_span)

        kick_roll_scores.append(float(np.clip(params.kick_roll_density * kick_roll_score, 0.0, 1.0)))

        snare_stretch_score = 0.0
        for family, probability in row_weights.items():
            if probability <= 1e-6:
                continue
            preview_step = _preview_step_from_family(step_index, family)
            normalized_weight = float(
                np.clip(
                    _snare_stretch_weight(preview_step, step_index=step_index, params=params) / 1.45,
                    0.0,
                    1.0,
                )
            )
            snare_stretch_score += float(probability) * normalized_weight
        snare_stretch_scores.append(
            float(
                np.clip(
                    params.snare_stretch_density
                    * snare_stretch_score
                    * _lerp(0.78, 1.12, params.snare_stretch_amount),
                    0.0,
                    1.0,
                )
            )
        )

    return {
        "repeat": float(np.mean(repeat_scores)) if repeat_scores else 0.0,
        "reverse": float(np.mean(reverse_scores)) if reverse_scores else 0.0,
        "kick_roll": float(np.mean(kick_roll_scores)) if kick_roll_scores else 0.0,
        "snare_stretch": float(np.mean(snare_stretch_scores)) if snare_stretch_scores else 0.0,
    }


def _preview_step_indices_for_row(row_name: str) -> tuple[int, ...]:
    mapping = {
        "downbeat": (1, 9),
        "backbeat": (5, 13),
        "offbeat": (3, 7, 11, 15),
        "subdivision": (2, 4, 6, 8, 10, 12, 14, 16),
    }
    return mapping.get(str(row_name), ())


def _row_name_for_step_index(step_index: int) -> str:
    rhythmic_position = _rhythmic_position_for_step_index(step_index)
    if rhythmic_position == "downbeat":
        return "downbeat"
    if rhythmic_position == "backbeat":
        return "backbeat"
    if rhythmic_position == "offbeat":
        return "offbeat"
    return "subdivision"


def _preview_step_from_family(step_index: int, family: str) -> GeneratedPatternStep:
    label_map = {
        "kick": "kick",
        "snare": "snare",
        "hat": "closed_hat",
        "ghost": "snare_ghost",
        "other": "perc",
        "silence": "silence",
    }
    label = label_map.get(str(family), "perc")
    return GeneratedPatternStep(
        step_index=int(step_index),
        label=label,
        velocity=0,
        source_hit_index=None,
        source_label=label if label != "silence" else None,
        source_start_s=0.0 if label != "silence" else None,
        source_end_s=0.1 if label != "silence" else None,
        tags=(_step_tag(step_index),),
    )


def _pick_sequence_for_step(
    step_index: int,
    steps: list[GeneratedPatternStep],
    sequence_pools: _SequencePools,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
) -> HitSequence | None:
    if params.sequence_density <= 0.0 or not sequence_pools.all_sequences:
        return None
    if float(rng.random()) > params.sequence_density:
        return None

    local_step = ((step_index - 1) % 16) + 1
    remaining_steps = 16 - local_step + 1
    target_position = _rhythmic_position_for_step_index(step_index)
    weighted_sequences: list[tuple[HitSequence, float]] = []
    for sequence in sequence_pools.all_sequences:
        total_steps = int(sequence.total_steps)
        if total_steps > remaining_steps:
            continue

        zone_match = _sequence_zone_match(sequence, local_step=local_step, params=params)
        if params.sequence_role_lock and zone_match <= 0.0:
            continue
        if zone_match <= 0.0:
            zone_match = 0.3

        density_weight = 1.0 + (0.12 * float(sequence.hit_count))
        role_weight = 1.0
        if sequence.role == "fill":
            role_weight += 0.2 + (0.4 * params.fill_strength)
        elif sequence.role == "groove":
            role_weight += 0.2 * params.sequence_density
        elif sequence.role == "anticipation":
            role_weight += 0.18
        elif sequence.role == "cadence":
            role_weight += 0.12

        if _sequence_conflicts_with_pillars(
            sequence,
            step_index=step_index,
            steps=steps,
            pools=pools,
            anchors=anchors,
        ):
            continue
        anchor_position = sequence.events[0].rhythmic_position if sequence.events else None
        position_weight = _rhythmic_position_bias(anchor_position, target_position, params.position_fidelity)
        weighted_sequences.append((sequence, max(0.01, zone_match * density_weight * role_weight * position_weight)))

    if not weighted_sequences:
        return None
    return _pick_weighted_sequence(weighted_sequences, rng)


def _sequence_zone_match(
    sequence: HitSequence,
    *,
    local_step: int,
    params: _ResolvedPatternParams,
) -> float:
    end_step = local_step + int(sequence.total_steps) - 1
    if end_step > 16:
        return 0.0
    if not params.sequence_role_lock:
        if sequence.role == "fill" and local_step >= 13:
            return 1.15
        if sequence.role == "groove" and end_step <= 12:
            return 1.1
        if sequence.role == "anticipation" and end_step in {5, 9, 13}:
            return 1.1
        if sequence.role == "cadence" and local_step in {1, 9}:
            return 1.1
        return 0.7

    if sequence.role == "fill":
        return 1.2 if local_step >= 13 and end_step <= 16 else 0.0
    if sequence.role == "groove":
        return 1.1 if local_step <= 12 and end_step <= 12 else 0.0
    if sequence.role == "anticipation":
        return 1.1 if local_step < end_step and end_step in {5, 9, 13} else 0.0
    if sequence.role == "cadence":
        return 1.0 if local_step in {1, 9} else 0.0
    return 0.0


def _sequence_conflicts_with_pillars(
    sequence: HitSequence,
    *,
    step_index: int,
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    anchors: Mapping[int, str] | None = None,
) -> bool:
    by_offset = {int(event.start_offset_steps): event for event in sequence.events}
    if anchors:
        for offset in range(int(sequence.total_steps)):
            anchor = anchors.get(int(step_index + offset))
            if anchor is None:
                continue
            if not _sequence_event_matches_anchor(by_offset.get(offset), anchor):
                return True

    if not steps:
        return False
    existing_pillars = {
        int(step.step_index)
        for step in steps
        if step.label in {"kick", "snare", "clap"}
    }
    if not existing_pillars:
        return False
    targeted_steps = {
        int(step_index + int(event.start_offset_steps))
        for event in sequence.events
        if event.label in {"kick", "snare", "clap"}
    }
    return bool(existing_pillars & targeted_steps and not pools.kick and not pools.snareish)


def _sequence_event_matches_anchor(event: HitSequenceEvent | None, anchor: str) -> bool:
    if anchor == "silence":
        return event is None
    if event is None:
        return False
    return _label_matches_anchor(event.label, anchor)


def _pick_weighted_sequence(
    weighted_sequences: list[tuple[HitSequence, float]],
    rng: np.random.Generator,
) -> HitSequence | None:
    if not weighted_sequences:
        return None
    weights = np.asarray([max(1e-4, float(weight)) for _, weight in weighted_sequences], dtype=np.float64)
    weights /= float(np.sum(weights))
    index = int(rng.choice(len(weighted_sequences), p=weights))
    return weighted_sequences[index][0]


def _sequence_block_steps(
    step_index: int,
    sequence: HitSequence,
    *,
    anchors: Mapping[int, str] | None = None,
) -> list[GeneratedPatternStep]:
    by_offset = {int(event.start_offset_steps): event for event in sequence.events}
    rendered: list[GeneratedPatternStep] = []
    for offset in range(int(sequence.total_steps)):
        current_step = step_index + offset
        anchor = None if anchors is None else anchors.get(current_step)
        event = by_offset.get(offset)
        if event is None:
            base_tags = _tags_with_owner(("sequence", f"sequence_{sequence.role}", "sequence_gap"), "sequence")
            if anchor is not None:
                base_tags = (*base_tags, "anchor", f"anchor_{anchor}")
            rendered.append(
                GeneratedPatternStep(
                    step_index=current_step,
                    label="silence",
                    velocity=0,
                    source_hit_index=None,
                    source_label=None,
                    source_start_s=None,
                    source_end_s=None,
                    tags=tuple(dict.fromkeys((_step_tag(current_step), *base_tags))),
                    relative_velocity_ratio=None,
                    source_sequence_index=int(sequence.index),
                    source_sequence_role=sequence.role,
                )
            )
            continue
        rendered.append(_sequence_step_from_event(current_step, sequence, event, anchor=anchor))
    return rendered


def _sequence_step_from_event(
    step_index: int,
    sequence: HitSequence,
    event: HitSequenceEvent,
    *,
    anchor: str | None = None,
) -> GeneratedPatternStep:
    tags = [_step_tag(step_index), *_tags_with_owner(("sequence", f"sequence_{sequence.role}", event.role), "sequence")]
    if anchor is not None:
        tags.extend(("anchor", f"anchor_{anchor}"))
    return GeneratedPatternStep(
        step_index=step_index,
        label=event.label,
        velocity=0,
        source_hit_index=int(event.hit_index),
        source_label=event.label,
        source_start_s=float(event.source_start_s),
        source_end_s=float(event.source_end_s),
        tags=tuple(dict.fromkeys(tags)),
        relative_velocity_ratio=float(event.velocity_ratio),
        source_sequence_index=int(sequence.index),
        source_sequence_role=sequence.role,
    )


def _label_matches_anchor(label: str, anchor: str) -> bool:
    compatible = _STEP_ANCHOR_COMPATIBILITY.get(anchor, ())
    return str(label) in compatible


def _generated_step_matches_anchor(step: GeneratedPatternStep, anchor: str) -> bool:
    if anchor == "silence":
        return step.label == "silence"
    return _label_matches_anchor(step.label, anchor)


def _pick_anchor_hit(
    anchor: str,
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    compatible_labels = _STEP_ANCHOR_COMPATIBILITY.get(anchor, ())
    weighted_hits: list[tuple[TransientHit, float]] = []
    for label in compatible_labels:
        for hit in pools.by_label.get(label, ()):
            weight = 1.0
            if label == anchor:
                weight *= 1.9
            elif anchor == "snare" and label == "clap":
                weight *= 0.75
            elif anchor == "clap" and label == "snare":
                weight *= 0.82
            elif anchor == "kick" and label == "kick_ghost":
                weight *= 0.45
            elif anchor == "ghost" and label == "snare_ruff":
                weight *= 0.72
            weighted_hits.append((hit, weight))

    if not weighted_hits:
        if anchor == "kick":
            return _pick_hit(
                pools.kick,
                rng,
                previous_source_index,
                previous_source_label,
                params,
                target_step_index=step_index,
            )
        if anchor == "snare":
            return _pick_snareish_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        if anchor == "hat":
            return _pick_hat_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        if anchor == "ghost":
            return _pick_ghost_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        if anchor == "other":
            return _pick_other_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        return None

    return _pick_weighted_hit(
        weighted_hits,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )


def _select_anchored_step_event(
    step_index: int,
    anchor: str,
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> GeneratedPatternStep:
    tags = [_step_tag(step_index), "anchor", f"anchor_{anchor}", "owner_anchor"]
    if ((step_index - 1) % 16) + 1 in _FILL_STEPS:
        tags.append("phrase_end")

    previous = steps[-1] if steps else None
    previous_source_index = previous.source_hit_index if previous is not None else None
    previous_source_label = previous.source_label if previous is not None else None

    if anchor == "silence":
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple(tags))

    hit = _pick_anchor_hit(
        anchor,
        step_index,
        pools,
        rng,
        previous_source_index,
        previous_source_label,
        params,
    )
    if hit is None:
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple((*tags, "anchor_unresolved")))
    return _event_from_hit(step_index, hit, tags)


def _select_step_event(
    step_index: int,
    family: str,
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> GeneratedPatternStep:
    tags = [_step_tag(step_index), "owner_skeleton"]
    if ((step_index - 1) % 16) + 1 in _FILL_STEPS:
        tags.append("phrase_end")
    previous = steps[-1] if steps else None
    previous_source_index = previous.source_hit_index if previous is not None else None
    previous_source_label = previous.source_label if previous is not None else None

    if family == "silence":
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple(tags))

    if family == "kick":
        hit = _pick_hit(
            pools.kick,
            rng,
            previous_source_index,
            previous_source_label,
            params,
            target_step_index=step_index,
        )
        return _event_from_hit(step_index, hit, tags)

    if family == "snare":
        hit = _pick_snareish_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        return _event_from_hit(step_index, hit, tags)

    if family == "hat":
        hit = _pick_hat_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        return _event_from_hit(step_index, hit, tags)

    if family == "ghost":
        hit = _pick_ghost_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
        ghost_label = "snare_ghost"
        if hit is not None and hit.label in {"snare_ghost", "kick_ghost"}:
            ghost_label = hit.label
        elif hit is not None and hit.label == "kick":
            ghost_label = "kick_ghost"
        return GeneratedPatternStep(
            step_index=step_index,
            label=ghost_label,
            velocity=0,
            source_hit_index=hit.index if hit is not None else None,
            source_label=hit.label if hit is not None else None,
            source_start_s=hit.start_s if hit is not None else None,
            source_end_s=hit.end_s if hit is not None else None,
            tags=tuple((*tags, "ghost")),
        )

    hit = _pick_other_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
    if hit is None:
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple(tags))
    return _event_from_hit(step_index, hit, tags)


def _pick_snareish_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    weighted_hits: list[tuple[TransientHit, float]] = []
    local_step = ((step_index - 1) % 16) + 1
    for hit in pools.snareish:
        base_weight = 1.0
        if hit.label == "snare":
            base_weight *= 1.15 if local_step in _BACKBEAT_STEPS else 1.0
        if hit.label == "clap":
            base_weight *= 1.05 if local_step in _BACKBEAT_STEPS else 0.92
        if hit.label == "snare_ruff":
            if local_step in _FILL_STEPS:
                base_weight *= 1.45
            elif local_step in _BACKBEAT_STEPS:
                base_weight *= 0.28
            else:
                base_weight *= 0.55
        weighted_hits.append((hit, base_weight))
    return _pick_weighted_hit(
        weighted_hits,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )


def _pick_ghost_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in (*pools.snare_ghost, *pools.kick_ghost):
        base_weight = 1.2 if hit.label == "snare_ghost" else 0.9
        weighted_hits.append((hit, base_weight))
    if weighted_hits:
        return _pick_weighted_hit(
            weighted_hits,
            rng,
            previous_source_index,
            previous_source_label,
            params,
            target_step_index=step_index,
        )
    snare_fallback = _pick_snareish_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
    if snare_fallback is not None:
        return snare_fallback
    return _pick_hit(
        pools.kick,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )


def _pick_hat_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    weighted_hits: list[tuple[TransientHit, float]] = []
    local_step = ((step_index - 1) % 16) + 1
    for hit in pools.hatish:
        base_weight = 1.0
        if hit.label == "closed_hat":
            base_weight *= 1.15
        elif hit.label == "open_hat":
            base_weight *= 1.35 if local_step in _FILL_STEPS else 0.75
        elif hit.label == "crash":
            base_weight *= 1.4 if local_step in {1, 16} else 0.45
        elif hit.label == "ride":
            base_weight *= 0.95 if local_step in _OFFBEAT_STEPS else 1.05
        weighted_hits.append((hit, base_weight))
    return _pick_weighted_hit(
        weighted_hits,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )


def _pick_other_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    weighted_hits: list[tuple[TransientHit, float]] = []
    local_step = ((step_index - 1) % 16) + 1
    for hit in pools.otherish:
        base_weight = 1.0
        if hit.label in {"perc", "tom"}:
            base_weight *= 1.12
        if local_step in _FILL_STEPS and hit.label in {"perc", "tom", "clap", "open_hat", "crash"}:
            base_weight *= 1.25
        weighted_hits.append((hit, base_weight))
    if not weighted_hits:
        for hit in pools.hatish:
            weighted_hits.append((hit, 0.65))
    return _pick_weighted_hit(
        weighted_hits,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )


def _pick_hit(
    pool: tuple[TransientHit, ...],
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
    *,
    target_step_index: int | None = None,
) -> TransientHit | None:
    return _pick_weighted_hit(
        [(hit, 1.0) for hit in pool],
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=target_step_index,
    )


def _pick_weighted_hit(
    weighted_hits: list[tuple[TransientHit, float]],
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
    *,
    target_step_index: int | None = None,
) -> TransientHit | None:
    if not weighted_hits:
        return None

    target_position = _rhythmic_position_for_step_index(target_step_index) if target_step_index is not None else None
    weights: list[float] = []
    for hit, base_weight in weighted_hits:
        weight = max(0.01, float(base_weight) * (0.45 + hit.confidence))
        weight *= _rhythmic_position_bias(hit.rhythmic_position, target_position, params.position_fidelity)
        if previous_source_index is not None and hit.index == previous_source_index:
            weight *= max(0.08, 1.0 - (0.85 * params.anti_repeat))
        if previous_source_label is not None and hit.label == previous_source_label:
            extra_penalty = 0.7 if hit.label in {"closed_hat", "open_hat", "crash"} else 0.45
            weight *= max(0.08, 1.0 - (extra_penalty * params.anti_repeat))
        weights.append(max(weight, 1e-4))

    normalized = np.asarray(weights, dtype=np.float64)
    normalized /= float(np.sum(normalized))
    index = int(rng.choice(len(weighted_hits), p=normalized))
    return weighted_hits[index][0]


def _inject_ghost_notes(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if not (pools.snareish or pools.snare_ghost or pools.kick_ghost) or params.ghost_density <= 0.0:
        return

    snare_steps = [
        step.step_index
        for step in steps
        if step.label in {"snare", "clap", "snare_ruff"}
    ]
    if not snare_steps:
        return

    candidate_steps = []
    for snare_step in snare_steps:
        local_step = ((snare_step - 1) % 16) + 1
        for candidate in (local_step - 2, local_step + 2):
            if 1 <= candidate <= len(steps) and candidate in _OFFBEAT_STEPS:
                candidate_steps.append(candidate)

    seen = set()
    for candidate in candidate_steps:
        if candidate in seen:
            continue
        seen.add(candidate)
        current = steps[candidate - 1]
        if "sequence" in current.tags:
            continue
        if current.label not in {"silence", "closed_hat", "open_hat", "perc", "ride"}:
            continue
        if float(rng.random()) > (0.25 + (0.55 * params.ghost_density)):
            continue
        replacement = _select_step_event(
            candidate,
            "ghost",
            steps[: candidate - 1],
            pools,
            params,
            rng,
        )
        steps[candidate - 1] = replacement


def _apply_fill_blocks(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if not steps:
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        _apply_bar_end_fill(steps, bar_start, pools, params, rng)


def _apply_bar_end_fill(
    steps: list[GeneratedPatternStep],
    bar_start: int,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    tail_steps = [steps[index - 1] for index in range(bar_start + 12, min(bar_start + 16, len(steps) + 1))]
    if any(_step_is_structurally_protected(step) for step in tail_steps):
        return

    fill_probability = 0.18 + (0.72 * params.fill_strength)
    release_probability = 0.42 + (0.42 * params.fill_strength)
    if float(rng.random()) > fill_probability:
        return

    step13 = bar_start + 12
    step14 = bar_start + 13
    step15 = bar_start + 14
    step16 = bar_start + 15
    if step16 > len(steps):
        return

    templates: list[str] = ["resolve"]
    if pools.snare_ruff or pools.snareish:
        templates.append("snare_run")
    if pools.kick:
        templates.append("double_kick")
    if pools.otherish:
        templates.append("perc_burst")

    template = str(rng.choice(templates))

    if step13 <= len(steps):
        current = steps[step13 - 1]
        if current.label not in {"snare", "clap"} and (pools.snareish or pools.clap):
            hit = _pick_fill_backbeat_hit(step13, pools, rng, params)
            if hit is not None:
                steps[step13 - 1] = _override_step_from_hit(step13, hit, ("fill", "backbeat_fill"))

    if template == "snare_run":
        hit14 = _pick_fill_texture_hit(step14, pools, rng, params)
        hit15 = _pick_fill_snare_hit(step15, pools, rng, params)
        hit16 = _pick_fill_release_hit(step16, pools, rng, params)
    elif template == "double_kick":
        hit14 = _pick_fill_texture_hit(step14, pools, rng, params)
        hit15 = _pick_fill_kick_hit(step15, pools, rng, params)
        hit16 = _pick_fill_kick_hit(step16, pools, rng, params)
        if hit16 is None or float(rng.random()) <= 0.32:
            hit16 = _pick_fill_release_hit(step16, pools, rng, params)
    elif template == "perc_burst":
        hit14 = _pick_fill_other_hit(step14, pools, rng, params)
        hit15 = _pick_fill_snare_hit(step15, pools, rng, params) or _pick_fill_other_hit(step15, pools, rng, params)
        hit16 = _pick_fill_release_hit(step16, pools, rng, params)
    else:
        hit14 = _pick_fill_texture_hit(step14, pools, rng, params)
        hit15 = _pick_fill_snare_hit(step15, pools, rng, params) if float(rng.random()) <= (0.45 + (0.35 * params.fill_strength)) else None
        hit16 = _pick_fill_release_hit(step16, pools, rng, params) if float(rng.random()) <= release_probability else None

    planned_indices = [index for index in (step14, step15, step16) if 1 <= index <= len(steps)]
    if step13 <= len(steps):
        current = steps[step13 - 1]
        if current.label not in {"snare", "clap"} and (pools.snareish or pools.clap):
            planned_indices.append(step13)
    if not _bar_has_post_mutation_capacity(
        steps,
        bar_start=bar_start,
        bar_end=min(len(steps), bar_start + 15),
        target_step_indices=planned_indices,
        params=params,
    ):
        return

    if step14 <= len(steps):
        steps[step14 - 1] = _override_step_from_hit(step14, hit14, ("fill", "lift"))
    if step15 <= len(steps):
        steps[step15 - 1] = _override_step_from_hit(step15, hit15, ("fill", "drive"))

    if hit16 is not None:
        steps[step16 - 1] = _override_step_from_hit(step16, hit16, ("fill", "release"))
    else:
        current = steps[step16 - 1]
        if template != "resolve" or current.label in {"closed_hat", "ride", "kick_ghost", "snare_ghost", "perc", "tom"}:
            steps[step16 - 1] = _override_step_from_hit(step16, None, ("fill", "release"))


def _apply_bar_start_resolutions(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if not steps:
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        previous_bar_start = ((bar_index - 1) % bar_count) * 16 + 1
        tail_steps = [
            steps[index - 1]
            for index in range(previous_bar_start + 12, previous_bar_start + 16)
            if 1 <= index <= step_count
        ]
        if not tail_steps:
            continue

        had_fill_tail = any("fill" in tag for step in tail_steps for tag in step.tags)
        if not had_fill_tail:
            continue

        current = steps[bar_start - 1]
        if _step_is_structurally_protected(current):
            continue
        if params.fill_strength < 0.8 and float(rng.random()) > (0.22 + (0.48 * params.fill_strength)):
            continue
        if params.fill_strength < 0.8 and not _bar_has_post_mutation_capacity(
            steps,
            bar_start=bar_start,
            bar_end=min(step_count, bar_start + 15),
            target_step_indices=(bar_start,),
            params=params,
        ):
            continue
        if current.label == "kick":
            steps[bar_start - 1] = replace(
                current,
                tags=tuple(dict.fromkeys((*current.tags, "resolution", "downbeat", "owner_fill"))),
            )
            continue
        if current.label in {"open_hat", "crash"} and (not pools.kick or params.kick_weight <= 1e-3):
            steps[bar_start - 1] = replace(
                current,
                tags=tuple(dict.fromkeys((*current.tags, "resolution", "downbeat", "owner_fill"))),
            )
            continue

        resolution_hit = _pick_bar_start_resolution_hit(bar_start, pools, rng, params)
        if resolution_hit is not None:
            steps[bar_start - 1] = _override_step_from_hit(bar_start, resolution_hit, ("resolution", "downbeat"))


def _apply_repeat_blocks(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
) -> None:
    if params.repeat_density <= 1e-3 or len(steps) < 4:
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        bar_end = min(step_count, bar_start + 15)
        weighted_candidates: list[tuple[int, float, int]] = []
        for step_index in range(bar_start, bar_end + 1):
            current = steps[step_index - 1]
            if anchors and int(step_index) in anchors:
                continue
            weight = _repeat_glitch_weight(current, step_index=step_index)
            if weight <= 1e-6:
                continue
            max_span = _repeat_glitch_max_span(
                steps,
                start_step_index=step_index,
                bar_end=bar_end,
                anchors=anchors,
            )
            if max_span <= 0:
                continue
            span_bonus = 1.0 + (0.08 * float(max_span - 1) * float(params.repeat_span))
            weighted_candidates.append((int(step_index), float(weight * span_bonus), int(max_span)))

        if not weighted_candidates:
            continue

        glitch_slots = 1
        if params.repeat_density >= 0.45 and len(weighted_candidates) >= 2:
            glitch_slots += 1
        if params.repeat_density >= 0.8 and len(weighted_candidates) >= 4 and float(rng.random()) < 0.5:
            glitch_slots += 1

        for _ in range(min(glitch_slots, len(weighted_candidates))):
            candidate_steps = np.asarray([step_index for step_index, _, _ in weighted_candidates], dtype=np.int32)
            candidate_weights = np.asarray([weight for _, weight, _ in weighted_candidates], dtype=np.float64)
            weight_sum = float(np.sum(candidate_weights))
            if candidate_steps.size == 0 or weight_sum <= 1e-9:
                break
            candidate_weights /= weight_sum
            chosen_step_index = int(rng.choice(candidate_steps, p=candidate_weights))
            current = steps[chosen_step_index - 1]
            max_span = next(
                (span for step_index, _weight, span in weighted_candidates if int(step_index) == chosen_step_index),
                1,
            )
            zone_span = _choose_repeat_glitch_zone_span(params=params, rng=rng, max_span=int(max_span))
            repeat_count = _choose_repeat_glitch_count(current, params=params, rng=rng)
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=bar_end,
                target_step_indices=range(chosen_step_index, chosen_step_index + zone_span),
                params=params,
            ):
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue
            for zone_offset in range(zone_span):
                target_step_index = chosen_step_index + zone_offset
                current_step = steps[target_step_index - 1]
                steps[target_step_index - 1] = _clone_step_for_repeat_glitch(
                    current_step,
                    repeat_count=repeat_count,
                    zone_span=zone_span,
                    zone_offset=zone_offset,
                )
            weighted_candidates = [
                (step_index, weight, span)
                for step_index, weight, span in weighted_candidates
                if int(step_index) < chosen_step_index - 1
                or int(step_index) > chosen_step_index + zone_span
            ]


def _repeat_glitch_max_span(
    steps: list[GeneratedPatternStep],
    *,
    start_step_index: int,
    bar_end: int,
    anchors: Mapping[int, str] | None = None,
) -> int:
    max_span = 0
    last_index = min(int(bar_end), int(start_step_index) + 3)
    for target_step_index in range(int(start_step_index), last_index + 1):
        if anchors and int(target_step_index) in anchors:
            break
        weight = _repeat_glitch_weight(steps[target_step_index - 1], step_index=target_step_index)
        if weight <= 1e-6:
            break
        max_span += 1
    return int(max_span)


def _choose_repeat_glitch_zone_span(
    *,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    max_span: int,
) -> int:
    upper_bound = max(1, min(int(max_span), 4))
    span_weights: list[tuple[int, float]] = []
    for span in range(1, upper_bound + 1):
        weight = {
            1: _lerp(1.8, 0.4, params.repeat_span),
            2: _lerp(0.95, 1.25, params.repeat_span),
            3: _lerp(0.3, 1.1, params.repeat_span),
            4: _lerp(0.08, 0.95, params.repeat_span),
        }.get(span, 0.0)
        if weight > 1e-6:
            span_weights.append((span, float(weight)))

    if not span_weights:
        return 1

    labels = np.asarray([span for span, _ in span_weights], dtype=np.int32)
    values = np.asarray([weight for _, weight in span_weights], dtype=np.float64)
    values /= float(np.sum(values))
    return int(rng.choice(labels, p=values))


def _repeat_glitch_weight(step: GeneratedPatternStep, *, step_index: int) -> float:
    if step.label == "silence":
        return 0.0

    tags = set(step.tags)
    if (
        "repeat" in tags
        or "sequence_gap" in tags
        or "fill" in tags
        or "resolution" in tags
        or "kick_roll" in tags
        or "sequence" in tags
        or "anchor" in tags
    ):
        return 0.0

    local_step = ((int(step_index) - 1) % 16) + 1
    family = _event_family(step.label)
    base_weight = {
        "hat": 1.35,
        "ghost": 1.15,
        "other": 0.95,
        "snare": 0.72,
        "kick": 0.48,
        "silence": 0.0,
    }.get(family, 0.6)

    if local_step in _OFFBEAT_STEPS:
        base_weight *= 1.18
    elif local_step in _BACKBEAT_STEPS:
        base_weight *= 0.82
    elif local_step in _STRONG_STEPS:
        base_weight *= 0.58
    else:
        base_weight *= 1.04

    if step.label in {"crash"}:
        return 0.0
    if step.label in {"open_hat", "kick"}:
        base_weight *= 0.82
    return float(max(0.0, base_weight))


def _choose_repeat_glitch_count(
    step: GeneratedPatternStep,
    *,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> int:
    family = _event_family(step.label)
    four_count_bias = _lerp(0.08, 0.88, params.repeat_rate)
    if family in {"hat", "ghost"}:
        four_count_bias += 0.14
    elif family == "kick":
        four_count_bias -= 0.08
    return 4 if float(rng.random()) < float(np.clip(four_count_bias, 0.05, 0.92)) else 2


def _clone_step_for_repeat_glitch(
    source_step: GeneratedPatternStep,
    *,
    repeat_count: int,
    zone_span: int = 1,
    zone_offset: int = 0,
) -> GeneratedPatternStep:
    target_step_index = int(source_step.step_index)
    repeated_tags = [
        _step_tag(target_step_index),
        "repeat",
        "repeat_glitch",
        f"repeat_count_{int(max(2, repeat_count))}",
        "repeat_zone",
        f"repeat_zone_span_{int(max(1, zone_span))}",
        "owner_fx",
    ]
    if int(zone_offset) <= 0:
        repeated_tags.append("repeat_zone_start")
    if int(zone_offset) >= int(max(1, zone_span) - 1):
        repeated_tags.append("repeat_zone_end")
    if ((target_step_index - 1) % 16) + 1 in _FILL_STEPS:
        repeated_tags.append("phrase_end")
    repeated_tags.extend(
        tag
        for tag in source_step.tags
        if tag not in _RHYTHMIC_TAGS and tag != "repeat" and not str(tag).startswith("repeat_")
    )

    return GeneratedPatternStep(
        step_index=target_step_index,
        label=source_step.label,
        velocity=0,
        source_hit_index=source_step.source_hit_index,
        source_label=source_step.source_label,
        source_start_s=source_step.source_start_s,
        source_end_s=source_step.source_end_s,
        tags=tuple(dict.fromkeys(repeated_tags)),
        relative_velocity_ratio=source_step.relative_velocity_ratio,
        source_sequence_index=source_step.source_sequence_index,
        source_sequence_role=source_step.source_sequence_role,
    )


def _apply_kick_rolls(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
) -> None:
    if params.kick_roll_density <= 1e-3 or len(steps) < 2 or not (pools.kick or pools.kick_ghost):
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        weighted_candidates: list[tuple[int, float, int]] = []
        for trigger_step_index in (bar_start + 4, bar_start + 12):
            if trigger_step_index < 1 or trigger_step_index > step_count:
                continue
            trigger_anchor = anchors.get(int(trigger_step_index)) if anchors else None
            if trigger_anchor is not None and str(trigger_anchor) != "kick":
                continue
            next_step_index = int(trigger_step_index) + 1
            if next_step_index > step_count:
                continue
            current_step = steps[next_step_index - 1]
            trigger_step = steps[trigger_step_index - 1]
            weight = _kick_roll_zone_weight(
                trigger_step,
                current_step,
                trigger_step_index=int(trigger_step_index),
                params=params,
            )
            if weight <= 1e-6:
                continue
            max_span = _kick_roll_max_even_span(
                steps,
                start_step_index=int(trigger_step_index),
                anchors=anchors,
            )
            if max_span < 2:
                continue
            span_bonus = 1.0 + (0.06 * float(max_span - 2) * float(params.kick_roll_span))
            weighted_candidates.append((int(trigger_step_index), float(weight * span_bonus), int(max_span)))

        if not weighted_candidates:
            continue
        if float(rng.random()) > (0.08 + (0.92 * params.kick_roll_density)):
            continue

        if params.kick_roll_density >= 0.95:
            roll_slots = len(weighted_candidates)
        else:
            roll_slots = 1
            if params.kick_roll_density >= 0.58 and len(weighted_candidates) >= 2:
                roll_slots += 1
            if params.kick_roll_density >= 0.88 and len(weighted_candidates) >= 3 and float(rng.random()) < 0.45:
                roll_slots += 1

        for _ in range(min(roll_slots, len(weighted_candidates))):
            candidate_steps = np.asarray([step_index for step_index, _, _ in weighted_candidates], dtype=np.int32)
            candidate_weights = np.asarray([weight for _, weight, _ in weighted_candidates], dtype=np.float64)
            weight_sum = float(np.sum(candidate_weights))
            if candidate_steps.size == 0 or weight_sum <= 1e-9:
                break
            candidate_weights /= weight_sum
            chosen_trigger_index = int(rng.choice(candidate_steps, p=candidate_weights))
            trigger_step = steps[chosen_trigger_index - 1]
            max_span = next(
                (span for step_index, _weight, span in weighted_candidates if int(step_index) == chosen_trigger_index),
                2,
            )
            zone_span = _choose_kick_roll_zone_span(params=params, rng=rng, max_span=int(max_span))
            source_hit = _pick_kick_roll_source_hit(
                trigger_step,
                pools,
                params=params,
                rng=rng,
                target_step_index=chosen_trigger_index,
            )
            if source_hit is None:
                continue
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=min(step_count, bar_start + 15),
                target_step_indices=range(chosen_trigger_index, chosen_trigger_index + zone_span),
                params=params,
            ):
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_trigger_index
                ]
                continue
            for zone_offset in range(zone_span):
                target_step_index = chosen_trigger_index + zone_offset
                steps[target_step_index - 1] = _build_kick_roll_step(
                    target_step_index,
                    source_hit=source_hit,
                    zone_span=zone_span,
                    zone_offset=zone_offset,
                    contrast=params.kick_roll_contrast,
                )
            chosen_zone_end = chosen_trigger_index + zone_span - 1
            weighted_candidates = [
                (step_index, weight, span)
                for step_index, weight, span in weighted_candidates
                if (int(step_index) + int(span) - 1) < chosen_trigger_index
                or int(step_index) > chosen_zone_end
            ]


def _kick_roll_max_even_span(
    steps: list[GeneratedPatternStep],
    *,
    start_step_index: int,
    anchors: Mapping[int, str] | None = None,
) -> int:
    max_span = 0
    step_count = len(steps)
    last_index = min(int(step_count), int(start_step_index) + 3)
    for target_step_index in range(int(start_step_index), last_index + 1):
        local_step = ((int(target_step_index) - 1) % 16) + 1
        if int(target_step_index) != int(start_step_index) and (
            local_step in _STRONG_STEPS or local_step in _BACKBEAT_STEPS
        ):
            break
        anchor_value = anchors.get(int(target_step_index)) if anchors else None
        if anchor_value is not None and str(anchor_value) != "kick":
            break
        current = steps[target_step_index - 1]
        tags = set(current.tags)
        if (
            "sequence_gap" in tags
            or "sequence" in tags
            or "repeat" in tags
            or "reverse" in tags
            or "resolution" in tags
        ):
            break
        max_span += 1
    even_span = min(4, max_span - (max_span % 2))
    return int(max(0, even_span))


def _choose_kick_roll_zone_span(
    *,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    max_span: int,
) -> int:
    even_spans = [span for span in range(2, max(2, int(max_span)) + 1, 2)]
    if not even_spans:
        return 2
    if params.kick_roll_span >= 0.95:
        return int(max(even_spans))

    span_weights: list[tuple[int, float]] = []
    for span in even_spans:
        weight = {
            2: _lerp(1.85, 0.45, params.kick_roll_span),
            4: _lerp(0.7, 1.15, params.kick_roll_span),
            6: _lerp(0.16, 0.92, params.kick_roll_span),
        }.get(span, 0.0)
        if weight > 1e-6:
            span_weights.append((span, float(weight)))

    if not span_weights:
        return int(even_spans[0])

    labels = np.asarray([span for span, _ in span_weights], dtype=np.int32)
    values = np.asarray([weight for _, weight in span_weights], dtype=np.float64)
    values /= float(np.sum(values))
    return int(rng.choice(labels, p=values))


def _kick_roll_zone_weight(
    trigger_step: GeneratedPatternStep | None,
    current_step: GeneratedPatternStep,
    *,
    trigger_step_index: int,
    params: _ResolvedPatternParams,
) -> float:
    if trigger_step is None:
        return 0.0
    local_step = ((int(trigger_step_index) - 1) % 16) + 1
    if local_step not in _BACKBEAT_STEPS:
        return 0.0

    trigger_tags = set(trigger_step.tags)
    current_tags = set(current_step.tags)
    if (
        "repeat" in current_tags
        or "reverse" in current_tags
        or "sequence_gap" in current_tags
        or "resolution" in current_tags
        or "anchor" in current_tags
        or "sequence" in current_tags
    ):
        return 0.0
    if "sequence_gap" in trigger_tags or "sequence" in trigger_tags or "resolution" in trigger_tags:
        return 0.0

    current_family = _event_family(current_step.label)
    space_weight = {
        "silence": 1.28,
        "hat": 1.14,
        "ghost": 1.0,
        "other": 0.88,
        "kick": 0.84,
        "snare": 0.62,
    }.get(current_family, 0.7)
    trigger_label = str(trigger_step.label)
    if trigger_label in _KICK_ROLL_TRIGGER_LABELS:
        trigger_weight = 1.22
    elif trigger_label in {"snare", "clap", "snare_ruff"}:
        trigger_weight = _lerp(0.2, 0.86, params.kick_roll_density)
    elif trigger_label == "silence":
        trigger_weight = _lerp(0.12, 0.58, params.kick_roll_density)
    else:
        trigger_weight = _lerp(0.16, 0.78, params.kick_roll_density)

    density_drive = _lerp(0.3, 1.24, params.kick_roll_density)
    kick_drive = _lerp(0.35, 1.0, params.kick_weight)
    base_weight = float(space_weight) * float(trigger_weight) * float(density_drive) * float(kick_drive)
    if "fill" in trigger_tags or "phrase_end" in current_tags:
        base_weight *= _lerp(0.88, 1.06, params.kick_roll_density)
    if "anchor" in trigger_tags:
        base_weight *= 1.22
    return float(max(0.0, base_weight))


def _pick_kick_roll_source_hit(
    trigger_step: GeneratedPatternStep,
    pools: _PatternPools,
    *,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    target_step_index: int,
) -> TransientHit | None:
    if trigger_step.label == "kick" and trigger_step.source_start_s is not None and trigger_step.source_end_s is not None:
        return TransientHit(
            index=int(trigger_step.source_hit_index or 0),
            start_s=float(trigger_step.source_start_s),
            end_s=float(trigger_step.source_end_s),
            label=str(trigger_step.source_label or trigger_step.label),
            confidence=1.0,
            peak_db=0.0,
            low_ratio=1.0,
            mid_ratio=0.0,
            high_ratio=0.0,
            rhythmic_position=_rhythmic_position_for_step_index(target_step_index),
        )

    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.kick:
        weight = 1.0
        if hit.label == "kick":
            weight *= 1.28
        elif hit.label == "kick_ghost":
            weight *= 0.52
        weighted_hits.append((hit, weight))
    return _pick_weighted_hit(
        weighted_hits,
        rng,
        trigger_step.source_hit_index,
        trigger_step.source_label,
        params,
        target_step_index=target_step_index,
    )


def _kick_roll_velocity_ratio(*, zone_offset: int, zone_span: int, contrast: float) -> float:
    del zone_offset, zone_span
    resolved_contrast = float(np.clip(contrast, 0.0, 1.0))
    return float(np.clip(_lerp(0.82, 1.0, resolved_contrast), 0.18, 1.0))


def _build_kick_roll_step(
    step_index: int,
    *,
    source_hit: TransientHit,
    zone_span: int,
    zone_offset: int,
    contrast: float,
) -> GeneratedPatternStep:
    target_step_index = int(step_index)
    kick_roll_tags = [
        _step_tag(target_step_index),
        "effect",
        "effect_kick_roll",
        "kick_roll",
        "kick_roll_zone",
        f"kick_roll_zone_span_{int(max(2, zone_span))}",
        "owner_fx",
    ]
    if int(zone_offset) <= 0:
        kick_roll_tags.append("kick_roll_zone_start")
    if int(zone_offset) >= int(max(2, zone_span) - 1):
        kick_roll_tags.append("kick_roll_zone_end")
    if ((target_step_index - 1) % 16) + 1 in _FILL_STEPS:
        kick_roll_tags.append("phrase_end")

    return GeneratedPatternStep(
        step_index=target_step_index,
        label=str(source_hit.label),
        velocity=0,
        source_hit_index=int(source_hit.index),
        source_label=str(source_hit.label),
        source_start_s=float(source_hit.start_s),
        source_end_s=float(source_hit.end_s),
        tags=tuple(dict.fromkeys(kick_roll_tags)),
        relative_velocity_ratio=_kick_roll_velocity_ratio(
            zone_offset=int(zone_offset),
            zone_span=int(zone_span),
            contrast=float(contrast),
        ),
    )


def _apply_snare_stretches(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
) -> None:
    if params.snare_stretch_density <= 1e-3 or not steps:
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        bar_end = min(step_count, bar_start + 15)
        weighted_candidates: list[tuple[int, float, int]] = []
        for step_index in range(bar_start, bar_end + 1):
            current = steps[step_index - 1]
            weight = _snare_stretch_weight(current, step_index=step_index, params=params)
            if weight <= 1e-6:
                continue
            max_span = _snare_stretch_max_span(
                start_step_index=int(step_index),
                step_count=step_count,
                anchors=anchors,
            )
            if max_span < 2:
                continue
            span_bonus = 1.0 + (0.08 * float(max_span - 2) * float(params.snare_stretch_span))
            weighted_candidates.append((int(step_index), float(weight * span_bonus), int(max_span)))

        if not weighted_candidates:
            continue
        if float(rng.random()) > (0.08 + (0.92 * params.snare_stretch_density)):
            continue

        if params.snare_stretch_density >= 0.95:
            stretch_slots = len(weighted_candidates)
        else:
            stretch_slots = 1
            if params.snare_stretch_density >= 0.58 and len(weighted_candidates) >= 2:
                stretch_slots += 1
            if params.snare_stretch_density >= 0.86 and len(weighted_candidates) >= 4 and float(rng.random()) < 0.48:
                stretch_slots += 1

        for _ in range(min(stretch_slots, len(weighted_candidates))):
            candidate_steps = np.asarray([step_index for step_index, _, _ in weighted_candidates], dtype=np.int32)
            candidate_weights = np.asarray([weight for _, weight, _ in weighted_candidates], dtype=np.float64)
            weight_sum = float(np.sum(candidate_weights))
            if candidate_steps.size == 0 or weight_sum <= 1e-9:
                break
            candidate_weights /= weight_sum
            chosen_step_index = int(rng.choice(candidate_steps, p=candidate_weights))
            current = steps[chosen_step_index - 1]
            max_span = next(
                (span for step_index, _weight, span in weighted_candidates if int(step_index) == chosen_step_index),
                2,
            )
            zone_span = _choose_snare_stretch_span(params=params, rng=rng, max_span=int(max_span))
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=bar_end,
                target_step_indices=range(chosen_step_index, chosen_step_index + zone_span),
                params=params,
            ):
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue
            steps[chosen_step_index - 1] = _mark_step_for_snare_stretch(
                current,
                zone_span=zone_span,
                amount=params.snare_stretch_amount,
            )
            for zone_offset in range(1, int(zone_span)):
                target_step_index = chosen_step_index + zone_offset
                if target_step_index > len(steps):
                    break
                steps[target_step_index - 1] = _decorate_step_for_snare_stretch_zone(
                    steps[target_step_index - 1],
                    zone_span=zone_span,
                    zone_offset=zone_offset,
                    amount=params.snare_stretch_amount,
                )
            chosen_zone_end = chosen_step_index + zone_span - 1
            weighted_candidates = [
                (step_index, weight, span)
                for step_index, weight, span in weighted_candidates
                if int(step_index) > chosen_zone_end or int(step_index) < chosen_step_index - 1
            ]


def _snare_stretch_weight(
    step: GeneratedPatternStep,
    *,
    step_index: int,
    params: _ResolvedPatternParams,
) -> float:
    if step.label not in _SNARE_STRETCH_TRIGGER_LABELS:
        return 0.0

    tags = set(step.tags)
    if (
        "snare_stretch" in tags
        or "repeat" in tags
        or "reverse" in tags
        or "kick_roll" in tags
        or "sequence_gap" in tags
        or "resolution" in tags
        or "sequence" in tags
    ):
        return 0.0

    local_step = ((int(step_index) - 1) % 16) + 1
    base_weight = {
        "snare": 1.0,
        "clap": 0.92,
        "snare_ruff": 0.82,
    }.get(step.label, 0.0)

    if local_step in _BACKBEAT_STEPS:
        base_weight *= 1.28
    elif local_step in _OFFBEAT_STEPS:
        base_weight *= 0.98
    elif local_step in _FILL_STEPS:
        base_weight *= 1.18
    elif local_step in _STRONG_STEPS:
        base_weight *= 0.16
    else:
        base_weight *= 0.56

    if step.label == "snare_ruff":
        if "fill" in tags or "phrase_end" in tags:
            base_weight *= 1.35
        else:
            base_weight *= 0.72

    if "phrase_end" in tags:
        base_weight *= _lerp(1.0, 1.12, params.fill_strength)
    if "fill" in tags:
        base_weight *= _lerp(1.0, 1.18, params.fill_strength)
    if "anchor" in tags:
        base_weight *= 1.18
    density_drive = _lerp(0.32, 1.28, params.snare_stretch_density)
    amount_drive = _lerp(0.84, 1.12, params.snare_stretch_amount)
    return float(max(0.0, base_weight * density_drive * amount_drive))


def _snare_stretch_max_span(
    *,
    start_step_index: int,
    step_count: int,
    anchors: Mapping[int, str] | None = None,
) -> int:
    local_step = ((int(start_step_index) - 1) % 16) + 1
    to_next_beat = 4 - ((local_step - 1) % 4)
    max_span = min(int(to_next_beat), int(step_count) - int(start_step_index) + 1)
    if anchors:
        for target_step_index in range(int(start_step_index) + 1, int(start_step_index) + int(max_span)):
            if int(target_step_index) in anchors:
                max_span = min(max_span, int(target_step_index) - int(start_step_index))
                break
    return int(max(0, max_span))


def _choose_snare_stretch_span(
    *,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    max_span: int,
) -> int:
    upper_bound = max(2, int(max_span))
    if params.snare_stretch_span >= 0.95:
        return int(upper_bound)

    span_weights: list[tuple[int, float]] = []
    for span in range(2, upper_bound + 1):
        weight = {
            2: _lerp(1.7, 0.48, params.snare_stretch_span),
            3: _lerp(0.72, 0.96, params.snare_stretch_span),
            4: _lerp(0.18, 1.16, params.snare_stretch_span),
        }.get(span, _lerp(0.12, 0.72, params.snare_stretch_span))
        if weight > 1e-6:
            span_weights.append((span, float(weight)))

    if not span_weights:
        return 2

    labels = np.asarray([span for span, _ in span_weights], dtype=np.int32)
    values = np.asarray([weight for _, weight in span_weights], dtype=np.float64)
    values /= float(np.sum(values))
    return int(rng.choice(labels, p=values))


def _mark_step_for_snare_stretch(
    source_step: GeneratedPatternStep,
    *,
    zone_span: int,
    amount: float,
) -> GeneratedPatternStep:
    target_step_index = int(source_step.step_index)
    stretch_tags = [
        _step_tag(target_step_index),
        "effect",
        "effect_snare_stretch",
        "snare_stretch",
        "snare_stretch_glitch",
        "snare_stretch_zone",
        "snare_stretch_zone_start",
        f"snare_stretch_zone_span_{int(max(2, zone_span))}",
        f"snare_stretch_amount_{int(round(np.clip(amount, 0.0, 1.0) * 100.0))}",
        "owner_fx",
    ]
    stretch_tags.extend(
        tag
        for tag in source_step.tags
        if tag not in _RHYTHMIC_TAGS and "snare_stretch" not in str(tag)
    )
    return GeneratedPatternStep(
        step_index=target_step_index,
        label=source_step.label,
        velocity=0,
        source_hit_index=source_step.source_hit_index,
        source_label=source_step.source_label,
        source_start_s=source_step.source_start_s,
        source_end_s=source_step.source_end_s,
        tags=tuple(dict.fromkeys(stretch_tags)),
        relative_velocity_ratio=source_step.relative_velocity_ratio,
        source_sequence_index=source_step.source_sequence_index,
        source_sequence_role=source_step.source_sequence_role,
    )


def _decorate_step_for_snare_stretch_zone(
    source_step: GeneratedPatternStep,
    *,
    zone_span: int,
    zone_offset: int,
    amount: float,
) -> GeneratedPatternStep:
    target_step_index = int(source_step.step_index)
    zone_tags = [
        _step_tag(target_step_index),
        "effect",
        "effect_snare_stretch",
        "snare_stretch_tail",
        "snare_stretch_glitch",
        "snare_stretch_zone",
        f"snare_stretch_zone_span_{int(max(2, zone_span))}",
        f"snare_stretch_amount_{int(round(np.clip(amount, 0.0, 1.0) * 100.0))}",
        "owner_fx",
    ]
    if int(zone_offset) >= int(max(2, zone_span) - 1):
        zone_tags.append("snare_stretch_zone_end")
    zone_tags.extend(tag for tag in source_step.tags if "snare_stretch" not in str(tag))
    return GeneratedPatternStep(
        step_index=target_step_index,
        label=source_step.label,
        velocity=source_step.velocity,
        source_hit_index=source_step.source_hit_index,
        source_label=source_step.source_label,
        source_start_s=source_step.source_start_s,
        source_end_s=source_step.source_end_s,
        tags=tuple(dict.fromkeys(zone_tags)),
        relative_velocity_ratio=source_step.relative_velocity_ratio,
        source_sequence_index=source_step.source_sequence_index,
        source_sequence_role=source_step.source_sequence_role,
    )


def _apply_reverse_steps(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
) -> None:
    if params.reverse_density <= 1e-3 or not steps:
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        bar_end = min(step_count, bar_start + 15)
        weighted_candidates: list[tuple[int, float]] = []
        for step_index in range(bar_start + 1, bar_end + 1):
            if anchors and int(step_index) in anchors:
                continue
            trigger_step = steps[step_index - 2]
            current = steps[step_index - 1]
            weight = _reverse_transition_weight(trigger_step, current, step_index=step_index)
            if weight <= 1e-6:
                continue
            weighted_candidates.append((int(step_index), float(weight)))

        if not weighted_candidates:
            continue

        if float(rng.random()) > (0.1 + (0.9 * params.reverse_density)):
            continue

        reverse_slots = 1
        if params.reverse_density >= 0.65 and len(weighted_candidates) >= 3 and float(rng.random()) < 0.45:
            reverse_slots += 1

        for _ in range(min(reverse_slots, len(weighted_candidates))):
            candidate_steps = np.asarray([step_index for step_index, _ in weighted_candidates], dtype=np.int32)
            candidate_weights = np.asarray([weight for _, weight in weighted_candidates], dtype=np.float64)
            weight_sum = float(np.sum(candidate_weights))
            if candidate_steps.size == 0 or weight_sum <= 1e-9:
                break
            candidate_weights /= weight_sum
            chosen_step_index = int(rng.choice(candidate_steps, p=candidate_weights))
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=bar_end,
                target_step_indices=(chosen_step_index,),
                params=params,
            ):
                weighted_candidates = [
                    (step_index, weight)
                    for step_index, weight in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue
            trigger_step = steps[chosen_step_index - 2]
            current = steps[chosen_step_index - 1]
            steps[chosen_step_index - 1] = _build_reverse_transition_step(
                chosen_step_index,
                trigger_step=trigger_step,
                current_step=current,
            )
            weighted_candidates = [
                (step_index, weight)
                for step_index, weight in weighted_candidates
                if abs(int(step_index) - chosen_step_index) > 1
            ]


def _maybe_reverse_step(
    step: GeneratedPatternStep,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    previous_step: GeneratedPatternStep | None = None,
    anchors: Mapping[int, str] | None = None,
) -> GeneratedPatternStep:
    if params.reverse_density <= 1e-3:
        return step
    if anchors and int(step.step_index) in anchors:
        return step
    weight = _reverse_transition_weight(previous_step, step, step_index=step.step_index)
    if weight <= 1e-6:
        return step
    threshold = min(0.9, params.reverse_density * weight * 0.72)
    if float(rng.random()) > threshold:
        return step
    if previous_step is None:
        return step
    return _build_reverse_transition_step(step.step_index, trigger_step=previous_step, current_step=step)


def _reverse_transition_weight(
    trigger_step: GeneratedPatternStep | None,
    target_step: GeneratedPatternStep,
    *,
    step_index: int,
) -> float:
    if trigger_step is None:
        return 0.0

    local_step = ((int(step_index) - 1) % 16) + 1
    if local_step in _STRONG_STEPS or local_step in _BACKBEAT_STEPS or local_step in _OFFBEAT_STEPS:
        return 0.0

    trigger_tags = set(trigger_step.tags)
    target_tags = set(target_step.tags)
    if (
        "reverse" in target_tags
        or "sequence_gap" in target_tags
        or "resolution" in target_tags
        or "repeat" in target_tags
        or "kick_roll" in target_tags
        or "snare_stretch" in target_tags
        or "snare_stretch_zone" in target_tags
        or "snare_stretch_tail" in target_tags
        or "fill" in target_tags
        or "sequence" in target_tags
    ):
        return 0.0
    if (
        "reverse" in trigger_tags
        or "sequence_gap" in trigger_tags
        or "resolution" in trigger_tags
        or "repeat" in trigger_tags
        or "kick_roll" in trigger_tags
        or "snare_stretch" in trigger_tags
        or "snare_stretch_zone" in trigger_tags
        or "snare_stretch_tail" in trigger_tags
    ):
        return 0.0

    if (
        trigger_step.label not in _REVERSE_TRIGGER_LABELS
        or trigger_step.source_start_s is None
        or trigger_step.source_end_s is None
    ):
        return 0.0

    if "anchor" in target_tags:
        return 0.0

    base_weight = 1.08 if trigger_step.label == "kick" else 0.98
    trigger_local_step = ((int(step_index) - 2) % 16) + 1
    if trigger_local_step in _STRONG_STEPS:
        base_weight *= 1.16
    elif trigger_local_step in _BACKBEAT_STEPS:
        base_weight *= 1.1
    elif trigger_local_step in _OFFBEAT_STEPS:
        base_weight *= 0.98

    target_family = _event_family(target_step.label)
    base_weight *= {
        "silence": 1.32,
        "hat": 1.0,
        "ghost": 0.9,
        "other": 0.84,
        "kick": 0.0,
        "snare": 0.0,
    }.get(target_family, 0.7)

    if "phrase_end" in target_tags:
        base_weight *= 1.08
    if "fill" in trigger_tags:
        base_weight *= 0.88
    if "anchor" in trigger_tags:
        base_weight *= 1.05
    return float(max(0.0, base_weight))


def _build_reverse_transition_step(
    step_index: int,
    *,
    trigger_step: GeneratedPatternStep,
    current_step: GeneratedPatternStep,
) -> GeneratedPatternStep:
    if trigger_step.source_start_s is None or trigger_step.source_end_s is None:
        return current_step

    local_step = ((int(step_index) - 1) % 16) + 1
    reverse_tags = [
        _step_tag(step_index),
        "reverse",
        "effect",
        "effect_reverse",
        "reverse_transition",
        f"reverse_from_{_event_family(trigger_step.label)}",
        "owner_fx",
    ]
    if local_step in _FILL_STEPS:
        reverse_tags.append("phrase_end")
    if "anchor" in current_step.tags:
        reverse_tags.append("anchor_blocked")

    return GeneratedPatternStep(
        step_index=int(step_index),
        label=trigger_step.label,
        velocity=0,
        source_hit_index=trigger_step.source_hit_index,
        source_label=trigger_step.source_label,
        source_start_s=trigger_step.source_start_s,
        source_end_s=trigger_step.source_end_s,
        tags=tuple(dict.fromkeys(reverse_tags)),
        relative_velocity_ratio=trigger_step.relative_velocity_ratio,
        source_sequence_index=trigger_step.source_sequence_index,
        source_sequence_role=trigger_step.source_sequence_role,
    )


def _enforce_step_anchors(
    steps: list[GeneratedPatternStep],
    anchors: Mapping[int, str] | None,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if not anchors or not steps:
        return

    for step_index in sorted(int(index) for index in anchors.keys()):
        if step_index < 1 or step_index > len(steps):
            continue
        anchor = str(anchors[step_index])
        current = steps[step_index - 1]
        if _generated_step_matches_anchor(current, anchor):
            steps[step_index - 1] = replace(
                current,
                tags=tuple(dict.fromkeys((*current.tags, "anchor", f"anchor_{anchor}", "owner_anchor"))),
            )
            continue
        steps[step_index - 1] = _select_anchored_step_event(
            step_index,
            anchor,
            steps[: step_index - 1],
            pools,
            params,
            rng,
        )


def _pick_fill_texture_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    if params.hat_density <= 1e-3:
        return None
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.hatish:
        weight = 1.0
        if hit.label == "closed_hat":
            weight *= 1.35
        elif hit.label == "ride":
            weight *= 1.05
        elif hit.label == "open_hat":
            weight *= 0.82
        elif hit.label == "crash":
            weight *= 0.08
        weighted_hits.append((hit, weight))
    if not weighted_hits and pools.otherish:
        weighted_hits = [(hit, 0.7) for hit in pools.otherish if hit.label in {"perc", "tom"}]
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _pick_fill_snare_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    if params.snare_weight <= 1e-3:
        return None
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in (*pools.snare_ruff, *pools.snareish):
        weight = 1.0
        if hit.label == "snare_ruff":
            weight *= 1.8
        elif hit.label == "snare":
            weight *= 1.15
        elif hit.label == "clap":
            weight *= 0.92
        weighted_hits.append((hit, weight))
    if not weighted_hits:
        weighted_hits = [(hit, 0.9) for hit in pools.otherish if hit.label in {"perc", "tom"}]
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _pick_fill_backbeat_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    if params.snare_weight <= 1e-3:
        return None
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in (*pools.snare, *pools.clap):
        weight = 1.18 if hit.label == "snare" else 1.05
        weighted_hits.append((hit, weight))
    if not weighted_hits:
        weighted_hits = [(hit, 0.55) for hit in pools.snare_ruff]
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _pick_fill_kick_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    if params.kick_weight <= 1e-3:
        return None
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.kick:
        weight = 1.1 if hit.label == "kick" else 0.75
        weighted_hits.append((hit, weight))
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _pick_fill_other_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.otherish:
        weight = 1.0
        if hit.label in {"perc", "tom"}:
            weight *= 1.35
        elif hit.label == "snare_ruff":
            weight *= 1.25
        elif hit.label in {"crash", "open_hat"}:
            weight *= 0.72
        weighted_hits.append((hit, weight))
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _pick_fill_release_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    if params.hat_density <= 1e-3:
        return None
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.hatish:
        weight = 1.0
        if hit.label == "open_hat":
            weight *= 1.45
        elif hit.label == "closed_hat":
            weight *= 1.2
        elif hit.label == "ride":
            weight *= 0.95
        elif hit.label == "crash":
            continue
        weighted_hits.append((hit, weight))
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _pick_bar_start_resolution_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    if pools.kick and params.kick_weight > 1e-3:
        weighted_kicks: list[tuple[TransientHit, float]] = []
        for hit in pools.kick:
            weight = 1.45 if hit.label == "kick" else 0.85
            if set(hit.secondary_labels) & {"open_hat", "crash", "closed_hat", "ride"}:
                weight *= 1.2 + (0.35 * hit.layer_score)
            weighted_kicks.append((hit, weight))
        selected = _pick_weighted_hit(weighted_kicks, rng, None, None, params, target_step_index=step_index)
        if selected is not None:
            return selected

    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.all_hits:
        weight = 0.0
        secondary = set(hit.secondary_labels)
        if hit.label == "kick":
            if params.kick_weight <= 1e-3:
                continue
            weight = 1.45 if hit.role == "pillar" else 1.25
            if secondary & {"open_hat", "crash", "closed_hat", "ride"}:
                weight *= 1.35 + (0.45 * hit.layer_score)
        elif hit.label in {"open_hat", "crash"}:
            if params.hat_density <= 1e-3:
                continue
            weight = 0.38 if not pools.kick else 0.22
            if "kick" in secondary:
                weight *= 1.9
            if hit.role == "punctuation":
                weight *= 1.2
        elif hit.label in {"snare", "clap"}:
            if params.snare_weight <= 1e-3:
                continue
            weight = 0.42 if not pools.kick else 0.26
        elif hit.label == "closed_hat":
            if params.hat_density <= 1e-3:
                continue
            weight = 0.12 if not pools.kick else 0.04

        if weight > 0.0:
            weighted_hits.append((hit, weight))

    if weighted_hits:
        return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)
    if pools.kick:
        return _pick_hit(pools.kick, rng, None, None, params, target_step_index=step_index)
    return None


def _pick_punctuation_hit(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    weighted_hits: list[tuple[TransientHit, float]] = []
    for hit in pools.hatish:
        weight = 1.0
        if hit.label == "crash":
            weight *= 1.8
        elif hit.label == "open_hat":
            weight *= 1.45
        elif hit.label == "ride":
            weight *= 0.8
        elif hit.label == "closed_hat":
            weight *= 0.4
        weighted_hits.append((hit, weight))
    return _pick_weighted_hit(weighted_hits, rng, None, None, params, target_step_index=step_index)


def _override_step_from_hit(
    step_index: int,
    hit: TransientHit | None,
    tags: tuple[str, ...] | list[str],
) -> GeneratedPatternStep:
    base_tags = [_step_tag(step_index)]
    local_step = ((step_index - 1) % 16) + 1
    if local_step in _FILL_STEPS:
        base_tags.append("phrase_end")
    owner = "fill" if any(tag in {"fill", "resolution"} for tag in tuple(tags)) else "skeleton"
    merged_tags = _tags_with_owner((*base_tags, *tuple(tags)), owner)
    if hit is None:
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, merged_tags)
    return GeneratedPatternStep(
        step_index=step_index,
        label=hit.label,
        velocity=0,
        source_hit_index=hit.index,
        source_label=hit.label,
        source_start_s=hit.start_s,
        source_end_s=hit.end_s,
        tags=merged_tags,
    )


def _finalize_step_velocity(
    step: GeneratedPatternStep,
    all_steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> GeneratedPatternStep:
    if step.label == "silence":
        return step

    step_tags = set(step.tags)
    if "kick_roll" in step_tags:
        velocity = _lerp(84.0, 102.0, params.kick_roll_contrast)
        return GeneratedPatternStep(
            step_index=step.step_index,
            label=step.label,
            velocity=int(np.clip(round(velocity), 1, 127)),
            source_hit_index=step.source_hit_index,
            source_label=step.source_label,
            source_start_s=step.source_start_s,
            source_end_s=step.source_end_s,
            tags=step.tags,
            relative_velocity_ratio=step.relative_velocity_ratio,
            source_sequence_index=step.source_sequence_index,
            source_sequence_role=step.source_sequence_role,
        )

    base, spread = _VELOCITY_RANGES.get(step.label, _VELOCITY_RANGES["perc"])
    jitter_span = spread * (0.35 + (0.95 * params.velocity_spread))
    velocity = base + rng.uniform(-jitter_span, jitter_span)
    local_step = ((step.step_index - 1) % 16) + 1

    if local_step in {1, 9}:
        velocity += 8.0
    if local_step in {5, 13}:
        velocity += 5.0

    fill_active = any(tag == "phrase_end" for tag in step.tags) and params.fill_strength >= 0.45
    if local_step == 16:
        velocity += 10.0 if fill_active else -15.0

    silent_run = 0
    for previous in reversed(all_steps[: step.step_index - 1]):
        if previous.label == "silence":
            silent_run += 1
        else:
            break
    if silent_run >= 2:
        velocity += 6.0

    previous_velocity = 0
    for previous in reversed(all_steps[: step.step_index - 1]):
        if previous.label != "silence":
            previous_velocity = previous.velocity
            break
    if previous_velocity > 85:
        velocity -= 8.0

    dense_recent = sum(1 for previous in all_steps[max(0, step.step_index - 4) : step.step_index - 1] if previous.label != "silence")
    velocity -= 5.0 * dense_recent

    if step.label in {"ghost_snare", "snare_ghost"}:
        velocity = rng.uniform(25.0, 45.0)
    elif step.label == "kick_ghost":
        velocity = rng.uniform(28.0, 52.0)
    elif step.relative_velocity_ratio is not None:
        ratio = float(np.clip(step.relative_velocity_ratio, 0.15, 1.0))
        velocity *= 0.35 + (0.65 * ratio)
        if step.source_sequence_role == "fill" and step.label in {"snare_ruff", "snare", "perc", "tom"}:
            velocity *= 1.04
        elif step.source_sequence_role == "groove" and step.label in {"closed_hat", "ride", "open_hat"}:
            velocity *= 0.96

    if "snare_stretch" in step_tags:
        velocity *= _lerp(0.96, 1.08, params.snare_stretch_amount)

    return GeneratedPatternStep(
        step_index=step.step_index,
        label=step.label,
        velocity=int(np.clip(round(velocity), 1, 127)),
        source_hit_index=step.source_hit_index,
        source_label=step.source_label,
        source_start_s=step.source_start_s,
        source_end_s=step.source_end_s,
        tags=step.tags,
        relative_velocity_ratio=step.relative_velocity_ratio,
        source_sequence_index=step.source_sequence_index,
        source_sequence_role=step.source_sequence_role,
    )


def _event_from_hit(step_index: int, hit: TransientHit | None, tags: list[str]) -> GeneratedPatternStep:
    if hit is None:
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple(tags))
    return GeneratedPatternStep(
        step_index=step_index,
        label=hit.label,
        velocity=0,
        source_hit_index=hit.index,
        source_label=hit.label,
        source_start_s=hit.start_s,
        source_end_s=hit.end_s,
        tags=tuple(tags),
    )


def _weighted_choice(weights: dict[str, float], rng: np.random.Generator) -> str:
    labels = list(weights.keys())
    values = np.asarray([max(0.0, float(weights[label])) for label in labels], dtype=np.float64)
    if float(np.sum(values)) <= 1e-9:
        return "silence"
    values /= float(np.sum(values))
    return str(labels[int(rng.choice(len(labels), p=values))])


def _event_family(label: str) -> str:
    if label == "kick":
        return "kick"
    if label in {"snare", "clap", "snare_ruff"}:
        return "snare"
    if label in {"closed_hat", "open_hat", "crash", "ride"}:
        return "hat"
    if label in {"ghost_snare", "snare_ghost", "kick_ghost"}:
        return "ghost"
    if label == "silence":
        return "silence"
    return "other"


def _step_tag(step_index: int) -> str:
    local_step = ((step_index - 1) % 16) + 1
    if local_step in _STRONG_STEPS:
        return "strong"
    if local_step in _BACKBEAT_STEPS:
        return "backbeat"
    if local_step in _OFFBEAT_STEPS:
        return "offbeat"
    return "subdivision"


def _tags_with_owner(tags: Iterable[str], owner: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*tuple(tags), f"owner_{str(owner)}")))


def _step_is_structurally_protected(step: GeneratedPatternStep) -> bool:
    tags = set(step.tags)
    return bool(tags & _STRUCTURAL_PROTECTION_TAGS)


def _step_has_post_mutation(step: GeneratedPatternStep) -> bool:
    return bool(set(step.tags) & _POST_MUTATION_TAGS)


def _bar_post_mutation_budget(params: _ResolvedPatternParams) -> int:
    fx_drive = max(
        float(params.repeat_density),
        float(params.reverse_density),
        float(params.kick_roll_density),
        float(params.snare_stretch_density),
    )
    groove_drive = max(float(params.kick_weight), float(params.snare_weight), float(params.hat_density))
    budget = 2.0 + (2.0 * groove_drive) + (4.0 * fx_drive) + (1.0 * float(params.fill_strength))
    return int(np.clip(round(budget), 2, 8))


def _bar_tail_mutation_budget(params: _ResolvedPatternParams) -> int:
    fx_tail_drive = max(
        float(params.fill_strength),
        float(params.kick_roll_density),
        float(params.snare_stretch_density),
        float(params.reverse_density) * 0.5,
    )
    budget = 1.5 + (2.8 * fx_tail_drive)
    return int(np.clip(round(budget), 1, 4))


def _bar_post_mutation_count(
    steps: list[GeneratedPatternStep],
    *,
    bar_start: int,
    bar_end: int,
    tail_only: bool = False,
) -> int:
    count = 0
    for step_index in range(int(bar_start), int(bar_end) + 1):
        local_step = ((int(step_index) - 1) % 16) + 1
        if tail_only and local_step < 13:
            continue
        if _step_has_post_mutation(steps[step_index - 1]):
            count += 1
    return int(count)


def _planned_post_mutation_cost(
    steps: list[GeneratedPatternStep],
    step_indices: Iterable[int],
) -> tuple[int, int]:
    total_cost = 0
    tail_cost = 0
    seen: set[int] = set()
    for raw_step_index in step_indices:
        step_index = int(raw_step_index)
        if step_index in seen or step_index < 1 or step_index > len(steps):
            continue
        seen.add(step_index)
        if _step_has_post_mutation(steps[step_index - 1]):
            continue
        total_cost += 1
        local_step = ((step_index - 1) % 16) + 1
        if local_step >= 13:
            tail_cost += 1
    return int(total_cost), int(tail_cost)


def _bar_has_post_mutation_capacity(
    steps: list[GeneratedPatternStep],
    *,
    bar_start: int,
    bar_end: int,
    target_step_indices: Iterable[int],
    params: _ResolvedPatternParams,
) -> bool:
    max_post_steps = _bar_post_mutation_budget(params)
    max_tail_steps = _bar_tail_mutation_budget(params)
    current_post_steps = _bar_post_mutation_count(steps, bar_start=bar_start, bar_end=bar_end)
    current_tail_steps = _bar_post_mutation_count(steps, bar_start=bar_start, bar_end=bar_end, tail_only=True)
    added_post_steps, added_tail_steps = _planned_post_mutation_cost(steps, target_step_indices)
    if current_post_steps + added_post_steps > max_post_steps:
        return False
    if current_tail_steps + added_tail_steps > max_tail_steps:
        return False
    return True


def _lerp(start: float, end: float, amount: float) -> float:
    return float(start + ((end - start) * np.clip(amount, 0.0, 1.0)))


def _build_generated_pattern(
    steps: tuple[GeneratedPatternStep, ...],
    params: BreakPatternParams,
    resolved_params: _ResolvedPatternParams,
) -> GeneratedBreakPattern:
    total_steps = max(1, len(steps))
    event_count = sum(1 for step in steps if step.label != "silence")
    counts: dict[str, int] = {}
    for step in steps:
        if step.label == "silence":
            continue
        counts[step.label] = counts.get(step.label, 0) + 1
    metrics = {
        "silence_ratio": float(sum(1 for step in steps if step.label == "silence") / total_steps),
        "sequence_ratio": float(sum(1 for step in steps if "sequence" in step.tags) / total_steps),
        "post_fx_ratio": float(sum(1 for step in steps if _step_has_post_mutation(step)) / total_steps),
        "fill_ratio": float(sum(1 for step in steps if "fill" in step.tags) / total_steps),
        "resolution_ratio": float(sum(1 for step in steps if "resolution" in step.tags) / total_steps),
        "protected_ratio": float(sum(1 for step in steps if _step_is_structurally_protected(step)) / total_steps),
    }
    summary = ", ".join(f"{label}:{count}" for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True))
    if not summary:
        summary = "silence only"
    return GeneratedBreakPattern(
        bars=max(1, int(params.bars)),
        step_count=max(16, int(max(1, params.bars) * 16)),
        seed=int(params.seed),
        swing=resolved_params.swing,
        params=params,
        event_count=event_count,
        summary=summary,
        steps=steps,
        metrics=metrics,
    )
