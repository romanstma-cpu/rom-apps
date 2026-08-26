# Getting ROM installers signed

Everything that can be done without a certificate is done. The application
itself needs you rather than an agent — see below for why.

Last updated 2026-08-26 (was written for two apps; there are now four with
installers).

## The SignPath application has to be submitted by you

<https://signpath.org/apply> is a HubSpot form behind **Google reCAPTCHA
Enterprise**. I don't complete CAPTCHAs — that is the site asking for a person
rather than a script, and working around it would be both a breach of their
terms and a poor first impression on an application that is entirely about
trustworthiness.

Everything you need is below. It should be a copy-and-paste job.

## Before you submit

| Check | State |
|---|---|
| Repos public | yes — rom-trader, rom-convert, rom-scribe, rom-nova |
| GitHub reports the licence as MIT | yes — **all four**; rom-nova's LICENSE was added 26 Aug, until then GitHub reported no licence at all |
| Repo descriptions set | yes |
| Released in the form to be signed | Trader v1.11.1, Convert v1.0.0, Scribe v1.2.0, Nova v1.0.2 |
| Functionality documented on the download page | romapps.xyz |
| Code signing policy published | romapps.xyz/code-signing-policy.html |
| Builds from a pipeline, not a laptop | yes — GitHub Actions, verified green |
| Two-factor auth on the GitHub account | yes — confirmed 23 Aug |

Every condition is met. The application is ready to send.

> **Why the licence row matters.** SignPath Foundation requires an
> OSI-approved licence on *every* component with no proprietary parts. Until
> 26 Aug, `rom-nova` had no LICENSE file, so GitHub reported it as
> all-rights-reserved and it would have been rejected. `rom-apps` (which hosts
> Polybot) was in the same state and is now MIT too.

## Apply for ROM Convert first

It is the strongest candidate: broad appeal, obviously benign, and the bundled
FFmpeg is itself open source. If it is accepted, the relationship is
established when the others follow. Then Scribe, then Nova, then Trader —
roughly least to most likely to need a conversation.

**Project name:** ROM Convert
**Project website:** https://romapps.xyz
**Repository:** https://github.com/romanstma-cpu/rom-convert
**Licence:** MIT
**Code signing policy:** https://romapps.xyz/code-signing-policy.html

> ROM Convert converts video, audio and images locally on Windows using a
> bundled FFmpeg build. Nothing is uploaded, there is no file size limit, no
> watermark and no account. It is a free alternative to online converters,
> which require users to hand their files to a third-party server.
>
> The project is MIT licensed with no proprietary components. FFmpeg is
> included as an unmodified upstream binary under its own LGPL/GPL terms and
> is documented in THIRD-PARTY-NOTICES.md.
>
> Installers are built by GitHub Actions from a tagged commit
> (.github/workflows/release.yml) and published as GitHub releases together
> with a SHA-256 checksum. The current release is v1.0.0.
>
> The project is maintained by one person, who is the sole author, reviewer
> and approver; the GitHub account has two-factor authentication enabled.
>
> The application contains no functionality for identifying or exploiting
> security vulnerabilities or circumventing security measures, makes no
> undisclosed changes to the system, installs per-user without administrator
> rights, and collects no telemetry or personal data.

## Then ROM Scribe

**Repository:** https://github.com/romanstma-cpu/rom-scribe · **Licence:** MIT

> ROM Scribe transcribes and subtitles video and audio entirely on the user's
> own PC using an offline speech recognition model. Nothing is uploaded, there
> is no per-minute pricing and no account. It is a free alternative to
> cloud transcription services.
>
> MIT licensed with no proprietary components. The Whisper model and the
> whisper.cpp binary are third-party open-source components, pinned by hash
> and verified at install time. Installers are built by GitHub Actions from a
> tagged commit and published with a SHA-256 checksum. Current release v1.2.0.
>
> Maintained by one person, sole author, reviewer and approver, with
> two-factor authentication enabled. No functionality for identifying or
> exploiting security vulnerabilities, no undisclosed changes to the system,
> installs per-user, collects no telemetry.

## Then ROM Nova

**Repository:** https://github.com/romanstma-cpu/rom-nova · **Licence:** MIT

