# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Widget flottant de controle d'enregistrement.
# - Pilote start/stop, etat retro et feedback visuel temps reel.
#
# LIENS CLES
# - backend/services/recorder_service.py
# - backend/services/settings_service.py
# -----------------------------------------------------------------------------
# frontend/record_widget.py

import logging

from PySide6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEvent, QRect, QSize, Signal
from PySide6.QtGui import QIcon, QCursor
from PySide6.QtWidgets import QMainWindow, QPushButton, QWidget, QLabel, QMenu
import qtawesome as qta

from utils.utils import get_folder_name
from backend.models.AppContext import AppContext
from backend.services.notification_service import NotificationType

logger = logging.getLogger("record_widget")


class RecordWidgetWindow(QMainWindow):
    """Floating recorder control (always on top)."""

    newSampleRecorded = Signal(str)

    # Palette proche du reste de l'app
    _COLOR_BG = "#16181b"
    _COLOR_BG_HOVER = "#1e2228"
    _COLOR_BORDER = "#3b3f46"
    _COLOR_TEXT = "#f2f2f2"
    _COLOR_MUTED = "#8d95a3"
    _COLOR_RETRO = "#2cc6cf"
    _COLOR_RECORDING = "#e45050"

    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context
        self.settings = self.app_context.settings

        # Widgets references (definis tot pour eviter les AttributeError
        # si un event Qt arrive pendant la construction).
        self.button_container = None
        self.recordButton = None
        self.library_indicator = None
        self.library_number_label = None
        self.drag_area = None
        self.library_name = None

        self.scale = 1.3
        self.library_selected = 0
        self.retro_time_selected = 0
        self.is_dragging = False
        self.drag_offset = QPoint(0, 0)
        self.current_animation = None
        self.current_animation_drag = None

        self._build_window()
        self._build_widgets()
        self._wire_signals()
        self._start_timers()

        self.updateLibraryCount()
        self.updateRetroRecording()
        self.updateRecordButtonDisplay()

    # ------------------------------------------------------------------ Setup
    def _build_window(self):
        self.setWindowTitle("Record Widget")
        self.setGeometry(
            int(150 * self.scale),
            int(150 * self.scale),
            int(110 * self.scale),
            int(55 * self.scale),
        )
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.setWindowOpacity(0.6)

    def _build_widgets(self):
        base_w = int(28 * self.scale)
        base_h = int(28 * self.scale)
        slot_w = int(28 * self.scale)

        self.button_container = QWidget(self)
        self.button_container.setObjectName("RecordShell")
        self.base_geometry = QRect(0, 0, base_w, base_h)
        self.button_container.setGeometry(self.base_geometry)

        self.recordButton = QPushButton(self.button_container)
        self.recordButton.setGeometry(int(4 * self.scale), int(4 * self.scale), int(20 * self.scale), int(20 * self.scale))
        self.recordButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recordButton.setIconSize(QSize(int(14 * self.scale), int(14 * self.scale)))

        self.library_indicator = QLabel(self.button_container)
        self.library_indicator.setGeometry(base_w, 0, slot_w, base_h)
        self.library_indicator.setCursor(Qt.CursorShape.SplitVCursor)
        self.library_indicator.setToolTip("Molette: changer de bibliotheque")

        self.library_number_label = QLabel(self.library_indicator)
        self.library_number_label.setGeometry(0, 0, slot_w, base_h)
        self.library_number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.drag_area = QLabel(self)
        self.drag_areaBase_geometry = QRect(
            int(34 * self.scale),
            0,
            int(10 * self.scale),
            base_h,
        )
        self.drag_area.setGeometry(self.drag_areaBase_geometry)
        self.drag_area.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_area.setToolTip("Deplacer le widget")
        self.drag_area.setStyleSheet("background: transparent;")

        self.library_name = QLabel(self)
        self.library_name.setGeometry(
            0,
            int(32 * self.scale),
            int(180 * self.scale),
            int(16 * self.scale),
        )
        self.library_name.setVisible(False)
        self.library_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.button_container.installEventFilter(self)
        self.recordButton.installEventFilter(self)
        self.library_indicator.installEventFilter(self)

        self._apply_static_icons()
        self._apply_shell_style()

    def _wire_signals(self):
        self.settings.librariesChanged.connect(self.updateLibraryCount)
        self.settings.retroToggled.connect(self.updateRetroRecording)
        self.settings.preSecondsChanged.connect(self.updateRetroRecording)
        self.app_context.recorder.recordingStateChanged.connect(self._on_recording_state_changed)

    def _start_timers(self):
        self.keep_top_timer = QTimer(self)
        self.keep_top_timer.timeout.connect(self.keep_on_top)
        self.keep_top_timer.start(1000)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_worker)
        self.poll_timer.start(100)

    def _apply_static_icons(self):
        self.library_indicator.setPixmap(
            qta.icon("fa5s.folder", color=self._COLOR_TEXT).pixmap(
                int(20 * self.scale), int(22 * self.scale)
            )
        )
        self.drag_area.setPixmap(
            qta.icon("fa5s.ellipsis-v", color=self._COLOR_MUTED).pixmap(
                int(10 * self.scale), int(18 * self.scale)
            )
        )

    def _apply_shell_style(self, hovered: bool = False):
        if self.app_context.recorder.is_recording:
            border = self._COLOR_RECORDING
        elif self.settings.isRetroEnabled():
            border = self._COLOR_RETRO
        else:
            border = self._COLOR_BORDER

        bg = self._COLOR_BG_HOVER if hovered else self._COLOR_BG
        radius = max(1, self.button_container.height() // 2)
        self.button_container.setStyleSheet(
            f"""
            QWidget#RecordShell {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            """
        )
        self.library_indicator.setStyleSheet("background: transparent; border: none;")
        self.library_number_label.setStyleSheet(
            """
            QLabel {
                background: transparent;
                color: #111111;
                border: none;
                font-size: 12px;
                font-weight: 700;
            }
            """
        )
        self.library_name.setStyleSheet(
            f"""
            QLabel {{
                background-color: {self._COLOR_BG};
                color: {self._COLOR_TEXT};
                border: 1px solid {self._COLOR_BORDER};
                border-radius: 4px;
                padding-left: 6px;
                font-size: 10px;
            }}
            """
        )

    # ------------------------------------------------------------------ Events
    def eventFilter(self, source, event):
        if source == self.button_container:
            if event.type() == QEvent.Type.Enter:
                self._apply_shell_style(hovered=True)
                self.animate_container(expand=True)
            elif event.type() == QEvent.Type.Leave:
                self._apply_shell_style(hovered=False)
                self.animate_container(expand=False)

        if source == self.library_indicator:
            if event.type() == QEvent.Type.Wheel:
                delta = event.angleDelta().y()
                self._rotate_library(delta)
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                self.library_name.setVisible(not self.library_name.isVisible())
                return True

        if source == self.recordButton:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if not self._has_valid_library():
                    self.app_context.notifications.notify(
                        title="Enregistrement impossible",
                        message="Selectionnez d'abord une bibliotheque avant d'enregistrer.",
                        type=NotificationType.WARNING,
                    )
                    return True
                selected_library = self.settings.libraries[self.library_selected].path
                self.app_context.recorder.record_button_clicked(
                    selected_library, self.retro_time_selected
                )
                self.updateRecordButtonDisplay()
                return True

            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                self._show_retro_context_menu()
                return True

            if event.type() == QEvent.Type.Wheel and self.settings.isRetroEnabled():
                self._adjust_retro_time(event.angleDelta().y())
                return True

        return super().eventFilter(source, event)

    def mousePressEvent(self, event):
        if self.drag_area.geometry().contains(event.position().toPoint()):
            self.is_dragging = True
            self.drag_offset = event.position().toPoint()
            self.drag_area.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.is_dragging = False

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            delta = event.position().toPoint() - self.drag_offset
            self.move(self.pos() + delta)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.drag_area.setCursor(Qt.CursorShape.OpenHandCursor)

    def enterEvent(self, event):
        self.setWindowOpacity(0.9)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setWindowOpacity(0.6)
        super().leaveEvent(event)

    # ------------------------------------------------------------------ UI Logic
    def _has_valid_library(self) -> bool:
        if not self.settings.libraries:
            return False
        return 0 <= self.library_selected < len(self.settings.libraries)

    def _rotate_library(self, delta: int):
        libs = self.settings.libraries
        if not libs:
            return
        if delta > 0:
            self.library_selected = (self.library_selected + 1) % len(libs)
        else:
            self.library_selected = (self.library_selected - 1) % len(libs)
        self.updateLibraryCount()

    def _adjust_retro_time(self, wheel_delta: int):
        max_pre = self.settings.getPreSeconds()
        if wheel_delta > 0 and self.retro_time_selected < max_pre:
            self.retro_time_selected += 1
        elif wheel_delta < 0 and self.retro_time_selected > 0:
            self.retro_time_selected -= 1
        self.updateRecordButtonDisplay()

    def _show_retro_context_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #1b1b1b;
                color: #f2f2f2;
                border: 1px solid #333;
            }
            QMenu::item:selected {
                background-color: #2a2a2a;
            }
            """
        )
        enabled = self.settings.isRetroEnabled()
        action = menu.addAction(
            "Desactiver retro-enregistrement" if enabled else "Activer retro-enregistrement"
        )
        if menu.exec(QCursor.pos()) == action:
            self.settings.toggleRetro()

    def updateLibraryCount(self):
        libs = self.settings.libraries
        if libs:
            if self.library_selected >= len(libs):
                self.library_selected = len(libs) - 1
            current = libs[self.library_selected]
            self.library_number_label.setText(str(current.position))
            self.library_name.setText(get_folder_name(current.path))
        else:
            self.library_number_label.setText("N")
            self.library_name.setText("Aucune bibliotheque")

    def updateRetroRecording(self):
        max_pre = self.settings.getPreSeconds()
        if self.retro_time_selected > max_pre:
            self.retro_time_selected = max_pre
        self._apply_shell_style()
        self.updateRecordButtonDisplay()

    def _on_recording_state_changed(self, _is_recording: bool):
        self._apply_shell_style()
        self.updateRecordButtonDisplay()

    def updateRecordButtonDisplay(self):
        is_recording = self.app_context.recorder.is_recording
        is_retro = self.settings.isRetroEnabled()
        show_retro_value = is_retro and self.retro_time_selected > 0

        if is_recording:
            border = self._COLOR_RECORDING
            icon_color = self._COLOR_RECORDING
            text_color = self._COLOR_RECORDING
        else:
            border = self._COLOR_RETRO if is_retro else self._COLOR_BORDER
            icon_color = self._COLOR_TEXT
            text_color = self._COLOR_TEXT

        button_radius = max(1, self.recordButton.height() // 2)
        self.recordButton.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self._COLOR_BG};
                color: {text_color};
                border: 1px solid {border};
                border-radius: {button_radius}px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                border-color: #ffffff;
            }}
            """
        )

        if show_retro_value:
            self.recordButton.setIcon(QIcon())
            self.recordButton.setText(str(self.retro_time_selected))
        else:
            self.recordButton.setText("")
            dot_color = "#ff3b3b" if is_recording else "#ffffff"
            self.recordButton.setIcon(qta.icon("fa5s.circle", color=dot_color))

        status = "Enregistrement en cours" if is_recording else "Pret"
        lib_name = self.library_name.text() if self.library_name.text() else "Aucune bibliotheque"
        self.recordButton.setToolTip(
            f"{status}\nBibliotheque: {lib_name}\n"
            "Clic gauche: start/stop\nClic droit: activer/desactiver retro\nMolette sur REC: retro time de la prise (0..duree max des Parametres)"
        )

    # ------------------------------------------------------------------ Animations / timers
    def animate_container(self, expand: bool):
        base_w = self.base_geometry.width()
        slot_w = int(28 * self.scale)
        drag_shift = slot_w

        end_geom = (
            QRect(self.base_geometry.x(), self.base_geometry.y(), base_w + slot_w, self.base_geometry.height())
            if expand
            else self.base_geometry
        )
        current_drag_geom = self.drag_area.geometry()
        end_drag_geom = (
            QRect(
                self.drag_areaBase_geometry.x() + drag_shift,
                self.drag_areaBase_geometry.y(),
                self.drag_areaBase_geometry.width(),
                self.drag_areaBase_geometry.height(),
            )
            if expand
            else self.drag_areaBase_geometry
        )

        if current_drag_geom == end_drag_geom and self.button_container.geometry() == end_geom:
            return

        anim = QPropertyAnimation(self.button_container, b"geometry", self)
        anim_drag = QPropertyAnimation(self.drag_area, b"geometry", self)
        anim.setDuration(160)
        anim_drag.setDuration(160)
        anim.setStartValue(self.button_container.geometry())
        anim.setEndValue(end_geom)
        anim_drag.setStartValue(self.drag_area.geometry())
        anim_drag.setEndValue(end_drag_geom)
        anim.start()
        anim_drag.start()
        self.current_animation = anim
        self.current_animation_drag = anim_drag

    def keep_on_top(self):
        self.raise_()

    def _poll_worker(self):
        try:
            for msg, payload in self.app_context.recorder.poll():
                if msg == "done" and payload:
                    self.newSampleRecorded.emit(payload)
        except KeyboardInterrupt:
            # Peut arriver pendant un shutdown/interrupt global de l'app.
            logger.info("record_widget: polling interrompu pendant la fermeture")
            if hasattr(self, "poll_timer") and self.poll_timer is not None:
                self.poll_timer.stop()
        except Exception:
            logger.exception("record_widget: erreur inattendue dans _poll_worker")

    def closeEvent(self, event):
        if hasattr(self, "poll_timer") and self.poll_timer is not None:
            self.poll_timer.stop()
        if hasattr(self, "keep_top_timer") and self.keep_top_timer is not None:
            self.keep_top_timer.stop()
        super().closeEvent(event)