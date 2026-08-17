from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QCheckBox
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest

from frontend.reserve.reserve_preview import ReservePreviewController
from frontend.sample_gui.sample.sample_card import SampleCard
from frontend.sample_gui.sample.sample_list_pagination import SampleListPagination
from frontend.sample_gui.sample.sample_list_selection import SampleListSelection
from frontend.sample_gui.sample.sample_list_ui import SampleListUIBuilder
from frontend.sample_gui.sample.sample_list_cards import SampleListCards


class _Signal:
    def connect(self, *_args): pass


class _Player:
    def __init__(self):
        self.current_sample_id = -1
        self.current_sample_path = None
        self.current_sample_duration = 0
        self.is_playing = False
        self.is_paused = False
        self.position = 0
    def toggle_play(self, sid, path, duration):
        self.current_sample_id, self.current_sample_path = sid, path
        self.current_sample_duration = duration
        self.is_playing, self.is_paused = True, False
        return True
    def seek_position(self, sid, path, duration, position):
        self.toggle_play(sid, path, duration)
        self.position = position
        return True
    def get_position(self): return self.position
    def clear_audio(self): self.is_playing = False


class _Settings:
    libraries = []
    librariesChanged = _Signal()
    def getNormalizationLevel(self): return -16


class _UiHost(QWidget):
    def __init__(self):
        super().__init__()
        for name in (
            "onSelectAll", "onDeselectAll", "bulkRemoveFromHistory", "bulkDelete",
            "bulkMove", "bulkNormalize", "_prev_page", "_next_page",
        ):
            setattr(self, name, mock.Mock())


class RecentPhaseFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _card(self, *, missing=False, needs_analysis=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = os.path.join(temp.name, "recent.wav")
        if not missing:
            open(path, "wb").close()
        sample = SimpleNamespace(
            id=8, path=path, name="recent", duration=12.0,
            created_at=dt.datetime(2026, 1, 1), missing=missing,
            needs_analysis=needs_analysis, rms_level=None, dominant_note="C#",
            detected_scale_label="C# minor", detected_scale_kind="scale",
            scale_confidence=.8, compatible_scales=None, material_metadata_dict={},
        )
        player = _Player()
        store = SimpleNamespace(sampleRenamed=_Signal(), sampleMoved=_Signal())
        context = SimpleNamespace(
            settings=_Settings(), audio_player=player, sample_store=store,
        )
        context.reserve_preview = ReservePreviewController(player)
        card = SampleCard(sample, context)
        self.addCleanup(card.deleteLater)
        return card, context

    def test_card_is_single_line_compact_without_heavy_waveform(self):
        card, _ = self._card()
        card.resize(700, card.sizeHint().height())
        card.show(); self.app.processEvents()
        self.assertLessEqual(card.sizeHint().height(), 55)
        self.assertFalse(card.editor_container.isVisible())
        self.assertIsNone(card.wave_edition_widget)
        self.assertTrue(card.play_button.isVisibleTo(card))
        self.assertTrue(card.playback_slider.isVisibleTo(card))
        self.assertTrue(card.options_button.isVisibleTo(card))

    def test_active_card_observes_common_preview_and_progress(self):
        card, context = self._card()
        card.show(); self.app.processEvents()
        card.playback.toggle_play()
        context.reserve_preview.seek(card.playback._entry(), 3000)
        self.assertTrue(card.property("previewActive"))
        self.assertFalse(card.active_progress.isVisibleTo(card))
        self.assertEqual(card.active_progress.value(), 250)
        self.assertEqual(card.playback_slider.value(), 25)

    def test_slider_seek_starts_preview_from_clicked_position(self):
        card, context = self._card()
        card.playback_slider.sliderMoved.emit(50)
        self.assertTrue(context.reserve_preview.is_active(card.playback._entry()))
        self.assertEqual(context.audio_player.position, 6000)

    def test_missing_card_keeps_actions_but_disables_preview(self):
        card, _ = self._card(missing=True)
        self.assertFalse(card.play_button.isEnabled())
        self.assertEqual(card.status_label.text(), "Fichier manquant")
        menu_texts = [action.text() for action in card.options_menu.actions()]
        self.assertTrue(any("Désindexer" in text for text in menu_texts))
        self.assertTrue(any("Supprimer" in text for text in menu_texts))

    def test_normal_status_is_not_repeated_on_recent_card(self):
        card, _ = self._card()
        card.show(); self.app.processEvents()
        self.assertEqual(card.status_label.text(), "Normal")
        self.assertFalse(card.status_label.isVisibleTo(card))

    def test_narrow_card_preserves_checkbox_name_status_and_menu(self):
        card, _ = self._card(needs_analysis=True)
        card.sample.name = "un_nom_de_sample_particulièrement_long_pour_la_vue_récente"
        card.refresh_display()
        card.setFixedWidth(260)
        card.show(); self.app.processEvents()
        self.assertTrue(card.name_label.isVisibleTo(card))
        self.assertTrue(card.status_label.isVisibleTo(card))
        self.assertTrue(card.options_button.isVisibleTo(card))
        self.assertFalse(card.length_label.isVisibleTo(card))
        self.assertFalse(card.key_badge.isVisibleTo(card))
        self.assertIn("…", card.name_label.text())

    def test_page_selection_wording_and_contextual_bulk_bar(self):
        host = _UiHost()
        self.addCleanup(host.deleteLater)
        SampleListUIBuilder(host).build()
        self.assertIn("cette page", host.select_all_btn.toolTip())
        self.assertFalse(host.bulk_bar.isVisible())
        host.selected_ids = {1, 2}
        host._card_widgets = {1: object(), 2: object()}
        SampleListSelection(host).update_select_actions()
        self.assertTrue(host.bulk_bar.isVisibleTo(host))
        self.assertEqual(host.bulk_count_label.text(), "2 sélectionnés")

    def test_checkbox_does_not_activate_inspector_selection(self):
        card, _ = self._card()
        activated = mock.Mock()
        card.activated.connect(activated)
        card.show(); self.app.processEvents()
        card.interactions.set_checkbox_revealed(True)
        QTest.qWait(180)
        QTest.mouseClick(card.checkbox, Qt.MouseButton.LeftButton)
        self.assertTrue(card.checkbox.isChecked())
        activated.assert_not_called()

    def test_checkbox_appears_on_hover_and_stays_when_checked(self):
        card, _ = self._card()
        self.assertTrue(card.checkbox.isHidden())
        card.show(); self.app.processEvents()
        card.interactions.set_checkbox_revealed(True)
        QTest.qWait(180)
        self.assertTrue(card.checkbox.isVisibleTo(card))
        self.assertGreater(card.checkbox.maximumWidth(), 0)
        card.checkbox.setChecked(True)
        card.interactions.set_checkbox_revealed(False)
        QTest.qWait(180)
        self.assertTrue(card.checkbox.isVisibleTo(card))

    def test_hover_selection_and_preview_do_not_change_card_height(self):
        card, context = self._card()
        card.resize(700, card.sizeHint().height())
        card.show(); self.app.processEvents()
        initial_height = card.height()
        card.interactions.set_checkbox_revealed(True)
        QTest.qWait(180)
        card.checkbox.setChecked(True)
        card.playback.toggle_play()
        context.reserve_preview.seek(card.playback._entry(), 1000)
        self.app.processEvents()
        self.assertEqual(card.height(), initial_height)

    def test_pagination_uses_dense_range_and_last_page(self):
        label = SimpleNamespace(setText=mock.Mock())
        widget = SimpleNamespace(pagination_label=label)
        SampleListPagination(widget).update_label(51, 84, 84)
        label.setText.assert_called_once_with("51–84 / 84")

    def test_recorder_concat_controls_are_preserved(self):
        card, _ = self._card()
        card.setConcatCandidate(True, 7)
        self.assertFalse(card.concat_button.isHidden())
        self.assertFalse(card.concat_cancel_button.isHidden())
        self.assertEqual(card.concat_prev_id, 7)

    def test_large_cache_instantiates_at_most_fifty_cards(self):
        samples = [SimpleNamespace(id=i, path=f"C:/audio/{i}.wav") for i in range(5000)]
        class _Layout:
            def __init__(self): self.widgets = []
            def count(self): return len(self.widgets)
            def takeAt(self, _index): return SimpleNamespace(widget=lambda: self.widgets.pop(0))
            def removeWidget(self, _widget): pass
            def addWidget(self, widget): self.widgets.append(widget)
            def addStretch(self): self.widgets.append(None)
        layout = _Layout()
        widget = SimpleNamespace(
            get_filtered_samples=lambda: samples, filtered_samples=[], samples_per_page=50,
            current_page=1, _card_widgets={}, selected_ids=set(), content_layout=layout,
            sample_store=SimpleNamespace(
                get_concat_previous_id=lambda _sid: None,
                is_normalization_locked=lambda _sid: False,
            ),
            updatePaginationLabel=mock.Mock(), _pending_focus_sample_id=None,
            _current_sample_id=None, updateSelectActions=mock.Mock(), samples=samples,
            _compute_samples_signature=lambda values: len(values),
        )
        cards = SampleListCards(widget)
        cards._clear_concat_preview = mock.Mock()
        cards._build_card = mock.Mock(side_effect=lambda sample: SimpleNamespace(
            sample=sample, checkbox=SimpleNamespace(setChecked=mock.Mock())
        ))
        cards.refresh_list()
        self.assertEqual(cards._build_card.call_count, 50)
        self.assertEqual(len(widget._card_widgets), 50)

    def test_first_visible_page_is_built_in_cooperative_batches(self):
        samples = [SimpleNamespace(id=i, path=f"C:/audio/{i}.wav") for i in range(12)]
        content = QWidget()
        self.addCleanup(content.deleteLater)
        layout = QVBoxLayout(content)
        widget = SimpleNamespace(
            get_filtered_samples=lambda: samples,
            filtered_samples=[], samples_per_page=50, current_page=1,
            _card_widgets={}, selected_ids=set(), content_layout=layout,
            content_widget=content, isVisible=lambda: True,
            updatePaginationLabel=mock.Mock(), updateSelectActions=mock.Mock(),
            _pending_focus_sample_id=None, _current_sample_id=None,
            samples=samples, _compute_samples_signature=lambda values: len(values),
        )
        cards = SampleListCards(widget)
        cards._clear_concat_preview = mock.Mock()

        def make_card(sample):
            card = QWidget(content)
            card.sample = sample
            card.checkbox = QCheckBox(card)
            return card

        cards._build_card = mock.Mock(side_effect=make_card)
        callbacks = []
        with mock.patch.object(QTimer, "singleShot", side_effect=lambda _ms, cb: callbacks.append(cb)):
            cards.refresh_list()
            self.assertEqual(cards._build_card.call_count, 0)
            callbacks.pop(0)()
            self.assertEqual(cards._build_card.call_count, 4)
            callbacks.pop(0)()
            self.assertEqual(cards._build_card.call_count, 8)
            callbacks.pop(0)()

        self.assertEqual(cards._build_card.call_count, 12)
        self.assertFalse(cards._incremental_refresh_running)
        self.assertTrue(all(card.parent() is content for card in widget._card_widgets.values()))


if __name__ == "__main__":
    unittest.main()
