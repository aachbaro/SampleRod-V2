from __future__ import annotations

import os
import pickle
import tempfile
import unittest

from PySide6.QtCore import QMimeData, QSettings, QUrl
from PySide6.QtWidgets import QApplication

from frontend.labo.bins_panel import (
    LaboBin,
    LaboBinsPanel,
    _compact_label,
    _dropped_folders,
    _has_supported_bin_drop,
)


class _DummySampleStore:
    def __init__(self):
        self.moves = []

    def get_cached(self):
        return []

    def move(self, sample_id: int, target_folder: str):
        self.moves.append((sample_id, target_folder))


class _DummyAppContext:
    def __init__(self):
        self.sample_store = _DummySampleStore()


class LaboBinsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_accepts_sample_card_drop(self):
        mime = QMimeData()
        mime.setData(
            "application/x-sample-card",
            pickle.dumps({"sample_id": 12}),
        )
        self.assertTrue(_has_supported_bin_drop(mime))

    def test_accepts_audio_file_urls(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(os.path.abspath("kick.wav"))])
        self.assertTrue(_has_supported_bin_drop(mime))

    def test_compact_label_shortens_long_names(self):
        self.assertEqual(_compact_label("Drums"), "Drums")
        self.assertTrue(_compact_label("Very long folder label for sorting").endswith("..."))

    def test_untracked_file_drop_moves_file_without_global_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            dst_dir = os.path.join(tmpdir, "dst")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(dst_dir, exist_ok=True)

            src_path = os.path.join(src_dir, "kick.wav")
            with open(src_path, "wb") as handle:
                handle.write(b"fake")

            settings = QSettings(os.path.join(tmpdir, "bins.ini"), QSettings.Format.IniFormat)
            panel = LaboBinsPanel(_DummyAppContext(), settings)
            panel._bins = [LaboBin(bin_id="bin-1", label="Dst", path=dst_dir)]

            moved_payloads = []
            refresh_events = []
            panel.sourcePathsMoved.connect(lambda paths: moved_payloads.append(list(paths)))
            panel.reserveRefreshRequested.connect(lambda: refresh_events.append(True))

            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(src_path)])
            panel._on_move_here_requested("bin-1", mime)

            self.assertFalse(os.path.exists(src_path))
            self.assertTrue(os.path.exists(os.path.join(dst_dir, "kick.wav")))
            self.assertEqual(moved_payloads, [[os.path.abspath(src_path)]])
            self.assertEqual(refresh_events, [])


    def test_folder_drop_is_detected_for_bin_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(tmpdir)])
            self.assertEqual(_dropped_folders(mime), [os.path.normpath(tmpdir)])
            # Un dossier n'est pas un depot "matiere" : il ne doit pas
            # declencher un deplacement sur un chip.
            self.assertFalse(_has_supported_bin_drop(mime))

    def test_chips_reflow_from_column_to_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = QSettings(os.path.join(tmpdir, "bins.ini"), QSettings.Format.IniFormat)
            panel = LaboBinsPanel(_DummyAppContext(), settings)
            panel._bins = [
                LaboBin(bin_id=f"bin-{index}", label=label, path=tmpdir)
                for index, label in enumerate(["drums", "voices", "synth", "archive"])
            ]
            panel._rebuild()
            panel.show()

            def columns_at(width: int) -> int:
                panel.resize(width, 320)
                self._app.processEvents()
                rows: dict[int, int] = {}
                for chip in panel._chip_widgets.values():
                    rows[chip.y()] = rows.get(chip.y(), 0) + 1
                return max(rows.values())

            self.assertEqual(columns_at(144), 1)
            self.assertGreater(columns_at(560), 1)
            panel.hide()


if __name__ == "__main__":
    unittest.main()
