"""Controleur spatial : registre, gardes, memoire et persistance debouncee.

Phase 1 : le controleur OBSERVE et PERSISTE. Il ne doit appliquer aucun
magnetisme — le snap viendra se brancher sur la fin d'interaction.

Les fenetres sont des doublures : on teste la logique, pas Qt.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from frontend.modular.layout.geometry import Rect
from frontend.modular.layout.layout_manager import (
    RegisteredWindow,
    WorkspaceLayoutManager,
)
from frontend.modular.layout.snap_engine import SnapSettings

_app = QApplication.instance() or QApplication([])


class _FakeQRect:
    def __init__(self, x, y, w, h):
        self._v = (x, y, w, h)

    def x(self): return self._v[0]
    def y(self): return self._v[1]
    def width(self): return self._v[2]
    def height(self): return self._v[3]


class _FakeWindow:
    """Fenetre minimale : une geometrie, un etat, eventuellement morte."""

    def __init__(self, x=0, y=0, w=400, h=300, visible=True):
        self._rect = (x, y, w, h)
        self.dead = False
        self.visible = visible
        self.minimized = False
        self.maximized = False
        self.fullscreen = False
        self.set_calls: list[tuple] = []

    def geometry(self):
        if self.dead:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        return _FakeQRect(*self._rect)

    def setGeometry(self, x, y, w, h):  # noqa: N802 (API Qt)
        if self.dead:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        self.set_calls.append((x, y, w, h))
        self._rect = (x, y, w, h)

    def isVisible(self):  # noqa: N802
        if self.dead:
            raise RuntimeError("wrapped C/C++ object has been deleted")
        return self.visible

    def isMinimized(self):  # noqa: N802
        return self.minimized

    def isMaximized(self):  # noqa: N802
        return self.maximized

    def isFullScreen(self):  # noqa: N802
        return self.fullscreen

    def move_to(self, x, y):
        """Simule un deplacement utilisateur (sans passer par setGeometry)."""
        self._rect = (x, y, self._rect[2], self._rect[3])

    def resize_to(self, w, h):
        self._rect = (self._rect[0], self._rect[1], w, h)


class _FramedFakeWindow(_FakeWindow):
    """Top-level Windows : geometry=client, frameGeometry=contour visible."""

    def __init__(self, frame=(97, 99, 403, 301), margins=(1, 27, 1, 1)):
        self._margins = margins
        left, top, right, bottom = margins
        x, y, w, h = frame
        super().__init__(x + left, y + top, w - left - right, h - top - bottom)

    def frameGeometry(self):  # noqa: N802
        left, top, right, bottom = self._margins
        x, y, w, h = self._rect
        return _FakeQRect(
            x - left, y - top,
            w + left + right, h + top + bottom,
        )


class _FakeInstance:
    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.geometry = None


class _FakeWindowManager:
    def __init__(self):
        self._instances = {}

    def add(self, instance_id):
        self._instances[instance_id] = _FakeInstance(instance_id)
        return self._instances[instance_id]

    def get_instance(self, instance_id):
        return self._instances.get(instance_id)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.manager = WorkspaceLayoutManager(_FakeWindowManager())

    def test_a_window_can_be_registered_and_found(self):
        self.manager.register_window("waveform_001", _FakeWindow())
        self.assertTrue(self.manager.is_registered("waveform_001"))
        self.assertEqual(self.manager.registered_ids(), ["waveform_001"])

    def test_unregistering_removes_it(self):
        self.manager.register_window("waveform_001", _FakeWindow())
        self.manager.unregister_window("waveform_001")
        self.assertFalse(self.manager.is_registered("waveform_001"))
        self.assertEqual(self.manager.registered_ids(), [])

    def test_unregistering_an_unknown_window_is_harmless(self):
        self.manager.unregister_window("jamais_vu")  # ne doit pas lever

    def test_registering_twice_updates_instead_of_duplicating(self):
        first, second = _FakeWindow(), _FakeWindow()
        self.manager.register_window("w", first)
        self.manager.register_window("w", second)
        self.assertEqual(len(self.manager.registered_ids()), 1)
        self.assertIs(self.manager.entry("w").window, second)

    def test_an_external_window_is_marked_as_such(self):
        self.manager.register_window(
            "workspace", _FakeWindow(), managed_by_window_manager=False
        )
        self.assertFalse(self.manager.entry("workspace").managed_by_window_manager)

    def test_participation_defaults_to_both_roles(self):
        entry = self.manager.register_window("w", _FakeWindow())
        self.assertTrue(entry.participates_as_source)
        self.assertTrue(entry.participates_as_target)

    def test_a_window_can_be_excluded_from_both_roles(self):
        # C'est ainsi que le Backdrop sera tenu a l'ecart.
        entry = self.manager.register_window(
            "backdrop", _FakeWindow(),
            participates_as_source=False, participates_as_target=False,
        )
        self.assertFalse(entry.participates_as_source)
        self.assertFalse(entry.participates_as_target)


class MemoryUpdateTests(unittest.TestCase):
    """La geometrie en memoire est mise a jour IMMEDIATEMENT."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("waveform_001")
        self.manager = WorkspaceLayoutManager(self.wm)
        self.window = _FakeWindow(120, 80, 900, 560)
        self.manager.register_window("waveform_001", self.window)

    def test_geometry_lands_in_the_instance_at_once(self):
        self.manager.geometry_changed("waveform_001")
        self.assertEqual(
            self.instance.geometry,
            {"x": 120, "y": 80, "width": 900, "height": 560},
        )

    def test_memory_is_updated_before_any_disk_write(self):
        # Le timer n'a pas encore expire : la memoire, elle, est deja a jour.
        written = []
        self.manager.persistRequested.connect(lambda: written.append(1))
        self.manager.geometry_changed("waveform_001")
        self.assertIsNotNone(self.instance.geometry)
        self.assertEqual(written, [])

    def test_an_unknown_window_changes_nothing(self):
        self.manager.geometry_changed("inconnue")
        self.assertIsNone(self.instance.geometry)

    def test_a_destroyed_window_is_ignored_without_raising(self):
        # Un objet Qt detruit leve RuntimeError a l'acces : cela ne doit pas
        # remonter depuis un moveEvent.
        self.window.dead = True
        self.manager.geometry_changed("waveform_001")
        self.assertIsNone(self.instance.geometry)

    def test_an_external_window_reports_through_a_signal(self):
        seen = []
        self.manager.externalGeometryChanged.connect(
            lambda wid, payload: seen.append((wid, payload))
        )
        self.manager.register_window(
            "workspace", _FakeWindow(10, 20, 320, 620), managed_by_window_manager=False
        )
        self.manager.geometry_changed("workspace")
        self.assertEqual(seen, [("workspace", {"x": 10, "y": 20, "width": 320, "height": 620})])


