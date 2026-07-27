"""Pure-Python .nwa linker (nwupdater.formats.nwa_linker, strategy C').

Links a distributed relocatable-ELF ``.nwa`` against our embedded clean-room EADK runtime with
no Node and no toolchain. The CI tests build a tiny synthetic app ELF in-process (no committed
binary) and link it against the SHIPPED runtime blob; a dev-PC-only test cross-checks a real app
against the nwlink oracle when clang + nwlink are available."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile

import pytest

from nwupdater.dfu import constants as C
from nwupdater.formats import nwa_link as L
from nwupdater.formats.nwa import AppInfo
from nwupdater.formats.nwa_linker import LinkError, PureLinker, link_nwa_pure

# device params used throughout (a plausible N0120 slot-A window)
FS, FL, RS, RL, TS = 0x90180000, 0x270000, 0x240117B4, 0x2584C, 0x90020038


def _min_app(name: bytes = b"T\x00") -> bytes:
    """A minimal but valid ARM ET_REL '.nwa': a `main` that `bl`s an undefined `eadk_random`,
    plus the KEEP sections (name/icon/api_level). Exercises cross-object linking + placement."""
    # section name string table
    names = [
        b"",
        b".text.main",
        b".rel.text.main",
        b".rodata.eadk_app_name",
        b".rodata.eadk_app_icon",
        b".rodata.eadk_api_level",
        b".symtab",
        b".strtab",
        b".shstrtab",
    ]
    shstr = b"\x00" + b"".join(n + b"\x00" for n in names if n)

    def nameoff(n: bytes) -> int:
        return shstr.index(n + b"\x00") if n else 0

    strtab = b"\x00main\x00eadk_random\x00"
    text = struct.pack("<HH", *L._thumb_bl_encode(0xF000, 0xF800, -4))  # a fresh `bl` (addend -4)
    icon = b"\x01\x02\x03\x04"
    apilv = struct.pack("<I", 0)
    namesec = name + b"\x00" * ((4 - len(name) % 4) % 4)

    # symbols: null, main (GLOBAL FUNC @ .text.main sec 1), eadk_random (GLOBAL UND)
    sym = struct.pack("<IIIBBH", 0, 0, 0, 0, 0, 0)
    sym += struct.pack("<IIIBBH", strtab.index(b"main"), 0, 0, (1 << 4) | 2, 0, 1)
    sym += struct.pack("<IIIBBH", strtab.index(b"eadk_random"), 0, 0, (1 << 4) | 0, 0, 0)
    rel = struct.pack("<II", 0, (2 << 8) | L.R_ARM_THM_CALL)  # site 0, sym #2, THM_CALL

    payloads = [b"", text, rel, namesec, icon, apilv, sym, strtab, shstr]
    off = 52
    offsets = []
    for p in payloads:
        offsets.append(off if p else 0)
        off += len(p)
    shoff = off

    def sh(nm, typ, flags, idx, size, link, info, align, ent):
        return struct.pack(
            "<IIIIIIIIII", nameoff(nm), typ, flags, 0, offsets[idx], size, link, info, align, ent
        )

    A, X = L.SHF_ALLOC, L.SHF_EXECINSTR
    shdrs = b"".join(
        [
            sh(b"", 0, 0, 0, 0, 0, 0, 0, 0),
            sh(b".text.main", L.SHT_PROGBITS, A | X, 1, len(text), 0, 0, 2, 0),
            sh(
                b".rel.text.main", L.SHT_REL, 0, 2, len(rel), 6, 1, 4, 8
            ),  # link symtab(6) info text(1)
            sh(b".rodata.eadk_app_name", L.SHT_PROGBITS, A, 3, len(namesec), 0, 0, 1, 0),
            sh(b".rodata.eadk_app_icon", L.SHT_PROGBITS, A, 4, len(icon), 0, 0, 1, 0),
            sh(b".rodata.eadk_api_level", L.SHT_PROGBITS, A, 5, len(apilv), 0, 0, 4, 0),
            sh(b".symtab", L.SHT_SYMTAB, 0, 6, len(sym), 7, 1, 4, 16),  # link strtab(7)
            sh(b".strtab", L.SHT_STRTAB, 0, 7, len(strtab), 0, 0, 1, 0),
            sh(b".shstrtab", L.SHT_STRTAB, 0, 8, len(shstr), 0, 0, 1, 0),
        ]
    )
    ehdr = struct.pack(
        "<16sHHIIIIIHHHHHH",
        b"\x7fELF\x01\x01\x01" + b"\x00" * 9,
        L.ET_REL,
        L.EM_ARM,
        1,
        0,
        0,
        shoff,
        0,
        52,
        0,
        0,
        40,
        9,
        8,
    )
    return ehdr + b"".join(payloads) + shdrs


def test_links_synthetic_app_against_embedded_runtime():
    out = link_nwa_pure(
        _min_app(name=b"T\x00"),
        flash_start=FS,
        flash_length=FL,
        ram_start=RS,
        ram_length=RL,
        trampoline_start=TS,
    )
    info = AppInfo.parse(out)
    assert info.valid and info.name == "T"
    magic0, _api, name_off, icon_sz, icon_off, entry, app_size, magic1 = struct.unpack_from(
        "<IIIIIIII", out, 0
    )
    assert magic0 == magic1 == C.MAGIC_EXTERNAL_APP
    assert name_off == 0x20  # name right after the 32-byte header
    assert icon_sz == 4 and 0 < icon_off < app_size
    assert 0 < entry < app_size  # entry points into the image (our _start)


def test_entry_points_at_start_and_calls_main():
    """The AppInfo entry must be our crt0 (`_start`); the app's `bl eadk_random` must reach the
    runtime's svc-0x2d stub (cross-object resolution + THM_CALL relocation)."""
    app = _min_app()
    lk = PureLinker(FS, FL, RS, RL, TS)
    out = lk.link(app, _load_rt())
    entry = struct.unpack_from("<I", out, 0x14)[0]
    # _start global should resolve to ORIGIN+entry (Thumb bit stripped)
    from nwupdater.formats.nwa_linker import _collect_globals, _Objects

    objs = _Objects(L.Elf32.parse(app), L.Elf32.parse(_load_rt()))
    _collect_globals(objs)
    oid, s = objs.globals_["_start"]
    start = lk._sec_vma[(oid, s.shndx)] + s.value
    assert (start & ~1) - FS == entry
    # the runtime's eadk_random stub must be present: svc #0x2d encodes as the bytes 2d df
    assert b"\x2d\xdf" in out


