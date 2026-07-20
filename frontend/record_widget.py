# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - La petite fenetre flottante "REC" toujours au premier plan : c'est la
#   telecommande d'enregistrement de SampleRod, utilisable par-dessus
#   n'importe quel autre logiciel.
# - Interactions (tout passe par la souris) :
#   * clic gauche sur REC      : demarrer / arreter l'enregistrement ;
#   * clic droit sur REC       : activer / desactiver le retro-enregistrement ;
#   * molette sur REC          : choisir combien de secondes de retro inclure
#                                dans la prochaine prise (0..duree max) ;
#   * molette sur la pastille  : changer de bibliotheque de destination ;
#   * clic sur la pastille     : afficher/cacher le nom de la bibliotheque ;
#   * glisser la zone de prise : deplacer la fenetre.
# - Couleurs du bouton : rouge = enregistrement en cours, couleur "retro" =
#   buffer retrospectif actif, bordure neutre sinon.
# - Interroge le RecorderService 10 fois par seconde (_poll_worker) pour
#   recuperer les evenements du processus d'enregistrement (fichier pret...).
#
# FONCTIONS (sommaire)
# - RecordWidgetWindow (QMainWindow)
#   - signal newSampleRecorded(path) : un nouveau fichier vient d'etre cree.
#   - _wire_signals()    : abonnements aux changements de reglages/etat.
#   - _start_timers()    : timer "rester au-dessus" (1 s) + polling (100 ms).
#   - eventFilter()      : toute la logique de clics/molette decrite ci-dessus.
#   - mousePress/Move/ReleaseEvent : deplacement de la fenetre a la souris.
#   - enter/leaveEvent   : opacite (plus visible au survol).
#   - _has_valid_library()/_rotate_library() : choix de la bibliotheque.
#   - _adjust_retro_time(): molette = retro time de la prochaine prise.
#   - _show_retro_context_menu() : menu clic-droit (toggle retro).
#   - updateLibraryCount()/updateRetroRecording()/updateRecordButtonDisplay():
#     rafraichissement des affichages (numero, couleurs, icone, tooltip).
#   - animate_container(): extension animee au survol (revele la poignee).
#   - keep_on_top()      : force la fenetre au premier plan.
#   - _poll_worker()     : lit les messages du recorder, emet newSampleRecorded.
#   - closeEvent()       : stoppe les timers.
#
# LIENS CLES
# - frontend/record_widget_ui.py : construction visuelle (RecordWidgetUIBuilder).
# - backend/services/recorder_service.py : start/stop/poll.
# - backend/services/settings_service.py : librairies, retro, durees.
# -----------------------------------------------------------------------------
# frontend/record_widget.py

import logging

from PySide6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEvent, QRect, QSize, Signal
from PySide6.QtGui import QIcon, QCursor
from PySide6.QtWidgets import QMainWindow, QMenu
import qtawesome as qta

from utils.utils import get_folder_name
from backend.models.AppContext import AppContext
from backend.services.notification_service import NotificationType
from frontend.styles import theme
from frontend.record_widget_ui import RecordWidgetUIBuilder

logger = logging.getLogger("record_widget")


