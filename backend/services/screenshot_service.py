# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Orchestration de la capture d'ecran (backend service).
# - S'appuie sur ScreenshotModel pour la logique pure.
# - Interprete les settings (dossier + ecran par defaut).
# - Notifie l'UI en cas d'erreur/succes.
#
# FLUX GLOBAL
# UI/Remote -> ScreenshotService -> ScreenshotModel -> FS/index.json -> UI
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from backend.models.screenshot import ScreenshotModel
from backend.services.notification_service import NotificationType

logger = logging.getLogger("screenshot_service")


class ScreenshotService(QObject):
    screenshotAdded = Signal(int)     # id ajoute
    screenshotDeleted = Signal(int)   # id supprime
    screenshotsChanged = Signal(list) # liste complete

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context
        self.settings = app_context.settings
        self._model = None
        self._refresh_model()
        try:
            self.settings.screenshotLibraryChanged.connect(self._refresh_model)
            self.settings.screenshotToggled.connect(self._refresh_model)
        except Exception:
            pass

    # ------------------------------------------------------------------ Setup
    def _refresh_model(self):
        enabled = getattr(self.settings, "screenshot_enabled", False)
        folder = getattr(self.settings, "screenshot_library_path", None)
        if enabled and folder:
            self._model = ScreenshotModel(folder)
        else:
            self._model = ScreenshotModel(None)

    def _ensure_ready(self) -> bool:
        if self._model is None:
            self._refresh_model()
        if not self._model or not self._model.is_ready():
            self.app_context.notifications.notify(
                title="Capture impossible",
                message="Selectionnez un dossier pour sauvegarder les captures.",
                type=NotificationType.WARNING,
            )
            return False
        return True

    # ------------------------------------------------------------------ Public API
    def list_screens(self):
        if not self._model:
            self._refresh_model()
        return self._model.list_screens()

    def list_items(self):
        if not self._model:
            self._refresh_model()
        return self._model.list_items()

    def capture(self, screen_index: int | None = None):
        if not self._ensure_ready():
            return None

        if screen_index is None:
            screen_index = getattr(self.settings, "screenshot_default_screen", 0)

        try:
            meta = self._model.capture(screen_index=screen_index)
            # Feedback utilisateur immediat avant les rafraichissements potentiellement lourds.
            self.app_context.notifications.notify(
                title="Capture enregistree",
                message=f"{meta['filename']}",
                type=NotificationType.SUCCESS,
            )
            self.screenshotAdded.emit(int(meta["id"]))
            self.screenshotsChanged.emit(self._model.list_items())
            return meta
        except Exception as exc:
            logger.error(f"[ScreenshotService] capture error: {exc}")
            self.app_context.notifications.notify(
                title="Capture impossible",
                message=str(exc),
                type=NotificationType.ERROR,
            )
            return None

    def rename(self, item_id: int, new_name: str):
        if not self._ensure_ready():
            return None
        meta = self._model.rename(item_id, new_name)
        if meta:
            self.screenshotsChanged.emit(self._model.list_items())
        return meta

    def delete(self, item_id: int) -> bool:
        if not self._ensure_ready():
            return False
        ok = self._model.delete(item_id)
        if ok:
            self.screenshotDeleted.emit(item_id)
            self.screenshotsChanged.emit(self._model.list_items())
        return ok

    def get_path(self, item_id: int):
        if not self._ensure_ready():
            return None
        return self._model.get_path(item_id)
