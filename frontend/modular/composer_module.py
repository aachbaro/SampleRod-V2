from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QTabBar, QTabWidget, QVBoxLayout, QWidget

from frontend.labo.audio_drop import can_accept_audio_drop, resolve_audio_drop_paths
from frontend.ui import IconButton, add_tab_close_button


class ComposerModule(QWidget):
    """Conteneur a onglets pour plusieurs compositions independantes."""

    compositionCountChanged = Signal(int)

    def __init__(self, app_context, parent=None, composer_factory=None):
        super().__init__(parent)
        self.app_context = app_context
        self._composer_factory = composer_factory or self._default_composer
        self._next_tab_number = 1

        self.setObjectName("ComposerModule")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("ComposerTabs")
        self._tabs.setTabsClosable(False)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)

        self._add_btn = IconButton("plus", tooltip="Nouvelle composition", size="s")
        self._add_btn.clicked.connect(self.new_composition)
        self._tabs.setCornerWidget(self._add_btn, Qt.Corner.TopRightCorner)

        tab_bar = self._tabs.tabBar()
        tab_bar.setAcceptDrops(True)
        tab_bar.installEventFilter(self)

        layout.addWidget(self._tabs)
        self.new_composition()

    def new_composition(self, *, title: str | None = None, make_current: bool = True):
        composer = self._composer_factory()
        tab_title = title or self._default_tab_title()
        index = self._tabs.addTab(composer, tab_title)
        self._tabs.setTabToolTip(index, tab_title)
        add_tab_close_button(self._tabs, index, lambda: self._close_editor(composer))
        if make_current:
            self._tabs.setCurrentIndex(index)
        self.compositionCountChanged.emit(self._tabs.count())
        return composer

    def save_state(self) -> dict:
        tabs: list[dict[str, object]] = []
        for index in range(self._tabs.count()):
            composer = self._tabs.widget(index)
            saver = getattr(composer, "snapshot_composition_state", None)
            state = saver() if callable(saver) else {}
            tabs.append(
                {
                    "title": self._tabs.tabText(index),
                    "state": dict(state or {}),
                }
            )
        return {"tabs": tabs, "active": self._tabs.currentIndex()}

    def restore_state(self, state: dict) -> None:
        self._clear_tabs()
        restored = False
        for raw_tab in (state or {}).get("tabs", []):
            if not isinstance(raw_tab, dict):
                continue
            composer = self.new_composition(
                title=str(raw_tab.get("title") or self._default_tab_title()),
                make_current=False,
            )
            restorer = getattr(composer, "restore_composition_state", None)
            if callable(restorer):
                restorer(dict(raw_tab.get("state") or {}))
            restored = True

        if not restored:
            self.new_composition()

        active = int((state or {}).get("active", 0) or 0)
        if 0 <= active < self._tabs.count():
            self._tabs.setCurrentIndex(active)
        self.compositionCountChanged.emit(self._tabs.count())

    def cleanup(self) -> None:
        for index in range(self._tabs.count()):
            self._cleanup_editor(self._tabs.widget(index))

    def eventFilter(self, watched, event):
        if watched is self._tabs.tabBar():
            return self._handle_tab_bar_event(event)
        return super().eventFilter(watched, event)

    def _handle_tab_bar_event(self, event) -> bool:
        if event.type() == QEvent.Type.DragEnter:
            return self._on_tab_bar_drag_enter(event)
        if event.type() == QEvent.Type.DragMove:
            return self._on_tab_bar_drag_move(event)
        if event.type() == QEvent.Type.DragLeave:
            event.accept()
            return True
        if event.type() == QEvent.Type.Drop:
            return self._on_tab_bar_drop(event)
        return False

    def _on_tab_bar_drag_enter(self, event) -> bool:
        if self._can_accept_mime(event.mimeData()):
            event.acceptProposedAction()
            return True
        event.ignore()
        return False

    def _on_tab_bar_drag_move(self, event) -> bool:
        if self._can_accept_mime(event.mimeData()):
            event.acceptProposedAction()
            return True
        event.ignore()
        return False

    def _on_tab_bar_drop(self, event) -> bool:
        paths = self._paths_from_mime(event.mimeData())
        if not paths:
            event.ignore()
            return False
        composer = self.new_composition()
        adder = getattr(composer, "add_file_paths", None)
        if callable(adder):
            adder(paths)
        event.acceptProposedAction()
        return True

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
        if self._tabs.count() == 0:
            self.new_composition()
        self.compositionCountChanged.emit(self._tabs.count())

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

    def _default_tab_title(self) -> str:
        title = f"Composition {self._next_tab_number}"
        self._next_tab_number += 1
        return title

    def _default_composer(self) -> QWidget:
        from frontend.right_panel.composer.composer_widget import SampleComposerWidget

        return SampleComposerWidget(self.app_context)

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
