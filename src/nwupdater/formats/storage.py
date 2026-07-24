"""NumWorks Python scripts storage (Ion ``FileSystem``) — parse & re-encode. Pure, no USB.

Layout [epsilon shared/ion/.../storage/file_system.{h,cpp}, cross-checked with the official
``Storage.js`` — see docs/reference/official-webusb-analysis.md]::

    | MAGIC (u32 LE 0xEE0BDDBA) | Record1 | Record2 | … | 0x0000 |
    Record = | Size (u16 LE, total incl. these 2 bytes) | FullName + \\0 | Body |

A Python (``.py``) Body is ``| Status (1 byte; bit0 = autoImportation) | Content (\\0-terminated)``.
End of store = a ``Size == 0`` word (NOT a second magic). Total bound: 42 KiB.

Non-``.py`` records (system prefs, etc.) are preserved verbatim so a re-write never drops them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..dfu import constants as C

PY_EXT = "py"


class StorageError(RuntimeError):
    """Malformed storage buffer, or content exceeding the 42 KiB bound."""


@dataclass
class Record:
    """One file-system record. ``body`` is kept raw so non-Python records round-trip."""

    fullname: str  # e.g. "mandelbrot.py"
    body: bytes

    @property
    def is_python(self) -> bool:
        return "." in self.fullname and self.fullname.rsplit(".", 1)[-1] == PY_EXT

    @property
    def auto_import(self) -> bool:
        # bit0 of the Status byte; default 1 for a new script (Script() constructor).
        return self.is_python and bool(self.body) and bool(self.body[0] & 1)

    @property
    def code(self) -> str:
        if not self.is_python or not self.body:
            return ""
        return self.body[1:].split(b"\x00", 1)[0].decode("utf-8", "replace")


def make_python(name: str, code: str, auto_import: bool = True) -> Record:
    """Build a ``.py`` record (Status byte + \\0-terminated content)."""
    fullname = name if name.endswith("." + PY_EXT) else f"{name}.{PY_EXT}"
    body = bytes([0x01 if auto_import else 0x00]) + code.encode("utf-8") + b"\x00"
    return Record(fullname, body)


def has_storage(blob: bytes) -> bool:
    """True if the buffer begins with the storage magic (an initialized store)."""
    return len(blob) >= 4 and struct.unpack_from("<I", blob, 0)[0] == C.MAGIC_STORAGE


def parse_storage(blob: bytes) -> list[Record]:
    if len(blob) < 4 or struct.unpack_from("<I", blob, 0)[0] != C.MAGIC_STORAGE:
        raise StorageError("storage magic not found (expected 0xEE0BDDBA)")
    records: list[Record] = []
    off = 4
    while off + 2 <= len(blob):
        (size,) = struct.unpack_from("<H", blob, off)
        if size == 0:  # terminator
            break
        if size < 3 or off + size > len(blob):
            raise StorageError(f"corrupt record at offset {off} (size={size})")
        try:
            name_end = blob.index(b"\x00", off + 2, off + size)
        except ValueError:
            raise StorageError(f"unterminated name in record at offset {off}") from None
        fullname = blob[off + 2 : name_end].decode("ascii", "replace")
        records.append(Record(fullname, blob[name_end + 1 : off + size]))
        off += size
    return records


def encode_storage(records: list[Record], *, capacity: int = C.STORAGE_TOTAL_SIZE) -> bytes:
    out = bytearray(struct.pack("<I", C.MAGIC_STORAGE))
    for r in records:
        name = r.fullname.encode("ascii", "replace") + b"\x00"
        size = 2 + len(name) + len(r.body)
        if size > 0xFFFF:
            raise StorageError(f"record '{r.fullname}' too large ({size} B)")
        out += struct.pack("<H", size) + name + r.body
    out += b"\x00\x00"  # terminator (Size == 0)
    if len(out) > capacity:
        raise StorageError(f"storage {len(out)} B exceeds capacity {capacity} B")
    return bytes(out)


def python_scripts(records: list[Record]) -> list[Record]:
    return [r for r in records if r.is_python]
