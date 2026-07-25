"""Lot 5 — local server integration test. Starts the HTTP server on an ephemeral port and
drives it over loopback exactly like the browser would. No real USB."""

import json
import threading
import urllib.request

import pytest

from nwupdater.server.httpd import make_server
from nwupdater.server.session import Session


@pytest.fixture
def server(tmp_path):
    session = Session(model_name="n0110", os_version="16.4.4", cache_dir=tmp_path / "cache")
    httpd = make_server(session, port=0)  # ephemeral port
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read())


def _post(base, path, payload):
    # A real browser's fetch() sends Origin on a same-origin POST; the CSRF guard requires it.
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Origin": base},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_identity_endpoint(server):
    i = _get(server, "/api/identity")
    assert i["model"] == "n0110"
    assert i["family"] == "graphique"
    assert i["os_version"] == "16.4.4"
    assert i["has_external_apps"] is True
    assert i["serial_number"] and len(i["serial_number"]) == 16


def test_catalog_endpoint(server):
    c = _get(server, "/api/catalog")
    assert c["current"] == "16.4.4"
    assert c["up_to_date"] is False
    assert any(u["latest"] for u in c["updates"])


def test_apps_endpoint(server):
    a = _get(server, "/api/apps")
    assert a["has_external_apps"] is True
    assert any(app["name"] == "Tetris" for app in a["apps"])


def test_install_firmware_endpoint(server):
    r = _post(server, "/api/install/firmware", {"version": "25.2.0"})
    assert r["ok"] is True
    assert r["target_slot"] == "B"
    assert r["verified_version"] == "25.2.0"


def test_install_app_endpoint(server):
    r = _post(server, "/api/install/app", {"name": "Tetris"})
    assert r["ok"] is True
    assert r["name"] == "Tetris"


def test_static_index_served(server):
    with urllib.request.urlopen(server + "/", timeout=5) as resp:
        html = resp.read().decode()
    assert "nwupdater" in html
    assert "logo.svg" in html  # header logo + favicon reference the app icon


