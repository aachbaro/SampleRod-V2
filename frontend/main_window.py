# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - La fenetre principale de l'application : tout ce que l'utilisateur voit
#   est assemble ici.
# - Structure generale :
#   * un bandeau d'onglets (Atelier / Screenshots / Parametres) ;
#   * sous les onglets, le "plateau d'activite" (taches de fond en cours) ;
#   * en coin haut-droit : bouton theme clair/sombre + cloche de
#     notifications avec badge de non-lus ;
#   * une fenetre flottante independante pour l'enregistrement (REC).
# - L'onglet Atelier (AtelierWidget) contient le coeur de l'application :
#   liste des samples, editeur de forme d'onde, panneau droit, labo...
# - C'est aussi cette classe qui declenche le grand nettoyage a la
#   fermeture (closeEvent -> _exit_procedure -> AppContext.shutdown).
#
# FONCTIONS (sommaire)
# - MainWindow (QMainWindow)
#   - __init__()            : cree les services UI puis enchaine les etapes.
#   - _setup_window()       : titre, taille, demarrage maximise.
#   - _build_ui()           : construit TOUTE l'interface (onglets, coins,
#                             notifications, fenetre REC, ecran parametres).
#   - _init_signals()       : connexions entre composants (nouvel enregistrement).
#   - _init_shortcuts()     : raccourcis globaux (F11 plein ecran).
#   - _toggle_fullscreen()  : bascule plein ecran <-> etat precedent.
#   - _apply_window_stylesheet() : couleurs de fond selon le theme.
#   - _update_theme_button_icon()/_on_theme_changed() : suivi du theme.
#   - closeEvent()/_exit_procedure() : fermeture propre de l'application.
#   - _increment_badge()/_clear_badge() : compteur de notifications non lues.
#   - _make_settings_group(): petit cadre titre+description pour les reglages.
#   - _on_notif_button_clicked() : ouvre/ferme le centre de notifications.
#
# LIENS CLES
# - frontend/workspace/atelier_widget.py : le contenu de l'onglet Atelier.
# - frontend/record_widget.py            : la fenetre flottante REC.
# - frontend/notification_widgets.py     : popups + centre de notifications.
# - frontend/activity/                   : le plateau des taches de fond.
# - frontend/settings_gui/               : les blocs de l'onglet Parametres.
# -----------------------------------------------------------------------------
# frontend/main_window.py

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QScrollArea,
)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QShortcut, QKeySequence
import logging
logger = logging.getLogger("main_window")

import qtawesome as qta

from frontend.record_widget import RecordWidgetWindow
from frontend.settings_gui.libraries_list import SettingsLibrariesList
from frontend.settings_gui.retro_recording_settings import RetroRecordingWidget
from frontend.settings_gui.audio_settings import AudioSettingsWidget
from frontend.settings_gui.display_settings import DisplaySettingsWidget
from frontend.settings_gui.remote_control_settings import RemoteControlSettingsWidget
from frontend.settings_gui.screenshot_settings import ScreenshotSettingsWidget
from frontend.settings_gui.waveform_settings import WaveformSettingsWidget
from frontend.screenshot_gui.screenshot_list import ScreenshotListWidget
from frontend.notification_widgets import NotificationManager, NotificationCenter
from frontend.workspace.atelier_widget import AtelierWidget
from frontend.styles import theme
from frontend.activity import ActivityService, ActivityTrayWidget
from frontend.ui import IconButton, install_fast_tooltips
from frontend.modular import (
    WindowManager,
    WorkspaceWindow,
    build_default_registry,
)

from backend.services.directory_service import DirectoryService

from backend.models.AppContext import AppContext

