# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Brique du design-core : un layout qui se comporte comme un "flex wrap"
#   CSS. Les enfants sont poses de gauche a droite et passent a la ligne des
#   que la largeur disponible est atteinte.
# - Effet vise : une meme liste s'affiche en COLONNE dans un panneau etroit et
#   en LIGNES/GRILLE quand la fenetre du module s'elargit, sans code de
#   bascule cote widget.
#
# API
#   layout = FlowLayout(container, margin=0, h_spacing=8, v_spacing=8)
#   layout.addWidget(chip)
#   - Les enfants doivent avoir un sizeHint stable (taille fixe conseillee).
#   - hasHeightForWidth() est vrai : dans un QScrollArea, mettre
#     setWidgetResizable(True) et couper la scrollbar horizontale.
#
# LIENS CLES
# - frontend/labo/bins_panel.py : premier usage (chips de bins)
# - UI_MODERNIZATION.md         : charte d'epuration de l'UI
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    """Layout "flex wrap" : retour a la ligne automatique selon la largeur."""

    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 8, v_spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # -- API publique -------------------------------------------------------
    def set_spacing(self, h_spacing: int, v_spacing: int) -> None:
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.invalidate()

    # -- Contrat QLayout ----------------------------------------------------
    def addItem(self, item) -> None:  # noqa: N802 (API Qt)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (API Qt)
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 (API Qt)
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 (API Qt)
        # Le layout ne reclame pas d'espace supplementaire : c'est la largeur
        # disponible qui pilote le nombre de colonnes.
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (API Qt)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (API Qt)
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (API Qt)
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 (API Qt)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (API Qt)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    # -- Interne ------------------------------------------------------------
    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """Pose les items ligne par ligne ; retourne la hauteur totale.

        En mode `test_only`, rien n'est deplace : on ne fait que mesurer
        (c'est ce que Qt appelle pour resoudre heightForWidth).
        """
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = area.x()
        y = area.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_space
            if next_x - self._h_space > area.right() + 1 and line_height > 0:
                # Plus de place sur cette ligne : on passe a la suivante.
                x = area.x()
                y = y + line_height + self._v_space
                next_x = x + hint.width() + self._h_space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()


def make_flow_container(widget, *, margin: int = 0, h_spacing: int = 8, v_spacing: int = 8) -> FlowLayout:
    """Installe un FlowLayout sur `widget` et regle sa politique de taille.

    Deux reglages indispensables pour que la hauteur suive vraiment le
    contenu dans un QScrollArea :
    - `setHeightForWidth(True)` : sinon QScrollArea ignore heightForWidth().
    - politique verticale `Preferred` (et pas `Minimum`) : `Minimum` interdit
      au widget de retrecir sous son sizeHint, donc la hauteur calculee en
      mode colonne restait figee quand le flux repassait en lignes.
    """
    layout = FlowLayout(widget, margin=margin, h_spacing=h_spacing, v_spacing=v_spacing)
    policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    policy.setHeightForWidth(True)
    widget.setSizePolicy(policy)
    return layout
