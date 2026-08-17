"""Cycle d'interaction : debut et fin du geste utilisateur.

Le decodage Win32 est PUR : il se teste avec de simples entiers, sans Windows.
Le reste verifie surtout la PASSIVITE — cette couche observe, elle n'agit pas.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from frontend.modular.layout.move_lifecycle import (
    FALLBACK_IDLE_MS,
    WM_ENTERSIZEMOVE,
    WM_EXITSIZEMOVE,
    WM_MOVING,
    WM_SIZING,
    InteractionPhase,
    TimerInteractionWatcher,
    Win32InteractionWatcher,
    create_interaction_watcher,
    decode_win32_message,
)

_app = QApplication.instance() or QApplication([])


class DecodeTests(unittest.TestCase):
    """Traduction pure d'un identifiant de message en phase."""

    def test_enter_size_move_starts_the_gesture(self):
        self.assertIs(decode_win32_message(WM_ENTERSIZEMOVE), InteractionPhase.START)

    def test_exit_size_move_ends_the_gesture(self):
        self.assertIs(decode_win32_message(WM_EXITSIZEMOVE), InteractionPhase.END)

    def test_wm_moving_is_deliberately_ignored(self):
        # Le traiter supposerait un snap continu, qui lutterait contre la
        # boucle modale de Windows. On ne le fait pas : c'est un choix.
        self.assertIsNone(decode_win32_message(WM_MOVING))

    def test_wm_sizing_is_deliberately_ignored(self):
        self.assertIsNone(decode_win32_message(WM_SIZING))

    def test_any_other_message_is_ignored(self):
        for msg_id in (0x0000, 0x0001, 0x0200, 0x0100, 0xFFFF):
            self.assertIsNone(decode_win32_message(msg_id))

    def test_the_constants_are_the_official_win32_values(self):
        self.assertEqual(WM_SIZING, 0x0214)
        self.assertEqual(WM_MOVING, 0x0216)
        self.assertEqual(WM_ENTERSIZEMOVE, 0x0231)
        self.assertEqual(WM_EXITSIZEMOVE, 0x0232)


class _FakeMessage:
    """Doublure d'un MSG Win32 : expose directement son identifiant."""

    def __init__(self, message):
        self.message = message


class Win32WatcherTests(unittest.TestCase):
    def setUp(self):
        self.watcher = Win32InteractionWatcher("w")
        self.started: list[str] = []
        self.finished: list[str] = []
        self.watcher.interactionStarted.connect(self.started.append)
        self.watcher.interactionFinished.connect(self.finished.append)

    def _send(self, msg_id):
        return self.watcher.handle_native(b"windows_generic_MSG", _FakeMessage(msg_id))

    def test_a_full_gesture_emits_start_then_end(self):
        self._send(WM_ENTERSIZEMOVE)
        self._send(WM_MOVING)
        self._send(WM_MOVING)
        self._send(WM_EXITSIZEMOVE)
        self.assertEqual(self.started, ["w"])
        self.assertEqual(self.finished, ["w"])

    def test_nothing_is_emitted_before_the_gesture_ends(self):
        self._send(WM_ENTERSIZEMOVE)
        for _ in range(20):
            self._send(WM_MOVING)
        self.assertEqual(self.finished, [], "un snap se serait applique en plein drag")

    def test_the_event_is_never_consumed(self):
        # Consommer l'evenement priverait Qt et l'OS du message : la fenetre
        # cesserait de se comporter normalement.
        for msg_id in (WM_ENTERSIZEMOVE, WM_MOVING, WM_SIZING, WM_EXITSIZEMOVE, 0x1234):
            self.assertFalse(self._send(msg_id))

    def test_a_second_start_does_not_re_emit(self):
        self._send(WM_ENTERSIZEMOVE)
        self._send(WM_ENTERSIZEMOVE)
        self.assertEqual(self.started, ["w"])

    def test_an_end_without_a_start_emits_nothing(self):
        self._send(WM_EXITSIZEMOVE)
        self.assertEqual(self.finished, [])

    def test_two_gestures_in_a_row(self):
        for _ in range(2):
            self._send(WM_ENTERSIZEMOVE)
            self._send(WM_EXITSIZEMOVE)
        self.assertEqual(self.started, ["w", "w"])
        self.assertEqual(self.finished, ["w", "w"])

    def test_the_interacting_flag_follows_the_gesture(self):
        self.assertFalse(self.watcher.is_interacting)
        self._send(WM_ENTERSIZEMOVE)
        self.assertTrue(self.watcher.is_interacting)
        self._send(WM_EXITSIZEMOVE)
        self.assertFalse(self.watcher.is_interacting)

    def test_an_undecodable_message_is_harmless(self):
        self.assertFalse(self.watcher.handle_native(b"x", None))
        self.assertEqual(self.started, [])

    def test_geometry_events_alone_start_nothing(self):
        # Sous Windows, seul le cycle natif fait foi : un moveEvent isole
        # (setGeometry programmatique) ne doit pas ouvrir de geste.
        self.watcher.on_geometry_event()
        self.assertEqual(self.started, [])
        self.assertFalse(self.watcher.is_interacting)


