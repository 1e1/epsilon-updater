"""Host-side DFU/DfuSe client.

Talks to *any* object exposing the small subset of the pyusb ``usb.core.Device`` API we
need (``ctrl_transfer`` plus ``idVendor``/``idProduct``/``bcdDevice`` attributes). This is
deliberately transport-agnostic so the exact same client drives:

  - the in-process virtual device (nwupdater.testing.virtual_dfu)  -> dev & tests, no USB
  - a real pyusb device                                            -> production only

It never imports pyusb itself; nothing here touches real hardware.

Reference: docs/01-specs/usb-dfu-protocol.md (§3-§8).
"""

from __future__ import annotations

import struct
import time
from typing import Protocol

from . import constants as C


class UsbDeviceLike(Protocol):
    idVendor: int
    idProduct: int
    bcdDevice: int

    def ctrl_transfer(
        self,
        bmRequestType: int,
        bRequest: int,
        wValue: int = 0,
        wIndex: int = 0,
        data_or_wLength=None,
        timeout: int | None = None,
    ): ...


class DfuError(RuntimeError):
    def __init__(self, status: int, state: int, context: str = ""):
        self.status = status
        self.state = state
        name = C.STATUS_NAMES.get(status, hex(status))
        sname = C.STATE_NAMES.get(state, hex(state))
        super().__init__(f"DFU error {name} in state {sname}" + (f" ({context})" if context else ""))


class DfuStatus:
    __slots__ = ("status", "poll_timeout_ms", "state", "istring")

    def __init__(self, raw: bytes):
        if len(raw) < 6:
            raise ValueError(f"GETSTATUS reply too short: {raw!r}")
        self.status = raw[0]
        self.poll_timeout_ms = raw[1] | (raw[2] << 8) | (raw[3] << 16)  # 24-bit LE
        self.state = raw[4]
        self.istring = raw[5]

    def __repr__(self) -> str:
        return (f"DfuStatus(status={C.STATUS_NAMES.get(self.status, self.status)}, "
                f"state={C.STATE_NAMES.get(self.state, self.state)}, "
                f"poll={self.poll_timeout_ms}ms)")


