"""NumWorks hardware model registry.

Two product families, keyed by bcdDevice (model = "n%04x" % bcdDevice):
  - N01xx  -> Graphique  (N0100, N0110, N0115, N0120)
  - N02xx  -> Scientifique (N0200, first of the series)

See docs/01-specs/hardware-variants.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryMap:
    internal_flash_origin: int
    internal_flash_size: int
    external_flash_origin: int | None  # None if no QSPI (N0100 / N02xx)
    external_flash_size: int
    sram_origin: int
    sram_size: int
    has_ab_slots: bool
    slot_size: int = 0  # per-slot size when has_ab_slots


@dataclass(frozen=True)
class Model:
    bcd_device: int
    name: str  # "n0110"
    family: str  # "graphique" | "scientifique"
    mcu: str
    memory: MemoryMap
    confirmed: bool = True  # False when memory map is inferred (N0100/N0200)
    # N02xx (Scientifique) ships an ENCRYPTED, opaque firmware blob: no plaintext
    # SlotInfo/Kernel/Userland headers, no readable version — see docs/01-specs/n02xx-firmware-format.md.
    opaque_firmware: bool = False
    # Per-page DfuSe ERASE before writing. The official N0200 flasher issues NO erase (verified
    # in a real update capture — the bootloader accepts DNLOAD writes directly); graphique models
    # keep erase. See docs/01-specs/n02xx-firmware-format.md.
    flash_erase: bool = True

    @property
    def marketing_family(self) -> str:
        return "Graphique" if self.family == "graphique" else "Scientifique"


def family_for_bcd(bcd: int) -> str:
    if 0x0100 <= bcd < 0x0200:
        return "graphique"
    if 0x0200 <= bcd < 0x0300:
        return "scientifique"
    return "unknown"


# Common maps -------------------------------------------------------------------
_MAP_N0110 = MemoryMap(
    internal_flash_origin=0x08000000,
    internal_flash_size=0x10000,  # 64 KiB (4x16K)
    external_flash_origin=0x90000000,
    external_flash_size=0x800000,  # 8 MiB
    sram_origin=0x20000000,
    sram_size=0x40000,  # 256 KiB
    has_ab_slots=True,
    slot_size=0x400000,  # 4 MiB per slot
)
_MAP_N0120 = MemoryMap(
    internal_flash_origin=0x08000000,
    internal_flash_size=0x80000,  # 512 KiB (4x128K)
    external_flash_origin=0x90000000,
    external_flash_size=0x800000,
    sram_origin=0x24000000,
    sram_size=0x50000,  # AXI SRAM (~320 KiB)
    has_ab_slots=True,
    slot_size=0x400000,
)
_MAP_N0100 = MemoryMap(  # inferred: internal flash only, no slots
    internal_flash_origin=0x08000000,
    internal_flash_size=0x100000,  # ~1 MiB
    external_flash_origin=None,
    external_flash_size=0,
    sram_origin=0x20000000,
    sram_size=0x40000,
    has_ab_slots=False,
)
_MAP_N0200 = MemoryMap(  # STM32U073 (M0+), no slots. DFU firmware base OBSERVED on the real
    # N0200 3.0.0 .dfu = 0x98000000 (NumWorks DFU address space, distinct from the CPU flash at
    # 0x08000000); single opaque/encrypted element of ~232 KiB. See docs/01-specs/n02xx-firmware-format.md.
    internal_flash_origin=0x98000000,
    internal_flash_size=0x40000,  # ~256 KiB region
    external_flash_origin=None,
    external_flash_size=0,
    sram_origin=0x20000000,
    sram_size=0xA000,  # ~40 KiB (M0+), still inferred
    has_ab_slots=False,
)

MODELS: dict[int, Model] = {
    0x0100: Model(0x0100, "n0100", "graphique", "STM32F412", _MAP_N0100, confirmed=False),
    0x0110: Model(0x0110, "n0110", "graphique", "STM32F730", _MAP_N0110),
    0x0115: Model(0x0115, "n0115", "graphique", "STM32F730(var)", _MAP_N0110),
    0x0120: Model(0x0120, "n0120", "graphique", "STM32H725", _MAP_N0120),
    0x0200: Model(
        0x0200,
        "n0200",
        "scientifique",
        "STM32U073KC",
        _MAP_N0200,
        confirmed=False,
        opaque_firmware=True,
        flash_erase=False,
    ),
}


def model_for_bcd(bcd: int) -> Model | None:
    """Exact model, or None if the bcdDevice is unknown."""
    return MODELS.get(bcd)


def describe_bcd(bcd: int) -> str:
    m = MODELS.get(bcd)
    if m:
        flag = "" if m.confirmed else " (inferred memory map)"
        return f"{m.name} — {m.marketing_family} — {m.mcu}{flag}"
    return f"n{bcd:04x} — family {family_for_bcd(bcd)} — unknown to the registry"
