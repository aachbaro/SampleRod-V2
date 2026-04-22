from __future__ import annotations

import os
import unittest

from PySide6.QtCore import QMimeData, QUrl

from frontend.right_panel.composer.composer_dnd import (
    has_audio_file_urls,
    parse_audio_file_urls,
)


class ComposerDnDTests(unittest.TestCase):
    def test_parse_audio_file_urls_keeps_only_local_audio_files(self):
        mime = QMimeData()
        audio_path = os.path.abspath("kick.wav")
        text_path = os.path.abspath("notes.txt")
        mime.setUrls(
            [
                QUrl.fromLocalFile(audio_path),
                QUrl.fromLocalFile(text_path),
            ]
        )

        self.assertTrue(has_audio_file_urls(mime))
        self.assertEqual(parse_audio_file_urls(mime), [os.path.normpath(audio_path)])


if __name__ == "__main__":
    unittest.main()
