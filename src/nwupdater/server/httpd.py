"""Local HTTP server exposing the updater as a JSON API + a static web UI.

Stdlib only (http.server) so packaging stays trivial. Binds to 127.0.0.1 (loopback) — the UI
is served to the local browser, but without WebUSB: all USB work happens in this process, the
browser only renders.

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
from typing import cast
from urllib.parse import urlsplit

from ..apps.proxy import MAX_APP_BYTES
from . import instance
from .session import Session

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 16 * 1024 * 1024  # reject request bodies larger than 16 MiB with HTTP 413


class _BodyTooLarge(Exception):
    """Signals a request whose Content-Length exceeds MAX_BODY (413 already sent)."""


def _handler(session: Session, web_dir: Path, control: dict | None = None):
    ctrl: dict = control if control is not None else {}

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

        def _locked_json(self, fn):
            """Run a device-touching read under the session I/O lock, then emit JSON — so the
            background liveness probe never issues USB transfers concurrently with it."""
            with session._io_lock:
                obj = fn()
            self._json(obj)

        def _guard(self, *, require_origin: bool = False) -> bool:
            """True if the request may touch the API. Blocks CSRF & DNS-rebinding.

            Always rejects when the ``Host`` header is not a loopback name (rebinding), or when a
            present ``Origin`` is not our own. With ``require_origin`` (mutating requests) it also
            rejects when NO ``Origin`` is sent: a same-origin fetch/XHR POST from our own page
            always carries one, so its absence means a cross-context or non-browser client. Reads
            (GET) stay lenient — top-level navigation legitimately omits Origin.
            """
            port = cast(tuple, self.server.server_address)[1]
            loopback = {"127.0.0.1", "localhost", "::1"}
            host = (self.headers.get("Host") or "").strip()
            # urlsplit unwraps a bracketed IPv6 literal and strips the :port uniformly. A naive
            # rsplit/count(":") mishandles "[::1]:8765" (multiple colons) -> false 403.
            try:
                hostname = (urlsplit("//" + host).hostname or "").lower()
            except ValueError:
                return False
            if hostname not in loopback:
                return False
            origin = self.headers.get("Origin")
            if origin:
                allowed = {
                    f"http://127.0.0.1:{port}",
                    f"http://localhost:{port}",
                    f"http://[::1]:{port}",
                }
                return origin.strip().lower() in allowed
            return not require_origin

        def _read_json(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):  # absent or non-numeric -> treat as empty, no 500
                return {}
            if n <= 0:
                return {}
            if n > MAX_BODY:
                self._json({"ok": False, "error": "request body too large"}, 413)
                raise _BodyTooLarge()
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _static(self, path: str):
            rel = path.lstrip("/") or "index.html"
            target = (web_dir / rel).resolve()
            # is_relative_to() is a true containment check: a plain startswith() prefix test lets
            # a sibling dir sharing the name prefix (…/web-secret) bypass a …/web root.
            if not target.is_relative_to(web_dir.resolve()) or not target.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _stream_app(self, session):
            """Proxy-stream a catalogue app's .nwa so the browser can show a byte-accurate
            progress bar (Content-Length forwarded from upstream). Validation happens BEFORE any
            header is sent so failures still return clean JSON."""
            from urllib.parse import parse_qs, urlparse

            url = (parse_qs(urlparse(self.path).query).get("url") or [""])[0]
            try:
                length, up = session.open_app_stream(url)
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
                return
            try:
                # Cap the proxied size even though the URL is catalogue-allowlisted: a rogue CDN
                # behind a listed URL must not be able to stream unbounded data through us.
                if length is not None and length > MAX_APP_BYTES:
                    self._json({"error": "file too large"}, 400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.end_headers()
                sent = 0
                while True:
                    chunk = up.read(65536)
                    if not chunk:
                        break
                    sent += len(chunk)
                    if sent > MAX_APP_BYTES:  # absent or lying Content-Length — stop, don't OOM
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client navigated away mid-download
            finally:
                up.close()

        # -- routing ---------------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            ctrl["last"] = time.time()
            if path.startswith("/api/") and not self._guard():
                self._json({"error": "forbidden origin"}, 403)
                return
            try:
                if path == "/api/ping":
                    self._json(
                        {
                            "app": instance.APP_MARKER,
                            "model": session.model.name if session.model else None,
                        }
                    )
                    return
                if path == "/api/identity":
                    self._locked_json(session.identity)
                elif path == "/api/device/demo-models":
                    self._json(session.demo_models())
                elif path == "/api/device/health":
                    # Hotplug watch: cheap, self-locking (non-blocking) — never queues behind
                    # an in-flight operation.
                    self._json(session.device_health())
                elif path == "/api/catalog":
                    self._locked_json(session.catalog_updates)
                elif path == "/api/apps":
                    self._locked_json(session.apps)
                elif path == "/api/apps/installed":
                    self._locked_json(session.installed_apps_on_device)
                elif path == "/api/scripts":
                    self._locked_json(session.scripts)
                elif path == "/api/cache":
                    self._json(session.cache_status())
                elif path == "/api/auth":
                    self._json(session.auth_status())
                elif path == "/api/apps/download":
                    self._stream_app(session)
                elif path.startswith("/api/"):
                    self._json({"error": "unknown endpoint"}, 404)
                else:
                    self._static(path)
            except Exception as exc:  # surface errors as JSON
                self._json({"error": str(exc)}, 500)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            ctrl["last"] = time.time()
            if not self._guard(require_origin=True):  # mutations require a same-origin Origin
                self._json({"ok": False, "error": "forbidden origin"}, 403)
                return
            try:
                body = self._read_json()
            except _BodyTooLarge:
                return  # 413 already sent
            # Serialize device access: a mutation holds the I/O lock so the background liveness
            # poll (a non-blocking acquirer) never issues USB transfers alongside it. The timeout
            # is a safety net against a wedged operation, not expected under the single-client UI.
            if not session._io_lock.acquire(timeout=120):
                self._json({"ok": False, "error": "device busy"}, 503)
                return
            try:
                if path == "/api/install/firmware":
                    self._json(
                        session.install_firmware(
                            body.get("version", ""),
                            from_cache=bool(body.get("from_cache")),
                            download=bool(body.get("download")),
                            channel=body.get("channel") or session.channel,
                        )
                    )
                elif path == "/api/device/rescan":
                    # Try to attach a real calculator; a clean "not connected" is not an error.
                    try:
                        self._json(session.attach_real())
                    except Exception as exc:
                        self._json({"connected": False, "error": str(exc)})
                elif path == "/api/device/demo":
                    self._json(session.attach_demo(body.get("model") or None))
                elif path == "/api/device/detach":
                    self._json(session.detach())
                elif path == "/api/channel":
                    self._json(session.set_channel(body.get("channel", "stable")))
                elif path == "/api/auth/login":
                    if body.get("email"):
                        self._json(
                            session.login_password(body.get("email", ""), body.get("password", ""))
                        )
                    else:
                        self._json(session.login_token(body.get("token", "")))
                elif path == "/api/boot":
                    self._json(session.boot())
                elif path == "/api/capture":
                    import datetime

                    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
                    self._json(session.capture_sequence(timestamp=ts))
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
                elif path == "/api/cache/preload-all":
                    self._json(session.preload_all())
                elif path == "/api/cache/clear":
                    self._json(session.cache_clear())
                elif path == "/api/apps/push":
                    import base64

                    self._json(
                        session.push_app(
                            body.get("filename", "app.nwa"),
                            base64.b64decode(body.get("data_b64", "")),
                        )
                    )
                elif path == "/api/apps/add":
                    self._json(session.add_store_app(body.get("name", "")))
                elif path == "/api/apps/inspect":
                    import base64

                    self._json(session.inspect_app(base64.b64decode(body.get("data_b64", ""))))
                elif path == "/api/apps/fetch":
                    self._json(session.fetch_app(body.get("url", "")))
                elif path == "/api/apps/uninstall":
                    self._json(session.uninstall_app(body.get("name", "")))
                elif path == "/api/apps/reorder":
                    self._json(session.reorder_apps(body.get("order", [])))
                elif path == "/api/apps/export":
                    self._json(session.export_app(body.get("name", "")))
                elif path == "/api/scripts/push":
                    self._json(
                        session.push_script(
                            body.get("name", ""),
                            body.get("code", ""),
                            bool(body.get("auto_import", True)),
                        )
                    )
                elif path == "/api/scripts/export":
                    self._json(session.export_script(body.get("name", "")))
                elif path == "/api/scripts/delete":
                    self._json(session.delete_script(body.get("name", "")))
                elif path == "/api/scripts/set":
                    self._json(session.set_scripts(body.get("scripts", [])))
                elif path == "/api/quit":
                    self._json({"ok": True})
                    if ctrl.get("shutdown"):
                        ctrl["shutdown"]()
                else:
                    self._json({"error": "unknown endpoint"}, 404)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            finally:
                session._io_lock.release()

    return Handler


def make_server(
    session: Session,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    web_dir: Path = WEB_DIR,
    control: dict | None = None,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _handler(session, web_dir, control))


def _idle_watcher(control: dict, timeout: float, interval: float = 20.0):
    while not control.get("stopping"):
        time.sleep(min(interval, timeout))
        if control.get("stopping"):
            return
        if time.time() - control.get("last", 0) > timeout:
            print(f"\ninactive > {int(timeout)}s — auto-shutdown.")
            if control.get("shutdown"):
                control["shutdown"]()
            return


def serve(
    session: Session,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    single_instance: bool = False,
    idle_timeout: float | None = None,
) -> None:
    # Single instance: if one is already running, just reopen the browser there.
    if single_instance:
        existing = instance.existing_url()
        if existing:
            print(f"Already running: {existing}")
            if open_browser:
                try:
                    webbrowser.open(existing)
                except Exception:
                    pass
            return

    # Local libraries where exported apps/scripts land (and are matched against for the
    # "already on the computer" state). Created empty on launch so both exist and can be browsed.
    try:
        from ..apps.sources import user_apps_dir, user_scripts_dir

        user_apps_dir().mkdir(parents=True, exist_ok=True)
        user_scripts_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    control: dict = {"last": time.time()}
    httpd = make_server(session, host=host, port=port, control=control)
    actual_port = httpd.server_address[1]  # resolves port 0 to the OS-chosen port
    control["shutdown"] = lambda: threading.Thread(target=httpd.shutdown, daemon=True).start()
    # Bind stays on the loopback IP (local-only, robust) but display the friendlier "localhost".
    display_host = "localhost" if host in ("127.0.0.1", "::1") else host
    url = f"http://{display_host}:{actual_port}/"
    if single_instance:
        instance.write(url, actual_port)

    ident = session.identity()
    where = (
        "no calculator — connect one or explore a demo from the page"
        if not ident.get("connected")
        else f"{ident['model']}{' (demo)' if session.virtual else ''}"
    )
    print(f"nwupdater UI : {url}  (device: {where})")
    print('Close the tab and click "Quit", or press Ctrl+C to stop.')
    if idle_timeout and idle_timeout > 0:
        print(f"Auto-shutdown after {int(idle_timeout)}s of inactivity.")
        threading.Thread(target=_idle_watcher, args=(control, idle_timeout), daemon=True).start()
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        control["stopping"] = True
        httpd.server_close()
        if single_instance:
            instance.clear()
