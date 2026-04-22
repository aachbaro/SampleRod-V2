from __future__ import annotations

import os
import pickle
import unittest

from PySide6.QtCore import QMimeData, QUrl

from frontend.labo.waveform_tool_dnd import (
    has_supported_waveform_drop,
    resolve_waveform_drop_paths,
)


class WaveformToolDnDTests(unittest.TestCase):
    def test_resolve_waveform_drop_paths_prefers_audio_urls(self):
        mime = QMimeData()
        audio_path = os.path.abspath("kick.wav")
        text_path = os.path.abspath("notes.txt")
        mime.setUrls(
            [
                QUrl.fromLocalFile(audio_path),
                QUrl.fromLocalFile(text_path),
            ]
        )
        mime.setData(
            "application/x-sample-card",
            pickle.dumps({"sample_id": 42}),
        )

        original_isfile = os.path.isfile
        try:
            os.path.isfile = lambda path: os.path.normpath(path) == os.path.normpath(audio_path)
            self.assertTrue(has_supported_waveform_drop(mime))
            self.assertEqual(
                resolve_waveform_drop_paths(mime, sample_path_lookup=lambda _sample_id: None),
                [os.path.normpath(audio_path)],
            )
        finally:
            os.path.isfile = original_isfile

    def test_resolve_waveform_drop_paths_uses_sample_card_lookup(self):
        mime = QMimeData()
        sample_path = os.path.abspath("snare.wav")
        mime.setData(
            "application/x-sample-card",
            pickle.dumps({"sample_id": 7}),
        )

        original_isfile = os.path.isfile
        try:
            os.path.isfile = lambda path: os.path.normpath(path) == os.path.normpath(sample_path)
            self.assertTrue(has_supported_waveform_drop(mime))
            self.assertEqual(
                resolve_waveform_drop_paths(
                    mime,
                    sample_path_lookup=lambda sample_id: sample_path if sample_id == 7 else None,
                ),
                [os.path.normpath(sample_path)],
            )
        finally:
            os.path.isfile = original_isfile


if __name__ == "__main__":
    unittest.main()
