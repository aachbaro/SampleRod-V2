# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Registre d'icones monochromes (style Tabler Icons) pour toute l'UI modulaire.
# - Rend des QIcon recolorees selon le theme courant (dark/light), avec cache.
#
# COMMENT REMPLACER PAR LES ICONES OFFICIELLES TABLER
# - Deposer un fichier <name>.svg dans frontend/ui/assets/icons/ : il est
#   prioritaire sur la version inline. Les SVG Tabler utilisent
#   stroke="currentColor", donc la recoloration par theme marche telle quelle.
# - Source : https://tabler.io/icons (licence MIT).
#
# API
# - themed_icon(name, size=20, color=None) -> QIcon
# - render_pixmap(name, size=20, color=None) -> QPixmap
# - icon_qss_url(name, size, color) -> "url(...)" pour une feuille de style
# - available_names() -> liste des noms connus (inline + assets)
#
# LIENS CLES
# - frontend/styles/theme.py : couleur par defaut = theme.manager.p.TEXT
# - frontend/ui/icon_button.py : consommateur principal
# -----------------------------------------------------------------------------

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from frontend.styles import theme

_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "icons"

# Corps SVG (viewBox 24x24) style Tabler : trait 2px, bouts ronds, currentColor.
# Les elements qui doivent etre pleins declarent fill="currentColor" localement.
_INLINE: dict[str, str] = {
    # --- Actions fenetres / instances ---
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "check": '<path d="M5 12l4 4L19 6"/>',
    "x": '<path d="M18 6 6 18"/><path d="M6 6l12 12"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/>'
             '<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>'
             '<path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/>',
    "bolt": '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/>',
    "eye": '<circle cx="12" cy="12" r="2"/>'
           '<path d="M22 12c-2.667 4.667-6 7-10 7s-7.333-2.333-10-7c2.667-4.667 6-7 10-7s7.333 2.333 10 7"/>',
    "eye-off": '<path d="M3 3l18 18"/>'
               '<path d="M10.585 10.587a2 2 0 0 0 2.829 2.828"/>'
               '<path d="M9.363 5.365A9.5 9.5 0 0 1 12 5c4 0 7.333 2.333 10 7a17 17 0 0 1-2.503 3.488"/>'
               '<path d="M6.61 6.61C4.9 7.8 3.48 9.6 2 12c2.667 4.667 6 7 10 7 1.5 0 2.9-.33 4.2-.94"/>',
    "pencil": '<path d="M4 20h4l10.5-10.5a2.828 2.828 0 1 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/>'
            '<path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M6 15l6-6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "dots-vertical": '<circle cx="12" cy="5" r="1" fill="currentColor" stroke="none"/>'
                     '<circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>'
                     '<circle cx="12" cy="19" r="1" fill="currentColor" stroke="none"/>',
    "refresh": '<path d="M19.933 13.04a8 8 0 1 1-9.925-8.788c3.899-1 7.935 1.007 9.425 4.747"/>'
               '<path d="M20 4v5h-5"/>',
    "player-play": '<path d="M7 4v16l13-8z" fill="currentColor" stroke="none"/>',
    "player-pause": '<path d="M6 5h4v14H6z" fill="currentColor" stroke="none"/>'
                    '<path d="M14 5h4v14h-4z" fill="currentColor" stroke="none"/>',
    "window": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 9h16"/>',
    "app-window": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 9h16M9 9v11"/>',
    "square": '<rect x="4" y="4" width="16" height="16" rx="2"/>',
    "player-stop": '<rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" stroke="none"/>',
    "repeat": '<path d="M4 12V9a3 3 0 0 1 3-3h13"/><path d="M17 3l3 3-3 3"/>'
              '<path d="M20 12v3a3 3 0 0 1-3 3H4"/><path d="M7 21l-3-3 3-3"/>',
    "scissors": '<circle cx="6" cy="7" r="2"/><circle cx="6" cy="17" r="2"/>'
                '<path d="M8.7 8.7 20 20"/><path d="M8.7 15.3 20 4"/>',
    "camera": '<path d="M5 8h2l1.5-2h7L17 8h2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z"/>'
              '<circle cx="12" cy="13" r="3"/>',
    "bell": '<path d="M10 5a2 2 0 1 1 4 0a5 5 0 0 1 3 4.6V13l1.5 2.5a1 1 0 0 1-.86 1.5H6.36a1 1 0 0 1-.86-1.5L7 13V9.6A5 5 0 0 1 10 5"/>'
            '<path d="M10 19a2 2 0 0 0 4 0"/>',
    "save": '<path d="M6 4h9l3 3v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/>'
            '<path d="M8 4v4h6V4"/><path d="M8 14h8"/>',
    "settings": '<path d="M10.325 4.317a1.724 1.724 0 0 1 3.35 0a1.724 1.724 0 0 0 2.573 1.066'
                'a1.724 1.724 0 0 1 2.755 2.387a1.724 1.724 0 0 0 1.272 2.255a1.724 1.724 0 0 1 0 3.35'
                'a1.724 1.724 0 0 0-1.066 2.573a1.724 1.724 0 0 1-2.387 2.755a1.724 1.724 0 0 0-2.255 1.272'
                'a1.724 1.724 0 0 1-3.35 0a1.724 1.724 0 0 0-2.573-1.066a1.724 1.724 0 0 1-2.755-2.387'
                'a1.724 1.724 0 0 0-1.272-2.255a1.724 1.724 0 0 1 0-3.35a1.724 1.724 0 0 0 1.066-2.573'
                'a1.724 1.724 0 0 1 2.387-2.755a1.724 1.724 0 0 0 2.255-1.272"/>'
                '<circle cx="12" cy="12" r="3"/>',
    "undo": '<path d="M9 13l-4-4 4-4"/><path d="M5 9h9a5 5 0 0 1 0 10h-1"/>',
    "redo": '<path d="M15 13l4-4-4-4"/><path d="M19 9h-9a5 5 0 0 0 0 10h1"/>',
    "pin": '<path d="M12 21s-6-5.686-6-10a6 6 0 1 1 12 0c0 4.314-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/>'
           '<path d="M12 2v2"/><path d="M12 20v2"/><path d="M4.93 4.93l1.41 1.41"/>'
           '<path d="M17.66 17.66l1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/>'
           '<path d="M4.93 19.07l1.41-1.41"/><path d="M17.66 6.34l1.41-1.41"/>',
    "moon": '<path d="M12 3a7.5 7.5 0 1 0 9 9A9 9 0 1 1 12 3z"/>',
    # --- Categories / modules ---
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "wave": '<path d="M3 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0"/>',
    "grid": '<path d="M4 4h16v16H4z"/><path d="M9 4v16"/><path d="M15 4v16"/>'
            '<path d="M4 9h16"/><path d="M4 15h16"/>',
    "layers": '<path d="M12 4l8 4-8 4-8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/>',
    "music": '<circle cx="6" cy="18" r="2.5"/><circle cx="17" cy="16" r="2.5"/>'
             '<path d="M8.5 18V6l11-2v10"/>',
    "stack": '<rect x="4" y="4" width="16" height="6" rx="1"/><rect x="4" y="14" width="16" height="6" rx="1"/>',
    "box": '<path d="M4 7l8-4 8 4v10l-8 4-8-4z"/><path d="M4 7l8 4 8-4M12 11v10"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    # --- Pastilles d'etat ---
    "dot-filled": '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
    "dot-empty": '<circle cx="12" cy="12" r="5"/>',
    "dot-half": '<circle cx="12" cy="12" r="5"/>'
                '<path d="M12 7a5 5 0 0 1 0 10z" fill="currentColor" stroke="none"/>',
}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)

