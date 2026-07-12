"""Read calculator identity (model + installed OS version) over DFU, read-only.

Procedure from docs/01-specs/usb-dfu-protocol.md §8.1:
  1. model from bcdDevice
  2. read SlotInfo (16 B) from SRAM base, verify magic
  3. follow userland-header pointer, read version @0x04; kernel header for kernel version
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..models import Model, family_for_bcd, model_for_bcd
from . import constants as C
from .protocol import DfuClient


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


@dataclass
class CalculatorIdentity:
    bcd_device: int
    model: Model | None
    model_name: str
    family: str
    os_version: str | None = None
    kernel_version: str | None = None
    commit: str | None = None
    external_apps_flash: tuple[int, int] | None = None  # (start, end)
    slot_info_valid: bool = False

    def __str__(self) -> str:
        v = self.os_version or "?"
        return f"{self.model_name} [{self.family}] OS {v}" + (
            f" ({self.commit})" if self.commit else "")


def read_identity(client: DfuClient, bcd_device: int, sram_origin: int | None = None) -> CalculatorIdentity:
    model = model_for_bcd(bcd_device)
    ident = CalculatorIdentity(
        bcd_device=bcd_device,
        model=model,
        model_name=f"n{bcd_device:04x}",
        family=model.family if model else family_for_bcd(bcd_device),
    )

    client.make_idle()

    base = sram_origin if sram_origin is not None else (model.memory.sram_origin if model else 0x20000000)
    slot_info = client.read(base, 16)
    header, kern_ptr, user_ptr, footer = struct.unpack("<IIII", slot_info)
    if header == C.MAGIC_SLOT_INFO and footer == C.MAGIC_SLOT_INFO:
        ident.slot_info_valid = True
        _read_kernel_header(client, kern_ptr, ident)
        _read_userland_header(client, user_ptr, ident)
    return ident


def _read_kernel_header(client: DfuClient, addr: int, ident: CalculatorIdentity) -> None:
    if not addr:
        return
    raw = client.read(addr, 24)
    magic, = struct.unpack("<I", raw[0:4])
    if magic != C.MAGIC_KERNEL_HEADER:
        return
    ident.kernel_version = _cstr(raw[4:12])
    ident.commit = _cstr(raw[12:20])


def _read_userland_header(client: DfuClient, addr: int, ident: CalculatorIdentity) -> None:
    if not addr:
        return
    raw = client.read(addr, C.USERLAND_HEADER_SIZE)
    magic, = struct.unpack("<I", raw[0:4])
    if magic != C.MAGIC_USERLAND_HEADER:
        return
    ident.os_version = _cstr(raw[4:12])
    apps_start, apps_end = struct.unpack("<II", raw[0x14:0x1C])
    ident.external_apps_flash = (apps_start, apps_end)
