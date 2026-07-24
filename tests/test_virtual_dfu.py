"""End-to-end tests of the DFU host client against the Level-1 virtual device.

No real USB is involved. These validate the protocol logic of Lots 1/3/4.
"""


import struct

import pytest

from nwupdater.dfu import constants as C
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient, DfuError
from nwupdater.testing.virtual_dfu import virtual_calculator


def _client(dev):
    # sleep=lambda *_: None -> no real waiting on poll timeouts
    return DfuClient(dev, sleep=lambda *_: None)


class _EraseRecorder:
    """Wraps a virtual device to record the addresses of DfuSe ERASE commands."""

    def __init__(self, inner):
        self._inner = inner
        self.erases: list[int] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0,
                      data_or_wLength=None, timeout=None):
        if (bmRequestType == C.REQ_OUT and bRequest == C.DFU_DNLOAD and wValue == 0
                and data_or_wLength):
            data = bytes(data_or_wLength)
            if data and data[0] == C.DFUSE_ERASE and len(data) >= 5:
                self.erases.append(struct.unpack("<I", data[1:5])[0])
        return self._inner.ctrl_transfer(bmRequestType, bRequest, wValue, wIndex,
                                         data_or_wLength, timeout)


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


def test_read_identity_reads_serial_number():
    """My Devices pairing key: iSerialNumber = Base64(MCU UID) -> 16 ASCII chars."""
    dev = virtual_calculator("n0110")
    ident = read_identity(_client(dev), dev.bcdDevice)
    assert ident.serial_number == dev.serial_number
    assert len(ident.serial_number) == 16  # Base64 of 12 bytes, no padding
    assert "SN " + ident.serial_number in str(ident)


def test_serial_number_is_overridable_and_deterministic():
    assert virtual_calculator("n0110").serial_number == virtual_calculator("n0110").serial_number
    # distinct models get distinct synthetic serials
    assert virtual_calculator("n0110").serial_number != virtual_calculator("n0120").serial_number
    dev = virtual_calculator("n0110", serial="CUSTOMSERIAL0001")
    assert read_identity(_client(dev), dev.bcdDevice).serial_number == "CUSTOMSERIAL0001"


def test_get_string_descriptor_paths():
    client = _client(virtual_calculator("n0110"))
    assert client.get_string_descriptor(C.SERIAL_STRING_INDEX)  # serial
    assert client.get_string_descriptor(1) == "NumWorks"  # manufacturer
    assert client.get_string_descriptor(0) is None  # index 0 is the langid table, not a string
    assert client.get_string_descriptor(99) is None  # unknown index -> device stalls -> None


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


def test_device_advertises_flash_layout_with_large_sectors():
    dev = virtual_calculator("n0110")
    assert dev.memory_layout is not None
    # external flash is modelled with 64 KiB sectors, far larger than a 2048-byte chunk
    assert dev.memory_layout.sector_of(0x90300000) == (0x90300000, 0x10000)


def test_erase_write_survives_across_a_full_sector():
    # Regression for the per-chunk erase bug: a payload larger than one transfer chunk but
    # inside a single 64 KiB sector must round-trip. A per-2048-byte erase would re-wipe the
    # sector on every chunk, leaving only the final chunk intact.
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    addr = 0x90300000  # 64 KiB-aligned, inside writable external flash
    payload = bytes((i * 37) & 0xFF for i in range(6000))  # ~3 chunks, one sector
    cli.write(addr, payload, erase=True)
    assert cli.read(addr, len(payload)) == payload


def test_erase_issues_one_command_per_sector():
    dev = _EraseRecorder(virtual_calculator("n0110"))
    cli = _client(dev)
    addr = 0x90300000
    payload = b"\x5a" * 6000  # ~3 chunks, all within the one 64 KiB sector
    cli.write(addr, payload, erase=True)
    assert dev.erases == [0x90300000]  # exactly one erase, at the sector base — not per chunk


def test_erase_spanning_two_sectors_erases_each_once():
    dev = _EraseRecorder(virtual_calculator("n0110"))
    cli = _client(dev)
    addr = 0x9030F000  # near the end of the sector at 0x90300000
    payload = b"\xa5" * (0x2000)  # crosses into 0x90310000
    cli.write(addr, payload, erase=True)
    assert dev.erases == [0x90300000, 0x90310000]
    assert cli.read(addr, len(payload)) == payload


def test_leave_sets_jump_address_past_userland_header():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    userland_hdr = 0x90010000
    cli.leave(userland_hdr)
    assert dev.left is True
    assert dev.jump_address == userland_hdr + C.USERLAND_HEADER_SIZE


def test_truncated_dfuse_command_stalls():
    # A malformed SET_ADDRESS / sector-ERASE (missing the 4-byte address) must STALL EP0
    # (UsbStall) exactly like real hardware, not raise a bare struct.error.
    from nwupdater.testing.virtual_dfu import UsbStall
    dev = virtual_calculator("n0110")
    with pytest.raises(UsbStall):
        dev.ctrl_transfer(C.REQ_OUT, C.DFU_DNLOAD, 0, 0, bytes([C.DFUSE_SET_ADDRESS, 0x00]))
    with pytest.raises(UsbStall):
        dev.ctrl_transfer(C.REQ_OUT, C.DFU_DNLOAD, 0, 0, bytes([C.DFUSE_ERASE, 0x00, 0x00]))
    # a bare ERASE (length 1) is still the valid mass-erase, not a stall
    dev.ctrl_transfer(C.REQ_OUT, C.DFU_DNLOAD, 0, 0, bytes([C.DFUSE_ERASE]))


def test_getstatus_reply_shape():
    dev = virtual_calculator("n0110")
    cli = _client(dev)
    st = cli.get_status()
    assert st.status == C.STATUS_OK
    assert st.state == C.STATE_DFU_IDLE
