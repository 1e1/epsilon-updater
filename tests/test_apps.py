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
    assert {"RPN", "Tetris"} <= names  # real bundled graphique/api-0 entries
    # scientific / no external-apps region -> nothing compatible
    assert (
        store.compatible(family="scientifique", device_api_level=0, has_external_apps=False) == []
    )


def test_compat_filters_by_api_level():
    from nwupdater.apps.store import AppEntry

    store = AppStore(
        [
            AppEntry(name="A0", version="1", api_level=0, family="graphique"),
            AppEntry(name="A1", version="1", api_level=1, family="graphique"),
        ]
    )
    names = {
        e.name
        for e in store.compatible(family="graphique", device_api_level=0, has_external_apps=True)
    }
    assert names == {"A0"}  # api_level 1 filtered out for an api-0 device


def test_bundled_catalog_has_no_placeholder_urls():
    # The shipped catalogue must hold only REAL downloadable apps — never an example.invalid
    # placeholder. A placeholder falls through to the synthesized zero-code demo image, which
    # installs fine but reboots the calculator when launched (see add_store_app). This guard keeps
    # fictitious entries out of the release.
    for e in AppStore.bundled().entries:
        assert e.url.startswith("https://"), f"{e.name}: not an https URL"
        assert "example.invalid" not in e.url, f"{e.name}: placeholder URL shipped"


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
