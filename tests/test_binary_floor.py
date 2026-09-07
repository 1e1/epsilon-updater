"""System-floor reading for the frozen build channel — Mach-O, ELF and PE, on synthetic files.

The floors the legacy zips promise (macOS 10.12, glibc 2.17, Windows 8.1) are only as good as
this parser, so the headers are built here by hand rather than taken from a fixture binary.
"""

import struct

from nwupdater.tools.binary_floor import (
    elf_glibc_floor,
    format_version,
    macho_floors,
    main,
    parse_version,
    pe_floor,
)


def _macho_thin(version=(10, 12, 0), cputype=0x01000007) -> bytes:
    """64-bit little-endian Mach-O carrying a single LC_VERSION_MIN_MACOSX."""
    packed = (version[0] << 16) | (version[1] << 8) | version[2]
    header = struct.pack("<4siiiIII I", b"\xcf\xfa\xed\xfe", cputype, 3, 2, 1, 16, 0, 0)
    return header + struct.pack("<IIII", 0x24, 16, packed, 0)


def _macho_build_version(minos=(11, 0, 0), platform=1) -> bytes:
    """Newer toolchains emit LC_BUILD_VERSION instead (arm64 always does)."""
    packed = (minos[0] << 16) | (minos[1] << 8) | minos[2]
    header = struct.pack("<4siiiIII I", b"\xcf\xfa\xed\xfe", 0x0100000C, 0, 2, 1, 32, 0, 0)
    return header + struct.pack("<IIIIIIII", 0x32, 32, platform, packed, 0, 1, 0, 0)


def _macho_fat(*slices: bytes) -> bytes:
    """Universal wrapper: big-endian header, then each slice at a 4 KiB-aligned offset."""
    head = struct.pack(">4sI", b"\xca\xfe\xba\xbe", len(slices))
    offset = 0x1000
    entries, body = b"", b""
    for payload in slices:
        cputype = struct.unpack_from("<i", payload, 4)[0]
        entries += struct.pack(">iiIII", cputype, 3, offset, len(payload), 12)
        body += b"\0" * (offset - len(head) - len(slices) * 20 - len(body)) + payload
        offset += 0x1000
    return head + entries + body


def _elf(*glibc_versions: str) -> bytes:
    """64-bit little-endian ELF whose .dynstr references the given GLIBC_x.y symbols."""
    shstrtab = b"\0.shstrtab\0.dynstr\0"
    dynstr = b"\0" + b"\0".join(f"GLIBC_{v}".encode() for v in glibc_versions) + b"\0"
    shstr_off = 64
    dynstr_off = shstr_off + len(shstrtab)
    sh_off = dynstr_off + len(dynstr)

    def entry(name: int, offset: int, size: int) -> bytes:
        return struct.pack("<IIQQQQIIQQ", name, 3, 0, 0, offset, size, 0, 0, 1, 0)

    header = (
        b"\x7fELF\x02\x01\x01"
        + b"\0" * 9
        + struct.pack("<HHIQQQIHHHHHH", 3, 62, 1, 0, 0, sh_off, 0, 64, 0, 0, 64, 3, 1)
    )
    sections = (
        entry(0, 0, 0)
        + entry(shstrtab.index(b".shstrtab"), shstr_off, len(shstrtab))
        + entry(shstrtab.index(b".dynstr"), dynstr_off, len(dynstr))
    )
    return header + shstrtab + dynstr + sections


def _pe(os_version=(6, 0), subsystem=(6, 0)) -> bytes:
    """PE32+ stub with just the optional-header fields the floor is read from."""
    stub = b"MZ" + b"\0" * (0x3C - 2) + struct.pack("<I", 0x40)
    coff = struct.pack("<4sHHIIIHH", b"PE\0\0", 0x8664, 0, 0, 0, 0, 240, 0x22)
    optional = struct.pack("<H", 0x20B) + b"\0" * 38
    optional += struct.pack("<HHHH", os_version[0], os_version[1], 0, 0)
    optional += struct.pack("<HHHH", subsystem[0], subsystem[1], 0, 0)
    return stub + coff + optional


