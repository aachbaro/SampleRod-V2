# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Palettes dark/light + ThemeManager (singleton QObject).
# - Genere le QSS global applique a QApplication.
# - Importer : from frontend.styles import theme
#   Puis acceder : theme.manager.palette["BG"]  ou  theme.manager.p.BG
#
# USAGE
#   # Lire la couleur courante
#   theme.manager.p.BG
#
#   # Changer le theme
#   theme.manager.toggle()
#   theme.manager.set_theme("light")
#
#   # Reagir au changement
#   theme.manager.themeChanged.connect(my_restyle_slot)
# -----------------------------------------------------------------------------

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

DARK: dict[str, str] = {
    "BG":           "#16181b",
    "BG_HOVER":     "#1e2228",
    "BG_DARK":      "#121212",
    "BG_MEDIUM":    "#1b1b1b",
    "BG_CARD":      "#2a2a2a",
    "BORDER":       "#3b3f46",
    "BORDER_LIGHT": "#3a3a3a",
    "TEXT":         "#f2f2f2",
    "TEXT_MUTED":   "#8d95a3",
    "RETRO":        "#2cc6cf",
    "RECORDING":    "#e45050",
    "SUCCESS":      "#9bd18f",
    "WARNING":      "#f2c94c",
    "ERROR":        "#d77a7a",
    "INFO":         "#2196F3",
}

LIGHT: dict[str, str] = {
    "BG":           "#f4f5f7",
    "BG_HOVER":     "#e8eaed",
    "BG_DARK":      "#dde0e6",
    "BG_MEDIUM":    "#eef0f3",
    "BG_CARD":      "#ffffff",
    "BORDER":       "#c1c5cc",
    "BORDER_LIGHT": "#d0d3d9",
    "TEXT":         "#1a1d23",
    "TEXT_MUTED":   "#6b7280",
    "RETRO":        "#0891b2",
    "RECORDING":    "#dc2626",
    "SUCCESS":      "#16a34a",
    "WARNING":      "#d97706",
    "ERROR":        "#dc2626",
    "INFO":         "#2563eb",
}


# ---------------------------------------------------------------------------
# Proxy objet — permet theme.manager.p.BG au lieu de theme.manager.palette["BG"]
# ---------------------------------------------------------------------------

class _PaletteProxy:
    """Acces par attribut a la palette courante. theme.manager.p.BG"""
    def __init__(self, palette: dict):
        object.__setattr__(self, "_palette", palette)

    def __getattr__(self, key: str) -> str:
        return object.__getattribute__(self, "_palette")[key]

    def _update(self, palette: dict):
        object.__setattr__(self, "_palette", palette)


# ---------------------------------------------------------------------------
# ThemeManager
# ---------------------------------------------------------------------------

class ThemeManager(QObject):
    """
    Singleton qui gere le theme actif (dark / light).
    Emet themeChanged(str) quand on bascule.
    """
    themeChanged = Signal(str)   # "dark" | "light"

    def __init__(self):
        super().__init__()
        self._name    = "dark"
        self._palette = DARK
        self.p        = _PaletteProxy(DARK)

    @property
    def palette(self) -> dict[str, str]:
        return self._palette

    @property
    def name(self) -> str:
        return self._name

    def is_dark(self) -> bool:
        return self._name == "dark"

    def toggle(self):
        self.set_theme("light" if self._name == "dark" else "dark")

    def set_theme(self, name: str):
        if name == self._name:
            return
        self._name    = name
        self._palette = DARK if name == "dark" else LIGHT
        self.p._update(self._palette)
        self._apply_global_qss()
        self.themeChanged.emit(name)

    def apply(self):
        """Appliquer le theme au demarrage (sans emettre le signal)."""
        self._apply_global_qss()

    def _apply_global_qss(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_global_qss(self._palette))


# ---------------------------------------------------------------------------
# QSS global
# ---------------------------------------------------------------------------

