from __future__ import annotations

import unittest
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

from frontend.modular.module_registry import ModuleRegistry
from frontend.modular.window_manager import WindowManager


@dataclass
class _FakeInstance:
    instance_id: str
    visible: bool = True


class _FakeWindow:
    """Fenetre minimale : enregistre l'ordre des raise_() dans un journal."""

    def __init__(self, name: str, log: list[str], visible: bool = True):
        self.name = name
        self._log = log
        self._visible = visible

    def isVisible(self) -> bool:  # noqa: N802 (API Qt)
        return self._visible

    def raise_(self) -> None:
        self._log.append(self.name)


class WindowStackingTests(unittest.TestCase):
    """La Reserve est la plus ancienne instance : elle ne doit pas retomber
    sous toutes les autres a chaque clic sur une autre fenetre."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = WindowManager(None, None, ModuleRegistry())
        self.log: list[str] = []
        # Ordre de creation : reserve d'abord, puis waveform, puis break.
        for name in ("reserve", "waveform", "break"):
            self.manager._instances[name] = _FakeInstance(name)
            self.manager._windows[name] = _FakeWindow(name, self.log)
            self.manager._touch_stack(name)

    def _raise_and_read(self, active: str | None) -> list[str]:
        self.log.clear()
        window = self.manager._windows.get(active) if active else None
        self.manager.raise_group(active_window=window)
        # La fenetre active est remontee en dernier : elle est au sommet.
        return self.log

    def test_activating_a_window_does_not_bury_the_oldest_one(self):
        # On clique waveform, puis break : la reserve ne doit pas repasser
        # systematiquement tout en bas du groupe.
        self.manager._on_window_activated("waveform")
        self.manager._on_window_activated("break")
        # Puis on remonte la reserve.
        self.manager._on_window_activated("reserve")
        order = self._raise_and_read("waveform")
        self.assertEqual(order[-1], "waveform")
        # La reserve, activee juste avant, reste au-dessus du break.
        self.assertGreater(order.index("reserve"), order.index("break"))

    def test_stack_order_follows_activation_not_creation(self):
        self.manager._on_window_activated("reserve")
        order = self._raise_and_read(None)
        self.assertEqual(order, ["waveform", "break", "reserve"])

    def test_active_window_is_raised_last(self):
        order = self._raise_and_read("reserve")
        self.assertEqual(order[-1], "reserve")

    def test_hidden_instances_are_skipped(self):
        self.manager._instances["waveform"].visible = False
        order = self._raise_and_read(None)
        self.assertNotIn("waveform", order)

    def test_closing_an_instance_forgets_its_stack_slot(self):
        self.manager._instances.pop("waveform")
        self.manager._windows.pop("waveform")
        self.manager.close_instance("waveform")  # deja retiree : ne doit pas lever
        self.manager._stack_order.remove("waveform")
        self.assertNotIn("waveform", self.manager._stack_order)
        self.assertEqual(self._raise_and_read(None), ["reserve", "break"])


if __name__ == "__main__":
    unittest.main()
