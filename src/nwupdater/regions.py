"""Generic write planner: rewrite only the part of a device region that changed.

A region holds an ordered list of named items — third-party apps in the QSPI external-apps
zone, or script records in the SRAM storage. The device is never left inconsistent: the
longest identical **prefix** is untouched, and only the **suffix** from the first divergence
is rewritten (read-modify-write). For flash, the erase granularity is a sector and items are
sector-aligned; for the packed SRAM storage there is no sector (``sector=None``).

This is the Python port of the mock's write-plan engine — see
docs/reference/official-webusb-analysis.md and docs/01-specs/scripts-and-device-pairing.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class PlanItem:
    id: str
    size: int  # bytes


@dataclass(frozen=True)
class WritePlan:
    first_changed: int  # index in target of the first divergence (= unchanged prefix length)
    rewrite: list[str]  # ids rewritten = target[first_changed:]
    write_bytes: int  # bytes written (sector-rounded for flash)
    erase_bytes: int  # bytes erased (flash only; 0 for packed SRAM)
    fits: bool  # does the target fit within capacity?

    @property
    def unchanged(self) -> int:
        return self.first_changed


def _footprint(size: int, sector: int | None) -> int:
    return ceil(size / sector) * sector if sector else size


def plan(
    current: list[PlanItem], target: list[PlanItem], *, capacity: int, sector: int | None = None
) -> WritePlan:
    """Compute the minimal-rewrite plan turning ``current`` (on device) into ``target``.

    ``first_changed`` is the first index where the ids differ (a missing item counts as a
    difference), so append is prefix-free and a middle delete/insert cascades from that point.
    """
    n = max(len(current), len(target))
    first_changed = len(target)
    for i in range(n):
        c = current[i].id if i < len(current) else None
        t = target[i].id if i < len(target) else None
        if c != t:
            first_changed = i
            break

    rewrite = target[first_changed:]
    write_bytes = sum(_footprint(it.size, sector) for it in rewrite)
    total = sum(_footprint(it.size, sector) for it in target)

    if sector:
        prefix_end = sum(_footprint(it.size, sector) for it in target[:first_changed])
        old_end = sum(_footprint(it.size, sector) for it in current)
        new_end = total
        erase_bytes = max(0, max(old_end, new_end) - prefix_end)
    else:
        erase_bytes = 0

    return WritePlan(
        first_changed, [it.id for it in rewrite], write_bytes, erase_bytes, total <= capacity
    )
