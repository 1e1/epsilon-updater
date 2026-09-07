"""Measure the system floor a built binary really demands.

The frozen build channel (see docs/05-packaging-ui/legacy-channel.md) promises one floor per
OS: macOS 10.12, glibc 2.17, Windows 8.1. A wheel tag or a table in a doc can claim anything —
what the OS enforces is what the Mach-O / ELF / PE headers say. So CI measures the tree that is
about to be zipped, and fails when a toolchain bump quietly raises a floor.

    python -m nwupdater.tools.binary_floor --macos 10.12 "dist/NumWorks Updater.app"
    python -m nwupdater.tools.binary_floor --glibc 2.17 --exclude site-packages dist "$prefix"
    python -m nwupdater.tools.binary_floor --windows 6.1 dist

Stdlib only, and it reads bytes rather than shelling out to vtool / objdump / dumpbin: the same
check then runs on all three runners, and on any machine inspecting a downloaded zip.
"""

from __future__ import annotations

import argparse
import re
import struct
from pathlib import Path

Version = tuple[int, ...]

# Mach-O
_MACHO_LE = {b"\xce\xfa\xed\xfe": False, b"\xcf\xfa\xed\xfe": True}  # magic -> is 64-bit
_FAT = {b"\xca\xfe\xba\xbe": False, b"\xca\xfe\xba\xbf": True}  # magic -> 64-bit offsets
_LC_VERSION_MIN_MACOSX = 0x24
_LC_BUILD_VERSION = 0x32
_PLATFORM_MACOS = 1
_CPU_NAMES = {0x01000007: "x86_64", 0x0100000C: "arm64", 0x00000007: "i386"}

# ELF
_ELF_MAGIC = b"\x7fELF"
_GLIBC_SYMBOL = re.compile(rb"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?")

# PE
_PE_MAGIC = b"PE\0\0"


def _trim(version: Version) -> Version:
    """(10, 12, 0) -> (10, 12); a floor reads better without the trailing zeros."""
    out = list(version)
    while len(out) > 2 and out[-1] == 0:
        out.pop()
    return tuple(out)


def parse_version(text: str) -> Version:
    """Read a dotted version — 10.12, 2.17, 6.3 — as a comparable tuple."""
    return _trim(tuple(int(part) for part in text.split(".")))


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


def _macho_version(packed: int) -> Version:
    """Mach-O packs a version as X.Y.Z in one 32-bit word: xxxx.yy.zz."""
    return _trim((packed >> 16, (packed >> 8) & 0xFF, packed & 0xFF))


def _macho_slice_floor(data: bytes, offset: int) -> tuple[str, Version] | None:
    """Read the macOS minimum version out of one Mach-O slice, or None if it declares none."""
    magic = data[offset : offset + 4]
    if magic not in _MACHO_LE:
        return None
    wide = _MACHO_LE[magic]
    cputype, _, _, ncmds = struct.unpack_from("<iiiI", data, offset + 4)
    arch = _CPU_NAMES.get(cputype & 0xFFFFFFFF, f"cpu-{cputype}")
    cursor = offset + (32 if wide else 28)
    for _ in range(ncmds):
        if cursor + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from("<II", data, cursor)
        if cmdsize < 8:
            break
        if cmd == _LC_VERSION_MIN_MACOSX:
            (packed,) = struct.unpack_from("<I", data, cursor + 8)
            return arch, _macho_version(packed)
        if cmd == _LC_BUILD_VERSION:
            platform, minos = struct.unpack_from("<II", data, cursor + 8)
            # A non-macOS platform (iOS simulator, tvOS…) says nothing about our floor.
            if platform == _PLATFORM_MACOS:
                return arch, _macho_version(minos)
        cursor += cmdsize
    return None


def macho_floors(data: bytes) -> list[tuple[str, Version]]:
    """Per-slice macOS floors. Thin binaries yield one entry, universal ones several."""
    magic = data[:4]
    if magic in _FAT:
        wide = _FAT[magic]
        (count,) = struct.unpack_from(">I", data, 4)
        # CAFEBABE is also the Java class-file magic; a bogus count means it is not a fat binary.
        if not 0 < count < 64:
            return []
        entry = 32 if wide else 20
        found = []
        for index in range(count):
            base = 8 + index * entry
            if base + entry > len(data):
                break
            offset = (
                struct.unpack_from(">Q", data, base + 8)[0]
                if wide
                else struct.unpack_from(">I", data, base + 8)[0]
            )
            slice_floor = _macho_slice_floor(data, offset)
            if slice_floor:
                found.append(slice_floor)
        return found
    slice_floor = _macho_slice_floor(data, 0)
    return [slice_floor] if slice_floor else []


