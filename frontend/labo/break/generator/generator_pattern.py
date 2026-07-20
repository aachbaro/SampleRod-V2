# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la logique metier du generateur de break hors playback/rendu.
# - Isole les parametres, la generation de pattern et la projection dans
#   le tableau Qt.
#
# LIENS CLES
# - backend/services/drum_analysis_service.py : generation de pattern.
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import replace
import os
import uuid
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidgetItem

from .generator_constants import (
    GENERATOR_MODE_CLASSIC,
    GENERATOR_MODE_HYBRID,
    GENERATOR_STEP_ANCHOR_LABELS,
    GENERATOR_STEP_ANCHOR_ORDER,
    GENERATOR_STEP_ANCHOR_SHORT_LABELS,
    STEP_COLORS,
    STEP_SHORT_LABELS,
)

_PATTERN_ROW_ANCHOR = 0
_PATTERN_ROW_LOCK = 1
_PATTERN_ROW_EVENT = 2
_PATTERN_ROW_VEL = 3
_PATTERN_ROW_SRC = 4
_PATTERN_ROW_FX = 5


class BreakGeneratorPatternController:
    """Gere generation, params et table du generateur de break."""

    def __init__(self, widget):
        self.widget = widget

    def set_analysis_result(self, result) -> None:
        self.widget._analysis_result = result
        self.widget._generated_pattern = None
        self.widget._pattern_dirty = False
        self.widget._generation_busy = False
        self.widget._render_busy = False
        self.widget._render_request_mode = None
        self.widget._pattern_step_anchors.clear()
        self.widget._pattern_locked_steps.clear()
        self.widget._pattern_loop_range = None
        self.widget._pattern_loop_anchor_step = None
        self.widget._preview_request = None
        self.widget._clear_preview_cache(stop_if_playing=True)
        self.widget.seed_value.setText("auto")
        if result is not None and float(result.tempo_bpm or 0.0) > 1.0:
            self.widget.target_bpm_spin.blockSignals(True)
            self.widget.target_bpm_spin.setValue(float(result.tempo_bpm))
            self.widget.target_bpm_spin.blockSignals(False)
        self._populate_pattern_table(None)
        self._refresh_actions()

    def clear_state(self) -> None:
        self.set_analysis_result(None)
        self.widget._clear_preview_cache(stop_if_playing=True)

    def _generate_pattern(self) -> None:
        if self.widget._analysis_result is None:
            self.widget.statusChanged.emit("Analyse les hits avant de generer un break.")
            return
        if self.widget._generation_busy:
            return
        target_step_count = max(16, int(self.widget.bars_spin.value()) * 16)
        self.widget._service.create_break_pattern(
            self.widget._analysis_result,
            self._pattern_params_payload(),
            target_bpm=float(self.widget.target_bpm_spin.value()),
            use_hybrid=str(self.widget.mode_combo.currentData() or GENERATOR_MODE_CLASSIC)
            == GENERATOR_MODE_HYBRID,
            anchors=self._active_pattern_anchors(step_count=target_step_count),
        )

    def _pattern_params_payload(self) -> dict[str, Any]:
        fill_style = str(self.widget.fill_style_combo.currentData() or "auto")
        fill_type_weights = None if fill_style == "auto" else {fill_style: 1.0}
        ghost_vel_min = min(
            float(self.widget.ghost_vel_min_spin.value()),
            float(self.widget.ghost_vel_max_spin.value()),
        )
        ghost_vel_max = max(
            float(self.widget.ghost_vel_min_spin.value()),
            float(self.widget.ghost_vel_max_spin.value()),
        )
        ghost_pitch_min = min(
            float(self.widget.ghost_pitch_min_spin.value()),
            float(self.widget.ghost_pitch_max_spin.value()),
        )
        ghost_pitch_max = max(
            float(self.widget.ghost_pitch_min_spin.value()),
            float(self.widget.ghost_pitch_max_spin.value()),
        )
        pitch_range_min = min(
            float(self.widget.pitch_range_min_spin.value()),
            float(self.widget.pitch_range_max_spin.value()),
        )
        pitch_range_max = max(
            float(self.widget.pitch_range_min_spin.value()),
            float(self.widget.pitch_range_max_spin.value()),
        )
        pitch_curve_min = min(
            float(self.widget.pitch_curve_min_spin.value()),
            float(self.widget.pitch_curve_max_spin.value()),
        )
        pitch_curve_max = max(
            float(self.widget.pitch_curve_min_spin.value()),
            float(self.widget.pitch_curve_max_spin.value()),
        )
        return {
            "energy": self.widget.energy_slider.value() / 100.0,
            "kick_weight": self.widget.kick_slider.value() / 100.0,
            "snare_weight": self.widget.snare_slider.value() / 100.0,
            "hat_density": self.widget.hat_slider.value() / 100.0,
            "ghost_density": self.widget.ghost_slider.value() / 100.0,
            "synth_ghost_enabled": bool(self.widget.synth_ghost_check.isChecked()),
            "ghost_vel_range": (ghost_vel_min, ghost_vel_max),
            "ghost_pitch_range": (ghost_pitch_min, ghost_pitch_max),
            "ghost_gate_ratio": self.widget.ghost_gate_slider.value() / 100.0,
            "fill_strength": self.widget.fill_slider.value() / 100.0,
            "fill_type_weights": fill_type_weights,
            "repeat_density": self.widget.repeat_density_slider.value() / 100.0,
            "repeat_span": self.widget.repeat_span_slider.value() / 100.0,
            "repeat_rate": self.widget.repeat_rate_slider.value() / 100.0,
            "reverse_density": self.widget.reverse_slider.value() / 100.0,
            "kick_roll_density": self.widget.kick_roll_density_slider.value() / 100.0,
            "kick_roll_span": self.widget.kick_roll_span_slider.value() / 100.0,
            "kick_roll_contrast": self.widget.kick_roll_contrast_slider.value() / 100.0,
            "snare_stretch_density": self.widget.snare_stretch_density_slider.value() / 100.0,
            "snare_stretch_span": self.widget.snare_stretch_span_slider.value() / 100.0,
            "snare_stretch_amount": self.widget.snare_stretch_amount_slider.value() / 100.0,
            "snare_stretch_vel_curve": str(
                self.widget.snare_stretch_curve_combo.currentData() or "decay"
            ),
            "pitch_mode": str(self.widget.pitch_mode_combo.currentData() or "off"),
            "pitch_scope": str(self.widget.pitch_scope_combo.currentData() or "snare"),
            "pitch_scale": str(self.widget.pitch_scale_combo.currentData() or "chromatic"),
            "pitch_root": int(self.widget.pitch_root_combo.currentData() or 0),
            "pitch_range": (pitch_range_min, pitch_range_max),
            "pitch_sequence": self._parse_pitch_sequence(),
            "pitch_curve": str(self.widget.pitch_curve_combo.currentData() or "up"),
            "pitch_curve_range": (pitch_curve_min, pitch_curve_max),
            "pitch_rate": str(self.widget.pitch_rate_combo.currentData() or "every_hit"),
            "pitch_amount": self.widget.pitch_amount_slider.value() / 100.0,
            "gate": max(0.05, self.widget.gate_slider.value() / 100.0),
            "mono_choke": bool(self.widget.mono_choke_check.isChecked()),
            "velocity_spread": self.widget.velocity_slider.value() / 100.0,
            "swing": self.widget.swing_slider.value() / 100.0,
            "anti_repeat": self.widget.anti_repeat_slider.value() / 100.0,
            "breath_factor": self.widget.breath_slider.value() / 100.0,
            "position_fidelity": self.widget.position_slider.value() / 100.0,
            "sequence_density": self.widget.sequence_density_slider.value() / 100.0,
            "sequence_max_len": int(self.widget.sequence_max_len_spin.value()),
            "sequence_role_lock": bool(self.widget.sequence_role_lock_check.isChecked()),
            "motif_density": self.widget.motif_density_slider.value() / 100.0,
            "user_motifs": self.widget._collect_user_motifs_payload(),
            "generation_profile": str(self.widget.profile_combo.currentData() or "musical"),
            "seed": int(uuid.uuid4().int % 999_999_999) + 1,
            "bars": int(self.widget.bars_spin.value()),
        }

    def _parse_pitch_sequence(self) -> list[float]:
        text = str(self.widget.pitch_sequence_input.text() or "").replace(";", ",")
        values: list[float] = []
        for chunk in text.split(","):
            token = chunk.strip()
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                continue
        return values or [0.0, 3.0, -2.0, 7.0]

    def _mark_pattern_dirty(self, *_args) -> None:
        self.widget._clear_preview_cache(stop_if_playing=False)
        if self.widget._generated_pattern is not None:
            self.widget._pattern_dirty = True
        self._refresh_actions()

    def _on_pattern_generation_started(self, source_path: str) -> None:
        if not self._matches_path(source_path):
            return
        self.widget._generation_busy = True
        self._refresh_actions()
        self.widget.statusChanged.emit("Generation du pattern en cours...")

    def _on_pattern_generated(self, payload) -> None:
        if not self._matches_path(payload.source_path):
            return
        previous_pattern = self.widget._generated_pattern
        merged_pattern = self._merge_locked_generated_steps(payload.pattern, previous_pattern)
        self.widget._generation_busy = False
        self.widget._generated_pattern = merged_pattern
        self.widget._pattern_dirty = False
        self.widget.seed_value.setText(str(int(getattr(merged_pattern, "seed", 0) or 0)))
        self._populate_pattern_table(merged_pattern)
        self._refresh_actions()
        event_count = int(getattr(merged_pattern, "event_count", 0) or 0)
        bars = int(
            getattr(merged_pattern, "bars", self.widget.bars_spin.value())
            or self.widget.bars_spin.value()
        )
        self.widget.statusChanged.emit(
            f"Pattern genere: {event_count} evenement(s) sur {bars} bar(s)."
        )

    def _on_pattern_generation_failed(self, source_path: str, message: str) -> None:
        if source_path and not self._matches_path(source_path):
            return
        self.widget._generation_busy = False
        self._refresh_actions()
        self.widget.statusChanged.emit(f"Generation impossible: {message}")

    def _populate_pattern_table(self, pattern: Any) -> None:
        step_count = max(
            16,
            int(
                getattr(pattern, "step_count", self.widget.bars_spin.value() * 16)
                or self.widget.bars_spin.value() * 16
            ),
        )
        self._sanitize_pattern_state(step_count)

        table = self.widget.pattern_table
        table.clearContents()
        table.setColumnCount(step_count)
        table.setHorizontalHeaderLabels([str(i) for i in range(1, step_count + 1)])
        for column in range(step_count):
            table.setColumnWidth(column, 60)
        table.setRowCount(6)
        table.setVerticalHeaderLabels(("Anchor", "Lock", "Event", "Vel", "Src", "FX"))
        table.setRowHeight(_PATTERN_ROW_ANCHOR, 34)
        table.setRowHeight(_PATTERN_ROW_LOCK, 34)
        table.setRowHeight(_PATTERN_ROW_EVENT, 34)
        table.setRowHeight(_PATTERN_ROW_VEL, 28)
        table.setRowHeight(_PATTERN_ROW_SRC, 28)
        table.setRowHeight(_PATTERN_ROW_FX, 40)

        steps = list(getattr(pattern, "steps", ()) or ()) if pattern is not None else []
        for column in range(step_count):
            step_index = column + 1
            table.setCellWidget(_PATTERN_ROW_ANCHOR, column, self._build_anchor_button(step_index))
            table.setCellWidget(_PATTERN_ROW_LOCK, column, self._build_lock_button(step_index))
            step = steps[column] if column < len(steps) else None
            if step is None:
                values = ("-", "-", "-", "-")
            else:
                values = (
                    self._step_label(step),
                    "-"
                    if getattr(step, "label", "silence") == "silence"
                    else str(int(getattr(step, "velocity", 0) or 0)),
                    "-"
                    if getattr(step, "source_hit_index", None) is None
                    else str(int(getattr(step, "source_hit_index", 0) or 0)),
                    self._step_fx_text(step),
                )
            for row_offset, value in enumerate(values, start=2):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_offset, column, item)

        if pattern is None:
            self.widget.pattern_summary.setText("Aucun pattern genere.")
            self._refresh_pattern_visual_state(pattern)
            self._refresh_pattern_interaction_label(step_count=step_count)
            return

        seed = int(getattr(pattern, "seed", 0) or 0)
        bars = int(
            getattr(pattern, "bars", self.widget.bars_spin.value())
            or self.widget.bars_spin.value()
        )
        event_count = int(getattr(pattern, "event_count", 0) or 0)
        self.widget.pattern_summary.setText(
            f"{event_count} evenement(s) sur {bars} bar(s), {step_count} steps, "
            f"seed {seed}, preview a {self.widget.target_bpm_spin.value():.1f} BPM."
        )
        self._refresh_pattern_visual_state(pattern)
        self._refresh_pattern_interaction_label(step_count=step_count)

    def _step_label(self, step: Any) -> str:
        label = str(getattr(step, "label", "silence") or "silence")
        return STEP_SHORT_LABELS.get(label, label[:3].title())

    def _step_fx_text(self, step: Any) -> str:
        tags = {str(tag) for tag in (getattr(step, "tags", ()) or ())}
        parts: list[str] = []
        for tag in tags:
            if tag.startswith("repeat_count_"):
                parts.append(f"Rpt x{tag.removeprefix('repeat_count_')}")
            elif tag == "reverse":
                parts.append("Rev")
            elif tag == "kick_roll":
                parts.append("Roll")
            elif tag == "snare_stretch":
                parts.append("Stretch")
        pitch_shift = float(getattr(step, "pitch_shift", 0.0) or 0.0)
        if abs(pitch_shift) > 1e-6:
            parts.append(f"Pch {round(pitch_shift, 1):+g}")
        return " | ".join(parts) if parts else "-"

    def _matches_path(self, path: str | None) -> bool:
        if not path or self.widget._analysis_result is None:
            return False
        return os.path.normcase(os.path.normpath(self.widget._analysis_result.source_path)) == os.path.normcase(os.path.normpath(path))

    def _refresh_actions(self) -> None:
        has_analysis = self.widget._analysis_result is not None and bool(
            getattr(self.widget._analysis_result, "slices", ())
        )
        has_pattern = self.widget._generated_pattern is not None
        can_use_pattern = has_pattern and not self.widget._pattern_dirty and not self.widget._render_busy
        self.widget.generate_button.setEnabled(has_analysis and not self.widget._generation_busy)
        self.widget.preview_button.setEnabled(
            (can_use_pattern and not self.widget._generation_busy) or self.widget._is_preview_playing()
        )
        self.widget.render_button.setEnabled(can_use_pattern and not self.widget._generation_busy)

    def _active_pattern_anchors(self, *, step_count: int | None = None) -> dict[int, str]:
        if step_count is None:
            pattern = self.widget._generated_pattern
            step_count = int(getattr(pattern, "step_count", 0) or max(16, int(self.widget.bars_spin.value()) * 16))
        return {
            int(step_index): str(anchor)
            for step_index, anchor in self.widget._pattern_step_anchors.items()
            if 1 <= int(step_index) <= int(step_count)
            and anchor in GENERATOR_STEP_ANCHOR_LABELS
        }

    def _anchor_summary_text(self, *, step_count: int | None = None) -> str:
        anchors = self._active_pattern_anchors(step_count=step_count)
        if not anchors:
            return "Ancres: aucune"
        preview = [
            f"{step}:{GENERATOR_STEP_ANCHOR_LABELS.get(anchor, anchor)}"
            for step, anchor in sorted(anchors.items())
        ]
        if len(preview) > 8:
            preview = [*preview[:8], "..."]
        return f"Ancres: {', '.join(preview)}"

    def _active_pattern_locked_steps(self, *, step_count: int | None = None) -> tuple[int, ...]:
        if step_count is None:
            pattern = self.widget._generated_pattern
            step_count = int(
                getattr(pattern, "step_count", 0)
                or max(16, int(self.widget.bars_spin.value()) * 16)
            )
        return tuple(
            sorted(
                step_index
                for step_index in self.widget._pattern_locked_steps
                if 1 <= int(step_index) <= int(step_count)
            )
        )

    def _lock_summary_text(self, *, step_count: int | None = None) -> str:
        locked_steps = self._active_pattern_locked_steps(step_count=step_count)
        if not locked_steps:
            return "Locks: aucun"
        preview = [str(step) for step in locked_steps[:10]]
        if len(locked_steps) > 10:
            preview.append("...")
        return f"Locks: {', '.join(preview)}"

    def _loop_summary_text(self) -> str:
        if self.widget._pattern_loop_range is None:
            if self.widget._pattern_loop_anchor_step is None:
                return "Boucle: inactive"
            return f"Boucle: origine step {self.widget._pattern_loop_anchor_step}"
        start_step, end_step = self.widget._pattern_loop_range
        if start_step == end_step:
            return f"Boucle: step {start_step}"
        return f"Boucle: steps {start_step}-{end_step}"

    def _refresh_pattern_interaction_label(self, *, step_count: int | None = None) -> None:
        step_count = int(step_count or 0)
        hint = (
            "Header = play from step | Shift+header = loop range | Anchor = type | "
            "Lock = keep step | Event = one-shot"
        )
        if step_count > 0:
            hint = (
                f"{hint} | {self._anchor_summary_text(step_count=step_count)} | "
                f"{self._lock_summary_text(step_count=step_count)} | "
                f"{self._loop_summary_text()}."
            )
        self.widget.pattern_interaction_label.setText(hint)

    def _sanitize_pattern_state(self, step_count: int) -> None:
        self.widget._pattern_step_anchors = {
            int(step_index): str(anchor)
            for step_index, anchor in self.widget._pattern_step_anchors.items()
            if 1 <= int(step_index) <= int(step_count)
        }
        self.widget._pattern_locked_steps = {
            int(step_index)
            for step_index in self.widget._pattern_locked_steps
            if 1 <= int(step_index) <= int(step_count)
        }
        if self.widget._pattern_loop_anchor_step is not None:
            anchor_step = int(self.widget._pattern_loop_anchor_step)
            self.widget._pattern_loop_anchor_step = (
                anchor_step if 1 <= anchor_step <= int(step_count) else None
            )
        if self.widget._pattern_loop_range is None:
            return
        start_step, end_step = self.widget._pattern_loop_range
        start_step = max(1, min(int(start_step), int(step_count)))
        end_step = max(1, min(int(end_step), int(step_count)))
        if start_step > end_step:
            start_step, end_step = end_step, start_step
        self.widget._pattern_loop_range = (start_step, end_step)

    def _build_anchor_button(self, step_index: int) -> QPushButton:
        button = QPushButton()
        button.setObjectName("BreakGeneratorAnchorButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(
            lambda _checked=False, current_step=int(step_index): self._on_pattern_anchor_step_clicked(current_step)
        )
        self._update_anchor_button(button, int(step_index))
        return button

    def _update_anchor_button(self, button: QPushButton, step_index: int) -> None:
        anchor = self.widget._pattern_step_anchors.get(int(step_index))
        button.setText(GENERATOR_STEP_ANCHOR_SHORT_LABELS.get(anchor, "."))
        button.setToolTip(
            f"Step {step_index} | anchor {GENERATOR_STEP_ANCHOR_LABELS.get(anchor, 'auto')}\n"
            "Clique pour cycler: auto -> kick -> snare -> clap -> hat -> ghost -> other -> silence."
        )
        button.setProperty("anchorActive", bool(anchor))
        button.setProperty("anchorKind", "auto" if anchor is None else anchor)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _refresh_pattern_anchor_button(self, step_index: int) -> None:
        column = int(step_index) - 1
        if column < 0 or column >= self.widget.pattern_table.columnCount():
            return
        button = self.widget.pattern_table.cellWidget(_PATTERN_ROW_ANCHOR, column)
        if isinstance(button, QPushButton):
            self._update_anchor_button(button, int(step_index))

    def _build_lock_button(self, step_index: int) -> QPushButton:
        button = QPushButton()
        button.setObjectName("BreakGeneratorLockButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(
            lambda _checked=False, current_step=int(step_index): self._on_pattern_lock_step_clicked(current_step)
        )
        self._update_lock_button(button, int(step_index))
        return button

    def _update_lock_button(self, button: QPushButton, step_index: int) -> None:
        locked = int(step_index) in self.widget._pattern_locked_steps
        button.setText("L" if locked else ".")
        button.setToolTip(
            f"Step {step_index} | {'verrouille' if locked else 'non verrouille'}\n"
            "Clique pour verrouiller ou deverrouiller ce step. "
            "Un step locke garde son contenu au prochain Generate."
        )
        button.setProperty("lockActive", locked)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _refresh_pattern_lock_button(self, step_index: int) -> None:
        column = int(step_index) - 1
        if column < 0 or column >= self.widget.pattern_table.columnCount():
            return
        button = self.widget.pattern_table.cellWidget(_PATTERN_ROW_LOCK, column)
        if isinstance(button, QPushButton):
            self._update_lock_button(button, int(step_index))

    def _on_pattern_anchor_step_clicked(self, step_index: int) -> None:
        current = self.widget._pattern_step_anchors.get(int(step_index))
        try:
            current_index = GENERATOR_STEP_ANCHOR_ORDER.index(current)
        except ValueError:
            current_index = 0
        next_anchor = GENERATOR_STEP_ANCHOR_ORDER[
            (current_index + 1) % len(GENERATOR_STEP_ANCHOR_ORDER)
        ]
        if next_anchor is None:
            self.widget._pattern_step_anchors.pop(int(step_index), None)
        else:
            self.widget._pattern_step_anchors[int(step_index)] = str(next_anchor)
        self.widget._pattern_loop_anchor_step = int(step_index)
        self.widget._pattern_loop_range = None
        self._mark_pattern_dirty()
        self._refresh_pattern_anchor_button(step_index)
        self._refresh_pattern_visual_state(self.widget._generated_pattern)
        self._refresh_pattern_interaction_label(step_count=self.widget.pattern_table.columnCount())
        anchor_text = GENERATOR_STEP_ANCHOR_LABELS.get(next_anchor, "auto")
        self.widget.statusChanged.emit(
            f"Anchor step {step_index}: {anchor_text}. Regenerer pour l'appliquer."
        )

    def _on_pattern_lock_step_clicked(self, step_index: int) -> None:
        step_index = int(step_index)
        if step_index in self.widget._pattern_locked_steps:
            self.widget._pattern_locked_steps.discard(step_index)
            state = "off"
        else:
            self.widget._pattern_locked_steps.add(step_index)
            state = "on"
        self.widget._pattern_loop_anchor_step = step_index
        self.widget._pattern_loop_range = None
        self._mark_pattern_dirty()
        self._refresh_pattern_lock_button(step_index)
        self._refresh_pattern_visual_state(self.widget._generated_pattern)
        self._refresh_pattern_interaction_label(step_count=self.widget.pattern_table.columnCount())
        self.widget.statusChanged.emit(
            f"Lock step {step_index}: {state}. Le prochain Generate {'gardera' if state == 'on' else 'pourra modifier'} ce step."
        )

    def _on_pattern_header_clicked(self, column: int) -> None:
        step_index = int(column) + 1
        if step_index < 1:
            return
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            origin_step = self.widget._pattern_loop_anchor_step or step_index
            start_step = min(int(origin_step), int(step_index))
            end_step = max(int(origin_step), int(step_index))
            self.widget._pattern_loop_anchor_step = int(origin_step)
            self.widget._pattern_loop_range = (start_step, end_step)
            self._refresh_pattern_visual_state(self.widget._generated_pattern)
            self._refresh_pattern_interaction_label(step_count=self.widget.pattern_table.columnCount())
            self.widget._preview_pattern_loop_range(start_step, end_step)
            return

        self.widget._pattern_loop_anchor_step = int(step_index)
        self.widget._pattern_loop_range = None
        self._refresh_pattern_visual_state(self.widget._generated_pattern)
        self._refresh_pattern_interaction_label(step_count=self.widget.pattern_table.columnCount())
        self.widget._preview_pattern_from_step(step_index)

    def _on_pattern_table_cell_clicked(self, row: int, column: int) -> None:
        step_index = int(column) + 1
        if row in {_PATTERN_ROW_ANCHOR, _PATTERN_ROW_LOCK}:
            return
        self.widget._pattern_loop_anchor_step = int(step_index)
        if row == _PATTERN_ROW_EVENT:
            self.widget._preview_pattern_step(step_index)
        self._refresh_pattern_visual_state(self.widget._generated_pattern)
        self._refresh_pattern_interaction_label(step_count=self.widget.pattern_table.columnCount())

    def _refresh_pattern_visual_state(self, pattern: Any) -> None:
        table = self.widget.pattern_table
        steps = list(getattr(pattern, "steps", ()) or ()) if pattern is not None else []
        loop_range = self.widget._pattern_loop_range
        anchor_step = self.widget._pattern_loop_anchor_step
        for column in range(table.columnCount()):
            step_index = column + 1
            header_item = table.horizontalHeaderItem(column)
            base_header_bg = QColor("#191d24")
            base_header_fg = QColor("#9aa4b2")
            if loop_range is not None and loop_range[0] <= step_index <= loop_range[1]:
                strength = 0.55 if step_index in {loop_range[0], loop_range[1]} else 0.4
                base_header_bg = self._blend_color(base_header_bg, QColor("#285266"), strength)
                base_header_fg = QColor("#d9f3ff")
            elif loop_range is None and anchor_step == step_index:
                base_header_bg = self._blend_color(base_header_bg, QColor("#70552a"), 0.45)
                base_header_fg = QColor("#ffe4ad")
            if header_item is not None:
                header_item.setBackground(base_header_bg)
                header_item.setForeground(base_header_fg)

            step = steps[column] if column < len(steps) else None
            for row in range(2, table.rowCount()):
                item = table.item(row, column)
                if item is None:
                    continue
                if row == _PATTERN_ROW_EVENT and step is not None:
                    color_hex = STEP_COLORS.get(str(getattr(step, "label", "") or ""))
                    background = QColor(f"{color_hex}33") if color_hex else QColor("#1a1e25")
                    foreground = QColor(color_hex) if color_hex else QColor("#d6d9de")
                else:
                    background = QColor("#1a1e25")
                    foreground = QColor("#d6d9de")
                if loop_range is not None and loop_range[0] <= step_index <= loop_range[1]:
                    overlay = QColor("#244857") if row != _PATTERN_ROW_EVENT else QColor("#1e5b72")
                    background = self._blend_color(background, overlay, 0.35)
                    foreground = QColor("#eefaff") if row != _PATTERN_ROW_EVENT else foreground
                item.setBackground(background)
                item.setForeground(foreground)

            self._refresh_pattern_anchor_button(step_index)
            self._refresh_pattern_lock_button(step_index)

    @staticmethod
    def _blend_color(base: QColor, overlay: QColor, alpha: float) -> QColor:
        ratio = max(0.0, min(float(alpha), 1.0))
        inv = 1.0 - ratio
        return QColor(
            int((base.red() * inv) + (overlay.red() * ratio)),
            int((base.green() * inv) + (overlay.green() * ratio)),
            int((base.blue() * inv) + (overlay.blue() * ratio)),
        )

    @staticmethod
    def _summarize_generated_pattern_steps(steps: tuple[Any, ...]) -> tuple[int, str]:
        event_count = sum(
            1 for step in steps
            if str(getattr(step, "label", "silence") or "silence") != "silence"
        )
        counts: dict[str, int] = {}
        for step in steps:
            label = str(getattr(step, "label", "silence") or "silence")
            if label == "silence":
                continue
            counts[label] = counts.get(label, 0) + 1
        summary = ", ".join(
            f"{label}:{count}"
            for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        )
        return event_count, (summary or "silence only")

    def _merge_locked_generated_steps(self, pattern: Any, previous_pattern: Any | None) -> Any:
        if previous_pattern is None or not self.widget._pattern_locked_steps:
            return pattern

        previous_steps = {
            int(getattr(step, "step_index", index + 1)): step
            for index, step in enumerate(tuple(getattr(previous_pattern, "steps", ()) or ()))
        }
        merged_steps: list[Any] = []
        changed = False
        for step in tuple(getattr(pattern, "steps", ()) or ()):
            step_number = int(getattr(step, "step_index", len(merged_steps) + 1))
            if step_number not in self.widget._pattern_locked_steps:
                merged_steps.append(step)
                continue
            previous_step = previous_steps.get(step_number)
            if previous_step is None:
                merged_steps.append(step)
                continue
            merged_steps.append(previous_step)
            changed = True

        if not changed:
            return pattern

        event_count, summary = self._summarize_generated_pattern_steps(tuple(merged_steps))
        try:
            return replace(
                pattern,
                steps=tuple(merged_steps),
                event_count=int(event_count),
                summary=str(summary),
            )
        except Exception:
            return pattern
