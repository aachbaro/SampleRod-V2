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

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QListWidgetItem

from .composer_model import ComposerModel
from .composer_ui import build_composer_widget_ui

logger = logging.getLogger("sample_composer_widget")


class SampleComposerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Tool card: stylisee dans RightToolsPanel (tools_panel.py).
        self.setObjectName("ComposerToolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.model = ComposerModel(self)
        self._syncing_view = False

        build_composer_widget_ui(self)
        self._wire_events()
        self._sync_all()

    # ------------------------------------------------------------------ wiring
    def _wire_events(self) -> None:
        # UI -> model
        self.clear_btn.clicked.connect(self.model.clear)
        self.delete_clip_btn.clicked.connect(self._delete_selected_clip)

        self.clip_list.sliceDropped.connect(self._on_slice_dropped)
        self.clip_list.orderChanged.connect(self._on_order_changed)

        # model -> UI
        self.model.clipsChanged.connect(self._sync_clip_list)
        self.model.previewChanged.connect(self._sync_preview_plot)
        self.model.formatChanged.connect(self._sync_info_label)
        self.clip_list.itemSelectionChanged.connect(self._sync_delete_button_state)

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

    # ------------------------------------------------------------------ sync UI
    def _sync_all(self) -> None:
        self._sync_clip_list()
        self._sync_preview_plot()
        self._sync_info_label()
        self._sync_delete_button_state()

    def _sync_delete_button_state(self) -> None:
        has_selection = self.clip_list.currentItem() is not None
        self.delete_clip_btn.setEnabled(has_selection)

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
                item = QListWidgetItem(str(idx + 1))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, int(clip.clip_id))

                tip = f"{clip.label} - {clip.duration_s:.2f}s"
                item.setToolTip(tip)
                self.clip_list.addItem(item)

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

        self._sync_delete_button_state()

    def _sync_preview_plot(self) -> None:
        audio, sr, ch = self.model.render_preview()

        # Clear
        if sr <= 0 or audio is None or audio.size == 0:
            self.curve.setData([], [])
            self.curve_left.setData([], [])
            self.curve_right.setData([], [])
            self.plot.setXRange(0, 1, padding=0)
            self.plot.setYRange(-1, 1, padding=0.1)
            return

        # Downsample pour garder le plot fluide.
        x, y_left, y_right, y_mono = self._make_preview_series(audio, sr)

        if ch == 2 and y_left is not None and y_right is not None:
            self.curve_left.setData(x, y_left)
            self.curve_right.setData(x, y_right)
            self.curve.setData([], [])
        else:
            self.curve.setData(x, y_mono if y_mono is not None else [])
            self.curve_left.setData([], [])
            self.curve_right.setData([], [])

        self.plot.setXRange(float(x[0]), float(x[-1]), padding=0.0)
        self.plot.setYRange(-1.0, 1.0, padding=0.08)

    # ------------------------------------------------------------------ preview helpers
    def _make_preview_series(
        self, audio: np.ndarray, sr: int, *, max_points: int = 4000
    ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        """
        Construit des series downsamplees pour le plot:
        - x: temps (s)
        - y_left/y_right si stereo
        - y_mono si mono
        """
        n_samples = int(audio.shape[0])
        if n_samples <= 1:
            x = np.array([0.0], dtype=np.float32)
            if audio.ndim == 2 and audio.shape[1] == 2:
                return x, np.array([0.0], dtype=np.float32), np.array([0.0], dtype=np.float32), None
            return x, None, None, np.array([0.0], dtype=np.float32)

        step = max(1, n_samples // int(max_points))
        idx = np.arange(0, n_samples, step, dtype=np.int64)
        x = (idx / float(sr)).astype(np.float32, copy=False)

        if audio.ndim == 2 and audio.shape[1] == 2:
            y_left = audio[idx, 0]
            y_right = audio[idx, 1]
            return x, y_left, y_right, None

        y = audio[idx] if audio.ndim == 1 else audio[idx, 0]
        return x, None, None, y

