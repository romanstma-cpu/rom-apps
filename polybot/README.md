# PolyBot — open Polymarket trading bot

A transparent, self-hosted remake of the Krypt PolyBot concept: an automated
trading bot for [Polymarket](https://polymarket.com) that watches live markets,
order flow, volume, and price action, and enters/manages positions from
configurable strategies instead of emotion. No black box — every signal, rule,
and trade decision is plain Python you can read and change.

## Features

- **Strategies** (enable any mix, tune each independently):
  - `momentum` — buy into sustained short-term price moves
  - `mean_reversion` — fade over-extended moves back toward the recent mean
  - `volume_spike` — react to sudden volume surges relative to baseline
  - `trend_continuation` — join established multi-window trends on pullbacks
  - `spread_scalp` — quote inside wide spreads on liquid markets
  - `whale_follow` — mirror unusually large trades from the public trade feed
  - `sentiment_shift` — trade sharp changes in order-book imbalance
  - `manual` — no auto entries; the engine only manages exits for you
- **Category-based trading** — politics, crypto, sports, culture, finance,
  news… monitor any Polymarket categories, with per-category overrides.
- **Risk manager** — max position size, max open positions, per-category caps,
  daily loss stop, price band filters, take-profit / stop-loss exits.
- **Paper mode by default** — full simulation against live market data with a
  local portfolio ledger. Live mode uses `py-clob-client` and is opt-in.
- **Plain data sources** — Polymarket's public Gamma API (market discovery)
  and CLOB API (books, prices, trade tape). No accounts needed to observe.

## Quick start

```bash
cd polybot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # then edit to taste
python -m polybot run                # paper trading (default)
python -m polybot scan               # one-shot: show markets + signals
```

## Windows

Two options:

- **PolyBot.exe (no Python needed)** — the GitHub Actions workflow
  `build-polybot-windows.yml` builds a standalone `PolyBot.exe` with
  PyInstaller on every push touching `polybot/` (also runnable manually from
  the Actions tab). Download the `PolyBot-windows` artifact, put a
  `config.yaml` next to the exe (optional — it falls back to the bundled
  example config in paper mode), and double-click. Your browser opens the
  dashboard at `http://127.0.0.1:8543`.
- **From source** — install Python 3.10+ from python.org (tick "Add to
  PATH"), then double-click `windows\run.bat`. It creates a venv, installs
  dependencies, copies the example config, and opens the dashboard.

## Dashboard

`python -m polybot ui` runs the engine and serves a local dashboard
(cash, open/realized P&L, watched markets, positions, activity feed, and a
pause/resume button for new entries). Local only — it binds to 127.0.0.1.

## Live trading (optional)

Paper mode is the default and needs no keys. To trade live:

1. `pip install py-clob-client`
2. Set `mode: live` in `config.yaml` and export:
   - `POLYBOT_PRIVATE_KEY` — your Polygon wallet private key
   - `POLYBOT_FUNDER` — your Polymarket proxy wallet address (if used)
3. Start small. Prediction markets are volatile; this software carries no
   warranty and you are responsible for your own trades.

## Layout

```
polybot/
  config.py      # YAML config + env loading
  models.py      # Market, Snapshot, Signal, Position dataclasses
  gamma.py       # Gamma API client (market discovery, categories)
  clob.py        # CLOB API client (midpoints, books, trade tape)
  strategies/    # one file per strategy, all subclass Strategy
  risk.py        # RiskManager: entry gating + exit rules
  portfolio.py   # paper ledger (JSON on disk) and P&L
  executor.py    # PaperExecutor / LiveExecutor
  engine.py      # the polling loop wiring it all together
  cli.py         # `run`, `scan`, `portfolio` commands
```
