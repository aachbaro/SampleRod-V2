# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Encapsule toutes les operations QSettings liees a l'historique des dossiers.
# - Utilise par DirectoryWidget et DirectoryToolWidget pour restaurer l'etat
#   de la session precedente (dernier dossier, nœuds ouverts, recents).
#
# Cles QSettings gerees :
#   last_directory        : dernier dossier consulte
#   last_root_directory   : derniere racine de navigation
#   expanded_directories  : nœuds d'arbre ouverts (max 200)
#   recent_directories    : liste des dossiers recents (max 10, LIFO)
#
# FONCTIONS (sommaire)
# - DirectoryHistory            : classe principale
# - get/set_last_directory()    : dernier dossier actif
# - get/set_last_root_directory() : derniere racine
# - get/add/remove_expanded_directory() : etat de l'arbre
# - get/add/remove_recent_directory()   : liste des recents
# - remove_from_history()       : methode statique (utile depuis un autre widget)
#
# LIENS CLES
# - frontend/right_panel/directory/directory_widget.py  : principal utilisateur
# - frontend/right_panel/directory/directory_tool.py    : restaure les recents
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import List

from PySide6.QtCore import QSettings


class DirectoryHistory:
    """Gestionnaire de l'historique de navigation des dossiers (persistance QSettings)."""

    def __init__(self, settings: QSettings):
        self._qs = settings

    # ------------------------------------------------------------------ last dir
    def get_last_directory(self) -> str:
        return self._qs.value("last_directory", "", type=str)

    def set_last_directory(self, path: str) -> None:
        self._qs.setValue("last_directory", path)

    def get_last_root_directory(self) -> str:
        return self._qs.value("last_root_directory", "", type=str)

    def set_last_root_directory(self, path: str) -> None:
        self._qs.setValue("last_root_directory", path)

    # ------------------------------------------------------------- tree state
    def get_expanded_directories(self) -> List[str]:
        dirs = self._qs.value("expanded_directories", [], type=list)
        try:
            dirs = list(dirs)
        except Exception:
            dirs = []
        return [path for path in dirs if isinstance(path, str) and path]

    def set_expanded_directories(self, dirs: List[str]) -> None:
        self._qs.setValue("expanded_directories", list(dirs))

    def add_expanded_directory(self, path: str, limit: int = 200) -> None:
        """Ajoute un nœud ouvert ; le ramene en fin de liste s'il existe deja."""
        dirs = self.get_expanded_directories()
        if path in dirs:
            dirs.remove(path)
        dirs.append(path)
        if limit > 0:
            dirs = dirs[-limit:]
        self.set_expanded_directories(dirs)

    def remove_expanded_directory(self, path: str) -> None:
        dirs = self.get_expanded_directories()
        if path in dirs:
            dirs.remove(path)
            self.set_expanded_directories(dirs)

    # ------------------------------------------------------------------ recent dirs
    def get_recent_directories(self) -> List[str]:
        dirs = self._qs.value("recent_directories", [], type=list)
        try:
            dirs = list(dirs)
        except Exception:
            dirs = []

        # Defensive: QSettings peut renvoyer autre chose qu'une liste[str]
        out: List[str] = []
        for d in dirs:
            if isinstance(d, str) and d:
                out.append(d)
        return out

    def set_recent_directories(self, dirs: List[str]) -> None:
        self._qs.setValue("recent_directories", list(dirs))

    def add_recent_directory(self, path: str, limit: int = 10) -> None:
        """Ajoute un dossier en tete des recents (LIFO, max 10 par defaut)."""
        dirs = self.get_recent_directories()
        if path in dirs:
            dirs.remove(path)
        dirs.insert(0, path)
        if limit > 0:
            dirs = dirs[:limit]
        self.set_recent_directories(dirs)

    def remove_recent_directory(self, path: str) -> None:
        dirs = self.get_recent_directories()
        if path in dirs:
            dirs.remove(path)
            self.set_recent_directories(dirs)

    # ------------------------------------------------------------------ convenience
    @staticmethod
    def remove_from_history(path: str) -> None:
        """Utilise une instance QSettings fraiche (utile depuis MainWindow)."""
        qs = QSettings("SampleRod", "Main")
        DirectoryHistory(qs).remove_recent_directory(path)

