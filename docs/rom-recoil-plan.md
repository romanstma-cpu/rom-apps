# ROM Recoil — distribution notes

Internal note (not published; `docs/` is outside the site allowlist).

## Now: free download

- ROM Recoil has its own page, `recoil/index.html` (romapps.xyz/recoil/), and a short homepage chapter (`index.html#recoil`) that links to it. Both carry the direct download.
- The zip lives on the `recoil-v1.5.0` release of this repository (older releases are still there for reference), created with **make_latest = false** so ROM Trader's update feed (this repository's latest release) is untouched.
- The checksum is copied to `assets/SHA256SUMS-Recoil-1.5.0.txt`.
- `assets/recoil-latest.json` tells installed copies (1.3.2 and later) which version is newest; they show an Update button when it is higher than their own.
- In the app, `Store.PaywallEnabled = false`: no activation screen and no license checks.

## Later: charging for it

The licensing code is kept in the app (`RomRecoil/Core/License.cs`) and is written for Lemon Squeezy's public License API (activate / validate / deactivate with no secret in the app, 3 PCs per key, refunds disable the key). To turn it on:

1. Pick a payment provider. Polar bans macros outright. Gumroad and Lemon Squeezy don't list them but can close accounts at their discretion. A plain Stripe payment link on romapps.xyz would also need a small server (Supabase Edge Function or Cloudflare Worker) to hand out keys after payment.
2. Set `PaywallEnabled = true` and the store/product IDs in `RomRecoil/Core/Store.cs`.
3. Replace the homepage download button with the checkout link.

## Risks to keep in mind

- Ubisoft's terms forbid third-party tools that give an advantage; players can be banned. Never claim it is undetectable.
- The exe is unsigned, so SmartScreen warns on first run (see `docs/code-signing.md`).
