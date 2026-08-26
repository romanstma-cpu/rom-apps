#!/usr/bin/env node
// Builds the ROM Discord server from server.config.mjs.
//
//   $env:DISCORD_BOT_TOKEN = "..."      # bot token, NOT the client secret
//   $env:DISCORD_GUILD_ID  = "..."      # right-click the server -> Copy Server ID
//   node discord/setup.mjs --dry-run    # show the plan, touch nothing
//   node discord/setup.mjs              # apply it
//
// Converges rather than creates: anything already present by name is left
// alone, so re-running after an edit is safe and is the intended workflow.
//
// Node 18+ (native fetch). No dependencies on purpose — a setup script that
// needs an install step is one more thing to go wrong.

import { ROLES, STRUCTURE, POSTS } from "./server.config.mjs";

const API = "https://discord.com/api/v10";
const TOKEN = process.env.DISCORD_BOT_TOKEN;
const GUILD = process.env.DISCORD_GUILD_ID;
const DRY = process.argv.includes("--dry-run");

// Permission bits. Values are stable; see Discord's permissions reference.
const VIEW_CHANNEL = 1n << 10n;
const SEND_MESSAGES = 1n << 11n;
const ADD_REACTIONS = 1n << 6n;
const CREATE_PUBLIC_THREADS = 1n << 35n;
const SEND_MESSAGES_IN_THREADS = 1n << 38n;

const CHANNEL_TEXT = 0;
const CHANNEL_CATEGORY = 4;
const CHANNEL_ANNOUNCEMENT = 5;