# Cache : (name, size, color) -> QIcon
_ICON_CACHE: dict[tuple[str, int, str], QIcon] = {}

# Cache disque des icones referencees depuis une feuille de style Qt
# (QSS ne sait pointer que vers des fichiers, pas vers un QPixmap en memoire).
_QSS_ICON_DIR = Path(tempfile.gettempdir()) / "SampleRod" / "qss_icons"


def _svg_text(name: str) -> str | None:
    """Texte SVG complet pour un nom : fichier assets prioritaire, sinon inline."""
    asset = _ASSETS_DIR / f"{name}.svg"
    if asset.is_file():
        try:
            return asset.read_text(encoding="utf-8")
        except OSError:
            pass
    body = _INLINE.get(name)
    if body is None:
        return None
    return _SVG_TEMPLATE.format(body=body)


def available_names() -> list[str]:
    """Noms connus (inline + fichiers deposes dans assets/icons/)."""
    names = set(_INLINE)
    if _ASSETS_DIR.is_dir():
        names.update(p.stem for p in _ASSETS_DIR.glob("*.svg"))
    return sorted(names)


def _default_color() -> str:
    return theme.manager.p.TEXT


def render_pixmap(name: str, size: int = 20, color: str | None = None) -> QPixmap:
    """Rend l'icone en QPixmap a la couleur donnee (defaut = texte du theme)."""
    color = color or _default_color()
    text = _svg_text(name)
    if text is None:
        return QPixmap()
    text = text.replace("currentColor", color)
    # Rendu 2x pour rester net sur ecrans HiDPI (devicePixelRatio = 2).
    ratio = 2
    physical = max(1, int(size)) * ratio
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def themed_icon(name: str, size: int = 20, color: str | None = None) -> QIcon:
    """QIcon recoloree selon le theme, mise en cache."""
    color = color or _default_color()
    key = (name, int(size), color)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon(render_pixmap(name, size, color))
    _ICON_CACHE[key] = icon
    return icon


