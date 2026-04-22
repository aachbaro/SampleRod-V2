# -----------------------------------------------------------------------------
# ROLE DANS L'ARCHITECTURE
# - Petit serveur HTTP local pour piloter l'application depuis un navigateur
#   (ex: page React sur mobile) sans toucher a l'UI principale.
# - Sert de "second frontend" qui envoie des commandes simples (start/stop)
#   vers le RecorderService.
#
# CE QUI EST DEJA EN PLACE
# - Serveur HTTP standard library (pas de dependance externe).
# - Serveur statique pour les fichiers React (dist).
# - Build auto si dist manquant ou plus vieux que src (npm run build).
# - Endpoints JSON:
#   - GET  /health          -> etat du service
#   - GET  /record/status   -> statut du recorder
#   - GET  /libraries       -> liste des librairies disponibles
#   - POST /record/start    -> demarrer un enregistrement
#   - POST /record/stop     -> arreter l'enregistrement
# - CORS simple (pour acces depuis un navigateur).
# - Option de securite via token (X-Api-Key ou Authorization: Bearer).
#
# CE QUI RESTE A IMPLEMENTER (IDEES)
# - Authentification plus robuste (token rotatif, pin, pairing QR).
# - HTTPS local (certificat auto-signe) si besoin.
# - WebSocket pour etat temps reel (vu/confirmation).
# - Rate limiting / anti-spam.
# - Journal d'audit (qui a lance quoi, quand).
# - Endpoints supplementaires (pause, mark, metadonnees, hotkeys).
#
# NOTES
# - Par defaut, on peut ecouter sur 0.0.0.0 pour le reseau local.
#   Pense a limiter l'acces (token) si tu ouvres le port.
# - Ce service peut etre demarre au lancement de l'app, puis stop a la fermeture.
# - Les commandes appellent RecorderService directement (thread serveur).
#   Si besoin, passe un dispatcher pour executer dans le thread UI.
# -----------------------------------------------------------------------------
# backend/services/remote_control_service.py

