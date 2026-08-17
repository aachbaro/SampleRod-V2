from __future__ import annotations

import os
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QMenu,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from backend.services.reserve_mutation_service import ReserveMutationStatus
from frontend.styles import theme
from frontend.ui import IconButton, themed_icon

from .reserve_capabilities import reserve_capabilities_for
from .reserve_entry import ReserveEntry, apply_status_badge
from .reserve_formatters import (
    format_reserve_date,
    format_reserve_duration,
    format_reserve_rms,
    format_reserve_scale,
    format_reserve_size,
)
from .reserve_preview import ensure_reserve_preview


class ReserveInspector(QWidget):
    """Inspecteur commun de la Réserve, alimenté exclusivement par ReserveEntry."""

    entryMutated = Signal(object, object)
    analyzeRequested = Signal(object)

    def __init__(self, app_context, *, reserve_actions=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.reserve_actions = reserve_actions
        self.preview = ensure_reserve_preview(app_context)
        self.mutations = (
            getattr(reserve_actions, "mutations", None)
            or getattr(app_context, "reserve_mutations", None)
        )
        self._entry: ReserveEntry | None = None
        self._mode = "compact"
        self._owner_id = f"reserve-inspector-{uuid.uuid4().hex}"
        self._build_ui()
        self.preview.attach_renderer(
            self._owner_id,
            self,
            active=self._on_active_changed,
            position=self._on_position_changed,
            state=self._on_playback_state,
            stopped=self._on_stopped,
        )
        self.destroyed.connect(lambda *_: self.preview.detach_renderer(self._owner_id))
        theme.manager.themeChanged.connect(self._on_theme_changed)
        self.clear_entry()

    @property
    def entry(self) -> ReserveEntry | None:
        return self._entry

    def set_entry(self, entry: ReserveEntry | None) -> None:
        if entry is None:
            self.clear_entry()
            return
        self._entry = entry
        self.title_label.setText(entry.display_name or os.path.basename(entry.path))
        self.path_label.setText(entry.path)
        self.path_label.setToolTip(entry.path)
        apply_status_badge(self.status_label, entry.status)
        self._set_metadata(entry)
        self._set_provenance(entry)
        self._apply_capabilities(entry)
        self._sync_preview()
        self.setVisible(True)

    def clear_entry(self) -> None:
        self._entry = None
        self.title_label.setText("Aucune sélection")
        self.path_label.setText("Sélectionne un son pour afficher ses détails.")
        self.status_label.clear()
        self.status_label.hide()
        for label in self.value_labels.values():
            label.clear()
        self.provenance_label.clear()
        self.provenance_label.hide()
        self.slider.setValue(0)
        self.time_label.setText("0.0 / 0.0 s")
        for button in self.action_buttons:
            button.setEnabled(False)
        self._set_play_state(False)

    def set_mode(self, mode: str) -> None:
        if mode not in {"compact", "expanded"}:
            raise ValueError("mode must be 'compact' or 'expanded'")
        self._mode = mode
        expanded = mode == "expanded"
        self.metadata_widget.setVisible(expanded or self._entry is not None)
        self.path_label.setWordWrap(expanded)
        self.provenance_label.setWordWrap(expanded)
        self.setMaximumHeight(16777215 if expanded else 230)

    def _build_ui(self) -> None:
        self.setObjectName("ReserveInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(4)

        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("ReserveInspectorTitle")
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label = QLabel()
        header.addWidget(self.title_label, 1)
        header.addWidget(self.status_label)
        root.addLayout(header)

        self.path_label = QLabel()
        self.path_label.setObjectName("ReserveInspectorPath")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.path_label)

        self.metadata_widget = QWidget()
        grid = QGridLayout(self.metadata_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        self.value_labels: dict[str, QLabel] = {}
        for column, (key, caption) in enumerate((
            ("duration", "Durée"), ("size", "Poids"), ("date", "Date"),
            ("rms", "RMS"), ("scale", "Gamme"), ("source", "Source"),
        )):
            row, col = divmod(column, 3)
            cell = QLabel()
            cell.setObjectName("ReserveInspectorMeta")
            self.value_labels[key] = cell
            grid.addWidget(QLabel(caption), row * 2, col)
            grid.addWidget(cell, row * 2 + 1, col)
        root.addWidget(self.metadata_widget)

        self.provenance_label = QLabel()
        self.provenance_label.setObjectName("ReserveInspectorProvenance")
        root.addWidget(self.provenance_label)

        playback = QHBoxLayout()
        playback.setSpacing(5)
        self.play_button = IconButton(
            "player-play", tooltip="Lire", size="s", variant="primary", parent=self
        )
        self.play_button.setText("Lire")  # API historique + accessibilite
        self.restart_button = IconButton(
            "refresh", tooltip="Reprendre depuis le début", size="s", parent=self
        )
        self.restart_button.setText("Reprendre")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.time_label = QLabel("0.0 / 0.0 s")
        self.play_button.clicked.connect(self._play_pause)
        self.restart_button.clicked.connect(self._restart)
        self.slider.sliderReleased.connect(self._seek)
        playback.addWidget(self.play_button)
        playback.addWidget(self.restart_button)
        playback.addWidget(self.slider, 1)
        playback.addWidget(self.time_label)
        root.addLayout(playback)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(3)
        self.waveform_button = IconButton(
            "wave", tooltip="Ouvrir dans Waveform", size="s", parent=self
        )
        self.reveal_button = IconButton(
            "folder", tooltip="Afficher dans le dossier", size="s", parent=self
        )
        self.analyze_button = IconButton(
            "bolt", tooltip="Analyser la gamme", size="s", parent=self
        )

        self.more_button = IconButton(
            "dots-vertical", tooltip="Plus d’actions", size="s", parent=self
        )
        self.actions_menu = QMenu(self)
        self.rename_button = self.actions_menu.addAction(
            themed_icon("pencil", size=16), "Renommer"
        )
        self.move_button = self.actions_menu.addAction(
            themed_icon("folder", size=16), "Déplacer…"
        )
        self.actions_menu.addSeparator()
        self.unindex_button = self.actions_menu.addAction("Désindexer")
        self.delete_button = self.actions_menu.addAction(
            themed_icon("trash", size=16, color=theme.manager.p.ERROR), "Supprimer"
        )
        self.more_button.clicked.connect(
            lambda: self.actions_menu.exec(
                self.more_button.mapToGlobal(self.more_button.rect().bottomLeft())
            )
        )
        self.action_buttons = [
            self.play_button, self.restart_button, self.waveform_button,
            self.reveal_button, self.rename_button, self.move_button,
            self.unindex_button, self.delete_button, self.analyze_button,
        ]
        actions.addWidget(self.waveform_button)
        actions.addWidget(self.reveal_button)
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.more_button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.waveform_button.clicked.connect(lambda: self._with_entry("open_waveform"))
        self.reveal_button.clicked.connect(lambda: self._with_entry("reveal_in_folder"))
        self.rename_button.triggered.connect(self._rename)
        self.move_button.triggered.connect(self._move)
        self.unindex_button.triggered.connect(self._unindex)
        self.delete_button.triggered.connect(self._delete)
        self.analyze_button.clicked.connect(lambda: self._entry and self.analyzeRequested.emit(self._entry))
        self._apply_styles()

    def _set_metadata(self, entry: ReserveEntry) -> None:
        try:
            size = os.path.getsize(entry.path) if os.path.isfile(entry.path) else None
        except OSError:
            size = None
        self.value_labels["duration"].setText(format_reserve_duration(entry.duration))
        self.value_labels["size"].setText(format_reserve_size(size) if size is not None else "-")
        self.value_labels["date"].setText(format_reserve_date(entry.created_at))
        self.value_labels["rms"].setText(format_reserve_rms(entry.rms_level))
        self.value_labels["scale"].setText(format_reserve_scale(entry))
        source_label = (
            "Externes"
            if entry.indexed and not entry.root_path
            else entry.source_label
        )
        self.value_labels["source"].setText(source_label)

    def _set_provenance(self, entry: ReserveEntry) -> None:
        provenance = dict((entry.metadata or {}).get("provenance") or {})
        parts = []
        if provenance.get("previous_status"):
            parts.append(str(provenance["previous_status"]).upper())
        source = provenance.get("source_path")
        if source:
            parts.append(os.path.basename(str(source)) or str(source))
        start, end = provenance.get("start_seconds"), provenance.get("end_seconds")
        if start is not None and end is not None:
            parts.append(f"{float(start):.2f}–{float(end):.2f} s")
        self.provenance_label.setText("Provenance · " + " · ".join(parts) if parts else "")
        self.provenance_label.setVisible(bool(parts))

    def _apply_capabilities(self, entry: ReserveEntry) -> None:
        cap = reserve_capabilities_for(entry)
        for button in (self.play_button, self.restart_button):
            button.setEnabled(cap.can_preview)
        self.waveform_button.setEnabled(cap.can_open_waveform)
        self.reveal_button.setEnabled(bool(entry.path))
        self.rename_button.setEnabled(cap.can_rename)
        self.move_button.setEnabled(cap.can_move)
        self.unindex_button.setEnabled(cap.can_unindex)
        self.delete_button.setEnabled(cap.can_delete)
        self.analyze_button.setEnabled(cap.can_analyze)

    def _play_pause(self) -> None:
        if self._entry:
            self.preview.play_pause(self._entry)

    def _restart(self) -> None:
        if self._entry:
            self.preview.restart(self._entry)

    def _seek(self) -> None:
        if self._entry:
            self.preview.seek(self._entry, self.slider.value())

    def _with_entry(self, method: str) -> None:
        if self._entry and self.reserve_actions:
            getattr(self.reserve_actions, method)(self._entry)

    def _rename(self) -> None:
        if not self._entry or self.mutations is None:
            return
        current = os.path.splitext(os.path.basename(self._entry.path))[0]
        name, accepted = QInputDialog.getText(self, "Renommer", "Nouveau nom", text=current)
        if accepted and name.strip():
            self._apply_mutation(self.mutations.rename(self._entry, name.strip()))

    def _move(self) -> None:
        if not self._entry or self.mutations is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Déplacer vers", os.path.dirname(self._entry.path))
        if folder:
            self._apply_mutation(self.mutations.move(self._entry, folder))

    def _unindex(self) -> None:
        if self._entry and self.mutations is not None and self._confirm("Désindexer sans supprimer le fichier ?"):
            self._apply_mutation(self.mutations.unindex(self._entry))

    def _delete(self) -> None:
        if self._entry and self.mutations is not None and self._confirm("Supprimer le fichier et sa fiche ?"):
            self._apply_mutation(self.mutations.delete_file_and_record(self._entry))

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Réserve", text) == QMessageBox.StandardButton.Yes

    def _apply_mutation(self, result) -> None:
        entry = self._entry
        if result.status in {ReserveMutationStatus.SUCCESS, ReserveMutationStatus.QUEUED}:
            self.clear_entry()
        self.entryMutated.emit(entry, result)

    def _sync_preview(self) -> None:
        entry = self._entry
        duration_ms = max(0, int(float(getattr(entry, "duration", 0.0) or 0.0) * 1000))
        self.slider.setRange(0, duration_ms)
        self._set_play_state(bool(entry and self.preview.is_active(entry)))
        self._update_time(self.slider.value())

    def _on_active_changed(self, _entry) -> None:
        self._sync_preview()

    def _on_position_changed(self, entry, position: int) -> None:
        if self._entry and self.preview.is_active(self._entry) and self.preview.is_active(entry):
            if not self.slider.isSliderDown():
                self.slider.setValue(position)
            self._update_time(position)

    def _on_playback_state(self, entry, playing: bool, paused: bool) -> None:
        if self._entry and entry is not None and self.preview.is_active(self._entry):
            self._set_play_state(bool(playing and not paused))

    def _on_stopped(self, _entry) -> None:
        self._set_play_state(False)
        self.slider.setValue(0)
        self._update_time(0)

    def _update_time(self, position_ms: int) -> None:
        duration = float(getattr(self._entry, "duration", 0.0) or 0.0)
        self.time_label.setText(f"{max(0, position_ms) / 1000:.1f} / {duration:.1f} s")

    def _set_play_state(self, playing: bool) -> None:
        self.play_button.setText("Pause" if playing else "Lire")
        self.play_button.setToolTip("Pause" if playing else "Lire")
        self.play_button.set_icon_name("player-pause" if playing else "player-play")

    def _on_theme_changed(self, _name: str) -> None:
        self._apply_styles()
        if self._entry:
            apply_status_badge(self.status_label, self._entry.status)

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"QWidget#ReserveInspector {{ background:{p.BG_MEDIUM}; border:1px solid {p.BORDER}; border-radius:10px; }}"
            f"QLabel#ReserveInspectorTitle {{ color:{p.TEXT}; font-weight:700; }}"
            f"QLabel#ReserveInspectorPath, QLabel#ReserveInspectorMeta, QLabel#ReserveInspectorProvenance {{ color:{p.TEXT_MUTED}; }}"
            f"QLabel#ReserveInspectorPath {{ font-size:11px; }}"
            f"QLabel#ReserveInspectorMeta {{ font-size:11px; }}"
            f"QSlider::groove:horizontal {{ height:3px; background:{p.BORDER}; border-radius:1px; }}"
            f"QSlider::sub-page:horizontal {{ background:{p.ACCENT}; border-radius:1px; }}"
            f"QSlider::handle:horizontal {{ background:{p.TEXT_MUTED}; width:10px; margin:-4px 0; border-radius:5px; }}"
        )
