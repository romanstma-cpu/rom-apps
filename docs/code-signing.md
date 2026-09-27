# Getting ROM installers signed

None of the installers are signed today. Windows shows an unknown-publisher
warning and macOS reports an unidentified developer. The site says so and
publishes SHA-256 checksums, which prove integrity but not identity.

Last updated 2026-09-26. ROM now ships Polybot and Nova; Trader stays
available but is no longer developed. Convert and Scribe are discontinued and
are not part of any application below.

## Where each app stands

| App | Source | Signing route |
|---|---|---|
| ROM Nova | public, MIT (`rom-nova`) | SignPath Foundation — apply first |
| ROM Trader | public, MIT (`rom-trader`) | SignPath Foundation — optional, it is no longer developed |
| ROM Polybot (Windows) | **not public** — `rom-polybot` is empty | SignPath only after the source is published; otherwise Azure Artifact Signing |
| ROM Polybot (Mac) | — | Apple Developer ID + notarization |

**Polybot is the blocker.** SignPath Foundation signs only open-source projects
with an OSI-approved licence on every component. The Polybot desktop source is
kept on one PC and has never been pushed, so as things stand the flagship app is
the one that cannot apply. Two ways forward:

1. Publish the desktop source to `romanstma-cpu/rom-polybot` under MIT, build
   installers from a tagged commit in GitHub Actions, then apply as below.
2. Keep it closed and use Azure Artifact Signing (see further down).

The Mac build needs Apple's route either way: an Apple Developer Program
membership, a Developer ID Application certificate, and notarization with
`notarytool` in the build. That is what removes the "unidentified developer"
prompt; nothing else does.

## The SignPath application has to be submitted by you

<https://signpath.org/apply> is a HubSpot form behind Google reCAPTCHA
Enterprise. That is the site asking for a person rather than a script, so it
needs you. Everything else is copy and paste.

## Before you submit

| Check | State |
|---|---|
| Repos public | rom-nova, rom-trader — yes. rom-polybot — empty |
| GitHub reports the licence as MIT | rom-nova, rom-trader — yes |
| Functionality documented on the download page | romapps.xyz |
| Code signing policy published | romapps.xyz/code-signing-policy.html |
| Builds from a pipeline, not a laptop | Nova and Trader — GitHub Actions |
| Two-factor auth on the GitHub account | yes — confirmed 23 Aug |

## Apply for ROM Nova first

**Project name:** ROM Nova
**Project website:** https://romapps.xyz
**Repository:** https://github.com/romanstma-cpu/rom-nova
**Licence:** MIT
**Code signing policy:** https://romapps.xyz/code-signing-policy.html

> ROM Nova is a Solana research terminal. It reads public on-chain and market
> data, labels the parts it simulates wherever they appear, and carries a
> "not investment advice" disclaimer. It places no trades, connects to no
> wallet, handles no private keys and holds no funds. Its paper-trading feature
> is a sandbox.
>
> MIT licensed with no proprietary components. The same build runs in the
> browser at https://romapps.xyz/nova/, which is the easiest way to see exactly
> what the application does before installing anything. Installers are built by
> GitHub Actions from a tagged commit and published with a SHA-256 checksum.
> Current release v1.29.0.
>
> Maintained by one person, sole author, reviewer and approver, with
> two-factor authentication enabled. No functionality for identifying or
> exploiting security vulnerabilities, no undisclosed changes to the system,
> installs per-user, collects no telemetry. Workspace data is stored locally in
> the browser or the app's own data directory. An optional account, used only
> for the hosted radar, stores an email address with the sign-in provider.

## Then ROM Trader, if you still want it signed

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
> release v1.15.1. Maintained by one person, sole author, reviewer and
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
   copies.

## Note on secrets in CI

There is deliberately **no `RELEASE_TOKEN`**. The only fine-grained permission
that can create a GitHub release is "Contents", which also allows pushing
commits — and this repository is the website. A long-lived token in another
repo's CI that could rewrite romapps.xyz is a poor trade for saving a click.

Instead, rom-trader publishes its build to its own (public) releases, and the
"Publish ROM Trader" workflow here mirrors it, re-checking the SHA-256 and
confirming `latest.yml` agrees with the tag and the real file size on the way
through. No secret is involved anywhere.

## If SignPath declines, or Polybot stays closed

**Azure Artifact Signing** — renamed from Trusted Signing in 2026 — is
**$9.99/month** on the Basic tier, up to 5,000 signatures with one certificate
profile. Individual developers are eligible in the USA and Canada; the EU and
UK are organisations only. Identity validation applies either way, and it does
not require open source.

- It does **not** use `CSC_LINK`/`CSC_KEY_PASSWORD`. The `.pfx` model is dead
  for new certificates anyway — since 2023 all OV keys must live on FIPS
  140-2 hardware. electron-builder supports it natively: on v25/26 that is
  `win.azureSignOptions`, and v27 moved it to `win.sign: { type: "azure" }`.
  Authenticate from Actions with OIDC so there is no long-lived secret.
- There is no certificate to export. If you stop paying or lose eligibility,
  signing stops and the identity cannot be moved elsewhere. The same is true
  of SignPath. Either way you are renting trust, not buying an asset.

<https://azure.microsoft.com/en-us/pricing/details/artifact-signing/>

## Do not bother with

**A cheap OV certificate on a USB token.** The key lives on physical hardware
that cannot be plugged into a GitHub-hosted runner. It would mean a self-hosted
runner or signing every installer by hand on every release.

**Self-signed certificates.** Windows does not trust the issuer, so they do
nothing for SmartScreen and can read worse than no signature at all.

## What signing will and will not fix

A certificate removes the "unknown publisher" wording and puts a verified name
in its place immediately. SmartScreen *reputation* still accrues over installs
— but it accrues to the certificate identity rather than resetting on every new
binary, which is the real win. Unsigned, every build starts from zero forever.
Expect steady improvement across releases, not an instant clean slate.
