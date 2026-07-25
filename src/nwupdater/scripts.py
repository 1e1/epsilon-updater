"""Read / write the Python scripts storage over DFU (SRAM zone m_storageAddressRAM).

Uses the transport-agnostic ``DfuClient`` (same code for the virtual device and, in
production, real hardware). Reading is non-destructive (UPLOAD only). Writing mutates the
running OS's RAM store, so callers gate it behind explicit confirmation (like a flash).
See docs/01-specs/scripts-and-device-pairing.md §3.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from .formats import storage as S
from .formats.storage import Record


def bundled_scripts() -> list[dict]:
    """Load the bundled community-scripts catalogue (``data/community-scripts.json``).

    Mirrors :meth:`nwupdater.apps.store.AppStore.bundled` (importlib.resources with a filesystem
    fallback). An EMPTY list is expected: there is no official public scripts API, so the real
    sources are the user's own files + ``_urls.txt`` under the user scripts dir.
    """
    try:
        raw = resources.files("nwupdater").joinpath("data/community-scripts.json").read_text()
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        raw = (Path(__file__).parent / "data" / "community-scripts.json").read_text()
    data = json.loads(raw)
    return list(data.get("scripts", []))


class StorageWriteError(RuntimeError):
    """The storage write did not land (read-back mismatch)."""


def read_storage(client, addr: int, size: int) -> list[Record]:
    """UPLOAD the storage zone and parse it. ``+8`` covers the magic + terminator margin.

    An uninitialized store (no magic — a fresh/rescue device) reads as an empty list.
    """
    blob = client.read(addr, size + 8)
    return S.parse_storage(blob) if S.has_storage(blob) else []


def write_storage(client, addr: int, records: list[Record], *, capacity: int) -> int:
    """Re-encode the whole store and DNLOAD it (SRAM → no erase). Returns bytes written.

    The storage lives in SRAM, exposed as its own DFU alt-setting; ``client.write`` routes to it
    by address. A DNLOAD aimed at the wrong backend (no SRAM alt selected) is silently ignored on
    real hardware, so we **verify by read-back** and raise rather than pretend success.
    """
    blob = S.encode_storage(records, capacity=capacity)
    client.write(addr, blob, erase=False)
    if client.read(addr, len(blob)) != blob:
        raise StorageWriteError(
            "storage read-back mismatch — the calculator did not accept the write "
            "(is the SRAM alt-setting reachable?)"
        )
    return len(blob)
