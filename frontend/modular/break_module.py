from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QTabWidget, QVBoxLayout, QWidget

from frontend.labo.audio_drop import can_accept_audio_drop, resolve_audio_drop_paths
from frontend.ui import IconButton, add_tab_close_button

_AUDIO_FILTER = "Audio (*.wav *.flac *.aif *.aiff *.mp3 *.ogg);;Tous (*.*)"


class BreakModule(QWidget):
    """Conteneur a onglets pour l'outil Break : un fichier par onglet."""

    artifactCreated = Signal(object)
    activeFileChanged = Signal(str)

    def __init__(self, app_context, parent=None, editor_factory=None):
        super().__init__(parent)
        self.app_context = app_context
        self._editor_factory = editor_factory or self._default_editor

        self.setObjectName("BreakModule")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("BreakTabs")
        self._tabs.setTabsClosable(False)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(
            lambda *_args: self.activeFileChanged.emit(self.current_path() or "")
        )

        self._add_btn = IconButton("plus", tooltip="Ouvrir un break", size="s")
        self._add_btn.clicked.connect(self._open_file_dialog)
        self._tabs.setCornerWidget(self._add_btn, Qt.Corner.TopRightCorner)

        layout.addWidget(self._tabs)

    def open_file(self, path: str) -> bool:
        normalized = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(normalized):
            return False

        existing = self._index_for_path(normalized)
        if existing is not None:
            self._tabs.setCurrentIndex(existing)
            return True

        editor = self._editor_factory()
        disable_replace = getattr(editor, "set_drop_replace_enabled", None)
        if callable(disable_replace):
            disable_replace(False)

        artifact_signal = getattr(editor, "artifactCreated", None)
        if artifact_signal is not None:
            artifact_signal.connect(self.artifactCreated.emit)

        ok = bool(editor.open_file(normalized))
        index = self._tabs.addTab(editor, Path(normalized).stem)
        self._tabs.setTabToolTip(index, normalized)
        add_tab_close_button(self._tabs, index, lambda: self._close_editor(editor))
        self._tabs.setCurrentIndex(index)
        return ok

    def current_path(self) -> str | None:
        editor = self._tabs.currentWidget()
        getter = getattr(editor, "current_path", None) if editor is not None else None
        return getter() if callable(getter) else None

    def dragEnterEvent(self, event):  # noqa: N802
        if self._can_accept_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._can_accept_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        paths = self._paths_from_mime(event.mimeData())
        if not paths:
            event.ignore()
            return
        opened = False
        for path in paths:
            opened = self.open_file(path) or opened
        if opened:
            event.acceptProposedAction()
        else:
            event.ignore()

    def save_state(self) -> dict:
        tabs: list[dict[str, object]] = []
        for index in range(self._tabs.count()):
            editor = self._tabs.widget(index)
            getter = getattr(editor, "current_path", None)
            path = getter() if callable(getter) else None
            if not path:
                continue
            markers_getter = getattr(editor, "_get_current_markers", None)
            markers = markers_getter() if callable(markers_getter) else []
            tabs.append(
                {
                    "path": path,
                    "markers": [float(marker) for marker in (markers or [])],
                }
            )
        return {"tabs": tabs, "active": self._tabs.currentIndex()}

    def restore_state(self, state: dict) -> None:
        self._clear_tabs()
        for raw_tab in (state or {}).get("tabs", []):
            if not isinstance(raw_tab, dict):
                continue
            path = str(raw_tab.get("path") or "")
            if not path:
                continue
            if not self.open_file(path):
                continue
            editor = self._tabs.currentWidget()
            setter = getattr(editor, "set_markers", None)
            if callable(setter):
                setter(list(raw_tab.get("markers") or []))
        active = int((state or {}).get("active", 0) or 0)
        if 0 <= active < self._tabs.count():
            self._tabs.setCurrentIndex(active)

    def cleanup(self) -> None:
        for index in range(self._tabs.count()):
            self._cleanup_editor(self._tabs.widget(index))

    def _close_editor(self, editor) -> None:
        index = self._tabs.indexOf(editor)
        if index >= 0:
            self._close_tab(index)

    def _close_tab(self, index: int) -> None:
        editor = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if editor is not None:
            self._cleanup_editor(editor)
            editor.deleteLater()

    def _clear_tabs(self) -> None:
        while self._tabs.count():
            editor = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if editor is not None:
                self._cleanup_editor(editor)
                editor.deleteLater()

    @staticmethod
    def _cleanup_editor(editor) -> None:
        cleanup = getattr(editor, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    def _index_for_path(self, normalized: str) -> int | None:
        for index in range(self._tabs.count()):
            editor = self._tabs.widget(index)
            getter = getattr(editor, "current_path", None)
            if callable(getter) and getter() == normalized:
                return index
        return None

    def _open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Ouvrir des breaks",
            "",
            _AUDIO_FILTER,
        )
        for path in paths or []:
            self.open_file(path)

    def _default_editor(self) -> QWidget:
        from frontend.labo.break_widget import BreakWidget

        return BreakWidget(self.app_context)

    def _can_accept_mime(self, mime) -> bool:
        return can_accept_audio_drop(
            mime,
            sample_path_lookup=self._path_for_sample_id,
            artifact_path_lookup=self._path_for_artifact_id,
        )

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_audio_drop_paths(
            mime,
            sample_path_lookup=self._path_for_sample_id,
            artifact_path_lookup=self._path_for_artifact_id,
        )

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        store = getattr(self.app_context, "sample_store", None)
        if store is None:
            return None
        samples = store.get_cached()
        sample = next(
            (sample for sample in samples if int(getattr(sample, "id", -1)) == int(sample_id)),
            None,
        )
        path = getattr(sample, "path", "") if sample is not None else ""
        return str(path or "") or None

    def _path_for_artifact_id(self, artifact_id: str) -> str | None:
        store = getattr(self.app_context, "lab_artifact_store", None)
        resolver = getattr(store, "resolve_path", None)
        if callable(resolver):
            return resolver(artifact_id)
        return None
