"""``dfu-diff`` — compare two DfuSe firmware images to characterise them.

Motivation (see docs/01-specs/n02xx-firmware-format.md): the Scientifique (N02xx) firmware is
an **encrypted/opaque** blob. A single sample tells us little about the cipher; **two**
versions can reveal the *mode*:

  - many bytes equal at the SAME offset  → keystream reuse (CTR/stream, fixed nonce): C1⊕C2
    leaks P1⊕P2, so unchanged plaintext regions surface as equal ciphertext;
  - long identical PREFIX then divergence → block cipher (CBC) with the same key/IV (or a shared
    plaintext header);
  - ~no correlation (≈1/256 equal)        → per-build key/nonce (properly encrypted): nothing
    extractable.

The verdict is only asserted for **high-entropy (encrypted)** inputs. For plaintext firmware
(the graphique Epsilon) the tool just reports an ordinary binary diff — no cipher claim.

Usage:
    python -m nwupdater.tools.dfudiff OLD.dfu NEW.dfu [--json]

No network, no USB. NumWorks firmware binaries are NOT redistributed with this project — the
user supplies their own local copies (see docs/reference/known-firmwares.json for anchors).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ..install.image import FirmwareImage

ENCRYPTED_ENTROPY = 7.5  # bits/byte above which we treat a segment as encrypted/opaque
KEYSTREAM_REUSE_RATIO = 0.20  # equal-byte fraction above which keystream reuse is likely
INDEPENDENT_RATIO = 0.01  # at/below this (~1/256) the two look independently encrypted
PREFIX_SIGNIFICANT = 64  # identical-prefix bytes worth reporting as a block-cipher signal


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _common_prefix(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _longest_equal_run(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    best = run = 0
    for i in range(n):
        if a[i] == b[i]:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


@dataclass
class SegmentDiff:
    address: int
    len_a: int
    len_b: int
    compared: int  # min length actually compared
    equal_bytes: int  # positions with a[i] == b[i]  (i.e. XOR == 0)
    equal_ratio: float
    equal_ratio_after_prefix: float  # equality in [common_prefix, n) — tells CBC from CTR reuse
    common_prefix: int
    longest_equal_run: int
    equal_blocks16: int  # aligned 16-byte blocks identical at the same offset
    total_blocks16: int
    entropy_a: float
    entropy_b: float

    @property
    def encrypted(self) -> bool:
        return min(self.entropy_a, self.entropy_b) >= ENCRYPTED_ENTROPY


def diff_bytes(address: int, a: bytes, b: bytes) -> SegmentDiff:
    n = min(len(a), len(b))
    equal = sum(1 for i in range(n) if a[i] == b[i])
    prefix = _common_prefix(a, b)
    tail = n - prefix
    equal_after = sum(1 for i in range(prefix, n) if a[i] == b[i])  # excludes the shared prefix
    blocks = n // 16
    eq_blocks = sum(1 for i in range(blocks) if a[i * 16 : i * 16 + 16] == b[i * 16 : i * 16 + 16])
    return SegmentDiff(
        address=address,
        len_a=len(a),
        len_b=len(b),
        compared=n,
        equal_bytes=equal,
        equal_ratio=(equal / n if n else 0.0),
        equal_ratio_after_prefix=(equal_after / tail if tail else 0.0),
        common_prefix=prefix,
        longest_equal_run=_longest_equal_run(a, b),
        equal_blocks16=eq_blocks,
        total_blocks16=blocks,
        entropy_a=entropy(a),
        entropy_b=entropy(b),
    )


def classify(d: SegmentDiff) -> str:
    """Human verdict for one segment pair."""
    if d.len_a == d.len_b and d.compared and d.equal_bytes == d.compared:
        return "IDENTICAL — byte-for-byte identical (no change)."
    if not d.encrypted:
        pct = 100 * (1 - d.equal_ratio)
        return (
            f"PLAINTEXT diff — {pct:.1f}% of bytes differ "
            f"(entropy {d.entropy_a:.2f}/{d.entropy_b:.2f}: unencrypted, ordinary firmware diff)."
        )
    # CBC same-key/IV: equality is CONCENTRATED in a shared prefix, then avalanches to ~1/256.
    # Check this before the scattered-equality (keystream) test so a big prefix isn't mistaken
    # for reuse.
    if (
        d.common_prefix >= PREFIX_SIGNIFICANT
        and d.equal_ratio_after_prefix <= 2 * INDEPENDENT_RATIO
    ):
        return (
            f"COMMON PREFIX of {d.common_prefix} B then divergence (~1/256 after) ⇒ block "
            "cipher (CBC) with identical key/IV, or a shared plaintext header before encryption."
        )
    if d.equal_ratio_after_prefix >= KEYSTREAM_REUSE_RATIO:
        return (
            f"LIKELY KEYSTREAM REUSE — {100 * d.equal_ratio:.1f}% of bytes equal at the "
            f"same offset, scattered (longest common run {d.longest_equal_run} B) ⇒ same "
            "keystream (stream/CTR with a fixed nonce): C1⊕C2 exposes the plaintext structure."
        )
    if d.equal_ratio <= INDEPENDENT_RATIO and d.common_prefix < PREFIX_SIGNIFICANT:
        return (
            "INDEPENDENT — no correlation (~1/256 bytes equal): per-build key/nonce, "
            "sound encryption. The diff reveals nothing."
        )
    return (
        f"INCONCLUSIVE — partial correlation ({100 * d.equal_ratio:.2f}% equal, "
        f"prefix {d.common_prefix} B, after-prefix {100 * d.equal_ratio_after_prefix:.2f}%)."
    )


@dataclass
class DfuDiff:
    size_a: int
    size_b: int
    segments: list[SegmentDiff]
    only_in_a: list[int]  # segment addresses present only in A
    only_in_b: list[int]

    def to_dict(self) -> dict:
        return {
            "size_a": self.size_a,
            "size_b": self.size_b,
            "only_in_a": [f"0x{a:08x}" for a in self.only_in_a],
            "only_in_b": [f"0x{a:08x}" for a in self.only_in_b],
            "segments": [
                {**asdict(s), "address": f"0x{s.address:08x}", "verdict": classify(s)}
                for s in self.segments
            ],
        }


def diff_images(a: FirmwareImage, b: FirmwareImage) -> DfuDiff:
    by_a = {s.address: s.data for s in a.segments}
    by_b = {s.address: s.data for s in b.segments}
    common = sorted(set(by_a) & set(by_b))
    seg_diffs = [diff_bytes(addr, by_a[addr], by_b[addr]) for addr in common]
    return DfuDiff(
        size_a=a.total_size,
        size_b=b.total_size,
        segments=seg_diffs,
        only_in_a=sorted(set(by_a) - set(by_b)),
        only_in_b=sorted(set(by_b) - set(by_a)),
    )


def diff_files(path_a: str, path_b: str) -> DfuDiff:
    a = FirmwareImage.from_dfuse(Path(path_a).read_bytes())
    b = FirmwareImage.from_dfuse(Path(path_b).read_bytes())
    return diff_images(a, b)


def format_report(diff: DfuDiff, path_a: str, path_b: str) -> str:
    lines = [
        f"dfu-diff  A={path_a}  B={path_b}",
        f"  size: A={diff.size_a} B  B={diff.size_b} B  (Δ {diff.size_b - diff.size_a:+d})",
    ]
    if diff.only_in_a:
        lines.append(f"  segments only in A: {[hex(x) for x in diff.only_in_a]}")
    if diff.only_in_b:
        lines.append(f"  segments only in B: {[hex(x) for x in diff.only_in_b]}")
    if not diff.segments:
        lines.append("  no segment at a shared address — nothing to compare.")
    for s in diff.segments:
        lines.append(f"\n  @0x{s.address:08x}  ({s.len_a}→{s.len_b} B, compared {s.compared} B)")
        lines.append(
            f"    equal {s.equal_bytes}/{s.compared} ({100 * s.equal_ratio:.2f}%) · "
            f"prefix {s.common_prefix} B · max common run {s.longest_equal_run} B · "
            f"blocks16 {s.equal_blocks16}/{s.total_blocks16}"
        )
        lines.append(f"    entropy A={s.entropy_a:.3f} B={s.entropy_b:.3f}")
        lines.append(f"    → {classify(s)}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(
        prog="python -m nwupdater.tools.dfudiff",
        description="Compare two DfuSe firmwares to characterise the encryption (unofficial project).",
    )
    p.add_argument("old", help="path to the older .dfu (A)")
    p.add_argument("new", help="path to the newer .dfu (B)")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = p.parse_args(argv)

    diff = diff_files(args.old, args.new)
    if args.json:
        print(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(diff, args.old, args.new))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
