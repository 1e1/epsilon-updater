"""Web-session API for scripts & device-truth app management (virtual device, offline)."""

import pytest

from nwupdater.catalog.firmware import FirmwareCatalog
from nwupdater.formats.nwa import build_nwa
from nwupdater.server.session import Session


def test_install_and_preload_when_disconnected_raise_valueerror():
    # Regression: bcd is None while disconnected; formatting it raised TypeError, not a clean
    # "no calculator connected" ValueError.
    s = Session(connect=False)
    with pytest.raises(ValueError):
        s.install_firmware("25.2.0")
    with pytest.raises(ValueError):
        s.preload("25.2.0")


def test_device_health_not_connected():
    s = Session(connect=False)
    assert s.device_health() == {"connected": False, "virtual": False}


def test_device_health_virtual_is_alive():
    s = Session(connect=False)
    s.attach_demo("n0110")
    assert s.device_health() == {"connected": True, "virtual": True}


def test_device_alive_probes_a_responding_device():
    s = Session(connect=False)
    s.attach_demo("n0110")
    s.virtual = False  # force the real-hardware probe path against the responding virtual DFU
    assert s.device_alive() is True


def test_device_health_lost_auto_detaches():
    s = Session(connect=False)
    s.attach_demo("n0110")
    s.virtual = False  # pretend a real device...

    def boom():
        raise OSError("device gone")  # ...that has just been unplugged

    s.client.get_state = boom  # type: ignore[union-attr]
    assert s.device_health() == {"connected": False, "virtual": False, "lost": True}
    assert s.connected is False


def test_device_health_busy_skips_probe():
    s = Session(connect=False)
    s.attach_demo("n0110")
    assert s._io_lock.acquire(blocking=False)  # simulate an operation holding the device
    try:
        assert s.device_health() == {"connected": True, "virtual": True, "busy": True}
    finally:
        s._io_lock.release()


def test_user_local_app_listed_and_installed_verbatim(tmp_path, monkeypatch):
    # #6: a .nwa dropped in the user apps dir shows up in "Available" AND installs its REAL bytes
    # (not a synthesized demo image) — the generic self-hosted source behind the UI.
    from nwupdater.formats.nwa import build_nwa

    d = tmp_path / "apps"
    d.mkdir()
    blob = build_nwa("LocalGame", api_level=0, code=b"\x07" * 512)
    (d / "LocalGame.nwa").write_bytes(blob)
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(d))
    s = Session(connect=False, cache_dir=tmp_path / "cache")
    s.attach_demo("n0110")
    assert "LocalGame" in [a["name"] for a in s.apps()["apps"]]
    r = s.add_store_app("LocalGame")
    assert r["ok"] and r["name"] == "LocalGame"
    got = next(m for m in s._appmgr().installed() if m.name == "LocalGame")
    assert got.blob == blob  # the exact local file bytes were flashed, not a synthesized image


def test_user_url_entry_is_proxy_allowlisted(tmp_path, monkeypatch):
    from nwupdater.apps import proxy

    d = tmp_path / "apps"
    d.mkdir()
    (d / "_urls.txt").write_text("https://host.example/cool.nwa\n")
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(d))
    s = Session(connect=False, cache_dir=tmp_path / "cache")
    proxy._require_allowed(s.store, "https://host.example/cool.nwa")  # in the store now → allowed
    with pytest.raises(ValueError):
        proxy._require_allowed(s.store, "https://evil.example/x.nwa")  # not listed → refused


def test_install_firmware_download_branch(tmp_path, monkeypatch):
    # Cover the signed-in "download the official .dfu" path without touching the network.
    from types import SimpleNamespace

    from nwupdater.catalog import auth as A
    from nwupdater.catalog import download as D
    from nwupdater.install.image import FirmwareImage
    from nwupdater.models import MODELS

    s = Session(connect=False, cache_dir=tmp_path)
    s.attach_demo("n0110")
    blob = FirmwareImage.synthetic(MODELS[0x0110], version="25.2.0").to_dfuse()
    monkeypatch.setattr(A, "load_auth", lambda **k: SimpleNamespace(is_expired=lambda: False))
    monkeypatch.setattr(
        D,
        "fetch_firmware",
        lambda *a, **k: (SimpleNamespace(version="25.2.0", patch_level="c0ffee"), blob),
    )
    monkeypatch.setattr(D, "record_download", lambda *a, **k: "/tmp/nwupdater-provenance.log")
    r = s.install_firmware("", download=True, channel="stable")
    assert r["downloaded"] is True and r["from_cache"] is False
    assert r["to_version"] == "25.2.0" and r["sha256"]


