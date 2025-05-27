# test.py
import os
# Désactive les logs qt.qpa.* (dont les messages OleInitialize)
# os.environ["QT_LOGGING_RULES"] = "qt.qpa.*=false"

import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFileDialog
)

class FolderSelector(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test Folder Selector")
        self.resize(400, 100)

        layout = QVBoxLayout(self)

        self.button = QPushButton("Sélectionner un dossier")
        self.label  = QLabel("Aucun dossier sélectionné")
        self.label.setWordWrap(True)

        layout.addWidget(self.button)
        layout.addWidget(self.label)

        self.button.clicked.connect(self.select_folder)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier",
            "",  # répertoire de départ
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self.label.setText(folder)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FolderSelector()
    window.show()
    sys.exit(app.exec())