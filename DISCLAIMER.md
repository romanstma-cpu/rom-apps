# Disclaimer & Risk Notice

**Read this before using ROM PolyBot with real money.**

ROM PolyBot is free, open-source, experimental software for placing trades on
[Polymarket](https://polymarket.com). By downloading, building, or running it, you
acknowledge and accept everything below.

## Not financial advice
ROM PolyBot, its strategies, signals, scores, and any documentation are for
informational and educational purposes only. Nothing here is financial,
investment, legal, or tax advice. The authors are **not** registered investment
advisors, commodity trading advisors, broker-dealers, or fiduciaries of any
kind, and nothing in this project creates such a relationship.

## Risk of loss
Trading event contracts involves substantial risk. **You can lose some or all
of the money in your account.** Automated trading can lose money quickly and at
scale, including while you are away from your computer. Only trade with money
you can afford to lose entirely.

## The strategies are unproven
The bundled strategies (whale tracker, momentum scanner, 15-minute crypto, etc.)
are **heuristics**. They:

- have **not** been validated with out-of-sample backtesting;
- do **not** currently account for Polymarket trading fees in their entry/sizing
  decisions, which can erode or eliminate any apparent edge;
- carry **no guarantee of profitability**.

Any performance figures, "edge" scores, or calibration claims are illustrative
and are **not** a promise of future results. Past or simulated performance does
not indicate future performance.

## No warranty
The software is provided "AS IS", without warranty of any kind, as stated in the
[LICENSE](./LICENSE). It may contain bugs that cause incorrect orders, missed
orders, or inaccurate P&L. The authors are not liable for any losses, damages,
or claims arising from its use.

## Your responsibilities
You are solely responsible for:

- Complying with [Polymarket's Terms of Service](https://polymarket.com/terms) and API
  terms, including any rules on automated/algorithmic trading. **Confirm that
  automated trading with your account is permitted before enabling it.**
- Complying with all laws and regulations in your jurisdiction, including
  eligibility, age, and licensing requirements.
- The security of your Polygon wallet private key and the machine you run this on.
  Anyone with that key controls the wallet's funds — use a dedicated trading wallet.
- Every order the software places on your behalf.

## Start small — there is no practice mode
There is **no paper, demo, or simulation mode**. Polymarket is mainnet-only (real
USDC) and there is no demo exchange, so **every engine places real orders with real
money the moment you enable it**. All engines ship **OFF by default**. Before turning
any engine on, understand exactly what it does, and begin with a small amount you can
afford to lose entirely.

## Usage data
ROM PolyBot sends **no** telemetry, analytics, or usage data of any kind. It
collects nothing about you and phones no home server. The only network traffic
it makes is to Polymarket's own APIs, the market-data feeds it needs to trade,
and any Discord webhook **you** configure yourself in Settings.

Your credentials, trade history, and database stay on your machine.

## No affiliation
ROM PolyBot is an independent project and is **not affiliated with, endorsed
by, or sponsored by** Polymarket, Discord, or any data provider. Your use of
those services is governed by their own terms, and you are responsible for
complying with them.

## Limitation of liability
To the maximum extent permitted by law, the authors and contributors shall not
be liable for any direct, indirect, incidental, special, consequential, or
exemplary damages — including, without limitation, trading losses, lost profits,
missed or erroneous orders, loss of funds, data loss, or actions taken by
Polymarket — arising out of or relating to your use of (or inability to use)
this software, even if advised of the possibility of such damages. Your sole
remedy is to stop using the software.

If you do not agree with any of the above, do not use this software.
