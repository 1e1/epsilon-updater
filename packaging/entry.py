"""Desktop entry point (packaged double-click app).

Starts the local server on a free port and opens the browser. Tries the REAL calculator
first (pyusb + bundled libusb); if none is plugged in (or NWUPDATER_DEMO=1), falls back to
the virtual demo so the app always opens.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from nwupdater.server.httpd import serve
    from nwupdater.server.session import Session

    force_demo = bool(os.environ.get("NWUPDATER_DEMO")) or "--demo" in sys.argv
    model = os.environ.get("NWUPDATER_MODEL", "n0110")
    # Auto-quit after inactivity (default 15 min; NWUPDATER_IDLE_TIMEOUT=0 disables).
    try:
        idle = float(os.environ.get("NWUPDATER_IDLE_TIMEOUT", "900"))
    except ValueError:
        idle = 900.0

    session = None
    if not force_demo:
        try:
            session = Session(model_name=model, real=True)  # real calculator if one is plugged
        except (SystemExit, Exception):
            session = None  # no device / pyusb / libusb -> fall back to the demo below
    if session is None:
        session = Session(model_name=model, real=False)

    # port 0 -> OS picks a free port; single_instance reuses a running app instead of
    # starting a second server on repeated double-clicks.
    serve(session, port=0, open_browser=True, single_instance=True,
          idle_timeout=idle if idle > 0 else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
