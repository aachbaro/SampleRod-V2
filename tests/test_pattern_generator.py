from __future__ import annotations

from dataclasses import replace
import unittest
import numpy as np

from prototypes.drum_detector.analyzer import HitSequence, HitSequenceEvent, TransientHit
from prototypes.drum_detector.pattern_generator import (
    BreakPatternParams,
    GeneratedPatternStep,
    StretchRetrigger,
    UserMotif,
    _bar_has_post_mutation_capacity,
    _post_generation_pipeline,
    _apply_pitch_movement,
    _build_pools,
    _build_hybrid_motif_anchors,
    _build_sequence_pools,
    _inject_ghost_notes,
    _pick_sequence_for_step,
    _pick_weighted_hit,
    _resolve_params,
    _select_ghost_step,
    apply_anchor_reapply,
    apply_fill_pass,
    estimate_pattern_effect_probabilities,
    estimate_pattern_family_probabilities,
    estimate_user_motif_effective_probability,
    generate_stretch_retriggers,
    generate_break_pattern,
    generate_break_pattern_debug,
    generate_break_pattern_hybrid,
    generate_break_skeleton_only,
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

    def test_generate_break_pattern_debug_returns_text_report(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        pattern, report = generate_break_pattern_debug(
            hits,
            BreakPatternParams(
                seed=123,
                hat_density=0.8,
                ghost_density=0.35,
                pitch_mode="random",
                pitch_amount=1.0,
                generation_profile="musical",
            ),
            target_bpm=170.0,
        )

        self.assertEqual(pattern.seed, 123)
        self.assertIn("=== BREAK GENERATION REPORT ===", report)
        self.assertIn("mode: Classic", report)
        self.assertIn("profile: Musical", report)
        self.assertIn("--- POOLS ---", report)
        self.assertIn("--- PASS IMPACT ---", report)
        self.assertIn("--- METRICS ---", report)
        self.assertIn("skeleton", report)

    def test_generate_break_pattern_debug_hybrid_logs_motif_block(self) -> None:
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

        _pattern, report = generate_break_pattern_debug(
            hits,
            BreakPatternParams(
                seed=77,
                motif_density=1.0,
                kick_weight=1.0,
                snare_weight=1.0,
                hat_density=0.8,
                ghost_density=0.0,
            ),
            use_hybrid=True,
            user_motifs=[motif],
            target_bpm=165.0,
        )

        self.assertIn("mode: Hybrid", report)
        self.assertIn("motif_block", report)

    def test_post_generation_pipeline_changes_with_generation_profile(self) -> None:
        self.assertEqual(
            _post_generation_pipeline("safe"),
            (
                "ghost_pass",
                "fill_pass",
                "resolution_pass",
                "kick_roll_pass",
                "repeat_pass",
                "snare_stretch_pass",
                "reverse_pass",
                "anchor_reapply",
            ),
        )
        self.assertEqual(_post_generation_pipeline("musical"), _post_generation_pipeline("safe"))
        self.assertEqual(
            _post_generation_pipeline("destructive"),
            (
                "ghost_pass",
                "fill_pass",
                "resolution_pass",
                "kick_roll_pass",
                "repeat_pass",
                "anchor_reapply",
                "snare_stretch_pass",
                "reverse_pass",
            ),
        )

    def test_skeleton_keeps_primary_pillars_but_secondary_support_varies(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        saw_secondary_kick = False
        saw_secondary_kick_exception = False
        saw_secondary_snare = False
        saw_secondary_snare_exception = False

        for seed in range(1, 17):
            state = generate_break_skeleton_only(
                hits,
                None,
                BreakPatternParams(
                    seed=seed,
                    bars=1,
                    sequence_density=0.0,
                    fill_strength=0.0,
                    kick_weight=0.7,
                    snare_weight=0.8,
                    hat_density=1.0,
                    ghost_density=0.0,
                    anti_repeat=0.75,
                    breath_factor=0.55,
                ),
            )

            labels = [step.label for step in state.current.steps[:16]]
            self.assertEqual(labels[0], "kick")
            self.assertIn(labels[4], {"snare", "clap", "snare_ruff"})

            if labels[8] == "kick":
                saw_secondary_kick = True
            else:
                saw_secondary_kick_exception = True

            if labels[12] in {"snare", "clap", "snare_ruff"}:
                saw_secondary_snare = True
            else:
                saw_secondary_snare_exception = True

        self.assertTrue(saw_secondary_kick)
        self.assertTrue(saw_secondary_kick_exception)
        self.assertTrue(saw_secondary_snare)
        self.assertTrue(saw_secondary_snare_exception)

    def test_snare_stretch_zone_budget_counts_as_single_post_mutation(self) -> None:
        params = _resolve_params(
            BreakPatternParams(
                generation_profile="musical",
                snare_stretch_density=1.0,
                fill_strength=0.0,
                repeat_density=0.0,
                reverse_density=0.0,
                kick_roll_density=0.0,
            )
        )
        steps = [
            GeneratedPatternStep(
                step_index=index,
                label="closed_hat" if index % 2 == 0 else "silence",
                velocity=72 if index % 2 == 0 else 0,
                source_hit_index=None,
                source_label=None,
                source_start_s=None,
                source_end_s=None,
                tags=("snare_stretch_tail",) if index in {13, 14, 15} else (),
            )
            for index in range(1, 17)
        ]

        self.assertFalse(
            _bar_has_post_mutation_capacity(
                steps,
                bar_start=1,
                bar_end=16,
                target_step_indices=range(13, 17),
                params=params,
            )
        )
        self.assertTrue(
            _bar_has_post_mutation_capacity(
                steps,
                bar_start=1,
                bar_end=16,
                target_step_indices=range(13, 17),
                params=params,
                planned_post_cost=1,
                planned_tail_cost=1,
            )
        )

    def test_generate_stretch_retriggers_accelerates_inside_requested_zone(self) -> None:
        retriggers = generate_stretch_retriggers(
            start_step=5,
            span_steps=4,
            ticks_per_step=96,
            amount=1.0,
            velocity_start=100.0,
            velocity_end=32.0,
        )

        self.assertGreaterEqual(len(retriggers), 3)
        self.assertEqual(retriggers[0].offset_ticks, 0)
        self.assertTrue(all(retriggers[index].offset_ticks < retriggers[index + 1].offset_ticks for index in range(len(retriggers) - 1)))
        intervals = [retriggers[index + 1].offset_ticks - retriggers[index].offset_ticks for index in range(len(retriggers) - 1)]
        self.assertTrue(all(intervals[index] >= intervals[index + 1] for index in range(len(intervals) - 1)))
        self.assertTrue(all(5 <= retrigger.step_index <= 8 for retrigger in retriggers))
        self.assertGreater(retriggers[0].velocity, retriggers[-1].velocity)

    def test_generate_break_skeleton_only_returns_pipeline_state(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        state = generate_break_skeleton_only(
            list(hits),
            None,
            BreakPatternParams(seed=91, sequence_density=0.0, motif_density=0.0),
        )

        self.assertEqual(state.current.seed, 91)
        self.assertEqual(state.current.step_count, 16)
        self.assertEqual(state.last_snapshot_name(), "skeleton")
        self.assertTrue(state.snapshots)

    def test_apply_anchor_reapply_returns_new_pattern_without_mutating_input(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )
        state = generate_break_skeleton_only(
            list(hits),
            None,
            BreakPatternParams(seed=34, sequence_density=0.0),
            anchors={1: "kick"},
        )
        original_pattern = state.current
        broken_first_step = replace(
            original_pattern.steps[0],
            label="silence",
            velocity=0,
            source_hit_index=None,
            source_label=None,
            source_start_s=None,
            source_end_s=None,
            tags=(),
        )
        broken_pattern = replace(
            original_pattern,
            steps=(broken_first_step, *original_pattern.steps[1:]),
        )

        repaired = apply_anchor_reapply(
            broken_pattern,
            list(hits),
            BreakPatternParams(seed=34),
            anchors={1: "kick"},
        )

        self.assertEqual(broken_pattern.steps[0].label, "silence")
        self.assertNotEqual(repaired.steps[0].label, "silence")
        self.assertEqual(original_pattern.steps[0].label, "kick")

    def test_pipeline_state_rollback_restores_previous_pattern_and_log(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )
        state = generate_break_skeleton_only(
            list(hits),
            None,
            BreakPatternParams(seed=56, sequence_density=0.0),
            anchors={1: "kick"},
        )
        broken_first_step = replace(
            state.current.steps[0],
            label="silence",
            velocity=0,
            source_hit_index=None,
            source_label=None,
            source_start_s=None,
            source_end_s=None,
            tags=(),
        )
        broken_pattern = replace(
            state.current,
            steps=(broken_first_step, *state.current.steps[1:]),
        )
        state.current = broken_pattern
        state.snapshot("anchor_reapply")
        state.current = apply_anchor_reapply(
            state.current,
            list(state.hits),
            state.params,
            log=state.log,
            anchors={1: "kick"},
        )

        self.assertIn("anchor_reapply", state.log.report())
        self.assertTrue(state.rollback_to("anchor_reapply"))
        self.assertEqual(state.current.to_dict(), broken_pattern.to_dict())
        self.assertNotIn("anchor_reapply", state.log.report())

    def test_generate_break_pattern_respects_enabled_velocity_and_pitch_passes(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "closed_hat", 0.8, -3.0, 0.1, 0.2, 0.8),
        )

        pattern = generate_break_pattern(
            hits,
            BreakPatternParams(
                seed=1234,
                pitch_mode="random",
                pitch_amount=1.0,
                enabled_passes=("ghost_pass", "fill_pass", "resolution_pass", "anchor_reapply"),
            ),
        )

        audible_steps = [step for step in pattern.steps if step.label != "silence"]
        self.assertTrue(audible_steps)
        self.assertTrue(all(step.velocity == 0 for step in audible_steps))
        self.assertTrue(all(abs(float(step.pitch_shift)) <= 1e-6 for step in pattern.steps))

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

    def test_inject_ghost_notes_builds_synthetic_ghosts_from_snare_pool_when_needed(self) -> None:
        hits = (
            TransientHit(1, 0.20, 0.34, "snare", 0.88, -2.0, 0.1, 0.75, 0.15),
            TransientHit(2, 0.48, 0.58, "closed_hat", 0.75, -3.0, 0.05, 0.2, 0.82),
        )
        pools = _build_pools(hits)
        params = _resolve_params(
            BreakPatternParams(
                ghost_density=1.0,
                synth_ghost_enabled=True,
                ghost_vel_range=(0.35, 0.35),
                ghost_pitch_range=(0.5, 0.5),
                ghost_gate_ratio=0.4,
            )
        )
        steps = [
            GeneratedPatternStep(index, "silence", 0, None, None, None, None, (f"step_{index}",))
            for index in range(1, 9)
        ]
        steps[4] = GeneratedPatternStep(
            5,
            "snare",
            0,
            hits[0].index,
            hits[0].label,
            hits[0].start_s,
            hits[0].end_s,
            ("step_5",),
        )

        _inject_ghost_notes(steps, pools, params, np.random.default_rng(0))

        synthetic_ghosts = [step for step in steps if step.is_synthetic_ghost]
        self.assertTrue(synthetic_ghosts)
        self.assertTrue(all(step.label == "snare_ghost" for step in synthetic_ghosts))
        self.assertTrue(all(step.source_label in {"snare", "clap", "snare_ruff"} for step in synthetic_ghosts))
        self.assertTrue(all(abs(step.ghost_vel_ratio - 0.35) <= 1e-6 for step in synthetic_ghosts))
        self.assertTrue(all(abs(step.ghost_pitch_offset - 0.5) <= 1e-6 for step in synthetic_ghosts))
        self.assertTrue(all(abs(step.ghost_gate_ratio - 0.4) <= 1e-6 for step in synthetic_ghosts))
        self.assertTrue(all("synthetic_ghost" in step.tags for step in synthetic_ghosts))

    def test_select_ghost_step_prefers_real_ghost_until_pool_capacity_is_exhausted(self) -> None:
        hits = (
            TransientHit(1, 0.10, 0.20, "snare_ghost", 0.82, -4.0, 0.05, 0.7, 0.25),
            TransientHit(2, 0.28, 0.42, "snare", 0.9, -2.0, 0.1, 0.72, 0.18),
        )
        pools = _build_pools(hits)
        params = _resolve_params(
            BreakPatternParams(
                ghost_density=1.0,
                synth_ghost_enabled=True,
                ghost_vel_range=(0.3, 0.3),
                ghost_pitch_range=(0.0, 0.0),
                ghost_gate_ratio=0.25,
            )
        )
        rng = np.random.default_rng(3)

        first = _select_ghost_step(3, [], pools, params, rng, tags=("step_3", "ghost"))
        second = _select_ghost_step(7, [first], pools, params, rng, tags=("step_7", "ghost"))

        self.assertFalse(first.is_synthetic_ghost)
        self.assertEqual(first.source_label, "snare_ghost")
        self.assertTrue(second.is_synthetic_ghost)
        self.assertEqual(second.source_label, "snare")

    def test_select_ghost_step_keeps_non_synthetic_fallback_when_synth_is_disabled(self) -> None:
        hits = (
            TransientHit(1, 0.20, 0.34, "snare", 0.88, -2.0, 0.1, 0.75, 0.15),
        )
        pools = _build_pools(hits)
        params = _resolve_params(
            BreakPatternParams(
                ghost_density=1.0,
                synth_ghost_enabled=False,
                ghost_vel_range=(0.25, 0.25),
                ghost_pitch_range=(0.6, 0.6),
                ghost_gate_ratio=0.4,
            )
        )

        ghost_step = _select_ghost_step(3, [], pools, params, np.random.default_rng(11), tags=("step_3", "ghost"))

        self.assertEqual(ghost_step.label, "snare_ghost")
        self.assertFalse(ghost_step.is_synthetic_ghost)
        self.assertAlmostEqual(ghost_step.ghost_vel_ratio, 1.0, places=6)
        self.assertAlmostEqual(ghost_step.ghost_pitch_offset, 0.0, places=6)
        self.assertAlmostEqual(ghost_step.ghost_gate_ratio, 0.0, places=6)

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

    def test_random_pitch_targets_only_selected_scope(self) -> None:
        steps = [
            GeneratedPatternStep(
                step_index=1,
                label="kick",
                velocity=96,
                source_hit_index=1,
                source_label="kick",
                source_start_s=0.0,
                source_end_s=0.12,
                tags=("downbeat",),
            ),
            GeneratedPatternStep(
                step_index=5,
                label="snare",
                velocity=94,
                source_hit_index=2,
                source_label="snare",
                source_start_s=0.2,
                source_end_s=0.32,
                tags=("backbeat",),
            ),
            GeneratedPatternStep(
                step_index=9,
                label="clap",
                velocity=88,
                source_hit_index=3,
                source_label="clap",
                source_start_s=0.4,
                source_end_s=0.5,
                tags=("downbeat",),
            ),
            GeneratedPatternStep(
                step_index=13,
                label="snare_ruff",
                velocity=76,
                source_hit_index=4,
                source_label="snare_ruff",
                source_start_s=0.6,
                source_end_s=0.68,
                tags=("backbeat",),
            ),
        ]
        params = _resolve_params(
            BreakPatternParams(
                pitch_mode="random",
                pitch_scope="snare",
                pitch_scale="chromatic",
                pitch_range=(6.0, 6.0),
                pitch_amount=1.0,
            )
        )

        pitched = _apply_pitch_movement(steps, params, seed=42)

        self.assertEqual([step.pitch_shift for step in pitched], [0.0, 6.0, 0.0, 6.0])

    def test_sequence_pitch_loops_over_target_hits(self) -> None:
        steps = [
            GeneratedPatternStep(
                step_index=1,
                label="snare",
                velocity=92,
                source_hit_index=1,
                source_label="snare",
                source_start_s=0.0,
                source_end_s=0.12,
                tags=("downbeat",),
            ),
            GeneratedPatternStep(
                step_index=5,
                label="snare",
                velocity=92,
                source_hit_index=2,
                source_label="snare",
                source_start_s=0.2,
                source_end_s=0.32,
                tags=("backbeat",),
            ),
            GeneratedPatternStep(
                step_index=9,
                label="snare",
                velocity=92,
                source_hit_index=3,
                source_label="snare",
                source_start_s=0.4,
                source_end_s=0.52,
                tags=("downbeat",),
            ),
            GeneratedPatternStep(
                step_index=13,
                label="snare",
                velocity=92,
                source_hit_index=4,
                source_label="snare",
                source_start_s=0.6,
                source_end_s=0.72,
                tags=("backbeat",),
            ),
        ]
        params = _resolve_params(
            BreakPatternParams(
                pitch_mode="sequence",
                pitch_scope="snare",
                pitch_sequence=[0.0, 3.0, -2.0],
                pitch_rate="every_hit",
                pitch_amount=1.0,
            )
        )

        pitched = _apply_pitch_movement(steps, params, seed=7)

        self.assertEqual([step.pitch_shift for step in pitched], [0.0, 3.0, -2.0, 0.0])

    def test_curve_pitch_quantizes_to_scale_and_respects_amount(self) -> None:
        steps = [
            GeneratedPatternStep(
                step_index=13,
                label="snare",
                velocity=88,
                source_hit_index=1,
                source_label="snare",
                source_start_s=0.5,
                source_end_s=0.6,
                tags=("backbeat", "fill"),
            ),
            GeneratedPatternStep(
                step_index=14,
                label="clap",
                velocity=84,
                source_hit_index=2,
                source_label="clap",
                source_start_s=0.62,
                source_end_s=0.7,
                tags=("subdivision", "fill"),
            ),
            GeneratedPatternStep(
                step_index=15,
                label="snare",
                velocity=84,
                source_hit_index=3,
                source_label="snare",
                source_start_s=0.72,
                source_end_s=0.8,
                tags=("offbeat", "fill"),
            ),
            GeneratedPatternStep(
                step_index=16,
                label="snare_ruff",
                velocity=78,
                source_hit_index=4,
                source_label="snare_ruff",
                source_start_s=0.82,
                source_end_s=0.9,
                tags=("subdivision", "fill"),
            ),
        ]
        params = _resolve_params(
            BreakPatternParams(
                pitch_mode="curve",
                pitch_scope="snare+clap",
                pitch_scale="minor",
                pitch_root=0,
                pitch_curve="up",
                pitch_curve_range=(-4.0, 4.0),
                pitch_amount=0.5,
            )
        )

        pitched = _apply_pitch_movement(steps, params, seed=99)

        self.assertEqual([step.pitch_shift for step in pitched], [-2.0, -1.0, 1.0, 1.5])

    def test_effect_probability_preview_includes_pitch_column(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.92, -1.0, 0.8, 0.1, 0.1),
            TransientHit(2, 0.25, 0.37, "snare", 0.84, -2.0, 0.1, 0.7, 0.2),
            TransientHit(3, 0.125, 0.19, "clap", 0.8, -3.0, 0.1, 0.5, 0.4),
        )

        preview = estimate_pattern_effect_probabilities(
            hits,
            BreakPatternParams(
                pitch_mode="random",
                pitch_scope="snare+clap",
                pitch_scale="minor",
                pitch_root=0,
                pitch_range=(-7.0, 7.0),
                pitch_amount=1.0,
            ),
        )

        self.assertIn("pitch", preview.rows["backbeat"])
        self.assertGreater(preview.rows["backbeat"]["pitch"], 0.0)

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
        )

        stretched_steps = [step for step in pattern.steps if "snare_stretch" in step.tags]
        zone_steps = [step for step in pattern.steps if "snare_stretch_zone" in step.tags]

        self.assertTrue(stretched_steps)
        self.assertTrue(zone_steps)
        self.assertTrue(all("effect_snare_stretch" in step.tags for step in stretched_steps))
        self.assertTrue(all(step.label in {"snare", "clap", "snare_ruff"} for step in stretched_steps))
        self.assertTrue(all("snare_stretch_zone_start" in step.tags for step in stretched_steps))
        self.assertTrue(all(any(str(tag).startswith("snare_stretch_zone_span_") for tag in step.tags) for step in stretched_steps))
        self.assertTrue(all(step.stretch_retriggers for step in zone_steps))
        self.assertTrue(all(any(retrigger.slice_source is not None for retrigger in step.stretch_retriggers) for step in stretched_steps))
        self.assertTrue(all(zone_step.label == "silence" for zone_step in zone_steps if "snare_stretch_tail" in zone_step.tags))
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

    def test_low_breath_uses_non_silence_fallbacks_when_primary_families_are_unavailable(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.11, "closed_hat", 0.9, -3.0, 0.08, 0.18, 0.82),
            TransientHit(2, 0.125, 0.22, "perc", 0.82, -4.0, 0.16, 0.42, 0.38),
        )

        for seed in range(1, 13):
            state = generate_break_skeleton_only(
                hits,
                None,
                BreakPatternParams(
                    seed=seed,
                    bars=1,
                    kick_weight=0.0,
                    snare_weight=0.0,
                    hat_density=1.0,
                    ghost_density=0.0,
                    fill_strength=0.0,
                    breath_factor=0.0,
                    sequence_density=0.0,
                ),
            )

            labels = [step.label for step in state.current.steps[:16]]
            self.assertNotEqual(labels[0], "silence")
            self.assertNotEqual(labels[4], "silence")

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

    def test_high_sequence_density_prefers_exact_sequence_start_hint(self) -> None:
        early_sequence = HitSequence(
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
        late_downbeat_sequence = HitSequence(
            index=2,
            role="groove",
            hit_count=2,
            total_steps=2,
            source_start_s=0.5,
            source_end_s=0.69,
            start_step_hint=9,
            end_step_hint=10,
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
                    0.5,
                    0.58,
                    rhythmic_position="downbeat",
                ),
                HitSequenceEvent(
                    2,
                    6,
                    "closed_hat",
                    "texture",
                    1,
                    1,
                    0.75,
                    0.625,
                    0.69,
                    rhythmic_position="subdivision",
                ),
            ),
        )
        params = _resolve_params(
            BreakPatternParams(
                sequence_density=1.0,
                sequence_max_len=2,
                sequence_role_lock=True,
                position_fidelity=0.0,
            )
        )
        sequence_pools = _build_sequence_pools((early_sequence, late_downbeat_sequence), max_hit_count=2)
        pools = _build_pools(())

        selected_indices: list[int] = []
        for seed in range(64):
            rng = np.random.default_rng(seed)
            selected = _pick_sequence_for_step(1, [], sequence_pools, pools, params, rng)
            self.assertIsNotNone(selected)
            selected_indices.append(int(selected.index))

        self.assertGreater(selected_indices.count(1), selected_indices.count(2) * 6)

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
            self.assertEqual(pattern.steps[16].label, "kick")
            self.assertIn("resolution", pattern.steps[16].tags)

        self.assertGreaterEqual(resolved_cases, 3)

    def test_skeleton_reserves_fill_zone_before_fill_pass(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8, role="texture"),
            TransientHit(3, 0.25, 0.37, "snare", 0.9, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(4, 0.312, 0.35, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill"),
        )

        state = generate_break_skeleton_only(
            hits,
            None,
            BreakPatternParams(seed=11, fill_strength=1.0, fill_type_weights={"ruff": 1.0}),
        )

        self.assertTrue(state.current.fill_decisions)
        decision = state.current.fill_decisions[0]
        self.assertTrue(decision.active)
        self.assertEqual(decision.fill_type, "ruff")
        reserved_steps = state.current.steps[decision.zone_start - 1 : decision.zone_end]
        self.assertTrue(reserved_steps)
        self.assertTrue(all("fill_reserved_zone" in step.tags for step in reserved_steps))
        self.assertTrue(all(step.label == "silence" for step in reserved_steps))

    def test_fill_pass_respects_forced_fill_type(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8, role="texture"),
            TransientHit(3, 0.25, 0.37, "snare", 0.9, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(4, 0.312, 0.35, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill"),
        )
        params = BreakPatternParams(seed=17, fill_strength=1.0, fill_type_weights={"ruff": 1.0})
        state = generate_break_skeleton_only(hits, None, params)

        filled = apply_fill_pass(state.current, list(hits), params)
        decision = filled.fill_decisions[0]
        zone_steps = filled.steps[decision.zone_start - 1 : decision.zone_end]

        self.assertTrue(any("fill_style_ruff" in step.tags for step in zone_steps))
        self.assertTrue(any(step.label in {"snare", "snare_ruff", "clap"} for step in zone_steps))

    def test_fill_sequence_becomes_reserved_zone_source(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar", rhythmic_position="downbeat"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8, role="texture", rhythmic_position="subdivision"),
            TransientHit(3, 0.25, 0.37, "snare", 0.9, -2.0, 0.1, 0.7, 0.2, role="pillar", rhythmic_position="backbeat"),
            TransientHit(4, 0.312, 0.35, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill", rhythmic_position="offbeat"),
        )
        fill_sequence = HitSequence(
            index=99,
            role="fill",
            hit_count=2,
            total_steps=2,
            source_start_s=0.25,
            source_end_s=0.35,
            start_step_hint=15,
            end_step_hint=16,
            labels=("snare_ruff", "closed_hat"),
            events=(
                HitSequenceEvent(0, 4, "snare_ruff", "fill", 0, 0, 1.0, 0.312, 0.35, rhythmic_position="offbeat"),
                HitSequenceEvent(1, 2, "closed_hat", "texture", 1, 1, 0.78, 0.125, 0.19, rhythmic_position="subdivision"),
            ),
        )

        state = generate_break_skeleton_only(
            hits,
            (fill_sequence,),
            BreakPatternParams(seed=23, fill_strength=1.0, fill_type_weights={"ghost_hat": 1.0}),
        )

        decision = state.current.fill_decisions[0]
        self.assertTrue(decision.active)
        self.assertEqual(decision.source, "sequence")
        zone_steps = state.current.steps[decision.zone_start - 1 : decision.zone_end]
        self.assertTrue(any("sequence" in step.tags for step in zone_steps))

    def test_fill_debug_report_lists_decision_per_bar(self) -> None:
        hits = (
            TransientHit(1, 0.0, 0.12, "kick", 0.95, -1.0, 0.8, 0.1, 0.1, role="pillar"),
            TransientHit(2, 0.125, 0.19, "closed_hat", 0.88, -3.0, 0.1, 0.2, 0.8, role="texture"),
            TransientHit(3, 0.25, 0.37, "snare", 0.9, -2.0, 0.1, 0.7, 0.2, role="pillar"),
            TransientHit(4, 0.312, 0.35, "snare_ruff", 0.82, -4.0, 0.15, 0.65, 0.2, role="fill"),
        )

        _pattern, report = generate_break_pattern_debug(
            hits,
            BreakPatternParams(seed=29, fill_strength=1.0, bars=2, fill_type_weights={"dense": 1.0}),
        )

        self.assertIn("fill:", report)
        self.assertRegex(report, r"fill: [a-z_]+ \| zone: \d+-16 \| source: (generated|sequence)")

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
