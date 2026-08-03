from __future__ import annotations

import pickle
import unittest

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from frontend.sample_gui.waveform.waveform_region import WaveformRegionController

_SR = 44100


class _Region:
    def __init__(self, start: float, end: float):
        self._bounds = (start, end)

    def getRegion(self):  # noqa: N802 (API pyqtgraph)
        return self._bounds


class _MarkerManager:
    """Reprend le vrai calcul de payload sans construire toute la waveform."""

    def __init__(self, widget):
        self.widget = widget

    def selection_payload(self):
        region = getattr(self.widget, "region", None)
        if region is None:
            return None
        start, end = region.getRegion()
        if end <= start:
            return None
        data = self.widget.waveform_data
        s0, s1 = int(start * _SR), int(end * _SR)
        return {
            "time": float(start),
            "end_time": float(end),
            "audio_data": data[s0:s1].astype("float32"),
            "sample_rate": _SR,
            "name": "break.wav",
        }


class _Widget:
    """Waveform reduite aux attributs que touche le controleur de region."""

    def __init__(self, data: np.ndarray | None = None, region: _Region | None = None):
        self.waveform_data = data
        self.sample_rate = _SR
        self.duration = 0.0 if data is None else len(data) / _SR
        self.audio_file_path = "C:/tmp/break.wav"
        self.region = region
        self._selection_drag_armed = False
        self._selection_drag_origin = None
        self.marker_manager = _MarkerManager(self)


class SelectionDragTests(unittest.TestCase):
    """Ctrl+double-clic puis glisser doit partir en drag de la slice, avec le
    meme MIME que depuis la liste de marqueurs."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        audio = np.linspace(-1.0, 1.0, _SR, dtype="float32")
        self.widget = _Widget(audio, _Region(0.25, 0.75))
        self.controller = WaveformRegionController(self.widget, _Region)
        self.started: list[bool] = []
        # On n'ouvre pas de vrai QDrag (bloquant) : on observe la decision.
        self.controller.start_selection_drag = lambda: (self.started.append(True) or True)

    def test_arming_records_the_press_position(self):
        self.controller.arm_selection_drag(QPointF(10.0, 20.0))
        self.assertTrue(self.widget._selection_drag_armed)
        self.assertEqual(self.widget._selection_drag_origin, QPointF(10.0, 20.0))

    def test_small_movement_does_not_start_a_drag(self):
        self.controller.arm_selection_drag(QPointF(10.0, 20.0))
        self.assertFalse(self.controller.maybe_start_selection_drag(QPointF(11.0, 20.0)))
        self.assertEqual(self.started, [])
        # Toujours arme : l'utilisateur peut encore aller plus loin.
        self.assertTrue(self.widget._selection_drag_armed)

    def test_movement_past_the_threshold_starts_the_drag(self):
        self.controller.arm_selection_drag(QPointF(10.0, 20.0))
        far = QPointF(10.0 + QApplication.startDragDistance() + 5, 20.0)
        self.assertTrue(self.controller.maybe_start_selection_drag(far))
        self.assertEqual(self.started, [True])
        # Desarme : un seul drag par geste.
        self.assertFalse(self.widget._selection_drag_armed)

    def test_movement_without_arming_is_ignored(self):
        self.assertFalse(self.controller.maybe_start_selection_drag(QPointF(500.0, 20.0)))
        self.assertEqual(self.started, [])

    def test_disarming_cancels_the_gesture(self):
        self.controller.arm_selection_drag(QPointF(10.0, 20.0))
        self.controller.disarm_selection_drag()
        far = QPointF(10.0 + QApplication.startDragDistance() + 5, 20.0)
        self.assertFalse(self.controller.maybe_start_selection_drag(far))
        self.assertEqual(self.started, [])


class SelectionDragPayloadTests(unittest.TestCase):
    """Le contenu transporte doit etre exactement la slice selectionnee."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_payload_matches_the_selected_region(self):
        audio = np.linspace(-1.0, 1.0, _SR, dtype="float32")
        widget = _Widget(audio, _Region(0.25, 0.75))
        payload = widget.marker_manager.selection_payload()
        expected = audio[int(0.25 * _SR): int(0.75 * _SR)]
        np.testing.assert_array_equal(payload["audio_data"], expected)
        self.assertEqual(payload["sample_rate"], _SR)

    def test_mime_round_trip_is_readable_by_the_labo(self):
        # Le Labo relit ce format via pickle (cf. bins_panel._MIME_SLICE).
        audio = np.linspace(-1.0, 1.0, _SR, dtype="float32")
        widget = _Widget(audio, _Region(0.1, 0.2))
        payload = widget.marker_manager.selection_payload()
        blob = pickle.dumps(
            {
                "audio_data": payload["audio_data"],
                "sample_rate": payload["sample_rate"],
                "name": payload["name"],
            }
        )
        restored = pickle.loads(blob)
        self.assertEqual(restored["sample_rate"], _SR)
        self.assertEqual(restored["name"], "break.wav")
        np.testing.assert_array_equal(restored["audio_data"], payload["audio_data"])

    def test_no_region_means_no_drag(self):
        widget = _Widget(np.zeros(_SR, dtype="float32"), region=None)
        controller = WaveformRegionController(widget, _Region)
        self.assertFalse(controller.start_selection_drag())

    def test_empty_selection_means_no_drag(self):
        widget = _Widget(np.zeros(_SR, dtype="float32"), _Region(0.5, 0.5))
        controller = WaveformRegionController(widget, _Region)
        self.assertFalse(controller.start_selection_drag())


if __name__ == "__main__":
    unittest.main()
