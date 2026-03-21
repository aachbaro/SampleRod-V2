# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service centralise de creation et diffusion des notifications UI.
# - Utilise par les services (settings, samples, recorder, etc.) pour informer
#   l'utilisateur sans coupler le code metier aux widgets.
#
# CE QUI EST DEJA EN PLACE
# - Enum NotificationType (INFO/SUCCESS/WARNING/ERROR).
# - Dataclass Notification (id, titre, message, timestamp, type, duree).
# - Service Qt avec signal `notificationAdded` pour pousser aux widgets.
# - Compteur interne pour garantir des IDs uniques.
#
# CE QUI RESTE A IMPLEMENTER (IDEES)
# - Niveaux de priorite + affichage en file (queue).
# - Suppression/expiration automatique (timer global).
# - Persistance (historique en base) pour audit/debug.
# - Groupement/dedup des notifications similaires.
# - Actions (boutons: "Ouvrir", "Annuler", "Reessayer").
# - Localisation i18n des messages.
#
# NOTES
# - Le service ne depend que de QtCore (pas de widgets).
# - Les widgets doivent s'abonner a `notificationAdded`.
# -----------------------------------------------------------------------------
# backend/services/notification_service.py

"""
Service centralise d'envoi et de diffusion des notifications
"""
# Qt: QObject + signaux
from PySide6.QtCore import QObject, Signal
# Dataclass pour le modele Notification
from dataclasses import dataclass
# Enum pour les types de notification
from enum import Enum, auto
# Timestamp d'emission
from datetime import datetime
# Logging
import logging
# Logger specifique au service
logger = logging.getLogger("notification_service")


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

    # Signal emis lors de l'ajout d'une notification (envoie l'objet Notification)
    notificationAdded = Signal(object)

    def __init__(self):
        super().__init__()
        # Compteur interne pour generer des IDs uniques
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
        logger.info(f"NotificationService: Création d'une notification '{title}' ({type.name})")
        notif = Notification(
            id=self._next_id,
            title=title,
            message=message,
            timestamp=datetime.now(),
            type=type,
            duration=duration
        )
        self._next_id += 1
        # Emission du signal vers les widgets abonnes
        self.notificationAdded.emit(notif)
