from __future__ import annotations

import unittest
import numpy as np

from prototypes.drum_detector.analyzer import HitSequence, HitSequenceEvent, TransientHit
from prototypes.drum_detector.pattern_generator import (
    BreakPatternParams,
    _build_pools,
    _build_sequence_pools,
    _pick_sequence_for_step,
    _pick_weighted_hit,
    _resolve_params,
    estimate_pattern_family_probabilities,
    generate_break_pattern,
    reroll_break_pattern_step,
)


class PatternGeneratorTests(unittest.TestCase):
    def test_generates_one_event_per_step_on_16_step_grid(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "closed_hat", 0.78, -3.0, 0.1, 0.2, 0.82),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(seed=123, ghost_density=0.4, hat_density=0.7),
        )

        self.assertEqual(pattern.step_count, 16)
        self.assertEqual(len(pattern.steps), 16)
        self.assertEqual([step.step_index for step in pattern.steps], list(range(1, 17)))

    def test_generates_requested_number_of_bars(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        pattern = generate_break_pattern(hits, BreakPatternParams(seed=321, bars=2))

        self.assertEqual(pattern.bars, 2)
        self.assertEqual(pattern.step_count, 32)
        self.assertEqual(len(pattern.steps), 32)
        self.assertEqual(pattern.steps[-1].step_index, 32)

    def test_falls_back_to_available_slice_types_when_pools_are_sparse(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(seed=7, kick_weight=1.0, snare_weight=1.0, hat_density=1.0),
        )

        non_silence = {step.label for step in pattern.steps if step.label != "silence"}
        self.assertTrue(non_silence.issubset({"kick", "kick_ghost"}))

    def test_probability_preview_reflects_kick_zero_setting(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        preview = estimate_pattern_family_probabilities(
            hits,
            BreakPatternParams(seed=12, kick_weight=0.0, snare_weight=1.0, hat_density=1.0, breath_factor=0.0),
        )

        self.assertAlmostEqual(preview.rows["downbeat"]["kick"], 0.0, places=6)
        self.assertGreater(preview.rows["downbeat"]["snare"], 0.0)
        self.assertGreater(preview.rows["downbeat"]["other"], 0.0)

    def test_zero_kick_weight_removes_automatic_kicks_from_skeleton(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "perc", 0.78, -4.0, 0.2, 0.4, 0.4),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=99,
                bars=1,
                kick_weight=0.0,
                snare_weight=0.9,
                hat_density=0.8,
                ghost_density=0.0,
                fill_strength=0.0,
                breath_factor=0.0,
            ),
        )

        self.assertFalse(any(step.label == "kick" for step in pattern.steps))

    def test_reroll_break_pattern_step_only_changes_requested_step_index(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "perc", 0.75, -4.0, 0.1, 0.4, 0.5),
        )
        pattern = generate_break_pattern(hits, BreakPatternParams(seed=123, hat_density=0.7, fill_strength=0.5))

        rerolled = reroll_break_pattern_step(hits, pattern, 4, seed=9876)

        self.assertEqual(rerolled.step_count, pattern.step_count)
        self.assertEqual(rerolled.seed, 9876)
        self.assertEqual(
            [step.step_index for step in rerolled.steps],
            [step.step_index for step in pattern.steps],
        )
        for index, (before, after) in enumerate(zip(pattern.steps, rerolled.steps), start=1):
            if index == 4:
                continue
            self.assertEqual(before, after)

    def test_sequence_density_zero_keeps_atomic_behavior(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "closed_hat", 0.78, -3.0, 0.1, 0.2, 0.82),
        )
        sequence = HitSequence(
            index=1,
            role="groove",
            hit_count=2,
            total_steps=3,
            source_start_s=0.125,
            source_end_s=0.43,
            start_step_hint=2,
            end_step_hint=4,
            labels=("closed_hat", "closed_hat"),
            events=(
                HitSequenceEvent(1, 3, "closed_hat", "texture", 0, 0, 1.0, 0.125, 0.19),
                HitSequenceEvent(2, 4, "closed_hat", "texture", 2, 2, 0.72, 0.375, 0.43),
            ),
        )

        params = BreakPatternParams(seed=123, ghost_density=0.4, hat_density=0.7, sequence_density=0.0)
        atomic = generate_break_pattern(hits, params)
        with_sequences_disabled = generate_break_pattern(hits, params, sequences=(sequence,))

        self.assertEqual(atomic, with_sequences_disabled)

    def test_sequence_mode_injects_sequence_block_without_breaking_internal_gaps(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "closed_hat", 0.78, -3.0, 0.1, 0.2, 0.82),
        )
        sequence = HitSequence(
            index=1,
            role="groove",
            hit_count=2,
            total_steps=3,
            source_start_s=0.125,
            source_end_s=0.43,
            start_step_hint=2,
            end_step_hint=4,
            labels=("closed_hat", "closed_hat"),
            events=(
                HitSequenceEvent(1, 3, "closed_hat", "texture", 0, 0, 1.0, 0.125, 0.19),
                HitSequenceEvent(2, 4, "closed_hat", "texture", 2, 2, 0.72, 0.375, 0.43),
            ),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(seed=123, sequence_density=1.0, sequence_max_len=2, sequence_role_lock=True, bars=1),
            sequences=(sequence,),
        )

        self.assertEqual(pattern.steps[0].label, "closed_hat")
        self.assertEqual(pattern.steps[1].label, "silence")
        self.assertEqual(pattern.steps[2].label, "closed_hat")
        self.assertIn("sequence", pattern.steps[0].tags)
        self.assertIn("sequence_gap", pattern.steps[1].tags)
        self.assertEqual(pattern.steps[0].source_sequence_index, 1)
        self.assertEqual(pattern.steps[2].source_sequence_index, 1)
        self.assertAlmostEqual(pattern.steps[2].relative_velocity_ratio or 0.0, 0.72, places=2)

    def test_position_fidelity_biases_atomic_hit_selection(self) -> None:
        downbeat_hit = TransientHit(
            1,
            0.0,
            0.12,
            "kick",
            0.9,
            -1.0,
            0.8,
            0.1,
            0.1,
            role="pillar",
            rhythmic_position="downbeat",
        )
        offbeat_hit = TransientHit(
            2,
            0.125,
            0.22,
            "kick",
            0.9,
            -1.0,
            0.8,
            0.1,
            0.1,
            role="pillar",
            rhythmic_position="offbeat",
        )
        params = _resolve_params(BreakPatternParams(position_fidelity=1.0))

        selected_indices: list[int] = []
        for seed in range(64):
            rng = np.random.default_rng(seed)
            selected = _pick_weighted_hit(
                [(downbeat_hit, 1.0), (offbeat_hit, 1.0)],
                rng,
                None,
                None,
                params,
                target_step_index=1,
            )
            self.assertIsNotNone(selected)
            selected_indices.append(int(selected.index))

        self.assertGreater(selected_indices.count(1), selected_indices.count(2) * 4)

    def test_position_fidelity_biases_sequence_anchor_selection(self) -> None:
        downbeat_sequence = HitSequence(
            index=1,
            role="groove",
            hit_count=2,
            total_steps=2,
            source_start_s=0.0,
            source_end_s=0.19,
            start_step_hint=1,
            end_step_hint=2,
            labels=("closed_hat", "closed_hat"),
            events=(
                HitSequenceEvent(
                    1,
                    3,
                    "closed_hat",
                    "texture",
                    0,
                    0,
                    1.0,
                    0.0,
                    0.08,
                    rhythmic_position="downbeat",
                ),
                HitSequenceEvent(
                    2,
                    4,
                    "closed_hat",
                    "texture",
                    1,
                    1,
                    0.75,
                    0.125,
                    0.19,
                    rhythmic_position="subdivision",
                ),
            ),
        )
        offbeat_sequence = HitSequence(
            index=2,
            role="groove",
            hit_count=2,
            total_steps=2,
            source_start_s=0.125,
            source_end_s=0.31,
            start_step_hint=3,
            end_step_hint=4,
            labels=("closed_hat", "closed_hat"),
            events=(
                HitSequenceEvent(
                    1,
                    5,
                    "closed_hat",
                    "texture",
                    0,
                    0,
                    1.0,
                    0.125,
                    0.19,
                    rhythmic_position="offbeat",
                ),
                HitSequenceEvent(
                    2,
                    6,
                    "closed_hat",
                    "texture",
                    1,
                    1,
                    0.75,
                    0.25,
                    0.31,
                    rhythmic_position="subdivision",
                ),
            ),
        )
        params = _resolve_params(
            BreakPatternParams(
                sequence_density=1.0,
                sequence_max_len=2,
                sequence_role_lock=True,
                position_fidelity=1.0,
            )
        )
        sequence_pools = _build_sequence_pools((downbeat_sequence, offbeat_sequence), max_hit_count=2)
        pools = _build_pools(())

        selected_indices: list[int] = []
        for seed in range(64):
            rng = np.random.default_rng(seed)
            selected = _pick_sequence_for_step(1, [], sequence_pools, pools, params, rng)
            self.assertIsNotNone(selected)
            selected_indices.append(int(selected.index))

        self.assertGreater(selected_indices.count(1), selected_indices.count(2) * 4)

    def test_high_fill_strength_resolves_next_bar_after_fill_tail(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, secondary_labels=("open_hat",), layer_score=0.62, role="pillar"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8, role="texture"),
            TransientHit(3, 0.25, 0.37, "snare", 0.9, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(4, 0.312, 0.35, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill"),
            TransientHit(5, 0.37, 0.46, "open_hat", 0.78, -5.0, 0.05, 0.2, 0.9, role="accent"),
            TransientHit(6, 0.49, 0.62, "crash", 0.74, -6.0, 0.08, 0.2, 0.92, role="punctuation"),
            TransientHit(7, 0.44, 0.54, "perc", 0.7, -6.0, 0.15, 0.5, 0.5, role="fill"),
        )

        resolved_cases = 0
        for seed in range(1, 9):
            pattern = generate_break_pattern(
                hits,
                BreakPatternParams(seed=seed, fill_strength=0.95, bars=2, hat_density=0.7, ghost_density=0.25),
            )
            bar1_tail = pattern.steps[12:16]
            if not any("fill" in tag for step in bar1_tail for tag in step.tags):
                continue
            resolved_cases += 1
            self.assertIn(pattern.steps[12].label, {"snare", "clap"})
            self.assertEqual(pattern.steps[16].label, "kick")
            self.assertIn("resolution", pattern.steps[16].tags)

        self.assertGreaterEqual(resolved_cases, 3)

    def test_fill_release_avoids_crash_on_last_step_when_fill_is_active(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, secondary_labels=("open_hat",), layer_score=0.62, role="pillar"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8, role="texture"),
            TransientHit(3, 0.25, 0.37, "snare", 0.9, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(4, 0.312, 0.35, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill"),
            TransientHit(5, 0.37, 0.46, "open_hat", 0.78, -5.0, 0.05, 0.2, 0.9, role="accent"),
            TransientHit(6, 0.49, 0.62, "crash", 0.74, -6.0, 0.08, 0.2, 0.92, role="punctuation"),
            TransientHit(7, 0.44, 0.54, "perc", 0.7, -6.0, 0.15, 0.5, 0.5, role="fill"),
        )

        fill_cases = 0
        for seed in range(1, 9):
            pattern = generate_break_pattern(
                hits,
                BreakPatternParams(seed=seed, fill_strength=0.95, bars=2, hat_density=0.7, ghost_density=0.25),
            )
            bar1_tail = pattern.steps[12:16]
            if not any("fill" in tag for step in bar1_tail for tag in step.tags):
                continue
            fill_cases += 1
            self.assertNotEqual(pattern.steps[15].label, "crash")

        self.assertGreaterEqual(fill_cases, 3)

    def test_generate_break_pattern_respects_step_anchors(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar"),
            TransientHit(2, 0.25, 0.37, "snare", 0.91, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.84, -3.0, 0.1, 0.2, 0.82, role="texture"),
            TransientHit(4, 0.375, 0.48, "perc", 0.72, -5.0, 0.15, 0.45, 0.4, role="fill"),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(seed=77, fill_strength=0.85, hat_density=0.65),
            anchors={1: "kick", 3: "silence", 5: "snare", 13: "snare"},
        )

        self.assertEqual(pattern.steps[0].label, "kick")
        self.assertEqual(pattern.steps[2].label, "silence")
        self.assertEqual(pattern.steps[4].label, "snare")
        self.assertEqual(pattern.steps[12].label, "snare")
        self.assertIn("anchor", pattern.steps[0].tags)
        self.assertIn("anchor_silence", pattern.steps[2].tags)
        self.assertIn("anchor_snare", pattern.steps[4].tags)

    def test_reroll_break_pattern_step_respects_anchor_override(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar"),
            TransientHit(2, 0.25, 0.37, "snare", 0.91, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.84, -3.0, 0.1, 0.2, 0.82, role="texture"),
        )

        pattern = generate_break_pattern(hits, BreakPatternParams(seed=123, hat_density=0.7))
        rerolled = reroll_break_pattern_step(hits, pattern, 4, seed=456, anchors={4: "silence"})

        self.assertEqual(rerolled.steps[3].label, "silence")
        self.assertIn("anchor_silence", rerolled.steps[3].tags)
        for index, (before, after) in enumerate(zip(pattern.steps, rerolled.steps), start=1):
            if index == 4:
                continue
            self.assertEqual(before, after)

    def test_conflicting_sequences_do_not_override_anchored_steps(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar"),
            TransientHit(2, 0.25, 0.37, "snare", 0.91, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.84, -3.0, 0.1, 0.2, 0.82, role="texture"),
        )
        conflicting_sequence = HitSequence(
            index=7,
            role="groove",
            hit_count=2,
            total_steps=3,
            source_start_s=0.125,
            source_end_s=0.43,
            start_step_hint=1,
            end_step_hint=3,
            labels=("closed_hat", "closed_hat"),
            events=(
                HitSequenceEvent(1, 3, "closed_hat", "texture", 0, 0, 1.0, 0.125, 0.19),
                HitSequenceEvent(2, 3, "closed_hat", "texture", 2, 2, 0.72, 0.375, 0.43),
            ),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(seed=123, sequence_density=1.0, sequence_max_len=2, sequence_role_lock=True),
            sequences=(conflicting_sequence,),
            anchors={2: "snare"},
        )

        self.assertEqual(pattern.steps[1].label, "snare")
        self.assertIn("anchor_snare", pattern.steps[1].tags)
        self.assertNotIn("sequence_gap", pattern.steps[1].tags)


if __name__ == "__main__":
    unittest.main()
