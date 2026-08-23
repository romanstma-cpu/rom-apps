"""
Prepare product screenshots for the site.

Takes the raw window captures and emits a web-sized PNG plus a WebP for each,
so the page can serve WebP to browsers that take it and fall back cleanly.

    python scripts/make_shots.py <capture-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# Displayed at most ~1012px wide in the layout; 1600 covers 2x screens with room.
TARGET_W = 1600

SHOTS = {
    "live-signals.png": "rom-trader-signals",
    "live-dashboard.png": "rom-trader-dashboard",
}


def prepare(src: Path, stem: str) -> None:
    img = Image.open(src).convert("RGB")
    if img.width > TARGET_W:
        h = round(img.height * TARGET_W / img.width)
        img = img.resize((TARGET_W, h), Image.LANCZOS)

    png = ASSETS / f"{stem}.png"
    webp = ASSETS / f"{stem}.webp"
    img.save(png, "PNG", optimize=True)
    img.save(webp, "WEBP", quality=86, method=6)

    print(
        f"{stem}: {img.width}x{img.height}  "
        f"png {png.stat().st_size:,}B  webp {webp.stat().st_size:,}B  "
        f"({100 - webp.stat().st_size * 100 // png.stat().st_size}% smaller)"
    )


if __name__ == "__main__":
    cap = Path(sys.argv[1])
    for fname, stem in SHOTS.items():
        p = cap / fname
        if p.exists():
            prepare(p, stem)
        else:
            print(f"missing: {p}")
