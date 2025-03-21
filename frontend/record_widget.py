from PyQt6.QtWidgets import QMainWindow, QPushButton, QWidget, QLabel
from PyQt6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEvent, QRect, QSize
from PyQt6.QtGui import QIcon
import qtawesome as qta

class RecordWidgetWindow(QMainWindow):
    def __init__(self):
        super().__init__()

# ------------------------------------------------------------------------ Geometrie de la fenetre
        self.setWindowTitle("Record Widget")
        self.setGeometry(150, 150, 80, 40)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)              # Supprime la bordure de la fenêtre
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)      # Transparence de la fenêtre
        self.setStyleSheet("background: transparent;")                     # Fond transparent
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)  # Toujours au premier plan
        self.setWindowOpacity(0.5)

        # 🔹 Timer pour forcer la fenêtre au premier plan
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.keep_on_top)
        self.timer.start(1000)
# ------------------------------------------------------------------------ Container a boutons

        self.button_container = QWidget(self)
        self.base_geometry = QRect(0, 0, 26, 26)
        self.button_container.setGeometry(self.base_geometry)
        self.button_container.setStyleSheet(
            "background: transparent; "
            "opacity: 10%;"
            "border: 1px solid white; "
            "border-radius: 4px;"
        )
        self.button_container.installEventFilter(self)  # Installer l'event filter pour le hover

        # ----- Bouton d'enregistrement placé à l'intérieur du conteneur

        self.recordButton = QPushButton(self.button_container)
        self.recordButton.setGeometry(4, 4, 18, 18)
        self.recordButton.setIcon(qta.icon('fa5s.microphone', color='white'))
        self.recordButton.setIconSize(QSize(14, 14))
        self.recordButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recordButton.setStyleSheet(
            "background: transparent; "
            "color: white; "
            "border: 1px solid white; "
            "border-radius: 8px;"
        )

        # ----- Indicateur de repertoire

        self.library_indicator = QLabel(self.button_container)
        self.library_indicator.setGeometry(26, 0, 26, 26)
        self.library_indicator.setPixmap(qta.icon('fa5s.folder', color='white').pixmap(20, 23))
        self.library_indicator.setCursor(Qt.CursorShape.SplitVCursor)

        self.library_number_label = QLabel(self.library_indicator)
        self.library_number_label.setGeometry(3, 2, 25, 25)  # Positionner le label à l'intérieur du `library_indicator`
        self.library_number_label.setStyleSheet(
            "background: transparent; "
            "color: black; "
            "border: none; "
            "font-size: 14px; "
            "text-align: center;"
        )
        self.library_number_label.setText("10") 

        self.library_indicator.setStyleSheet(
            "background: transparent; "
            "color: white; "
            "border: none; "
        )


# ------------------------------------------------------------------------ Zone draggable

        self.drag_area = QLabel(self)
        self.drag_areaBase_geometry = QRect(30, 0, 10, 26)
        self.drag_area.setGeometry(30, 0, 10, 26)
        self.drag_area.setPixmap(qta.icon('fa5s.ellipsis-v', color='white').pixmap(10, 20))
        self.drag_area.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_area.setStyleSheet(
            "background: transparent;"
            "font-size: 1x;"    
        )
        self.is_dragging = False
        self.drag_offset = QPoint(0, 0)


# ------------------------------------------------------------------------ Extension du container a bouton
    def eventFilter(self, source, event):
        if source == self.button_container:
            if event.type() == QEvent.Type.Enter:
                self.animate_container(expand=True)
            elif event.type() == QEvent.Type.Leave:
                self.animate_container(expand=False)
        return super().eventFilter(source, event)

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
                self.base_geometry.width() + 26,
                self.base_geometry.height()
            )
            end_geomDragZone = QRect(
                start_geomDragZone.x() + 26,
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
