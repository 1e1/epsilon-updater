"""Pure-Python ELF32 reader + ARM REL relocation engine (nwupdater.formats.nwa_link).

This module is the groundwork for a future no-Node linker; it is NOT wired into the shipped
install path (that delegates to nwlink — see nwupdater.apps.link). These tests pin the
correctness-critical, hand-rolled parts: the Thumb-2 branch bit-math and the AAELF REL
relocations. A minimal synthetic ELF exercises the reader with no committed binary; an opt-in
env-gated test parses a real .nwa."""

from __future__ import annotations

import os
import struct

import pytest

from nwupdater.formats import nwa_link as L


# -- relocation engine (bit math) ----------------------------------------------------------
@pytest.mark.parametrize("disp", [4, -4, 0x100, -0x100, 0x00FFFFFE, -0x01000000, 0x2A])
def test_thumb_bl_encode_decode_roundtrip(disp):
    # Even, signed displacement round-trips exactly (decode is sign-extended over the 25-bit field).
    hw1, hw2 = L._thumb_bl_encode(0xF000, 0xF800, disp)
    assert L._thumb_bl_decode_addend(hw1, hw2) == disp


def test_apply_abs32_adds_symbol_to_addend():
    data = struct.pack("<I", 0x10)  # in-place addend A = 0x10
    relocs = [L.Reloc(offset=0, sym=1, type=L.R_ARM_ABS32)]
    ctx = L.RelocContext(section_addr=0x90180000, resolve=lambda _s: 0x90020039)  # Thumb (odd)
    out = L.apply_relocations(data, relocs, ctx)
    # ABS32 keeps the Thumb bit (function pointers stay odd): S + A
    assert struct.unpack("<I", out)[0] == (0x90020039 + 0x10) & 0xFFFFFFFF


def test_apply_rel32_is_pc_relative():
    data = struct.pack("<I", 0)  # addend 0
    relocs = [L.Reloc(offset=0, sym=1, type=L.R_ARM_REL32)]
    ctx = L.RelocContext(section_addr=0x1000, resolve=lambda _s: 0x2001)  # even target after &~1
    out = L.apply_relocations(data, relocs, ctx)
    # (S&~1) + A - P, P = section_addr + offset = 0x1000
    assert struct.unpack("<I", out)[0] == (0x2000 - 0x1000) & 0xFFFFFFFF


def test_apply_prel31_masks_top_bit():
    data = struct.pack("<I", 0x80000000)  # top bit set in the field must be preserved
    relocs = [L.Reloc(offset=0, sym=1, type=L.R_ARM_PREL31)]
    ctx = L.RelocContext(section_addr=0x1000, resolve=lambda _s: 0x1100)
    out = L.apply_relocations(data, relocs, ctx)
    word = struct.unpack("<I", out)[0]
    assert word & 0x80000000  # preserved
    assert (word & 0x7FFFFFFF) == (0x1100 - 0x1000) & 0x7FFFFFFF


def test_apply_thm_call_encodes_reachable_target():
    # A *fresh* Thumb BL carries addend -4 (absorbs the PC+4 pipeline offset). After relocating
    # to a Thumb target, the CPU (PC = site + 4) must land exactly on the target.
    site = struct.pack("<HH", *L._thumb_bl_encode(0xF000, 0xF800, -4))
    P = 0x90181000
    target = 0x90182345  # Thumb (odd)
    relocs = [L.Reloc(offset=0, sym=1, type=L.R_ARM_THM_CALL)]
    ctx = L.RelocContext(section_addr=P, resolve=lambda _s: target)
    out = L.apply_relocations(site, relocs, ctx)
    hw1, hw2 = struct.unpack("<HH", out)
    disp = L._thumb_bl_decode_addend(hw1, hw2)
    assert P + 4 + disp == (target & ~1)  # Thumb BL is relative to PC (= site + 4)


def test_unsupported_relocation_raises():
    with pytest.raises(L.ElfError):
        L.apply_relocations(
            b"\x00\x00\x00\x00", [L.Reloc(0, 1, 99)], L.RelocContext(0, lambda _s: 0)
        )


@pytest.mark.parametrize("imm", [0, 0x1234, 0xFFFF, 0xABCD, 0x8000])
def test_thumb_movw_movt_imm_roundtrip(imm):
    hw1, hw2 = L._thumb_movw_movt_encode(0xF240, 0x0000, imm)  # movw r0, #imm base
    assert L._thumb_movw_movt_decode(hw1, hw2) == imm


def test_apply_movw_movt_loads_split_absolute_address():
    # movw r0,#0 / movt r0,#0 with ABS_NC + ABS relocs must reconstruct S (Thumb bit kept in bit0).
    movw = struct.pack("<HH", 0xF240, 0x0000)
    movt = struct.pack("<HH", 0xF2C0, 0x0000)
    S = 0x9018ABCD  # Thumb function pointer (odd)
    ctx = L.RelocContext(section_addr=0, resolve=lambda _s: S)
    lo_ins = L.apply_relocations(movw, [L.Reloc(0, 1, L.R_ARM_THM_MOVW_ABS_NC)], ctx)
    hi_ins = L.apply_relocations(movt, [L.Reloc(0, 1, L.R_ARM_THM_MOVT_ABS)], ctx)
    lo = L._thumb_movw_movt_decode(*struct.unpack("<HH", lo_ins))
    hi = L._thumb_movw_movt_decode(*struct.unpack("<HH", hi_ins))
    assert (hi << 16) | lo == S


