"""Install-time linker: a distributed ``.nwa`` (an ARM **relocatable** ELF, ``ET_REL``) is not
yet the flat ``0xDEC0BEBA`` AppInfo blob the calculator runs — it becomes one only after a
*link* against the target's flash/RAM addresses (see ``docs`` + the ``formats/nwa.py`` header).

**Status — foundation, not the shipped path.** The install path that actually ships
(:mod:`nwupdater.apps.link`) *delegates* the link to ``nwlink`` (offline), because a faithful
byte-exact link needs NumWorks' compiled EADK runtime (``_start`` + the ``eadk_*`` / newlib
stubs) which lives only inside ``nwlink`` and cannot be regenerated in Python. This module is the
pure-Python **groundwork** for a future no-Node linker: a self-contained ELF32 reader and an ARM
``REL`` relocation engine, both unit-tested. It is deliberately NOT wired into the install path
(the working delegation must not depend on it). Completing it would additionally require placement
matching lld's linker script and vendoring the EADK runtime bytes — out of scope here.

This file is the ELF32 reader + relocation engine the rest of a linker would build on: it parses
the section table, symbol table and ARM ``REL`` relocation tables of a little-endian ARM ``ET_REL``
object, and applies the AAELF ``REL`` relocations a real ``.nwa`` carries (ABS32, REL32, THM_CALL,
THM_JUMP24, PREL31). Only what a linker needs is decoded — not a general-purpose ELF library.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass, field

# -- ELF identification --------------------------------------------------------------------
ELFMAG = b"\x7fELF"
ELFCLASS32 = 1
ELFDATA2LSB = 1
ET_REL = 1
EM_ARM = 40

# -- section header types (sh_type) --------------------------------------------------------
SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHT_NOBITS = 8
SHT_REL = 9
SHT_ARM_EXIDX = 0x70000001

# -- section header flags (sh_flags) -------------------------------------------------------
SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4
SHF_MERGE = 0x10
SHF_STRINGS = 0x20

# -- symbol table st_info fields -----------------------------------------------------------
STB_LOCAL = 0
STB_GLOBAL = 1
STB_WEAK = 2
STT_NOTYPE = 0
STT_OBJECT = 1
STT_FUNC = 2
STT_SECTION = 3
STT_FILE = 4

# special section indices
SHN_UNDEF = 0
SHN_ABS = 0xFFF1
SHN_COMMON = 0xFFF2

# -- ARM relocation types (ELF for the ARM Architecture, "AAELF") --------------------------
R_ARM_NONE = 0
R_ARM_ABS32 = 2
R_ARM_REL32 = 3
R_ARM_THM_CALL = 10
R_ARM_THM_JUMP24 = 30
R_ARM_TARGET1 = 38
R_ARM_PREL31 = 42

_EHDR = struct.Struct("<16sHHIIIIIHHHHHH")  # e_ident + 13 half/word fields
_SHDR = struct.Struct("<IIIIIIIIII")  # 10 words
_SYM = struct.Struct("<IIIBBH")  # st_name,st_value,st_size,st_info,st_other,st_shndx
_REL = struct.Struct("<II")  # r_offset, r_info


class ElfError(ValueError):
    pass


@dataclass
class Section:
    index: int
    name: str
    sh_type: int
    flags: int
    addr: int
    offset: int
    size: int
    link: int
    info: int
    addralign: int
    entsize: int
    data: bytes  # raw bytes (empty for SHT_NOBITS)

    @property
    def alloc(self) -> bool:
        return bool(self.flags & SHF_ALLOC)

    @property
    def is_nobits(self) -> bool:
        return self.sh_type == SHT_NOBITS


@dataclass
class Symbol:
    name: str
    value: int
    size: int
    info: int
    other: int
    shndx: int

    @property
    def bind(self) -> int:
        return self.info >> 4

    @property
    def type(self) -> int:
        return self.info & 0xF

    @property
    def defined(self) -> bool:
        return self.shndx not in (SHN_UNDEF,)


@dataclass
class Reloc:
    offset: int  # byte offset within the section being relocated
    sym: int  # symbol table index
    type: int  # R_ARM_*


@dataclass
class Elf32:
    """A parsed little-endian ARM ``ET_REL`` object."""

    e_type: int
    e_machine: int
    e_entry: int
    sections: list[Section]
    symbols: list[Symbol]
    # relocations keyed by the index of the section they apply to (sh_info of the REL section)
    relocs: dict[int, list[Reloc]] = field(default_factory=dict)
    _symstr_index: int = 0

    @classmethod
    def parse(cls, blob: bytes) -> Elf32:
        if blob[:4] != ELFMAG:
            raise ElfError("not an ELF file (bad magic)")
        if blob[4] != ELFCLASS32 or blob[5] != ELFDATA2LSB:
            raise ElfError("only little-endian ELF32 is supported (NumWorks is 32-bit ARM LE)")
        (
            _ident,
            e_type,
            e_machine,
            _e_version,
            e_entry,
            _e_phoff,
            e_shoff,
            _e_flags,
            _e_ehsize,
            _e_phentsize,
            _e_phnum,
            e_shentsize,
            e_shnum,
            e_shstrndx,
        ) = _EHDR.unpack_from(blob, 0)
        if e_machine != EM_ARM:
            raise ElfError(f"not an ARM object (e_machine={e_machine})")
        if e_shentsize != _SHDR.size:
            raise ElfError(f"unexpected section header size {e_shentsize}")

        # -- section headers --
        raw: list[tuple] = []
        for i in range(e_shnum):
            raw.append(_SHDR.unpack_from(blob, e_shoff + i * e_shentsize))
        # section-header string table gives every section its name
        shstr_off = raw[e_shstrndx][4]
        shstr_size = raw[e_shstrndx][5]
        shstr = blob[shstr_off : shstr_off + shstr_size]

        def _name(tab: bytes, off: int) -> str:
            end = tab.find(b"\x00", off)
            return tab[off:end].decode("ascii", "replace")

        sections: list[Section] = []
        for i, (nameoff, styp, flags, addr, offset, size, link, info, align, ent) in enumerate(raw):
            data = b"" if styp == SHT_NOBITS else blob[offset : offset + size]
            sections.append(
                Section(
                    i,
                    _name(shstr, nameoff),
                    styp,
                    flags,
                    addr,
                    offset,
                    size,
                    link,
                    info,
                    align,
                    ent,
                    data,
                )
            )

        # -- symbol table (first SHT_SYMTAB) --
        symbols: list[Symbol] = []
        symstr_index = 0
        for s in sections:
            if s.sh_type == SHT_SYMTAB:
                symstr_index = s.link
                symstr = sections[s.link].data
                n = s.size // _SYM.size
                for k in range(n):
                    st_name, st_value, st_size, st_info, st_other, st_shndx = _SYM.unpack_from(
                        s.data, k * _SYM.size
                    )
                    symbols.append(
                        Symbol(
                            _name(symstr, st_name), st_value, st_size, st_info, st_other, st_shndx
                        )
                    )
                break

        # -- relocation tables (REL only; ARM uses implicit in-place addends) --
        relocs: dict[int, list[Reloc]] = {}
        for s in sections:
            if s.sh_type == SHT_REL:
                target = s.info  # section these relocations apply to
                lst: list[Reloc] = []
                for k in range(s.size // _REL.size):
                    r_offset, r_info = _REL.unpack_from(s.data, k * _REL.size)
                    lst.append(Reloc(r_offset, r_info >> 8, r_info & 0xFF))
                relocs[target] = lst
            elif s.sh_type == SHT_RELA:
                raise ElfError("RELA relocations are unexpected for ARM ET_REL (.nwa uses REL)")

        return cls(e_type, e_machine, e_entry, sections, symbols, relocs, symstr_index)

    # -- convenience lookups ---------------------------------------------------------------
    def section(self, name: str) -> Section | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def alloc_sections(self) -> list[Section]:
        return [s for s in self.sections if s.alloc]


# ==========================================================================================
# ARM relocation engine (host-side: pure integer/bit math over `bytes`; NO ARM is executed).
#
# The values patched are ARM **Thumb-2** machine code destined for the calculator's Cortex-M.
# We reproduce the subset of the "ELF for the ARM Architecture" (AAELF) REL relocations that a
# real distributed .nwa actually carries — verified counts on RPN v2.0.0:
#   THM_CALL 1662, ABS32 396, THM_JUMP24 47, PREL31 4  (REL32 only in the discarded .eh_frame).
# REL semantics: the addend A is read *in place* from the field (there is no explicit addend).
# ==========================================================================================


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _thumb_bl_decode_addend(hw1: int, hw2: int) -> int:
    """Decode the signed branch displacement already encoded in a Thumb BL/B.W (T1/T4)."""
    s = (hw1 >> 10) & 1
    imm10 = hw1 & 0x3FF
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1
    imm11 = hw2 & 0x7FF
    i1 = (~(j1 ^ s)) & 1
    i2 = (~(j2 ^ s)) & 1
    value = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
    return _sign_extend(value, 25)


def _thumb_bl_encode(hw1: int, hw2: int, disp: int) -> tuple[int, int]:
    """Re-encode a signed displacement into a Thumb BL/B.W, preserving the opcode bits."""
    if disp & 1:
        raise ElfError(f"odd Thumb branch displacement {disp:#x}")
    v = disp & 0x1FFFFFF  # 25-bit
    s = (v >> 24) & 1
    i1 = (v >> 23) & 1
    i2 = (v >> 22) & 1
    imm10 = (v >> 12) & 0x3FF
    imm11 = (v >> 1) & 0x7FF
    j1 = (~i1 & 1) ^ s
    j2 = (~i2 & 1) ^ s
    hw1 = (hw1 & 0xF800) | (s << 10) | imm10
    hw2 = (hw2 & 0xD000) | (j1 << 13) | (j2 << 11) | imm11
    return hw1, hw2


@dataclass
class RelocContext:
    """Everything a relocation needs: the final address of the site's section, and a resolver
    that maps an input symbol index to its final value (with the Thumb bit folded in for
    Thumb-function targets, exactly as lld does)."""

    section_addr: int  # final VMA of the section being relocated
    resolve: Callable[[int], int]  # symbol index -> final address (Thumb bit applied)


def apply_relocations(data: bytes, relocs: list[Reloc], ctx: RelocContext) -> bytes:
    """Return ``data`` with ``relocs`` applied in place. ``data`` is one section's bytes,
    laid at ``ctx.section_addr``. Raises on an unsupported relocation type."""
    buf = bytearray(data)
    for r in relocs:
        if r.type == R_ARM_NONE:
            continue
        P = ctx.section_addr + r.offset  # address of the relocation site
        # The resolver returns the symbol value with bit0=1 for Thumb functions (AAELF "T").
        # ABS32 keeps T (function pointers must be odd for BX); branch/PREL31 targets are even.
        S = ctx.resolve(r.sym)
        Se = S & ~1
        o = r.offset
        if r.type == R_ARM_ABS32:
            A = int.from_bytes(buf[o : o + 4], "little")
            buf[o : o + 4] = ((S + A) & 0xFFFFFFFF).to_bytes(4, "little")
        elif r.type == R_ARM_REL32:
            A = int.from_bytes(buf[o : o + 4], "little")
            buf[o : o + 4] = ((Se + A - P) & 0xFFFFFFFF).to_bytes(4, "little")
        elif r.type == R_ARM_PREL31:
            raw = int.from_bytes(buf[o : o + 4], "little")
            A = _sign_extend(raw & 0x7FFFFFFF, 31)
            val = (Se + A - P) & 0x7FFFFFFF
            buf[o : o + 4] = ((raw & 0x80000000) | val).to_bytes(4, "little")
        elif r.type in (R_ARM_THM_CALL, R_ARM_THM_JUMP24):
            hw1 = int.from_bytes(buf[o : o + 2], "little")
            hw2 = int.from_bytes(buf[o + 2 : o + 4], "little")
            A = _thumb_bl_decode_addend(hw1, hw2)
            disp = (Se + A - P) & 0xFFFFFFFF
            disp = _sign_extend(disp, 32)
            nhw1, nhw2 = _thumb_bl_encode(hw1, hw2, disp)
            buf[o : o + 2] = nhw1.to_bytes(2, "little")
            buf[o + 2 : o + 4] = nhw2.to_bytes(2, "little")
        else:
            raise ElfError(f"unsupported relocation type {r.type}")
    return bytes(buf)
