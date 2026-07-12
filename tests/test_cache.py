"""Firmware cache tests — one-version policy + 30-day auto-expiry, offline."""

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


def test_keeps_only_one_version(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "24.3.0", b"OLD")
    c.put("n0120", "24.3.0", b"OLD-120")   # same version, different model -> both kept
    assert c.status()["version"] == "24.3.0"
    assert set(c.status()["models"]) == {"n0110", "n0120"}
    # caching a new version evicts the previous version entirely
    c.put("n0110", "25.2.0", b"NEW")
    assert c.get("n0110", "24.3.0") is None
    assert c.get("n0120", "24.3.0") is None
    assert c.get("n0110", "25.2.0") == b"NEW"
    assert c.status()["version"] == "25.2.0"


def test_classroom_same_version_multiple_models(tmp_path):
    c = FirmwareCache(tmp_path)
    c.put("n0110", "25.2.0", b"A")
    c.put("n0120", "25.2.0", b"B")  # add a second model of the SAME version -> kept
    assert c.has("n0110", "25.2.0") and c.has("n0120", "25.2.0")
    assert c.status()["version"] == "25.2.0"


def test_auto_expiry_after_ttl(tmp_path):
    clock = Clock()
    c = FirmwareCache(tmp_path, ttl_days=30, now=clock)
    c.put("n0110", "25.2.0", b"DATA")
    assert c.has("n0110", "25.2.0")
    clock.t += 29 * 86400          # still fresh at 29 days
    assert c.has("n0110", "25.2.0")
    clock.t += 2 * 86400           # now 31 days -> expired & pruned
    assert c.get("n0110", "25.2.0") is None
    assert c.status()["version"] is None


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
