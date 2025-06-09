# backend/services/notifications_service.py

"""
Service centralisé d'envoi et de diffusion des notifications
"""
from PyQt6.QtCore import QObject, pyqtSignal
from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime


class NotificationType(Enum):
    """Types de notifications utilisées pour déterminer le style / icône"""
    INFO = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()


@dataclass
class Notification:
    """Modèle représentant une notification à afficher"""
    id: int
    title: str
    message: str
    timestamp: datetime
    type: NotificationType
    duration: int  # durée d'affichage en millisecondes


class NotificationService(QObject):
    """Service Qt pour gérer la création et la diffusion des notifications"""

    # Signal émis lors de l'ajout d'une notification (envoie l'objet Notification)
    notificationAdded = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        # Compteur interne pour générer des IDs uniques
        self._next_id = 1

    def notify(self,
               title: str,
               message: str,
               type: NotificationType = NotificationType.INFO,
               duration: int = 5000):
        """
        Crée une notification et émet le signal notificationAdded.

        :param title:   Titre de la notification
        :param message: Message détaillé
        :param type:    Type de la notification (INFO, SUCCESS, WARNING, ERROR)
        :param duration:Durée d'affichage en millisecondes
        """
        print(f"NotificationService: Création d'une notification '{title}' ({type.name})")
        notif = Notification(
            id=self._next_id,
            title=title,
            message=message,
            timestamp=datetime.now(),
            type=type,
            duration=duration
        )
        self._next_id += 1
        # Émission du signal vers les widgets abonnés
        self.notificationAdded.emit(notif)