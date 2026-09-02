"""Workshop view state: the user's pending arrangement, projected into rows the UI can draw.

Pure Python — no Qt, no device access. The QML backend owns one of these per workshop and only
copies the results into its list models, which is what makes the whole staging rule testable
without a window (and, before that, without a browser: the same rule lived in ``app.js``).
"""

from __future__ import annotations

from typing import Any

from .format import color_for, fmt_bytes, initial_for
from .plan import Slot, Stage, footprint

# Fields every workshop row exposes to QML. Declared once so the models, the delegates and the
# tests cannot drift apart.
ROW_FIELDS = (
    "name",
    "size",
    "sizeText",
    "status",
    "kind",
    "movable",
    "onDevice",
    "deleted",
    "source",
    "origin",
    "iconColor",
    "initial",
    "apiLevel",
    "local",
)


class Workshop:
    """One workshop (apps or scripts) for the connected calculator."""

    def __init__(
        self,
        kind: str,
        device: list[dict],
        available: list[dict],
        capacity: int,
        *,
        enabled: bool = True,
    ):
        self.kind = kind
        self.available = list(available)
        self.capacity = capacity
        self.enabled = enabled
        self.stage = Stage(kind, device, capacity)

    # -- projections ------------------------------------------------------------------
    def device_rows(self) -> list[dict[str, Any]]:
        """One row per staged slot, in memory order, carrying its write status."""
        plan = self.stage.plan()
        return [
            self._row(
                slot.name,
                slot.size,
                status,
                movable=status in ("rw", "new"),
                on_device=slot.on_device,
                deleted=slot.deleted,
                extra=slot.extra,
            )
            for slot, status in zip(self.stage.slots, plan.status)
        ]

    def available_rows(self) -> list[dict[str, Any]]:
        """The catalogue side, marked ``staged`` for anything already in the plan."""
        staged = {s.name for s in self.stage.slots if not s.deleted}
        return [
            self._row(
                entry["name"],
                entry.get("size"),
                "staged" if entry["name"] in staged else "free",
                extra=entry,
            )
            for entry in self.available
        ]

    def plan_view(self) -> dict[str, Any]:
        """Everything the header, the memory bar and the footer need, in one map."""
        plan = self.stage.plan()
        segments = [
            {
                "w": (footprint(self.kind, slot.size) / plan.cap * 100) if plan.cap else 0,
                "status": status,
            }
            for slot, status in zip(self.stage.slots, plan.status)
            if status != "del"
        ]
        return {
            "enabled": self.enabled,
            "un": plan.un,
            "rw": plan.rw,
            "nw": plan.nw,
            "rewrite": plan.rewrite_count,
            "usedB": plan.used_b,
            "freeB": plan.free_b,
            "cap": plan.cap,
            "usedText": fmt_bytes(plan.used_b),
            "freeText": fmt_bytes(plan.free_b),
            "capText": fmt_bytes(plan.cap),
            "dirty": plan.dirty,
            "canUndo": self.stage.can_undo,
            "segments": segments,
            "deviceCount": len([s for s in self.stage.slots if not s.deleted]),
            "availCount": len(self.available),
        }

    def entry(self, name: str) -> dict | None:
        """The catalogue entry behind an available row."""
        return next((a for a in self.available if a["name"] == name), None)

    def kept_slots(self) -> list[Slot]:
        return [s for s in self.stage.slots if not s.deleted]

    # -- internals --------------------------------------------------------------------
    def _row(
        self,
        name: str,
        size: int | None,
        status: str,
        *,
        movable: bool = False,
        on_device: bool = False,
        deleted: bool = False,
        extra: dict | None = None,
    ) -> dict[str, Any]:
        extra = extra or {}
        api = extra.get("apiLevel")
        return {
            "name": name,
            "size": int(size or 0),
            "sizeText": fmt_bytes(footprint(self.kind, size)),
            "status": status,
            "kind": self.kind,
            "movable": movable,
            "onDevice": on_device,
            "deleted": deleted,
            "source": extra.get("source", "") or "",
            "origin": extra.get("origin", "") or "",
            "iconColor": color_for(name),
            "initial": initial_for(name),
            "apiLevel": -1 if api is None else int(api),
            "local": bool(extra.get("local")),
        }
