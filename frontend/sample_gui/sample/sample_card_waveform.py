# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Gere l'affichage du waveform editor a l'interieur d'une SampleCard.
# - Cycle de vie: creation a la demande, destruction a la fermeture.
# - Bascule UI: playback_container <-> waveform_container via QStackedLayout.
# - Animations: expansion OutCubic (220 ms) + fade-in/out (140/120 ms).
#
# FONCTIONS (sommaire)
# - SampleCardWaveform    : controleur de waveform inline
# - toggle()              : bascule affichage waveform / playback
# - _open_waveform()      : cree le WaveformWidget + anime l'expansion
# - _close_waveform()     : stoppe audio + anime la reduction
# - _cleanup_waveform()   : stoppe audio/timer + deleteLater
# - _on_expand_finished() : libere maximumHeight + desactive QGraphicsOpacityEffect
# - _on_collapse_finished(): rebascule sur playback_container
# - _ensure_waveform_opacity_effect() : cree/recupere l'effet d'opacite
#
# LIENS CLES
# - frontend/sample_gui/wave_form.py           : WaveformWidget cree inline
# - frontend/sample_gui/sample/sample_card.py  : showWaveform / waveform_container
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QGraphicsOpacityEffect

from frontend.sample_gui.wave_form import WaveformWidget