def test_install_firmware_download_requires_auth(tmp_path, monkeypatch):
    from nwupdater.catalog import auth as A

    s = Session(connect=False, cache_dir=tmp_path)
    s.attach_demo("n0110")
    monkeypatch.setattr(A, "load_auth", lambda **k: None)  # not signed in
    with pytest.raises(ValueError, match="authentication required"):
        s.install_firmware("25.2.0", download=True)


def test_active_slot_detection():
    # Graphing demo device runs from slot A; a single-slot scientific always reports "A".
    s = Session(connect=False)
    s.attach_demo("n0110")
    assert s._active_slot() == "A"
    s.attach_demo("n0200")
    assert s._active_slot() == "A"


def test_ui_parser_rejects_removed_real_flag():
    from nwupdater import cli

    with pytest.raises(SystemExit):  # --real was never read and is removed from the ui subparser
        cli.main(["ui", "--real", "--no-browser"])


def test_scripts_list_and_push_and_delete():
    s = Session(model_name="n0110")
    d = s.scripts()
    assert d["has_scripts"] and any(x["name"] == "mandelbrot.py" for x in d["scripts"])

    s.push_script("newone", "print(1)\n", True)
    assert any(x["name"] == "newone.py" and x["auto_import"] for x in s.scripts()["scripts"])

    s.delete_script("mandelbrot")
    names = {x["name"] for x in s.scripts()["scripts"]}
    assert "mandelbrot.py" not in names and "newone.py" in names


def test_scripts_absent_on_scientific():
    s = Session(model_name="n0200")
    assert s.scripts()["has_scripts"] is False


@pytest.mark.parametrize("model", ["n0110", "n0120"])
def test_demo_graphing_device_is_populated(model):
    # The 'explore a demo' graphing device ships realistic on-calc content so BOTH workshops
    # render populated offline: non-empty installed apps (each with a decodable icon) + scripts.
    s = Session(model_name=model)
    installed = s.installed_apps_on_device()["installed"]
    assert installed, "demo apps region should not be empty"
    assert all(a["api_level"] == 0 for a in installed)
    assert all(a["name"] and a["size"] > 0 for a in installed)
    assert all(a["icon"] for a in installed)  # real, decodable icons
    d = s.scripts()
    assert d["has_scripts"] and d["scripts"]


def test_demo_scientific_has_no_apps_region():
    # A scientifique demo (N0200) has no external-apps region, so the Apps workshop is absent and
    # nothing is (or can be) installed — while firmware update still works elsewhere.
    s = Session(model_name="n0200")
    assert s.identity()["has_external_apps"] is False
    assert s.apps()["has_external_apps"] is False
    assert s.installed_apps_on_device()["installed"] == []
    assert s.scripts()["has_scripts"] is False


def test_apps_device_truth_push_uninstall_reorder():
    s = Session(connect=False)
    s.attach_demo("n0110", preinstalled_apps=False)  # blank region: manage apps from empty
    s.push_app("a.nwa", build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    s.push_app("b.nwa", build_nwa("Beta", api_level=0, code=b"\x02" * 100))
    assert [x["name"] for x in s.installed_apps_on_device()["installed"]] == ["Alpha", "Beta"]

    s.uninstall_app("Alpha")
    assert [x["name"] for x in s.installed_apps_on_device()["installed"]] == ["Beta"]

    s.push_app("c.nwa", build_nwa("Gamma", api_level=0, code=b"\x03" * 100))
    s.reorder_apps(["Gamma", "Beta"])
    assert [x["name"] for x in s.installed_apps_on_device()["installed"]] == ["Gamma", "Beta"]


def test_export_app_saves_to_local_library_and_flags_it(tmp_path, monkeypatch):
    import base64

    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path))
    s = Session(connect=False)
    s.attach_demo("n0110", preinstalled_apps=False)  # blank region: Alpha is the only app
    s.push_app("a.nwa", build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    # Nothing in the local library yet → not flagged.
    assert s.installed_apps_on_device()["installed"][0]["local"] is False

    r = s.export_app("Alpha")
    assert r["ok"] and r["filename"] == "Alpha.nwa"
    saved = tmp_path / "Alpha.nwa"
    assert saved.is_file()
    assert base64.b64decode(r["data_b64"]) == saved.read_bytes()
    # Same name + same byte size now present locally → flagged so the UI shows "already there".
    assert s.installed_apps_on_device()["installed"][0]["local"] is True


def test_export_app_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path))
    s = Session(model_name="n0110")
    with pytest.raises(ValueError, match="not installed"):
        s.export_app("Nope")


