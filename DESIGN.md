# ROM Apps design context

ROM Apps is a marketing site for independent trading tools. Its primary job is to help someone understand ROM Polybot and choose the correct desktop download. Nova and Trader form a smaller secondary shelf. Visitors include phone users who need a simple way to share the download page with a computer. The Polymarket US referral must remain noticeable and disclose that ROM may receive a reward.

## Visual direction

The concept is command: monumental typography contrasts with precise desktop controls. The signature artifact is one interactive theater of actual Polybot screenshots, framed by a large POLYBOT wordmark, orbit hairlines, and restrained mint/blue light. Visitors switch between Workspace, Practice & risk, and Evidence at their own pace. Other products remain secondary. The page should feel like a calm trading desk: deep navy space, precise rules, and broad icy-blue actions. Decoration never poses as market data. Do not fabricate trading results or imply profitable live returns have been demonstrated. Practice shows strategy setup; Evidence shows the initial state with zero settled samples.

## Runtime ownership

The homepage structure and metadata live in `index.html`. `assets/market-stage.css` owns all homepage styling and the `:root` tokens: background `#090f19`, surface `#101b29`, text `#f3f7fd`, secondary text `#b0bfd0`, action blue `#b7d7ff`, and signal mint `#91e2c8`. Display type uses self-hosted Space Grotesk (22 KB, SIL OFL, `assets/fonts/`); body copy uses the platform UI stack; metadata uses monospace. `assets/market-stage.js` owns screenshot selection, decorative pointer lighting, motion replay, once-only reveals, and mobile sharing. Other app pages and Nova keep their own styling. No framework or animation dependency is required.

## Content hierarchy

The first screen states Polybot's purpose, presents one download action, keeps the ROMANR offer visible with its disclosure, and shows a real app screenshot. The next section offers equal Windows and Apple Silicon choices, checksums, release notes, and installation guidance. A short Connect → Practice → Inspect sequence explains the workflow. Two smaller cards introduce Nova and Trader. FAQ disclosures hold the longer requirements and risk explanations. Preserve links to the official Polymarket US API and referral pages, the latest verified installers, and checksums.

## Motion and access

The hero entrance and one light sweep run once. A replay button restarts that short moment. Native toggle buttons select screenshots with Enter/Space and expose `aria-pressed`; there is no automatic cycling. The next image loads offscreen before changing the fixed 8:5 frame, alt text, caption and full-size links together. A failed image leaves the last working view intact; the latest click wins over slower requests. Without JavaScript the overview remains linked and inert controls are hidden. Pointer movement shifts only the decorative light on precise-pointer devices. Motion respects reduced-motion and never moves hit targets. Lower sections reveal once, with content visible by default without JavaScript. Native scrolling, links, buttons, details, visible focus, readable contrast, and a 320px mobile layout remain baseline requirements. Phone visitors can share the page; Polybot itself remains a desktop app.
