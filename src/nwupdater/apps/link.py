"""Install-time linking of a distributed ``.nwa`` via ``nwlink`` (offline).

A ``.nwa`` published as a release asset is an ARM **relocatable** ELF (``ET_REL``), not the flat
``0xDEC0BEBA`` AppInfo blob the calculator runs. It becomes runnable only after a *link* against
the target's flash/RAM addresses — and that link needs NumWorks' EADK runtime (``_start`` plus
the ``eadk_*`` / newlib stubs), which ships **only inside ``nwlink``**. So we delegate just the
link to ``nwlink nwa-bin``, run **offline** with the target params epsilon-updater already
resolves over DFU (the external-apps flash window + the external-apps RAM window), then flash the
result with our own DFU engine (:mod:`nwupdater.apps.installer`).

Runtime dependency
------------------
Linking a relocatable ``.nwa`` REQUIRES ``nwlink`` (a Node package) — there is no pure-Python
substitute because the link needs NumWorks' compiled EADK runtime, which ships only inside
``nwlink``. This is a **Node/npm dependency outside the Python package** (see the note in
``pyproject.toml``). It is used lazily and only for relocatable ELFs; pre-linked ``.nwa`` blobs
never touch it. Resolution order (see :func:`_resolve_nwlink`): an explicit command, then the
``NWUPDATER_NWLINK`` env var, then the pinned ``npx nwlink@<spec>`` (byte-exact/reproducible;
first run fetches from npm), then a bare ``nwlink`` on PATH as an offline fallback.

Design notes
------------
* This is the ONLY path that shells out. It is invoked lazily — only when a blob is a relocatable
  ELF. A blob that already carries the AppInfo magic (pre-linked, or our synthetic test blobs) is
  returned untouched, so nothing here runs in dev/tests without opting in.
* ``nwlink`` is deterministic, so the linked output is byte-for-byte what the official web
  uploader produces for the same target params. The version is pinned for reproducibility.
* The flash address the app is linked at is its **actual install address**
  (``region_start + at_offset``), because external apps run in place (XIP) from flash.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from ..dfu import constants as C

# Pinned so the link is reproducible (and matches the byte-exact oracle we validated against).
NWLINK_SPEC = "nwlink@0.0.19"

# A linked/flat .nwa starts with the AppInfo magic 0xDEC0BEBA (LE: BA BE C0 DE); a distributed
# one starts with the ELF magic. We only need to link the latter.
_ELF_MAGIC = b"\x7fELF"

# The EADK trampoline (the OS-resident dispatch table the app's stubs point at) sits just past
# the UserlandHeader + its ISR area. nwlink's `install-nwa` computes it from the CONNECTED device
# as `userlandHeaderAddress + h + magic_len + UserlandISRSize`, where `h` is where its
# parseUserlandHeader stops = the footer-magic offset = (header_size - magic_len). So the two
# magic_len terms cancel and the offset is simply `header_size + UserlandISRSize`. nwa-bin's
# default (0x90010030) is a static placeholder matching NO real device, so we MUST pass the
# device-derived value or the app dereferences a bad API pointer and reboots on launch.
# NB: this encodes the Epsilon userland ABI (full 48-byte header + an 8-byte ISR area) — the same
# layout headers.UserlandHeader.unpack requires; a device whose header doesn't match won't parse,
# so we never reach here with a mismatched layout. Constants live in dfu.constants (single source).
TRAMPOLINE_OFFSET_FROM_USERLAND = C.USERLAND_HEADER_SIZE + C.USERLAND_ISR_SIZE  # 0x30 + 8 = 0x38


class NwlinkError(RuntimeError):
    """A link via nwlink failed (with an actionable, human-facing message)."""


class NwlinkNotFound(NwlinkError):
    """Neither a ``nwlink`` binary nor ``npx`` is available to perform the link."""


def is_relocatable_nwa(blob: bytes) -> bool:
    """True if ``blob`` is an un-linked (relocatable ELF) ``.nwa`` that must be linked first."""
    return blob[:4] == _ELF_MAGIC


def trampoline_word_looks_valid(word: int) -> bool:
    """Sanity-check the first word read at the computed EADK trampoline: it must be a **Thumb code
    pointer into flash** (internal ``0x08xxxxxx`` or external QSPI ``0x90xxxxxx``). This is the
    cheap guard against a mis-derived trampoline — whose only symptom is a silent reboot on launch.
    The bad values observed while getting the offset right were ``0x00000000`` (empty flash) and a
    RAM *data* address (even); both are rejected here, the correct one (a Thumb fn ptr) passes."""
    if word in (0, 0xFFFFFFFF) or not (word & 1):  # 0/-1 or non-Thumb (even) -> not a code ptr
        return False
    return (0x08000000 <= word < 0x08200000) or (0x90000000 <= word < 0x90800000)


@dataclass(frozen=True)
class LinkTarget:
    """Where the app will live on the device, resolved from the calculator identity over DFU.

    ``flash_start`` is the app's final install address (region start + install offset). The
    ``*_length`` values bound the linker's flash/RAM regions; ``ram_start``/``ram_length`` come
    from the UserlandHeader's external-apps RAM window (see :mod:`nwupdater.formats.headers`)."""

    flash_start: int
    flash_length: int
    ram_start: int
    ram_length: int
    trampoline_start: int | None = None  # device-derived; None -> nwlink's (offline) default

    @classmethod
    def from_identity(
        cls,
        external_apps_flash: tuple[int, int],
        external_apps_ram: tuple[int, int],
        *,
        at_offset: int = 0,
        userland_header_addr: int | None = None,
    ) -> LinkTarget:
        fs, fe = external_apps_flash
        rs, re = external_apps_ram
        if not (fe > fs) or not (re > rs):
            raise NwlinkError(
                "device did not report both an external-apps flash region and RAM window; "
                "cannot link (is this a model with third-party apps?)"
            )
        return cls(
            flash_start=fs + at_offset,
            flash_length=fe - fs - at_offset,
            ram_start=rs,
            ram_length=re - rs,
            trampoline_start=(
                userland_header_addr + TRAMPOLINE_OFFSET_FROM_USERLAND
                if userland_header_addr
                else None
            ),
        )


