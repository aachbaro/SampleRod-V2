# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe le glisser-deposer entrant du BreakWidget.
# - Isole la resolution des chemins deposees et le style visuel de drop.
#
# LIENS CLES
# - frontend/labo/waveform_tool_dnd.py : resolution des chemins / sample ids.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget

from frontend.labo.waveform_tool_dnd import (
    has_supported_waveform_drop,
    resolve_waveform_drop_paths,
)


class BreakDndController:
    """Gere le drag-and-drop entrant du BreakWidget."""

    def __init__(self, widget):
        self.widget = widget

    def eventFilter(self, watched, event):
        etype = event.type()
        if etype == QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if etype == QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if etype == QEvent.Type.DragLeave:
            return self._handle_drag_leave(event)
        if etype == QEvent.Type.Drop:
            return self._handle_drop(event)
        return QWidget.eventFilter(self.widget, watched, event)

    def dragEnterEvent(self, event):
        if not self._handle_drag_enter(event):
            QWidget.dragEnterEvent(self.widget, event)

    def dragMoveEvent(self, event):
        if not self._handle_drag_move(event):
            QWidget.dragMoveEvent(self.widget, event)

    def dragLeaveEvent(self, event):
        if not self._handle_drag_leave(event):
            QWidget.dragLeaveEvent(self.widget, event)

    def dropEvent(self, event):
        if not self._handle_drop(event):
            QWidget.dropEvent(self.widget, event)

    def _handle_drag_enter(self, event) -> bool:
        if self.widget._internal_drag_active:
            return False
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime) or not self._paths_from_mime(mime):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_move(self, event) -> bool:
        if self.widget._internal_drag_active:
            return False
        mime = event.mimeData()
        if not has_supported_waveform_drop(mime) or not self._paths_from_mime(mime):
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_leave(self, event) -> bool:
        self._set_drop_active(False)
        event.accept()
        return True

    def _handle_drop(self, event) -> bool:
        if self.widget._internal_drag_active:
            self._set_drop_active(False)
            return False
        paths = self._paths_from_mime(event.mimeData())
        self._set_drop_active(False)
        if not paths:
            return False
        opened = any(self.widget.open_file(p) for p in paths)
        if not opened:
            return False
        event.acceptProposedAction()
        self.widget.setFocus()
        return True

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_waveform_drop_paths(
            mime, sample_path_lookup=self._path_for_sample_id
        )

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        samples = self.widget.app_context.sample_store.get_cached()
        s = next((x for x in samples if int(getattr(x, "id", -1)) == int(sample_id)), None)
        path = getattr(s, "path", "") if s is not None else ""
        return str(path or "") or None

    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self.widget._drop_active == active:
            return
        self.widget._drop_active = active
        self.widget.waveform_host.setProperty("dropActive", active)
        self.widget.waveform_host.style().unpolish(self.widget.waveform_host)
        self.widget.waveform_host.style().polish(self.widget.waveform_host)
        if active:
            self.widget.status_label.setText("Depose le fichier ici pour l'analyser.")
        elif self.widget._current_path is None:
            self.widget.status_label.setText("Depose un break dans la zone waveform pour commencer.")
