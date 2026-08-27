# The ROM Discord server

The whole server is defined in `server.config.mjs` and built by `setup.mjs`.
Edit the config, re-run the script, and it converges — nothing gets created
twice, so re-running after a change is the intended workflow rather than
something to be careful about.

Two steps need your Discord account and cannot be scripted. They take about a
minute between them.

## 1. Create the empty server

Discord, left sidebar, **+** → **Create My Own** → **For me and my friends**.

Name it **ROM Apps**. Use `assets/rom-icon.png` from this repo as the icon.

Then **User Settings → Advanced → Developer Mode** on, right-click the server,
**Copy Server ID**.

## 2. Create the bot

<https://discord.com/developers/applications> → **New Application** → name it
`ROM Setup`.

- **Bot** tab → **Reset Token** → copy it. This is the bot token. It is not the
  same thing as the client secret on the OAuth2 tab, and using the wrong one is
  the single most common reason this script fails.
- **OAuth2 → URL Generator** → scope **`bot`** → permission **Administrator**.
- Open the generated URL, pick your server, authorise.

Administrator is deliberate and temporary. Discord validates channel permission
overwrites against what the bot itself holds, so a bot that cannot send
messages cannot create a channel that denies sending. **Remove the bot from the
server once you are done** — it has no runtime job.

## 3. Run it

```bash
node discord/setup.mjs --dry-run
```

Prints the plan and touches nothing. When it looks right:

```bash
node discord/setup.mjs
```

PowerShell:

```powershell
$env:DISCORD_BOT_TOKEN = "your-bot-token"
$env:DISCORD_GUILD_ID  = "your-server-id"
node discord/setup.mjs
```

Needs Node 18+ for native `fetch`. No dependencies, nothing to install.

## 4. The three things left to do by hand

- **Server icon** — upload it in Server Settings → Overview. `PATCH /guilds/{id}`
  could set this from the config (as a base64 data URI) and the script
  deliberately does not: it is a one-time click, and a rebrand living in a
  config file means any routine re-run can overwrite an icon somebody chose
  later. The Discord-specific cut is a circle on a bright gradient — the square
  app icon loses its corners to Discord's crop and its dark face disappears
  against the `#1e1f22` sidebar.
- **GitHub feed** — `#github` → Edit Channel → Integrations → Webhooks → New
  Webhook → copy the URL. Then on each repo: Settings → Webhooks → Add, paste
  the URL with **`/github`** appended, content type `application/json`, and pick
  the events you want (releases and issues are the useful ones; pushes get
  noisy fast).
- **Invite link** — Server Settings → Invites, or right-click the server →
  Invite People → **Edit invite link** → set it to never expire, unlimited uses.
  Then put it on romapps.xyz.

## What gets built

Seven channels in three categories. Small on purpose: a new server with twenty
channels reads as abandoned on day one, and seven that people actually post in
reads as alive. Split `#support` per-app when the traffic justifies it.

```
START HERE
  #welcome           read-only · About, Rules, Safety, and the honesty notice, all pinned
  #announcements     read-only · announcement channel, so other servers can follow releases

HELP & FEEDBACK
  #support           one channel for all five apps
  #bugs-and-requests confirmed bugs get promoted to GitHub Issues
  #showcase

COMMUNITY
  #general
  #github            read-only · webhook feed
```

Roles: **Maintainer** (violet) and **Contributor** (cyan), both hoisted so they
show separately in the member list. Neither carries any permission bits — grant
those by hand in the UI, so a config file in a public repo can never quietly
widen somebody's access.

Read-only channels deny sending and starting threads for `@everyone` but keep
reactions and thread replies, so announcements stay clean without feeling
sealed off.

## The copy

All of it lives in `POSTS` at the bottom of `server.config.mjs`. Two pieces
matter more than the rest and are worth not softening:

**The safety notice.** A Discord attached to a trading bot attracts people who
want your keys, and the impersonation-DM pattern is completely predictable. The
pinned message states plainly that nobody from ROM will ever DM first and that
no real request for an API key exists. Say it before it happens, not after.

**The honesty notice.** It repeats what the apps' own docs already say: ROM
Trader has no demonstrated edge and ships dry-run, ROM Nova runs on simulated
data. The site refuses to imply a profit; the Discord has to hold the same line,
because a community is exactly where that erodes first.

## Later, if it grows

- **Community features** (Server Settings → Enable Community) unlock forum
  channels, which suit `#support` far better than a flat text channel once
  there is real volume. Needs a rules channel and a public updates channel,
  both of which `#welcome` and `#announcements` can serve.
- **AutoMod** (Server Settings → AutoMod) will block invite links and common
  scam phrasing on its own. Worth switching on before the server is public.
- **Onboarding** (Server Settings → Onboarding) can gate entry behind reading
  `#welcome`, which is the cheapest filter there is.
