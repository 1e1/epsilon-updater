"""Install-time linking of a relocatable .nwa (nwupdater.apps.link).

All CI tests mock the nwlink subprocess — no Node, no network, no committed binaries. A single
opt-in integration test runs the real nwlink when a dev PC provides one (env-gated)."""

from __future__ import annotations

import os
import shutil
import types

import pytest

from nwupdater.apps import link
from nwupdater.apps.installer import AppCompatibilityError, validate_nwa
from nwupdater.apps.manage import AppManager
from nwupdater.dfu.identity import read_identity
from nwupdater.dfu.protocol import DfuClient
from nwupdater.formats.nwa import AppInfo, build_nwa
from nwupdater.testing.virtual_dfu import virtual_calculator

ELF_BLOB = b"\x7fELF" + b"\x00" * 60  # enough to look like a relocatable ELF (content irrelevant)
FLAT_BLOB = build_nwa("Demo", api_level=0, code=b"\x00" * 64)  # already-linked AppInfo blob


# -- detection & targets -------------------------------------------------------------------
def test_is_relocatable_detects_elf_vs_flat():
    assert link.is_relocatable_nwa(ELF_BLOB) is True
    assert link.is_relocatable_nwa(FLAT_BLOB) is False


def test_link_target_from_identity_math():
    t = link.LinkTarget.from_identity((0x90180000, 0x903F0000), (0x240117B4, 0x24037000))
    assert (t.flash_start, t.flash_length) == (0x90180000, 0x270000)
    assert (t.ram_start, t.ram_length) == (0x240117B4, 0x2584C)
    assert t.trampoline_start is None  # no userland header addr -> nwlink's offline default
    # with the UserlandHeader address, the EADK trampoline is derived (addr + magic_len + ISR)
    t3 = link.LinkTarget.from_identity(
        (0x90180000, 0x903F0000), (0x240117B4, 0x24037000), userland_header_addr=0x90010000
    )
    assert t3.trampoline_start == 0x90010000 + link.TRAMPOLINE_OFFSET_FROM_USERLAND
    # install offset shifts flash_start and shrinks the usable flash length
    t2 = link.LinkTarget.from_identity(
        (0x90180000, 0x903F0000), (0x240117B4, 0x24037000), at_offset=0x10000
    )
    assert (t2.flash_start, t2.flash_length) == (0x90190000, 0x260000)


def test_link_target_requires_both_windows():
    with pytest.raises(link.NwlinkError):
        link.LinkTarget.from_identity((0, 0), (0x240117B4, 0x24037000))
    with pytest.raises(link.NwlinkError):
        link.LinkTarget.from_identity((0x90180000, 0x903F0000), (0, 0))


# -- ensure_linked pass-through / guards ---------------------------------------------------
def test_ensure_linked_passthrough_for_flat_blob():
    # a flat blob is returned untouched, no target and no nwlink needed
    assert link.ensure_linked(FLAT_BLOB, None) is FLAT_BLOB


def test_ensure_linked_relocatable_without_target_raises():
    with pytest.raises(link.NwlinkError, match="must be linked"):
        link.ensure_linked(ELF_BLOB, None)


def test_resolve_nwlink_missing_raises(monkeypatch):
    monkeypatch.delenv("NWUPDATER_NWLINK", raising=False)
    monkeypatch.setattr(link.shutil, "which", lambda _name: None)
    with pytest.raises(link.NwlinkNotFound):
        link._resolve_nwlink(None)
    assert link.nwlink_available() is False


def test_resolve_nwlink_priority_order(monkeypatch):
    monkeypatch.delenv("NWUPDATER_NWLINK", raising=False)
    # both present -> the PINNED npx spec wins over an unknown-version PATH nwlink (deliberate)
    monkeypatch.setattr(link.shutil, "which", lambda name: "/usr/bin/" + name)
    assert link._resolve_nwlink(None) == ["npx", "--yes", link.NWLINK_SPEC]
    # npx absent -> PATH nwlink is the offline fallback
    monkeypatch.setattr(link.shutil, "which", lambda name: None if name == "npx" else "/u/nwlink")
    assert link._resolve_nwlink(None) == ["nwlink"]
    # env var overrides discovery (shell-split so it can carry args)
    monkeypatch.setenv("NWUPDATER_NWLINK", "/opt/nwlink --foo")
    assert link._resolve_nwlink(None) == ["/opt/nwlink", "--foo"]
    # explicit arg beats everything
    assert link._resolve_nwlink(["my", "nwlink"]) == ["my", "nwlink"]


# -- link_nwa with a mocked nwlink ---------------------------------------------------------
def _fake_nwlink(monkeypatch, output: bytes, capture: dict):
    """Patch subprocess.run so it emulates `nwlink nwa-bin ... IN OUT`: records argv, writes
    ``output`` to the OUT path, returns success."""

    def fake_run(argv, capture_output=True, timeout=None, cwd=None, check=False):
        capture["argv"] = argv
        with open(argv[-1], "wb") as f:  # argv[-1] == out_path
            f.write(output)
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(link.subprocess, "run", fake_run)


