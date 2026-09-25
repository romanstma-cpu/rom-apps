# ROM Apps design context

ROM Apps is a marketing site for independent trading tools. Its primary job is to help someone understand ROM Polybot and choose the correct desktop download. Nova, Trader, and Scribe form a smaller secondary shelf. Visitors include phone users who need a simple way to share the download page with a computer. The Polymarket US referral must remain noticeable and disclose that ROM may receive a reward.

## Visual direction

The actual Polybot workspace is the signature artifact. The homepage gives that screenshot one large, framed appearance in the hero; other product screenshots remain small and secondary. The page should feel like a calm trading desk: deep navy space, precise hairline rules, restrained mint status accents, and broad icy-blue actions. Grid and light-sweep decoration frame the real product rather than posing as market data. Do not fabricate trading results or imply profitable live returns have been demonstrated.

## Runtime ownership

The homepage structure and metadata live in `index.html`. `assets/market-stage.css` owns all homepage styling and the `:root` tokens: background `#090f19`, surface `#101b29`, text `#f3f7fd`, secondary text `#b0bfd0`, action blue `#b7d7ff`, and signal mint `#91e2c8`. Display type uses the platform display stack; body copy uses the platform UI stack; compact metadata uses a monospace stack. `assets/market-stage.js` owns motion replay, once-only section reveals, and mobile sharing. The separate app pages and Nova application keep their own styling.

## Content hierarchy

The first screen states Polybot's purpose, presents one download action, keeps the ROMANR offer visible with its disclosure, and shows a real app screenshot. The next section offers equal Windows and Apple Silicon choices, checksums, release notes, and installation guidance. A short Connect → Practice → Inspect sequence explains the workflow. Smaller cards introduce Nova, Trader, and Scribe. FAQ disclosures hold the longer requirements and risk explanations. Preserve links to the official Polymarket US API and referral pages, the latest verified installers, and checksums.

## Motion and access

The hero entrance and one light sweep run once. A replay button restarts that short moment. Lower sections reveal only after entering view, with content visible by default if JavaScript is unavailable. Animation moves opacity and transforms only; reduced-motion disables it and hides replay. Native links, buttons, details, visible focus, readable contrast, and a 320px mobile layout remain baseline requirements. Phone visitors can share the download page; Polybot itself remains a desktop app.
