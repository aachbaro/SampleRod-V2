# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Facade du BreakGeneratorPanel, suivant le pattern facade + controleurs.
# - Garde les signaux Qt et delegue UI / pattern / playback / export a des
#   controleurs specialises.
#
# LIENS CLES
# - generator_ui.py       : construction de l'interface
# - generator_pattern.py  : generation + table du pattern
# - generator_playback.py : preview audio
# - generator_export.py   : rendu artefact
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import Any

import json

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton, QTableWidgetItem, QWidget

from backend.services.drum_analysis_service import (
    DEFAULT_GENERATOR_TARGET_BPM,
    DEFAULT_PATTERN_TAIL_MODE,
    DrumAnalysisResult,
    DrumGeneratedPatternResult,
    DrumPatternRender,
)
from frontend.styles import theme

from .generator_constants import (
    DEFAULT_PITCH_SEQUENCE,
    FILL_STYLE_LABELS,
    GENERATION_PROFILE_LABELS,
    GENERATOR_MODE_CLASSIC,
    GENERATOR_MODE_HYBRID,
    GENERATOR_MODE_LABELS,
    PATTERN_TAIL_MODE_LABELS,
    PITCH_CURVE_OPTIONS,
    PITCH_MODE_OPTIONS,
    PITCH_NOTE_NAMES,
    PITCH_RATE_OPTIONS,
    PITCH_SCALE_OPTIONS,
    PITCH_SCOPE_OPTIONS,
    SNARE_STRETCH_CURVE_OPTIONS,
    STEP_COLORS,
    STEP_SHORT_LABELS,
)
from .generator_export import BreakGeneratorExportController
from .generator_pattern import BreakGeneratorPatternController
from .generator_playback import BreakGeneratorPlaybackController
from .generator_ui import BreakGeneratorUIBuilder


