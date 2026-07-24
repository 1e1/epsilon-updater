"""Smoke tests for the CLI virtual-device path (the shared ``_open_device`` dispatch).

These run fully offline against the in-process virtual device — no USB, no network — and
guard the per-command device-open wiring that used to be copy-pasted."""

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
