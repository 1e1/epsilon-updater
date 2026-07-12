"""Level-1 virtual NumWorks DFU device (in-process, no real USB).

Implements the pyusb ``usb.core.Device`` subset the host client uses (``ctrl_transfer`` +
``idVendor``/``idProduct``/``bcdDevice``) and faithfully replays the DfuSe state machine and
memory model of the real calculator, including a preloaded platforminfo (SlotInfo ->
KernelHeader / UserlandHeader) so identity reads work end-to-end.

Fidelity level 1 per docs/01-specs/emulators-and-usb-analysis.md: it validates ALL of the
DFU command logic (Lots 3/4) without USB enumeration. Level 2 (a Linux USB gadget in Docker)
comes later for real enumeration + pcap capture.

This module contains NO hardware access and is safe to import anywhere.
"""

from __future__ import annotations

import base64
import struct

from ..dfu import constants as C
from ..formats import headers
from ..formats import storage as _storage
from ..models import MODELS, Model


def _synth_serial(bcd_device: int) -> str:
    """A plausible, deterministic serial: Base64 of a 12-byte pseudo-UID -> 16 chars.

    Matches the real device's scheme (Base64 of the MCU's 12-byte Unique Device ID;
    see docs/01-specs/scripts-and-device-pairing.md §2.2) without any randomness, so
    tests are stable."""
    uid = bytes(((bcd_device * 7 + i * 31) & 0xFF) for i in range(12))
    return base64.b64encode(uid).decode("ascii")  # 12 bytes -> 16 chars, no padding


class UsbStall(Exception):
    """Raised to emulate an EP0 STALL (host sees a USB pipe error)."""


class _SparseMemory:
    """Page-based zero-filled address space with a set of writable ranges."""

    PAGE = C.TRANSFER_SIZE

    def __init__(self, writable_ranges: list[tuple[int, int]]):
        self._pages: dict[int, bytearray] = {}
        self._writable = writable_ranges

    def _page(self, page_index: int) -> bytearray:
        p = self._pages.get(page_index)
        if p is None:
            p = bytearray(self.PAGE)
            self._pages[page_index] = p
        return p

    def is_writable(self, address: int, length: int) -> bool:
        end = address + length
        return any(lo <= address and end <= hi for lo, hi in self._writable)

    def read(self, address: int, length: int) -> bytes:
        out = bytearray()
        addr = address
        while len(out) < length:
            page_index, off = divmod(addr, self.PAGE)
            take = min(self.PAGE - off, length - len(out))
            out += self._page(page_index)[off:off + take]
            addr += take
        return bytes(out)

    def write(self, address: int, data: bytes) -> None:
        addr = address
        pos = 0
        while pos < len(data):
            page_index, off = divmod(addr, self.PAGE)
            take = min(self.PAGE - off, len(data) - pos)
            self._page(page_index)[off:off + take] = data[pos:pos + take]
            addr += take
            pos += take

    def erase_page(self, address: int) -> None:
        page_index = address // self.PAGE
        self._pages.pop(page_index, None)


