"""Stage and check the romapps.xyz GitHub Pages site. Standard library only.

    python3 scripts/site.py build _site   # copy the public files, then check them
    python3 scripts/site.py changelog     # regenerate changelog.html from the notes
    python3 scripts/site.py downloads     # check installer links and update feeds

`build` publishes an allowlist, not the repository. The site used to deploy
the whole checkout, which put internal notes, the Discord setup script and
tooling on romapps.xyz. Anything not listed in PUBLIC stays private; a new
public file has to be added here on purpose.

The checks after staging fail the deploy when a page links to a file that is
not published, an in-page anchor is missing, the Polybot version, installer
names and checksum files disagree with each other, or changelog.html is not
what `changelog` would write from assets/RELEASE-*.md.

`downloads` needs the network. It follows every GitHub release link on the
pages and confirms the update feeds that installed apps read: ROM Nova's on
its own repository, and (as a warning only, since Trader is retired) ROM
Trader's `latest.yml` on this repository's latest release.
"""
from __future__ import annotations

import html
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
    "changelog.html",
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

# Update feeds that installed apps read: (repository, name the latest release
# must carry, whether a problem fails the run). A 404 here means no installed
# copy can see a new version. Trader is retired and will not ship again, so
# its feed only warns; Nova is maintained, so its feed must work.
FEEDS = {
    "ROM Nova": ("romanstma-cpu/rom-nova", None, True),
    "ROM Trader": ("romanstma-cpu/rom-apps", "ROM Trader", False),
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
    problems += _check_changelog(site)

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


# ---------------------------------------------------------------- changelog

_NOTES = re.compile(r"^RELEASE-(\d+(?:\.\d+)+)\.md$")
_SUMS = {
    "Windows": re.compile(r"^SHA256SUMS-Polybot-(\d+\.\d+\.\d+)\.txt$"),
    "Apple Silicon": re.compile(r"^POLYBOT-MAC-CHECKSUMS-(\d+\.\d+\.\d+)\.txt$"),
}


def _full(version: str) -> str:
    """2.6 -> 2.6.0, so notes and checksum files for one release line up."""
    return version if version.count(".") >= 2 else version + ".0"


def _releases(assets: Path) -> dict[str, dict]:
    """Every Polybot version with release notes or checksum files, keyed by x.y.z."""
    out: dict[str, dict] = {}
    for path in assets.iterdir():
        if m := _NOTES.match(path.name):
            out.setdefault(_full(m.group(1)), {"sums": {}})["notes"] = path
        for label, pattern in _SUMS.items():
            if m := pattern.match(path.name):
                out.setdefault(m.group(1), {"sums": {}})["sums"][label] = path.name
    return out


def _inline(text: str) -> str:
    parts = text.split("`")
    if len(parts) % 2 == 0:  # an unmatched backtick is literal
        parts[-2:] = ["`".join(parts[-2:])]
    out = []
    for i, part in enumerate(parts):
        esc = html.escape(part, quote=False)
        out.append(f"<code>{esc}</code>" if i % 2 else
                   re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc))
    return "".join(out)


def _render_notes(md: str) -> str:
    """The Markdown the release notes use: ## headings, paragraphs, - lists."""
    lines = md.replace("\r\n", "\n").split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]  # the page supplies its own heading
    blocks: list[str] = []
    para: list[str] = []
    items: list[list[str]] = []

    def flush() -> None:
        if para:
            blocks.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            lis = "".join(f"<li>{_inline(' '.join(i))}</li>" for i in items)
            blocks.append(f"<ul>{lis}</ul>")
            items.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("## "):
            flush()
            blocks.append(f"<h3>{_inline(line[3:])}</h3>")
        elif line.startswith("- "):
            if para:
                flush()
            items.append([line[2:]])
        elif items and raw.startswith(" "):
            items[-1].append(line)  # a wrapped list item
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return "\n".join(blocks)


