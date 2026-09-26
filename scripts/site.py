"""Stage and check the romapps.xyz GitHub Pages site. Standard library only.

    python3 scripts/site.py build _site   # copy the public files, then check them
    python3 scripts/site.py downloads     # check installer links and update feeds

`build` publishes an allowlist, not the repository. The site used to deploy
the whole checkout, which put internal notes, the Discord setup script and
tooling on romapps.xyz. Anything not listed in PUBLIC stays private; a new
public file has to be added here on purpose.

The checks after staging fail the deploy when a page links to a file that is
not published, an in-page anchor is missing, or the Polybot version, installer
names and checksum files disagree with each other.

`downloads` needs the network. It follows every GitHub release link on the
pages and confirms the two update feeds that installed apps read: ROM Trader's
`latest.yml` on this repository's latest release, and ROM Nova's on its own.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SITE_HOST = "romapps.xyz"

# Everything romapps.xyz serves. Directories are copied whole.
PUBLIC = [
    "index.html",
    "404.html",
    "code-signing-policy.html",
    "CNAME",
    "robots.txt",
    "sitemap.xml",
    "favicon.ico",
    "apple-touch-icon.png",
    "assets",
    "nova",
    "whalenova",
]

# Pages whose Polybot version must match the homepage's.
VERSIONED = ["index.html", "code-signing-policy.html", "assets/market-stage.js"]

# Update feeds that installed apps read. A 404 here means no installed copy
# can see a new version.
FEEDS = {
    "ROM Trader": ("romanstma-cpu/rom-apps", "ROM Trader"),
    "ROM Nova": ("romanstma-cpu/rom-nova", None),
}


# ---------------------------------------------------------------- build

def stage(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} already exists and is not empty; choose a new directory")
    out.mkdir(parents=True, exist_ok=True)
    for name in PUBLIC:
        src = ROOT / name
        if not src.exists():
            sys.exit(f"PUBLIC lists {name}, which does not exist")
        if src.is_dir():
            shutil.copytree(src, out / name, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
        else:
            shutil.copy2(src, out / name)


class _Refs(HTMLParser):
    """Collect link targets, element ids and metadata URLs from one page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []
        self.ids: set[str] = set()
        self.jsonld: list[str] = []
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])
        # Social cards and canonical URLs are fetched by other sites, so a
        # broken one fails silently everywhere except here.
        if tag == "meta" and a.get("property", a.get("name", "")) in (
                "og:image", "twitter:image", "og:url"):
            self.refs.append(a.get("content", ""))
        self._in_jsonld = tag == "script" and a.get("type") == "application/ld+json"

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld.append(data)


def _local_target(site: Path, page: Path, ref: str) -> tuple[Path, str] | None:
    """Map a reference to (file in the staged site, fragment), or None if external."""
    parts = urlsplit(ref)
    if parts.scheme in ("mailto", "tel", "javascript", "data"):
        return None
    if (parts.scheme or parts.netloc) and parts.netloc != SITE_HOST:
        return None
    path = unquote(parts.path) or ("/" if parts.netloc else "")
    if path == "":
        return page, parts.fragment
    target = (site / path.lstrip("/")) if path.startswith("/") or parts.netloc else (page.parent / path)
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def check(site: Path) -> list[str]:
    problems: list[str] = []
    pages = sorted(site.rglob("*.html"))
    parsed: dict[Path, _Refs] = {}
    for page in pages:
        p = _Refs()
        p.feed(page.read_text(encoding="utf-8"))
        parsed[page.resolve()] = p

    for page in pages:
        rel = page.relative_to(site)
        for ref in parsed[page.resolve()].refs:
            hit = _local_target(site, page, ref)
            if hit is None:
                continue
            target, fragment = hit
            target = target.resolve()
            if site.resolve() not in target.parents and target != site.resolve():
                problems.append(f"{rel}: {ref} points outside the site")
                continue
            if not target.is_file():
                problems.append(f"{rel}: {ref} is not published")
                continue
            if fragment and target.suffix == ".html" and fragment not in parsed[target].ids:
                problems.append(f"{rel}: {ref} has no #{fragment} on the target page")

    # Stylesheet url()s resolve against the stylesheet.
    for css in sorted((site / "assets").glob("*.css")):
        for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", css.read_text(encoding="utf-8")):
            if ref.startswith(("data:", "http:", "https:", "#")):
                continue
            if not (css.parent / ref.split("?")[0]).is_file():
                problems.append(f"{css.relative_to(site)}: url({ref}) is not published")

    # Screenshot paths the homepage script swaps in.
    for js in sorted((site / "assets").glob("*.js")):
        for ref in re.findall(r"['\"](assets/[^'\"?]+)", js.read_text(encoding="utf-8")):
            if not (site / ref).is_file():
                problems.append(f"{js.relative_to(site)}: {ref} is not published")

    problems += _check_versions(site, parsed[(site / "index.html").resolve()])

    for private in ("docs", "scripts", "discord", ".github", "README.md", "DESIGN.md"):
        if (site / private).exists():
            problems.append(f"{private} is private and must not be published")
    return problems


