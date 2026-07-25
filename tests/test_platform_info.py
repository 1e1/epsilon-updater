"""N0200 FirmwareHeader platform-info struct (magic 0xFACECAFE) — parse/pack.

Offline, synthetic values only (never the real captured serial/version). Reflects the layout
reverse-engineered in docs/01-specs/n02xx-firmware-format.md.
"""

from nwupdater.formats.platform_info import (
    MAGIC_PLATFORM_INFO,
    N0200_FIRMWARE_HEADER_ADDR,
    PLATFORM_INFO_SIZE,
    pack,
    parse,
)


def test_pack_parse_roundtrip():
    raw = pack("3.0.0", "8059a46", field1=0x11223344, field2=0x55667788)
    assert len(raw) == PLATFORM_INFO_SIZE == 32
    pi = parse(raw)
    assert pi.valid is True
    assert pi.software_version == "3.0.0"
    assert pi.patch_level == "8059a46"
    assert pi.field1 == 0x11223344 and pi.field2 == 0x55667788


def test_bookend_magics_required():
    raw = bytearray(pack("1.0.0", "abcdef0"))
    # break the footer magic → invalid
    raw[-1] ^= 0xFF
    assert parse(bytes(raw)).valid is False
    assert parse(bytes(raw)).software_version == "1.0.0"  # fields still readable


def test_short_buffer_is_invalid():
    assert parse(b"\xfe\xca\xce\xfa" + b"\x00" * 8).valid is False


def test_magic_and_addr_constants():
    assert MAGIC_PLATFORM_INFO == 0xFACECAFE
    assert N0200_FIRMWARE_HEADER_ADDR == 0x080040C0
