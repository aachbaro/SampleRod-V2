import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QMainWindow, QPushButton, QWidget, QLabel
from PyQt6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEvent, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QWheelEvent
import qtawesome as qta
from backend.models.User import User
from utils.utils import get_folder_name
from backend.models.sample import Sample
import datetime

class RecordWidgetWindow(QMainWindow):
    newSampleRecorded = pyqtSignal(str)

    def __init__(self, user: User):
        super().__init__()

# ------------------------------------------------------------------------ Geometrie de la fenetre
        self.scale = 1.3
        self.setWindowTitle("Record Widget")
        self.setGeometry(int(150 * self.scale), int(150 * self.scale), int(80 * self.scale), int(40 * self.scale))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)              # Supprime la bordure de la fenêtre
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)      # Transparence de la fenêtre
        self.setStyleSheet("background: transparent;")                     # Fond transparent
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)  # Toujours au premier plan
        self.setWindowOpacity(0.5)
        self.button_container = QWidget(self)
        self.recordButton = QPushButton(self.button_container)
        self.library_indicator = QLabel(self.button_container)
        self.library_number_label = QLabel(self.library_indicator)
        self.library_name = QLabel(self)
        self.user = user
        self.library_selected = 0
        self.retro_time_selected = 0

        # 🔹 Timer pour forcer la fenêtre au premier plan
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.keep_on_top)
        self.timer.start(1000)
        # Timer pour poller le worker et mettre à jour l'UI
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_worker)
        self.poll_timer.start(200) # Poll every 200ms
# ------------------------------------------------------------------------ Container a boutons

        self.base_geometry = QRect(0, 0, int(26 * self.scale), int(26 * self.scale))
        self.button_container.setGeometry(self.base_geometry)
        self.button_container.setStyleSheet(
            "background: black; "
            "opacity: 10%;"
            "border: 1px solid white; "
            "border-radius: 4px;"
        )
        self.button_container.installEventFilter(self)  # Installer l'event filter pour le hover

        # ----- Bouton d'enregistrement placé à l'intérieur du conteneur

        self.recordButton.setGeometry(int(4 * self.scale), int(4 * self.scale), int(18 * self.scale), int(18 * self.scale))
        self.recordButton.setIcon(qta.icon('fa5s.microphone', color='white'))
        self.recordButton.setIconSize(QSize(int(14 * self.scale), int(14 * self.scale)))
        self.recordButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recordButton.setStyleSheet(
            "background: black; "
            "color: white; "
            "border: 1px solid white; "
            "border-radius: 8px;"
        )
        self.recordButton.installEventFilter(self)

        # ----- Indicateur de repertoire

        self.library_indicator.setGeometry(int(26 * self.scale), int(0 * self.scale), int(26 * self.scale), int(26 * self.scale))
        self.library_indicator.setPixmap(qta.icon('fa5s.folder', color='white').pixmap(int(20 * self.scale), int(23 * self.scale)))
        self.library_indicator.setCursor(Qt.CursorShape.SplitVCursor)

        self.library_number_label.setGeometry(int(3 * self.scale), int(2 * self.scale), int(25 * self.scale), int(25 * self.scale))  # Positionner le label à l'intérieur du `library_indicator`
        self.library_number_label.setStyleSheet(
            "background: transparent; "
            "color: black; "
            "border: none; "
            "font-size: 14px; "
            "text-align: center;"
        )
        if (self.user.libraries):
            self.library_number_label.setText(str(self.user.libraries[self.library_selected].position))
        else:
            self.library_number_label.setText("N")
        self.library_indicator.setStyleSheet(
            "background: transparent; "
            "color: white; "
            "border: none; "
        )
        self.library_indicator.installEventFilter(self)



# ------------------------------------------------------------------------ Zone draggable

        self.drag_area = QLabel(self)
        self.drag_areaBase_geometry = QRect(int(30 * self.scale), int(0 * self.scale), int(10 * self.scale), int(26 * self.scale))
        self.drag_area.setGeometry(int(30 * self.scale), int(0 * self.scale), int(10 * self.scale), int(26 * self.scale))
        self.drag_area.setPixmap(qta.icon('fa5s.ellipsis-v', color='white').pixmap(int(10 * self.scale), int(20 * self.scale)))
        self.drag_area.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_area.setStyleSheet(
            "background: transparent;"
            "font-size: 1x;"
        )
        self.is_dragging = False
        self.drag_offset = QPoint(0, 0)

