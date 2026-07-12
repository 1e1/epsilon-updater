"""Local HTTP server exposing the updater as a JSON API + a static web UI.

Stdlib only (http.server) so packaging stays trivial. Binds to 127.0.0.1 (loopback) — the UI
is served to the local browser exactly like the Flipper/Lunii desktop apps, but without
WebUSB: all USB work happens in this process, the browser only renders.

Loopback is not a security boundary on its own: any page in the same browser can POST to
127.0.0.1 (CSRF), and a page whose hostname is rebound to 127.0.0.1 can reach us with a
foreign ``Host`` header (DNS-rebinding). Because a NumWorks token lives behind this API, every
``/api/`` request is guarded (:meth:`Handler._guard`): the ``Host`` header must be a loopback
name, and any ``Origin`` present must match our own.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import instance
from .session import Session

WEB_DIR = Path(__file__).parent / "web"


def _handler(session: Session, web_dir: Path, control: dict | None = None):
    control = control if control is not None else {}

    class Handler(BaseHTTPRequestHandler):
        server_version = "nwupdater/0.1"

        def log_message(self, *a):  # quiet
            pass

        # -- helpers ---------------------------------------------------------------
        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _guard(self) -> bool:
            """True if the request may touch the API. Blocks CSRF & DNS-rebinding.

            Rejects when the ``Host`` header is not a loopback name (rebinding), or when an
            ``Origin`` is present that is not our own (cross-origin POST). Same-origin requests
            from our own page send a matching Origin (or none, for top-level GET) and pass.
            """
            port = self.server.server_address[1]
            loopback = {"127.0.0.1", "localhost", "[::1]", "::1"}
            host = (self.headers.get("Host") or "").strip().lower()
            hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
            if hostname not in loopback:
                return False
            origin = self.headers.get("Origin")
            if origin:
                allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}",
                           f"http://[::1]:{port}"}
                if origin.strip().lower() not in allowed:
                    return False
            return True

        def _read_json(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _static(self, path: str):
            rel = path.lstrip("/") or "index.html"
            target = (web_dir / rel).resolve()
            if not str(target).startswith(str(web_dir.resolve())) or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # -- routing ---------------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            control["last"] = time.time()
            if path.startswith("/api/") and not self._guard():
                self._json({"error": "forbidden origin"}, 403)
                return
            try:
                if path == "/api/ping":
                    self._json({"app": instance.APP_MARKER, "model": session.model.name if session.model else None})
                    return
                if path == "/api/identity":
                    self._json(session.identity())
                elif path == "/api/catalog":
                    self._json(session.catalog_updates())
                elif path == "/api/apps":
                    self._json(session.apps())
                elif path == "/api/cache":
                    self._json(session.cache_status())
                elif path == "/api/auth":
                    self._json(session.auth_status())
                elif path.startswith("/api/"):
                    self._json({"error": "unknown endpoint"}, 404)
                else:
                    self._static(path)
            except Exception as exc:  # surface errors as JSON
                self._json({"error": str(exc)}, 500)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            control["last"] = time.time()
            if not self._guard():
                self._json({"ok": False, "error": "forbidden origin"}, 403)
                return
            body = self._read_json()
            try:
                if path == "/api/install/firmware":
                    self._json(session.install_firmware(body.get("version", ""),
                                                        from_cache=bool(body.get("from_cache")),
                                                        download=bool(body.get("download")),
                                                        channel=body.get("channel", "stable")))
                elif path == "/api/auth/login":
                    if body.get("email"):
                        self._json(session.login_password(body.get("email", ""), body.get("password", "")))
                    else:
                        self._json(session.login_token(body.get("token", "")))
                elif path == "/api/boot":
                    self._json(session.boot())
                elif path == "/api/auth/logout":
                    self._json(session.logout())
                elif path == "/api/install/app":
                    self._json(session.install_app(body.get("name", "")))
                elif path == "/api/install/app-local":
                    import base64
                    data = base64.b64decode(body.get("data_b64", ""))
                    self._json(session.install_local_app(body.get("filename", "app.nwa"), data))
                elif path == "/api/cache/preload":
                    self._json(session.preload(body.get("version", "")))
                elif path == "/api/cache/clear":
                    self._json(session.cache_clear())
                elif path == "/api/quit":
                    self._json({"ok": True})
                    if control.get("shutdown"):
                        control["shutdown"]()
                else:
                    self._json({"error": "unknown endpoint"}, 404)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

    return Handler


def make_server(session: Session, *, host: str = "127.0.0.1", port: int = 8765,
                web_dir: Path = WEB_DIR, control: dict | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _handler(session, web_dir, control))


def _idle_watcher(control: dict, timeout: float, interval: float = 20.0):
    while not control.get("stopping"):
        time.sleep(min(interval, timeout))
        if control.get("stopping"):
            return
        if time.time() - control.get("last", 0) > timeout:
            print(f"\ninactivité > {int(timeout)}s — arrêt automatique.")
            if control.get("shutdown"):
                control["shutdown"]()
            return


def serve(session: Session, *, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True, single_instance: bool = False,
          idle_timeout: float | None = None) -> None:
    # Single instance: if one is already running, just reopen the browser there.
    if single_instance:
        existing = instance.existing_url()
        if existing:
            print(f"Déjà en cours d'exécution : {existing}")
            if open_browser:
                try:
                    webbrowser.open(existing)
                except Exception:
                    pass
            return

    control: dict = {"last": time.time()}
    httpd = make_server(session, host=host, port=port, control=control)
    actual_port = httpd.server_address[1]  # resolves port 0 to the OS-chosen port
    control["shutdown"] = lambda: threading.Thread(target=httpd.shutdown, daemon=True).start()
    # Bind stays on the loopback IP (local-only, robust) but display the friendlier "localhost".
    display_host = "localhost" if host in ("127.0.0.1", "::1") else host
    url = f"http://{display_host}:{actual_port}/"
    if single_instance:
        instance.write(url, actual_port)

    print(f"nwupdater UI : {url}  (device: {session.identity()['model']}"
          f"{' virtuel' if session.virtual else ''})")
    print("Fermez l'onglet et cliquez « Quitter », ou Ctrl+C pour arrêter.")
    if idle_timeout and idle_timeout > 0:
        print(f"Arrêt auto après {int(idle_timeout)}s sans activité.")
        threading.Thread(target=_idle_watcher, args=(control, idle_timeout), daemon=True).start()
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt.")
    finally:
        control["stopping"] = True
        httpd.server_close()
        if single_instance:
            instance.clear()
