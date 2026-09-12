# ROM Apps

The public catalog at https://romapps.xyz is served by GitHub Pages from `main`. The homepage is static HTML and CSS, with no build step or client-side framework. It lists ROM Polybot, Nova, Trader and Scribe. ROM Convert is no longer listed.

The independently built Nova web application lives under `nova/`; preserve that directory when updating the homepage. `CNAME` keeps the existing custom domain.

## Polybot downloads

The current Windows download is `assets/ROM-Polybot-Setup-2.16.0.exe`, with its SHA-256 in `assets/SHA256SUMS-Polybot-2.16.0.txt`. macOS 15 downloads for Apple Silicon and Intel are attached to the `polybot-mac-7` prerelease, with hashes in `assets/POLYBOT-MAC-CHECKSUMS-2.16.0.txt`. Versioned filenames prevent stale browser caches from serving a different build under the same name. The corresponding source and release notes are maintained in the ROM Polybot desktop workspace; the legacy Python code under `polybot/` is not the source of this desktop release.

When publishing a new build, update the homepage metadata, download link, screenshot and verification page together. Verify the downloaded artifact against the locally built installer before announcing availability.

## Preserve other update channels

This repository’s latest GitHub release is ROM Trader’s update feed. Do not make another app’s release the latest: installed Trader builds expect their own `latest.yml` there. Nova and Scribe use their respective repositories for Windows releases. Polybot is served from versioned site assets, independently of that release feed.

## Page validation

Check local links and anchors, image loading, narrow-screen layout, product/version references and download integrity. There are no external font, animation or analytics scripts on the homepage.