# ------------------------------------------------------------------------ Indicateur de nom
        self.library_name.setGeometry(int(0 * self.scale), int(26 * self.scale), int(100 * self.scale), int(10 * self.scale))  # Définir la géométrie correctement
        if (self.user.libraries):
            self.library_name.setText(get_folder_name(self.user.libraries[self.library_selected].path))
        else:
            self.library_name.setText("No library")
        self.library_name.setVisible(False)
        self.library_name.setStyleSheet("font-size: 10px;")

# ------------------------------------------------------------------------ Extension du container a bouton
    def eventFilter(self, source, event):
        """Filtre les événements pour gérer le survol et le clic sur le conteneur de boutons."""
        # ------------------------------------------------ Button container
        if source == self.button_container:
            if event.type() == QEvent.Type.Enter:
                self.animate_container(expand=True)
            elif event.type() == QEvent.Type.Leave:
                self.animate_container(expand=False)

        # ------------------------------------------------ lIBRARY INDICATOR

        if source == self.library_indicator:
            if event.type() == QEvent.Type.Wheel:
                # event est déjà un QWheelEvent, pas besoin de le recréer
                delta = event.angleDelta().y()
                if self.user.libraries:
                    if delta > 0:
                        self.library_selected = (self.library_selected + 1) % len(self.user.libraries)
                    else:
                        self.library_selected = (self.library_selected - 1) % len(self.user.libraries)
                    self.updateLibraryCount()
                    if (self.user.libraries):
                        self.library_name.setText(get_folder_name(self.user.libraries[self.library_selected].path))
                    else:
                        self.library_name.setText("No library.")

                return True
            elif event.type() == QEvent.Type.MouseButtonPress:
                self.library_name.setVisible(not self.library_name.isVisible())

        # ----------------------------------------------- RecordButton

        if source == self.recordButton:
            if event.type() == QEvent.Type.MouseButtonPress:
                selected_library = self.user.libraries[self.library_selected].path
                self.user.recorder.record_button_clicked(selected_library, self.retro_time_selected)
                # on sort, on laisse le timer plus tard rafraîchir l'état
                self.updateRecordButtonDisplay()
                return True

        # -------------------------------- Scroll sur retro recording

            elif event.type() == QEvent.Type.Wheel and self.user.settings.retro_recording_enabled:
                delta = event.angleDelta().y()
                if delta > 0 and self.retro_time_selected < self.user.settings.pre_recording_seconds:
                    self.retro_time_selected += 1
                elif delta < 0 and self.retro_time_selected > 0:
                    self.retro_time_selected -= 1
                
                self.updateRecordButtonDisplay()

        return super().eventFilter(source, event)


    def updateLibraryCount(self):
        """Met à jour le nombre de bibliothèques affiché"""
        if (self.user.libraries):
            if (len(self.user.libraries) - 1 < self.library_selected):
                self.library_selected = len(self.user.libraries) - 1
            self.library_number_label.setText(str(self.user.libraries[self.library_selected].position))
            self.library_name.setText(get_folder_name(self.user.libraries[self.library_selected].path))
        else:
            self.library_number_label.setText('N')
            self.library_name.setText("No library.")

    def updateRetroRecording(self):
        print("update Retro Recoring from record widget")
        if self.user.settings:
            if self.retro_time_selected > self.user.settings.pre_recording_seconds:
                self.retro_time_selected = self.user.settings.pre_recording_seconds
                self.updateRecordButtonDisplay()
            if self.user.settings.retro_recording_enabled:
                self.button_container.setStyleSheet(
                    "background: black; "
                    "border: 1px solid #40E0D0; "
                    "border-radius: 4px;"
                )
            else:
                self.recordButton.setText("")  # Supprime le texte
                self.recordButton.setIcon(qta.icon('fa5s.microphone', color='white'))
                self.button_container.setStyleSheet(
                    "background: black; "
                    "border: 1px solid white; "
                    "border-radius: 4px;"
                )


