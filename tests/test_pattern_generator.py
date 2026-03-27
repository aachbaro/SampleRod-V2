from __future__ import annotations

import unittest
import numpy as np

from prototypes.drum_detector.analyzer import HitSequence, HitSequenceEvent, TransientHit
from prototypes.drum_detector.pattern_generator import (
    BreakPatternParams,
    UserMotif,
    _build_pools,
    _build_hybrid_motif_anchors,
    _build_sequence_pools,
    _pick_sequence_for_step,
    _pick_weighted_hit,
    _resolve_params,
    estimate_pattern_effect_probabilities,
    estimate_pattern_family_probabilities,
    estimate_user_motif_effective_probability,
    generate_break_pattern,
    generate_break_pattern_hybrid,
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

    def test_user_motif_effective_probability_respects_motif_density(self) -> None:
        motif = UserMotif(
            steps=["kick", None, "snare", None],
            base_prob=0.8,
            role="groove",
            dominant_type="mixed",
            name="Kick Snare",
        )

        zero_density = estimate_user_motif_effective_probability(
            motif,
            BreakPatternParams(
                motif_density=0.0,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=1.0,
                ghost_density=1.0,
            ),
        )
        full_density = estimate_user_motif_effective_probability(
            motif,
            BreakPatternParams(
                motif_density=1.0,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=1.0,
                ghost_density=1.0,
            ),
        )

        self.assertAlmostEqual(zero_density, 0.0, places=6)
        self.assertGreater(full_density, 0.0)

    def test_hybrid_motif_anchor_builder_truncates_on_manual_anchor_collision(self) -> None:
        motif = UserMotif(
            steps=["kick", "hat", "snare", "hat"],
            base_prob=1.0,
            role="groove",
            dominant_type="mixed",
            name="Colliding motif",
        )
        params = BreakPatternParams(
            seed=12,
            motif_density=1.0,
            kick_weight=1.0,
            snare_weight=1.0,
            hat_density=1.0,
            ghost_density=0.0,
        )
        resolved = _resolve_params(params)

        anchors, placements = _build_hybrid_motif_anchors(
            (motif,),
            params,
            resolved,
            step_count=4,
            manual_anchors={3: "snare"},
            rng=np.random.default_rng(12),
        )

        self.assertEqual(anchors, {1: "kick", 2: "hat"})
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0].consumed_steps, 2)
        self.assertEqual(placements[0].applied_anchors, ((1, "kick"), (2, "hat")))

    def test_generate_break_pattern_hybrid_uses_user_motif_as_temporary_skeleton(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )
        motif = UserMotif(
            steps=["kick", None, "snare", None],
            base_prob=1.0,
            role="groove",
            dominant_type="mixed",
            name="Kick Snare",
        )

        pattern = generate_break_pattern_hybrid(
            hits,
            BreakPatternParams(
                seed=77,
                motif_density=1.0,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=0.8,
                ghost_density=0.0,
                fill_strength=0.0,
                repeat_density=0.0,
                reverse_density=0.0,
                sequence_density=0.0,
            ),
            user_motifs=[motif],
        )

        self.assertEqual(pattern.step_count, 16)
        self.assertIn(pattern.steps[0].label, {"kick", "kick_ghost"})
        self.assertIn(pattern.steps[2].label, {"snare", "clap", "snare_ruff"})

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

    def test_probability_preview_allows_kick_and_snare_on_offbeats(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        preview = estimate_pattern_family_probabilities(
            hits,
            BreakPatternParams(
                seed=21,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=1.0,
                ghost_density=0.0,
                breath_factor=0.0,
            ),
        )

        self.assertGreater(preview.rows["offbeat"]["kick"], 0.0)
        self.assertGreater(preview.rows["offbeat"]["snare"], 0.0)

    def test_probability_preview_allows_hat_and_ghost_on_downbeats_and_backbeats(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        preview = estimate_pattern_family_probabilities(
            hits,
            BreakPatternParams(
                seed=31,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=1.0,
                ghost_density=1.0,
                breath_factor=0.0,
            ),
        )

        self.assertGreater(preview.rows["downbeat"]["hat"], 0.0)
        self.assertGreater(preview.rows["downbeat"]["ghost"], 0.0)
        self.assertGreater(preview.rows["backbeat"]["hat"], 0.0)
        self.assertGreater(preview.rows["backbeat"]["ghost"], 0.0)

    def test_effect_probability_preview_favors_repeat_on_offbeats_and_fx_between_main_beats(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "perc", 0.75, -4.0, 0.1, 0.4, 0.5),
        )

        preview = estimate_pattern_effect_probabilities(
            hits,
            BreakPatternParams(
                seed=21,
                repeat_density=1.0,
                reverse_density=1.0,
                kick_roll_density=1.0,
                snare_stretch_density=1.0,
                snare_stretch_span=1.0,
                snare_stretch_amount=1.0,
                hat_density=1.0,
                snare_weight=1.0,
                kick_weight=1.0,
                breath_factor=0.0,
            ),
        )

        self.assertGreater(preview.rows["offbeat"]["repeat"], preview.rows["downbeat"]["repeat"])
        self.assertGreater(preview.rows["subdivision"]["reverse"], 0.0)
        self.assertGreater(preview.rows["subdivision"]["kick_roll"], 0.0)
        self.assertGreater(preview.rows["subdivision"]["kick_roll"], 0.18)
        self.assertGreater(preview.rows["offbeat"]["kick_roll"], 0.18)
        self.assertGreater(preview.rows["backbeat"]["kick_roll"], 0.55)
        self.assertAlmostEqual(preview.rows["downbeat"]["reverse"], 0.0, places=6)
        self.assertAlmostEqual(preview.rows["backbeat"]["reverse"], 0.0, places=6)
        self.assertAlmostEqual(preview.rows["offbeat"]["reverse"], 0.0, places=6)
        self.assertAlmostEqual(preview.rows["downbeat"]["kick_roll"], 0.0, places=6)
        self.assertGreater(preview.rows["backbeat"]["kick_roll"], preview.rows["subdivision"]["kick_roll"])
        self.assertGreater(preview.rows["backbeat"]["snare_stretch"], preview.rows["downbeat"]["snare_stretch"])
        self.assertGreater(preview.rows["backbeat"]["snare_stretch"], 0.1)
        self.assertGreater(preview.rows["offbeat"]["snare_stretch"], 0.02)

    def test_kick_roll_density_marks_even_length_kick_roll_zones(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "closed_hat", 0.78, -3.0, 0.1, 0.2, 0.82),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=717,
                kick_roll_density=1.0,
                kick_roll_span=1.0,
                kick_roll_contrast=1.0,
                repeat_density=0.0,
                reverse_density=0.0,
                fill_strength=0.0,
                sequence_density=0.0,
                hat_density=1.0,
                ghost_density=0.0,
                snare_weight=0.0,
            ),
            anchors={1: "kick", 5: "kick", 9: "kick", 13: "kick"},
        )

        kick_roll_steps = [step for step in pattern.steps if "kick_roll" in step.tags]

        self.assertTrue(kick_roll_steps)
        self.assertTrue(all("effect_kick_roll" in step.tags for step in kick_roll_steps))
        self.assertTrue(all(step.label in {"kick", "kick_ghost"} for step in kick_roll_steps))
        self.assertTrue(any("kick_roll_zone_start" in step.tags for step in kick_roll_steps))
        self.assertTrue(any("kick_roll_zone_end" in step.tags for step in kick_roll_steps))
        self.assertTrue(all(any(tag.startswith("kick_roll_zone_span_") for tag in step.tags) for step in kick_roll_steps))

        spans = []
        relative_ratios = []
        velocities = []
        for step in kick_roll_steps:
            for tag in step.tags:
                text = str(tag)
                if text.startswith("kick_roll_zone_span_"):
                    spans.append(int(text.removeprefix("kick_roll_zone_span_")))
            if step.relative_velocity_ratio is not None:
                relative_ratios.append(float(step.relative_velocity_ratio))
            velocities.append(int(step.velocity))
        self.assertTrue(spans)
        self.assertTrue(all(span % 2 == 0 for span in spans))
        self.assertGreaterEqual(max(spans), 4)
        self.assertTrue(relative_ratios)
        self.assertEqual(len({round(value, 4) for value in relative_ratios}), 1)
        self.assertEqual(len(set(velocities)), 1)
        self.assertTrue(all((((step.step_index - 1) % 16) + 1) in {5, 6, 7, 8, 13, 14, 15, 16} for step in kick_roll_steps))
        zone_starts = [step for step in kick_roll_steps if "kick_roll_zone_start" in step.tags]
        self.assertTrue(zone_starts)
        self.assertGreaterEqual(len(zone_starts), 2)
        self.assertTrue(all((((step.step_index - 1) % 16) + 1) in {5, 13} for step in zone_starts))

    def test_snare_stretch_density_marks_snare_steps_with_stretch_metadata(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "clap", 0.8, -3.0, 0.1, 0.5, 0.4),
            TransientHit(4, 0.375, 0.43, "closed_hat", 0.78, -3.0, 0.1, 0.2, 0.82),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=512,
                snare_stretch_density=1.0,
                snare_stretch_span=1.0,
                snare_stretch_amount=1.0,
                repeat_density=0.0,
                reverse_density=0.0,
                kick_roll_density=0.0,
                fill_strength=0.0,
                hat_density=0.0,
                ghost_density=0.0,
                kick_weight=0.0,
                snare_weight=1.0,
                sequence_density=0.0,
            ),
            anchors={5: "snare", 13: "snare"},
        )

        stretched_steps = [step for step in pattern.steps if "snare_stretch" in step.tags]
        zone_steps = [step for step in pattern.steps if "snare_stretch_zone" in step.tags]

        self.assertTrue(stretched_steps)
        self.assertTrue(zone_steps)
        self.assertTrue(all("effect_snare_stretch" in step.tags for step in stretched_steps))
        self.assertTrue(all(step.label in {"snare", "clap", "snare_ruff"} for step in stretched_steps))
        self.assertTrue(all("snare_stretch_zone_start" in step.tags for step in stretched_steps))
        self.assertTrue(all(any(str(tag).startswith("snare_stretch_zone_span_") for tag in step.tags) for step in stretched_steps))
        self.assertTrue(any((((step.step_index - 1) % 16) + 1) in {5, 13} for step in stretched_steps))
        self.assertFalse(any("snare_stretch_hold" in step.tags for step in pattern.steps))
        self.assertTrue(any("snare_stretch_zone_end" in step.tags for step in zone_steps))

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

    def test_repeat_density_marks_repeat_zones_with_configurable_rate(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "closed_hat", 0.78, -3.0, 0.1, 0.2, 0.82),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=123,
                repeat_density=1.0,
                repeat_span=1.0,
                repeat_rate=1.0,
                fill_strength=0.0,
                ghost_density=0.0,
                sequence_density=0.0,
                breath_factor=0.0,
            ),
        )

        repeated_steps = [step for step in pattern.steps if "repeat" in step.tags]

        self.assertTrue(repeated_steps)
        self.assertTrue(all("repeat_zone" in step.tags for step in repeated_steps))
        self.assertTrue(all("repeat_count_4" in step.tags for step in repeated_steps))
        self.assertTrue(any("repeat_zone_start" in step.tags for step in repeated_steps))
        self.assertTrue(any("repeat_zone_end" in step.tags for step in repeated_steps))
        self.assertTrue(any(any(tag.startswith("repeat_zone_span_") for tag in step.tags) for step in repeated_steps))
        self.assertTrue(all("repeat_glitch" in step.tags for step in repeated_steps))
        self.assertTrue(all(step.label != "silence" for step in repeated_steps))

    def test_reverse_density_marks_some_steps_as_reversed(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "perc", 0.75, -4.0, 0.1, 0.4, 0.5),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=444,
                reverse_density=1.0,
                sequence_density=0.0,
                repeat_density=0.0,
                fill_strength=0.0,
            ),
        )

        reversed_steps = [step for step in pattern.steps if "reverse" in step.tags]

        self.assertTrue(reversed_steps)
        self.assertTrue(all(step.label != "silence" for step in reversed_steps))

    def test_reverse_effect_lands_on_subdivisions_after_kick_or_snare(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
            TransientHit(4, 0.375, 0.43, "perc", 0.75, -4.0, 0.1, 0.4, 0.5),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=912,
                reverse_density=1.0,
                sequence_density=0.0,
                repeat_density=0.0,
                fill_strength=0.0,
                kick_weight=0.0,
                snare_weight=0.0,
                ghost_density=0.0,
            ),
            anchors={1: "kick", 5: "snare", 9: "kick", 13: "snare"},
        )

        reversed_steps = [step for step in pattern.steps if "reverse" in step.tags]

        self.assertTrue(reversed_steps)
        for step in reversed_steps:
            local_step = ((step.step_index - 1) % 16) + 1
            self.assertIn(local_step, {2, 4, 6, 8, 10, 12, 14, 16})
            self.assertIn("effect_reverse", step.tags)
            self.assertIn("reverse_transition", step.tags)
            previous = pattern.steps[step.step_index - 2]
            self.assertIn(previous.label, {"kick", "snare", "clap"})
            self.assertEqual(step.source_hit_index, previous.source_hit_index)
            self.assertEqual(step.source_start_s, previous.source_start_s)
            self.assertEqual(step.source_end_s, previous.source_end_s)

    def test_reverse_effect_does_not_appear_without_kick_or_snare_triggers(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.08, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8),
            TransientHit(2, 0.125, 0.18, "open_hat", 0.81, -4.0, 0.1, 0.2, 0.85),
            TransientHit(3, 0.25, 0.31, "ride", 0.76, -4.0, 0.1, 0.2, 0.75),
            TransientHit(4, 0.375, 0.44, "perc", 0.73, -5.0, 0.2, 0.4, 0.4),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=271,
                reverse_density=1.0,
                sequence_density=0.0,
                repeat_density=0.0,
                fill_strength=0.0,
                kick_weight=0.0,
                snare_weight=0.0,
                hat_density=1.0,
                ghost_density=0.0,
            ),
        )

        self.assertFalse(any("reverse" in step.tags for step in pattern.steps))

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

    def test_default_probability_preview_keeps_structural_silence_lower_on_pillars(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.91, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.84, -3.0, 0.1, 0.2, 0.82),
            TransientHit(4, 0.375, 0.48, "perc", 0.72, -5.0, 0.15, 0.45, 0.4),
        )

        preview = estimate_pattern_family_probabilities(hits, BreakPatternParams())

        self.assertLess(preview.rows["downbeat"]["silence"], 0.18)
        self.assertLess(preview.rows["backbeat"]["silence"], 0.2)
        self.assertLess(preview.rows["downbeat"]["silence"], preview.rows["downbeat"]["kick"])
        self.assertLess(preview.rows["backbeat"]["silence"], preview.rows["backbeat"]["snare"])

    def test_sequences_are_protected_from_late_repeat_and_stretch_fx(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar", rhythmic_position="downbeat"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.84, -3.0, 0.1, 0.2, 0.82, role="texture", rhythmic_position="subdivision"),
            TransientHit(3, 0.25, 0.37, "snare", 0.91, -2.0, 0.1, 0.7, 0.2, role="pillar", rhythmic_position="backbeat"),
            TransientHit(4, 0.375, 0.43, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill", rhythmic_position="offbeat"),
        )
        sequence = HitSequence(
            index=3,
            role="groove",
            hit_count=3,
            total_steps=4,
            source_start_s=0.0,
            source_end_s=0.37,
            start_step_hint=1,
            end_step_hint=4,
            labels=("kick", "snare", "closed_hat"),
            events=(
                HitSequenceEvent(0, 1, "kick", "pillar", 0, 0, 1.0, 0.0, 0.12, rhythmic_position="downbeat"),
                HitSequenceEvent(1, 3, "snare", "pillar", 2, 2, 1.0, 0.25, 0.37, rhythmic_position="offbeat"),
                HitSequenceEvent(2, 2, "closed_hat", "texture", 3, 1, 0.8, 0.125, 0.19, rhythmic_position="subdivision"),
            ),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=22,
                sequence_density=1.0,
                sequence_max_len=4,
                sequence_role_lock=True,
                repeat_density=1.0,
                snare_stretch_density=1.0,
                reverse_density=1.0,
                kick_roll_density=1.0,
            ),
            sequences=(sequence,),
        )

        sequence_steps = [step for step in pattern.steps if "sequence" in step.tags]
        self.assertTrue(sequence_steps)
        for step in sequence_steps:
            self.assertNotIn("repeat", step.tags)
            self.assertNotIn("snare_stretch", step.tags)
            self.assertNotIn("snare_stretch_tail", step.tags)
            self.assertNotIn("kick_roll", step.tags)
            self.assertNotIn("reverse", step.tags)

    def test_generated_pattern_exposes_break_quality_metrics(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(seed=123, fill_strength=0.4, repeat_density=0.2, bars=2),
        )

        self.assertIn("silence_ratio", pattern.metrics)
        self.assertIn("post_fx_ratio", pattern.metrics)
        self.assertIn("protected_ratio", pattern.metrics)
        self.assertGreaterEqual(pattern.metrics["silence_ratio"], 0.0)
        self.assertLessEqual(pattern.metrics["silence_ratio"], 1.0)
        self.assertGreaterEqual(pattern.metrics["post_fx_ratio"], 0.0)
        self.assertLessEqual(pattern.metrics["post_fx_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
