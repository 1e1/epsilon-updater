"""Local classroom roster store (``nwupdater.classroom_roster``) + the ``GET /api/roster`` endpoint.

Mirrors ``test_device_names``: pure-store round-trips (upsert idempotency, name join, class
fallback, corruption/schema tolerance), the session upsert-on-attach seam under classroom policy,
and HTTP dispatch over an ephemeral loopback port.
"""

import json
import threading
import urllib.request

import pytest

from nwupdater import classroom_roster as R
from nwupdater import device_names as N
from nwupdater.capabilities import Policy
from nwupdater.server.httpd import make_server
from nwupdater.server.session import Session


# -- store: paths --------------------------------------------------------------------------
def test_roster_path_env_and_override(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    assert R.roster_path() == tmp_path / "nwupdater" / "classroom-roster.json"
    # It sits next to the name store (same base, different filename).
    assert R.roster_path().parent == N.store_path().parent
    p = tmp_path / "explicit.json"
    assert R.roster_path(path=p) == p


# -- store: upsert -------------------------------------------------------------------------
def test_upsert_creates_unfiled_then_is_idempotent_and_refreshes_firmware(tmp_path):
    p = tmp_path / "roster.json"
    np = tmp_path / "names.json"
    # New device: created, unfiled (class=None), known_* set.
    assert R.upsert_on_scan("n0110", "SER1", firmware="23.2.0", family="graphique", path=p) is True
    e = R.all_entries(path=p, names_path=np)[0]
    assert e["class"] is None and e["known_firmware"] == "23.2.0"
    assert e["known_family"] == "graphique" and e["known_model"] == "n0110"
    assert e["last_scan"]
    # Same scan again → nothing changed → NOT written (anti-thrash), last_scan unchanged.
    before = p.read_text()
    assert R.upsert_on_scan("n0110", "SER1", firmware="23.2.0", family="graphique", path=p) is False
    assert p.read_text() == before
    # A newer firmware → written, known_firmware refreshed, class preserved.
    assert R.upsert_on_scan("n0110", "SER1", firmware="23.2.4", family="graphique", path=p) is True
    e = R.all_entries(path=p, names_path=np)[0]
    assert e["known_firmware"] == "23.2.4" and e["class"] is None


def test_upsert_preserves_class_and_name_on_refresh(tmp_path):
    p = tmp_path / "roster.json"
    np = tmp_path / "names.json"
    R.upsert_on_scan("n0110", "SER1", firmware="1.0", family="graphique", path=p)
    # Simulate a filing + a name assigned elsewhere.
    data = json.loads(p.read_text())
    data["calculators"]["n0110:SER1"]["class"] = "Seconde A"
    data["classes"] = ["Seconde A"]
    p.write_text(json.dumps(data))
    N.set_name("n0110", "SER1", "Poste 3", path=np)
    # A re-scan refreshes firmware but must NOT touch class or the (joined) name.
    R.upsert_on_scan("n0110", "SER1", firmware="2.0", family="graphique", path=p)
    e = R.all_entries(path=p, names_path=np)[0]
    assert e["class"] == "Seconde A" and e["known_firmware"] == "2.0" and e["name"] == "Poste 3"


def test_upsert_skips_when_no_serial(tmp_path):
    p = tmp_path / "roster.json"
    assert R.upsert_on_scan("n0110", "", firmware="1.0", family="graphique", path=p) is False
    assert R.upsert_on_scan("n0110", "   ", firmware="1.0", family="graphique", path=p) is False
    assert not p.exists()
    assert R.all_entries(path=p) == []


# -- store: name join + fallback -----------------------------------------------------------
def test_name_is_joined_from_the_name_store_not_duplicated(tmp_path):
    p = tmp_path / "roster.json"
    np = tmp_path / "names.json"
    R.upsert_on_scan("n0110", "SER1", firmware="23.2.4", family="graphique", path=p)
    # No name yet → name is None, default is the calc-model fallback.
    e = R.all_entries(path=p, names_path=np)[0]
    assert e["name"] is None and e["default"] == "calc N0110"
    # The name lives ONLY in the name store; the roster JSON never stores it.
    assert "Poste 3" not in p.read_text()
    N.set_name("n0110", "SER1", "Poste 3", path=np)
    assert R.all_entries(path=p, names_path=np)[0]["name"] == "Poste 3"
    assert "Poste 3" not in p.read_text()


# -- store: corruption / schema tolerance --------------------------------------------------
def test_corrupt_file_loads_as_empty_then_upsert_starts_fresh(tmp_path):
    p = tmp_path / "roster.json"
    p.write_text("{ this is : not json", encoding="utf-8")
    assert R.all_entries(path=p) == []
    assert R.all_classes(path=p) == []
    assert R.upsert_on_scan("n0110", "SER1", firmware="1.0", family="graphique", path=p) is True
    assert len(R.all_entries(path=p, names_path=tmp_path / "n.json")) == 1


def test_non_dict_json_loads_as_empty(tmp_path):
    p = tmp_path / "roster.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert R.all_entries(path=p) == [] and R.all_classes(path=p) == []


def test_unknown_schema_is_read_cautiously(tmp_path):
    p = tmp_path / "roster.json"
    p.write_text(
        json.dumps(
            {
                "schema": 99,  # newer/unknown — read what we recognise, never crash
                "classes": ["A"],
                "calculators": {
                    "n0110:SER1": {
                        "class": "A",
                        "known_firmware": "1.0",
                        "known_family": "graphique",
                        "known_model": "n0110",
                        "last_scan": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    entries = R.all_entries(path=p, names_path=tmp_path / "n.json")
    assert len(entries) == 1 and entries[0]["class"] == "A"
    assert R.all_classes(path=p) == ["A"]


# -- session: upsert-on-attach seam --------------------------------------------------------
def test_session_upsert_on_attach_only_under_classroom_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    s = Session(model_name="n0110")  # default policy → construction attach does NOT enrol
    assert s.roster()["total"] == 0
    assert not R.roster_path().exists()
    # Turn on classroom policy and re-scan (demo attach) → the device is enrolled, unfiled.
    s.policy = Policy(classroom=True)
    assert s.roster_upsert_current() is True
    r = s.roster()
    assert r["total"] == 1 and r["unfiled_count"] == 1
    assert r["calculators"][0]["class"] is None and r["calculators"][0]["known_firmware"]
    # Idempotent: a second scan of the same (unchanged) device rewrites nothing.
    assert s.roster_upsert_current() is False


def test_session_attach_demo_enrols_under_classroom_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    s = Session(model_name="n0110")
    s.policy = Policy(classroom=True)
    s.attach_demo("n0120")  # attach path → _after_scan → roster_upsert_current
    r = s.roster()
    assert r["total"] == 1
    assert r["calculators"][0]["model"] == "n0120"


def test_roster_up_to_date_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    s = Session(model_name="n0110")
    # Unknown firmware/family → the "up to date" state is unknown (None).
    assert s._roster_up_to_date(None, None) is None
    assert s._roster_up_to_date("graphique", None) is None
    # A very old firmware is behind the bundled latest.
    assert s._roster_up_to_date("graphique", "1.0.0") is False


# -- server API: GET /api/roster -----------------------------------------------------------
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


def test_roster_endpoint_empty(server):
    d = _get(server, "/api/roster")
    assert d["schema"] == R.SCHEMA
    assert d["classes"] == [] and d["counts"] == {}
    assert d["calculators"] == [] and d["total"] == 0 and d["unfiled_count"] == 0


def test_roster_endpoint_joins_names_groups_classes_and_hides_serial(server):
    # Seed the store the server reads (same config dir via the fixture's env).
    R.upsert_on_scan("n0110", "SERAAA111", firmware="16.4.4", family="graphique")
    R.upsert_on_scan("n0120", "SERBBB222", firmware="10.0.0", family="graphique")
    N.set_name("n0110", "SERAAA111", "Poste 1")
    # File one calculator into a class directly in the store.
    p = R.roster_path()
    data = json.loads(p.read_text())
    data["calculators"]["n0120:SERBBB222"]["class"] = "Seconde A"
    data["classes"] = ["Seconde A"]
    p.write_text(json.dumps(data))

    d = _get(server, "/api/roster")
    assert d["classes"] == ["Seconde A"]
    assert d["counts"]["Seconde A"] == 1
    assert d["unfiled_count"] == 1 and d["total"] == 2
    by_model = {c["model"]: c for c in d["calculators"]}
    assert by_model["n0110"]["name"] == "Poste 1"  # joined from the name store
    assert by_model["n0110"]["class"] is None
    assert by_model["n0120"]["class"] == "Seconde A"
    assert "up_to_date" in by_model["n0110"]
    # No serial ever appears in a display field.
    for c in d["calculators"]:
        for field in ("name", "default", "model", "family", "class", "known_firmware"):
            assert "SERAAA111" not in str(c.get(field))
            assert "SERBBB222" not in str(c.get(field))
