"""Desktop entry point for the NATIVE window (packaged double-click app).

Real-first, exactly like the browser app: the window opens DISCONNECTED and attaches a real
calculator only if one is actually plugged in; one connected afterwards is picked up by the
hot-plug watch. The demo device is never started silently — ``NWUPDATER_DEMO`` / ``--demo``, or
the "explore a demo" button.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    from nwupdater.gui.app import run

    force_demo = bool(os.environ.get("NWUPDATER_DEMO")) or "--demo" in sys.argv
    model = os.environ.get("NWUPDATER_MODEL", "n0110")
    lang = os.environ.get("NWUPDATER_LANG", "fr")
    return run(model=model, real=not force_demo, demo=force_demo, lang=lang)


if __name__ == "__main__":
    raise SystemExit(main())
