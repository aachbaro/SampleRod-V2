from PyQt6.QtWidgets import QMainWindow, QPushButton, QWidget
from PyQt6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEvent, QRect
from PyQt6.QtGui import QIcon

class RecordWidgetWindow(QMainWindow):
    def __init__(self):
        super().__init__()

# ---------------------------------------------------------------------- Geometrie de la fenetre
        self.setWindowTitle("Record Widget")
        self.setGeometry(150, 150, 80, 40)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)              # Supprime la bordure de la fenêtre
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)      # Transparence de la fenêtre
        self.setStyleSheet("background: transparent;")                     # Fond transparent
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)  # Toujours au premier plan

        # 🔹 Timer pour forcer la fenêtre au premier plan
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.keep_on_top)
        self.timer.start(1000)
# ----------------------------------------------------------------------- Container a boutons

        self.button_container = QWidget(self)
        self.base_geometry = QRect(0, 0, 26, 26)
        self.button_container.setGeometry(self.base_geometry)
        self.button_container.setStyleSheet(
            "background: transparent; "
            "border: 1px solid white; "
            "border-radius: 4px;"
        )
        self.button_container.installEventFilter(self)  # Installer l'event filter pour le hover

        # 🔹 Bouton d'enregistrement placé à l'intérieur du conteneur
        self.recordButton = QPushButton(self.button_container)
        self.recordButton.setGeometry(4, 4, 18, 18)
        self.recordButton.setIcon(QIcon("ressources/microphone.png"))
        self.recordButton.setStyleSheet(
            "background: transparent; "
            "color: white; "
            "border: 1px solid white; "
            "border-radius: 8px;"
        )

# --------------------------------------------------------------------- Zone draggable

        self.drag_area = QWidget(self)
        self.drag_area.setGeometry(30, 5, 10, 20)
        self.drag_area.setStyleSheet("background: black;")
        self.is_dragging = False
        self.drag_offset = QPoint(0, 0)


# --------------------------------------------------------------------- Extension du container a bouton
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
        anim.setDuration(200)  # Durée de l'animation en ms
        start_geom = self.button_container.geometry()
        if expand:
            # Augmente la largeur de 26 pixels
            end_geom = QRect(
                self.base_geometry.x(),
                self.base_geometry.y(),
                self.base_geometry.width() + 26,
                self.base_geometry.height()
            )
        else:
            # Retour à la géométrie de base
            end_geom = self.base_geometry
        anim.setStartValue(start_geom)
        anim.setEndValue(end_geom)
        anim.start()
        self.current_animation = anim  # Conserver une référence


# --------------------------------------------------------------------- Position de la fenetre
    def keep_on_top(self):
        """Assure que la fenêtre reste au premier plan."""
        self.raise_()

    def mousePressEvent(self, event):
        """Capture l'événement de clic sur la zone draggable."""
        if self.drag_area.geometry().contains(event.pos()):
            self.is_dragging = True
            self.drag_offset = event.pos()
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