class RecordWidgetWindow(QMainWindow):
    """Floating recorder control (always on top)."""

    newSampleRecorded = Signal(str)

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

        RecordWidgetUIBuilder(self).build()
        self._wire_signals()
        self._start_timers()

        self.updateLibraryCount()
        self.updateRetroRecording()
        self.updateRecordButtonDisplay()

    # ------------------------------------------------------------------ Setup
    def _wire_signals(self):
        self.settings.librariesChanged.connect(self.updateLibraryCount)
        self.settings.retroToggled.connect(self.updateRetroRecording)
        self.settings.preSecondsChanged.connect(self.updateRetroRecording)
        self.app_context.recorder.recordingStateChanged.connect(self._on_recording_state_changed)
        theme.manager.themeChanged.connect(self._on_theme_changed)

    def _start_timers(self):
        self.keep_top_timer = QTimer(self)
        self.keep_top_timer.timeout.connect(self.keep_on_top)
        self.keep_top_timer.start(1000)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_worker)
        self.poll_timer.start(100)

    def _apply_shell_style(self, hovered: bool = False):
        RecordWidgetUIBuilder.apply_shell_style(self, hovered)

    # ------------------------------------------------------------------ Events
    def eventFilter(self, source, event):
        """Centralise les interactions souris des sous-widgets.

        Un eventFilter permet d'intercepter les evenements des widgets
        enfants (bouton REC, pastille de bibliotheque, conteneur) sans
        devoir creer une sous-classe pour chacun. Renvoyer True = evenement
        consomme ; sinon on laisse Qt poursuivre le traitement normal.
        """
        # Survol du conteneur : extension animee + style "survole".
        if source == self.button_container:
            if event.type() == QEvent.Type.Enter:
                self._apply_shell_style(hovered=True)
                self.animate_container(expand=True)
            elif event.type() == QEvent.Type.Leave:
                self._apply_shell_style(hovered=False)
                self.animate_container(expand=False)

        # Pastille de bibliotheque : molette = changer, clic = voir le nom.
        if source == self.library_indicator:
            if event.type() == QEvent.Type.Wheel:
                delta = event.angleDelta().y()
                self._rotate_library(delta)
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                self.library_name.setVisible(not self.library_name.isVisible())
                return True

        # Bouton REC : gauche = start/stop, droit = menu retro, molette = retro time.
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

    def _on_theme_changed(self, _name: str):
        self._apply_shell_style()
        self.updateRecordButtonDisplay()

    def _show_retro_context_menu(self):
        p = theme.manager.p
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {p.BG_MEDIUM};
                color: {p.TEXT};
                border: 1px solid {p.BORDER_LIGHT};
            }}
            QMenu::item:selected {{
                background-color: {p.BG_CARD};
            }}
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
        p = theme.manager.p
        is_recording = self.app_context.recorder.is_recording
        is_retro = self.settings.isRetroEnabled()
        show_retro_value = is_retro and self.retro_time_selected > 0

        if is_recording:
            border     = p.RECORDING
            text_color = p.RECORDING
        else:
            border     = p.RETRO if is_retro else p.BORDER
            text_color = p.TEXT

        button_radius = max(1, self.recordButton.height() // 2)
        self.recordButton.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {p.BG};
                color: {text_color};
                border: 1px solid {border};
                border-radius: {button_radius}px;
                font-size: 11px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                border-color: {p.TEXT};
            }}
            """
        )

        if show_retro_value:
            self.recordButton.setIcon(QIcon())
            self.recordButton.setText(str(self.retro_time_selected))
        else:
            self.recordButton.setText("")
            dot_color = p.RECORDING if is_recording else p.TEXT
            self.recordButton.setIcon(qta.icon("fa5s.circle", color=dot_color))

        status = "Enregistrement en cours" if is_recording else "Pret"
        lib_name = self.library_name.text() if self.library_name.text() else "Aucune bibliotheque"
        self.recordButton.setToolTip(
            f"{status}\nBibliotheque: {lib_name}\n"
            "Clic gauche: start/stop\nClic droit: activer/desactiver retro\nMolette sur REC: retro time de la prise (0..duree max des Parametres)"
        )

    # ------------------------------------------------------------------ Animations / timers
    def animate_container(self, expand: bool):
        """Etend ou retracte la fenetre au survol (revele la poignee de prise).

        Au survol, le conteneur s'elargit d'un "slot" et la zone de prise
        (drag) se decale d'autant ; a la sortie, tout revient a la geometrie
        de base. Les deux animations sont gardees en attributs pour ne pas
        etre detruites par le ramasse-miettes avant la fin.
        """
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
        """Remonte la fenetre au premier plan (appele chaque seconde)."""
        self.raise_()

    def _poll_worker(self):
        """Lit les messages du recorder (10x/s) et signale les fichiers prets."""
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