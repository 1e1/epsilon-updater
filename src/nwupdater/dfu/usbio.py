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
from .protocol import read_string_descriptor


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
    dev: object          # the pyusb usb.core.Device (opaque here)
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
            "Aucune calculatrice NumWorks détectée en USB.\n"
            "  • Branchez la calculatrice et mettez-la en mode DFU/bootloader\n"
            "    (ex. N0110 : RESET en maintenant la touche 6 ; écran noir, LED),\n"
            "  • vérifiez le câble (données, pas seulement charge),\n"
            f"  • VID 0x{vid:04x}, PID attendus : {', '.join(f'0x{p:04x}' for p in pids)}.")

    # 2. activate configuration (idempotent; ignore if already configured)
    try:
        dev.set_configuration()
    except Exception:
        pass

    # 3. locate the DFU interface by class
    try:
        cfg = dev.get_active_configuration()
    except Exception as exc:  # pragma: no cover - hardware-specific
        raise UsbError(f"configuration USB illisible : {exc}") from exc
    intf = _find_dfu_interface(cfg)
    if intf is None:
        raise DfuInterfaceNotFound(
            "Interface DFU introuvable (classe 0xFE/0x01). L'appareil n'est probablement pas "
            "en mode DFU — repassez-le en bootloader et réessayez.")
    interface = getattr(intf, "bInterfaceNumber", C.DFU_INTERFACE)
    alt = getattr(intf, "bAlternateSetting", C.ALT_FLASH)

    # 4. claim the interface (surface permission problems clearly)
    try:
        util.claim_interface(dev, interface)
    except Exception as exc:
        raise InterfaceClaimError(
            f"impossible de réserver l'interface DFU {interface} : {exc}\n"
            "  • macOS/Linux : droits USB insuffisants (libusb / règle udev),\n"
            "  • un autre logiciel (navigateur en WebUSB ?) l'utilise peut-être déjà.") from exc

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
