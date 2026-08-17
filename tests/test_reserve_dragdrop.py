import pickle
import unittest

import numpy as np
from PySide6.QtCore import QMimeData

from frontend.sample_gui.sample.sample_list_dragdrop import SampleListDragDrop


class _Store:
    def get_cached(self):
        return []


class _Context:
    lab_artifact_store = None


class _Widget:
    sample_store = _Store()
    app_context = _Context()


class ReserveDragDropTests(unittest.TestCase):
    def test_reserve_accepts_an_edited_waveform_selection(self):
        mime = QMimeData()
        mime.setData(
            "application/x-sample-slice-data",
            pickle.dumps({
                "audio_data": np.zeros(128, dtype="float32"),
                "sample_rate": 48_000,
                "name": "selection.wav",
            }),
        )

        self.assertTrue(SampleListDragDrop(_Widget())._accepts(mime))


if __name__ == "__main__":
    unittest.main()
