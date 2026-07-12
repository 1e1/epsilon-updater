"""Lot 2 — firmware catalog tests. Fully offline (bundled snapshot + inline fixtures)."""


from nwupdater.catalog.firmware import FirmwareCatalog, FirmwareRelease
from nwupdater.catalog.version import compare, is_newer, parse_version

FIXTURE = [
    {"version": "25.2.0", "patch_level": "43f67db"},
    {"version": "24.11.0", "patch_level": "a58aaa0"},
    {"version": "16.4.4", "patch_level": "088dcb9"},
    {"version": "1.1.0", "patch_level": "679cea7"},
]


def test_parse_version():
    assert parse_version("25.2.0") == (25, 2)
    assert parse_version("16.4.4") == (16, 4, 4)
    assert parse_version(" 23.2.4\x00") == (23, 2, 4)


def test_compare_and_is_newer():
    assert compare("25.2.0", "24.11.0") == 1
    assert compare("24.11.0", "25.2.0") == -1
    assert compare("23.2.4", "23.2.4") == 0
    assert compare("25.2.0", "25.2") == 0  # trailing zero ignored
    assert is_newer("16.4.4", "16.4.3") is True
    assert is_newer("2.0.0", "16.4.4") is False


def test_catalog_sorted_newest_first_and_deduped():
    cat = FirmwareCatalog.from_json(FIXTURE + [{"version": "25.2.0", "patch_level": "dup"}])
    assert len(cat) == 4  # dedup
    assert cat.latest().version == "25.2.0"
    assert [r.version for r in cat.releases][0] == "25.2.0"


def test_updates_for():
    cat = FirmwareCatalog.from_json(FIXTURE)
    ups = cat.updates_for("16.4.4")
    assert [r.version for r in ups] == ["25.2.0", "24.11.0"]
    assert cat.is_up_to_date("25.2.0") is True
    assert cat.is_up_to_date("25.3.0") is True  # newer than catalog -> up to date
    assert cat.is_up_to_date("1.1.0") is False


def test_bundled_snapshot_loads():
    cat = FirmwareCatalog.bundled()
    assert len(cat) >= 50
    assert cat.latest() is not None
    # snapshot captured 2026-07 had 25.2.0 as latest
    assert cat.get("25.2.0") is not None


def test_release_str():
    r = FirmwareRelease("25.2.0", "43f67db")
    assert str(r) == "25.2.0 (43f67db)"
