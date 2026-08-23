# romapps.xyz

The download site for [ROM](https://romapps.xyz) — small, free Windows apps.

Static site served by GitHub Pages from `main`. No build step: `index.html`
carries its own CSS and JS inline, and pulls GSAP and Three.js from CDNs with
subresource integrity.

```
index.html            the whole site
404.html              styled not-found page
assets/rom-icon.png   logo (256px)
favicon.ico           root favicon
apple-touch-icon.png  browsers probe this path directly
robots.txt            allows everything, points at the sitemap
sitemap.xml           single-page sitemap
CNAME                 custom domain for GitHub Pages
```

## Releases

Application installers are published as GitHub releases on this repo. The site
links to the stable URL
`releases/latest/download/ROM-Trader-Setup.exe`, and ROM Trader's auto-updater
reads `latest.yml` from the same release.

ROM Trader's source is at
[romanstma-cpu/rom-trader](https://github.com/romanstma-cpu/rom-trader).
