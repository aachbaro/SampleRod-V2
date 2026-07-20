# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - L'onglet "Stems" du Labo : l'interface de la separation de pistes
#   (voix / batterie / basse / autres) assuree par StemSeparatorService.
# - Fonctionnement pour l'utilisateur :
#   1. choisir un modele IA et un dossier de travail (memorises en QSettings) ;
#   2. glisser un fichier audio (ou une carte de sample) : il arrive dans la
#      zone de PREPARATION ;
#   3. router les stems (pins 🥁🎸🎤🎹) vers 4 canaux de sortie ou "Hors mix"
#      (drag & drop, routage memorise en QSettings) ;
#   4. cliquer sur Separer : la file d'attente traite les fichiers ;
#   5. chaque CANAL produit un ARTEFACT (signal artifactCreated) — un canal
#      avec plusieurs stems donne un mix somme des stems.
#
# FONCTIONS (sommaire)
# - StemSeparatorToolWidget (QWidget)
#   - signal artifactCreated(LabArtifact) : un stem/mix est pret.
#   - _build_ui()          : titre, controles, statut, zone de decantation
#                            (preparation + routage + courant + file).
#   - _bind_signals()      : abonnements aux signaux du service et du board.
#   - enqueue_paths()      : file directe avec snapshot du routage courant.
#   - add_to_preparation()/_launch_preparation()/_rebuild_prep_view() :
#     zone de preparation avant lancement.
#   - _persist_routing()   : routage stem->canal en QSettings (JSON).
#   - updateLibraryOrder() : callback de reorder interne de la liste.
#   - eventFilter() + drag*/dropEvent + _handle_* : gestion du glisser-
#     deposer entrant (Reserve / fichiers externes).
#   - _sync_queue_view()   : recolle l'UI sur la file du service.
#   - _restore_settings()/_choose_workspace_dir()/_set_workspace_dir() :
#     modele, dossier de travail et routage persistes.
#   - _on_initialized()/_on_file_started()/_on_file_finished()/
#     _on_file_failed()/_on_queue_idle() : reactions aux evenements.
#   - _emit_stem_artifacts(): applique le routage — canal a 1 stem = stem
#     tel quel, canal a plusieurs stems = mix (mix_stem_files), Hors mix =
#     ignore ; sans routage, chaque stem devient un artefact (historique).
#   - _emit_single_stem()  : LabArtifact pour un stem individuel.
#   - _paths_from_mime()/_path_for_sample_id() : decodage des depots.
#   - _set_drop_active()/_refresh_status()/_set_status()/_apply_styles().
#
# LIENS CLES
# - backend/services/stem_separator_service.py : le service pilote ici.
# - frontend/labo/labo_widget.py : relie artifactCreated au plateau.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.services.audio_metadata import (
    collect_audio_file_metadata,
    is_audio_file,
    normalize_audio_path,
)
from backend.services.stem_separator_service import StemQueueEntry, mix_stem_files
from frontend.custom_widgets import QListWidgetDragBugFix
from frontend.styles import theme

from .audio_drop import has_supported_audio_drop, resolve_audio_drop_paths
from .lab_artifact import LabArtifact
from .stem_routing import STEM_COLORS, STEM_ORDER, StemRoutingBoard