> ROM Nova is an on-chain analytics terminal that demonstrates a signal-scoring
> engine on a deterministic simulated dataset. It is clearly labelled as
> simulated throughout the interface and carries a "not investment advice"
> disclaimer on every screen. It places no trades, connects to no wallet,
> handles no keys and holds no funds. The paper-trading feature is a scoring
> sandbox against the same simulated data.
>
> MIT licensed with no proprietary components. The same build runs in the
> browser at https://romapps.xyz/nova/, which is the easiest way to see exactly
> what the application does before installing anything. Installers are built by
> GitHub Actions from a tagged commit and published with a SHA-256 checksum.
> Current release v1.0.2.
>
> Maintained by one person, sole author, reviewer and approver, with
> two-factor authentication enabled. No functionality for identifying or
> exploiting security vulnerabilities, no undisclosed changes to the system,
> installs per-user, collects no telemetry. All user state is stored locally in
> the browser or the app's own data directory and is never transmitted.

## Then ROM Trader

**Repository:** https://github.com/romanstma-cpu/rom-trader · **Licence:** MIT

> ROM Trader is an automated trading client for the Kalshi prediction market
> API. It ships in dry-run mode: it paper-trades against live prices and
> places no real orders until the user supplies their own Kalshi API key and
> explicitly enables live mode. The key is encrypted with the user's Windows
> account via DPAPI, is never shown back to the interface, and is transmitted
> only to Kalshi.
>
> MIT licensed with no proprietary components. Installers are built by GitHub
> Actions from a tagged commit and published with a SHA-256 checksum. Current
> release v1.11.1. Maintained by one person, sole author, reviewer and
> approver, with two-factor authentication enabled.
>
> The application contains no functionality for identifying or exploiting
> security vulnerabilities, makes no undisclosed changes to the system,
> installs per-user, and collects no telemetry.

## After approval

1. Add the SignPath credit to `/code-signing-policy.html`. Their terms require
   it, and it should not appear before approval.
2. Wire their GitHub Action into each `.github/workflows/release.yml`, after
   the package step and **before** the checksum step, so the hash covers the
   signed binary.
3. Re-run the checksum step so `SHA256SUMS.txt` describes the signed file.
4. For ROM Trader, remember the update feed is `rom-apps`, not `rom-trader` —
   re-run "Publish ROM Trader" there so the signed build reaches installed
   copies. (The mirror step inside rom-trader's own workflow reports success
   while doing nothing; it needs a RELEASE_TOKEN that deliberately does not
   exist.)

## Note on secrets in CI

There is deliberately **no `RELEASE_TOKEN`**. The only fine-grained permission
that can create a GitHub release is "Contents", which also allows pushing
commits — and this repository is the website. A long-lived token in another
repo's CI that could rewrite romapps.xyz is a poor trade for saving a click.

Instead, rom-trader publishes its build to its own (public) releases, and the
"Publish ROM Trader" workflow here mirrors it, re-checking the SHA-256 and
confirming `latest.yml` agrees with the tag and the real file size on the way
through. No secret is involved anywhere.

## If SignPath declines

**Azure Artifact Signing** — renamed from Trusted Signing in 2026 — is
**$9.99/month** on the Basic tier, up to 5,000 signatures with one certificate
profile. Individual developers are eligible in the USA and Canada; the EU and
UK are organisations only. Identity validation applies either way.

Two things to know before choosing it:

- It does **not** use `CSC_LINK`/`CSC_KEY_PASSWORD`. The `.pfx` model is dead
  for new certificates anyway — since 2023 all OV keys must live on FIPS
  140-2 hardware. electron-builder supports it natively: on v25/26 that is
  `win.azureSignOptions`, and v27 moved it to `win.sign: { type: "azure" }`.
  Authenticate from Actions with OIDC so there is no long-lived secret.
- There is no certificate to export. If you stop paying or lose eligibility,
  signing stops and the identity cannot be moved elsewhere. The same is true
  of SignPath. Either way you are renting trust, not buying an asset.

- <https://azure.microsoft.com/en-us/pricing/details/artifact-signing/>

## Do not bother with

**A cheap OV certificate on a USB token.** Certum's open-source certificate is
about €30/year and looks like the bargain, but the key lives on physical
hardware that cannot be plugged into a GitHub-hosted runner. It would mean a
self-hosted runner or signing four installers by hand on every release.

**Self-signed certificates.** Windows does not trust the issuer, so they do
nothing for SmartScreen and can read worse than no signature at all.

## What signing will and will not fix

A certificate removes the "unknown publisher" wording and puts a verified name
in its place immediately. SmartScreen *reputation* still accrues over installs
— but it accrues to the certificate identity rather than resetting on every new
binary, which is the real win. Unsigned, every build starts from zero forever.
Expect steady improvement across releases, not an instant clean slate.