class DfuClient:
    """Stateless-ish wrapper implementing the NumWorks DFU/DfuSe host protocol."""

    def __init__(self, device: UsbDeviceLike, *, sleep=time.sleep, timeout_ms: int = 4000,
                 interface: int = C.DFU_INTERFACE):
        self.dev = device
        self._sleep = sleep
        self.timeout_ms = timeout_ms
        self.interface = interface  # DFU interface (wIndex); 0 on all known NumWorks devices
        self._address_pointer = 0

    # -- low-level requests --------------------------------------------------------
    def _out(self, request: int, wValue: int = 0, data: bytes = b"") -> None:
        self.dev.ctrl_transfer(C.REQ_OUT, request, wValue, self.interface, data, self.timeout_ms)

    def _in(self, request: int, length: int, wValue: int = 0) -> bytes:
        return bytes(self.dev.ctrl_transfer(C.REQ_IN, request, wValue, self.interface, length, self.timeout_ms))

    # -- DFU primitives ------------------------------------------------------------
    def get_status(self) -> DfuStatus:
        st = DfuStatus(self._in(C.DFU_GETSTATUS, 6))
        if st.poll_timeout_ms:
            self._sleep(st.poll_timeout_ms / 1000.0)
        return st

    def get_state(self) -> int:
        return self._in(C.DFU_GETSTATE, 1)[0]

    def clear_status(self) -> None:
        self._out(C.DFU_CLRSTATUS)

    def abort(self) -> None:
        self._out(C.DFU_ABORT)

    def _wait_idle_after_command(self, context: str) -> None:
        """After a command DNLOAD (set-address/erase/write): expect DNBUSY then DNLOAD_IDLE."""
        st = self.get_status()  # triggers deferred action; device reports DNBUSY
        if st.status != C.STATUS_OK:
            raise DfuError(st.status, st.state, context)
        st = self.get_status()  # now DNLOAD_IDLE
        if st.status != C.STATUS_OK:
            raise DfuError(st.status, st.state, context)

    def make_idle(self) -> None:
        """Bring the device to dfuIDLE regardless of current state (docs §8.1 step 2)."""
        for _ in range(8):
            state = self.get_state()
            if state == C.STATE_DFU_IDLE:
                return
            if state == C.STATE_ERROR:
                self.clear_status()
            elif state in (C.STATE_DNLOAD_IDLE, C.STATE_UPLOAD_IDLE, C.STATE_MANIFEST_SYNC):
                self.abort()
            else:
                self.abort()
        raise RuntimeError("could not reach dfuIDLE")

    # -- DfuSe commands ------------------------------------------------------------
    def set_address(self, address: int) -> None:
        self._out(C.DFU_DNLOAD, 0, struct.pack("<BI", C.DFUSE_SET_ADDRESS, address))
        self._wait_idle_after_command(f"set_address 0x{address:08x}")
        self._address_pointer = address

    def erase_page(self, address: int) -> None:
        self._out(C.DFU_DNLOAD, 0, struct.pack("<BI", C.DFUSE_ERASE, address))
        self._wait_idle_after_command(f"erase 0x{address:08x}")

    def mass_erase(self) -> None:
        self._out(C.DFU_DNLOAD, 0, bytes([C.DFUSE_ERASE]))
        self._wait_idle_after_command("mass_erase")

    # -- standard descriptors (serial number) --------------------------------------
    def get_string_descriptor(self, index: int, langid: int = C.USB_LANGID_EN_US) -> str | None:
        """Read USB string descriptor ``index`` (standard GET_DESCRIPTOR), or None.

        Transport-agnostic: works against both the virtual device and real hardware
        (this is exactly what pyusb's ``util.get_string`` does under the hood). Returns
        None for index 0 or on any failure/empty descriptor. Does not disturb the DFU
        state machine — it is a standard device request, valid in any state.
        """
        if not index:
            return None
        wValue = (C.DESC_TYPE_STRING << 8) | index
        try:
            raw = bytes(self.dev.ctrl_transfer(
                C.REQ_STD_DEVICE_IN, C.STD_GET_DESCRIPTOR, wValue, langid, 255, self.timeout_ms))
        except Exception:
            return None
        if len(raw) < 2 or raw[1] != C.DESC_TYPE_STRING:
            return None
        # raw[0] is bLength; trust it but never read past what we got.
        end = min(raw[0], len(raw))
        text = raw[2:end].decode("utf-16-le", "replace").strip("\x00").strip()
        return text or None

    # -- memory read/write ---------------------------------------------------------
    def read(self, address: int, length: int) -> bytes:
        """UPLOAD ``length`` bytes starting at ``address`` (Flash backend memcpy)."""
        self.set_address(address)
        self.abort()  # return to dfuIDLE so UPLOAD block numbering starts clean
        out = bytearray()
        block = C.DNLOAD_BLOCK_BASE
        while len(out) < length:
            chunk = self._in(C.DFU_UPLOAD, min(C.TRANSFER_SIZE, length - len(out)), block)
            if not chunk:
                break
            out += chunk
            block += 1
        return bytes(out[:length])

    def write(self, address: int, data: bytes, *, erase: bool = False) -> None:
        """DNLOAD ``data`` at ``address`` in <=2048-byte chunks (dfu.py strategy)."""
        for off in range(0, len(data), C.TRANSFER_SIZE):
            chunk = data[off:off + C.TRANSFER_SIZE]
            addr = address + off
            if erase:
                self.erase_page(addr)
            self.set_address(addr)
            self._out(C.DFU_DNLOAD, C.DNLOAD_BLOCK_BASE, chunk)
            self._wait_idle_after_command(f"write 0x{addr:08x}")

    # -- leave ---------------------------------------------------------------------
    def leave(self, jump_address: int) -> None:
        """Set address pointer then zero-length DNLOAD -> manifest -> reset+jump.

        The device jumps to ``jump_address + sizeof(UserlandHeader)`` (docs §8.3). The USB
        handle drops (manifestationTolerant=0); callers must re-enumerate to talk again.
        """
        self.set_address(jump_address)
        self._out(C.DFU_DNLOAD, C.DNLOAD_BLOCK_BASE, b"")  # zero-length -> manifest
        try:
            self.get_status()  # device enters MANIFEST, sleeps 1ms, resets
        except Exception:
            pass  # disconnect is expected
