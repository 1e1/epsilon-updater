"""Transparent USB control-transfer recorder.

Wraps any device exposing the pyusb ``ctrl_transfer`` subset and logs every transfer
(direction, setup fields, payload) before delegating. Used by the diagnostic harness to
produce a reference capture of the real calculator dialogue — without changing any logic,
and testable here against the virtual device.
"""

from __future__ import annotations

_MAX_DATA = 2048  # cap logged payload (bytes) so a capture never explodes


class CapturingDevice:
    def __init__(self, inner):
        self._inner = inner
        self.transfers: list[dict] = []
        # mirror the identity attributes the DFU client reads
        self.idVendor = inner.idVendor
        self.idProduct = inner.idProduct
        self.bcdDevice = inner.bcdDevice

    def ctrl_transfer(
        self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None
    ):
        is_in = bool(bmRequestType & 0x80)
        result = self._inner.ctrl_transfer(
            bmRequestType, bRequest, wValue, wIndex, data_or_wLength, timeout
        )
        entry = {
            "seq": len(self.transfers),
            "dir": "IN" if is_in else "OUT",
            "bmRequestType": f"0x{bmRequestType:02x}",
            "bRequest": bRequest,
            "wValue": f"0x{wValue:04x}",
            "wIndex": wIndex,
        }
        if is_in:
            data = bytes(result) if result is not None else b""
            entry["wLength"] = data_or_wLength if isinstance(data_or_wLength, int) else len(data)
        else:
            data = bytes(data_or_wLength) if data_or_wLength else b""
        entry["data_len"] = len(data)
        entry["data"] = data[:_MAX_DATA].hex()
        self.transfers.append(entry)
        return result
