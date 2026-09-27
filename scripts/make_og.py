"""
Render the 1200x630 Open Graph card, assets/og-card.png.

The card is plain HTML (scripts/og-card.html) using the site's own font,
colours and product screenshot, so it cannot drift from the page. This script
screenshots it with the Chrome or Edge you already have, in headless mode.

    python scripts/make_og.py
    CHROME="C:/path/to/chrome.exe" python scripts/make_og.py   # pick a browser

Needs Pillow (pip install pillow). Social platforms crop anything far from
1.91:1, which is why the homepage points og:image here rather than at a raw
1440x900 screenshot.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "og-card.html"
OUT = ROOT / "assets" / "og-card.png"
W, H = 1200, 630

CANDIDATES = [
    "google-chrome", "chrome", "chromium", "chromium-browser", "msedge",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_browser() -> str:
    for cand in [os.environ.get("CHROME", "")] + CANDIDATES:
        if cand and (shutil.which(cand) or Path(cand).is_file()):
            return shutil.which(cand) or cand
    sys.exit("No Chrome or Edge found. Set CHROME to the browser's executable path.")


def run(browser: str, *args: str) -> str:
    base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=1"]
    # Chromium refuses to start as root (CI containers) without this. The page
    # is a local file with no scripts, so the sandbox protects nothing here.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        base.append("--no-sandbox")
    result = subprocess.run(base + list(args), capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"{Path(browser).name} failed:\n{result.stderr[-2000:]}")
    return result.stdout


def main() -> None:
    browser = find_browser()
    # Headless Chrome reserves part of the window for browser UI it does not
    # draw, so the page area is shorter than --window-size by a version-
    # dependent amount. Measure it, then ask for a window that much taller.
    probe = run(browser, f"--window-size={W},{H}", "--dump-dom",
                "data:text/html,<script>document.title=innerHeight</script>")
    shortfall = H - int(re.search(r"<title>(\d+)</title>", probe).group(1))
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "card.png"
        run(browser, f"--window-size={W},{H + shortfall}",
            "--virtual-time-budget=4000",  # let the web font and screenshot load
            f"--screenshot={shot}", TEMPLATE.as_uri())
        Image.open(shot).convert("RGB").crop((0, 0, W, H)).save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes) with "
          f"{Path(browser).name}; page area was {shortfall}px short of the window")


if __name__ == "__main__":
    main()
