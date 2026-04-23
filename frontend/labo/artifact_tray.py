from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QMimeData, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend.custom_widgets import CustomSlider

from backend.services.audio_metadata import get_audio_duration
from frontend.styles import theme

from .lab_artifact import (
    LabArtifact,
    artifact_duration_label,
    artifact_file_path,
    artifact_kind_label,
    artifact_source_name,
    artifact_status_label,
)


def _fmt_ms(ms: float) -> str:
    """Format milliseconds → M:SS ou X.Xs."""
    secs = max(0.0, ms / 1000.0)
    if secs >= 60:
        m = int(secs) // 60
        s = int(secs) % 60
        return f"{m}:{s:02d}"
    return f"{secs:.1f}s"


def _short_kind(kind: str) -> str:
    return {
        "slice": "CUT",
        "stem": "STEM",
        "current_file": "FILE",
        "break_preview": "QTZ",
    }.get(kind, kind.upper()[:4])



class ArtifactTrayRow(QWidget):
    previewRequested = Signal(str)
    saveRequested = Signal(str)
    openRequested = Signal(str)
    seekRequested = Signal(str, float)    # artifact_id, pos_ms
    removeRequested = Signal(str, bool)   # artifact_id, delete_from_disk

    def __init__(self, artifact: LabArtifact, parent=None):
        super().__init__(parent)
        self.artifact = artifact
        self._drag_start_pos: QPoint | None = None
        self._playing = False
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("ArtifactTrayRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        # ── Bouton play / pause ──────────────────────────────────────────
        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("ArtifactPlayBtn")
        self.play_button.setFixedSize(24, 24)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(
            lambda: self.previewRequested.emit(self.artifact.artifact_id)
        )

        # ── Badge de type ────────────────────────────────────────────────
        self.kind_label = QLabel("")
        self.kind_label.setObjectName("ArtifactKind")

        # ── Nom (tronqué, tooltip = métas complètes) ─────────────────────
        self.name_label = QLabel("")
        self.name_label.setObjectName("ArtifactName")
        self.name_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.name_label.setMinimumWidth(50)
        self.name_label.setMaximumWidth(200)

        # ── Slider de lecture (même logique que les sample cards) ─────────
        self.slider = CustomSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("ArtifactSlider")
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.sliderMoved.connect(self._on_slider_moved)

        # ── Temps ────────────────────────────────────────────────────────
        self.time_label = QLabel("—")
        self.time_label.setObjectName("ArtifactTime")
        self.time_label.setFixedWidth(42)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ── Bouton supprimer ─────────────────────────────────────────────
        self.delete_button = QPushButton("✕")
        self.delete_button.setObjectName("ArtifactDeleteBtn")
        self.delete_button.setFixedSize(18, 18)
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setToolTip("Supprimer l'artefact")
        self.delete_button.clicked.connect(
            lambda: self.removeRequested.emit(self.artifact.artifact_id, True)
        )

        layout.addWidget(self.play_button)
        layout.addWidget(self.kind_label)
        layout.addWidget(self.name_label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.time_label)
        layout.addWidget(self.delete_button)

    # ------------------------------------------------------------------
    # Mise à jour des données

    def refresh(self) -> None:
        artifact = self.artifact
        active_path = artifact_file_path(artifact)
        stem_name = str(artifact.metadata.get("stem_name", "") or "").strip()

        self.kind_label.setText(_short_kind(artifact.kind))

        # Nom élisionné
        fm = self.name_label.fontMetrics()
        elided = fm.elidedText(
            artifact.display_name,
            Qt.TextElideMode.ElideRight,
            self.name_label.maximumWidth() - 4,
        )
        self.name_label.setText(elided)

        # Slider range
        duration_ms = int((artifact.duration or 0.0) * 1000)
        self.slider.setRange(0, max(1, duration_ms))
        if not self._playing:
            self.slider.blockSignals(True)
            self.slider.setValue(0)
            self.slider.blockSignals(False)
            self.time_label.setText(_fmt_ms(duration_ms) if duration_ms > 0 else "—")

        # Tooltip riche
        parts = [
            artifact.display_name,
            f"Stem : {stem_name}" if stem_name else "",
            f"Source : {artifact_source_name(artifact)}",
            f"Durée : {artifact_duration_label(artifact.duration)}",
            f"Statut : {artifact_status_label(artifact)}",
            f"Origine : {artifact.origin}" if artifact.origin else "",
            f"Chemin : {active_path or artifact.source_path}",
        ]
        self.setToolTip("\n".join(p for p in parts if p))

        has_file = bool(active_path and os.path.isfile(active_path))
        self.play_button.setEnabled(has_file)
        self.slider.setEnabled(has_file)
        self._apply_play_state()

    # ------------------------------------------------------------------
    # État lecture

    def set_playing(self, playing: bool) -> None:
        if self._playing == bool(playing):
            return
        self._playing = bool(playing)
        if not self._playing:
            self._reset_position()
        self._apply_play_state()

    def update_position(self, pos_ms: float) -> None:
        duration_ms = self.slider.maximum()
        if duration_ms <= 0:
            return
        self.slider.blockSignals(True)
        self.slider.setValue(int(min(max(0, pos_ms), duration_ms)))
        self.slider.blockSignals(False)
        self.time_label.setText(_fmt_ms(pos_ms))

    def _reset_position(self) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        duration_ms = self.slider.maximum()
        self.time_label.setText(_fmt_ms(duration_ms) if duration_ms > 0 else "—")

    def _apply_play_state(self) -> None:
        self.play_button.setText("⏸" if self._playing else "▶")

    # ------------------------------------------------------------------
    # Slider seek


    def _on_slider_moved(self, value: int) -> None:
        """Seek en temps réel pendant le drag du handle."""
        self.seekRequested.emit(self.artifact.artifact_id, float(value))


    # ------------------------------------------------------------------
    # Souris / drag-and-drop (move)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.openRequested.emit(self.artifact.artifact_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
            and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._start_drag()
            self._drag_start_pos = None
            return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event) -> None:
        path = artifact_file_path(self.artifact)
        menu = QMenu(self)
        preview_label = "Stopper l'écoute" if self._playing else "Lire"
        preview_action = menu.addAction(preview_label)
        open_action = menu.addAction("Ouvrir dans Waveform")
        save_action = menu.addAction("Sauvegarder sous…")
        reveal_action = menu.addAction("Ouvrir le dossier")
        menu.addSeparator()
        delete_action = menu.addAction("Supprimer l'artefact")

        if not path or not os.path.isfile(path):
            preview_action.setEnabled(False)
            open_action.setEnabled(False)
            save_action.setEnabled(False)
            reveal_action.setEnabled(False)

        action = menu.exec(event.globalPos())
        if action is preview_action:
            self.previewRequested.emit(self.artifact.artifact_id)
        elif action is open_action:
            self.openRequested.emit(self.artifact.artifact_id)
        elif action is save_action:
            self.saveRequested.emit(self.artifact.artifact_id)
        elif action is reveal_action and path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        elif action is delete_action:
            self.removeRequested.emit(self.artifact.artifact_id, True)

    def _start_drag(self) -> None:
        path = artifact_file_path(self.artifact)
        if not path or not os.path.isfile(path):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        drag.setMimeData(mime)
        result = drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)
        if result == Qt.DropAction.MoveAction:
            # La cible a déplacé le fichier elle-même — source déjà supprimée.
            self.removeRequested.emit(self.artifact.artifact_id, False)
        elif result == Qt.DropAction.CopyAction:
            # La cible a copié le fichier → on supprime la source pour garantir
            # la sémantique "déplacer" (l'artefact ne vit qu'à un seul endroit).
            self.removeRequested.emit(self.artifact.artifact_id, True)


