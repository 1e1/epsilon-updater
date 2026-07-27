"""App management on the external-apps region: push / uninstall / reorder with compaction."""

import struct

import pytest

from nwupdater.apps.installer import list_installed
from nwupdater.apps.manage import SECTOR, AppError, AppManager
from nwupdater.dfu import constants as C
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient
from nwupdater.formats.nwa import build_nwa
from nwupdater.testing.virtual_dfu import virtual_calculator


def _mgr(model="n0110"):
    dev = virtual_calculator(model)
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    return cli, ident, AppManager(cli, ident.external_apps_flash, device_api_level=0)


class _EraseRecorder:
    """Wraps a virtual device to record the addresses of DfuSe ERASE commands."""

    def __init__(self, inner):
        self._inner = inner
        self.erases: list[int] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def ctrl_transfer(
        self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None
    ):
        if (
            bmRequestType == C.REQ_OUT
            and bRequest == C.DFU_DNLOAD
            and wValue == 0
            and data_or_wLength
        ):
            data = bytes(data_or_wLength)
            if data and data[0] == C.DFUSE_ERASE and len(data) >= 5:
                self.erases.append(struct.unpack("<I", data[1:5])[0])
        return self._inner.ctrl_transfer(
            bmRequestType, bRequest, wValue, wIndex, data_or_wLength, timeout
        )


def _recording_mgr(model="n0110"):
    dev = _EraseRecorder(virtual_calculator(model))
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    mgr = AppManager(cli, ident.external_apps_flash, device_api_level=0)
    dev.erases.clear()  # a read-only identity read never erases; start from a clean slate
    return dev, ident, mgr


def test_apply_erases_once_per_64k_sector():
    # Regression for the per-chunk erase bug: the erase loop stepped by the 2048-byte transfer
    # size, re-issuing 32 redundant ERASE commands per 64 KiB sector. It must step by SECTOR.
    dev, ident, mgr = _recording_mgr()
    start = ident.external_apps_flash[0]
    mgr.push(build_nwa("Alpha", api_level=0, code=b"\x01" * 100))  # ~1 sector
    assert dev.erases == [start]  # exactly one erase for the single 64 KiB sector


def test_apply_erases_span_two_sectors_once_each():
    dev, ident, mgr = _recording_mgr()
    start = ident.external_apps_flash[0]
    mgr.push(build_nwa("Big", api_level=0, code=b"\x02" * (SECTOR + 4096)))  # spans 2 sectors
    assert dev.erases == [start, start + SECTOR]  # one erase per sector, aligned


def test_push_then_uninstall_compacts():
    cli, ident, mgr = _mgr()
    mgr.push(build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    mgr.push(build_nwa("Beta", api_level=0, code=b"\x02" * 100))
    assert [m.name for m in mgr.installed()] == ["Alpha", "Beta"]

    mgr.uninstall("Alpha")
    assert [m.name for m in mgr.installed()] == ["Beta"]
    # Beta was compacted down to the region start (no ghost app left behind)
    assert list_installed(cli, ident.external_apps_flash)[0].offset == 0


def test_reorder():
    _cli, _ident, mgr = _mgr()
    mgr.push(build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    mgr.push(build_nwa("Beta", api_level=0, code=b"\x02" * 100))
    mgr.reorder(["Beta", "Alpha"])
    assert [m.name for m in mgr.installed()] == ["Beta", "Alpha"]


def test_push_rejects_api_mismatch():
    _, _, mgr = _mgr()
    with pytest.raises(AppError):
        mgr.push(build_nwa("X", api_level=1))


def test_push_refuses_duplicate_name():
    # A name is unique on the device: re-pushing must NOT silently create a second copy (which also
    # breaks reorder). The user replaces by removing first (see the delete-then-add flow below).
    _, _, mgr = _mgr()
    mgr.push(build_nwa("Tetris", api_level=0, code=b"\x01" * 100))
    with pytest.raises(AppError):
        mgr.push(build_nwa("Tetris", api_level=0, code=b"\x02" * 100))
    assert [m.name for m in mgr.installed()] == ["Tetris"]  # still exactly one


def test_replace_via_delete_then_add():
    _, _, mgr = _mgr()
    mgr.push(build_nwa("Tetris", api_level=0, code=b"\x01" * 100))
    mgr.uninstall("Tetris")  # stage-delete old ...
    mgr.push(build_nwa("Tetris", api_level=0, code=b"\x02" * 200))  # ... then add the new version
    apps = mgr.installed()
    assert [m.name for m in apps] == ["Tetris"] and apps[0].blob.count(b"\x02") >= 200


def test_uninstall_many_single_rewrite():
    dev, _ident, mgr = _recording_mgr()
    for n in ("A", "B", "C"):
        mgr.push(build_nwa(n, api_level=0, code=b"\x01" * 100))
    dev.erases.clear()
    mgr.uninstall_many(["A", "C"])  # remove two at once
    assert [m.name for m in mgr.installed()] == ["B"]


def test_uninstall_many_reports_missing():
    _, _, mgr = _mgr()
    mgr.push(build_nwa("A", api_level=0, code=b"\x01" * 100))
    with pytest.raises(AppError):
        mgr.uninstall_many(["A", "Ghost"])


def test_usage_is_sector_aligned():
    _, _, mgr = _mgr()
    mgr.push(build_nwa("A", api_level=0, code=b"\x01" * 100))  # ~100 B app -> one 64 KiB sector
    u = mgr.usage()
    assert u["used"] == SECTOR and u["free"] == u["capacity"] - SECTOR


def test_uninstall_unknown_raises():
    _, _, mgr = _mgr()
    with pytest.raises(AppError):
        mgr.uninstall("Nope")


def test_reorder_must_be_a_permutation():
    _, _, mgr = _mgr()
    mgr.push(build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    with pytest.raises(AppError):
        mgr.reorder(["Alpha", "Ghost"])


def test_preinstalled_demo_apps_are_enumerable_and_valid():
    # The populated demo device lays out generic sample apps sector-aligned from the region start;
    # they must enumerate exactly like installed apps and stay manageable (push appends after them).
    dev = virtual_calculator("n0110", preinstalled_apps=True)
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    mgr = AppManager(cli, ident.external_apps_flash, device_api_level=0)
    seeded = mgr.installed()
    assert len(seeded) >= 2
    assert all(a.api_level == 0 and a.name for a in seeded)
    mgr.push(build_nwa("Extra", api_level=0, code=b"\x09" * 100))
    assert [m.name for m in mgr.installed()] == [a.name for a in seeded] + ["Extra"]


def test_preinstalled_apps_noop_on_scientific():
    # N0200 has no external-apps region: preinstalled_apps is a no-op, nothing enumerates.
    dev = virtual_calculator("n0200", preinstalled_apps=True)
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    assert AppManager(cli, ident.external_apps_flash, device_api_level=0).installed() == []
