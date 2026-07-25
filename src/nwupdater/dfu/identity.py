"""Read calculator identity (model + installed OS version) over DFU, read-only.

Procedure from docs/01-specs/usb-dfu-protocol.md §8.1:
  1. model from bcdDevice
  2. read SlotInfo (16 B) from SRAM base, verify magic
  3. follow userland-header pointer, read version @0x04; kernel header for kernel version

Also reads the serial number (iSerialNumber string descriptor) — the calculator-side
key of "My Devices" pairing; see docs/01-specs/scripts-and-device-pairing.md §2.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..formats.headers import KernelHeader, SlotInfo, UserlandHeader
from ..models import Model, family_for_bcd, model_for_bcd
from . import constants as C
from .protocol import DfuClient


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
    external_apps_ram: tuple[int, int] | None = None  # (start, end) RAM window for external apps
    userland_header_addr: int | None = None  # active slot's UserlandHeader address (from SlotInfo)
    storage_ram: tuple[int, int] | None = None  # (m_storageAddressRAM, m_storageSizeRAM)
    slot_info_valid: bool = False
    serial_number: str | None = None  # iSerialNumber = Base64(MCU UID), 16 chars

    def __str__(self) -> str:
        v = self.os_version or "?"
        return (
            f"{self.model_name} [{self.family}] OS {v}"
            + (f" ({self.commit})" if self.commit else "")
            + (f" SN {self.serial_number}" if self.serial_number else "")
        )


def read_identity(
    client: DfuClient,
    bcd_device: int,
    sram_origin: int | None = None,
    serial_index: int = C.SERIAL_STRING_INDEX,
) -> CalculatorIdentity:
    model = model_for_bcd(bcd_device)
    ident = CalculatorIdentity(
        bcd_device=bcd_device,
        model=model,
        model_name=f"n{bcd_device:04x}",
        family=model.family if model else family_for_bcd(bcd_device),
    )

    # Serial number: a standard string-descriptor read, independent of the DFU state
    # machine, so we do it first and never let its absence break the rest (raw ST
    # bootloader modes may not expose it).
    ident.serial_number = client.get_string_descriptor(serial_index)

    client.make_idle()

    if model and model.opaque_firmware:
        # N02xx: no Epsilon SlotInfo/headers. The firmware version lives in the read-only
        # FirmwareHeader (magic 0xFACECAFE) the bootloader exposes at 0x080040C0.
        _read_firmware_header(client, ident)
        return ident

    base = (
        sram_origin
        if sram_origin is not None
        else (model.memory.sram_origin if model else 0x20000000)
    )
    slot = SlotInfo.unpack(client.read(base, C.SLOT_INFO_SIZE))
    if slot.valid:
        ident.slot_info_valid = True
        ident.userland_header_addr = slot.userland_header_addr or None
        _read_kernel_header(client, slot.kernel_header_addr, ident)
        _read_userland_header(client, slot.userland_header_addr, ident)
    return ident


def _read_kernel_header(client: DfuClient, addr: int, ident: CalculatorIdentity) -> None:
    if not addr:
        return
    kern = KernelHeader.unpack(client.read(addr, C.KERNEL_HEADER_SIZE))
    if not kern.valid:
        return
    ident.kernel_version = kern.software_version
    ident.commit = kern.commit_hash


def _read_userland_header(client: DfuClient, addr: int, ident: CalculatorIdentity) -> None:
    if not addr:
        return
    user = UserlandHeader.unpack(client.read(addr, C.USERLAND_HEADER_SIZE))
    if not user.valid:
        return
    ident.os_version = user.expected_software_version
    st_addr, st_size = user.storage_addr_ram, user.storage_size_ram
    ident.storage_ram = (st_addr, st_size) if st_addr and st_size else None
    ident.external_apps_flash = user.external_apps_flash
    ram_s, ram_e = user.external_apps_ram
    ident.external_apps_ram = (ram_s, ram_e) if ram_e > ram_s else None


def _read_firmware_header(client: DfuClient, ident: CalculatorIdentity) -> None:
    """N02xx: read the read-only FirmwareHeader (magic 0xFACECAFE @ 0x080040C0) for the version.

    The Scientifique firmware payload is encrypted/opaque, but the bootloader exposes a small
    header block carrying the software version + patch level (a git short hash)."""
    from ..formats import platform_info

    try:
        fw = platform_info.read_firmware_header(client)
    except Exception:
        return
    if fw.valid:
        ident.os_version = fw.software_version or None
        ident.commit = fw.patch_level or None
