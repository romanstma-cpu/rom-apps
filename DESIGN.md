# ROM Apps design context

ROM Apps is a marketing site for independent trading tools. Its primary job is to help someone understand ROM Polybot and choose the correct desktop download. Nova, Trader, and Scribe form a smaller secondary shelf. Visitors include phone users who need a simple way to share the download page with a computer. The Polymarket US referral must remain noticeable and disclose that ROM may receive a reward.

## Visual direction

The direction is a quiet, product-first trading desk: one strong headline, restrained mint type, a clear icy-blue action, and one interactive preview of real Polybot screens. Visitors switch between Workspace, Practice & risk, and Evidence at their own pace. Avoid giant decorative wordmarks, orbit lines, multiple frame headers, numbered screenshot labels, and repeated setup sections. The user explicitly asked for less clutter after the more theatrical design. Keep useful information easy to find through clear native disclosures. Do not fabricate trading results or imply profitable live returns have been demonstrated. Practice shows strategy setup; Evidence shows the initial state with zero settled samples.

## Runtime ownership

The homepage structure and metadata live in `index.html`. `assets/market-stage.css` owns all homepage styling and the `:root` tokens: background `#090f19`, surface `#101b29`, text `#f3f7fd`, secondary text `#b0bfd0`, action blue `#b7d7ff`, and signal mint `#91e2c8`. Display type uses self-hosted Space Grotesk (22 KB, SIL OFL, `assets/fonts/`); body copy uses the platform UI stack; metadata uses monospace. `assets/market-stage.js` owns screenshot selection, once-only reveals, and mobile sharing. Other app pages and Nova keep their own styling. No framework or animation dependency is required.

## Content hierarchy

The hero states Polybot's purpose, presents one download action, keeps the ROMANR offer visible with its reward disclosure, and shows a real app screenshot with a short caption. The download section combines setup guidance with equal Windows and Apple Silicon choices. Version notes and the official API link stay visible. Installation guidance and checksums sit in a clearly labeled disclosure; unsigned/not-notarized status stays visible beside downloads. Nova, Trader, and Scribe use compact expandable rows: opening one reveals its actual screenshot, product limitations, and download/source links. Limitations precede those actions. FAQ disclosures hold detailed requirements, variable referral terms and risk explanations. Preserve official URLs, verified installers and checksums. The former `#how-it-works` anchor points to the consolidated setup paragraph.

## Motion and access

The hero enters once; screenshot switching uses a short fade. No looping, pointer lighting, or replay controls. Native toggle buttons select screenshots with Enter/Space and expose `aria-pressed`; there is no automatic cycling. The next image loads offscreen before changing the fixed 8:5 frame, alt text, caption and full-size links together. A failed image leaves the last working view intact; the latest click wins over slower requests. Without JavaScript the overview remains linked, inert controls are hidden, and all native disclosures work. Motion respects reduced-motion and never moves hit targets. Lower sections reveal once, with content visible by default without JavaScript. Native scrolling, links, buttons, details, visible focus, readable contrast, and a 320px mobile layout remain baseline requirements. Phone visitors can share the page; Polybot itself remains a desktop app.
