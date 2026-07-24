"""Alt-setting write routing (dfu/protocol.py) + verified storage write (scripts.py).

NumWorks advertises one DFU alt-setting per memory backend (alt 0 ``@Flash``, alt 1 ``@SRAM``);
a DNLOAD only lands within the CURRENT alt's region — confirmed on a real N0120. The client
discovers the layouts and routes each write to the owning alt (nothing per-model hard-coded).
These tests drive that against a virtual device modelling the two alt-settings.
"""

from __future__ import annotations

import pytest

from nwupdater.dfu import constants as C
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient
from nwupdater.formats.storage import make_python, python_scripts
from nwupdater.scripts import StorageWriteError, read_storage, write_storage
from nwupdater.testing.virtual_dfu import virtual_calculator


def _client(model: str = "n0120"):
    dev = virtual_calculator(model, alt_settings=True)
    return dev, DfuClient(dev, sleep=lambda *_: None)


def test_alt_regions_are_discovered():
    dev, _ = _client()
    alts = dict(dev.alt_regions)
    assert C.ALT_FLASH in alts and C.ALT_SRAM in alts
    # the SRAM alt owns the storage address, the flash alt owns the QSPI base
    assert alts[C.ALT_SRAM].sector_of(dev.model.memory.sram_origin) is not None
    assert alts[C.ALT_FLASH].sector_of(dev.model.memory.external_flash_origin) is not None


def test_storage_write_routes_to_sram_alt_and_lands():
    dev, client = _client()
    addr, size = read_identity(client, dev.bcdDevice).storage_ram
    assert addr and size
    recs = read_storage(client, addr, size)
    write_storage(client, addr, recs + [make_python("routed", "print(1)\n", True)], capacity=size)
    assert client._current_alt == C.ALT_SRAM  # switched to the SRAM backend for the write
    names = [r.fullname for r in python_scripts(read_storage(client, addr, size))]
    assert "routed.py" in names  # the write actually landed (read-back verified inside)


def test_write_switches_back_to_flash_alt_for_a_flash_address():
    dev, client = _client()
    addr, size = read_identity(client, dev.bcdDevice).storage_ram
    write_storage(client, addr, read_storage(client, addr, size), capacity=size)
    assert client._current_alt == C.ALT_SRAM
    client.write(dev.model.memory.external_flash_origin, b"\xaa" * 64, erase=True)
    assert client._current_alt == C.ALT_FLASH  # routed back to Flash by address


def test_dnload_to_sram_on_flash_alt_is_silently_ignored():
    # Models the real-hardware behaviour that motivated routing: a DNLOAD outside the current
    # alt's region is accepted (status OK) but does nothing. Bypass routing to observe it.
    dev, client = _client()
    addr, _ = read_identity(client, dev.bcdDevice).storage_ram
    before = client.read(addr, 32)
    dev.set_interface_altsetting(interface=0, alternate_setting=C.ALT_FLASH)
    client._current_alt = C.ALT_FLASH  # pretend we forgot to route
    client.set_address(addr)
    client._out(C.DFU_DNLOAD, C.DNLOAD_BLOCK_BASE, b"\x5a" * 32)
    client._wait_idle_after_command("noop-write")
    assert client.read(addr, 32) == before  # unchanged — the wrong-backend write was ignored


def test_no_alt_map_keeps_current_alt():
    # A device advertising no alt map (older model / test double) → routing is a no-op and writes
    # use the current alt. The default virtual device has no alt_regions.
    dev = virtual_calculator("n0110")
    client = DfuClient(dev, sleep=lambda *_: None)
    assert client._alt_map() is None
    addr, size = read_identity(client, dev.bcdDevice).storage_ram
    write_storage(client, addr, read_storage(client, addr, size), capacity=size)
    assert client._current_alt == C.ALT_FLASH  # never switched


def test_select_alt_without_setter_is_a_noop():
    # A device that cannot switch alt-settings (no set_interface_altsetting): select_alt records
    # the intent without erroring, so routing degrades gracefully.
    class _NoSetter:
        idVendor = C.USB_VID
        idProduct = C.PID_EPSILON
        bcdDevice = 0x0110

    client = DfuClient(_NoSetter(), sleep=lambda *_: None)
    client.select_alt(C.ALT_SRAM)
    assert client._current_alt == C.ALT_SRAM


def test_alt_for_address_outside_all_regions_is_none():
    dev, client = _client()
    assert client._alt_for(0x00000000) is None  # owned by neither Flash nor SRAM


def test_make_idle_recovers_from_busy_and_error_states():
    # The DFU FSM helper must return to dfuIDLE from any state: ABORT out of DNLOAD_IDLE, and
    # CLEAR_STATUS out of dfuERROR. Locks down the recovery logic for future refactoring.
    dev = virtual_calculator("n0110")
    cli = DfuClient(dev, sleep=lambda *_: None)
    cli.write(dev.model.memory.sram_origin, b"\x00" * 16)  # leaves the device in DNLOAD_IDLE
    assert dev.state == C.STATE_DNLOAD_IDLE
    cli.make_idle()
    assert dev.state == C.STATE_DFU_IDLE
    with pytest.raises(Exception):
        cli.write(0x00000000, b"\x01" * 16)  # out-of-range → errTARGET → dfuERROR
    assert dev.state == C.STATE_ERROR
    cli.make_idle()
    assert dev.state == C.STATE_DFU_IDLE


def test_write_storage_raises_on_readback_mismatch():
    # A silent no-op must fail loudly, not pretend success.
    class Dud:
        def write(self, addr, data, *, erase=False):
            pass  # accept but drop

        def read(self, addr, n):
            return b"\x00" * n

    with pytest.raises(StorageWriteError):
        write_storage(Dud(), 0x24001000, [make_python("x", "y\n", True)], capacity=0x1000)