class GuardTests(unittest.TestCase):
    """Les trois gardes. Deux d'entre elles couvrent des risques MESURES."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("w")
        self.manager = WorkspaceLayoutManager(self.wm)
        self.manager.register_window("w", _FakeWindow(3, 5, 400, 300))

    def test_a_suspended_manager_ignores_everything(self):
        self.manager.set_suspended(True)
        self.manager.geometry_changed("w")
        self.assertIsNone(self.instance.geometry)

    def test_applying_geometry_ourselves_does_not_re_enter(self):
        # setGeometry declenche un moveEvent, donc un geometryChanged. Sans
        # cette garde on repartait pour un tour : la re-entrance a ete mesuree
        # a la profondeur 2 sur une vraie fenetre.
        with self.manager.applying_geometry_guard():
            self.manager.geometry_changed("w")
        self.assertIsNone(self.instance.geometry)

    def test_the_guard_is_released_afterwards(self):
        with self.manager.applying_geometry_guard():
            pass
        self.manager.geometry_changed("w")
        self.assertIsNotNone(self.instance.geometry)

    def test_restoring_a_session_never_looks_like_a_gesture(self):
        with self.manager.restoring_session_guard():
            self.manager.geometry_changed("w")
        self.assertIsNone(self.instance.geometry)

    def test_guards_nest_without_leaking(self):
        with self.manager.applying_geometry_guard():
            with self.manager.applying_geometry_guard():
                self.assertTrue(self.manager.applying_geometry)
            self.assertTrue(self.manager.applying_geometry)   # encore dedans
        self.assertFalse(self.manager.applying_geometry)

    def test_a_guard_is_released_even_if_something_raises(self):
        with self.assertRaises(ValueError):
            with self.manager.applying_geometry_guard():
                raise ValueError("boom")
        self.assertFalse(self.manager.applying_geometry)


class PersistenceDebounceTests(unittest.TestCase):
    """Memoire immediate, disque groupe."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.wm.add("w")
        self.manager = WorkspaceLayoutManager(self.wm)
        self.manager.register_window("w", _FakeWindow())
        self.writes = []
        self.manager.persistRequested.connect(lambda: self.writes.append(1))

    def test_many_rapid_moves_produce_a_single_write(self):
        for _ in range(50):
            self.manager.geometry_changed("w")
        self.assertEqual(self.writes, [])          # rien n'est encore parti
        self.manager.flush_persist()
        self.assertEqual(len(self.writes), 1)

    def test_flushing_stops_the_pending_timer(self):
        self.manager.geometry_changed("w")
        self.manager.flush_persist()
        self.assertFalse(self.manager._persist_timer.isActive())
        self.assertEqual(len(self.writes), 1)

    def test_the_timer_is_single_shot(self):
        self.assertTrue(self.manager._persist_timer.isSingleShot())


class ExistingGeometryGridAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("module")
        self.manager = WorkspaceLayoutManager(self.wm)
        self.window = _FakeWindow(13, 19, 101, 77)
        self.manager.register_window("module", self.window)

    def test_position_and_size_are_aligned_in_one_geometry_call(self):
        changed = self.manager.align_windows_to_grid(16)
        self.assertEqual(changed, 1)
        self.assertEqual(self.window.set_calls, [(16, 16, 96, 80)])
        self.assertEqual(
            self.instance.geometry,
            {"x": 16, "y": 16, "width": 96, "height": 80},
        )

    def test_hidden_windows_are_aligned_for_their_next_opening(self):
        self.window.visible = False
        self.manager.align_windows_to_grid(16)
        self.assertEqual(self.window.set_calls, [(16, 16, 96, 80)])

    def test_maximized_windows_are_not_touched(self):
        self.window.maximized = True
        self.assertEqual(self.manager.align_windows_to_grid(16), 0)
        self.assertEqual(self.window.set_calls, [])

    def test_dead_windows_are_ignored(self):
        self.window.dead = True
        self.assertEqual(self.manager.align_windows_to_grid(16), 0)

    def test_all_changes_share_one_debounced_write(self):
        self.wm.add("second")
        second = _FakeWindow(31, 47, 99, 71)
        self.manager.register_window("second", second)
        writes = []
        self.manager.persistRequested.connect(lambda: writes.append(1))
        self.manager.align_windows_to_grid(16)
        self.assertEqual(writes, [])
        self.manager.flush_persist()
        self.assertEqual(writes, [1])


class NativeFrameGridAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("framed")
        self.manager = WorkspaceLayoutManager(self.wm)
        self.window = _FramedFakeWindow()
        self.entry = self.manager.register_window("framed", self.window)

    def test_spatial_rectangle_is_the_visible_native_frame(self):
        self.assertEqual(self.manager._rect_of(self.entry), Rect(97, 99, 403, 301))

    def test_grid_aligns_frame_but_persists_historical_client_geometry(self):
        self.assertEqual(self.manager.align_windows_to_grid(32), 1)

        frame = self.window.frameGeometry()
        self.assertEqual(
            (frame.x(), frame.y(), frame.width(), frame.height()),
            (96, 96, 416, 320),
        )
        self.assertEqual(self.window.set_calls, [(97, 123, 414, 292)])
        self.assertEqual(
            self.instance.geometry,
            {"x": 97, "y": 123, "width": 414, "height": 292},
        )


class ProgrammaticGeometryAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("stem")
        self.manager = WorkspaceLayoutManager(self.wm)
        self.manager.set_alignment_grid_px(32)
        self.window = _FakeWindow(64, 64, 320, 256)
        self.manager.register_window("stem", self.window)

    def test_content_driven_resize_is_aligned_after_the_layout_settles(self):
        # Simule Stem Lab qui grandit lorsque ses pistes apparaissent.
        self.window.resize_to(347, 283)
        self.manager.geometry_changed("stem")
        self.assertEqual(self.window.set_calls, [])
        QTest.qWait(5)
        self.assertEqual(self.window.set_calls, [(64, 64, 352, 288)])
        self.assertEqual(
            self.instance.geometry,
            {"x": 64, "y": 64, "width": 352, "height": 288},
        )

    def test_user_drag_is_never_corrected_by_the_programmatic_path(self):
        self.manager.interaction_started("stem")
        self.window.resize_to(347, 283)
        self.manager.geometry_changed("stem")
        QTest.qWait(5)
        self.assertEqual(self.window.set_calls, [])

    def test_all_four_final_edges_are_grid_aligned(self):
        self.window._rect = (71, 79, 347, 283)
        self.manager.geometry_changed("stem")
        QTest.qWait(5)
        rect = self.window.geometry()
        edges = (rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())
        self.assertTrue(all(edge % 32 == 0 for edge in edges))


class NoSnapInPhaseOneTests(unittest.TestCase):
    """Phase 1 : le controleur n'applique AUCUNE geometrie."""

    def test_observing_never_moves_a_window(self):
        wm = _FakeWindowManager()
        wm.add("w")
        manager = WorkspaceLayoutManager(wm)
        window = _FakeWindow(103, 207, 400, 300)   # position non alignee
        manager.register_window("w", window)
        for _ in range(10):
            manager.geometry_changed("w")
        # Aucun setGeometry : la fenetre reste exactement ou elle etait.
        self.assertEqual(window.set_calls, [])
        self.assertEqual(window.geometry().x(), 103)