class FallbackWatcherTests(unittest.TestCase):
    """Le fallback detecte une INACTIVITE, pas un relachement de bouton.

    C'est une difference de nature, et la raison pour laquelle il n'est jamais
    choisi sous Windows : maintenir le clic sans bouger declencherait une fin
    prematuree.
    """

    def setUp(self):
        self.watcher = TimerInteractionWatcher("w", idle_ms=30)
        self.started: list[str] = []
        self.finished: list[str] = []
        self.watcher.interactionStarted.connect(self.started.append)
        self.watcher.interactionFinished.connect(self.finished.append)

    def _wait(self, ms):
        loop_over = []
        QTimer.singleShot(ms, lambda: loop_over.append(True))
        while not loop_over:
            _app.processEvents()

    def test_the_first_geometry_event_starts_the_gesture(self):
        self.watcher.on_geometry_event()
        self.assertEqual(self.started, ["w"])

    def test_close_together_events_keep_restarting_the_timer(self):
        for _ in range(5):
            self.watcher.on_geometry_event()
            self._wait(10)          # bien en dessous des 30 ms d'inactivite
        self.assertEqual(self.started, ["w"])
        self.assertEqual(self.finished, [], "fin prematuree pendant le mouvement")

    def test_enough_inactivity_ends_the_gesture_once(self):
        self.watcher.on_geometry_event()
        self._wait(80)
        self.assertEqual(self.finished, ["w"])

    def test_a_later_move_opens_a_brand_new_cycle(self):
        self.watcher.on_geometry_event()
        self._wait(80)
        self.watcher.on_geometry_event()
        self._wait(80)
        self.assertEqual(self.started, ["w", "w"])
        self.assertEqual(self.finished, ["w", "w"])

    def test_it_ignores_native_messages_entirely(self):
        self.assertFalse(
            self.watcher.handle_native(b"windows_generic_MSG", _FakeMessage(WM_ENTERSIZEMOVE))
        )
        self.assertEqual(self.started, [])

    def test_the_default_idle_delay_is_exposed(self):
        self.assertGreater(FALLBACK_IDLE_MS, 0)


@unittest.skipUnless(sys.platform.startswith("win"), "structure MSG propre a Windows")
class RealMsgDecodingTests(unittest.TestCase):
    """Decodage d'une VRAIE structure MSG, telle que Qt la transmet.

    C'est le seul endroit fragile de la couche native : si la disposition des
    champs etait fausse, on lirait n'importe quoi. Les doublures a attribut
    `.message` ne le verifient pas.
    """

    def _real_msg_address(self, message_id):
        import ctypes
        from ctypes import wintypes

        class _MSG(ctypes.Structure):
            _fields_ = [
                ("hWnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG),
            ]

        msg = _MSG()
        msg.message = message_id
        self._keep = getattr(self, "_keep", [])
        self._keep.append(msg)          # garder en vie pendant la lecture
        return ctypes.addressof(msg)

    def test_a_real_msg_pointer_is_decoded(self):
        from frontend.modular.layout.move_lifecycle import _win32_message_id

        for msg_id in (WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE, WM_MOVING, WM_SIZING):
            with self.subTest(msg_id=hex(msg_id)):
                address = self._real_msg_address(msg_id)
                self.assertEqual(_win32_message_id(address), msg_id)

    def test_a_full_gesture_through_real_pointers(self):
        watcher = Win32InteractionWatcher("w")
        started, finished = [], []
        watcher.interactionStarted.connect(started.append)
        watcher.interactionFinished.connect(finished.append)

        watcher.handle_native(b"windows_generic_MSG", self._real_msg_address(WM_ENTERSIZEMOVE))
        watcher.handle_native(b"windows_generic_MSG", self._real_msg_address(WM_MOVING))
        self.assertEqual(finished, [], "fin declenchee en plein drag")
        watcher.handle_native(b"windows_generic_MSG", self._real_msg_address(WM_EXITSIZEMOVE))

        self.assertEqual(started, ["w"])
        self.assertEqual(finished, ["w"])

    def test_a_bogus_pointer_is_survivable(self):
        from frontend.modular.layout.move_lifecycle import _win32_message_id

        # Ne doit pas faire tomber le processus : on renvoie None ou un entier,
        # mais on ne laisse jamais remonter d'exception.
        try:
            _win32_message_id(0)
        except Exception as exc:  # pragma: no cover
            self.fail(f"une exception a remonte : {exc}")


class WatcherSelectionTests(unittest.TestCase):
    def test_windows_gets_the_native_watcher(self):
        with mock.patch.object(sys, "platform", "win32"):
            watcher = create_interaction_watcher("w")
        self.assertIsInstance(watcher, Win32InteractionWatcher)

    def test_the_fallback_is_never_selected_on_windows(self):
        with mock.patch.object(sys, "platform", "win32"):
            watcher = create_interaction_watcher("w")
        self.assertNotIsInstance(watcher, TimerInteractionWatcher)

    def test_other_platforms_get_the_fallback(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                with mock.patch.object(sys, "platform", platform):
                    watcher = create_interaction_watcher("w")
                self.assertIsInstance(watcher, TimerInteractionWatcher)

    def test_the_implementation_can_be_forced_for_tests(self):
        watcher = create_interaction_watcher("w", force=TimerInteractionWatcher)
        self.assertIsInstance(watcher, TimerInteractionWatcher)

    def test_the_watcher_keeps_its_window_id(self):
        self.assertEqual(create_interaction_watcher("waveform_007").window_id, "waveform_007")


if __name__ == "__main__":
    unittest.main()
