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
    QGroupBox,
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QShortcut, QKeySequence
import json
import logging
logger = logging.getLogger("main_window")

from frontend.record_widget import RecordWidgetWindow
from frontend.notification_widgets import NotificationManager, NotificationCenter
from frontend.labo.artifact_store import ensure_lab_artifact_store
from frontend.styles import theme
from frontend.activity import ActivityService, ActivityTrayWidget
from frontend.ui import IconButton, LazyWidgetHost, install_fast_tooltips
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
        self.lab_artifact_store = ensure_lab_artifact_store(self.app_context, self)
        self._settings_tab_index = 0

        # Atelier modulaire (nouvelle UI, ouverte a la demande, non destructif)
        self._window_manager: WindowManager | None = None
        self._workspace_window: WorkspaceWindow | None = None

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

        # Les trois ecrans classiques sont couteux et inutiles au lancement
        # modulaire. Leurs imports ET leurs widgets sont donc différes jusqu'a
        # la premiere fois ou l'onglet devient effectivement visible.
        self.atelier_widget = None
        self.screenshot_list_widget = None
        self.settings_panel = None
        self._atelier_host = LazyWidgetHost(
            self._create_atelier_widget, "Préparation de l’atelier…"
        )
        self._screenshots_host = LazyWidgetHost(
            self._create_screenshot_widget, "Chargement des captures…"
        )
        self._settings_host = LazyWidgetHost(
            self._create_settings_widget, "Chargement des paramètres…"
        )
        self.tab_widget.addTab(self._atelier_host, "Atelier")
        self.tab_widget.addTab(self._screenshots_host, "Screenshots")
        self.tab_widget.addTab(self._settings_host, "ParamÃ¨tres")

        self._settings_tab_index = self.tab_widget.count() - 1

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

        self.theme_button = IconButton("sun", tooltip="Basculer dark / light mode", size="s")
        self.theme_button.setToolTip("Basculer dark / light mode")
        self._update_theme_button_icon()
        self.theme_button.clicked.connect(theme.manager.toggle)
        _corner_layout.addWidget(self.theme_button)

        self.notif_button = IconButton("bell", tooltip="Notifications", size="s")
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

    def _create_atelier_widget(self):
        from frontend.workspace.atelier_widget import AtelierWidget

        self.atelier_widget = AtelierWidget(
            directory_service=self.directory_service,
            app_context=self.app_context,
        )
        return self.atelier_widget

    def _create_screenshot_widget(self):
        from frontend.screenshot_gui.screenshot_list import ScreenshotListWidget

        self.screenshot_list_widget = ScreenshotListWidget(self.app_context)
        return self.screenshot_list_widget

    def _create_settings_widget(self):
        from frontend.settings_gui.settings_panel import SettingsPanelWidget

        self.settings_panel = SettingsPanelWidget(self.app_context)
        return self.settings_panel

    _MODULAR_MODE_KEY = "modular_ui_mode"
    _MODULAR_SESSION_KEY = "modular_session_v1"

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
            # Restaure la session precedente AVANT de brancher l'auto-save.
            self._restore_modular_session()
            # Migration douce des anciennes geometries libres : une fois toutes
            # les instances restaurees, leurs quatre contours rejoignent les
            # lignes du quadrillage actuellement configure.
            self._window_manager.align_windows_to_grid()
            self._window_manager.instancesChanged.connect(self._persist_modular_session)
            self._window_manager.instanceUpdated.connect(
                lambda *_a: self._persist_modular_session()
            )
            # Deplacements et redimensionnements : le controleur spatial met la
            # geometrie a jour en memoire tout de suite et regroupe les
            # ecritures disque. Sans cela, la geometrie n'etait capturee qu'a la
            # fermeture d'une fenetre ou a l'arret de l'application.
            self._window_manager.layout_manager.persistRequested.connect(
                self._persist_modular_session
            )
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._persist_modular_session)
        # Premiere ouverture (session vide) : au moins une reserve pour demarrer.
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
        self._persist_modular_session()
        if self._workspace_window is not None:
            self._workspace_window.hide()
        if self._window_manager is not None:
            self._window_manager.suspend()
        self.show()
        self.raise_()
        self.activateWindow()
        QSettings("SampleRod", "Main").setValue(self._MODULAR_MODE_KEY, "classic")

    def _quit_app(self):
        """Fermer l'orchestrateur ferme l'application, avec nettoyage complet.

        En mode modulaire la fenetre classique est masquee : app.quit() seul ne
        declencherait pas closeEvent, donc les services (thread de separation de
        stems, etc.) ne s'arreteraient pas et bloqueraient la sortie. On masque
        l'atelier pour un retour visuel immediat, puis on lance la meme
        procedure de nettoyage que closeEvent avant de quitter.
        """
        if self._workspace_window is not None:
            self._workspace_window.hide()
        if self._window_manager is not None:
            self._window_manager.suspend()
        QApplication.processEvents()
        self._exit_procedure()
        try:
            self.record_widget.close()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def start(self):
        """Demarrage : affiche directement le bon mode, sans flash de l'autre.

        Appelee par app.py a la place de show() : si le dernier mode etait
        modulaire, on ouvre l'atelier sans jamais afficher la fenetre classique.
        """
        mode = QSettings("SampleRod", "Main").value(
            self._MODULAR_MODE_KEY, "classic", type=str
        )
        if mode == "modular":
            try:
                self._enter_modular_mode()
                return
            except Exception:
                logger.exception(
                    "Ouverture en mode modulaire impossible, retour au classique"
                )
        self.show()

    def _restore_modular_session(self):
        """Recree les instances de la session precedente (si presente)."""
        if self._window_manager is None:
            return
        raw = QSettings("SampleRod", "Main").value(self._MODULAR_SESSION_KEY, "", type=str)
        if not raw:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        if isinstance(data, dict) and data.get("instances"):
            self._window_manager.restore_session(data)

    def _persist_modular_session(self, *_args):
        """Sauvegarde la session modulaire courante en QSettings (JSON)."""
        if self._window_manager is None:
            return
        try:
            payload = json.dumps(self._window_manager.save_session())
            QSettings("SampleRod", "Main").setValue(self._MODULAR_SESSION_KEY, payload)
        except Exception:
            pass

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
        self.theme_button.set_icon_name("sun" if theme.manager.is_dark() else "moon")

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
