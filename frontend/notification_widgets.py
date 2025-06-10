"""
frontend/widgets/notification_widget.py

Contient les widgets pour afficher les notifications :
- NotificationPopup : mini-pop-up animé en bas à droite
- NotificationCenter : liste escamotable des notifications
- NotificationManager : contrôleur qui relie le service aux widgets
"""

from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QListWidget, QPushButton,
    QHBoxLayout, QScrollArea
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, pyqtSlot,
    QPropertyAnimation, QEasingCurve, QObject, QRect
)
from PyQt6.QtGui import QFont

from backend.services.notification_service import NotificationService, Notification, NotificationType


class NotificationPopup(QFrame):
    """
    Pop-up animé pour afficher brièvement une notification.
    Apparait en bas à droite, puis disparaît au bout de notification.duration ms.
    """
    def __init__(self, notification: Notification, parent=None):
        # ── Création en tant que fenêtre « tooltip » autonome (ne prend pas le focus)
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint    # pas de bordure
          | Qt.WindowType.ToolTip               # ne prend jamais le focus ni priorise la MainWindow
          | Qt.WindowType.WindowStaysOnTopHint  # toujours au-dessus
        )
        # Ne pas activer la fenêtre (n’invoque pas activateWindow())
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Empêche toute acceptation de focus
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        # self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self.notif = notification
        self._build_ui()
        self._animate_in()

        # Timer pour disparaître
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._animate_out)
        self.timer.start(self.notif.duration)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(5)

        # Titre
        self.title = QLabel(self.notif.title)
        font = QFont()
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)

        # Message
        self.message = QLabel(self.notif.message)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        # Style en fonction du type
        colors = {
            NotificationType.INFO: '#2196F3',
            NotificationType.SUCCESS: '#4CAF50',
            NotificationType.WARNING: '#FF9800',
            NotificationType.ERROR: '#F44336'
        }
        border_color = colors.get(self.notif.type, '#2196F3')
        self.setStyleSheet(f"""
            NotificationPopup {{
                background-color: rgba(30,30,30,240);
                border: 2px solid {border_color};
                border-radius: 8px;
            }}
            NotificationPopup QLabel {{ color: white; }}
        """)

        self.adjustSize()

    def _animate_in(self):
        # Apparition par glissement vertical depuis hors-écran
        # 1) Calcul de la géométrie de l'écran
        screen_geometry = self.screen().availableGeometry()
        w, h = self.width(), self.height()
        end_x = screen_geometry.x() + screen_geometry.width() - w - 20

        # 2) Récupère tous les NotificationPopup déjà affichés
        from PyQt6.QtWidgets import QApplication
        existing_popups = [
            w for w in QApplication.topLevelWidgets()
            if isinstance(w, NotificationPopup)
        ]

        # 3) Décale verticalement en fonction du nombre de pop-ups
        end_y = (
            screen_geometry.y() + screen_geometry.height() - h - 20
            - len(existing_popups) * (h + 10)
        )

        # Position initiale hors-écran
        start_rect = QRect(end_x, screen_geometry.y() + screen_geometry.height(), w, h)
        end_rect = QRect(end_x, end_y, w, h)
        self.setGeometry(start_rect)

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(300)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.start()
        self._anim_in = anim

    def _animate_out(self):
        # Disparition par fondu
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.close)
        anim.start()
        self._anim_out = anim


class NotificationCenter(QWidget):
    """
    Centre de notifications : liste défilante, avec bouton de purge.
    Peut être docké/escamoté dans l'UI principale.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Centre de Notifications")
        self.setWindowFlag(Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self._build_ui()
        self.notifications = []  # stocke les Notification

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5,5,5,5)
        main_layout.setSpacing(5)

        # En-tête avec bouton vider
        header = QHBoxLayout()
        self.clear_btn = QPushButton("Vider tout")
        self.clear_btn.clicked.connect(self.clear)
        header.addStretch()
        header.addWidget(self.clear_btn)
        main_layout.addLayout(header)

        # Liste scrollable
        self.list = QListWidget()
        main_layout.addWidget(self.list)

        self.resize(300, 400)

    @pyqtSlot(Notification)
    def add_notification(self, notification: Notification):
        """Ajoute une notification à la liste et rafraîchit l'affichage."""
        text = f"[{notification.timestamp.strftime('%H:%M:%S')}] {notification.title} – {notification.message}"
        self.list.addItem(text)
        self.notifications.append(notification)
        self.list.scrollToBottom()

    def clear(self):
        """Purge toutes les notifications du centre et libère la liste."""
        self.list.clear()
        self.notifications.clear()


class NotificationManager(QObject):
    """
    Contrôleur qui relie NotificationService aux widgets Popup et Center.
    Gère le nombre de popups simultanés.
    """
    MAX_POPUPS = 3

    def __init__(self, service: NotificationService, parent=None):
        super().__init__(parent)
        self.service = service
        self.popups = []
        self.center = None
        self.service.notificationAdded.connect(self._on_new_notification)

    def set_center(self, center: NotificationCenter):
        """Associe un NotificationCenter pour y dupliquer les notifications."""
        self.center = center

    @pyqtSlot(Notification)
    def _on_new_notification(self, notification: Notification):
        # Ajout au centre
        if self.center:
            self.center.add_notification(notification)

        # Création et affichage du popup
        popup = NotificationPopup(notification, parent=self.parent())
        popup.show()
        self.popups.append(popup)

        # Nettoyage des anciens popups si nécessaire
        if len(self.popups) > self.MAX_POPUPS:
            old = self.popups.pop(0)
            old._animate_out()