def test_link_nwa_builds_argv_and_returns_output(monkeypatch):
    cap: dict = {}
    _fake_nwlink(monkeypatch, FLAT_BLOB, cap)
    target = link.LinkTarget(0x90190000, 0x260000, 0x240117B4, 0x2584C)
    out = link.link_nwa(ELF_BLOB, target, nwlink_cmd=["nwlink"])
    assert out == FLAT_BLOB
    argv = cap["argv"]
    assert argv[:2] == ["nwlink", "nwa-bin"]
    # target params are passed as hex, in the CLI's expected flags
    assert "--flash-start" in argv and argv[argv.index("--flash-start") + 1] == "0x90190000"
    assert argv[argv.index("--ram-start") + 1] == "0x240117b4"
    assert argv[argv.index("--flash-length") + 1] == "0x260000"
    assert "--trampoline-start" not in argv  # this target has no trampoline -> omitted


def test_link_nwa_passes_trampoline_when_set(monkeypatch):
    cap: dict = {}
    _fake_nwlink(monkeypatch, FLAT_BLOB, cap)
    target = link.LinkTarget(0x90180000, 0x270000, 0x240117B4, 0x2584C, trampoline_start=0x9001000C)
    link.link_nwa(ELF_BLOB, target, nwlink_cmd=["nwlink"])
    argv = cap["argv"]
    assert argv[argv.index("--trampoline-start") + 1] == "0x9001000c"


def test_link_nwa_surfaces_nwlink_failure(monkeypatch):
    def fail_run(argv, **kw):
        return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(link.subprocess, "run", fail_run)
    target = link.LinkTarget(0x90180000, 0x270000, 0x240117B4, 0x2584C)
    with pytest.raises(link.NwlinkError, match="boom"):
        link.link_nwa(ELF_BLOB, target, nwlink_cmd=["nwlink"])


def test_link_nwa_rejects_non_binary_output(monkeypatch):
    cap: dict = {}
    _fake_nwlink(monkeypatch, ELF_BLOB, cap)  # nwlink "returns" an ELF again -> invalid
    target = link.LinkTarget(0x90180000, 0x270000, 0x240117B4, 0x2584C)
    with pytest.raises(link.NwlinkError, match="not a linked binary"):
        link.link_nwa(ELF_BLOB, target, nwlink_cmd=["nwlink"])


# -- validate_nwa gives an actionable error for an unlinked ELF ----------------------------
def test_validate_nwa_flags_relocatable_elf():
    with pytest.raises(AppCompatibilityError, match="relocatable ELF"):
        validate_nwa(ELF_BLOB, 0)


# -- integration through AppManager.push (virtual device + mocked nwlink) ------------------
def test_push_links_relocatable_elf_at_install_offset(monkeypatch):
    dev = virtual_calculator("n0120")
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    mgr = AppManager(
        cli,
        ident.external_apps_flash,
        device_api_level=0,
        external_apps_ram=ident.external_apps_ram,
        userland_header_addr=ident.userland_header_addr,
    )
    cap: dict = {}
    _fake_nwlink(monkeypatch, FLAT_BLOB, cap)

    m = mgr.push(ELF_BLOB)  # a relocatable ELF: must be linked, then flashed
    assert m.name == "Demo" and m.blob == FLAT_BLOB
    argv = cap["argv"]
    # linked at the region start (first app, offset 0), with the device's real RAM window
    assert argv[argv.index("--flash-start") + 1] == hex(ident.external_apps_flash[0])
    assert argv[argv.index("--ram-start") + 1] == hex(ident.external_apps_ram[0])
    # and the EADK trampoline derived from the device's UserlandHeader address (not nwlink default)
    assert argv[argv.index("--trampoline-start") + 1] == hex(
        ident.userland_header_addr + link.TRAMPOLINE_OFFSET_FROM_USERLAND
    )
    # and the linked app is actually installed on the device
    assert [a.name for a in mgr.installed()] == ["Demo"]


def test_push_second_relocatable_links_at_next_sector(monkeypatch):
    """A second app is appended after the first (sector-aligned), so it must be LINKED at
    region_start + first-app-sectors*SECTOR, not at the region start."""
    from nwupdater.apps.manage import SECTOR

    dev = virtual_calculator("n0120")
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    mgr = AppManager(
        cli,
        ident.external_apps_flash,
        device_api_level=0,
        external_apps_ram=ident.external_apps_ram,
        userland_header_addr=ident.userland_header_addr,
    )
    mgr.push(FLAT_BLOB)  # first app: flat, no link, occupies 1 sector
    linked2 = build_nwa("Second", api_level=0, code=b"\x00" * 64)
    cap: dict = {}
    _fake_nwlink(monkeypatch, linked2, cap)
    mgr.push(ELF_BLOB)  # second app: relocatable -> linked at the append offset
    argv = cap["argv"]
    assert argv[argv.index("--flash-start") + 1] == hex(ident.external_apps_flash[0] + SECTOR)
    assert [a.name for a in mgr.installed()] == ["Demo", "Second"]


