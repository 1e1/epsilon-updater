"""Display formatting for the native UI — pure functions, no Qt, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone

# Stable per-name accent for an app tile, mirroring the web UI's APPCOLORS.
APP_COLORS = (
    "#e8735a",
    "#7d6ce0",
    "#e05a8c",
    "#2fa8a0",
    "#5a8fe0",
    "#d9a13b",
    "#5aab5e",
)


def color_for(name: str) -> str:
    """A deterministic tile colour for an app, keyed on its first character."""
    return APP_COLORS[(ord(name[0]) if name else 0) % len(APP_COLORS)]


def initial_for(name: str) -> str:
    return (name[:1] or "?").upper()


def fmt_bytes(n: int | None) -> str:
    """Kio/Mio in the calculator's own idiom (binary units, as Epsilon reports them)."""
    n = int(n or 0)
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} Mio".replace(".0 ", " ")
    if n >= 1024:
        return f"{n / 1024:.0f} Kio"
    return f"{n} o"


def fmt_relative(iso: str | None, *, now: datetime | None = None) -> str:
    """Coarse "how long ago", the granularity the roster's last-scan column needs.

    ``now`` is injectable so the behaviour is testable without freezing the clock.
    """
    if not iso:
        return "—"
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return "—"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = ((now or datetime.now(timezone.utc)) - then).total_seconds()
    if seconds < 90:
        return "à l'instant"
    if seconds < 5400:
        return f"il y a {round(seconds / 60)} min"
    if seconds < 129600:
        return f"il y a {round(seconds / 3600)} h"
    return f"il y a {round(seconds / 86400)} j"