class BreakGeneratorPanel(QWidget):
    """Facade du generateur de break integre au BreakWidget."""

    artifactCreated = Signal(object)
    statusChanged = Signal(str)

    def __init__(self, app_context, break_service, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._service = break_service
        self._settings = QSettings("SampleRod", "Main")
        self._analysis_result: DrumAnalysisResult | None = None
        self._generated_pattern: Any = None
        self._pattern_dirty = False
        self._generation_busy = False
        self._render_busy = False
        self._render_request_mode: str | None = None
        self._preview_signature: tuple[Any, ...] | None = None
        self._preview_temp_path = ""
        self._preview_duration_s = 0.0
        self._preview_sample_id: int | None = None
        self._active_preview_path = ""
        self._active_preview_looping = False
        self._preview_request: dict[str, Any] | None = None
        self._pattern_step_anchors: dict[int, str] = {}
        self._pattern_locked_steps: set[int] = set()
        self._pattern_loop_range: tuple[int, int] | None = None
        self._pattern_loop_anchor_step: int | None = None

        self._motifs: list[dict] = []
        self._motif_editor_steps: list[str | None] = [None] * 8

        self.ui = BreakGeneratorUIBuilder(self)
        self.pattern = BreakGeneratorPatternController(self)
        self.playback = BreakGeneratorPlaybackController(self)
        self.export = BreakGeneratorExportController(self)

        self._build_ui()
        self._load_saved_motifs()
        self._bind_signals()
        self._refresh_motif_step_buttons()
        self._refresh_motif_table()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

        self._preview_refresh_timer = QTimer(self)
        self._preview_refresh_timer.setInterval(250)
        self._preview_refresh_timer.timeout.connect(self._refresh_preview_button)
        self._preview_refresh_timer.start()

    def _build_ui(self) -> None:
        self.ui._build_ui()

    def _bind_signals(self) -> None:
        self.generate_button.clicked.connect(self._generate_pattern)
        self.preview_button.clicked.connect(self._preview_pattern)
        self.render_button.clicked.connect(self._render_pattern_artifact)

        generation_controls = (
            self.mode_combo,
            self.profile_combo,
            self.fill_style_combo,
            self.bars_spin,
            self.energy_slider,
            self.kick_slider,
            self.snare_slider,
            self.hat_slider,
            self.ghost_slider,
            self.velocity_slider,
            self.swing_slider,
            self.anti_repeat_slider,
            self.breath_slider,
            self.position_slider,
            self.sequence_density_slider,
            self.motif_density_slider,
            self.synth_ghost_check,
            self.ghost_vel_min_spin,
            self.ghost_vel_max_spin,
            self.ghost_pitch_min_spin,
            self.ghost_pitch_max_spin,
            self.ghost_gate_slider,
            self.fill_slider,
            self.repeat_density_slider,
            self.repeat_span_slider,
            self.repeat_rate_slider,
            self.reverse_slider,
            self.kick_roll_density_slider,
            self.kick_roll_span_slider,
            self.kick_roll_contrast_slider,
            self.snare_stretch_density_slider,
            self.snare_stretch_span_slider,
            self.snare_stretch_amount_slider,
            self.snare_stretch_curve_combo,
            self.pitch_mode_combo,
            self.pitch_scope_combo,
            self.pitch_scale_combo,
            self.pitch_root_combo,
            self.pitch_range_min_spin,
            self.pitch_range_max_spin,
            self.pitch_sequence_input,
            self.pitch_rate_combo,
            self.pitch_curve_combo,
            self.pitch_curve_min_spin,
            self.pitch_curve_max_spin,
            self.pitch_amount_slider,
            self.sequence_max_len_spin,
            self.sequence_role_lock_check,
        )
        for widget in generation_controls:
            self._connect_change_signal(widget, self._mark_pattern_dirty)

        preview_controls = (
            self.target_bpm_spin,
            self.gate_slider,
            self.mono_choke_check,
            self.tail_mode_combo,
        )
        for widget in preview_controls:
            self._connect_change_signal(widget, self._on_preview_settings_changed)

        self.motif_add_button.clicked.connect(self._add_motif)
        self.motif_length_spin.valueChanged.connect(self._refresh_motif_step_buttons)
        for _i, _btn in enumerate(self.motif_step_buttons):
            _btn.clicked.connect(lambda _=False, idx=_i: self._on_motif_step_clicked(idx))

        self._service.patternGenerationStarted.connect(self._on_pattern_generation_started)
        self._service.patternGenerated.connect(self._on_pattern_generated)
        self._service.patternGenerationFailed.connect(self._on_pattern_generation_failed)
        self._service.patternRenderStarted.connect(self._on_pattern_render_started)
        self._service.patternRendered.connect(self._on_pattern_rendered)
        self._service.patternRenderFailed.connect(self._on_pattern_render_failed)
        self.pattern_table.cellClicked.connect(self._on_pattern_table_cell_clicked)
        self.pattern_table.horizontalHeader().sectionClicked.connect(
            self._on_pattern_header_clicked
        )

    def set_analysis_result(self, result: DrumAnalysisResult | None) -> None:
        self.pattern.set_analysis_result(result)

    def clear_state(self) -> None:
        self.pattern.clear_state()

    def _generate_pattern(self) -> None:
        self.pattern._generate_pattern()

    def _preview_pattern(self) -> None:
        self.playback._preview_pattern()

    def _preview_pattern_from_step(self, step_index: int) -> None:
        self.playback._preview_pattern_from_step(step_index)

    def _preview_pattern_step(self, step_index: int) -> None:
        self.playback._preview_pattern_step(step_index)

    def _preview_pattern_loop_range(self, start_step: int, end_step: int) -> None:
        self.playback._preview_pattern_loop_range(start_step, end_step)

    def _render_pattern_artifact(self) -> None:
        self.export._render_pattern_artifact()

    def _preview_sample_id_for_path(self, path: str) -> int:
        return self.playback._preview_sample_id_for_path(path)

    def _is_preview_playing(self) -> bool:
        return self.playback._is_preview_playing()

    def _start_loop_preview(self, path: str, duration_s: float) -> None:
        self.playback._start_loop_preview(path, duration_s)

    def _stop_preview(self) -> None:
        self.playback._stop_preview()

    def _refresh_preview_button(self) -> None:
        self.playback._refresh_preview_button()

    def _start_requested_preview(self, path: str, duration_s: float) -> str:
        return self.playback._start_requested_preview(path, duration_s)

    def _pattern_params_payload(self) -> dict[str, Any]:
        return self.pattern._pattern_params_payload()

    def _parse_pitch_sequence(self) -> list[float]:
        return self.pattern._parse_pitch_sequence()

    def _mark_pattern_dirty(self, *_args) -> None:
        self.pattern._mark_pattern_dirty(*_args)

    def _on_preview_settings_changed(self, *_args) -> None:
        self.playback._on_preview_settings_changed(*_args)

    def _on_pattern_generation_started(self, source_path: str) -> None:
        self.pattern._on_pattern_generation_started(source_path)

    def _on_pattern_generated(self, payload: DrumGeneratedPatternResult) -> None:
        self.pattern._on_pattern_generated(payload)

    def _on_pattern_generation_failed(self, source_path: str, message: str) -> None:
        self.pattern._on_pattern_generation_failed(source_path, message)

    def _on_pattern_render_started(self, source_path: str) -> None:
        self.export._on_pattern_render_started(source_path)

    def _on_pattern_rendered(self, payload: DrumPatternRender) -> None:
        self.export._on_pattern_rendered(payload)

    def _on_pattern_render_failed(self, source_path: str, message: str) -> None:
        self.export._on_pattern_render_failed(source_path, message)

    def _populate_pattern_table(self, pattern: Any) -> None:
        self.pattern._populate_pattern_table(pattern)

    def _on_pattern_table_cell_clicked(self, row: int, column: int) -> None:
        self.pattern._on_pattern_table_cell_clicked(row, column)

    def _on_pattern_header_clicked(self, column: int) -> None:
        self.pattern._on_pattern_header_clicked(column)

    def _step_label(self, step: Any) -> str:
        return self.pattern._step_label(step)

    def _step_fx_text(self, step: Any) -> str:
        return self.pattern._step_fx_text(step)

    def _current_preview_signature(self) -> tuple[Any, ...] | None:
        return self.playback._current_preview_signature()

    def _clear_preview_cache(self, *, stop_if_playing: bool) -> None:
        self.playback._clear_preview_cache(stop_if_playing=stop_if_playing)

    def _matches_path(self, path: str | None) -> bool:
        return self.pattern._matches_path(path)

    def _refresh_actions(self) -> None:
        self.pattern._refresh_actions()

    def _build_knob(self, value: int, *, default: int | None = None):
        return self.ui._build_knob(value, default=default)

    def _build_knob_cell(self, label: str, knob) -> QWidget:
        return self.ui._build_knob_cell(label, knob)

    def _build_knob_row(self, items):
        return self.ui._build_knob_row(items)

    def _build_section(self, title: str):
        return self.ui._build_section(title)

    def _build_combo(self, labels: dict[str, str]):
        return self.ui._build_combo(labels)

    def _build_double_spin(self, minimum: float, maximum: float, step: float, value: float):
        return self.ui._build_double_spin(minimum, maximum, step, value)

    def _add_labeled_widget(
        self,
        layout,
        row: int,
        column: int,
        label: str,
        widget: QWidget,
        *,
        span: int = 1,
    ) -> None:
        self.ui._add_labeled_widget(layout, row, column, label, widget, span=span)

    def _connect_change_signal(self, widget: QWidget, callback) -> None:
        self.ui._connect_change_signal(widget, callback)

    def _apply_styles(self) -> None:
        self.ui._apply_styles()

    # ---- Motif management -----------------------------------------------

    def _on_motif_step_clicked(self, idx: int) -> None:
        from .generator_ui import _MOTIF_STEP_ORDER
        current = self._motif_editor_steps[idx]
        ci = _MOTIF_STEP_ORDER.index(current) if current in _MOTIF_STEP_ORDER else 0
        self._motif_editor_steps[idx] = _MOTIF_STEP_ORDER[(ci + 1) % len(_MOTIF_STEP_ORDER)]
        self._refresh_motif_step_buttons()

    def _add_motif(self) -> None:
        length = int(self.motif_length_spin.value())
        steps = self._motif_editor_steps[:length]
        if not any(s is not None for s in steps):
            return
        name = self.motif_name_input.text().strip() or f"Motif {len(self._motifs) + 1}"
        role = str(self.motif_role_combo.currentData() or "groove")
        base_prob = int(self.motif_base_prob_spin.value()) / 100.0
        counts: dict[str, int] = {}
        for s in steps:
            if s and s != "silence":
                counts[s] = counts.get(s, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        if not ranked or ranked[0][1] == 0:
            dominant = "mixed"
        elif len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            dominant = "mixed"
        else:
            dominant = ranked[0][0]
        self._motifs.append({
            "name": name,
            "steps": list(steps),
            "role": role,
            "base_prob": base_prob,
            "dominant_type": dominant,
        })
        self._motif_editor_steps = [None] * 8
        self.motif_name_input.clear()
        self._refresh_motif_step_buttons()
        self._refresh_motif_table()
        self._persist_motifs()
        self._mark_pattern_dirty()

    def _delete_motif(self, row: int) -> None:
        if 0 <= row < len(self._motifs):
            self._motifs.pop(row)
            self._refresh_motif_table()
            self._persist_motifs()
            self._mark_pattern_dirty()

    def _refresh_motif_step_buttons(self, *_args) -> None:
        from .generator_ui import _MOTIF_STEP_SHORT, _MOTIF_STEP_FG, _MOTIF_STEP_BG
        from frontend.styles import theme
        p = theme.manager.p
        length = int(self.motif_length_spin.value())
        for i, btn in enumerate(self.motif_step_buttons):
            active = i < length
            btn.setEnabled(active)
            value = self._motif_editor_steps[i] if active else None
            btn.setText(_MOTIF_STEP_SHORT.get(value, "·"))
            if active and value and value in _MOTIF_STEP_FG:
                fg = _MOTIF_STEP_FG[value]
                bg = _MOTIF_STEP_BG.get(value, "transparent")
                btn.setStyleSheet(
                    f"background: {bg}; color: {fg}; border: 1px solid {fg}; "
                    f"border-radius: 4px; font-size: 10px; font-weight: 700; padding: 0;"
                )
            else:
                btn.setStyleSheet(
                    f"background: {p.BG_MEDIUM}; color: {p.TEXT_MUTED}; border: 1px solid {p.BORDER}; "
                    f"border-radius: 4px; font-size: 10px; font-weight: 700; padding: 0;"
                )

    def _refresh_motif_table(self) -> None:
        from .generator_ui import _MOTIF_STEP_SHORT
        _ROLE_LABELS = {"groove": "Groove", "fill": "Fill", "cadence": "Cadence", "anticipation": "Anticip."}
        tbl = self.motifs_table
        tbl.setRowCount(len(self._motifs))
        for row, m in enumerate(self._motifs):
            steps_txt = " ".join(_MOTIF_STEP_SHORT.get(s, "·") for s in (m.get("steps") or []))
            for col, val in enumerate([
                m.get("name", "?"),
                steps_txt,
                _ROLE_LABELS.get(str(m.get("role", "")), str(m.get("role", ""))),
                f"{int((m.get('base_prob') or 0) * 100)}%",
            ]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tbl.setItem(row, col, item)
            del_btn = QPushButton("✕")
            del_btn.setObjectName("BreakGeneratorAction")
            del_btn.setFixedSize(26, 26)
            del_btn.clicked.connect(lambda _=False, r=row: self._delete_motif(r))
            tbl.setCellWidget(row, 4, del_btn)

    def _collect_user_motifs_payload(self) -> list[dict]:
        return list(self._motifs)

    def _load_saved_motifs(self) -> None:
        raw = self._settings.value("break_generator_user_motifs_v1", "")
        if not raw or not isinstance(raw, str):
            return
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                self._motifs = [m for m in data if isinstance(m, dict)]
        except Exception:
            pass

    def _persist_motifs(self) -> None:
        try:
            self._settings.setValue("break_generator_user_motifs_v1", json.dumps(self._motifs))
        except Exception:
            pass
