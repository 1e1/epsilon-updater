"""Firmware image model: a set of (address, data) segments to flash.

Two real-world sources:
  - Two raw bins (``epsilon.onboarding.internal.bin`` @0x08000000 and ``.external.bin``
    @0x90000000) — how NumWorks ships firmware (docs/02-update-catalog/web-api.md).
  - A DfuSe (.dfu) file — self-describing addresses + a suffix carrying VID/PID/bcdDevice.

``synthetic()` builds a structurally valid image (kernel + userland headers) so the whole
flash+verify+boot flow can be exercised against the virtual device without any real binary.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from ..dfu import constants as C
from ..formats import headers
from ..models import Model


@dataclass(frozen=True)
class FirmwareSegment:
    address: int
    data: bytes

    @property
    def end(self) -> int:
        return self.address + len(self.data)


@dataclass
class FirmwareImage:
    segments: list[FirmwareSegment]
    version: str = "?"
    model_name: str = "?"
    id_product: int | None = None
    bcd_device: int | None = None
    note: str = ""

    @property
    def total_size(self) -> int:
        return sum(len(s.data) for s in self.segments)

    # -- constructors --------------------------------------------------------------
    @classmethod
    def from_raw_bins(cls, model: Model, *, internal: bytes | None = None,
                      external: bytes | None = None, version: str = "?") -> "FirmwareImage":
        segs: list[FirmwareSegment] = []
        if internal:
            segs.append(FirmwareSegment(model.memory.internal_flash_origin, internal))
        if external:
            if model.memory.external_flash_origin is None:
                raise ValueError(f"{model.name} has no external flash")
            segs.append(FirmwareSegment(model.memory.external_flash_origin, external))
        return cls(segs, version=version, model_name=model.name, bcd_device=model.bcd_device)

    @classmethod
    def synthetic(cls, model: Model, *, version: str = "99.9.9", commit: str = "synth00",
                  filler: int = 0x00) -> "FirmwareImage":
        """A minimal, structurally valid OS image targeting the model's primary slot/flash."""
        mem = model.memory
        if mem.external_flash_origin is not None:
            base = mem.external_flash_origin  # slot A origin
            kernel_off, userland_off = 8, 0x10000
            size = userland_off + 0x1000
            apps = (base + userland_off + 0x100000, base + mem.slot_size - 0x10000)
        else:
            base = mem.internal_flash_origin
            kernel_off, userland_off = 8, 0x8000
            size = userland_off + 0x1000
            apps = (0, 0)

        buf = bytearray([filler]) * size
        buf[kernel_off:kernel_off + 24] = headers.pack_kernel_header(version, commit)
        buf[userland_off:userland_off + C.USERLAND_HEADER_SIZE] = headers.pack_userland_header(
            version, storage_addr_ram=mem.sram_origin + 0x1000, storage_size_ram=0x10000,
            external_apps_flash=apps)
        return cls([FirmwareSegment(base, bytes(buf))], version=version,
                   model_name=model.name, bcd_device=model.bcd_device,
                   note="synthetic")

    @classmethod
    def from_dfuse(cls, raw: bytes) -> "FirmwareImage":
        """Parse a DfuSe (.dfu) container. See dfu.py / UM0391."""
        if raw[:5] != b"DfuSe":
            raise ValueError("not a DfuSe file (bad prefix)")
        if len(raw) < 11 + 16:  # 11-byte DfuSe prefix + 16-byte suffix (VID/PID/bcd + CRC)
            raise ValueError("DfuSe file truncated (header/suffix)")
        _, _ver, _total, ntargets = struct.unpack("<5sBIB", raw[:11])
        # suffix (last 16 bytes) starts with 4x u16: bcdDevice, idProduct, idVendor, bcdDFU
        suffix = raw[-16:]
        bcd_device, id_product, id_vendor, _bcd_dfu = struct.unpack("<HHHH", suffix[:8])

        segments: list[FirmwareSegment] = []
        off = 11
        for _ in range(ntargets):
            # Target prefix: "Target" + altSetting(1) + named(4) + name(255) + size(4) + nbElem(4)
            if off + 274 > len(raw):
                raise ValueError("DfuSe file truncated (target prefix)")
            _sig, _alt, _named, _name, _tsize, nelem = struct.unpack(
                "<6sBI255sII", raw[off:off + 274])
            off += 274
            for _ in range(nelem):
                if off + 8 > len(raw):
                    raise ValueError("DfuSe file truncated (element header)")
                addr, esize = struct.unpack("<II", raw[off:off + 8])
                off += 8
                if off + esize > len(raw):
                    raise ValueError("DfuSe file truncated (element data)")
                segments.append(FirmwareSegment(addr, raw[off:off + esize]))
                off += esize
        return cls(segments, id_product=id_product, bcd_device=bcd_device,
                   model_name=f"n{bcd_device:04x}", note="dfuse")

    # -- serialization (build a .dfu we could feed back / archive) -----------------
    def to_dfuse(self, *, id_vendor: int = C.USB_VID, id_product: int = C.PID_EPSILON,
                 bcd_device: int | None = None) -> bytes:
        bcd_device = bcd_device if bcd_device is not None else (self.bcd_device or 0x0000)
        target = bytearray()
        for s in self.segments:
            target += struct.pack("<II", s.address, len(s.data)) + s.data
        name = b"NumWorks".ljust(255, b"\x00")
        target_block = struct.pack("<6sBI255sII", b"Target", 0, 1, name,
                                   len(target), len(self.segments)) + target
        body = struct.pack("<5sBIB", b"DfuSe", 1, 11 + len(target_block) + 16, 1) + target_block
        suffix_wo_crc = body + struct.pack("<HHHH3sB", bcd_device, id_product, id_vendor,
                                           0x011A, b"UFD", 16)
        crc = 0xFFFFFFFF ^ zlib.crc32(suffix_wo_crc)
        return suffix_wo_crc + struct.pack("<I", crc)
