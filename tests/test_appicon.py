"""NumWorks .nwa app-icon decoding — LZ4 block codec + RGB565→BMP, pure stdlib, offline.

Format (from Epsilon / nwlink): 55×56 RGB565, LZ4-block compressed.
"""

from nwupdater.formats.appicon import (
    ICON_RAW,
    decode_app_icon,
    demo_icon_lz4,
    lz4_block_compress_stored,
    lz4_block_decompress,
)
from nwupdater.formats.nwa import build_nwa


def test_lz4_literals_roundtrip():
    data = bytes(range(256)) * 25  # 6400 bytes, exercises the >15 literal-length path
    comp = lz4_block_compress_stored(data)
    assert lz4_block_decompress(comp, len(data)) == data


def test_lz4_match_decode():
    # "ABC" literals, then match (offset=3, len=6) -> "ABCABCABC" (exercises the match path)
    assert lz4_block_decompress(b"\x32ABC\x03\x00", 9) == b"ABCABCABC"


def test_demo_icon_decodes_to_full_raster():
    assert lz4_block_decompress(demo_icon_lz4("Tetris"), ICON_RAW).__len__() == ICON_RAW


def test_decode_app_icon_from_nwa():
    blob = build_nwa("Tetris", api_level=0, code=b"\x00" * 4096, icon=demo_icon_lz4("Tetris"))
    uri = decode_app_icon(blob)
    assert uri and uri.startswith("data:image/bmp;base64,")


def test_decode_app_icon_none_when_no_icon():
    assert decode_app_icon(build_nwa("Plain", api_level=0, code=b"\x00" * 100)) is None


def _elf_with_icon(icon: bytes) -> bytes:
    """Minimal ELF32-LE carrying the icon in a `.rodata.eadk_app_icon` section (like a real .nwa)."""
    import struct

    strtab = b"\x00.rodata.eadk_app_icon\x00.shstrtab\x00"
    icon_off = 52
    strtab_off = icon_off + len(icon)
    shoff = strtab_off + len(strtab)
    eident = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\x00" * 8
    hdr = eident + struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, 0, 0, shoff, 0, 52, 0, 0, 40, 3, 2)

    def shent(name, typ, off, size):
        return struct.pack("<IIIIIIIIII", name, typ, 0, 0, off, size, 0, 0, 1, 0)

    sh = b"\x00" * 40 + shent(1, 1, icon_off, len(icon)) + shent(23, 3, strtab_off, len(strtab))
    return hdr + icon + strtab + sh


def test_decode_app_icon_from_elf():
    # Real .nwa are ELF: the icon lives in .rodata.eadk_app_icon, not a flat header.
    uri = decode_app_icon(_elf_with_icon(demo_icon_lz4("RPN")))
    assert uri and uri.startswith("data:image/bmp;base64,")


def test_decode_app_icon_truncated_elf_does_not_crash():
    # A blob that begins with the ELF magic but is only 4-5 bytes must not raise IndexError.
    from nwupdater.formats.appicon import _elf_section

    assert _elf_section(b"\x7fELF", ".rodata.eadk_app_icon") is None  # 4 bytes
    assert _elf_section(b"\x7fELF\x01", ".rodata.eadk_app_icon") is None  # 5 bytes
    assert decode_app_icon(b"\x7fELF\x01") is None
