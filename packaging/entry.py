"""Desktop entry point (packaged double-click app).

Starts the local server on a free port and opens the browser. Real-first, exactly like the
``ui`` command: the app opens DISCONNECTED and attaches a real calculator only if one is
actually plugged in. A calculator connected AFTER launch is picked up automatically (the page
rescans). The demo device is NEVER started silently — it is opt-in via ``NWUPDATER_DEMO`` /
``--demo`` or the "explore a demo" button on the page.
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

    session = Session(model_name=model, connect=False, live_catalog=True)
    if force_demo:
        session.attach_demo(model)
    else:
        try:
            session.attach_real()  # real calculator if one is already plugged in
        except Exception:
            pass  # none yet — the page waits and auto-detects one when it is plugged in

    # port 0 -> OS picks a free port; single_instance reuses a running app instead of
    # starting a second server on repeated double-clicks.
    serve(
        session,
        port=0,
        open_browser=True,
        single_instance=True,
        idle_timeout=idle if idle > 0 else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
