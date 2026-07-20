# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Atelier modulaire de SampleRod : chaque outil devient une fenetre top-level
#   independante, pilotee par un WindowManager central et listee dans une
#   petite fenetre Workspace (centre de controle).
#
# MODULES
# - instance.py        : ModuleInstance (etat serialisable d'une instance)
# - module_window.py   : ModuleWindow (fenetre hide-on-close + geometrie)
# - module_registry.py : ModuleType / ModuleRegistry (catalogue des types)
# - window_manager.py  : WindowManager (controleur central) + ModuleContext
# - modules_setup.py   : enregistrement des modules concrets
# - workspace_window.py: WorkspaceWindow (centre de controle)
# -----------------------------------------------------------------------------

from .instance import ModuleInstance
from .module_registry import ModuleRegistry, ModuleType
from .module_window import ModuleWindow, clamp_rect_to_screens
from .modules_setup import build_default_registry
from .window_manager import ModuleContext, WindowManager
from .workspace_window import WorkspaceWindow

__all__ = [
    "ModuleInstance",
    "ModuleRegistry",
    "ModuleType",
    "ModuleWindow",
    "clamp_rect_to_screens",
    "build_default_registry",
    "ModuleContext",
    "WindowManager",
    "WorkspaceWindow",
]