class MainWindow(QMainWindow):
    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context
        self.settings = self.app_context.settings
        self.directory_service = DirectoryService(self.app_context.sample_store)
        self.activity_service = ActivityService(self.app_context, self)

        # Atelier modulaire (nouvelle UI, ouverte a la demande, non destructif)
        self._window_manager: WindowManager | None = None
        self._workspace_window: WorkspaceWindow | None = None

        self._setup_window()
        self._build_ui()
        self._init_signals()
        self._init_shortcuts()
        theme.manager.apply()
        theme.manager.themeChanged.connect(self._on_theme_changed)
        # Restaure le dernier mode d'affichage (classique / modulaire) apres show.
        QTimer.singleShot(0, self._apply_startup_mode)

    def _setup_window(self):
        """Configure la fenÃªtre principale"""
        self.setWindowTitle("SampleRod")
        self.setGeometry(300, 200, 1200, 600)
        # DÃ©marrage en mode maximisÃ© (barre de titre visible)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _build_ui(self):
        """Construit toute l'interface : onglets, plateau d'activite, coins.

        Ordre de construction : conteneur central (onglets + plateau
        d'activite), fenetre REC flottante, onglet Atelier, onglet
        Screenshots, onglet Parametres (organise en deux colonnes de
        groupes), puis le coin haut-droit (theme + notifications).
        """
        # Conteneur d'onglets
        self._central_widget = QWidget(self)
        self._central_layout = QVBoxLayout(self._central_widget)
        self._central_layout.setContentsMargins(0, 0, 0, 0)
        self._central_layout.setSpacing(0)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("MainTabWidget")
        # Theme global (fond) : on veut que les "gaps" autour des widgets (marges, splitters,
        # etc.) soient coherents avec le reste (SampleCard / SampleList / Waveform).
        # On limite volontairement le scope via des objectName pour eviter des effets de bord.
        self.setObjectName("MainWindow")
        self._apply_window_stylesheet()

        self.activity_tray = ActivityTrayWidget(self.activity_service, self._central_widget)
        self._central_layout.addWidget(self.tab_widget, 1)
        self._central_layout.addWidget(self.activity_tray, 0)
        self.setCentralWidget(self._central_widget)

        # --- Onglet 'Enregistrement' (pop-up flottant)
        self.record_widget = RecordWidgetWindow(self.app_context)
        self.record_widget.show()
        # On ne l'ajoute pas aux tabs, c'est une fenÃªtre indÃ©pendante

        # --- Onglet 'Atelier'
        atelier_tab = QWidget()
        atelier_layout = QVBoxLayout(atelier_tab)
        atelier_layout.setContentsMargins(0, 0, 0, 0)
        self.atelier_widget = AtelierWidget(
            directory_service=self.directory_service,
            app_context=self.app_context,
        )
        atelier_layout.addWidget(self.atelier_widget)
        self.tab_widget.addTab(atelier_tab, "Atelier")

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
        self.waveform_settings_widget = WaveformSettingsWidget(self.settings)

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
        waveform_group = self._make_settings_group(
            "Waveform / Decoupage",
            "Comportement de l'editeur waveform et des outils de decoupage.",
            self.waveform_settings_widget
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

        self.tab_widget.addTab(settings_tab, "ParamÃ¨tres")

        # Tooltips rapides sur toute l'application (UI icone-only)
        app = QApplication.instance()
        if app is not None:
            install_fast_tooltips(app, 250)

        # coin superieur droit : atelier modulaire + bouton theme + bouton notif
        _corner = QWidget()
        _corner_layout = QHBoxLayout(_corner)
        _corner_layout.setContentsMargins(0, 0, 4, 0)
        _corner_layout.setSpacing(4)

        self.modular_button = IconButton(
            "app-window",
            tooltip="Basculer vers l'atelier modulaire",
            size="s",
        )
        self.modular_button.clicked.connect(self._enter_modular_mode)
        _corner_layout.addWidget(self.modular_button)

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

    _MODULAR_MODE_KEY = "modular_ui_mode"

    def _enter_modular_mode(self):
        """Bascule vers l'atelier modulaire : masque l'affichage classique.

        Construction paresseuse du WindowManager + Workspace au premier appel.
        On ne montre jamais les deux affichages en meme temps.
        """
        if self._window_manager is None:
            registry = build_default_registry()
            self._window_manager = WindowManager(
                self.app_context, self.directory_service, registry, self
            )
            self._workspace_window = WorkspaceWindow(self._window_manager)
            self._workspace_window.exitRequested.connect(self._exit_modular_mode)
            self._workspace_window.quitRequested.connect(self._quit_app)
            # NOTE : la restauration des fenetres de session est desactivee
            # pour l'instant (comportement a revoir plus tard).
        if not self._window_manager.instances():
            self._window_manager.create_instance("reserve")
        # Bascule : masque le classique, affiche l'atelier modulaire.
        self.hide()
        self._window_manager.resume()
        self._workspace_window.show()
        self._workspace_window.raise_()
        self._workspace_window.activateWindow()
        QSettings("SampleRod", "Main").setValue(self._MODULAR_MODE_KEY, "modular")

    def _exit_modular_mode(self):
        """Bascule vers l'affichage classique (les fenetres restent en memoire)."""
        if self._workspace_window is not None:
            self._workspace_window.hide()
        if self._window_manager is not None:
            self._window_manager.suspend()
        self.show()
        self.raise_()
        self.activateWindow()
        QSettings("SampleRod", "Main").setValue(self._MODULAR_MODE_KEY, "classic")

    def _quit_app(self):
        """Fermer l'orchestrateur ferme l'application (modes au meme niveau)."""
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _apply_startup_mode(self):
        """Restaure le dernier mode d'affichage utilise (classique / modulaire)."""
        mode = QSettings("SampleRod", "Main").value(
            self._MODULAR_MODE_KEY, "classic", type=str
        )
        if mode == "modular":
            self._enter_modular_mode()

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
        try:
            self.activity_tray.shutdown()
        except Exception:
            logger.exception("ActivityTrayWidget: shutdown impossible")
        try:
            self.activity_service.shutdown()
        except Exception:
            logger.exception("ActivityService: shutdown impossible")
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
        """Encadre un widget de reglages avec un titre et une description.

        Donne leur aspect uniforme a tous les blocs de l'onglet Parametres.
        """
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