def elf_glibc_floor(data: bytes) -> Version | None:
    """Highest GLIBC_x.y version an ELF imports — the glibc it refuses to run below.

    The versions live in ``.dynstr``, referenced by ``.gnu.version_r``; reading the whole
    dynamic string table is enough here and keeps the parser to one section lookup.
    """
    if data[:4] != _ELF_MAGIC or len(data) < 64:
        return None
    wide = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    if wide:
        shoff = struct.unpack_from(endian + "Q", data, 0x28)[0]
        shentsize, shnum, shstrndx = struct.unpack_from(endian + "HHH", data, 0x3A)
        name_off, size_off = 0x00, 0x20
        offset_field = 0x18
    else:
        shoff = struct.unpack_from(endian + "I", data, 0x20)[0]
        shentsize, shnum, shstrndx = struct.unpack_from(endian + "HHH", data, 0x2E)
        name_off, size_off = 0x00, 0x14
        offset_field = 0x10
    if not shoff or not shnum or shstrndx >= shnum:
        return None

    def section(index: int) -> tuple[int, int, int]:
        base = shoff + index * shentsize
        (name,) = struct.unpack_from(endian + "I", data, base + name_off)
        fmt = endian + ("Q" if wide else "I")
        (offset,) = struct.unpack_from(fmt, data, base + offset_field)
        (size,) = struct.unpack_from(fmt, data, base + size_off)
        return name, offset, size

    _, str_offset, str_size = section(shstrndx)
    names = data[str_offset : str_offset + str_size]
    for index in range(shnum):
        name, offset, size = section(index)
        label = names[name : names.find(b"\0", name)]
        if label == b".dynstr":
            versions = [
                _trim(tuple(int(g) for g in match.groups() if g is not None))
                for match in _GLIBC_SYMBOL.finditer(data[offset : offset + size])
            ]
            return max(versions) if versions else None
    return None


def pe_floor(data: bytes) -> Version | None:
    """Minimum Windows version from a PE optional header (OS and subsystem fields)."""
    if data[:2] != b"MZ" or len(data) < 0x40:
        return None
    (pe_offset,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe_offset : pe_offset + 4] != _PE_MAGIC:
        return None
    optional = pe_offset + 24
    if len(data) < optional + 52:
        return None
    os_major, os_minor = struct.unpack_from("<HH", data, optional + 40)
    sub_major, sub_minor = struct.unpack_from("<HH", data, optional + 48)
    return max(_trim((os_major, os_minor)), _trim((sub_major, sub_minor)))


def inspect(path: Path, kind: str) -> list[tuple[str, Version]]:
    """Floors declared by one file, as (label, version) pairs. Non-matching files yield []."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if kind == "macos":
        return macho_floors(data)
    if kind == "glibc":
        floor = elf_glibc_floor(data)
        return [("elf", floor)] if floor else []
    floor = pe_floor(data)
    return [("pe", floor)] if floor else []


def _walk(paths: list[Path], exclude: list[str] | None = None) -> list[Path]:
    """Files to inspect under each named root.

    ``exclude`` matches the path RELATIVE to the root it was found under, so a build-only
    dependency can be skipped inside an interpreter tree (``--exclude site-packages``) while the
    one package that does ship stays inspectable by naming its directory as its own root.
    """
    patterns = exclude or []
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            # Symlinks inside a .app framework point back into the same binaries.
            for found in sorted(path.rglob("*")):
                if not found.is_file() or found.is_symlink():
                    continue
                relative = str(found.relative_to(path))
                if any(pattern in relative for pattern in patterns):
                    continue
                files.append(found)
        elif path.is_file():
            files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwupdater-binary-floor", description=__doc__.splitlines()[0]
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--macos", metavar="X.Y", help="max allowed macOS floor, e.g. 10.12")
    target.add_argument("--glibc", metavar="X.Y", help="max allowed glibc floor, e.g. 2.17")
    target.add_argument("--windows", metavar="X.Y", help="max allowed Windows floor, e.g. 6.1")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="skip what a root contains at this relative path (repeatable), e.g. site-packages",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to inspect")
    args = parser.parse_args(argv)

    kind = "macos" if args.macos else "glibc" if args.glibc else "windows"
    limit = parse_version(args.macos or args.glibc or args.windows)

    worst: Version = ()
    offenders: list[tuple[Path, str, Version]] = []
    inspected = 0
    for path in _walk(args.paths, args.exclude):
        for label, floor in inspect(path, kind):
            inspected += 1
            worst = max(worst, floor)
            if floor > limit:
                offenders.append((path, label, floor))

    if not inspected:
        print(f"no {kind} binary found in {', '.join(str(p) for p in args.paths)}")
        return 1
    for path, label, floor in offenders:
        print(f"  {format_version(floor)}  {path} ({label})")
    verdict = "above the target" if offenders else "within the target"
    print(
        f"{kind} floor: {format_version(worst)} across {inspected} binaries "
        f"— {verdict} {format_version(limit)}"
    )
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
