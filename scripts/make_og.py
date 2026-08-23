"""
Build the 1200x630 Open Graph card for romapps.xyz.

Social platforms crop and letterbox anything that isn't close to 1.91:1, and a
square app icon (what this used to point at) renders as a tiny badge on a grey
field. This composes a real card in the site's own palette.

    python scripts/make_og.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

VOID = (11, 8, 18)
PANEL = (21, 16, 32)
TEXT = (236, 231, 245)
MUTED = (141, 132, 163)
VIOLET = (124, 58, 237)
PINK = (255, 45, 154)
GREEN = (34, 197, 94)

FONTS = Path("C:/Windows/Fonts")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def rounded(size: tuple[int, int], radius: int) -> Image.Image:
    """A white rounded-rect mask."""
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius, fill=255)
    return m


def build() -> Path:
    img = Image.new("RGB", (W, H), VOID)
    d = ImageDraw.Draw(img)

    # --- candle field, echoing the site's 3D hero -------------------------
    candles = Image.new("RGB", (W, H), VOID)
    cd = ImageDraw.Draw(candles)
    rng_state = 20260823
    def rnd() -> float:
        nonlocal rng_state
        rng_state = (1103515245 * rng_state + 12345) % (1 << 31)
        return rng_state / (1 << 31)

    for i in range(46):
        x = int(rnd() * W)
        h = int(60 + rnd() * 300)
        y = int(rnd() * (H - h))
        w = 10
        t = x / W
        col = lerp(VIOLET, PINK, min(1.0, max(0.0, t + (rnd() - 0.5) * 0.3)))
        cd.rectangle([x, y, x + w, y + h], fill=col)
        cd.rectangle([x + w // 2 - 1, y - 26, x + w // 2 + 1, y + h + 26], fill=col)

    candles = candles.filter(ImageFilter.GaussianBlur(1.2))
    img = Image.blend(img, candles, 0.30)
    d = ImageDraw.Draw(img)

    # fade the field out behind the copy so text stays legible
    veil = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(veil)
    for x in range(W):
        vd.line([(x, 0), (x, H)], fill=int(232 * max(0.0, 1 - (x / W) ** 1.5)))
    img = Image.composite(Image.new("RGB", (W, H), VOID), img, veil)
    d = ImageDraw.Draw(img)

    # --- logo -------------------------------------------------------------
    logo = Image.open(ASSETS / "rom-icon.png").convert("RGBA").resize((88, 88), Image.LANCZOS)
    img.paste(logo, (72, 66), logo)

    d.text((178, 78), "ROM", font=font("segoeuib.ttf", 40), fill=TEXT)
    d.text((180, 126), "romapps.xyz", font=font("consola.ttf", 20), fill=MUTED)

    # --- headline ---------------------------------------------------------
    d.text((72, 232), "Small, sharp apps.", font=font("segoeuib.ttf", 76), fill=TEXT)

    # gradient second line, drawn through a text mask
    line2 = "Download and run."
    f2 = font("segoeuib.ttf", 76)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((72, 318), line2, font=f2, fill=255)
    grad = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(grad)
    bbox = f2.getbbox(line2)
    span = max(1, bbox[2] - bbox[0])
    for x in range(W):
        gd.line([(x, 0), (x, H)], fill=lerp(VIOLET, PINK, min(1.0, max(0.0, (x - 72) / span))))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # --- supporting line --------------------------------------------------
    d.text(
        (72, 432),
        "Free Windows apps. No accounts, no subscriptions, no bloat.",
        font=font("segoeui.ttf", 27),
        fill=MUTED,
    )

    # --- chips ------------------------------------------------------------
    x = 72
    for label, col in (
        ("ROM TRADER v1.1.0", GREEN),
        ("OPEN SOURCE", MUTED),
        ("WINDOWS 10/11", MUTED),
    ):
        f = font("consolab.ttf", 18)
        tw = d.textlength(label, font=f)
        cw, ch = int(tw) + 34, 44
        chip = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(chip).rounded_rectangle([0, 0, cw - 1, ch - 1], 22, outline=col + (150,), width=2)
        img.paste(chip, (x, 500), chip)
        d.text((x + 17, 500 + 12), label, font=f, fill=col)
        x += cw + 14

    # subtle top hairline in brand gradient
    for px in range(W):
        d.point((px, 0), fill=lerp(VIOLET, PINK, px / W))
        d.point((px, 1), fill=lerp(VIOLET, PINK, px / W))

    out = ASSETS / "og-card.png"
    img.save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size} bytes)")
