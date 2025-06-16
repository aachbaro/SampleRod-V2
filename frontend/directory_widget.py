from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QFileDialog,
    QSizePolicy,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QListWidgetItem,
    QMessageBox,
)
from PyQt6.QtCore import QMimeData, pyqtSignal, QSettings
import qtawesome as qta
import wave

from backend.services.directory_service import DirectoryService
from backend.models.AppContext import AppContext

import os
import logging
logger = logging.getLogger("directory_widget")

class DirectoryWidget(QWidget):
    """Simple widget to import samples into a folder via drag & drop."""
    # Signal émis quand on change de dossier
    directoryChanged = pyqtSignal(str)

    def __init__(self, service: DirectoryService, app_context: AppContext, parent=None, path: str | None = None):
        super().__init__(parent)
        self.service = service
        self.app_context = app_context
        self._current_item = None
        self._items_by_id = {}
        self._qs = QSettings("SampleRod", "Main")
        self.current_dir = path or self._qs.value("last_directory", "", type=str)
        self._build_ui()
        # Mise à jour des items lorsqu'un renommage survient ailleurs dans l'application
        self.app_context.sample_store.sampleRenamed.connect(self.on_sample_renamed)
        self.app_context.sample_store.sampleDeleted.connect(self.on_sample_deleted)
        self.app_context.sample_store.sampleMoved.connect(self.on_sample_moved)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(100)
        logger.info("[DirectoryWidget] Initialisation")

        if path:
            self.open_directory(path)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.choose_btn = QPushButton("Choose folder")
        self.choose_btn.clicked.connect(self._on_choose)
        self.list_widget = DirectoryListWidget(self)
        self.list_widget.setAcceptDrops(True)
        layout.addWidget(self.choose_btn)
        layout.addWidget(self.list_widget)

    def _on_choose(self):
        start_dir = self.current_dir or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "Choose folder", start_dir)
        if d:
            self.open_directory(d)
            logger.info(f"[DirectoryWidget] Dossier sélectionné : {d}")
        else:
            logger.info("[DirectoryWidget] Sélection de dossier annulée")

    def open_directory(self, path: str) -> None:
        """Set current directory, refresh list and update history."""
        if not path:
            return
        self.current_dir = path
        self._qs.setValue("last_directory", path)
        self._add_recent_directory(path)
        self.refresh_list()
        self.directoryChanged.emit(path)

    def _add_recent_directory(self, path: str) -> None:
        """Add path to the history of recent directories."""
        dirs = self._qs.value("recent_directories", [], type=list)
        try:
            dirs = list(dirs)
        except Exception:
            dirs = []
        if path in dirs:
            dirs.remove(path)
        dirs.insert(0, path)
        if len(dirs) > 10:
            dirs = dirs[:10]
        self._qs.setValue("recent_directories", dirs)

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event):
        if self._accepts(event.mimeData()):
            logger.info("[DirectoryWidget] dragEnter: accepté")
            event.acceptProposedAction()
        else:
            logger.info("[DirectoryWidget] dragEnter: refusé")
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not self.current_dir:
            logger.info("[DirectoryWidget] dropEvent ignoré (aucun dossier choisi)")
            event.ignore()
            return
        if self._accepts(event.mimeData()):
            logger.info("[DirectoryWidget] dropEvent accepté")
            self.service.handle_drop(self.current_dir, event.mimeData())
            self.refresh_list()
            event.acceptProposedAction()
        else:
            logger.info("[DirectoryWidget] dropEvent refusé")
            event.ignore()

    def _accepts(self, mime: QMimeData) -> bool:
        return (
            mime.hasFormat("application/x-sample-slice-data")
            or mime.hasFormat("application/x-sample-card")
        )

    def _get_duration(self, path: str) -> float:
        """Return duration of a wav file in seconds."""
        try:
            with wave.open(path, 'rb') as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            return 0.0

    def toggle_preview(self, item_widget: 'DirectoryListItemWidget') -> None:
        """Toggle playback of the item using the shared audio player."""
        file_path = item_widget.file_path
        sample_id = hash(file_path) & 0x7FFFFFFF
        duration = self._get_duration(file_path)

        ap = self.app_context.audio_player

        if ap.is_playing and ap.current_sample_id == sample_id:
            ap.clear_audio()
            item_widget.set_playing(False)
            self._current_item = None
            return

        if ap.is_playing:
            ap.clear_audio()
            if self._current_item:
                self._current_item.set_playing(False)

        ap.toggle_play(sample_id, file_path, duration)
        item_widget.set_playing(True)
        self._current_item = item_widget

    def refresh_list(self):
        self.list_widget.clear()
        self._items_by_id.clear()
        if self.current_dir:
            files = self.service.list_samples(self.current_dir)
            logger.info(
                f"[DirectoryWidget] Rafraîchissement de la liste ({len(files)} fichiers)"
            )
            cache = {
                s.path: s.id
                for s in self.app_context.sample_store.get_cached()
            }
            for name in files:
                path = os.path.join(self.current_dir, name)
                sample_id = cache.get(path)
                item_widget = DirectoryListItemWidget(path, self, sample_id)
                list_item = QListWidgetItem(self.list_widget)
                list_item.setSizeHint(item_widget.sizeHint())
                self.list_widget.addItem(list_item)
                self.list_widget.setItemWidget(list_item, item_widget)
                if sample_id is not None:
                    self._items_by_id[sample_id] = (list_item, item_widget)

    def on_sample_renamed(self, sample_id: int, old_path: str, new_path: str):
        """Met à jour l'entrée correspondante si elle est affichée."""
        if os.path.dirname(old_path) != self.current_dir:
            return
        item = self._items_by_id.get(sample_id)
        if item:
            _, widget = item
            widget.file_path = new_path
            widget.name_label.setText(os.path.basename(new_path))
            base = os.path.splitext(os.path.basename(new_path))[0]
            widget.rename_input.setText(base)

    def on_sample_deleted(self, sample_id: int):
        """Retire l'entrée si elle est présente."""
        item = self._items_by_id.get(sample_id)
        if item:
            _, widget = item
            self._remove_widget(widget)
            if self._current_item is widget:
                try:
                    self.app_context.audio_player.clear_audio()
                except Exception:
                    pass
                self._current_item = None
            self._items_by_id.pop(sample_id, None)

    def on_sample_moved(self, sample_id: int, target_folder: str):
        """Met à jour ou retire l'entrée selon le nouveau dossier."""
        sample = next(
            (s for s in self.app_context.sample_store.get_cached() if s.id == sample_id),
            None,
        )
        if not sample:
            return
        new_path = sample.path
        in_list = sample_id in self._items_by_id
        if target_folder == self.current_dir:
            if in_list:
                _, widget = self._items_by_id[sample_id]
                widget.file_path = new_path
                widget.name_label.setText(os.path.basename(new_path))
                base = os.path.splitext(os.path.basename(new_path))[0]
                widget.rename_input.setText(base)
            else:
                item_widget = DirectoryListItemWidget(new_path, self, sample_id)
                list_item = QListWidgetItem(self.list_widget)
                list_item.setSizeHint(item_widget.sizeHint())
                self.list_widget.addItem(list_item)
                self.list_widget.setItemWidget(list_item, item_widget)
                self._items_by_id[sample_id] = (list_item, item_widget)
        else:
            if in_list:
                _, widget = self._items_by_id.pop(sample_id)
                self._remove_widget(widget)
                if self._current_item is widget:
                    try:
                        self.app_context.audio_player.clear_audio()
                    except Exception:
                        pass
                    self._current_item = None

    def _remove_widget(self, widget: 'DirectoryListItemWidget') -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if self.list_widget.itemWidget(item) is widget:
                self.list_widget.takeItem(i)
                widget.deleteLater()
                break
        if widget.sample_id is not None:
            self._items_by_id.pop(widget.sample_id, None)

    @staticmethod
    def remove_from_history(path: str) -> None:
        """Remove a directory from the stored history."""
        qs = QSettings("SampleRod", "Main")
        dirs = qs.value("recent_directories", [], type=list)
        try:
            dirs = list(dirs)
        except Exception:
            dirs = []
        if path in dirs:
            dirs.remove(path)
            qs.setValue("recent_directories", dirs)



