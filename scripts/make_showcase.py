"""
Render the 1600x1000 product showcase images from scripts/showcase.html with headless Chrome.

Each image is composed only from the app's real screenshot (tilted behind, details enlarged in
front). Writes assets/<app>-showcase-<rev>.png and .webp.

    python scripts/make_showcase.py [rev]
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_og import find_browser, run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "showcase.html"
W, H = 1600, 1000


def main() -> None:
    rev = sys.argv[1] if len(sys.argv) > 1 else "1"
    browser = find_browser()
    probe = run(browser, f"--window-size={W},{H}", "--dump-dom", "data:text/html,<script>document.title=innerHeight</script>")
    shortfall = H - int(re.search(r"<title>(\d+)</title>", probe).group(1))
    for app in ("polybot", "nova", "recoil"):
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "shot.png"
            run(browser, f"--window-size={W},{H + shortfall}", "--virtual-time-budget=4000",
                f"--screenshot={shot}", TEMPLATE.as_uri() + "#" + app)
            img = Image.open(shot).convert("RGB").crop((0, 0, W, H))
        png, webp = ROOT / f"assets/{app}-showcase-{rev}.png", ROOT / f"assets/{app}-showcase-{rev}.webp"
        img.save(png, "PNG", optimize=True)
        img.save(webp, "WEBP", quality=86, method=6)
        print(f"{webp.name}: {webp.stat().st_size:,} B  ({png.stat().st_size:,} B png)")


if __name__ == "__main__":
    main()
