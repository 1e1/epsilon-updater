"""Manage the third-party apps installed in the external-apps flash region.

Apps are laid out from the region start, each **sector-aligned** (64 KiB); the OS iterator
stops at the first sector without the AppInfo magic. So we read-modify-write only the changed
**suffix** (``regions.plan``): appending is prefix-free, while a middle uninstall or a reorder
rewrites from the first change. When the app list shrinks, the boundary sector is cleared so a
stale magic can't make the OS see ghost apps. Every write is verified by read-back.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..dfu import constants as C
from ..dfu.protocol import DfuClient
from ..formats.nwa import AppInfo, iter_apps
from ..install.installer import VerificationError
from ..regions import PlanItem, plan

SECTOR = C.EXTERNAL_APP_SECTOR  # external-apps sector unit (Board::Config::ExternalAppsSectorUnit)


class AppError(RuntimeError):
    pass


@dataclass
class ManagedApp:
    name: str
    api_level: int
    blob: bytes

    @property
    def sectors(self) -> int:
        return max(1, (len(self.blob) + SECTOR - 1) // SECTOR)


def _sectors(n: int) -> int:
    return max(1, (n + SECTOR - 1) // SECTOR)


def _digest(b: bytes) -> str:
    return hashlib.sha1(b, usedforsecurity=False).hexdigest()[:12]


class AppManager:
    """Read/modify/write the external-apps region with minimal rewrites."""

    def __init__(self, client: DfuClient, region: tuple[int, int] | None,
                 *, device_api_level: int = 0):
        self.client = client
        self.start, self.end = region or (0, 0)
        self.capacity = max(0, self.end - self.start)
        self.device_api_level = device_api_level

    def installed(self) -> list[ManagedApp]:
        if self.capacity <= 0:
            return []
        blob = self.client.read(self.start, self.capacity)
        apps = []
        for a in iter_apps(blob):
            size = a.info.app_size or 0
            apps.append(ManagedApp(a.info.name or "?", a.info.api_level,
                                   blob[a.offset:a.offset + size]))
        return apps

    def push(self, blob: bytes) -> ManagedApp:
        info = AppInfo.parse(blob)
        if not info.valid:
            raise AppError("not a valid .nwa (bad AppInfo magic)")
        if info.api_level != self.device_api_level:
            raise AppError(f"API level {info.api_level} != device {self.device_api_level}")
        target = [m.blob for m in self.installed()] + [blob]
        self._apply(target)
        return ManagedApp(info.name or "?", info.api_level, blob)

    def uninstall(self, name: str) -> None:
        current = self.installed()
        if not any(m.name == name for m in current):
            raise AppError(f"app not installed: {name}")
        self._apply([m.blob for m in current if m.name != name])

    def reorder(self, order: list[str]) -> None:
        by_name = {m.name: m.blob for m in self.installed()}
        unknown = [n for n in order if n not in by_name]
        if unknown:
            raise AppError(f"unknown app(s): {', '.join(unknown)}")
        if sorted(order) != sorted(by_name):
            raise AppError("reorder must list every installed app exactly once")
        self._apply([by_name[n] for n in order])

    def _apply(self, target: list[bytes]) -> None:
        current = self.installed()
        cur_items = [PlanItem(_digest(m.blob), len(m.blob)) for m in current]
        tgt_items = [PlanItem(_digest(b), len(b)) for b in target]
        p = plan(cur_items, tgt_items, capacity=self.capacity, sector=SECTOR)
        if not p.fits:
            need = sum(_sectors(len(b)) for b in target) * SECTOR
            raise AppError(f"not enough space: need {need} B, region is {self.capacity} B")

        offsets, off = [], 0
        for b in target:
            offsets.append(off)
            off += _sectors(len(b)) * SECTOR
        new_end = off
        old_end = sum(m.sectors * SECTOR for m in current)

        # erase the changed span (sector by sector) so writes land clean and stale magics die.
        # The erase unit is the 64 KiB app sector, not the 2048-byte transfer chunk: a DfuSe
        # erase wipes the whole containing sector, so stepping by the chunk size would re-issue
        # 32 redundant ERASE commands per sector (extra flash wear, slow).
        erase_from = offsets[p.first_changed] if p.first_changed < len(offsets) else new_end
        addr = self.start + erase_from
        end = self.start + max(old_end, new_end)
        while addr < end:
            self.client.erase_page(addr)
            addr += SECTOR

        for i in range(p.first_changed, len(target)):
            at = self.start + offsets[i]
            self.client.write(at, target[i], erase=False)
            if self.client.read(at, len(target[i])) != target[i]:
                raise VerificationError(f"read-back mismatch @0x{at:08x}")
