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


# -- store: mutations (move / delete) ------------------------------------------------------
def _enrol(p, *serials, model="n0110"):
    for s in serials:
        R.upsert_on_scan(model, s, firmware="1.0", family="graphique", path=p)


def test_move_single_multiple_and_back_to_unfiled(tmp_path):
    p, np = tmp_path / "r.json", tmp_path / "n.json"
    _enrol(p, "SER1", "SER2", "SER3")
    # Move two into a NEW class → it is added to the rail; returns the count moved.
    assert R.move(["n0110:SER1", "n0110:SER2"], "Seconde A", path=p) == 2
    assert "Seconde A" in R.all_classes(path=p)
    by = {e["key"]: e["class"] for e in R.all_entries(path=p, names_path=np)}
    assert by["n0110:SER1"] == "Seconde A" and by["n0110:SER2"] == "Seconde A"
    assert by["n0110:SER3"] is None
    # Unknown keys are skipped (not counted).
    assert R.move(["n0110:NOPE"], "Seconde A", path=p) == 0
    # class=None files back to "Sans classe".
    assert R.move(["n0110:SER1"], None, path=p) == 1
    by = {e["key"]: e["class"] for e in R.all_entries(path=p, names_path=np)}
    assert by["n0110:SER1"] is None


def test_delete_removes_records_and_counts_only_known(tmp_path):
    p, np = tmp_path / "r.json", tmp_path / "n.json"
    _enrol(p, "SER1", "SER2")
    assert R.delete(["n0110:SER1", "n0110:NOPE"], path=p) == 1
    assert {e["key"] for e in R.all_entries(path=p, names_path=np)} == {"n0110:SER2"}


# -- store: class CRUD ---------------------------------------------------------------------
def test_create_class_allows_empty_dedups_and_sorts(tmp_path):
    p = tmp_path / "r.json"
    assert R.create_class("Terminale S", path=p) == ["Terminale S"]
    assert R.create_class("Terminale S", path=p) == ["Terminale S"]  # dedup
    assert R.create_class("   ", path=p) == ["Terminale S"]  # blank ignored
    assert R.create_class("Seconde A", path=p) == ["Seconde A", "Terminale S"]  # sorted


def test_rename_class_reassigns_members_and_merges_on_collision(tmp_path):
    p, np = tmp_path / "r.json", tmp_path / "n.json"
    _enrol(p, "SER1", "SER2")
    R.move(["n0110:SER1"], "A", path=p)
    R.move(["n0110:SER2"], "B", path=p)
    # A → C: the member follows; C replaces A in the rail.
    assert R.rename_class("A", "C", path=p) == ["B", "C"]
    assert {e["key"]: e["class"] for e in R.all_entries(path=p, names_path=np)}["n0110:SER1"] == "C"
    # C → B: MERGE into the existing B (no data loss, no duplicate rail entry).
    assert R.rename_class("C", "B", path=p) == ["B"]
    by = {e["key"]: e["class"] for e in R.all_entries(path=p, names_path=np)}
    assert by["n0110:SER1"] == "B" and by["n0110:SER2"] == "B"
    # Blank target / same name → no-op.
    assert R.rename_class("B", "", path=p) == ["B"]
    assert R.rename_class("B", "B", path=p) == ["B"]


def test_delete_class_empty_direct_then_nonempty_confirm_flow(tmp_path):
    p, np = tmp_path / "r.json", tmp_path / "n.json"
    # Empty class → removed directly.
    R.create_class("Empty", path=p)
    assert R.delete_class("Empty", path=p) == {"ok": True, "classes": []}
    # Non-empty WITHOUT confirm → asks, nothing changed yet.
    _enrol(p, "SER1")
    R.move(["n0110:SER1"], "Full", path=p)
    assert R.delete_class("Full", path=p) == {"ok": False, "needs_confirm": True, "count": 1}
    assert "Full" in R.all_classes(path=p)  # untouched
    # WITH confirm → member falls back to unfiled, class removed (never lost).
    res = R.delete_class("Full", confirm=True, path=p)
    assert res["ok"] is True and res["classes"] == []
    assert R.all_entries(path=p, names_path=np)[0]["class"] is None


# -- session: mixin mutations against a virtual device -------------------------------------
def test_session_roster_mutations(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    s = Session(model_name="n0110")
    R.upsert_on_scan("n0110", "SER1", firmware="1.0", family="graphique")
    assert s.roster_class_create("A")["classes"] == ["A"]
    assert s.roster_move(["n0110:SER1"], "A")["moved"] == 1
    assert s.roster_rename("n0110:SER1", "Poste 1")["name"] == "Poste 1"
    assert s.roster()["calculators"][0]["name"] == "Poste 1"  # joined from the name store
    assert s.roster_class_delete("A") == {"ok": False, "needs_confirm": True, "count": 1}
    assert s.roster_class_delete("A", confirm=True)["ok"] is True
    assert s.roster()["unfiled_count"] == 1
    assert s.roster_delete(["n0110:SER1"])["deleted"] == 1
    assert s.roster()["total"] == 0


# -- server API: POST /api/roster/* --------------------------------------------------------
def _post(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Origin": base},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_roster_rename_move_delete_endpoints(server):
    R.upsert_on_scan("n0110", "SERA", firmware="16.4.4", family="graphique")
    R.upsert_on_scan("n0110", "SERB", firmware="16.4.4", family="graphique")
    # rename → delegates to the shared name store
    r = _post(server, "/api/roster/rename", {"key": "n0110:SERA", "name": "Poste 7"})
    assert r["ok"] and r["name"] == "Poste 7" and N.get_name("n0110", "SERA") == "Poste 7"
    # bulk move (several keys)
    r = _post(server, "/api/roster/move", {"keys": ["n0110:SERA", "n0110:SERB"], "class": "Seconde A"})
    assert r == {"ok": True, "moved": 2}
    d = _get(server, "/api/roster")
    assert d["counts"]["Seconde A"] == 2 and d["unfiled_count"] == 0
    # class=null moves back to unfiled
    assert _post(server, "/api/roster/move", {"keys": ["n0110:SERA"], "class": None})["moved"] == 1
    # delete
    assert _post(server, "/api/roster/delete", {"keys": ["n0110:SERB"]}) == {"ok": True, "deleted": 1}
    assert _get(server, "/api/roster")["total"] == 1


def test_roster_class_crud_endpoints_and_delete_confirm(server):
    # create (empty class allowed)
    assert _post(server, "/api/roster/class/create", {"name": "Terminale S"})["classes"] == [
        "Terminale S"
    ]
    R.upsert_on_scan("n0110", "SERA", firmware="16.4.4", family="graphique")
    _post(server, "/api/roster/move", {"keys": ["n0110:SERA"], "class": "Terminale S"})
    # rename the class (member follows)
    assert _post(server, "/api/roster/class/rename", {"from": "Terminale S", "to": "Terminale T"})[
        "classes"
    ] == ["Terminale T"]
    # delete non-empty WITHOUT confirm → needs_confirm (two-step flow)
    assert _post(server, "/api/roster/class/delete", {"name": "Terminale T"}) == {
        "ok": False,
        "needs_confirm": True,
        "count": 1,
    }
    # WITH confirm → member unfiled, class gone
    res = _post(server, "/api/roster/class/delete", {"name": "Terminale T", "confirm": True})
    assert res["ok"] is True and res["classes"] == []
    assert _get(server, "/api/roster")["unfiled_count"] == 1
