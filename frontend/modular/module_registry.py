# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Catalogue des TYPES de modules disponibles dans l'atelier modulaire.
# - Chaque type declare : libelle, categorie (entete Workspace), icone, et une
#   factory qui construit le widget de l'outil a partir d'un contexte.
# - Le WindowManager s'appuie dessus pour creer des instances sans connaitre
#   les details de construction de chaque outil.
#
# LIENS CLES
# - frontend/modular/window_manager.py : consomme le registre + fournit le ctx
# - frontend/modular/modules_setup.py  : enregistre les types concrets
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QWidget

# La factory recoit un contexte (duck-typed : app_context, directory_service,
# window_manager) et renvoie le widget de l'outil.
ModuleFactory = Callable[[object], QWidget]


@dataclass(frozen=True)
class ModuleType:
    """Declaration d'un type de module."""

    type_id: str
    label: str            # au singulier, ex "Reserve"
    category: str         # entete plurielle Workspace, ex "RESERVES"
    icon: str             # nom d'icone (frontend/ui/icons.py)
    factory: ModuleFactory
    default_title: str    # titre de base des instances
    multi: bool = True    # plusieurs instances autorisees ?
    workspace_creatable: bool = True
    renamable: bool = True
    duplicable: bool = True
    closable: bool = True


class ModuleRegistry:
    """Registre ordonne des types de modules."""

    def __init__(self):
        self._types: dict[str, ModuleType] = {}

    def register(self, module_type: ModuleType) -> None:
        self._types[module_type.type_id] = module_type

    def get(self, type_id: str) -> ModuleType:
        return self._types[type_id]

    def has(self, type_id: str) -> bool:
        return type_id in self._types

    def all(self) -> list[ModuleType]:
        return list(self._types.values())

    def categories(self) -> list[str]:
        """Categories dans l'ordre d'enregistrement (sans doublon)."""
        seen: list[str] = []
        for mt in self._types.values():
            if mt.category not in seen:
                seen.append(mt.category)
        return seen