def test_export_script_saves_to_local_library_and_flags_it(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_SCRIPTS_DIR", str(tmp_path))
    s = Session(model_name="n0110")  # the demo device seeds mandelbrot.py
    assert any(x["name"] == "mandelbrot.py" and x["local"] is False for x in s.scripts()["scripts"])

    r = s.export_script("mandelbrot")
    assert r["ok"] and r["filename"] == "mandelbrot.py"
    saved = tmp_path / "mandelbrot.py"
    assert saved.is_file() and saved.read_text(encoding="utf-8") == r["code"]
    assert any(x["name"] == "mandelbrot.py" and x["local"] is True for x in s.scripts()["scripts"])


def test_scientific_bundled_snapshot():
    cat = FirmwareCatalog.bundled("firmwares-n0200")
    assert cat.latest().version == "3.0.0"
    assert cat.is_up_to_date("2.9.0") is False
    assert cat.is_up_to_date("3.0.0") is True


def test_catalog_is_family_aware():
    # A demo picker attach (no explicit os) puts the device on its own family's version line.
    g = Session(connect=False)
    g.attach_demo("n0110")
    assert g.catalog_updates()["latest"] == "25.2.0"

    s = Session(connect=False)
    s.attach_demo("n0200")
    cs = s.catalog_updates()
    assert cs["current"] == "2.9.0"
    assert cs["latest"] == "3.0.0"
    assert cs["up_to_date"] is False
    assert cs["updates"][0]["version"] == "3.0.0"
    assert cs["source"] == "sample"


def _make_token(exp="2099-01-01T00:00:00Z"):
    import base64
    import json as _j

    from nwupdater.catalog import auth as A

    payload = {"_rails": {"message": "W1td", "exp": exp, "pur": A.REMEMBER_PURPOSE}}
    return base64.b64encode(_j.dumps(payload).encode()).decode() + "--sig"


class _FakeTransport:
    def __init__(self, routes):
        self.routes = routes

    def open(self, method, url, *, headers=None, data=None, timeout=20.0, allow_redirects=False):
        return self.routes[(method, url)]


def test_catalog_live_official_when_signed_in():
    import json as _j

    from nwupdater.catalog import download as D
    from nwupdater.catalog.auth import Auth, Response

    # live_catalog on + a valid (fake) token + a fake transport → the REAL per-model manifest.
    s = Session(connect=False, live_catalog=True)
    s.attach_demo("n0200")  # installed 3.0.0 (bundled family default)
    s._auth_override = Auth(_make_token())
    manifest = _j.dumps(
        {
            "version": "3.4.0",
            "patch_level": "abc1234",
            "device_model": {"device_type_id": 6},
            "size": 100,
        }
    ).encode()
    s._transport = _FakeTransport(
        {("GET", D.manifest_url("n0200", "stable")): Response(200, [], manifest)}
    )
    c = s.catalog_updates()
    assert c["source"] == "official"
    assert c["latest"] == "3.4.0"
    assert c["up_to_date"] is False
    assert c["updates"][0]["version"] == "3.4.0"


def test_catalog_live_off_never_touches_network():
    # Default Session (live_catalog off) must stay fully offline: bundled snapshot only.
    s = Session(connect=False)
    s.attach_demo("n0200")
    s._transport = _FakeTransport({})  # any network use would KeyError on an empty route table
    assert s.catalog_updates()["source"] == "sample"


def test_preload_caches_real_firmware_when_signed_in(tmp_path, monkeypatch):
    import json as _j

    from nwupdater.catalog import download as D
    from nwupdater.catalog.auth import Auth, Response
    from nwupdater.install.image import FirmwareImage
    from nwupdater.models import MODELS

    monkeypatch.setattr(D, "record_download", lambda *a, **k: None)  # no disk provenance in tests
    dfu = FirmwareImage.synthetic(MODELS[0x0110], version="25.2.0").to_dfuse()
    manifest = _j.dumps(
        {
            "version": "25.2.0",
            "patch_level": "43f67db",
            "device_model": {"device_type_id": 1},
            "size": len(dfu),
        }
    ).encode()
    s = Session(connect=False, live_catalog=True, cache_dir=tmp_path)
    s.attach_demo("n0110")
    s._auth_override = Auth(_make_token())
    s._transport = _FakeTransport(
        {
            ("GET", D.manifest_url("n0110", "stable")): Response(200, [], manifest),
            ("GET", D.dfu_url("n0110", "stable")): Response(200, [], dfu),
        }
    )
    r = s.preload("25.2.0")
    assert r["real"] is True
    assert r["entries"][0] == {
        "model": "n0110",
        "version": "25.2.0",
        "size": len(dfu),
        "real": True,
        "channel": "stable",
    }


def test_preload_synthetic_when_offline(tmp_path):
    s = Session(connect=False, cache_dir=tmp_path)  # live_catalog off → never the network
    s.attach_demo("n0110")
    r = s.preload("25.2.0")
    assert r["real"] is False
    assert r["entries"][0]["real"] is False


def test_fetch_app_allowlist_and_download():
    import pytest

    from nwupdater.catalog.auth import Response
    from nwupdater.formats.appicon import demo_icon_lz4

    s = Session(connect=False)
    s.attach_demo("n0120")
    url = next(e.url for e in s.store.entries if e.name == "RPN")
    nwa = build_nwa("RPN", api_level=0, code=b"\x00" * 4096, icon=demo_icon_lz4("RPN"))
    s._transport = _FakeTransport({("GET", url): Response(200, [], nwa)})
    r = s.fetch_app(url)
    assert r["ok"] and r["size"] == len(nwa) and r["icon"].startswith("data:image/bmp")
    with pytest.raises(ValueError):  # SSRF guard: refuse a URL not in the catalogue
        s.fetch_app("https://evil.example/x.nwa")


def test_add_store_app_fetches_and_installs_real_bytes():
    # A catalogue entry with a real URL (not example.invalid) is downloaded through the SSRF-guarded
    # proxy and its REAL bytes are installed — no synthesized demo image.
    from nwupdater.catalog.auth import Response
    from nwupdater.formats.appicon import demo_icon_lz4

    s = Session(connect=False)
    s.attach_demo("n0110")
    url = next(e.url for e in s.store.entries if e.name == "RPN")
    nwa = build_nwa("RPN", api_level=0, code=b"\x00" * 4096, icon=demo_icon_lz4("RPN"))
    s._transport = _FakeTransport({("GET", url): Response(200, [], nwa)})
    r = s.add_store_app("RPN")
    assert r["ok"] and r["name"] == "RPN"
    got = next(m for m in s._appmgr().installed() if m.name == "RPN")
    assert got.blob == nwa  # the exact fetched bytes were flashed, not a synthesized image


def test_add_store_app_synthesizes_for_placeholder_url():
    # An example.invalid placeholder has no real download → fall back to the demo image (offline).
    # The shipped catalogue no longer carries placeholders (they crash on launch), so inject one.
    from nwupdater.apps.store import AppEntry

    s = Session(connect=False)
    s.attach_demo("n0110")
    s.store.entries.append(
        AppEntry(
            name="DemoApp",
            version="1.0",
            api_level=0,
            family="graphique",
            url="https://example.invalid/demoapp.nwa",
            size=65536,
        )
    )
    r = s.add_store_app("DemoApp")  # placeholder URL → synthesized demo image, no network
    assert r["ok"] and r["name"] == "DemoApp"


def test_scripts_available_aggregates_user_sources(tmp_path, monkeypatch):
    # The bundled scripts catalogue is empty by design; `available` reflects the user's own generic
    # sources (local .py + a _urls.txt list) under the user scripts dir.
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "hello.py").write_text("print(1)\n")
    (d / "_urls.txt").write_text("https://host.example/pub/util.py\n")
    monkeypatch.setenv("NWUPDATER_SCRIPTS_DIR", str(d))
    s = Session(model_name="n0110")
    by_name = {a["name"]: a for a in s.scripts()["available"]}
    assert by_name["hello.py"]["source"] == "local file"
    assert by_name["util.py"]["url"] == "https://host.example/pub/util.py"
    assert by_name["util.py"]["source"] == "host.example"


