"""Scripts storage (Ion FileSystem) format — parse/encode round-trips. Pure, offline."""

import pytest

from nwupdater.formats import storage as S
from nwupdater.formats.storage import Record, encode_storage, make_python, parse_storage


def test_roundtrip_python_records():
    recs = [make_python("mandelbrot", "print('hi')\n", True),
            make_python("suites", "u=1\n", False)]
    back = parse_storage(encode_storage(recs))
    assert [r.fullname for r in back] == ["mandelbrot.py", "suites.py"]
    assert back[0].is_python and back[0].auto_import and back[0].code == "print('hi')\n"
    assert back[1].auto_import is False and back[1].code == "u=1\n"


def test_magic_is_ee0bddba_and_terminator_is_zero():
    blob = encode_storage([make_python("a", "1\n")])
    assert blob[:4] == b"\xba\xdd\x0b\xee"   # 0xEE0BDDBA little-endian
    assert blob[-2:] == b"\x00\x00"          # Size==0 terminator (not a second magic)


def test_non_python_records_are_preserved():
    recs = [Record("prefs.bin", b"\x01\x02\x03"), make_python("a", "1\n")]
    back = parse_storage(encode_storage(recs))
    assert back[0].fullname == "prefs.bin" and back[0].body == b"\x01\x02\x03"
    assert not back[0].is_python and back[1].is_python


def test_capacity_bound_rejected():
    with pytest.raises(S.StorageError):
        encode_storage([make_python("big", "x" * 100_000)], capacity=1024)


def test_bad_magic_rejected():
    with pytest.raises(S.StorageError):
        parse_storage(b"nope" + b"\x00" * 8)