def test_version_helpers_drop_trailing_zeros():
    assert parse_version("10.12") == (10, 12)
    assert parse_version("10.12.0") == (10, 12)
    assert format_version((2, 17)) == "2.17"
    assert parse_version("2.17") < parse_version("2.34")


def test_macho_version_min_and_build_version():
    assert macho_floors(_macho_thin((10, 12, 0))) == [("x86_64", (10, 12))]
    assert macho_floors(_macho_build_version((11, 0, 0))) == [("arm64", (11, 0))]


def test_macho_ignores_non_macos_platform():
    # platform 7 is the iOS simulator: it says nothing about the macOS floor.
    assert macho_floors(_macho_build_version((13, 0, 0), platform=7)) == []


def test_macho_universal_reports_every_slice():
    fat = _macho_fat(_macho_thin((10, 12, 0)), _macho_build_version((11, 0, 0)))
    assert macho_floors(fat) == [("x86_64", (10, 12)), ("arm64", (11, 0))]


def test_macho_rejects_java_class_magic():
    # CAFEBABE is also a Java class file; the arch count is what tells them apart.
    assert macho_floors(b"\xca\xfe\xba\xbe" + struct.pack(">I", 0xFFFF)) == []


def test_elf_reports_highest_glibc():
    assert elf_glibc_floor(_elf("2.2.5", "2.14", "2.17")) == (2, 17)
    assert elf_glibc_floor(_elf()) is None
    assert elf_glibc_floor(b"not an elf") is None


def test_pe_takes_the_higher_of_os_and_subsystem():
    assert pe_floor(_pe((6, 0), (6, 0))) == (6, 0)
    assert pe_floor(_pe((6, 0), (6, 3))) == (6, 3)
    assert pe_floor(b"MZ") is None


def test_main_passes_within_target_and_fails_above(tmp_path):
    tree = tmp_path / "dist"
    tree.mkdir()
    (tree / "run").write_bytes(_macho_thin((10, 12, 0)))
    assert main(["--macos", "10.12", str(tree)]) == 0

    (tree / "libqt").write_bytes(_macho_build_version((11, 0, 0)))
    assert main(["--macos", "10.12", str(tree)]) == 1


def test_main_fails_when_nothing_was_inspected(tmp_path):
    # A silent pass on an empty or wrongly-pointed dist/ would make the gate worthless.
    (tmp_path / "readme.txt").write_text("no binaries here")
    assert main(["--glibc", "2.17", str(tmp_path)]) == 1


def test_main_exclude_skips_build_only_dependencies(tmp_path):
    # pillow (icon generation) sits in site-packages and needs GLIBC_2.27, but never reaches the
    # app — measuring it would fail the gate on a file nobody ships.
    tree = tmp_path / "python"
    (tree / "lib" / "site-packages" / "PIL").mkdir(parents=True)
    (tree / "lib" / "libpython.so").write_bytes(_elf("2.17"))
    (tree / "lib" / "site-packages" / "PIL" / "_imaging.so").write_bytes(_elf("2.27"))
    assert main(["--glibc", "2.17", str(tree)]) == 1
    assert main(["--glibc", "2.17", "--exclude", "site-packages", str(tree)]) == 0

    # …while the one package that DOES ship stays measurable, named as its own root.
    shipped = tree / "lib" / "site-packages" / "libusb_package"
    shipped.mkdir()
    (shipped / "libusb-1.0.so").write_bytes(_elf("2.34"))
    assert main(["--glibc", "2.17", "--exclude", "site-packages", str(tree), str(shipped)]) == 1


def test_main_reads_glibc_and_pe_trees(tmp_path):
    (tmp_path / "python").write_bytes(_elf("2.17"))
    assert main(["--glibc", "2.17", str(tmp_path)]) == 0
    assert main(["--glibc", "2.14", str(tmp_path)]) == 1

    (tmp_path / "app.exe").write_bytes(_pe((6, 0), (6, 0)))
    assert main(["--windows", "6.1", str(tmp_path / "app.exe")]) == 0
