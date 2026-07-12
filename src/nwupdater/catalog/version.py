"""NumWorks firmware version parsing & comparison.

Versions are dotted-numeric ("25.2.0", "16.4.4", "1.1.0"). We parse into a tuple of ints
and compare like the on-device ``KernelHeader::softwareVersionComparedTo`` (numeric,
component-wise). Unparseable components degrade gracefully to 0 so a stray build tag never
crashes the comparison.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+")


def parse_version(v: str) -> tuple[int, ...]:
    """'25.2.0' -> (25, 2, 0). Robust to spaces/nulls and non-numeric tails."""
    parts = str(v).strip().strip("\x00").split(".")
    out: list[int] = []
    for p in parts:
        m = _NUM.search(p)
        out.append(int(m.group()) if m else 0)
    # drop trailing zeros so (25,2,0) == (25,2)
    while len(out) > 1 and out[-1] == 0:
        out.pop()
    return tuple(out)


def compare(a: str, b: str) -> int:
    """-1 if a<b, 0 if equal, 1 if a>b (numeric, component-wise)."""
    pa, pb = parse_version(a), parse_version(b)
    n = max(len(pa), len(pb))
    pa += (0,) * (n - len(pa))
    pb += (0,) * (n - len(pb))
    return (pa > pb) - (pa < pb)


def is_newer(candidate: str, current: str) -> bool:
    return compare(candidate, current) > 0
