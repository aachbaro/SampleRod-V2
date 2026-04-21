from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt  # noqa: F401

from frontend.sample_gui.waveform.history_stack import HistoryStack
from frontend.sample_gui.waveform import waveform_playback, waveform_region


class _FakeSignal:
    def __init__(self) -> None:
        self.values: list[object] = []

    def emit(self, value=None) -> None:
        self.values.append(value)


class _FakeTimer:
    def __init__(self) -> None:
        self.started: list[int] = []
        self.stop_calls = 0

    def start(self, interval: int) -> None:
        self.started.append(int(interval))

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeSounddevice:
    class CallbackStop(Exception):
        pass

    class _Stream:
        def __init__(self, **kwargs) -> None:
            self.callback = kwargs["callback"]
            self.active = False
            self.closed = False

        def start(self) -> None:
            self.active = True

        def stop(self) -> None:
            self.active = False

        def close(self) -> None:
            self.active = False
            self.closed = True

    def __init__(self) -> None:
        self.streams: list[_FakeSounddevice._Stream] = []

    def OutputStream(self, **kwargs):
        stream = self._Stream(**kwargs)
        self.streams.append(stream)
        return stream


class _FakeStatus:
    output_underflow = False


class _FakePlaybackWidget:
    def __init__(self, waveform_data: np.ndarray, *, sample_rate: int, loop_enabled: bool = False) -> None:
        self.waveform_data = waveform_data
        self.sample_rate = sample_rate
        self.duration = len(waveform_data) / sample_rate
        self.start_sample = 0
        self.current_time = 0.0
        self.is_playing = False
        self.loop_enabled = loop_enabled
        self.play_start = 0.0
        self.play_end = 0.0
        self.is_stereo = False
        self.stream = None
        self.timer = _FakeTimer()
        self.positionUpdated = _FakeSignal()
        self.stop_timer_signal = _FakeSignal()


class _FakeViewBox:
    def __init__(self) -> None:
        self.limits: dict[str, float] | None = None

    def setLimits(self, **kwargs) -> None:
        self.limits = {key: float(value) for key, value in kwargs.items()}


class _FakePlot:
    def __init__(self) -> None:
        self.view_box = _FakeViewBox()
        self.x_ranges: list[tuple[float, float, int]] = []
        self.removed_items: list[object] = []

    def getViewBox(self):
        return self.view_box

    def setXRange(self, start: float, end: float, padding: int = 0) -> None:
        self.x_ranges.append((float(start), float(end), int(padding)))

    def removeItem(self, item) -> None:
        self.removed_items.append(item)


class _FakeMarkerLine:
    def __init__(self, pos: float) -> None:
        self.positions = [float(pos)]

    def setPos(self, pos: float) -> None:
        self.positions.append(float(pos))


class _FakeReadHead:
    def __init__(self) -> None:
        self.positions: list[float] = []

    def setPos(self, pos: float) -> None:
        self.positions.append(float(pos))


class _FakeRegionWidget:
    def __init__(self) -> None:
        self.sample_rate = 100
        self.waveform_data = np.arange(200, dtype=np.float32)
        self.duration = len(self.waveform_data) / self.sample_rate
        self.plot = _FakePlot()
        self.markers = [0.2, 0.8, 1.5]
        self.marker_lines = {time_s: _FakeMarkerLine(time_s) for time_s in self.markers}
        self.current_marker_idx = 0
        self.read_head = _FakeReadHead()
        self.current_time = 1.2
        self.play_start = 0.5
        self.play_end = 1.4
        self.start_sample = 120
        self.is_playing = True
        self.stop_calls = 0
        self.refresh_calls = 0
        self.redraw_calls = 0

    def stop_audio(self) -> None:
        self.stop_calls += 1
        self.is_playing = False

    def _refresh_marker_list(self) -> None:
        self.refresh_calls += 1

    def _redraw_all(self) -> None:
        self.redraw_calls += 1


class WaveformPlaybackControllerTests(unittest.TestCase):
    def test_loop_callback_survives_waveform_shrink_after_cut(self) -> None:
        fake_sd = _FakeSounddevice()
        widget = _FakePlaybackWidget(np.linspace(-1.0, 1.0, 2000, dtype=np.float32), sample_rate=1000, loop_enabled=True)
        controller = waveform_playback.WaveformPlaybackController(widget)

        with mock.patch.object(waveform_playback, "sd", fake_sd):
            controller.play_audio(1.5)
            stream = fake_sd.streams[-1]

            widget.waveform_data = np.linspace(-0.5, 0.5, 100, dtype=np.float32)
            widget.duration = len(widget.waveform_data) / widget.sample_rate
            widget.start_sample = 133907
            outdata = np.zeros((64, 1), dtype=np.float32)

            stream.callback(outdata, 64, None, _FakeStatus())

        self.assertEqual(outdata.shape, (64, 1))
        self.assertFalse(np.isnan(outdata).any())
        self.assertGreaterEqual(widget.start_sample, 0)
        self.assertLess(widget.start_sample, len(widget.waveform_data))
        self.assertTrue(widget.positionUpdated.values)

    def test_loop_callback_stops_cleanly_when_buffer_is_empty(self) -> None:
        fake_sd = _FakeSounddevice()
        widget = _FakePlaybackWidget(np.linspace(-1.0, 1.0, 256, dtype=np.float32), sample_rate=1000, loop_enabled=True)
        controller = waveform_playback.WaveformPlaybackController(widget)

        with mock.patch.object(waveform_playback, "sd", fake_sd):
            controller.play_audio(0.0)
            stream = fake_sd.streams[-1]
            widget.waveform_data = np.array([], dtype=np.float32)
            outdata = np.ones((32, 1), dtype=np.float32)

            with self.assertRaises(fake_sd.CallbackStop):
                stream.callback(outdata, 32, None, _FakeStatus())

        self.assertFalse(widget.is_playing)
        self.assertTrue(np.all(outdata == 0))


class WaveformRegionControllerTests(unittest.TestCase):
    def test_cut_stops_playback_before_mutating_waveform(self) -> None:
        widget = _FakeRegionWidget()
        controller = waveform_region.WaveformRegionController(widget, region_cls=None)

        removed, removed_markers, shift = controller._do_cut(0.5, 1.0)

        self.assertEqual(widget.stop_calls, 1)
        self.assertFalse(widget.is_playing)
        self.assertEqual(widget.start_sample, 0)
        self.assertEqual(len(removed), 50)
        self.assertEqual(shift, 0.5)
        self.assertEqual(removed_markers, [0.8])
        self.assertEqual(widget.markers, [0.2, 1.0])
        self.assertEqual(len(widget.waveform_data), 150)
        self.assertEqual(widget.current_time, 0.0)
        self.assertEqual(widget.play_start, 0.0)
        self.assertEqual(widget.play_end, widget.duration)
        self.assertEqual(widget.read_head.positions[-1], 0.0)
        self.assertEqual(widget.refresh_calls, 1)
        self.assertEqual(widget.redraw_calls, 1)


class HistoryStackTests(unittest.TestCase):
    def test_push_is_bounded_to_max_commands(self) -> None:
        history = HistoryStack(max_commands=3)

        for index in range(5):
            history.push({"action": "cut", "index": index})

        self.assertEqual(len(history._commands), 3)
        self.assertEqual([command["index"] for command in history._commands], [2, 3, 4])
        self.assertEqual(history._index, 2)


if __name__ == "__main__":
    unittest.main()
