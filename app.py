# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Point d'entree principal de l'application desktop : c'est CE fichier
#   qu'on lance pour demarrer SampleRod (python app.py).
# - Prepare tout ce dont l'application a besoin avant d'afficher la fenetre :
#   journal de bord (logging), base de donnees, contexte global, interface Qt.
# - Empeche d'ouvrir deux fois l'application en meme temps (instance unique).
# - Declenche la recherche de mise a jour automatique (version installee).
#
# FONCTIONS (sommaire)
# - create_database()          : cree les tables de la base si absentes.
# - _acquire_single_instance() : verrou systeme "une seule appli a la fois".
# - _should_skip_update()      : decide si on saute la mise a jour auto.
# - bloc "__main__"            : le scenario de demarrage, etape par etape
#                                (verrou -> theme -> splash -> base -> contexte
#                                 -> update -> fenetre principale).
#
# LIENS CLES
# - backend/models/AppContext.py : le "sac a dos" de services partage partout.
# - frontend/main_window.py      : la fenetre principale construite a la fin.
# - frontend/splash.py           : l'ecran d'attente affiche pendant le chargement.
# - utils/logger.py              : configuration du journal de bord.
# -----------------------------------------------------------------------------
# app.py

import sys
import os

# Reglages d'environnement a faire AVANT d'importer Qt :
# - PYQTGRAPH_QT_LIB : force pyqtgraph (la lib qui dessine les ondes audio)
#   a utiliser PySide6, la meme version de Qt que le reste de l'application.
# - Les variables QT_* desactivent la mise a l'echelle automatique des ecrans
#   haute resolution, qui rendait l'interface floue ou mal proportionnee.
#   (SAMPLEROD_DISABLE_SCALE=1 permet de retrouver le comportement par defaut.)
os.environ.setdefault('PYQTGRAPH_QT_LIB', 'PySide6')
if os.getenv("SAMPLEROD_DISABLE_SCALE", "0") != "1":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
import subprocess
import multiprocessing as mp
from pathlib import Path

# Le journal de bord (logging) est configure en tout premier : ainsi, tout
# probleme survenant pendant le demarrage laisse une trace dans les logs.
from utils.logger import configure_logging, get_logger
configure_logging()
logger = get_logger("app")

# Sous Windows, initialise OLE (mecanisme systeme utilise par le
# glisser-deposer et le presse-papier) avant la creation de l'interface.
if sys.platform.startswith("win"):
    import ctypes
    ctypes.windll.ole32.OleInitialize(0)

from backend.db import engine, Base, ensure_sqlite_schema
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSharedMemory, QSystemSemaphore, Qt

# Patch linecache.getlines juste apres le chargement de PySide6.
# Le hook shiboken (feature_imported) appelle inspect.getsource() sur chaque
# module importe pour savoir s'il utilise PySide6. Sur Windows, l'ouverture
# des fichiers source des extensions C (.pyd) peut se bloquer (Defender / IO).
# En retournant [] pour les fichiers non-.py, on fait lever OSError
# qu'inspect traite gracieusement, sans bloquer.
import linecache as _lc
def _lc_getlines_safe(filename, module_globals=None, _orig=_lc.getlines):
    if filename and not str(filename).endswith('.py'):
        return []
    return _orig(filename, module_globals)
_lc.getlines = _lc_getlines_safe

import os
from backend.models.AppContext import AppContext
from backend.services.settings_service import SettingsService

from frontend.main_window import MainWindow
from frontend.splash import SplashScreen

def create_database():
    """Cree la base de donnees et ses tables si elles n'existent pas encore.

    Au premier lancement, le fichier sample.db est cree avec toutes les
    tables (samples, librairies, screenshots...). Aux lancements suivants,
    rien n'est ecrase : ensure_sqlite_schema() ajoute seulement les
    colonnes apparues dans les nouvelles versions de l'application.
    """
    logger.info("Création de la base de données...")
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema()
    logger.info("Base de données créée avec succès.")

# Garde une reference vivante sur le bloc de memoire partagee : si cette
# variable etait liberee, le verrou "instance unique" tomberait aussitot.
_singleton_memory = None


def _acquire_single_instance(key: str) -> bool:
    """Empeche l'ouverture de plusieurs SampleRod en parallele.

    Principe : on essaie de creer un petit bloc de memoire partagee connu
    de tout le systeme (identifie par `key`). Si le bloc existe deja,
    c'est qu'une autre instance tourne -> on repond False et l'appli se
    ferme immediatement. Le semaphore sert de "tour de parole" pour que
    deux lancements simultanes ne se marchent pas dessus.
    """
    global _singleton_memory
    # Prend le tour de parole (un seul processus a la fois dans cette section).
    semaphore = QSystemSemaphore(f"{key}_sem", 1)
    semaphore.acquire()
    shared = QSharedMemory(key)
    if shared.attach():
        # Le bloc existe deja : une autre instance est ouverte.
        shared.detach()
        semaphore.release()
        return False
    if not shared.create(1):
        # Creation impossible (cas limite) : on prefere refuser le lancement.
        semaphore.release()
        return False
    semaphore.release()
    # On garde le bloc en vie pour toute la duree de l'application.
    _singleton_memory = shared
    return True


