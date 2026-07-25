"""Local store for user-assigned calculator names.

A calculator's display name is chosen by the user and kept LOCALLY, keyed by ``model + serial``,
in a small JSON file under the app config dir (mirroring where the NumWorks token lives, see
:func:`nwupdater.catalog.auth.config_path`). This is the offline-first foundation; syncing the
name to the NumWorks account is a separate, deferred step (a stub/TODO lives in the server
session layer). Local naming works fully on its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def store_path(*, path: Path | None = None) -> Path:
    """Where the names JSON lives: ``$NWUPDATER_CONFIG_DIR`` / ``$XDG_CONFIG_HOME`` /
    ``~/.config`` + ``nwupdater/device-names.json`` (same base as the credentials file)."""
    if path is not None:
        return path
    base = (
        os.environ.get("NWUPDATER_CONFIG_DIR")
        or os.environ.get("XDG_CONFIG_HOME")
        or os.path.join(os.path.expanduser("~"), ".config")
    )
    return Path(base) / "nwupdater" / "device-names.json"


def _key(model: str, serial: str) -> str:
    return f"{(model or '').strip().lower()}:{(serial or '').strip()}"


def _load(path: Path | None) -> dict[str, str]:
    p = store_path(path=path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def all_names(*, path: Path | None = None) -> dict[str, str]:
    """Every stored ``"model:serial" -> name`` pair."""
    return _load(path)


def get_name(model: str, serial: str, *, path: Path | None = None) -> str | None:
    """The user name for this calculator, or ``None`` when unset (caller shows the default)."""
    return _load(path).get(_key(model, serial))


def set_name(model: str, serial: str, name: str, *, path: Path | None = None) -> str | None:
    """Persist ``name`` for this calculator. An empty/whitespace name CLEARS the override (the
    display falls back to the ``calc <MODEL>`` default). Returns the stored name (or ``None``)."""
    p = store_path(path=path)
    data = _load(path)
    key = _key(model, serial)
    trimmed = (name or "").strip()
    if trimmed:
        data[key] = trimmed
    else:
        data.pop(key, None)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return trimmed or None
