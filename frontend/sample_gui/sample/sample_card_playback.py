# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Encapsule la logique de lecture audio d'une SampleCard.
# - Gere le bouton play/pause, le slider de position et le label de temps.
# - Centralise les appels a app_context.audio_player pour garder SampleCard simple.
#
# FONCTIONS (sommaire)
# - SampleCardPlayback   : controleur de lecture
# - bind()               : connecte play_button.clicked et playback_slider.sliderMoved
# - toggle_play()        : toggle play/pause via audio_player + met a jour l'icone
# - seek_audio()         : deplace la position de lecture via le slider
# - update_slider()      : boucle 100 ms pour mettre a jour slider + temps
# - _apply_state()       : bascule l'icone play/pause selon l'etat
# - set_paused_icon()    : force l'icone pause (ap externe, ex: waveform ouvert)
# - format_time()        : ms -> "MM:SS"
#
# LIENS CLES
# - frontend/sample_gui/sample/sample_card.py       : carte parente
# - backend/models/AppContext.py                    : audio_player partage
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QTimer

from frontend.ui import themed_icon


class SampleCardPlayback:
    """Controleur de lecture audio pour une SampleCard.

    Le flag `_alive` evite les callbacks Qt apres la destruction du widget.
    """

    def __init__(self, card):
        self.card = card
        self._alive = True
        try:
            self.card.destroyed.connect(self._on_card_destroyed)
        except Exception:
            # Si la carte est deja en cours de destruction, on bloque tout.
            self._alive = False

    def _on_card_destroyed(self, *_):
        self._alive = False

    def bind(self):
        """Connecte les signaux UI -> actions playback."""
        c = self.card
        c.play_button.clicked.connect(self.toggle_play)
        c.playback_slider.sliderMoved.connect(self.seek_audio)

    def toggle_play(self):
        """Toggle play/pause: emet playSample et lance update_slider si en lecture."""
        if not self._alive:
            return
        c = self.card
        c.playSample.emit(c.sample)
        is_playing = c.app_context.audio_player.toggle_play(
            c.sample.id,
            c.sample.path,
            c.sample.duration,
        )
        self._apply_state(is_playing)
        if is_playing:
            self.update_slider()

    def seek_audio(self, value: int):
        """Deplace la position de lecture lorsque l'utilisateur interagit avec le slider."""
        if not self._alive:
            return
        c = self.card
        new_position = int((value / 100) * (c.sample.duration * 1000))
        is_playing = c.app_context.audio_player.seek_position(
            c.sample.id,
            c.sample.path,
            c.sample.duration,
            new_position,
        )
        self._apply_state(is_playing)
        if is_playing:
            self.update_slider()

    def update_slider(self):
        """Met a jour la position du slider, le temps affiche et detecte la fin de lecture."""
        if not self._alive:
            return
        c = self.card
        position = int(c.app_context.audio_player.get_position())
        sample_id = c.app_context.audio_player.current_sample_id
        duration = int(c.app_context.audio_player.current_sample_duration * 1000)
        if duration <= 0:
            duration = 1

        if sample_id == c.sample.id:
            c.playback_slider.setValue(int((position / duration) * 100))
            c.time_label.setText(
                f"{format_time(position)} / {format_time(int(c.sample.duration * 1000))}"
            )
        else:
            self._apply_state(False)
            c.playback_slider.setValue(0)
            c.time_label.setText(
                f"{format_time(0)} / {format_time(int(c.sample.duration * 1000))}"
            )

        if c.app_context.audio_player.is_playing and c.sample.id == sample_id:
            QTimer.singleShot(100, self.update_slider)

    def _apply_state(self, is_playing: bool):
        """Bascule l'icone du bouton entre play et pause selon l'etat courant."""
        if not self._alive:
            return
        icon_name = "player-pause" if is_playing else "player-play"
        try:
            if hasattr(self.card.play_button, "set_icon_pair"):
                self.card.play_button.set_icon_pair(
                    icon_name,
                    icon_color_normal="#cfcfcf",
                    icon_color_hover="#121212",
                )
            else:
                self.card.play_button.setIcon(
                    themed_icon(icon_name, size=14, color="#cfcfcf")
                )
        except RuntimeError:
            # Objet Qt deja detruit (deleteLater), on ignore.
            self._alive = False

    def set_paused_icon(self):
        self._apply_state(False)


def format_time(milliseconds: int) -> str:
    minutes = (milliseconds // 1000) // 60
    seconds = (milliseconds // 1000) % 60
    return f"{minutes:02}:{seconds:02}"