def test_open_app_stream_ssrf_guard():
    import pytest

    s = Session(connect=False)
    s.attach_demo("n0120")
    with pytest.raises(ValueError):
        s.open_app_stream("https://evil.example/x.nwa")  # not in the catalogue
    with pytest.raises(ValueError):
        s.open_app_stream("http://example.invalid/x.nwa")  # not https


def test_preload_all_caches_every_model(tmp_path):
    from nwupdater.models import MODELS

    s = Session(connect=False, cache_dir=tmp_path)  # live off → synthetic, offline
    s.attach_demo("n0110")
    r = s.preload_all()
    assert {e["model"] for e in r["entries"]} == {m.name for m in MODELS.values()}
    assert all(e["real"] is False for e in r["entries"])


def test_preload_all_extends_ttl_on_second_run(tmp_path):
    s = Session(connect=False, cache_dir=tmp_path)
    s.attach_demo("n0110")
    first = s.preload_all()
    assert first["downloaded"] > 0 and first["refreshed"] == 0
    second = s.preload_all()  # same versions already cached → extend the TTL, no re-download
    assert second["downloaded"] == 0 and second["refreshed"] == first["downloaded"]


def test_reveal_folder_creates_dir_and_spawns_file_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path / "apps"))
    monkeypatch.setenv("NWUPDATER_SCRIPTS_DIR", str(tmp_path / "scripts"))
    calls: list = []
    monkeypatch.setattr("subprocess.Popen", lambda argv, **kw: calls.append(argv) or object())
    s = Session(connect=False)
    out = s.reveal_folder("apps")
    assert out["ok"] and out["which"] == "apps"
    assert (tmp_path / "apps").is_dir()  # created on demand
    assert calls and str(tmp_path / "apps") in calls[0]  # whitelisted path handed to the file manager
    s.reveal_folder("scripts")
    assert str(tmp_path / "scripts") in calls[1]


