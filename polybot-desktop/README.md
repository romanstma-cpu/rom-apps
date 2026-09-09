# ROM Polybot

Independent desktop copy configured for the Polymarket US retail API.

## Windows app
Run `release/ROM PolyBot-Setup-2.0.0.exe`, then open ROM PolyBot.
Python and the app runtime are included in the installer.

## Development
Install Node.js and Python 3.12+, run `npm install`, then `npm run dev`.
For a Windows installer, run `npm run dist`.

Open API and enter the Key ID and Secret Key from https://polymarket.us/developer.
No wallet, referral signup, or additional API subscription is required. Account
verification and funding are handled in Polymarket US.

Settings and encrypted credentials use ROM PolyBot's separate application-data directory.
The original app and its saved data are not migrated.

US market availability differs. Wallet copy-trading is not supplied by the US retail API. Whale and momentum scanners consume the authenticated US trade stream. Those features must not
silently use international exchange data. Crypto strategies need US-listed markets.

Original third-party copyright notices are retained in LICENSE as required.

## Verification
997 active Python tests pass. The 23 Electron script-arming checks pass, and
the packaged Windows app has been opened and its API screen inspected.
Public US market data was verified. Authenticated account access, streaming,
and live trading still require validation with the user's own US credentials.

International wallet-only tests are retained as text in
`python/tests/international_reference`; US API contract tests replace them.
