# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Point d'entree principal de l'application desktop.
# - Initialise logging, base SQLAlchemy, AppContext et UI PyQt.
# - Assure le shutdown propre des services a la fermeture.
#
# LIENS CLES
# - backend/models/AppContext.py
# - frontend/main_window.py
# - utils/logger.py
# -----------------------------------------------------------------------------
# app.py

# ./app.py

import sys
import os
import subprocess
import multiprocessing as mp
from pathlib import Path
from utils.logger import configure_logging, get_logger
configure_logging()
logger = get_logger("app")
if sys.platform.startswith("win"):
    import ctypes
    ctypes.windll.ole32.OleInitialize(0)

from backend.db import engine, Base
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSharedMemory, QSystemSemaphore, Qt
import os
from backend.models.AppContext import AppContext
from backend.services.settings_service import SettingsService

from frontend.main_window import MainWindow

def create_database():
    """Crée la base de données et les tables."""
    logger.info("Création de la base de données...")
    Base.metadata.create_all(bind=engine)
    logger.info("Base de données créée avec succès.")

_singleton_memory = None


def _acquire_single_instance(key: str) -> bool:
    """Empêche l'ouverture de plusieurs fenêtres en parallèle."""
    global _singleton_memory
    semaphore = QSystemSemaphore(f"{key}_sem", 1)
    semaphore.acquire()
    shared = QSharedMemory(key)
    if shared.attach():
        shared.detach()
        semaphore.release()
        return False
    if not shared.create(1):
        semaphore.release()
        return False
    semaphore.release()
    _singleton_memory = shared
    return True


def _should_skip_update() -> bool:
    """Evite les boucles d'update (Squirrel) et permet un kill switch."""
    # Kill switch explicite
    if os.getenv("SAMPLEROD_DISABLE_UPDATE") == "1":
        return True
    # Squirrel passe des flags speciaux lors des events
    for arg in sys.argv[1:]:
        if arg.startswith("--squirrel-"):
            return True
    return False


if __name__ == '__main__':
    # Necessaire pour multiprocessing en binaire PyInstaller (Windows)
    mp.freeze_support()
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        # Peut deja etre defini ailleurs
        pass
    # Force un scale stable entre dev et exe (evite tailles UI differentes)
    if os.getenv("SAMPLEROD_DISABLE_SCALE", "0") != "1":
        try:
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_DisableHighDpiScaling, True)
        except Exception:
            pass
    if not _acquire_single_instance("SampleRod.SingleInstance"):
        sys.exit(0)
    create_database()
    app_context = AppContext()  # Initialisation du contexte de l'application
    gui = QApplication(sys.argv)
    # Auto-update (Squirrel) - uniquement en version packagée
    try:
        if (
            getattr(sys, "frozen", False)
            and sys.platform.startswith("win")
            and not _should_skip_update()
        ):
            exe_path = Path(sys.argv[0]).resolve()
            # En Squirrel, l'exe est dans app-<version>\ et Update.exe est un niveau au-dessus
            update_exe = exe_path.parents[1] / "Update.exe"
            if update_exe.exists():
                feed = os.getenv("SAMPLEROD_UPDATE_FEED", "")
                if not feed:
                    try:
                        from PyQt6.QtCore import QSettings
                        qs = QSettings("SampleRod", "Main")
                        feed = qs.value("update_feed", "")
                    except Exception:
                        feed = ""
                if not feed:
                    # Dev: dossier local (a adapter si besoin)
                    feed = "file:///C:/SampleRod/updates"
                subprocess.Popen(
                    [str(update_exe), "--update", feed],
                    creationflags=subprocess.DETACHED_PROCESS,
                    close_fds=True,
                )
    except Exception:
        pass

    gui.setStyleSheet(
        """
        QToolTip {
            background-color: #1e1e1e;
            color: #f2f2f2;
            border: 1px solid #3a3a3a;
            padding: 4px 6px;
        }
        """
    )
    main_window = MainWindow(app_context)
    main_window.show()
    sys.exit(gui.exec())
