# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fenetre top-level SANS CADRE qui heberge le widget d'une instance de module.
# - Look immersif : pas de barre de titre OS (ni croix ni reduction). A la
#   place, une barre fine deplacable + une bordure qui s'eclaire quand la
#   fenetre est active (focus).
# - Comportements cles :
#   * deplacement : glisser la barre de titre fine (startSystemMove) ;
#   * redimensionnement : glisser les bords (startSystemResize) ;
#   * hide-on-close : masque au lieu de detruire (contenu conserve) ;
#   * geometrie : sauvegarde/restauration {x,y,w,h} avec securite multi-ecran.
#
# LIENS CLES
# - frontend/modular/window_manager.py : cree et pilote ces fenetres
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from frontend.styles import theme

_MIN_VISIBLE_W = 96
_MIN_VISIBLE_H = 48
_RESIZE_MARGIN = 6  # epaisseur de la zone de redimensionnement au bord


def clamp_rect_to_screens(rect: QRect) -> QRect:
    """Ramene un rectangle sur un ecran existant (securite 2e moniteur debranche)."""
    screens = QGuiApplication.screens()
    if not screens:
        return rect
    for screen in screens:
        inter = screen.availableGeometry().intersected(rect)
        if inter.width() >= _MIN_VISIBLE_W and inter.height() >= _MIN_VISIBLE_H:
            return rect
    primary = QGuiApplication.primaryScreen().availableGeometry()
    width = min(rect.width(), primary.width())
    height = min(rect.height(), primary.height())
    x = primary.x() + (primary.width() - width) // 2
    y = primary.y() + (primary.height() - height) // 2
    return QRect(x, y, width, height)


class _ModuleHeader(QWidget):
    """Barre de titre fine et deplacable (glisser pour bouger la fenetre)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ModuleHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(26)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(6)
        self._title = QLabel(title)
        self._title.setObjectName("ModuleHeaderTitle")
        row.addWidget(self._title, 1)

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)


class ModuleWindow(QWidget):
    """Fenetre sans cadre d'une instance de module (bordure lumineuse au focus)."""

    windowHidden = Signal(str)  # instance_id : la fenetre a ete masquee
    activated = Signal(str)     # instance_id : la fenetre est devenue active

    def __init__(self, instance_id: str, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self._instance_id = instance_id
        self._content = content
        self.setObjectName("ModuleWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMouseTracking(True)

        outer = QVBoxLayout(self)
        # Marge = gouttiere de redimensionnement autour du contenu.
        outer.setContentsMargins(
            _RESIZE_MARGIN, _RESIZE_MARGIN, _RESIZE_MARGIN, _RESIZE_MARGIN
        )
        outer.setSpacing(0)

        self._header = _ModuleHeader(title, self)
        body = QWidget()
        body.setObjectName("ModuleBody")
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)
        body_l.addWidget(self._header, 0)
        body_l.addWidget(content, 1)

        outer.addWidget(body)
        self.resize(900, 560)
        self._apply_frame_style()
        theme.manager.themeChanged.connect(lambda *_a: self._apply_frame_style())

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def module_widget(self) -> QWidget:
        return self._content

    def set_title(self, title: str) -> None:
        self.setWindowTitle(title)
        self._header.set_title(title)

    # -- Geometrie ----------------------------------------------------------
    def current_geometry(self) -> dict:
        geo = self.geometry()
        return {"x": geo.x(), "y": geo.y(), "width": geo.width(), "height": geo.height()}

    def apply_geometry(self, geometry: dict | None) -> None:
        if not geometry:
            return
        try:
            rect = QRect(
                int(geometry["x"]),
                int(geometry["y"]),
                int(geometry["width"]),
                int(geometry["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return
        self.setGeometry(clamp_rect_to_screens(rect))

    # -- Evenements ---------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        event.ignore()
        self.hide()
        self.windowHidden.emit(self._instance_id)

    def changeEvent(self, event):  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange:
            self._refresh_active_state()
            if self.isActiveWindow():
                self.activated.emit(self._instance_id)
        super().changeEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        # Curseur adapte quand on survole un bord (feedback de resize).
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(self._cursor_for_edges(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    return
        super().mousePressEvent(event)

    # -- Interne ------------------------------------------------------------
    def _edges_at(self, pos) -> Qt.Edge:
        margin = _RESIZE_MARGIN
        rect = self.rect()
        edges = Qt.Edge(0)
        if pos.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= rect.width() - margin:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= margin:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= rect.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape:
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (top and left) or (bottom and right):
            return Qt.CursorShape.SizeFDiagCursor
        if (top and right) or (bottom and left):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _refresh_active_state(self) -> None:
        self.setProperty("active", bool(self.isActiveWindow()))
        self.style().unpolish(self)
        self.style().polish(self)

    def _apply_frame_style(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#ModuleWindow {{
                background: {p.BG_DARK};
                border: 1px solid {p.BORDER};
            }}
            QWidget#ModuleWindow[active="true"] {{
                border: 2px solid {p.ACCENT};
            }}
            QWidget#ModuleBody {{ background: {p.BG_DARK}; }}
            QWidget#ModuleHeader {{
                background: {p.BG_MEDIUM};
                border-bottom: 1px solid {p.BORDER};
            }}
            QLabel#ModuleHeaderTitle {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )
