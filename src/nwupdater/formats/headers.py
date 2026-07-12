"""Pack/unpack the NumWorks flash header structures (the "platforminfo").

Single source of truth shared by the virtual device (which preloads them) and the firmware
image synthesizer / identity reader. Byte layouts are documented in
docs/01-specs/usb-dfu-protocol.md §7.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..dfu import constants as C


def _fixed(s: str, n: int) -> bytes:
    return s.encode("ascii", "replace")[:n].ljust(n, b"\x00")


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


# -- SlotInfo (16 B, at SRAM base) --------------------------------------------------
def pack_slot_info(kernel_header_addr: int, userland_header_addr: int) -> bytes:
    return struct.pack("<IIII", C.MAGIC_SLOT_INFO, kernel_header_addr,
                       userland_header_addr, C.MAGIC_SLOT_INFO)


@dataclass
class SlotInfo:
    kernel_header_addr: int
    userland_header_addr: int
    valid: bool

    @classmethod
    def unpack(cls, raw: bytes) -> "SlotInfo":
        header, kern, user, footer = struct.unpack("<IIII", raw[:16])
        return cls(kern, user, header == C.MAGIC_SLOT_INFO and footer == C.MAGIC_SLOT_INFO)


# -- KernelHeader (24 B) ------------------------------------------------------------
def pack_kernel_header(software_version: str, commit_hash: str) -> bytes:
    return struct.pack("<I8s8sI", C.MAGIC_KERNEL_HEADER,
                       _fixed(software_version, C.SOFTWARE_VERSION_SIZE),
                       _fixed(commit_hash, C.COMMIT_HASH_SIZE),
                       C.MAGIC_KERNEL_HEADER)


@dataclass
class KernelHeader:
    software_version: str
    commit_hash: str
    valid: bool

    @classmethod
    def unpack(cls, raw: bytes) -> "KernelHeader":
        magic, ver, commit, footer = struct.unpack("<I8s8sI", raw[:24])
        return cls(_cstr(ver), _cstr(commit),
                   magic == C.MAGIC_KERNEL_HEADER and footer == C.MAGIC_KERNEL_HEADER)


# -- UserlandHeader (48 B) ----------------------------------------------------------
def pack_userland_header(
    expected_software_version: str,
    *,
    storage_addr_ram: int,
    storage_size_ram: int,
    external_apps_flash: tuple[int, int],
    external_apps_ram: tuple[int, int] = (0, 0),
    device_name_flash: tuple[int, int] = (0, 0),
) -> bytes:
    return struct.pack(
        "<I8sIIIIIIIII", C.MAGIC_USERLAND_HEADER,
        _fixed(expected_software_version, C.SOFTWARE_VERSION_SIZE),
        storage_addr_ram, storage_size_ram,
        external_apps_flash[0], external_apps_flash[1],
        external_apps_ram[0], external_apps_ram[1],
        device_name_flash[0], device_name_flash[1],
        C.MAGIC_USERLAND_HEADER)


@dataclass
class UserlandHeader:
    expected_software_version: str
    storage_addr_ram: int
    storage_size_ram: int
    external_apps_flash: tuple[int, int]
    valid: bool

    @classmethod
    def unpack(cls, raw: bytes) -> "UserlandHeader":
        fields = struct.unpack("<I8sIIIIIIIII", raw[:C.USERLAND_HEADER_SIZE])
        magic, ver, st_addr, st_size, apps_s, apps_e = fields[0:6]
        footer = fields[10]
        return cls(_cstr(ver), st_addr, st_size, (apps_s, apps_e),
                   magic == C.MAGIC_USERLAND_HEADER and footer == C.MAGIC_USERLAND_HEADER)
