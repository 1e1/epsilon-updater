"""Pure-Python install-time linker for distributed ``.nwa`` apps (strategy C', no Node).

A distributed ``.nwa`` is an ARM ``ET_REL`` object that references ``_start`` (crt0) and the
``eadk_*`` / newlib symbols without defining them. This module links it against our own
**clean-room** EADK runtime (:mod:`nwupdater.formats.eadk_runtime` → the embedded object in
:mod:`nwupdater.formats._eadk_runtime`) at the device's flash/RAM addresses, producing the flat
``0xDEC0BEBA`` AppInfo blob the calculator runs — **without** ``nwlink``/Node and without
redistributing any NumWorks runtime byte.

It reuses the ELF32 reader + ARM ``REL`` relocation engine in :mod:`nwupdater.formats.nwa_link`,
and mirrors nwlink's linker-script layout closely enough for the OS to accept the image (AppInfo
header → name → icon → ``.text`` → ``.rodata`` → ``.data`` LMA → ``.bss``/heap in RAM). It does
**not** aim for byte-exactness with nwlink (dropped on purpose): the acceptance bar is a
functionally correct app on real hardware, cross-checked against nwlink offline where possible.

See docs/04-third-party-apps/nwlink-port-plan.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..dfu import constants as C
from .nwa_link import (
    SHF_ALLOC,
    SHF_EXECINSTR,
    SHF_WRITE,
    SHN_ABS,
    SHN_UNDEF,
    STB_GLOBAL,
    STB_WEAK,
    STT_FUNC,
    STT_SECTION,
    Elf32,
    ElfError,
    RelocContext,
    Section,
    apply_relocations,
)

APPINFO_SIZE = 0x20


class LinkError(ValueError):
    """A pure-Python link failed (unresolved symbol, bad layout, …)."""


def _align(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return (value + alignment - 1) // alignment * alignment


# Sections we deliberately drop: unwind tables the OS does not need to launch/run an app, and
# anything non-allocatable. (nwlink folds .ARM.exidx to 8 B and discards .eh_frame; dropping both
# is fine for a running app that does not unwind — the acceptance test is on-device behaviour.)
_DROP_EXACT = {".eh_frame", ".ARM.exidx"}


def _kind(sec: Section) -> str:
    """Bucket an allocatable input section into the layout group it belongs to."""
    n = sec.name
    if n == ".rodata.eadk_app_name":
        return "name"
    if n == ".rodata.eadk_app_icon":
        return "icon"
    if n == ".rodata.eadk_api_level":
        return "api"
    if sec.is_nobits:
        return "bss"
    if sec.flags & SHF_EXECINSTR:
        return "text"
    if sec.flags & SHF_WRITE:
        return "data"
    return "rodata"


@dataclass
class _Placed:
    obj: int  # 0 = app, 1 = runtime
    sec: Section
    vma: int
    lma: int  # differs from vma only for .data (LMA in flash, VMA in RAM)


@dataclass
class _Objects:
    app: Elf32
    runtime: Elf32
    # name -> (obj_id, symbol) for every GLOBAL/WEAK defined symbol across both inputs
    globals_: dict = field(default_factory=dict)


def _collect_globals(objs: _Objects) -> None:
    for obj_id, elf in ((0, objs.app), (1, objs.runtime)):
        for sym in elf.symbols:
            if not sym.name or sym.bind not in (STB_GLOBAL, STB_WEAK):
                continue
            if sym.shndx in (SHN_UNDEF,):
                continue
            # a strong (GLOBAL) definition wins over a weak one already seen
            prev = objs.globals_.get(sym.name)
            if prev is None or (prev[1].bind == STB_WEAK and sym.bind == STB_GLOBAL):
                objs.globals_[sym.name] = (obj_id, sym)


@dataclass
class PureLinker:
    """Links an app ``ET_REL`` + our runtime ``ET_REL`` into a flat AppInfo ``.bin``."""

    flash_start: int
    flash_length: int
    ram_start: int
    ram_length: int
    trampoline_start: int

    def link(self, app_blob: bytes, runtime_blob: bytes) -> bytes:
        app = Elf32.parse(app_blob)
        rt = Elf32.parse(runtime_blob)
        objs = _Objects(app, rt)
        _collect_globals(objs)

        placed: list[_Placed] = []
        # final VMA of each input section, keyed (obj_id, section_index) — for symbol resolution
        self._sec_vma: dict[tuple[int, int], int] = {}

        # --- gather allocatable sections per group, in input order (app before runtime) ---
        groups: dict[str, list[tuple[int, Section]]] = {
            k: [] for k in ("name", "icon", "api", "text", "rodata", "data", "bss")
        }
        for obj_id, elf in ((0, app), (1, rt)):
            for sec in elf.sections:
                if not (sec.flags & SHF_ALLOC):
                    continue
                if sec.name in _DROP_EXACT:
                    continue
                groups[_kind(sec)].append((obj_id, sec))

        origin = self.flash_start

        # --- FLASH layout: header, name, icon, api, text, rodata ---
        cursor = origin + APPINFO_SIZE

        def place_flash(group: str) -> None:
            nonlocal cursor
            for obj_id, sec in groups[group]:
                cursor = _align(cursor, max(sec.addralign, 1))
                placed.append(_Placed(obj_id, sec, cursor, cursor))
                self._sec_vma[(obj_id, sec.index)] = cursor
                cursor += sec.size

        for g in ("name", "icon", "api"):
            place_flash(g)
        # .text aligned to the widest input requirement (>=4)
        text_align = max([4] + [s.addralign for _, s in groups["text"]])
        cursor = _align(cursor, text_align)
        place_flash("text")
        place_flash("rodata")
        eadk_app_end = _align(cursor, 4)

        # --- .data: LMA continues in flash (init image), VMA lives in RAM; both advance in
        # lockstep (same per-section alignment) so crt0's straight byte-copy is correct ---
        data_lma = _align(eadk_app_end, 4)
        data_vma = self.ram_start
        data_lma_start = data_lma
        data_vma_start = data_vma
        for obj_id, sec in groups["data"]:
            data_lma = _align(data_lma, max(sec.addralign, 1))
            data_vma = _align(data_vma, max(sec.addralign, 1))
            if sec is groups["data"][0][1]:
                data_lma_start, data_vma_start = data_lma, data_vma
            placed.append(_Placed(obj_id, sec, data_vma, data_lma))
            self._sec_vma[(obj_id, sec.index)] = data_vma
            data_lma += sec.size
            data_vma += sec.size
        data_end_vma = data_vma
        flash_end = data_lma  # end of the flat image in flash

        # --- .bss: VMA in RAM after .data (NOBITS, not emitted) ---
        bss_vma = data_end_vma
        bss_start = _align(bss_vma, 4)
        bss_vma = bss_start
        for obj_id, sec in groups["bss"]:
            bss_vma = _align(bss_vma, max(sec.addralign, 1))
            placed.append(_Placed(obj_id, sec, bss_vma, bss_vma))
            self._sec_vma[(obj_id, sec.index)] = bss_vma
            bss_vma += sec.size
        bss_end = bss_vma

        # --- linker-defined symbols the runtime (and some apps) reference ---
        self._linker_syms: dict[str, int] = {
            "_data_section_start_flash": data_lma_start,  # LMA where .data init bytes begin
            "_data_section_start_ram": data_vma_start,
            "_data_section_end_ram": data_end_vma,
            "_bss_section_start_ram": bss_start,
            "_bss_section_end_ram": bss_end,
            "_heap_start": _align(bss_end, 8),
            "_heap_end": self.ram_start + self.ram_length,
            "_userland_trampoline_address": self.trampoline_start,
            "_eadk_app_end": eadk_app_end,
        }
        # eadk_app_name / eadk_app_icon addresses (the app's KEEP sections)
        for g, symname in (("name", "eadk_app_name"), ("icon", "eadk_app_icon")):
            if groups[g]:
                oid, sec = groups[g][0]
                self._linker_syms[symname] = self._sec_vma[(oid, sec.index)]

        # --- resolve + relocate every placed PROGBITS section, copy into the flat image ---
        image = bytearray(flash_end - origin)
        # AppInfo header first (filled after we know _start / offsets)
        for p in placed:
            if p.sec.is_nobits:
                continue
            data = p.sec.data
            relocs = (objs.app if p.obj == 0 else objs.runtime).relocs.get(p.sec.index)
            if relocs:
                ctx = RelocContext(p.vma, self._make_resolver(objs, p.obj))
                data = apply_relocations(data, relocs, ctx)
            # flash sections copy at (vma-origin); .data copies at its LMA
            at = (p.lma if _kind(p.sec) == "data" else p.vma) - origin
            image[at : at + len(data)] = data

        # --- AppInfo header ---
        start_addr = self._resolve_name(objs, "_start")
        if start_addr is None:
            raise LinkError("runtime does not define _start")
        api_level = self._read_api_level(objs)
        name_off = self._linker_syms.get("eadk_app_name", origin) - origin
        icon_sec = groups["icon"][0][1] if groups["icon"] else None
        icon_off = (self._linker_syms.get("eadk_app_icon", origin) - origin) if icon_sec else 0
        icon_size = icon_sec.size if icon_sec else 0
        header = struct.pack(
            "<IIIIIIII",
            C.MAGIC_EXTERNAL_APP,
            api_level,
            name_off,
            icon_size,
            icon_off,
            (start_addr & ~1) - origin,
            eadk_app_end - origin,
            C.MAGIC_EXTERNAL_APP,
        )
        image[0:APPINFO_SIZE] = header
        return bytes(image)

    # -- symbol resolution -----------------------------------------------------------------
    def _make_resolver(self, objs: _Objects, obj_id: int):
        elf = objs.app if obj_id == 0 else objs.runtime

        def resolve(sym_index: int) -> int:
            sym = elf.symbols[sym_index]
            # section symbol (or unnamed local): value = final base of its section
            if sym.type == STT_SECTION or (not sym.name and sym.shndx not in (SHN_UNDEF, SHN_ABS)):
                base = self._sec_vma.get((obj_id, sym.shndx))
                if base is None:
                    raise LinkError(f"reloc against dropped/absent section index {sym.shndx}")
                return base
            if sym.shndx == SHN_ABS:
                return sym.value
            if sym.shndx != SHN_UNDEF:
                base = self._sec_vma.get((obj_id, sym.shndx))
                if base is None:
                    raise LinkError(f"symbol {sym.name!r} in a dropped section")
                val = base + sym.value
                return val | 1 if sym.type == STT_FUNC else val
            # undefined here: linker-defined, then the cross-object global table
            if sym.name in self._linker_syms:
                return self._linker_syms[sym.name]
            g = objs.globals_.get(sym.name)
            if g is None:
                raise LinkError(f"unresolved symbol: {sym.name!r}")
            g_obj, g_sym = g
            base = self._sec_vma.get((g_obj, g_sym.shndx))
            if base is None:
                if g_sym.shndx == SHN_ABS:
                    return g_sym.value
                raise LinkError(f"symbol {sym.name!r} defined in a dropped section")
            val = base + g_sym.value
            return val | 1 if g_sym.type == STT_FUNC else val

        return resolve

    def _resolve_name(self, objs: _Objects, name: str) -> int | None:
        g = objs.globals_.get(name)
        if g is None:
            return None
        obj_id, sym = g
        base = self._sec_vma.get((obj_id, sym.shndx))
        if base is None:
            return None
        val = base + sym.value
        return val | 1 if sym.type == STT_FUNC else val

    def _read_api_level(self, objs: _Objects) -> int:
        sec = objs.app.section(".rodata.eadk_api_level")
        if sec and len(sec.data) >= 4:
            return struct.unpack_from("<I", sec.data, 0)[0]
        return 0


def _load_runtime() -> bytes:
    """The embedded clean-room EADK runtime object (built from ``eadk_runtime.s``)."""
    from ._eadk_runtime import RUNTIME_OBJECT

    return RUNTIME_OBJECT


def link_nwa_pure(
    blob: bytes,
    *,
    flash_start: int,
    flash_length: int,
    ram_start: int,
    ram_length: int,
    trampoline_start: int | None,
) -> bytes:
    """Link a relocatable ``.nwa`` ``blob`` against our clean-room runtime, no Node.

    Returns the flat, flashable AppInfo ``.bin``. ``trampoline_start`` is required (the
    ``eadk_display_draw_string`` dispatch needs the device-derived OS trampoline); raises
    :class:`LinkError` if it is missing or the link fails."""
    if trampoline_start is None:
        raise LinkError("pure-Python link needs a device-derived trampoline address")
    try:
        return PureLinker(flash_start, flash_length, ram_start, ram_length, trampoline_start).link(
            blob, _load_runtime()
        )
    except ElfError as exc:  # malformed input object -> surface as a link failure (fallback-able)
        raise LinkError(f"cannot parse .nwa as an ARM ET_REL object: {exc}") from exc
