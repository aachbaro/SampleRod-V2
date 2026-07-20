# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Boite a outils de petits widgets reutilisables par plusieurs ecrans.
#
# CLASSES (sommaire)
# - QListWidgetDragBugFix : liste Qt dont on peut reordonner les elements a
#   la souris ; corrige un bug Windows ou l'element glisse "disparaissait",
#   et previent le parent (updateLibraryOrder) pour sauvegarder le nouvel
#   ordre. Utilisee pour la liste des librairies dans les parametres.
# - CustomSlider : slider ameliore — un clic n'importe ou sur la barre
#   positionne directement le curseur a cet endroit (au lieu d'avancer pas
#   a pas), et la molette est desactivee pour eviter les changements
#   accidentels en scrollant la page.
# - SaveWaveformDialog : boite de dialogue "Enregistrer la forme d'onde" —
#   propose d'ecraser le fichier original ou d'enregistrer une copie sous
#   un nouveau nom ; choice() renvoie (ecraser?, nouveau_nom).
#
# LIENS CLES
# - frontend/settings_gui/libraries_list.py : utilise QListWidgetDragBugFix.
# - frontend/sample_gui/waveform/waveform_save.py : utilise SaveWaveformDialog.
# -----------------------------------------------------------------------------
# frontend/custom_widgets.py

from PySide6.QtWidgets import QListWidget, QSlider, QStyle
from PySide6.QtCore    import Qt
from PySide6.QtGui     import QDragMoveEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QLineEdit,
    QLabel, QDialogButtonBox, QFormLayout
)
import qtawesome as qta

class QListWidgetDragBugFix(QListWidget):
    """Liste reordonnables a la souris, avec contournement d'un bug Windows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, e: QDragEnterEvent):
        e.acceptProposedAction()

    def dragMoveEvent(self, e: QDragMoveEvent):
        # pour ne pas perdre l’item sous Windows
        row_under = self.row(self.itemAt(e.pos()))
        if ((row_under == self.currentRow() + 1) or
            (self.currentRow() == self.count() - 1 and row_under == -1)):
            e.ignore()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e: QDropEvent):
        """Replace l'element lache a sa nouvelle position, widget compris.

        On retire l'element de son ancienne ligne, on le reinsere a la
        ligne visee (ou en fin de liste si lache dans le vide), puis on
        remonte la hierarchie des parents pour trouver qui sait sauvegarder
        le nouvel ordre (methode updateLibraryOrder).
        """
        src_row = self.currentRow()
        dest_row = self.row(self.itemAt(e.pos()))
        if dest_row < 0:
            dest_row = self.count() - 1

        # on récupère l'item et son widget
        item = self.takeItem(src_row)
        widget = self.itemWidget(item)
        if widget:
            self.removeItemWidget(item)

        # on le ré‐insère à la bonne place
        self.insertItem(dest_row, item)
        if widget:
            self.setItemWidget(item, widget)

        self.setCurrentRow(dest_row)
        e.acceptProposedAction()

        # enfin on notifie qu’il faut re‐sauvegarder l’ordre
        parent = self.parent()
        while parent and not hasattr(parent, 'updateLibraryOrder'):
            parent = parent.parent()
        if parent:
            parent.updateLibraryOrder()

class CustomSlider(QSlider):
    """Slider clic-direct (sans molette) utilise pour les reglages audio."""

    def mousePressEvent(self, event):
        """Permet de positionner directement le slider là où on clique."""
        if self.orientation() == Qt.Orientation.Horizontal:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().x()),
                self.width(),
                self.invertedAppearance()
            )
        else:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().y()),
                self.height(),
                self.invertedAppearance()
            )

        self.setValue(value)
        self.sliderMoved.emit(value)
        super().mousePressEvent(event)
    def wheelEvent(self, event):
        # ignore les événements de molette pour éviter les changements accidentels
        event.ignore()


class SaveWaveformDialog(QDialog):
    """Dialogue 'ecraser ou copier ?' a la sauvegarde d'une forme d'onde."""

    def __init__(self, parent, default_name: str):
        super().__init__(parent)
        self.setWindowTitle("Enregistrer la forme d'onde")
        self.setModal(True)
        self.resize(400, 150)
        # --- Style global
        self.setStyleSheet("""
            QDialog { background-color: #2d2d2d; color: #ddd; border-radius: 8px; }
            QRadioButton, QLabel { font-size: 12px; }
            QLineEdit { background-color: #444; color: #eee; padding: 4px; border: 1px solid #666; border-radius: 4px; }
        """)

        layout = QVBoxLayout(self)

        # — Titre : icône + texte
        from PySide6.QtWidgets import QHBoxLayout
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.save', color='lightgray').pixmap(24, 24))
        text_label = QLabel("Choisissez une option d’enregistrement")
        text_label.setStyleSheet("font-size: 14px; color: #ddd;")
        title_layout = QHBoxLayout()
        title_layout.addWidget(icon_label)
        title_layout.addWidget(text_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # — Radio boutons
        self.rb_over = QRadioButton("Écraser le fichier original")
        self.rb_copy = QRadioButton("Enregistrer une copie")
        self.rb_over.setChecked(True)
        layout.addWidget(self.rb_over)
        layout.addWidget(self.rb_copy)

        # — Champ de saisie pour le nom (activé seulement si copy)
        form = QFormLayout()
        self.name_edit = QLineEdit(default_name)
        self.name_edit.setEnabled(False)
        form.addRow("Nom du nouveau fichier :", self.name_edit)
        layout.addLayout(form)
        self.rb_copy.toggled.connect(self.name_edit.setEnabled)

        # — Boutons OK / Annuler
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choice(self):
        """
        Retourne un tuple (overwrite: bool, new_name: str|None)
        """
        if self.exec() != QDialog.DialogCode.Accepted:
            return None, None
        if self.rb_over.isChecked():
            return True, None
        name = self.name_edit.text().strip()
        return False, name or self.name_edit.placeholderText()