# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - La partie VISIBLE des notifications (la partie logique est dans
#   backend/services/notification_service.py).
# - Trois pieces qui travaillent ensemble :
#   * NotificationPopup  : la petite bulle qui surgit en bas a droite de
#     l'ecran, glisse vers le haut, reste quelques secondes puis s'efface ;
#   * NotificationCenter : la fenetre "historique" ouverte par la cloche,
#     qui liste toutes les notifications recues avec un bouton Vider ;
#   * NotificationManager: le chef d'orchestre — il ecoute le service,
#     alimente le centre, cree les popups (3 maximum a l'ecran, les plus
#     anciens sont chasses) et les re-empile proprement quand l'un se ferme.
#
# CLASSES ET FONCTIONS (sommaire)
# - NotificationPopup (QFrame)
#   - _build_ui()     : titre + message, bordure coloree selon le type
#                       (bleu=info, vert=succes, orange=alerte, rouge=erreur).
#   - _animate_in()   : entree glissee depuis le bas de l'ecran.
#   - _animate_out()  : sortie en fondu puis fermeture.
# - NotificationCenter (QWidget)
#   - add_notification() : ajoute une ligne horodatee a la liste.
#   - clear()            : vide tout.
# - NotificationManager (QObject)
#   - set_center()           : branche le centre de notifications.
#   - _on_new_notification() : recoit chaque notification du service ;
#     l'ajoute au centre, puis cree un popup (sauf notification silencieuse).
#   - _reposition_popups()   : re-empile les popups du bas vers le haut.
#   - _remove_popup()        : retire un popup ferme de la pile.
#
# LIENS CLES
# - backend/services/notification_service.py : la source des notifications.
# - frontend/main_window.py : cree le manager, le centre et la cloche.
# -----------------------------------------------------------------------------

"""
Widgets pour afficher les notifications.

- NotificationPopup : mini popup anime en bas a droite.
- NotificationCenter : liste escamotable des notifications.
- NotificationManager : controleur reliant le service aux widgets.
"""

from PySide6.QtCore import QObject, QPropertyAnimation, QRect, Qt, QTimer, Slot, QEasingCurve
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.services.notification_service import Notification, NotificationService, NotificationType

import logging

logger = logging.getLogger("notification_widgets")


class NotificationPopup(QFrame):
    """Popup anime pour afficher brievement une notification."""

    def __init__(self, notification: Notification, parent=None):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.ToolTip
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self.notif = notification
        self._build_ui()
        self._animate_in()
        logger.info("[NotificationWidgets] Popup '%s' affiche", notification.title)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._animate_out)
        self.timer.start(self.notif.duration)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(5)

        title = QLabel(self.notif.title)
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        message = QLabel(self.notif.message)
        message.setWordWrap(True)
        layout.addWidget(message)

        colors = {
            NotificationType.INFO: "#2196F3",
            NotificationType.SUCCESS: "#4CAF50",
            NotificationType.WARNING: "#FF9800",
            NotificationType.ERROR: "#F44336",
        }
        border_color = colors.get(self.notif.type, "#2196F3")
        self.setStyleSheet(
            f"""
            NotificationPopup {{
                background-color: rgba(30,30,30,240);
                border: 2px solid {border_color};
                border-radius: 8px;
            }}
            NotificationPopup QLabel {{ color: white; }}
            """
        )
        self.adjustSize()

    def _animate_in(self) -> None:
        """Fait glisser le popup depuis le bord bas vers sa place definitive."""
        screen_geometry = self.screen().availableGeometry()
        width, height = self.width(), self.height()
        # Position finale : coin bas-droit de l'ecran, avec une marge de 20 px.
        end_x = screen_geometry.x() + screen_geometry.width() - width - 20
        end_y = screen_geometry.y() + screen_geometry.height() - height - 20

        start_rect = QRect(end_x, screen_geometry.y() + screen_geometry.height(), width, height)
        end_rect = QRect(end_x, end_y, width, height)
        self.setGeometry(start_rect)

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(300)
        anim.setStartValue(start_rect)
        anim.setEndValue(end_rect)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.start()
        self._anim_in = anim

    def _animate_out(self) -> None:
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.close)
        anim.start()
        self._anim_out = anim


class NotificationCenter(QWidget):
    """Centre de notifications : liste defilante avec bouton de purge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Centre de Notifications")
        self.setWindowFlag(Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.notifications = []
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        header = QHBoxLayout()
        self.clear_btn = QPushButton("Vider tout")
        self.clear_btn.clicked.connect(self.clear)
        header.addStretch()
        header.addWidget(self.clear_btn)
        main_layout.addLayout(header)

        self.list = QListWidget()
        main_layout.addWidget(self.list)
        self.resize(300, 400)

    @Slot(Notification)
    def add_notification(self, notification: Notification) -> None:
        text = (
            f"[{notification.timestamp.strftime('%H:%M:%S')}] "
            f"{notification.title} - {notification.message}"
        )
        self.list.addItem(text)
        self.notifications.append(notification)
        self.list.scrollToBottom()
        logger.info(
            "[NotificationWidgets] Notification ajoutee au centre : %s",
            notification.title,
        )

    def clear(self) -> None:
        self.list.clear()
        self.notifications.clear()
        logger.info("[NotificationWidgets] Centre vide")


class NotificationManager(QObject):
    """Relie NotificationService au centre et aux popups flottants."""

    MAX_POPUPS = 3

    def __init__(self, service: NotificationService, parent=None):
        super().__init__(parent)
        self.service = service
        self.popups = []
        self.center = None
        self.service.notificationAdded.connect(self._on_new_notification)

    def set_center(self, center: NotificationCenter) -> None:
        self.center = center

    @Slot(Notification)
    def _on_new_notification(self, notification: Notification) -> None:
        if self.center:
            self.center.add_notification(notification)
        logger.info("[NotificationWidgets] Nouvelle notification : %s", notification.title)

        if not bool(getattr(notification, "popup", True)):
            logger.info(
                "[NotificationWidgets] Notification silencieuse, aucun popup : %s",
                notification.title,
            )
            return

        popup = NotificationPopup(notification, parent=self.parent())
        popup.show()
        self.popups.append(popup)
        popup.destroyed.connect(lambda obj=None, p=popup: self._remove_popup(p))

        if len(self.popups) > self.MAX_POPUPS:
            old = self.popups.pop(0)
            old._animate_out()

        self._reposition_popups()

    def _reposition_popups(self) -> None:
        """Re-empile les popups visibles du bas vers le haut de l'ecran.

        Le plus recent reste en bas ; chaque popup plus ancien est anime
        vers sa nouvelle position juste au-dessus du precedent.
        """
        if not self.popups:
            return

        screen_geometry = self.popups[-1].screen().availableGeometry()
        spacing = 10
        y = screen_geometry.y() + screen_geometry.height() - self.popups[-1].height() - 20

        for popup in reversed(self.popups[:-1]):
            y -= spacing + popup.height()
            end_x = screen_geometry.x() + screen_geometry.width() - popup.width() - 20
            end_rect = QRect(end_x, y, popup.width(), popup.height())

            anim = QPropertyAnimation(popup, b"geometry", popup)
            anim.setDuration(300)
            anim.setStartValue(popup.geometry())
            anim.setEndValue(end_rect)
            anim.setEasingCurve(QEasingCurve.Type.OutBack)
            anim.start()
            popup._anim_move = anim

    def _remove_popup(self, popup: NotificationPopup) -> None:
        if popup in self.popups:
            self.popups.remove(popup)
            self._reposition_popups()
            logger.info("[NotificationWidgets] Popup ferme")
