"""Panneau de parametres moderne, responsive et charge a la demande."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from frontend.styles import theme
from frontend.ui.lazy_widget import LazyWidgetHost


class SettingsCard(QFrame):
    """Carte plate avec une hierarchie plus legere qu'un QGroupBox."""

    def __init__(self, title: str, description: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("SettingsCardTitle")
        layout.addWidget(title_label)
        if description:
            desc = QLabel(description)
            desc.setObjectName("SettingsCardDescription")
            desc.setWordWrap(True)
            layout.addWidget(desc)
        layout.addWidget(content)


class ResponsiveSettingsPage(QWidget):
    """Une colonne en module etroit, deux dans une grande fenetre."""

    TWO_COLUMN_MIN_WIDTH = 820

    def __init__(self, cards: list[QWidget], parent=None):
        super().__init__(parent)
        self._cards = list(cards)
        self._column_count = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(14, 14, 14, 18)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)
        self._relayout(1)

    @property
    def column_count(self) -> int:
        return self._column_count

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout(2 if event.size().width() >= self.TWO_COLUMN_MIN_WIDTH else 1)

    def _relayout(self, columns: int) -> None:
        columns = max(1, int(columns))
        if columns == self._column_count:
            return
        while self._grid.count():
            self._grid.takeAt(0)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
        final_row = (len(self._cards) + columns - 1) // columns
        self._grid.setRowStretch(final_row, 1)
        for column in range(columns):
            self._grid.setColumnStretch(column, 1)
        self._column_count = columns


class SettingsPanelWidget(QWidget):
    """Panneau partage entre l'onglet classique et le module Parametres."""

    def __init__(self, app_context, parent=None, window_manager=None):
        super().__init__(parent)
        self.app_context = app_context
        self.settings = app_context.settings
        self._window_manager = window_manager
        self._build_ui()
        self._apply_styles()
        theme.manager.themeChanged.connect(lambda *_: self._apply_styles())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)
        self._add_lazy_page("Bibliothèques", self._build_libraries_page)
        self._add_lazy_page("Audio", self._build_audio_page)
        self._add_lazy_page("Interface", self._build_interface_page)
        self._add_lazy_page("Services", self._build_services_page)

    def _add_lazy_page(self, title: str, factory: Callable[[], QWidget]) -> None:
        self.tabs.addTab(LazyWidgetHost(factory, f"Chargement · {title}"), title)

    def _build_libraries_page(self) -> QWidget:
        from frontend.settings_gui.libraries_list import SettingsLibrariesList
        return self._page([self._card(
            "Bibliothèques", "Sources de samples, ordre et dossiers.",
            SettingsLibrariesList(self.app_context),
        )])

    def _build_audio_page(self) -> QWidget:
        from frontend.settings_gui.audio_settings import AudioSettingsWidget
        from frontend.settings_gui.retro_recording_settings import RetroRecordingWidget
        return self._page([
            self._card("Enregistrement rétro", "Buffer récupéré avant une prise.",
                       RetroRecordingWidget(self.settings)),
            self._card("Entrée audio", "Périphérique, fréquence et normalisation.",
                       AudioSettingsWidget(self.app_context)),
        ])

    def _build_interface_page(self) -> QWidget:
        from frontend.settings_gui.display_settings import DisplaySettingsWidget
        from frontend.settings_gui.waveform_settings import WaveformSettingsWidget
        cards = [
            self._card("Affichage", "Densité et pagination.",
                       DisplaySettingsWidget(self.settings)),
            self._card("Waveform", "Découpage et marqueurs.",
                       WaveformSettingsWidget(self.settings)),
        ]
        if self._window_manager is not None:
            from frontend.settings_gui.modular_grid_settings import ModularGridSettingsWidget
            cards.insert(0, self._card(
                "Atelier modulaire", "Quadrillage et alignement des fenêtres.",
                ModularGridSettingsWidget(self._window_manager),
            ))
        return self._page(cards)

    def _build_services_page(self) -> QWidget:
        from frontend.settings_gui.remote_control_settings import RemoteControlSettingsWidget
        from frontend.settings_gui.screenshot_settings import ScreenshotSettingsWidget
        return self._page([
            self._card("Contrôle distant", "Accès local depuis un autre appareil.",
                       RemoteControlSettingsWidget(self.app_context)),
            self._card("Captures d’écran", "Destination et écran utilisé.",
                       ScreenshotSettingsWidget(self.app_context)),
        ])

    @staticmethod
    def _card(title: str, description: str, widget: QWidget) -> SettingsCard:
        return SettingsCard(title, description, widget)

    @staticmethod
    def _page(cards: list[QWidget]) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(ResponsiveSettingsPage(cards))
        return scroll

    def _apply_styles(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(f"""
            SettingsPanelWidget, QScrollArea#SettingsScroll,
            QScrollArea#SettingsScroll > QWidget > QWidget {{
                background: {p.BG_DARK}; border: none;
            }}
            QTabWidget#SettingsTabs::pane {{
                border: none; background: {p.BG_DARK};
            }}
            QTabWidget#SettingsTabs QTabBar::tab {{
                background: transparent; color: {p.TEXT_MUTED}; border: none;
                border-bottom: 2px solid transparent; padding: 9px 14px;
                margin: 0 2px;
            }}
            QTabWidget#SettingsTabs QTabBar::tab:selected {{
                color: {p.TEXT}; border-bottom-color: {p.RETRO};
            }}
            QTabWidget#SettingsTabs QTabBar::tab:hover:!selected {{
                color: {p.TEXT}; background: {p.BG_HOVER};
            }}
            QFrame#SettingsCard {{
                background: {p.BG_MEDIUM}; border: 1px solid {p.BORDER_LIGHT};
                border-radius: 8px;
            }}
            QLabel#SettingsCardTitle {{
                color: {p.TEXT}; font-size: 13px; font-weight: 700;
                border: none; background: transparent;
            }}
            QLabel#SettingsCardDescription {{
                color: {p.TEXT_MUTED}; font-size: 11px;
                border: none; background: transparent;
            }}
        """)
