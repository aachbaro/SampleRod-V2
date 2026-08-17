from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass(frozen=True, slots=True)
class ReserveFilterState:
    query: str = ""
    technical_status: str = "all"
    scale: str = "__all__"
    compatibility_sample_id: int | None = None
    scope_kind: str = "all"
    scope_value: str | None = None


class ReserveFilterController(QObject):
    """Owns shared Reserve filter state; views remain responsible for filtering."""

    QUERY_DEBOUNCE_MS = 200

    queryChanged = Signal(str)
    statusChanged = Signal(str)
    scaleChanged = Signal(str)
    compatibilityChanged = Signal(object)
    scopeChanged = Signal(str, object)
    stateChanged = Signal(object)

    def __init__(self, parent=None, *, debounce_ms: int | None = None):
        super().__init__(parent)
        self._state = ReserveFilterState()
        self._pending_query = ""
        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(
            self.QUERY_DEBOUNCE_MS if debounce_ms is None else int(debounce_ms)
        )
        self._query_timer.timeout.connect(self.flush_query)

    @property
    def state(self) -> ReserveFilterState:
        return self._state

    @staticmethod
    def normalize_query(query: str | None) -> str:
        return (query or "").strip()

    def set_query(self, query: str | None) -> None:
        normalized = self.normalize_query(query)
        if normalized == self._state.query and not self._query_timer.isActive():
            return
        if normalized == self._pending_query and self._query_timer.isActive():
            return
        self._pending_query = normalized
        self._query_timer.start()

    def flush_query(self) -> None:
        self._query_timer.stop()
        query = self._pending_query
        if query == self._state.query:
            return
        self._state = replace(self._state, query=query)
        self.queryChanged.emit(query)
        self.stateChanged.emit(self._state)

    def set_status(self, status: str | None) -> None:
        value = status or "all"
        if value == self._state.technical_status:
            return
        self._state = replace(self._state, technical_status=value)
        self.statusChanged.emit(value)
        self.stateChanged.emit(self._state)

    def set_scale(self, scale: str | None) -> None:
        value = scale or "__all__"
        if value == self._state.scale:
            return
        self._state = replace(self._state, scale=value)
        self.scaleChanged.emit(value)
        self.stateChanged.emit(self._state)

    def set_compatibility(self, sample_id: int | None) -> None:
        value = int(sample_id) if sample_id else None
        if value == self._state.compatibility_sample_id:
            return
        self._state = replace(self._state, compatibility_sample_id=value)
        self.compatibilityChanged.emit(value)
        self.stateChanged.emit(self._state)

    def set_scope(self, kind: str, value: str | None = None) -> None:
        kind = kind or "all"
        if (kind, value) == (self._state.scope_kind, self._state.scope_value):
            return
        self._state = replace(self._state, scope_kind=kind, scope_value=value)
        self.scopeChanged.emit(kind, value)
        self.stateChanged.emit(self._state)

    def clear_all(self) -> None:
        self._query_timer.stop()
        old = self._state
        self._pending_query = ""
        self._state = ReserveFilterState()
        if old.query:
            self.queryChanged.emit("")
        if old.technical_status != "all":
            self.statusChanged.emit("all")
        if old.scale != "__all__":
            self.scaleChanged.emit("__all__")
        if old.compatibility_sample_id is not None:
            self.compatibilityChanged.emit(None)
        if (old.scope_kind, old.scope_value) != ("all", None):
            self.scopeChanged.emit("all", None)
        if old != self._state:
            self.stateChanged.emit(self._state)
