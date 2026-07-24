"""NumWorks "FirmwareHeader" platform-info struct (magic 0xFACECAFE).

Reverse-engineered from a real N0200 capture (docs/01-specs/n02xx-firmware-format.md). The
bootloader exposes it as a DfuSe target string ``@FirmwareHeader/0x080040C0/01*64B`` and it is
read over DFU as a 32-byte block at ``0x080040C0``. It carries the software version + patch
level (a git short hash) — this is where the workshop reads the calc's firmware version for the
``POST /devices/{serial}`` heartbeat. The calculator SERIAL is NOT here — it comes from the USB
``iSerialNumber`` string descriptor (``usb.core.Device.serial_number``).

Layout (32 B, little-endian), bookended by the magic:
    0x00  u32   magic 0xFACECAFE
    0x04  u32   field1 (meaning unknown)
    0x08  u32   field2 (meaning unknown)
    0x0c  8s    software_version   (NUL-padded ASCII, e.g. "3.0.0")
    0x14  8s    software_patch_level (NUL-padded ASCII, e.g. "8059a46")
    0x1c  u32   magic 0xFACECAFE
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..dfu.constants import (
    MAGIC_PLATFORM_INFO,
    N0200_FIRMWARE_HEADER_ADDR,
    PLATFORM_INFO_SIZE,
)
from ._bytes import cstr as _cstr
from ._bytes import fixed as _fixed

# Re-exported for backward compatibility (tests + device.py import these from here).
__all__ = [
    "MAGIC_PLATFORM_INFO",
    "N0200_FIRMWARE_HEADER_ADDR",
    "PLATFORM_INFO_SIZE",
    "PlatformInfo",
    "pack",
    "parse",
]


@dataclass
class PlatformInfo:
    valid: bool
    software_version: str
    patch_level: str
    field1: int
    field2: int

    def __str__(self) -> str:
        v = f"{self.software_version} ({self.patch_level})" if self.software_version else "?"
        return f"PlatformInfo v{v}" + ("" if self.valid else " [magic invalide]")


def parse(raw: bytes) -> PlatformInfo:
    """Parse the 32-byte FirmwareHeader block. ``valid`` is True only if both magics match."""
    if len(raw) < PLATFORM_INFO_SIZE:
        return PlatformInfo(False, "", "", 0, 0)
    head, field1, field2 = struct.unpack("<III", raw[0:12])
    version = _cstr(raw[12:20])
    patch = _cstr(raw[20:28])
    (foot,) = struct.unpack("<I", raw[28:32])
    valid = head == MAGIC_PLATFORM_INFO and foot == MAGIC_PLATFORM_INFO
    return PlatformInfo(valid, version, patch, field1, field2)


def pack(software_version: str, patch_level: str, *, field1: int = 0, field2: int = 0) -> bytes:
    """Build a structurally valid block (for tests / virtual device)."""
    return struct.pack(
        "<III8s8sI",
        MAGIC_PLATFORM_INFO,
        field1,
        field2,
        _fixed(software_version, 8),
        _fixed(patch_level, 8),
        MAGIC_PLATFORM_INFO,
    )
