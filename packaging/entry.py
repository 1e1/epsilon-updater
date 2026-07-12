"""Desktop entry point (packaged double-click app).

Starts the local server on a free port and opens the browser. Runs in virtual/demo mode by
default (no real USB); set NWUPDATER_REAL=1 to drive a real calculator via pyusb (falls back
to the demo if none is found).
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from nwupdater.server.session import Session
    from nwupdater.server.httpd import serve

    want_real = bool(os.environ.get("NWUPDATER_REAL")) or "--real" in sys.argv
    model = os.environ.get("NWUPDATER_MODEL", "n0110")
    # Auto-quit after inactivity (default 15 min; NWUPDATER_IDLE_TIMEOUT=0 disables).
    try:
        idle = float(os.environ.get("NWUPDATER_IDLE_TIMEOUT", "900"))
    except ValueError:
        idle = 900.0

    try:
        session = Session(model_name=model, real=want_real)
    except SystemExit:
        # no real device / pyusb missing -> demo mode so the app still opens
        session = Session(model_name=model, real=False)

    # port 0 -> OS picks a free port; single_instance reuses a running app instead of
    # starting a second server on repeated double-clicks.
    serve(session, port=0, open_browser=True, single_instance=True,
          idle_timeout=idle if idle > 0 else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
