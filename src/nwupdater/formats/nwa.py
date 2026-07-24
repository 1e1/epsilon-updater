"""NumWorks external-app (`.nwa`) container: the EADK ``AppInfo`` header.

Layout (8x u32, docs/04-third-party-apps/app-store-and-nwa.md):
  0x00 magic start  = 0xDEC0BEBA
  0x04 api_level    (must equal the device EXTERNAL_APPS_API_LEVEL)
  0x08 name address (offset/pointer to the app name string)
  0x0C icon size
  0x10 icon address
  0x14 entry point
  0x18 app size     (total, header included)
  0x1C magic end    = 0xDEC0BEBA

Addresses in a real .nwa are relative to the app load base; our synthesizer uses offsets
from the blob start so a standalone blob is self-describing and round-trips.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..dfu import constants as C

APPINFO_SIZE = 0x20


@dataclass
class AppInfo:
    api_level: int
    name: str
    icon_size: int
    app_size: int
    valid: bool
    name_address: int = 0
    entry_point: int = 0
    icon_address: int = 0

    @classmethod
    def parse(cls, blob: bytes) -> AppInfo:
        if len(blob) < APPINFO_SIZE:
            return cls(0, "", 0, len(blob), valid=False)
        (magic0, api, name_addr, icon_size, icon_addr, entry, app_size, magic1) = struct.unpack(
            "<IIIIIIII", blob[:APPINFO_SIZE]
        )
        valid = magic0 == C.MAGIC_EXTERNAL_APP and magic1 == C.MAGIC_EXTERNAL_APP
        name = ""
        if valid and 0 < name_addr < len(blob):
            name = blob[name_addr:].split(b"\x00", 1)[0].decode("ascii", "replace")
        return cls(api, name, icon_size, app_size or len(blob), valid, name_addr, entry, icon_addr)


def build_nwa(name: str, *, api_level: int, code: bytes = b"", icon: bytes = b"") -> bytes:
    """Build a minimal, valid standalone .nwa blob (for tests / demo)."""
    name_bytes = name.encode("ascii", "replace") + b"\x00"
    name_addr = APPINFO_SIZE
    icon_addr = name_addr + len(name_bytes)
    code_addr = icon_addr + len(icon)
    body = name_bytes + icon + code
    app_size = APPINFO_SIZE + len(body)
    header = struct.pack(
        "<IIIIIIII",
        C.MAGIC_EXTERNAL_APP,
        api_level,
        name_addr,
        len(icon),
        icon_addr if icon else 0,
        code_addr,
        app_size,
        C.MAGIC_EXTERNAL_APP,
    )
    return header + body


@dataclass
class InstalledApp:
    offset: int  # byte offset within the external-apps region
    info: AppInfo


def iter_apps(blob: bytes, *, sector_size: int = C.EXTERNAL_APP_SECTOR) -> list[InstalledApp]:
    """Enumerate apps in an external-apps region blob.

    Apps are laid out from the start, each **sector-aligned** (64 KiB), and the run ends at
    the first sector without the AppInfo magic — exactly the OS iterator
    (external_apps.cpp ``nextSectorAlignedAddress`` / ``appAtAddress``).
    """
    out: list[InstalledApp] = []
    off = 0
    while off + APPINFO_SIZE <= len(blob):
        info = AppInfo.parse(blob[off:])
        if not info.valid:
            break
        out.append(InstalledApp(off, info))
        step = info.app_size or APPINFO_SIZE
        nxt = ((off + step + sector_size - 1) // sector_size) * sector_size
        if nxt <= off:
            break
        off = nxt
    return out
