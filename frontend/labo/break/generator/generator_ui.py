# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la construction visuelle du BreakGeneratorPanel.
# - Isole le gros build UI, les helpers de creation de controls et le QSS.
#
# LIENS CLES
# - frontend/labo/break/generator/knob_widget.py : potentiometre reutilise.
# - frontend/styles/theme.py                     : couleurs dynamiques.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from backend.services.drum_analysis_service import (
    DEFAULT_GENERATOR_TARGET_BPM,
    DEFAULT_PATTERN_TAIL_MODE,
)
from frontend.styles import theme
from frontend.ui import icon_qss_url

from .generator_constants import (
    DEFAULT_PITCH_SEQUENCE,
    FILL_STYLE_LABELS,
    GENERATION_PROFILE_LABELS,
    GENERATOR_MODE_LABELS,
    PATTERN_CELL_SIZE,
    PATTERN_ROW_LABELS,
    PATTERN_TABLE_HEIGHT,
    PATTERN_TAIL_MODE_LABELS,
    PITCH_CURVE_OPTIONS,
    PITCH_MODE_OPTIONS,
    PITCH_NOTE_NAMES,
    PITCH_RATE_OPTIONS,
    PITCH_SCALE_OPTIONS,
    PITCH_SCOPE_OPTIONS,
    SNARE_STRETCH_CURVE_OPTIONS,
)
from .knob_widget import KnobWidget

_MOTIF_STEP_ORDER: tuple = (None, "kick", "snare", "hat", "ghost", "silence")
_MOTIF_STEP_SHORT: dict = {None: "·", "kick": "K", "snare": "S", "hat": "H", "ghost": "G", "silence": "–"}
_MOTIF_STEP_FG: dict = {"kick": "#d46666", "snare": "#d89747", "hat": "#4bb6b7", "ghost": "#b68553", "silence": "#888888"}
_MOTIF_STEP_BG: dict = {"kick": "#d4666622", "snare": "#d8974722", "hat": "#4bb6b722", "ghost": "#b6855322", "silence": "#88888822"}
_MOTIF_ROLE_OPTIONS: tuple = (
    ("groove", "Groove"),
    ("fill", "Fill"),
    ("cadence", "Cadence"),
    ("anticipation", "Anticipation"),
)


# Note : les combos et spins du generateur acceptent volontairement la
# molette (changer le BPM, les bars, passer d'une option a l'autre). Le
# panneau n'est pas dans un QScrollArea, donc il n'y a pas de conflit avec le
# defilement de la page. Les knobs, eux, restent insensibles a la molette.