class InteractionClassificationTests(unittest.TestCase):
    """WM_ENTERSIZEMOVE/EXITSIZEMOVE couvrent DEUX gestes distincts.

    Sans classification, redimensionner une fenetre corrigerait sa position :
    c'est le piege le plus subtil de cette phase.
    """

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("moving")
        # Grille coupee : on veut isoler l'effet des cibles.
        self.manager = WorkspaceLayoutManager(
            self.wm,
            # Grille et ecrans coupes : ces tests portent sur les cibles
            # fenetres. Sans cela ils dependraient de la taille de l'ecran
            # offscreen, qui n'a rien a voir avec ce qu'ils verifient.
            settings=SnapSettings(grid_enabled=False, screens_enabled=False),
        )
        # Cible fixe dont le bord droit est a 100.
        self.target_window = _FakeWindow(0, 0, 100, 100)
        self.manager.register_window("target", self.target_window)
        self.window = _FakeWindow(300, 0, 50, 50)
        self.manager.register_window("moving", self.window)

    def _gesture(self, *, move_to=None, resize_to=None):
        self.manager.interaction_started("moving")
        if move_to is not None:
            self.window.move_to(*move_to)
        if resize_to is not None:
            self.window.resize_to(*resize_to)
        self.manager.interaction_finished("moving")

    def test_a_move_alone_snaps_the_position(self):
        self._gesture(move_to=(105, 0))            # vise 108 (100 + 8)
        self.assertEqual(self.window.geometry().x(), 108)

    def test_window_magnetism_cannot_leave_a_window_between_visible_lines(self):
        self.manager.set_settings(
            SnapSettings(grid_enabled=True, screens_enabled=False)
        )
        self.manager.set_alignment_grid_px(32)
        # La cible finit sur une ligne (x=128). L'ancien gap de 8 proposerait
        # x=136, visiblement decale ; le resultat final revient a x=128.
        self.target_window._rect = (32, 0, 96, 96)
        self._gesture(move_to=(135, 0))
        self.assertEqual(self.window.geometry().x(), 128)
        self.assertEqual(self.window.geometry().x() % 32, 0)

    def test_a_free_move_uses_the_visible_grid_step(self):
        self.manager.set_settings(
            SnapSettings(windows_enabled=False, screens_enabled=False, grid_px=8)
        )
        self.manager.set_alignment_grid_px(32)
        self._gesture(move_to=(47, 79))
        self.assertEqual(
            (self.window.geometry().x(), self.window.geometry().y()),
            (32, 64),
        )

    def test_a_resize_alone_never_corrects_the_position(self):
        # La fenetre reste a x=105 : on n'a PAS deplace, donc on ne snappe pas.
        self.window.move_to(105, 0)
        self.manager.interaction_started("moving")
        self.window.resize_to(80, 80)
        self.manager.interaction_finished("moving")
        self.assertEqual(self.window.geometry().x(), 105)
        self.assertEqual(self.window.geometry().width(), 79)

    def test_a_resize_alone_still_persists(self):
        self.window.move_to(105, 0)
        self.manager.interaction_started("moving")
        self.window.resize_to(80, 80)
        self.manager.interaction_finished("moving")
        self.assertEqual(self.instance.geometry["width"], 79)

    def test_resize_uses_the_visible_grid_step(self):
        self.manager.set_alignment_grid_px(32)
        self.window = _FakeWindow(32, 32, 96, 64)
        self.manager.register_window("moving", self.window)
        self.manager.interaction_started("moving")
        self.window.resize_to(115, 83)
        self.manager.interaction_finished("moving")
        self.assertEqual(self.window.set_calls, [(32, 32, 128, 96)])

    def test_a_combined_gesture_aligns_all_edges_that_moved(self):
        self._gesture(move_to=(105, 0), resize_to=(77, 63))
        rect = self.window.geometry()
        self.assertEqual(
            (rect.x(), rect.y(), rect.width(), rect.height()),
            (104, 0, 80, 64),
        )

    def test_a_gesture_that_changed_nothing_applies_no_geometry(self):
        self.window.move_to(108, 0)                # deja accole
        self._gesture()
        self.assertEqual(self.window.set_calls, [])

    def test_at_most_one_set_geometry_is_applied(self):
        self._gesture(move_to=(105, 0))
        self.assertEqual(len(self.window.set_calls), 1)

    def test_the_start_rect_is_forgotten_after_the_gesture(self):
        self._gesture(move_to=(105, 0))
        self.assertNotIn("moving", self.manager._start_rects)

    def test_a_finish_without_a_start_is_treated_as_a_move(self):
        # Cas degrade : on suppose un deplacement, l'hypothese la moins
        # destructrice puisque le snap ne touche jamais aux dimensions.
        self.window.move_to(105, 0)
        self.manager.interaction_finished("moving")
        self.assertEqual(self.window.geometry().x(), 108)

    def test_closing_a_window_mid_gesture_leaves_no_orphan(self):
        self.manager.interaction_started("moving")
        self.manager.unregister_window("moving")
        self.assertNotIn("moving", self.manager._start_rects)