# ======================================================================
# Conteneur principal
# ======================================================================

class ArtifactTrayWidget(QWidget):
    saveArtifactRequested = Signal(str)
    openArtifactRequested = Signal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._rows: dict[str, tuple[QListWidgetItem, ArtifactTrayRow]] = {}
        self._expanded = True
        self._build_ui()
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(100)
        self._preview_timer.timeout.connect(self._sync_preview_state)
        self._preview_timer.start()
        theme.manager.themeChanged.connect(lambda *_: self._apply_styles())

    def _build_ui(self) -> None:
        self.setObjectName("ArtifactTrayRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 8)
        layout.setSpacing(6)

        # ── En-tête ────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(5)

        self.toggle_btn = QPushButton("▼")
        self.toggle_btn.setObjectName("ArtifactToggleBtn")
        self.toggle_btn.setFixedSize(16, 16)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setToolTip("Réduire / développer")
        self.toggle_btn.clicked.connect(self._toggle_expand)

        self.title_label = QLabel("Artefacts")
        self.title_label.setObjectName("ArtifactTrayTitle")

        self.count_label = QLabel("0")
        self.count_label.setObjectName("ArtifactTrayCount")

        header.addWidget(self.toggle_btn)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.count_label)

        # ── Liste ───────────────────────────────────────────────────────
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("ArtifactTrayList")
        self.list_widget.setSpacing(3)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        layout.addLayout(header)
        layout.addWidget(self.list_widget, 1)

        self._apply_styles()

    # ------------------------------------------------------------------
    # Collapse / expand

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self.list_widget.setVisible(self._expanded)
        self.toggle_btn.setText("▼" if self._expanded else "▶")

    # ------------------------------------------------------------------
    # Gestion des artefacts

    def upsert_artifact(self, artifact: LabArtifact) -> None:
        row_data = self._rows.get(artifact.artifact_id)
        if row_data is None:
            item = QListWidgetItem(self.list_widget)
            row = ArtifactTrayRow(artifact, self.list_widget)
            row.previewRequested.connect(self._toggle_preview)
            row.saveRequested.connect(self.saveArtifactRequested.emit)
            row.openRequested.connect(self.openArtifactRequested.emit)
            row.seekRequested.connect(self._on_seek_requested)
            row.removeRequested.connect(self._on_remove_requested)
            item.setSizeHint(row.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)
            self._rows[artifact.artifact_id] = (item, row)
        else:
            item, row = row_data
            row.artifact = artifact
            row.refresh()
            item.setSizeHint(row.sizeHint())
        self._update_count()
        self._sync_preview_state()

    def set_artifacts(self, artifacts: list[LabArtifact]) -> None:
        self.list_widget.clear()
        self._rows.clear()
        for artifact in artifacts:
            self.upsert_artifact(artifact)
        self._update_count()

    def artifact(self, artifact_id: str) -> LabArtifact | None:
        row_data = self._rows.get(artifact_id)
        return row_data[1].artifact if row_data else None

    # ------------------------------------------------------------------
    # Suppression

    def _on_remove_requested(self, artifact_id: str, delete_from_disk: bool) -> None:
        """Retire un artefact du tray. Si delete_from_disk, supprime aussi le fichier temp."""
        artifact = self.artifact(artifact_id)

        # Stopper la lecture si c'est cet artefact qui joue
        if artifact is not None and self._is_playing(artifact):
            try:
                self.app_context.audio_player.clear_audio()
            except Exception:
                pass

        # Supprimer le fichier si demandé (bouton ✕ ou menu clic droit)
        if delete_from_disk and artifact is not None:
            path = artifact_file_path(artifact)
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        # Retirer la ligne
        row_data = self._rows.pop(artifact_id, None)
        if row_data:
            item, _ = row_data
            row_idx = self.list_widget.row(item)
            if row_idx >= 0:
                self.list_widget.takeItem(row_idx)

        self._update_count()

    # ------------------------------------------------------------------
    # Lecture

    def _toggle_preview(self, artifact_id: str) -> None:
        artifact = self.artifact(artifact_id)
        if artifact is None:
            return
        path = artifact_file_path(artifact)
        if not path or not os.path.isfile(path):
            return

        player = self.app_context.audio_player
        sample_id = hash(("artifact", artifact_id)) & 0x7FFFFFFF

        # Si un autre artefact tourne, on le coupe d'abord
        if player.is_playing and player.current_sample_path:
            current = os.path.normcase(os.path.normpath(player.current_sample_path))
            this = os.path.normcase(os.path.normpath(path))
            if current != this:
                try:
                    player.clear_audio()
                except Exception:
                    pass

        duration = float(artifact.duration or 0.0)
        if duration <= 0:
            try:
                duration = float(get_audio_duration(path))
            except Exception:
                duration = 0.0

        player.toggle_play(sample_id, path, duration)
        self._sync_preview_state()

    def _on_seek_requested(self, artifact_id: str, pos_ms: float) -> None:
        artifact = self.artifact(artifact_id)
        if artifact is None:
            return
        path = artifact_file_path(artifact)
        if not path or not os.path.isfile(path):
            return
        sample_id = hash(("artifact", artifact_id)) & 0x7FFFFFFF
        duration = float(artifact.duration or 0.0)
        if duration <= 0:
            return
        try:
            self.app_context.audio_player.seek_position(sample_id, path, duration, pos_ms)
        except Exception:
            pass
        self._sync_preview_state()

    def _is_playing(self, artifact: LabArtifact) -> bool:
        path = artifact_file_path(artifact)
        if not path:
            return False
        player = self.app_context.audio_player
        if not player.is_playing:
            return False
        current = os.path.normcase(os.path.normpath(player.current_sample_path or ""))
        return current == os.path.normcase(os.path.normpath(path))

    def _sync_preview_state(self) -> None:
        player = self.app_context.audio_player
        pos_ms = -1.0
        try:
            if player.is_playing and not getattr(player, "is_paused", False):
                raw = player.get_position()
                if raw >= 0:
                    pos_ms = float(raw)
        except Exception:
            pass

        for _, row in self._rows.values():
            is_playing = self._is_playing(row.artifact)
            row.set_playing(is_playing)
            if is_playing and pos_ms >= 0:
                row.update_position(pos_ms)

    # ------------------------------------------------------------------
    # Compteur

    def _update_count(self) -> None:
        count = len(self._rows)
        self.count_label.setText(f"{count} artefact{'s' if count != 1 else ''}")

    # ------------------------------------------------------------------
    # Styles

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            QWidget#ArtifactTrayRoot {{
                background: {p.BG_MEDIUM};
                border: 1px solid {p.BORDER_LIGHT};
                border-radius: 10px;
            }}
            QLabel#ArtifactTrayTitle {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#ArtifactTrayCount {{
                color: {p.TEXT_MUTED};
                font-size: 11px;
            }}
            QPushButton#ArtifactToggleBtn {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: none;
                border-radius: 4px;
                font-size: 8px;
                padding: 0;
            }}
            QPushButton#ArtifactToggleBtn:hover {{
                background: {p.BG_HOVER};
                color: {p.TEXT};
            }}
            QListWidget#ArtifactTrayList {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget#ArtifactTrayList::item {{
                border: none;
                background: transparent;
                padding: 0;
            }}
            QWidget#ArtifactTrayRow {{
                background: {p.BG_CARD};
                border: 1px solid {p.BORDER};
                border-radius: 8px;
            }}
            QWidget#ArtifactTrayRow:hover {{
                border-color: {p.BORDER_LIGHT};
            }}
            QLabel#ArtifactKind {{
                color: {p.WARNING};
                font-size: 9px;
                font-weight: 700;
                padding: 1px 5px;
                background: {p.BG_DARK};
                border: 1px solid {p.BORDER};
                border-radius: 6px;
            }}
            QLabel#ArtifactName {{
                color: {p.TEXT};
                font-size: 12px;
                font-weight: 500;
            }}
            QLabel#ArtifactTime {{
                color: {p.TEXT_MUTED};
                font-size: 10px;
            }}
            QPushButton#ArtifactPlayBtn {{
                background: {p.BG_DARK};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 12px;
                font-size: 9px;
                fo
                font-weight: 700;
                padding: 0;
            }}
            QPushButton#ArtifactPlayBtn:hover {{
                background: {p.BG_HOVER};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#ArtifactPlayBtn:disabled {{
                color: {p.TEXT_MUTED};
                border-color: {p.BORDER_LIGHT};
            }}
            QPushButton#ArtifactDeleteBtn {{
                background: transparent;
                color: {p.TEXT_MUTED};
                border: none;
                border-radius: 9px;
                font-size: 9px;
                font-weight: 700;
                padding: 0;
            }}
            QPushButton#ArtifactDeleteBtn:hover {{
                background: {p.ERROR};
                color: #ffffff;
            }}
            QSlider#ArtifactSlider {{
                height: 14px;
            }}
            QSlider#ArtifactSlider::groove:horizontal {{
                height: 3px;
                background: {p.BORDER};
                border-radius: 2px;
                margin: 0px;
            }}
            QSlider#ArtifactSlider::sub-page:horizontal {{
                background: {p.INFO};
                border-radius: 2px;
            }}
            QSlider#ArtifactSlider::handle:horizontal {{
                width: 10px;
                height: 10px;
                background: {p.TEXT_MUTED};
                border-radius: 5px;
                margin: -4px 0;
            }}
            QSlider#ArtifactSlider::handle:horizontal:hover {{
                background: {p.TEXT};
            }}
            QSlider#ArtifactSlider:disabled::groove:horizontal {{
                background: {p.BORDER_LIGHT};
            }}
            QSlider#ArtifactSlider:disabled::handle:horizontal {{
                background: {p.BORDER_LIGHT};
            }}
            """
        )
