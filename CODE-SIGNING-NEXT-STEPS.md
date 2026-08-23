# Getting ROM installers signed

Everything that can be done without a certificate is done. What remains needs
your identity and, on one of the two routes, your money — so it has to be you.

## What is already in place

- **Releases are built by GitHub Actions** from a tagged commit in the public
  repo, not from a laptop. Signing is two repository secrets away:
  electron-builder reads `CSC_LINK` (base64 of the `.pfx`) and
  `CSC_KEY_PASSWORD` on its own, so no code changes when a certificate lands.
- **Every release publishes `SHA256SUMS.txt`**, and the site shows a PowerShell
  snippet that prints `MATCH` or `DOES NOT MATCH`.
- **A code signing policy page** is live at `/code-signing-policy.html`,
  covering how builds are made, what each app touches, and the bundled FFmpeg.
  SignPath requires such a page.

## Route 1 — SignPath Foundation (free) ← recommended

SignPath Foundation gives qualifying open-source projects free OV-level code
signing. Both ROM apps appear to meet the published conditions:

| Condition | ROM Trader | ROM Convert |
|---|---|---|
| OSI-approved licence, no commercial dual-licensing | MIT | MIT |
| No proprietary components | yes | yes — FFmpeg is LGPL/GPL |
| Actively maintained | yes | yes |
| Already released in the form to be signed | v1.1.2 | v1.0.0 |
| Functionality documented on the download page | romapps.xyz | romapps.xyz |
| Not a security or hacking tool | correct | correct |

Two conditions still need action from you:

1. **Team roles.** SignPath wants Authors, Reviewers and Approvers defined,
   with multi-factor authentication on every account. For a solo project you
   hold all three — say so plainly in the application, and make sure 2FA is on
   for the GitHub account.
2. **Credit on the policy page.** Once granted, add a line to
   `/code-signing-policy.html` crediting SignPath Foundation. Do not add it
   before approval.

Apply at <https://signpath.org/apply>. Draft text:

---

**Project:** ROM Convert
**Repository:** https://github.com/romanstma-cpu/rom-convert
**Licence:** MIT (bundled FFmpeg under LGPL v2.1+ / GPL v2+)
**Download page:** https://romapps.xyz
**Code signing policy:** https://romapps.xyz/code-signing-policy.html

ROM Convert converts video, audio and images locally on Windows using a
bundled FFmpeg build. Nothing is uploaded, there is no file size limit and no
account is required. It is a free alternative to online converters that take
users' files onto a server.

Installers are built by GitHub Actions from a tagged commit
(`.github/workflows/release.yml`) and published as GitHub releases with a
SHA-256 checksum. The project is maintained by one person, who is the sole
author, reviewer and approver; the GitHub account has two-factor
authentication enabled. The current release is v1.0.0.

The app contains no functionality for identifying or exploiting security
vulnerabilities, makes no undisclosed system modifications, and collects no
telemetry or personal data.

---

Submit ROM Trader separately with the same structure, noting it is an
automated trading client for the Kalshi API that ships in dry-run and only
places real orders once the user supplies their own API key.

## Route 2 — Azure Artifact Signing (paid)

Formerly Trusted Signing. **$9.99/month** on the Basic tier (up to 5,000
signatures); Premium is $99.99/month. Far cheaper than a traditional OV
certificate, which now runs several hundred dollars a year and must live on
hardware since the 2023 CA/Browser Forum key-storage rules.

Individual developers can sign up, but availability is limited to verified
entities in the US, Canada, the EU and other eligible countries, and identity
validation is required. Note that signing this way does **not** use
`CSC_LINK` — it needs `azureSignOptions` in the electron-builder config, which
is a small change to make at that point.

- Pricing: <https://azure.microsoft.com/en-gb/pricing/details/trusted-signing/>
- Product: <https://azure.microsoft.com/en-us/products/artifact-signing>

## What signing will and will not fix

A certificate removes the "unknown publisher" wording, but SmartScreen
reputation still accrues per-publisher over downloads. A brand-new OV
certificate can still show a warning until enough installs are seen; an EV
certificate gets reputation immediately and costs considerably more. Expect
improvement rather than an instant clean bill of health.

## Do not bother with

**Self-signed certificates.** They do nothing for SmartScreen — Windows does
not trust the issuer — and a signature from an untrusted root can read worse
than no signature at all.
