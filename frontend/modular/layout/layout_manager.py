# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Controleur spatial de l'atelier : sait quelles fenetres existent, ou elles
#   sont, met a jour leur geometrie en memoire et planifie l'ecriture disque.
# - N'est PAS un second WindowManager : celui-ci reste l'autorite sur le cycle
#   de vie des instances. Ce controleur ne s'occupe que de l'espace.
#
# CE QU'IL NE FAIT PAS ENCORE (phase 1)
# - Aucun magnetisme. Il observe et persiste, rien de plus. Le snap arrivera
#   en phase 4, branche sur le cycle d'interaction de la phase 3.
#
# DEUX CONCEPTS A NE PAS CONFONDRE
# - `geometry_changed()` : la fenetre a bougé, pour n'importe quelle raison
#   (drag en cours, setGeometry programmatique, restauration). Sert UNIQUEMENT
#   a la memoire et a la persistance. Ne declenche JAMAIS de snap.
# - `interaction_started/finished()` (phase 3) : l'utilisateur a saisi puis
#   relache la fenetre. C'est le seul signal qui declenchera le magnetisme.
#
# LES TROIS GARDES
# - _suspended          : controleur en veille (bascule de mode, arret)
# - _applying_geometry  : on est en train d'appliquer une geometrie nous-memes.
#                         Sans cette garde, setGeometry -> moveEvent ->
#                         geometry_changed -> ... La re-entrance a ete MESUREE
#                         (profondeur 2), ce n'est pas une precaution theorique.
# - _restoring_session  : restauration en cours ; les positions restaurees ne
#                         doivent jamais etre traitees comme un geste.
#
# LIENS CLES
# - frontend/modular/window_manager.py : enregistre/desenregistre les fenetres
# - frontend/modular/layout/snap_engine.py : le moteur (phase 4)
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from .geometry import (
    Rect,
    rect_from_qrect,
    snap_rect_edges_to_grid,
    snap_resized_edges_to_grid,
    snap_to_grid,
)
from .snap_engine import CandidateKind, SnapSettings, resolve_snap

logger = logging.getLogger("layout_manager")

# Delai d'ecriture disque. La geometrie en memoire, elle, est mise a jour
# immediatement : ce debounce ne retarde que le passage en QSettings.
PERSIST_DEBOUNCE_MS = 500


def _is_snappable(window) -> bool:
    """Une fenetre participe-t-elle a l'espace en ce moment ?

    Sont ecartees : les fenetres masquees (elles ne sont pas la), maximisees,
    minimisees ou en plein ecran (leur geometrie est imposee par l'OS, la
    corriger n'aurait aucun sens), et les objets Qt detruits.
    """
    try:
        if not window.isVisible():
            return False
        for state in ("isMinimized", "isMaximized", "isFullScreen"):
            check = getattr(window, state, None)
            if callable(check) and check():
                return False
        return True
    except (RuntimeError, AttributeError):
        return False


@dataclass
class RegisteredWindow:
    """Une fenetre connue du controleur spatial.

    `managed_by_window_manager` distingue les fenetres d'instances (dont la
    geometrie vit dans ModuleInstance.geometry) des fenetres externes comme le
    Workspace, qui ont leur propre stockage. Le controleur n'a pas a le savoir
    au-dela de ce drapeau.
    """

    window_id: str
    window: object
    module_type: str | None = None
    participates_as_source: bool = True
    participates_as_target: bool = True
    managed_by_window_manager: bool = True


