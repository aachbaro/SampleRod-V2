from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from frontend.styles import theme

from .payload import DragKind, DragPayload, MaterialStatus


def drag_preview_pixmap(payload: DragPayload) -> QPixmap:
    """Construit l'aperçu compact standard attaché au curseur par QDrag."""
    pixmap = QPixmap(248, 62)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    p = theme.manager.p

    shape = QPainterPath()
    shape.addRoundedRect(1, 1, 246, 60, 8, 8)
    painter.fillPath(shape, QColor(p.BG_CARD))
    border = QPen(QColor(p.ACCENT), 1)
    if payload.status is MaterialStatus.DERIVED:
        border.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(border)
    painter.drawPath(shape)

    _draw_status_mark(painter, payload.status, QColor(p.ACCENT))

    status_font = QFont(painter.font())
    status_font.setPixelSize(8)
    status_font.setWeight(QFont.Weight.DemiBold)
    status_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.7)
    painter.setFont(status_font)
    painter.setPen(QColor(p.TEXT_MUTED))
    painter.drawText(QRect(30, 5, 205, 13), Qt.AlignmentFlag.AlignLeft, _status_label(payload))

    title_font = QFont(painter.font())
    title_font.setPixelSize(12)
    title_font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(title_font)
    painter.setPen(QColor(p.TEXT))
    painter.drawText(QRect(12, 20, 224, 18), Qt.AlignmentFlag.AlignLeft, payload.display_name)

    detail_font = QFont(painter.font())
    detail_font.setPixelSize(10)
    detail_font.setWeight(QFont.Weight.Normal)
    painter.setFont(detail_font)
    painter.setPen(QColor(p.TEXT_MUTED))
    painter.drawText(QRect(12, 40, 224, 15), Qt.AlignmentFlag.AlignLeft, _detail(payload))
    painter.end()
    return pixmap


def _status_label(payload: DragPayload) -> str:
    if payload.status is MaterialStatus.ARTIFACT:
        return "ARTEFACT"
    if payload.status is MaterialStatus.DERIVED:
        subtype = {
            DragKind.AUDIO_SELECTION: "SÉLECTION",
            DragKind.STEM: "STEM",
        }.get(payload.kind)
        return "DÉRIVÉ" + (f" · {subtype}" if subtype else "")
    return "SOURCE"


def _draw_status_mark(
    painter: QPainter, status: MaterialStatus | None, color: QColor
) -> None:
    """Forme distincte par statut : le sens ne dépend pas de la couleur."""
    painter.setPen(QPen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if status is MaterialStatus.ARTIFACT:
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([
            QPointF(18, 6), QPointF(23, 11),
            QPointF(18, 16), QPointF(13, 11),
        ]))
    elif status is MaterialStatus.DERIVED:
        painter.drawLine(QPointF(13, 7), QPointF(18, 11))
        painter.drawLine(QPointF(13, 15), QPointF(18, 11))
        painter.drawLine(QPointF(18, 11), QPointF(23, 11))
    else:
        painter.drawEllipse(QPointF(18, 11), 5, 5)


def _detail(payload: DragPayload) -> str:
    labels = {
        DragKind.AUDIO_FILE: "Audio",
        DragKind.AUDIO_SELECTION: "Sélection",
        DragKind.STEM: "Stem",
        DragKind.ARTIFACT: "Artefact",
        DragKind.MULTIPLE_AUDIO: "Audio",
    }
    bits = [labels[payload.kind]]
    if payload.selection is not None:
        bits.append(
            f"{payload.selection.start_seconds:.2f}–{payload.selection.end_seconds:.2f} s"
        )
    if payload.duration is not None:
        bits.append(f"{payload.duration:.2f} s")
    return " · ".join(bits)
