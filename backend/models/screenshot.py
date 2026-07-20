# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Toute la mecanique des captures d'ecran, SANS interface : prendre la
#   photo d'un ecran, la ranger dans un dossier, tenir le catalogue a jour.
# - Contrairement aux samples, les captures ne sont PAS en base de donnees :
#   un simple fichier "index.json" dans le dossier des captures sert de
#   catalogue (id, nom de fichier, date, ecran, dimensions).
# - Les fichiers sont nommes IMG_0001.png, IMG_0002.png, etc.
#
# CLASSES ET FONCTIONS (sommaire)
# - ScreenshotItem : fiche descriptive d'une capture (id, fichier, date...).
# - ScreenshotModel
#   - is_ready()       : le dossier de destination est-il configure ?
#   - _load_index() / _save_index() : lecture/ecriture du catalogue JSON
#                        (ecriture "atomique" : fichier temporaire + rename).
#   - _next_id()       : prochain numero IMG_XXXX disponible.
#   - list_screens()   : liste des ecrans branches (multi-moniteurs).
#   - list_items()     : liste des captures du catalogue.
#   - get_path()       : chemin complet d'une capture par son id.
#   - capture()        : prend la photo d'un ecran et l'ajoute au catalogue.
#   - rename()/delete(): renomme ou supprime une capture (fichier + index).
#   - _sanitize_name() : nettoie un nom saisi par l'utilisateur.
#   - _enumerate_monitors_windows() : interroge Windows sur les ecrans.
#   - _grab_all_screens() : photo de tout le bureau (multi-ecrans).
#
# NOTES
# - Pas de dependance au reste de l'app (pas de services, pas de UI) :
#   c'est backend/services/screenshot_service.py qui fait le lien.
# - Utilise PIL.ImageGrab + enumeration Windows via ctypes.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from PIL import ImageGrab

logger = logging.getLogger("screenshot_model")


@dataclass
class ScreenshotItem:
    """Fiche descriptive d'une capture : ce qu'on stocke dans index.json."""

    id: int
    filename: str
    created_at: str
    screen_index: int
    width: int
    height: int

    @property
    def path(self) -> str:
        return self.filename