class VirtualDfuDevice:
    """A software NumWorks calculator speaking DFU/DfuSe over a mocked control endpoint."""

    def __init__(self, model: Model, *, os_version: str, commit: str,
                 product_string: str = "NumWorks Calculator", serial: str | None = None):
        self.idVendor = C.USB_VID
        self.idProduct = C.PID_EPSILON
        self.bcdDevice = model.bcd_device
        self.model = model
        self.product_string = product_string
        self.serial_number = serial if serial is not None else _synth_serial(model.bcd_device)
        self.iSerialNumber = C.SERIAL_STRING_INDEX  # so usb.util.get_string-style code works
        # USB string descriptor table (index -> value); see calculator.h. Only #3 is
        # asserted from source; #1/#2 are faithful conveniences for the mock.
        self._strings = {1: "NumWorks", 2: product_string, C.SERIAL_STRING_INDEX: self.serial_number}

        self.state = C.STATE_DFU_IDLE
        self.status = C.STATUS_OK
        self.address_pointer = 0
        self._pending = None  # deferred action performed on next GETSTATUS
        self.left = False  # set True after leave/manifest -> reset
        self.jump_address = None

        mem = model.memory
        writable: list[tuple[int, int]] = [
            (mem.internal_flash_origin, mem.internal_flash_origin + mem.internal_flash_size),
            (mem.sram_origin, mem.sram_origin + mem.sram_size),
        ]
        if mem.external_flash_origin is not None:
            writable.append((mem.external_flash_origin, mem.external_flash_origin + mem.external_flash_size))
        self.memory = _SparseMemory(writable)
        self._install_platform_info(os_version, commit)

    # -- platforminfo preload ------------------------------------------------------
    def _install_platform_info(self, os_version: str, commit: str) -> None:
        mem = self.model.memory
        if mem.external_flash_origin is not None:
            slot_origin = mem.external_flash_origin
            kernel_hdr_addr = slot_origin + 8
            userland_hdr_addr = slot_origin + 0x10000  # no extra data (docs §6.2)
            apps_start = userland_hdr_addr + 0x100000
            apps_end = slot_origin + mem.slot_size - 0x10000
        else:  # N0100 / N02xx: everything in internal flash, no slots
            slot_origin = mem.internal_flash_origin
            kernel_hdr_addr = slot_origin + 8
            userland_hdr_addr = slot_origin + 0x8000
            apps_start = apps_end = 0  # no external-apps region

        self.memory.write(mem.sram_origin, headers.pack_slot_info(kernel_hdr_addr, userland_hdr_addr))
        self.memory.write(kernel_hdr_addr, headers.pack_kernel_header(os_version, commit))
        graphing = self.model.family == "graphique"  # scientific N02xx has no Python -> no storage
        self.memory.write(userland_hdr_addr, headers.pack_userland_header(
            os_version,
            storage_addr_ram=(mem.sram_origin + 0x1000) if graphing else 0,
            storage_size_ram=0x10000 if graphing else 0,
            external_apps_flash=(apps_start, apps_end),
            external_apps_ram=(mem.sram_origin + 0x2000, mem.sram_origin + 0x3000),
            device_name_flash=(slot_origin + 0x100, slot_origin + 0x500)))
        # Graphing models embed a Python scripts store; preload a small sample so reads/CLI
        # demo have content (scientific N02xx has no Python -> left zeroed).
        if self.model.family == "graphique":
            self.memory.write(mem.sram_origin + 0x1000, _storage.encode_storage([
                _storage.make_python("mandelbrot", "from math import *\n", True),
                _storage.make_python("suites", "def u(n):\n  return 2 * n\n", False)]))

    # -- pyusb-compatible control endpoint ----------------------------------------
    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0,
                      data_or_wLength=None, timeout=None):
        if bmRequestType == C.REQ_IN:
            length = data_or_wLength if isinstance(data_or_wLength, int) else 0
            return self._handle_in(bRequest, wValue, length)
        elif bmRequestType == C.REQ_STD_DEVICE_IN:
            length = data_or_wLength if isinstance(data_or_wLength, int) else 0
            return self._handle_standard_in(bRequest, wValue, length)
        elif bmRequestType == C.REQ_OUT:
            data = bytes(data_or_wLength) if data_or_wLength else b""
            self._handle_out(bRequest, wValue, data)
            return len(data)
        raise UsbStall(f"unsupported bmRequestType 0x{bmRequestType:02x}")

    # -- standard requests (GET_DESCRIPTOR string) --------------------------------
    def _handle_standard_in(self, request, wValue, length):
        if request != C.STD_GET_DESCRIPTOR:
            raise UsbStall(f"unsupported standard IN request {request}")
        desc_type, index = wValue >> 8, wValue & 0xFF
        if desc_type != C.DESC_TYPE_STRING:
            raise UsbStall(f"unsupported descriptor type 0x{desc_type:02x}")
        if index == 0:  # LANGID table (English/US)
            desc = bytes([4, C.DESC_TYPE_STRING,
                          C.USB_LANGID_EN_US & 0xFF, C.USB_LANGID_EN_US >> 8])
        else:
            value = self._strings.get(index)
            if value is None:
                raise UsbStall(f"unknown string index {index}")
            body = value.encode("utf-16-le")
            desc = bytes([len(body) + 2, C.DESC_TYPE_STRING]) + body
        return desc[:length] if length else desc

    # -- OUT (host -> device) ------------------------------------------------------
    def _handle_out(self, request, wValue, data):
        if request == C.DFU_DNLOAD:
            self._dnload(wValue, data)
        elif request == C.DFU_CLRSTATUS:
            self.status = C.STATUS_OK
            self.state = C.STATE_DFU_IDLE
        elif request == C.DFU_ABORT:
            self.status = C.STATUS_OK
            self.state = C.STATE_DFU_IDLE
        elif request == C.DFU_DETACH:
            self.left = True
            self.state = C.STATE_APP_DETACH
        else:
            raise UsbStall(f"unsupported OUT request {request}")

    def _dnload(self, wValue, data):
        if wValue == 0:  # DfuSe command
            if not data:
                raise UsbStall("empty DfuSe command")
            cmd = data[0]
            if cmd == C.DFUSE_SET_ADDRESS:
                addr, = struct.unpack("<I", data[1:5])
                self._pending = ("setaddr", addr)
            elif cmd == C.DFUSE_ERASE:
                if len(data) == 1:
                    self._pending = ("mass_erase",)
                else:
                    addr, = struct.unpack("<I", data[1:5])
                    self._pending = ("erase", addr)
            else:
                raise UsbStall(f"unsupported DfuSe cmd 0x{cmd:02x}")
            self.state = C.STATE_DNLOAD_SYNC
        elif wValue == 1:
            raise UsbStall("reserved block 1")
        else:  # wValue >= 2
            if len(data) == 0:  # zero-length -> leave / manifest
                self._pending = ("manifest",)
                self.state = C.STATE_MANIFEST_SYNC
            else:
                addr = (wValue - C.DNLOAD_BLOCK_BASE) * C.TRANSFER_SIZE + self.address_pointer
                self._pending = ("write", addr, data)
                self.state = C.STATE_DNLOAD_SYNC

    # -- IN (device -> host) -------------------------------------------------------
    def _handle_in(self, request, wValue, length):
        if request == C.DFU_GETSTATUS:
            return self._getstatus()
        if request == C.DFU_GETSTATE:
            return bytes([self.state])
        if request == C.DFU_UPLOAD:
            if wValue < C.DNLOAD_BLOCK_BASE:
                raise UsbStall("upload block < 2")
            addr = (wValue - C.DNLOAD_BLOCK_BASE) * C.TRANSFER_SIZE + self.address_pointer
            return self.memory.read(addr, min(length, C.TRANSFER_SIZE))
        raise UsbStall(f"unsupported IN request {request}")

    def _getstatus(self) -> bytes:
        # The deferred action runs during the first GETSTATUS after a command DNLOAD.
        if self.state == C.STATE_DNLOAD_SYNC:
            self._apply_pending()
            self.state = C.STATE_ERROR if self.status != C.STATUS_OK else C.STATE_DNBUSY
        elif self.state == C.STATE_DNBUSY:
            self.state = C.STATE_DNLOAD_IDLE
        elif self.state == C.STATE_MANIFEST_SYNC:
            self._apply_pending()
            self.state = C.STATE_MANIFEST
        elif self.state == C.STATE_MANIFEST:
            self.state = C.STATE_MANIFEST_WAIT_RESET
        poll = 1  # ms
        return bytes([self.status, poll & 0xFF, (poll >> 8) & 0xFF, (poll >> 16) & 0xFF,
                      self.state, 0])

    def _apply_pending(self):
        action = self._pending
        self._pending = None
        if action is None:
            return
        kind = action[0]
        if kind == "setaddr":
            self.address_pointer = action[1]
        elif kind == "erase":
            if self.memory.is_writable(action[1], 1):
                self.memory.erase_page(action[1])
            else:
                self.status = C.STATUS_errTARGET
        elif kind == "mass_erase":
            self.memory = _SparseMemory(self.memory._writable)
        elif kind == "write":
            _, addr, data = action
            if self.memory.is_writable(addr, len(data)):
                self.memory.write(addr, data)
            else:
                self.status = C.STATUS_errTARGET
        elif kind == "manifest":
            self.left = True
            self.jump_address = self.address_pointer + C.USERLAND_HEADER_SIZE


def virtual_calculator(model_name: str = "n0110", *, os_version: str = "23.2.4",
                       commit: str = "abc1234", serial: str | None = None) -> VirtualDfuDevice:
    """Convenience factory. ``model_name`` is e.g. 'n0110', 'n0120', 'n0200'."""
    bcd = next((b for b, m in MODELS.items() if m.name == model_name), None)
    if bcd is None:
        raise ValueError(f"unknown model {model_name!r}; known: {[m.name for m in MODELS.values()]}")
    return VirtualDfuDevice(MODELS[bcd], os_version=os_version, commit=commit, serial=serial)
