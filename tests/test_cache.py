"""Firmware cache tests — one-entry-per-model policy + 30-day auto-expiry, offline."""

from nwupdater.cache.store import FirmwareCache


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_put_get_roundtrip(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"FIRMWARE-A")
    assert c.get("n0110", "25.2.0") == b"FIRMWARE-A"
    assert c.has("n0110", "25.2.0")


def test_keeps_one_entry_per_model(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "24.3.0", b"OLD")
    c.put("n0120", "24.3.0", b"OLD-120")
    assert set(c.status()["models"]) == {"n0110", "n0120"}
    # re-caching a model replaces ONLY that model's entry (fleet keeps latest per model)
    c.put("n0110", "25.2.0", b"NEW")
    assert c.get("n0110", "24.3.0") is None  # old n0110 version evicted
    assert c.get("n0110", "25.2.0") == b"NEW"
    assert c.get("n0120", "24.3.0") == b"OLD-120"  # other model untouched
    assert set(c.status()["models"]) == {"n0110", "n0120"}


def test_classroom_multi_family_multi_version(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"G", real=True)
    c.put("n0200", "3.0.0", b"S", real=True)  # different family + version -> both kept
    assert c.has("n0110", "25.2.0") and c.has("n0200", "3.0.0")
    assert {e["model"] for e in c.status()["entries"]} == {"n0110", "n0200"}


def test_classroom_same_version_multiple_models(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"A")
    c.put("n0120", "25.2.0", b"B")  # add a second model of the SAME version -> kept
    assert c.has("n0110", "25.2.0") and c.has("n0120", "25.2.0")
    assert c.status()["version"] == "25.2.0"


def test_mixed_fleet_versions_report_no_single_version(tmp_path):
    # Two models cached at DIFFERENT versions -> no single common version.
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"G")
    c.put("n0200", "3.0.0", b"S")
    assert c.cached_version() is None
    assert c.status()["version"] is None


def test_auto_expiry_after_ttl(tmp_path):
    clock = Clock()
    c = FirmwareCache(tmp_path, ttl_days=30, now=clock)
    c.put("n0110", "25.2.0", b"DATA")
    assert c.has("n0110", "25.2.0")
    clock.t += 29 * 86400  # still fresh at 29 days
    assert c.has("n0110", "25.2.0")
    clock.t += 2 * 86400  # now 31 days -> expired & pruned
    assert c.get("n0110", "25.2.0") is None
    assert c.status()["version"] is None


def test_touch_extends_ttl_without_redownload(tmp_path):
    clock = Clock()
    c = FirmwareCache(tmp_path, ttl_days=30, now=clock)
    c.put("n0110", "25.2.0", b"DATA")
    clock.t += 20 * 86400  # 20 days later
    assert c.touch("n0110") is True  # extend from now — no re-download
    clock.t += 20 * 86400  # 40 days after the original put, but only 20 since the touch
    assert c.has("n0110", "25.2.0")  # still fresh thanks to the touch
    assert c.touch("n0120") is False  # nothing cached for this model
    assert (
        c.touch("n0110", "0.0.0") is False
    )  # version-guarded: only the matching version refreshes


def test_status_reports_expiry(tmp_path):
    clock = Clock()
    c = FirmwareCache(tmp_path, ttl_days=30, now=clock)
    e = c.put("n0110", "25.2.0", b"XYZ")
    st = c.status()
    assert st["version"] == "25.2.0"
    assert st["total_size"] == 3
    assert st["expires_at"] == e.downloaded_at + 30 * 86400
    assert st["ttl_days"] == 30


def test_clear(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"DATA")
    c.clear()
    assert c.get("n0110", "25.2.0") is None
    assert c.entries() == []


def test_sha_recorded(tmp_path):
    import hashlib

    c = FirmwareCache(tmp_path)
    e = c.put("n0110", "25.2.0", b"DATA")
    assert e.sha256 == hashlib.sha256(b"DATA").hexdigest()


def test_reads_do_not_rewrite_index_when_nothing_expired(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"DATA")
    saves = 0
    orig = c._save

    def counting(entries):
        nonlocal saves
        saves += 1
        orig(entries)

    c._save = counting
    assert c.get("n0110", "25.2.0") == b"DATA"
    c.has("n0110", "25.2.0")
    c.entries()
    assert saves == 0  # pure reads never rewrite index.json


def test_expiry_is_persisted_to_the_index(tmp_path):
    import json

    clock = Clock()
    c = FirmwareCache(tmp_path, ttl_days=30, now=clock)
    c.put("n0110", "25.2.0", b"DATA")
    clock.t += 31 * 86400
    c.get("n0110", "25.2.0")  # expired -> pruned AND written back
    assert json.loads((tmp_path / "index.json").read_text()) == {}


def test_corrupt_index_is_treated_as_empty_and_self_heals(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"DATA")
    (tmp_path / "index.json").write_text("{ not valid json")
    assert c.get("n0110", "25.2.0") is None  # no crash
    assert c.entries() == []
    c.put("n0120", "1.0.0", b"E")  # cache still usable afterwards
    assert c.get("n0120", "1.0.0") == b"E"


def test_channel_defaults_to_stable_and_is_reported(tmp_path):
    c = FirmwareCache(tmp_path)
    e = c.put("n0110", "25.2.0", b"DATA")
    assert e.channel == "stable"
    assert c.status()["entries"][0]["channel"] == "stable"


def test_channel_beta_is_persisted_and_surfaced(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "26.1.0", b"BETA", real=True, channel="beta")
    # survives a reload from index.json (fresh instance, same dir)
    c2 = FirmwareCache(tmp_path)
    entry = next(e for e in c2.status()["entries"] if e["model"] == "n0110")
    assert entry["channel"] == "beta"


def test_old_index_without_channel_loads_as_stable(tmp_path):
    import json

    # An index written before the channel field existed must still load (defaulted), not be
    # discarded as schema-incompatible.
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"DATA")
    raw = json.loads((tmp_path / "index.json").read_text())
    for v in raw.values():
        v.pop("channel", None)
    (tmp_path / "index.json").write_text(json.dumps(raw))
    c2 = FirmwareCache(tmp_path)
    assert c2.get("n0110", "25.2.0") == b"DATA"
    assert c2.status()["entries"][0]["channel"] == "stable"


def test_no_temp_files_left_after_writes(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"DATA")
    c.clear()
    c.put("n0120", "1.0.0", b"E")
    assert not list(tmp_path.glob(".*.tmp"))
