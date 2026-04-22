"""
------------------------------------------------------------------------------
Sample Composer - Widget (Tool UI + orchestration)
------------------------------------------------------------------------------
Role
----
Ce widget est l'onglet "Compositeur" du RightToolsPanel.

Il orchestre:
- l'UI (construction via composer_ui.py)
- le modele (ComposerModel: clips + format cible + preview concat)
- le drag & drop (via ComposerClipListWidget)
- le rendu preview (PlotWidget PyQtGraph)

Ce que fait l'outil (MVP)
-------------------------
- Drop une slice depuis le MarkerManager (MIME: application/x-sample-slice-data)
  -> ajoute un clip dans la composition.
- Reorder interne (drag & drop dans la colonne des clips).
- Preview: affiche la waveform du resultat concatene.

Ce que l'outil ne fait pas encore
---------------------------------
- Export en fichier / creation de "Sample" dans la DB
- Crossfades / trims par clip
- Undo/redo

Notes UI
--------
- Le "cadre" global (background/border/radius) est applique par RightToolsPanel
  sur QWidget#ComposerToolCard pour rester coherent avec DirectoryToolCard.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import os

import pyqtgraph as pg
from PySide6.QtCore import Qt, QEvent, QThread, Signal, QSettings
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QListWidgetItem, QApplication, QFileDialog

from frontend.sample_gui.wave_form import WaveformWidget
from frontend.sample_gui.waveform.waveform_plot_helpers import ContextMenuLinearRegionItem

from .composer_model import ComposerModel
from .composer_ui import build_composer_widget_ui
from .composer_dnd import (
    has_audio_file_urls,
    has_sample_card,
    has_slice,
    parse_audio_file_urls,
    parse_sample_card_mime,
    parse_slice_mime,
)
from .composer_clip_list import ComposerClipRow

logger = logging.getLogger("sample_composer_widget")


class SampleComposerWidget(QWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        logger.info("[Composer] Initialisation (start)")

        # Tool card: stylisee dans RightToolsPanel (tools_panel.py).
        self.setObjectName("ComposerToolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.app_context = app_context
        self.model = ComposerModel(self)
        self._syncing_view = False
        self._boundary_lines: list[pg.InfiniteLine] = []
        self._load_threads: dict[int, _ComposerSampleLoader] = {}

        logger.info("[Composer] UI build (start)")
        build_composer_widget_ui(self)
        logger.info("[Composer] UI build (done)")
        self._build_waveform()
        self._wire_events()
        self._build_shortcuts()
        self._install_focus_filters()
        self._sync_all()
        self.setAcceptDrops(True)
        logger.info("[Composer] DnD target ready (acceptDrops=True)")
        logger.info("[Composer] Initialisation (ready)")

    # ------------------------------------------------------------------ wiring
    def _wire_events(self) -> None:
        # UI -> model
        self.clear_btn.clicked.connect(self.model.clear)
        self.save_comp_btn.clicked.connect(self._save_composition)

        self.clip_list.sliceDropped.connect(self._on_slice_dropped)
        self.clip_list.orderChanged.connect(self._on_order_changed)
        self.clip_list.itemClicked.connect(self._on_clip_item_clicked)
        self.clip_list.sampleCardDropped.connect(self._on_sample_card_dropped)
        self.clip_list.audioFilesDropped.connect(self.add_file_paths)

        # model -> UI
        self.model.clipsChanged.connect(self._sync_clip_list)
        self.model.previewChanged.connect(self._sync_preview_plot)
        self.model.formatChanged.connect(self._sync_info_label)
        self.clip_list.itemSelectionChanged.connect(self._sync_save_button_state)

    def _build_shortcuts(self) -> None:
        """
        Raccourcis actifs seulement quand le compositeur (ou un enfant) a le focus.
        On aligne les touches de playback sur celles du Waveform Editor.
        """
        for seq, handler in [
            ("Ctrl+X", lambda: self._with_wave(lambda w: w._on_cut_shortcut())),
            ("Ctrl+Z", lambda: self._with_wave(lambda w: w.undo())),
            ("Ctrl+Shift+Z", lambda: self._with_wave(lambda w: w.redo())),
            ("Ctrl+S", lambda: self._with_wave(lambda w: w.onSaveClicked())),
            ("Ctrl+L", lambda: self._with_wave(lambda w: w.loop_button.toggle())),
            ("Ctrl+G", lambda: self._with_wave(lambda w: w.toggle_marker_mode(not w.marker_mode))),
            ("Space", lambda: self._with_wave(lambda w: w.pause_or_resume())),
            ("Ctrl+Space", lambda: self._with_wave(lambda w: w.play_from_start())),
            ("Alt+Space", lambda: self._with_wave(lambda w: w.stop_and_reset())),
            ("Ctrl+E", lambda: self._with_wave(lambda w: w._on_export_shortcut())),
            ("Ctrl+Shift+G", lambda: self._with_wave(lambda w: w.add_markers_to_region())),
        ]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    def _with_wave(self, fn):
        if hasattr(self, "waveform") and self.waveform:
            fn(self.waveform)

    # ------------------------------------------------------------------ focus handling
    def _install_focus_filters(self) -> None:
        # Installer l'event filter sur tous les enfants pour gerer le focus visuel
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            self.setFocus()
        if event.type() == QEvent.Type.DragLeave:
            self._set_drop_active(False)
            return False
        if event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            return self._handle_drag_event(event)
        return False

    def focusInEvent(self, event):
        self.setProperty("focused", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self._clear_sample_card_focus()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        fw = QApplication.focusWidget()
        if fw and (fw is self or self.isAncestorOf(fw)):
            return
        self.setProperty("focused", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusOutEvent(event)

    # ------------------------------------------------------------------ drag & drop (global)
    def dragEnterEvent(self, event):
        self._handle_drag_event(event)

    def dragMoveEvent(self, event):
        self._handle_drag_event(event)

    def dragLeaveEvent(self, event):
        self._set_drop_active(False)
        event.accept()

    def dropEvent(self, event):
        self._handle_drag_event(event)

    def _handle_drag_event(self, event) -> bool:
        mime = event.mimeData()
        if event.type() == QEvent.Type.Drop:
            logger.info(
                "[Composer] drop formats=%s",
                list(mime.formats()),
            )
        if has_slice(mime) or has_sample_card(mime) or has_audio_file_urls(mime):
            if event.type() == QEvent.Type.Drop:
                if has_slice(mime):
                    try:
                        payload = parse_slice_mime(mime)
                        self._on_slice_dropped(payload)
                    except Exception:
                        logger.exception("[Composer] Invalid slice drop")
                elif has_sample_card(mime):
                    try:
                        payload = parse_sample_card_mime(mime)
                        self._on_sample_card_dropped(payload)
                    except Exception:
                        logger.exception("[Composer] Invalid sample-card drop")
                elif has_audio_file_urls(mime):
                    try:
                        self.add_file_paths(parse_audio_file_urls(mime))
                    except Exception:
                        logger.exception("[Composer] Invalid file-url drop")
                self._set_drop_active(False)
            else:
                self._set_drop_active(True)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return True

        event.ignore()
        return False

    def _set_drop_active(self, active: bool) -> None:
        if self.property("dropActive") == active:
            return
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _clear_sample_card_focus(self) -> None:
        """
        Retire l'etat "focused" de toutes les SampleCards.
        (On ne touche pas a l'etat "checked" pour ne pas casser la selection.)
        """
        for w in QApplication.allWidgets():
            try:
                if w.objectName() != "SampleCard":
                    continue
                if w.property("focused"):
                    w.setProperty("focused", False)
                    w.style().unpolish(w)
                    w.style().polish(w)
            except Exception:
                continue


        # model -> UI
        self.model.clipsChanged.connect(self._sync_clip_list)
        self.model.previewChanged.connect(self._sync_preview_plot)
        self.model.formatChanged.connect(self._sync_info_label)
        self.clip_list.itemSelectionChanged.connect(self._sync_save_button_state)

    # ------------------------------------------------------------------ actions
    def _on_slice_dropped(self, payload: dict) -> None:
        """
        Slot: drop externe d'une slice (depuis MarkerManager).

        payload (normalise par composer_dnd.py):
        - audio, sample_rate, label, source
        """
        try:
            self.model.add_slice(
                audio=payload.get("audio"),
                sample_rate=payload.get("sample_rate"),
                label=payload.get("label", "slice"),
                source=payload.get("source") or {},
            )
        except Exception as e:
            logger.exception("[Composer] Failed to add slice")
            self.info_label.setText(f"Drop refuse: {e}")

    def _on_order_changed(self, ordered_ids: list[int]) -> None:
        if self._syncing_view:
            return
        try:
            self.model.reorder_by_ids(list(ordered_ids))
        except Exception:
            logger.exception("[Composer] Failed to reorder clips")

    def _delete_selected_clip(self) -> None:
        item = self.clip_list.currentItem()
        if not item:
            return
        try:
            clip_id = int(item.data(Qt.ItemDataRole.UserRole))
        except Exception:
            return
        self.model.remove_clip(clip_id)

    def _remove_clip_by_id(self, clip_id: int) -> None:
        try:
            self.model.remove_clip(int(clip_id))
        except Exception:
            logger.exception("[Composer] Failed to remove clip")

    def _add_silence_after(self, clip_id: int) -> None:
        try:
            self.model.insert_silence_after(int(clip_id), duration_s=1.0)
        except Exception as e:
            logger.exception("[Composer] Failed to insert silence")
            try:
                self.info_label.setText(f"Impossible d'ajouter un blanc: {e}")
            except Exception:
                pass

    def _play_clip_by_id(self, clip_id: int) -> None:
        # Selection visuelle sur la ligne correspondante
        for i in range(self.clip_list.count()):
            item = self.clip_list.item(i)
            try:
                cid = int(item.data(Qt.ItemDataRole.UserRole))
            except Exception:
                continue
            if cid == int(clip_id):
                self.clip_list.setCurrentItem(item)
                break
        rng = self._clip_time_range(clip_id)
        if not rng:
            return
        start, end = rng
        self._set_waveform_region(start, end)
        self.waveform.play_from_start()

    def _clip_time_range(self, clip_id: int) -> tuple[float, float] | None:
        start = 0.0
        for clip in self.model.clips:
            end = start + float(clip.duration_s)
            if int(clip.clip_id) == int(clip_id):
                return start, end
            start = end
        return None

    def _on_sample_card_dropped(self, payload: dict) -> None:
        """
        Drop d'une SampleCard -> charge le fichier audio et ajoute un clip entier.
        """
        try:
            sample_id = int(payload.get("sample_id"))
        except Exception:
            logger.info("[Composer] sample-card drop invalide")
            return

        # Récupère le sample en cache
        sample = next(
            (s for s in self.app_context.sample_store.get_cached() if getattr(s, "id", None) == sample_id),
            None,
        )
        if not sample:
            self.info_label.setText("Sample introuvable dans le cache")
            return

        self._queue_audio_file_load(
            sample_id,
            sample.path,
            sample.name,
            {"sample_id": int(sample.id), "path": sample.path},
        )

    def add_file_paths(self, paths: list[str]) -> None:
        normalized_paths = []
        for path in paths:
            try:
                normalized = os.path.normpath(os.path.abspath(path))
            except Exception:
                continue
            if os.path.isfile(normalized):
                normalized_paths.append(normalized)

        if not normalized_paths:
            self.info_label.setText("Aucun fichier audio local exploitable")
            return

        for path in normalized_paths:
            sample = next(
                (s for s in self.app_context.sample_store.get_cached() if getattr(s, "path", None) == path),
                None,
            )
            sample_id = int(getattr(sample, "id", 0) or 0) if sample is not None else abs(hash(path))
            name = getattr(sample, "name", None) or os.path.splitext(os.path.basename(path))[0]
            source = {"path": path}
            if sample is not None:
                source["sample_id"] = int(sample.id)
            self._queue_audio_file_load(sample_id, path, name, source)

    def _on_sample_loaded(self, sample_id: int, audio, sr: int, name: str, source: dict) -> None:
        try:
            self.model.add_slice(
                audio=audio,
                sample_rate=sr,
                label=name,
                source=source,
            )
            self.info_label.setText("Drop des slices (markers) pour composer un sample")
        except Exception as e:
            logger.exception("[Composer] Failed to add sample card")
            self.info_label.setText(f"Drop refuse: {e}")

    def _on_sample_load_failed(self, sample_id: int, message: str) -> None:
        self.info_label.setText(f"Erreur chargement sample: {message}")

    def _queue_audio_file_load(self, sample_id: int, path: str, name: str, source: dict | None = None) -> None:
        if sample_id in self._load_threads:
            return
        self.info_label.setText(f"Chargement: {name}...")
        loader = _ComposerSampleLoader(sample_id, path, name, source=source or {}, parent=self)
        loader.loaded.connect(self._on_sample_loaded)
        loader.failed.connect(self._on_sample_load_failed)
        loader.finished.connect(lambda: self._load_threads.pop(sample_id, None))
        self._load_threads[sample_id] = loader
        loader.start()

    # ------------------------------------------------------------------ sync UI
    def _sync_all(self) -> None:
        self._sync_clip_list()
        self._sync_preview_plot()
        self._sync_info_label()
        self._sync_save_button_state()

    def _sync_save_button_state(self) -> None:
        # Active le bouton save uniquement s'il y a au moins un clip.
        has_clips = len(self.model.clips) > 0
        self.save_comp_btn.setEnabled(has_clips)
        self._sync_clip_row_selection()

    def _sync_clip_row_selection(self) -> None:
        cur = self.clip_list.currentItem()
        for i in range(self.clip_list.count()):
            item = self.clip_list.item(i)
            row = self.clip_list.itemWidget(item)
            if row is None or not hasattr(row, "set_selected"):
                continue
            row.set_selected(item is cur)

    def _sync_info_label(self) -> None:
        if self.model.is_empty():
            self.info_label.setText("Drop des slices (markers) pour composer un sample")
            return

        audio, sr, ch = self.model.render_preview()
        duration_s = 0.0
        if sr and audio is not None and audio.size:
            duration_s = float(audio.shape[0]) / float(sr)

        ch_txt = "stereo" if ch == 2 else "mono"
        self.info_label.setText(
            f"{len(self.model.clips)} clip(s)  -  {duration_s:.2f}s  -  {sr} Hz  -  {ch_txt}"
        )

    def _sync_clip_list(self) -> None:
        selected_id: int | None = None
        cur = self.clip_list.currentItem()
        if cur is not None:
            try:
                selected_id = int(cur.data(Qt.ItemDataRole.UserRole))
            except Exception:
                selected_id = None

        self._syncing_view = True
        try:
            self.clip_list.clear()
            for idx, clip in enumerate(self.model.clips):
                label = f"{idx + 1} — {clip.label}"
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, int(clip.clip_id))

                tip = f"{clip.label} • {clip.duration_s:.2f}s • {clip.sr} Hz"
                item.setToolTip(tip)
                self.clip_list.addItem(item)
                row = ComposerClipRow(int(clip.clip_id), label, parent=self.clip_list)
                row.removeRequested.connect(self._remove_clip_by_id)
                row.playRequested.connect(self._play_clip_by_id)
                row.silenceRequested.connect(self._add_silence_after)
                row.clicked.connect(lambda _=None, it=item: self.clip_list.setCurrentItem(it))
                item.setSizeHint(row.sizeHint())
                self.clip_list.setItemWidget(item, row)

            # Restore selection by clip_id
            if selected_id is not None:
                for i in range(self.clip_list.count()):
                    it = self.clip_list.item(i)
                    try:
                        cid = int(it.data(Qt.ItemDataRole.UserRole))
                    except Exception:
                        continue
                    if cid == selected_id:
                        self.clip_list.setCurrentItem(it)
                        break
        finally:
            self._syncing_view = False

        self._sync_save_button_state()

    # ------------------------------------------------------------------ export (UI)
    def _save_composition(self) -> None:
        """
        Ouvre un QFileDialog pour choisir un dossier de sauvegarde.
        Le dernier dossier est memorise via QSettings.
        """
        # Rien a sauver
        audio, sr, ch = self.model.render_preview()
        if sr <= 0 or audio is None or audio.size == 0:
            try:
                self.info_label.setText("Aucune composition a sauvegarder")
            except Exception:
                pass
            return

        default_dir = self._get_default_export_dir()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier de sauvegarde",
            default_dir,
        )
        if not directory:
            return

        # Persiste le dernier dossier choisi
        try:
            qs = QSettings("SampleRod", "Main")
            qs.setValue("composer_last_export_dir", directory)
        except Exception:
            pass

        # Ecriture du fichier WAV + ajout dans la DB via SampleService
        try:
            import soundfile as sf
            from backend.models.sample import Sample as DBSample
            from backend.services.notification_service import NotificationType

            base_name = f"SMPL_{DBSample.get_next_id():04d}"
            target = self._unique_export_path(directory, base_name, ".wav")

            sf.write(target, audio, sr)
            # Cree le nouveau sample (FS+DB) + notification standard
            self.app_context.sample_store.add(target)
            # Feedback court
            self.app_context.notifications.notify(
                title="✅ Composition sauvegardee",
                message=os.path.basename(target),
                type=NotificationType.SUCCESS,
            )
        except Exception as e:
            try:
                from backend.services.notification_service import NotificationType
                self.app_context.notifications.notify(
                    title="❌ Erreur sauvegarde",
                    message=str(e),
                    type=NotificationType.ERROR,
                )
            except Exception:
                pass

    def _get_default_export_dir(self) -> str:
        """
        Priorite:
        1) Dernier dossier choisi (QSettings)
        2) Premiere librairie de samples (SettingsService)
        3) Dossier utilisateur
        """
        try:
            qs = QSettings("SampleRod", "Main")
            last = qs.value("composer_last_export_dir", "")
            if last and isinstance(last, str) and os.path.isdir(last):
                return last
        except Exception:
            pass

        libs = getattr(self.app_context.settings, "libraries", []) or []
        if libs:
            try:
                libs_sorted = sorted(libs, key=lambda lib: getattr(lib, "position", 0))
                path = getattr(libs_sorted[0], "path", "")
                if path and os.path.isdir(path):
                    return path
            except Exception:
                pass

        return os.path.expanduser("~")

    @staticmethod
    def _unique_export_path(folder: str, base: str, ext: str) -> str:
        """
        Genere un chemin unique (si le fichier existe deja).
        """
        candidate = os.path.join(folder, f"{base}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i = 2
        while True:
            candidate = os.path.join(folder, f"{base}_{i}{ext}")
            if not os.path.exists(candidate):
                return candidate
            i += 1

    def _sync_preview_plot(self) -> None:
        audio, sr, ch = self.model.render_preview()

        # Clear
        if sr <= 0 or audio is None or audio.size == 0:
            self._clear_waveform()
            self._clear_boundary_lines()
            if hasattr(self, "time_label"):
                self.time_label.setText("Durée: 0.00s")
            return

        duration_s = float(audio.shape[0]) / float(sr) if sr > 0 else 1.0
        if duration_s <= 0:
            duration_s = 1.0
        # Alimente le vrai WaveformWidget (meme rendu que l'editor).
        # WaveformWidget attend un format "channel-first" (n_channels, n_samples)
        # car il transpose en interne pour obtenir (n_samples, n_channels).
        audio_for_widget = audio
        if audio is not None and getattr(audio, "ndim", 0) == 2:
            # audio est normalement (n_samples, 2) -> on transpose pour correspondre
            # a l'attente du WaveformWidget.
            if audio.shape[1] == 2:
                audio_for_widget = audio.T
        self.waveform.set_waveform_data(audio_for_widget, sr, duration_s)
        # Assure un playback "plein buffer" par defaut
        self.waveform.play_start = 0.0
        self.waveform.play_end = float(duration_s)
        self._update_boundary_lines()
        if hasattr(self, "time_label"):
            self.time_label.setText(f"Durée: {duration_s:.2f}s")

    # ------------------------------------------------------------------ boundaries
    def _clear_boundary_lines(self) -> None:
        if not self._boundary_lines:
            return
        for line in self._boundary_lines:
            try:
                self.waveform.plot.removeItem(line)
            except Exception:
                pass
        self._boundary_lines = []

    def _update_boundary_lines(self) -> None:
        """
        Affiche des lignes verticales (jaunes) entre les clips.
        """
        # Nettoie avant de reposer les lignes.
        self._clear_boundary_lines()

        if self.model.is_empty():
            return

        # On place une ligne a chaque frontiere entre clips (cumul des durées).
        t = 0.0
        clips = self.model.clips
        if len(clips) <= 1:
            return

        for clip in clips[:-1]:
            t += float(clip.duration_s)
            line = pg.InfiniteLine(
                pos=t,
                angle=90,
                pen=pg.mkPen("#DAA520", width=1),
            )
            line.setMovable(False)
            line.setZValue(20)
            self.waveform.plot.addItem(line)
            self._boundary_lines.append(line)

    # ------------------------------------------------------------------ waveform integration
    def _build_waveform(self) -> None:
        # Reutilise le vrai WaveformWidget (sans auto-load).
        self.waveform = WaveformWidget(None, self.app_context, auto_load=False)
        self.waveform_layout.addWidget(self.waveform)

        # On garde les interactions classiques (selection / play start),
        # mais on bloque les actions destructives (cut/export).
        self.waveform.disable_region_interactions = False
        self.waveform.disable_marker_add = False
        self.waveform.allow_cut_export = False
        # Pas de region active au depart -> playback doit lire tout le buffer.
        self.waveform.play_start = 0.0
        self.waveform.play_end = 0.0

        # Masque des actions non pertinentes en mode compositeur.
        for btn_name in ("save_button", "undo_button", "redo_button", "marker_mode_button"):
            btn = getattr(self.waveform, btn_name, None)
            if btn is not None:
                btn.setVisible(False)

        # Cache la colonne de markers a droite (on utilise la liste en dessous).
        marker_list = getattr(self.waveform, "marker_list", None)
        if marker_list is not None:
            marker_list.setVisible(False)
            marker_list.setFixedWidth(0)
            marker_list.setMaximumWidth(0)

    def _clear_waveform(self) -> None:
        w = self.waveform
        try:
            w.waveform_data = None
            w.sample_rate = None
            w.duration = 0.0
            w.curve.setData([], [])
            w.curve_left.setData([], [])
            w.curve_right.setData([], [])
            w.plot.setXRange(0, 1, padding=0)
            w.plot.setYRange(-1, 1, padding=0.1)
        except Exception:
            pass

    def _on_clip_item_clicked(self, item: QListWidgetItem) -> None:
        """
        Selectionne la region correspondant au clip (start/end).
        """
        try:
            row = self.clip_list.row(item)
        except Exception:
            return
        clips = self.model.clips
        if row < 0 or row >= len(clips):
            return

        start = 0.0
        for c in clips[:row]:
            start += float(c.duration_s)
        end = start + float(clips[row].duration_s)
        self._set_waveform_region(start, end)

    def _set_waveform_region(self, start: float, end: float) -> None:
        w = self.waveform
        if w is None:
            return
        if end < start:
            start, end = end, start

        # Supprime l'ancienne region si elle existe
        if getattr(w, "region", None) is not None:
            try:
                w.plot.removeItem(w.region)
            except Exception:
                pass
            w.region = None

        # Cree une region "selection" simple (comme dans WaveformMarkersController)
        w.region = ContextMenuLinearRegionItem(
            [start, end],
            brush=pg.mkBrush(255, 255, 255, 40),
            pen=pg.mkPen("c", width=1),
        )
        w.region.setZValue(1)
        w.region.setBounds([0, w.duration])
        w.region.sigRegionChangeFinished.connect(w.on_region_changed)
        w.region._parent = w
        w.plot.addItem(w.region)

        w.play_start, w.play_end = start, end
        w.read_head.setPos(start)


class _ComposerSampleLoader(QThread):
    loaded = Signal(int, object, int, str, dict)
    failed = Signal(int, str)

    def __init__(self, sample_id: int, path: str, name: str, source: dict | None = None, parent=None):
        super().__init__(parent)
        self.sample_id = sample_id
        self.path = path
        self.name = name
        self.source = dict(source or {})

    def run(self):
        try:
            import soundfile as sf

            y, sr = sf.read(self.path, dtype="float32", always_2d=True)
            source = dict(self.source)
            source.setdefault("path", self.path)
            source.setdefault("sample_id", int(self.sample_id))
            self.loaded.emit(
                int(self.sample_id),
                y,
                int(sr),
                self.name,
                source,
            )
        except Exception as e:
            self.failed.emit(int(self.sample_id), str(e))
