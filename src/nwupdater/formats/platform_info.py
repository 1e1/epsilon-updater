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

MAGIC_PLATFORM_INFO = 0xFACECAFE
PLATFORM_INFO_SIZE = 32
# DfuSe target the N0200 bootloader declares for this block (@FirmwareHeader/0x080040C0/01*64B).
N0200_FIRMWARE_HEADER_ADDR = 0x080040C0


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


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
        "<III8s8sI", MAGIC_PLATFORM_INFO, field1, field2,
        software_version.encode("ascii", "replace")[:8].ljust(8, b"\x00"),
        patch_level.encode("ascii", "replace")[:8].ljust(8, b"\x00"),
        MAGIC_PLATFORM_INFO)