class BreakGeneratorUIBuilder:
    """Construit l'interface et les helpers UI du generateur de break."""

    def __init__(self, widget):
        self.widget = widget

    def _build_ui(self) -> None:
        self.widget.setObjectName("BreakGeneratorRoot")
        self.widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self.widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.widget.container = QFrame()
        self.widget.container.setObjectName("BreakGeneratorFrame")
        layout = QVBoxLayout(self.widget.container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        self.widget.title_label = QLabel("Generateur de break")
        self.widget.title_label.setObjectName("BreakSectionTitle")
        title_col.addWidget(self.widget.title_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)

        self.widget.generate_button = QPushButton("Generer")
        self.widget.generate_button.setObjectName("BreakGeneratorAction")
        self.widget.preview_button = QPushButton("▶  Preview")
        self.widget.preview_button.setObjectName("BreakGeneratorAction")
        self.widget.render_button = QPushButton("Rendre artefact")
        self.widget.render_button.setObjectName("BreakGeneratorAction")

        actions.addWidget(self.widget.generate_button)
        actions.addWidget(self.widget.preview_button)
        actions.addWidget(self.widget.render_button)

        header.addLayout(title_col, 1)
        header.addLayout(actions, 0)

        self.widget.controls_frame = QWidget()
        controls_row = QHBoxLayout(self.widget.controls_frame)
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)

        self.widget.mode_combo = self._build_combo(GENERATOR_MODE_LABELS)
        self.widget.profile_combo = self._build_combo(GENERATION_PROFILE_LABELS)
        self.widget.fill_style_combo = self._build_combo(FILL_STYLE_LABELS)
        profile_index = self.widget.profile_combo.findData("musical")
        if profile_index >= 0:
            self.widget.profile_combo.setCurrentIndex(profile_index)

        self.widget.bars_spin = QSpinBox()
        self.widget.bars_spin.setObjectName("BreakGeneratorSpin")
        self.widget.bars_spin.setRange(1, 4)
        self.widget.bars_spin.setValue(1)
        self.widget.bars_spin.setFixedWidth(62)
        self.widget.bars_spin.setToolTip("Nombre de mesures (molette pour changer)")

        self.widget.target_bpm_spin = QDoubleSpinBox()
        self.widget.target_bpm_spin.setObjectName("BreakGeneratorSpin")
        self.widget.target_bpm_spin.setRange(40.0, 300.0)
        self.widget.target_bpm_spin.setDecimals(1)
        self.widget.target_bpm_spin.setSingleStep(1.0)
        self.widget.target_bpm_spin.setValue(float(DEFAULT_GENERATOR_TARGET_BPM))
        # Assez large pour "300.0" + les fleches, sinon la valeur est rognee.
        self.widget.target_bpm_spin.setFixedWidth(88)
        self.widget.target_bpm_spin.setToolTip("BPM de preview (molette pour changer)")

        self.widget.seed_value = QLabel("auto")
        self.widget.seed_value.setObjectName("BreakGeneratorSeed")

        def _lbl(text):
            l = QLabel(text)
            l.setObjectName("BreakGeneratorFieldLabel")
            return l

        for ui_widget in (
            self.widget.mode_combo,
            self.widget.profile_combo,
            self.widget.fill_style_combo,
        ):
            ui_widget.setMaximumWidth(110)

        controls_row.addWidget(_lbl("Moteur"))
        controls_row.addWidget(self.widget.mode_combo)
        controls_row.addWidget(_lbl("Profil"))
        controls_row.addWidget(self.widget.profile_combo)
        controls_row.addWidget(_lbl("Fill"))
        controls_row.addWidget(self.widget.fill_style_combo)
        controls_row.addWidget(_lbl("Bars"))
        controls_row.addWidget(self.widget.bars_spin)
        controls_row.addWidget(_lbl("BPM"))
        controls_row.addWidget(self.widget.target_bpm_spin)
        controls_row.addWidget(_lbl("Seed :"))
        controls_row.addWidget(self.widget.seed_value)
        controls_row.addStretch()

        self.widget.tab_widget = QTabWidget()
        self.widget.tab_widget.setObjectName("BreakGeneratorTabs")

        def _fl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("BreakGeneratorFieldLabel")
            return lbl

        _groove_tab = QWidget()
        _gtl = QVBoxLayout(_groove_tab)
        _gtl.setContentsMargins(8, 8, 8, 8)
        _gtl.setSpacing(4)

        self.widget.energy_slider = self._build_knob(55)
        self.widget.kick_slider = self._build_knob(60)
        self.widget.snare_slider = self._build_knob(70)
        self.widget.hat_slider = self._build_knob(60)
        self.widget.ghost_slider = self._build_knob(25)
        self.widget.velocity_slider = self._build_knob(50)
        self.widget.swing_slider = self._build_knob(0)
        self.widget.anti_repeat_slider = self._build_knob(60)
        self.widget.breath_slider = self._build_knob(35)
        self.widget.position_slider = self._build_knob(0)
        self.widget.sequence_density_slider = self._build_knob(0)
        self.widget.motif_density_slider = self._build_knob(0)

        _gtl.addWidget(self._build_knob_row([
            ("Energy", self.widget.energy_slider), ("Kick", self.widget.kick_slider),
            ("Snare", self.widget.snare_slider), ("Hats", self.widget.hat_slider),
            ("Ghosts", self.widget.ghost_slider), ("Velocity", self.widget.velocity_slider),
        ]))
        _gtl.addWidget(self._build_knob_row([
            ("Swing", self.widget.swing_slider), ("Anti-rpt", self.widget.anti_repeat_slider),
            ("Breath", self.widget.breath_slider), ("Position", self.widget.position_slider),
            ("Sequences", self.widget.sequence_density_slider), ("Motifs", self.widget.motif_density_slider),
        ]))

        self.widget.synth_ghost_check = QCheckBox("Ghosts synthetiques")
        self.widget.synth_ghost_check.setChecked(True)
        self.widget.ghost_vel_min_spin = self._build_double_spin(0.0, 1.0, 0.01, 0.20)
        self.widget.ghost_vel_max_spin = self._build_double_spin(0.0, 1.0, 0.01, 0.45)
        self.widget.ghost_pitch_min_spin = self._build_double_spin(-24.0, 24.0, 0.5, 0.0)
        self.widget.ghost_pitch_max_spin = self._build_double_spin(-24.0, 24.0, 0.5, 0.0)
        self.widget.ghost_gate_slider = self._build_knob(0)

        _ghost_row = QWidget()
        _grl = QHBoxLayout(_ghost_row)
        _grl.setContentsMargins(0, 4, 0, 0)
        _grl.setSpacing(6)
        _grl.addWidget(self.widget.synth_ghost_check)
        for _lbl_txt, _spin in [
            ("Vel min", self.widget.ghost_vel_min_spin), ("Vel max", self.widget.ghost_vel_max_spin),
            ("Pitch min", self.widget.ghost_pitch_min_spin), ("Pitch max", self.widget.ghost_pitch_max_spin),
        ]:
            _grl.addWidget(_fl(_lbl_txt))
            _grl.addWidget(_spin)
        _grl.addWidget(self._build_knob_cell("Gate", self.widget.ghost_gate_slider))
        _grl.addStretch()
        _gtl.addWidget(_ghost_row)
        _gtl.addStretch()
        self.widget.tab_widget.addTab(_groove_tab, "Groove")

        _var_tab = QWidget()
        _vtl = QVBoxLayout(_var_tab)
        _vtl.setContentsMargins(8, 8, 8, 8)
        _vtl.setSpacing(4)

        self.widget.fill_slider = self._build_knob(35)
        self.widget.repeat_density_slider = self._build_knob(0)
        self.widget.repeat_span_slider = self._build_knob(15)
        self.widget.repeat_rate_slider = self._build_knob(35)
        self.widget.reverse_slider = self._build_knob(0)
        self.widget.kick_roll_density_slider = self._build_knob(0)
        self.widget.kick_roll_span_slider = self._build_knob(20)
        self.widget.kick_roll_contrast_slider = self._build_knob(55)
        self.widget.snare_stretch_density_slider = self._build_knob(0)
        self.widget.snare_stretch_span_slider = self._build_knob(35)
        self.widget.snare_stretch_amount_slider = self._build_knob(80)

        self.widget.snare_stretch_curve_combo = QComboBox()
        self.widget.snare_stretch_curve_combo.setObjectName("BreakGeneratorCombo")
        for option in SNARE_STRETCH_CURVE_OPTIONS:
            self.widget.snare_stretch_curve_combo.addItem(option.replace("_", " ").title(), option)

        _vtl.addWidget(self._build_knob_row([
            ("Fill", self.widget.fill_slider), ("Rpt dens.", self.widget.repeat_density_slider),
            ("Rpt span", self.widget.repeat_span_slider), ("Rpt rate", self.widget.repeat_rate_slider),
            ("Reverse", self.widget.reverse_slider), ("Roll", self.widget.kick_roll_density_slider),
        ]))

        _row2_w = QWidget()
        _row2_l = QHBoxLayout(_row2_w)
        _row2_l.setContentsMargins(0, 0, 0, 0)
        _row2_l.setSpacing(2)
        for _lbl, _knob in [
            ("Roll span", self.widget.kick_roll_span_slider), ("Roll cont.", self.widget.kick_roll_contrast_slider),
            ("Stretch", self.widget.snare_stretch_density_slider), ("Str. span", self.widget.snare_stretch_span_slider),
            ("Str. amt.", self.widget.snare_stretch_amount_slider),
        ]:
            _row2_l.addWidget(self._build_knob_cell(_lbl, _knob))
        _curve_cell = QWidget()
        _ccl = QVBoxLayout(_curve_cell)
        _ccl.setContentsMargins(4, 0, 2, 0)
        _ccl.setSpacing(2)
        _curve_lbl_w = QLabel("Vel curve")
        _curve_lbl_w.setObjectName("KnobLabel")
        _curve_lbl_w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.widget.snare_stretch_curve_combo.setMaximumWidth(90)
        _ccl.addWidget(_curve_lbl_w)
        _ccl.addWidget(self.widget.snare_stretch_curve_combo)
        _row2_l.addWidget(_curve_cell)
        _row2_l.addStretch()
        _vtl.addWidget(_row2_w)
        _vtl.addStretch()
        self.widget.tab_widget.addTab(_var_tab, "Variations")

        _pitch_tab = QWidget()
        _ptl = QVBoxLayout(_pitch_tab)
        _ptl.setContentsMargins(8, 8, 8, 8)
        _ptl.setSpacing(8)

        self.widget.pitch_mode_combo = QComboBox()
        self.widget.pitch_mode_combo.setObjectName("BreakGeneratorCombo")
        for option in PITCH_MODE_OPTIONS:
            self.widget.pitch_mode_combo.addItem(option.replace("_", " ").title(), option)
        self.widget.pitch_scope_combo = QComboBox()
        self.widget.pitch_scope_combo.setObjectName("BreakGeneratorCombo")
        for option in PITCH_SCOPE_OPTIONS:
            self.widget.pitch_scope_combo.addItem(option.replace("_", " ").capitalize(), option)
        self.widget.pitch_scale_combo = QComboBox()
        self.widget.pitch_scale_combo.setObjectName("BreakGeneratorCombo")
        for option in PITCH_SCALE_OPTIONS:
            self.widget.pitch_scale_combo.addItem(option.capitalize(), option)
        self.widget.pitch_root_combo = QComboBox()
        self.widget.pitch_root_combo.setObjectName("BreakGeneratorCombo")
        for index, note in enumerate(PITCH_NOTE_NAMES):
            self.widget.pitch_root_combo.addItem(note, index)
        self.widget.pitch_range_min_spin = self._build_double_spin(-24.0, 24.0, 1.0, -12.0)
        self.widget.pitch_range_max_spin = self._build_double_spin(-24.0, 24.0, 1.0, 12.0)
        self.widget.pitch_sequence_input = QLineEdit(DEFAULT_PITCH_SEQUENCE)
        self.widget.pitch_sequence_input.setObjectName("BreakGeneratorInput")
        self.widget.pitch_rate_combo = QComboBox()
        self.widget.pitch_rate_combo.setObjectName("BreakGeneratorCombo")
        for option in PITCH_RATE_OPTIONS:
            self.widget.pitch_rate_combo.addItem(option.replace("_", " ").capitalize(), option)
        self.widget.pitch_curve_combo = QComboBox()
        self.widget.pitch_curve_combo.setObjectName("BreakGeneratorCombo")
        for option in PITCH_CURVE_OPTIONS:
            self.widget.pitch_curve_combo.addItem(option.replace("_", " ").capitalize(), option)
        self.widget.pitch_curve_min_spin = self._build_double_spin(-12.0, 12.0, 1.0, -7.0)
        self.widget.pitch_curve_max_spin = self._build_double_spin(-12.0, 12.0, 1.0, 7.0)
        self.widget.pitch_amount_slider = self._build_knob(0)

        _pr1 = QWidget()
        _pr1l = QHBoxLayout(_pr1)
        _pr1l.setContentsMargins(0, 0, 0, 0)
        _pr1l.setSpacing(8)
        for _lbl_txt, _widget in [
            ("Mode", self.widget.pitch_mode_combo), ("Scope", self.widget.pitch_scope_combo),
            ("Scale", self.widget.pitch_scale_combo), ("Root", self.widget.pitch_root_combo),
        ]:
            _pr1l.addWidget(_fl(_lbl_txt))
            _pr1l.addWidget(_widget)
        _pr1l.addWidget(self._build_knob_cell("Amount", self.widget.pitch_amount_slider))
        _pr1l.addStretch()
        _ptl.addWidget(_pr1)

        _pr2 = QWidget()
        _pr2l = QHBoxLayout(_pr2)
        _pr2l.setContentsMargins(0, 0, 0, 0)
        _pr2l.setSpacing(8)
        for _lbl_txt, _widget in [
            ("Range min", self.widget.pitch_range_min_spin), ("Range max", self.widget.pitch_range_max_spin),
            ("Rate", self.widget.pitch_rate_combo),
        ]:
            _pr2l.addWidget(_fl(_lbl_txt))
            _pr2l.addWidget(_widget)
        _pr2l.addStretch()
        _ptl.addWidget(_pr2)

        _pr3 = QWidget()
        _pr3l = QHBoxLayout(_pr3)
        _pr3l.setContentsMargins(0, 0, 0, 0)
        _pr3l.setSpacing(8)
        for _lbl_txt, _widget in [
            ("Curve", self.widget.pitch_curve_combo),
            ("Curve min", self.widget.pitch_curve_min_spin), ("Curve max", self.widget.pitch_curve_max_spin),
        ]:
            _pr3l.addWidget(_fl(_lbl_txt))
            _pr3l.addWidget(_widget)
        _pr3l.addStretch()
        _ptl.addWidget(_pr3)

        _pr4 = QWidget()
        _pr4l = QHBoxLayout(_pr4)
        _pr4l.setContentsMargins(0, 0, 0, 0)
        _pr4l.setSpacing(8)
        _pr4l.addWidget(_fl("Sequence"))
        _pr4l.addWidget(self.widget.pitch_sequence_input, 1)
        _ptl.addWidget(_pr4)
        _ptl.addStretch()
        self.widget.tab_widget.addTab(_pitch_tab, "Pitch")

        _render_tab = QWidget()
        _rtl = QVBoxLayout(_render_tab)
        _rtl.setContentsMargins(8, 8, 8, 8)
        _rtl.setSpacing(4)

        self.widget.gate_slider = self._build_knob(100)
        self.widget.mono_choke_check = QCheckBox("Mono choke")
        self.widget.tail_mode_combo = self._build_combo(PATTERN_TAIL_MODE_LABELS)
        self.widget.tail_mode_combo.setMaximumWidth(110)
        tail_mode_index = self.widget.tail_mode_combo.findData(DEFAULT_PATTERN_TAIL_MODE)
        if tail_mode_index >= 0:
            self.widget.tail_mode_combo.setCurrentIndex(tail_mode_index)
        self.widget.sequence_max_len_spin = QSpinBox()
        self.widget.sequence_max_len_spin.setObjectName("BreakGeneratorSpin")
        self.widget.sequence_max_len_spin.setRange(1, 8)
        self.widget.sequence_max_len_spin.setValue(4)
        self.widget.sequence_role_lock_check = QCheckBox("Sequence role lock")
        self.widget.sequence_role_lock_check.setChecked(True)

        _render_row = QWidget()
        _rrl = QHBoxLayout(_render_row)
        _rrl.setContentsMargins(0, 0, 0, 0)
        _rrl.setSpacing(12)
        _rrl.addWidget(self._build_knob_cell("Gate", self.widget.gate_slider))
        _rrl.addWidget(self.widget.mono_choke_check)
        _tail_block = QHBoxLayout()
        _tail_block.setSpacing(6)
        _tail_block.addWidget(_fl("Tail"))
        _tail_block.addWidget(self.widget.tail_mode_combo)
        _rrl.addLayout(_tail_block)
        _seq_block = QHBoxLayout()
        _seq_block.setSpacing(6)
        _seq_block.addWidget(_fl("Seq. max"))
        _seq_block.addWidget(self.widget.sequence_max_len_spin)
        _rrl.addLayout(_seq_block)
        _rrl.addWidget(self.widget.sequence_role_lock_check)
        _rrl.addStretch()
        _rtl.addWidget(_render_row)
        _rtl.addStretch()
        self.widget.tab_widget.addTab(_render_tab, "Rendu")

        self._build_motifs_tab()

        self.widget.pattern_frame = QFrame()
        self.widget.pattern_frame.setObjectName("BreakGeneratorSection")
        pattern_layout = QVBoxLayout(self.widget.pattern_frame)
        pattern_layout.setContentsMargins(10, 10, 10, 10)
        pattern_layout.setSpacing(8)

        self.widget.pattern_title = QLabel("Pattern final")
        self.widget.pattern_title.setObjectName("BreakSectionTitle")
        self.widget.pattern_summary = QLabel("Aucun pattern genere.")
        self.widget.pattern_summary.setObjectName("BreakSectionHint")
        self.widget.pattern_summary.setWordWrap(True)
        self.widget.pattern_interaction_label = QLabel("")
        self.widget.pattern_interaction_label.setObjectName("BreakGeneratorInfo")
        self.widget.pattern_interaction_label.setWordWrap(True)

        # 3 lignes seulement : velocite / source / FX partent en tooltip de la
        # case Event, ce qui rend la grille carree et beaucoup plus compacte.
        self.widget.pattern_table = QTableWidget(3, 16)
        self.widget.pattern_table.setObjectName("BreakGeneratorTable")
        self.widget.pattern_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.widget.pattern_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.widget.pattern_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.widget.pattern_table.setAlternatingRowColors(False)
        self.widget.pattern_table.setWordWrap(False)
        self.widget.pattern_table.setVerticalHeaderLabels(PATTERN_ROW_LABELS)
        self.widget.pattern_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.widget.pattern_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.widget.pattern_table.horizontalHeader().setMinimumSectionSize(PATTERN_CELL_SIZE)
        self.widget.pattern_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.widget.pattern_table.setToolTip(
            "Clic gauche sur un Hit = jouer ce coup seul\n"
            "Clic droit sur un Hit = ouvrir la slice dans Decoupage\n"
            "Numeros : clic = jouer depuis ce step, glisser = selectionner une\n"
            "plage et la boucler, clic droit = figer ou exporter la selection\n"
            "Anc = imposer un type | Lock = garder ce step au prochain Generer"
        )
        self.widget.pattern_table.setFixedHeight(PATTERN_TABLE_HEIGHT)
        self.widget.pattern_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.widget.pattern_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Le defilement suit le playhead step par step, pas par a-coups d'un
        # ecran entier.
        self.widget.pattern_table.setHorizontalScrollMode(
            QTableWidget.ScrollMode.ScrollPerPixel
        )

        pattern_layout.addWidget(self.widget.pattern_title)
        pattern_layout.addWidget(self.widget.pattern_summary)
        pattern_layout.addWidget(self.widget.pattern_interaction_label)
        pattern_layout.addWidget(self.widget.pattern_table)

        layout.addLayout(header)
        layout.addWidget(self.widget.controls_frame)
        layout.addWidget(self.widget.tab_widget)
        layout.addWidget(self.widget.pattern_frame)

        root.addWidget(self.widget.container)
        self._apply_styles()
        self.widget._refresh_actions()
        self.widget._populate_pattern_table(None)

    def _build_motifs_tab(self) -> None:
        w = self.widget

        _motifs_tab = QWidget()
        _mtl = QVBoxLayout(_motifs_tab)
        _mtl.setContentsMargins(8, 8, 8, 8)
        _mtl.setSpacing(6)

        def _fl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("BreakGeneratorFieldLabel")
            return lbl

        # --- Éditeur de motif ---
        editor_frame = QFrame()
        editor_frame.setObjectName("BreakGeneratorSection")
        editor_l = QVBoxLayout(editor_frame)
        editor_l.setContentsMargins(8, 6, 8, 6)
        editor_l.setSpacing(4)

        editor_title = QLabel("Créer un motif")
        editor_title.setObjectName("BreakSectionTitle")
        editor_l.addWidget(editor_title)

        hint_lbl = QLabel("Actif en mode Hybrid — combinez avec le knob Motifs.")
        hint_lbl.setObjectName("BreakSectionHint")
        editor_l.addWidget(hint_lbl)

        steps_row = QHBoxLayout()
        steps_row.setContentsMargins(0, 0, 0, 0)
        steps_row.setSpacing(3)
        steps_row.addWidget(_fl("Steps :"))

        w.motif_step_buttons: list[QPushButton] = []
        for _i in range(8):
            _btn = QPushButton("·")
            _btn.setFixedSize(28, 28)
            _btn.setObjectName("MotifStepButton")
            steps_row.addWidget(_btn)
            w.motif_step_buttons.append(_btn)

        steps_row.addSpacing(8)
        steps_row.addWidget(_fl("Len :"))
        w.motif_length_spin = QSpinBox()
        w.motif_length_spin.setObjectName("BreakGeneratorSpin")
        w.motif_length_spin.setRange(4, 8)
        w.motif_length_spin.setValue(8)
        w.motif_length_spin.setFixedWidth(58)
        steps_row.addWidget(w.motif_length_spin)
        steps_row.addStretch()
        editor_l.addLayout(steps_row)

        props_row = QHBoxLayout()
        props_row.setContentsMargins(0, 0, 0, 0)
        props_row.setSpacing(8)

        props_row.addWidget(_fl("Nom :"))
        w.motif_name_input = QLineEdit()
        w.motif_name_input.setObjectName("BreakGeneratorInput")
        w.motif_name_input.setPlaceholderText("Motif 1")
        w.motif_name_input.setMaximumWidth(120)
        props_row.addWidget(w.motif_name_input)

        props_row.addWidget(_fl("Base :"))
        w.motif_base_prob_spin = QSpinBox()
        w.motif_base_prob_spin.setObjectName("BreakGeneratorSpin")
        w.motif_base_prob_spin.setRange(0, 100)
        w.motif_base_prob_spin.setValue(60)
        w.motif_base_prob_spin.setSuffix("%")
        w.motif_base_prob_spin.setFixedWidth(76)
        props_row.addWidget(w.motif_base_prob_spin)

        props_row.addWidget(_fl("Rôle :"))
        w.motif_role_combo = QComboBox()
        w.motif_role_combo.setObjectName("BreakGeneratorCombo")
        for _key, _label in _MOTIF_ROLE_OPTIONS:
            w.motif_role_combo.addItem(_label, _key)
        w.motif_role_combo.setFixedWidth(110)
        props_row.addWidget(w.motif_role_combo)

        props_row.addStretch()

        w.motif_add_button = QPushButton("+ Ajouter")
        w.motif_add_button.setObjectName("BreakGeneratorAction")
        props_row.addWidget(w.motif_add_button)
        editor_l.addLayout(props_row)

        _mtl.addWidget(editor_frame)

        # --- Table des motifs sauvegardés ---
        table_frame = QFrame()
        table_frame.setObjectName("BreakGeneratorSection")
        table_l = QVBoxLayout(table_frame)
        table_l.setContentsMargins(8, 6, 8, 6)
        table_l.setSpacing(4)

        table_title = QLabel("Motifs sauvegardés")
        table_title.setObjectName("BreakSectionTitle")
        table_l.addWidget(table_title)

        w.motifs_table = QTableWidget(0, 5)
        w.motifs_table.setObjectName("BreakGeneratorTable")
        w.motifs_table.setHorizontalHeaderLabels(("Nom", "Steps", "Rôle", "Base", ""))
        w.motifs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        w.motifs_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        w.motifs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        w.motifs_table.verticalHeader().setVisible(False)
        _mh = w.motifs_table.horizontalHeader()
        _mh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        _mh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        _mh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        _mh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        _mh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        w.motifs_table.setColumnWidth(4, 32)
        w.motifs_table.setMinimumHeight(80)
        w.motifs_table.setMaximumHeight(180)
        table_l.addWidget(w.motifs_table)
        _mtl.addWidget(table_frame)
        _mtl.addStretch()

        w.tab_widget.addTab(_motifs_tab, "Motifs")

    def _build_knob(self, value: int, *, default: int | None = None) -> KnobWidget:
        return KnobWidget(0, 100, value, default=default if default is not None else value)

    def _build_knob_cell(self, label: str, knob: KnobWidget) -> QWidget:
        cell = QWidget()
        cell.setObjectName("KnobCell")
        vbox = QVBoxLayout(cell)
        vbox.setContentsMargins(2, 0, 2, 0)
        vbox.setSpacing(0)

        name_lbl = QLabel(label)
        name_lbl.setObjectName("KnobLabel")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        val_lbl = QLabel(f"{knob.value()}%")
        val_lbl.setObjectName("KnobValue")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        knob.valueChanged.connect(lambda v, lbl=val_lbl: lbl.setText(f"{v}%"))

        vbox.addWidget(name_lbl)
        vbox.addWidget(knob, 0, Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(val_lbl)
        return cell

    def _build_knob_row(self, items: list[tuple[str, KnobWidget]]) -> QWidget:
        row = QWidget()
        row.setObjectName("KnobRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        for label, knob in items:
            h.addWidget(self._build_knob_cell(label, knob))
        h.addStretch()
        return row

    def _build_section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("BreakGeneratorSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("BreakSectionTitle")
        layout.addWidget(title_label)
        frame.content_layout = layout  # type: ignore[attr-defined]
        return frame

    def _build_combo(self, labels: dict[str, str]) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("BreakGeneratorCombo")
        for key, label in labels.items():
            combo.addItem(label, key)
        return combo

    def _build_double_spin(
        self, minimum: float, maximum: float, step: float, value: float
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName("BreakGeneratorSpin")
        spin.setRange(float(minimum), float(maximum))
        spin.setSingleStep(float(step))
        spin.setValue(float(value))
        spin.setDecimals(2 if step < 1.0 else 1 if step < 10.0 else 0)
        return spin

    def _add_labeled_widget(
        self,
        layout: QGridLayout,
        row: int,
        column: int,
        label: str,
        widget: QWidget,
        *,
        span: int = 1,
    ) -> None:
        label_widget = QLabel(label)
        label_widget.setObjectName("BreakGeneratorFieldLabel")
        layout.addWidget(label_widget, row, column)
        layout.addWidget(widget, row, column + 1, 1, span)

    def _connect_change_signal(self, widget: QWidget, callback) -> None:
        for candidate in ("valueChanged", "currentIndexChanged", "textChanged", "toggled"):
            if hasattr(widget, candidate):
                getattr(widget, candidate).connect(callback)
                return

    def _apply_styles(self) -> None:
        p = theme.manager.p
        # Fleches des combos / spins : Qt n'affiche plus ses indicateurs natifs
        # des que le widget est style, on les fournit donc en image.
        chevron_down = icon_qss_url("chevron-down", 12, p.TEXT_MUTED) or "none"
        chevron_up = icon_qss_url("chevron-up", 12, p.TEXT_MUTED) or "none"
        self.widget.setStyleSheet(
            f"""
            QWidget#BreakGeneratorRoot {{
                background: transparent;
            }}
            QFrame#BreakGeneratorFrame,
            QFrame#BreakGeneratorSection {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
            }}
            QLabel#BreakSectionTitle {{
                color: {p.TEXT};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel#BreakSectionHint,
            QLabel#BreakGeneratorInfo,
            QLabel#BreakGeneratorFieldLabel,
            QLabel#BreakGeneratorSeed {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#KnobLabel {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 500;
            }}
            QLabel#KnobValue {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            QPushButton#BreakGeneratorAction {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#BreakGeneratorAction:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#BreakGeneratorAction:disabled {{
                color: {p.TEXT_MUTED};
            }}
            QPushButton#BreakGeneratorAction[looping="true"] {{
                background: {p.BG_HOVER};
                border-color: {p.INFO};
                color: {p.INFO};
            }}
            QPushButton#BreakGeneratorAnchorButton {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 5px;
                min-height: 22px;
                max-height: 22px;
                font-size: 9px;
                font-weight: 700;
                padding: 0;
            }}
            QPushButton#BreakGeneratorAnchorButton:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            QPushButton#BreakGeneratorAnchorButton[anchorActive="true"] {{
                color: #f0c05a;
                border-color: #d1a142;
                background: #2a2220;
            }}
            QPushButton#BreakGeneratorAnchorButton[anchorKind="silence"][anchorActive="true"] {{
                color: #a9b4c7;
                border-color: #70839d;
                background: #1d232d;
            }}
            QPushButton#BreakGeneratorLockButton {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 5px;
                min-height: 22px;
                max-height: 22px;
                font-size: 9px;
                font-weight: 700;
                padding: 0;
            }}
            QPushButton#BreakGeneratorLockButton:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            QPushButton#BreakGeneratorLockButton[lockActive="true"] {{
                color: #f0c05a;
                border-color: #d1a142;
                background: #2a2220;
            }}
            QComboBox#BreakGeneratorCombo,
            QSpinBox#BreakGeneratorSpin,
            QDoubleSpinBox#BreakGeneratorSpin,
            QLineEdit#BreakGeneratorInput {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 4px 6px;
                min-height: 26px;
            }}
            /* Fleches : Qt ne dessine plus les indicateurs natifs des qu'on
               style le widget. On les redessine en triangles CSS. */
            QComboBox#BreakGeneratorCombo::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 16px;
                border: none;
                background: transparent;
            }}
            QComboBox#BreakGeneratorCombo::down-arrow {{
                image: {chevron_down};
                width: 11px;
                height: 11px;
                margin-right: 3px;
            }}
            QSpinBox#BreakGeneratorSpin::up-button,
            QDoubleSpinBox#BreakGeneratorSpin::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 16px;
                border: none;
                border-top-right-radius: 6px;
                background: transparent;
            }}
            QSpinBox#BreakGeneratorSpin::down-button,
            QDoubleSpinBox#BreakGeneratorSpin::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 16px;
                border: none;
                border-bottom-right-radius: 6px;
                background: transparent;
            }}
            QSpinBox#BreakGeneratorSpin::up-button:hover,
            QDoubleSpinBox#BreakGeneratorSpin::up-button:hover,
            QSpinBox#BreakGeneratorSpin::down-button:hover,
            QDoubleSpinBox#BreakGeneratorSpin::down-button:hover {{
                background: {p.BG_HOVER};
            }}
            QSpinBox#BreakGeneratorSpin::up-arrow,
            QDoubleSpinBox#BreakGeneratorSpin::up-arrow {{
                image: {chevron_up};
                width: 10px;
                height: 10px;
            }}
            QSpinBox#BreakGeneratorSpin::down-arrow,
            QDoubleSpinBox#BreakGeneratorSpin::down-arrow {{
                image: {chevron_down};
                width: 10px;
                height: 10px;
            }}
            QCheckBox {{
                color: {p.TEXT};
                spacing: 6px;
                font-size: 12px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 4px;
                border: 1px solid {p.BORDER_LIGHT};
                background: {p.BG_MEDIUM};
            }}
            QCheckBox::indicator:checked {{
                background: {p.INFO};
                border-color: {p.INFO};
            }}
            QTableWidget#BreakGeneratorTable {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                gridline-color: {p.BORDER};
            }}
            QHeaderView::section {{
                background: {p.BG_CARD};
                color: {p.TEXT_MUTED};
                border: none;
                border-bottom: 1px solid {p.BORDER};
                padding: 4px 6px;
            }}
            /* Zone du header au-dela de la derniere colonne + coin haut-gauche :
               sans ca Qt les peint en clair et ca ressort violemment. */
            QHeaderView {{
                background: {p.BG_MEDIUM};
                border: none;
            }}
            QTableCornerButton::section {{
                background: {p.BG_CARD};
                border: none;
                border-bottom: 1px solid {p.BORDER};
            }}
            QTableWidget#BreakGeneratorTable QHeaderView::section:vertical {{
                padding: 0 6px;
                font-size: 10px;
            }}
            QTableWidget#BreakGeneratorTable QHeaderView::section:horizontal {{
                padding: 3px 0;
                font-size: 10px;
            }}
            QTabWidget#BreakGeneratorTabs::pane {{
                border: 1px solid {p.BORDER};
                border-radius: 0 8px 8px 8px;
                background: {p.BG_CARD};
            }}
            QTabWidget#BreakGeneratorTabs > QTabBar::tab {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-bottom: none;
                border-radius: 6px 6px 0 0;
                padding: 5px 14px;
                font-size: 11px;
                font-weight: 600;
            }}
            QTabWidget#BreakGeneratorTabs > QTabBar::tab:selected {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border-color: {p.BORDER};
            }}
            QTabWidget#BreakGeneratorTabs > QTabBar::tab:hover:!selected {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
            }}
            QPushButton#MotifStepButton {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                font-size: 10px;
                font-weight: 700;
                padding: 0;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
            }}
            QPushButton#MotifStepButton:disabled {{
                color: {p.BORDER};
                border-color: transparent;
                background: transparent;
            }}
            QPushButton#MotifStepButton:hover:!disabled {{
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            """
        )