class SnapTargetEligibilityTests(unittest.TestCase):
    """Qui a le droit d'attirer, et qui a le droit d'etre attire."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.wm.add("moving")
        self.manager = WorkspaceLayoutManager(
            self.wm,
            # Grille et ecrans coupes : ces tests portent sur les cibles
            # fenetres. Sans cela ils dependraient de la taille de l'ecran
            # offscreen, qui n'a rien a voir avec ce qu'ils verifient.
            settings=SnapSettings(grid_enabled=False, screens_enabled=False),
        )
        self.window = _FakeWindow(105, 0, 50, 50)
        self.manager.register_window("moving", self.window)

    def _finish(self):
        self.manager.interaction_started("moving")
        self.manager.interaction_finished("moving")

    def _add_target(self, **kwargs):
        target = _FakeWindow(0, 0, 100, 100, **kwargs)
        self.manager.register_window("target", target)
        return target

    def test_a_visible_target_attracts(self):
        self._add_target()
        self._finish()
        self.assertEqual(self.window.geometry().x(), 108)

    def test_a_hidden_target_does_not_attract(self):
        self._add_target(visible=False)
        self._finish()
        self.assertEqual(self.window.geometry().x(), 105)

    def test_a_maximized_target_does_not_attract(self):
        self._add_target().maximized = True
        self._finish()
        self.assertEqual(self.window.geometry().x(), 105)

    def test_a_minimized_target_does_not_attract(self):
        self._add_target().minimized = True
        self._finish()
        self.assertEqual(self.window.geometry().x(), 105)

    def test_a_destroyed_target_does_not_attract_and_does_not_raise(self):
        self._add_target().dead = True
        self._finish()
        self.assertEqual(self.window.geometry().x(), 105)

    def test_a_target_excluded_by_contract_does_not_attract(self):
        # C'est ainsi que le Backdrop est tenu a l'ecart.
        backdrop = _FakeWindow(0, 0, 100, 100)
        self.manager.register_window(
            "backdrop", backdrop,
            participates_as_source=False, participates_as_target=False,
        )
        self._finish()
        self.assertEqual(self.window.geometry().x(), 105)

    def test_a_maximized_window_is_never_moved(self):
        self._add_target()
        self.window.maximized = True
        self._finish()
        self.assertEqual(self.window.set_calls, [])

    def test_a_hidden_window_is_never_moved(self):
        self._add_target()
        self.window.visible = False
        self._finish()
        self.assertEqual(self.window.set_calls, [])

    def test_a_window_excluded_as_source_is_never_moved(self):
        self._add_target()
        self.manager.register_window(
            "moving", self.window, participates_as_source=False
        )
        self._finish()
        self.assertEqual(self.window.set_calls, [])

    def test_the_target_itself_never_moves(self):
        target = self._add_target()
        self._finish()
        self.assertEqual(target.set_calls, [])

    def test_a_window_is_never_its_own_target(self):
        # Sans cible autre que soi, rien ne doit bouger.
        self._finish()
        self.assertEqual(self.window.set_calls, [])


class ControlKeyTests(unittest.TestCase):
    """Ctrl est lu AU MOMENT du relachement, pas suivi manuellement."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.instance = self.wm.add("moving")
        self.manager = WorkspaceLayoutManager(
            self.wm,
            # Grille et ecrans coupes : ces tests portent sur les cibles
            # fenetres. Sans cela ils dependraient de la taille de l'ecran
            # offscreen, qui n'a rien a voir avec ce qu'ils verifient.
            settings=SnapSettings(grid_enabled=False, screens_enabled=False),
        )
        self.manager.register_window("target", _FakeWindow(0, 0, 100, 100))
        self.window = _FakeWindow(105, 0, 50, 50)
        self.manager.register_window("moving", self.window)

    def _finish_with_control(self, held: bool):
        with mock.patch.object(
            WorkspaceLayoutManager, "_control_held", staticmethod(lambda: held)
        ):
            self.manager.interaction_started("moving")
            self.manager.interaction_finished("moving")

    def test_without_control_the_snap_applies(self):
        self._finish_with_control(False)
        self.assertEqual(self.window.geometry().x(), 108)

    def test_holding_control_keeps_the_free_position(self):
        self._finish_with_control(True)
        self.assertEqual(self.window.geometry().x(), 105)
        self.assertEqual(self.window.set_calls, [])

    def test_the_free_position_is_still_persisted(self):
        self._finish_with_control(True)
        self.assertEqual(self.instance.geometry["x"], 105)


