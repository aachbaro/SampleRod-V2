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
from frontend.dragdrop import (
    DragItem, DragKind, DragPayload, DragProvenance,
    MaterialOperation, MaterialStatus,
    attach_payload, drag_preview_pixmap, drag_session,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QSizePolicy,
    QSlider,
    QWidget,
)

from frontend.reserve import (
    ReserveEntry,
    apply_status_badge,
    format_reserve_clock_duration,
    format_reserve_duration,
    format_reserve_rms,
)

from . import directory_ui

logger = logging.getLogger("directory_item_widget")


class DirectorySubfolderRowWidget(QWidget):
    """
    Ligne compacte représentant un sous-dossier dans la liste.
    Un clic sélectionne la ligne, un double-clic ou → ouvre le dossier.
    """

    clicked = Signal(str)  # path

    def __init__(self, folder_path: str, parent_widget, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.parent_widget = parent_widget
        self.setObjectName("DirectorySubfolderRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)

        icon_lbl = QLabel("▸")
        icon_lbl.setObjectName("SubfolderIcon")
        icon_lbl.setFixedWidth(18)
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        name = os.path.basename(folder_path) or folder_path
        name_lbl = QLabel(name)
        name_lbl.setObjectName("SubfolderName")
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # File count (lazy)
        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("SubfolderCount")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        arrow_lbl = QLabel("›")
        arrow_lbl.setObjectName("SubfolderArrow")
        arrow_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(icon_lbl)
        layout.addWidget(name_lbl, 1)
        layout.addWidget(self._count_lbl)
        layout.addWidget(arrow_lbl)

    def set_count(self, n: int) -> None:
        self._count_lbl.setText(str(n) if n >= 0 else "")

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if self.property("focused") == selected:
            return
        self.setProperty("focused", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.folder_path)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent_widget.open_directory(self.folder_path)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.parent_widget.open_directory(self.folder_path)
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.AltModifier and key == Qt.Key.Key_Right:
            self.parent_widget.open_directory(self.folder_path)
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.AltModifier and key == Qt.Key.Key_Left:
            self.parent_widget.go_to_parent_directory()
            event.accept()
            return
        super().keyPressEvent(event)


class DirectorySectionHeader(QLabel):
    """Séparateur visuel inerte pour la liste mixte dossiers/fichiers."""

    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setObjectName("DirectorySectionHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


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
        self._selected = False
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
            on_find_compatibles=self._on_find_compatibles,
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
        self._refresh_scale_badge()
        self._refresh_duration_chip(entry)

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
        """Valide le renommage depuis le champ texte.

        Si le nouveau nom est identique a l'ancien, on sort silencieusement.
        Sinon, delegue au DirectoryWidget.rename_entry() puis met a jour les
        attributs locaux (file_path, entry.path, display_name) en cas de succes.
        """
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
        """Supprime le fichier apres confirmation.

        Si le fichier est en cours d'ecoute, il est stoppe avant la suppression.
        Si l'entree n'est pas trackee en DB (sample_id=None), la ligne est retiree
        immediatement sans attendre le signal sampleDeleted.
        """
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

        result = self.parent_widget.app_context.reserve_mutations.delete_file_and_record(self.entry)
        success, err = result.success, (result.message or None)
        if not success and err:
            QMessageBox.warning(self, "Erreur", err)

        # Si l'entree n'est pas trackee en DB, on retire immediatement la ligne.
        # Sinon, le sample_store emettra sampleDeleted -> le DirectoryWidget se mettra a jour.
        if self.sample_id is None:
            self.parent_widget._remove_widget(self)

    def _on_find_compatibles(self) -> None:
        if self.sample_id is None:
            return
        self.parent_widget.on_find_compatibles_requested(int(self.sample_id))

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
        selected = bool(selected)
        self._selected = selected
        if self.property("focused") == selected:
            return
        self.setProperty("focused", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        apply_status_badge(self.status_badge, self.entry.status)

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
        descriptor = DragPayload(
            kind=DragKind.AUDIO_FILE,
            items=(DragItem(
                item_id=str(self.sample_id or ""),
                path=self.file_path,
                display_name=os.path.basename(self.file_path) or "Sample",
            ),),
            source_id=f"directory:{self.sample_id or self.file_path}",
            source_module="directory",
            status=MaterialStatus.SOURCE,
            provenance=DragProvenance(self.file_path, MaterialOperation.IMPORT),
        )
        attach_payload(mime, descriptor)
        drag.setMimeData(mime)
        drag.setPixmap(drag_preview_pixmap(descriptor))
        with drag_session(descriptor):
            drag.exec(Qt.DropAction.CopyAction)

    def contextMenuEvent(self, event):
        self.clicked.emit(self)

        menu = QMenu(self)
        preview_label = "Stopper l'ecoute" if self.parent_widget.reserve_actions.is_previewing(self.entry) else "Pre-ecouter"
        preview_action = menu.addAction(f"{preview_label}\tEspace")
        rename_action = menu.addAction("Renommer\tF2")
        compat_action = None
        if self.entry.dominant_note and self.sample_id is not None:
            compat_label = self.entry.detected_scale_label or self.entry.dominant_note
            compat_action = menu.addAction(f"Compatibles avec {compat_label}")
        send_to_lab_action = menu.addAction("Envoyer au labo\tEntrée")
        reveal_action = menu.addAction("Ouvrir le dossier")
        menu.addSeparator()
        delete_action = menu.addAction("Supprimer\tSuppr")

        action = menu.exec(event.globalPos())
        if action is preview_action:
            self._on_clicked()
        elif action is rename_action:
            self._start_rename()
        elif compat_action is not None and action is compat_action:
            self._on_find_compatibles()
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
        self.meta_label.hide()
        self.rename_input.setText(entry.display_name or os.path.splitext(os.path.basename(entry.path))[0])
        self.setToolTip(entry.path)
        self.name_label.setToolTip(entry.path)
        self.meta_label.setToolTip(entry.path)
        apply_status_badge(self.status_badge, entry.status)
        self._refresh_scale_badge()
        self._refresh_duration_chip(entry)
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
        """Met a jour le slider et le label de temps selon la position courante de l'audio_player.

        Appele toutes les 100 ms par le _preview_timer. Si le sample n'est plus
        en lecture (fin naturelle ou stop), bascule la ligne en mode "arrete".
        """
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

    def _advance_preview_position(self, delta_ms: int = 1000) -> None:
        """Déplace la lecture d'une seconde, comme Récents et Indexé."""
        duration_ms = max(0, int(self._duration_ms))
        if duration_ms <= 0:
            return

        current_position_ms = 0
        if self.parent_widget.reserve_actions.is_previewing(self.entry):
            current_position_ms = max(
                0,
                int(self.parent_widget.app_context.audio_player.get_position()),
            )

        target_position_ms = max(0, min(duration_ms, current_position_ms + int(delta_ms)))
        if self.parent_widget.seek_preview(self.entry, target_position_ms):
            self._refresh_time_label(target_position_ms)

    @staticmethod
    def _preview_seek_step_ms(duration_ms: int) -> int:
        if duration_ms <= 0:
            return 0
        return max(750, min(8000, int(duration_ms * 0.10)))

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
        compact_reserve = bool(getattr(self.parent_widget, "embedded_in_reserve", False))
        if compact_reserve:
            column_width = 180 if self.width() >= 520 else (145 if self.width() >= 440 else 110)
            self.name_label.parentWidget().setFixedWidth(column_width)
            available_width = max(32, column_width - 4)
        else:
            available_width = max(32, self.name_label.width() or self.width() - 180)
        self.name_label.setText(
            metrics.elidedText(self._full_display_name, Qt.TextElideMode.ElideMiddle, available_width)
        )
        self.name_label.setToolTip(self.file_path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_display_name()
        self._apply_compact_visibility()

    def eventFilter(self, watched, event):
        # Les labels et conteneurs internes occupent presque toute la carte.
        # Sans ce relais, ils absorbent le clic et seul le petit espace vide de
        # DirectoryRow permet réellement de sélectionner l'entrée.
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and not isinstance(watched, (QAbstractButton, QLineEdit, QSlider))
        ):
            self._drag_start_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.clicked.emit(self)
            event.accept()
            return True
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
            parts.append(format_reserve_clock_duration(entry.duration))
        if entry.rms_level is not None:
            parts.append(f"RMS {format_reserve_rms(entry.rms_level)}")
        return " | ".join(parts)

    def _refresh_duration_chip(self, entry) -> None:
        chip = getattr(self, "duration_chip", None)
        if chip is None:
            return
        chip.setText(format_reserve_clock_duration(entry.duration))
        self._apply_compact_visibility()

    def _apply_compact_visibility(self) -> None:
        width = max(0, self.width())
        compact_reserve = bool(getattr(self.parent_widget, "embedded_in_reserve", False))
        if not compact_reserve:
            return
        self.playback_slider.setVisible(width >= 360)
        self.duration_chip.setVisible(width >= 280 and bool(self.duration_chip.text()))
        self.status_slot.setVisible(width >= 500 or str(getattr(self.entry.status, "value", self.entry.status)) != "normal")
        self.key_slot.setVisible(width >= 390)
        self.key_badge.setVisible(
            width >= 390 and bool(self.entry.dominant_note) and self.sample_id is not None
        )
        # Les états qui demandent une action restent visibles même étroits.
        status_value = str(getattr(self.entry.status, "value", self.entry.status))
        self.status_badge.setVisible(status_value != "normal")

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.AltModifier:
            if key == Qt.Key.Key_Left:
                self.parent_widget.go_to_parent_directory()
                event.accept()
                return
            if key == Qt.Key.Key_Right:
                event.accept()
                return
        if key == Qt.Key.Key_Space:
            self._on_clicked()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.parent_widget.send_path_to_composer(self.file_path)
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self._advance_preview_position(1000)
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self._advance_preview_position(-1000)
            event.accept()
            return
        if key == Qt.Key.Key_F2:
            self._start_rename()
            event.accept()
            return
        if key == Qt.Key.Key_Delete:
            self._on_delete()
            event.accept()
            return
        super().keyPressEvent(event)

    def _refresh_scale_badge(self) -> None:
        """Affiche ou masque le badge de note/gamme (key_badge).

        Le badge n'est visible que si une note dominante est detectee ET que le
        sample est indexe (sample_id != None). Un clic sur le badge declenche
        un filtre "compatibles" dans le DirectoryWidget.
        """
        note = self.entry.dominant_note
        if not note or self.sample_id is None:
            self.key_badge.setVisible(False)
            self.key_badge.setText("")
            self.key_badge.setToolTip("")
            return

        self.key_badge.setText(str(note))
        detected_scale = self.entry.detected_scale_label or note
        label_prefix = "Gamme detectee" if self.entry.detected_scale_kind == "scale" else "Note dominante"
        confidence = (
            f" ({float(self.entry.scale_confidence):.0%})"
            if self.entry.scale_confidence is not None
            else ""
        )
        tooltip_lines = [f"{label_prefix} : {detected_scale}{confidence}"]
        if self.entry.compatible_scales:
            tooltip_lines.append(
                "Compatibles : " + ", ".join(self.entry.compatible_scales)
            )
        tooltip_lines.append("Cliquer pour filtrer les fichiers compatibles")
        self.key_badge.setToolTip("\n".join(tooltip_lines))
        self.key_badge.setVisible(True)
