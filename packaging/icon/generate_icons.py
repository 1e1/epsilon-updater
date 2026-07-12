#!/usr/bin/env python3
"""Generate the NumWorks Updater app icon (PNG / ICO / ICNS) — no font dependency.

The "N" and the update arrow are drawn as vector shapes and supersampled, so the result is
crisp at every size and reproducible on any OS (only Pillow required; iconutil on macOS is
used for .icns when available).

    python3 generate_icons.py [--arrow up|down]

Outputs into this directory: icon_<size>.png, icon.ico, icon.iconset/, icon.icns (macOS).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
AMBER = (245, 166, 35, 255)
CHAR = (43, 45, 49, 255)
WHITE = (255, 255, 255, 255)
SS = 4  # supersampling factor


def _rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def draw_icon(size: int, arrow: str = "up") -> Image.Image:
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # app-tile background (amber, macOS-ish corner)
    _rounded(d, [S * 0.016, S * 0.016, S * 0.984, S * 0.984], S * 0.227, AMBER)

    # letter "N" as three strokes
    x0, x1 = S * 0.30, S * 0.70
    y0, y1 = S * 0.28, S * 0.72
    w = S * 0.088
    d.rectangle([x0, y0, x0 + w, y1], fill=WHITE)             # left bar
    d.rectangle([x1 - w, y0, x1, y1], fill=WHITE)             # right bar
    d.line([(x0 + w / 2, y0), (x1 - w / 2, y1)], fill=WHITE, width=int(w))  # diagonal

    # update badge (charcoal disc, bottom-right) with an arrow
    cx, cy, r = S * 0.75, S * 0.75, S * 0.205
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CHAR)
    aw = S * 0.045
    shaft = S * 0.085
    head = S * 0.075
    if arrow == "down":
        d.line([(cx, cy - shaft), (cx, cy + shaft)], fill=AMBER, width=int(aw))
        d.line([(cx - head, cy + shaft - head), (cx, cy + shaft)], fill=AMBER, width=int(aw))
        d.line([(cx + head, cy + shaft - head), (cx, cy + shaft)], fill=AMBER, width=int(aw))
    else:  # up
        d.line([(cx, cy + shaft), (cx, cy - shaft)], fill=AMBER, width=int(aw))
        d.line([(cx - head, cy - shaft + head), (cx, cy - shaft)], fill=AMBER, width=int(aw))
        d.line([(cx + head, cy - shaft + head), (cx, cy - shaft)], fill=AMBER, width=int(aw))

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrow", choices=["up", "down"], default="up")
    args = ap.parse_args()

    sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    imgs = {s: draw_icon(s, args.arrow) for s in sizes}
    for s, im in imgs.items():
        im.save(HERE / f"icon_{s}.png")
    print("PNG:", ", ".join(f"icon_{s}.png" for s in sizes))

    # Windows .ico (multi-size)
    imgs[256].save(HERE / "icon.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    print("ICO: icon.ico")

    # macOS .icns via iconutil (if present)
    iconset = HERE / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    mapping = {16: "16x16", 32: ["16x16@2x", "32x32"], 64: "32x32@2x", 128: "128x128",
               256: ["128x128@2x", "256x256"], 512: ["256x256@2x", "512x512"],
               1024: "512x512@2x"}
    for s, names in mapping.items():
        for n in ([names] if isinstance(names, str) else names):
            imgs[s].save(iconset / f"icon_{n}.png")
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")],
                       check=True)
        print("ICNS: icon.icns")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("ICNS: skipped (iconutil unavailable — macOS only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