def test_requires_trampoline():
    with pytest.raises(LinkError):
        link_nwa_pure(
            _min_app(),
            flash_start=FS,
            flash_length=FL,
            ram_start=RS,
            ram_length=RL,
            trampoline_start=None,
        )


def test_rejects_garbage():
    with pytest.raises(LinkError):
        link_nwa_pure(
            b"not an elf",
            flash_start=FS,
            flash_length=FL,
            ram_start=RS,
            ram_length=RL,
            trampoline_start=TS,
        )


def _load_rt() -> bytes:
    from nwupdater.formats.nwa_linker import _load_runtime

    return _load_runtime()


# -- dev-PC cross-check vs the nwlink oracle (needs clang + nwlink + a real .nwa) -------------
@pytest.mark.skipif(
    not (os.environ.get("NWUPDATER_TEST_NWA") and shutil.which("npx")),
    reason="dev-PC only: set NWUPDATER_TEST_NWA=<real .nwa> and have npx (nwlink) available",
)
def test_appinfo_matches_nwlink_oracle():
    """Our AppInfo header (magic/api/name/icon) must match nwlink's for the same app+params.
    entry/app_size legitimately differ (we are not byte-exact — different runtime placement)."""
    with open(os.environ["NWUPDATER_TEST_NWA"], "rb") as f:
        blob = f.read()
    mine = link_nwa_pure(
        blob, flash_start=FS, flash_length=FL, ram_start=RS, ram_length=RL, trampoline_start=TS
    )
    with tempfile.TemporaryDirectory() as td:
        inp, outp = f"{td}/a.nwa", f"{td}/a.bin"
        with open(inp, "wb") as g:
            g.write(blob)
        subprocess.run(
            [
                "npx",
                "--yes",
                "nwlink@0.0.19",
                "nwa-bin",
                "-fs",
                hex(FS),
                "-fl",
                hex(FL),
                "-rs",
                hex(RS),
                "-rl",
                hex(RL),
                "-ts",
                hex(TS),
                inp,
                outp,
            ],
            check=True,
            capture_output=True,
        )
        with open(outp, "rb") as h:
            gold = h.read()
    m, g = struct.unpack_from("<IIIIIIII", mine, 0), struct.unpack_from("<IIIIIIII", gold, 0)
    assert m[0] == g[0] == C.MAGIC_EXTERNAL_APP  # magic
    assert m[1] == g[1]  # api_level
    assert m[2] == g[2]  # name offset
    assert m[3] == g[3]  # icon size
    assert AppInfo.parse(mine).name == AppInfo.parse(gold).name
