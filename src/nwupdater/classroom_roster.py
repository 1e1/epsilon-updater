"""Local classroom roster — the offline fleet register (classroom mode only).

This EXTENDS the device-name store (:mod:`nwupdater.device_names`) rather than reimplementing it:
a calculator's identity key is the same ``model:serial`` (:func:`device_names._key`) and its
DISPLAY NAME is **not** duplicated here — it is joined at read time from the name store, so a
rename in either mode follows the calculator everywhere. This module only records which class a
scanned calculator belongs to plus what was seen at the last scan (firmware / family / model +
timestamp).

Local only: the file sits next to ``device-names.json`` under the app config dir and never leaves
the machine. A calculator enters the roster on a successful scan only (no pre-fill); a corrupt or
missing file loads as an empty roster, mirroring :func:`device_names._load`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import device_names

SCHEMA = 1


def roster_path(*, path: Path | None = None) -> Path:
    """Where the roster JSON lives — the SAME base as :func:`device_names.store_path`
    (``$NWUPDATER_CONFIG_DIR`` / ``$XDG_CONFIG_HOME`` / ``~/.config`` + ``nwupdater/``), with the
    filename ``classroom-roster.json``. ``path`` overrides everything (tests)."""
    if path is not None:
        return path
    return device_names.store_path().parent / "classroom-roster.json"


def _now() -> str:
    """ISO 8601 UTC timestamp for ``last_scan``."""
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict:
    return {"schema": SCHEMA, "classes": [], "calculators": {}}


def _load(path: Path | None) -> dict:
    """Load the roster, tolerating a missing/corrupt file (→ empty) like ``device_names._load``.

    An unknown/newer ``schema`` is read cautiously: only the recognised shapes are kept (a list of
    class names, a ``key -> record`` mapping), never a crash."""
    p = roster_path(path=path)
    if not p.is_file():
        return _empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    classes_raw = data.get("classes")
    classes = [str(c) for c in classes_raw] if isinstance(classes_raw, list) else []
    calcs_raw = data.get("calculators")
    calculators: dict[str, dict] = {}
    if isinstance(calcs_raw, dict):
        for k, v in calcs_raw.items():
            if isinstance(v, dict):
                calculators[str(k)] = v
    schema = data.get("schema")
    return {
        "schema": schema if isinstance(schema, int) else SCHEMA,
        "classes": classes,
        "calculators": calculators,
    }


def _save(data: dict, path: Path | None) -> None:
    """Atomic-enough write of the whole blob (mirrors ``device_names.set_name``)."""
    p = roster_path(path=path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _split_key(key: str) -> tuple[str, str]:
    """``"model:serial"`` -> ``(model, serial)``. The serial (Base64 MCU UID) carries no ``:``."""
    model, _, serial = key.partition(":")
    return model, serial


def all_classes(*, path: Path | None = None) -> list[str]:
    """The explicit class list — the rail's source of truth (an empty class may exist here)."""
    return [str(c) for c in _load(path)["classes"]]


def all_entries(*, path: Path | None = None, names_path: Path | None = None) -> list[dict]:
    """Every calculator record, each JOINED with its display name from the name store.

    The serial is never a display field: it stays inside the internal ``key`` (``model:serial``).
    ``default`` is the fallback display (``calc <MODEL>``) when no name is set."""
    data = _load(path)
    out: list[dict] = []
    for key, rec in data["calculators"].items():
        model, serial = _split_key(key)
        known_model = str(rec.get("known_model") or model)
        default = f"calc {model.upper()}" if model else "calc"
        out.append(
            {
                "key": key,  # internal id (model:serial); never a display field
                "model": known_model,
                "name": device_names.get_name(model, serial, path=names_path),
                "default": default,
                "class": rec.get("class"),
                "known_firmware": rec.get("known_firmware"),
                "known_family": rec.get("known_family"),
                "known_model": known_model,
                "last_scan": rec.get("last_scan"),
            }
        )
    return out


def upsert_on_scan(
    model: str,
    serial: str,
    firmware: str | None,
    family: str | None,
    *,
    path: Path | None = None,
) -> bool:
    """Record a scanned calculator, idempotently.

    A NEW calculator lands unfiled (``class=None``, i.e. "Sans classe") with its ``known_*`` set;
    a KNOWN one gets ``known_firmware/family/model`` refreshed while its ``class`` (and its name,
    held in the name store) are left untouched — a re-read never undoes a filing.

    Writes ONLY when a recorded ``known_*`` field actually changes, so repeated scans / the
    liveness poll never thrash ``last_scan``. Returns ``True`` iff the store was written."""
    serial = (serial or "").strip()
    if not serial:
        return False  # no serial (e.g. a raw ST bootloader) → nothing to enrol
    key = device_names._key(model, serial)
    data = _load(path)
    calcs = data["calculators"]
    cur = calcs.get(key)
    known = {
        "known_firmware": firmware or None,
        "known_family": family or None,
        "known_model": (model or "").strip().lower() or None,
    }
    if cur is None:
        calcs[key] = {"class": None, **known, "last_scan": _now()}
        _save(data, path)
        return True
    if all(cur.get(k) == v for k, v in known.items()):
        return False  # nothing changed — leave last_scan alone (anti-thrash)
    cur.update(known)
    cur["last_scan"] = _now()
    _save(data, path)
    return True