class StemQueueRowWidget(QWidget):
    removeRequested = Signal(str)

    def __init__(self, path: str, priority: int, parent=None):
        super().__init__(parent)
        self.path = normalize_audio_path(path)
        self.priority = max(1, int(priority))
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("StemQueueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        self.setLayout(layout)

        self.handle_label = QLabel("⋮⋮")
        self.handle_label.setObjectName("StemQueueHandle")
        self.handle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.handle_label.setFixedWidth(18)

        self.priority_badge = QLabel("")
        self.priority_badge.setObjectName("StemQueuePriority")
        self.priority_badge.setFixedWidth(36)
        self.priority_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.name_label = QLabel("")
        self.name_label.setObjectName("StemQueueName")

        self.folder_label = QLabel("")
        self.folder_label.setObjectName("StemQueueFolder")

        text_col.addWidget(self.name_label)
        text_col.addWidget(self.folder_label)

        self.remove_button = QPushButton("Retirer")
        self.remove_button.setObjectName("StemQueueAction")
        self.remove_button.clicked.connect(
            lambda: self.removeRequested.emit(self.path)
        )

        layout.addWidget(self.handle_label, 0)
        layout.addWidget(self.priority_badge, 0)
        layout.addLayout(text_col, 1)
        layout.addWidget(self.remove_button, 0)

    def refresh(self) -> None:
        name = Path(self.path).name
        folder = str(Path(self.path).parent)
        self.priority_badge.setText(f"P{self.priority}")
        self.name_label.setText(name)
        self.folder_label.setText(folder)
        self.setToolTip(f"{name}\n{folder}")


class StemPendingListWidget(QListWidgetDragBugFix):
    """Liste reorderable des fichiers en attente de separation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StemQueueList")
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSpacing(6)
        self.setAlternatingRowColors(False)
        self.setUniformItemSizes(False)


class StemSeparatorToolWidget(QWidget):
    artifactCreated = Signal(object)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.service = self.app_context.stem_separator
        self._qs = QSettings("SampleRod", "Main")
        self._drop_active = False
        self._current_source = ""
        self._queue_entries: list[StemQueueEntry] = []
        self._syncing_queue_list = False
        self._service_status_text = ""
        self._prep_paths: list[str] = []
        self._routing_by_path: dict[str, dict[str, int | None]] = {}
        self._build_ui()
        self._restore_settings()
        self._bind_signals()
        self._sync_queue_view()
        theme.manager.themeChanged.connect(lambda *_args: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("StemToolRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)

        self.title_label = QLabel("Stem Separation")
        self.title_label.setObjectName("StemToolTitle")

        self.subtitle_label = QLabel(
            "Depose une matiere sonore, ajuste sa priorite dans la file, puis laisse les stems descendre dans les artefacts."
        )
        self.subtitle_label.setObjectName("StemToolSubtitle")
        self.subtitle_label.setWordWrap(True)

        header.addWidget(self.title_label)
        header.addWidget(self.subtitle_label)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("StemToolCombo")
        for model in self.service.available_models:
            self.model_combo.addItem(model, model)

        self.output_button = QPushButton("Dossier de travail...")
        self.output_button.setObjectName("StemToolAction")
        self.output_button.clicked.connect(self._choose_workspace_dir)

        self.output_label = QLabel("")
        self.output_label.setObjectName("StemToolOutput")
        self.output_label.setWordWrap(True)

        self.cancel_button = QPushButton("Annuler le courant")
        self.cancel_button.setObjectName("StemToolAction")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.service.cancel_current)

        controls.addWidget(self.model_combo, 0)
        controls.addWidget(self.output_button, 0)
        controls.addWidget(self.output_label, 1)
        controls.addWidget(self.cancel_button, 0)

        self.status_label = QLabel("Preparation du stem separator...")
        self.status_label.setObjectName("StemToolStatus")
        self.status_label.setWordWrap(True)

        self.drop_zone = QWidget()
        self.drop_zone.setObjectName("StemToolDropZone")
        self.drop_zone.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.drop_zone.setAcceptDrops(True)

        drop_layout = QVBoxLayout()
        drop_layout.setContentsMargins(14, 14, 14, 14)
        drop_layout.setSpacing(10)
        self.drop_zone.setLayout(drop_layout)

        drop_header = QHBoxLayout()
        drop_header.setContentsMargins(0, 0, 0, 0)
        drop_header.setSpacing(8)

        drop_titles = QVBoxLayout()
        drop_titles.setContentsMargins(0, 0, 0, 0)
        drop_titles.setSpacing(2)

        self.drop_title = QLabel("Zone de decantation")
        self.drop_title.setObjectName("StemToolDropTitle")

        self.drop_help = QLabel(
            "Glisse ici un sample depuis la Reserve ou un fichier externe : il arrive en preparation. "
            "Route les stems vers les canaux puis clique sur Separer."
        )
        self.drop_help.setObjectName("StemToolDropHelp")
        self.drop_help.setWordWrap(True)

        self.drop_hint = QLabel("Drop")
        self.drop_hint.setObjectName("StemToolDropHint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setFixedSize(54, 28)

        drop_titles.addWidget(self.drop_title)
        drop_titles.addWidget(self.drop_help)

        drop_header.addLayout(drop_titles, 1)
        drop_header.addWidget(self.drop_hint, 0, Qt.AlignmentFlag.AlignTop)

        self.prep_files_host = QWidget()
        self.prep_files_host.setObjectName("StemPrepHost")
        self.prep_files_box = QVBoxLayout(self.prep_files_host)
        self.prep_files_box.setContentsMargins(0, 0, 0, 0)
        self.prep_files_box.setSpacing(4)
        self.prep_files_host.setVisible(False)

        self.routing_board = StemRoutingBoard(self.drop_zone)

        launch_row = QHBoxLayout()
        launch_row.setContentsMargins(0, 0, 0, 0)
        launch_row.setSpacing(6)
        self.launch_button = QPushButton("Separer")
        self.launch_button.setObjectName("StemToolLaunch")
        self.launch_button.setEnabled(False)
        self.launch_button.setToolTip(
            "Lance la separation des fichiers en preparation avec le routage actuel"
        )
        self.launch_button.clicked.connect(self._launch_preparation)
        launch_row.addStretch(1)
        launch_row.addWidget(self.launch_button)

        self.current_card = QWidget()
        self.current_card.setObjectName("StemCurrentCard")
        self.current_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        current_layout = QHBoxLayout()
        current_layout.setContentsMargins(10, 8, 10, 8)
        current_layout.setSpacing(8)
        self.current_card.setLayout(current_layout)

        current_text = QVBoxLayout()
        current_text.setContentsMargins(0, 0, 0, 0)
        current_text.setSpacing(2)

        self.current_badge = QLabel("EN COURS")
        self.current_badge.setObjectName("StemCurrentBadge")

        self.current_name = QLabel("Aucun fichier en cours")
        self.current_name.setObjectName("StemCurrentName")

        self.current_path_label = QLabel("")
        self.current_path_label.setObjectName("StemCurrentPath")
        self.current_path_label.setWordWrap(True)

        current_text.addWidget(self.current_badge)
        current_text.addWidget(self.current_name)
        current_text.addWidget(self.current_path_label)

        self.current_cancel_button = QPushButton("Annuler")
        self.current_cancel_button.setObjectName("StemQueueAction")
        self.current_cancel_button.clicked.connect(self.service.cancel_current)

        current_layout.addLayout(current_text, 1)
        current_layout.addWidget(self.current_cancel_button, 0, Qt.AlignmentFlag.AlignTop)

        queue_header = QHBoxLayout()
        queue_header.setContentsMargins(0, 0, 0, 0)
        queue_header.setSpacing(6)

        self.queue_title = QLabel("File d'attente")
        self.queue_title.setObjectName("StemToolQueueTitle")

        self.queue_count = QLabel("0")
        self.queue_count.setObjectName("StemToolQueueCount")

        queue_header.addWidget(self.queue_title)
        queue_header.addStretch(1)
        queue_header.addWidget(self.queue_count)

        self.empty_label = QLabel(
            "Aucun fichier en attente. Depose de la matiere ici pour lancer la decantation."
        )
        self.empty_label.setObjectName("StemToolEmpty")
        self.empty_label.setWordWrap(True)

        self.pending_list = StemPendingListWidget(self.drop_zone)

        drop_layout.addLayout(drop_header)
        drop_layout.addWidget(self.prep_files_host)
        drop_layout.addWidget(self.routing_board)
        drop_layout.addLayout(launch_row)
        drop_layout.addWidget(self.current_card)
        drop_layout.addLayout(queue_header)
        drop_layout.addWidget(self.empty_label)
        drop_layout.addWidget(self.pending_list, 1)

        self.drop_zone.installEventFilter(self)
        self.pending_list.installEventFilter(self)
        self.pending_list.viewport().installEventFilter(self)

        layout.addLayout(header)
        layout.addLayout(controls)
        layout.addWidget(self.status_label)
        layout.addWidget(self.drop_zone, 1)

        self._apply_styles()

    def _bind_signals(self) -> None:
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.routing_board.routingChanged.connect(self._persist_routing)
        self.service.statusChanged.connect(self._set_status)
        self.service.initialized.connect(self._on_initialized)
        self.service.fileStarted.connect(self._on_file_started)
        self.service.fileFinished.connect(self._on_file_finished)
        self.service.fileFailed.connect(self._on_file_failed)
        self.service.queueIdle.connect(self._on_queue_idle)
        self.service.queueUpdated.connect(self._on_queue_updated)

    def enqueue_paths(self, paths: list[str]) -> int:
        """Met des fichiers en file avec un snapshot du routage actuel."""
        routing = self.routing_board.routing()
        count = self.service.enqueue_paths(paths)
        if count > 0 and any(channel is not None for channel in routing.values()):
            for path in paths or []:
                normalized = normalize_audio_path(path)
                if normalized:
                    self._routing_by_path[normalized] = dict(routing)
        return count

    def add_to_preparation(self, paths: list[str]) -> int:
        """Ajoute des fichiers a la zone de preparation (avant lancement)."""
        added = 0
        for path in paths or []:
            normalized = normalize_audio_path(path)
            if (
                not normalized
                or normalized in self._prep_paths
                or not os.path.isfile(normalized)
                or not is_audio_file(normalized)
            ):
                continue
            self._prep_paths.append(normalized)
            added += 1
        if added > 0:
            self._rebuild_prep_view()
        return added

    def _remove_prep_path(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        if normalized in self._prep_paths:
            self._prep_paths.remove(normalized)
            self._rebuild_prep_view()

    def _rebuild_prep_view(self) -> None:
        while self.prep_files_box.count():
            item = self.prep_files_box.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()
        for path in self._prep_paths:
            self.prep_files_box.addWidget(self._build_prep_chip(path))
        has_prep = bool(self._prep_paths)
        self.prep_files_host.setVisible(has_prep)
        self.launch_button.setEnabled(has_prep)
        self.launch_button.setText(
            f"Separer ({len(self._prep_paths)})" if has_prep else "Separer"
        )
        self._refresh_status()

    def _build_prep_chip(self, path: str) -> QWidget:
        chip = QWidget()
        chip.setObjectName("StemPrepChip")
        chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chip.setToolTip(path)
        row = QHBoxLayout(chip)
        row.setContentsMargins(8, 4, 6, 4)
        row.setSpacing(6)
        name = QLabel(Path(path).name)
        name.setObjectName("StemPrepChipName")
        remove = QPushButton("×")
        remove.setObjectName("StemPrepChipRemove")
        remove.setFixedSize(18, 18)
        remove.setToolTip("Retirer de la preparation")
        remove.clicked.connect(lambda _=False, p=path: self._remove_prep_path(p))
        row.addWidget(name, 1)
        row.addWidget(remove, 0)
        return chip

    def _launch_preparation(self) -> None:
        if not self._prep_paths:
            return
        routing = self.routing_board.routing()
        if all(channel is None for channel in routing.values()):
            self._set_status(
                "Aucun stem route : glisse au moins un pin dans un canal avant de separer."
            )
            return
        paths = list(self._prep_paths)
        count = self.enqueue_paths(paths)
        if count > 0:
            self._prep_paths.clear()
            self._rebuild_prep_view()

    def _persist_routing(self) -> None:
        self._qs.setValue(
            "labo_stem_routing_v1",
            json.dumps(self.routing_board.routing()),
        )

    def updateLibraryOrder(self) -> None:
        if self._syncing_queue_list:
            return
        ordered_paths: list[str] = []
        for index in range(self.pending_list.count()):
            item = self.pending_list.item(index)
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if path:
                ordered_paths.append(path)
        self.service.reorder_pending_paths(ordered_paths)

    def eventFilter(self, watched, event):
        pending_list = getattr(self, "pending_list", None)
        pending_viewport = pending_list.viewport() if pending_list is not None else None
        drop_zone = getattr(self, "drop_zone", None)
        event_type = event.type()
        if watched in {drop_zone, pending_list, pending_viewport}:
            if event_type == QEvent.Type.DragEnter:
                return self._handle_drag_enter(event, watched)
            if event_type == QEvent.Type.DragMove:
                return self._handle_drag_move(event, watched)
            if event_type == QEvent.Type.DragLeave:
                return self._handle_drag_leave(event)
            if event_type == QEvent.Type.Drop:
                return self._handle_drop(event, watched)
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if self._handle_drag_enter(event, self):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._handle_drag_move(event, self):
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        if self._handle_drag_leave(event):
            return
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._handle_drop(event, self):
            return
        super().dropEvent(event)

    def _restore_settings(self) -> None:
        saved_model = self._qs.value("labo_stem_model", self.service.model_name, type=str)
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index) == saved_model:
                self.model_combo.setCurrentIndex(index)
                break

        raw_routing = self._qs.value("labo_stem_routing_v1", "", type=str)
        if raw_routing:
            try:
                data = json.loads(raw_routing)
                if isinstance(data, dict):
                    self.routing_board.set_routing(data)
            except Exception:
                pass

        workspace_dir = self._qs.value("labo_stem_workspace_dir", "", type=str)
        if not workspace_dir or not os.path.isdir(workspace_dir):
            workspace_dir = os.path.join(tempfile.gettempdir(), "SampleRod", "stem_workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        self._set_workspace_dir(workspace_dir)
        self._refresh_status()

    def _choose_workspace_dir(self) -> None:
        start_dir = self.service.output_dir or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choisir le dossier de travail des stems",
            start_dir,
        )
        if folder:
            self._set_workspace_dir(folder)
            self._set_status("Dossier de travail mis a jour.")

    def _set_workspace_dir(self, path: str) -> None:
        normalized = normalize_audio_path(path)
        os.makedirs(normalized, exist_ok=True)
        self.service.set_output_dir(normalized)
        self._qs.setValue("labo_stem_workspace_dir", normalized)
        self.output_label.setText(normalized)
        self.output_label.setToolTip(normalized)

    def _on_model_changed(self, _index: int) -> None:
        model = self.model_combo.currentData()
        if not model:
            return
        self.service.set_model(str(model))
        self._qs.setValue("labo_stem_model", str(model))
        self._refresh_status()

    def _on_initialized(self, ok: bool, message: str) -> None:
        if not ok:
            self.cancel_button.setEnabled(False)
            self.current_cancel_button.setEnabled(False)
        self._set_status(message)

    def _on_file_started(self, path: str) -> None:
        self._current_source = normalize_audio_path(path)
        self.cancel_button.setEnabled(True)
        self.current_cancel_button.setEnabled(True)
        self._refresh_status()

    def _on_file_finished(self, source_path: str, stem_dir: str) -> None:
        self._emit_stem_artifacts(source_path, stem_dir)
        self._refresh_status(extra=f"Stems prets pour {Path(source_path).name}")

    def _on_file_failed(self, source_path: str, _message: str) -> None:
        self._routing_by_path.pop(normalize_audio_path(source_path), None)
        self._refresh_status(extra=f"Echec sur {Path(source_path).name}")

    def _on_queue_idle(self) -> None:
        self.cancel_button.setEnabled(False)
        self.current_cancel_button.setEnabled(False)
        self._refresh_status()

    def _on_queue_updated(self, entries: object) -> None:
        queue_entries = list(entries or [])
        self._queue_entries = [
            entry for entry in queue_entries
            if isinstance(entry, StemQueueEntry)
        ]
        self._current_source = self.service.current_path()
        pending_count = self.service.pending_count()
        has_current = bool(self._current_source)
        self.cancel_button.setEnabled(has_current)
        self.current_cancel_button.setEnabled(has_current)
        self._sync_queue_view()
        self._refresh_status()
        self.queue_count.setText(str(pending_count))

    def _sync_queue_view(self) -> None:
        current_entry = next(
            (entry for entry in self._queue_entries if entry.state == "processing"),
            None,
        )
        pending_entries = [
            entry for entry in self._queue_entries
            if entry.state == "queued"
        ]

        self.current_card.setVisible(current_entry is not None)
        if current_entry is not None:
            current_name = Path(current_entry.path).name
            self.current_name.setText(current_name)
            self.current_path_label.setText(current_entry.path)
            self.current_card.setToolTip(current_entry.path)
        else:
            self.current_name.setText("Aucun fichier en cours")
            self.current_path_label.setText("")
            self.current_card.setToolTip("")

        self._syncing_queue_list = True
        try:
            self.pending_list.clear()
            for index, entry in enumerate(pending_entries, start=1):
                item = QListWidgetItem(self.pending_list)
                item.setData(Qt.ItemDataRole.UserRole, entry.path)
                row = StemQueueRowWidget(entry.path, index, self.pending_list)
                row.removeRequested.connect(self._remove_pending_path)
                item.setSizeHint(row.sizeHint())
                self.pending_list.addItem(item)
                self.pending_list.setItemWidget(item, row)
        finally:
            self._syncing_queue_list = False

        has_pending = bool(pending_entries)
        self.pending_list.setVisible(has_pending)
        self.empty_label.setVisible(not has_pending)

    def _remove_pending_path(self, path: str) -> None:
        self.service.remove_pending_path(path)

    def _emit_stem_artifacts(self, source_path: str, stem_dir: str) -> None:
        source_path = normalize_audio_path(source_path)
        stem_dir = normalize_audio_path(stem_dir)
        routing = self._routing_by_path.pop(source_path, None)
        # Les fichiers "mix_*" sont nos propres sorties d'un passage precedent
        # dans le meme dossier : ils ne sont jamais des stems sources.
        stem_files = {
            stem_file.stem: stem_file
            for stem_file in sorted(Path(stem_dir).glob("*.wav"))
            if not stem_file.stem.startswith("mix_")
        }

        if routing is None:
            for stem_file in stem_files.values():
                self._emit_single_stem(source_path, stem_dir, stem_file)
            return

        channels: dict[int, list[str]] = {}
        for stem_name, stem_file in stem_files.items():
            if stem_name not in routing:
                # Stem inconnu du routage (ex: modele 6 stems) : emis tel quel.
                self._emit_single_stem(source_path, stem_dir, stem_file)
                continue
            channel = routing[stem_name]
            if channel is None:
                continue
            channels.setdefault(int(channel), []).append(stem_name)

        stem_rank = {name: index for index, name in enumerate(STEM_ORDER)}
        for channel in sorted(channels):
            stems = sorted(channels[channel], key=lambda name: stem_rank.get(name, 99))
            if len(stems) == 1:
                self._emit_single_stem(
                    source_path, stem_dir, stem_files[stems[0]], channel=channel
                )
                continue
            mix_name = "+".join(stems)
            output_path = Path(stem_dir) / f"mix_ch{channel + 1}_{mix_name}.wav"
            try:
                duration = mix_stem_files(
                    [str(stem_files[name]) for name in stems],
                    str(output_path),
                )
            except Exception as exc:
                self._set_status(f"Mix du canal {channel + 1} impossible: {exc}")
                continue
            mix_path = normalize_audio_path(str(output_path))
            artifact = LabArtifact(
                artifact_id=f"stemmix::{mix_path}",
                kind="stem",
                display_name=f"{mix_name} ({Path(source_path).stem})",
                source_path=source_path,
                temp_path=mix_path,
                duration=duration,
                persisted=False,
                origin="stem_separation",
                metadata={
                    "stem_name": mix_name,
                    "stems": list(stems),
                    "channel": channel + 1,
                    "workspace_dir": stem_dir,
                },
            )
            self.artifactCreated.emit(artifact)

    def _emit_single_stem(
        self,
        source_path: str,
        stem_dir: str,
        stem_file: Path,
        channel: int | None = None,
    ) -> None:
        stem_path = normalize_audio_path(str(stem_file))
        try:
            metadata = collect_audio_file_metadata(stem_path, include_rms=False)
            duration = float(metadata.duration or 0.0)
        except Exception:
            duration = 0.0
        meta: dict = {
            "stem_name": stem_file.stem,
            "workspace_dir": stem_dir,
        }
        if channel is not None:
            meta["channel"] = channel + 1
        artifact = LabArtifact(
            artifact_id=f"stem::{stem_path}",
            kind="stem",
            display_name=f"{stem_file.stem} ({Path(source_path).stem})",
            source_path=source_path,
            temp_path=stem_path,
            duration=duration,
            persisted=False,
            origin="stem_separation",
            metadata=meta,
        )
        self.artifactCreated.emit(artifact)

    def _handle_drag_enter(self, event, watched) -> bool:
        if watched in {self.pending_list, self.pending_list.viewport()}:
            source = getattr(event, "source", lambda: None)()
            if source is self.pending_list:
                return False
        mime = event.mimeData()
        if not has_supported_audio_drop(mime):
            self._set_drop_active(False)
            return False
        paths = self._paths_from_mime(mime)
        if not paths:
            self._set_drop_active(False)
            return False
        event.acceptProposedAction()
        self._set_drop_active(True)
        return True

    def _handle_drag_move(self, event, watched) -> bool:
        return self._handle_drag_enter(event, watched)

    def _handle_drag_leave(self, event) -> bool:
        self._set_drop_active(False)
        event.accept()
        return True

    def _handle_drop(self, event, watched) -> bool:
        if watched in {self.pending_list, self.pending_list.viewport()}:
            source = getattr(event, "source", lambda: None)()
            if source is self.pending_list:
                return False
        paths = self._paths_from_mime(event.mimeData())
        self._set_drop_active(False)
        if not paths:
            return False
        count = self.add_to_preparation(paths)
        if count <= 0:
            return False
        event.acceptProposedAction()
        return True

    def _paths_from_mime(self, mime) -> list[str]:
        return resolve_audio_drop_paths(
            mime,
            sample_path_lookup=self._path_for_sample_id,
        )

    def _path_for_sample_id(self, sample_id: int) -> str | None:
        samples = self.app_context.sample_store.get_cached()
        sample = next(
            (item for item in samples if int(getattr(item, "id", -1)) == int(sample_id)),
            None,
        )
        path = getattr(sample, "path", "") if sample is not None else ""
        return str(path or "") or None

    def _set_drop_active(self, active: bool) -> None:
        active = bool(active)
        if self._drop_active == active:
            return
        self._drop_active = active
        self.drop_zone.setProperty("dropActive", active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self._refresh_status()

    def _refresh_status(self, *, extra: str = "") -> None:
        if extra:
            self.status_label.setText(extra)
            return
        if not self.service.is_available():
            self.status_label.setText(
                self.service.availability_error() or "Stem separator indisponible."
            )
            return
        if self._drop_active:
            self.status_label.setText(
                "Depose le fichier pour l'ajouter a la file de separation."
            )
            return
        pending_count = self.service.pending_count()
        current_path = self.service.current_path()
        if current_path:
            self.status_label.setText(
                f"Separation en cours: {Path(current_path).name} | En attente: {pending_count}"
            )
            return
        if pending_count > 0:
            self.status_label.setText(f"En attente: {pending_count} fichier(s).")
            return
        if self._prep_paths:
            self.status_label.setText(
                f"{len(self._prep_paths)} fichier(s) en preparation. "
                "Ajuste le routage puis clique sur Separer."
            )
            return
        if self._service_status_text:
            self.status_label.setText(self._service_status_text)
            return
        workspace = self.service.output_dir or "(aucun dossier)"
        self.status_label.setText(f"Pret. Les stems temporaires tombent dans: {workspace}")

    def _set_status(self, text: str) -> None:
        self._service_status_text = text or ""
        self._refresh_status()

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#StemToolRoot {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#StemToolTitle {{
                color: {p.TEXT};
                font-size: 16px;
                font-weight: 700;
            }}
            QLabel#StemToolSubtitle,
            QLabel#StemToolOutput,
            QLabel#StemToolStatus,
            QLabel#StemToolDropHelp,
            QLabel#StemToolEmpty,
            QLabel#StemQueueFolder,
            QLabel#StemCurrentPath {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QLabel#StemToolDropTitle,
            QLabel#StemToolQueueTitle {{
                color: {p.TEXT};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#StemToolDropHint {{
                color: {p.INFO};
                font-size: 11px;
                font-weight: 700;
                background: {p.BG_DARK};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 8px;
            }}
            QLabel#StemToolQueueCount {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
                font-weight: 600;
            }}
            QWidget#StemToolDropZone {{
                background: {p.BG_CARD};
                border: 1px dashed {p.BORDER_LIGHT};
                border-radius: 12px;
            }}
            QWidget#StemToolDropZone[dropActive="true"] {{
                border-color: {p.INFO};
                background: {p.BG_HOVER};
            }}
            QWidget#StemCurrentCard,
            QWidget#StemQueueRow {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER};
                border-radius: 10px;
            }}
            QWidget#StemCurrentCard:hover,
            QWidget#StemQueueRow:hover {{
                border-color: {p.BORDER_LIGHT};
            }}
            QLabel#StemCurrentBadge {{
                color: {p.WARNING};
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#StemCurrentName,
            QLabel#StemQueueName {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#StemQueueHandle {{
                color: {p.TEXT_MUTED};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#StemQueuePriority {{
                color: {p.INFO};
                font-size: 10px;
                font-weight: 700;
                background: {p.BG_DARK};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 2px 0;
            }}
            QListWidget#StemQueueList {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget#StemQueueList::item {{
                border: none;
                background: transparent;
                padding: 0;
            }}
            QListWidget#StemQueueList::item:selected {{
                background: transparent;
            }}
            QPushButton#StemToolAction,
            QComboBox#StemToolCombo,
            QPushButton#StemQueueAction {{
                background: {p.BG_CARD};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QPushButton#StemToolAction:hover,
            QComboBox#StemToolCombo:hover,
            QPushButton#StemQueueAction:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#StemToolAction:disabled,
            QPushButton#StemQueueAction:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER_LIGHT};
            }}
            QLabel#StemRoutingTitle {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#StemRoutingLegend {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            QWidget#StemChannelZone {{
                background: {p.BG_DARK};
                border: 1px dashed {p.BORDER};
                border-radius: 8px;
            }}
            QWidget#StemChannelZone[tray="true"] {{
                background: transparent;
            }}
            QWidget#StemChannelZone[dropActive="true"] {{
                border-color: {p.INFO};
                background: {p.BG_HOVER};
            }}
            QLabel#StemChannelTitle {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
                font-weight: 700;
            }}
            QLabel#StemPin {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 8px;
                font-size: 13px;
            }}
            QLabel#StemPin[stem="drums"] {{ border-color: {STEM_COLORS["drums"]}; }}
            QLabel#StemPin[stem="bass"] {{ border-color: {STEM_COLORS["bass"]}; }}
            QLabel#StemPin[stem="vocals"] {{ border-color: {STEM_COLORS["vocals"]}; }}
            QLabel#StemPin[stem="other"] {{ border-color: {STEM_COLORS["other"]}; }}
            QWidget#StemPrepChip {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QLabel#StemPrepChipName {{
                color: {p.TEXT};
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#StemPrepChipRemove {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: none;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#StemPrepChipRemove:hover {{
                color: {p.TEXT};
            }}
            QPushButton#StemToolLaunch {{
                background: {p.INFO};
                color: {p.BG_DARK};
                border: none;
                border-radius: 8px;
                padding: 6px 18px;
                font-weight: 700;
            }}
            QPushButton#StemToolLaunch:hover {{
                border: 1px solid {p.TEXT};
            }}
            QPushButton#StemToolLaunch:disabled {{
                background: {p.BG_CARD};
                color: {p.TEXT_MUTED};
                border: 1px solid {p.BORDER};
            }}
            """
        )
