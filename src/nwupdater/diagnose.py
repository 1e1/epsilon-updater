"""Read-only diagnostic + capture harness.

Enumerates a NumWorks calculator, reads its identity **read-only** (model, OS version,
headers — no erase, no download-data, nothing written to the device) and records every USB
control transfer. Produces a JSON report a volunteer can send back to validate `usbio` and
the DFU read path on real hardware.

The core (`diagnose`) is transport-agnostic and fully tested here against the virtual device;
only the real-USB enumeration (in the CLI) runs on the volunteer's machine.
"""

from __future__ import annotations

import time

from .dfu.capture import CapturingDevice
from .dfu.identity import read_identity
from .dfu.protocol import DfuClient
from .models import describe_bcd, family_for_bcd

TOOL = "nwupdater-diagnose"


def _fmt_region(region):
    """Format an (start, end) apps region, treating absent/(0,0) as None (no QSPI)."""
    if not region or region == (0, 0):
        return None
    return [f"0x{region[0]:08x}", f"0x{region[1]:08x}"]


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("nwupdater")
    except Exception:
        from . import __version__

        return __version__


def diagnose(
    device,
    *,
    interface: int = 0,
    bcd_device: int | None = None,
    sleep=time.sleep,
    timestamp: str | None = None,
) -> dict:
    """Run the read-only identity read against ``device`` and return a report dict.

    ``device`` is any pyusb-like device (real or virtual). Never writes to the device.
    """
    bcd = bcd_device if bcd_device is not None else device.bcdDevice
    cap = CapturingDevice(device)
    client = DfuClient(cap, interface=interface, sleep=sleep)

    error = None
    ident = None
    try:
        ident = read_identity(client, bcd)
    except Exception as exc:  # report the failure instead of crashing the harness
        error = f"{type(exc).__name__}: {exc}"

    report = {
        "tool": TOOL,
        "tool_version": _version(),
        "timestamp": timestamp,
        "read_only": True,
        "usb": {
            "idVendor": f"0x{device.idVendor:04x}",
            "idProduct": f"0x{device.idProduct:04x}",
            "bcdDevice": f"0x{bcd:04x}",
            "interface": interface,
        },
        "model": ident.model_name if ident else f"n{bcd:04x}",
        "family": ident.family if ident else family_for_bcd(bcd),
        "description": describe_bcd(bcd),
        "serial_number": ident.serial_number if ident else None,
        "os_version": ident.os_version if ident else None,
        "kernel_version": ident.kernel_version if ident else None,
        "commit": ident.commit if ident else None,
        "slot_info_valid": ident.slot_info_valid if ident else False,
        "external_apps_flash": _fmt_region(ident.external_apps_flash if ident else None),
        "external_apps_ram": _fmt_region(ident.external_apps_ram if ident else None),
        "transfers": cap.transfers,
        "transfer_count": len(cap.transfers),
        "error": error,
    }
    return report
