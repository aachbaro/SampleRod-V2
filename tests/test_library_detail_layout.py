from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from frontend.library_gui import library_ui
from frontend.library_gui.library_detail import LibraryDetailWidget

_LONG_PATH = r"C:\Users\adama\Desktop\musique\Productions\Live\un_nom_de_fichier_vraiment_tres_long.wav"


class _Signal:
    def connect(self, *_args, **_kwargs) -> None:
        pass


class _Store:
    def __getattr__(self, _name):
        return _Signal()


class _Ctx:
    sample_store = _Store()


class LibraryDetailLayoutTests(unittest.TestCase):
    """Le detail passe sous la table : la liste recupere toute la largeur et
    la bande de detail se limite a quelques infos plus la carte de lecture."""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.addCleanup(self.host.deleteLater)
        self.host.detail_widget = LibraryDetailWidget(_Ctx())
        library_ui.build_library_widget_ui(self.host)
        self.host.resize(1200, 800)
        self.host.show()
        self._app.processEvents()
        self.addCleanup(self.host.hide)

    def test_detail_sits_below_the_table_not_beside_it(self):
        self.assertEqual(self.host.content_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertGreater(self.host.detail_widget.y(), self.host.table_panel.y())

    def test_table_uses_the_full_content_width(self):
        self.assertEqual(self.host.table_panel.width(), self.host.detail_widget.width())
        # Avant, le detail prenait ~460 px sur 1200 : la table doit desormais
        # occuper largement plus de la moitie de la fenetre.
        self.assertGreater(self.host.table_panel.width(), self.host.width() * 0.6)

    def test_detail_strip_stays_compact(self):
        self.assertLess(self.host.detail_widget.height(), 260)

    def test_main_splitter_has_only_navigation_and_content(self):
        self.assertEqual(self.host.splitter.count(), 2)

    def test_redundant_action_buttons_are_gone(self):
        detail = self.host.detail_widget
        self.assertFalse(hasattr(detail, "open_folder_button"))
        self.assertFalse(hasattr(detail, "toggle_waveform_button"))
        # Les actions restent joignables : elles vivent dans le menu contextuel
        # de la table et sur le double-clic.
        self.assertTrue(callable(detail.open_current_folder))
        self.assertTrue(callable(detail.toggle_waveform))


class ElidedLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_long_path_is_elided_but_kept_whole_in_the_tooltip(self):
        detail = LibraryDetailWidget(_Ctx())
        self.addCleanup(detail.deleteLater)
        detail.path_label.setFixedWidth(180)
        detail.path_label.set_full_text(_LONG_PATH)
        self.assertNotEqual(detail.path_label.text(), _LONG_PATH)
        self.assertIn("…", detail.path_label.text())
        self.assertEqual(detail.path_label.toolTip(), _LONG_PATH)

    def test_short_text_is_left_untouched(self):
        detail = LibraryDetailWidget(_Ctx())
        self.addCleanup(detail.deleteLater)
        detail.path_label.setFixedWidth(600)
        detail.path_label.set_full_text("court.wav")
        self.assertEqual(detail.path_label.text(), "court.wav")


if __name__ == "__main__":
    unittest.main()
