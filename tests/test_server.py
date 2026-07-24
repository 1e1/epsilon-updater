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
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
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
    assert instance.existing_url() is None            # no file yet
    instance.write(server + "/", 0)                   # point at the live test server
    assert instance.existing_url() == server + "/"    # probe /api/ping succeeds
    instance.write("http://127.0.0.1:1/", 0)          # dead url
    assert instance.existing_url() is None            # stale -> cleared
    assert not (tmp_path / "inst.json").exists()


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
    resp = _raw(port, "POST /api/quit HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                      "Content-Length: 20000000\r\n\r\n")
    assert "413" in resp.split("\r\n", 1)[0]


def test_non_numeric_content_length_does_not_500(server):
    port = int(server.rsplit(":", 1)[1])
    resp = _raw(port, "POST /api/channel HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                      "Content-Length: not-a-number\r\n\r\n")
    status = resp.split("\r\n", 1)[0]
    assert "500" not in status  # garbage Content-Length is tolerated, treated as empty body


def test_install_local_nwa(server):
    import base64

    from nwupdater.formats.nwa import build_nwa
    blob = build_nwa("MyApp", api_level=0, code=b"\x00" * 256)
    r = _post(server, "/api/install/app-local",
              {"filename": "MyApp.nwa", "data_b64": base64.b64encode(blob).decode()})
    assert r["ok"] is True and r["name"] == "MyApp"

