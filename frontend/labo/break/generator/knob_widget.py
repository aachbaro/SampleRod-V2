# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Isole le potentiometre circulaire reutilise dans le generateur de break.
# - Fournit un widget type "plugin audio" compatible avec un signal
#   valueChanged(int), utilise comme un slider compact.
#
# DEPENDANCES
# - frontend.styles.theme : couleurs dynamiques du theme courant.
# -----------------------------------------------------------------------------

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from frontend.styles import theme


class KnobWidget(QWidget):
    """Pseudo-potentiometre style plugin audio."""

    valueChanged = Signal(int)

    _ARC_W: int = 3
    _DOT_R: float = 2.5
    _KNOB_D: int = 38
    _QT_START: int = 210
    _SPAN: int = 270

    def __init__(
        self,
        minimum: int = 0,
        maximum: int = 100,
        value: int = 0,
        default: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = int(maximum)
        self._val = max(self._min, min(self._max, int(value)))
        self._default = int(default) if default is not None else int(value)
        self._drag_y: float | None = None
        self._drag_val: int = 0

        size = self._KNOB_D + 10
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setToolTip("↑↓ drag • double-clic = reset")

    def value(self) -> int:
        return self._val

    def setValue(self, v: int, *, _emit: bool = True) -> None:
        v = max(self._min, min(self._max, int(v)))
        if v == self._val:
            return
        self._val = v
        self.update()
        if _emit:
            self.valueChanged.emit(v)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._min = int(minimum)
        self._max = max(self._min, int(maximum))
        self.setValue(self._val)

    def minimum(self) -> int:
        return self._min

    def maximum(self) -> int:
        return self._max

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_y = float(event.position().y())
            self._drag_val = self._val
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_y is None:
            return
        delta_y = self._drag_y - float(event.position().y())
        total_range = max(1, self._max - self._min)
        delta_val = int(delta_y * total_range / 80.0)
        self.setValue(max(self._min, min(self._max, self._drag_val + delta_val)))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_y = None
        event.accept()

    def wheelEvent(self, event) -> None:
        event.ignore()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._default)
        event.accept()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        margin = 5
        d = min(w, h) - margin * 2
        r = d / 2.0
        cx = w / 2.0
        cy = h / 2.0
        rect = QRectF(cx - r, cy - r, d, d)

        p = theme.manager.p

        pen_track = QPen(
            QColor(p.BORDER_LIGHT), self._ARC_W,
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
        )
        painter.setPen(pen_track)
        painter.drawArc(rect, self._QT_START * 16, -self._SPAN * 16)

        normalized = (self._val - self._min) / max(1, self._max - self._min)
        filled_span = int(normalized * self._SPAN)
        if filled_span > 0:
            pen_fill = QPen(
                QColor(p.INFO), self._ARC_W,
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
            )
            painter.setPen(pen_fill)
            painter.drawArc(rect, self._QT_START * 16, -filled_span * 16)

        angle_qt_deg = self._QT_START - normalized * self._SPAN
        angle_rad = math.radians(angle_qt_deg)
        dot_radius = r - self._ARC_W / 2.0 - 0.5
        ix = cx + dot_radius * math.cos(angle_rad)
        iy = cy - dot_radius * math.sin(angle_rad)

        dot_color = QColor(p.INFO) if normalized > 0.001 else QColor(p.TEXT_MUTED)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color)
        painter.drawEllipse(QPointF(ix, iy), self._DOT_R, self._DOT_R)
