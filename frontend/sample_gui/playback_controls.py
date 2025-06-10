from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
import qtawesome as qta

from frontend.custom_widgets import CustomSlider
from backend.models.AppContext import AppContext
from backend.models.sample import Sample


def format_time(milliseconds: int) -> str:
    minutes = (milliseconds // 1000) // 60
    seconds = (milliseconds // 1000) % 60
    return f"{minutes:02}:{seconds:02}"


class PlaybackControls(QWidget):
    """Widget regroupant les contrôles de lecture d'un sample."""

    playSample = pyqtSignal(object)

    def __init__(self, sample: Sample, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.sample = sample
        self.app_context = app_context

        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.play_button = QPushButton()
        self.play_button.setFixedSize(30, 30)
        self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
        self.play_button.setToolTip("Lire")
        self.play_button.clicked.connect(self.togglePlay)
        layout.addWidget(self.play_button)

        self.playback_slider = CustomSlider(Qt.Orientation.Horizontal)
        self.playback_slider.setRange(0, 100)
        self.playback_slider.setValue(0)
        self.playback_slider.setFixedHeight(30)
        self.playback_slider.sliderMoved.connect(self.seekAudio)
        layout.addWidget(self.playback_slider)

        self.time_label = QLabel("00:00/00:00")
        self.time_label.setFixedSize(80, 30)
        self.time_label.setStyleSheet("font-size: 12px; color: #ffffff;")
        layout.addWidget(self.time_label)

        # Mise à jour initiale du slider
        self.updateSlider()

        # Style du slider
        self.playback_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #e2e2e2;
            }
            QSlider::groove:horizontal:add-page {
                background: #e2e2e2;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
        """)

    # ------------------------------------------------------------------
    #  API publique appelée par SampleCard
    # ------------------------------------------------------------------

    def togglePlay(self):
        self.playSample.emit(self.sample)
        is_playing = self.app_context.audio_player.toggle_play(
            self.sample.id,
            self.sample.path,
            self.sample.duration,
        )
        icon_name = 'fa5s.pause' if is_playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
        if is_playing:
            self.updateSlider()

    def seekAudio(self, value: int):
        new_position = int((value / 100) * (self.sample.duration * 1000))
        is_playing = self.app_context.audio_player.seek_position(
            self.sample.id,
            self.sample.path,
            self.sample.duration,
            new_position,
        )
        icon_name = 'fa5s.pause' if is_playing else 'fa5s.play'
        self.play_button.setIcon(qta.icon(icon_name, color='lightgray'))
        if is_playing:
            self.updateSlider()

    def updateSlider(self):
        position = int(self.app_context.audio_player.get_position())
        sample_id = self.app_context.audio_player.current_sample_id
        duration = int(self.app_context.audio_player.current_sample_duration * 1000)

        if sample_id == self.sample.id:
            self.playback_slider.setValue(int((position / duration) * 100))
            self.time_label.setText(
                f"{format_time(position)} / {format_time(int(self.sample.duration * 1000))}"
            )
        else:
            self.play_button.setIcon(qta.icon('fa5s.play', color='lightgray'))
            self.playback_slider.setValue(int((0 / duration) * 100))
            self.time_label.setText(
                f"{format_time(0)} / {format_time(int(self.sample.duration * 1000))}"
            )

        if self.app_context.audio_player.is_playing and self.sample.id == sample_id:
            QTimer.singleShot(100, self.updateSlider)

