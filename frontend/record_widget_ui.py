# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Construit l'interface visuelle de RecordWidgetWindow.
# - Isole la creation des widgets, la geometrie et les styles statiques.
# - Ne contient pas de logique d'enregistrement ni de gestion d'evenements.
#
# CE QUI EST COUVERT
# - Configuration de la fenetre (flags, opacite, taille).
# - Creation des widgets (bouton REC, indicateur librairie, zone de drag).
# - Icones statiques via qtawesome.
# - Methode apply_shell_style() pour rafraichir le style selon l'etat.
#
# NON-OBJECTIFS
# - Logique start/stop/retro (RecordWidgetWindow).
# - Gestion des evenements souris/molette.
# - Polling du worker d'enregistrement.
#
# CLASSE ET FONCTIONS (sommaire)
# - RecordWidgetUIBuilder
#   - build()              : enchaine les trois etapes ci-dessous.
#   - _build_window()      : fenetre sans bordure, translucide, toujours
#                            au-dessus, opacite 60% au repos.
#   - _build_widgets()     : bouton REC rond, pastille de bibliotheque,
#                            poignee de deplacement, etiquette du nom de
#                            bibliotheque (cachee par defaut) ; installe
#                            les eventFilters vers la fenetre principale.
#   - _apply_static_icons(): icones dossier et poignee (qtawesome).
#   - apply_shell_style()  : couleurs de la coque selon l'etat (rouge =
#                            enregistrement, couleur retro, survol...).
#
# NOTE
# - Toutes les dimensions sont multipliees par window.scale (zoom global
#   du widget) : modifier scale redimensionne tout proportionnellement.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
import qtawesome as qta

from frontend.styles import theme


class RecordWidgetUIBuilder:
    """
    Construit toute l'UI de RecordWidgetWindow.
    Appeler build() depuis __init__ apres avoir initialise les attributs d'etat.
    """

    def __init__(self, window):
        self.w = window

    def build(self):
        self._build_window()
        self._build_widgets()
        self._apply_static_icons()

    # ------------------------------------------------------------------ Window
    def _build_window(self):
        w = self.w
        s = w.scale
        w.setWindowTitle("Record Widget")
        w.setGeometry(int(150 * s), int(150 * s), int(110 * s), int(55 * s))
        w.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        w.setStyleSheet("background: transparent;")
        w.setWindowOpacity(0.6)

    # ------------------------------------------------------------------ Widgets
    def _build_widgets(self):
        w = self.w
        s = w.scale
        base_w = int(28 * s)
        base_h = int(28 * s)
        slot_w  = int(28 * s)

        w.button_container = QWidget(w)
        w.button_container.setObjectName("RecordShell")
        w.base_geometry = QRect(0, 0, base_w, base_h)
        w.button_container.setGeometry(w.base_geometry)

        w.recordButton = QPushButton(w.button_container)
        w.recordButton.setGeometry(
            int(4 * s), int(4 * s), int(20 * s), int(20 * s)
        )
        w.recordButton.setCursor(Qt.CursorShape.PointingHandCursor)
        w.recordButton.setIconSize(QSize(int(14 * s), int(14 * s)))

        w.library_indicator = QLabel(w.button_container)
        w.library_indicator.setGeometry(base_w, 0, slot_w, base_h)
        w.library_indicator.setCursor(Qt.CursorShape.SplitVCursor)
        w.library_indicator.setToolTip("Molette: changer de bibliotheque")

        w.library_number_label = QLabel(w.library_indicator)
        w.library_number_label.setGeometry(0, 0, slot_w, base_h)
        w.library_number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        w.drag_area = QLabel(w)
        w.drag_areaBase_geometry = QRect(
            int(34 * s), 0, int(10 * s), base_h
        )
        w.drag_area.setGeometry(w.drag_areaBase_geometry)
        w.drag_area.setCursor(Qt.CursorShape.OpenHandCursor)
        w.drag_area.setToolTip("Deplacer le widget")
        w.drag_area.setStyleSheet("background: transparent;")

        w.library_name = QLabel(w)
        w.library_name.setGeometry(
            0, int(32 * s), int(180 * s), int(16 * s)
        )
        w.library_name.setVisible(False)
        w.library_name.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        w.button_container.installEventFilter(w)
        w.recordButton.installEventFilter(w)
        w.library_indicator.installEventFilter(w)

    # ------------------------------------------------------------------ Icons
    def _apply_static_icons(self):
        w = self.w
        s = w.scale
        p = theme.manager.p
        w.library_indicator.setPixmap(
            qta.icon("fa5s.folder", color=p.TEXT).pixmap(int(20 * s), int(22 * s))
        )
        w.drag_area.setPixmap(
            qta.icon("fa5s.ellipsis-v", color=p.TEXT_MUTED).pixmap(int(10 * s), int(18 * s))
        )

    # ------------------------------------------------------------------ Style dynamique
    @staticmethod
    def apply_shell_style(window, hovered: bool = False):
        """
        Applique le style de la coque selon l'etat courant.
        Statique pour pouvoir etre appele depuis RecordWidgetWindow sans
        instancier un nouveau builder.
        """
        w = window
        p = theme.manager.p

        if w.app_context.recorder.is_recording:
            border = p.RECORDING
        elif w.settings.isRetroEnabled():
            border = p.RETRO
        else:
            border = p.BORDER

        bg     = p.BG_HOVER if hovered else p.BG
        radius = max(1, w.button_container.height() // 2)

        w.button_container.setStyleSheet(
            f"""
            QWidget#RecordShell {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            """
        )
        w.library_indicator.setStyleSheet("background: transparent; border: none;")
        w.library_number_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {p.BG_CARD};
                border: none;
                font-size: 11px;
                font-weight: 700;
            }}
            """
        )
        w.library_name.setStyleSheet(
            f"""
            QLabel {{
                background-color: {p.BG};
                color: {p.TEXT};
                border: 1px solid {p.BORDER};
                border-radius: 4px;
                padding-left: 6px;
                font-size: 10px;
            }}
            """
        )