def _check_versions(site: Path, home: _Refs) -> list[str]:
    problems: list[str] = []
    try:
        version = json.loads("".join(home.jsonld))["softwareVersion"]
    except (ValueError, KeyError):
        return ["index.html: the SoftwareApplication JSON-LD has no softwareVersion"]
    for name in VERSIONED:
        text = (site / name).read_text(encoding="utf-8")
        for other in sorted(set(re.findall(r"(?<![\d.])2\.\d+\.\d+(?![\d.])", text)) - {version}):
            problems.append(f"{name}: mentions Polybot {other}, but the homepage says {version}")

    win = f"ROM.PolyBot-Setup-{version}.exe"
    mac = f"ROM.PolyBot-{version}-arm64.dmg"
    for sums, installer in ((f"assets/SHA256SUMS-Polybot-{version}.txt", win),
                            (f"assets/POLYBOT-MAC-CHECKSUMS-{version}.txt", mac)):
        path = site / sums
        if not path.is_file():
            problems.append(f"{sums} is missing for the current version")
        elif not re.search(rf"^[0-9A-Fa-f]{{64}}\s+\*?{re.escape(installer)}\s*$",
                           path.read_text(encoding="utf-8"), re.M):
            problems.append(f"{sums} has no SHA-256 line for {installer}")
        if not any(r.endswith("/" + installer) for r in home.refs):
            problems.append(f"index.html does not link {installer}")
    return problems


# ---------------------------------------------------------------- downloads

def _open(url: str, *, api: bool = False):
    headers = {"User-Agent": "romapps-site-check"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    else:
        headers["Range"] = "bytes=0-1023"  # proves the file is there without downloading it
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def downloads() -> list[str]:
    problems: list[str] = []
    urls: set[str] = set()
    for name in ("index.html", "code-signing-policy.html"):
        p = _Refs()
        p.feed((ROOT / name).read_text(encoding="utf-8"))
        urls |= {r for r in p.refs if re.match(r"https://github\.com/[^/]+/[^/]+/releases/.*download/", r)}
    for url in sorted(urls):
        try:
            with _open(url) as r:
                print(f"ok    {r.status}  {url}")
        except urllib.error.HTTPError as e:
            problems.append(f"{url} returned {e.code}")
        except urllib.error.URLError as e:
            problems.append(f"{url} failed: {e.reason}")

    for app, (repo, expected) in FEEDS.items():
        feed = f"https://github.com/{repo}/releases/latest/download/latest.yml"
        try:
            with _open(feed) as r:
                body = r.read().decode("utf-8", "replace")
            if "version:" not in body:
                problems.append(f"{app}: {feed} is not an update feed")
            else:
                print(f"ok    {app} update feed")
        except urllib.error.HTTPError as e:
            problems.append(f"{app}: {feed} returned {e.code}; installed copies cannot see updates")
        if expected:
            try:
                with _open(f"https://api.github.com/repos/{repo}/releases/latest", api=True) as r:
                    latest = json.load(r)
                if expected not in (latest.get("name") or ""):
                    problems.append(
                        f"{app}: the latest release on {repo} is {latest.get('tag_name')} "
                        f"({latest.get('name')}). Mark the newest {expected} release as latest "
                        f"(gh release edit <tag> --latest) and publish other apps with --latest=false.")
            except urllib.error.HTTPError as e:
                problems.append(f"{app}: GitHub API returned {e.code}")
    return problems


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "build":
        out = Path(argv[1])
        stage(out)
        problems = check(out)
        files = sum(1 for p in out.rglob("*") if p.is_file())
        print(f"staged {files} files into {out}")
    elif argv == ["downloads"]:
        problems = downloads()
    else:
        print(__doc__)
        return 2
    for p in problems:
        print(f"::error::{p}" if os.environ.get("GITHUB_ACTIONS") else f"FAIL  {p}")
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
