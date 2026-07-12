"""Single-instance coordination for the desktop app.

A tiny JSON file records the URL of the running instance. A second launch probes that URL
(`/api/ping`) and, if a live nwupdater answers, just reopens the browser there instead of
starting a second server. Stale files (crash, port reused by something else) are detected by
the probe and cleared.
"""

from __future__ import annotations

import json
import os
import urllib.request

from ..cache.store import default_cache_dir

INSTANCE_FILE = default_cache_dir().parent / "instance.json"
APP_MARKER = "nwupdater"


def _read() -> dict | None:
    try:
        return json.loads(INSTANCE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def probe(url: str, *, timeout: float = 0.6) -> bool:
    """True if a live nwupdater instance answers /api/ping at ``url``."""
    if not url.startswith(("http://", "https://")):  # only ever HTTP(S), never file:/
        return False
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/ping", timeout=timeout) as r:  # nosec B310 - schéma http(s) validé ci-dessus
            return json.loads(r.read()).get("app") == APP_MARKER
    except Exception:
        return False


def existing_url() -> str | None:
    """URL of a running instance, or None. Clears a stale record as a side effect."""
    info = _read()
    if info and info.get("url") and probe(info["url"]):
        return info["url"]
    clear()
    return None


def write(url: str, port: int) -> None:
    INSTANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(json.dumps({"url": url, "port": port, "pid": os.getpid()}))


def clear() -> None:
    try:
        INSTANCE_FILE.unlink()
    except OSError:
        pass
