"""Firmware install engine (Lot 3).

Builds on the DFU host client (Lot 1). For A/B devices it flashes the *inactive* slot then
boots it — an atomic update that can never leave the calculator unbootable. Every write is
read-back verified by default.

No real USB: drive it with the virtual device.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable

from ..dfu import constants as C
from ..dfu.protocol import DfuClient
from ..formats import headers
from ..models import Model
from .image import FirmwareImage, FirmwareSegment

Progress = Callable[[str, int, int], None]  # (phase, done_bytes, total_bytes)

# Slot-internal offsets, confirmed empirically on the real N0110 25.2.0 firmware:
# each 4 MiB slot holds KernelHeader at +0x8 and UserlandHeader at +0x10000.
SLOT_USERLAND_OFFSET = 0x10000
_UL_MAGIC = struct.pack("<I", C.MAGIC_USERLAND_HEADER)


class CompatibilityError(RuntimeError):
    pass


class VerificationError(RuntimeError):
    pass


@dataclass
class InstallPlan:
    segments: list[FirmwareSegment]
    target_slot: str | None  # "A"/"B" (single-slot remap), "A+B" (full image), or None
    boot_address: int | None  # userland-header address to jump to, or None
    total_bytes: int
    full_image: bool = False  # True when a complete multi-slot official image is flashed verbatim


def _slot_origin(model: Model, slot: str) -> int:
    base = model.memory.external_flash_origin
    if base is None:  # only reachable on a misconfigured A/B model; fail loudly (not under -O)
        raise ValueError(f"{model.name} has no external flash but A/B slots were requested")
    return base if slot == "A" else base + model.memory.slot_size


def _userland_at(data: bytes, off: int) -> bool:
    return (0 <= off and off + C.USERLAND_HEADER_SIZE <= len(data)
            and data[off:off + 4] == _UL_MAGIC
            and data[off + 44:off + 48] == _UL_MAGIC)


def _find_userland(segments: list[FirmwareSegment], *, prefer_addr: int | None = None) -> int | None:
    """Locate a valid UserlandHeader to boot into. Tries a preferred absolute address, then the
    conventional +0x10000 slot offset, then a full scan — robust to real vs synthetic layouts."""
    if prefer_addr is not None:
        for s in segments:
            if s.address <= prefer_addr < s.address + len(s.data) and _userland_at(s.data, prefer_addr - s.address):
                return prefer_addr
    for s in segments:  # fast path: header at the conventional slot offset
        if _userland_at(s.data, SLOT_USERLAND_OFFSET):
            return s.address + SLOT_USERLAND_OFFSET
    for s in segments:  # last resort: scan (4-byte aligned)
        d = s.data
        for off in range(0, len(d) - C.USERLAND_HEADER_SIZE + 1, 4):
            if _userland_at(d, off):
                return s.address + off
    return None


def plan_install(model: Model, image: FirmwareImage, *, active_slot: str = "A") -> InstallPlan:
    """Compute where to flash.

    - Real official ``.dfu`` files carry a COMPLETE image: both slots A and B pre-populated
      (plus persistent regions). Those are written **verbatim**, like NumWorks' own updater.
    - A single-slot-authored image (the synthetic/demo one, at slot A only) is remapped to the
      *inactive* slot for an atomic A/B update.
    """
    mem = model.memory
    if not mem.has_ab_slots:
        # Single-slot (N0100 / N02xx): flash addresses as-is; boot into the userland header only
        # if the image actually contains one. A synthetic/plaintext image does; the real N02xx
        # firmware is ENCRYPTED/opaque, so none is found → boot=None (the bootloader boots on
        # detach). We never guess an offset for an opaque blob.
        boot = _find_userland(image.segments)
        return InstallPlan(list(image.segments), None, boot, image.total_size)

    # has_ab_slots implies an external QSPI flash origin (see the models.py memory maps).
    assert mem.external_flash_origin is not None
    slot_a = mem.external_flash_origin
    slot_b = slot_a + mem.slot_size
    has_a = any(slot_a <= s.address < slot_b for s in image.segments)
    has_b = any(slot_b <= s.address < slot_b + mem.slot_size for s in image.segments)

    if has_a and has_b:
        # Complete multi-slot image → write verbatim; boot the requested slot's userland header.
        prefer = _slot_origin(model, active_slot) + SLOT_USERLAND_OFFSET
        boot = _find_userland(image.segments, prefer_addr=prefer)
        return InstallPlan(list(image.segments), "A+B", boot, image.total_size, full_image=True)

    # Single-slot-authored image: remap external segments (at slot A) to the inactive slot.
    inactive = "B" if active_slot == "A" else "A"
    delta = _slot_origin(model, inactive) - slot_a
    remapped: list[FirmwareSegment] = []
    boot = None
    for s in image.segments:
        if slot_a <= s.address < slot_b:
            new_addr = s.address + delta
            remapped.append(FirmwareSegment(new_addr, s.data))
            boot = new_addr + SLOT_USERLAND_OFFSET
        else:
            remapped.append(s)  # internal-flash segment: leave as-is
    return InstallPlan(remapped, inactive, boot, image.total_size)


class Installer:
    def __init__(self, client: DfuClient, model: Model, *, progress: Progress | None = None):
        self.client = client
        self.model = model
        self._progress = progress or (lambda *a: None)

    # -- compatibility -------------------------------------------------------------
    def check_compatibility(self, image: FirmwareImage) -> None:
        # NB: les .dfu officiels NumWorks portent un bcdDevice générique 0x0000 dans le suffixe
        # DfuSe (le modèle est distingué par l'URL de téléchargement, pas par le suffixe). On ne
        # rejette donc que si l'image déclare un modèle précis, non nul, ET différent.
        if image.bcd_device not in (None, 0) and image.bcd_device != self.model.bcd_device:
            raise CompatibilityError(
                f"image targets n{image.bcd_device:04x} != device {self.model.name}")
        for s in image.segments:
            region_ok = (
                self.model.memory.internal_flash_origin <= s.address
                or (self.model.memory.external_flash_origin is not None
                    and s.address >= self.model.memory.external_flash_origin))
            if not region_ok:
                raise CompatibilityError(f"segment 0x{s.address:08x} hors flash")

    # -- flash + verify ------------------------------------------------------------
    def flash(self, plan: InstallPlan, *, verify: bool = True) -> None:
        done = 0
        total = plan.total_bytes
        for seg in plan.segments:
            self.client.write(seg.address, seg.data, erase=self.model.flash_erase)
            done += len(seg.data)
            self._progress("write", done, total)
            if verify:
                back = self.client.read(seg.address, len(seg.data))
                if back != seg.data:
                    raise VerificationError(
                        f"read-back mismatch at 0x{seg.address:08x}")
                self._progress("verify", done, total)

    # -- full install --------------------------------------------------------------
    def install(self, image: FirmwareImage, *, active_slot: str = "A", verify: bool = True,
                boot: bool = False) -> InstallPlan:
        self.check_compatibility(image)
        plan = plan_install(self.model, image, active_slot=active_slot)
        self.flash(plan, verify=verify)
        if boot and plan.boot_address is not None:
            self.client.leave(plan.boot_address)
        return plan

    # -- post-flash sanity: read headers back from where we flashed ----------------
    def read_installed_version(self, plan: InstallPlan) -> str | None:
        if plan.boot_address is None:
            return None
        raw = self.client.read(plan.boot_address, C.USERLAND_HEADER_SIZE)
        uh = headers.UserlandHeader.unpack(raw)
        return uh.expected_software_version if uh.valid else None