if (!TOKEN || !GUILD) {
  console.error(
    "Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID first.\n" +
      "See discord/README.md — it is four steps and none of them are hard.",
  );
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * One API call, honouring Discord's rate limits.
 *
 * 429 carries `retry_after` in seconds and must be waited out rather than
 * hammered; a burst of channel creations will hit it, and a setup script that
 * dies half-built is worse than one that takes an extra few seconds.
 */
async function api(method, path, body, attempt = 0) {
  const res = await fetch(API + path, {
    method,
    headers: {
      Authorization: `Bot ${TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "ROMSetup (https://romapps.xyz, 1.0)",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 429 && attempt < 5) {
    const info = await res.json().catch(() => ({}));
    const wait = Math.ceil((info.retry_after ?? 1) * 1000) + 250;
    console.log(`    rate limited, waiting ${wait}ms`);
    await sleep(wait);
    return api(method, path, body, attempt + 1);
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${method} ${path} -> ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.status === 204 ? null : res.json();
}

/** Discord wants a decimal int; the brand palette is written as hex. */
const color = (hex) => parseInt(hex, 16);

async function main() {
  const guild = await api("GET", `/guilds/${GUILD}`);
  console.log(`\n  ${DRY ? "PLAN for" : "Building"}: ${guild.name}\n`);

  // ---------------------------------------------------------------- roles
  const existingRoles = await api("GET", `/guilds/${GUILD}/roles`);
  const roleByName = new Map(existingRoles.map((r) => [r.name, r]));

  for (const role of ROLES) {
    if (roleByName.has(role.name)) {
      console.log(`  role   = ${role.name} (exists)`);
      continue;
    }
    if (DRY) {
      console.log(`  role   + ${role.name}`);
      continue;
    }
    const made = await api("POST", `/guilds/${GUILD}/roles`, {
      name: role.name,
      color: color(role.color),
      hoist: role.hoist,
      mentionable: role.mentionable,
      permissions: role.permissions,
    });
    roleByName.set(made.name, made);
    console.log(`  role   + ${role.name}`);
  }

  // ------------------------------------------------------------- channels
  const existingChannels = await api("GET", `/guilds/${GUILD}/channels`);
  const chanByName = new Map(
    existingChannels.map((c) => [`${c.type === CHANNEL_CATEGORY ? "cat" : "chan"}:${c.name}`, c]),
  );

  // A read-only channel: @everyone keeps VIEW and reactions and can still reply
  // in threads, but cannot start top-level noise.
  const readOnlyOverwrites = () => [
    {
      id: GUILD, // the @everyone role always shares the guild id
      type: 0,
      allow: String(VIEW_CHANNEL | ADD_REACTIONS | SEND_MESSAGES_IN_THREADS),
      deny: String(SEND_MESSAGES | CREATE_PUBLIC_THREADS),
    },
  ];

  let position = 0;

  for (const group of STRUCTURE) {
    const catKey = `cat:${group.category}`;
    let category = chanByName.get(catKey);

    if (category) {
      console.log(`\n  cat    = ${group.category} (exists)`);
    } else if (DRY) {
      console.log(`\n  cat    + ${group.category}`);
      category = { id: "DRY" };
    } else {
      category = await api("POST", `/guilds/${GUILD}/channels`, {
        name: group.category,
        type: CHANNEL_CATEGORY,
        position: position++,
      });
      chanByName.set(catKey, category);
      console.log(`\n  cat    + ${group.category}`);
    }

    for (const ch of group.channels) {
      const wanted = ch.announcement ? CHANNEL_ANNOUNCEMENT : CHANNEL_TEXT;
      // Keyed by name, not by name+type: an announcement channel can land as a
      // plain text channel via the fallback below, and a type-keyed lookup
      // would then miss it on the next run and create a duplicate.
      const key = `chan:${ch.name}`;
      let channel = chanByName.get(key);

      if (channel) {
        console.log(`  chan   = #${ch.name} (exists)`);
      } else if (DRY) {
        console.log(`  chan   + #${ch.name}${ch.readOnly ? "  [read-only]" : ""}`);
        continue;
      } else {
        const slot = position++;
        const create = (type) =>
          api("POST", `/guilds/${GUILD}/channels`, {
            name: ch.name,
            type,
            topic: ch.topic,
            parent_id: category.id,
            position: slot,
            ...(ch.readOnly ? { permission_overwrites: readOnlyOverwrites() } : {}),
          });

        try {
          channel = await create(wanted);
        } catch (e) {
          // Announcement channels exist only on Community servers, and Discord
          // rejects the type outright rather than degrading — a brand new
          // server cannot have one. A plain text channel is the right fallback:
          // the only thing lost is other servers being able to *follow* the
          // channel, and it converts later with one toggle in Edit Channel.
          const unsupportedType =
            wanted === CHANNEL_ANNOUNCEMENT && /BASE_TYPE_CHOICES|50035/.test(e.message);
          if (!unsupportedType) throw e;
          console.log(`  note     not a Community server — #${ch.name} will be a normal text channel`);
          channel = await create(CHANNEL_TEXT);
        }

        chanByName.set(key, channel);
        console.log(`  chan   + #${ch.name}${ch.readOnly ? "  [read-only]" : ""}`);
      }

      // ------------------------------------------------------------ posts
      // Only ever posted into a channel that has none, so a re-run cannot
      // duplicate the welcome text underneath itself.
      if (!ch.posts?.length || DRY) continue;

      const existing = await api("GET", `/channels/${channel.id}/messages?limit=5`).catch(() => []);
      if (existing.length > 0) {
        console.log(`           (already has messages, leaving them)`);
        continue;
      }

      for (const postKey of ch.posts) {
        const post = POSTS[postKey];
        if (!post) {
          console.log(`           ! no copy named "${postKey}" — skipped`);
          continue;
        }
        const msg = await api("POST", `/channels/${channel.id}/messages`, {
          embeds: [{ title: post.title, description: post.description, color: color(post.color) }],
        });
        await api("PUT", `/channels/${channel.id}/pins/${msg.id}`).catch(() => {
          console.log(`           (could not pin "${post.title}")`);
        });
        console.log(`           posted + pinned: ${post.title}`);
        // Comfortably under the per-channel message limit without tripping 429.
        await sleep(400);
      }
    }
  }

  console.log(
    DRY
      ? "\n  Dry run only — nothing was changed. Drop --dry-run to apply.\n"
      : "\n  Done. Next: set the server icon, and add the GitHub webhook in #github.\n",
  );
}

main().catch((e) => {
  console.error(`\n  Failed: ${e.message}\n`);
  console.error("  Most common causes:");
  console.error("   - the bot is not in the server yet (use the invite link from README)");
  console.error("   - the bot's role lacks Manage Channels / Manage Roles");
  console.error("   - DISCORD_BOT_TOKEN is the client secret rather than the bot token\n");
  process.exit(1);
});
