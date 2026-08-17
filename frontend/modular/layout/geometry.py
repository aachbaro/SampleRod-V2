# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Rectangles et arithmetique de placement. AUCUN import Qt : ce module doit
#   rester testable sans QApplication.
#
# CONVENTION — SEMI-OUVERTE
# - right  = x + width      (PAS x + width - 1)
# - bottom = y + height     (PAS y + height - 1)
#
#   Qt utilise la convention INCLUSIVE pour QRect.right()/bottom(), qui renvoient
#   x + width - 1. Melanger les deux produit des decalages d'un pixel : un
#   accolement demande a 8 px en donnerait 7. On ne passe donc JAMAIS par les
#   aretes calculees par Qt — `rect_from_qrect` est le seul pont, et il n'utilise
#   que les quatre valeurs primitives.
#
# LIENS CLES
# - frontend/modular/layout/snap_engine.py : consommateur principal
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, replace
import math


@dataclass(frozen=True)
class Rect:
    """Rectangle a coordonnees semi-ouvertes, en pixels logiques."""

    x: int
    y: int
    w: int
    h: int

    # -- Aretes -------------------------------------------------------------
    @property
    def left(self) -> int:
        return self.x

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def top(self) -> int:
        return self.y

    @property
    def bottom(self) -> int:
        return self.y + self.h

    # -- Transformations ----------------------------------------------------
    def moved_to(self, x: int, y: int) -> "Rect":
        """Meme rectangle a une autre position. Les dimensions ne bougent pas."""
        return replace(self, x=int(x), y=int(y))

    def translated(self, dx: int, dy: int) -> "Rect":
        return self.moved_to(self.x + int(dx), self.y + int(dy))

    def is_valid(self) -> bool:
        """Un rectangle sans surface ne participe a aucun calcul."""
        return self.w > 0 and self.h > 0


def rect_from_qrect(qrect) -> Rect:
    """Convertit un QRect en Rect. SEUL pont entre les deux conventions.

    On lit les quatre valeurs primitives et on laisse Rect recalculer ses
    aretes. Utiliser qrect.right()/bottom() ici reintroduirait la convention
    inclusive de Qt, donc le decalage d'un pixel qu'on cherche a eviter.
    """
    return Rect(int(qrect.x()), int(qrect.y()), int(qrect.width()), int(qrect.height()))


def snap_to_grid(value: int, grid: int) -> int:
    """Arrondit une coordonnee au multiple de `grid` le plus proche.

    Une grille nulle ou negative n'a pas de sens : on rend la valeur telle
    quelle plutot que de lever, pour qu'un reglage aberrant desactive la
    grille au lieu de casser un deplacement.
    """
    step = int(grid or 0)
    if step <= 0:
        return int(value)
    # round() de Python arrondit les demis vers le pair ; on veut un
    # comportement previsible et symetrique, d'ou le calcul explicite.
    raw = int(value)
    remainder = raw % step
    if remainder * 2 < step:
        return raw - remainder
    return raw + (step - remainder)


def snap_rect_edges_to_grid(
    rect: Rect,
    grid: int,
    *,
    min_width: int = 1,
    min_height: int = 1,
    max_width: int | None = None,
    max_height: int | None = None,
) -> Rect:
    """Aligne les quatre contours d'un rectangle sur la grille.

    Contrairement au snap de deplacement, cette operation peut ajuster la
    taille : gauche/droite et haut/bas deviennent tous des multiples du pas.
    Les minima sont arrondis au multiple superieur afin que Qt ne recorrige
    pas ensuite la taille vers une valeur hors grille.
    """
    step = int(grid or 0)
    if step <= 0 or not rect.is_valid():
        return rect

    left = snap_to_grid(rect.left, step)
    top = snap_to_grid(rect.top, step)
    right = snap_to_grid(rect.right, step)
    bottom = snap_to_grid(rect.bottom, step)

    required_w = max(1, int(min_width or 0))
    required_h = max(1, int(min_height or 0))
    snapped_min_w = math.ceil(required_w / step) * step
    snapped_min_h = math.ceil(required_h / step) * step
    if right - left < snapped_min_w:
        right = left + snapped_min_w
    if bottom - top < snapped_min_h:
        bottom = top + snapped_min_h
    if max_width is not None and int(max_width) > 0:
        snapped_max_w = max(snapped_min_w, (int(max_width) // step) * step)
        if right - left > snapped_max_w:
            right = left + snapped_max_w
    if max_height is not None and int(max_height) > 0:
        snapped_max_h = max(snapped_min_h, (int(max_height) // step) * step)
        if bottom - top > snapped_max_h:
            bottom = top + snapped_max_h
    return Rect(left, top, right - left, bottom - top)


def snap_resized_edges_to_grid(start: Rect, end: Rect, grid: int) -> Rect:
    """Aligne seulement les aretes manipulees pendant un redimensionnement.

    Une arete reste fixe si sa coordonnee est identique entre le debut et la
    fin du geste. Cela evite qu'un resize par la droite fasse bouger la gauche.
    """
    step = int(grid or 0)
    if step <= 0 or not start.is_valid() or not end.is_valid():
        return end
    left = snap_to_grid(end.left, step) if end.left != start.left else end.left
    right = snap_to_grid(end.right, step) if end.right != start.right else end.right
    top = snap_to_grid(end.top, step) if end.top != start.top else end.top
    bottom = snap_to_grid(end.bottom, step) if end.bottom != start.bottom else end.bottom
    if right <= left:
        right = left + step
    if bottom <= top:
        bottom = top + step
    return Rect(left, top, right - left, bottom - top)