def build_global_qss(p: dict[str, str]) -> str:
    """Genere le QSS applique a QApplication pour couvrir les widgets standard."""
    return f"""
    /* --- Base --- */
    QMainWindow, QDialog {{
        background-color: {p['BG']};
        color: {p['TEXT']};
    }}
    QWidget {{
        background-color: {p['BG']};
        color: {p['TEXT']};
        font-size: 13px;
    }}

    /* --- Labels --- */
    QLabel {{
        background: transparent;
        color: {p['TEXT']};
    }}

    /* --- Boutons --- */
    QPushButton {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 4px;
        padding: 4px 10px;
    }}
    QPushButton:hover {{
        background-color: {p['BG_HOVER']};
        border-color: {p['TEXT_MUTED']};
    }}
    QPushButton:pressed {{
        background-color: {p['BG_DARK']};
    }}
    QPushButton:disabled {{
        color: {p['TEXT_MUTED']};
        border-color: {p['BORDER_LIGHT']};
    }}

    QToolButton {{
        background-color: transparent;
        color: {p['TEXT']};
        border: 1px solid {p['BORDER_LIGHT']};
        border-radius: 4px;
        padding: 2px;
    }}
    QToolButton:hover {{
        background-color: {p['BG_HOVER']};
    }}

    /* --- Onglets --- */
    QTabWidget::pane {{
        border: 1px solid {p['BORDER']};
        background-color: {p['BG']};
    }}
    QTabBar::tab {{
        background-color: {p['BG_MEDIUM']};
        color: {p['TEXT_MUTED']};
        border: 1px solid {p['BORDER']};
        border-bottom: none;
        padding: 6px 14px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {p['BG']};
        color: {p['TEXT']};
        border-bottom: 1px solid {p['BG']};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {p['BG_HOVER']};
        color: {p['TEXT']};
    }}

    /* --- Listes --- */
    QListWidget, QListView, QTreeView {{
        background-color: {p['BG_MEDIUM']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        alternate-background-color: {p['BG_CARD']};
    }}
    QListWidget::item:hover, QListView::item:hover {{
        background-color: {p['BG_HOVER']};
    }}
    QListWidget::item:selected, QListView::item:selected {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
    }}

    /* --- Scrollbar --- */
    QScrollBar:vertical {{
        background: {p['BG_DARK']};
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p['BORDER']};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p['TEXT_MUTED']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {p['BG_DARK']};
        height: 8px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['BORDER']};
        border-radius: 4px;
        min-width: 20px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {p['TEXT_MUTED']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* --- Inputs --- */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 4px;
        padding: 4px 6px;
        selection-background-color: {p['INFO']};
    }}
    QLineEdit:focus, QTextEdit:focus {{
        border-color: {p['INFO']};
    }}

    QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 4px;
        padding: 3px 6px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {p['BG_MEDIUM']};
        border: none;
    }}
    QComboBox::drop-down {{
        border: none;
        background: {p['BG_MEDIUM']};
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        selection-background-color: {p['BG_HOVER']};
    }}

    /* --- Checkbox --- */
    QCheckBox {{
        color: {p['TEXT']};
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {p['BORDER']};
        border-radius: 3px;
        background: {p['BG_CARD']};
    }}
    QCheckBox::indicator:checked {{
        background: {p['INFO']};
        border-color: {p['INFO']};
    }}

    /* --- GroupBox --- */
    QGroupBox {{
        color: {p['TEXT_MUTED']};
        border: 1px solid {p['BORDER']};
        border-radius: 4px;
        margin-top: 8px;
        padding-top: 8px;
        font-size: 11px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }}

    /* --- Menus --- */
    QMenu {{
        background-color: {p['BG_MEDIUM']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
    }}
    QMenu::item:selected {{
        background-color: {p['BG_CARD']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p['BORDER']};
        margin: 2px 0;
    }}

    /* --- Splitter --- */
    QSplitter::handle {{
        background-color: {p['BORDER']};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}
    """


# ---------------------------------------------------------------------------
# Singleton global
# ---------------------------------------------------------------------------

manager = ThemeManager()
