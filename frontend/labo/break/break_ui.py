# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la construction visuelle du BreakWidget.
# - Isole le build UI, les metadonnees d'entete, les styles et l'etat
#   d'activation des boutons pour alleger la facade.
#
# LIENS CLES
# - frontend/labo/break/generator/ : generateur integre.
# - frontend/styles/theme.py       : couleurs dynamiques.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from backend.services.drum_analysis_service import (
    DEFAULT_QUANTIZE_GRID_DIVISION,
    DEFAULT_QUANTIZE_STRENGTH,
)
from frontend.styles import theme

from .generator import BreakGeneratorPanel


class BreakUIBuilder:
    """Construit l'UI et gere les etats visuels du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def _build_ui(self) -> None:
        self.widget.setObjectName("BreakRoot")
        self.widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.widget.setAcceptDrops(True)

        root = QVBoxLayout(self.widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setObjectName("BreakHeaderBar")
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(12, 8, 12, 8)
        hdr_l.setSpacing(6)

        self.widget.file_label = QLabel("Depose un break pour commencer")
        self.widget.file_label.setObjectName("BreakFileLabel")
        self.widget._meta_dot1 = QLabel("·")
        self.widget._meta_dot1.setObjectName("BreakMetaDot")
        self.widget._meta_dot1.setVisible(False)
        self.widget._meta_bpm = QLabel("")
        self.widget._meta_bpm.setObjectName("BreakMetaInfo")
        self.widget._meta_bpm.setVisible(False)
        self.widget._meta_dot2 = QLabel("·")
        self.widget._meta_dot2.setObjectName("BreakMetaDot")
        self.widget._meta_dot2.setVisible(False)
        self.widget._meta_loop = QLabel("preview en boucle")
        self.widget._meta_loop.setObjectName("BreakMetaInfo")
        self.widget._meta_loop.setVisible(False)

        hdr_l.addWidget(self.widget.file_label)
        hdr_l.addWidget(self.widget._meta_dot1)
        hdr_l.addWidget(self.widget._meta_bpm)
        hdr_l.addWidget(self.widget._meta_dot2)
        hdr_l.addWidget(self.widget._meta_loop)
        hdr_l.addStretch(1)

        tab_bar = QWidget()
        tab_bar.setObjectName("BreakTabBar")
        tab_l = QHBoxLayout(tab_bar)
        tab_l.setContentsMargins(0, 0, 0, 0)
        tab_l.setSpacing(0)

        self.widget._tab_btns = []
        for i, lbl in enumerate(("Decoupage", "Tempo", "Generateur")):
            btn = QPushButton(lbl)
            btn.setObjectName("BreakTab")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda checked=False, idx=i: self.widget._on_tab_clicked(idx))
            self.widget._tab_btns.append(btn)
            tab_l.addWidget(btn)
        tab_l.addStretch(1)

        def _icon_btn(text: str, name: str, tip: str, size: int = 28) -> QPushButton:
            b = QPushButton(text)
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setFixedSize(size, size)
            return b

        def _vline() -> QFrame:
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setObjectName("BreakToolbarSep")
            return f

        page_dc = QWidget()
        page_dc.setObjectName("BreakPageDecoupage")
        dc_l = QVBoxLayout(page_dc)
        dc_l.setContentsMargins(0, 0, 0, 0)
        dc_l.setSpacing(0)

        self.widget.waveform_host = QWidget()
        self.widget.waveform_host.setObjectName("BreakWaveformHost")
        self.widget.waveform_host.setAcceptDrops(True)
        self.widget.waveform_host.installEventFilter(self.widget)
        self.widget.waveform_layout = QVBoxLayout(self.widget.waveform_host)
        self.widget.waveform_layout.setContentsMargins(0, 0, 0, 0)
        self.widget.waveform_layout.setSpacing(0)
        self.widget.waveform_host.setMinimumHeight(130)

        toolbar = QWidget()
        toolbar.setObjectName("BreakToolbar")
        tb_l = QHBoxLayout(toolbar)
        tb_l.setContentsMargins(8, 4, 8, 4)
        tb_l.setSpacing(3)

        self.widget._play_btn = _icon_btn("▶", "BreakIconBtn", "Lecture")
        self.widget._pause_btn = _icon_btn("⏸", "BreakIconBtn", "Pause")
        self.widget._stop_btn = _icon_btn("■", "BreakIconBtn", "Stop")
        self.widget._loop_btn = _icon_btn("🔁", "BreakIconBtnToggle", "Boucle")
        self.widget._loop_btn.setCheckable(True)
        self.widget._loop_btn.setChecked(True)

        self.widget.split_button = _icon_btn("✂", "BreakIconBtn", "Decoupage automatique")
        self.widget.analyze_button = _icon_btn("📊", "BreakIconBtn", "Analyser les slices")
        self.widget._fill_btn = _icon_btn(
            "↦",
            "BreakIconBtn",
            "Propager l'intervalle selectionne jusqu'a la fin\n"
            "(selectionne d'abord une slice ou clique sur un marqueur)",
        )
        self.widget._undo_btn = _icon_btn("↩", "BreakIconBtn", "Annuler")

        self.widget._slices_label = QLabel("")
        self.widget._slices_label.setObjectName("BreakSlicesCount")

        tb_l.addWidget(self.widget._play_btn)
        tb_l.addWidget(self.widget._pause_btn)
        tb_l.addWidget(self.widget._stop_btn)
        tb_l.addWidget(self.widget._loop_btn)
        tb_l.addWidget(_vline())
        tb_l.addWidget(self.widget.split_button)
        tb_l.addWidget(self.widget.analyze_button)
        tb_l.addWidget(self.widget._fill_btn)
        tb_l.addWidget(_vline())
        tb_l.addWidget(self.widget._undo_btn)
        tb_l.addStretch(1)
        tb_l.addWidget(self.widget._slices_label)

        self.widget._hits_scroll = QScrollArea()
        self.widget._hits_scroll.setObjectName("BreakHitsScroll")
        self.widget._hits_scroll.setWidgetResizable(True)
        self.widget._hits_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.widget._hits_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.widget.hits_container = QWidget()
        self.widget.hits_container.setObjectName("BreakHitsContainer")
        self.widget.hits_vbox = QVBoxLayout(self.widget.hits_container)
        self.widget.hits_vbox.setContentsMargins(0, 0, 0, 0)
        self.widget.hits_vbox.setSpacing(2)
        self.widget.hits_vbox.addStretch(1)
        self.widget._hits_scroll.setWidget(self.widget.hits_container)

        self.widget._empty_label = QLabel("Lance d'abord l'analyse du break.")
        self.widget._empty_label.setObjectName("BreakEmptyLabel")
        self.widget._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.widget._empty_label.setWordWrap(True)

        self.widget.status_label = QLabel("")
        self.widget.status_label.setObjectName("BreakStatus")
        self.widget.status_label.setWordWrap(True)
        self.widget.status_label.setContentsMargins(8, 3, 8, 3)

        dc_l.addWidget(self.widget.waveform_host, 2)
        dc_l.addWidget(toolbar)
        dc_l.addWidget(self.widget._hits_scroll, 1)
        dc_l.addWidget(self.widget._empty_label)
        dc_l.addWidget(self.widget.status_label)

        page_tp = QWidget()
        page_tp.setObjectName("BreakPageTempo")
        tp_l = QVBoxLayout(page_tp)
        tp_l.setContentsMargins(12, 10, 12, 10)
        tp_l.setSpacing(10)

        pb_row = QHBoxLayout()
        pb_row.setSpacing(3)

        self.widget._tp_play_btn = _icon_btn("▶", "BreakIconBtn", "Lecture preview")
        self.widget._tp_stop_btn = _icon_btn("■", "BreakIconBtn", "Stop preview")

        self.widget._tp_loop_btn = _icon_btn("🔁", "BreakIconBtnToggle", "Boucle")
        self.widget._tp_loop_btn.setCheckable(True)
        self.widget._tp_loop_btn.setChecked(True)
        self.widget._tp_rev_btn = _icon_btn("↩", "BreakIconBtnToggle", "Reverse")
        self.widget._tp_rev_btn.setCheckable(True)
        self.widget._tp_pp_btn = _icon_btn("↔", "BreakIconBtnToggle", "Ping-pong")
        self.widget._tp_pp_btn.setCheckable(True)
        self.widget._tp_once_btn = _icon_btn("▷", "BreakIconBtnToggle", "One-shot")
        self.widget._tp_once_btn.setCheckable(True)

        self.widget._tp_mode_group = QButtonGroup(self.widget)
        self.widget._tp_mode_group.setExclusive(True)
        for _b in (
            self.widget._tp_loop_btn,
            self.widget._tp_rev_btn,
            self.widget._tp_pp_btn,
            self.widget._tp_once_btn,
        ):
            self.widget._tp_mode_group.addButton(_b)

        pb_row.addWidget(self.widget._tp_play_btn)
        pb_row.addWidget(self.widget._tp_stop_btn)
        pb_row.addWidget(_vline())
        pb_row.addWidget(self.widget._tp_loop_btn)
        pb_row.addWidget(self.widget._tp_rev_btn)
        pb_row.addWidget(self.widget._tp_pp_btn)
        pb_row.addWidget(self.widget._tp_once_btn)
        pb_row.addStretch(1)

        fields_row = QHBoxLayout()
        fields_row.setSpacing(14)
        fields_row.setContentsMargins(0, 0, 0, 0)

        def _field_col(label_text: str, widget) -> QVBoxLayout:
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setObjectName("BreakFieldLabel")
            col.addWidget(lbl)
            col.addWidget(widget)
            return col

        self.widget.bpm_spin = QDoubleSpinBox()
        self.widget.bpm_spin.setObjectName("BreakSpin")
        self.widget.bpm_spin.setRange(40.0, 300.0)
        self.widget.bpm_spin.setDecimals(1)
        self.widget.bpm_spin.setSingleStep(1.0)
        self.widget.bpm_spin.setValue(120.0)
        self.widget.bpm_spin.setFixedWidth(80)
        self.widget.bpm_spin.valueChanged.connect(self.widget._refresh_quantized_projection)

        self.widget.grid_combo = QComboBox()
        self.widget.grid_combo.setObjectName("BreakCombo")
        self.widget.grid_combo.addItem("1/8", 8)
        self.widget.grid_combo.addItem("1/16", 16)
        self.widget.grid_combo.addItem("1/32", 32)
        _gidx = self.widget.grid_combo.findData(DEFAULT_QUANTIZE_GRID_DIVISION)
        if _gidx >= 0:
            self.widget.grid_combo.setCurrentIndex(_gidx)
        self.widget.grid_combo.currentIndexChanged.connect(self.widget._refresh_quantized_projection)

        self.widget.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.widget.strength_slider.setObjectName("BreakSlider")
        self.widget.strength_slider.setRange(0, 100)
        self.widget.strength_slider.setValue(int(round(DEFAULT_QUANTIZE_STRENGTH * 100)))
        self.widget.strength_slider.setFixedWidth(110)
        self.widget.strength_slider.valueChanged.connect(self.widget._on_strength_changed)
        self.widget.strength_slider.valueChanged.connect(self.widget._refresh_quantized_projection)
        self.widget.strength_value = QLabel(
            f"{int(round(DEFAULT_QUANTIZE_STRENGTH * 100))}%"
        )
        self.widget.strength_value.setObjectName("BreakFieldValue")
        force_inner = QWidget()
        force_inner_l = QHBoxLayout(force_inner)
        force_inner_l.setContentsMargins(0, 0, 0, 0)
        force_inner_l.setSpacing(4)
        force_inner_l.addWidget(self.widget.strength_slider)
        force_inner_l.addWidget(self.widget.strength_value)

        fields_row.addLayout(_field_col("BPM", self.widget.bpm_spin))
        fields_row.addLayout(_field_col("Grille", self.widget.grid_combo))
        fields_row.addLayout(_field_col("Force", force_inner))
        fields_row.addStretch(1)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(4)
        actions_row.setContentsMargins(0, 0, 0, 0)

        self.widget.quantize_preview_button = QPushButton("▶  Preview tempo")
        self.widget.quantize_preview_button.setObjectName("BreakIconLabelBtn")
        self.widget.quantize_preview_button.setToolTip("Previsualiser le break quantise")
        self.widget.quantize_preview_button.clicked.connect(self.widget._preview_quantized_break)

        self.widget.quantize_button = QPushButton("⊾  Generer artefact")
        self.widget.quantize_button.setObjectName("BreakIconLabelBtn")
        self.widget.quantize_button.setToolTip("Creer un artefact du break quantise")
        self.widget.quantize_button.clicked.connect(self.widget._create_quantized_preview)

        actions_row.addWidget(self.widget.quantize_preview_button)
        actions_row.addWidget(self.widget.quantize_button)
        actions_row.addStretch(1)

        tp_l.addLayout(pb_row)
        tp_l.addLayout(fields_row)
        tp_l.addLayout(actions_row)
        tp_l.addStretch(1)

        page_gn = QWidget()
        page_gn.setObjectName("BreakPageGenerateur")
        gn_l = QVBoxLayout(page_gn)
        gn_l.setContentsMargins(0, 0, 0, 0)
        gn_l.setSpacing(0)
        self.widget.generator_panel = BreakGeneratorPanel(
            self.widget.app_context,
            self.widget._break_service,
        )
        gn_l.addWidget(self.widget.generator_panel)

        self.widget._pages = [page_dc, page_tp, page_gn]
        self.widget._stack = QStackedWidget()
        for pg in self.widget._pages:
            self.widget._stack.addWidget(pg)
        self.widget._stack.setCurrentIndex(0)

        root.addWidget(hdr)
        root.addWidget(tab_bar)
        root.addWidget(self.widget._stack, 1)

        self._apply_styles()
        self._refresh_actions()

    def _on_tab_clicked(self, idx: int) -> None:
        for i, btn in enumerate(self.widget._tab_btns):
            btn.setChecked(i == idx)
        self.widget._stack.setCurrentIndex(idx)

    def _update_header_meta(self) -> None:
        r = self.widget._analysis_result
        has_bpm = r is not None and r.tempo_bpm > 1.0
        self.widget._meta_dot1.setVisible(has_bpm)
        self.widget._meta_bpm.setVisible(has_bpm)
        if has_bpm:
            self.widget._meta_bpm.setText(f"{r.tempo_bpm:.1f} BPM")
        has_file = bool(self.widget._current_path)
        self.widget._meta_dot2.setVisible(has_file)
        self.widget._meta_loop.setVisible(has_file)

    def _update_slices_label(self) -> None:
        r = self.widget._analysis_result
        n = len(r.slices) if r is not None else 0
        self.widget._slices_label.setText(f"{n} slices" if n else "")

    def _refresh_actions(self) -> None:
        has_path = bool(self.widget._current_path)
        ready = self.widget._waveform_ready()
        analyzed = self.widget._analysis_result is not None
        can_quantize = analyzed and len(self.widget._quantized_slices) >= 2
        self.widget._play_btn.setEnabled(has_path and ready)
        self.widget._pause_btn.setEnabled(has_path and ready)
        self.widget._stop_btn.setEnabled(has_path and ready)
        self.widget.split_button.setEnabled(has_path and ready)
        self.widget.analyze_button.setEnabled(
            bool(self.widget._current_path) and bool(self.widget._get_current_markers())
        )
        self.widget._fill_btn.setEnabled(self.widget._has_valid_fill_interval())
        self.widget._tp_play_btn.setEnabled(can_quantize)
        self.widget._tp_stop_btn.setEnabled(can_quantize)
        self.widget.bpm_spin.setEnabled(analyzed)
        self.widget.grid_combo.setEnabled(analyzed)
        self.widget.strength_slider.setEnabled(analyzed)
        self.widget.quantize_preview_button.setEnabled(can_quantize)
        self.widget.quantize_button.setEnabled(can_quantize)

    def _apply_styles(self) -> None:
        p = theme.manager.p
        accent = getattr(p, "ACCENT", p.INFO)
        self.widget.setStyleSheet(
            f"""
            QWidget#BreakRoot {{
                background: {p.BG_MEDIUM};
            }}
            QWidget#BreakHeaderBar {{
                background: {p.BG_CARD};
                border-bottom: 1px solid {p.BORDER};
            }}
            QLabel#BreakFileLabel {{
                color: {p.TEXT};
                font-size: 13px;
                font-weight: 500;
            }}
            QLabel#BreakMetaDot {{
                color: {p.BORDER_LIGHT};
                font-size: 12px;
            }}
            QLabel#BreakMetaInfo {{
                color: {p.TEXT_MUTED};
                font-size: 12px;
            }}
            QWidget#BreakTabBar {{
                background: {p.BG_CARD};
                border-bottom: 1px solid {p.BORDER};
            }}
            QPushButton#BreakTab {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: none;
                border-bottom: 2px solid transparent;
                border-radius: 0;
                padding: 7px 16px;
                font-size: 13px;
            }}
            QPushButton#BreakTab:checked {{
                color: {p.TEXT};
                border-bottom: 2px solid {p.TEXT};
                font-weight: 500;
            }}
            QPushButton#BreakTab:hover:!checked {{
                color: {p.TEXT};
                background: {p.BG_HOVER};
            }}
            QWidget#BreakToolbar {{
                background: {p.BG_CARD};
                border-bottom: 1px solid {p.BORDER};
            }}
            QPushButton#BreakIconBtn {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                font-size: 11px;
                padding: 0;
            }}
            QPushButton#BreakIconBtn:hover {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#BreakIconBtn:disabled {{
                color: {p.BORDER};
                border-color: {p.BORDER};
            }}
            QPushButton#BreakIconBtnToggle {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                font-size: 11px;
                padding: 0;
            }}
            QPushButton#BreakIconBtnToggle:checked {{
                background: {accent}22;
                color: {accent};
                border-color: {accent};
            }}
            QPushButton#BreakIconBtnToggle:hover:!checked {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
                border-color: {p.BORDER_LIGHT};
            }}
            QFrame#BreakToolbarSep {{
                background: {p.BORDER};
                max-width: 1px;
                margin: 4px 2px;
            }}
            QLabel#BreakSlicesCount {{
                color: {p.TEXT_MUTED};
                font-size: 12px;
            }}
            QWidget#BreakWaveformHost {{
                background: transparent;
                border: 1px dashed {p.BORDER};
                border-radius: 0;
            }}
            QWidget#BreakWaveformHost[dropActive="true"] {{
                background: {p.BG_CARD};
                border-color: {p.INFO};
            }}
            QScrollArea#BreakHitsScroll {{
                background: transparent;
                border: none;
            }}
            QWidget#BreakHitsContainer {{
                background: transparent;
            }}
            QLabel#BreakEmptyLabel {{
                color: {p.TEXT_MUTED};
                font-size: 12px;
                padding: 20px;
            }}
            QLabel#BreakStatus {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QFrame#BreakHitRow {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 7px;
            }}
            QFrame#BreakHitRow:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QFrame#BreakHitRow[selected="true"] {{
                background: {p.BG_HOVER};
                border-color: {accent};
            }}
            QScrollArea#BreakHitsScroll QWidget#BreakHitsContainer {{
                background: transparent;
            }}
            QWidget#BreakHitRadios {{
                background: transparent;
            }}
            QRadioButton#BreakHitRadio {{
                color: {p.TEXT_MUTED};
                font-size: 9px;
                spacing: 1px;
                padding: 0 1px;
            }}
            QRadioButton#BreakHitRadio:checked {{
                color: {p.TEXT};
                font-weight: 700;
            }}
            QRadioButton#BreakHitRadio::indicator {{
                width: 9px;
                height: 9px;
                border-radius: 5px;
                border: 1px solid {p.BORDER_LIGHT};
                background: {p.BG_MEDIUM};
            }}
            QRadioButton#BreakHitRadio::indicator:hover {{
                border-color: {p.TEXT_MUTED};
            }}
            QRadioButton#BreakHitRadio::indicator:checked {{
                background: {accent};
                border-color: {accent};
            }}
            QComboBox#BreakCombo,
            QDoubleSpinBox#BreakSpin {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 3px 7px;
                min-height: 26px;
            }}
            QSlider#BreakSlider::groove:horizontal {{
                background: {p.BORDER};
                height: 4px;
                border-radius: 2px;
            }}
            QSlider#BreakSlider::handle:horizontal {{
                background: {p.TEXT};
                width: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }}
            QPushButton#BreakIconLabelBtn {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton#BreakIconLabelBtn:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
                color: {p.TEXT};
            }}
            QPushButton#BreakIconLabelBtn:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER};
            }}
            """
        )
