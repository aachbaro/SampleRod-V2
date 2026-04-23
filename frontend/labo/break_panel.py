# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Panneau de correction manuelle des hits detectes par le drum analyzer.
# - Affiche la liste des slices, permet la lecture et la re-classification.
# - Bouton "re-analyser depuis les markers" pour forcer une nouvelle passe
#   avec les markers courants du waveform tool.
#
# LIENS CLES
# - frontend/labo/labo_widget.py  (ajout de l'onglet Break)
# - frontend/labo/waveform_tool.py  (signal analysisResultChanged)
# - backend/services/drum_analysis_service.py  (reanalyze_from_markers)
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace

import soundfile as sf
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.services.drum_analysis_service import DrumAnalysisResult, DrumSlice
from frontend.styles import theme

logger = logging.getLogger("break_panel")

# ── Hit type catalogue ─────────────────────────────────────────────────────────

HIT_LABELS: tuple[str, ...] = (
    "kick", "kick_ghost",
    "snare", "snare_ghost", "snare_ruff", "clap",
    "closed_hat", "open_hat",
    "crash", "ride", "tom", "perc",
)

HIT_SHORT: dict[str, str] = {
    "kick": "K",  "kick_ghost": "Kg",
    "snare": "S", "snare_ghost": "Sg", "snare_ruff": "Rf", "clap": "C",
    "closed_hat": "HC", "open_hat": "HO",
    "crash": "Cr", "ride": "Rd", "tom": "T", "perc": "P",
}

# Dark-mode colours (softened to blend with SampleRod palette)
HIT_COLOR: dict[str, str] = {
    "kick": "#d46666",       "kick_ghost": "#b04040",
    "snare": "#6699cc",      "snare_ghost": "#4a7aaa", "snare_ruff": "#5588bb", "clap": "#7ab4e0",
    "closed_hat": "#5caa5c", "open_hat": "#3c8a3c",
    "crash": "#c8a850",      "ride": "#a88c38", "tom": "#9966cc", "perc": "#cc8855",
}


def _hit_color(label: str) -> str:
    return HIT_COLOR.get(label, "#6b7280")


