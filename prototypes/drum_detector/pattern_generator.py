from __future__ import annotations

from copy import deepcopy
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
    synth_ghost_enabled: bool = True
    ghost_vel_range: tuple[float, float] = (0.2, 0.45)
    ghost_pitch_range: tuple[float, float] = (0.0, 0.0)
    ghost_gate_ratio: float = 0.0
    fill_strength: float = 0.35
    fill_type_weights: dict[str, float] | None = None
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
    snare_stretch_vel_curve: str = "decay"
    pitch_mode: str = "off"
    pitch_scope: str = "snare"
    pitch_scale: str = "chromatic"
    pitch_root: int = 0
    pitch_range: tuple[float, float] = (-12.0, 12.0)
    pitch_sequence: list[float] = field(default_factory=lambda: [0.0, 3.0, -2.0, 7.0])
    pitch_curve: str = "up"
    pitch_curve_range: tuple[float, float] = (-7.0, 7.0)
    pitch_rate: str = "every_hit"
    pitch_amount: float = 0.0
    gate: float = 1.0
    mono_choke: bool = False
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
    generation_profile: str = "musical"
    enabled_passes: tuple[str, ...] = field(
        default_factory=lambda: (
            "ghost_pass",
            "fill_pass",
            "resolution_pass",
            "kick_roll_pass",
            "repeat_pass",
            "reverse_pass",
            "snare_stretch_pass",
            "velocity_pass",
            "pitch_pass",
            "anchor_reapply",
        )
    )
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
class StretchRetrigger:
    slice_source: TransientHit | None
    offset_ticks: int
    step_index: int
    sub_step_offset: int
    velocity: float