def _resolve_nwlink(nwlink_cmd: list[str] | None) -> list[str]:
    """The argv prefix that runs nwlink, in priority order:

    1. an explicit ``nwlink_cmd`` (callers / tests);
    2. the ``NWUPDATER_NWLINK`` env var (operator override, e.g. a pinned local install), split
       shell-style so it can carry args;
    3. ``npx --yes nwlink@<pinned>`` — the DEFAULT: the exact version this module was validated
       against, so the link stays byte-exact/reproducible (first run fetches it from npm);
    4. a bare ``nwlink`` on PATH — offline fallback ONLY when ``npx`` is absent; its version is
       NOT pinned, so byte-for-byte reproducibility is not guaranteed.

    Preferring the pinned spec over an unknown-version PATH ``nwlink`` is deliberate. Raises
    :class:`NwlinkNotFound` if none is available."""
    if nwlink_cmd:
        return list(nwlink_cmd)
    env = os.environ.get("NWUPDATER_NWLINK")
    if env:
        return shlex.split(env)
    if shutil.which("npx"):
        return ["npx", "--yes", NWLINK_SPEC]
    if shutil.which("nwlink"):
        return ["nwlink"]
    raise NwlinkNotFound(
        "linking a distributed .nwa needs nwlink (Node).\n"
        "  • install Node.js, then either rely on `npx` or `npm i -g nwlink`,\n"
        "  • or point NWUPDATER_NWLINK at an nwlink command,\n"
        f"  • or run the link yourself: `npx {NWLINK_SPEC} install-nwa <file>`."
    )


def nwlink_available() -> bool:
    """True if a way to run nwlink is available (for a caller to preflight before doing work)."""
    try:
        _resolve_nwlink(None)
        return True
    except NwlinkNotFound:
        return False


def link_nwa(
    blob: bytes,
    target: LinkTarget,
    *,
    nwlink_cmd: list[str] | None = None,
    timeout: float = 180.0,
) -> bytes:
    """Link a relocatable ``.nwa`` ``blob`` for ``target`` and return the flat, flashable ``.bin``.

    Runs ``nwlink nwa-bin`` offline (no device). Raises :class:`NwlinkError` (or the
    :class:`NwlinkNotFound` subclass) with a helpful message on any failure."""
    argv0 = _resolve_nwlink(nwlink_cmd)
    with tempfile.TemporaryDirectory(prefix="nwlink-") as td:
        in_path = os.path.join(td, "app.nwa")
        out_path = os.path.join(td, "app.bin")
        with open(in_path, "wb") as f:
            f.write(blob)
        argv = [
            *argv0,
            "nwa-bin",
            "--flash-start",
            hex(target.flash_start),
            "--flash-length",
            hex(target.flash_length),
            "--ram-start",
            hex(target.ram_start),
            "--ram-length",
            hex(target.ram_length),
            *(
                ["--trampoline-start", hex(target.trampoline_start)]
                if target.trampoline_start is not None
                else []
            ),
            in_path,
            out_path,
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=td, check=False)
        except FileNotFoundError as exc:  # the resolved command vanished between which() and run()
            raise NwlinkNotFound(f"cannot run {argv0[0]}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise NwlinkError(f"nwlink timed out after {timeout:g}s") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
            raise NwlinkError(f"nwlink nwa-bin failed (exit {proc.returncode}): {err}")
        try:
            with open(out_path, "rb") as f:
                out = f.read()
        except OSError as exc:
            raise NwlinkError(f"nwlink produced no output: {exc}") from exc
    if not out or is_relocatable_nwa(out):
        raise NwlinkError("nwlink output is empty or not a linked binary")
    return out


def ensure_linked(
    blob: bytes,
    target: LinkTarget | None,
    *,
    nwlink_cmd: list[str] | None = None,
) -> bytes:
    """Return a flashable ``.nwa``: link ``blob`` if it is a relocatable ELF, else return it as-is.

    ``target`` may be ``None`` when the caller has no device context; in that case an un-linked
    blob raises (there is nothing to link against), while an already-linked blob passes through."""
    if not is_relocatable_nwa(blob):
        return blob
    if target is None:
        raise NwlinkError(
            "this .nwa is a relocatable ELF and must be linked to the device's flash/RAM "
            "addresses, but no target was resolved (connect a calculator)."
        )
    return link_nwa(blob, target, nwlink_cmd=nwlink_cmd)
