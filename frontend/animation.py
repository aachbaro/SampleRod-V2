from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QGraphicsOpacityEffect

class AnimationHelper:
    """Utility class to run simple Qt animations on widgets."""

    _active = []

    @classmethod
    def _keep(cls, anim):
        cls._active.append(anim)
        anim.finished.connect(lambda: cls._active.remove(anim))

    @classmethod
    def fade_in(cls, widget, duration=300, easing=QEasingCurve.Type.InOutQuad):
        """Fade in ``widget`` by animating its opacity."""
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        widget.show()
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(easing)
        cls._keep(anim)
        anim.start()
        return anim

    @classmethod
    def fade_out(cls, widget, duration=300, easing=QEasingCurve.Type.InOutQuad):
        """Fade out ``widget`` then hide it when finished."""
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        start = effect.opacity() if hasattr(effect, "opacity") else 1.0
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(0.0)
        anim.setEasingCurve(easing)
        def on_finished():
            widget.hide()
        anim.finished.connect(on_finished)
        cls._keep(anim)
        anim.start()
        return anim

    @classmethod
    def animate_height(cls, widget, start_h, end_h,
                       duration=300, easing=QEasingCurve.Type.InOutQuad):
        """Animate ``widget`` maximum height from ``start_h`` to ``end_h``."""
        anim = QPropertyAnimation(widget, b"maximumHeight", widget)
        anim.setDuration(duration)
        anim.setStartValue(start_h)
        anim.setEndValue(end_h)
        anim.setEasingCurve(easing)
        cls._keep(anim)
        anim.start()
        return anim

    @classmethod
    def animate_property(cls, widget, prop, start, end,
                         duration=300, easing=QEasingCurve.Type.InOutQuad):
        """Generic helper to animate ``prop`` of ``widget``."""
        anim = QPropertyAnimation(widget, prop, widget)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(easing)
        cls._keep(anim)
        anim.start()
        return anim
