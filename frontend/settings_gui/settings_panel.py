from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from frontend.settings_gui.audio_settings import AudioSettingsWidget
from frontend.settings_gui.display_settings import DisplaySettingsWidget
from frontend.settings_gui.libraries_list import SettingsLibrariesList
from frontend.settings_gui.remote_control_settings import RemoteControlSettingsWidget
from frontend.settings_gui.retro_recording_settings import RetroRecordingWidget
from frontend.settings_gui.screenshot_settings import ScreenshotSettingsWidget
from frontend.settings_gui.waveform_settings import WaveformSettingsWidget


class SettingsPanelWidget(QWidget):
    """Panneau partage des reglages, reutilisable en onglet classique ou module."""

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.settings = app_context.settings
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 12, 12, 12)
        container_layout.setSpacing(12)

        settings_libraries_list = SettingsLibrariesList(self.app_context)
        settings_retro_widget = RetroRecordingWidget(self.settings)
        audio_settings_widget = AudioSettingsWidget(self.app_context)
        display_settings_widget = DisplaySettingsWidget(self.settings)
        remote_control_widget = RemoteControlSettingsWidget(self.app_context)
        screenshot_settings_widget = ScreenshotSettingsWidget(self.app_context)
        waveform_settings_widget = WaveformSettingsWidget(self.settings)

        libraries_group = self._make_settings_group(
            "Bibliotheques",
            "Gestion des bibliotheques de samples (ajout, suppression, ordre).",
            settings_libraries_list,
        )
        container_layout.addWidget(libraries_group)

        columns = QHBoxLayout()
        columns.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        retro_group = self._make_settings_group(
            "Enregistrement retro",
            "Active le pre-enregistrement, ajuste la duree du buffer, puis utilise la molette sur REC pour choisir le retro time de chaque prise.",
            settings_retro_widget,
        )
        display_group = self._make_settings_group(
            "Affichage",
            "Configuration de la pagination et de la densite des listes.",
            display_settings_widget,
        )
        audio_group = self._make_settings_group(
            "Audio",
            "Sample rate, loopback et normalisation.",
            audio_settings_widget,
        )
        remote_group = self._make_settings_group(
            "Controle distant",
            "Piloter l'app depuis un navigateur (mobile) sur le meme reseau.",
            remote_control_widget,
        )
        screenshot_group = self._make_settings_group(
            "Captures d'ecran",
            "Capturer des images depuis le telephone (optionnel).",
            screenshot_settings_widget,
        )
        waveform_group = self._make_settings_group(
            "Waveform / Decoupage",
            "Comportement de l'editeur waveform et des outils de decoupage.",
            waveform_settings_widget,
        )

        left_col.addWidget(retro_group)
        left_col.addWidget(display_group)
        left_col.addWidget(waveform_group)
        left_col.addStretch()

        right_col.addWidget(audio_group)
        right_col.addWidget(remote_group)
        right_col.addWidget(screenshot_group)
        right_col.addStretch()

        columns.addLayout(left_col, 1)
        columns.addLayout(right_col, 1)
        container_layout.addLayout(columns)
        container_layout.addStretch()

    @staticmethod
    def _make_settings_group(title: str, description: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setObjectName("SettingsDesc")
            layout.addWidget(desc_label)

        layout.addWidget(widget)
        return group
