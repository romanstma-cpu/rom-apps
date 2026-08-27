// The ROM Discord server, as data.
//
// setup.mjs applies this to a real server through the Discord API. Edit here,
// re-run, and it converges — nothing is created twice.
//
// Deliberately small. A new server with twenty channels reads as abandoned on
// day one; seven that people actually post in reads as alive. Split #support
// into per-app channels when the traffic justifies it, not before.

export const BRAND = {
  violet: "7c3aed",
  cyan: "38e1ff",
  amber: "f59e0b",
};

export const SITE = "https://romapps.xyz";
export const GH = "https://github.com/romanstma-cpu";

/**
 * Server identity.
 *
 * `icon` is relative to this file. Discord takes PNG, JPEG or GIF as a base64
 * data URI; 256x256 is accepted and 512 is the recommended source size.
 *
 * setup.mjs only applies the icon when the server has none, so a nicer one
 * uploaded by hand later is never clobbered by a routine re-run. Pass
 * `--rebrand` to overwrite it deliberately.
 */
export const SERVER = {
  name: "ROM Apps",
  icon: "../assets/rom-icon.png",
};

/** Hoisted roles, created top-down. The bot's own role is managed by Discord. */
export const ROLES = [
  {
    name: "Maintainer",
    color: BRAND.violet,
    hoist: true,
    mentionable: true,
    // No permission bits set here on purpose: grant these by hand in the UI so
    // a config file in a public repo can never widen someone's access.
    permissions: "0",
  },
  {
    name: "Contributor",
    color: BRAND.cyan,
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
  ["ROM Trader", "Automated momentum bot for Kalshi prediction markets. Dry-run by default.", `${GH}/rom-trader`],
  ["ROM Convert", "Convert video, audio and images on your own PC. Bundled ffmpeg, nothing uploaded.", `${GH}/rom-convert`],
  ["ROM Scribe", "Transcribe and subtitle anything, offline. No per-minute pricing.", `${GH}/rom-scribe`],
  ["ROM Nova", "On-chain intelligence terminal. Runs in your browser — no install.", `${GH}/rom-nova`],
  ["ROM Polybot", "Open Polymarket trading bot in plain, readable Python.", `${GH}/rom-apps/tree/main/polybot`],
];

export const POSTS = {
  about: {
    color: BRAND.violet,
    title: "ROM — apps, no strings",
    description: [
      "Free Windows apps built by one person. No accounts, no subscriptions, no telemetry, no upsell. Download and run.",
      "",
      apps.map(([n, d, u]) => `**${n}** — ${d}\n${u}`).join("\n\n"),
      "",
      `**Everything** → ${SITE}`,
      `**Try Nova right now, no install** → ${SITE}/nova/`,
      "",
      "All five are open source under MIT. Read the code, fork it, or tell me it is wrong.",
    ].join("\n"),
  },

  rules: {
    color: BRAND.violet,
    title: "Rules",
    description: [
      "**1. Be decent.** Disagree about code all you like. Not about people.",
      "",
      "**2. No profit claims, no signal selling, no paid groups.** ROM Trader ships in dry-run and has no demonstrated edge — that is written into its own docs. Anyone here promising returns is either mistaken or working you.",
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
      "**Nobody will ever ask for your API key, private key, seed phrase, wallet, or password.** There is no situation where that is a real request. ROM Trader stores your Kalshi key encrypted on your own machine with Windows DPAPI, never shows it back to the interface, and sends it only to Kalshi.",
      "",
      `**Download only from ${SITE} or the GitHub releases linked above.** Every release publishes a SHA-256 so you can check the file is byte-for-byte the one that was built. The command is on the site under *IS THIS SAFE?*`,
      "",
      "**Windows will warn you.** The installers are not code-signed yet, so SmartScreen says *unknown publisher*. That warning is about a missing signature, not about anything found in the file — and it is exactly why the checksums are published.",
      "",
      "See someone impersonating ROM or asking for keys? Screenshot it and post in #general. Do not engage.",
    ].join("\n"),
  },

  honesty: {
    color: BRAND.cyan,
    title: "What these tools do and do not claim",
    description: [
      "**ROM Trader** is an automated momentum bot. It has no demonstrated edge — measured, written down, and published in its own `docs/STRATEGY-FINDINGS.md`. It ships in dry-run and places no real orders until you supply your own key and explicitly enable live mode. It is a tool for testing an idea honestly, not a machine that prints money.",
      "",
      "**ROM Nova** runs on clearly-labelled simulated data. Every screen says so. It is a demonstration of a scoring engine, not a live feed, and its paper trading is a sandbox.",
      "",
      "**Neither is financial advice** and neither is a prediction engine. If that disappoints you, that is the honest version, and it will keep being the honest version here.",
    ].join("\n"),
  },

  supportHowTo: {
    color: BRAND.cyan,
    title: "Getting a useful answer fast",
    description: [
      "Include these and you will usually get a real answer first time:",
      "",
      "• **Which app** and **which version** — Settings shows it, or read it off the installer.",
      "• **What you expected** and **what happened instead.**",
      "• **The exact error text** if there is one. A screenshot of the Logs page beats a description of it.",
      "• Windows version, if it looks like an install or permissions problem.",
      "",
      "Never paste an API key, private key or seed phrase — not even a partial one, not even to prove a point. If you already have, revoke it at Kalshi now and generate a new one.",
    ].join("\n"),
  },

  bugsHowTo: {
    color: BRAND.cyan,
    title: "Reporting a bug",
    description: [
      "Post it here and it will get read. If it is reproducible it gets moved to GitHub Issues on the right repo, because a thread here scrolls away and an issue does not.",
      "",
      "**Most useful thing you can give:** the steps that reproduce it. Even 'it happens every time I click X with Y enabled' is enough to start.",
      "",
      "Feature requests are welcome in the same channel. Say what you are trying to *do*, not just what button you want — the underlying problem is often solvable a better way.",
      "",
      `Repos: ${apps.map(([n, , u]) => `[${n.replace("ROM ", "")}](${u})`).join(" · ")}`,
    ].join("\n"),
  },
};
