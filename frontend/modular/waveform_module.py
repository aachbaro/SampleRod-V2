# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Module Waveform de l'atelier modulaire : un conteneur a ONGLETS ou chaque
#   onglet edite un fichier. Ouvrir un nouveau fichier = nouvel onglet (au lieu
#   d'une nouvelle fenetre).
# - Enveloppe le WaveformToolWidget existant (un par onglet) et relaie ses
#   signaux (artifactCreated, separationRequested).
#
# API attendue par le WindowManager
# - open_file(path)          : ouvre / focus l'onglet du fichier
# - current_path()           : fichier de l'onglet actif
# - save_state()/restore_state(): liste des fichiers + onglet actif (session)
#
# LIENS CLES
# - frontend/labo/waveform_tool.py : l'editeur reel (un par onglet)
# - frontend/modular/modules_setup.py : factory du module 'waveform'
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QTabWidget, QVBoxLayout, QWidget

from frontend.labo.audio_drop import can_accept_audio_drop
from frontend.ui import IconButton

_AUDIO_FILTER = "Audio (*.wav *.flac *.aif *.aiff *.mp3 *.ogg);;Tous (*.*)"


class WaveformModule(QWidget):
    """Conteneur a onglets : un onglet Waveform par fichier ouvert."""

    artifactCreated = Signal(object)
    separationRequested = Signal(list)
    activeFileChanged = Signal(str)

    def __init__(self, app_context, parent=None, editor_factory=None):
        super().__init__(parent)
        self.app_context = app_context
        self._editor_factory = editor_factory or self._default_editor
        self.setObjectName("WaveformModule")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("WaveformTabs")
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(lambda *_a: self.activeFileChanged.emit(self.current_path() or ""))

        self._add_btn = IconButton("plus", tooltip="Ouvrir un fichier", size="s")
        self._add_btn.clicked.connect(self._open_file_dialog)
        self._tabs.setCornerWidget(self._add_btn, Qt.Corner.TopRightCorner)

        layout.addWidget(self._tabs)

    # -- Ouverture / onglets ------------------------------------------------
    def open_file(self, path: str) -> bool:
        normalized = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(normalized):
            return False
        existing = self._index_for_path(normalized)
        if existing is not None:
            self._tabs.setCurrentIndex(existing)
            return True
        editor = self._editor_factory()
        _connect = getattr(editor, "artifactCreated", None)
        if _connect is not None:
            editor.artifactCreated.connect(self.artifactCreated.emit)
        _sep = getattr(editor, "separationRequested", None)
        if _sep is not None:
            editor.separationRequested.connect(self.separationRequested.emit)
        ok = bool(editor.open_file(normalized))
        index = self._tabs.addTab(editor, Path(normalized).stem)
        self._tabs.setTabToolTip(index, normalized)
        self._tabs.setCurrentIndex(index)
        return ok

    def current_path(self) -> str | None:
        editor = self._tabs.currentWidget()
        getter = getattr(editor, "current_path", None) if editor is not None else None
        return getter() if callable(getter) else None

    # -- Glisser-deposer (Reserve / fichiers externes) ----------------------
    def dragEnterEvent(self, event):  # noqa: N802
        if can_accept_audio_drop(
            event.mimeData(),
            sample_path_lookup=self._path_for_sample_id,
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if can_accept_audio_drop(
            event.mimeData(),
            sample_path_lookup=self._path_for_sample_id,
        ):
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

    def _paths_from_mime(self, mime) -> list[str]:
        from frontend.labo.audio_drop import resolve_audio_drop_paths

        return resolve_audio_drop_paths(mime, sample_path_lookup=self._path_for_sample_id)

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        store = getattr(self.app_context, "sample_store", None)
        if store is None:
            return None
        samples = store.get_cached()
        sample = next(
            (s for s in samples if int(getattr(s, "id", -1)) == int(sample_id)), None
        )
        path = getattr(sample, "path", "") if sample is not None else ""
        return str(path or "") or None

    def _index_for_path(self, normalized: str) -> int | None:
        for i in range(self._tabs.count()):
            editor = self._tabs.widget(i)
            getter = getattr(editor, "current_path", None)
            if callable(getter) and getter() == normalized:
                return i
        return None

    def _close_tab(self, index: int) -> None:
        editor = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if editor is not None:
            self._cleanup_editor(editor)
            editor.deleteLater()

    @staticmethod
    def _cleanup_editor(editor) -> None:
        # Arrete la lecture avant destruction (evite le crash du callback
        # sounddevice sur un widget deja detruit).
        cleanup = getattr(editor, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    def cleanup(self) -> None:
        """Arrete la lecture de tous les onglets (avant destruction du module)."""
        for i in range(self._tabs.count()):
            self._cleanup_editor(self._tabs.widget(i))

    def _open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Ouvrir des fichiers audio", "", _AUDIO_FILTER
        )
        for path in paths or []:
            self.open_file(path)

    def _default_editor(self) -> QWidget:
        from frontend.labo.waveform_tool import WaveformToolWidget

        return WaveformToolWidget(self.app_context)

    # -- Session ------------------------------------------------------------
    def save_state(self) -> dict:
        files: list[str] = []
        for i in range(self._tabs.count()):
            editor = self._tabs.widget(i)
            getter = getattr(editor, "current_path", None)
            path = getter() if callable(getter) else None
            if path:
                files.append(path)
        return {"files": files, "active": self._tabs.currentIndex()}

    def restore_state(self, state: dict) -> None:
        for path in (state or {}).get("files", []):
            self.open_file(path)
        active = int((state or {}).get("active", 0) or 0)
        if 0 <= active < self._tabs.count():
            self._tabs.setCurrentIndex(active)