class GuardsDuringSnapTests(unittest.TestCase):
    """Les gardes valent aussi pour le magnetisme."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.wm.add("moving")
        self.manager = WorkspaceLayoutManager(
            self.wm,
            # Grille et ecrans coupes : ces tests portent sur les cibles
            # fenetres. Sans cela ils dependraient de la taille de l'ecran
            # offscreen, qui n'a rien a voir avec ce qu'ils verifient.
            settings=SnapSettings(grid_enabled=False, screens_enabled=False),
        )
        self.manager.register_window("target", _FakeWindow(0, 0, 100, 100))
        self.window = _FakeWindow(105, 0, 50, 50)
        self.manager.register_window("moving", self.window)

    def test_a_suspended_manager_never_snaps(self):
        self.manager.set_suspended(True)
        self.manager.interaction_started("moving")
        self.manager.interaction_finished("moving")
        self.assertEqual(self.window.set_calls, [])

    def test_a_restoring_manager_never_snaps(self):
        with self.manager.restoring_session_guard():
            self.manager.interaction_started("moving")
            self.manager.interaction_finished("moving")
        self.assertEqual(self.window.set_calls, [])

    def test_applying_geometry_does_not_re_enter(self):
        # La garde est posee pendant setGeometry : le geometryChanged qui en
        # decoule ne doit pas relancer un tour. Re-entrance MESUREE (prof. 2).
        seen = []
        original = self.window.setGeometry

        def spy(x, y, w, h):
            seen.append((x, y, w, h))
            original(x, y, w, h)
            # Simule le moveEvent que Qt emettrait derriere.
            self.manager.geometry_changed("moving")

        self.window.setGeometry = spy
        self.manager.interaction_started("moving")
        self.manager.interaction_finished("moving")
        self.assertEqual(len(seen), 1, "setGeometry applique plus d'une fois")

    def test_snapping_can_be_disabled_entirely(self):
        self.manager.set_settings(SnapSettings(enabled=False))
        self.manager.interaction_started("moving")
        self.manager.interaction_finished("moving")
        self.assertEqual(self.window.set_calls, [])


class ScreenSnapTests(unittest.TestCase):
    """Magnetisme aux bords utiles de l'ecran, sans espacement."""

    def setUp(self):
        self.wm = _FakeWindowManager()
        self.wm.add("moving")
        self.manager = WorkspaceLayoutManager(
            self.wm, settings=SnapSettings(grid_enabled=False, gap_px=8)
        )
        # Ecrans simules : on ne depend pas de la machine qui execute.
        self._screens = [("main", Rect(0, 0, 1920, 1040))]
        self.manager._collect_screens = lambda: list(self._screens)

    def _finish(self, window):
        self.manager.register_window("moving", window)
        self.manager.interaction_started("moving")
        self.manager.interaction_finished("moving")

    def test_a_window_snaps_flush_to_the_left_edge(self):
        window = _FakeWindow(4, 400, 300, 200)
        self._finish(window)
        # A ras : l'espacement de 8 px ne s'applique PAS aux bords d'ecran.
        self.assertEqual(window.geometry().x(), 0)

    def test_a_window_snaps_flush_to_the_right_edge(self):
        window = _FakeWindow(1615, 400, 300, 200)      # right = 1915
        self._finish(window)
        self.assertEqual(window.geometry().x() + 300, 1920)

    def test_a_window_snaps_to_the_bottom_of_the_usable_area(self):
        # 1040 et non 1080 : la barre des taches est exclue en amont.
        window = _FakeWindow(400, 835, 300, 200)       # bottom = 1035
        self._finish(window)
        self.assertEqual(window.geometry().y() + 200, 1040)

    def test_a_far_window_is_left_alone(self):
        window = _FakeWindow(500, 400, 300, 200)
        self._finish(window)
        self.assertEqual(window.set_calls, [])

    def test_screen_magnetism_can_be_disabled(self):
        self.manager.set_settings(
            SnapSettings(grid_enabled=False, screens_enabled=False)
        )
        window = _FakeWindow(4, 400, 300, 200)
        self._finish(window)
        self.assertEqual(window.set_calls, [])

    def test_a_nearer_screen_edge_beats_a_further_window(self):
        # Proximite d'abord : l'ecran a 4 px l'emporte sur la fenetre a 7 px.
        self.manager.register_window("target", _FakeWindow(11, 400, 100, 100))
        window = _FakeWindow(4, 700, 300, 200)
        self._finish(window)
        self.assertEqual(window.geometry().x(), 0)

    def test_real_screens_are_collected_with_a_usable_name(self):
        # Le nom peut etre vide selon la plateforme : un repli doit exister,
        # sinon deux ecrans anonymes seraient indiscernables.
        manager = WorkspaceLayoutManager(self.wm)
        screens = manager._collect_screens()
        self.assertTrue(screens)
        for name, rect in screens:
            self.assertTrue(name)
            self.assertTrue(rect.is_valid())