def render_changelog(root: Path) -> str:
    """changelog.html, built from assets/RELEASE-*.md and the checksum files."""
    home = _Refs()
    home.feed((root / "index.html").read_text(encoding="utf-8"))
    current = json.loads("".join(home.jsonld))["softwareVersion"]
    releases = _releases(root / "assets")
    order = sorted(releases, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)

    index = "".join(f'<a href="#v{v}">{v}</a>' for v in order)
    entries = []
    for v in order:
        rel = releases[v]
        badge = ' <span class="release-current">CURRENT</span>' if v == current else ""
        notes = (_render_notes(rel["notes"].read_text(encoding="utf-8")) if "notes" in rel else
                 "<p>No release notes were published for this version.</p>")
        sums = " ".join(f'<a href="assets/{name}">{label}</a>'
                        for label, name in sorted(rel["sums"].items(), key=lambda kv: kv[0] != "Windows"))
        files = f'\n        <p class="release-files">SHA-256 checksums: {sums}</p>' if sums else ""
        entries.append(
            f'      <section class="release" id="v{v}" aria-labelledby="v{v}-title">\n'
            f'        <h2 id="v{v}-title">Polybot {v}{badge}</h2>\n'
            f'        {notes}{files}\n'
            f'      </section>')

    return f"""<!doctype html>
<!-- Generated by `python3 scripts/site.py changelog` from assets/RELEASE-*.md
     and the checksum files. Edit those, not this page. -->
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ROM Polybot release notes — ROM Apps</title>
  <meta name="description" content="What changed in every ROM Polybot release, newest first, with SHA-256 checksums for each version's installers.">
  <meta name="theme-color" content="#090f19">
  <link rel="canonical" href="https://romapps.xyz/changelog.html">
  <link rel="icon" type="image/x-icon" href="favicon.ico">
  <link rel="apple-touch-icon" href="apple-touch-icon.png">
  <link rel="preload" href="assets/fonts/space-grotesk-latin-variable.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="assets/market-stage.css?v=viewer-2">
</head>
<body>
  <a class="skip-link" href="#main">Skip to main content</a>
  <header class="site-header">
    <nav class="wrap nav" aria-label="Main navigation">
      <a class="brand" href="/" aria-label="ROM Apps home"><img src="assets/rom-icon-nav.png" width="36" height="36" alt=""><span>ROM<span class="brand-apps"> APPS</span></span></a>
      <div class="nav-links"><a href="/#polybot">Polybot</a><a href="/#nova-h">Nova</a><a class="nav-cta" href="/#download-polybot">Get Polybot <span aria-hidden="true">↗</span></a></div>
    </nav>
  </header>

  <main id="main" tabindex="-1">
    <div class="wrap doc">
      <p class="eyebrow">ROM POLYBOT / RELEASE NOTES</p>
      <h1>What changed, version by version.</h1>
      <p class="doc-intro">Every published ROM Polybot release, newest first, with the SHA-256 checksum files for its installers. The current version is {current}. Release notes describe what changed; they do not show that any version trades profitably.</p>
      <nav class="doc-toc" aria-label="Related pages"><a href="/#download-polybot">Download {current}</a><a href="code-signing-policy.html">How to verify a download</a><a href="https://github.com/romanstma-cpu/rom-apps/releases">All installers on GitHub</a></nav>
      <nav class="version-index" aria-label="Versions">{index}</nav>

{chr(10).join(entries)}
    </div>
  </main>

  <footer class="footer"><div class="wrap footer-inner"><a class="brand" href="/" aria-label="ROM Apps home"><img src="assets/rom-icon-nav.png" width="32" height="32" loading="lazy" alt=""><span>ROM<span class="brand-apps"> APPS</span></span></a><div class="footer-links"><a href="changelog.html">Release notes</a><a href="code-signing-policy.html">Verification &amp; support</a><a href="https://github.com/romanstma-cpu/rom-apps">GitHub <span aria-hidden="true">↗</span></a></div><small>© 2026 ROM Apps</small></div></footer>
</body>
</html>
"""


def _check_changelog(site: Path) -> list[str]:
    page = site / "changelog.html"
    if page.read_text(encoding="utf-8") != render_changelog(site):
        return ["changelog.html is out of date; run python3 scripts/site.py changelog"]
    return []


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


def downloads() -> tuple[list[str], list[str]]:
    """Return (problems, warnings)."""
    problems: list[str] = []
    warnings: list[str] = []
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

    for app, (repo, expected, required) in FEEDS.items():
        issues = problems if required else warnings
        feed = f"https://github.com/{repo}/releases/latest/download/latest.yml"
        try:
            with _open(feed) as r:
                body = r.read().decode("utf-8", "replace")
            if "version:" not in body:
                issues.append(f"{app}: {feed} is not an update feed")
            else:
                print(f"ok    {app} update feed")
        except urllib.error.HTTPError as e:
            issues.append(f"{app}: {feed} returned {e.code}; installed copies cannot see updates")
        if expected:
            try:
                with _open(f"https://api.github.com/repos/{repo}/releases/latest", api=True) as r:
                    latest = json.load(r)
                if expected not in (latest.get("name") or ""):
                    issues.append(
                        f"{app}: the latest release on {repo} is {latest.get('tag_name')} "
                        f"({latest.get('name')}). Mark the newest {expected} release as latest "
                        f"(gh release edit <tag> --latest) and publish other apps with --latest=false.")
            except urllib.error.HTTPError as e:
                issues.append(f"{app}: GitHub API returned {e.code}")
    return problems, warnings


# ---------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    warnings: list[str] = []
    if len(argv) == 2 and argv[0] == "build":
        out = Path(argv[1])
        stage(out)
        problems = check(out)
        files = sum(1 for p in out.rglob("*") if p.is_file())
        print(f"staged {files} files into {out}")
    elif argv == ["changelog"]:
        page = ROOT / "changelog.html"
        page.write_text(render_changelog(ROOT), encoding="utf-8")
        print(f"wrote {page.relative_to(ROOT)} with {len(_releases(ROOT / 'assets'))} versions")
        return 0
    elif argv == ["downloads"]:
        problems, warnings = downloads()
    else:
        print(__doc__)
        return 2
    ci = bool(os.environ.get("GITHUB_ACTIONS"))
    for w in warnings:
        print(f"::warning::{w}" if ci else f"WARN  {w}")
    for p in problems:
        print(f"::error::{p}" if ci else f"FAIL  {p}")
    print(f"{len(problems)} problem(s), {len(warnings)} warning(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