def test_unknown_app_returns_error(server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(server, "/api/install/app", {"name": "Nope"})
    assert ei.value.code == 400


def test_cache_preload_and_install_from_cache(server):
    empty = _get(server, "/api/cache")
    assert empty["version"] is None
    st = _post(server, "/api/cache/preload", {"version": "25.2.0"})
    assert st["version"] == "25.2.0"
    assert st["expires_in_days"] == 30
    r = _post(server, "/api/install/firmware", {"version": "25.2.0", "from_cache": True})
    assert r["ok"] is True and r["from_cache"] is True
    cleared = _post(server, "/api/cache/clear", {})
    assert cleared["version"] is None


def test_flash_cached_by_model_without_version(server):
    # Classroom one-click: preload once, then flash "whatever is cached for this model" with no
    # version and no sign-in.
    _post(server, "/api/cache/preload", {"version": "25.2.0"})
    r = _post(server, "/api/install/firmware", {"from_cache": True})  # no version given
    assert r["ok"] is True and r["from_cache"] is True
    assert r["to_version"] == "25.2.0"  # resolved from the model's cached entry


def test_boot_after_install(server):
    _post(server, "/api/install/firmware", {"version": "25.2.0"})
    r = _post(server, "/api/boot", {})
    assert r["ok"] is True and r["jumped_to"].startswith("0x")


def test_boot_without_install_errors(server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(server, "/api/boot", {})
    assert ei.value.code == 400


def test_capture_requires_auth(server, monkeypatch):
    # No token → the /api/capture endpoint must refuse (400), never hit the network.
    from nwupdater.catalog import auth as A

    monkeypatch.setattr(A, "load_auth", lambda **k: None)
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(server, "/api/capture", {})
    assert ei.value.code == 400


def test_ping_endpoint(server):
    p = _get(server, "/api/ping")
    assert p["app"] == "nwupdater"
    assert p["model"] == "n0110"


def test_single_instance_detection(server, tmp_path, monkeypatch):
    from nwupdater.server import instance

    monkeypatch.setattr(instance, "INSTANCE_FILE", tmp_path / "inst.json")
    assert instance.existing_url() is None  # no file yet
    instance.write(server + "/", 0)  # point at the live test server
    assert instance.existing_url() == server + "/"  # probe /api/ping succeeds
    instance.write("http://127.0.0.1:1/", 0)  # dead url
    assert instance.existing_url() is None  # stale -> cleared
    assert not (tmp_path / "inst.json").exists()


def test_instance_lock_is_exclusive(tmp_path):
    """The OS lock admits exactly one holder — the mutual exclusion behind single-instance."""
    from nwupdater.server import instance

    lock_path = tmp_path / "inst.lock"
    first, second = instance.InstanceLock(lock_path), instance.InstanceLock(lock_path)
    assert first.acquire() is True  # first launch wins
    assert second.acquire() is False  # a concurrent launch is refused while the first holds it
    first.release()
    assert second.acquire() is True  # released -> the next launch can take over
    second.release()


def test_wait_for_url_polls_until_live(server, tmp_path, monkeypatch):
    """A launch that lost the lock finds the running instance's URL (and never a dead one)."""
    from nwupdater.server import instance

    monkeypatch.setattr(instance, "INSTANCE_FILE", tmp_path / "inst.json")
    instance.write(server + "/", 0)
    assert instance.wait_for_url(attempts=3, delay=0.01) == server + "/"
    instance.write("http://127.0.0.1:1/", 0)  # nothing answering there
    assert instance.wait_for_url(attempts=2, delay=0.01) is None
    assert (tmp_path / "inst.json").exists()  # loser must not clear the holder's record


def _raw(port, request: str) -> str:
    """Send a verbatim HTTP request over a raw socket (so literal '..' path segments and a
    lying Content-Length reach the server unmodified) and return the full response text."""
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request.encode())
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    return b"".join(chunks).decode("utf-8", "replace")


def test_static_path_traversal_is_404(tmp_path):
    from nwupdater.server.httpd import make_server

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>nwupdater</html>")
    # Sibling dir sharing the name prefix: the classic case a startswith() check would leak.
    secret = tmp_path / "web-secret"
    secret.mkdir()
    (secret / "flag.txt").write_text("TOP SECRET")
    session = Session(model_name="n0110", cache_dir=tmp_path / "cache")
    httpd = make_server(session, port=0, web_dir=web)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        resp = _raw(port, "GET /../web-secret/flag.txt HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        assert "404" in resp.split("\r\n", 1)[0]
        assert "TOP SECRET" not in resp
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_oversized_body_returns_413(server):
    port = int(server.rsplit(":", 1)[1])
    # Content-Length way above MAX_BODY (16 MiB): rejected with 413 before any body is read.
    resp = _raw(
        port,
        f"POST /api/quit HTTP/1.0\r\nHost: 127.0.0.1\r\n"
        f"Origin: http://127.0.0.1:{port}\r\n"
        "Content-Length: 20000000\r\n\r\n",
    )
    assert "413" in resp.split("\r\n", 1)[0]


def test_non_numeric_content_length_does_not_500(server):
    port = int(server.rsplit(":", 1)[1])
    resp = _raw(
        port,
        f"POST /api/channel HTTP/1.0\r\nHost: 127.0.0.1\r\n"
        f"Origin: http://127.0.0.1:{port}\r\n"
        "Content-Length: not-a-number\r\n\r\n",
    )
    status = resp.split("\r\n", 1)[0]
    assert "500" not in status  # garbage Content-Length is tolerated, treated as empty body


def test_post_without_origin_is_forbidden(server):
    port = int(server.rsplit(":", 1)[1])
    # A state-changing POST with no Origin (CSRF / non-browser client) is rejected up front.
    resp = _raw(
        port,
        "POST /api/install/firmware HTTP/1.0\r\nHost: 127.0.0.1\r\n"
        "Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}",
    )
    assert "403" in resp.split("\r\n", 1)[0]


def test_post_with_foreign_origin_is_forbidden(server):
    port = int(server.rsplit(":", 1)[1])
    resp = _raw(
        port,
        "POST /api/install/firmware HTTP/1.0\r\nHost: 127.0.0.1\r\n"
        "Origin: http://evil.example\r\n"
        "Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}",
    )
    assert "403" in resp.split("\r\n", 1)[0]


def test_guard_accepts_ipv6_loopback_host_with_port(server):
    port = int(server.rsplit(":", 1)[1])
    # Host "[::1]:port" is loopback and must pass the guard, not be rejected as a foreign origin.
    resp = _raw(port, f"GET /api/ping HTTP/1.0\r\nHost: [::1]:{port}\r\n\r\n")
    status = resp.split("\r\n", 1)[0]
    assert "200" in status and "403" not in status


def test_read_routes_smoke(server):
    # Remaining GET routes — read-only, offline (httpd dispatch coverage).
    assert isinstance(_get(server, "/api/device/demo-models"), list)
    assert "installed" in _get(server, "/api/apps/installed")
    assert _get(server, "/api/scripts")["has_scripts"] is True
    assert "authenticated" in _get(server, "/api/auth")


def test_device_and_channel_routes(server):
    assert _post(server, "/api/channel", {"channel": "beta"})["channel"] == "beta"
    assert _post(server, "/api/device/demo", {"model": "n0120"})["model"] == "n0120"
    assert _post(server, "/api/device/rescan", {})["connected"] is False  # no real HW in tests
    assert _post(server, "/api/device/detach", {})["connected"] is False


def test_device_health_route(server):
    # Connected to the demo device in tests → reports alive + virtual.
    assert _get(server, "/api/device/health") == {"connected": True, "virtual": True}
    _post(server, "/api/device/detach", {})
    assert _get(server, "/api/device/health")["connected"] is False


def test_scripts_routes(server):
    assert (
        _post(
            server, "/api/scripts/push", {"name": "hi", "code": "print(1)\n", "auto_import": True}
        )["ok"]
        is True
    )
    assert (
        _post(server, "/api/scripts/set", {"scripts": [{"name": "a", "code": "x=1\n"}]})["ok"]
        is True
    )
    assert _post(server, "/api/scripts/delete", {"name": "a"})["ok"] is True


def test_apps_routes(server):
    import base64

    from nwupdater.formats.nwa import build_nwa

    b64 = base64.b64encode(build_nwa("Beta", api_level=0, code=b"\x02" * 128)).decode()
    assert _post(server, "/api/apps/inspect", {"data_b64": b64})["size"] > 0
    assert _post(server, "/api/apps/add", {"name": "Tetris"})["ok"] is True
    assert _post(server, "/api/apps/push", {"filename": "b.nwa", "data_b64": b64})["ok"] is True
    assert _post(server, "/api/apps/reorder", {"order": ["Tetris", "Beta"]})["ok"] is True
    assert _post(server, "/api/apps/uninstall", {"name": "Tetris"})["ok"] is True


def test_auth_routes_smoke(server):
    assert "authenticated" in _post(server, "/api/auth/logout", {})
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(server, "/api/auth/login", {"token": ""})  # empty token rejected
    assert ei.value.code == 400


def test_preload_all_route(server):
    st = _post(server, "/api/cache/preload-all", {})
    assert st["models"]  # cached the whole known fleet (synthetic, offline)


def test_install_local_nwa(server):
    import base64

    from nwupdater.formats.nwa import build_nwa

    blob = build_nwa("MyApp", api_level=0, code=b"\x00" * 256)
    r = _post(
        server,
        "/api/install/app-local",
        {"filename": "MyApp.nwa", "data_b64": base64.b64encode(blob).decode()},
    )
    assert r["ok"] is True and r["name"] == "MyApp"
