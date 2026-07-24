"""Decode a NumWorks external-app (`.nwa`) icon to a displayable image — pure stdlib.

The EADK icon (``.nwi``, produced by ``nwlink``) is a **55×56 RGB565** image, **LZ4-block
compressed**, stored in the app at ``icon_address`` for ``icon_size`` bytes (see
formats/nwa.py). The `.nwa` header gives us both. We LZ4-decode to the fixed 55×56×2 raster,
then emit a 24-bit BMP data URI (no third-party image lib, no PIL at runtime).

RGB565 byte order is assumed little-endian (ARM native). If a real icon comes out colour-
swapped, that is the only knob to flip; the shape/decoding is unaffected.
"""

from __future__ import annotations

import base64
import struct

from .nwa import AppInfo

ICON_W, ICON_H = 55, 56
ICON_RAW = ICON_W * ICON_H * 2  # 6160 bytes of RGB565


def lz4_block_decompress(src: bytes, max_out: int) -> bytes:
    """Decode an LZ4 *block* (no frame header; output size known by the caller)."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break  # last sequence is literals-only
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        mlen = (token & 0x0F) + 4  # min-match is 4
        if (token & 0x0F) == 15:
            while True:
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        start = len(out) - offset
        if start < 0:
            raise ValueError("bad LZ4 offset")
        for k in range(mlen):
            out.append(out[start + k])
        if len(out) >= max_out:
            break
    return bytes(out[:max_out])


def lz4_block_compress_stored(data: bytes) -> bytes:
    """Wrap ``data`` as a valid literals-only LZ4 block (no matches). Used to embed a demo
    icon that round-trips through :func:`lz4_block_decompress`."""
    out = bytearray()
    lit = len(data)
    out.append(0xF0 if lit >= 15 else (lit << 4))
    if lit >= 15:
        rem = lit - 15
        while rem >= 255:
            out.append(255)
            rem -= 255
        out.append(rem)
    return bytes(out) + data


def _rgb565_to_bmp(px: bytes, w: int = ICON_W, h: int = ICON_H) -> bytes:
    row = w * 3
    pad = (4 - row % 4) % 4
    body = bytearray()
    for y in range(h - 1, -1, -1):  # BMP is bottom-up
        for x in range(w):
            o = (y * w + x) * 2
            v = px[o] | (px[o + 1] << 8)
            r, g, b = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
            body += bytes(((b * 255) // 31, (g * 255) // 63, (r * 255) // 31))  # BGR
        body += b"\x00" * pad
    header = b"BM" + struct.pack("<IHHI", 54 + len(body), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    return header + info + bytes(body)


def icon_data_uri(px565: bytes) -> str:
    return "data:image/bmp;base64," + base64.b64encode(_rgb565_to_bmp(px565)).decode("ascii")


def _elf_section(blob: bytes, want: str) -> bytes | None:
    """Bytes of an ELF32 section by name (e.g. ``.rodata.eadk_app_icon``), or None. Real
    NumWorks ``.nwa`` files are ELF binaries — the icon is a section, not a flat header."""
    if len(blob) < 6:  # need e_ident[0:4] magic + EI_CLASS (4) + EI_DATA (5)
        return None
    if blob[:4] != b"\x7fELF" or blob[4] != 1:  # ELF32 only (NumWorks is 32-bit ARM)
        return None
    end = "<" if blob[5] == 1 else ">"
    try:
        e_shoff = struct.unpack(end + "I", blob[32:36])[0]
        e_shentsize, e_shnum, e_shstrndx = struct.unpack(end + "HHH", blob[46:52])

        def sh(i):
            o = e_shoff + i * e_shentsize
            return struct.unpack(end + "IIIIIIIIII", blob[o:o + 40])

        stroff = sh(e_shstrndx)[4]
        for i in range(e_shnum):
            h = sh(i)
            j = blob.index(b"\x00", stroff + h[0])
            if blob[stroff + h[0]:j].decode("ascii", "replace") == want:
                return blob[h[4]:h[4] + h[5]]
    except (struct.error, IndexError, ValueError):
        return None
    return None


def decode_app_icon(blob: bytes) -> str | None:
    """Return a BMP data URI for the app's icon, or None if it has none / can't be decoded.

    Handles both real ELF ``.nwa`` (icon in ``.rodata.eadk_app_icon``) and the flat synthetic
    format used by the demo (:func:`nwa.build_nwa`)."""
    comp = _elf_section(blob, ".rodata.eadk_app_icon")
    if comp is None:  # flat synthetic fallback
        info = AppInfo.parse(blob)
        if info.valid and info.icon_size and info.icon_address:
            comp = blob[info.icon_address: info.icon_address + info.icon_size]
    if not comp:
        return None
    try:
        raw = lz4_block_decompress(comp, ICON_RAW)
    except (IndexError, ValueError):
        return None
    return icon_data_uri(raw) if len(raw) == ICON_RAW else None


# -- demo icon generation (so the synthetic demo apps carry a real, decodable icon) -----
_PALETTE = [(0x5a, 0x8f, 0xef), (0xf0, 0xa6, 0x3a), (0x38, 0xb2, 0xac), (0xef, 0x6f, 0x6c),
            (0x9b, 0x7e, 0xde), (0x4b, 0xb7, 0x6a), (0xe0, 0x60, 0x7e)]


def _rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def demo_icon_lz4(seed: str) -> bytes:
    """A recognisable framed-square icon (colour from ``seed``), LZ4-encoded like a real .nwi."""
    r, g, b = _PALETTE[(ord(seed[0]) if seed else 0) % len(_PALETTE)]
    bg, fg = _rgb565(r, g, b), _rgb565(0xff, 0xff, 0xff)
    px = bytearray()
    for y in range(ICON_H):
        for x in range(ICON_W):
            v = fg if (11 <= x < ICON_W - 11 and 11 <= y < ICON_H - 11) else bg
            px += bytes((v & 0xFF, (v >> 8) & 0xFF))
    return lz4_block_compress_stored(bytes(px))
