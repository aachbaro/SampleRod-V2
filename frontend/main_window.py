from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QGroupBox,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QSettings
import os
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
from frontend.notification_widgets import NotificationManager, NotificationCenter
from frontend.directory_widget import DirectoryWidget

from backend.services.directory_service import DirectoryService

from backend.models.sample import Sample
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

    def _setup_window(self):
        """Configure la fenêtre principale"""
        self.setWindowTitle("SampleRod")
        self.setGeometry(300, 200, 1200, 600)

    def _build_ui(self):
        """Construit l'interface utilisateur"""
        # Conteneur d'onglets
        self.tab_widget = QTabWidget(self)
        self.setCentralWidget(self.tab_widget)

        # --- Onglet 'Enregistrement' (pop-up flottant)
        self.record_widget = RecordWidgetWindow(self.app_context)
        self.record_widget.show()
        # On ne l'ajoute pas aux tabs, c'est une fenêtre indépendante

        # --- Onglet 'Liste des Samples'
        samples_tab = QWidget()
        samples_layout = QHBoxLayout(samples_tab)
        self.sample_list_widget = SampleListWidget(
            app_context=self.app_context
        )

        # ---- Panel directory tabs ----
        dir_panel = QWidget()
        dir_layout = QVBoxLayout(dir_panel)
        self.add_dir_btn = QPushButton("Add directory")
        self.add_dir_btn.clicked.connect(self._add_directory_tab)
        self.dir_tab_widget = QTabWidget()
        self.dir_tab_widget.setTabsClosable(True)
        self.dir_tab_widget.tabCloseRequested.connect(self._close_directory_tab)
        dir_layout.addWidget(self.add_dir_btn)
        dir_layout.addWidget(self.dir_tab_widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.sample_list_widget)
        splitter.addWidget(dir_panel)
        splitter.setSizes([300, 150])

        samples_layout.addWidget(splitter)

        self.tab_widget.addTab(samples_tab, "Liste des Samples")

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
            "Active le pre-enregistrement et ajuste la duree du buffer.",
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

        left_col.addWidget(retro_group)
        left_col.addWidget(display_group)
        left_col.addStretch()

        right_col.addWidget(audio_group)
        right_col.addWidget(remote_group)
        right_col.addStretch()

        columns.addLayout(left_col, 1)
        columns.addLayout(right_col, 1)
        container_layout.addLayout(columns)
        container_layout.addStretch()

        self.tab_widget.addTab(settings_tab, "Paramètres")

        # bouton 🛎 placé dans le coin supérieur droit des onglets
        self.notif_button = QPushButton()
        self.notif_button.setIcon(qta.icon('fa5s.bell', color='lightgray'))
        self.notif_button.setToolTip("Notifications")
        # positionne le bouton dans le coin
        self.tab_widget.setCornerWidget(self.notif_button, Qt.Corner.TopRightCorner)

        # instancie le centre et le manager
        self.notif_center  = NotificationCenter(self)
        self.notif_center.hide()  # masqué par défaut
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

        self._restore_directories()

    def _init_signals(self):
        """Connecte les signaux entre composants"""
        # Quand un nouvel échantillon est enregistré, on l'ajoute à la liste
        self.record_widget.newSampleRecorded.connect(
            lambda path: self.app_context.sample_store.load_all()
        )

    def closeEvent(self, event):
        """Nettoyage lors de la fermeture de la fenêtre principale"""
        self._exit_procedure()
        # Fermer aussi la fenêtre d'enregistrement si ouverte
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
        """Incrémente le badge et l’affiche."""
        self._unread_count += 1
        self._notif_badge.setText(str(self._unread_count))
        self._notif_badge.show()

    def _clear_badge(self):
        """Remet le compteur à zéro et masque le badge."""
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
            desc_label.setStyleSheet("color: #6b6b6b;")
            layout.addWidget(desc_label)

        layout.addWidget(widget)
        return group

    def _restore_directories(self):
        """Reopen directories stored in settings if they still exist."""
        qs = QSettings("SampleRod", "Main")
        dirs = qs.value("recent_directories", [], type=list)
        missing = []
        for path in dirs:
            if os.path.exists(path):
                self._add_directory_tab(path)
            else:
                missing.append(path)
        if missing:
            logger.info(f"[MainWindow] Dossiers introuvables: {missing}")

    def _on_notif_button_clicked(self):
        # on inverse la visibilité du centre
        visible = not self.notif_center.isVisible()
        self.notif_center.setVisible(visible)
        # si on vient de l'ouvrir, on remet le badge à zéro
        if visible:
            self._clear_badge()

    # ------------------------------------------------------------------ Directories
    def _add_directory_tab(self, path: str | None = None):
        widget = DirectoryWidget(self.directory_service, self.app_context, path=path)
        widget.directoryChanged.connect(
            lambda path, w=widget: self._update_dir_tab_text(w, path)
        )
        index = self.dir_tab_widget.addTab(widget, "New directory")
        self.dir_tab_widget.setCurrentIndex(index)
        if path:
            self._update_dir_tab_text(widget, path)

    def _update_dir_tab_text(self, widget: DirectoryWidget, path: str):
        name = os.path.basename(path) or path
        idx = self.dir_tab_widget.indexOf(widget)
        if idx != -1:
            self.dir_tab_widget.setTabText(idx, name)

    def _close_directory_tab(self, index: int):
        w = self.dir_tab_widget.widget(index)
        if w:
            if getattr(w, "current_dir", None):
                DirectoryWidget.remove_from_history(w.current_dir)
            w.deleteLater()
        self.dir_tab_widget.removeTab(index)
