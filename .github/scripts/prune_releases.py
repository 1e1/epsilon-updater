#!/usr/bin/env python3
"""Compute which GitHub releases to delete under the retention policy.

Reads candidate tags (one per line) on stdin, takes the just-published tag as
argv[1], and prints the tags to delete (one per line) on stdout. See
prune-releases.sh for the plain-language policy. The current tag is never
printed, and the keep-set is derived from scratch so the result is idempotent.
"""
import re
import sys

RC_RE = re.compile(r"-rc(\.\d+)?$")


def is_rc(tag):
    return RC_RE.search(tag) is not None


def parse(tag):
    """'vX.Y.Z[-rc...]' -> (major, minor, patch) as ints."""
    core = tag.lstrip("v").split("-", 1)[0]
    parts = (core.split(".") + ["0", "0", "0"])[:3]
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def main():
    current = sys.argv[1]
    tags = [t.strip() for t in sys.stdin if t.strip()]
    rc = [t for t in tags if is_rc(t)]
    stable = [t for t in tags if not is_rc(t)]
    to_delete = set()

    if is_rc(current):
        # New RC: keep only this one; leave stable releases alone.
        to_delete.update(t for t in rc if t != current)
        print_result(to_delete, current)
        return

    # Stable release: no RC survives.
    to_delete.update(rc)

    if stable:
        # Winner of each "major.minor" line = highest patch.
        line_tag = {}
        for t in stable:
            ma, mi, pa = parse(t)
            key = (ma, mi)
            if key not in line_tag or pa > parse(line_tag[key])[2]:
                line_tag[key] = t

        max_major = max(ma for ma, _ in line_tag)
        # Highest minor line kept for each major.
        major_top_minor = {}
        for ma, mi in line_tag:
            major_top_minor[ma] = max(mi, major_top_minor.get(ma, mi))

        keep = set()
        for (ma, mi), tag in line_tag.items():
            if ma == max_major or mi == major_top_minor[ma]:
                keep.add(tag)
        to_delete.update(t for t in stable if t not in keep)

    print_result(to_delete, current)


def print_result(to_delete, current):
    for t in sorted(to_delete):
        if t != current:
            print(t)


if __name__ == "__main__":
    main()