class ScreenshotModel:
    def __init__(self, base_dir: str | Path | None):
        """
        base_dir: dossier de destination des captures.
        Si None/"" -> le module est "disabled" (capture refuse).
        """
        self.base_dir = Path(base_dir) if base_dir else None
        if self.base_dir:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self.index_path = self.base_dir / "index.json"
        else:
            self.index_path = None

    def is_ready(self) -> bool:
        """Vrai si un dossier de destination est configure (captures possibles)."""
        return self.base_dir is not None and self.index_path is not None

    # ------------------------------------------------------------------ Index
    def _load_index(self) -> List[Dict]:
        """Lit le catalogue index.json ; liste vide si absent ou corrompu."""
        if not self.is_ready():
            return []
        if not self.index_path.exists():
            return []
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Screenshot index illisible, reset.")
            return []

    def _save_index(self, items: List[Dict]) -> None:
        """Ecrit le catalogue de facon "atomique".

        On ecrit d'abord dans un fichier temporaire, puis on le renomme
        par-dessus l'index : ainsi, meme si l'application est coupee en
        pleine ecriture, l'index n'est jamais a moitie ecrit.
        """
        if not self.is_ready():
            return
        tmp_path = self.index_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.index_path)

    def _next_id(self, items: List[Dict]) -> int:
        """Prochain numero libre (max des ids existants + 1)."""
        if not items:
            return 1
        return max(int(it.get("id", 0)) for it in items) + 1

    # -------------------------------------------------------------- Screens
    def list_screens(self) -> List[Dict]:
        """Retourne la liste des ecrans disponibles (Windows)."""
        try:
            return self._enumerate_monitors_windows()
        except Exception as exc:
            logger.warning(f"Impossible d'enumerer les ecrans: {exc}")
            return [{"index": 0, "name": "Primary", "left": 0, "top": 0, "right": 0, "bottom": 0}]

    # -------------------------------------------------------------- Public API
    def list_items(self) -> List[Dict]:
        """Renvoie toutes les captures connues (contenu du catalogue)."""
        return self._load_index()

    def get_path(self, item_id: int) -> Optional[str]:
        """Renvoie le chemin complet du fichier image d'une capture, ou None."""
        if not self.is_ready():
            return None
        items = self._load_index()
        it = next((i for i in items if int(i.get("id", -1)) == item_id), None)
        if not it:
            return None
        return str(self.base_dir / it["filename"])

    def capture(self, screen_index: int = 0) -> Dict:
        """Prend une capture de l'ecran demande et l'ajoute au catalogue.

        Subtilite multi-ecrans : avec plusieurs moniteurs, certains ont des
        coordonnees negatives (ecran a gauche du principal). On photographie
        donc TOUT le bureau virtuel d'un coup, puis on decoupe (crop) la
        zone correspondant a l'ecran voulu. Renvoie la fiche de la capture.
        """
        if not self.is_ready():
            raise RuntimeError("Screenshot folder not configured.")
        screens = self.list_screens()
        # Index hors limites -> on retombe sur l'ecran principal.
        if screen_index < 0 or screen_index >= len(screens):
            screen_index = 0
        screen = screens[screen_index]

        left, top, right, bottom = (
            screen.get("left", 0),
            screen.get("top", 0),
            screen.get("right", 0),
            screen.get("bottom", 0),
        )

        # Capture via PIL (multi-ecrans + coords negatives)
        try:
            # bounding box globale (desktop virtuel)
            v_left = min(s.get("left", 0) for s in screens)
            v_top = min(s.get("top", 0) for s in screens)
            v_right = max(s.get("right", 0) for s in screens)
            v_bottom = max(s.get("bottom", 0) for s in screens)

            # capture du desktop complet (all_screens si supporte)
            img_full = self._grab_all_screens((v_left, v_top, v_right, v_bottom))
            # crop vers l'ecran cible
            crop_box = (
                left - v_left,
                top - v_top,
                right - v_left,
                bottom - v_top,
            )
            img = img_full.crop(crop_box)
        except Exception:
            # fallback simple si la capture globale echoue
            img = self._grab_all_screens((left, top, right, bottom))

        # Enregistrement : nom IMG_XXXX.png + nouvelle entree dans l'index.
        items = self._load_index()
        new_id = self._next_id(items)
        filename = f"IMG_{new_id:04d}.png"
        path = self.base_dir / filename
        img.save(path, format="PNG")

        meta = {
            "id": new_id,
            "filename": filename,
            "created_at": datetime.utcnow().isoformat(),
            "screen_index": screen_index,
            "width": img.width,
            "height": img.height,
        }
        items.append(meta)
        self._save_index(items)
        return meta

    def rename(self, item_id: int, new_name: str) -> Optional[Dict]:
        """Renomme le fichier d'une capture (nom nettoye, extension .png gardee)."""
        if not self.is_ready():
            return None
        items = self._load_index()
        it = next((i for i in items if int(i.get("id", -1)) == item_id), None)
        if not it:
            return None

        safe = self._sanitize_name(new_name)
        if not safe:
            return None
        new_filename = safe + ".png"
        old_path = self.base_dir / it["filename"]
        new_path = self.base_dir / new_filename

        if old_path.exists():
            old_path.rename(new_path)
        it["filename"] = new_filename
        self._save_index(items)
        return it

    def delete(self, item_id: int) -> bool:
        """Supprime une capture : le fichier image puis sa fiche dans l'index."""
        if not self.is_ready():
            return False
        items = self._load_index()
        it = next((i for i in items if int(i.get("id", -1)) == item_id), None)
        if not it:
            return False

        path = self.base_dir / it["filename"]
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

        items = [i for i in items if int(i.get("id", -1)) != item_id]
        self._save_index(items)
        return True

    # -------------------------------------------------------------- Utils
    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Nettoie un nom saisi : espaces -> _, caracteres exotiques retires.

        Evite de creer des noms de fichiers invalides sous Windows.
        Limite a 80 caracteres.
        """
        name = name.strip().replace(" ", "_")
        name = "".join(ch for ch in name if ch.isalnum() or ch in ("_", "-"))
        return name[:80]

    @staticmethod
    def _enumerate_monitors_windows() -> List[Dict]:
        """Demande a Windows la liste des ecrans et leurs positions.

        Passe par l'API systeme EnumDisplayMonitors (via ctypes) : pour
        chaque moniteur, Windows appelle notre fonction _enum_proc qui note
        sa position (left/top/right/bottom) et s'il est l'ecran principal.
        """
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        MONITORINFOF_PRIMARY = 1
        monitors = []

        def _enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
            rect = info.rcMonitor
            monitors.append({
                "index": len(monitors),
                "name": "Primary" if (info.dwFlags & MONITORINFOF_PRIMARY) else f"Monitor {len(monitors)+1}",
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            })
            return 1

        MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                             ctypes.POINTER(RECT), wintypes.LPARAM)
        user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_enum_proc), 0)
        return monitors

    @staticmethod
    def _grab_all_screens(bbox):
        """Wrapper PIL pour compatibilite all_screens."""
        try:
            return ImageGrab.grab(bbox=bbox, all_screens=True)
        except TypeError:
            return ImageGrab.grab(bbox=bbox)
