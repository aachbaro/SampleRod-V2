# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Liste scrollable des captures d'ecran, affichees en ScreenshotCard.
# - Se rafraichit automatiquement via le signal screenshotsChanged.
#
# FONCTIONS (sommaire)
# - ScreenshotListWidget : widget principal (scroll + cartes)
# - _build_ui()          : scroll area + header + empty label
# - _wire_signals()      : branchement screenshotsChanged
# - refresh()            : reconstruit la liste depuis le service
#
# LIENS CLES
# - frontend/screenshot_gui/screenshot_card.py : ScreenshotCard
# - backend/services/screenshot_service.py     : screenshotsChanged
# -----------------------------------------------------------------------------

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QLabel,
    QHBoxLayout,
    QPushButton,
)
from PySide6.QtCore import Qt

from backend.models.AppContext import AppContext
from frontend.screenshot_gui.screenshot_card import ScreenshotCard


class ScreenshotListWidget(QWidget):
    """Liste scrollable des captures d'ecran, reconstruite a chaque screenshotsChanged."""

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.svc = app_context.screenshots
        self._cards = []

        self._build_ui()
        self._wire_signals()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        """Construit le scroll area, le header et le label vide."""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # header simple
        header = QHBoxLayout()
        title = QLabel("Screenshots")
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #e6e6e6;")
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("Rafraichir")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        # scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(10, 10, 10, 10)
        self.container_layout.setSpacing(10)
        self.container_layout.addStretch(1)

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

        self.empty_label = QLabel("Aucune capture (choisis un dossier dans les paramètres).")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #7a7a7a; padding: 24px;")
        self.container_layout.insertWidget(0, self.empty_label)

    def _wire_signals(self):
        """Branche screenshotsChanged pour rafraichir automatiquement la liste."""
        self.svc.screenshotsChanged.connect(lambda _items: self.refresh())

    # ------------------------------------------------------------------ Data
    def refresh(self):
        """Recharge les items du service et reconstruit toutes les ScreenshotCard."""
        items = self.svc.list_items()
        # plus recentes en premier
        items = list(reversed(items))

        # cleanup
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        # remove all widgets except stretch
        while self.container_layout.count() > 0:
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w:
                if w is not self.empty_label:
                    w.setParent(None)
                    w.deleteLater()

        if not items:
            if self.empty_label.parent() is None:
                self.container_layout.addWidget(self.empty_label)
            self.container_layout.addStretch(1)
            return

        self.empty_label.setParent(None)

        for it in items:
            card = ScreenshotCard(self.app_context, it)
            self._cards.append(card)
            self.container_layout.addWidget(card)

        self.container_layout.addStretch(1)
