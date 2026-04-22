"""
------------------------------------------------------------------------------
Directory List Item Widget
------------------------------------------------------------------------------
Role
----
Ce module contient le widget "ligne" utilise par le DirectoryWidget.

Chaque ligne represente un fichier audio present dans le dossier courant et
expose des actions rapides:
- Renommer inline (double-clic sur le nom).
- Pre-ecouter (play/pause) via l'audio_player partage.
- Supprimer le fichier (via sample_store).

Pourquoi l'extraire ?
---------------------
Le DirectoryWidget reste un "orchestrateur" (liste + DnD + synchro store),
alors que la ligne elle-meme est un composant UI autonome.
Cela rend le refactor plus simple et prepare l'arrivee d'autres outils dans le
Right Panel (ex: Sample Composer) sans gonfler un seul fichier monolithique.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import logging
import pickle
from typing import Any

from PySide6.QtCore import QEvent, QMimeData, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QMenu,
    QWidget,
)

from frontend.reserve import ReserveEntry, apply_status_badge

from . import directory_ui

logger = logging.getLogger("directory_item_widget")


class DirectoryListItemWidget(QWidget):
    """
    UI "row" pour la liste du DirectoryWidget.

    Note: on garde volontairement la dependance au parent_widget (DirectoryWidget)
    via des callbacks/methodes (toggle_preview, _remove_widget, app_context...).
    Dans une etape suivante, on pourra remplacer ca par une petite interface
    (controller) pour decoupler davantage.
    """

    clicked = Signal(object)

    def __init__(self, entry: ReserveEntry, parent_widget: Any):
        super().__init__()
        self.entry = entry
        self.file_path = entry.path
        self.parent_widget = parent_widget
        self.sample_id = entry.sample_id
        self._drag_start_pos = None
        self._playing = False
        self._scrubbing = False
        self._duration_ms = max(0, int(float(entry.duration or 0.0) * 1000))
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(100)
        self._preview_timer.timeout.connect(self._sync_playback_position)

        # UI construction: centralisee dans directory_ui.py
        directory_ui.build_directory_item_ui(
            self,
            self.file_path,
            status_text=entry.status_label,
            meta_text=self._build_meta_text(entry),
            on_start_rename=self._start_rename,
            on_submit_rename=self._submit_rename,
            on_toggle_preview=self._on_clicked,
            on_delete=self._on_delete,
        )
        self.playback_slider.sliderPressed.connect(self._on_scrub_started)
        self.playback_slider.sliderMoved.connect(self._on_scrub_moved)
        self.playback_slider.sliderReleased.connect(self._on_scrub_released)
        self._refresh_time_label(0)
        self.setToolTip(self.file_path)
        self.name_label.setToolTip(self.file_path)
        self.meta_label.setToolTip(self.file_path)
        apply_status_badge(self.status_badge, entry.status)
        self._full_display_name = entry.display_name or os.path.basename(entry.path)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
        self._refresh_display_name()

    # ------------------------------------------------------------------ actions
    def _on_clicked(self):
        """Delegue au DirectoryWidget (un seul preview a la fois)."""
        self.clicked.emit(self)
        self.parent_widget.toggle_preview(self)

    # ------------------------------------------------------------------ rename
    def _start_rename(self, event=None):
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        self.rename_input.setText(base_name)
        self.name_label.hide()
        self.rename_input.show()
        self.rename_input.setFocus()
        self.rename_input.selectAll()

    def _submit_rename(self):
        new_name = self.rename_input.text().strip()
        old_base = self.entry.display_name or os.path.splitext(os.path.basename(self.file_path))[0]
        if new_name and new_name != old_base:
            old_path = self.file_path
            success, err = self.parent_widget.rename_entry(self.entry, new_name)
            if success:
                ext = os.path.splitext(self.file_path)[1]
                folder = os.path.dirname(self.file_path)
                new_path = os.path.join(folder, new_name + ext)
                self.file_path = new_path
                self.entry.path = new_path
                self.entry.display_name = new_name
                self.parent_widget.on_file_renamed(old_path, new_path, self.sample_id)
            elif err:
                QMessageBox.warning(self, "Erreur", err)

        self.rename_input.hide()
        self.name_label.show()

    # ------------------------------------------------------------------ delete
    def _on_delete(self):
        reply = QMessageBox.question(
            self,
            "Supprimer",
            f"Supprimer le fichier '{os.path.basename(self.file_path)}' ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Arret de la lecture si ce fichier est en cours.
        ap = self.parent_widget.app_context.audio_player
        if ap.current_sample_path == self.file_path:
            try:
                ap.clear_audio()
            except Exception:
                pass

        success, err = self.parent_widget.app_context.sample_store.delete_by_path(self.file_path)
        if not success and err:
            QMessageBox.warning(self, "Erreur", err)

        # Si l'entree n'est pas trackee en DB, on retire immediatement la ligne.
        # Sinon, le sample_store emettra sampleDeleted -> le DirectoryWidget se mettra a jour.
        if self.sample_id is None:
            self.parent_widget._remove_widget(self)

    # ------------------------------------------------------------------ ui state
    def set_playing(self, playing: bool):
        """Met a jour l'icone play/pause de la ligne."""
        self._playing = bool(playing)
        directory_ui.set_item_playing(self, playing)
        if self._playing:
            self._sync_playback_position()
            if not self._preview_timer.isActive():
                self._preview_timer.start()
            return

        self._preview_timer.stop()
        if not self._scrubbing:
            self.playback_slider.blockSignals(True)
            self.playback_slider.setValue(0)
            self.playback_slider.blockSignals(False)
            self._refresh_time_label(0)

    def set_selected(self, selected: bool):
        if self.property("focused") == selected:
            return
        self.setProperty("focused", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        if selected:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def mouseDoubleClickEvent(self, event):
        """Double-clic sur la carte → envoyer vers la waveform du labo."""
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            # Le double-clic sur le nom déclenche le rename (géré par le label lui-même).
            # Sur tout autre endroit de la carte on ouvre dans le waveform.
            if child is not self.name_label:
                self.parent_widget.send_path_to_composer(self.file_path)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
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

    def _start_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.file_path)])
        if self.sample_id is not None:
            mime.setData(
                "application/x-sample-card",
                pickle.dumps({"sample_id": int(self.sample_id)}),
            )
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def contextMenuEvent(self, event):
        self.clicked.emit(self)

        menu = QMenu(self)
        preview_label = "Stopper l'ecoute" if self.parent_widget.reserve_actions.is_previewing(self.entry) else "Pre-ecouter"
        preview_action = menu.addAction(preview_label)
        rename_action = menu.addAction("Renommer")
        send_to_lab_action = menu.addAction("Envoyer au labo")
        reveal_action = menu.addAction("Ouvrir le dossier")
        menu.addSeparator()
        delete_action = menu.addAction("Supprimer")

        action = menu.exec(event.globalPos())
        if action is preview_action:
            self._on_clicked()
        elif action is rename_action:
            self._start_rename()
        elif action is send_to_lab_action:
            self.parent_widget.send_path_to_composer(self.file_path)
        elif action is reveal_action:
            self.parent_widget.reserve_actions.reveal_in_folder(self.entry)
        elif action is delete_action:
            self._on_delete()

    def refresh_entry(self, entry: ReserveEntry) -> None:
        self.entry = entry
        self.file_path = entry.path
        self.sample_id = entry.sample_id
        self._duration_ms = max(0, int(float(entry.duration or 0.0) * 1000))
        self._full_display_name = entry.display_name or os.path.basename(entry.path)
        self._refresh_display_name()
        self.meta_label.setText(self._build_meta_text(entry))
        self.meta_label.setVisible(bool(self.meta_label.text()))
        self.rename_input.setText(entry.display_name or os.path.splitext(os.path.basename(entry.path))[0])
        self.setToolTip(entry.path)
        self.name_label.setToolTip(entry.path)
        self.meta_label.setToolTip(entry.path)
        apply_status_badge(self.status_badge, entry.status)
        if not self._playing:
            self._refresh_time_label(0)

    def _on_scrub_started(self) -> None:
        self._scrubbing = True

    def _on_scrub_moved(self, value: int) -> None:
        self._refresh_time_label(self._slider_to_ms(value))

    def _on_scrub_released(self) -> None:
        self._scrubbing = False
        position_ms = self._slider_to_ms(self.playback_slider.value())
        self.parent_widget.seek_preview(self.entry, position_ms)
        self._sync_playback_position()

    def _sync_playback_position(self) -> None:
        if self._scrubbing:
            return
        if not self.parent_widget.reserve_actions.is_previewing(self.entry):
            self.set_playing(False)
            return

        position_ms = int(self.parent_widget.app_context.audio_player.get_position())
        if position_ms < 0:
            self.set_playing(False)
            return

        slider_value = self._ms_to_slider(position_ms)
        self.playback_slider.blockSignals(True)
        self.playback_slider.setValue(slider_value)
        self.playback_slider.blockSignals(False)
        self._refresh_time_label(position_ms)

    def _slider_to_ms(self, slider_value: int) -> int:
        duration_ms = max(1, self._duration_ms)
        return int((int(slider_value) / 1000.0) * duration_ms)

    def _ms_to_slider(self, position_ms: int) -> int:
        duration_ms = max(1, self._duration_ms)
        return max(0, min(1000, int((int(position_ms) / duration_ms) * 1000)))

    def _refresh_time_label(self, position_ms: int) -> None:
        total_ms = max(0, self._duration_ms)
        self.time_label.setText(
            f"{self._format_time(position_ms)} / {self._format_time(total_ms)}"
        )

    def _refresh_display_name(self) -> None:
        metrics = self.name_label.fontMetrics()
        available_width = max(32, self.name_label.width() or self.width() - 180)
        self.name_label.setText(
            metrics.elidedText(self._full_display_name, Qt.TextElideMode.ElideMiddle, available_width)
        )
        self.name_label.setToolTip(self.file_path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_display_name()

    def focusInEvent(self, event):
        self.setProperty("focused", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        fw = QApplication.focusWidget()
        if fw and (fw is self or self.isAncestorOf(fw)):
            super().focusOutEvent(event)
            return
        self.setProperty("focused", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusOutEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        return super().eventFilter(watched, event)

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        total_seconds = max(0, int(milliseconds) // 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02}:{seconds:02}"

    @staticmethod
    def _build_meta_text(entry) -> str:
        parts = []
        if entry.duration is not None:
            parts.append(f"{float(entry.duration):.2f}s")
        if entry.rms_level is not None:
            parts.append(f"RMS {float(entry.rms_level):.3f}")
        return " | ".join(parts)
