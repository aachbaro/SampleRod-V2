# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Regroupe la navigation filesystem du DirectoryWidget.
# - Isole le choix de racine, l'ouverture d'un dossier, la synchro de l'arbre
#   et la restauration des noeuds expandes.
#
# CE QUI EST COUVERT
# - choose_root_directory() : dialogue de choix de dossier racine.
# - set_root_directory()    : maj racine + historique + ouverture.
# - open_directory()        : bascule de dossier courant.
# - go_to_parent_directory(): remonte d'un cran.
# - _on_tree_*()           : callbacks du tree view.
# - _sync_tree_selection() : reflète le dossier courant dans l'arbre.
# - _update_tree_root()    : redefine la racine visible de l'arbre.
# - _restore_tree_expansion() : reouvre les noeuds memorises.
#
# LIENS CLES
# - directory_widget.py  : facade qui garde les signaux Qt.
# - directory_history.py : persistance des derniers dossiers / noeuds ouverts.
# - directory_ui.py      : widgets et labels mis a jour ici.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os

from PySide6.QtCore import QModelIndex, QSignalBlocker
from PySide6.QtWidgets import QFileDialog

from backend.services.audio_metadata import normalize_audio_path


class DirectoryNavigationController:
    """Gere la navigation disque et la synchro de l'arborescence Qt."""

    def __init__(self, widget):
        self.widget = widget

    def choose_root_directory(self):
        start_dir = (
            self.widget.current_dir
            or self.widget.history.get_last_directory()
            or os.path.expanduser("~")
        )
        selected = QFileDialog.getExistingDirectory(
            self.widget,
            "Choisir un dossier audio",
            start_dir,
        )
        if selected:
            self.set_root_directory(selected)

    def set_root_directory(self, path: str) -> None:
        if not path:
            return
        normalized = normalize_audio_path(path)
        if not os.path.isdir(normalized):
            return

        self.widget.root_dir = normalized
        self.widget.history.set_last_root_directory(normalized)
        self.widget.history.set_last_directory(normalized)
        self.widget.history.add_recent_directory(normalized)
        self._update_tree_root(normalized)
        self.widget.rootDirectoryChanged.emit(self.widget.root_dir)
        self.open_directory(normalized)

    def open_directory(self, path: str) -> None:
        if not path:
            return
        normalized = normalize_audio_path(path)
        if not os.path.isdir(normalized):
            return

        self.widget.current_dir = normalized
        from . import directory_ui

        directory_ui.set_directory_path(self.widget, self.widget.current_dir)
        self.widget.history.set_last_directory(self.widget.current_dir)
        if not self.widget.root_dir:
            self.widget.root_dir = normalized
            self.widget.history.set_last_root_directory(normalized)
            self.widget.rootDirectoryChanged.emit(self.widget.root_dir)
        self._update_tree_root(self.widget.current_dir)
        self._sync_tree_selection(self.widget.current_dir)
        self._update_up_button_state()
        self.widget.refresh_list()
        self.widget._refresh_index_status()
        self.widget.directoryChanged.emit(self.widget.current_dir)

    def go_to_parent_directory(self) -> None:
        if not self.widget.current_dir:
            return
        parent = normalize_audio_path(os.path.dirname(self.widget.current_dir))
        if not parent or parent == self.widget.current_dir:
            return
        self.open_directory(parent)

    def _on_tree_current_changed(self, current: QModelIndex, _previous: QModelIndex):
        path = self.widget.fs_model.filePath(current)
        if (
            path
            and os.path.isdir(path)
            and normalize_audio_path(path) != self.widget.current_dir
        ):
            self.open_directory(path)

    def _on_tree_expanded(self, index: QModelIndex) -> None:
        path = normalize_audio_path(self.widget.fs_model.filePath(index))
        if path and os.path.isdir(path):
            self.widget.history.add_expanded_directory(path)

    def _on_tree_collapsed(self, index: QModelIndex) -> None:
        path = normalize_audio_path(self.widget.fs_model.filePath(index))
        if path and os.path.isdir(path):
            self.widget.history.remove_expanded_directory(path)

    def _sync_tree_selection(self, path: str) -> None:
        index = self.widget.fs_model.index(path)
        if not index.isValid():
            return
        selection_model = self.widget.tree_view.selectionModel()
        if selection_model is None:
            return
        with QSignalBlocker(selection_model):
            self.widget.tree_view.setCurrentIndex(index)
        self.widget.tree_view.scrollTo(index)

    def _update_up_button_state(self) -> None:
        if not self.widget.current_dir:
            self.widget.up_button.setEnabled(False)
            return
        current = normalize_audio_path(self.widget.current_dir)
        parent = normalize_audio_path(os.path.dirname(current))
        self.widget.up_button.setEnabled(bool(parent) and parent != current)

    def _update_tree_root(self, path: str) -> None:
        tree_root = self._tree_root_for(path)
        root_index = self.widget.fs_model.setRootPath(tree_root)
        self.widget.tree_view.setRootIndex(root_index)
        self._restore_tree_expansion(tree_root, path)

    @staticmethod
    def _tree_root_for(path: str) -> str:
        normalized = normalize_audio_path(path)
        parent = normalize_audio_path(os.path.dirname(normalized))
        if parent and parent != normalized and os.path.isdir(parent):
            return parent
        return normalized

    def _restore_tree_expansion(self, tree_root: str, current_path: str) -> None:
        to_expand: list[str] = []
        current = normalize_audio_path(current_path)
        root = normalize_audio_path(tree_root)

        while current:
            to_expand.append(current)
            if current == root:
                break
            parent = normalize_audio_path(os.path.dirname(current))
            if not parent or parent == current:
                break
            current = parent

        for path in self.widget.history.get_expanded_directories():
            normalized = normalize_audio_path(path)
            if normalized not in to_expand and _is_path_in_folder(normalized, root):
                to_expand.append(normalized)

        for path in reversed(to_expand):
            index = self.widget.fs_model.index(path)
            if index.isValid():
                self.widget.tree_view.expand(index)


def _is_path_in_folder(path: str, folder: str) -> bool:
    try:
        return (
            os.path.commonpath([normalize_audio_path(path), normalize_audio_path(folder)])
            == normalize_audio_path(folder)
        )
    except ValueError:
        return False
