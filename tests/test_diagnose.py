"""Diagnostic harness tests — fully offline against the virtual device (no real USB)."""

from nwupdater.dfu.capture import CapturingDevice
from nwupdater.dfu.protocol import DfuClient
from nwupdater.diagnose import diagnose
from nwupdater.testing.virtual_dfu import virtual_calculator


def _report(model="n0110", **kw):
    dev = virtual_calculator(model, **kw)
    return diagnose(dev, interface=0, bcd_device=dev.bcdDevice, sleep=lambda *_: None,
                    timestamp="2026-07-12T00:00:00+00:00")


def test_capturing_device_records_transfers():
    dev = virtual_calculator("n0110")
    cap = CapturingDevice(dev)
    DfuClient(cap, sleep=lambda *_: None).get_state()
    assert cap.transfers and cap.transfers[0]["dir"] == "IN"
    assert cap.transfers[0]["bRequest"] == 5  # DFU_GETSTATE
    assert cap.idVendor == dev.idVendor and cap.bcdDevice == dev.bcdDevice


def test_diagnose_graphing_report():
    r = _report("n0110", os_version="23.2.4", commit="abc1234")
    assert r["model"] == "n0110" and r["family"] == "graphique"
    assert r["os_version"] == "23.2.4" and r["commit"] == "abc1234"
    assert r["slot_info_valid"] is True
    assert r["external_apps_flash"] is not None
    assert r["transfer_count"] > 0 and r["error"] is None
    assert r["read_only"] is True
    assert r["usb"]["idProduct"] == "0xa291"
    assert r["serial_number"] and len(r["serial_number"]) == 16  # My Devices pairing key


def test_diagnose_scientific_no_external_apps():
    r = _report("n0200", os_version="3.0.0")
    assert r["family"] == "scientifique"
    assert r["external_apps_flash"] is None


def test_diagnose_is_strictly_read_only():
    """No erase and no data-block download: read_identity must only read + set the pointer."""
    r = _report("n0110")
    for tr in r["transfers"]:
        if tr["bRequest"] == 1:  # DFU_DNLOAD
            wvalue = int(tr["wValue"], 16)
            assert wvalue == 0, "no data-block write (wValue>=2) during a read-only diagnose"
            cmd = bytes.fromhex(tr["data"])[0] if tr["data"] else None
            assert cmd == 0x21, "only Set-Address (0x21) — never Erase (0x41) or a write"


def test_diagnose_transfers_have_expected_shape():
    r = _report("n0110")
    kinds = {tr["bRequest"] for tr in r["transfers"]}
    assert 2 in kinds   # DFU_UPLOAD (reads headers)
    assert 3 in kinds or 5 in kinds  # GETSTATUS / GETSTATE
    for tr in r["transfers"]:
        assert set(tr) >= {"seq", "dir", "bmRequestType", "bRequest", "wValue", "wIndex", "data"}
