# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Fenetre de chargement affichee pendant l'initialisation de l'app.
# - S'affiche entre la creation de QApplication et l'affichage de MainWindow.
# - Mise a jour du statut via set_status() + processEvents() pour rester reactive.
#
# CLASSE ET FONCTIONS (sommaire)
# - SplashScreen (QWidget)
#   - __init__()           : carte sombre arrondie, titre + ligne de statut.
#   - _center_on_screen()  : centre la fenetre sur l'ecran principal.
#   - set_status()         : change le texte ("Initialisation de la base...")
#     et force un rafraichissement immediat — sans processEvents(), rien ne
#     s'afficherait car le chargement bloque la boucle d'evenements Qt.
# -----------------------------------------------------------------------------
# frontend/splash.py

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


class SplashScreen(QWidget):
    """Fenetre de chargement minimaliste, sans decorations, centree a l'ecran."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(380, 170)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(0)

        self._title = QLabel("SampleRod")
        self._title.setObjectName("SplashTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._status = QLabel("Demarrage...")
        self._status.setObjectName("SplashStatus")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addSpacing(12)
        layout.addWidget(self._status)
        layout.addStretch(1)

        self.setStyleSheet("""
            QWidget {
                background-color: #16181b;
                border: 1px solid #3b3f46;
                border-radius: 14px;
                color: #f2f2f2;
            }
            QLabel {
                background: transparent;
                border: none;
                color: #f2f2f2;
            }
            QLabel#SplashTitle {
                font-size: 28px;
                font-weight: bold;
            }
            QLabel#SplashStatus {
                color: #8d95a3;
                font-size: 12px;
            }
        """)

        self._center_on_screen()

    def _center_on_screen(self):
        """Place la fenetre au centre de l'ecran principal."""
        screen = QGuiApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            x = rect.x() + (rect.width() - self.width()) // 2
            y = rect.y() + (rect.height() - self.height()) // 2
            self.move(x, y)

    def set_status(self, message: str):
        """Met a jour le texte de statut et force un rendu immediat."""
        self._status.setText(message)
        QApplication.processEvents()
