from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.services import temp_workspace


class TempWorkspaceTests(unittest.TestCase):
    """Les dossiers de travail ne doivent plus grossir indefiniment : chaque
    rendu de pattern ou apercu ecrivait un WAV que rien ne supprimait."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = patch.object(temp_workspace, "TEMP_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fill(self, name: str, count: int, *, age_s: float = 0.0) -> list[Path]:
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        created = []
        now = time.time()
        for index in range(count):
            path = folder / f"clip_{index:03d}.wav"
            path.write_bytes(b"x" * 16)
            # mtime croissant : clip_000 est le plus ancien.
            stamp = now - age_s - (count - index)
            os.utime(path, (stamp, stamp))
            created.append(path)
        return created

    def test_temp_dir_creates_the_folder(self):
        path = temp_workspace.temp_dir("break_pattern")
        self.assertTrue(path.is_dir())
        self.assertEqual(path.parent, self.root)

    def test_only_the_most_recent_files_survive(self):
        self._fill("break_pattern", 50)
        removed = temp_workspace.prune_temp_dir("break_pattern", keep_recent=10)
        remaining = sorted(p.name for p in (self.root / "break_pattern").iterdir())
        self.assertEqual(removed, 40)
        self.assertEqual(len(remaining), 10)
        # Ce sont bien les plus recents (les indices les plus hauts).
        self.assertEqual(remaining[0], "clip_040.wav")

    def test_a_protected_file_is_never_deleted(self):
        files = self._fill("break_pattern_segments", 20)
        oldest = files[0]
        removed = temp_workspace.prune_temp_dir(
            "break_pattern_segments", keep_recent=5, protect=(str(oldest),)
        )
        self.assertTrue(oldest.exists())
        self.assertEqual(removed, 14)

    def test_old_files_go_even_within_the_budget(self):
        self._fill("break_edits", 3, age_s=30 * 24 * 3600)  # un mois
        removed = temp_workspace.prune_temp_dir(
            "break_edits", keep_recent=100, max_age_s=7 * 24 * 3600
        )
        self.assertEqual(removed, 3)

    def test_recent_files_within_budget_are_kept(self):
        self._fill("break_edits", 3)
        removed = temp_workspace.prune_temp_dir("break_edits", keep_recent=100)
        self.assertEqual(removed, 0)

    def test_missing_folder_is_not_an_error(self):
        self.assertEqual(temp_workspace.prune_temp_dir("jamais_cree"), 0)

    def test_startup_sweep_covers_every_known_folder(self):
        self._fill("break_pattern", 60)
        self._fill("break_pattern_segments", 60)
        self._fill("break_preview", 30)
        report = temp_workspace.prune_all_workspaces()
        self.assertEqual(set(report), {"break_pattern", "break_pattern_segments", "break_preview"})
        self.assertEqual(report["break_pattern"], 30)   # budget 30
        self.assertEqual(report["break_preview"], 20)   # budget 10

    def test_startup_sweep_on_an_empty_root(self):
        self.assertEqual(temp_workspace.prune_all_workspaces(), {})

    def test_directories_inside_a_workspace_are_left_alone(self):
        folder = self.root / "stem_mix"
        folder.mkdir(parents=True)
        (folder / "sous_dossier").mkdir()
        self._fill("stem_mix", 40)
        temp_workspace.prune_temp_dir("stem_mix", keep_recent=5)
        self.assertTrue((folder / "sous_dossier").is_dir())


if __name__ == "__main__":
    unittest.main()
