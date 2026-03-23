# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fenetre principale de l'application desktop.
# - Compose les onglets, panneaux et widgets racine de l'interface.
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_list.py
# - frontend/right_panel/tools_panel.py
# - frontend/record_widget.py
# -----------------------------------------------------------------------------
# frontend/main_window.py

from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QGroupBox,
    QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence
import logging
logger = logging.getLogger("main_window")

import qtawesome as qta

from frontend.record_widget import RecordWidgetWindow
from frontend.settings_gui.libraries_list import SettingsLibrariesList
from frontend.settings_gui.retro_recording_settings import RetroRecordingWidget
from frontend.sample_gui.sample.sample_list import SampleListWidget
from frontend.settings_gui.audio_settings import AudioSettingsWidget
from frontend.settings_gui.display_settings import DisplaySettingsWidget
from frontend.settings_gui.remote_control_settings import RemoteControlSettingsWidget
from frontend.settings_gui.screenshot_settings import ScreenshotSettingsWidget
from frontend.screenshot_gui.screenshot_list import ScreenshotListWidget
from frontend.notification_widgets import NotificationManager, NotificationCenter
from frontend.right_panel.tools_panel import RightToolsPanel
from frontend.styles import theme

from backend.services.directory_service import DirectoryService

from backend.models.AppContext import AppContext

