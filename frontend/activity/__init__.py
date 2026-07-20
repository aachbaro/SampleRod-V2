# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Index du paquet "activity" (le plateau des taches de fond) : permet
#   d'importer directement ActivityService, ActivityTrayWidget, etc. depuis
#   frontend.activity sans connaitre les fichiers internes.
# -----------------------------------------------------------------------------

from .activity_service import ActivityItem, ActivityService, ActivityStatus
from .activity_tray import ActivityTrayWidget

__all__ = [
    "ActivityItem",
    "ActivityService",
    "ActivityStatus",
    "ActivityTrayWidget",
]
