# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere l'affichage du waveform editor a l'interieur d'une SampleCard.
# - S'occupe du cycle de vie (creation, ajout au layout, nettoyage).
# - Centralise la logique de bascule UI (playback <-> waveform).
# - Ajoute une animation d'expansion/reduction pour une transition plus douce.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QEasingCurve

from frontend.sample_gui.wave_form import WaveformWidget


class SampleCardWaveform:
    def __init__(self, card):
        self.card = card
        self._anim: QPropertyAnimation | None = None

    def toggle(self):
        c = self.card
        c.showWaveform = not c.showWaveform

        if c.showWaveform:
            self._open_waveform()
        else:
            self._close_waveform()

    def _open_waveform(self):
        c = self.card

        # Stoppe toute animation en cours pour repartir proprement.
        if self._anim is not None:
            try:
                self._anim.stop()
            except Exception:
                pass
        self._anim = None

        try:
            c.app_context.audio_player.clear_audio()
        except Exception:
            pass

        if c.wave_edition_widget is None:
            c.wave_edition_widget = WaveformWidget(c.sample.path, c.app_context)
            c.wave_edition_widget.waveformSaved.connect(c.newSampleSaved)
            c.waveform_layout.addWidget(c.wave_edition_widget)

        editor = getattr(c, "editor_container", None)
        stack = getattr(c, "editor_stack", None)
        if editor is None or stack is None:
            # Fallback (devrait etre rare) : sans stack, on affiche sans animation.
            c.waveform_container.setVisible(True)
            self._hide_playback()
            return

        start_h = self._editor_current_height()
        editor.setMaximumHeight(start_h)
        stack.setCurrentWidget(c.waveform_container)

        target_h = self._target_height()
        self._anim = self._animate_max_height(editor, to_height=target_h)

    def _close_waveform(self):
        c = self.card

        if self._anim is not None:
            try:
                self._anim.stop()
            except Exception:
                pass
        self._anim = None

        editor = getattr(c, "editor_container", None)
        stack = getattr(c, "editor_stack", None)
        if editor is None or stack is None:
            self._cleanup_waveform()
            self._show_playback()
            return

        # Stoppe l'audio / timer tout de suite, mais garde le widget visible
        # pendant l'animation de fermeture.
        self._stop_waveform_runtime()

        start_h = self._editor_current_height()
        editor.setMaximumHeight(start_h)
        playback_h = self._playback_target_height()
        self._anim = self._animate_max_height(
            editor,
            to_height=playback_h,
            on_finished=self._on_collapse_finished,
        )

    def _on_collapse_finished(self):
        c = self.card
        editor = getattr(c, "editor_container", None)
        stack = getattr(c, "editor_stack", None)
        if editor is not None and stack is not None:
            stack.setCurrentWidget(c.playback_container)
        self._cleanup_waveform()
        self._show_playback()

    def _target_height(self) -> int:
        """
        Calcule une hauteur cible raisonnable pour reveler le waveform.
        On s'appuie sur le sizeHint du widget (si disponible) et on borne
        un minimum pour que l'animation soit visible.
        """
        c = self.card
        if c.wave_edition_widget is None:
            return 0
        try:
            hint = int(c.wave_edition_widget.sizeHint().height())
        except Exception:
            hint = 0
        return max(220, hint)

    def _editor_current_height(self) -> int:
        c = self.card
        editor = getattr(c, "editor_container", None)
        if editor is None:
            return 0
        h = int(editor.maximumHeight())
        if h > 10000:
            h = int(editor.height())
        if h <= 0:
            h = self._playback_target_height()
        return h

    def _playback_target_height(self) -> int:
        c = self.card
        container = getattr(c, "playback_container", None)
        if container is None:
            return 0
        if hasattr(c, "playback_height_hint"):
            try:
                return int(c.playback_height_hint)
            except Exception:
                pass
        try:
            hint = int(container.sizeHint().height())
        except Exception:
            hint = 0
        return max(0, hint)

    def _animate_max_height(self, container, to_height: int, on_finished=None):
        if container is None:
            return None

        # Assure une valeur de depart "reelle" (pas QWIDGETSIZE_MAX).
        start_h = int(container.maximumHeight())
        if start_h > 10000:
            start_h = int(container.height())
            if start_h <= 0:
                try:
                    start_h = int(container.sizeHint().height())
                except Exception:
                    start_h = 0

        container.setMaximumHeight(start_h)

        anim = QPropertyAnimation(container, b"maximumHeight", container)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(start_h)
        anim.setEndValue(int(to_height))
        if on_finished is not None:
            anim.finished.connect(on_finished)
        anim.start()
        return anim

    def _stop_waveform_runtime(self):
        """Stoppe l'audio/timer du waveform sans detruire le widget (pour l'anim)."""
        c = self.card
        if not c.wave_edition_widget:
            return
        try:
            c.wave_edition_widget.stop_audio()
        except Exception:
            pass
        try:
            c.wave_edition_widget.timer.stop()
        except Exception:
            pass

    def _hide_playback(self):
        c = self.card
        if hasattr(c, "playback_container") and c.playback_container is not None:
            c.playback_container.setVisible(False)
            c.playback_container.setMaximumHeight(0)
            return
        c.play_button.setVisible(False)
        c.playback_slider.setVisible(False)
        c.time_label.setVisible(False)

    def _show_playback(self):
        c = self.card
        if hasattr(c, "playback_container") and c.playback_container is not None:
            c.playback_container.setVisible(True)
            c.playback_container.setMaximumHeight(self._playback_target_height())
            return
        c.play_button.setVisible(True)
        c.playback_slider.setVisible(True)
        c.time_label.setVisible(True)

    def _cleanup_waveform(self):
        c = self.card
        if not c.wave_edition_widget:
            return

        try:
            c.wave_edition_widget.stop_audio()
        except Exception:
            pass

        try:
            c.wave_edition_widget.timer.stop()
        except Exception:
            pass

        c.waveform_layout.removeWidget(c.wave_edition_widget)
        c.wave_edition_widget.deleteLater()
        c.wave_edition_widget = None