class MainWindow(QMainWindow):
    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context
        self.settings = self.app_context.settings
        self.directory_service = DirectoryService(self.app_context.sample_store)
        
        self._setup_window()
        self._build_ui()
        self._init_signals()
        self._init_shortcuts()
        theme.manager.apply()
        theme.manager.themeChanged.connect(self._on_theme_changed)

    def _setup_window(self):
        """Configure la fenÃªtre principale"""
        self.setWindowTitle("SampleRod")
        self.setGeometry(300, 200, 1200, 600)
        # DÃ©marrage en mode maximisÃ© (barre de titre visible)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _build_ui(self):
        """Construit l'interface utilisateur"""
        # Conteneur d'onglets
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("MainTabWidget")
        # Theme global (fond) : on veut que les "gaps" autour des widgets (marges, splitters,
        # etc.) soient coherents avec le reste (SampleCard / SampleList / Waveform).
        # On limite volontairement le scope via des objectName pour eviter des effets de bord.
        self.setObjectName("MainWindow")
        self._apply_window_stylesheet()
        self.setCentralWidget(self.tab_widget)

        # --- Onglet 'Enregistrement' (pop-up flottant)
        self.record_widget = RecordWidgetWindow(self.app_context)
        self.record_widget.show()
        # On ne l'ajoute pas aux tabs, c'est une fenÃªtre indÃ©pendante

        # --- Onglet 'Liste des Samples'
        samples_tab = QWidget()
        samples_layout = QHBoxLayout(samples_tab)
        self.sample_list_widget = SampleListWidget(
            app_context=self.app_context
        )

        # ---- Right tools panel (Directory + future tools like Sample Composer) ----
        self.right_tools_panel = RightToolsPanel(
            directory_service=self.directory_service,
            app_context=self.app_context,
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.sample_list_widget)
        splitter.addWidget(self.right_tools_panel)
        splitter.setSizes([350, 100])

        samples_layout.addWidget(splitter)

        self.tab_widget.addTab(samples_tab, "Liste des Samples")

        # --- Onglet 'Screenshots'
        screenshots_tab = QWidget()
        screenshots_layout = QVBoxLayout(screenshots_tab)
        self.screenshot_list_widget = ScreenshotListWidget(self.app_context)
        screenshots_layout.addWidget(self.screenshot_list_widget)
        self.tab_widget.addTab(screenshots_tab, "Screenshots")

        # --- Onglet 'Parametres'
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)

        # Scroll area pour garder une UI lisible sur petites fenetres
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_layout.addWidget(settings_scroll)

        settings_container = QWidget()
        settings_scroll.setWidget(settings_container)
        container_layout = QVBoxLayout(settings_container)
        container_layout.setContentsMargins(12, 12, 12, 12)
        container_layout.setSpacing(12)

        # Widgets settings
        self.settings_libraries_list = SettingsLibrariesList(self.app_context)
        self.settings_retro_widget = RetroRecordingWidget(self.settings)
        self.audio_settings_widget = AudioSettingsWidget(self.app_context)
        self.display_settings_widget = DisplaySettingsWidget(self.settings)
        self.remote_control_widget = RemoteControlSettingsWidget(self.app_context)
        self.screenshot_settings_widget = ScreenshotSettingsWidget(self.app_context)

        # Section: bibliotheques (pleine largeur)
        libraries_group = self._make_settings_group(
            "Bibliotheques",
            "Gestion des bibliotheques de samples (ajout, suppression, ordre).",
            self.settings_libraries_list
        )
        container_layout.addWidget(libraries_group)

        # Section: colonnes pour clarifier l'organisation
        columns = QHBoxLayout()
        columns.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        retro_group = self._make_settings_group(
            "Enregistrement retro",
            "Active le pre-enregistrement, ajuste la duree du buffer, puis utilise la molette sur REC pour choisir le retro time de chaque prise.",
            self.settings_retro_widget
        )
        display_group = self._make_settings_group(
            "Affichage",
            "Configuration de la pagination et de la densite des listes.",
            self.display_settings_widget
        )
        audio_group = self._make_settings_group(
            "Audio",
            "Sample rate, loopback et normalisation.",
            self.audio_settings_widget
        )
        remote_group = self._make_settings_group(
            "Controle distant",
            "Piloter l'app depuis un navigateur (mobile) sur le meme reseau.",
            self.remote_control_widget
        )
        screenshot_group = self._make_settings_group(
            "Captures d'ecran",
            "Capturer des images depuis le telephone (optionnel).",
            self.screenshot_settings_widget
        )

        left_col.addWidget(retro_group)
        left_col.addWidget(display_group)
        left_col.addStretch()

        right_col.addWidget(audio_group)
        right_col.addWidget(remote_group)
        right_col.addWidget(screenshot_group)
        right_col.addStretch()

        columns.addLayout(left_col, 1)
        columns.addLayout(right_col, 1)
        container_layout.addLayout(columns)
        container_layout.addStretch()

        self.tab_widget.addTab(settings_tab, "ParamÃ¨tres")

        # coin superieur droit : bouton theme + bouton notif
        _corner = QWidget()
        _corner_layout = QHBoxLayout(_corner)
        _corner_layout.setContentsMargins(0, 0, 4, 0)
        _corner_layout.setSpacing(4)

        self.theme_button = QPushButton()
        self.theme_button.setFixedSize(28, 28)
        self.theme_button.setToolTip("Basculer dark / light mode")
        self._update_theme_button_icon()
        self.theme_button.clicked.connect(theme.manager.toggle)
        _corner_layout.addWidget(self.theme_button)

        self.notif_button = QPushButton()
        self.notif_button.setIcon(qta.icon('fa5s.bell', color='lightgray'))
        self.notif_button.setToolTip("Notifications")
        _corner_layout.addWidget(self.notif_button)

        self.tab_widget.setCornerWidget(_corner, Qt.Corner.TopRightCorner)

        # instancie le centre et le manager
        self.notif_center  = NotificationCenter(self)
        self.notif_center.hide()  # masquÃ© par dÃ©faut
        self.notif_manager = NotificationManager(self.app_context.notifications, parent=self)
        self.notif_manager.set_center(self.notif_center)

        self.notif_button.clicked.connect(self._on_notif_button_clicked)

        # compteur de non-lus
        self._unread_count = 0

        # badge (QLabel) enfant du bouton notif
        self._notif_badge = QLabel(self.notif_button)
        self._notif_badge.setFixedSize(16, 16)
        self._notif_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._notif_badge.setStyleSheet("""
            QLabel {
            background-color: red;
            color: white;
            border-radius: 8px;
            font-size: 10px;
            }
        """)
        # positionne le badge en haut-droite du bouton
        self._notif_badge.move(self.notif_button.width() - 12, 2)
        self._notif_badge.hide()

        self.app_context.notifications.notificationAdded.connect(self._increment_badge)

    def _init_signals(self):
        """Connecte les signaux entre composants"""
        # Quand un nouvel Ã©chantillon est enregistrÃ©, on l'ajoute Ã  la liste
        self.record_widget.newSampleRecorded.connect(
            lambda path: self.app_context.sample_store.load_all()
        )

    def _init_shortcuts(self):
        """Raccourcis clavier globaux de la fenetre principale."""
        self._was_maximized_before_fullscreen = True
        self._toggle_fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._toggle_fullscreen_shortcut.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        """
        F11: bascule plein ecran <-> etat precedent.
        - si la fenetre etait maximisee avant le plein ecran, on y revient.
        - sinon on revient en mode normal.
        """
        if self.isFullScreen():
            if self._was_maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()
            return

        self._was_maximized_before_fullscreen = self.isMaximized()
        self.showFullScreen()

    def _apply_window_stylesheet(self):
        p = theme.manager.p
        self.setStyleSheet(f"""
            QMainWindow#MainWindow {{
                background-color: {p.BG_DARK};
            }}
            QTabWidget#MainTabWidget {{
                background-color: {p.BG_DARK};
            }}
            QTabWidget#MainTabWidget::pane {{
                border: none;
                background-color: {p.BG_DARK};
            }}
        """)

    def _update_theme_button_icon(self):
        icon_name = "fa5s.sun" if theme.manager.is_dark() else "fa5s.moon"
        color = "lightgray" if theme.manager.is_dark() else "#555555"
        self.theme_button.setIcon(qta.icon(icon_name, color=color))

    def _on_theme_changed(self, _name: str):
        self._update_theme_button_icon()
        self._apply_window_stylesheet()

    def closeEvent(self, event):
        """Nettoyage lors de la fermeture de la fenÃªtre principale"""
        self._exit_procedure()
        # Fermer aussi la fenÃªtre d'enregistrement si ouverte
        try:
            self.record_widget.close()
        except Exception:
            pass
        event.accept()

    def _exit_procedure(self):
        """Actions de nettoyage avant fermeture"""
        logger.info("Fermeture de l'application proprement...")
        self.app_context.shutdown()
        # TODO: autres nettoyages (sauvegarde, etc.)

    def _increment_badge(self):
        """IncrÃ©mente le badge et lâ€™affiche."""
        self._unread_count += 1
        self._notif_badge.setText(str(self._unread_count))
        self._notif_badge.show()

    def _clear_badge(self):
        """Remet le compteur Ã  zÃ©ro et masque le badge."""
        self._unread_count = 0
        self._notif_badge.hide()


    # ------------------------------------------------------------------ Helpers UI
    def _make_settings_group(self, title: str, description: str, widget: QWidget) -> QGroupBox:
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

    def _on_notif_button_clicked(self):
        # on inverse la visibilitÃ© du centre
        visible = not self.notif_center.isVisible()
        self.notif_center.setVisible(visible)
        # si on vient de l'ouvrir, on remet le badge Ã  zÃ©ro
        if visible:
            self._clear_badge()