class SampleCardWaveform:
    """Controleur du waveform editor inline dans une SampleCard."""

    def __init__(self, card):
        self.card = card
        self._anim: QPropertyAnimation | None = None
        self._fade: QPropertyAnimation | None = None

    def toggle(self):
        """Bascule entre la vue playback et la vue waveform editor."""
        c = self.card
        c.showWaveform = not c.showWaveform

        if c.showWaveform:
            self._open_waveform()
        else:
            self._close_waveform()

    def _open_waveform(self):
        """Cree le WaveformWidget (si besoin), puis anime l'expansion de l'editor_container."""
        c = self.card

        # Stoppe toute animation en cours pour repartir proprement.
        for anim in (self._anim, self._fade):
            if anim is None:
                continue
            try:
                anim.stop()
            except Exception:
                pass
        self._anim = None
        self._fade = None

        try:
            c.playback.controller.stop(c.playback._entry())
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

        # Prepare le fade-in du waveform AVANT de l'afficher pour eviter un flash.
        wave_fx = self._ensure_waveform_opacity_effect()
        if wave_fx is not None:
            # Active l'effet uniquement pendant la transition.
            wave_fx.setEnabled(True)
            wave_fx.setOpacity(0.0)

        start_h = self._editor_current_height()
        editor.setMaximumHeight(start_h)
        editor.setMinimumHeight(0)
        stack.setCurrentWidget(c.waveform_container)

        target_h = self._target_height()
        self._anim = self._animate_max_height(
            editor,
            to_height=target_h,
            on_finished=self._on_expand_finished,
        )

        # Fade-in du waveform (leger, pour adoucir la transition)
        if wave_fx is not None:
            self._fade = self._animate_opacity(
                wave_fx,
                to_opacity=1.0,
                duration_ms=140,
                easing=QEasingCurve.Type.OutCubic,
            )

    def _on_expand_finished(self):
        """
        Apres l'animation d'ouverture, on "libere" la hauteur max de l'editor
        pour que des changements internes (ex: apparition de la liste de markers)
        puissent agrandir le widget sans overflow.
        """
        c = self.card
        editor = getattr(c, "editor_container", None)
        stack = getattr(c, "editor_stack", None)
        if editor is None or stack is None:
            return
        if not getattr(c, "showWaveform", False):
            return
        if stack.currentWidget() is not c.waveform_container:
            return
        editor.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

        # IMPORTANT (PyQtGraph + QGraphicsOpacityEffect)
        # QGraphicsOpacityEffect force un rendu offscreen: sur PyQtGraph, ca peut
        # spammer des warnings QPainter au survol (repaints frequents).
        # Solution: garder l'effet installe, mais le DESACTIVER hors transition.
        wave_fx = self._ensure_waveform_opacity_effect()
        if wave_fx is not None:
            wave_fx.setOpacity(1.0)
            wave_fx.setEnabled(False)

    def _close_waveform(self):
        """Stoppe le waveform et anime la reduction de l'editor_container vers playback_height."""
        c = self.card

        for anim in (self._anim, self._fade):
            if anim is None:
                continue
            try:
                anim.stop()
            except Exception:
                pass
        self._anim = None
        self._fade = None

        editor = getattr(c, "editor_container", None)
        stack = getattr(c, "editor_stack", None)
        if editor is None or stack is None:
            self._cleanup_waveform()
            self._show_playback()
            return

        # Stoppe l'audio / timer tout de suite, mais garde le widget visible
        # pendant l'animation de fermeture.
        self._stop_waveform_runtime()

        # Fade-out du waveform pendant la fermeture.
        wave_fx = self._ensure_waveform_opacity_effect()
        if wave_fx is not None:
            wave_fx.setEnabled(True)
            wave_fx.setOpacity(1.0)
            self._fade = self._animate_opacity(
                wave_fx,
                to_opacity=0.0,
                duration_ms=120,
                easing=QEasingCurve.Type.InCubic,
            )

        start_h = self._editor_current_height()
        editor.setMaximumHeight(start_h)
        # Le minimum sera re-serre au playback dans _on_collapse_finished
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
            # Prepare fade-in playback avant le switch (evite flash).
            pb_fx = getattr(c, "playback_opacity_effect", None)
            if pb_fx is not None:
                try:
                    pb_fx.setOpacity(0.0)
                except Exception:
                    pass
            stack.setCurrentWidget(c.playback_container)

            # Fade-in playback (petit, mais rend le retour plus doux)
            if pb_fx is not None:
                self._fade = self._animate_opacity(
                    pb_fx,
                    to_opacity=1.0,
                    duration_ms=140,
                    easing=QEasingCurve.Type.OutCubic,
                )

            # Waveform hors ecran: on desactive l'effet (voir note PyQtGraph).
            wave_fx = self._ensure_waveform_opacity_effect()
            if wave_fx is not None:
                wave_fx.setOpacity(1.0)
                wave_fx.setEnabled(False)
            # Re-serre la hauteur sur le playback pour eviter l'espace vide.
            playback_h = self._playback_target_height()
            editor.setMinimumHeight(playback_h)
            editor.setMaximumHeight(playback_h)
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

    def _animate_opacity(
        self,
        opacity_effect,
        to_opacity: float,
        duration_ms: int,
        easing: QEasingCurve.Type,
    ) -> QPropertyAnimation:
        """
        Anime l'opacite d'un QGraphicsOpacityEffect.
        L'animation doit rester courte pour ne pas "ralentir" l'UI.
        """
        anim = QPropertyAnimation(opacity_effect, b"opacity", opacity_effect)
        anim.setDuration(int(duration_ms))
        anim.setEasingCurve(easing)
        try:
            start = float(opacity_effect.opacity())
        except Exception:
            start = 1.0
        anim.setStartValue(start)
        anim.setEndValue(float(to_opacity))
        anim.start()
        return anim

    def _ensure_waveform_opacity_effect(self) -> QGraphicsOpacityEffect | None:
        """
        Renvoie l'opacite effect du waveform (cree si besoin).

        Pourquoi:
        - QWidget.setGraphicsEffect() prend ownership et peut detruire l'effet
          si on le remplace / retire.
        - On veut un objet stable, mais on souhaite aussi pouvoir recuperer
          si un effet a ete supprime dans une session precedente (dev).
        """
        c = self.card
        container = getattr(c, "waveform_container", None)
        if container is None:
            return None

        wave_fx = getattr(c, "waveform_opacity_effect", None)
        if wave_fx is None:
            wave_fx = QGraphicsOpacityEffect(container)
            wave_fx.setOpacity(1.0)
            container.setGraphicsEffect(wave_fx)
            c.waveform_opacity_effect = wave_fx
            return wave_fx

        # Si l'objet C++ a ete supprime, PyQt leve RuntimeError.
        try:
            _ = wave_fx.opacity()
        except RuntimeError:
            wave_fx = QGraphicsOpacityEffect(container)
            wave_fx.setOpacity(1.0)
            container.setGraphicsEffect(wave_fx)
            c.waveform_opacity_effect = wave_fx
            return wave_fx

        return wave_fx

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
        """Stoppe audio/timer et detruit le WaveformWidget (deleteLater)."""
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
