# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Carte UI representant une capture d'ecran sauvegardee.
# - Affiche miniature, metadonnees et actions (ouvrir/rename/delete).
#
# LIENS CLES
# - frontend/screenshot_gui/screenshot_list.py
# - backend/services/screenshot_service.py
# -----------------------------------------------------------------------------
# frontend/screenshot_gui/screenshot_card.py

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QSizePolicy,
)

from frontend.sample_gui.waveform.waveform_ui import HoverIconButton


class ScreenshotCard(QWidget):
    def __init__(self, app_context, item: dict, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.svc = app_context.screenshots
        self.item = item
        self._build_ui()
        self._render()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ScreenshotCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.setStyleSheet("""
        QWidget#ScreenshotCard {
            background-color: #1b1b1b;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
        }
        QWidget#ScreenshotCard:hover {
            background-color: #202020;
            border-color: #3a3a3a;
        }
        QLabel#ShotName {
            font-weight: 600;
            font-size: 14px;
            color: #f5f5f5;
        }
        QLabel#ShotMeta {
            color: #b9b9b9;
            font-size: 11px;
        }
        QLineEdit#ShotRenameInput {
            background-color: #2a2a2a;
            color: #ffffff;
            border: 1px solid #f2c94c;
            padding: 4px 6px;
            border-radius: 4px;
        }
        QLabel#ShotPreview {
            background-color: #111111;
            border: 1px solid #2a2a2a;
            border-radius: 8px;
        }
        """)

        btn_size = 24
        btn_icon = 10
        icon_normal = "#cfcfcf"
        icon_hover = "#121212"

        # preview
        self.preview = QLabel()
        self.preview.setObjectName("ShotPreview")
        self.preview.setFixedSize(QSize(120, 80))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # name + rename
        self.name_label = QLabel("")
        self.name_label.setObjectName("ShotName")
        self.rename_input = QLineEdit()
        self.rename_input.setObjectName("ShotRenameInput")
        self.rename_input.returnPressed.connect(self._submit_rename)
        self.rename_input.setVisible(False)

        # meta
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("ShotMeta")

        # buttons
        self.rename_button = self._make_btn("fa6s.pen", "Renommer", icon_normal, icon_hover, btn_size, btn_icon)
        self.rename_button.clicked.connect(self._start_rename)

        self.folder_button = self._make_btn("fa5s.folder-open", "Ouvrir le dossier", icon_normal, icon_hover, btn_size, btn_icon)
        self.folder_button.clicked.connect(self._open_folder)

        self.delete_button = self._make_btn("fa5s.trash-alt", "Supprimer", "#d77a7a", icon_hover, btn_size, btn_icon)
        self.delete_button.clicked.connect(self._delete)

        # layout
        main = QHBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(12)
        main.addWidget(self.preview)

        right = QVBoxLayout()
        right.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self.name_label, 1)
        header.addWidget(self.rename_input, 1)
        header.addWidget(self.rename_button)
        header.addWidget(self.folder_button)
        header.addWidget(self.delete_button)

        right.addLayout(header)
        right.addWidget(self.meta_label)
        right.addStretch(1)

        main.addLayout(right, 1)

    # ------------------------------------------------------------------ Data
    def _render(self):
        filename = self.item.get("filename", "")
        self.name_label.setText(filename)
        self.rename_input.setText(Path(filename).stem)

        created_at = self.item.get("created_at")
        try:
            created_at = datetime.fromisoformat(created_at).strftime("%d/%m/%Y %H:%M")
        except Exception:
            created_at = created_at or ""

        screen_index = self.item.get("screen_index", 0)
        size_txt = f"{self.item.get('width', 0)}x{self.item.get('height', 0)}"
        self.meta_label.setText(f"{created_at} · Ecran {int(screen_index)+1} · {size_txt}")

        path = self.svc.get_path(int(self.item.get("id", -1)))
        if path and Path(path).exists():
            pix = QPixmap(path)
            if not pix.isNull():
                pix = pix.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
                self.preview.setPixmap(pix)

    # ------------------------------------------------------------------ Actions
    def _start_rename(self):
        self.name_label.setVisible(False)
        self.rename_input.setVisible(True)
        self.rename_input.setFocus()
        self.rename_input.selectAll()

    def _submit_rename(self):
        new_name = self.rename_input.text().strip()
        if not new_name:
            self._cancel_rename()
            return
        meta = self.svc.rename(int(self.item.get("id", -1)), new_name)
        if meta:
            self.item = meta
            self._render()
        self._cancel_rename()

    def _cancel_rename(self):
        self.rename_input.setVisible(False)
        self.name_label.setVisible(True)

    def _delete(self):
        self.svc.delete(int(self.item.get("id", -1)))

    def _open_folder(self):
        path = self.svc.get_path(int(self.item.get("id", -1)))
        if not path:
            return
        folder = str(Path(path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def mouseDoubleClickEvent(self, event):
        # ouvre l'image en double clic
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.rename_input.isVisible():
            return
        path = self.svc.get_path(int(self.item.get("id", -1)))
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ Utils
    def _make_btn(self, icon_name, tooltip, color_normal, color_hover, size, icon_size):
        btn = HoverIconButton(
            icon_name=icon_name,
            size=size,
            icon_size=icon_size,
            icon_color_normal=color_normal,
            icon_color_hover=color_hover,
            border_color="#2a2a2a",
            parent=self,
        )
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn
