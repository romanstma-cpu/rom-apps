// The ROM Discord server, as data.
//
// setup.mjs applies this to a real server through the Discord API. Edit here,
// re-run, and it converges — nothing is created twice.
//
// Deliberately small. A new server with twenty channels reads as abandoned on
// day one; seven that people actually post in reads as alive. Split #support
// into per-app channels when the traffic justifies it, not before.

// Matches the site: signal mint and action blue from assets/market-stage.css.
// Amber is kept for the safety notice so it reads as a warning.
export const BRAND = {
  mint: "91e2c8",
  blue: "b7d7ff",
  amber: "f59e0b",
};

export const SITE = "https://romapps.xyz";
export const GH = "https://github.com/romanstma-cpu";

/** Hoisted roles, created top-down. The bot's own role is managed by Discord. */
export const ROLES = [
  {
    name: "Maintainer",
    color: BRAND.mint,
    hoist: true,
    mentionable: true,
    // No permission bits set here on purpose: grant these by hand in the UI so
    // a config file in a public repo can never widen someone's access.
    permissions: "0",
  },
  {
    name: "Contributor",
    color: BRAND.blue,
    hoist: true,
    mentionable: true,
    permissions: "0",
  },
];

/**
 * Channels, in order, grouped by category.
 *
 * `readOnly` denies SEND_MESSAGES to @everyone but leaves reactions and thread
 * replies alone, so announcements stay clean without feeling like a wall.
 */
export const STRUCTURE = [
  {
    category: "START HERE",
    channels: [
      {
        name: "welcome",
        topic: "What ROM is, the rules, and how to stay safe. Start here.",
        readOnly: true,
        posts: ["about", "rules", "safety", "honesty"],
      },
      {
        name: "announcements",
        topic: "New releases and anything that changes how an app behaves.",
        readOnly: true,
        // Announcement channels let *other* servers follow this one. They exist
        // only on Community servers, and Discord rejects the type outright on a
        // plain one rather than degrading — so setup.mjs falls back to a normal
        // text channel. Nothing is lost day to day; flip it in Edit Channel
        // once Community is enabled.
        announcement: true,
      },
    ],
  },
  {
    category: "HELP & FEEDBACK",
    channels: [
      {
        name: "support",
        topic:
          "Stuck on any ROM app? Ask here. Say which app and which version — it is in Settings, or the installer filename.",
        posts: ["supportHowTo"],
      },
      {
        name: "bugs-and-requests",
        topic:
          "Something broken or missing? Post it here. Confirmed bugs get moved to GitHub Issues so they are actually tracked.",
        posts: ["bugsHowTo"],
      },
      {
        name: "showcase",
        topic: "Built something with a ROM app, or found a setup that works? Show it.",
      },
    ],
  },
  {
    category: "COMMUNITY",
    channels: [
      { name: "general", topic: "Anything ROM-adjacent." },
      {
        name: "github",
        topic: "Automated feed: commits, releases and issues. Add the webhook in channel settings.",
        readOnly: true,
      },
    ],
  },
];

/* ------------------------------------------------------------------ copy */

const apps = [
  ["ROM Polybot", "Polymarket US desktop app for Windows and Apple Silicon Macs. Scan markets, practice with simulated funds, and inspect the evidence before you allow live orders.", `${SITE}/#download-polybot`],
  ["ROM Nova", "Solana research terminal. Runs in your browser, no install; a Windows app is also available.", `${GH}/rom-nova`],
  ["ROM Trader", "Kalshi strategy tester. Starts in dry-run; its published study found every measured strategy lost after fees.", `${GH}/rom-trader`],
];

export const POSTS = {
  about: {
    color: BRAND.mint,
    title: "ROM — apps, no strings",
    description: [
      "Free trading tools built by one person. No telemetry, no upsell. Download and run.",
      "",
      apps.map(([n, d, u]) => `**${n}** — ${d}\n${u}`).join("\n\n"),
      "",
      `**Everything** → ${SITE}`,
      `**Try Nova right now, no install** → ${SITE}/nova/`,
      "",
      "Nova and Trader are open source under MIT. Read the code, fork it, or tell me it is wrong.",
    ].join("\n"),
  },

  rules: {
    color: BRAND.mint,
    title: "Rules",
    description: [
      "**1. Be decent.** Disagree about code all you like. Not about people.",
      "",
      "**2. No profit claims, no signal selling, no paid groups.** No ROM app has demonstrated a profitable edge, and each one says so in its own docs. Anyone here promising returns is either mistaken or working you.",
      "",
      "**3. No unsolicited DMs offering help.** Support happens in public channels where others can check it. See the safety notice below.",
      "",
      "**4. Bugs belong on GitHub.** Post here first if you like, but confirmed bugs get moved to Issues so they are tracked instead of scrolling away.",
      "",
      "**5. Right channel, roughly.** Nobody will shout at you for getting it wrong.",
      "",
      "**6. No piracy, cracks, malware, or scraped credentials.**",
      "",
      "Breaking 2 or 3 gets you removed without much conversation. The rest is a nudge.",
    ].join("\n"),
  },

  safety: {
    color: BRAND.amber,
    title: "Read this before anyone DMs you",
    description: [
      "Trading tools attract people who want your keys. Some of this will happen here. None of it is subtle once you know the shape of it.",
      "",
      "**Nobody from ROM will ever DM you first.** Not for support, not to verify anything, not about a giveaway.",
      "",
      "**Nobody will ever ask for your API key, private key, seed phrase, wallet, or password.** There is no situation where that is a real request. Polybot encrypts your Polymarket US keys on your own computer with a key held in the operating system's credential store. ROM Trader stores your Kalshi key encrypted with Windows DPAPI and sends it only to Kalshi.",
      "",
      `**Download only from ${SITE} or the GitHub releases linked above.** Every release publishes a SHA-256 so you can check the file is byte-for-byte the one that was built. The steps are at ${SITE}/code-signing-policy.html`,
      "",
      "**Your computer will warn you.** The installers are not code-signed yet and the Mac build is not Apple-notarized, so Windows says *unknown publisher* and macOS says *unidentified developer*. That warning is about a missing signature, not about anything found in the file — and it is exactly why the checksums are published.",
      "",
      "See someone impersonating ROM or asking for keys? Screenshot it and post in #general. Do not engage.",
    ].join("\n"),
  },

  honesty: {
    color: BRAND.blue,
    title: "What these tools do and do not claim",
    description: [
      "**ROM Polybot** starts paused. Practice uses simulated funds, and its fills can differ from real exchange execution. Live orders need your own Polymarket US keys and an explicit switch, and profitable live returns have not been demonstrated.",
      "",
      "**ROM Nova** reads real Solana data from public sources. The parts it cannot get for free, wallet activity and smart-money scoring, run on a simulation that is labelled wherever it appears. Nova places no trades.",
      "",
      "**ROM Trader** has no demonstrated edge — measured, written down, and published in its own `docs/STRATEGY-FINDINGS.md`. It ships in dry-run and places no real orders until you supply your own key and explicitly enable live mode.",
      "",
      "**None of them is financial advice** and none is a prediction engine. If that disappoints you, that is the honest version, and it will keep being the honest version here.",
    ].join("\n"),
  },

  supportHowTo: {
    color: BRAND.blue,
    title: "Getting a useful answer fast",
    description: [
      "Include these and you will usually get a real answer first time:",
      "",
      "• **Which app** and **which version** — Settings shows it, or read it off the installer.",
      "• **What you expected** and **what happened instead.**",
      "• **The exact error text** if there is one. A screenshot of the Logs page beats a description of it.",
      "• Windows or macOS version, if it looks like an install or permissions problem.",
      "",
      "Never paste an API key, private key or seed phrase — not even a partial one, not even to prove a point. If you already have, revoke it at Polymarket US or Kalshi now and generate a new one.",
    ].join("\n"),
  },

  bugsHowTo: {
    color: BRAND.blue,
    title: "Reporting a bug",
    description: [
      "Post it here and it will get read. If it is reproducible it gets moved to GitHub Issues on the right repo, because a thread here scrolls away and an issue does not.",
      "",
      "**Most useful thing you can give:** the steps that reproduce it. Even 'it happens every time I click X with Y enabled' is enough to start.",
      "",
      "Feature requests are welcome in the same channel. Say what you are trying to *do*, not just what button you want — the underlying problem is often solvable a better way.",
      "",
      `Issues: [Polybot](${GH}/rom-apps/issues) · [Nova](${GH}/rom-nova/issues) · [Trader](${GH}/rom-trader/issues)`,
    ].join("\n"),
  },
};