class DirectoryListWidget(QListWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.parent_widget = parent  # ton DirectoryWidget

    def dragEnterEvent(self, event):
        if self.parent_widget._accepts(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if not self.parent_widget.current_dir:
            event.ignore()
            return
        if self.parent_widget._accepts(event.mimeData()):
            self.parent_widget.service.handle_drop(
                self.parent_widget.current_dir,
                event.mimeData()
            )
            self.parent_widget.refresh_list()
            event.acceptProposedAction()
        else:
            event.ignore()


class DirectoryListItemWidget(QWidget):
    def __init__(self, file_path: str, parent_widget: DirectoryWidget, sample_id: int | None = None):
        super().__init__()
        self.file_path = file_path
        self.parent_widget = parent_widget
        self.sample_id = sample_id

        self.name_label = QLabel(os.path.basename(file_path))
        self.name_label.mouseDoubleClickEvent = self._start_rename
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        self.rename_input = QLineEdit(base_name)
        self.rename_input.hide()
        self.rename_input.editingFinished.connect(self._submit_rename)
        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.clicked.connect(self._on_clicked)

        self.delete_button = QPushButton()
        self.delete_button.setFixedSize(30, 30)
        self.delete_button.setIcon(qta.icon('fa5s.trash-alt', color='red'))
        self.delete_button.clicked.connect(self._on_delete)

        layout = QHBoxLayout(self)
        layout.addWidget(self.name_label)
        layout.addWidget(self.rename_input)
        layout.addStretch()
        layout.addWidget(self.play_button)
        layout.addWidget(self.delete_button)

    def _on_clicked(self):
        self.parent_widget.toggle_preview(self)

    def _start_rename(self, event):
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        self.rename_input.setText(base_name)
        self.name_label.hide()
        self.rename_input.show()
        self.rename_input.setFocus()
        self.rename_input.selectAll()

    def _submit_rename(self):
        new_name = self.rename_input.text().strip()
        old_base = os.path.splitext(os.path.basename(self.file_path))[0]
        if new_name and new_name != old_base:
            success, err = self.parent_widget.app_context.sample_store.rename_by_path(
                self.file_path, new_name
            )
            if success:
                ext = os.path.splitext(self.file_path)[1]
                folder = os.path.dirname(self.file_path)
                new_path = os.path.join(folder, new_name + ext)
                self.file_path = new_path
                self.name_label.setText(os.path.basename(new_path))
            elif err:
                QMessageBox.warning(self, "Erreur", err)
        self.rename_input.hide()
        self.name_label.show()

    def _on_delete(self):
        reply = QMessageBox.question(
            self,
            "Supprimer",
            f"Supprimer le fichier '{os.path.basename(self.file_path)}' ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Arrêt de la lecture si ce fichier est en cours
        ap = self.parent_widget.app_context.audio_player
        if ap.current_sample_path == self.file_path:
            try:
                ap.clear_audio()
            except Exception:
                pass

        success, err = self.parent_widget.app_context.sample_store.delete_by_path(self.file_path)
        if not success and err:
            QMessageBox.warning(self, "Erreur", err)
        if self.sample_id is None:
            # Not tracked in DB, remove immediately
            self.parent_widget._remove_widget(self)

    def set_playing(self, playing: bool):
        icon_name = 'fa5s.pause' if playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
