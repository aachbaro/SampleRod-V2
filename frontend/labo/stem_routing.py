# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Tableau de routage des stems pour l'outil Stems du Labo.
# - 4 pins draggables (drums / bass / vocals / other) a repartir dans
#   4 canaux de sortie + une zone "Hors mix" pour ignorer un stem.
# - Aucun traitement audio ici : le widget expose seulement la configuration
#   stem -> canal choisie par l'utilisateur (routing()).
#
# FONCTIONS (sommaire)
# - StemPinWidget      : pin icone draggable representant un stem.
# - StemChannelZone    : zone de depot (canal 1-4 ou Hors mix).
# - StemRoutingBoard   : assemble pins + zones, expose routing()/set_routing().
#
# LIENS CLES
# - frontend/labo/stem_separator_tool.py : consomme routing() au lancement
#   et style les widgets via les objectName definis ici.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

STEM_PIN_MIME = "application/x-samplerod-stem-pin"
STEM_ORDER: tuple[str, ...] = ("drums", "bass", "vocals", "other")
STEM_ICONS: dict[str, str] = {
    "drums": "\U0001f941",   # 🥁
    "bass": "\U0001f3b8",    # 🎸
    "vocals": "\U0001f3a4",  # 🎤
    "other": "\U0001f3b9",   # 🎹
}
STEM_COLORS: dict[str, str] = {
    "drums": "#d46666",
    "bass": "#7a6fd4",
    "vocals": "#4bb6b7",
    "other": "#d8a747",
}
CHANNEL_COUNT = 4
# Routage par defaut : un stem par canal (equivaut au comportement historique).
DEFAULT_ROUTING: dict[str, int | None] = {
    name: index for index, name in enumerate(STEM_ORDER)
}


class StemPinWidget(QLabel):
    """Pin draggable (icone seule, nom en tooltip) representant un stem."""

    def __init__(self, stem: str, parent=None):
        super().__init__(STEM_ICONS.get(stem, "\U0001f3b5"), parent)
        self.stem = str(stem)
        self.setObjectName("StemPin")
        self.setProperty("stem", self.stem)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedSize(28, 28)
        self.setToolTip(f"{self.stem} — glisse ce pin dans un canal (Hors mix = ignore)")
        self._press_pos: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        mime = QMimeData()
        mime.setData(STEM_PIN_MIME, self.stem.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self._press_pos)
        self._press_pos = None
        drag.exec(Qt.DropAction.MoveAction)


class StemChannelZone(QWidget):
    """Zone de depot pour les pins : un canal (0-3) ou la zone Hors mix (None)."""

    pinDropped = Signal(str, object)  # (stem, zone_id: int | None)

    def __init__(self, zone_id: int | None, title: str, parent=None):
        super().__init__(parent)
        self.zone_id = zone_id
        self.setObjectName("StemChannelZone")
        self.setProperty("tray", zone_id is None)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(56)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("StemChannelTitle")

        self.pins_row = QHBoxLayout()
        self.pins_row.setContentsMargins(0, 0, 0, 0)
        self.pins_row.setSpacing(4)
        self.pins_row.addStretch(1)

        layout.addWidget(self.title_label)
        layout.addLayout(self.pins_row)

    def add_pin(self, pin: StemPinWidget) -> None:
        self.pins_row.insertWidget(self.pins_row.count() - 1, pin)
        pin.show()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(STEM_PIN_MIME):
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(STEM_PIN_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_active(False)
        event.accept()

    def dropEvent(self, event):
        self._set_active(False)
        if not event.mimeData().hasFormat(STEM_PIN_MIME):
            event.ignore()
            return
        stem = bytes(event.mimeData().data(STEM_PIN_MIME)).decode("utf-8", "ignore")
        if not stem:
            event.ignore()
            return
        event.acceptProposedAction()
        self.pinDropped.emit(stem, self.zone_id)

    def _set_active(self, active: bool) -> None:
        self.setProperty("dropActive", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)


class StemRoutingBoard(QWidget):
    """Tableau de routage : 4 canaux + Hors mix, pins persistants reparentes."""

    routingChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StemRoutingBoard")
        self._routing: dict[str, int | None] = dict(DEFAULT_ROUTING)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.board_title = QLabel("Routage vers les canaux")
        self.board_title.setObjectName("StemRoutingTitle")

        self.channel_zones: list[StemChannelZone] = [
            StemChannelZone(index, str(index + 1), self)
            for index in range(CHANNEL_COUNT)
        ]
        channels_row = QHBoxLayout()
        channels_row.setContentsMargins(0, 0, 0, 0)
        channels_row.setSpacing(6)
        for zone in self.channel_zones:
            channels_row.addWidget(zone, 1)

        self.tray_zone = StemChannelZone(None, "Hors mix", self)

        legend_parts = " · ".join(
            f"{STEM_ICONS[stem]} {stem}" for stem in STEM_ORDER
        )
        self.legend_label = QLabel(
            f"{legend_parts} — plusieurs pins dans un canal = stems mixes ensemble."
        )
        self.legend_label.setObjectName("StemRoutingLegend")
        self.legend_label.setWordWrap(True)

        layout.addWidget(self.board_title)
        layout.addLayout(channels_row)
        layout.addWidget(self.tray_zone)
        layout.addWidget(self.legend_label)

        # Pins persistants : reparentes entre zones au lieu d'etre recrees,
        # pour ne jamais detruire la source d'un QDrag en cours.
        self._pins: dict[str, StemPinWidget] = {
            stem: StemPinWidget(stem) for stem in STEM_ORDER
        }

        for zone in (*self.channel_zones, self.tray_zone):
            zone.pinDropped.connect(self._on_pin_dropped)

        self._rebuild()

    def routing(self) -> dict[str, int | None]:
        return dict(self._routing)

    def set_routing(self, routing: dict) -> None:
        cleaned: dict[str, int | None] = {}
        for stem in STEM_ORDER:
            value = (routing or {}).get(stem, DEFAULT_ROUTING[stem])
            if value is None:
                cleaned[stem] = None
            elif isinstance(value, (int, float)) and 0 <= int(value) < CHANNEL_COUNT:
                cleaned[stem] = int(value)
            else:
                cleaned[stem] = DEFAULT_ROUTING[stem]
        if cleaned == self._routing:
            return
        self._routing = cleaned
        self._rebuild()

    def _on_pin_dropped(self, stem: str, zone_id: object) -> None:
        if stem not in self._routing:
            return
        target = int(zone_id) if isinstance(zone_id, int) else None
        if self._routing[stem] == target:
            return
        self._routing[stem] = target
        self._rebuild()
        self.routingChanged.emit()

    def _rebuild(self) -> None:
        for stem in STEM_ORDER:
            pin = self._pins[stem]
            channel = self._routing.get(stem)
            if channel is None:
                self.tray_zone.add_pin(pin)
            else:
                self.channel_zones[channel].add_pin(pin)
