# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Section Parametres du controle distant (serveur HTTP local).
# - Affiche etat, URL/QR code et actions de rafraichissement.
#
# LIENS CLES
# - backend/services/remote_control_service.py
# - backend/services/settings_service.py
# -----------------------------------------------------------------------------
# frontend/settings_gui/remote_control_settings.py

from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QFormLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from pathlib import Path
from io import BytesIO
import socket
import os
import logging

from backend.models.AppContext import AppContext
from backend.services.remote_control_service import RemoteControlService
from backend.services.notification_service import NotificationType

logger = logging.getLogger("remote_control_settings")

try:
    import qrcode
    from PIL import Image as PILImage
    _HAS_QR = True
except Exception:
    qrcode = None
    PILImage = None
    _HAS_QR = False

class RemoteControlSettingsWidget(QWidget):
    """
    Widget de configuration pour le controle distant (serveur HTTP local).
    - Toggle on/off
    - Affiche l'etat et les URLs utiles (LAN + local)
    """

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.settings = self.app_context.settings

        self._build_ui()
        self._load_state()

        # Si l'etat change ailleurs, on se resynchronise
        self.settings.remoteControlToggled.connect(self._on_service_toggled)
        self.settings.remoteControlPortChanged.connect(self._update_status_labels)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Toggle + refresh
        top_row = QHBoxLayout()
        self.enable_checkbox = QCheckBox("Activer le controle distant")
        self.enable_checkbox.toggled.connect(self._on_toggle)
        self.refresh_button = QPushButton("Rafraichir")
        self.refresh_button.clicked.connect(self._update_status_labels)
        top_row.addWidget(self.enable_checkbox)
        top_row.addStretch()
        top_row.addWidget(self.refresh_button)
        layout.addLayout(top_row)

        # Formulaire d'info
        form = QFormLayout()
        self.status_label = QLabel()
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.listen_label = QLabel()
        self.listen_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.url_lan_label = QLabel()
        self.url_lan_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.url_local_label = QLabel()
        self.url_local_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        form.addRow(QLabel("Etat :"), self.status_label)
        form.addRow(QLabel("Ecoute :"), self.listen_label)
        form.addRow(QLabel("URL LAN :"), self.url_lan_label)
        form.addRow(QLabel("URL local :"), self.url_local_label)
        layout.addLayout(form)

        # QR code
        qr_row = QHBoxLayout()
        qr_title = QLabel("QR code :")
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(140, 140)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("background: #f5f5f5; border: 1px solid #ddd;")
        qr_row.addWidget(qr_title)
        qr_row.addWidget(self.qr_label)
        qr_row.addStretch()
        layout.addLayout(qr_row)

        # Petit hint
        self.hint_label = QLabel(
            "Depuis le telephone, ouvre l'URL LAN ci-dessus "
            "(meme reseau Wi-Fi)."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #6b6b6b;")
        layout.addWidget(self.hint_label)
        layout.addStretch()

    # ------------------------------------------------------------------ State
    def _load_state(self):
        enabled = self.settings.isRemoteControlEnabled()
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(enabled)
        self.enable_checkbox.blockSignals(False)

        if enabled:
            self._ensure_running()

        self._update_status_labels()

    def _on_service_toggled(self, enabled: bool):
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(enabled)
        self.enable_checkbox.blockSignals(False)
        if enabled:
            self._ensure_running()
        else:
            self._stop_server()
        self._update_status_labels()

    def _on_toggle(self, checked: bool):
        self.settings.setRemoteControlEnabled(checked)
        if checked:
            started = self._ensure_running()
            if not started:
                # revert toggle if start failed
                self.settings.setRemoteControlEnabled(False)
                self.enable_checkbox.blockSignals(True)
                self.enable_checkbox.setChecked(False)
                self.enable_checkbox.blockSignals(False)
        else:
            self._stop_server()
        self._update_status_labels()

    # ------------------------------------------------------------------ Server ops
    def _ensure_running(self) -> bool:
        svc = self.app_context.remote_control
        if svc is None:
            repo_root = Path(__file__).resolve().parents[2]
            ui_root = repo_root / "frontend" / "remote_ui"
            svc = RemoteControlService(
                app_context=self.app_context,
                host=os.getenv("REMOTE_CONTROL_HOST", "0.0.0.0"),
                port=self.settings.getRemoteControlPort(),
                allow_origin=os.getenv("REMOTE_CONTROL_CORS", "*"),
                auth_token=os.getenv("REMOTE_CONTROL_TOKEN"),
                ui_root=ui_root,
                auto_build_ui=True,
            )
            self.app_context.remote_control = svc
            try:
                if not getattr(svc, "_signals_hooked", False):
                    self.app_context.recorder.recordingStateChanged.connect(
                        svc.push_status
                    )
                    self.app_context.sample_store.sampleAdded.connect(
                        svc.push_sample_added
                    )
                    self.app_context.sample_store.sampleDeleted.connect(
                        svc.push_sample_deleted
                    )
                    self.app_context.sample_store.sampleRenamed.connect(
                        svc.push_sample_renamed
                    )
                    self.app_context.settings.retroToggled.connect(
                        svc.push_status
                    )
                    self.app_context.settings.preSecondsChanged.connect(
                        svc.push_status
                    )
                    try:
                        self.app_context.screenshots.screenshotAdded.connect(
                            svc.push_screenshot_added
                        )
                        self.app_context.screenshots.screenshotDeleted.connect(
                            svc.push_screenshot_deleted
                        )
                    except Exception:
                        pass
                    svc._signals_hooked = True
            except Exception:
                pass

        if svc.is_running:
            return True

        try:
            svc.prepare_static()
            svc.start()
            return True
        except Exception as exc:
            logger.exception("[RemoteControlSettings] Demarrage impossible")
            try:
                self.app_context.notifications.notify(
                    title="Controle distant",
                    message=f"Demarrage impossible: {exc}",
                    type=NotificationType.ERROR,
                )
            except Exception:
                pass
            return False

    def _stop_server(self):
        svc = self.app_context.remote_control
        if svc and svc.is_running:
            try:
                svc.stop()
            except Exception:
                logger.exception("[RemoteControlSettings] Arret impossible")

    # ------------------------------------------------------------------ UI updates
    def _update_status_labels(self):
        svc = self.app_context.remote_control
        running = bool(svc and svc.is_running)

        self.status_label.setText("Actif" if running else "Arrete")
        self.status_label.setStyleSheet("color: #2f8f2f;" if running else "color: #9a2f2f;")

        host = self._get_host()
        port = self._get_port()
        self.listen_label.setText(f"{host}:{port}")

        lan_ip = self._get_lan_ip()
        url_lan = f"http://{lan_ip}:{port}"
        self.url_lan_label.setText(url_lan)
        self.url_local_label.setText(f"http://127.0.0.1:{port}")
        self._update_qr_code(url_lan, running)

    def _get_host(self) -> str:
        svc = self.app_context.remote_control
        if svc:
            return svc.host
        return os.getenv("REMOTE_CONTROL_HOST", "0.0.0.0")

    def _get_port(self) -> int:
        svc = self.app_context.remote_control
        if svc:
            return svc.port
        return self.settings.getRemoteControlPort()

    def _get_lan_ip(self) -> str:
        # Methode robuste pour recuperer l'IP locale reelle
        ip = "127.0.0.1"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        except Exception:
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                ip = "127.0.0.1"
        finally:
            try:
                sock.close()
            except Exception:
                pass
        return ip

    def _update_qr_code(self, url: str, running: bool):
        if not _HAS_QR:
            self.qr_label.setPixmap(QPixmap())
            self.qr_label.setText("QR indisponible\n(installe qrcode)")
            return
        if not running:
            self.qr_label.setPixmap(QPixmap())
            self.qr_label.setText("Active le\nserveur")
            return

        try:
            qr = qrcode.QRCode(box_size=4, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            # qrcode peut renvoyer un wrapper PilImage, on recupere l'image PIL
            if hasattr(img, "get_image"):
                img = img.get_image()
            if PILImage and not isinstance(img, PILImage.Image):
                img = PILImage.fromarray(img)
            img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="PNG")
            pix = QPixmap()
            pix.loadFromData(buf.getvalue(), "PNG")
            self.qr_label.setPixmap(pix)
            self.qr_label.setText("")
        except Exception:
            logger.exception("[RemoteControlSettings] QR generation failed")
            self.qr_label.setPixmap(QPixmap())
            self.qr_label.setText("QR erreur")