class WindowManagerWiringTests(unittest.TestCase):
    """Le cablage reel : vrai WindowManager, vraies ModuleWindow.

    Le registre en isolation ne prouve rien si personne ne l'alimente. Ces
    tests verifient que le cycle de vie des instances enregistre et
    desenregistre effectivement.
    """

    def setUp(self):
        from frontend.modular.module_registry import ModuleRegistry, ModuleType
        from frontend.modular.window_manager import WindowManager
        from PySide6.QtWidgets import QWidget

        registry = ModuleRegistry()
        registry.register(
            ModuleType(
                type_id="dummy",
                label="Dummy",
                category="test",
                icon="square",
                default_title="Dummy",
                multi=True,
                factory=lambda _ctx: QWidget(),
            )
        )
        self.manager = WindowManager(None, None, registry)

    def tearDown(self):
        self.manager.clear()

    def test_creating_an_instance_registers_its_window(self):
        instance_id = self.manager.create_instance("dummy", show=False)
        self.assertTrue(self.manager.layout_manager.is_registered(instance_id))

    def test_the_registered_entry_knows_its_module_type(self):
        instance_id = self.manager.create_instance("dummy", show=False)
        entry = self.manager.layout_manager.entry(instance_id)
        self.assertEqual(entry.module_type, "dummy")

    def test_closing_an_instance_unregisters_its_window(self):
        instance_id = self.manager.create_instance("dummy", show=False)
        self.manager.close_instance(instance_id)
        self.assertFalse(self.manager.layout_manager.is_registered(instance_id))

    def test_a_closed_window_is_no_longer_a_possible_target(self):
        # Scenario du plan : A et B enregistrees, B fermee, A doit continuer
        # a fonctionner sans jamais consulter la reference morte de B.
        first = self.manager.create_instance("dummy", show=False)
        second = self.manager.create_instance("dummy", show=False)
        self.manager.close_instance(second)

        remaining = self.manager.layout_manager.registered_ids()
        self.assertIn(first, remaining)
        self.assertNotIn(second, remaining)
        # A continue de rapporter sa geometrie sans lever.
        self.manager.layout_manager.geometry_changed(first)
        self.assertIsNotNone(self.manager.get_instance(first).geometry)

    def test_restoring_a_session_does_not_persist_along_the_way(self):
        # La restauration applique des geometries : elles ne doivent pas etre
        # prises pour des gestes, sinon on reecrit ce qu'on vient de lire.
        writes = []
        self.manager.layout_manager.persistRequested.connect(lambda: writes.append(1))
        self.manager.restore_session(
            {"instances": [{
                "instance_id": "dummy_001", "module_type": "dummy", "title": "D",
                "visible": False,
                "geometry": {"x": 33, "y": 44, "width": 500, "height": 400},
            }]}
        )
        self.assertFalse(self.manager.layout_manager.restoring_session)
        self.assertEqual(writes, [])

    def test_a_restored_geometry_survives_the_restoration(self):
        self.manager.restore_session(
            {"instances": [{
                "instance_id": "dummy_001", "module_type": "dummy", "title": "D",
                "visible": False,
                "geometry": {"x": 33, "y": 44, "width": 500, "height": 400},
            }]}
        )
        instance = self.manager.get_instance("dummy_001")
        self.assertEqual(instance.geometry["x"], 33)

    def test_an_old_format_session_restores_without_error(self):
        # Retro-compatibilite : pas de screen_name ni de relative.
        self.manager.restore_session(
            {"instances": [{
                "instance_id": "dummy_002", "module_type": "dummy", "title": "D",
                "visible": False,
                "geometry": {"x": 10, "y": 10, "width": 300, "height": 200},
            }]}
        )
        self.assertIsNotNone(self.manager.get_instance("dummy_002"))


class RegisteredWindowTests(unittest.TestCase):
    def test_defaults_are_the_common_case(self):
        entry = RegisteredWindow(window_id="w", window=object())
        self.assertTrue(entry.participates_as_source)
        self.assertTrue(entry.participates_as_target)
        self.assertTrue(entry.managed_by_window_manager)
        self.assertIsNone(entry.module_type)


if __name__ == "__main__":
    unittest.main()
