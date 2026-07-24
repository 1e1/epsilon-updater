"""Real-hardware USB acquisition for the DFU client.

This is the ONLY code path that talks to physical hardware, and it is used **in production
only** — never in dev/tests (see the project's hard rule: no real USB). To keep it testable
without pyusb or a device, the pyusb modules are **injected** (``core``/``util`` params):
the CLI passes the real ``usb.core``/``usb.util``; tests pass fakes.

Responsibilities the transport-agnostic ``DfuClient`` does NOT handle but a real device needs:
  1. enumerate NumWorks devices (VID 0x0483 × known PIDs), in priority order;
  2. ``set_configuration()``;
  3. locate the DFU interface (bInterfaceClass 0xFE / subclass 0x01) and its number;
  4. ``claim_interface`` it;
  5. select the Flash alt-setting (alt 0 — memcpy read from any address on NumWorks).

Errors are raised as :class:`UsbError` subclasses carrying actionable, human hints.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import constants as C
from .layout import parse_memory_layout
from .protocol import UsbDeviceLike, read_string_descriptor


class UsbError(RuntimeError):
    """Base for real-USB acquisition failures (with a human-actionable message)."""


class PyusbMissing(UsbError):
    pass


class NoCalculatorFound(UsbError):
    pass


class DfuInterfaceNotFound(UsbError):
    pass


class InterfaceClaimError(UsbError):
    pass


@dataclass
class OpenDevice:
    dev: UsbDeviceLike   # the pyusb usb.core.Device or the virtual device (structural contract)
    bcd_device: int
    interface: int       # DFU interface number (wIndex for control transfers)
    alt_setting: int
    id_product: int
    memory_layout: object | None = None  # parsed DfuSe flash layout (§6.4), if advertised


def _read_memory_layout(dev, intf):
    """Read + parse the DFU interface's DfuSe memory-layout string (``iInterface``).

    Gives the real, possibly non-uniform flash sector geometry so writes erase each sector
    once (see dfu/layout.py). Best-effort: any failure returns None (erase then falls back
    to the historical per-chunk behaviour)."""
    index = getattr(intf, "iInterface", 0) or 0
    if not index:
        return None
    try:
        return parse_memory_layout(read_string_descriptor(dev, index))
    except Exception:
        return None


def _find_dfu_interface(cfg):
    """Return the DFU interface descriptor (class 0xFE / subclass 0x01), or None.

    Matches by class like webdfu_numworks (robust to interface renumbering). An active pyusb
    configuration is directly iterable over its interface descriptors."""
    for intf in cfg:
        if (getattr(intf, "bInterfaceClass", None) == C.DFU_INTERFACE_CLASS
                and getattr(intf, "bInterfaceSubClass", None) == C.DFU_INTERFACE_SUBCLASS):
            return intf
    return None


def _resolve_backend(backend):
    """A libusb backend. Prefer the bundled one (``libusb-package``) so a packaged app is
    self-contained; fall back to pyusb's system-libusb discovery."""
    if backend is not None:
        return backend
    try:
        import libusb_package
        return libusb_package.get_libusb1_backend()
    except Exception:
        return None


def find_calculator(core, util, *, vid: int = C.USB_VID, pids=C.KNOWN_PIDS,
                    backend=None) -> OpenDevice:
    """Find, configure and claim a NumWorks calculator's DFU interface.

    ``core``/``util`` are the ``usb.core``/``usb.util`` modules (injected for testability).
    ``backend`` is an optional libusb backend (defaults to the bundled ``libusb-package``).
    Raises a :class:`UsbError` subclass with a helpful message on any failure.
    """
    backend = _resolve_backend(backend)
    # Only pass backend when we actually resolved one — keeps compatibility with a system
    # libusb (backend=None) and with test doubles whose find() doesn't take the kwarg.
    kw = {"backend": backend} if backend is not None else {}
    # 1. enumerate, PID priority order (bootloader modes first — that's where flashing lives)
    dev = None
    matched_pid = None
    for pid in pids:
        found = list(core.find(find_all=True, idVendor=vid, idProduct=pid, **kw) or [])
        if found:
            dev, matched_pid = found[0], pid
            break
    if dev is None:
        raise NoCalculatorFound(
            "No NumWorks calculator detected over USB.\n"
            "  • Plug in the calculator and put it in DFU/bootloader mode\n"
            "    (e.g. N0110: RESET while holding the 6 key; black screen, LED),\n"
            "  • check the cable (data, not charge-only),\n"
            f"  • VID 0x{vid:04x}, expected PIDs: {', '.join(f'0x{p:04x}' for p in pids)}.")
    assert matched_pid is not None  # set alongside dev in the scan loop above

    # 2. activate configuration (idempotent; ignore if already configured)
    try:
        dev.set_configuration()
    except Exception:
        pass

    # 3. locate the DFU interface by class
    try:
        cfg = dev.get_active_configuration()
    except Exception as exc:  # pragma: no cover - hardware-specific
        raise UsbError(f"unreadable USB configuration: {exc}") from exc
    intf = _find_dfu_interface(cfg)
    if intf is None:
        raise DfuInterfaceNotFound(
            "DFU interface not found (class 0xFE/0x01). The device is probably not in "
            "DFU mode — put it back in bootloader and retry.")
    interface = getattr(intf, "bInterfaceNumber", C.DFU_INTERFACE)
    alt = getattr(intf, "bAlternateSetting", C.ALT_FLASH)

    # 4. claim the interface (surface permission problems clearly)
    try:
        util.claim_interface(dev, interface)
    except Exception as exc:
        raise InterfaceClaimError(
            f"cannot claim DFU interface {interface}: {exc}\n"
            "  • macOS/Linux: insufficient USB permissions (libusb / udev rule),\n"
            "  • another program (a WebUSB browser?) may already be using it.") from exc

    # 5. select the Flash alt-setting (best effort — NumWorks alt 0 reads/writes any address)
    try:
        dev.set_interface_altsetting(interface=interface, alternate_setting=C.ALT_FLASH)
        alt = C.ALT_FLASH
    except Exception:
        pass

    # 6. read the real flash sector geometry and attach it to the device so DfuClient erases
    #    correctly (sector-aligned, once per sector). Optional — never blocks opening.
    layout = _read_memory_layout(dev, intf)
    if layout is not None:
        try:
            dev.memory_layout = layout
        except Exception:
            pass

    return OpenDevice(dev=dev, bcd_device=dev.bcdDevice, interface=interface,
                      alt_setting=alt, id_product=matched_pid, memory_layout=layout)


def open_calculator(core=None, util=None, *, backend=None) -> OpenDevice:
    """Import pyusb (unless ``core``/``util`` are injected) then find/configure/claim a calculator.

    The single library entry point both the CLI and the local server use to reach real hardware,
    so neither reaches into the other. Library-clean: raises :class:`PyusbMissing` when pyusb is
    absent, or another :class:`UsbError` subclass on failure — it never prints or calls
    ``sys.exit``, leaving each caller to present the error its own way.
    """
    if core is None or util is None:
        try:
            import usb.core
            import usb.util
        except ImportError as exc:
            raise PyusbMissing(
                "pyusb required for real mode: pip install 'nwupdater[usb]'") from exc
        core, util = usb.core, usb.util
    return find_calculator(core, util, backend=backend)
