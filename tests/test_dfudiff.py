"""dfu-diff tool: cipher-mode characterisation from two firmware images.

Offline, synthetic. We fabricate ciphertext-shaped inputs that each exhibit one mode's
signature and assert the verdict — no real firmware, no network, no USB.
"""

import random

from nwupdater.install.image import FirmwareImage, FirmwareSegment
from nwupdater.tools import dfudiff as DD

ADDR = 0x90000000


def rb(seed, n):
    return random.Random(seed).randbytes(n)


def xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _img(data):
    return FirmwareImage([FirmwareSegment(ADDR, data)], bcd_device=0x0000)


def _verdict(a, b):
    return DD.classify(DD.diff_images(_img(a), _img(b)).segments[0])


# -- entropy sanity --------------------------------------------------------------------
def test_entropy_bounds():
    assert DD.entropy(b"") == 0.0
    assert DD.entropy(bytes(range(256)) * 4) > 7.9      # uniform → ~8
    assert DD.entropy(b"\x00" * 4096) < 0.01            # constant → ~0


# -- the four modes --------------------------------------------------------------------
def test_plaintext_diff_is_not_a_cipher_claim():
    base = bytes([(i // 64) % 4 for i in range(8192)])  # very low entropy (plaintext-like)
    v2 = bytearray(base)
    v2[5000:5050] = bytes(50)
    verdict = _verdict(base, bytes(v2))
    assert verdict.startswith("PLAINTEXT")


def test_identical_files_are_reported_as_identical():
    blob = rb(1, 8192)
    assert _verdict(blob, blob).startswith("IDENTICAL")


def test_independent_encryption_yields_nothing():
    verdict = _verdict(rb(7, 8192), rb(8, 8192))        # two unrelated high-entropy blobs
    assert verdict.startswith("INDEPENDENT")


def test_keystream_reuse_detected():
    P = rb(1, 8192)
    K = rb(2, 8192)
    P2 = bytearray(P)
    P2[4000:4200] = rb(3, 200)       # small change, same keystream K
    verdict = _verdict(xor(P, K), xor(bytes(P2), K))
    assert "KEYSTREAM" in verdict


def test_cbc_same_key_common_prefix_detected():
    prefix = rb(4, 4096)                                 # identical leading plaintext/blocks
    c1 = prefix + rb(5, 4096)
    c2 = prefix + rb(6, 4096)                            # diverges after the prefix
    verdict = _verdict(c1, c2)
    assert verdict.startswith("COMMON PREFIX")


# -- image-level + file round-trip -----------------------------------------------------
def test_diff_reports_size_delta_and_unique_segments():
    a = FirmwareImage([FirmwareSegment(ADDR, rb(1, 2048)),
                       FirmwareSegment(0x08000000, rb(9, 512))], bcd_device=0)
    b = FirmwareImage([FirmwareSegment(ADDR, rb(2, 2048))], bcd_device=0)
    d = DD.diff_images(a, b)
    assert d.size_a == 2560 and d.size_b == 2048
    assert d.only_in_a == [0x08000000] and d.only_in_b == []
    assert len(d.segments) == 1  # only the shared address is compared


def test_diff_files_roundtrip(tmp_path):
    pa = tmp_path / "a.dfu"
    pb = tmp_path / "b.dfu"
    pa.write_bytes(_img(rb(1, 4096)).to_dfuse())
    pb.write_bytes(_img(rb(2, 4096)).to_dfuse())
    d = DD.diff_files(str(pa), str(pb))
    assert d.segments and d.segments[0].address == ADDR
    # JSON view is serialisable and carries a verdict
    js = d.to_dict()
    assert "verdict" in js["segments"][0]
