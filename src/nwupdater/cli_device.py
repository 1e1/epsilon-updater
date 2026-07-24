"""Device acquisition for the CLI: open the in-memory virtual device or a real calculator."""

from __future__ import annotations

import sys
import time
from typing import Callable, NamedTuple

from .dfu.protocol import DfuClient


def _open_real_device():
    """Open + configure + claim a real calculator's DFU interface. Production only.

    Returns ``(device, bcdDevice, interface)``. Exits with a helpful message if pyusb is
    missing or no calculator/DFU interface is available."""
    from .dfu import usbio

    try:
        od = usbio.open_calculator()
    except usbio.PyusbMissing as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except usbio.UsbError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    return od.dev, od.bcd_device, od.interface


def _nosleep(*_) -> None:
    """No-op sleep for the in-memory virtual device (no real DFU polling delay)."""


class _Opened(NamedTuple):
    """A device opened for a CLI command (virtual or real)."""

    dev: object
    bcd: int
    client: DfuClient
    iface: int
    sleep: Callable[..., None]


def _open_device(args) -> _Opened:
    """Open the device a CLI command targets — the in-memory virtual device when ``--virtual``,
    otherwise a real calculator (pyusb). One place instead of the per-command copy.

    ``client`` is ``DfuClient(dev, interface=iface, sleep=sleep)`` in both cases; ``iface`` and
    ``sleep`` are also returned for the read-only harnesses (diagnose/capture) that drive the raw
    device with their own timing."""
    if args.virtual:
        from .testing.virtual_dfu import virtual_calculator

        kw: dict[str, str] = {}
        if getattr(args, "os_version", None) is not None:
            kw["os_version"] = args.os_version
        if getattr(args, "commit", None) is not None:
            kw["commit"] = args.commit
        dev = virtual_calculator(args.virtual, **kw)
        return _Opened(dev, dev.bcdDevice, DfuClient(dev, sleep=_nosleep), 0, _nosleep)
    dev, bcd, iface = _open_real_device()
    return _Opened(dev, bcd, DfuClient(dev, interface=iface), iface, time.sleep)
