"""Packaged entry point for the `nwupdater-capture` executable.

Double-clicked (no args) → runs `serve` (opens the local page with the bookmarklet + checklist).
With args → passes them through (`analyze`, `scrub`, `serve --port …`).
"""

from __future__ import annotations

import sys

from nwupdater.tools.capture_cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["serve"]))
