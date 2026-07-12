"""App management on the external-apps region: push / uninstall / reorder with compaction."""

import pytest

from nwupdater.apps.installer import list_installed
from nwupdater.apps.manage import AppError, AppManager
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient
from nwupdater.formats.nwa import build_nwa
from nwupdater.testing.virtual_dfu import virtual_calculator


def _mgr(model="n0110"):
    dev = virtual_calculator(model)
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    return cli, ident, AppManager(cli, ident.external_apps_flash, device_api_level=0)


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
    cli, ident, mgr = _mgr()
    mgr.push(build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    mgr.push(build_nwa("Beta", api_level=0, code=b"\x02" * 100))
    mgr.reorder(["Beta", "Alpha"])
    assert [m.name for m in mgr.installed()] == ["Beta", "Alpha"]


def test_push_rejects_api_mismatch():
    _, _, mgr = _mgr()
    with pytest.raises(AppError):
        mgr.push(build_nwa("X", api_level=1))


def test_uninstall_unknown_raises():
    _, _, mgr = _mgr()
    with pytest.raises(AppError):
        mgr.uninstall("Nope")


def test_reorder_must_be_a_permutation():
    _, _, mgr = _mgr()
    mgr.push(build_nwa("Alpha", api_level=0, code=b"\x01" * 100))
    with pytest.raises(AppError):
        mgr.reorder(["Alpha", "Ghost"])
