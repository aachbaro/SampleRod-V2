# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - TOUTE la politique de placement magnetique. AUCUN import Qt.
# - Recoit des rectangles et des reglages, retourne une proposition de
#   geometrie. Ne deplace rien, ne persiste rien, ne lit pas le clavier.
#
# REGLE DE SELECTION
# 1. Le candidat admissible le PLUS PROCHE gagne (|delta| minimal, sous le seuil).
# 2. A distance strictement egale, une fenetre l'emporte sur un ecran.
# 3. La grille n'est evaluee que si aucun candidat fenetre ou ecran n'a ete
#    retenu sur cet axe : elle comble un axe libre, elle ne concourt pas.
# 4. Un seul candidat par axe. Une fenetre peut donc s'aligner horizontalement
#    sur une cible et verticalement sur une autre.
# 5. L'egalite finale reste deterministe (target_id puis relation), sans quoi le
#    resultat ne serait pas testable.
#
# ESPACEMENT
# - `gap_px` ne s'applique QU'A l'accolement entre deux fenetres.
# - Jamais aux alignements paralleles, jamais aux bords d'ecran (fenetre a ras).
#
# LIENS CLES
# - frontend/modular/layout/geometry.py      : Rect (convention semi-ouverte)
# - frontend/modular/layout/layout_manager.py: seul appelant en production
# -----------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Iterable, Sequence

from .geometry import Rect, snap_to_grid


class CandidateKind(IntEnum):
    """Type de cible. L'ordre departage une EGALITE de distance, pas plus.

    Ce n'est PAS une priorite absolue : un bord d'ecran a 2 px l'emporte sur
    une fenetre a 5 px. On s'accroche a ce dont on est le plus proche.
    """

    WINDOW = 0
    SCREEN = 1
    GRID = 2  # jamais en competition : voir _resolve_axis


class Relation(str, Enum):
    """Quelle arete s'aligne sur quelle arete."""

    ABUT_LEFT_TO_RIGHT = "abut_left_to_right"
    ABUT_RIGHT_TO_LEFT = "abut_right_to_left"
    ABUT_TOP_TO_BOTTOM = "abut_top_to_bottom"
    ABUT_BOTTOM_TO_TOP = "abut_bottom_to_top"
    ALIGN_LEFT = "align_left"
    ALIGN_RIGHT = "align_right"
    ALIGN_TOP = "align_top"
    ALIGN_BOTTOM = "align_bottom"
    GRID = "grid"


AXIS_X = "x"
AXIS_Y = "y"

_GRID_TARGET_ID = "__grid__"


@dataclass(frozen=True)
class SnapSettings:
    """Reglages du magnetisme. Valeurs par defaut = comportement V1."""

    enabled: bool = True
    threshold_px: int = 12
    grid_px: int = 8
    gap_px: int = 8              # fenetre <-> fenetre UNIQUEMENT
    windows_enabled: bool = True
    screens_enabled: bool = True
    grid_enabled: bool = True


@dataclass(frozen=True)
class SnapCandidate:
    """Une possibilite d'alignement sur un axe."""

    axis: str
    delta: int                   # deplacement signe a appliquer
    kind: CandidateKind
    target_id: str               # identifiant STABLE, departage les egalites
    relation: Relation


@dataclass(frozen=True)
class SnapResult:
    """Proposition finale, explicite pour etre testable."""

    rect: Rect
    snapped_x: bool
    snapped_y: bool
    horizontal_target: SnapCandidate | None
    vertical_target: SnapCandidate | None


def resolve_snap(
    *,
    moving_rect: Rect,
    other_rects: Sequence[tuple[str, Rect]] = (),
    screen_rects: Sequence[tuple[str, Rect]] = (),
    settings: SnapSettings | None = None,
) -> SnapResult:
    """Position proposee pour `moving_rect`. Ne modifie AUCUN rectangle cible.

    Les dimensions ne sont jamais touchees : ce moteur ne fait que deplacer.
    L'alignement des dimensions viendra avec le redimensionnement.
    """
    config = settings or SnapSettings()
    if not config.enabled or not moving_rect.is_valid():
        return SnapResult(moving_rect, False, False, None, None)

    candidates: list[SnapCandidate] = []
    if config.windows_enabled:
        for target_id, target in other_rects or ():
            if target.is_valid():
                candidates.extend(
                    _window_candidates(moving_rect, target, str(target_id), config.gap_px)
                )
    if config.screens_enabled:
        for screen_id, screen in screen_rects or ():
            if screen.is_valid():
                candidates.extend(
                    _screen_candidates(moving_rect, screen, str(screen_id))
                )

    best_x = _resolve_axis(candidates, AXIS_X, moving_rect.left, config)
    best_y = _resolve_axis(candidates, AXIS_Y, moving_rect.top, config)

    rect = moving_rect.moved_to(
        moving_rect.x + (best_x.delta if best_x else 0),
        moving_rect.y + (best_y.delta if best_y else 0),
    )
    return SnapResult(
        rect=rect,
        snapped_x=best_x is not None,
        snapped_y=best_y is not None,
        horizontal_target=best_x,
        vertical_target=best_y,
    )