def test_apply_target1_is_abs32():
    data = struct.pack("<I", 0x8)
    ctx = L.RelocContext(section_addr=0x1000, resolve=lambda _s: 0x90180001)
    out = L.apply_relocations(data, [L.Reloc(0, 1, L.R_ARM_TARGET1)], ctx)
    assert struct.unpack("<I", out)[0] == (0x90180001 + 0x8) & 0xFFFFFFFF


# -- ELF32 reader (synthetic minimal ARM ET_REL) -------------------------------------------
def _min_elf() -> bytes:
    """A tiny but valid little-endian ARM ET_REL: .text + .rel.text (one ABS32 to 'foo') +
    .symtab/.strtab/.shstrtab. Enough to exercise every branch of Elf32.parse."""
    shstr = b"\x00.text\x00.rel.text\x00.symtab\x00.strtab\x00.shstrtab\x00"
    n_text, n_rel, n_sym, n_str, n_shstr = (
        shstr.index(s) for s in (b".text", b".rel.text", b".symtab", b".strtab", b".shstrtab")
    )
    strtab = b"\x00foo\x00"
    text = struct.pack("<I", 0)  # ABS32 relocation site, addend 0
    sym = struct.pack("<IIIBBH", 0, 0, 0, 0, 0, 0)  # null symbol
    sym += struct.pack("<IIIBBH", 1, 0x1234, 0, (1 << 4) | 2, 0, 1)  # foo: GLOBAL FUNC in .text(1)
    rel = struct.pack("<II", 0, (1 << 8) | L.R_ARM_ABS32)  # r_offset=0, sym=1, ABS32

    blobs = [b"", text, rel, sym, strtab, shstr]  # section [i] payload (NULL section has none)
    off = 52  # after the ELF header
    offsets = []
    for b in blobs:
        offsets.append(off if b else 0)
        off += len(b)
    shoff = off

    def sh(name, typ, flags, addr, idx, size, link, info, align, ent):
        return struct.pack(
            "<IIIIIIIIII", name, typ, flags, addr, offsets[idx], size, link, info, align, ent
        )

    shdrs = b"".join(
        [
            sh(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),  # NULL
            sh(n_text, L.SHT_PROGBITS, L.SHF_ALLOC | L.SHF_EXECINSTR, 0, 1, len(text), 0, 0, 4, 0),
            sh(n_rel, L.SHT_REL, 0, 0, 2, len(rel), 3, 1, 4, 8),  # link=symtab(3), info=.text(1)
            sh(n_sym, L.SHT_SYMTAB, 0, 0, 3, len(sym), 4, 1, 4, 16),  # link=strtab(4)
            sh(n_str, L.SHT_STRTAB, 0, 0, 4, len(strtab), 0, 0, 1, 0),
            sh(n_shstr, L.SHT_STRTAB, 0, 0, 5, len(shstr), 0, 0, 1, 0),
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
        6,
        5,  # shstrndx
    )
    return ehdr + b"".join(blobs) + shdrs


def test_parse_minimal_elf():
    elf = L.Elf32.parse(_min_elf())
    assert elf.e_type == L.ET_REL and elf.e_machine == L.EM_ARM
    assert elf.section(".text") is not None and elf.section(".text").size == 4
    names = {s.name for s in elf.alloc_sections()}
    assert ".text" in names
    # symbols: null + foo
    foo = next(s for s in elf.symbols if s.name == "foo")
    assert foo.value == 0x1234 and foo.defined and foo.type == L.STT_FUNC
    # relocations keyed by the target section index (.text == 1), one ABS32 to sym 1
    text_idx = elf.section(".text").index
    assert elf.relocs[text_idx] == [L.Reloc(offset=0, sym=1, type=L.R_ARM_ABS32)]


def test_parse_rejects_non_arm_or_bad_magic():
    with pytest.raises(L.ElfError):
        L.Elf32.parse(b"not an elf")
    bad = bytearray(_min_elf())
    bad[18] = 0  # e_machine -> 0 (not ARM)
    with pytest.raises(L.ElfError):
        L.Elf32.parse(bytes(bad))


@pytest.mark.skipif(
    not os.environ.get("NWUPDATER_TEST_NWA"), reason="dev-PC only: set NWUPDATER_TEST_NWA=<.nwa>"
)
def test_parse_real_nwa_reader():
    with open(os.environ["NWUPDATER_TEST_NWA"], "rb") as f:
        elf = L.Elf32.parse(f.read())
    assert elf.e_type == L.ET_REL and elf.e_machine == L.EM_ARM
    types = {r.type for lst in elf.relocs.values() for r in lst}
    assert types <= {
        L.R_ARM_ABS32,
        L.R_ARM_REL32,
        L.R_ARM_THM_CALL,
        L.R_ARM_THM_JUMP24,
        L.R_ARM_PREL31,
        L.R_ARM_NONE,
        L.R_ARM_TARGET1,
    }  # only types we handle/expect
