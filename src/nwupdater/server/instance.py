"""Single-instance coordination for the desktop app.

Correctness rests on :class:`InstanceLock`, an OS advisory file lock: exactly one process can
hold it, and the kernel drops it automatically when that process dies — so a crash never leaves
a stale lock behind (unlike a PID file). Whoever wins the lock is *the* instance; a second
launch that fails to take it reads the JSON record below to learn where the running instance
serves, reopens the browser there, and exits instead of starting a competing server (two
servers split the UI state and fight over the calculator's USB handle).

The JSON file is only the address channel — it records the URL/port of the live instance so a
losing launch knows where to point the browser. The lock, not the file, guarantees uniqueness.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

from ..cache.store import default_cache_dir

INSTANCE_FILE = default_cache_dir().parent / "instance.json"
LOCK_FILE = default_cache_dir().parent / "instance.lock"
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


def wait_for_url(*, attempts: int = 12, delay: float = 0.25) -> str | None:
    """URL of the running instance once it answers ``/api/ping``, or None.

    For the launch that lost the lock: the winner holds the lock the instant it starts, but its
    HTTP server needs a moment more to bind and answer. Poll briefly to cover that window.
    Unlike :func:`existing_url` this never clears the record — the lock holder owns it."""
    for _ in range(attempts):
        info = _read()
        url = info.get("url") if info else None
        if url and probe(url):
            return url
        time.sleep(delay)
    return None


def write(url: str, port: int) -> None:
    INSTANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCE_FILE.write_text(json.dumps({"url": url, "port": port, "pid": os.getpid()}))


def clear() -> None:
    try:
        INSTANCE_FILE.unlink()
    except OSError:
        pass


class InstanceLock:
    """Exclusive, crash-safe single-instance lock.

    Backed by an OS advisory file lock — ``fcntl.flock`` on POSIX, ``msvcrt.locking`` on
    Windows — so acquisition is atomic (no check-then-act race between concurrent launches) and
    the kernel releases it automatically if the process dies. Held for the whole run: keep the
    handle open for as long as the instance should stay the only one.
    """

    def __init__(self, path=LOCK_FILE):
        self._path = path
        self._fh = None

    def acquire(self) -> bool:
        """True if this process now owns the lock; False if another live instance holds it."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self._path, "a+")  # noqa: SIM115 — kept open for the process lifetime
        except OSError:
            return False
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:  # already locked by another instance (or unsupported) — not us
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None
