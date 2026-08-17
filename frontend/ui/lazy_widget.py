"""Coquille legere pour construire un QWidget seulement a sa premiere vue.

Qt interdit de creer des widgets dans un thread secondaire. Cette classe
affiche donc immediatement un etat de chargement, rend la main a la boucle
d'evenements, puis appelle la factory sur le thread UI. Les travaux de donnees
propres a chaque ecran peuvent, eux, rester dans leurs QThread respectifs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from frontend.styles import theme

logger = logging.getLogger("lazy_widget")


class LazyWidgetHost(QWidget):
    """Charge une seule fois le widget produit par ``factory``."""

    loadingStarted = Signal()
    loaded = Signal(object)
    loadingFailed = Signal(str)

    def __init__(self, factory: Callable[[], QWidget], label: str, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._loaded_widget: QWidget | None = None
        self._scheduled = False
        self._loading = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.addStretch()
        self._label = QLabel(label)
        self._label.setObjectName("LazyLoadingLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._label)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setMaximumWidth(280)
        self._layout.addWidget(self._progress)
        self._layout.setAlignment(self._progress, Qt.AlignmentFlag.AlignHCenter)
        self._layout.addStretch()
        self._apply_style()
        theme.manager.themeChanged.connect(lambda *_: self._apply_style())

    @property
    def loaded_widget(self) -> QWidget | None:
        return self._loaded_widget

    def ensure_loaded(self) -> None:
        """Programme le chargement apres un premier rendu de la coquille."""
        if self._loaded_widget is not None or self._scheduled or self._loading:
            return
        self._scheduled = True
        # Une courte frame permet a Qt de peindre la fenetre et l'indicateur
        # avant une construction de widgets potentiellement couteuse.
        QTimer.singleShot(30, self._load_now)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.ensure_loaded()

    def _load_now(self) -> None:
        self._scheduled = False
        if self._loaded_widget is not None or self._loading:
            return
        self._loading = True
        self.loadingStarted.emit()
        try:
            widget = self._factory()
            if not isinstance(widget, QWidget):
                raise TypeError("La factory lazy doit retourner un QWidget")
        except Exception as exc:
            logger.exception("Construction differee impossible")
            self._loading = False
            self._progress.hide()
            self._label.setText(f"Chargement impossible : {exc}")
            self.loadingFailed.emit(str(exc))
            return

        self._factory = None
        self._loaded_widget = widget
        self._loading = False
        self._layout.removeWidget(self._label)
        self._layout.removeWidget(self._progress)
        self._label.deleteLater()
        self._progress.deleteLater()
        self._layout.takeAt(0)  # stretch superieur
        self._layout.takeAt(self._layout.count() - 1)  # stretch inferieur
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(widget)
        self.loaded.emit(widget)

    def _apply_style(self) -> None:
        p = theme.manager.p
        self.setStyleSheet(
            f"""
            LazyWidgetHost {{ background: {p.BG_DARK}; }}
            QLabel#LazyLoadingLabel {{
                color: {p.TEXT_MUTED};
                font-size: 13px;
                padding: 8px;
            }}
            QProgressBar {{
                min-height: 3px;
                max-height: 3px;
                border: none;
                border-radius: 1px;
                background: {p.BORDER};
            }}
            QProgressBar::chunk {{ background: {p.RETRO}; }}
            """
        )