def icon_qss_url(name: str, size: int = 12, color: str | None = None) -> str:
    """Fragment `url("...")` d'une icone, utilisable dans une feuille de style.

    Pourquoi : des qu'on style un `QComboBox` / `QSpinBox` en QSS, Qt cesse de
    dessiner ses indicateurs natifs et les fleches disparaissent. Qt ne sait
    charger une image que depuis un fichier, donc on materialise l'icone du
    theme dans un cache disque et on renvoie son `url(...)`.

    Le fichier `@2x` est ecrit a cote : Qt le choisit automatiquement sur les
    ecrans HiDPI. Retourne "" si l'icone est inconnue (l'appelant peut alors
    omettre la regle plutot que de referencer un fichier absent).
    """
    color = color or _default_color()
    slug = f"{name}_{int(size)}_{color.lstrip('#').lower()}"
    path = _QSS_ICON_DIR / f"{slug}.png"
    if not path.is_file():
        text = _svg_text(name)
        if text is None:
            return ""
        try:
            _QSS_ICON_DIR.mkdir(parents=True, exist_ok=True)
            for suffix, scale in (("", 1), ("@2x", 2)):
                pixmap = _render_flat_pixmap(text, color, int(size) * scale)
                pixmap.save(str(_QSS_ICON_DIR / f"{slug}{suffix}.png"), "PNG")
        except OSError:
            return ""
    return f'url("{path.as_posix()}")'


def _render_flat_pixmap(svg_text: str, color: str, physical_size: int) -> QPixmap:
    """Rend le SVG a une taille physique exacte (sans devicePixelRatio)."""
    renderer = QSvgRenderer(QByteArray(svg_text.replace("currentColor", color).encode("utf-8")))
    pixmap = QPixmap(physical_size, physical_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, physical_size, physical_size))
    painter.end()
    return pixmap


def clear_cache() -> None:
    """Vide le cache d'icones (a appeler si le theme change)."""
    _ICON_CACHE.clear()


# Le theme change -> les couleurs par defaut changent : on invalide le cache.
theme.manager.themeChanged.connect(lambda *_a: clear_cache())
