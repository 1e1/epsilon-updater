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


def relative_key(iso: str | None, *, now: datetime | None = None) -> tuple[str, int]:
    """Coarse "how long ago" as an ``(i18n key, count)`` pair, NOT a rendered string.

    The web UI hands this to ``Intl.RelativeTimeFormat(LANG)``; the native one hands the pair to
    ``i18n.t(key, {n})`` in QML. Returning the pair rather than a sentence is what makes the
    roster's last-scan column follow a language switch: the QML binding re-evaluates on its own,
    with no row re-projection and no i18n dependency down here.

    ``now`` is injectable so the behaviour is testable without freezing the clock.
    """
    if not iso:
        return ("rel_never", 0)
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ("rel_never", 0)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = ((now or datetime.now(timezone.utc)) - then).total_seconds()
    if seconds < 90:
        return ("rel_now", 0)
    if seconds < 5400:
        return ("rel_min", round(seconds / 60))
    if seconds < 129600:
        return ("rel_hour", round(seconds / 3600))
    return ("rel_day", round(seconds / 86400))
