"""End-to-end tests of the DFU host client against the Level-1 virtual device.

No real USB is involved. These validate the protocol logic of Lots 1/3/4.
"""


import pytest

from nwupdater.dfu import constants as C
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient, DfuError
from nwupdater.testing.virtual_dfu import virtual_calculator


def _client(dev):
    # sleep=lambda *_: None -> no real waiting on poll timeouts
    return DfuClient(dev, sleep=lambda *_: None)


def test_read_identity_graphique_n0110():
    dev = virtual_calculator("n0110", os_version="23.2.4", commit="abc1234")
    ident = read_identity(_client(dev), dev.bcdDevice)

    assert ident.model_name == "n0110"
    assert ident.family == "graphique"
    assert ident.slot_info_valid is True
    assert ident.os_version == "23.2.4"
    assert ident.kernel_version == "23.2.4"
    assert ident.commit == "abc1234"
    assert ident.external_apps_flash is not None
    start, end = ident.external_apps_flash
    assert 0x90000000 <= start < end <= 0x90400000


def test_read_identity_scientifique_n0200():
    dev = virtual_calculator("n0200", os_version="1.0.0", commit="deadbee")
    ident = read_identity(_client(dev), dev.bcdDevice)

    assert ident.model_name == "n0200"
    assert ident.family == "scientifique"
    assert ident.os_version == "1.0.0"
    # N02xx has no external QSPI -> no external-apps region
    assert ident.external_apps_flash == (0, 0)


def test_write_read_roundtrip_in_external_flash():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    addr = 0x90200000  # inside slot A external flash, writable
    payload = bytes(range(256)) * 4  # 1 KiB, spans one chunk
    cli.write(addr, payload, erase=True)
    assert cli.read(addr, len(payload)) == payload


def test_write_multichunk_roundtrip():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    addr = 0x90300000
    payload = bytes((i * 7) & 0xFF for i in range(5000))  # >2 chunks
    cli.write(addr, payload)
    assert cli.read(addr, len(payload)) == payload


def test_write_out_of_range_raises_errtarget():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    with pytest.raises(DfuError) as ei:
        cli.write(0x10000000, b"\xff" * 16)  # unmapped address
    assert ei.value.status == C.STATUS_errTARGET


def test_leave_sets_jump_address_past_userland_header():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    userland_hdr = 0x90010000
    cli.leave(userland_hdr)
    assert dev.left is True
    assert dev.jump_address == userland_hdr + C.USERLAND_HEADER_SIZE


def test_getstatus_reply_shape():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    st = cli.get_status()
    assert st.status == C.STATUS_OK
    assert st.state == C.STATE_DFU_IDLE
