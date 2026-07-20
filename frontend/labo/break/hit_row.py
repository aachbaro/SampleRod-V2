# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la ligne unitaire du tableau de hits du BreakWidget.
# - Isole le drag d'une slice et la logique UI compacte du tableau.
#
# CE QUI EST COUVERT
# - Catalogue des labels de coups + abreviations + couleurs.
# - _HitRow : selection, changement de label, suppression, drag d'un hit.
#
# LIENS CLES
# - frontend/labo/break/break_hits_table.py : reconstruit la liste de _HitRow.
# - backend/services/drum_analysis_service.py : type DrumSlice.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import tempfile

import soundfile as sf
from PySide6.QtCore import QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QWidget,
)

from backend.services.drum_analysis_service import DrumSlice

MANUAL_HIT_LABEL_OPTIONS: tuple[str, ...] = (
    "kick", "kick_ghost", "snare", "snare_ghost",
    "snare_ruff", "clap", "closed_hat", "open_hat",
    "crash", "ride", "tom", "perc",
)
HIT_LABEL_SHORT: dict[str, str] = {
    "kick": "K",  "kick_ghost": "Kg", "snare": "S",  "snare_ghost": "Sg",
    "snare_ruff": "Rf", "clap": "C",  "closed_hat": "HC", "open_hat": "HO",
    "crash": "Cr", "ride": "Rd", "tom": "T",  "perc": "P",
}
HIT_LABEL_COLOR: dict[str, str] = {
    "kick": "#e05c5c",     "kick_ghost": "#c47878",
    "snare": "#e0a040",    "snare_ghost": "#c49060",  "snare_ruff": "#c4a070",
    "clap": "#d4b040",
    "closed_hat": "#4bb6b7", "open_hat": "#2ec4c5",
    "crash": "#9b6ee0",    "ride": "#7a5cb8",
    "tom": "#5ca0e0",      "perc": "#7abce0",
}


class _HitRow(QFrame):
    selected = Signal(int)
    removeRequested = Signal(int)
    labelChanged = Signal(int, str)
    dragStarted = Signal()
    dragFinished = Signal()

    def __init__(self, drum_slice: DrumSlice, source_path: str, parent=None):
        super().__init__(parent)
        self.drum_slice = drum_slice
        self._source_path = source_path
        self._drag_start_pos = None
        self._current_label = drum_slice.label
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("BreakHitRow")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(8)

        grip = QLabel("⠿")
        grip.setObjectName("BreakHitGrip")
        grip.setFixedWidth(12)

        idx = QLabel(f"{self.drum_slice.index:02d}")
        idx.setObjectName("BreakHitIndex")
        idx.setFixedWidth(22)
        idx.setAlignment(Qt.AlignmentFlag.AlignCenter)

        color = HIT_LABEL_COLOR.get(self._current_label, "#7abce0")
        self.badge = QLabel(self._current_label.replace("_", " "))
        self.badge.setObjectName("BreakHitBadge")
        self.badge.setFixedWidth(76)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_badge_color(color)

        dur = self.drum_slice.end_s - self.drum_slice.start_s
        time_lbl = QLabel(
            f"{self.drum_slice.start_s:.3f}s→{self.drum_slice.end_s:.3f}s"
            f"  <span style='color:#666'>{dur*1000:.0f}ms</span>"
        )
        time_lbl.setObjectName("BreakHitTime")
        time_lbl.setTextFormat(Qt.TextFormat.RichText)
        time_lbl.setFixedWidth(140)

        radio_widget = QWidget()
        radio_widget.setObjectName("BreakHitRadios")
        radio_row = QHBoxLayout(radio_widget)
        radio_row.setContentsMargins(0, 0, 0, 0)
        radio_row.setSpacing(1)

        self._radio_group = QButtonGroup(self)
        for label in MANUAL_HIT_LABEL_OPTIONS:
            short = HIT_LABEL_SHORT.get(label, label[:2])
            rb = QRadioButton(short)
            rb.setObjectName("BreakHitRadio")
            rb.setChecked(label == self._current_label)
            rb.setToolTip(label.replace("_", " "))
            rb.clicked.connect(lambda checked, lbl=label: self._on_radio(lbl))
            self._radio_group.addButton(rb)
            radio_row.addWidget(rb)

        row.addWidget(grip)
        row.addWidget(idx)
        row.addWidget(self.badge)
        row.addWidget(time_lbl)
        row.addStretch(1)
        row.addWidget(radio_widget)

    def _set_badge_color(self, color: str) -> None:
        self.badge.setStyleSheet(
            f"background: {color}22; color: {color}; border: 1px solid {color}55;"
            f"border-radius: 8px; padding: 2px 6px; font-size: 10px; font-weight: 700;"
        )

    def _on_radio(self, new_label: str) -> None:
        self._current_label = new_label
        color = HIT_LABEL_COLOR.get(new_label, "#7abce0")
        self.badge.setText(new_label.replace("_", " "))
        self._set_badge_color(color)
        self.labelChanged.emit(self.drum_slice.index, new_label)

    def get_label(self) -> str:
        return self._current_label

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_start_pos is not None:
                dist = (event.pos() - self._drag_start_pos).manhattanLength()
                if dist < QApplication.startDragDistance():
                    self.selected.emit(self.drum_slice.index)
            self._drag_start_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start_pos is not None:
            dist = (event.pos() - self._drag_start_pos).manhattanLength()
            if dist > QApplication.startDragDistance():
                self._drag_start_pos = None
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
            self.removeRequested.emit(self.drum_slice.index)
        super().mouseDoubleClickEvent(event)

    def _start_drag(self) -> None:
        if not self._source_path or not os.path.isfile(self._source_path):
            return
        try:
            audio, sr = sf.read(self._source_path, dtype="float32", always_2d=False)
            s0 = int(self.drum_slice.start_s * sr)
            s1 = int(self.drum_slice.end_s * sr)
            segment = audio[s0:s1]
            if segment.size == 0:
                return
            source_name = os.path.splitext(os.path.basename(self._source_path))[0]
            label_slug = self._current_label
            fname = f"{label_slug}__{source_name}__{self.drum_slice.index:02d}.wav"
            fname = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in fname)
            temp_path = os.path.join(tempfile.gettempdir(), fname)
            sf.write(temp_path, segment, int(sr))
        except Exception:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(temp_path)])
        drag = QDrag(self)
        drag.setMimeData(mime)
        self.dragStarted.emit()
        drag.exec(Qt.DropAction.CopyAction)
        self.dragFinished.emit()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
