"""Lot 4 — third-party apps: .nwa format, store, install. Offline, virtual device only."""

import pytest

from nwupdater.apps.installer import AppCompatibilityError, AppInstaller
from nwupdater.apps.store import AppStore
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient
from nwupdater.formats.nwa import AppInfo, build_nwa
from nwupdater.testing.virtual_dfu import virtual_calculator


def _client(dev):
    return DfuClient(dev, sleep=lambda *_: None)


def test_nwa_build_and_parse_roundtrip():
    blob = build_nwa("Tetris", api_level=0, code=b"\x01\x02\x03\x04")
    info = AppInfo.parse(blob)
    assert info.valid is True
    assert info.name == "Tetris"
    assert info.api_level == 0
    assert info.app_size == len(blob)


def test_parse_rejects_non_nwa():
    assert AppInfo.parse(b"not an app").valid is False


def test_store_bundled_and_compat_filter():
    store = AppStore.bundled()
    assert len(store) >= 5
    compat = store.compatible(family="graphique", device_api_level=0, has_external_apps=True)
    names = {e.name for e in compat}
    assert "Tetris" in names
    assert "Periodic" not in names  # api_level 1 filtered out
    # scientific / no external-apps region -> nothing compatible
    assert (
        store.compatible(family="scientifique", device_api_level=0, has_external_apps=False) == []
    )


def test_install_app_into_external_region_and_verify():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    ident = read_identity(cli, dev.bcdDevice)
    assert ident.external_apps_flash is not None

    inst = AppInstaller(cli, external_apps_flash=ident.external_apps_flash, device_api_level=0)
    blob = build_nwa("Nofrendo", api_level=0, code=b"\xaa" * 512)
    result = inst.install(blob)

    assert result.name == "Nofrendo"
    assert result.address == ident.external_apps_flash[0]
    # read it back off the device and re-parse -> still a valid app
    back = cli.read(result.address, len(blob))
    assert AppInfo.parse(back).name == "Nofrendo"


def test_install_rejects_api_level_mismatch():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    ident = read_identity(cli, dev.bcdDevice)
    inst = AppInstaller(cli, external_apps_flash=ident.external_apps_flash, device_api_level=0)
    with pytest.raises(AppCompatibilityError):
        inst.install(build_nwa("Periodic", api_level=1))


def test_install_rejects_when_no_external_region_scientific():
    dev = virtual_calculator("n0200")
    cli = _client(dev)
    ident = read_identity(cli, dev.bcdDevice)
    inst = AppInstaller(cli, external_apps_flash=ident.external_apps_flash or (0, 0))
    with pytest.raises(AppCompatibilityError):
        inst.install(build_nwa("Tetris", api_level=0))
