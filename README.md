# romapps.xyz

The download site for [ROM](https://romapps.xyz) — free Windows apps.

Static site served by GitHub Pages from `main`. No build step: `index.html`
carries its own CSS and JS inline, and pulls GSAP from a CDN with subresource
integrity. The hero is a hand-written canvas point field — there is no 3D
library on the page.

```
index.html            the whole site
404.html              styled not-found page
assets/               logo, social card, app screenshots (png + webp)
favicon.ico           root favicon
apple-touch-icon.png  browsers probe this path directly
robots.txt            allows everything, points at the sitemap
sitemap.xml           single-page sitemap
CNAME                 custom domain for GitHub Pages
scripts/make_og.py    regenerates assets/og-card.png
scripts/make_shots.py regenerates the ROM Trader screenshots
```

ROM Convert's screenshots come from `scripts/shots.ts` in its own repo, which
drives the running app over the DevTools protocol and captures the renderer.

## Apps

| App | Source | Releases |
|---|---|---|
| ROM Trader | [rom-trader](https://github.com/romanstma-cpu/rom-trader) | this repo |
| ROM Convert | [rom-convert](https://github.com/romanstma-cpu/rom-convert) | rom-convert |

## Releases, and one thing to be careful about

**Each auto-updating app needs its own releases repo.** electron-updater
resolves its feed from the *newest release in the repo*, then looks for
`latest.yml` attached to that release. Publishing a second app's release here
makes it the newest, so the other app looks for its `latest.yml` under a tag
that does not have one, and every update check fails with a 404.

That happened once: ROM Convert 1.0.0 was published here and broke ROM
Trader's updater until `make_latest` was set back on `v1.1.2`. ROM Convert now
publishes to its own repo. Keep it that way — this repo is ROM Trader's
release channel and the site's host, nothing else.

The site links to `releases/latest/download/…` for each app, so a new release
does not need a site edit — only the version and size in the download table.
