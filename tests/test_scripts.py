"""Scripts read/write + apps listing end-to-end against the virtual DFU device. No real USB."""

from nwupdater.apps.installer import AppInstaller, list_installed
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient
from nwupdater.formats.nwa import build_nwa
from nwupdater.formats.storage import make_python
from nwupdater.scripts import read_storage, write_storage
from nwupdater.testing.virtual_dfu import virtual_calculator


def _client(dev):
    return DfuClient(dev, sleep=lambda *_: None)


def test_identity_exposes_storage_zone():
    dev = virtual_calculator("n0110")
    ident = read_identity(_client(dev), dev.bcdDevice)
    assert ident.storage_ram is not None
    addr, size = ident.storage_ram
    assert addr and size


def test_scripts_write_then_read_back():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    ident = read_identity(cli, dev.bcdDevice)
    addr, size = ident.storage_ram
    write_storage(
        cli,
        addr,
        [
            make_python("mandelbrot", "print(1)\n", True),
            make_python("dice", "import random\n", False),
        ],
        capacity=size,
    )
    back = read_storage(cli, addr, size)
    assert [r.fullname for r in back] == ["mandelbrot.py", "dice.py"]
    assert back[0].code == "print(1)\n" and back[0].auto_import
    assert back[1].auto_import is False


def test_list_installed_apps_on_device():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    ident = read_identity(cli, dev.bcdDevice)
    inst = AppInstaller(cli, external_apps_flash=ident.external_apps_flash, device_api_level=0)
    inst.install(build_nwa("Tetris", api_level=0, code=b"\x01" * 200))
    apps = list_installed(cli, ident.external_apps_flash)
    assert [a.info.name for a in apps] == ["Tetris"]
