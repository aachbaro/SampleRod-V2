from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from backend.services.library_service import LibraryScope, LibraryService


class _FakeSampleStore:
    def __init__(self, samples):
        self._samples = list(samples)

    def get_cached(self):
        return list(self._samples)


class _FakeSettings:
    def __init__(self, libraries):
        self.libraries = libraries


class LibraryServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.library_root = os.path.join(self._tmpdir.name, "Drums")
        self.external_root = os.path.join(self._tmpdir.name, "External")
        os.makedirs(os.path.join(self.library_root, "Kits"), exist_ok=True)
        os.makedirs(self.external_root, exist_ok=True)

        self.samples = [
            self._sample(
                1,
                os.path.join(self.library_root, "Kits", "kick.wav"),
                missing=False,
                needs_analysis=True,
                rms_level=0.123,
            ),
            self._sample(
                2,
                os.path.join(self.library_root, "snare.wav"),
                missing=False,
                needs_analysis=False,
                rms_level=0.321,
            ),
            self._sample(
                3,
                os.path.join(self.external_root, "texture.wav"),
                missing=True,
                needs_analysis=False,
                rms_level=None,
            ),
        ]
        self.service = LibraryService(
            _FakeSettings([SimpleNamespace(path=self.library_root, position=0)]),
            _FakeSampleStore(self.samples),
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_build_navigation_groups_samples_by_library_and_external(self):
        nodes = self.service.build_navigation(self.samples)

        self.assertEqual(nodes[0].label, "Toute la bibliotheque")
        self.assertEqual(nodes[0].sample_count, 3)
        self.assertEqual(nodes[1].label, "Drums")
        self.assertEqual(nodes[1].sample_count, 2)
        self.assertEqual(nodes[1].children[0].label, "Kits")
        self.assertEqual(nodes[1].children[0].sample_count, 1)
        self.assertEqual(nodes[2].label, "Externes")
        self.assertEqual(nodes[2].sample_count, 1)

    def test_filter_samples_by_status_and_scope(self):
        pending = self.service.filter_samples(
            self.samples,
            scope=LibraryScope("all"),
            status_filter=LibraryService.STATUS_PENDING,
        )
        self.assertEqual([sample.id for sample in pending], [1])

        missing = self.service.filter_samples(
            self.samples,
            scope=LibraryScope("external"),
            status_filter=LibraryService.STATUS_MISSING,
        )
        self.assertEqual([sample.id for sample in missing], [3])

        folder_scope = LibraryScope("folder", os.path.join(self.library_root, "Kits"))
        scoped = self.service.filter_samples(self.samples, scope=folder_scope)
        self.assertEqual([sample.id for sample in scoped], [1])

    def test_descriptive_helpers_return_readable_labels(self):
        kick = self.samples[0]
        external = self.samples[2]

        self.assertEqual(self.service.get_root_label(kick), "Drums")
        self.assertEqual(self.service.get_folder_label(kick), "Kits")
        self.assertEqual(self.service.get_status_label(kick), "A analyser")
        self.assertEqual(self.service.format_duration(kick), "1.5s")
        self.assertEqual(self.service.format_rms(kick), "0.123")
        self.assertEqual(self.service.get_status_label(external), "Fichier manquant")
        self.assertEqual(self.service.get_root_label(external), "Externes")

    def _sample(self, sample_id: int, path: str, *, missing: bool, needs_analysis: bool, rms_level):
        return SimpleNamespace(
            id=sample_id,
            name=os.path.splitext(os.path.basename(path))[0],
            path=os.path.abspath(path),
            duration=1.5,
            rms_level=rms_level,
            missing=missing,
            needs_analysis=needs_analysis,
        )


if __name__ == "__main__":
    unittest.main()
