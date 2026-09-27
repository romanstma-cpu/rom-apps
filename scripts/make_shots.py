"""
Prepare a product screenshot for the site.

Takes a window capture and writes a web-sized PNG (the full-size link) plus a
WebP (what the page displays) into assets/, so a release's screenshots come out
consistent and small.

    python scripts/make_shots.py <capture.png> <stem>
    python scripts/make_shots.py capture.png rom-polybot-overview-2.36.0

Needs Pillow (pip install pillow). If the capture is already the PNG in
assets/, it is left untouched and only the WebP is written.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# Displayed at most ~1012px wide in the layout; 1600 covers 2x screens with room.
TARGET_W = 1600


def prepare(src: Path, stem: str) -> None:
    img = Image.open(src).convert("RGB")
    if img.width > TARGET_W:
        h = round(img.height * TARGET_W / img.width)
        img = img.resize((TARGET_W, h), Image.LANCZOS)

    png = ASSETS / f"{stem}.png"
    webp = ASSETS / f"{stem}.webp"
    if src.resolve() != png.resolve():
        img.save(png, "PNG", optimize=True)
    img.save(webp, "WEBP", quality=86, method=6)

    print(
        f"{stem}: {img.width}x{img.height}  "
        f"png {png.stat().st_size:,}B  webp {webp.stat().st_size:,}B  "
        f"({100 - webp.stat().st_size * 100 // png.stat().st_size}% smaller)"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    prepare(Path(sys.argv[1]), sys.argv[2])
