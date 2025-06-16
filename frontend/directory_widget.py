from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QFileDialog,
    QSizePolicy,
    QLabel,
    QHBoxLayout,
    QListWidgetItem,
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

    def __init__(self, service: DirectoryService, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.service = service
        self.app_context = app_context
        self._current_item = None
        self._qs = QSettings("SampleRod", "Main")
        self.current_dir = self._qs.value("last_directory", "", type=str)
        self._build_ui()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(100)
        logger.info("[DirectoryWidget] Initialisation")

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
            self.current_dir = d
            self._qs.setValue("last_directory", d)
            self.refresh_list()
            # On notifie que le dossier a changé
            self.directoryChanged.emit(d)
            logger.info(f"[DirectoryWidget] Dossier sélectionné : {d}")
        else:
            logger.info("[DirectoryWidget] Sélection de dossier annulée")

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
        if self.current_dir:
            files = self.service.list_samples(self.current_dir)
            logger.info(f"[DirectoryWidget] Rafraîchissement de la liste ({len(files)} fichiers)")
            for name in files:
                path = os.path.join(self.current_dir, name)
                item_widget = DirectoryListItemWidget(path, self)
                list_item = QListWidgetItem(self.list_widget)
                list_item.setSizeHint(item_widget.sizeHint())
                self.list_widget.addItem(list_item)
                self.list_widget.setItemWidget(list_item, item_widget)



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
    def __init__(self, file_path: str, parent_widget: DirectoryWidget):
        super().__init__()
        self.file_path = file_path
        self.parent_widget = parent_widget

        self.name_label = QLabel(os.path.basename(file_path))
        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.clicked.connect(self._on_clicked)

        layout = QHBoxLayout(self)
        layout.addWidget(self.name_label)
        layout.addStretch()
        layout.addWidget(self.play_button)

    def _on_clicked(self):
        self.parent_widget.toggle_preview(self)

    def set_playing(self, playing: bool):
        icon_name = 'fa5s.pause' if playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