class WorkspaceLayoutManager(QObject):
    """Registre spatial des fenetres et planificateur de persistance."""

    # Emis quand la session merite d'etre ecrite sur disque (debouncé).
    persistRequested = Signal()
    # Emis quand la geometrie memoire d'une fenetre externe change.
    externalGeometryChanged = Signal(str, dict)

    def __init__(self, window_manager=None, parent=None, settings: "SnapSettings | None" = None):
        super().__init__(parent)
        self._window_manager = window_manager
        self._windows: dict[str, RegisteredWindow] = {}
        self._settings = settings or SnapSettings()
        # Le quadrillage affiche peut etre plus large que le pas spatial de
        # base. Les deplacements libres doivent rejoindre les lignes que
        # l'utilisateur voit, sans modifier les autres reglages du moteur.
        self._alignment_grid_px = self._settings.grid_px
        # Rectangle au DEBUT du geste, par fenetre. C'est lui qui permet de
        # distinguer un deplacement d'un redimensionnement : WM_ENTERSIZEMOVE
        # et WM_EXITSIZEMOVE couvrent les deux gestes indistinctement.
        self._start_rects: dict[str, Rect] = {}
        # Debounce par fenetre des changements imposes par un layout/contenu
        # (apparition de stems, page de reglages chargee, etc.).
        self._programmatic_timers: dict[str, QTimer] = {}
        # Gardes — voir l'en-tete du module.
        self._suspended = False
        self._applying_geometry = False
        self._restoring_session = False

        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(PERSIST_DEBOUNCE_MS)
        self._persist_timer.timeout.connect(self.persistRequested.emit)

    # -- Registre -----------------------------------------------------------
    def register_window(
        self,
        window_id: str,
        window,
        *,
        module_type: str | None = None,
        participates_as_source: bool = True,
        participates_as_target: bool = True,
        managed_by_window_manager: bool = True,
    ) -> RegisteredWindow:
        """Enregistre une fenetre. Idempotent : re-enregistrer met a jour."""
        entry = RegisteredWindow(
            window_id=str(window_id),
            window=window,
            module_type=module_type,
            participates_as_source=bool(participates_as_source),
            participates_as_target=bool(participates_as_target),
            managed_by_window_manager=bool(managed_by_window_manager),
        )
        self._windows[entry.window_id] = entry
        return entry

    def unregister_window(self, window_id: str) -> None:
        """Retire une fenetre. A appeler a la FERMETURE, sans exception.

        Une fenetre detruite mais toujours enregistree deviendrait une cible
        fantome, et la consulter reviendrait a toucher un objet Qt mort. On
        jette aussi son rectangle de depart, sans quoi un geste interrompu par
        une fermeture laisserait une entree orpheline.
        """
        key = str(window_id)
        self._windows.pop(key, None)
        self._start_rects.pop(key, None)
        timer = self._programmatic_timers.pop(key, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def is_registered(self, window_id: str) -> bool:
        return str(window_id) in self._windows

    def registered_ids(self) -> list[str]:
        return list(self._windows.keys())

    def entry(self, window_id: str) -> RegisteredWindow | None:
        return self._windows.get(str(window_id))

    # -- Gardes -------------------------------------------------------------
    @property
    def suspended(self) -> bool:
        return self._suspended

    @property
    def applying_geometry(self) -> bool:
        return self._applying_geometry

    @property
    def restoring_session(self) -> bool:
        return self._restoring_session

    def set_suspended(self, suspended: bool) -> None:
        self._suspended = bool(suspended)

    @contextmanager
    def applying_geometry_guard(self):
        """Encadre toute geometrie que NOUS appliquons."""
        previous = self._applying_geometry
        self._applying_geometry = True
        try:
            yield
        finally:
            self._applying_geometry = previous

    @contextmanager
    def restoring_session_guard(self):
        """Encadre la restauration de session."""
        previous = self._restoring_session
        self._restoring_session = True
        try:
            yield
        finally:
            self._restoring_session = previous

    def _is_inert(self) -> bool:
        """Vrai si le controleur doit ignorer ce qui se passe."""
        return self._suspended or self._applying_geometry or self._restoring_session

    # -- Observation --------------------------------------------------------
    def geometry_changed(self, window_id: str) -> None:
        """La fenetre a bouge, pour une raison quelconque.

        Met a jour la memoire et planifie l'ecriture. **Ne declenche aucun
        magnetisme** : le snap n'ecoute que la fin d'interaction (phase 4).
        """
        if self._is_inert():
            return
        entry = self._windows.get(str(window_id))
        if entry is None:
            return
        rect = self._rect_of(entry)
        if rect is None:
            return
        self._commit(entry, rect)
        # Pendant un geste natif, la correction attend interaction_finished.
        # Hors geste, il s'agit d'un resize/move de contenu ou de code : on le
        # normalise apres que Qt a fini sa cascade de layouts.
        if entry.window_id not in self._start_rects:
            self._schedule_programmatic_alignment(entry.window_id)

    # -- Cycle d'interaction (le seul declencheur du magnetisme) -------------
    @property
    def settings(self) -> SnapSettings:
        return self._settings

    def set_settings(self, settings: SnapSettings) -> None:
        self._settings = settings or SnapSettings()
        self._alignment_grid_px = self._settings.grid_px

    @property
    def alignment_grid_px(self) -> int:
        return self._alignment_grid_px

    def set_alignment_grid_px(self, grid_px: int) -> None:
        """Definit le pas visible utilise par le snap de position."""
        value = int(grid_px or 0)
        self._alignment_grid_px = value if value > 0 else self._settings.grid_px

    def align_windows_to_grid(self, grid_px: int) -> int:
        """Recale les geometries existantes sur les lignes du quadrillage.

        Les fenetres masquees sont incluses : leur geometrie serialisee doit
        elle aussi etre propre avant leur prochaine ouverture. Les etats
        imposes par l'OS (minimise/maximise/plein ecran) restent intacts.
        Retourne le nombre de fenetres effectivement modifiees.
        """
        if self._is_inert() or int(grid_px or 0) <= 0:
            return 0

        changed = 0
        for entry in list(self._windows.values()):
            window = entry.window
            try:
                if any(
                    callable(check := getattr(window, state, None)) and check()
                    for state in ("isMinimized", "isMaximized", "isFullScreen")
                ):
                    continue
            except (RuntimeError, AttributeError):
                continue

            current = self._rect_of(entry)
            if current is None or not current.is_valid():
                continue
            min_w, min_h, max_w, max_h = self._size_limits_of(window)
            final = snap_rect_edges_to_grid(
                current, grid_px, min_width=min_w, min_height=min_h,
                max_width=max_w, max_height=max_h,
            )
            if final == current:
                continue
            try:
                with self.applying_geometry_guard():
                    self._apply_spatial_rect(window, final)
            except (RuntimeError, AttributeError):
                continue
            # Les move/resizeEvent emis par setGeometry sont volontairement
            # ignores par la garde ; on enregistre donc nous-memes le resultat.
            self._store_geometry(entry, final)
            changed += 1

        if changed:
            self.schedule_persist()
        return changed

    def _schedule_programmatic_alignment(self, window_id: str) -> None:
        key = str(window_id)
        timer = self._programmatic_timers.get(key)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(lambda key=key: self._align_programmatic_window(key))
            self._programmatic_timers[key] = timer
        timer.start()

    def _align_programmatic_window(self, window_id: str) -> None:
        """Repare un changement de geometrie qui ne vient pas d'un drag."""
        key = str(window_id)
        if self._is_inert() or key in self._start_rects:
            return
        entry = self._windows.get(key)
        if entry is None:
            return
        window = entry.window
        try:
            if any(
                callable(check := getattr(window, state, None)) and check()
                for state in ("isMinimized", "isMaximized", "isFullScreen")
            ):
                return
        except (RuntimeError, AttributeError):
            return
        current = self._rect_of(entry)
        if current is None or not current.is_valid():
            return
        min_w, min_h, max_w, max_h = self._size_limits_of(window)
        final = snap_rect_edges_to_grid(
            current, self._alignment_grid_px,
            min_width=min_w, min_height=min_h,
            max_width=max_w, max_height=max_h,
        )
        if final == current:
            return
        try:
            with self.applying_geometry_guard():
                self._apply_spatial_rect(window, final)
        except (RuntimeError, AttributeError):
            return
        self._commit(entry, final)

    def interaction_started(self, window_id: str) -> None:
        """L'utilisateur a saisi la fenetre : on retient son rectangle."""
        entry = self._windows.get(str(window_id))
        if entry is None:
            return
        rect = self._rect_of(entry)
        if rect is not None:
            self._start_rects[entry.window_id] = rect

    def interaction_finished(self, window_id: str) -> None:
        """L'utilisateur a relache : c'est ICI, et seulement ici, qu'on snappe."""
        key = str(window_id)
        start = self._start_rects.pop(key, None)

        if self._is_inert():
            return
        entry = self._windows.get(key)
        if entry is None or not entry.participates_as_source:
            return
        if not _is_snappable(entry.window):
            return
        end = self._rect_of(entry)
        if end is None:
            return

        # Classification. Sans rectangle de depart (cas degrade), on suppose un
        # deplacement : c'est l'hypothese la moins destructrice, car le snap de
        # position ne touche de toute facon jamais aux dimensions.
        moved = start is None or (start.x != end.x or start.y != end.y)
        resized = start is not None and (start.w != end.w or start.h != end.h)

        # Ctrl maintenu AU MOMENT DU RELACHEMENT : placement libre, mais
        # persiste. On lit l'etat reel du clavier plutot que de suivre nous
        # memes les appuis, qui se desynchronisent des qu'un raccourci passe.
        if self._control_held():
            self._commit(entry, end)
            return

        # Un redimensionnement aligne uniquement les aretes qui ont vraiment
        # bouge. Cela couvre aussi une poignee gauche/haute, pour laquelle x/y
        # changent en meme temps que w/h sans etre un deplacement de fenetre.
        if resized and start is not None:
            final = snap_resized_edges_to_grid(
                start, end, self._alignment_grid_px
            )
            if final != end:
                with self.applying_geometry_guard():
                    try:
                        self._apply_spatial_rect(entry.window, final)
                    except (RuntimeError, AttributeError):
                        logger.debug("Redimensionnement impossible sur %s", key)
                        return
            self._commit(entry, final)
            return

        result = resolve_snap(
            moving_rect=end,
            other_rects=self._collect_targets(exclude=key),
            screen_rects=self._collect_screens(),
            settings=replace(self._settings, grid_px=self._alignment_grid_px),
        )
        # Geste combine : on ne retient QUE la position. Les dimensions du
        # rectangle final sont celles que l'utilisateur vient de definir.
        # Le magnetisme FENETRE peut proposer un accolement avec un gap
        # historique (8 px, par exemple) qui tombe entre deux lignes d'une
        # grille visible plus large. Sur cet axe, la grille est l'invariant
        # final. Les bords d'ecran restent exacts : availableGeometry() n'est
        # pas garanti multiple de la grille (barre des taches, multi-ecran).
        snap_x_after_window = (
            self._settings.grid_enabled
            and result.horizontal_target is not None
            and result.horizontal_target.kind == CandidateKind.WINDOW
        )
        snap_y_after_window = (
            self._settings.grid_enabled
            and result.vertical_target is not None
            and result.vertical_target.kind == CandidateKind.WINDOW
        )
        final = Rect(
            snap_to_grid(result.rect.x, self._alignment_grid_px)
            if snap_x_after_window else result.rect.x,
            snap_to_grid(result.rect.y, self._alignment_grid_px)
            if snap_y_after_window else result.rect.y,
            end.w,
            end.h,
        )

        if final != end:
            with self.applying_geometry_guard():
                try:
                    self._apply_spatial_rect(entry.window, final)
                except (RuntimeError, AttributeError):
                    logger.debug("Application impossible sur %s", key)
                    return
        self._commit(entry, final)

    # -- Collecte ------------------------------------------------------------
    def _collect_targets(self, exclude: str | None = None) -> list[tuple[str, Rect]]:
        """Cibles eligibles : enregistrees, vivantes, visibles, etat normal."""
        targets: list[tuple[str, Rect]] = []
        for window_id, entry in self._windows.items():
            if window_id == exclude or not entry.participates_as_target:
                continue
            if not _is_snappable(entry.window):
                continue
            rect = self._rect_of(entry)
            if rect is not None and rect.is_valid():
                targets.append((window_id, rect))
        return targets

    @staticmethod
    def _collect_screens() -> list[tuple[str, Rect]]:
        """Zones UTILES des ecrans : la barre des taches en est deja exclue."""
        screens: list[tuple[str, Rect]] = []
        for index, screen in enumerate(QGuiApplication.screens()):
            try:
                name = screen.name() or f"screen_{index}"
                screens.append((str(name), rect_from_qrect(screen.availableGeometry())))
            except (RuntimeError, AttributeError):
                continue
        return screens

    @staticmethod
    def _control_held() -> bool:
        app = QApplication.instance()
        if app is None:
            return False
        return bool(app.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

    # -- Persistance --------------------------------------------------------
    def _commit(self, entry: RegisteredWindow, rect: Rect) -> None:
        """Geometrie en MEMOIRE immediatement, disque un peu plus tard."""
        self._store_geometry(entry, rect)
        self.schedule_persist()

    def _store_geometry(self, entry: RegisteredWindow, rect: Rect) -> None:
        # Le moteur travaille avec le CADRE visible. La session historique,
        # elle, stocke QWidget.geometry() (rectangle client). On conserve ce
        # format pour restaurer sans migration ni saut au prochain lancement.
        stored = self._client_rect_of(entry.window) or rect
        payload = {
            "x": stored.x, "y": stored.y,
            "width": stored.w, "height": stored.h,
        }
        if entry.managed_by_window_manager:
            instance = self._instance_for(entry.window_id)
            if instance is not None:
                instance.geometry = payload
        else:
            # Fenetre externe (Workspace) : elle gere son propre stockage.
            self.externalGeometryChanged.emit(entry.window_id, payload)

    def schedule_persist(self) -> None:
        """Planifie une ecriture disque. Les appels rapproches fusionnent."""
        self._persist_timer.start()

    def flush_persist(self) -> None:
        """Force l'ecriture tout de suite (arret de l'application)."""
        if self._persist_timer.isActive():
            self._persist_timer.stop()
        self.persistRequested.emit()

    # -- Acces au modele ----------------------------------------------------
    def _instance_for(self, window_id: str):
        if self._window_manager is None:
            return None
        getter = getattr(self._window_manager, "get_instance", None)
        if not callable(getter):
            return None
        try:
            return getter(window_id)
        except Exception:
            return None

    @staticmethod
    def _rect_of(entry: RegisteredWindow) -> Rect | None:
        """Rectangle courant d'une fenetre, None si elle n'est plus utilisable.

        Une fenetre Qt detruite leve RuntimeError a l'acces : on l'attrape ici
        plutot que de laisser remonter depuis un moveEvent.
        """
        window = entry.window
        try:
            frame_getter = getattr(window, "frameGeometry", None)
            if callable(frame_getter):
                frame = frame_getter()
                if frame is not None and frame.width() > 0 and frame.height() > 0:
                    return rect_from_qrect(frame)
            return rect_from_qrect(window.geometry())
        except (RuntimeError, AttributeError):
            logger.debug("Fenetre %s inaccessible, ignoree", entry.window_id)
            return None

    @staticmethod
    def _client_rect_of(window) -> Rect | None:
        try:
            return rect_from_qrect(window.geometry())
        except (RuntimeError, AttributeError):
            return None

    @staticmethod
    def _frame_margins_of(window) -> tuple[int, int, int, int]:
        """Marges natives (gauche, haut, droite, bas) en pixels logiques."""
        try:
            client = window.geometry()
            frame = window.frameGeometry()
            left = max(0, int(client.x() - frame.x()))
            top = max(0, int(client.y() - frame.y()))
            right = max(0, int(frame.width() - client.width() - left))
            bottom = max(0, int(frame.height() - client.height() - top))
            return left, top, right, bottom
        except (RuntimeError, AttributeError, TypeError, ValueError):
            return 0, 0, 0, 0

    @classmethod
    def _apply_spatial_rect(cls, window, frame_rect: Rect) -> None:
        """Applique un rectangle de cadre via l'API client de QWidget."""
        left, top, right, bottom = cls._frame_margins_of(window)
        window.setGeometry(
            frame_rect.x + left,
            frame_rect.y + top,
            max(1, frame_rect.w - left - right),
            max(1, frame_rect.h - top - bottom),
        )

    @staticmethod
    def _size_limits_of(window) -> tuple[int, int, int | None, int | None]:
        """Contraintes propres au module, convertibles en cellules de grille."""
        width = height = 1
        try:
            width = max(width, int(window.minimumWidth()))
            height = max(height, int(window.minimumHeight()))
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass
        try:
            hint = window.minimumSizeHint()
            if hint is not None and hint.isValid():
                width = max(width, int(hint.width()))
                height = max(height, int(hint.height()))
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass
        max_width = max_height = None
        try:
            raw_w = int(window.maximumWidth())
            raw_h = int(window.maximumHeight())
            # Valeur sentinelle QWidget : aucune limite utile.
            max_width = raw_w if 0 < raw_w < 16_777_215 else None
            max_height = raw_h if 0 < raw_h < 16_777_215 else None
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass
        left, top, right, bottom = WorkspaceLayoutManager._frame_margins_of(window)
        extra_w, extra_h = left + right, top + bottom
        return (
            width + extra_w,
            height + extra_h,
            max_width + extra_w if max_width is not None else None,
            max_height + extra_h if max_height is not None else None,
        )
