"""DfuSe memory-layout descriptor parsing (the DFU interface ``iInterface`` string).

The bootloader advertises its real — possibly non-uniform — flash sector geometry in a
string of the form::

    @Flash/0x90000000/08*004Kg,01*032Kg,63*064Kg/0x90430000/61*064Kg

``@Name`` followed by repeating ``/0xADDR/seg,seg,…`` groups; each segment is
``<count>*<size><multiplier><access>`` (multiplier ``K``/``M``/blank, access ``a``/``e``/``g``).
This is the same format read by the reference host tools (``get_memory_layout`` /
``parseMemoryDescriptor``). See docs/01-specs/usb-dfu-protocol.md §6.4.

Why the host needs it: a DfuSe *erase* wipes the **whole sector** containing the given
address. The host must therefore erase each sector once, aligned to its boundary — never
once per transfer chunk. Sectors are 4–128 KiB while a transfer chunk is 2048 B, so a
per-chunk erase re-wipes the sector and destroys data already written into it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# <count>*<size><multiplier><access>, e.g. "08*004Kg". Multiplier optional (blank/space = bytes).
_SEG_RE = re.compile(r"^(\d+)\*(\d+)([KkMmBb ]?)([aeg])$")
_MULT = {"": 1, " ": 1, "b": 1, "k": 1024, "m": 1024 * 1024}


@dataclass(frozen=True)
class Region:
    """A contiguous run of ``count`` equal-sized sectors starting at ``base``."""

    base: int
    sector_size: int
    count: int

    @property
    def end(self) -> int:
        return self.base + self.sector_size * self.count


class MemoryLayout:
    def __init__(self, regions: list[Region]):
        self.regions = sorted(regions, key=lambda r: r.base)

    def __repr__(self) -> str:
        segs = ", ".join(f"0x{r.base:08x}:{r.count}x{r.sector_size}" for r in self.regions)
        return f"MemoryLayout({segs})"

    def sector_of(self, address: int) -> tuple[int, int] | None:
        """``(base, size)`` of the sector containing ``address``, or None if unmapped."""
        for r in self.regions:
            if r.base <= address < r.end:
                i = (address - r.base) // r.sector_size
                return r.base + i * r.sector_size, r.sector_size
        return None

    def sectors_covering(self, start: int, length: int) -> list[int]:
        """Ascending, de-duplicated sector base addresses whose sector overlaps
        ``[start, start+length)``. Empty if the range hits no mapped sector."""
        if length <= 0:
            return []
        end = start + length
        out: set[int] = set()
        for r in self.regions:
            lo = max(start, r.base)
            hi = min(end, r.end)
            if lo >= hi:
                continue
            first = (lo - r.base) // r.sector_size
            last = (hi - 1 - r.base) // r.sector_size
            for i in range(first, last + 1):
                out.add(r.base + i * r.sector_size)
        return sorted(out)


def parse_memory_layout(descriptor: str | None) -> MemoryLayout | None:
    """Parse a DfuSe ``iInterface`` layout string into a :class:`MemoryLayout`.

    Returns None if ``descriptor`` is empty or not a layout string (does not start with
    ``@``). Raises ValueError on a malformed segment inside an otherwise well-formed one.
    """
    if not descriptor or not descriptor.startswith("@"):
        return None
    parts = descriptor.split("/")
    # parts[0] is "@Name"; the rest are (address, segment-list) pairs.
    regions: list[Region] = []
    i = 1
    while i < len(parts):
        addr_tok = parts[i].strip()
        seglist = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2
        if not addr_tok:
            continue
        base = int(addr_tok, 16)  # accepts the "0x" prefix
        cursor = base
        for seg in seglist.split(","):
            m = _SEG_RE.match(seg.strip())
            if not m:
                raise ValueError(f"bad layout segment {seg!r} in {descriptor!r}")
            count = int(m.group(1))
            size = int(m.group(2)) * _MULT[m.group(3).lower()]
            regions.append(Region(cursor, size, count))
            cursor += size * count
    return MemoryLayout(regions) if regions else None
