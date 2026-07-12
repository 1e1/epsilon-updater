"""Bespoke capture session for the "scientific first-boot" test scenario.

Records BOTH channels — USB (calculator↔Mac) and WEB (Mac↔my.numworks.com) — for this exact
flow: authenticate, read the calculator, attempt to download the OS, **without flashing**
(so the sequence stays replayable). The server refusing an unregistered calculator is a
valid, captured outcome — not an error.

Nothing is written to the calculator. Secrets are redacted and the firmware binary is never
stored (see net_capture). The core runs here against the virtual device + a fake transport;
only real USB enumeration and real network run on the tester's machine.
"""

from __future__ import annotations

import hashlib
import time

from .catalog import download as D
from .catalog.auth import BASE, UA
from .diagnose import diagnose
from .net_capture import RecordingTransport, inspect_forms

SCENARIO = "scientific-first-boot-download-no-flash"
ENROLL_PORTAL_URL = f"{BASE}/devices/upgrade/"  # WebUSB flash/enrollment page (login required)


def inspect_enrollment(auth, transport, *, serial: str | None = None) -> dict:
    """Read-only inspection of the device-enrollment portal.

    Device enrollment itself runs in Chrome (WebUSB reads the calculator, then the page
    POSTs to register it). We only **GET** the portal to document its form — action, fields,
    CSRF, CAPTCHA — so a headless enrollment can later be grounded on the real endpoint.
    We never submit the form, so **nothing is enrolled**. ``serial``, if known, is recorded
    only to correlate with the field the page would submit; it is never sent anywhere."""
    out: dict = {"url": ENROLL_PORTAL_URL, "read_only": True, "serial_available": bool(serial)}
    try:
        r = transport.open("GET", ENROLL_PORTAL_URL, allow_redirects=True, headers={
            "User-Agent": UA, "Accept": "text/html", "Cookie": auth.cookie_header()})
        out["status"] = r.status
        html = r.body.decode("utf-8", "replace")
        out["forms"] = inspect_forms(html)
        out["authenticated"] = "sign_in" not in (r.header("Location") or "") and r.status == 200
    except Exception as exc:  # never crash the harness
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_capture(usb_device, *, auth, transport, interface: int = 0, bcd_device: int | None = None,
                model: str = "n0200", channel: str = "stable", sleep=time.sleep,
                timestamp: str | None = None, serial: str | None = None) -> dict:
    """Capture the USB + WEB dialogue for the scenario. Never flashes; read-only on the calc."""
    # --- USB side (read-only identity + transfer capture) ---
    usb_report = diagnose(usb_device, interface=interface, bcd_device=bcd_device,
                          sleep=sleep, timestamp=timestamp)

    # --- WEB side (attempt the official download; capture request/response, redacted) ---
    rt = RecordingTransport(transport)
    web: dict = {"model": model, "channel": channel}
    try:
        manifest, blob = D.fetch_firmware(model, channel, auth, transport=rt)
        web["outcome"] = "downloaded"
        web["firmware"] = {
            "version": manifest.version, "size": manifest.size,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "device_type_id": manifest.device_type_id,
        }
        web["note"] = "firmware téléchargé mais NON flashé (séquence rejouable)"
    except D.AuthRequired as exc:
        web["outcome"] = "auth_required"
        web["error"] = str(exc)
    except D.DownloadError as exc:
        # e.g. server refuses an unregistered calculator (first boot) — a captured outcome
        web["outcome"] = "refused_or_error"
        web["error"] = str(exc)
    except Exception as exc:  # never crash the harness; record the failure
        web["outcome"] = "error"
        web["error"] = f"{type(exc).__name__}: {exc}"
    web["transfers"] = rt.transfers

    # --- Enrollment portal (read-only inspection; never enrolls) ---
    # A dedicated recorder so the download transfers above stay isolated from this probe.
    ert = RecordingTransport(transport)
    enrollment = inspect_enrollment(auth, ert, serial=serial)
    enrollment["transfers"] = ert.transfers

    return {
        "scenario": SCENARIO,
        "timestamp": timestamp,
        "flashed": False,
        "enrolled": False,
        "calculator_serial": serial,
        "usb": usb_report,
        "web": web,
        "enrollment": enrollment,
        "redaction": ("secrets caviardés (mot de passe, CSRF, cookies) ; "
                      "firmware non versionné (taille + sha256 uniquement)"),
    }
