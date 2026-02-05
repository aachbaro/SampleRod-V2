"""
------------------------------------------------------------------------------
Directory History (QSettings)
------------------------------------------------------------------------------
Role
----
Centralise la gestion de l'historique des dossiers pour le Directory tool.

Stockage (QSettings)
--------------------
On utilise les memes cles que l'implementation initiale:
- last_directory      : dernier dossier ouvert
- recent_directories  : liste (max 10) des dossiers recents

Pourquoi l'extraire ?
---------------------
La logique QSettings est transversale et bruyante dans les widgets.
En l'isolant, on:
- garde DirectoryWidget plus lisible (orchestration + UI)
- peut reutiliser l'historique dans d'autres endroits (ex: MainWindow restore)
------------------------------------------------------------------------------
"""

from __future__ import annotations

from typing import List

from PyQt6.QtCore import QSettings


class DirectoryHistory:
    def __init__(self, settings: QSettings):
        self._qs = settings

    # ------------------------------------------------------------------ last dir
    def get_last_directory(self) -> str:
        return self._qs.value("last_directory", "", type=str)

    def set_last_directory(self, path: str) -> None:
        self._qs.setValue("last_directory", path)

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

