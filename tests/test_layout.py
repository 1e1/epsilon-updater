"""DfuSe memory-layout descriptor parsing (dfu/layout.py).

Strings are the real ones observed on device / in the reference tools — see
docs/01-specs/usb-dfu-protocol.md §6.4.
"""

import pytest

from nwupdater.dfu.layout import parse_memory_layout

# real slot-A (authenticated) layout: two runs of 64 KiB sectors
SLOT_A = "@Flash/0x90030000/61*064Kg,64*064Kg"
# real slot-B layout: mixed sector sizes + a second address group
SLOT_B = "@Flash/0x90000000/08*004Kg,01*032Kg,63*064Kg/0x90430000/61*064Kg"


def test_non_layout_string_returns_none():
    assert parse_memory_layout(None) is None
    assert parse_memory_layout("") is None
    assert parse_memory_layout("NumWorks Calculator") is None


def test_uniform_64k_sectors():
    lay = parse_memory_layout(SLOT_A)
    assert lay.sector_of(0x90030000) == (0x90030000, 0x10000)
    # a byte at the end of the first sector still maps to that sector's base
    assert lay.sector_of(0x9003FFFF) == (0x90030000, 0x10000)
    assert lay.sector_of(0x90040000) == (0x90040000, 0x10000)
    # 125 sectors * 64 KiB total; one past the end is unmapped
    assert lay.sector_of(0x90030000 + 125 * 0x10000) is None


def test_mixed_sector_sizes_and_multiple_groups():
    lay = parse_memory_layout(SLOT_B)
    # first 8 sectors are 4 KiB
    assert lay.sector_of(0x90000000) == (0x90000000, 0x1000)
    assert lay.sector_of(0x90007FFF) == (0x90007000, 0x1000)
    # then one 32 KiB sector at 0x90008000
    assert lay.sector_of(0x90008000) == (0x90008000, 0x8000)
    assert lay.sector_of(0x9000FFFF) == (0x90008000, 0x8000)
    # then 64 KiB sectors from 0x90010000
    assert lay.sector_of(0x90010000) == (0x90010000, 0x10000)
    # the second address group
    assert lay.sector_of(0x90430000) == (0x90430000, 0x10000)


def test_sectors_covering_single_sector_write():
    lay = parse_memory_layout(SLOT_A)
    # a write that fits inside one 64 KiB sector needs exactly one erase
    assert lay.sectors_covering(0x90030000, 6000) == [0x90030000]
    # even a write not starting on the boundary
    assert lay.sectors_covering(0x90030800, 1000) == [0x90030000]


def test_sectors_covering_spanning_boundary():
    lay = parse_memory_layout(SLOT_A)
    # a write crossing into the next sector needs both, de-duplicated and sorted
    assert lay.sectors_covering(0x9003F000, 0x2000) == [0x90030000, 0x90040000]


def test_sectors_covering_across_mixed_sizes():
    lay = parse_memory_layout(SLOT_B)
    # spans the last 4 KiB sector, the 32 KiB sector, and into the first 64 KiB sector
    got = lay.sectors_covering(0x90007000, 0x1000 + 0x8000 + 1)
    assert got == [0x90007000, 0x90008000, 0x90010000]


def test_megabyte_multiplier_and_access_variants():
    lay = parse_memory_layout("@Internal/0x08000000/02*001Mg,04*016Ka")
    assert lay.sector_of(0x08000000) == (0x08000000, 0x100000)
    assert lay.sector_of(0x08200000) == (0x08200000, 0x4000)  # first 16 KiB sector after 2 MiB


def test_malformed_segment_raises():
    with pytest.raises(ValueError):
        parse_memory_layout("@Flash/0x08000000/not-a-segment")
