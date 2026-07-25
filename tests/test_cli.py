"""Smoke tests for the CLI virtual-device path (the shared ``_open_device`` dispatch).

These run fully offline against the in-process virtual device — no USB, no network — and
guard the per-command device-open wiring that used to be copy-pasted."""

import builtins

import pytest

from nwupdater import cli


def test_identify_virtual():
    assert cli.main(["identify", "--virtual", "n0110"]) == 0


def test_catalog_virtual():
    assert cli.main(["catalog", "--virtual", "n0110"]) == 0


def test_apps_list_virtual():
    assert cli.main(["apps", "--virtual", "n0110"]) == 0


def test_scripts_list_virtual():
    assert cli.main(["scripts", "--virtual", "n0110"]) == 0


def test_install_virtual():
    assert cli.main(["install", "--virtual", "n0110", "--to-version", "25.2.0"]) == 0


def test_pair_virtual_dry_run():
    assert cli.main(["pair", "--virtual", "n0110", "--dry-run"]) == 0


def test_diagnose_virtual(tmp_path):
    out = tmp_path / "diag.json"
    assert cli.main(["diagnose", "--virtual", "n0110", "--out", str(out)]) == 0
    assert out.exists()


def test_scientific_virtual_identify():
    # N0200: opaque firmware, no apps/scripts — the open path must still work.
    assert cli.main(["identify", "--virtual", "n0200"]) == 0


def test_sources_lists_bundled_and_user(tmp_path, monkeypatch, capsys):
    # `sources` needs no device: it prints the bundled catalogues plus the user's own generic
    # sources (local files + _urls.txt) for both apps and scripts.
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "_urls.txt").write_text("https://host.example/cool.nwa\n")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "hello.py").write_text("print(1)\n")
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(apps))
    monkeypatch.setenv("NWUPDATER_SCRIPTS_DIR", str(scripts))

    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "App sources" in out and "Script sources" in out
    assert "RPN" in out  # a bundled app-catalog entry
    assert "https://host.example/cool.nwa" in out  # user apps _urls.txt entry
    assert "hello.py" in out  # user local script file


def test_apps_install_fetches_and_installs_real_bytes(tmp_path, monkeypatch, capsys):
    # `apps --install NAME` on a catalog entry with a real URL downloads the actual .nwa through the
    # SSRF-guarded proxy and installs its REAL bytes — mirrors the server's add_store_app.
    from nwupdater.apps.store import AppStore
    from nwupdater.catalog.auth import Response
    from nwupdater.formats.appicon import demo_icon_lz4
    from nwupdater.formats.nwa import build_nwa

    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path))  # hermetic: no stray user .nwa
    url = next(e.url for e in AppStore.bundled().entries if e.name == "RPN")
    nwa = build_nwa("RPN", api_level=0, code=b"\x00" * 4096, icon=demo_icon_lz4("RPN"))

    class _FakeTransport:
        def open(self, method, u, *, headers=None, data=None, timeout=20.0, allow_redirects=False):
            assert (method, u) == ("GET", url)  # the allowlisted catalogue URL, over the proxy
            return Response(200, [], nwa)

    monkeypatch.setattr("nwupdater.catalog.auth.UrllibTransport", _FakeTransport)

    assert cli.main(["apps", "--virtual", "n0110", "--install", "RPN"]) == 0
    out = capsys.readouterr().out
    assert f"({len(nwa)} B)" in out  # the exact fetched bytes were flashed, not a synthesized demo


def test_apps_install_synthesizes_for_placeholder_url(tmp_path, monkeypatch, capsys):
    # An example.invalid placeholder has no real download → offline demo fallback, no network. The
    # shipped catalogue holds only real apps now, so supply the placeholder via the user _urls.txt
    # source (aggregated into the store exactly like the web UI).
    monkeypatch.setenv("NWUPDATER_APPS_DIR", str(tmp_path))
    (tmp_path / "_urls.txt").write_text("https://example.invalid/demoapp.nwa\n")

    def _boom():
        raise AssertionError("placeholder install must not fetch over the network")

    monkeypatch.setattr("nwupdater.catalog.auth.UrllibTransport", _boom)
    assert cli.main(["apps", "--virtual", "n0110", "--install", "demoapp.nwa"]) == 0
    out = capsys.readouterr().out
    assert "installed 'demoapp.nwa'" in out


def test_identify_real_without_pyusb_exits(monkeypatch):
    # No --virtual and pyusb unavailable → a clean SystemExit(2), not a traceback.
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.split(".")[0] == "usb":
            raise ImportError("no pyusb")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as ei:
        cli.main(["identify"])
    assert ei.value.code == 2
