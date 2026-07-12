#!/usr/bin/env python3
"""Policy scenarios for prune_releases.py. Run: python3 test_prune_releases.py

Each case: (pushed_tag, existing_release_tags, tags_that_must_be_deleted).
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("prune_releases.py")

CASES = [
    # patch replaces its whole X.Y line
    ("v1.2.3", "v1.2.1 v1.2.2 v1.2.3 v1.3.0", "v1.2.1 v1.2.2"),
    # minor is additive
    ("v1.3.0", "v1.2.3 v1.3.0", ""),
    # patch removes the .0 of its line too
    ("v1.3.1", "v1.2.3 v1.3.0 v1.3.1", "v1.3.0"),
    # major keeps only the previous major's top minor line
    ("v2.0.0", "v1.2.3 v1.3.1 v2.0.0", "v1.2.3"),
    # each previous major keeps its own top minor line
    ("v3.0.0", "v1.3.1 v2.5.2 v3.0.0", ""),
    ("v2.0.0", "v1.1.5 v1.2.0 v1.3.1 v2.0.0", "v1.1.5 v1.2.0"),
    # only one RC survives; stable untouched by a new RC
    ("v0.0.2-rc.3", "v0.0.1 v0.0.2-rc.1 v0.0.2-rc.2 v0.0.2-rc.3", "v0.0.2-rc.1 v0.0.2-rc.2"),
    ("v1.4.0-rc", "v1.2.3 v1.3.1 v1.4.0-rc", ""),
    ("v0.0.2-rc", "v0.0.2-rc.1 v0.0.2-rc", "v0.0.2-rc.1"),
    # a stable release clears all RCs (and its own lower-patch line members)
    ("v0.0.2", "v0.0.1 v0.0.2-rc.3 v0.0.2", "v0.0.1 v0.0.2-rc.3"),
]


def run(current, existing):
    out = subprocess.run(
        [sys.executable, str(SCRIPT), current],
        input="\n".join(existing.split()),
        capture_output=True, text=True, check=True,
    ).stdout
    return " ".join(sorted(t for t in out.split() if t))


def main():
    failures = 0
    for current, existing, expected in CASES:
        got = run(current, existing)
        want = " ".join(sorted(expected.split()))
        ok = got == want
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  push {current:14s} del:[{got}]"
              + ("" if ok else f"  expected:[{want}]"))
    if failures:
        print(f"\n{failures} failure(s)")
        sys.exit(1)
    print(f"\nall {len(CASES)} scenarios passed")


if __name__ == "__main__":
    main()