"""
Service HTTP local pour controler l'enregistrement a distance.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any, Callable, Dict, Optional
from pathlib import Path
import json
import logging
import mimetypes
import shutil
import os
import subprocess
import threading
import time
import queue

logger = logging.getLogger("remote_control_service")


class RemoteControlService:
    """
    Demarre un serveur HTTP dans un thread dedie et route des commandes JSON
    vers les services backend (ex: RecorderService).

    Parametres principaux:
    - host/port        : interface d'ecoute (0.0.0.0 pour LAN)
    - allow_origin     : CORS (ex: "*" ou "http://IP:PORT")
    - auth_token       : si defini, exige un token dans les headers
    - dispatch         : optionnel, permet d'executer une action dans un thread
                         specifique (ex: thread UI Qt).
    """

    def __init__(
        self,
        app_context,
        host: str = "0.0.0.0",
        port: int = 8765,
        allow_origin: str = "*",
        auth_token: Optional[str] = None,
        dispatch: Optional[Callable[[Callable[[], None]], None]] = None,
        ui_root: Optional[Path] = None,
        static_dir: Optional[Path] = None,
        auto_build_ui: bool = False,
    ):
        self.app_context = app_context
        self.host = host
        self.port = port
        self.allow_origin = allow_origin
        self.auth_token = auth_token
        self._dispatch = dispatch
        self.ui_root = Path(ui_root).resolve() if ui_root else None
        self.static_dir = Path(static_dir).resolve() if static_dir else None
        self.auto_build_ui = auto_build_ui

        # Etat interne du serveur
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # SSE clients (queues)
        self._sse_clients: list[queue.Queue] = []
        self._sse_lock = threading.Lock()
        # Historique local des samples (session)
        self._sample_history: list[Dict[str, Any]] = []
        self._sample_history_max = 50
        self._history_lock = threading.Lock()

    # ------------------------------------------------------------------ Lifecycle
    def start(self) -> None:
        """Demarre le serveur HTTP en thread daemon."""
        if self._running:
            return

        # Preparer les fichiers statiques (build + chemin dist)
        self.prepare_static()

        handler_cls = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler_cls)
        # Injection d'un pointeur vers le service pour le handler
        self._server.service = self  # type: ignore[attr-defined]

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="RemoteControlHTTP",
            daemon=True,
        )
        self._thread.start()
        self._running = True
        logger.info("[RemoteControl] Server started on %s:%s", self.host, self.port)

    def stop(self) -> None:
        """Arrete proprement le serveur HTTP."""
        if not self._running or self._server is None:
            return
        logger.info("[RemoteControl] Server stopping...")
        self._close_sse_clients()
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        logger.info("[RemoteControl] Server stopped")

    @property
    def is_running(self) -> bool:
        """True si le serveur est actif."""
        return self._running

    # ------------------------------------------------------------------ Static UI
    def prepare_static(self) -> None:
        """
        Prepare la UI statique (React build). Si auto_build_ui est actif,
        on rebuilde uniquement si dist est absent ou plus vieux que src.
        """
        if self.ui_root:
            dist_dir = self.ui_root / "dist"
            if self.auto_build_ui:
                try:
                    if self._is_build_needed(self.ui_root, dist_dir):
                        self._build_ui(self.ui_root)
                except Exception:
                    logger.exception("[RemoteControl] UI build failed")
            if dist_dir.exists():
                self.static_dir = dist_dir

    def _is_build_needed(self, ui_root: Path, dist_dir: Path) -> bool:
        if not dist_dir.exists():
            return True

        src_dir = ui_root / "src"
        # Fichiers importants hors src
        watch_files = [
            ui_root / "index.html",
            ui_root / "package.json",
            ui_root / "package-lock.json",
            ui_root / "vite.config.js",
            ui_root / "vite.config.ts",
        ]

        src_latest = max(
            self._latest_mtime(src_dir),
            *[self._latest_mtime(p) for p in watch_files],
        )
        dist_latest = self._latest_mtime(dist_dir)
        return src_latest > dist_latest

    def _latest_mtime(self, path: Path) -> float:
        if not path.exists():
            return 0.0
        if path.is_file():
            return path.stat().st_mtime
        latest = 0.0
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    latest = max(latest, p.stat().st_mtime)
                except Exception:
                    pass
        return latest

    def _build_ui(self, ui_root: Path) -> None:
        """
        Lance npm install (si node_modules absent) puis npm run build.
        Ne lance rien si npm n'est pas disponible.
        """
        logger.info("[RemoteControl] UI build check...")
        if not (ui_root / "package.json").exists():
            logger.info("[RemoteControl] No package.json, skip UI build")
            return
        npm_exe = shutil.which("npm")
        if npm_exe is None:
            logger.warning("[RemoteControl] npm not found in PATH. Install Node.js to enable UI build.")
            return

        node_modules = ui_root / "node_modules"
        if not node_modules.exists():
            logger.info("[RemoteControl] npm install...")
            subprocess.run([npm_exe, "install"], cwd=str(ui_root), check=True)

        logger.info("[RemoteControl] npm run build...")
        subprocess.run([npm_exe, "run", "build"], cwd=str(ui_root), check=True)
        # Laisse au FS une micro-fenetre pour ecrire les timestamps
        time.sleep(0.1)

    # ------------------------------------------------------------------ HTTP Routing
    def _make_handler(self):
        """Cree une classe Handler liee a cette instance (closure)."""
        service = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            # Raccourci pour eviter du bruit dans la console
            def log_message(self, fmt: str, *args: Any) -> None:
                logger.info("[RemoteControl] " + fmt, *args)

            def handle(self) -> None:
                try:
                    super().handle()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    # Le client a ferme la connexion (normal avec SSE/reload)
                    return

            def do_OPTIONS(self) -> None:
                service._handle_options(self)

            def do_GET(self) -> None:
                service._handle_request(self, method="GET")

            def do_POST(self) -> None:
                service._handle_request(self, method="POST")

        return _Handler

    def _handle_options(self, handler: BaseHTTPRequestHandler) -> None:
        """Repond aux preflight CORS."""
        handler.send_response(204)
        self._send_cors_headers(handler)
        handler.end_headers()

    def _handle_request(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        """Router minimaliste pour les endpoints REST."""
        path = urlparse(handler.path).path

        # Auth simple si token defini
        if not self._authorize(handler):
            return

        # Fichiers statiques (React) - seulement si ce n'est pas une route API
        if not self._is_api_path(path):
            if method == "GET" and self._try_serve_static(handler, path):
                return

        if method == "GET" and path == "/health":
            self._send_json(handler, 200, {"status": "ok", "service": "remote-control"})
            return

        if method == "GET" and path == "/record/status":
            self._send_json(handler, 200, self._build_status_payload())
            return

        if method == "GET" and path == "/events":
            self._handle_sse(handler)
            return

        if method == "GET" and path == "/samples/history":
            with self._history_lock:
                samples = list(self._sample_history)
            self._send_json(handler, 200, {"samples": samples})
            return

        if method == "GET" and path == "/libraries":
            self._send_json(handler, 200, self._build_libraries_payload())
            return

        if path.startswith("/screenshots"):
            handled = self._handle_screenshots_route(handler, method, path)
            if handled:
                return

        if method == "POST" and path == "/record/start":
            payload = self._read_json(handler)
            if payload is None:
                return
            response = self._handle_start(payload)
            self._send_json(handler, response["code"], response["body"])
            return

        if method == "POST" and path == "/record/stop":
            response = self._handle_stop()
            self._send_json(handler, response["code"], response["body"])
            return

        if path.startswith("/samples/"):
            handled = self._handle_samples_route(handler, method, path)
            if handled:
                return

        # Endpoint inconnu
        self._send_json(handler, 404, {"error": "not_found", "path": path})

    # ------------------------------------------------------------------ Payload builders
    def _build_status_payload(self) -> Dict[str, Any]:
        """Construit le JSON de statut a partir du RecorderService."""
        recorder = self.app_context.recorder
        return {
            "is_recording": bool(getattr(recorder, "is_recording", False)),
            "retro_enabled": bool(getattr(recorder, "retro_enabled", False)),
            "pre_seconds": int(getattr(recorder, "pre_seconds", 0)),
        }

    def _build_libraries_payload(self) -> Dict[str, Any]:
        """Expose les librairies connues pour selection dans le frontend."""
        libs = getattr(self.app_context.settings, "libraries", []) or []
        libraries = []
        for lib in libs:
            # SampleBank expose to_dict()
            if hasattr(lib, "to_dict"):
                libraries.append(lib.to_dict())
            else:
                libraries.append({"id": getattr(lib, "id", None), "path": getattr(lib, "path", "")})
        return {"libraries": libraries}

    def _get_sample_by_id(self, sample_id: int):
        samples = self.app_context.sample_store.get_cached()
        return next((s for s in samples if s.id == sample_id), None)

    def _get_screenshot_by_id(self, item_id: int):
        svc = getattr(self.app_context, "screenshots", None)
        if not svc:
            return None
        items = svc.list_items()
        return next((i for i in items if int(i.get("id", -1)) == item_id), None)

    def _sample_to_dict(self, sample) -> Dict[str, Any]:
        created_at = getattr(sample, "created_at", None)
        created_iso = created_at.isoformat() if created_at else None
        analyzed_at = getattr(sample, "analyzed_at", None)
        analyzed_iso = analyzed_at.isoformat() if analyzed_at else None
        return {
            "id": sample.id,
            "name": sample.name,
            "path": sample.path,
            "duration": float(getattr(sample, "duration", 0)),
            "created_at": created_iso,
            "missing": bool(getattr(sample, "missing", False)),
            "rms_level": getattr(sample, "rms_level", None),
            "analyzed_at": analyzed_iso,
        }

    def _add_to_history(self, sample_dict: Dict[str, Any]) -> None:
        with self._history_lock:
            self._sample_history = [
                s for s in self._sample_history if s.get("id") != sample_dict.get("id")
            ]
            self._sample_history.insert(0, sample_dict)
            if len(self._sample_history) > self._sample_history_max:
                self._sample_history = self._sample_history[: self._sample_history_max]

    # ------------------------------------------------------------------ Commands
    def _handle_start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Valide la requete puis lance l'enregistrement."""
        output_folder = self._resolve_output_folder(payload)
        if not output_folder:
            return {
                "code": 400,
                "body": {"error": "missing_library", "detail": "library_path or library_id required"},
            }

        retro_time = payload.get("retro_time")
        if retro_time is None:
            retro_time = getattr(self.app_context.recorder, "pre_seconds", 0)

        # Appel effectif vers le RecorderService
        self._execute(self.app_context.recorder.start, output_folder, retro_time)

        return {
            "code": 202,
            "body": {
                "status": "accepted",
                "action": "start",
                "output_folder": output_folder,
                "retro_time": retro_time,
            },
        }

    def _handle_stop(self) -> Dict[str, Any]:
        """Arrete l'enregistrement en cours."""
        self._execute(self.app_context.recorder.stop)
        return {"code": 202, "body": {"status": "accepted", "action": "stop"}}

    def _handle_samples_route(self, handler: BaseHTTPRequestHandler, method: str, path: str) -> bool:
        parts = path.strip("/").split("/")
        if len(parts) < 2 or parts[0] != "samples":
            return False

        # /samples/{id}/audio
        if len(parts) == 3 and parts[2] == "audio" and method == "GET":
            sample_id = self._parse_sample_id(parts[1])
            if sample_id is None:
                self._send_json(handler, 400, {"error": "invalid_sample_id"})
                return True
            sample = self._get_sample_by_id(sample_id)
            if not sample or not os.path.isfile(sample.path):
                self._send_json(handler, 404, {"error": "sample_not_found"})
                return True
            self._send_file(handler, Path(sample.path))
            return True

        # /samples/{id}/download
        if len(parts) == 3 and parts[2] == "download" and method == "GET":
            sample_id = self._parse_sample_id(parts[1])
            if sample_id is None:
                self._send_json(handler, 400, {"error": "invalid_sample_id"})
                return True
            sample = self._get_sample_by_id(sample_id)
            if not sample or not os.path.isfile(sample.path):
                self._send_json(handler, 404, {"error": "sample_not_found"})
                return True
            filename = os.path.basename(sample.path)
            self._send_file(handler, Path(sample.path), download_name=filename)
            return True

        # /samples/{id}/rename
        if len(parts) == 3 and parts[2] == "rename" and method == "POST":
            sample_id = self._parse_sample_id(parts[1])
            if sample_id is None:
                self._send_json(handler, 400, {"error": "invalid_sample_id"})
                return True
            payload = self._read_json(handler)
            if payload is None:
                return True
            new_name = str(payload.get("name", "")).strip()
            if not new_name:
                self._send_json(handler, 400, {"error": "missing_name"})
                return True
            sample = self._get_sample_by_id(sample_id)
            if not sample:
                self._send_json(handler, 404, {"error": "sample_not_found"})
                return True

            # Renommage via SampleService
            self.app_context.sample_store.rename(sample_id, new_name)
            updated = self._get_sample_by_id(sample_id)
            if not updated or updated.name != new_name:
                self._send_json(handler, 500, {"error": "rename_failed"})
                return True

            sample_dict = self._sample_to_dict(updated)
            self._add_to_history(sample_dict)
            self._broadcast_event("sample_renamed", sample_dict)
            self._send_json(handler, 200, {"status": "ok", "sample": sample_dict})
            return True

        # /samples/{id}/delete
        if len(parts) == 3 and parts[2] == "delete" and method == "POST":
            sample_id = self._parse_sample_id(parts[1])
            if sample_id is None:
                self._send_json(handler, 400, {"error": "invalid_sample_id"})
                return True
            sample = self._get_sample_by_id(sample_id)
            if not sample:
                self._send_json(handler, 404, {"error": "sample_not_found"})
                return True
            self.app_context.sample_store.delete(sample_id)
            with self._history_lock:
                self._sample_history = [
                    s for s in self._sample_history if s.get("id") != sample_id
                ]
            self._broadcast_event("sample_deleted", {"id": sample_id})
            self._send_json(handler, 200, {"status": "ok"})
            return True

        return False

    def _handle_screenshots_route(self, handler: BaseHTTPRequestHandler, method: str, path: str) -> bool:
        parts = path.strip("/").split("/")
        if len(parts) < 2 or parts[0] != "screenshots":
            return False

        svc = getattr(self.app_context, "screenshots", None)
        if not svc:
            self._send_json(handler, 501, {"error": "screenshot_service_unavailable"})
            return True

        # /screenshots/list
        if len(parts) == 2 and parts[1] == "list" and method == "GET":
            items = svc.list_items()
            # plus recentes d'abord
            items = list(reversed(items))
            # limit optionnel
            try:
                query = urlparse(handler.path).query
                limit = None
                if query:
                    for kv in query.split("&"):
                        if kv.startswith("limit="):
                            limit = int(kv.split("=", 1)[1])
                            break
                if limit:
                    items = items[:limit]
            except Exception:
                pass
            self._send_json(handler, 200, {"items": items})
            return True

        # /screenshots/screens
        if len(parts) == 2 and parts[1] == "screens" and method == "GET":
            self._send_json(handler, 200, {"screens": svc.list_screens()})
            return True

        # /screenshots/capture
        if len(parts) == 2 and parts[1] == "capture" and method == "POST":
            payload = self._read_json(handler)
            if payload is None:
                return True
            screen_index = payload.get("screen_index")
            try:
                screen_index = int(screen_index) if screen_index is not None else None
            except Exception:
                screen_index = None
            meta = svc.capture(screen_index=screen_index)
            if not meta:
                self._send_json(handler, 400, {"error": "capture_failed"})
                return True
            self._send_json(handler, 200, {"status": "ok", "item": meta})
            return True

        # /screenshots/rename
        if len(parts) == 2 and parts[1] == "rename" and method == "POST":
            payload = self._read_json(handler)
            if payload is None:
                return True
            raw_id = payload.get("id")
            new_name = str(payload.get("name", "")).strip()
            item_id = self._parse_int(raw_id)
            if item_id is None or not new_name:
                self._send_json(handler, 400, {"error": "invalid_payload"})
                return True
            meta = svc.rename(item_id, new_name)
            if not meta:
                self._send_json(handler, 404, {"error": "item_not_found"})
                return True
            self._send_json(handler, 200, {"status": "ok", "item": meta})
            return True

        # /screenshots/delete
        if len(parts) == 2 and parts[1] == "delete" and method == "POST":
            payload = self._read_json(handler)
            if payload is None:
                return True
            item_id = self._parse_int(payload.get("id"))
            if item_id is None:
                self._send_json(handler, 400, {"error": "invalid_payload"})
                return True
            ok = svc.delete(item_id)
            if not ok:
                self._send_json(handler, 404, {"error": "item_not_found"})
                return True
            self._send_json(handler, 200, {"status": "ok"})
            return True

        # /screenshots/file/{id}
        if len(parts) == 3 and parts[1] == "file" and method == "GET":
            item_id = self._parse_int(parts[2])
            if item_id is None:
                self._send_json(handler, 400, {"error": "invalid_id"})
                return True
            path_str = svc.get_path(item_id)
            if not path_str or not os.path.isfile(path_str):
                self._send_json(handler, 404, {"error": "item_not_found"})
                return True
            self._send_file(handler, Path(path_str))
            return True

        return False

    # ------------------------------------------------------------------ Helpers
    def _execute(self, func: Callable[..., None], *args: Any) -> None:
        """
        Execute une action soit directement, soit via un dispatcher.
        Utile si tu veux tout rerouter dans le thread UI (Qt).
        """
        if self._dispatch:
            self._dispatch(lambda: func(*args))
        else:
            func(*args)

    def _resolve_output_folder(self, payload: Dict[str, Any]) -> Optional[str]:
        """Trouve un dossier de sortie valide a partir du payload JSON."""
        # 1) Chemin direct
        for key in ("output_folder", "library_path", "path"):
            if key in payload and isinstance(payload[key], str):
                candidate = payload[key].strip()
                if candidate and os.path.isdir(candidate):
                    return candidate

        # 2) Resolution via library_id
        lib_id = payload.get("library_id")
        if lib_id is not None:
            libs = getattr(self.app_context.settings, "libraries", []) or []
            for lib in libs:
                if getattr(lib, "id", None) == lib_id and os.path.isdir(getattr(lib, "path", "")):
                    return lib.path

        # 3) Fallback: premiere librairie disponible
        libs = getattr(self.app_context.settings, "libraries", []) or []
        if libs:
            first = libs[0]
            if os.path.isdir(getattr(first, "path", "")):
                return first.path

        return None

    def _parse_sample_id(self, raw: str) -> Optional[int]:
        try:
            return int(raw)
        except Exception:
            return None

    def _parse_int(self, raw: Any) -> Optional[int]:
        try:
            return int(raw)
        except Exception:
            return None

    def _read_json(self, handler: BaseHTTPRequestHandler) -> Optional[Dict[str, Any]]:
        """Lit le body JSON. Retourne None si invalide (reponse 400)."""
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = handler.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(handler, 400, {"error": "invalid_json"})
            return None

    def _authorize(self, handler: BaseHTTPRequestHandler) -> bool:
        """Verifie le token si l'auth est activee."""
        if not self.auth_token:
            return True

        header_token = handler.headers.get("X-Api-Key")
        auth_header = handler.headers.get("Authorization", "")
        bearer = auth_header.replace("Bearer", "").strip() if auth_header else ""

        if header_token == self.auth_token or bearer == self.auth_token:
            return True

        self._send_json(handler, 401, {"error": "unauthorized"})
        return False

    def _send_cors_headers(self, handler: BaseHTTPRequestHandler) -> None:
        """Ajoute les headers CORS indispensables."""
        handler.send_header("Access-Control-Allow-Origin", self.allow_origin)
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Api-Key",
        )

    def _send_json(
        self,
        handler: BaseHTTPRequestHandler,
        status_code: int,
        payload: Dict[str, Any],
    ) -> None:
        """Envoie une reponse JSON propre avec headers CORS."""
        body = json.dumps(payload).encode("utf-8")
        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        self._send_cors_headers(handler)
        handler.end_headers()
        handler.wfile.write(body)

    # ------------------------------------------------------------------ SSE (Server-Sent Events)
    def push_status(self) -> None:
        """Envoie un event SSE 'status' aux clients connectes."""
        self._broadcast_event("status", self._build_status_payload())

    def push_sample_added(self, sample_id: int) -> None:
        """Envoie un event SSE 'sample_added' et ajoute a l'historique."""
        sample = self._get_sample_by_id(sample_id)
        if not sample:
            return
        sample_dict = self._sample_to_dict(sample)
        self._add_to_history(sample_dict)
        self._broadcast_event("sample_added", sample_dict)

    def push_sample_deleted(self, sample_id: int) -> None:
        """Envoie un event SSE 'sample_deleted'."""
        with self._history_lock:
            self._sample_history = [s for s in self._sample_history if s.get("id") != sample_id]
        self._broadcast_event("sample_deleted", {"id": sample_id})

    def push_sample_renamed(self, sample_id: int, _old_path: str = "", _new_path: str = "") -> None:
        """Envoie un event SSE 'sample_renamed'."""
        sample = self._get_sample_by_id(sample_id)
        if not sample:
            return
        sample_dict = self._sample_to_dict(sample)
        self._add_to_history(sample_dict)
        self._broadcast_event("sample_renamed", sample_dict)

    def push_screenshot_added(self, item_id: int) -> None:
        item = self._get_screenshot_by_id(item_id)
        if not item:
            return
        self._broadcast_event("screenshot_added", item)

    def push_screenshot_deleted(self, item_id: int) -> None:
        self._broadcast_event("screenshot_deleted", {"id": item_id})

    def push_screenshots_changed(self, items: list) -> None:
        self._broadcast_event("screenshots_changed", {"items": items})

    def _register_sse_client(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._sse_lock:
            self._sse_clients.append(q)
        return q

    def _unregister_sse_client(self, q: queue.Queue) -> None:
        with self._sse_lock:
            try:
                self._sse_clients.remove(q)
            except ValueError:
                pass

    def _close_sse_clients(self) -> None:
        with self._sse_lock:
            for q in self._sse_clients:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
            self._sse_clients.clear()

    def _broadcast_event(self, event: str, payload: Dict[str, Any]) -> None:
        with self._sse_lock:
            clients = list(self._sse_clients)
        for q in clients:
            try:
                q.put_nowait((event, payload))
            except Exception:
                pass

    def _handle_sse(self, handler: BaseHTTPRequestHandler) -> None:
        """Ouvre un flux SSE et pousse les evenements."""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        self._send_cors_headers(handler)
        handler.end_headers()
        try:
            handler.wfile.flush()
        except Exception:
            return

        q = self._register_sse_client()

        # Envoi d'un snapshot initial
        self._write_sse(handler, "status", self._build_status_payload())

        try:
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    # keepalive
                    try:
                        handler.wfile.write(b": keepalive\n\n")
                        handler.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    continue

                if item is None:
                    break
                event, payload = item
                try:
                    self._write_sse(handler, event, payload)
                except (BrokenPipeError, ConnectionResetError):
                    break
        except Exception:
            pass
        finally:
            self._unregister_sse_client(q)

    def _write_sse(self, handler: BaseHTTPRequestHandler, event: str, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload)
        msg = f"event: {event}\ndata: {data}\n\n"
        handler.wfile.write(msg.encode("utf-8"))
        handler.wfile.flush()

    # ------------------------------------------------------------------ Static files
    def _is_api_path(self, path: str) -> bool:
        """Retourne True si le path correspond a une route API connue."""
        if path.startswith("/samples/"):
            return True
        if path.startswith("/screenshots/"):
            return True
        return path in (
            "/health",
            "/events",
            "/record/status",
            "/record/start",
            "/record/stop",
            "/libraries",
            "/samples/history",
            "/screenshots/list",
            "/screenshots/screens",
            "/screenshots/capture",
            "/screenshots/rename",
            "/screenshots/delete",
        )

    def _try_serve_static(self, handler: BaseHTTPRequestHandler, path: str) -> bool:
        """Tente de servir un fichier statique. Retourne True si servi."""
        if not self.static_dir or not self.static_dir.exists():
            return False

        # Normalize path
        req_path = path.lstrip("/") or "index.html"
        target = (self.static_dir / req_path).resolve()

        # Security: prevent directory traversal
        if self.static_dir not in target.parents and target != self.static_dir:
            return False

        if target.is_dir():
            target = target / "index.html"

        if not target.exists():
            # SPA fallback: si pas d'extension, renvoyer index.html
            if "." not in req_path:
                target = (self.static_dir / "index.html").resolve()
            else:
                return False

        if not target.exists():
            return False

        self._send_file(handler, target)
        return True

    def _send_file(
        self,
        handler: BaseHTTPRequestHandler,
        path: Path,
        download_name: Optional[str] = None,
    ) -> None:
        """Envoie un fichier statique avec le bon Content-Type."""
        try:
            data = path.read_bytes()
        except Exception:
            self._send_json(handler, 500, {"error": "read_failed"})
            return

        mime, _ = mimetypes.guess_type(str(path))
        if not mime:
            mime = "application/octet-stream"

        handler.send_response(200)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(data)))
        if download_name:
            handler.send_header(
                "Content-Disposition",
                f'attachment; filename="{download_name}"',
            )
        self._send_cors_headers(handler)
        handler.end_headers()
        handler.wfile.write(data)
