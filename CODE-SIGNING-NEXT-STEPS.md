# Getting ROM installers signed

Everything that can be done without a certificate is done. Two things remain,
and both need you rather than an agent.

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
| Both repos public | yes |
| GitHub reports the licence as MIT | yes — fixed 23 Aug; the FFmpeg note used to make ROM Convert read as "Other" |
| Repo descriptions set | yes |
| Released in the form to be signed | Trader v1.1.2, Convert v1.0.0 |
| Functionality documented on the download page | romapps.xyz |
| Code signing policy published | romapps.xyz/code-signing-policy.html |
| Builds from a pipeline, not a laptop | yes — GitHub Actions, verified green |
| **Two-factor auth on the GitHub account** | **you must confirm** |

That last one is a stated SignPath requirement and I cannot read it — the CLI
token lacks the `read:user` scope. Check at
<https://github.com/settings/security>. If it is off, turn it on before
applying.

## Apply for ROM Convert first

It is the stronger candidate: broad appeal, obviously benign, and the bundled
FFmpeg is itself open source. If it is accepted, the relationship is
established when ROM Trader follows.

**Project name:** ROM Convert
**Project website:** https://romapps.xyz
**Repository:** https://github.com/romanstma-cpu/rom-convert
**Licence:** MIT
**Code signing policy:** https://romapps.xyz/code-signing-policy.html

**Description:**

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

## Then ROM Trader

Same structure, with this description:

> ROM Trader is an automated trading client for the Kalshi prediction market
> API. It ships in dry-run mode: it paper-trades against live prices and
> places no real orders until the user supplies their own Kalshi API key and
> explicitly enables live mode. The key is encrypted with the user's Windows
> account via DPAPI and is transmitted only to Kalshi.
>
> MIT licensed with no proprietary components. Installers are built by GitHub
> Actions from a tagged commit and published with a SHA-256 checksum. Current
> release v1.1.2. Maintained by one person, sole author, reviewer and
> approver, with two-factor authentication enabled.
>
> The application contains no functionality for identifying or exploiting
> security vulnerabilities, makes no undisclosed changes to the system,
> installs per-user, and collects no telemetry.

## After approval

1. Add the SignPath credit to `/code-signing-policy.html`. Their terms require
   it, and it should not appear before approval.
2. Wire their GitHub Action into `.github/workflows/release.yml`, after the
   package step and before the checksum step, so the hash covers the signed
   binary.
3. Re-run the checksum step so `SHA256SUMS.txt` describes the signed file.

## If SignPath declines

Azure Artifact Signing (formerly Trusted Signing) is **$9.99/month** on the
Basic tier, up to 5,000 signatures. Individual developers are eligible, but
only in verified US, Canadian, EU and other listed countries, with identity
validation.

Note it does **not** use `CSC_LINK`; it needs `azureSignOptions` in the
electron-builder config, which is a small change at that point.

- <https://azure.microsoft.com/en-gb/pricing/details/trusted-signing/>

## What signing will and will not fix

A certificate removes the "unknown publisher" wording, but SmartScreen
reputation still accrues per publisher over installs. A new OV certificate can
still warn until enough downloads are seen; EV gets reputation immediately and
costs considerably more. Expect improvement, not an instant clean slate.

## Do not bother with

**Self-signed certificates.** Windows does not trust the issuer, so they do
nothing for SmartScreen and can read worse than no signature at all.
