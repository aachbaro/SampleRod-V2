from __future__ import annotations

import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from frontend.styles import theme

from .acceptance import DropAcceptance, DropVisualState
from .codec import payload_from_mime
from .payload import DragPayload


class _TargetOverlay(QLabel):
    def __init__(self, target: QWidget):
        super().__init__(target)
        self._target = target
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        target.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self._target and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._target.rect())
        return False

    def show_state(self, state: DropVisualState, label: str = "") -> None:
        if state == DropVisualState.NORMAL:
            self.hide()
            return
        p = theme.manager.p
        hover = state == DropVisualState.HOVER
        self.setText(label if hover else "")
        self.setGeometry(self._target.rect())
        self.setStyleSheet(
            f"background: rgba(44,198,207,{34 if hover else 14});"
            f"border: {2 if hover else 1}px solid {p.ACCENT}; border-radius: 8px;"
            f"color: {p.TEXT}; font-size: 12px; font-weight: 700; padding: 8px;"
        )
        self.raise_()
        self.show()


@dataclass
class _RegisteredTarget:
    target_id: str
    widget_ref: weakref.ReferenceType
    accepts: Callable[[DragPayload], DropAcceptance]
    overlay: _TargetOverlay


class DragDropController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.payload: DragPayload | None = None
        self._targets: dict[str, _RegisteredTarget] = {}
        self._hovered_id: str | None = None

    def register_target(self, target_id: str, widget: QWidget, accepts) -> None:
        key = str(target_id)
        self.unregister_target(key)
        overlay = _TargetOverlay(widget)
        self._targets[key] = _RegisteredTarget(key, weakref.ref(widget), accepts, overlay)
        widget.destroyed.connect(lambda *_args, key=key: self.unregister_target(key))

    def unregister_target(self, target_id: str) -> None:
        entry = self._targets.pop(str(target_id), None)
        if entry is not None:
            try:
                entry.overlay.deleteLater()
            except RuntimeError:
                pass

    def start_drag(self, payload: DragPayload) -> None:
        self.finish_drag()
        self.payload = payload
        self._refresh_compatible_targets()

    def enter_target(self, target_id: str, mime=None) -> DropAcceptance:
        payload = self.payload or payload_from_mime(mime)
        entry = self._targets.get(str(target_id))
        if payload is None or entry is None:
            return DropAcceptance.reject()
        acceptance = entry.accepts(payload)
        if acceptance.accepted:
            self._hovered_id = entry.target_id
            entry.overlay.show_state(DropVisualState.HOVER, acceptance.label)
        return acceptance

    def leave_target(self, target_id: str) -> None:
        entry = self._targets.get(str(target_id))
        if entry is None:
            return
        self._hovered_id = None
        if self.payload is not None:
            acceptance = entry.accepts(self.payload)
            entry.overlay.show_state(
                DropVisualState.COMPATIBLE if acceptance.accepted else DropVisualState.NORMAL
            )
        else:
            entry.overlay.show_state(DropVisualState.NORMAL)

    def finish_drag(self) -> None:
        self.payload = None
        self._hovered_id = None
        for entry in list(self._targets.values()):
            try:
                entry.overlay.show_state(DropVisualState.NORMAL)
            except RuntimeError:
                pass

    def _refresh_compatible_targets(self) -> None:
        if self.payload is None:
            return
        for key, entry in list(self._targets.items()):
            widget = entry.widget_ref()
            if widget is None:
                self.unregister_target(key)
                continue
            try:
                visible = widget.isVisible()
                acceptance = entry.accepts(self.payload)
            except RuntimeError:
                self.unregister_target(key)
                continue
            entry.overlay.show_state(
                DropVisualState.COMPATIBLE
                if visible and acceptance.accepted else DropVisualState.NORMAL
            )


_controller: DragDropController | None = None


def drag_controller() -> DragDropController:
    global _controller
    if _controller is None:
        app = QApplication.instance()
        _controller = DragDropController(app)
    return _controller


@contextmanager
def drag_session(payload: DragPayload):
    controller = drag_controller()
    controller.start_drag(payload)
    try:
        yield controller
    finally:
        controller.finish_drag()