@dataclass(frozen=True)
class FillDecision:
    active: bool
    fill_type: str
    zone_start: int
    zone_end: int
    source: str = "generated"

    def to_dict(self) -> dict:
        return asdict(self)


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
    pitch_shift: float = 0.0
    is_synthetic_ghost: bool = False
    ghost_vel_ratio: float = 1.0
    ghost_pitch_offset: float = 0.0
    ghost_gate_ratio: float = 0.0
    stretch_retriggers: tuple[StretchRetrigger, ...] = ()

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
    fill_decisions: tuple[FillDecision, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["params"] = self.params.to_dict()
        payload["steps"] = [step.to_dict() for step in self.steps]
        payload["fill_decisions"] = [decision.to_dict() for decision in self.fill_decisions]
        return payload


@dataclass(frozen=True)
class DebugStepEntry:
    passe: str
    label: str
    note: str = ""


class DebugLog:
    def __init__(self, bars: int, steps_per_bar: int = 16):
        self.bars = max(1, int(bars))
        self.steps_per_bar = max(1, int(steps_per_bar))
        self.steps: dict[tuple[int, int], list[DebugStepEntry]] = {
            (bar, step): []
            for bar in range(self.bars)
            for step in range(1, self.steps_per_bar + 1)
        }
        self.params: BreakPatternParams | None = None
        self.target_bpm: float | None = None
        self.mode: str = "Classic"
        self.profile: str = "musical"
        self.pools_summary: dict[str, int] = {}
        self.sequence_summary: dict[str, int] = {}
        self.final_pattern: GeneratedBreakPattern | None = None
        self.final_steps: dict[tuple[int, int], GeneratedPatternStep] = {}
        self.fill_decisions: dict[int, FillDecision] = {}
        self.pass_stats: dict[str, dict[str, int]] = {}

    def write(self, bar: int, step: int, passe: str, label: str, note: str = ""):
        key = (int(bar), int(step))
        if key not in self.steps:
            return
        self.steps[key].append(DebugStepEntry(str(passe), str(label), str(note or "")))

    def write_step_index(self, step_index: int, passe: str, label: str, note: str = "") -> None:
        bar = max(0, (int(step_index) - 1) // self.steps_per_bar)
        step = ((int(step_index) - 1) % self.steps_per_bar) + 1
        self.write(bar, step, passe, label, note)

    def set_context(
        self,
        *,
        params: BreakPatternParams,
        pools: "_PatternPools",
        sequence_pools: "_SequencePools",
        mode: str | None = None,
        target_bpm: float | None = None,
    ) -> None:
        self.params = params
        if mode is not None:
            self.mode = str(mode)
        if target_bpm is not None:
            self.target_bpm = float(target_bpm)
        self.profile = _normalize_generation_profile(getattr(params, "generation_profile", "musical"))
        self.pools_summary = {
            "kick": len(pools.kick),
            "snare": len(pools.snare),
            "hat": len(pools.hatish),
            "ghost": len(pools.snare_ghost) + len(pools.kick_ghost),
            "clap": len(pools.clap),
            "snare_ghost": len(pools.snare_ghost),
            "snare_ruff": len(pools.snare_ruff),
            "ride": len(pools.ride),
            "otherish": len(pools.otherish),
        }
        self.sequence_summary = {
            "groove": len(sequence_pools.groove),
            "fill": len(sequence_pools.fill),
            "anticipation": len(sequence_pools.anticipation),
            "cadence": len(sequence_pools.cadence),
        }

    def set_final_pattern(self, pattern: GeneratedBreakPattern) -> None:
        self.final_pattern = pattern
        self.final_steps = {}
        self.fill_decisions = {
            index: decision
            for index, decision in enumerate(getattr(pattern, "fill_decisions", ()))
        }
        for step in pattern.steps:
            bar = max(0, (int(step.step_index) - 1) // self.steps_per_bar)
            local_step = ((int(step.step_index) - 1) % self.steps_per_bar) + 1
            self.final_steps[(bar, local_step)] = step

    def bump_pass_stat(self, passe: str, stat: str, amount: int = 1) -> None:
        pass_name = str(passe or "").strip()
        stat_name = str(stat or "").strip()
        delta = int(amount)
        if not pass_name or not stat_name or delta == 0:
            return
        bucket = self.pass_stats.setdefault(pass_name, {})
        bucket[stat_name] = int(bucket.get(stat_name, 0)) + delta

    def _collision_data(self) -> dict[tuple[int, int], tuple[tuple[str, ...], int]]:
        collisions: dict[tuple[int, int], tuple[tuple[str, ...], int]] = {}
        for key, entries in self.steps.items():
            relevant_entries = [entry for entry in entries if entry.passe != "anchor_reapply"]
            overwrite_count = max(0, len(relevant_entries) - 1)
            if overwrite_count < 2:
                continue
            late_passes = [
                entry.passe
                for entry in relevant_entries
                if entry.passe not in {"skeleton", "sequence_block", "motif_block"}
            ]
            if not late_passes:
                late_passes = [entry.passe for entry in relevant_entries[1:]]
            collisions[key] = (tuple(dict.fromkeys(late_passes)), overwrite_count)
        return collisions

    def _format_params_lines(self) -> list[str]:
        if self.params is None:
            return ["(no params)"]
        params = self.params
        profile_label = _titleize_generation_profile(self.profile)
        lines = [
            f"energy: {_fmt_param(params.energy)}          kick_weight: {_fmt_param(params.kick_weight)}       snare_weight: {_fmt_param(params.snare_weight)}",
            f"hat_density: {_fmt_param(params.hat_density)}      ghost_density: {_fmt_param(params.ghost_density)}     fill_strength: {_fmt_param(params.fill_strength)}",
            f"anti_repeat: {_fmt_param(params.anti_repeat)}      breath_factor: {_fmt_param(params.breath_factor)}     position_fidelity: {_fmt_param(params.position_fidelity)}",
            f"velocity_spread: {_fmt_param(params.velocity_spread)}  swing: {_fmt_param(params.swing)}             sequence_density: {_fmt_param(params.sequence_density)}",
            f"sequence_max_len: {int(params.sequence_max_len)}   sequence_role_lock: {_fmt_bool(params.sequence_role_lock)}  motif_density: {_fmt_param(params.motif_density)}",
            f"generation_profile: {profile_label}",
            "",
            f"repeat_density: {_fmt_param(params.repeat_density)}   repeat_span: {_fmt_param(params.repeat_span)}         repeat_rate: {_format_repeat_rate(params.repeat_rate)}",
            f"reverse_density: {_fmt_param(params.reverse_density)}",
            f"kick_roll_density: {_fmt_param(params.kick_roll_density)}  kick_roll_span: {_fmt_param(params.kick_roll_span)}    kick_roll_contrast: {_fmt_param(params.kick_roll_contrast)}",
            f"snare_stretch_density: {_fmt_param(params.snare_stretch_density)}  snare_stretch_span: {_fmt_param(params.snare_stretch_span)}  snare_stretch_amount: {_fmt_param(params.snare_stretch_amount)}",
            f"snare_stretch_vel_curve: {params.snare_stretch_vel_curve}",
            "",
            f"pitch_mode: {params.pitch_mode}    pitch_scope: {params.pitch_scope}     pitch_scale: {params.pitch_scale}",
            f"pitch_root: {int(params.pitch_root)}         pitch_range: {_fmt_range(params.pitch_range)}  pitch_rate: {params.pitch_rate}",
            f"pitch_amount: {_fmt_param(params.pitch_amount)}",
            "",
            f"synth_ghost_enabled: {_fmt_bool(params.synth_ghost_enabled)}  ghost_vel_range: {_fmt_range(params.ghost_vel_range)}",
            f"ghost_pitch_range: {_fmt_range(params.ghost_pitch_range)}  ghost_gate_ratio: {_fmt_param(params.ghost_gate_ratio)}",
            "",
            f"gate: {_fmt_param(params.gate)}  mono_choke: {_fmt_bool(getattr(params, 'mono_choke', False))}",
        ]
        return lines

    def _format_pass_impact_lines(self) -> list[str]:
        if not self.pass_stats:
            return ["none"]

        preferred_order = (
            "motif_block",
            "sequence_block",
            *PIPELINE_PASS_ORDER,
        )
        ordered_passes = [
            pass_name for pass_name in preferred_order if pass_name in self.pass_stats
        ]
        remaining_passes = sorted(
            pass_name for pass_name in self.pass_stats if pass_name not in ordered_passes
        )
        metric_order = (
            "applied",
            "writes",
            "candidates",
            "skipped_budget",
            "skipped_protected",
            "skipped_probability",
            "skipped_incompatible",
            "skipped_no_source",
            "no_candidate",
            "no_pool",
            "no_trigger",
            "skipped_constraints",
        )
        lines: list[str] = []
        for pass_name in [*ordered_passes, *remaining_passes]:
            stats = self.pass_stats.get(pass_name, {})
            if not stats:
                continue
            stat_parts = [
                f"{metric} {int(stats[metric])}"
                for metric in metric_order
                if int(stats.get(metric, 0)) > 0
            ]
            extra_parts = [
                f"{metric} {int(value)}"
                for metric, value in sorted(stats.items())
                if metric not in metric_order and int(value) > 0
            ]
            joined = " | ".join([*stat_parts, *extra_parts]) or "no activity"
            lines.append(f"{pass_name}: {joined}")
        return lines or ["none"]

    def report(self) -> str:
        collision_data = self._collision_data()
        target_bpm = "-" if self.target_bpm is None else _fmt_param(self.target_bpm)
        header_line = (
            f"seed: {int(self.params.seed) if self.params is not None else '-'} | "
            f"bars: {self.bars} | bpm: {target_bpm} | mode: {self.mode} | "
            f"profile: {_titleize_generation_profile(self.profile)}"
        )
        lines = [
            "=== BREAK GENERATION REPORT ===",
            header_line,
            "",
            "--- PARAMS ---",
            *self._format_params_lines(),
            "",
            "--- POOLS ---",
            " | ".join(f"{name}: {count}" for name, count in self.pools_summary.items()) if self.pools_summary else "(no pools)",
            (
                "sequences: "
                + " | ".join(f"{name} x{count}" for name, count in self.sequence_summary.items())
                if self.sequence_summary
                else "sequences: none"
            ),
            "",
            "--- PASS IMPACT ---",
            *self._format_pass_impact_lines(),
        ]

        for bar in range(self.bars):
            lines.extend(["", f"--- BAR {bar + 1} ---", ""])
            fill_decision = self.fill_decisions.get(bar)
            if fill_decision is not None and bool(fill_decision.active):
                lines.extend(
                    [
                        (
                            f"fill: {fill_decision.fill_type} | "
                            f"zone: {int(fill_decision.zone_start)}-{int(fill_decision.zone_end)} | "
                            f"source: {fill_decision.source}"
                        ),
                        "",
                    ]
                )
            else:
                lines.extend(["fill: none", ""])
            for step in range(1, self.steps_per_bar + 1):
                entries = self.steps.get((bar, step), [])
                lines.append(f"STEP {step}  [{_rhythmic_position_for_step_index((bar * self.steps_per_bar) + step)}]")
                if not entries:
                    lines.append("  (no writes)")
                for entry_index, entry in enumerate(entries):
                    suffix_parts: list[str] = []
                    if entry.note:
                        suffix_parts.append(f"({entry.note})")
                    if entry_index > 0:
                        previous = entries[entry_index - 1]
                        suffix_parts.append(f"<- OVERWRITE {previous.label}")
                    collision = collision_data.get((bar, step))
                    if collision is not None and entry_index == len(entries) - 1:
                        pass_chain, _overwrite_count = collision
                        collision_label = "+".join(pass_chain) if pass_chain else "multi_pass"
                        suffix_parts.append(f"WARNING COLLISION {collision_label}")
                    suffix = f"  {'  '.join(suffix_parts)}" if suffix_parts else ""
                    lines.append(f"  {entry.passe:<15} -> {entry.label:<12}{suffix}".rstrip())
                final_step = self.final_steps.get((bar, step))
                if final_step is not None and _step_is_structurally_protected(final_step):
                    lines.append("  [protected]")
                lines.append("")

        lines.append("--- COLLISIONS SUMMARY ---")
        if collision_data:
            for (bar, step), (pass_chain, overwrite_count) in sorted(collision_data.items()):
                chain_text = " -> ".join(pass_chain) if pass_chain else "multi_pass"
                lines.append(
                    f"bar {bar + 1}, step {step} : {chain_text} ({overwrite_count} overwrite{'s' if overwrite_count > 1 else ''})"
                )
        else:
            lines.append("none")

        lines.extend(["", "--- METRICS ---"])
        metrics = self.final_pattern.metrics if self.final_pattern is not None else {}
        if metrics:
            for metric_name, metric_value in metrics.items():
                lines.append(f"{metric_name}:   {_fmt_param(metric_value)}")
        else:
            lines.append("none")
        return "\n".join(lines).rstrip() + "\n"


@dataclass
class PipelineState:
    snapshots: list[tuple[str, GeneratedBreakPattern]]
    current: GeneratedBreakPattern
    hits: tuple[TransientHit, ...]
    sequences: tuple[HitSequence, ...]
    params: BreakPatternParams
    log: DebugLog
    anchors: dict[int, str] = field(default_factory=dict)
    use_hybrid: bool = False
    user_motifs: tuple[UserMotif, ...] = ()
    _log_snapshots: list[tuple[str, DebugLog]] = field(default_factory=list, repr=False)

    def snapshot(self, passe: str):
        self.snapshots.append((str(passe), deepcopy(self.current)))
        self._log_snapshots.append((str(passe), deepcopy(self.log)))

    def rollback_to(self, passe: str) -> bool:
        target = str(passe)
        for index in range(len(self.snapshots) - 1, -1, -1):
            snapshot_name, snapshot_pattern = self.snapshots[index]
            if snapshot_name != target:
                continue
            _log_name, snapshot_log = self._log_snapshots[index]
            self.current = deepcopy(snapshot_pattern)
            self.log = deepcopy(snapshot_log)
            self.snapshots = self.snapshots[: index + 1]
            self._log_snapshots = self._log_snapshots[: index + 1]
            return True
        return False

    def last_snapshot_name(self) -> str:
        if not self.snapshots:
            return ""
        return str(self.snapshots[-1][0])


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
    synth_ghost_enabled: bool
    ghost_vel_range: tuple[float, float]
    ghost_pitch_range: tuple[float, float]
    ghost_gate_ratio: float
    fill_strength: float
    fill_type_weights: tuple[tuple[str, float], ...]
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
    snare_stretch_vel_curve: str
    pitch_mode: str
    pitch_scope: str
    pitch_scale: str
    pitch_root: int
    pitch_range: tuple[float, float]
    pitch_sequence: tuple[float, ...]
    pitch_curve: str
    pitch_curve_range: tuple[float, float]
    pitch_rate: str
    pitch_amount: float
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
    generation_profile: str


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
_PRIMARY_STRONG_STEPS = frozenset({1})
_SECONDARY_STRONG_STEPS = frozenset({9})
_PRIMARY_BACKBEAT_STEPS = frozenset({5})
_SECONDARY_BACKBEAT_STEPS = frozenset({13})
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
_SNARE_STRETCH_VEL_CURVES = frozenset({"flat", "decay", "crescendo", "random"})
_GENERATION_PROFILES = frozenset({"safe", "musical", "destructive"})
STRETCH_TICKS_PER_STEP = 96
FILL_TYPES: dict[str, dict[str, object]] = {
    "ghost_hat": {
        "density": "light",
        "typical_zone": (13, 16),
    },
    "ruff": {
        "density": "medium",
        "typical_zone": (14, 16),
    },
    "crash_open": {
        "density": "light",
        "typical_zone": (15, 16),
    },
    "double_kick": {
        "density": "medium",
        "typical_zone": (14, 16),
    },
    "dense": {
        "density": "heavy",
        "typical_zone": (12, 16),
    },
    "perc_burst": {
        "density": "medium",
        "typical_zone": (13, 16),
    },
    "kick_snare_alternance": {
        "density": "heavy",
        "typical_zone": (13, 16),
    },
    "silence_drop": {
        "density": "none",
        "typical_zone": (13, 16),
    },
}
FILL_STYLE_AUTO = "auto"
FILL_STYLE_LABELS: dict[str, str] = {
    FILL_STYLE_AUTO: "Auto",
    "ghost_hat": "Ghost + Hat",
    "ruff": "Ruff",
    "crash_open": "Crash / Open",
    "double_kick": "Double kick",
    "dense": "Dense",
    "perc_burst": "Perc burst",
    "kick_snare_alternance": "Kick / Snare alt.",
    "silence_drop": "Silence drop",
}
FILL_STYLE_OPTIONS: tuple[str, ...] = tuple(FILL_STYLE_LABELS.keys())
PIPELINE_PASS_ORDER: tuple[str, ...] = (
    "skeleton",
    "ghost_pass",
    "fill_pass",
    "resolution_pass",
    "kick_roll_pass",
    "repeat_pass",
    "reverse_pass",
    "snare_stretch_pass",
    "velocity_pass",
    "pitch_pass",
    "anchor_reapply",
)
TOGGLEABLE_PIPELINE_PASSES: tuple[str, ...] = tuple(
    pass_name for pass_name in PIPELINE_PASS_ORDER if pass_name != "skeleton"
)
_PITCH_MODES = frozenset({"off", "random", "sequence", "curve"})
_PITCH_SCOPES = frozenset({"snare", "snare+clap", "all_pillar", "all"})
_PITCH_SCALES: dict[str, tuple[int, ...]] = {
    "chromatic": tuple(range(12)),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "pentatonic": (0, 2, 4, 7, 9),
    "diminished": (0, 2, 3, 5, 6, 8, 9, 11),
}
_PITCH_CURVES = frozenset({"up", "down", "bell", "inv_bell"})
_PITCH_RATES = frozenset({"every_hit", "every_2", "every_bar"})
_FILL_TYPE_NAMES = frozenset(FILL_TYPES.keys())
_FILL_LIGHT_TYPES = frozenset(
    fill_type for fill_type, meta in FILL_TYPES.items() if str(meta.get("density", "")) == "light"
)
_FILL_NON_DENSE_TYPES = frozenset(fill_type for fill_type in FILL_TYPES if fill_type != "dense")
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


def _build_skeleton_steps(
    hits: Iterable[TransientHit],
    params: BreakPatternParams,
    resolved_params: "_ResolvedPatternParams",
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    fill_decisions: Iterable[FillDecision] | None = None,
    log: DebugLog | None = None,
) -> tuple[list[GeneratedPatternStep], "_PatternPools", "_SequencePools", dict[int, str], tuple[FillDecision, ...], np.random.Generator]:
    ordered_hits = tuple(sorted(hits, key=lambda hit: (float(hit.start_s), int(hit.index))))
    pools = _build_pools(ordered_hits)
    sequence_pools = _build_sequence_pools(tuple(sequences or ()), max_hit_count=resolved_params.sequence_max_len)
    step_count = max(16, int(max(1, params.bars) * 16))
    normalized_anchors = _normalize_step_anchors(anchors, step_count=step_count)
    rng = np.random.default_rng(int(params.seed))
    fill_decisions = list(fill_decisions or _decide_fill_map(resolved_params, bars=max(1, int(step_count // 16)), rng=rng))
    if log is not None:
        if not str(log.mode or "").strip():
            log.mode = "Classic"
        log.set_context(params=params, pools=pools, sequence_pools=sequence_pools)

    generated_steps: list[GeneratedPatternStep] = []
    step_index = 1
    while step_index <= step_count:
        bar_index = max(0, (int(step_index) - 1) // 16)
        fill_decision = _fill_decision_for_bar(fill_decisions, bar_index)
        local_step = ((int(step_index) - 1) % 16) + 1
        if fill_decision is not None and bool(fill_decision.active) and int(fill_decision.zone_start) <= local_step <= int(fill_decision.zone_end):
            zone_start_step = (int(bar_index) * 16) + int(fill_decision.zone_start)
            anchor = normalized_anchors.get(step_index)
            if int(step_index) == int(zone_start_step) and anchor is None:
                sequence = _pick_fill_sequence_for_decision(
                    step_index,
                    generated_steps,
                    sequence_pools,
                    pools,
                    resolved_params,
                    rng,
                    decision=fill_decision,
                    anchors=normalized_anchors,
                )
                if sequence is not None:
                    sequence_decision = replace(fill_decision, source="sequence")
                    fill_decisions[bar_index] = sequence_decision
                    sequence_steps = [
                        _merge_fill_decision_tags(sequence_step, sequence_decision)
                        for sequence_step in _sequence_block_steps(step_index, sequence, anchors=normalized_anchors)
                    ]
                    if log is not None:
                        for offset, sequence_step in enumerate(sequence_steps):
                            note = _debug_note_for_sequence_step(sequence, sequence_step, offset=offset)
                            log.write_step_index(sequence_step.step_index, "sequence_block", sequence_step.label, note)
                            log.bump_pass_stat("sequence_block", "writes")
                    generated_steps.extend(sequence_steps)
                    step_index += int(sequence.total_steps)
                    continue

            if anchor is not None:
                reserved_step = _select_anchored_step_event(step_index, anchor, generated_steps, pools, resolved_params, rng)
                reserved_step = _merge_fill_decision_tags(reserved_step, fill_decision)
                if log is not None:
                    log.write_step_index(
                        reserved_step.step_index,
                        "skeleton",
                        reserved_step.label,
                        _debug_note_for_skeleton_step(reserved_step, family=anchor, anchor=anchor),
                    )
                    log.bump_pass_stat("skeleton", "writes")
                generated_steps.append(reserved_step)
                step_index += 1
                continue

            reserved_step = _merge_fill_decision_tags(
                GeneratedPatternStep(
                    step_index=int(step_index),
                    label="silence",
                    velocity=0,
                    source_hit_index=None,
                    source_label=None,
                    source_start_s=None,
                    source_end_s=None,
                    tags=tuple(dict.fromkeys((_step_tag(step_index), "fill_reserved", "fill_pending", "phrase_end"))),
                ),
                fill_decision,
            )
            if log is not None:
                log.write_step_index(
                    reserved_step.step_index,
                    "skeleton",
                    reserved_step.label,
                    f"reserved fill zone {fill_decision.fill_type}",
                )
                log.bump_pass_stat("skeleton", "writes")
            generated_steps.append(reserved_step)
            step_index += 1
            continue

        sequence = _pick_sequence_for_step(
            step_index,
            generated_steps,
            sequence_pools,
            pools,
            resolved_params,
            rng,
            anchors=normalized_anchors,
            fill_decisions=tuple(fill_decisions),
        )
        if sequence is not None:
            sequence_steps = _sequence_block_steps(step_index, sequence, anchors=normalized_anchors)
            if log is not None:
                for offset, sequence_step in enumerate(sequence_steps):
                    note = _debug_note_for_sequence_step(sequence, sequence_step, offset=offset)
                    log.write_step_index(sequence_step.step_index, "sequence_block", sequence_step.label, note)
                    log.bump_pass_stat("sequence_block", "writes")
            generated_steps.extend(sequence_steps)
            step_index += int(sequence.total_steps)
            continue
        anchor = normalized_anchors.get(step_index)
        if anchor is not None:
            anchored_step = _select_anchored_step_event(step_index, anchor, generated_steps, pools, resolved_params, rng)
            if log is not None:
                log.write_step_index(
                    anchored_step.step_index,
                    "skeleton",
                    anchored_step.label,
                    _debug_note_for_skeleton_step(anchored_step, family=anchor, anchor=anchor),
                )
                log.bump_pass_stat("skeleton", "writes")
            generated_steps.append(anchored_step)
            step_index += 1
            continue
        family_weights = _step_family_weights(step_index, generated_steps, pools, resolved_params)
        selected_step, family = _select_step_event_with_fallback(
            step_index,
            family_weights,
            generated_steps,
            pools,
            resolved_params,
            rng,
        )
        if log is not None:
            log.write_step_index(
                selected_step.step_index,
                "skeleton",
                selected_step.label,
                _debug_note_for_skeleton_step(selected_step, family=family),
            )
            log.bump_pass_stat("skeleton", "writes")
        generated_steps.append(selected_step)
        step_index += 1
    _reinforce_skeleton_structure(generated_steps, pools, resolved_params, rng, log=log)
    return generated_steps, pools, sequence_pools, normalized_anchors, tuple(fill_decisions), rng


def generate_break_pattern(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    log: DebugLog | None = None,
) -> GeneratedBreakPattern:
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    enabled_passes = set(_normalize_enabled_passes(getattr(effective_params, "enabled_passes", TOGGLEABLE_PIPELINE_PASSES)))
    generated_steps, pools, _sequence_pools, normalized_anchors, fill_decisions, rng = _build_skeleton_steps(
        hits,
        effective_params,
        resolved_params,
        sequences=sequences,
        anchors=anchors,
        log=log,
    )

    _apply_post_generation_passes(
        generated_steps,
        pools,
        resolved_params,
        rng,
        anchors=normalized_anchors,
        fill_decisions=fill_decisions,
        log=log,
        enabled_passes=enabled_passes,
    )
    finalized_steps = list(generated_steps)
    if "velocity_pass" in enabled_passes:
        finalized_steps = _apply_velocity_pass_steps(
            finalized_steps,
            resolved_params,
            seed=int(effective_params.seed),
            log=log,
        )
    if "pitch_pass" in enabled_passes:
        finalized_steps = _apply_pitch_movement(finalized_steps, resolved_params, seed=int(effective_params.seed), log=log)
    pattern = _build_generated_pattern(
        tuple(finalized_steps),
        effective_params,
        resolved_params,
        fill_decisions=fill_decisions,
    )
    if log is not None:
        log.set_final_pattern(pattern)
    return pattern


def generate_break_pattern_hybrid(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    user_motifs: Iterable[UserMotif] | None = None,
    log: DebugLog | None = None,
) -> GeneratedBreakPattern:
    effective_params = params or BreakPatternParams()
    resolved_params = _resolve_params(effective_params)
    if log is not None:
        log.mode = "Hybrid"
    normalized_motifs = _normalize_user_motifs(
        tuple(user_motifs) if user_motifs is not None else tuple(effective_params.user_motifs)
    )
    if resolved_params.motif_density <= 1e-6 or not normalized_motifs:
        return generate_break_pattern(hits, effective_params, sequences=sequences, anchors=anchors, log=log)

    step_count = max(16, int(max(1, effective_params.bars) * 16))
    normalized_anchors = _normalize_step_anchors(anchors, step_count=step_count)
    rng = np.random.default_rng(int(effective_params.seed))
    fill_decisions = _decide_fill_map(
        resolved_params,
        bars=max(1, int(effective_params.bars)),
        rng=np.random.default_rng(int(effective_params.seed)),
    )
    motif_anchors, _placements = _build_hybrid_motif_anchors(
        normalized_motifs,
        effective_params,
        resolved_params,
        step_count=step_count,
        manual_anchors=normalized_anchors,
        rng=rng,
        fill_decisions=fill_decisions,
        log=log,
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
        log=log,
    )


def generate_break_pattern_for_mode(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    use_hybrid: bool = False,
    user_motifs: Iterable[UserMotif] | None = None,
    log: DebugLog | None = None,
) -> GeneratedBreakPattern:
    if bool(use_hybrid):
        return generate_break_pattern_hybrid(
            hits,
            params,
            sequences=sequences,
            anchors=anchors,
            user_motifs=user_motifs,
            log=log,
        )
    return generate_break_pattern(
        hits,
        params,
        sequences=sequences,
        anchors=anchors,
        log=log,
    )


def generate_break_pattern_debug(
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None = None,
    *,
    sequences: Iterable[HitSequence] | None = None,
    anchors: Mapping[int, str | None] | None = None,
    use_hybrid: bool = False,
    user_motifs: Iterable[UserMotif] | None = None,
    target_bpm: float | None = None,
) -> tuple[GeneratedBreakPattern, str]:
    effective_params = params or BreakPatternParams()
    debug_log = DebugLog(bars=max(1, int(effective_params.bars)))
    debug_log.mode = "Hybrid" if bool(use_hybrid) else "Classic"
    if target_bpm is not None:
        debug_log.target_bpm = float(target_bpm)
    pattern = generate_break_pattern_for_mode(
        hits,
        effective_params,
        sequences=sequences,
        anchors=anchors,
        use_hybrid=use_hybrid,
        user_motifs=user_motifs,
        log=debug_log,
    )
    debug_log.set_final_pattern(pattern)
    return pattern, debug_log.report()


def _post_generation_pipeline(profile: str) -> tuple[str, ...]:
    normalized = _normalize_generation_profile(profile)
    if normalized == "destructive":
        return (
            "ghost_pass",
            "fill_pass",
            "resolution_pass",
            "kick_roll_pass",
            "repeat_pass",
            "anchor_reapply",
            "snare_stretch_pass",
            "reverse_pass",
        )
    return (
        "ghost_pass",
        "fill_pass",
        "resolution_pass",
        "kick_roll_pass",
        "repeat_pass",
        "snare_stretch_pass",
        "reverse_pass",
        "anchor_reapply",
    )


def _apply_post_generation_passes(
    steps: list[GeneratedPatternStep],
    pools: "_PatternPools",
    params: "_ResolvedPatternParams",
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
    fill_decisions: Iterable[FillDecision] | None = None,
    log: DebugLog | None = None,
    enabled_passes: Iterable[str] | None = None,
) -> None:
    enabled_set = set(_normalize_enabled_passes(tuple(enabled_passes) if enabled_passes is not None else TOGGLEABLE_PIPELINE_PASSES))
    pipeline = tuple(pass_name for pass_name in _post_generation_pipeline(params.generation_profile) if pass_name in enabled_set)
    for pass_name in pipeline:
        if pass_name == "ghost_pass":
            _inject_ghost_notes(steps, pools, params, rng, log=log)
        elif pass_name == "fill_pass":
            _apply_fill_blocks(steps, pools, params, rng, fill_decisions=fill_decisions, log=log)
        elif pass_name == "resolution_pass":
            _apply_bar_start_resolutions(steps, pools, params, rng, log=log)
        elif pass_name == "kick_roll_pass":
            _apply_kick_rolls(steps, pools, params, rng, anchors=anchors, log=log)
        elif pass_name == "repeat_pass":
            _apply_repeat_blocks(steps, params, rng, anchors=anchors, log=log)
        elif pass_name == "anchor_reapply":
            _enforce_step_anchors(steps, anchors, pools, params, rng, log=log)
        elif pass_name == "snare_stretch_pass":
            _apply_snare_stretches(steps, pools, params, rng, anchors=anchors, log=log)
        elif pass_name == "reverse_pass":
            _apply_reverse_steps(steps, params, rng, anchors=anchors, log=log)


def _manual_pass_rng(seed: int, pass_name: str) -> np.random.Generator:
    salt = 0x811C9DC5
    for char in str(pass_name):
        salt ^= ord(char)
        salt = (salt * 0x01000193) & 0xFFFFFFFF
    return np.random.default_rng((int(seed) & 0xFFFFFFFF) ^ salt)


def _anchors_from_pattern(pattern: GeneratedBreakPattern) -> dict[int, str]:
    anchors: dict[int, str] = {}
    for step in pattern.steps:
        for tag in step.tags:
            if not str(tag).startswith("anchor_"):
                continue
            anchor = _normalize_anchor_value(str(tag).removeprefix("anchor_"))
            if anchor is not None:
                anchors[int(step.step_index)] = anchor
                break
    return anchors


def _pattern_pass_params(pattern: GeneratedBreakPattern, params: BreakPatternParams | None) -> BreakPatternParams:
    source_params = params or pattern.params
    return replace(
        source_params,
        bars=max(1, int(pattern.bars)),
        seed=int(pattern.seed),
        enabled_passes=_normalize_enabled_passes(getattr(source_params, "enabled_passes", TOGGLEABLE_PIPELINE_PASSES)),
    )


def _manual_pass_context(
    pattern: GeneratedBreakPattern,
    hits: Iterable[TransientHit],
    params: BreakPatternParams | None,
    *,
    anchors: Mapping[int, str | None] | None = None,
    log: DebugLog | None = None,
) -> tuple[BreakPatternParams, _ResolvedPatternParams, _PatternPools, dict[int, str]]:
    effective_params = _pattern_pass_params(pattern, params)
    resolved_params = _resolve_params(effective_params)
    ordered_hits = tuple(sorted(hits, key=lambda hit: (float(hit.start_s), int(hit.index))))
    pools = _build_pools(ordered_hits)
    normalized_anchors = _normalize_step_anchors(
        anchors if anchors is not None else _anchors_from_pattern(pattern),
        step_count=max(16, int(pattern.step_count)),
    )
    if log is not None:
        empty_sequence_pools = _build_sequence_pools((), max_hit_count=resolved_params.sequence_max_len)
        log.set_context(params=effective_params, pools=pools, sequence_pools=empty_sequence_pools)
    return effective_params, resolved_params, pools, normalized_anchors


def _build_pattern_after_manual_pass(
    steps: list[GeneratedPatternStep],
    params: BreakPatternParams,
    resolved_params: _ResolvedPatternParams,
    *,
    fill_decisions: Iterable[FillDecision] | None = None,
    log: DebugLog | None = None,
) -> GeneratedBreakPattern:
    pattern = _build_generated_pattern(
        tuple(steps),
        params,
        resolved_params,
        fill_decisions=fill_decisions,
    )
    if log is not None:
        log.set_final_pattern(pattern)
    return pattern


def _apply_velocity_pass_steps(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    *,
    seed: int,
    log: DebugLog | None = None,
) -> list[GeneratedPatternStep]:
    base_steps = [
        step if int(getattr(step, "velocity", 0)) == 0 else replace(step, velocity=0)
        for step in steps
    ]
    rng = _manual_pass_rng(seed, "velocity_pass")
    updated_steps = [_finalize_step_velocity(step, base_steps, params, rng) for step in base_steps]
    updated_steps = _refresh_snare_stretch_velocity_curves(updated_steps, params, rng)
    if log is not None:
        for previous_step, current_step in zip(steps, updated_steps):
            if previous_step.label == current_step.label and int(previous_step.velocity) == int(current_step.velocity):
                continue
            _debug_log_step_write(
                log,
                pass_name="velocity_pass",
                step=current_step,
                note=_debug_note_for_velocity_step(current_step),
            )
    return updated_steps


def _refresh_snare_stretch_velocity_curves(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> list[GeneratedPatternStep]:
    if not steps:
        return []

    updated_steps = list(steps)
    for step in tuple(steps):
        if "snare_stretch" not in set(step.tags):
            continue
        retriggers = tuple(getattr(step, "stretch_retriggers", ()) or ())
        if not retriggers:
            continue
        zone_span = next(
            (
                int(str(tag).split("_")[-1])
                for tag in step.tags
                if str(tag).startswith("snare_stretch_zone_span_")
            ),
            2,
        )
        source_hit = next((retrigger.slice_source for retrigger in retriggers if retrigger.slice_source is not None), None)
        if source_hit is None:
            continue
        refreshed = _build_snare_stretch_retriggers(
            step,
            source_hit,
            span_steps=int(max(2, zone_span)),
            params=params,
            rng=rng,
        )
        for zone_offset in range(int(max(2, zone_span))):
            target_index = int(step.step_index) + zone_offset
            if target_index > len(updated_steps):
                break
            updated_steps[target_index - 1] = replace(updated_steps[target_index - 1], stretch_retriggers=refreshed)
    return updated_steps


def generate_break_skeleton_only(
    hits: list[TransientHit],
    sequences: list[HitSequence] | None,
    params: BreakPatternParams,
    *,
    anchors: Mapping[int, str | None] | None = None,
    use_hybrid: bool = False,
    user_motifs: Iterable[UserMotif] | None = None,
    log: DebugLog | None = None,
) -> PipelineState:
    effective_params = params or BreakPatternParams()
    debug_log = log or DebugLog(bars=max(1, int(effective_params.bars)))
    debug_log.mode = "Hybrid" if bool(use_hybrid) else "Classic"

    ordered_hits = tuple(sorted(hits, key=lambda hit: (float(hit.start_s), int(hit.index))))
    ordered_sequences = tuple(sequences or ())
    normalized_user_motifs = _normalize_user_motifs(
        tuple(user_motifs) if user_motifs is not None else tuple(effective_params.user_motifs)
    )

    skeleton_params = effective_params
    skeleton_anchors = anchors
    resolved_params = _resolve_params(effective_params)
    prefill_decisions = _decide_fill_map(
        resolved_params,
        bars=max(1, int(effective_params.bars)),
        rng=np.random.default_rng(int(effective_params.seed)),
    )
    if bool(use_hybrid) and resolved_params.motif_density > 1e-6 and normalized_user_motifs:
        step_count = max(16, int(max(1, effective_params.bars) * 16))
        manual_anchors = _normalize_step_anchors(anchors, step_count=step_count)
        motif_anchors, _placements = _build_hybrid_motif_anchors(
            normalized_user_motifs,
            effective_params,
            resolved_params,
            step_count=step_count,
            manual_anchors=manual_anchors,
            rng=np.random.default_rng(int(effective_params.seed)),
            fill_decisions=prefill_decisions,
            log=debug_log,
        )
        skeleton_anchors = {**motif_anchors, **manual_anchors}
        skeleton_params = replace(effective_params, user_motifs=[*normalized_user_motifs])
        resolved_params = _resolve_params(skeleton_params)
        prefill_decisions = _decide_fill_map(
            resolved_params,
            bars=max(1, int(skeleton_params.bars)),
            rng=np.random.default_rng(int(skeleton_params.seed)),
        )

    generated_steps, _pools, _sequence_pools, normalized_anchors, fill_decisions, _rng = _build_skeleton_steps(
        ordered_hits,
        skeleton_params,
        resolved_params,
        sequences=ordered_sequences,
        anchors=skeleton_anchors,
        fill_decisions=prefill_decisions,
        log=debug_log,
    )
    pattern = _build_generated_pattern(
        tuple(generated_steps),
        skeleton_params,
        resolved_params,
        fill_decisions=fill_decisions,
    )
    debug_log.set_final_pattern(pattern)
    state = PipelineState(
        snapshots=[],
        current=pattern,
        hits=ordered_hits,
        sequences=ordered_sequences,
        params=skeleton_params,
        log=debug_log,
        anchors=dict(normalized_anchors),
        use_hybrid=bool(use_hybrid),
        user_motifs=tuple(normalized_user_motifs),
    )
    state.snapshot("skeleton")
    return state


def apply_ghost_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, pools, _normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _inject_ghost_notes(steps, pools, resolved_params, _manual_pass_rng(effective_params.seed, "ghost_pass"), log=log)
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_fill_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    fill_decision: FillDecision | None = None,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, pools, _normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _apply_fill_blocks(
        steps,
        pools,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "fill_pass"),
        fill_decisions=(
            (fill_decision,)
            if fill_decision is not None
            else pattern.fill_decisions
        ),
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_resolution_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, pools, _normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _apply_bar_start_resolutions(
        steps,
        pools,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "resolution_pass"),
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_kick_roll_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, pools, normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _apply_kick_rolls(
        steps,
        pools,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "kick_roll_pass"),
        anchors=normalized_anchors,
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_repeat_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, _pools, normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _apply_repeat_blocks(
        steps,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "repeat_pass"),
        anchors=normalized_anchors,
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_reverse_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, _pools, normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _apply_reverse_steps(
        steps,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "reverse_pass"),
        anchors=normalized_anchors,
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_snare_stretch_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, _pools, normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _apply_snare_stretches(
        steps,
        _pools,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "snare_stretch_pass"),
        anchors=normalized_anchors,
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_velocity_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, _pools, _normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    updated_steps = _apply_velocity_pass_steps(
        list(pattern.steps),
        resolved_params,
        seed=int(effective_params.seed),
        log=log,
    )
    return _build_pattern_after_manual_pass(
        updated_steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_pitch_pass(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, _pools, _normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    updated_steps = _apply_pitch_movement(
        list(pattern.steps),
        resolved_params,
        seed=int(effective_params.seed),
        log=log,
    )
    return _build_pattern_after_manual_pass(
        updated_steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
    )


def apply_anchor_reapply(
    pattern: GeneratedBreakPattern,
    hits: list[TransientHit],
    params: BreakPatternParams,
    log: DebugLog | None = None,
    *,
    anchors: Mapping[int, str | None] | None = None,
) -> GeneratedBreakPattern:
    effective_params, resolved_params, pools, normalized_anchors = _manual_pass_context(
        pattern, hits, params, anchors=anchors, log=log
    )
    steps = list(pattern.steps)
    _enforce_step_anchors(
        steps,
        normalized_anchors,
        pools,
        resolved_params,
        _manual_pass_rng(effective_params.seed, "anchor_reapply"),
        log=log,
    )
    return _build_pattern_after_manual_pass(
        steps,
        effective_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
        log=log,
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
        fill_decisions=pattern.fill_decisions,
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
    pitched_steps = _apply_pitch_movement(updated_steps, resolved_params, seed=int(reroll_params.seed))
    return _build_generated_pattern(
        tuple(pitched_steps),
        reroll_params,
        resolved_params,
        fill_decisions=pattern.fill_decisions,
    )


def _resolve_params(params: BreakPatternParams) -> _ResolvedPatternParams:
    energy = float(np.clip(params.energy, 0.0, 1.0))
    ghost_vel_range = _normalize_ratio_range(params.ghost_vel_range, default=(0.2, 0.45))
    ghost_pitch_range = _normalize_pitch_range(params.ghost_pitch_range, default=(0.0, 0.0), minimum=-2.0, maximum=2.0)
    pitch_range = _normalize_pitch_range(params.pitch_range, default=(-12.0, 12.0))
    pitch_curve_range = _normalize_pitch_range(params.pitch_curve_range, default=(-7.0, 7.0))
    fill_type_weights = _normalize_fill_type_weights(getattr(params, "fill_type_weights", None))
    return _ResolvedPatternParams(
        kick_weight=_scaled_density_control(params.kick_weight, energy, low_scale=0.9, high_scale=1.1),
        snare_weight=_scaled_density_control(params.snare_weight, energy, low_scale=0.9, high_scale=1.1),
        hat_density=_scaled_density_control(params.hat_density, energy, low_scale=0.65, high_scale=1.35),
        ghost_density=_scaled_density_control(params.ghost_density, energy, low_scale=0.4, high_scale=1.55),
        synth_ghost_enabled=bool(params.synth_ghost_enabled),
        ghost_vel_range=ghost_vel_range,
        ghost_pitch_range=ghost_pitch_range,
        ghost_gate_ratio=float(np.clip(float(params.ghost_gate_ratio), 0.0, 1.0)),
        fill_strength=_scaled_density_control(params.fill_strength, energy, low_scale=0.55, high_scale=1.45),
        fill_type_weights=fill_type_weights,
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
        snare_stretch_vel_curve=_normalize_snare_stretch_vel_curve(params.snare_stretch_vel_curve),
        pitch_mode=_normalize_pitch_mode(params.pitch_mode),
        pitch_scope=_normalize_pitch_scope(params.pitch_scope),
        pitch_scale=_normalize_pitch_scale(params.pitch_scale),
        pitch_root=int(np.clip(int(params.pitch_root), 0, 11)),
        pitch_range=pitch_range,
        pitch_sequence=_normalize_pitch_sequence(params.pitch_sequence),
        pitch_curve=_normalize_pitch_curve(params.pitch_curve),
        pitch_curve_range=pitch_curve_range,
        pitch_rate=_normalize_pitch_rate(params.pitch_rate),
        pitch_amount=float(np.clip(params.pitch_amount, 0.0, 1.0)),
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
        generation_profile=_normalize_generation_profile(getattr(params, "generation_profile", "musical")),
    )


def _normalize_generation_profile(value: object) -> str:
    normalized = str(value or "musical").strip().lower().replace(" ", "_")
    return normalized if normalized in _GENERATION_PROFILES else "musical"


def _titleize_generation_profile(value: object) -> str:
    normalized = _normalize_generation_profile(value)
    return {
        "safe": "Safe",
        "musical": "Musical",
        "destructive": "Destructive",
    }.get(normalized, "Musical")


def _normalize_enabled_passes(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raw_values: tuple[str, ...] = TOGGLEABLE_PIPELINE_PASSES
    else:
        raw_values = tuple(str(item or "").strip() for item in value)
    normalized_values = {
        str(item).strip().lower()
        for item in raw_values
        if str(item or "").strip().lower() in TOGGLEABLE_PIPELINE_PASSES
    }
    return tuple(pass_name for pass_name in TOGGLEABLE_PIPELINE_PASSES if pass_name in normalized_values)


def _normalize_pitch_mode(value: object) -> str:
    normalized = str(value or "off").strip().lower()
    return normalized if normalized in _PITCH_MODES else "off"


def _normalize_pitch_scope(value: object) -> str:
    normalized = str(value or "snare").strip().lower()
    return normalized if normalized in _PITCH_SCOPES else "snare"


def _normalize_pitch_scale(value: object) -> str:
    normalized = str(value or "chromatic").strip().lower()
    return normalized if normalized in _PITCH_SCALES else "chromatic"


def _normalize_pitch_curve(value: object) -> str:
    normalized = str(value or "up").strip().lower()
    return normalized if normalized in _PITCH_CURVES else "up"


def _normalize_snare_stretch_vel_curve(value: object) -> str:
    normalized = str(value or "decay").strip().lower().replace(" ", "_")
    return normalized if normalized in _SNARE_STRETCH_VEL_CURVES else "decay"


def _normalize_pitch_rate(value: object) -> str:
    normalized = str(value or "every_hit").strip().lower()
    return normalized if normalized in _PITCH_RATES else "every_hit"


def _normalize_fill_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if normalized in _FILL_TYPE_NAMES:
        return normalized
    return None


def _normalize_fill_type_weights(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, Mapping):
        return ()
    normalized: list[tuple[str, float]] = []
    for raw_fill_type, raw_weight in value.items():
        fill_type = _normalize_fill_type(raw_fill_type)
        if fill_type is None:
            continue
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            continue
        if weight <= 1e-6:
            continue
        normalized.append((fill_type, float(weight)))
    normalized.sort(key=lambda item: item[0])
    return tuple(normalized)


def _normalize_pitch_range(
    value: object,
    *,
    default: tuple[float, float],
    minimum: float = -24.0,
    maximum: float = 24.0,
) -> tuple[float, float]:
    min_bound = float(min(minimum, maximum))
    max_bound = float(max(minimum, maximum))
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            lower_value = float(value[0])
            upper_value = float(value[1])
        except (TypeError, ValueError):
            lower_value, upper_value = default
    else:
        lower_value, upper_value = default
    lower = float(np.clip(min(lower_value, upper_value), min_bound, max_bound))
    upper = float(np.clip(max(lower_value, upper_value), min_bound, max_bound))
    return lower, upper


def _normalize_ratio_range(value: object, *, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            lower = float(value[0])
            upper = float(value[1])
        except (TypeError, ValueError):
            lower, upper = default
    else:
        lower, upper = default
    return (
        float(np.clip(min(lower, upper), 0.0, 1.0)),
        float(np.clip(max(lower, upper), 0.0, 1.0)),
    )


def _normalize_pitch_sequence(values: object) -> tuple[float, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    normalized: list[float] = []
    for value in values:
        try:
            normalized.append(float(np.clip(float(value), -24.0, 24.0)))
        except (TypeError, ValueError):
            continue
    return tuple(normalized)


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


def _fill_decision_zone_length(decision: FillDecision) -> int:
    if not bool(decision.active):
        return 0
    return int(max(0, int(decision.zone_end) - int(decision.zone_start) + 1))


def _fill_decision_for_bar(
    fill_decisions: Iterable[FillDecision] | None,
    bar_index: int,
) -> FillDecision | None:
    if fill_decisions is None:
        return None
    decisions = tuple(fill_decisions)
    if bar_index < 0 or bar_index >= len(decisions):
        return None
    return decisions[bar_index]


def _fill_decision_for_step(
    fill_decisions: Iterable[FillDecision] | None,
    step_index: int,
) -> FillDecision | None:
    decisions = tuple(fill_decisions or ())
    if not decisions:
        return None
    bar_index = max(0, (int(step_index) - 1) // 16)
    decision = _fill_decision_for_bar(decisions, bar_index)
    if decision is None or not bool(decision.active):
        return None
    local_step = ((int(step_index) - 1) % 16) + 1
    if int(decision.zone_start) <= local_step <= int(decision.zone_end):
        return decision
    return None


def _step_fill_decision(step: GeneratedPatternStep) -> FillDecision | None:
    if "fill_reserved_zone" not in set(step.tags):
        return None
    fill_type = next(
        (
            str(tag).removeprefix("fill_type_")
            for tag in step.tags
            if str(tag).startswith("fill_type_")
        ),
        "",
    )
    source = next(
        (
            str(tag).removeprefix("fill_source_")
            for tag in step.tags
            if str(tag).startswith("fill_source_")
        ),
        "generated",
    )
    zone_start = next(
        (
            int(str(tag).removeprefix("fill_zone_start_"))
            for tag in step.tags
            if str(tag).startswith("fill_zone_start_")
        ),
        16,
    )
    zone_end = next(
        (
            int(str(tag).removeprefix("fill_zone_end_"))
            for tag in step.tags
            if str(tag).startswith("fill_zone_end_")
        ),
        16,
    )
    return FillDecision(
        active=True,
        fill_type=_normalize_fill_type(fill_type) or "ghost_hat",
        zone_start=int(zone_start),
        zone_end=int(zone_end),
        source=str(source or "generated"),
    )


def _fill_decision_tags(step_index: int, decision: FillDecision) -> tuple[str, ...]:
    local_step = ((int(step_index) - 1) % 16) + 1
    tags = [
        "fill_reserved_zone",
        f"fill_type_{decision.fill_type}",
        f"fill_source_{decision.source}",
        f"fill_zone_start_{int(decision.zone_start)}",
        f"fill_zone_end_{int(decision.zone_end)}",
    ]
    if local_step == int(decision.zone_start):
        tags.append("fill_reserved_zone_start")
    if local_step == int(decision.zone_end):
        tags.append("fill_reserved_zone_end")
    return tuple(tags)


def _merge_fill_decision_tags(step: GeneratedPatternStep, decision: FillDecision) -> GeneratedPatternStep:
    merged_tags = tuple(dict.fromkeys((*step.tags, *_fill_decision_tags(int(step.step_index), decision))))
    return replace(step, tags=merged_tags)


def _step_in_fill_reserved_zone(step: GeneratedPatternStep) -> bool:
    return "fill_reserved_zone" in set(step.tags)


def _zone_intersects_fill_reserved(
    steps: list[GeneratedPatternStep],
    *,
    start_step_index: int,
    end_step_index: int,
) -> bool:
    if not steps:
        return False
    start = max(1, int(start_step_index))
    end = min(len(steps), int(end_step_index))
    if end < start:
        return False
    return any(_step_in_fill_reserved_zone(steps[index - 1]) for index in range(start, end + 1))


def _fill_allowed_type_names(
    *,
    fill_strength: float,
) -> tuple[str, ...]:
    strength = float(np.clip(fill_strength, 0.0, 1.0))
    if strength <= 0.35:
        return tuple(sorted(_FILL_LIGHT_TYPES))
    if strength <= 0.75:
        return tuple(sorted(_FILL_NON_DENSE_TYPES))
    return tuple(sorted(_FILL_TYPE_NAMES))


def _fill_allowed_zone_start_range(fill_strength: float) -> tuple[int, int]:
    strength = float(np.clip(fill_strength, 0.0, 1.0))
    if strength <= 0.35:
        return 15, 15
    if strength <= 0.75:
        return 13, 15
    return 11, 15


def _pick_fill_zone_start(
    fill_type: str,
    *,
    fill_strength: float,
    bar_index: int,
    bars_total: int,
    rng: np.random.Generator,
) -> int:
    min_start, max_start = _fill_allowed_zone_start_range(fill_strength)
    preferred_start = int(FILL_TYPES.get(fill_type, {}).get("typical_zone", (15, 16))[0])
    weighted_candidates: list[tuple[int, float]] = []
    for zone_start in range(int(min_start), int(max_start) + 1):
        distance = abs(int(zone_start) - preferred_start)
        weight = 1.0 / (1.0 + float(distance))
        if bars_total > 1 and int(bar_index) == int(bars_total) - 1 and zone_start < preferred_start:
            weight *= _lerp(1.0, 1.45, float(np.clip(fill_strength, 0.0, 1.0)))
        if fill_type == "dense" and zone_start <= 12:
            weight *= 1.35
        weighted_candidates.append((int(zone_start), float(weight)))
    return _pick_weighted_label(weighted_candidates, rng, fallback=int(np.clip(preferred_start, min_start, max_start)))


def _pick_weighted_label(
    weighted_candidates: list[tuple[int, float]] | list[tuple[str, float]],
    rng: np.random.Generator,
    *,
    fallback,
):
    if not weighted_candidates:
        return fallback
    labels = [label for label, _ in weighted_candidates]
    weights = np.asarray([max(1e-6, float(weight)) for _, weight in weighted_candidates], dtype=np.float64)
    weights /= float(np.sum(weights))
    choice = int(rng.choice(len(labels), p=weights))
    return labels[choice]


def _decide_fill(
    params: _ResolvedPatternParams,
    bar_index: int,
    bars_total: int,
    rng: np.random.Generator,
) -> FillDecision:
    strength = float(np.clip(params.fill_strength, 0.0, 1.0))
    if strength <= 1e-6:
        return FillDecision(False, "none", 16, 16, "generated")

    fill_probability = _lerp(0.06, 0.94, strength)
    if int(bars_total) > 1 and int(bar_index) == int(bars_total) - 1:
        fill_probability = min(0.98, fill_probability + _lerp(0.04, 0.18, strength))
    if float(rng.random()) > fill_probability:
        return FillDecision(False, "none", 16, 16, "generated")

    allowed_types = _fill_allowed_type_names(fill_strength=strength)
    configured_weights = dict(params.fill_type_weights)
    candidate_types: tuple[str, ...]
    if configured_weights:
        explicit_types = tuple(fill_type for fill_type in configured_weights if fill_type in _FILL_TYPE_NAMES)
        if len(explicit_types) == 1:
            candidate_types = explicit_types
        else:
            candidate_types = tuple(fill_type for fill_type in allowed_types if fill_type in configured_weights) or allowed_types
    else:
        candidate_types = allowed_types

    weighted_fill_types: list[tuple[str, float]] = []
    for fill_type in candidate_types:
        weight = float(configured_weights.get(fill_type, 1.0))
        density = str(FILL_TYPES.get(fill_type, {}).get("density", "medium"))
        if density == "light":
            weight *= _lerp(1.2, 0.85, strength)
        elif density == "heavy":
            weight *= _lerp(0.45, 1.35, strength)
        elif density == "none":
            weight *= _lerp(0.35, 0.95, strength)
        if int(bars_total) > 1 and int(bar_index) == int(bars_total) - 1 and fill_type == "dense":
            weight *= _lerp(1.0, 1.7, strength)
        weighted_fill_types.append((fill_type, max(1e-6, weight)))

    fill_type = _pick_weighted_label(weighted_fill_types, rng, fallback="ghost_hat")
    zone_start = _pick_fill_zone_start(
        str(fill_type),
        fill_strength=strength,
        bar_index=int(bar_index),
        bars_total=max(1, int(bars_total)),
        rng=rng,
    )
    return FillDecision(
        active=True,
        fill_type=str(fill_type),
        zone_start=int(zone_start),
        zone_end=16,
        source="generated",
    )


def _decide_fill_map(
    params: _ResolvedPatternParams,
    *,
    bars: int,
    rng: np.random.Generator,
) -> tuple[FillDecision, ...]:
    decisions = [
        _decide_fill(params, bar_index=index, bars_total=max(1, int(bars)), rng=rng)
        for index in range(max(1, int(bars)))
    ]
    return tuple(decisions)


def _fill_sequence_conflicts_with_reservation(
    sequence: HitSequence,
    *,
    step_index: int,
    fill_decisions: Iterable[FillDecision] | None,
) -> bool:
    decision = _fill_decision_for_step(fill_decisions, step_index)
    end_step_index = int(step_index) + int(sequence.total_steps) - 1
    if decision is None:
        next_decision = _fill_decision_for_step(fill_decisions, end_step_index)
        return next_decision is not None

    zone_start_index = int(step_index) - ((((int(step_index) - 1) % 16) + 1) - int(decision.zone_start))
    zone_end_index = zone_start_index + _fill_decision_zone_length(decision) - 1
    if int(step_index) < zone_start_index and end_step_index >= zone_start_index:
        return True
    if int(step_index) > zone_end_index:
        return False
    if sequence.role != "fill":
        return True
    if int(step_index) != zone_start_index:
        return True
    return end_step_index > zone_end_index


def _pick_fill_sequence_for_decision(
    step_index: int,
    steps: list[GeneratedPatternStep],
    sequence_pools: _SequencePools,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    decision: FillDecision,
    anchors: Mapping[int, str] | None = None,
) -> HitSequence | None:
    if not bool(decision.active) or not sequence_pools.fill:
        return None
    zone_length = _fill_decision_zone_length(decision)
    if zone_length <= 0:
        return None
    weighted_sequences: list[tuple[HitSequence, float]] = []
    target_position = _rhythmic_position_for_step_index(step_index)
    for sequence in sequence_pools.fill:
        if int(sequence.total_steps) > int(zone_length):
            continue
        if _sequence_conflicts_with_pillars(
            sequence,
            step_index=step_index,
            steps=steps,
            pools=pools,
            anchors=anchors,
        ):
            continue
        first_position = sequence.events[0].rhythmic_position if sequence.events else None
        weight = 1.0 + (0.12 * float(sequence.hit_count))
        weight *= _rhythmic_position_bias(first_position, target_position, params.position_fidelity)
        if int(sequence.total_steps) == int(zone_length):
            weight *= 1.1
        weighted_sequences.append((sequence, float(max(0.01, weight))))
    return _pick_weighted_sequence(weighted_sequences, rng)


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
    fill_decisions: Iterable[FillDecision] | None = None,
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
        if _fill_decision_for_step(fill_decisions, target_step_index) is not None:
            return None
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
    fill_decisions: Iterable[FillDecision] | None = None,
    log: DebugLog | None = None,
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
                    fill_decisions=fill_decisions,
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
                    if log is not None:
                        log.write_step_index(
                            int(step_index),
                            "motif_block",
                            str(anchor),
                            f"{chosen.motif.name}, role {chosen.motif.role}",
                        )
                        log.bump_pass_stat("motif_block", "writes")
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
    if local_step in _PRIMARY_STRONG_STEPS:
        weights = {
            "kick": 1.48 * params.kick_weight,
            "snare": 0.32 * params.snare_weight,
            "hat": 0.14 * params.hat_density,
            "ghost": 0.08 * params.ghost_density,
            "silence": 0.06 + (0.22 * params.breath_factor),
            "other": 0.05,
        }
    elif local_step in _SECONDARY_STRONG_STEPS:
        weights = {
            "kick": 0.94 * params.kick_weight,
            "snare": 0.32 * params.snare_weight,
            "hat": 0.34 * params.hat_density,
            "ghost": 0.16 * params.ghost_density,
            "silence": 0.11 + (0.32 * params.breath_factor),
            "other": 0.13,
        }
    elif local_step in _PRIMARY_BACKBEAT_STEPS:
        weights = {
            "snare": 1.32 * params.snare_weight,
            "kick": 0.22 * params.kick_weight,
            "hat": 0.16 * params.hat_density,
            "ghost": 0.14 * params.ghost_density,
            "silence": 0.08 + (0.22 * params.breath_factor),
            "other": 0.10,
        }
    elif local_step in _SECONDARY_BACKBEAT_STEPS:
        weights = {
            "snare": 0.88 * params.snare_weight,
            "kick": 0.34 * params.kick_weight,
            "hat": 0.28 * params.hat_density,
            "ghost": 0.20 * params.ghost_density,
            "silence": 0.12 + (0.28 * params.breath_factor),
            "other": 0.16,
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

    if local_step in _PRIMARY_BACKBEAT_STEPS and not any(step.label in {"snare", "clap"} for step in steps[-4:]):
        weights["snare"] = weights.get("snare", 0.0) * (1.45 + (0.55 * params.snare_weight))
    elif local_step in _SECONDARY_BACKBEAT_STEPS and not any(step.label in {"snare", "clap"} for step in steps[-5:]):
        weights["snare"] = weights.get("snare", 0.0) * (1.08 + (0.22 * params.snare_weight))

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

    if availability["kick"] and local_step in _PRIMARY_STRONG_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.1 + (0.12 * params.breath_factor))
    elif availability["kick"] and local_step in _SECONDARY_STRONG_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.16 + (0.18 * params.breath_factor))
    elif availability["snare"] and local_step in _PRIMARY_BACKBEAT_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.11 + (0.14 * params.breath_factor))
    elif availability["snare"] and local_step in _SECONDARY_BACKBEAT_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.16 + (0.18 * params.breath_factor))
    elif availability["hat"] and local_step in _OFFBEAT_STEPS:
        weights["silence"] = min(weights.get("silence", 0.0), 0.13 + (0.18 * params.breath_factor))

    strongest_non_silence = max(
        (float(weight) for family, weight in weights.items() if family != "silence"),
        default=0.0,
    )
    if strongest_non_silence > 1e-6 and params.breath_factor <= 0.15:
        low_breath_ratio = float(np.clip(params.breath_factor / 0.15, 0.0, 1.0))
        silence_cap_factor = _lerp(0.18, 0.42, low_breath_ratio)
        if local_step in _PRIMARY_STRONG_STEPS or local_step in _PRIMARY_BACKBEAT_STEPS:
            silence_cap_factor *= 0.82
        elif local_step in _SECONDARY_STRONG_STEPS or local_step in _SECONDARY_BACKBEAT_STEPS:
            silence_cap_factor *= 0.9
        weights["silence"] = min(weights.get("silence", 0.0), strongest_non_silence * silence_cap_factor)
    return weights


def _estimate_effect_row_probability(
    *,
    row_name: str,
    family_preview: PlacementProbabilityPreview,
    params: _ResolvedPatternParams,
) -> dict[str, float]:
    step_indices = _preview_step_indices_for_row(row_name)
    if not step_indices:
        return {"repeat": 0.0, "reverse": 0.0, "kick_roll": 0.0, "snare_stretch": 0.0, "pitch": 0.0}

    repeat_scores: list[float] = []
    reverse_scores: list[float] = []
    kick_roll_scores: list[float] = []
    snare_stretch_scores: list[float] = []
    pitch_scores: list[float] = []
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

        pitch_score = 0.0
        if params.pitch_mode != "off" and params.pitch_amount > 1e-6:
            for family, probability in row_weights.items():
                if probability <= 1e-6:
                    continue
                preview_step = _preview_step_from_family(step_index, family)
                if not _step_is_pitch_target(preview_step, params.pitch_scope):
                    continue
                weight = 1.0
                if params.pitch_mode == "curve":
                    if row_name in {"backbeat", "offbeat"}:
                        weight *= 1.12
                    elif row_name == "subdivision":
                        weight *= 0.92
                elif params.pitch_mode == "sequence":
                    weight *= 0.96
                pitch_score += float(probability) * weight
            pitch_scores.append(float(np.clip(pitch_score * params.pitch_amount, 0.0, 1.0)))
        else:
            pitch_scores.append(0.0)

    return {
        "repeat": float(np.mean(repeat_scores)) if repeat_scores else 0.0,
        "reverse": float(np.mean(reverse_scores)) if reverse_scores else 0.0,
        "kick_roll": float(np.mean(kick_roll_scores)) if kick_roll_scores else 0.0,
        "snare_stretch": float(np.mean(snare_stretch_scores)) if snare_stretch_scores else 0.0,
        "pitch": float(np.mean(pitch_scores)) if pitch_scores else 0.0,
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
    fill_decisions: Iterable[FillDecision] | None = None,
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
        if _fill_sequence_conflicts_with_reservation(
            sequence,
            step_index=step_index,
            fill_decisions=fill_decisions,
        ):
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
        hint_weight = _sequence_hint_alignment_bias(sequence, step_index=step_index, params=params)
        weighted_sequences.append(
            (
                sequence,
                max(0.01, zone_match * density_weight * role_weight * position_weight * hint_weight),
            )
        )

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


def _sequence_hint_alignment_bias(
    sequence: HitSequence,
    *,
    step_index: int,
    params: _ResolvedPatternParams,
) -> float:
    sequence_density = float(np.clip(params.sequence_density, 0.0, 1.0))
    if sequence_density <= 1e-6:
        return 1.0

    local_start = ((int(step_index) - 1) % 16) + 1
    local_end = int(local_start + int(sequence.total_steps) - 1)
    start_hint = int(np.clip(int(sequence.start_step_hint), 1, 16))
    end_hint = int(np.clip(int(sequence.end_step_hint), start_hint, 16))
    start_distance = abs(int(local_start) - start_hint)
    end_distance = abs(int(local_end) - end_hint)

    def _distance_bias(distance: int, *, exact_boost: float, near_boost: float, medium_penalty: float, far_penalty: float) -> float:
        if distance <= 0:
            return _lerp(1.0, exact_boost, sequence_density)
        if distance == 1:
            return _lerp(1.0, near_boost, sequence_density)
        if distance == 2:
            return _lerp(1.0, medium_penalty, sequence_density)
        return _lerp(1.0, far_penalty, sequence_density)

    start_bias = _distance_bias(
        start_distance,
        exact_boost=4.0,
        near_boost=1.35,
        medium_penalty=0.42,
        far_penalty=0.08,
    )
    end_bias = _distance_bias(
        end_distance,
        exact_boost=2.2,
        near_boost=1.12,
        medium_penalty=0.64,
        far_penalty=0.2,
    )

    if sequence.role == "anticipation":
        end_bias *= _lerp(1.0, 1.2, sequence_density)
    elif sequence.role == "cadence":
        start_bias *= _lerp(1.0, 1.1, sequence_density)
    elif sequence.role == "fill":
        end_bias *= _lerp(1.0, 1.08, sequence_density)

    return float(max(0.01, start_bias * end_bias))


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


def _reinforce_skeleton_structure(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    log: DebugLog | None = None,
) -> None:
    if not steps:
        return
    step_count = len(steps)
    for bar_start in range(1, step_count + 1, 16):
        _reinforce_bar_pillars(
            steps,
            bar_start=bar_start,
            pools=pools,
            params=params,
            rng=rng,
            log=log,
        )


def _reinforce_bar_pillars(
    steps: list[GeneratedPatternStep],
    *,
    bar_start: int,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    log: DebugLog | None = None,
) -> None:
    bar_targets: tuple[tuple[int, str, bool, float], ...] = (
        (int(bar_start), "kick", float(params.kick_weight) > 1e-3, 1.0),
        (int(bar_start) + 4, "snare", float(params.snare_weight) > 1e-3, 1.0),
        (
            int(bar_start) + 8,
            "kick",
            float(params.kick_weight) >= 0.45,
            _secondary_pillar_support_probability("kick", params),
        ),
        (
            int(bar_start) + 12,
            "snare",
            float(params.snare_weight) >= 0.45,
            _secondary_pillar_support_probability("snare", params),
        ),
    )
    for step_index, family, enabled, probability in bar_targets:
        if not enabled or step_index < 1 or step_index > len(steps):
            continue
        if probability < 0.999 and float(rng.random()) > probability:
            continue
        _reinforce_structural_step(
            steps,
            step_index=step_index,
            family=family,
            pools=pools,
            params=params,
            rng=rng,
            log=log,
        )


def _step_matches_structural_family(step: GeneratedPatternStep, family: str) -> bool:
    if family == "kick":
        return step.label == "kick"
    if family == "snare":
        return step.label in {"snare", "clap", "snare_ruff"}
    return False


def _reinforce_structural_step(
    steps: list[GeneratedPatternStep],
    *,
    step_index: int,
    family: str,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    log: DebugLog | None = None,
) -> None:
    current = steps[step_index - 1]
    if _step_in_fill_reserved_zone(current):
        return
    if _step_is_structurally_protected(current):
        return
    if _step_matches_structural_family(current, family):
        return

    previous = steps[step_index - 2] if step_index > 1 else None
    previous_source_index = previous.source_hit_index if previous is not None else None
    previous_source_label = previous.source_label if previous is not None else None

    replacement_hit: TransientHit | None = None
    if family == "kick" and pools.kick:
        replacement_hit = _pick_hit(
            pools.kick,
            rng,
            previous_source_index,
            previous_source_label,
            params,
            target_step_index=step_index,
        )
    elif family == "snare" and pools.snareish:
        replacement_hit = _pick_snareish_hit(
            step_index,
            pools,
            rng,
            previous_source_index,
            previous_source_label,
            params,
        )

    if replacement_hit is None:
        return

    replacement = _override_step_from_hit(step_index, replacement_hit, ("structural_pillar",))
    steps[step_index - 1] = replacement
    _debug_log_step_write(
        log,
        pass_name="skeleton",
        step=replacement,
        note=f"reinforce {family} pillar",
    )


def _secondary_pillar_support_probability(family: str, params: _ResolvedPatternParams) -> float:
    structural_weight = float(params.kick_weight if family == "kick" else params.snare_weight)
    probability = _lerp(0.22, 0.68, structural_weight)
    probability *= _lerp(1.0, 0.82, params.anti_repeat)
    probability *= _lerp(1.0, 0.86, params.breath_factor)
    if family == "snare":
        probability *= _lerp(1.0, 0.82, params.fill_strength)
        probability += 0.04
    return float(np.clip(probability, 0.16, 0.8))


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
    if anchor == "ghost":
        return _select_ghost_step(step_index, steps, pools, params, rng, tags=tuple(tags))

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
        return _select_ghost_step(step_index, steps, pools, params, rng, tags=tuple((*tags, "ghost")))

    hit = _pick_other_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)
    if hit is None:
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple(tags))
    return _event_from_hit(step_index, hit, tags)


def _select_step_event_with_fallback(
    step_index: int,
    family_weights: Mapping[str, float],
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> tuple[GeneratedPatternStep, str]:
    requested_family = _weighted_choice(dict(family_weights), rng)
    low_breath_no_silence_preference = requested_family == "silence" and float(params.breath_factor) <= 0.15

    candidate_families: list[str] = [requested_family]
    if requested_family != "silence" or low_breath_no_silence_preference:
        ranked_fallbacks = sorted(
            (
                (str(family), float(weight))
                for family, weight in family_weights.items()
                if family not in {requested_family, "silence"} and float(weight) > 1e-6
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        candidate_families.extend(family for family, _weight in ranked_fallbacks)
    if "silence" not in candidate_families:
        candidate_families.append("silence")

    selected_silence: GeneratedPatternStep | None = None
    for attempt_index, candidate_family in enumerate(candidate_families):
        candidate_step = _select_step_event(step_index, candidate_family, steps, pools, params, rng)
        if candidate_step.label == "silence":
            selected_silence = candidate_step
            continue
        if attempt_index > 0:
            candidate_step = replace(
                candidate_step,
                tags=tuple(
                    dict.fromkeys(
                        (
                            *candidate_step.tags,
                            f"fallback_from_{requested_family}",
                            f"fallback_to_{candidate_family}",
                        )
                    )
                ),
            )
        return candidate_step, candidate_family

    return (selected_silence or _select_step_event(step_index, "silence", steps, pools, params, rng)), requested_family


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


def _pick_real_ghost_hit(
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
    return _pick_weighted_hit(
        weighted_hits,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )


def _pick_synthetic_ghost_source(
    step_index: int,
    pools: _PatternPools,
    rng: np.random.Generator,
    previous_source_index: int | None,
    previous_source_label: str | None,
    params: _ResolvedPatternParams,
) -> TransientHit | None:
    return _pick_snareish_hit(step_index, pools, rng, previous_source_index, previous_source_label, params)


def _existing_real_ghost_count(steps: Iterable[GeneratedPatternStep]) -> int:
    return sum(
        1
        for step in steps
        if (not bool(getattr(step, "is_synthetic_ghost", False)))
        and str(getattr(step, "label", "")) in {"snare_ghost", "kick_ghost"}
        and str(getattr(step, "source_label", "")) in {"snare_ghost", "kick_ghost"}
    )


def _synthetic_ghost_render_values(
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    vel_min, vel_max = params.ghost_vel_range
    vel_ratio = float(rng.uniform(vel_min, vel_max)) if vel_max > vel_min else float(vel_min)
    pitch_min, pitch_max = params.ghost_pitch_range
    pitch_offset = float(rng.uniform(pitch_min, pitch_max)) if pitch_max > pitch_min else float(pitch_min)
    gate_ratio = float(np.clip(params.ghost_gate_ratio, 0.0, 1.0))
    return vel_ratio, pitch_offset, gate_ratio


def _build_ghost_step_from_hit(
    step_index: int,
    hit: TransientHit | None,
    *,
    tags: tuple[str, ...],
    synthetic: bool,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> GeneratedPatternStep:
    if hit is None:
        return GeneratedPatternStep(step_index, "silence", 0, None, None, None, None, tuple(tags))

    if synthetic:
        ghost_vel_ratio, ghost_pitch_offset, ghost_gate_ratio = _synthetic_ghost_render_values(params, rng)
        return GeneratedPatternStep(
            step_index=step_index,
            label="snare_ghost",
            velocity=0,
            source_hit_index=hit.index,
            source_label=hit.label,
            source_start_s=hit.start_s,
            source_end_s=hit.end_s,
            tags=tuple(dict.fromkeys((*tags, "synthetic_ghost"))),
            is_synthetic_ghost=True,
            ghost_vel_ratio=ghost_vel_ratio,
            ghost_pitch_offset=ghost_pitch_offset,
            ghost_gate_ratio=ghost_gate_ratio,
        )

    ghost_label = "snare_ghost"
    if hit.label in {"snare_ghost", "kick_ghost"}:
        ghost_label = hit.label
    elif hit.label == "kick":
        ghost_label = "kick_ghost"
    return GeneratedPatternStep(
        step_index=step_index,
        label=ghost_label,
        velocity=0,
        source_hit_index=hit.index,
        source_label=hit.label,
        source_start_s=hit.start_s,
        source_end_s=hit.end_s,
        tags=tuple(tags),
    )


def _select_ghost_step(
    step_index: int,
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    tags: tuple[str, ...],
) -> GeneratedPatternStep:
    previous = steps[-1] if steps else None
    previous_source_index = previous.source_hit_index if previous is not None else None
    previous_source_label = previous.source_label if previous is not None else None
    real_ghost_capacity = len(pools.snare_ghost) + len(pools.kick_ghost)
    real_ghost_count = _existing_real_ghost_count(steps)
    real_hit = _pick_real_ghost_hit(
        step_index,
        pools,
        rng,
        previous_source_index,
        previous_source_label,
        params,
    )
    use_real = (
        real_hit is not None
        and (
            not params.synth_ghost_enabled
            or real_ghost_capacity <= 0
            or real_ghost_count < real_ghost_capacity
        )
    )
    if use_real:
        return _build_ghost_step_from_hit(
            step_index,
            real_hit,
            tags=tags,
            synthetic=False,
            params=params,
            rng=rng,
        )

    if params.synth_ghost_enabled:
        synthetic_source = _pick_synthetic_ghost_source(
            step_index,
            pools,
            rng,
            previous_source_index,
            previous_source_label,
            params,
        )
        if synthetic_source is not None:
            return _build_ghost_step_from_hit(
                step_index,
                synthetic_source,
                tags=tags,
                synthetic=True,
                params=params,
                rng=rng,
            )

    fallback_source = _pick_synthetic_ghost_source(
        step_index,
        pools,
        rng,
        previous_source_index,
        previous_source_label,
        params,
    )
    if fallback_source is not None:
        return _build_ghost_step_from_hit(
            step_index,
            fallback_source,
            tags=tags,
            synthetic=False,
            params=params,
            rng=rng,
        )

    fallback_kick = _pick_hit(
        pools.kick,
        rng,
        previous_source_index,
        previous_source_label,
        params,
        target_step_index=step_index,
    )
    return _build_ghost_step_from_hit(
        step_index,
        fallback_kick,
        tags=tags,
        synthetic=False,
        params=params,
        rng=rng,
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


def _debug_log_step_write(
    log: DebugLog | None,
    *,
    pass_name: str,
    step: GeneratedPatternStep,
    note: str = "",
) -> None:
    if log is None:
        return
    log.write_step_index(int(step.step_index), pass_name, step.label, note)
    log.bump_pass_stat(pass_name, "writes")


def _debug_log_pass_stat(
    log: DebugLog | None,
    *,
    pass_name: str,
    stat: str,
    amount: int = 1,
) -> None:
    if log is None:
        return
    log.bump_pass_stat(pass_name, stat, amount)


def _debug_note_for_sequence_step(
    sequence: HitSequence,
    step: GeneratedPatternStep,
    *,
    offset: int,
) -> str:
    if step.label == "silence":
        return f"seq gap, {sequence.role}#{int(sequence.index)}, off {int(offset)}"
    return f"{sequence.role}#{int(sequence.index)}, off {int(offset)}"


def _debug_note_for_skeleton_step(
    step: GeneratedPatternStep,
    *,
    family: str,
    anchor: str | None = None,
) -> str:
    if anchor is not None:
        return f"anchor {anchor}"
    if step.label == "silence":
        return f"family {family}"
    if step.label != family:
        return f"family {family}"
    return f"{family} pool"


def _debug_note_for_ghost_step(step: GeneratedPatternStep) -> str:
    if step.is_synthetic_ghost:
        note = f"synth fallback, vel_ratio {_fmt_param(step.ghost_vel_ratio)}"
        if abs(float(step.ghost_pitch_offset)) > 1e-6:
            note += f", pitch {_fmt_signed(step.ghost_pitch_offset)}"
        if float(step.ghost_gate_ratio) > 1e-6:
            note += f", gate {_fmt_param(step.ghost_gate_ratio)}"
        return note
    if step.source_label:
        return f"from {step.source_label}"
    return "ghost pool"


def _debug_note_for_fill_step(step: GeneratedPatternStep) -> str:
    tags = set(step.tags)
    if "backbeat_fill" in tags:
        return "backbeat"
    if "lift" in tags:
        return "lift"
    if "drive" in tags:
        return "drive"
    if "release" in tags:
        return "release"
    return "fill block"


def _debug_note_for_resolution_step(step: GeneratedPatternStep) -> str:
    if step.label == "kick":
        return "downbeat kick"
    return "downbeat"


def _debug_note_for_repeat_step(step: GeneratedPatternStep) -> str:
    repeat_count = next(
        (
            int(str(tag).split("_")[-1])
            for tag in step.tags
            if str(tag).startswith("repeat_count_")
        ),
        2,
    )
    zone_span = next(
        (
            int(str(tag).split("_")[-1])
            for tag in step.tags
            if str(tag).startswith("repeat_zone_span_")
        ),
        1,
    )
    return f"x{repeat_count}, span {zone_span}"


def _debug_note_for_kick_roll_step(step: GeneratedPatternStep) -> str:
    zone_span = next(
        (
            int(str(tag).split("_")[-1])
            for tag in step.tags
            if str(tag).startswith("kick_roll_zone_span_")
        ),
        2,
    )
    return f"span {zone_span}"


def _debug_note_for_snare_stretch_step(step: GeneratedPatternStep) -> str:
    zone_span = next(
        (
            int(str(tag).split("_")[-1])
            for tag in step.tags
            if str(tag).startswith("snare_stretch_zone_span_")
        ),
        2,
    )
    amount = next(
        (
            int(str(tag).split("_")[-1])
            for tag in step.tags
            if str(tag).startswith("snare_stretch_amount_")
        ),
        0,
    )
    curve = next(
        (
            str(tag).removeprefix("snare_stretch_curve_")
            for tag in step.tags
            if str(tag).startswith("snare_stretch_curve_")
        ),
        "decay",
    )
    retrigger_count = len(tuple(getattr(step, "stretch_retriggers", ()) or ()))
    label = "tail" if "snare_stretch_tail" in step.tags else "start"
    return f"{label}, span {zone_span}, amount {amount}%, curve {curve}, retriggers {retrigger_count}"


def _debug_note_for_reverse_step(step: GeneratedPatternStep) -> str:
    for tag in step.tags:
        text = str(tag)
        if text.startswith("reverse_from_"):
            return text.replace("reverse_from_", "from ")
    return "reverse transition"


def _debug_note_for_anchor_reapply(anchor: str) -> str:
    return f"manual anchor {anchor}"


def _debug_note_for_pitch_step(step: GeneratedPatternStep) -> str:
    return _fmt_signed(step.pitch_shift)


def _debug_note_for_velocity_step(step: GeneratedPatternStep) -> str:
    if step.label == "silence":
        return "silence"
    return f"vel {int(step.velocity)}"


def _inject_ghost_notes(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    log: DebugLog | None = None,
) -> None:
    if params.ghost_density <= 0.0:
        _debug_log_pass_stat(log, pass_name="ghost_pass", stat="skipped_constraints")
        return
    if not (pools.snareish or pools.snare_ghost or pools.kick_ghost or pools.kick):
        _debug_log_pass_stat(log, pass_name="ghost_pass", stat="no_pool")
        return

    snare_steps = [
        step.step_index
        for step in steps
        if step.label in {"snare", "clap", "snare_ruff"}
    ]
    if not snare_steps:
        _debug_log_pass_stat(log, pass_name="ghost_pass", stat="no_trigger")
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
        _debug_log_pass_stat(log, pass_name="ghost_pass", stat="candidates")
        current = steps[candidate - 1]
        if _step_in_fill_reserved_zone(current):
            _debug_log_pass_stat(log, pass_name="ghost_pass", stat="skipped_protected")
            continue
        if "sequence" in current.tags:
            _debug_log_pass_stat(log, pass_name="ghost_pass", stat="skipped_protected")
            continue
        if current.label not in {"silence", "closed_hat", "open_hat", "perc", "ride"}:
            _debug_log_pass_stat(log, pass_name="ghost_pass", stat="skipped_incompatible")
            continue
        if float(rng.random()) > (0.25 + (0.55 * params.ghost_density)):
            _debug_log_pass_stat(log, pass_name="ghost_pass", stat="skipped_probability")
            continue
        replacement = _select_ghost_step(
            candidate,
            steps[: candidate - 1],
            pools,
            params,
            rng,
            tags=tuple((_step_tag(candidate), "owner_skeleton", "ghost")),
        )
        _debug_log_pass_stat(log, pass_name="ghost_pass", stat="applied")
        _debug_log_step_write(log, pass_name="ghost_pass", step=replacement, note=_debug_note_for_ghost_step(replacement))
        steps[candidate - 1] = replacement


def _apply_fill_blocks(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    fill_decisions: Iterable[FillDecision] | None = None,
    log: DebugLog | None = None,
) -> None:
    if not steps:
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        decision = _fill_decision_for_bar(fill_decisions, bar_index)
        _apply_bar_end_fill(steps, bar_start, pools, params, rng, fill_decision=decision, log=log)


def _apply_bar_end_fill(
    steps: list[GeneratedPatternStep],
    bar_start: int,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    fill_decision: FillDecision | None,
    log: DebugLog | None = None,
) -> None:
    _debug_log_pass_stat(log, pass_name="fill_pass", stat="candidates")
    if fill_decision is None or not bool(fill_decision.active):
        _debug_log_pass_stat(log, pass_name="fill_pass", stat="skipped_probability")
        return

    zone_start = int(bar_start) + int(fill_decision.zone_start) - 1
    zone_end = min(len(steps), int(bar_start) + int(fill_decision.zone_end) - 1)
    if zone_start < 1 or zone_start > len(steps) or zone_end < zone_start:
        _debug_log_pass_stat(log, pass_name="fill_pass", stat="skipped_constraints")
        return

    zone_steps = [steps[index - 1] for index in range(zone_start, zone_end + 1)]
    if any(
        _step_is_structurally_protected(step)
        and "anchor" not in set(step.tags)
        and not (fill_decision.source == "sequence" and "sequence" in set(step.tags))
        for step in zone_steps
    ):
        _debug_log_pass_stat(log, pass_name="fill_pass", stat="skipped_protected")
        return

    if not _bar_has_post_mutation_capacity(
        steps,
        bar_start=bar_start,
        bar_end=min(len(steps), bar_start + 15),
        target_step_indices=range(zone_start, zone_end + 1),
        params=params,
        planned_post_cost=1,
        planned_tail_cost=1 if zone_end >= (bar_start + 12) else 0,
    ):
        _debug_log_pass_stat(log, pass_name="fill_pass", stat="skipped_budget")
        return

    replacements = _build_fill_zone_replacements(
        steps,
        zone_start=zone_start,
        zone_end=zone_end,
        decision=fill_decision,
        pools=pools,
        params=params,
        rng=rng,
    )
    if not replacements:
        _debug_log_pass_stat(log, pass_name="fill_pass", stat="no_candidate")
        return

    _debug_log_pass_stat(log, pass_name="fill_pass", stat="applied")
    _debug_log_pass_stat(log, pass_name="fill_pass", stat="writes", amount=len(replacements))
    for step_index in sorted(replacements.keys()):
        replacement = replacements[step_index]
        _debug_log_step_write(log, pass_name="fill_pass", step=replacement, note=_debug_note_for_fill_step(replacement))
        steps[step_index - 1] = replacement


def _build_fill_zone_replacements(
    steps: list[GeneratedPatternStep],
    *,
    zone_start: int,
    zone_end: int,
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> dict[int, GeneratedPatternStep]:
    zone_indices = list(range(int(zone_start), int(zone_end) + 1))
    current_zone_steps = {index: steps[index - 1] for index in zone_indices}
    replacements = {
        index: _decorate_existing_fill_zone_step(current_zone_steps[index], decision)
        for index in zone_indices
    }
    replaceable = {
        index: _fill_zone_step_is_replaceable(current_zone_steps[index], decision)
        for index in zone_indices
    }

    fill_type = str(decision.fill_type)
    if fill_type == "ghost_hat":
        _apply_fill_type_ghost_hat(replacements, replaceable, steps, zone_indices, decision, pools, params, rng)
    elif fill_type == "ruff":
        _apply_fill_type_ruff(replacements, replaceable, zone_indices, decision, pools, params, rng)
    elif fill_type == "crash_open":
        _apply_fill_type_crash_open(replacements, replaceable, zone_indices, decision, pools, params, rng)
    elif fill_type == "double_kick":
        _apply_fill_type_double_kick(replacements, replaceable, zone_indices, decision, pools, params, rng)
    elif fill_type == "dense":
        _apply_fill_type_dense(replacements, replaceable, steps, zone_indices, decision, pools, params, rng)
    elif fill_type == "perc_burst":
        _apply_fill_type_perc_burst(replacements, replaceable, zone_indices, decision, pools, params, rng)
    elif fill_type == "kick_snare_alternance":
        _apply_fill_type_kick_snare_alternance(replacements, replaceable, zone_indices, decision, pools, params, rng)
    elif fill_type == "silence_drop":
        _apply_fill_type_silence_drop(replacements, replaceable, zone_indices, decision)
    return replacements


def _fill_zone_step_is_replaceable(step: GeneratedPatternStep, decision: FillDecision) -> bool:
    tags = set(step.tags)
    if "anchor" in tags:
        return False
    if decision.source == "sequence" and "sequence" in tags and "sequence_gap" not in tags:
        return False
    return True


def _decorate_existing_fill_zone_step(
    step: GeneratedPatternStep,
    decision: FillDecision,
    *,
    relative_velocity_ratio: float | None = None,
) -> GeneratedPatternStep:
    extra_tags = ("fill", f"fill_style_{decision.fill_type}", f"fill_source_{decision.source}", "owner_fill")
    updated = replace(
        step,
        tags=tuple(dict.fromkeys((*step.tags, *extra_tags))),
        relative_velocity_ratio=(
            step.relative_velocity_ratio
            if relative_velocity_ratio is None
            else float(np.clip(relative_velocity_ratio, 0.15, 1.25))
        ),
    )
    return _merge_fill_decision_tags(updated, decision)


def _build_fill_step(
    step_index: int,
    hit: TransientHit | None,
    decision: FillDecision,
    *extra_tags: str,
    relative_velocity_ratio: float | None = None,
) -> GeneratedPatternStep:
    step = _override_step_from_hit(
        int(step_index),
        hit,
        ("fill", f"fill_style_{decision.fill_type}", f"fill_source_{decision.source}", *extra_tags),
    )
    if relative_velocity_ratio is not None:
        step = replace(step, relative_velocity_ratio=float(np.clip(relative_velocity_ratio, 0.15, 1.25)))
    return _merge_fill_decision_tags(step, decision)


def _apply_fill_type_ghost_hat(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    steps: list[GeneratedPatternStep],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    count = max(1, len(zone_indices))
    for order, step_index in enumerate(zone_indices):
        if not bool(replaceable.get(step_index, False)):
            continue
        t = float(order / max(1, count - 1))
        if order % 2 == 0:
            hit = _pick_fill_texture_hit(step_index, pools, rng, params) or _pick_fill_other_hit(step_index, pools, rng, params)
            replacements[step_index] = _build_fill_step(
                step_index,
                hit,
                decision,
                "fill_lift",
                relative_velocity_ratio=_lerp(0.58, 0.92, t),
            )
        else:
            ghost_step = _select_ghost_step(
                step_index,
                steps[: step_index - 1],
                pools,
                params,
                rng,
                tags=("fill", f"fill_style_{decision.fill_type}", f"fill_source_{decision.source}", "fill_ghost"),
            )
            replacements[step_index] = _decorate_existing_fill_zone_step(
                ghost_step,
                decision,
                relative_velocity_ratio=_lerp(0.42, 0.82, t),
            )


def _apply_fill_type_ruff(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if not zone_indices:
        return
    hit_count = 3 if len(zone_indices) >= 3 and float(rng.random()) < 0.65 else 2
    target_indices = zone_indices[-hit_count:]
    for order, step_index in enumerate(target_indices):
        if not bool(replaceable.get(step_index, False)):
            continue
        hit = _pick_fill_snare_hit(step_index, pools, rng, params)
        if hit is not None and hit.label != "snare_ruff" and pools.snare_ruff:
            hit = _pick_weighted_hit([(candidate, 1.6) for candidate in pools.snare_ruff], rng, None, None, params, target_step_index=step_index)
        replacements[step_index] = _build_fill_step(
            step_index,
            hit,
            decision,
            "fill_ruff",
            relative_velocity_ratio=_lerp(0.96, 0.62, float(order / max(1, len(target_indices) - 1))),
        )


def _apply_fill_type_crash_open(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if len(zone_indices) < 2:
        return
    lead_step_index = zone_indices[-2]
    release_step_index = zone_indices[-1]
    if bool(replaceable.get(lead_step_index, False)):
        lead_hit = _pick_fill_backbeat_hit(lead_step_index, pools, rng, params)
        replacements[lead_step_index] = _build_fill_step(
            lead_step_index,
            lead_hit,
            decision,
            "fill_drive",
            relative_velocity_ratio=0.9,
        )
    if bool(replaceable.get(release_step_index, False)):
        release_hit = _pick_weighted_hit(
            [
                (hit, 1.5 if hit.label == "open_hat" else 1.2 if hit.label == "crash" else 0.0)
                for hit in pools.hatish
                if hit.label in {"open_hat", "crash"}
            ],
            rng,
            None,
            None,
            params,
            target_step_index=release_step_index,
        ) or _pick_fill_release_hit(release_step_index, pools, rng, params)
        replacements[release_step_index] = _build_fill_step(
            release_step_index,
            release_hit,
            decision,
            "fill_release",
            relative_velocity_ratio=1.0,
        )


def _apply_fill_type_double_kick(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    if not zone_indices:
        return
    target_indices = [index for index in zone_indices[-3:] if ((index - 1) % 2) == 1]
    if len(target_indices) < 2:
        target_indices = zone_indices[-2:]
    for order, step_index in enumerate(target_indices[:2]):
        if not bool(replaceable.get(step_index, False)):
            continue
        hit = _pick_fill_kick_hit(step_index, pools, rng, params)
        replacements[step_index] = _build_fill_step(
            step_index,
            hit,
            decision,
            "fill_double_kick",
            relative_velocity_ratio=_lerp(0.82, 0.96, float(order)),
        )


def _apply_fill_type_dense(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    steps: list[GeneratedPatternStep],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    pattern = ("snare", "ghost", "hat")
    count = max(1, len(zone_indices))
    for order, step_index in enumerate(zone_indices):
        if not bool(replaceable.get(step_index, False)):
            continue
        slot = pattern[order % len(pattern)]
        t = float(order / max(1, count - 1))
        if slot == "snare":
            hit = _pick_fill_snare_hit(step_index, pools, rng, params)
            if order == len(zone_indices) - 1 and pools.snare_ruff:
                hit = _pick_weighted_hit([(candidate, 1.6) for candidate in pools.snare_ruff], rng, None, None, params, target_step_index=step_index) or hit
            replacements[step_index] = _build_fill_step(
                step_index,
                hit,
                decision,
                "fill_dense",
                relative_velocity_ratio=_lerp(0.9, 1.0, t),
            )
        elif slot == "ghost":
            ghost_step = _select_ghost_step(
                step_index,
                steps[: step_index - 1],
                pools,
                params,
                rng,
                tags=("fill", f"fill_style_{decision.fill_type}", f"fill_source_{decision.source}", "fill_dense"),
            )
            replacements[step_index] = _decorate_existing_fill_zone_step(
                ghost_step,
                decision,
                relative_velocity_ratio=_lerp(0.38, 0.74, t),
            )
        else:
            hit = _pick_fill_texture_hit(step_index, pools, rng, params)
            replacements[step_index] = _build_fill_step(
                step_index,
                hit,
                decision,
                "fill_dense",
                relative_velocity_ratio=_lerp(0.62, 0.88, t),
            )


def _apply_fill_type_perc_burst(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    count = max(1, len(zone_indices))
    for order, step_index in enumerate(zone_indices):
        if not bool(replaceable.get(step_index, False)):
            continue
        hit = _pick_fill_other_hit(step_index, pools, rng, params) or _pick_fill_texture_hit(step_index, pools, rng, params)
        replacements[step_index] = _build_fill_step(
            step_index,
            hit,
            decision,
            "fill_burst",
            relative_velocity_ratio=_lerp(0.7, 0.96, float(order / max(1, count - 1))),
        )


def _apply_fill_type_kick_snare_alternance(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    zone_indices: list[int],
    decision: FillDecision,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> None:
    for order, step_index in enumerate(zone_indices):
        if not bool(replaceable.get(step_index, False)):
            continue
        if order % 2 == 0:
            hit = _pick_fill_kick_hit(step_index, pools, rng, params)
            replacements[step_index] = _build_fill_step(step_index, hit, decision, "fill_alt", relative_velocity_ratio=0.92)
        else:
            hit = _pick_fill_backbeat_hit(step_index, pools, rng, params)
            replacements[step_index] = _build_fill_step(step_index, hit, decision, "fill_alt", relative_velocity_ratio=0.88)


def _apply_fill_type_silence_drop(
    replacements: dict[int, GeneratedPatternStep],
    replaceable: Mapping[int, bool],
    zone_indices: list[int],
    decision: FillDecision,
) -> None:
    for step_index in zone_indices:
        if not bool(replaceable.get(step_index, False)):
            continue
        replacements[step_index] = _build_fill_step(step_index, None, decision, "fill_drop", relative_velocity_ratio=0.2)


def _apply_bar_start_resolutions(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    log: DebugLog | None = None,
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

        _debug_log_pass_stat(log, pass_name="resolution_pass", stat="candidates")

        current = steps[bar_start - 1]
        if _step_is_structurally_protected(current):
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="skipped_protected")
            continue
        if params.fill_strength < 0.8 and float(rng.random()) > (0.22 + (0.48 * params.fill_strength)):
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="skipped_probability")
            continue
        if params.fill_strength < 0.8 and not _bar_has_post_mutation_capacity(
            steps,
            bar_start=bar_start,
            bar_end=min(step_count, bar_start + 15),
            target_step_indices=(bar_start,),
            params=params,
        ):
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="skipped_budget")
            continue
        if current.label == "kick":
            replacement = replace(
                current,
                tags=tuple(dict.fromkeys((*current.tags, "resolution", "downbeat", "owner_fill"))),
            )
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="applied")
            _debug_log_step_write(log, pass_name="resolution_pass", step=replacement, note=_debug_note_for_resolution_step(replacement))
            steps[bar_start - 1] = replacement
            continue
        if current.label in {"open_hat", "crash"} and (not pools.kick or params.kick_weight <= 1e-3):
            replacement = replace(
                current,
                tags=tuple(dict.fromkeys((*current.tags, "resolution", "downbeat", "owner_fill"))),
            )
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="applied")
            _debug_log_step_write(log, pass_name="resolution_pass", step=replacement, note=_debug_note_for_resolution_step(replacement))
            steps[bar_start - 1] = replacement
            continue

        resolution_hit = _pick_bar_start_resolution_hit(bar_start, pools, rng, params)
        if resolution_hit is not None:
            replacement = _override_step_from_hit(bar_start, resolution_hit, ("resolution", "downbeat"))
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="applied")
            _debug_log_step_write(log, pass_name="resolution_pass", step=replacement, note=_debug_note_for_resolution_step(replacement))
            steps[bar_start - 1] = replacement
        else:
            _debug_log_pass_stat(log, pass_name="resolution_pass", stat="no_candidate")


def _apply_repeat_blocks(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
    log: DebugLog | None = None,
) -> None:
    if params.repeat_density <= 1e-3 or len(steps) < 4:
        _debug_log_pass_stat(log, pass_name="repeat_pass", stat="skipped_constraints")
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        bar_end = min(step_count, bar_start + 15)
        weighted_candidates: list[tuple[int, float, int]] = []
        for step_index in range(bar_start, bar_end + 1):
            current = steps[step_index - 1]
            if _step_in_fill_reserved_zone(current):
                continue
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
            _debug_log_pass_stat(log, pass_name="repeat_pass", stat="no_candidate")
            continue
        _debug_log_pass_stat(log, pass_name="repeat_pass", stat="candidates", amount=len(weighted_candidates))

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
            if _zone_intersects_fill_reserved(
                steps,
                start_step_index=chosen_step_index,
                end_step_index=chosen_step_index + zone_span - 1,
            ):
                _debug_log_pass_stat(log, pass_name="repeat_pass", stat="skipped_protected")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=bar_end,
                target_step_indices=range(chosen_step_index, chosen_step_index + zone_span),
                params=params,
            ):
                _debug_log_pass_stat(log, pass_name="repeat_pass", stat="skipped_budget")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue
            _debug_log_pass_stat(log, pass_name="repeat_pass", stat="applied")
            for zone_offset in range(zone_span):
                target_step_index = chosen_step_index + zone_offset
                current_step = steps[target_step_index - 1]
                replacement = _clone_step_for_repeat_glitch(
                    current_step,
                    repeat_count=repeat_count,
                    zone_span=zone_span,
                    zone_offset=zone_offset,
                )
                _debug_log_step_write(log, pass_name="repeat_pass", step=replacement, note=_debug_note_for_repeat_step(replacement))
                steps[target_step_index - 1] = replacement
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
        pitch_shift=source_step.pitch_shift,
        is_synthetic_ghost=source_step.is_synthetic_ghost,
        ghost_vel_ratio=source_step.ghost_vel_ratio,
        ghost_pitch_offset=source_step.ghost_pitch_offset,
        ghost_gate_ratio=source_step.ghost_gate_ratio,
    )


def _apply_kick_rolls(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
    log: DebugLog | None = None,
) -> None:
    if params.kick_roll_density <= 1e-3 or len(steps) < 2 or not (pools.kick or pools.kick_ghost):
        _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="skipped_constraints")
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
            if _step_in_fill_reserved_zone(trigger_step) or _step_in_fill_reserved_zone(current_step):
                continue
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
            _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="no_candidate")
            continue
        _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="candidates", amount=len(weighted_candidates))
        if float(rng.random()) > (0.08 + (0.92 * params.kick_roll_density)):
            _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="skipped_probability")
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
            if _zone_intersects_fill_reserved(
                steps,
                start_step_index=chosen_trigger_index,
                end_step_index=chosen_trigger_index + zone_span - 1,
            ):
                _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="skipped_protected")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_trigger_index
                ]
                continue
            source_hit = _pick_kick_roll_source_hit(
                trigger_step,
                pools,
                params=params,
                rng=rng,
                target_step_index=chosen_trigger_index,
            )
            if source_hit is None:
                _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="skipped_no_source")
                continue
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=min(step_count, bar_start + 15),
                target_step_indices=range(chosen_trigger_index, chosen_trigger_index + zone_span),
                params=params,
            ):
                _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="skipped_budget")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_trigger_index
                ]
                continue
            _debug_log_pass_stat(log, pass_name="kick_roll_pass", stat="applied")
            for zone_offset in range(zone_span):
                target_step_index = chosen_trigger_index + zone_offset
                replacement = _build_kick_roll_step(
                    target_step_index,
                    source_hit=source_hit,
                    zone_span=zone_span,
                    zone_offset=zone_offset,
                    contrast=params.kick_roll_contrast,
                )
                _debug_log_step_write(log, pass_name="kick_roll_pass", step=replacement, note=_debug_note_for_kick_roll_step(replacement))
                steps[target_step_index - 1] = replacement
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
        if _step_in_fill_reserved_zone(current):
            break
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


def generate_stretch_retriggers(
    start_step: int,
    span_steps: int,
    ticks_per_step: int,
    amount: float,
    velocity_start: float,
    velocity_end: float,
) -> list[StretchRetrigger]:
    resolved_span = int(np.clip(int(span_steps), 2, 16))
    resolved_ticks = max(1, int(ticks_per_step))
    ratio = _lerp(0.85, 0.40, amount)
    total_ticks = max(1, resolved_span * resolved_ticks)
    retriggers: list[StretchRetrigger] = []
    current = 0.0
    interval = max(1.0, float(total_ticks) * 0.3)

    while current < float(total_ticks) and interval >= 1.0:
        step_idx = int(start_step) + int(current // resolved_ticks)
        sub_offset = int(current % resolved_ticks)
        t = float(current / float(total_ticks))
        retriggers.append(
            StretchRetrigger(
                slice_source=None,
                offset_ticks=int(current),
                step_index=step_idx,
                sub_step_offset=sub_offset,
                velocity=float(_lerp(velocity_start, velocity_end, t)),
            )
        )
        interval *= ratio
        current += interval

    return retriggers


def _apply_snare_stretches(
    steps: list[GeneratedPatternStep],
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
    log: DebugLog | None = None,
) -> None:
    if params.snare_stretch_density <= 1e-3 or not steps:
        _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="skipped_constraints")
        return

    hit_by_index = {int(hit.index): hit for hit in pools.all_hits}
    if not hit_by_index:
        _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="no_pool")
        return

    step_count = len(steps)
    bar_count = max(1, step_count // 16)
    desired_span = _snare_stretch_target_span_steps(params.snare_stretch_span)
    for bar_index in range(bar_count):
        bar_start = (bar_index * 16) + 1
        bar_end = min(step_count, bar_start + 15)
        weighted_candidates: list[tuple[int, float, int]] = []
        for step_index in range(bar_start, bar_end + 1):
            current = steps[step_index - 1]
            if _step_in_fill_reserved_zone(current):
                continue
            weight = _snare_stretch_weight(current, step_index=step_index, params=params)
            if weight <= 1e-6:
                continue
            max_span = _snare_stretch_max_span(
                start_step_index=int(step_index),
                steps=steps,
                anchors=anchors,
            )
            zone_span = min(int(max_span), int(desired_span))
            if zone_span < 2:
                continue
            if int(current.source_hit_index or -1) not in hit_by_index:
                continue
            span_bonus = 1.0 + (0.05 * float(zone_span - 2))
            weighted_candidates.append((int(step_index), float(weight * span_bonus), int(zone_span)))

        if not weighted_candidates:
            _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="no_candidate")
            continue
        _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="candidates", amount=len(weighted_candidates))
        if float(rng.random()) > (0.08 + (0.92 * params.snare_stretch_density)):
            _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="skipped_probability")
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
            zone_span = next(
                (span for step_index, _weight, span in weighted_candidates if int(step_index) == chosen_step_index),
                2,
            )
            stretch_tail_cost = 1 if any((((int(step_index) - 1) % 16) + 1) >= 13 for step_index in range(chosen_step_index, chosen_step_index + zone_span)) else 0
            if not _bar_has_post_mutation_capacity(
                steps,
                bar_start=bar_start,
                bar_end=bar_end,
                target_step_indices=range(chosen_step_index, chosen_step_index + zone_span),
                params=params,
                planned_post_cost=1,
                planned_tail_cost=stretch_tail_cost,
            ):
                _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="skipped_budget")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue

            source_hit = hit_by_index.get(int(current.source_hit_index or -1))
            if source_hit is None:
                _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="skipped_no_source")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue

            retriggers = _build_snare_stretch_retriggers(
                current,
                source_hit,
                span_steps=int(zone_span),
                params=params,
                rng=rng,
            )
            if not retriggers:
                _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="skipped_constraints")
                weighted_candidates = [
                    (step_index, weight, span)
                    for step_index, weight, span in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue

            _debug_log_pass_stat(log, pass_name="snare_stretch_pass", stat="applied")
            replacement = _mark_step_for_snare_stretch(
                current,
                zone_span=zone_span,
                amount=params.snare_stretch_amount,
                vel_curve=params.snare_stretch_vel_curve,
                retriggers=tuple(retriggers),
            )
            _debug_log_step_write(log, pass_name="snare_stretch_pass", step=replacement, note=_debug_note_for_snare_stretch_step(replacement))
            steps[chosen_step_index - 1] = replacement
            for zone_offset in range(1, int(zone_span)):
                target_step_index = chosen_step_index + zone_offset
                if target_step_index > len(steps):
                    break
                replacement = _decorate_step_for_snare_stretch_zone(
                    steps[target_step_index - 1],
                    zone_span=zone_span,
                    zone_offset=zone_offset,
                    amount=params.snare_stretch_amount,
                    vel_curve=params.snare_stretch_vel_curve,
                    retriggers=tuple(retriggers),
                )
                _debug_log_step_write(log, pass_name="snare_stretch_pass", step=replacement, note=_debug_note_for_snare_stretch_step(replacement))
                steps[target_step_index - 1] = replacement
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
    if _step_in_fill_reserved_zone(step):
        return 0.0
    if _step_is_structurally_protected(step):
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
        base_weight *= 1.32
    elif local_step in _OFFBEAT_STEPS:
        base_weight *= 0.94
    elif local_step in _FILL_STEPS:
        base_weight *= 1.08
    elif local_step in _STRONG_STEPS:
        base_weight *= 0.12
    else:
        base_weight *= 0.52

    if step.label == "snare_ruff":
        base_weight *= 1.08 if ("fill" in tags or "phrase_end" in tags) else 0.68

    if "phrase_end" in tags:
        base_weight *= _lerp(1.0, 1.08, params.fill_strength)
    if "fill" in tags:
        base_weight *= _lerp(1.0, 1.12, params.fill_strength)
    if "anchor" in tags:
        base_weight *= 1.16
    density_drive = _lerp(0.32, 1.28, params.snare_stretch_density)
    amount_drive = _lerp(0.88, 1.16, params.snare_stretch_amount)
    return float(max(0.0, base_weight * density_drive * amount_drive))


def _snare_stretch_max_span(
    *,
    start_step_index: int,
    steps: list[GeneratedPatternStep],
    anchors: Mapping[int, str] | None = None,
) -> int:
    local_step = ((int(start_step_index) - 1) % 16) + 1
    to_bar_end = 17 - local_step
    max_span = min(int(to_bar_end), len(steps) - int(start_step_index) + 1, 16)
    for target_step_index in range(int(start_step_index) + 1, int(start_step_index) + int(max_span)):
        if _step_in_fill_reserved_zone(steps[target_step_index - 1]):
            max_span = min(max_span, int(target_step_index) - int(start_step_index))
            break
        if anchors and int(target_step_index) in anchors:
            max_span = min(max_span, int(target_step_index) - int(start_step_index))
            break
        if _step_is_structurally_protected(steps[target_step_index - 1]):
            max_span = min(max_span, int(target_step_index) - int(start_step_index))
            break
    return int(max(0, max_span))


def _snare_stretch_target_span_steps(value: float) -> int:
    return int(np.clip(round(_lerp(2.0, 16.0, float(np.clip(value, 0.0, 1.0)))), 2, 16))


def _snare_stretch_base_velocity(step: GeneratedPatternStep) -> float:
    if int(getattr(step, "velocity", 0)) > 0:
        return float(np.clip(float(step.velocity), 1.0, 127.0))
    velocity_label = str(step.source_label or step.label or "snare")
    base_velocity = float(_VELOCITY_RANGES.get(velocity_label, _VELOCITY_RANGES["snare"])[0])
    return float(np.clip(base_velocity, 1.0, 127.0))


def _snare_stretch_velocity_bounds(
    base_velocity: float,
    *,
    amount: float,
    vel_curve: str,
) -> tuple[float, float]:
    resolved_base = float(np.clip(base_velocity, 1.0, 127.0))
    tail_velocity = float(np.clip(_lerp(resolved_base * 0.72, resolved_base * 0.18, amount), 12.0, resolved_base))
    if vel_curve == "flat":
        return resolved_base, resolved_base
    if vel_curve == "crescendo":
        return tail_velocity, resolved_base
    return resolved_base, tail_velocity


def _build_snare_stretch_retriggers(
    step: GeneratedPatternStep,
    source_hit: TransientHit,
    *,
    span_steps: int,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
) -> tuple[StretchRetrigger, ...]:
    velocity_start, velocity_end = _snare_stretch_velocity_bounds(
        _snare_stretch_base_velocity(step),
        amount=params.snare_stretch_amount,
        vel_curve=params.snare_stretch_vel_curve,
    )
    retriggers = generate_stretch_retriggers(
        start_step=int(step.step_index),
        span_steps=int(span_steps),
        ticks_per_step=STRETCH_TICKS_PER_STEP,
        amount=params.snare_stretch_amount,
        velocity_start=velocity_start,
        velocity_end=velocity_end,
    )
    low_velocity = min(velocity_start, velocity_end)
    high_velocity = max(velocity_start, velocity_end)
    assigned: list[StretchRetrigger] = []
    for retrigger in retriggers:
        velocity = float(retrigger.velocity)
        if params.snare_stretch_vel_curve == "random":
            velocity = float(rng.uniform(low_velocity, high_velocity))
        assigned.append(
            replace(
                retrigger,
                slice_source=source_hit,
                velocity=float(np.clip(velocity, 1.0, 127.0)),
            )
        )
    return tuple(assigned)


def _snare_stretch_zone_tags(
    target_step_index: int,
    *,
    zone_span: int,
    amount: float,
    vel_curve: str,
    is_start: bool,
    is_end: bool,
    inherited_tags: Iterable[str],
) -> tuple[str, ...]:
    tags = [
        _step_tag(target_step_index),
        "effect",
        "effect_snare_stretch",
        "snare_stretch_zone",
        f"snare_stretch_zone_span_{int(max(2, zone_span))}",
        f"snare_stretch_amount_{int(round(np.clip(amount, 0.0, 1.0) * 100.0))}",
        f"snare_stretch_curve_{_normalize_snare_stretch_vel_curve(vel_curve)}",
        "owner_fx",
    ]
    if is_start:
        tags.extend(("snare_stretch", "snare_stretch_zone_start"))
    else:
        tags.append("snare_stretch_tail")
    if is_end:
        tags.append("snare_stretch_zone_end")
    tags.extend(tag for tag in inherited_tags if "snare_stretch" not in str(tag))
    return tuple(dict.fromkeys(tags))


def _mark_step_for_snare_stretch(
    source_step: GeneratedPatternStep,
    *,
    zone_span: int,
    amount: float,
    vel_curve: str,
    retriggers: tuple[StretchRetrigger, ...],
) -> GeneratedPatternStep:
    target_step_index = int(source_step.step_index)
    return GeneratedPatternStep(
        step_index=target_step_index,
        label=source_step.label,
        velocity=source_step.velocity,
        source_hit_index=source_step.source_hit_index,
        source_label=source_step.source_label,
        source_start_s=source_step.source_start_s,
        source_end_s=source_step.source_end_s,
        tags=_snare_stretch_zone_tags(
            target_step_index,
            zone_span=zone_span,
            amount=amount,
            vel_curve=vel_curve,
            is_start=True,
            is_end=zone_span <= 1,
            inherited_tags=(
                tag
                for tag in source_step.tags
                if tag in _RHYTHMIC_TAGS or str(tag).startswith("anchor_") or tag == "anchor"
            ),
        ),
        relative_velocity_ratio=source_step.relative_velocity_ratio,
        source_sequence_index=source_step.source_sequence_index,
        source_sequence_role=source_step.source_sequence_role,
        pitch_shift=source_step.pitch_shift,
        is_synthetic_ghost=source_step.is_synthetic_ghost,
        ghost_vel_ratio=source_step.ghost_vel_ratio,
        ghost_pitch_offset=source_step.ghost_pitch_offset,
        ghost_gate_ratio=source_step.ghost_gate_ratio,
        stretch_retriggers=retriggers,
    )


def _decorate_step_for_snare_stretch_zone(
    source_step: GeneratedPatternStep,
    *,
    zone_span: int,
    zone_offset: int,
    amount: float,
    vel_curve: str,
    retriggers: tuple[StretchRetrigger, ...],
) -> GeneratedPatternStep:
    target_step_index = int(source_step.step_index)
    return GeneratedPatternStep(
        step_index=target_step_index,
        label="silence",
        velocity=0,
        source_hit_index=None,
        source_label=None,
        source_start_s=None,
        source_end_s=None,
        tags=_snare_stretch_zone_tags(
            target_step_index,
            zone_span=zone_span,
            amount=amount,
            vel_curve=vel_curve,
            is_start=False,
            is_end=int(zone_offset) >= int(max(2, zone_span) - 1),
            inherited_tags=(tag for tag in source_step.tags if tag in _RHYTHMIC_TAGS),
        ),
        stretch_retriggers=retriggers,
    )


def _apply_reverse_steps(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    *,
    anchors: Mapping[int, str] | None = None,
    log: DebugLog | None = None,
) -> None:
    if params.reverse_density <= 1e-3 or not steps:
        _debug_log_pass_stat(log, pass_name="reverse_pass", stat="skipped_constraints")
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
            if _step_in_fill_reserved_zone(trigger_step) or _step_in_fill_reserved_zone(current):
                continue
            weight = _reverse_transition_weight(trigger_step, current, step_index=step_index)
            if weight <= 1e-6:
                continue
            weighted_candidates.append((int(step_index), float(weight)))

        if not weighted_candidates:
            _debug_log_pass_stat(log, pass_name="reverse_pass", stat="no_candidate")
            continue
        _debug_log_pass_stat(log, pass_name="reverse_pass", stat="candidates", amount=len(weighted_candidates))

        if float(rng.random()) > (0.1 + (0.9 * params.reverse_density)):
            _debug_log_pass_stat(log, pass_name="reverse_pass", stat="skipped_probability")
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
                _debug_log_pass_stat(log, pass_name="reverse_pass", stat="skipped_budget")
                weighted_candidates = [
                    (step_index, weight)
                    for step_index, weight in weighted_candidates
                    if int(step_index) != chosen_step_index
                ]
                continue
            trigger_step = steps[chosen_step_index - 2]
            current = steps[chosen_step_index - 1]
            replacement = _build_reverse_transition_step(
                chosen_step_index,
                trigger_step=trigger_step,
                current_step=current,
            )
            _debug_log_pass_stat(log, pass_name="reverse_pass", stat="applied")
            _debug_log_step_write(log, pass_name="reverse_pass", step=replacement, note=_debug_note_for_reverse_step(replacement))
            steps[chosen_step_index - 1] = replacement
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
    if _step_in_fill_reserved_zone(step):
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
    if _step_in_fill_reserved_zone(trigger_step) or _step_in_fill_reserved_zone(target_step):
        return 0.0
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
        pitch_shift=trigger_step.pitch_shift,
        is_synthetic_ghost=trigger_step.is_synthetic_ghost,
        ghost_vel_ratio=trigger_step.ghost_vel_ratio,
        ghost_pitch_offset=trigger_step.ghost_pitch_offset,
        ghost_gate_ratio=trigger_step.ghost_gate_ratio,
    )


def _enforce_step_anchors(
    steps: list[GeneratedPatternStep],
    anchors: Mapping[int, str] | None,
    pools: _PatternPools,
    params: _ResolvedPatternParams,
    rng: np.random.Generator,
    log: DebugLog | None = None,
) -> None:
    if not anchors or not steps:
        return

    for step_index in sorted(int(index) for index in anchors.keys()):
        if step_index < 1 or step_index > len(steps):
            continue
        anchor = str(anchors[step_index])
        current = steps[step_index - 1]
        fill_decision = _step_fill_decision(current)
        if _generated_step_matches_anchor(current, anchor):
            replacement = replace(
                current,
                tags=tuple(dict.fromkeys((*current.tags, "anchor", f"anchor_{anchor}", "owner_anchor"))),
            )
            if fill_decision is not None:
                replacement = _merge_fill_decision_tags(replacement, fill_decision)
            _debug_log_step_write(log, pass_name="anchor_reapply", step=replacement, note=_debug_note_for_anchor_reapply(anchor))
            steps[step_index - 1] = replacement
            continue
        replacement = _select_anchored_step_event(
            step_index,
            anchor,
            steps[: step_index - 1],
            pools,
            params,
            rng,
        )
        if fill_decision is not None:
            replacement = _merge_fill_decision_tags(replacement, fill_decision)
        _debug_log_step_write(log, pass_name="anchor_reapply", step=replacement, note=_debug_note_for_anchor_reapply(anchor))
        steps[step_index - 1] = replacement


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
            pitch_shift=step.pitch_shift,
            is_synthetic_ghost=step.is_synthetic_ghost,
            ghost_vel_ratio=step.ghost_vel_ratio,
            ghost_pitch_offset=step.ghost_pitch_offset,
            ghost_gate_ratio=step.ghost_gate_ratio,
            stretch_retriggers=step.stretch_retriggers,
        )

    velocity_label = step.source_label if step.is_synthetic_ghost and step.source_label else step.label
    base, spread = _VELOCITY_RANGES.get(velocity_label, _VELOCITY_RANGES["perc"])
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

    if (not step.is_synthetic_ghost) and step.label in {"ghost_snare", "snare_ghost"}:
        velocity = rng.uniform(25.0, 45.0)
    elif (not step.is_synthetic_ghost) and step.label == "kick_ghost":
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
        pitch_shift=step.pitch_shift,
        is_synthetic_ghost=step.is_synthetic_ghost,
        ghost_vel_ratio=step.ghost_vel_ratio,
        ghost_pitch_offset=step.ghost_pitch_offset,
        ghost_gate_ratio=step.ghost_gate_ratio,
        stretch_retriggers=step.stretch_retriggers,
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
    if params.generation_profile == "safe":
        budget -= 1.0
    elif params.generation_profile == "destructive":
        budget += 1.0
    return int(np.clip(round(budget), 2, 9))


def _bar_tail_mutation_budget(params: _ResolvedPatternParams) -> int:
    fx_tail_drive = max(
        float(params.fill_strength),
        float(params.kick_roll_density),
        float(params.snare_stretch_density),
        float(params.reverse_density) * 0.5,
    )
    budget = 1.5 + (2.8 * fx_tail_drive)
    if params.generation_profile == "safe":
        budget -= 1.0
    elif params.generation_profile == "destructive":
        budget += 1.0
    return int(np.clip(round(budget), 1, 5))


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
    *,
    params: _ResolvedPatternParams,
) -> tuple[int, int]:
    total_cost = 0
    tail_cost = 0
    seen: set[int] = set()
    for raw_step_index in step_indices:
        step_index = int(raw_step_index)
        if step_index in seen or step_index < 1 or step_index > len(steps):
            continue
        seen.add(step_index)
        if _step_has_post_mutation(steps[step_index - 1]) and params.generation_profile == "destructive":
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
    planned_post_cost: int | None = None,
    planned_tail_cost: int | None = None,
) -> bool:
    max_post_steps = _bar_post_mutation_budget(params)
    max_tail_steps = _bar_tail_mutation_budget(params)
    current_post_steps = _bar_post_mutation_count(steps, bar_start=bar_start, bar_end=bar_end)
    current_tail_steps = _bar_post_mutation_count(steps, bar_start=bar_start, bar_end=bar_end, tail_only=True)
    if planned_post_cost is None or planned_tail_cost is None:
        added_post_steps, added_tail_steps = _planned_post_mutation_cost(
            steps,
            target_step_indices,
            params=params,
        )
    else:
        added_post_steps = max(0, int(planned_post_cost))
        added_tail_steps = max(0, int(planned_tail_cost))
    if current_post_steps + added_post_steps > max_post_steps:
        return False
    if current_tail_steps + added_tail_steps > max_tail_steps:
        return False
    return True


def _fmt_param(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _fmt_signed(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    formatted = f"{number:+.2f}".rstrip("0").rstrip(".")
    return formatted


def _fmt_bool(value: object) -> str:
    return "T" if bool(value) else "F"


def _fmt_range(value: object) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return f"({_fmt_signed(value[0])}, {_fmt_signed(value[1])})"
    return str(value)


def _format_repeat_rate(value: object) -> str:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "x4" if rate >= 0.5 else "x2"


def _lerp(start: float, end: float, amount: float) -> float:
    return float(start + ((end - start) * np.clip(amount, 0.0, 1.0)))


def _apply_pitch_movement(
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    *,
    seed: int,
    log: DebugLog | None = None,
) -> list[GeneratedPatternStep]:
    if not steps:
        return []

    if params.pitch_mode == "off" or params.pitch_amount <= 1e-6:
        return [
            replace(step, pitch_shift=0.0) if abs(float(getattr(step, "pitch_shift", 0.0))) > 1e-6 else step
            for step in steps
        ]

    target_indices = [index for index, step in enumerate(steps) if _step_is_pitch_target(step, params.pitch_scope)]
    if not target_indices:
        return [
            replace(step, pitch_shift=0.0) if abs(float(getattr(step, "pitch_shift", 0.0))) > 1e-6 else step
            for step in steps
        ]

    pitch_by_index: dict[int, float] = {}
    if params.pitch_mode == "random":
        pitch_by_index = _random_pitch_shifts_for_targets(target_indices, steps, params, seed=seed)
    elif params.pitch_mode == "sequence":
        pitch_by_index = _sequence_pitch_shifts_for_targets(target_indices, steps, params)
    elif params.pitch_mode == "curve":
        pitch_by_index = _curve_pitch_shifts_for_targets(target_indices, steps, params)

    updated_steps: list[GeneratedPatternStep] = []
    for index, step in enumerate(steps):
        pitch_shift = float(np.clip(pitch_by_index.get(index, 0.0), -24.0, 24.0))
        if abs(float(getattr(step, "pitch_shift", 0.0)) - pitch_shift) <= 1e-6:
            updated_steps.append(step)
            continue
        updated_step = replace(step, pitch_shift=pitch_shift)
        if log is not None:
            _debug_log_step_write(log, pass_name="pitch_pass", step=updated_step, note=_debug_note_for_pitch_step(updated_step))
        updated_steps.append(updated_step)
    return updated_steps


def _step_is_pitch_target(step: GeneratedPatternStep, scope: str) -> bool:
    if step.label == "silence" or step.source_start_s is None or step.source_end_s is None:
        return False
    if any(tag in {"reverse", "snare_stretch_tail", "snare_stretch_hold"} for tag in step.tags):
        return False

    if scope == "snare":
        return step.label in {"snare", "snare_ruff"}
    if scope == "snare+clap":
        return step.label in {"snare", "snare_ruff", "clap"}
    if scope == "all_pillar":
        return step.label in {"kick", "snare", "snare_ruff", "clap"}
    return True


def _random_pitch_shifts_for_targets(
    target_indices: list[int],
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
    *,
    seed: int,
) -> dict[int, float]:
    allowed_values = _allowed_pitch_values(
        params.pitch_scale,
        root=params.pitch_root,
        pitch_range=params.pitch_range,
    )
    if not allowed_values:
        return {}

    rng = np.random.default_rng(int(seed) ^ 0x5F3759DF)
    shifts_by_group: dict[int, float] = {}
    pitch_by_index: dict[int, float] = {}
    for order_index, target_index in enumerate(target_indices):
        group_key = _pitch_group_key(order_index, steps[target_index], params.pitch_rate)
        if group_key not in shifts_by_group:
            raw_value = float(rng.choice(allowed_values))
            shifts_by_group[group_key] = float(raw_value * params.pitch_amount)
        pitch_by_index[target_index] = shifts_by_group[group_key]
    return pitch_by_index


def _sequence_pitch_shifts_for_targets(
    target_indices: list[int],
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
) -> dict[int, float]:
    if not params.pitch_sequence:
        return {}

    sequence_values = tuple(float(np.clip(value, -24.0, 24.0)) for value in params.pitch_sequence)
    shifts_by_group: dict[int, float] = {}
    pitch_by_index: dict[int, float] = {}
    group_counter = 0
    for order_index, target_index in enumerate(target_indices):
        group_key = _pitch_group_key(order_index, steps[target_index], params.pitch_rate)
        if group_key not in shifts_by_group:
            shifts_by_group[group_key] = float(sequence_values[group_counter % len(sequence_values)] * params.pitch_amount)
            group_counter += 1
        pitch_by_index[target_index] = shifts_by_group[group_key]
    return pitch_by_index


def _curve_pitch_shifts_for_targets(
    target_indices: list[int],
    steps: list[GeneratedPatternStep],
    params: _ResolvedPatternParams,
) -> dict[int, float]:
    lower, upper = params.pitch_curve_range
    pitch_by_index: dict[int, float] = {}
    for group in _pitch_curve_groups(target_indices, steps, rate=params.pitch_rate):
        group_size = len(group)
        for position, target_index in enumerate(group):
            raw_value = _pitch_curve_value(
                position=position,
                count=group_size,
                minimum=lower,
                maximum=upper,
                curve=params.pitch_curve,
            )
            quantized = _quantize_pitch_value(
                raw_value,
                scale=params.pitch_scale,
                root=params.pitch_root,
                pitch_range=params.pitch_curve_range,
            )
            pitch_by_index[target_index] = float(quantized * params.pitch_amount)
    return pitch_by_index


def _pitch_group_key(order_index: int, step: GeneratedPatternStep, rate: str) -> int:
    if rate == "every_bar":
        return max(0, (int(step.step_index) - 1) // 16)
    if rate == "every_2":
        return max(0, int(order_index) // 2)
    return max(0, int(order_index))


def _pitch_curve_groups(
    target_indices: list[int],
    steps: list[GeneratedPatternStep],
    *,
    rate: str,
) -> tuple[tuple[int, ...], ...]:
    if rate == "every_bar":
        groups_by_bar: dict[int, list[int]] = {}
        for target_index in target_indices:
            step_number = int(steps[target_index].step_index)
            bar_index = max(0, (step_number - 1) // 16)
            groups_by_bar.setdefault(bar_index, []).append(int(target_index))
        return tuple(tuple(group) for _bar, group in sorted(groups_by_bar.items()))

    if rate == "every_2":
        paired_groups: list[tuple[int, ...]] = []
        current_group: list[int] = []
        current_bar_index: int | None = None
        for target_index in target_indices:
            step_number = int(steps[target_index].step_index)
            bar_index = max(0, (step_number - 1) // 16)
            if current_group and (current_bar_index != bar_index or len(current_group) >= 2):
                paired_groups.append(tuple(current_group))
                current_group = []
            current_group.append(int(target_index))
            current_bar_index = bar_index
        if current_group:
            paired_groups.append(tuple(current_group))
        return tuple(paired_groups)

    groups: list[tuple[int, ...]] = []
    current_group: list[int] = []
    previous_step_index: int | None = None
    previous_bar_index: int | None = None
    for target_index in target_indices:
        step_number = int(steps[target_index].step_index)
        bar_index = max(0, (step_number - 1) // 16)
        if (
            current_group
            and (
                previous_step_index is None
                or previous_bar_index != bar_index
                or step_number - previous_step_index > 2
            )
        ):
            groups.append(tuple(current_group))
            current_group = []
        current_group.append(int(target_index))
        previous_step_index = step_number
        previous_bar_index = bar_index
    if current_group:
        groups.append(tuple(current_group))
    return tuple(groups)


def _pitch_curve_value(
    *,
    position: int,
    count: int,
    minimum: float,
    maximum: float,
    curve: str,
) -> float:
    if count <= 1:
        phase = 0.5
    else:
        phase = float(position) / float(max(1, count - 1))
    if curve == "down":
        amount = 1.0 - phase
    elif curve == "bell":
        amount = 1.0 - abs((2.0 * phase) - 1.0)
    elif curve == "inv_bell":
        amount = abs((2.0 * phase) - 1.0)
    else:
        amount = phase
    return _lerp(minimum, maximum, amount)


def _allowed_pitch_values(
    scale: str,
    *,
    root: int,
    pitch_range: tuple[float, float],
) -> tuple[float, ...]:
    lower, upper = pitch_range
    if upper < lower:
        lower, upper = upper, lower
    start = int(np.floor(lower))
    end = int(np.ceil(upper))
    if scale == "chromatic":
        return tuple(float(value) for value in range(start, end + 1))

    allowed_pitch_classes = {
        int((int(root) + int(interval)) % 12)
        for interval in _PITCH_SCALES.get(scale, _PITCH_SCALES["chromatic"])
    }
    values = [
        float(value)
        for value in range(start, end + 1)
        if int(value) % 12 in allowed_pitch_classes
    ]
    return tuple(values)


def _quantize_pitch_value(
    value: float,
    *,
    scale: str,
    root: int,
    pitch_range: tuple[float, float],
) -> float:
    if scale == "chromatic":
        lower, upper = pitch_range
        return float(np.clip(round(float(value)), lower, upper))
    allowed_values = _allowed_pitch_values(scale, root=root, pitch_range=pitch_range)
    if not allowed_values:
        lower, upper = pitch_range
        return float(np.clip(round(float(value)), lower, upper))
    return float(min(allowed_values, key=lambda candidate: (abs(candidate - float(value)), abs(candidate))))


def _build_generated_pattern(
    steps: tuple[GeneratedPatternStep, ...],
    params: BreakPatternParams,
    resolved_params: _ResolvedPatternParams,
    *,
    fill_decisions: Iterable[FillDecision] | None = None,
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
        "pitch_ratio": float(sum(1 for step in steps if abs(float(step.pitch_shift)) > 1e-6) / total_steps),
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
        fill_decisions=tuple(fill_decisions or ()),
        metrics=metrics,
    )
