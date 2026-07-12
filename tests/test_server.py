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


def test_install_local_nwa(server):
    import base64

    from nwupdater.formats.nwa import build_nwa
    blob = build_nwa("MyApp", api_level=0, code=b"\x00" * 256)
    r = _post(server, "/api/install/app-local",
              {"filename": "MyApp.nwa", "data_b64": base64.b64encode(blob).decode()})
    assert r["ok"] is True and r["name"] == "MyApp"

