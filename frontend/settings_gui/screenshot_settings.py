# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres de la fonctionnalite screenshot.
# - Choix dossier cible, ecran cible et activation des options associees.
#
# LIENS CLES
# - backend/services/screenshot_service.py
# - backend/services/settings_service.py
# -----------------------------------------------------------------------------
# frontend/settings_gui/screenshot_settings.py

from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QComboBox,
    QFileDialog,
    QLineEdit,
)
from PySide6.QtCore import Qt
import logging

from backend.models.AppContext import AppContext

logger = logging.getLogger("screenshot_settings")


class ScreenshotSettingsWidget(QWidget):
    """
    Configuration de la capture d'ecran.
    - Toggle on/off
    - Dossier de sauvegarde
    - Ecran par defaut
    """

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.settings = self.app_context.settings
        self.screens = []

        self._build_ui()
        self._load_state()

        self.settings.screenshotToggled.connect(self._on_toggle_signal)
        self.settings.screenshotLibraryChanged.connect(self._on_path_changed)
        self.settings.screenshotDefaultScreenChanged.connect(self._on_screen_changed)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Toggle
        row = QHBoxLayout()
        self.enable_checkbox = QCheckBox("Activer les captures d'ecran")
        self.enable_checkbox.toggled.connect(self._on_toggle)
        row.addWidget(self.enable_checkbox)
        row.addStretch()
        layout.addLayout(row)

        # Dossier
        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText("Selectionner un dossier...")
        self.browse_button = QPushButton("Choisir")
        self.browse_button.clicked.connect(self._choose_folder)
        path_row.addWidget(QLabel("Dossier :"))
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(self.browse_button)
        layout.addLayout(path_row)

        # Ecran par defaut
        screen_row = QHBoxLayout()
        self.screen_combo = QComboBox()
        self.refresh_button = QPushButton("Rafraichir")
        self.refresh_button.clicked.connect(self._load_screens)
        self.screen_combo.currentIndexChanged.connect(self._on_screen_selected)
        screen_row.addWidget(QLabel("Ecran :"))
        screen_row.addWidget(self.screen_combo, 1)
        screen_row.addWidget(self.refresh_button)
        layout.addLayout(screen_row)

        # Hint
        hint = QLabel(
            "Choisis l'ecran et le dossier cible. La capture est accessible "
            "depuis le controle distant."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b6b6b;")
        layout.addWidget(hint)
        layout.addStretch()

    # ------------------------------------------------------------------ State
    def _load_state(self):
        enabled = self.settings.isScreenshotEnabled()
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(enabled)
        self.enable_checkbox.blockSignals(False)

        self.path_input.setText(self.settings.getScreenshotLibraryPath())
        self._load_screens()
        self._apply_enabled(enabled)

    def _apply_enabled(self, enabled: bool):
        self.path_input.setEnabled(enabled)
        self.browse_button.setEnabled(enabled)
        self.screen_combo.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)

    # ------------------------------------------------------------------ Actions
    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if path:
            self.settings.setScreenshotLibraryPath(path)

    def _load_screens(self):
        try:
            self.screens = self.app_context.screenshots.list_screens()
        except Exception:
            self.screens = []
        self.screen_combo.blockSignals(True)
        self.screen_combo.clear()
        for s in self.screens:
            label = s.get("name") or f"Ecran {s.get('index', 0) + 1}"
            self.screen_combo.addItem(label, s.get("index", 0))
        # selection
        target = self.settings.getScreenshotDefaultScreen()
        idx = next((i for i in range(self.screen_combo.count())
                    if self.screen_combo.itemData(i) == target), 0)
        if self.screen_combo.count():
            self.screen_combo.setCurrentIndex(idx)
        self.screen_combo.blockSignals(False)

    def _on_toggle(self, checked: bool):
        self.settings.setScreenshotEnabled(checked)
        self._apply_enabled(checked)

    def _on_toggle_signal(self, enabled: bool):
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(enabled)
        self.enable_checkbox.blockSignals(False)
        self._apply_enabled(enabled)

    def _on_path_changed(self, path: str):
        self.path_input.setText(path)

    def _on_screen_selected(self, _index: int):
        data = self.screen_combo.currentData()
        if data is None:
            return
        try:
            self.settings.setScreenshotDefaultScreen(int(data))
        except Exception:
            pass

    def _on_screen_changed(self, index: int):
        idx = next((i for i in range(self.screen_combo.count())
                    if self.screen_combo.itemData(i) == index), 0)
        self.screen_combo.blockSignals(True)
        if self.screen_combo.count():
            self.screen_combo.setCurrentIndex(idx)
        self.screen_combo.blockSignals(False)
