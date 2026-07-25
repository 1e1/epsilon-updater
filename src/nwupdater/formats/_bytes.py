"""Shared byte helpers for the on-flash struct formats (single source of truth).

Kept in one place so the fixed-width ASCII field encode/decode logic is not copied across
headers.py / platform_info.py.
"""

from __future__ import annotations


def cstr(raw: bytes) -> str:
    """Decode a NUL-terminated ASCII field, trimming trailing NULs and surrounding blanks."""
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def fixed(s: str, n: int) -> bytes:
    """Encode ``s`` as exactly ``n`` ASCII bytes, NUL-padded (or truncated to ``n``)."""
    return s.encode("ascii", "replace")[:n].ljust(n, b"\x00")
