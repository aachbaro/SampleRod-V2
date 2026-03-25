"""
------------------------------------------------------------------------------
Directory Widget (Right Panel Tool)
------------------------------------------------------------------------------
Role / intention
----------------
Ce module implemente le "DirectoryWidget" : un outil UI qui permet de gerer un
dossier de samples et d'y importer du contenu via drag & drop.

Fonctionnalites principales
---------------------------
- Ouvrir un dossier cible (via l'outil "Directory" du Right Panel) + persister
  l'historique (QSettings).
- Lister les fichiers audio presents dans le dossier.
- Importer des elements par drag & drop (MIME types custom) :
  - application/x-sample-slice-data : slice depuis le MarkerManager (audio_data+sr)
  - application/x-sample-card       : sample entier depuis une SampleCard (sample_id)
- Pre-ecoute rapide (play/pause) via l'audio_player partage (AppContext).
- Renommer inline et supprimer un fichier (via sample_store).
- Se synchroniser avec le reste de l'app via les signaux du sample_store
  (rename/delete/move) pour garder la liste a jour.

Position dans l'architecture
----------------------------
- UI (ce fichier) : interactions utilisateur + rendu widgets.
- DirectoryService (backend) : logique "import depuis drop" + copy/save.
- AppContext : fournit sample_store (DB/cache) et audio_player (preview).

Notes / refactor (en cours)
---------------------------
On est en train de decouper ce module (meme approche que waveform.py / sample_card.py).
Premiere extraction deja faite:
- DirectoryListItemWidget -> directory_item_widget.py

Prochaines extractions probables:
- DnD: fait -> directory_list_widget.py + directory_dnd.py (un seul drop target).
- Preview: fait -> directory_preview.py (un seul item en lecture a la fois).
- Store sync + historique QSettings: fait -> directory_store_sync.py + directory_history.py
- UI: fait -> directory_ui.py (construction layout + row widget)

Ce decoupage prepare l'arrivee d'autres outils dans le Right Panel (ex: Sample Composer).
------------------------------------------------------------------------------
"""

from PySide6.QtWidgets import QWidget, QSizePolicy, QListWidgetItem
from PySide6.QtCore import Signal, QSettings, QPropertyAnimation, QEasingCurve, QSize
import wave

from backend.services.directory_service import DirectoryService
from backend.models.AppContext import AppContext
from .directory_item_widget import DirectoryListItemWidget
from .directory_history import DirectoryHistory
from .directory_preview import DirectoryPreviewController
from .directory_store_sync import DirectoryStoreSync
from . import directory_ui
from frontend.styles import theme

import os
import logging
logger = logging.getLogger("directory_widget")