def test_push_relocatable_without_ram_window_raises(monkeypatch):
    """No external-apps RAM window (older/other model) -> a relocatable ELF cannot be linked;
    the failure is clear rather than a confusing AppInfo-magic error."""
    dev = virtual_calculator("n0120")
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    mgr = AppManager(cli, ident.external_apps_flash, device_api_level=0)  # no external_apps_ram
    called = []
    monkeypatch.setattr(link.subprocess, "run", lambda *a, **k: called.append(a))
    with pytest.raises(link.NwlinkError, match="must be linked"):
        mgr.push(ELF_BLOB)
    assert not called  # never even tried to shell out


def test_push_flat_blob_never_shells_out(monkeypatch):
    """A pre-linked/synthetic blob installs without invoking nwlink at all."""
    dev = virtual_calculator("n0120")
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    mgr = AppManager(
        cli,
        ident.external_apps_flash,
        device_api_level=0,
        external_apps_ram=ident.external_apps_ram,
        userland_header_addr=ident.userland_header_addr,
    )
    called = []
    monkeypatch.setattr(link.subprocess, "run", lambda *a, **k: called.append(a))
    mgr.push(FLAT_BLOB)
    assert not called and [a.name for a in mgr.installed()] == ["Demo"]


def test_link_nwa_timeout_raises(monkeypatch):
    def timeout_run(argv, **kw):
        raise link.subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(link.subprocess, "run", timeout_run)
    target = link.LinkTarget(0x90180000, 0x270000, 0x240117B4, 0x2584C)
    with pytest.raises(link.NwlinkError, match="timed out"):
        link.link_nwa(ELF_BLOB, target, nwlink_cmd=["nwlink"], timeout=0.01)


def test_link_nwa_missing_binary_at_run_raises(monkeypatch):
    def enoent_run(argv, **kw):
        raise FileNotFoundError(2, "No such file", argv[0])

    monkeypatch.setattr(link.subprocess, "run", enoent_run)
    target = link.LinkTarget(0x90180000, 0x270000, 0x240117B4, 0x2584C)
    with pytest.raises(link.NwlinkNotFound):
        link.link_nwa(ELF_BLOB, target, nwlink_cmd=["nwlink"])


# -- trampoline sanity guard (Rec 2) ------------------------------------------------------
def test_trampoline_word_looks_valid():
    assert link.trampoline_word_looks_valid(0x900F3D45)  # external-flash Thumb ptr (real value)
    assert link.trampoline_word_looks_valid(0x08001235)  # internal-flash Thumb ptr
    assert not link.trampoline_word_looks_valid(0x00000000)  # empty flash (the 1st bad value)
    assert not link.trampoline_word_looks_valid(0x240064A4)  # RAM data addr, even (2nd bad value)
    assert not link.trampoline_word_looks_valid(0x90020038)  # in flash but even -> not a code ptr
    assert not link.trampoline_word_looks_valid(0xFFFFFFFF)


def test_push_rejects_bad_trampoline(monkeypatch):
    """If the derived trampoline doesn't point at a code table, refuse BEFORE shelling out —
    catching exactly the mis-derived-trampoline reboot we hit during bring-up."""
    dev = virtual_calculator("n0120")
    cli = DfuClient(dev, sleep=lambda *_: None)
    ident = read_identity(cli, dev.bcdDevice)
    tramp = ident.userland_header_addr + link.TRAMPOLINE_OFFSET_FROM_USERLAND
    dev.memory.write(tramp, b"\x00\x00\x00\x00")  # corrupt: now points at empty flash
    mgr = AppManager(
        cli,
        ident.external_apps_flash,
        device_api_level=0,
        external_apps_ram=ident.external_apps_ram,
        userland_header_addr=ident.userland_header_addr,
    )
    called = []
    monkeypatch.setattr(link.subprocess, "run", lambda *a, **k: called.append(a))
    with pytest.raises(link.NwlinkError, match="trampoline"):
        mgr.push(ELF_BLOB)
    assert not called  # rejected before any nwlink invocation


@pytest.mark.skipif(
    not (os.environ.get("NWUPDATER_TEST_NWA") and (shutil.which("nwlink") or shutil.which("npx"))),
    reason="dev-PC only: set NWUPDATER_TEST_NWA=<path to a real .nwa> and have nwlink/npx",
)
def test_real_nwlink_link_produces_valid_appinfo():
    with open(os.environ["NWUPDATER_TEST_NWA"], "rb") as f:
        blob = f.read()
    assert link.is_relocatable_nwa(blob)
    target = link.LinkTarget.from_identity((0x90180000, 0x903F0000), (0x240117B4, 0x24037000))
    out = link.link_nwa(blob, target)
    info = AppInfo.parse(out)
    assert info.valid and info.app_size > 0  # nwlink output passes our installer's validation
