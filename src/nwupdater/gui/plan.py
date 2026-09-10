"""Memory write plan and staging — pure Python, no Qt, no UI.

Ported from the staging logic that lived in ``server/web/app.js`` so the rule that decides
what actually gets rewritten has ONE implementation, testable without a browser. The web UI
keeps its own copy for now; the invariants below are the contract between the two.

Rule: the *frozen prefix* is the longest run of kept items still matching the device's memory
order — nothing there is rewritten. From the first divergence on, every item is (re)written, so
its order is the user's to arrange.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

APP_SECTOR = 65536  # apps occupy whole 64 KiB flash sectors; scripts pack byte-for-byte


def footprint(kind: str, size: int | None) -> int:
    """Bytes an item really costs on the device (apps are sector-rounded, scripts are not)."""
    b = int(size or 0)
    if kind != "apps":
        return b
    return -(-b // APP_SECTOR) * APP_SECTOR if b > 0 else 0


@dataclass(frozen=True)
class Slot:
    name: str
    size: int = 0
    on_device: bool = False
    deleted: bool = False
    extra: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Plan:
    frozen: int
    status: tuple[str, ...]  # one of "un" | "rw" | "new" | "del", positional with the slots
    un: int
    rw: int
    nw: int
    used_b: int
    free_b: int
    cap: int
    dirty: bool

    @property
    def rewrite_count(self) -> int:
        return self.rw + self.nw


def plan_for(kind: str, device: list[dict], slots: list[Slot], capacity: int) -> Plan:
    dnames = [d.get("name") for d in device]
    target = [s for s in slots if not s.deleted]
    frozen = 0
    while frozen < len(target) and frozen < len(device) and target[frozen].name == dnames[frozen]:
        frozen += 1
    status: list[str] = []
    ti = 0
    for s in slots:
        if s.deleted:
            status.append("del")
            continue
        status.append("un" if ti < frozen else ("rw" if s.name in dnames else "new"))
        ti += 1
    un = rw = nw = 0
    used_b = 0
    for s, st in zip(slots, status):
        if st == "del":
            continue
        b = footprint(kind, s.size)
        used_b += b
        un, rw, nw = (
            (un + 1, rw, nw)
            if st == "un"
            else ((un, rw + 1, nw) if st == "rw" else (un, rw, nw + 1))
        )
    return Plan(
        frozen=frozen,
        status=tuple(status),
        un=un,
        rw=rw,
        nw=nw,
        used_b=used_b,
        free_b=max(0, capacity - used_b),
        cap=capacity,
        dirty=[s.name for s in target] != dnames,
    )


class Stage:
    """The user's pending arrangement of one workshop, with an undo history."""

    def __init__(self, kind: str, device: list[dict], capacity: int):
        self.kind = kind
        self.capacity = capacity
        self.device = list(device)
        self.slots: list[Slot] = []
        self._hist: list[list[Slot]] = []
        self.reset()

    # -- history --------------------------------------------------------------------
    def _push(self) -> None:
        self._hist.append(list(self.slots))

    @property
    def can_undo(self) -> bool:
        return bool(self._hist)

    def undo(self) -> None:
        if self._hist:
            self.slots = self._hist.pop()

    def reset(self) -> None:
        self.slots = [
            Slot(name=d.get("name", ""), size=int(d.get("size") or 0), on_device=True, extra=d)
            for d in self.device
        ]
        self._hist = []

    # -- edits ----------------------------------------------------------------------
    def add(self, name: str, size: int, extra: dict | None = None) -> bool:
        """Re-arm a slot staged for deletion, or append a new one. False if already staged."""
        for i, s in enumerate(self.slots):
            if s.name == name:
                if not s.deleted:
                    return False
                self._push()
                self.slots[i] = replace(s, deleted=False)
                return True
        self._push()
        self.slots.append(Slot(name=name, size=size, on_device=False, extra=extra or {}))
        return True

    def remove(self, name: str) -> None:
        """Mark for erase if it is on the device (stays visible, struck through), else drop it."""
        for i, s in enumerate(self.slots):
            if s.name == name:
                self._push()
                if s.on_device:
                    self.slots[i] = replace(s, deleted=True)
                else:
                    del self.slots[i]
                return

    def restore(self, name: str) -> None:
        for i, s in enumerate(self.slots):
            if s.name == name and s.deleted:
                self._push()
                self.slots[i] = replace(s, deleted=False)
                return

    def move(self, name: str, direction: int) -> None:
        """Step one slot through the WRITABLE region, skipping frozen ones.

        Up/down walk the list of rewritable slots rather than raw positions: a frozen prefix
        item is never displaced, and an item does not get stuck behind one either. Same rule as
        the web workshop, so a plan built in either front-end writes the same bytes.
        """
        plan = self.plan()
        movable = [i for i, st in enumerate(plan.status) if st in ("rw", "new")]
        position = next(
            (i for i, s in enumerate(self.slots) if s.name == name and not s.deleted), -1
        )
        if position < 0 or position not in movable:
            return
        target_rank = movable.index(position) + direction
        if not 0 <= target_rank < len(movable):
            return
        self._push()
        other = movable[target_rank]
        self.slots[position], self.slots[other] = self.slots[other], self.slots[position]

    def minimize(self) -> None:
        """Drop everything not already on the device, and un-delete the rest — the smallest
        write that reaches a clean state."""
        self._push()
        self.slots = [replace(s, deleted=False) for s in self.slots if s.on_device]

    # -- read -----------------------------------------------------------------------
    def plan(self) -> Plan:
        return plan_for(self.kind, self.device, self.slots, self.capacity)