def _play_slice(source_path: str, start_s: float, end_s: float) -> None:
    """Lecture non-bloquante d'une slice via sounddevice."""
    def _run():
        try:
            import sounddevice as sd  # lazy import
            audio, sr = sf.read(source_path, dtype="float32", always_2d=True)
            s0 = max(0, int(start_s * sr))
            s1 = min(len(audio), int(end_s * sr))
            chunk = audio[s0:s1]
            if chunk.size == 0:
                return
            sd.stop()
            sd.play(chunk, samplerate=sr)
        except Exception as exc:
            logger.debug("[BreakPanel] slice playback error: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


# ── HitRow ─────────────────────────────────────────────────────────────────────

class HitRow(QWidget):
    """Ligne compacte representant un hit detecte."""

    selected = Signal(int)   # index du hit
    playClicked = Signal(int)

    def __init__(self, hit: DrumSlice, effective_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.hit = hit
        self._effective_label = effective_label
        self._selected = False
        self.setObjectName("BreakHitRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        self._play_btn = QPushButton("▶")
        self._play_btn.setObjectName("BreakHitPlay")
        self._play_btn.setFixedSize(22, 22)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.clicked.connect(lambda: self.playClicked.emit(self.hit.index))

        self._badge = QLabel(HIT_SHORT.get(self._effective_label, "?"))
        self._badge.setObjectName("BreakHitBadge")
        self._badge.setFixedWidth(26)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        duration = self.hit.end_s - self.hit.start_s
        self._time_label = QLabel(
            f"{self.hit.start_s:.2f}s → {self.hit.end_s:.2f}s  ({duration:.2f}s)"
        )
        self._time_label.setObjectName("BreakHitTime")

        conf_pct = int(round(self.hit.confidence * 100))
        self._conf_label = QLabel(f"{conf_pct}%")
        self._conf_label.setObjectName("BreakHitConf")
        self._conf_label.setFixedWidth(34)
        self._conf_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._play_btn)
        layout.addWidget(self._badge)
        layout.addWidget(self._time_label, 1)
        layout.addWidget(self._conf_label)

        self._refresh_badge_style()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.hit.index)
        super().mousePressEvent(event)

    def set_selected(self, active: bool) -> None:
        self._selected = active
        self.setProperty("selected", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_label(self, label: str) -> None:
        self._effective_label = label
        self._badge.setText(HIT_SHORT.get(label, "?"))
        self._refresh_badge_style()

    def _refresh_badge_style(self) -> None:
        color = _hit_color(self._effective_label)
        self._badge.setStyleSheet(
            f"""
            QLabel#BreakHitBadge {{
                background: {color};
                color: #ffffff;
                border-radius: 4px;
                font-size: 9px;
                font-weight: 700;
                padding: 2px 0;
            }}
            """
        )


# ── HitTypeEditor ──────────────────────────────────────────────────────────────

class HitTypeEditor(QWidget):
    """Grille compacte de boutons pour choisir le type d'un hit."""

    labelSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_label: str = ""
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._build()

    def _build(self) -> None:
        self.setObjectName("BreakTypeEditor")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        lbl = QLabel("Type de hit")
        lbl.setObjectName("BreakTypeEditorTitle")

        # 2 lignes × 6 colonnes
        rows_labels = (
            ("kick", "kick_ghost", "snare", "snare_ghost", "snare_ruff", "clap"),
            ("closed_hat", "open_hat", "crash", "ride", "tom", "perc"),
        )

        grid_widget = QWidget()
        grid_widget.setObjectName("BreakTypeGrid")
        grid_layout = QVBoxLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(3)

        for row_labels in rows_labels:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            for label in row_labels:
                btn = QPushButton(HIT_SHORT.get(label, label))
                btn.setObjectName("BreakTypeBtn")
                btn.setCheckable(True)
                btn.setFixedSize(36, 26)
                btn.setToolTip(label.replace("_", " "))
                btn.clicked.connect(lambda checked, l=label: self._on_clicked(l))
                self._group.addButton(btn)
                self._buttons[label] = btn
                row.addWidget(btn)
            row.addStretch(1)
            grid_layout.addLayout(row)

        outer.addWidget(lbl)
        outer.addWidget(grid_widget)

    def _on_clicked(self, label: str) -> None:
        self._current_label = label
        self.labelSelected.emit(label)
        self._refresh_colors()

    def set_label(self, label: str) -> None:
        self._current_label = label
        btn = self._buttons.get(label)
        if btn is not None:
            btn.setChecked(True)
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        for label, btn in self._buttons.items():
            if btn.isChecked():
                color = _hit_color(label)
                btn.setStyleSheet(
                    f"""
                    QPushButton#BreakTypeBtn {{
                        background: {color};
                        color: #ffffff;
                        border: 1px solid {color};
                        border-radius: 4px;
                        font-size: 9px;
                        font-weight: 700;
                    }}
                    """
                )
            else:
                btn.setStyleSheet("")


# ── Scale detection worker ─────────────────────────────────────────────────────

class _ScaleWorker(QThread):
    """Detecte les gammes compatibles d'un fichier audio en arriere-plan."""
    finished = Signal(object)   # prototypes.scale_detector.analyzer.DetectionResult
    failed = Signal(str)        # message d'erreur

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            from prototypes.scale_detector.analyzer import analyze_file  # noqa: PLC0415
            result = analyze_file(self._path, top_n=5)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


# ── ScaleResultWidget ──────────────────────────────────────────────────────────

class ScaleResultWidget(QWidget):
    """Affiche les resultats de detection de gamme : note dominante + gammes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ScaleResultRoot")
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._note_badge = QLabel("--")
        self._note_badge.setObjectName("ScaleNoteBadge")
        self._note_badge.setFixedSize(32, 32)
        self._note_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._scales_row = QHBoxLayout()
        self._scales_row.setContentsMargins(0, 0, 0, 0)
        self._scales_row.setSpacing(4)

        self._scale_pills: list[QLabel] = []

        self._conf_label = QLabel("")
        self._conf_label.setObjectName("ScaleConfLabel")

        layout.addWidget(self._note_badge)
        layout.addLayout(self._scales_row, 1)
        layout.addWidget(self._conf_label)

    def set_result(self, result) -> None:
        """Met a jour avec un DetectionResult du scale_detector."""
        # Note dominante
        note = getattr(result, "dominant_note", "--") or "--"
        self._note_badge.setText(note)

        # Confidence
        conf = getattr(result, "confidence", 0.0) or 0.0
        self._conf_label.setText(f"{int(conf * 100)}%")

        # Supprimer les anciennes pills
        for pill in self._scale_pills:
            self._scales_row.removeWidget(pill)
            pill.deleteLater()
        self._scale_pills.clear()

        # Ajouter les nouvelles (top 3)
        candidates = getattr(result, "candidates", ()) or ()
        p = theme.manager.p
        for i, candidate in enumerate(candidates[:3]):
            label = getattr(candidate, "label", "?") or "?"
            score = getattr(candidate, "score", 0.0) or 0.0
            pill = QLabel(label)
            pill.setObjectName("ScalePill")
            # Premiers = opaque, suivants = plus transparent
            opacity = 1.0 if i == 0 else (0.7 if i == 1 else 0.45)
            pill.setToolTip(f"{label}  score: {score:.3f}")
            self._scales_row.addWidget(pill)
            self._scale_pills.append(pill)

        self._scales_row.addStretch(1)
        self._apply_pill_styles()

    def clear(self) -> None:
        self._note_badge.setText("--")
        self._conf_label.setText("")
        for pill in self._scale_pills:
            self._scales_row.removeWidget(pill)
            pill.deleteLater()
        self._scale_pills.clear()

    def _apply_pill_styles(self) -> None:
        p = theme.manager.p
        self._note_badge.setStyleSheet(
            f"""
            QLabel#ScaleNoteBadge {{
                background: {p.RETRO};
                color: #ffffff;
                border-radius: 16px;
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )
        colors = [p.RETRO, p.TEXT_MUTED, p.BORDER_LIGHT]
        for i, pill in enumerate(self._scale_pills):
            color = colors[min(i, len(colors) - 1)]
            alpha = "ff" if i == 0 else ("bb" if i == 1 else "77")
            pill.setStyleSheet(
                f"""
                QLabel#ScalePill {{
                    background: {p.BG_CARD};
                    color: {color};
                    border: 1px solid {color};
                    border-radius: 8px;
                    padding: 2px 8px;
                    font-size: 10px;
                    font-weight: {'700' if i == 0 else '500'};
                }}
                """
            )


# ── BreakPanelWidget ───────────────────────────────────────────────────────────

class BreakPanelWidget(QWidget):
    """
    Panneau de correction manuelle des hits du break.

    Connexion attendue depuis LaboWidget:
        waveform_tool.analysisResultChanged.connect(break_panel.set_result)
        break_panel.reanalyzeFromMarkersRequested.connect(waveform_tool.reanalyze_from_current_markers)
    """

    reanalyzeFromMarkersRequested = Signal()

    def __init__(self, app_context, parent: QWidget | None = None):
        super().__init__(parent)
        self.app_context = app_context
        self._result: DrumAnalysisResult | None = None
        self._overrides: dict[int, str] = {}   # index → label corrige manuellement
        self._selected_index: int | None = None
        self._rows: dict[int, HitRow] = {}      # index → HitRow widget
        self._source_path: str | None = None    # chemin du fichier courant
        self._scale_worker: _ScaleWorker | None = None
        self._build_ui()
        theme.manager.themeChanged.connect(lambda *_: self._apply_styles())

    # ── Construction UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setObjectName("BreakPanelRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # En-tete
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._title = QLabel("Break — Hits")
        self._title.setObjectName("BreakPanelTitle")
        self._subtitle = QLabel("Cliquer pour lire, choisir le type en bas.")
        self._subtitle.setObjectName("BreakPanelSubtitle")
        title_col.addWidget(self._title)
        title_col.addWidget(self._subtitle)

        self._reanalyze_btn = QPushButton("↺  Re-analyser depuis markers")
        self._reanalyze_btn.setObjectName("BreakPanelAction")
        self._reanalyze_btn.setToolTip(
            "Relancer la detection de type avec les markers actuels du waveform editor"
        )
        self._reanalyze_btn.clicked.connect(self.reanalyzeFromMarkersRequested.emit)
        self._reanalyze_btn.setEnabled(False)

        header.addLayout(title_col, 1)
        header.addWidget(self._reanalyze_btn, 0)

        # Infos break (BPM, famille…)
        self._info_bar = QLabel("Aucune analyse chargee.")
        self._info_bar.setObjectName("BreakPanelInfo")
        self._info_bar.setWordWrap(True)

        # Section gamme
        scale_sep = QFrame()
        scale_sep.setFrameShape(QFrame.Shape.HLine)
        scale_sep.setObjectName("BreakPanelSep")

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(8)

        self._scale_detect_btn = QPushButton("♪  Détecter la gamme")
        self._scale_detect_btn.setObjectName("BreakPanelAction")
        self._scale_detect_btn.setToolTip("Analyser les gammes compatibles du fichier chargé")
        self._scale_detect_btn.clicked.connect(self._run_scale_detection)
        self._scale_detect_btn.setEnabled(False)

        scale_row.addWidget(self._scale_detect_btn)
        scale_row.addStretch(1)

        self._scale_result = ScaleResultWidget()

        # Separateur
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("BreakPanelSep")

        # Liste de hits dans un scroll area
        self._scroll = QScrollArea()
        self._scroll.setObjectName("BreakPanelScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_container = QWidget()
        self._list_container.setObjectName("BreakPanelList")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list_container)

        self._empty_label = QLabel("Lance d'abord l'analyse du break depuis l'onglet Waveform.")
        self._empty_label.setObjectName("BreakPanelEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)

        # Editeur de type (visible seulement si un hit est selectionne)
        self._type_sep = QFrame()
        self._type_sep.setFrameShape(QFrame.Shape.HLine)
        self._type_sep.setObjectName("BreakPanelSep")

        self._type_editor = HitTypeEditor()
        self._type_editor.labelSelected.connect(self._on_label_selected)
        self._type_editor.setVisible(False)
        self._type_sep.setVisible(False)

        main_layout.addLayout(header)
        main_layout.addWidget(self._info_bar)
        main_layout.addWidget(scale_sep)
        main_layout.addLayout(scale_row)
        main_layout.addWidget(self._scale_result)
        main_layout.addWidget(sep)
        main_layout.addWidget(self._scroll, 1)
        main_layout.addWidget(self._empty_label)
        main_layout.addWidget(self._type_sep)
        main_layout.addWidget(self._type_editor)

        self._apply_styles()

    # ── API publique ───────────────────────────────────────────────────────────

    def set_source_path(self, path: str) -> None:
        """Appele depuis WaveformToolWidget via signal currentFileChanged."""
        self._source_path = path or None
        self._scale_result.clear()
        self._scale_detect_btn.setEnabled(bool(self._source_path))

    def set_result(self, result: DrumAnalysisResult | None) -> None:
        """Appele depuis WaveformToolWidget via signal analysisResultChanged."""
        self._result = result
        self._overrides.clear()
        self._selected_index = None
        self._type_editor.setVisible(False)
        self._type_sep.setVisible(False)
        self._rebuild_list()
        self._refresh_info_bar()
        self._reanalyze_btn.setEnabled(result is not None)
        # Mettre a jour le chemin source si disponible via le resultat
        if result is not None and result.source_path:
            self.set_source_path(result.source_path)

    def get_overrides(self) -> dict[int, str]:
        """Retourne le dictionnaire {hit_index: label_manuel} courant."""
        return dict(self._overrides)

    def effective_label(self, hit: DrumSlice) -> str:
        return self._overrides.get(hit.index, hit.label)

    # ── Construction de la liste ───────────────────────────────────────────────

    def _rebuild_list(self) -> None:
        # Supprimer les anciennes rows
        for row in self._rows.values():
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        result = self._result
        if result is None or not result.slices:
            self._empty_label.setVisible(True)
            self._scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._scroll.setVisible(True)

        for hit in result.slices:
            label = self.effective_label(hit)
            row = HitRow(hit, label, self._list_container)
            row.selected.connect(self._on_row_selected)
            row.playClicked.connect(self._on_play_clicked)
            # Inserer avant le stretch final
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
            self._rows[hit.index] = row

    def _refresh_info_bar(self) -> None:
        r = self._result
        if r is None:
            self._info_bar.setText("Aucune analyse chargee.")
            return
        bpm = f"{r.tempo_bpm:.1f} BPM" if r.tempo_bpm else "--"
        n = len(r.slices)
        family = r.family or r.label or "?"
        self._info_bar.setText(
            f"{bpm}  ·  {n} hit{'s' if n != 1 else ''}  ·  {family}"
        )

    # ── Interactions ───────────────────────────────────────────────────────────

    def _on_row_selected(self, index: int) -> None:
        # Deselectionner l'ancien
        if self._selected_index is not None and self._selected_index != index:
            old = self._rows.get(self._selected_index)
            if old is not None:
                old.set_selected(False)

        self._selected_index = index
        row = self._rows.get(index)
        if row is not None:
            row.set_selected(True)

        # Mettre a jour l'editeur de type
        hit = self._hit_by_index(index)
        if hit is not None:
            label = self.effective_label(hit)
            self._type_editor.set_label(label)
            self._type_editor.setVisible(True)
            self._type_sep.setVisible(True)

    def _on_play_clicked(self, index: int) -> None:
        hit = self._hit_by_index(index)
        if hit is None or self._result is None:
            return
        _play_slice(self._result.source_path, hit.start_s, hit.end_s)
        # Selectionner la row aussi
        self._on_row_selected(index)

    def _on_label_selected(self, label: str) -> None:
        if self._selected_index is None:
            return
        self._overrides[self._selected_index] = label
        row = self._rows.get(self._selected_index)
        if row is not None:
            row.set_label(label)

    def _run_scale_detection(self) -> None:
        if not self._source_path:
            return
        self._scale_detect_btn.setEnabled(False)
        self._scale_detect_btn.setText("⏳  Analyse en cours...")
        self._scale_result.clear()

        # Arreter un worker precedent s'il tourne encore
        if self._scale_worker is not None:
            try:
                self._scale_worker.finished.disconnect()
                self._scale_worker.failed.disconnect()
            except Exception:
                pass
            self._scale_worker = None

        worker = _ScaleWorker(self._source_path, self)
        worker.finished.connect(self._on_scale_finished)
        worker.failed.connect(self._on_scale_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._scale_worker = worker
        worker.start()

    def _on_scale_finished(self, result) -> None:
        self._scale_result.set_result(result)
        self._scale_detect_btn.setText("♪  Détecter la gamme")
        self._scale_detect_btn.setEnabled(bool(self._source_path))

    def _on_scale_failed(self, message: str) -> None:
        logger.warning("[BreakPanel] Scale detection failed: %s", message)
        self._scale_detect_btn.setText("♪  Détecter la gamme")
        self._scale_detect_btn.setEnabled(bool(self._source_path))
        self._scale_result.clear()

    def _hit_by_index(self, index: int) -> DrumSlice | None:
        if self._result is None:
            return None
        return next((s for s in self._result.slices if s.index == index), None)

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#BreakPanelRoot {{
                background: transparent;
            }}
            QLabel#BreakPanelTitle {{
                color: {p.TEXT};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#BreakPanelSubtitle {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#BreakPanelInfo {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#BreakPanelEmpty {{
                color: {p.TEXT_MUTED};
                font-size: 12px;
                padding: 24px;
            }}
            QPushButton#BreakPanelAction {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 11px;
            }}
            QPushButton#BreakPanelAction:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#BreakPanelAction:disabled {{
                color: {p.TEXT_MUTED};
            }}
            QFrame#BreakPanelSep {{
                background: {p.BORDER};
                max-height: 1px;
            }}
            QScrollArea#BreakPanelScroll {{
                background: transparent;
                border: none;
            }}
            QWidget#BreakPanelList {{
                background: transparent;
            }}
            QWidget#BreakHitRow {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
            }}
            QWidget#BreakHitRow[selected="true"] {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#BreakHitPlay {{
                background: {p.BG_MEDIUM};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 11px;
                font-size: 8px;
                padding: 0;
            }}
            QPushButton#BreakHitPlay:hover {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
            }}
            QLabel#BreakHitTime {{
                color: {p.TEXT};
                font-size: 11px;
            }}
            QLabel#BreakHitConf {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            QLabel#BreakTypeEditorTitle {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
            }}
            QPushButton#BreakTypeBtn {{
                background: {p.BG_CARD};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                font-size: 9px;
                font-weight: 600;
                padding: 0;
            }}
            QPushButton#BreakTypeBtn:hover {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
                border-color: {p.BORDER_LIGHT};
            }}
            QLabel#ScaleConfLabel {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            """
        )
        # Rafraichir aussi les pills dynamiques
        self._scale_result._apply_pill_styles()
