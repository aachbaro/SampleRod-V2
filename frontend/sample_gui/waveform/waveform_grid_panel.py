# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Table de commande du decoupage au tempo. La grille se pose des l'ouverture
#   et se REGLE EN DIRECT : chaque changement remplace la grille au lieu de
#   l'empiler, jusqu'a ce qu'on valide ou qu'on annule.
#
# LES TROIS GESTES
# - Decalage : cale le depart de la grille. Le debut d'un pattern est rarement
#   net au tout debut d'un enregistrement ; on pose d'abord, on cale ensuite.
#   Un decalage d'une tranche entiere redonne la meme grille -> le slider n'a
#   besoin que d'une plage de +/- une tranche.
# - Tranche : la longueur d'une coupe, en steps.
# - Caler sur la selection : on selectionne un bout dont on est SUR du nombre
#   de steps, et le BPM s'en deduit. Plus fiable que de deviner a l'oreille ;
#   ensuite on subdivise autant qu'on veut, la grille reste calee.
#
# FENETRE
# - Qt.Tool et non Popup : un popup se ferme au premier clic sur la waveform,
#   ce qui interdirait justement de regarder le resultat en reglant.
#
# LIENS CLES
# - waveform_grid.py         : le calcul pur (positions, tempo, translation)
# - waveform_grid_session.py : l'etat "grille en cours de reglage"
# - waveform_markers.py      : la pose effective
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from frontend.styles import theme

from .waveform_grid import bpm_from_span, grid_marker_times, slice_duration_s
from .waveform_grid_session import GridSettings

# Raccourcis de longueur : la plupart du temps on veut des mesures entieres.
_PRESETS: tuple[tuple[str, int], ...] = (
    ("1 temps", 4),
    ("1 mesure", 16),
    ("2 mesures", 32),
    ("4 mesures", 64),
)

# Nudges fins du decalage, en millisecondes.
_NUDGES: tuple[int, ...] = (-50, -5, 5, 50)