class DirectoryWidget(QWidget):
    """Widget UI pour importer / pre-ecouter / renommer / supprimer des samples dans un dossier."""
    # Signal émis quand on change de dossier
    directoryChanged = Signal(str)

    def __init__(self, service: DirectoryService, app_context: AppContext, parent=None, path: str | None = None):
        super().__init__(parent)
        logger.info("[DirectoryWidget] Initialisation (start)")
        self.service = service
        self.app_context = app_context
        # Controller: gere la logique de preview (un seul item en lecture a la fois).
        self.preview = DirectoryPreviewController(
            audio_player=self.app_context.audio_player,
            duration_provider=self._get_duration,
        )
        self._items_by_id = {}
        self._qs = QSettings("SampleRod", "Main")
        self.history = DirectoryHistory(self._qs)
        self.current_dir = path or self.history.get_last_directory()
        logger.info("[DirectoryWidget] UI build (start)")
        self._build_ui()
        logger.info("[DirectoryWidget] UI build (done)")

        # Synchro store -> UI (rename/delete/move) via un QObject parented a ce widget.
        self.store_sync = DirectoryStoreSync(self, self.app_context.sample_store)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(100)
        logger.info("[DirectoryWidget] Initialisation (core ready)")

        # Si un dossier est connu a l'init (path explicite ou dernier dossier en memoire),
        # on l'ouvre directement. (Sinon le widget reste vide.)
        if self.current_dir:
            self.open_directory(self.current_dir)
        logger.info("[DirectoryWidget] Initialisation (ready)")

    def _build_ui(self):
        # Construction UI centralisee dans directory_ui.py (layout + widgets).
        directory_ui.build_directory_widget_ui(self)
        theme.manager.themeChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self, _name: str):
        directory_ui.apply_styles(self)
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            w = self.list_widget.itemWidget(list_item)
            if w is not None:
                directory_ui.restyle_item(w)

    def open_directory(self, path: str) -> None:
        """Set current directory, refresh list and update history."""
        if not path:
            return
        self.current_dir = path
        directory_ui.set_directory_path(self, path)
        self.history.set_last_directory(path)
        self.history.add_recent_directory(path)
        self.refresh_list()
        self.directoryChanged.emit(path)

    def _get_duration(self, path: str) -> float:
        """Return duration of a wav file in seconds."""
        try:
            with wave.open(path, 'rb') as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            return 0.0

    def toggle_preview(self, item_widget: 'DirectoryListItemWidget') -> None:
        """Toggle playback (delegue au DirectoryPreviewController)."""
        self.preview.toggle(item_widget)

    def refresh_list(self):
        # Evite de garder une reference vers un widget Qt qui va etre detruit par clear().
        self.preview.detach_current_widget()
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
                self._add_row(path, sample_id)

    # ------------------------------------------------------------------ list ops (used by store sync)
    def _add_row(self, path: str, sample_id: int | None) -> None:
        item_widget = DirectoryListItemWidget(path, self, sample_id)
        list_item = QListWidgetItem(self.list_widget)
        target_h = max(1, item_widget.sizeHint().height())
        item_widget.setMaximumHeight(0)
        list_item.setSizeHint(QSize(0, 0))
        self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, item_widget)
        if sample_id is not None:
            self._items_by_id[sample_id] = (list_item, item_widget)

        lw = self.list_widget
        anim = QPropertyAnimation(item_widget, b"maximumHeight", lw)
        anim.setDuration(200)
        anim.setStartValue(0)
        anim.setEndValue(target_h)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _hint(h):
            try:
                list_item.setSizeHint(QSize(lw.viewport().width(), h))
            except RuntimeError:
                pass

        anim.valueChanged.connect(_hint)
        anim.finished.connect(
            lambda: (
                item_widget.setMaximumHeight(16777215),
                _hint(target_h),
            )
        )
        anim.start()
        item_widget._anim_in = anim

    def _update_row(self, sample_id: int, new_path: str) -> None:
        item = self._items_by_id.get(sample_id)
        if not item:
            return
        _, widget = item
        widget.file_path = new_path
        widget.name_label.setText(os.path.basename(new_path))
        base = os.path.splitext(os.path.basename(new_path))[0]
        widget.rename_input.setText(base)

    def _remove_row(self, sample_id: int) -> None:
        item = self._items_by_id.get(sample_id)
        if not item:
            return
        _, widget = item
        self._remove_widget(widget)

    def _remove_widget(self, widget: 'DirectoryListItemWidget') -> None:
        # IMPORTANT: si le widget etait en preview, on detache/stoppe proprement avant destruction.
        self.preview.on_widget_removed(widget)

        target_item = None
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if self.list_widget.itemWidget(item) is widget:
                target_item = item
                break

        if widget.sample_id is not None:
            self._items_by_id.pop(widget.sample_id, None)

        if target_item is None:
            return

        start_h = max(1, widget.height())
        lw = self.list_widget

        anim = QPropertyAnimation(widget, b"maximumHeight", lw)
        anim.setDuration(160)
        anim.setStartValue(start_h)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def _hint(h):
            try:
                target_item.setSizeHint(QSize(lw.viewport().width(), h))
            except RuntimeError:
                pass

        def _finalize():
            try:
                row = lw.row(target_item)
                if row >= 0:
                    lw.takeItem(row)
            except RuntimeError:
                pass
            try:
                widget.deleteLater()
            except RuntimeError:
                pass

        anim.valueChanged.connect(_hint)
        anim.finished.connect(_finalize)
        anim.start()
        widget._anim_out = anim

    @staticmethod
    def remove_from_history(path: str) -> None:
        """Remove a directory from the stored history."""
        DirectoryHistory.remove_from_history(path)
