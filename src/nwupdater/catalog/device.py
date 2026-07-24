"""Device registration / heartbeat with the workshop — OPTIONAL, account-side.

Reverse-engineered from a real capture (dump_capture, docs/01-specs/scripts-and-device-pairing.md):
the official workshop reads the calculator identity over USB, then POSTs to
``/devices/{serial}`` (session-cookie auth) to register/refresh the device on the account:

    POST https://my.numworks.com/devices/{serial}
    {"device":{"device_model":"N0200"},
     "firmware":{"software_version":"3.0.0","software_patch_level":"8059a46"}}
    -> 200 {"id":…,"serial_number":…,"device_model":{…},"software_version":…}  (or 204)

This is NOT required to flash the calculator — it only keeps the account's device record in
sync (pairing). Network is injected via the :mod:`auth` Transport → testable offline, no USB.
"""

from __future__ import annotations

import json

from ..formats import platform_info as _pi
from .auth import BASE, UA, Auth, TransportError, UrllibTransport


def device_url(serial: str) -> str:
    return f"{BASE}/devices/{serial}"


def read_firmware_identity(client, model) -> tuple[str, str]:
    """Read ``(software_version, software_patch_level)`` from the connected calculator.

    - N02xx (opaque firmware): the 32-byte FirmwareHeader block @0x080040C0 (magic 0xFACECAFE).
    - Graphique: the on-device identity (KernelHeader/UserlandHeader reached via SlotInfo),
      mapping os_version→version and commit→patch_level.
    """
    if getattr(model, "opaque_firmware", False):
        info = _pi.parse(client.read(_pi.N0200_FIRMWARE_HEADER_ADDR, _pi.PLATFORM_INFO_SIZE))
        return info.software_version, info.patch_level
    from ..dfu.identity import read_identity

    ident = read_identity(client, model.bcd_device)
    return (ident.os_version or ""), (ident.commit or "")


def read_device_identity(client, model) -> dict:
    """Everything the /devices heartbeat needs, read from a connected calc (no network).

    ``{serial, device_model, software_version, software_patch_level}``. Serial comes from the
    USB iSerialNumber descriptor (via the DfuClient — works on real and virtual devices).
    """
    from ..dfu import constants as C

    serial = client.get_string_descriptor(C.SERIAL_STRING_INDEX)
    version, patch = read_firmware_identity(client, model)
    return {
        "serial": (str(serial) if serial else None),
        "device_model": model.name.upper(),  # "N0200" — matches the workshop body
        "software_version": version,
        "software_patch_level": patch,
    }


def pair_device(client, model, auth: Auth, *, transport=None) -> dict:
    """Read identity from a connected calc, then POST the /devices heartbeat (pairing).

    ``client`` = DfuClient, ``model`` = models.Model. Returns the identity used + register result.
    """
    ident = read_device_identity(client, model)
    if not ident["serial"]:
        raise ValueError(
            "serial number unavailable (empty USB iSerialNumber descriptor) — cannot pair"
        )
    reg = register_device(
        auth,
        ident["serial"],
        device_model=ident["device_model"],
        software_version=ident["software_version"],
        software_patch_level=ident["software_patch_level"],
        transport=transport,
    )
    return {**ident, "register": reg}


def register_device(
    auth: Auth,
    serial: str,
    *,
    device_model: str,
    software_version: str,
    software_patch_level: str = "",
    transport=None,
) -> dict:
    """Register/refresh a device on the account. Returns ``{status, body}``.

    ``serial``/``device_model``/``software_version`` come from the on-calc identity read (for
    N0200, the platform-info struct at 0x080040c0). Raises :class:`auth.TransportError` on a
    network failure.
    """
    tr = transport or UrllibTransport()
    payload = json.dumps(
        {
            "device": {"device_model": device_model},
            "firmware": {
                "software_version": software_version,
                "software_patch_level": software_patch_level,
            },
        }
    ).encode("utf-8")
    resp = tr.open(
        "POST",
        device_url(serial),
        data=payload,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cookie": auth.cookie_header(),
        },
    )
    if resp.status == 401:
        raise TransportError("401 — authentication required/expired for /devices")
    return {"status": resp.status, "body": resp.body.decode("utf-8", "replace")[:4000]}