class WaveformGridPanel(QFrame):
    """Table de commande du decoupage au tempo, reglable en direct."""

    settingsChanged = Signal(object)   # GridSettings
    committed = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("WaveformGridPanel")
        self.setWindowTitle("Decouper au tempo")
        self._origin_s = 0.0
        self._duration_s = 0.0
        self._selection_s = 0.0
        self._live = False
        self._build_ui()
        self._apply_styles()
        theme.manager.themeChanged.connect(lambda *_a: self._apply_styles())

    # -- Construction ---------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("Decouper au tempo")
        title.setObjectName("WaveformGridTitle")
        root.addWidget(title)

        fields = QGridLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(8)
        fields.setVerticalSpacing(6)

        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setObjectName("WaveformGridSpin")
        self.bpm_spin.setRange(20.0, 400.0)
        self.bpm_spin.setDecimals(2)
        self.bpm_spin.setSingleStep(0.5)
        self.bpm_spin.setValue(120.0)
        self.bpm_spin.setFixedWidth(96)
        self.bpm_spin.valueChanged.connect(self._on_shape_changed)

        self.steps_spin = QSpinBox()
        self.steps_spin.setObjectName("WaveformGridSpin")
        self.steps_spin.setRange(1, 256)
        self.steps_spin.setValue(16)
        self.steps_spin.setFixedWidth(96)
        self.steps_spin.setToolTip(
            "Longueur d'une tranche, en steps.\n"
            "1 step = une double-croche. 16 = une mesure a 4/4."
        )
        self.steps_spin.valueChanged.connect(self._on_shape_changed)

        fields.addWidget(self._label("BPM"), 0, 0)
        fields.addWidget(self.bpm_spin, 0, 1)
        fields.addWidget(self._label("Tranche"), 1, 0)
        fields.addWidget(self.steps_spin, 1, 1)
        root.addLayout(fields)

        presets = QHBoxLayout()
        presets.setContentsMargins(0, 0, 0, 0)
        presets.setSpacing(4)
        for label, steps in _PRESETS:
            button = QPushButton(label)
            button.setObjectName("WaveformGridPreset")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, value=steps: self.steps_spin.setValue(value)
            )
            presets.addWidget(button)
        root.addLayout(presets)

        # -- Caler le tempo sur une selection
        self.fit_button = QPushButton("Caler sur la selection")
        self.fit_button.setObjectName("WaveformGridPreset")
        self.fit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fit_button.setToolTip(
            "Selectionne un passage dont tu es sur du nombre de steps\n"
            "(celui du champ Tranche) : le BPM s'en deduit."
        )
        self.fit_button.clicked.connect(self._fit_to_selection)
        root.addWidget(self.fit_button)

        # -- Decalage du depart
        root.addWidget(self._label("Decalage du depart"))
        self.offset_slider = QSlider(Qt.Orientation.Horizontal)
        self.offset_slider.setObjectName("WaveformGridSlider")
        self.offset_slider.setRange(-500, 500)      # ms, recalibre par _sync_offset_range
        self.offset_slider.setValue(0)
        self.offset_slider.setToolTip(
            "Fait glisser TOUTE la grille d'un bloc, sans la reconstruire."
        )
        self.offset_slider.valueChanged.connect(self._on_offset_changed)
        root.addWidget(self.offset_slider)

        nudges = QHBoxLayout()
        nudges.setContentsMargins(0, 0, 0, 0)
        nudges.setSpacing(4)
        for delta_ms in _NUDGES:
            button = QPushButton(f"{delta_ms:+d} ms")
            button.setObjectName("WaveformGridPreset")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, value=delta_ms: self._nudge_offset(value)
            )
            nudges.addWidget(button)
        self.offset_reset = QPushButton("0")
        self.offset_reset.setObjectName("WaveformGridPreset")
        self.offset_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.offset_reset.setToolTip("Remet le decalage a zero.")
        self.offset_reset.clicked.connect(lambda: self.offset_slider.setValue(0))
        nudges.addWidget(self.offset_reset)
        root.addLayout(nudges)

        self.preview_label = QLabel("")
        self.preview_label.setObjectName("WaveformGridPreview")
        self.preview_label.setWordWrap(True)
        root.addWidget(self.preview_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setObjectName("WaveformGridPreset")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._emit_cancel)
        actions.addWidget(self.cancel_button)

        self.apply_button = QPushButton("Valider")
        self.apply_button.setObjectName("WaveformGridApply")
        self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button.clicked.connect(self._emit_commit)
        actions.addWidget(self.apply_button, 1)
        root.addLayout(actions)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("WaveformGridLabel")
        return label

    # -- API ------------------------------------------------------------------
    def prepare(
        self,
        *,
        origin_s: float,
        duration_s: float,
        bpm: float | None = None,
        selection_s: float = 0.0,
    ) -> None:
        """Renseigne le contexte courant avant d'afficher le panneau."""
        self._origin_s = float(origin_s or 0.0)
        self._duration_s = float(duration_s or 0.0)
        self.set_selection_span(selection_s)
        if bpm and float(bpm) > 1.0:
            self.bpm_spin.blockSignals(True)
            self.bpm_spin.setValue(float(bpm))
            self.bpm_spin.blockSignals(False)
        self.offset_slider.blockSignals(True)
        self.offset_slider.setValue(0)
        self.offset_slider.blockSignals(False)
        self._sync_offset_range()
        self._refresh_preview()

    def set_selection_span(self, span_s: float) -> None:
        """Duree de la selection courante (0 s'il n'y en a pas)."""
        self._selection_s = max(0.0, float(span_s or 0.0))
        self.fit_button.setEnabled(self._selection_s > 0.0)

    def settings(self) -> GridSettings:
        return GridSettings(
            bpm=float(self.bpm_spin.value()),
            steps_per_slice=int(self.steps_spin.value()),
            offset_s=self.offset_slider.value() / 1000.0,
        )

    def set_live(self, live: bool) -> None:
        """Active l'emission des changements (evite les emissions au montage)."""
        self._live = bool(live)

    # -- Interne --------------------------------------------------------------
    def _emit_settings(self) -> None:
        if self._live:
            self.settingsChanged.emit(self.settings())

    def _on_shape_changed(self, *_args) -> None:
        # Changer BPM ou tranche change la longueur de coupe : la plage utile
        # du decalage suit.
        self._sync_offset_range()
        self._refresh_preview()
        self._emit_settings()

    def _on_offset_changed(self, *_args) -> None:
        self._refresh_preview()
        self._emit_settings()

    def _nudge_offset(self, delta_ms: int) -> None:
        self.offset_slider.setValue(self.offset_slider.value() + int(delta_ms))

    def _sync_offset_range(self) -> None:
        """Cadre le slider sur +/- une tranche.

        Au-dela, on retombe sur la meme grille decalee d'une coupe entiere :
        laisser plus de course n'apporterait rien et rendrait le reglage fin
        impossible a la souris.
        """
        slice_s = slice_duration_s(
            float(self.bpm_spin.value()), int(self.steps_spin.value())
        )
        span_ms = int(round(max(slice_s, 0.05) * 1000.0))
        current = self.offset_slider.value()
        self.offset_slider.blockSignals(True)
        self.offset_slider.setRange(-span_ms, span_ms)
        self.offset_slider.setValue(max(-span_ms, min(span_ms, current)))
        self.offset_slider.blockSignals(False)

    def _fit_to_selection(self) -> None:
        """Deduit le BPM de la selection, supposee faire `steps` steps."""
        if self._selection_s <= 0.0:
            return
        steps = int(self.steps_spin.value())
        bpm = bpm_from_span(self._selection_s, steps)
        if bpm < self.bpm_spin.minimum() or bpm > self.bpm_spin.maximum():
            self.preview_label.setText(
                f"Tempo deduit hors plage ({bpm:.1f} BPM) — "
                f"verifie le nombre de steps."
            )
            return
        self.bpm_spin.setValue(bpm)   # declenche _on_shape_changed

    def _emit_commit(self) -> None:
        self.close()
        self.committed.emit()

    def _emit_cancel(self) -> None:
        self.close()
        self.cancelled.emit()

    def _refresh_preview(self, *_args) -> None:
        settings = self.settings()
        length_s = slice_duration_s(settings.bpm, settings.steps_per_slice)
        planned = self._planned_times(settings)
        count = len(planned)
        if count <= 0:
            self.preview_label.setText("Rien a decouper depuis ce point.")
            self.apply_button.setEnabled(False)
            return
        self.apply_button.setEnabled(True)
        anchor = self._origin_s + settings.offset_s
        offset_note = ""
        if abs(settings.offset_s) > 1e-6:
            offset_note = f" ({settings.offset_s * 1000:+.0f} ms)"
        # La grille rayonne des deux cotes de l'ancrage : on annonce ce qu'il y
        # a avant, sinon on croit que le decoupage commence a ce point.
        before = sum(1 for t in planned if t < anchor - 1e-6)
        spread = f"{before} avant / {max(count - before, 0)} a partir de l'ancrage"
        self.preview_label.setText(
            f"Ancrage a {anchor:.3f}s{offset_note} — {count} marqueur(s) "
            f"({spread}), tranches de {length_s:.3f}s."
        )

    def _planned_times(self, settings: GridSettings) -> list[float]:
        """Positions que produiraient ces reglages (pour l'apercu seulement)."""
        return grid_marker_times(
            origin_s=self._origin_s + settings.offset_s,
            bpm=settings.bpm,
            steps_per_slice=settings.steps_per_slice,
            duration_s=self._duration_s,
        )

    def closeEvent(self, event):
        # Fermer la fenetre sans choisir vaut abandon : on ne laisse pas une
        # grille a moitie reglee derriere soi.
        super().closeEvent(event)

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QFrame#WaveformGridPanel {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#WaveformGridTitle {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#WaveformGridLabel {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#WaveformGridPreview {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QDoubleSpinBox#WaveformGridSpin,
            QSpinBox#WaveformGridSpin {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 3px 6px;
                min-height: 24px;
            }}
            QSlider#WaveformGridSlider::groove:horizontal {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER};
                border-radius: 3px;
                height: 6px;
            }}
            QSlider#WaveformGridSlider::handle:horizontal {{
                background: {p.TEXT};
                border-radius: 6px;
                width: 12px;
                margin: -4px 0;
            }}
            QPushButton#WaveformGridPreset {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
                padding: 3px 6px;
                font-size: 10px;
            }}
            QPushButton#WaveformGridPreset:hover {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
            }}
            QPushButton#WaveformGridPreset:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER};
            }}
            QPushButton#WaveformGridApply {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#WaveformGridApply:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#WaveformGridApply:disabled {{
                color: {p.TEXT_MUTED};
            }}
            """
        )