def _should_skip_update() -> bool:
    """Decide si on doit sauter la recherche de mise a jour automatique.

    Deux cas ou on ne lance PAS l'updater :
    - l'utilisateur l'a desactive via la variable SAMPLEROD_DISABLE_UPDATE=1 ;
    - l'application vient d'etre lancee PAR l'updater lui-meme (Squirrel),
      qui passe des arguments --squirrel-* : relancer l'update creerait
      une boucle infinie installation -> relance -> installation...
    """
    # Kill switch explicite
    if os.getenv("SAMPLEROD_DISABLE_UPDATE") == "1":
        return True
    # Squirrel passe des flags speciaux lors des events
    for arg in sys.argv[1:]:
        if arg.startswith("--squirrel-"):
            return True
    return False


# =============================================================================
# SCENARIO DE DEMARRAGE
# Ce bloc ne s'execute que si on lance directement "python app.py".
# Chaque etape prepare une brique de l'application, dans l'ordre.
# =============================================================================
if __name__ == '__main__':
    # Etape 0 — multiprocessing : certains traitements lourds (separation de
    # stems, analyse) tournent dans des processus separes. Ces deux appels
    # sont necessaires pour que cela fonctionne aussi dans la version
    # packagee en .exe (PyInstaller sous Windows).
    mp.freeze_support()
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        # Peut deja etre defini ailleurs
        pass

    # Etape 1 — instance unique : si SampleRod est deja ouvert, on quitte.
    if not _acquire_single_instance("SampleRod.SingleInstance"):
        sys.exit(0)

    # Etape 2 — creation de l'application Qt (la boucle d'evenements
    # qui fera vivre toute l'interface).
    gui = QApplication(sys.argv)

    # Etape 3 — theme visuel : applique des le debut pour que le splash
    # herite deja des bons styles (evite le QFont::setPointSize warning).
    from frontend.styles import theme as _theme
    _theme.manager.apply()

    # Etape 4 — ecran d'attente : affiche tout de suite quelque chose a
    # l'utilisateur pendant que le reste (plus long) se charge derriere.
    splash = SplashScreen()
    splash.show()
    QApplication.processEvents()

    # Etape 5 — base de donnees (tables creees / mises a niveau si besoin).
    splash.set_status("Initialisation de la base de donnees...")
    create_database()

    # Etape 6 — AppContext : cree tous les services partages (samples,
    # librairies, enregistrement, notifications...). C'est l'objet qui sera
    # passe a toute l'interface pour acceder aux donnees.
    app_context = None
    main_window = None
    splash.set_status("Chargement du contexte...")
    app_context = AppContext()  # Initialisation du contexte de l'application

    # Etape 7 — auto-update (Squirrel), uniquement en version packagee (.exe).
    # On lance Update.exe en arriere-plan : il telecharge une eventuelle
    # nouvelle version qui sera installee au prochain demarrage. Tout echec
    # ici est ignore : la mise a jour ne doit jamais empecher de demarrer.
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
                        from PySide6.QtCore import QSettings
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

    # Etape 8 — construction de la fenetre principale (tous les onglets,
    # panneaux et widgets sont crees ici, via frontend/main_window.py).
    try:
        splash.set_status("Construction de l'interface...")
        main_window = MainWindow(app_context)

        # Etape 9 — on remplace le splash par la vraie fenetre, puis on entre
        # dans la boucle d'evenements Qt : l'application "vit" dans gui.exec()
        # jusqu'a sa fermeture par l'utilisateur.
        splash.close()
        # start() choisit le mode (classique / modulaire) sans flash de l'autre.
        main_window.start()
        # Le menage des WAV temporaires est secondaire et purement disque : il
        # ne doit plus retarder le premier affichage. Un thread daemon le fait
        # apres que l'interface est deja visible.
        def _prune_in_background():
            try:
                from backend.services.temp_workspace import prune_all_workspaces

                prune_all_workspaces()
            except Exception:
                logger.exception("Menage des fichiers temporaires impossible")

        import threading
        threading.Thread(
            target=_prune_in_background,
            daemon=True,
            name="startup-temp-prune",
        ).start()
        sys.exit(gui.exec())
    except Exception:
        logger.exception("Echec pendant l'initialisation de l'interface")
        try:
            splash.close()
        except Exception:
            pass
        if app_context is not None:
            try:
                app_context.shutdown()
            except Exception:
                logger.exception("Echec pendant le shutdown de secours")
        raise
