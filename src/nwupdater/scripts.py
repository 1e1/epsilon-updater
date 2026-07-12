"""Read / write the Python scripts storage over DFU (SRAM zone m_storageAddressRAM).

Uses the transport-agnostic ``DfuClient`` (same code for the virtual device and, in
production, real hardware). Reading is non-destructive (UPLOAD only). Writing mutates the
running OS's RAM store, so callers gate it behind explicit confirmation (like a flash).
See docs/01-specs/scripts-and-device-pairing.md §3.
"""

from __future__ import annotations

from .formats import storage as S
from .formats.storage import Record


def read_storage(client, addr: int, size: int) -> list[Record]:
    """UPLOAD the storage zone and parse it. ``+8`` covers the magic + terminator margin.

    An uninitialized store (no magic — a fresh/rescue device) reads as an empty list.
    """
    blob = client.read(addr, size + 8)
    return S.parse_storage(blob) if S.has_storage(blob) else []


def write_storage(client, addr: int, records: list[Record], *, capacity: int) -> int:
    """Re-encode the whole store and DNLOAD it (SRAM → no erase). Returns bytes written."""
    blob = S.encode_storage(records, capacity=capacity)
    client.write(addr, blob, erase=False)
    return len(blob)