# ------------------------------------------------------------------------ Position de la fenetre
    def keep_on_top(self):
        """Assure que la fenêtre reste au premier plan."""
        self.raise_()

    def mousePressEvent(self, event):
        """Capture l'événement de clic sur la zone draggable."""
        if self.drag_area.geometry().contains(event.pos()):
            self.is_dragging = True
            self.drag_offset = event.pos()
            self.drag_area.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.is_dragging = False

    def mouseMoveEvent(self, event):
        """Déplace la fenêtre si on est en mode 'dragging'."""
        if self.is_dragging:
            delta = event.pos() - self.drag_offset
            self.move(self.pos() + delta)

    def mouseReleaseEvent(self, event):
        """Arrête le glissement de la fenêtre."""
        self.is_dragging = False
        self.drag_area.setCursor(Qt.CursorShape.OpenHandCursor)
    
    def enterEvent(self, event):
        """Augmente l'opacité lorsque la souris entre dans la fenêtre."""
        self.setWindowOpacity(0.8)  # Opacité à 100%
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Diminue l'opacité lorsque la souris quitte la fenêtre."""
        self.setWindowOpacity(0.5)  # Opacité à 50%
        super().leaveEvent(event)

    def updateRecordButtonDisplay(self):
        """Met à jour l'affichage du bouton en fonction du mode de rétro-enregistrement et de l'état d'enregistrement."""
        if self.user.recorder.is_recording:
            if self.retro_time_selected > 0:
                self.recordButton.setIcon(QIcon())
                self.recordButton.setText(str(self.retro_time_selected))
                self.recordButton.setStyleSheet(
                    "background: black; "
                    "color: red; "
                    "border: 1px solid red; "
                    "border-radius: 8px;"
                )
            else:
                self.recordButton.setIcon(qta.icon('fa5s.microphone', color='red'))
        else:
            if self.retro_time_selected > 0 and self.user.settings.retro_recording_enabled:
                # Si le rétro-enregistrement est activé, on affiche le temps restant
                self.recordButton.setIcon(QIcon())
                self.recordButton.setText(str(self.retro_time_selected))
                self.recordButton.setStyleSheet(
                    "background: black; "
                    "color: white; "
                    "border: 1px solid white; "
                    "border-radius: 8px;"
                )
            else:
                self.recordButton.setIcon(qta.icon('fa5s.microphone', color='white'))
                self.recordButton.setText("")  # Supprime le texte


    def animate_container(self, expand: bool):
        """Anime le conteneur pour qu'il s'étende vers la droite de 26 pixels ou revienne à sa taille initiale."""
        anim = QPropertyAnimation(self.button_container, b"geometry", self)
        animDragZone = QPropertyAnimation(self.drag_area, b"geometry", self)

        anim.setDuration(200)  # Durée de l'animation en ms
        animDragZone.setDuration(200)  # Durée de l'animation en ms

        start_geom = self.button_container.geometry()
        start_geomDragZone = self.drag_area.geometry()

        if expand:
            # Augmente la largeur du conteneur et décale la drag_area de 26 pixels vers la droite
            end_geom = QRect(
                self.base_geometry.x(),
                self.base_geometry.y(),
                self.base_geometry.width() + int(26  * self.scale),
                self.base_geometry.height()
            )
            end_geomDragZone = QRect(
                start_geomDragZone.x() + int(26 * self.scale),
                start_geomDragZone.y(),
                start_geomDragZone.width(),
                start_geomDragZone.height()
            )
        else:
            # Retour à la géométrie de base
            end_geom = self.base_geometry
            end_geomDragZone = self.drag_areaBase_geometry

        anim.setStartValue(start_geom)
        anim.setEndValue(end_geom)

        animDragZone.setStartValue(start_geomDragZone)
        animDragZone.setEndValue(end_geomDragZone)

        anim.start()
        animDragZone.start()

        self.current_animation = anim  # Conserver une référence
        self.current_animation_drag = animDragZone

    def _poll_worker(self):
        for msg, payload in self.user.recorder.poll():
            print(f"polling {msg} {payload}")
            if msg == 'started' or msg == 'stopped':
                # À chaque changement d’état on met à jour le bouton
                print("update record button display")
                self.updateRecordButtonDisplay()
            elif msg == 'done':
                self.newSampleRecorded.emit(payload)