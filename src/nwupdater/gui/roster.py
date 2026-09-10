"""Classroom projections: the fleet table, the class buckets and a class's distribution.

Pure Python — the backend calls these to turn ``Session.roster()`` into rows and maps. Keeping
them here means the filtering rule and the distribution defaults are unit-testable, and that the
QML never has to know the roster's storage shape.
"""

from __future__ import annotations

from typing import Any

from .format import relative_key

CLASS_ALL = "__all__"
CLASS_UNFILED = "__unfiled__"

# QML reserves `id`, and inside a delegate `model` is the model object itself: a role by either
# name silently blanks the whole row. Both are renamed here, once.
#
# Every field below is bound by the table's delegate. A role nobody draws is not free: it is
# rebuilt for every calculator on every keystroke of the filter.
ROSTER_FIELDS = (
    "key",
    "displayName",
    "family",
    "knownFirmware",
    "upToDate",
    "lastScanKey",  # i18n key + count rather than a sentence, so a language switch is free
    "lastScanN",
    "lastDist",  # per-action outcome of the last batch pass, {} until one runs
)
CLASS_FIELDS = ("classId", "label", "count", "icon")

# The chain, in execution order. ``journal`` is the key the batch journal records an outcome
# under — ``census`` is configured but recorded as ``recensement`` (see Session.batch_run).
DIST_ACTIONS = ("census", "firmware", "apps", "scripts")
DIST_JOURNAL_KEYS = ("recensement", "firmware", "apps", "scripts")


def default_distribution() -> dict[str, Any]:
    """Mirror of ``classroom_roster.default_distribution`` — the shape shown before a class has
    ever been configured."""
    return {
        "actions": {"census": True, "firmware": False, "apps": True, "scripts": True},
        "onboarding": "move",
        "apps": [],
        "scripts": [],
    }


def in_class(calculator: dict, class_id: str) -> bool:
    if class_id == CLASS_ALL:
        return True
    if class_id == CLASS_UNFILED:
        return not calculator.get("class")
    return calculator.get("class") == class_id


def roster_rows(roster: dict, class_id: str, name_filter: str = "", **kw) -> list[dict[str, Any]]:
    """The calculators of ``class_id`` whose display name matches ``name_filter``.

    ``kw`` is forwarded to :func:`~nwupdater.gui.format.relative_key` (only ``now``, injected by
    the tests so the last-scan column can be asserted without freezing the clock).
    """
    needle = (name_filter or "").strip().lower()
    rows = []
    for c in roster.get("calculators", []):
        if not in_class(c, class_id):
            continue
        display = c.get("name") or c.get("default") or ""
        if needle and needle not in display.lower():
            continue
        scan_key, scan_n = relative_key(c.get("last_scan"), **kw)
        last_dist = c.get("last_dist")
        rows.append(
            {
                "key": c.get("key"),
                "displayName": display,
                "family": c.get("family") or "",
                "knownFirmware": c.get("known_firmware") or "—",
                "upToDate": bool(c.get("up_to_date")),
                "lastScanKey": scan_key,
                "lastScanN": scan_n,
                "lastDist": dict(last_dist) if isinstance(last_dist, dict) else {},
            }
        )
    return rows


def class_buckets(roster: dict) -> list[dict[str, Any]]:
    """The rail: All on top, the classes in the middle, Unfiled at the bottom."""
    counts = roster.get("counts") or {}
    buckets = [
        {"classId": CLASS_ALL, "label": "", "count": int(roster.get("total") or 0), "icon": "stack"}
    ]
    buckets += [
        {"classId": name, "label": name, "count": int(counts.get(name, 0)), "icon": "folder"}
        for name in roster.get("classes", [])
    ]
    buckets.append(
        {
            "classId": CLASS_UNFILED,
            "label": "",
            "count": int(roster.get("unfiled_count") or 0),
            "icon": "inbox",
        }
    )
    return buckets


def distribution_view(roster: dict, class_id: str) -> dict[str, Any]:
    """A class's distribution config plus the pools it can draw from.

    ``editable`` is false for All and Unfiled: distribution is a property of a real class, and
    the pane says so rather than showing a form that saves nowhere.
    """
    editable = class_id not in (CLASS_ALL, CLASS_UNFILED) and bool(class_id)
    stored = (roster.get("distributions") or {}).get(class_id) if editable else None
    config = stored if isinstance(stored, dict) else default_distribution()
    return {
        "className": class_id if editable else "",
        "editable": editable,
        "actions": {a: bool(config.get("actions", {}).get(a)) for a in DIST_ACTIONS},
        "onboarding": config.get("onboarding", "move"),
        "apps": list(config.get("apps", [])),
        "scripts": list(config.get("scripts", [])),
        "availableApps": list(roster.get("dist_apps") or []),
        "availableScripts": list(roster.get("dist_scripts") or []),
    }


def enabled_steps(view: dict) -> list[str]:
    """The distribution's actions in chain order — what a batch pass will actually do."""
    return [a for a in DIST_ACTIONS if view["actions"].get(a)]
