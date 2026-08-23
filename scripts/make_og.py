"""
Build the 1200x630 Open Graph card for romapps.xyz.

Social platforms crop and letterbox anything far from 1.91:1, and a square app
icon renders as a tiny badge on a grey field. This composes a real card that
mirrors the site's hero: a perspective point-grid on a slow wave.

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
TEXT = (236, 231, 245)
MUTED = (141, 132, 163)
VIOLET = (124, 58, 237)
PINK = (255, 45, 154)
GREEN = (34, 197, 94)

FONTS = Path("C:/Windows/Fonts")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def lerp(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def point_field(t: float = 2.1) -> Image.Image:
    """Same projection and wave as the site's hero canvas."""
    field = Image.new("RGB", (W, H), VOID)
    d = ImageDraw.Draw(field, "RGBA")

    COLS, ROWS = 104, 44
    SPAN, NEAR, DEPTH, FOV = 30.0, 4.2, 33.0, 330.0
    cx, cy = W * 0.5, H * 0.56

    for r in range(ROWS - 1, -1, -1):
        z = NEAR + (r / (ROWS - 1)) * DEPTH
        near = 1 - (z - NEAR) / DEPTH
        scale = FOV / z
        alpha = int(pow(near, 2.1) * 0.9 * 255)
        if alpha < 4:
            continue
        size = max(1, round(2.5 * near + 0.6))

        for c in range(COLS):
            gx = (c / (COLS - 1) - 0.5) * SPAN
            y = (
                math.sin(gx * 0.40 + t * 0.5 + z * 0.15) * 0.95
                + math.sin(gx * 0.16 - t * 0.29 + z * 0.08) * 0.62
            )
            sx = cx + gx * scale
            if sx < -8 or sx > W + 8:
                continue
            sy = cy + (y - 1.35) * scale
            if sy < -8 or sy > H + 8:
                continue
            col = lerp(VIOLET, PINK, c / (COLS - 1))
            d.rectangle([sx, sy, sx + size, sy + size], fill=col + (alpha,))

    return field.filter(ImageFilter.GaussianBlur(0.4))


def build() -> Path:
    img = point_field()

    # Fade the field out under the copy so the type stays crisp.
    veil = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(veil)
    for x in range(W):
        vd.line([(x, 0), (x, H)], fill=int(238 * max(0.0, 1 - (x / W) ** 1.45)))
    img = Image.composite(Image.new("RGB", (W, H), VOID), img, veil)
    d = ImageDraw.Draw(img)

    # --- logo + wordmark ---
    logo = Image.open(ASSETS / "rom-icon.png").convert("RGBA").resize((88, 88), Image.LANCZOS)
    img.paste(logo, (72, 66), logo)
    d.text((178, 78), "ROM", font=font("segoeuib.ttf", 40), fill=TEXT)
    d.text((180, 126), "romapps.xyz", font=font("consola.ttf", 20), fill=MUTED)

    # --- headline ---
    d.text((72, 226), "Apps.", font=font("segoeuib.ttf", 82), fill=TEXT)

    line2 = "No strings."
    f2 = font("segoeuib.ttf", 82)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((72, 320), line2, font=f2, fill=255)
    grad = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(grad)
    bbox = f2.getbbox(line2)
    span = max(1, bbox[2] - bbox[0])
    for x in range(W):
        gd.line([(x, 0), (x, H)], fill=lerp(VIOLET, PINK, (x - 72) / span))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    d.text(
        (72, 442),
        "Free Windows apps. No accounts, no subscriptions, no bloat.",
        font=font("segoeui.ttf", 27),
        fill=MUTED,
    )

    # --- chips ---
    x = 72
    for label, col in (
        ("ROM TRADER v1.1.0", GREEN),
        ("OPEN SOURCE", MUTED),
        ("WINDOWS 10/11", MUTED),
    ):
        f = font("consolab.ttf", 18)
        cw, ch = int(d.textlength(label, font=f)) + 34, 44
        chip = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(chip).rounded_rectangle(
            [0, 0, cw - 1, ch - 1], 22, outline=col + (150,), width=2
        )
        img.paste(chip, (x, 508), chip)
        d.text((x + 17, 508 + 12), label, font=f, fill=col)
        x += cw + 14

    for px in range(W):
        c = lerp(VIOLET, PINK, px / W)
        d.point((px, 0), fill=c)
        d.point((px, 1), fill=c)

    out = ASSETS / "og-card.png"
    img.save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size} bytes)")