def test_reveal_folder_rejects_unknown_key():
    s = Session(connect=False)
    with pytest.raises(ValueError):
        s.reveal_folder("../etc")  # only "apps"/"scripts" resolve — no arbitrary path


def test_apps_report_nwlink_availability(monkeypatch):
    s = Session(model_name="n0110")
    monkeypatch.setattr("nwupdater.apps.link.nwlink_available", lambda: False)
    assert s.apps()["nwlink"] is False


def test_batch_run_files_and_records_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("NWUPDATER_SCRIPTS_DIR", str(tmp_path / "scripts"))
    from nwupdater import classroom_roster as R

    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "stats.py").write_text("print(1)\n", encoding="utf-8")
    s = Session(model_name="n0110", os_version="99.0.0")  # newer than any catalogue → firmware "ok"
    R.set_distribution(
        "Seconde A",
        {
            "actions": {"census": True, "firmware": True, "apps": False, "scripts": True},
            "onboarding": "move",
            "apps": [],
            "scripts": ["stats.py"],
        },
    )
    j = s.batch_run("Seconde A")
    assert j["dist"]["recensement"] == "ok"  # newly filed
    assert j["dist"]["firmware"] == "ok"  # already up to date
    assert j["dist"]["scripts"] == "change"  # stats.py pushed
    assert "apps" not in j["dist"]  # the apps action was off → its panel/step is skipped
    entry = next(e for e in R.all_entries() if e["class"] == "Seconde A")
    assert entry["last_dist"]["scripts"] == "change"
    assert any(x["name"] in ("stats.py", "stats") for x in s.scripts()["scripts"])  # really on device
    assert ":" in j["key"]  # opaque id (model:serial) — never rendered


def test_batch_run_ignore_refuses_calc_filed_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("NWUPDATER_CONFIG_DIR", str(tmp_path))
    from nwupdater import classroom_roster as R
    from nwupdater import device_names

    s = Session(model_name="n0110", os_version="99.0.0")
    i = s._identity()
    key = device_names._key(i.model_name or "", i.serial_number or "")
    R.upsert_on_scan(i.model_name or "", i.serial_number or "", firmware=i.os_version, family=i.family)
    R.move([key], "Terminale S")  # already filed in another class
    R.set_distribution(
        "Seconde A",
        {"actions": {"census": True, "firmware": False, "apps": False, "scripts": False}, "onboarding": "ignore"},
    )
    j = s.batch_run("Seconde A")
    assert j["dist"] == {"recensement": "error"}  # refused, chain stopped
    assert next(e for e in R.all_entries() if e["key"] == key)["class"] == "Terminale S"  # untouched


def test_set_scripts_rewrites_store_in_order():
    s = Session(model_name="n0110")
    s.set_scripts(
        [
            {"name": "alpha", "code": "print(1)\n", "auto_import": True},
            {"name": "beta.py", "code": "print(2)\n", "auto_import": False},
        ]
    )
    got = s.scripts()["scripts"]
    assert [x["name"] for x in got] == ["alpha.py", "beta.py"]
    assert got[0]["auto_import"] is True and got[1]["auto_import"] is False
