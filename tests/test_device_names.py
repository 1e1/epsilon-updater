"""Local calculator-name store + the ``/api/device/name`` and ``/api/sources`` endpoints.

Mirrors the ``test_server_api``/``test_server`` style: pure-store round-trips, session methods
against a virtual device, and HTTP dispatch over an ephemeral loopback port.
"""

import json
import threading
import urllib.request

import pytest

from nwupdater import device_names as N
from nwupdater.server.httpd import make_server
from nwupdater.server.session import Session


def test_store_roundtrip_and_clear(tmp_path):
    p = tmp_path / "names.json"
    assert N.get_name("n0110", "SER1", path=p) is None
    N.set_name("n0110", "SER1", "Front desk", path=p)
    assert N.get_name("n0110", "SER1", path=p) == "Front desk"
    # Keyed by model + serial: a different serial (same model) is independent.
    assert N.get_name("n0110", "SER2", path=p) is None
    assert N.all_names(path=p) == {"n0110:SER1": "Front desk"}
    # An empty / whitespace name clears the override (falls back to the default display).
    assert N.set_name("n0110", "SER1", "   ", path=p) is None
    assert N.get_name("n0110", "SER1", path=p) is None
    assert N.all_names(path=p) == {}


def test_session_device_name_defaults_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    s = Session(model_name="n0110")
    d = s.device_name()
    assert d["default"] == "calc N0110" and d["name"] is None
    r = s.set_device_name("Salle 12")
    assert r["ok"] and r["name"] == "Salle 12"
    assert s.device_name()["name"] == "Salle 12"
    # Empty clears.
    assert s.set_device_name("")["name"] is None
    assert s.device_name()["name"] is None


def test_sources_lists_apps_scripts_and_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path / "apps"))
    monkeypatch.setenv("NWUPDATER_SCRIPTS_DIR", str(tmp_path / "scripts"))
    s = Session(model_name="n0110")
    src = s.sources()
    assert isinstance(src["apps"], list) and src["apps"]  # bundled catalogue feeds Available
    assert {"apps", "scripts"} <= set(src["dirs"])
    assert str(tmp_path / "apps") == src["dirs"]["apps"]
    assert all(a["kind"] in {"online", "cloud", "local"} for a in src["apps"])


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    session = Session(model_name="n0110", os_version="16.4.4", cache_dir=tmp_path / "cache")
    httpd = make_server(session, port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as r:
        return json.loads(r.read())


def _post(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Origin": base},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_device_name_endpoints(server):
    d = _get(server, "/api/device/name")
    assert d["default"] == "calc N0110" and d["name"] is None
    r = _post(server, "/api/device/name", {"name": "Lab A"})
    assert r["ok"] and r["name"] == "Lab A"
    assert _get(server, "/api/device/name")["name"] == "Lab A"
    _post(server, "/api/device/name", {"name": ""})  # empty clears
    assert _get(server, "/api/device/name")["name"] is None


def test_sources_endpoint(server):
    s = _get(server, "/api/sources")
    assert "apps" in s and "scripts" in s and "dirs" in s
    assert "apps" in s["dirs"] and "scripts" in s["dirs"]
