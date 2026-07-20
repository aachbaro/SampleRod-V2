# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Service centralise de creation et diffusion des notifications UI.
# - Utilise par les services (settings, samples, recorder, etc.) pour informer
#   l'utilisateur sans coupler le code metier aux widgets.
#
# CLASSES ET FONCTIONS (sommaire)
# - NotificationType (Enum)     : INFO / SUCCESS / WARNING / ERROR, determine
#                                 la couleur et l'icone affichees.
# - Notification (dataclass)    : une notification (id, titre, message, date,
#                                 type, duree d'affichage, popup oui/non).
# - NotificationService (QObject)
#   - notify() : cree la notification et la diffuse via le signal
#                notificationAdded ; tous les widgets abonnes la recoivent.
#
# NOTES
# - Le service ne depend que de QtCore (pas de widgets).
# - Les widgets doivent s'abonner a `notificationAdded`.
# - `popup=False` permet de garder une notification dans le centre sans ouvrir
#   de fenetre flottante, utile pour les taches de fond.
# -----------------------------------------------------------------------------

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("notification_service")


class NotificationType(Enum):
    """Types de notifications utilises pour determiner le style / icone."""

    INFO = auto()
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()


@dataclass
class Notification:
    """Modele representant une notification a afficher."""

    id: int
    title: str
    message: str
    timestamp: datetime
    type: NotificationType
    duration: int
    popup: bool = True


class NotificationService(QObject):
    """Service Qt pour gerer la creation et la diffusion des notifications."""

    notificationAdded = Signal(object)

    def __init__(self):
        super().__init__()
        self._next_id = 1

    def notify(
        self,
        title: str,
        message: str,
        type: NotificationType = NotificationType.INFO,
        duration: int = 5000,
        popup: bool = True,
    ) -> None:
        """Cree une notification et emet le signal `notificationAdded`."""

        logger.info(
            "NotificationService: creation d'une notification '%s' (%s, popup=%s)",
            title,
            type.name,
            bool(popup),
        )
        notif = Notification(
            id=self._next_id,
            title=title,
            message=message,
            timestamp=datetime.now(),
            type=type,
            duration=int(duration),
            popup=bool(popup),
        )
        self._next_id += 1
        self.notificationAdded.emit(notif)
