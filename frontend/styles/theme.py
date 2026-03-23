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

from PySide6.QtCore import QObject, Signal, QSettings
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
        saved = QSettings("SampleRod", "Main").value("ui/theme", "dark", type=str)
        name = saved if saved in ("dark", "light") else "dark"
        self._name    = name
        self._palette = DARK if name == "dark" else LIGHT
        self.p        = _PaletteProxy(self._palette)

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
        QSettings("SampleRod", "Main").setValue("ui/theme", name)
        # Bloquer les repaints intermediaires : tout s'applique en un seul frame
        app = QApplication.instance()
        top_level = app.topLevelWidgets() if app else []
        for w in top_level:
            w.setUpdatesEnabled(False)
        self._apply_global_qss()
        self.themeChanged.emit(name)
        for w in top_level:
            w.setUpdatesEnabled(True)

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
    /* === Base === */
    QMainWindow, QDialog {{
        background-color: {p['BG']};
        color: {p['TEXT']};
    }}
    QWidget {{
        background-color: {p['BG']};
        color: {p['TEXT']};
    }}

    /* === Labels === */
    QLabel {{
        background: transparent;
        color: {p['TEXT']};
    }}
    QLabel#SettingsDesc {{
        color: {p['TEXT_MUTED']};
        font-size: 12px;
    }}

    /* === Boutons === */
    QPushButton {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        padding: 5px 12px;
        font-weight: 500;
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
        border: none;
        border-radius: 4px;
        padding: 2px;
    }}
    QToolButton:hover {{
        background-color: {p['BG_HOVER']};
    }}

    /* === Onglets (style underline moderne) === */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {p['BORDER']};
        background-color: {p['BG']};
    }}
    QTabBar {{
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p['TEXT_MUTED']};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 8px 16px;
        margin-right: 2px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        color: {p['TEXT']};
        border-bottom: 2px solid {p['RETRO']};
    }}
    QTabBar::tab:hover:!selected {{
        color: {p['TEXT']};
        background-color: {p['BG_HOVER']};
        border-radius: 4px 4px 0 0;
    }}

    /* === Listes === */
    QListWidget, QListView, QTreeView {{
        background-color: {p['BG_MEDIUM']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        outline: none;
    }}
    QListWidget::item:hover, QListView::item:hover {{
        background-color: {p['BG_HOVER']};
    }}
    QListWidget::item:selected, QListView::item:selected {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
    }}

    /* === Scrollbars (fines et discretes) === */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p['BORDER']};
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p['TEXT_MUTED']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['BORDER']};
        border-radius: 3px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {p['TEXT_MUTED']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    /* === Inputs === */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {p['INFO']};
    }}
    QLineEdit:focus, QTextEdit:focus {{
        border-color: {p['INFO']};
    }}

    QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        padding: 4px 8px;
        min-height: 24px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {p['BG_MEDIUM']};
        border: none;
        width: 16px;
    }}
    QComboBox::drop-down {{
        border: none;
        background: {p['BG_MEDIUM']};
        width: 20px;
        border-radius: 0 6px 6px 0;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['BG_CARD']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        selection-background-color: {p['BG_HOVER']};
        outline: none;
    }}

    /* === Checkbox === */
    QCheckBox {{
        color: {p['TEXT']};
        spacing: 6px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1.5px solid {p['BORDER']};
        border-radius: 4px;
        background: {p['BG_CARD']};
    }}
    QCheckBox::indicator:checked {{
        background: {p['INFO']};
        border-color: {p['INFO']};
    }}
    QCheckBox::indicator:hover {{
        border-color: {p['TEXT_MUTED']};
    }}

    /* === GroupBox === */
    QGroupBox {{
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 10px;
        margin-top: 12px;
        padding: 14px 12px 12px 12px;
        background-color: {p['BG_MEDIUM']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        top: -6px;
        padding: 2px 8px;
        background-color: {p['BG_MEDIUM']};
        border-radius: 4px;
    }}

    /* === Menus === */
    QMenu {{
        background-color: {p['BG_MEDIUM']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 20px 6px 12px;
        border-radius: 4px;
        margin: 1px 4px;
    }}
    QMenu::item:selected {{
        background-color: {p['BG_CARD']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p['BORDER']};
        margin: 4px 8px;
    }}

    /* === Splitter === */
    QSplitter::handle {{
        background-color: {p['BORDER']};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* === Tooltips === */
    QToolTip {{
        background-color: {p['BG_MEDIUM']};
        color: {p['TEXT']};
        border: 1px solid {p['BORDER']};
        border-radius: 6px;
        padding: 4px 8px;
    }}
    """


# ---------------------------------------------------------------------------
# Singleton global
# ---------------------------------------------------------------------------

manager = ThemeManager()
