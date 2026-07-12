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


def _iter_interfaces(cfg):
    """Yield interface descriptors from an active configuration (pyusb is iterable)."""
    for intf in cfg:
        yield intf


def _find_dfu_interface(cfg):
    """Return the DFU interface descriptor (class 0xFE / subclass 0x01), or None.

    Matches by class like webdfu_numworks (robust to interface renumbering)."""
    for intf in _iter_interfaces(cfg):
        if (getattr(intf, "bInterfaceClass", None) == C.DFU_INTERFACE_CLASS
                and getattr(intf, "bInterfaceSubClass", None) == C.DFU_INTERFACE_SUBCLASS):
            return intf
    return None


def find_calculator(core, util, *, vid: int = C.USB_VID, pids=C.KNOWN_PIDS) -> OpenDevice:
    """Find, configure and claim a NumWorks calculator's DFU interface.

    ``core``/``util`` are the ``usb.core``/``usb.util`` modules (injected for testability).
    Raises a :class:`UsbError` subclass with a helpful message on any failure.
    """
    # 1. enumerate, PID priority order (bootloader modes first — that's where flashing lives)
    dev = None
    matched_pid = None
    for pid in pids:
        found = list(core.find(find_all=True, idVendor=vid, idProduct=pid) or [])
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

    return OpenDevice(dev=dev, bcd_device=dev.bcdDevice, interface=interface,
                      alt_setting=alt, id_product=matched_pid)