# -- Interne ------------------------------------------------------------------


def _resolve_axis(
    candidates: Iterable[SnapCandidate],
    axis: str,
    origin_edge: int,
    config: SnapSettings,
) -> SnapCandidate | None:
    """Candidat retenu sur un axe, grille en dernier recours."""
    best = _pick(candidates, axis, config.threshold_px)
    if best is not None:
        return best
    # Rien n'a accroche : la grille peut combler cet axe.
    if not config.grid_enabled:
        return None
    return _grid_candidate(origin_edge, axis, config.grid_px)


def _pick(
    candidates: Iterable[SnapCandidate], axis: str, threshold: int
) -> SnapCandidate | None:
    """Le plus PROCHE gagne ; le type ne departage qu'une egalite."""
    limit = max(0, int(threshold))
    eligible = [
        c for c in candidates if c.axis == axis and abs(c.delta) <= limit
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda c: (
            abs(c.delta),        # 1. proximite — c'est elle qui decide
            c.kind,              # 2. fenetre avant ecran, a distance egale
            c.target_id,         # 3. determinisme
            c.relation.value,    # 4. determinisme
        ),
    )


def _window_candidates(
    moving: Rect, target: Rect, target_id: str, gap: int
) -> list[SnapCandidate]:
    """4 accolements (AVEC espacement) + 4 alignements paralleles (SANS)."""
    space = max(0, int(gap))
    return [
        # Accolement : les fenetres se touchent, a `space` pres.
        SnapCandidate(AXIS_X, (target.right + space) - moving.left,
                      CandidateKind.WINDOW, target_id, Relation.ABUT_LEFT_TO_RIGHT),
        SnapCandidate(AXIS_X, (target.left - space) - moving.right,
                      CandidateKind.WINDOW, target_id, Relation.ABUT_RIGHT_TO_LEFT),
        SnapCandidate(AXIS_Y, (target.bottom + space) - moving.top,
                      CandidateKind.WINDOW, target_id, Relation.ABUT_TOP_TO_BOTTOM),
        SnapCandidate(AXIS_Y, (target.top - space) - moving.bottom,
                      CandidateKind.WINDOW, target_id, Relation.ABUT_BOTTOM_TO_TOP),
        # Alignement parallele : les aretes se confondent, sans espacement.
        SnapCandidate(AXIS_X, target.left - moving.left,
                      CandidateKind.WINDOW, target_id, Relation.ALIGN_LEFT),
        SnapCandidate(AXIS_X, target.right - moving.right,
                      CandidateKind.WINDOW, target_id, Relation.ALIGN_RIGHT),
        SnapCandidate(AXIS_Y, target.top - moving.top,
                      CandidateKind.WINDOW, target_id, Relation.ALIGN_TOP),
        SnapCandidate(AXIS_Y, target.bottom - moving.bottom,
                      CandidateKind.WINDOW, target_id, Relation.ALIGN_BOTTOM),
    ]


def _screen_candidates(moving: Rect, screen: Rect, screen_id: str) -> list[SnapCandidate]:
    """Bords d'ecran : alignement A RAS. `gap_px` ne s'y applique pas."""
    return [
        SnapCandidate(AXIS_X, screen.left - moving.left,
                      CandidateKind.SCREEN, screen_id, Relation.ALIGN_LEFT),
        SnapCandidate(AXIS_X, screen.right - moving.right,
                      CandidateKind.SCREEN, screen_id, Relation.ALIGN_RIGHT),
        SnapCandidate(AXIS_Y, screen.top - moving.top,
                      CandidateKind.SCREEN, screen_id, Relation.ALIGN_TOP),
        SnapCandidate(AXIS_Y, screen.bottom - moving.bottom,
                      CandidateKind.SCREEN, screen_id, Relation.ALIGN_BOTTOM),
    ]


def _grid_candidate(edge: int, axis: str, grid: int) -> SnapCandidate | None:
    """Arrondi sur la grille, seulement si cela deplace vraiment."""
    delta = snap_to_grid(edge, grid) - edge
    if delta == 0:
        return None
    return SnapCandidate(axis, delta, CandidateKind.GRID, _GRID_TARGET_ID, Relation.GRID)
