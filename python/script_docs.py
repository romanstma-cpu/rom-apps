from __future__ import annotations

import db as dbmod
import replay

LIVE_ONLY_FIELDS = ("bookImbalance", "peersAgree", "marketBias", "arbEdgeCents")

FIELD_DOCS: dict[str, str] = {
    "asset": "str — coin symbol: BTC, ETH, SOL, XRP, DOGE, HYPE or BNB",
    "ticker": "str — the market's unique id for this window",
    "series": "str — series id, e.g. 'BTC-updown'",
    "hasMarket": "bool — a live Up/Down market exists right now",
    "closeTime": "str — ISO close time of the current window",
    "minsLeft": "float|None — minutes until the window settles",
    "hourUtc": "int|None — current UTC hour 0-23",
    "inWindow": "bool — inside the configured entry window (time_delay_min)",
    "signal": "bool — the built-in favorite-follow signal fired this tick",
    "favorite": "str|None — 'up' or 'down', the side priced >= 50%",
    "favoritePrice": "float|None — favorite mid probability, 0..1",
    "entryCost": "float|None — cost to BUY the favorite, 0..1",
    "upProb": "float|None — up/yes mid probability, 0..1",
    "downProb": "float|None — 1 - upProb",
    "upAsk": "float|None — REAL order-book best ask for UP, 0..1 (None = no live book — you cannot buy up this tick)",
    "downAsk": "float|None — REAL order-book best ask for DOWN, 0..1 (None = no live book)",
    "yesBid": "float|None — yes/up best bid, 0..1",
    "yesAsk": "float|None — yes/up best ask (may be a lagging Gamma mid; prefer upAsk)",
    "deltaPct": "float|None — abs(spot - window open)/open, fraction",
    "deltaSignedPct": "float|None — (spot - open)/open, SIGNED fraction (positive = price above open)",
    "sigma1m": "float|None — realized 1-min volatility of the underlying (fraction/sqrt-min)",
    "spotUsd": "float|None — live underlying price, USD",
    "strikeUsd": "float|None — the window-open reference the market settles against, USD",
    "spotLive": "bool — a live websocket spot feed is up (vs slower REST)",
    "modelProb": "float|None — the app's terminal-spot model P(up), 0..1",
    "edgeNetCents": "float|None — the model's best fee-net edge across both sides, cents",
    "macd": "float|None — MACD line on 1-min underlying closes",
    "macdSignal": "float|None — MACD signal line",
    "macdHist": "float|None — MACD histogram (macd - signal)",
    "macdCross": "int|None — +1 bullish cross this bar, -1 bearish, 0 none",
    "rsi": "float|None — Wilder RSI(14) on 1-min closes, 0..100",
    "vwap1h": "float|None — 1-hour VWAP of the underlying, USD",
    "ema12": "float|None — EMA(12) of 1-min closes, USD",
    "sma20": "float|None — SMA(20) of 1-min closes, USD",
    "sma50": "float|None — SMA(50) of 1-min closes, USD",
    "priceVsVwapPct": "float|None — (spot - vwap1h)/vwap1h, percent (>0 = above VWAP)",
    "ema12VsSma20Pct": "float|None — (ema12 - sma20)/sma20, percent",
    "ema1VsSma5Pct": "float|None — (ema1 - sma5)/sma5, percent (fast momentum)",
    "velocity1mPct": "float|None — 1-minute percent change of the underlying",
    "change5mPct": "float|None — 5-minute percent change",
    "change15mPct": "float|None — 15-minute percent change",
    "spreadCents": "float|None — yes ask minus yes bid, in cents (book width / liquidity: a wide spread means a costly round trip)",
    "modelEdgePts": "float|None — signed (modelProb - upProb) in percentage points: >0 = the model thinks UP is underpriced vs the book's mid",
    "favoriteAskCents": "float|None — the favorite side's REAL executable ask in cents (None = no live book on that side)",
    "timeFracLeft": "float|None — fraction of the window still to run, 0..1 — use this instead of minsLeft to write one script that works on the 5m, 15m and hourly series",
    "bookImbalance": "float|None — (bid-ask)/(bid+ask) volume on the up token, -1..1",
    "peersAgree": "int|None — how many other coins' favorites point the same way",
    "marketBias": "float|None — snapshot-wide up-bias across coins",
    "arbEdgeCents": "float|None — up+down combined-ask arb edge, cents",
}

CONTRACT_DOC = '''\
Your reply must be EXACTLY one fenced ```python code block and nothing else —
no prose before or after it. The first lines of the script MUST be this
metadata header (comments):

# rom-script v1
# name: <short strategy name>
# description: <one sentence>

The script must define a top-level function:

    def decide(ctx):
        ...

`decide(ctx)` is called once per coin per engine tick (~every 5s live; once
per recorded tick, ~25s apart, in backtest) while an Up/Down market is open.
`ctx` is a plain dict of market fields (full reference below). Return None
to do nothing, or an order-intent dict to buy one side of the market:

    {"side": "up" | "down",        # REQUIRED - which side to buy
     "price": "ask" | <int 1-99>,  # REQUIRED - "ask" = cross the real book
                                   #   now (taker). An integer rests a limit
                                   #   at that many cents (fills only if the
                                   #   ask comes to it; not modeled as a
                                   #   maker fill in backtests).
     "size": <int>,                # optional contracts; capped by the user's
                                   #   safety rails, defaulted from settings
     "take_profit_pct": <float>,   # optional, e.g. 0.15 = sell at +15%
     "stop_loss_cents": <int>,     # optional, sell if our side's bid <= this
     "reason": "<short note>"}     # optional, shown in the trade history

Winning contracts settle at $1.00, losing at $0.00. Taker fee per contract:
theta x P x (1 - P) dollars at price P, where theta is the Polymarket US
schedule in force when the order is placed (0.06 since 1 Jul 2026, 0.05
before). At 0.06 that is ~1.5c at 50c and ~0.5c at 90c.
At most ONE position per market window per script — after your first intent
in a window (even one refused by the rails) that window is consumed.

ctx["portfolio"] is always present: {"balanceUsd" (None in backtests),
"openCount", "openPositions" (list of this script's open position dicts),
"todayPnlUsd"} — use it for "stop after -$10 today" / "size down when busy"
logic.

OPTIONAL HOOKS (define any subset; a script must define at least one of
decide / decide_market / manage / decide_signal / supervise):

    def manage(position, ctx):
        # Called every tick for EACH open position this script holds.
        # Return None or "hold" to keep holding, "sell" to flatten NOW at
        # the bid, or {"action": "update", "take_profit_pct": 0.2,
        # "stop_loss_cents": 30} to retune the exit targets (0 clears one).
        # This is how you build trailing stops, signal-reversal exits, and
        # time-based exits. `position`: {ticker, asset, side, contracts,
        # avgEntryCents, curBidCents, minsLeft, tpPct, slCents,
        # unrealizedPct}.

    def decide_market(market):
        # Called once per tick for each of the top general Polymarket markets
        # by volume (NOT the crypto Up/Down windows — decide() owns those).
        # This is how a script trades politics, sports, news, etc. Return None
        # to skip, or an intent:
        #   {"side": "yes"|"no",          # REQUIRED - which outcome to buy
        #    "price": "ask"|<int 1-99>,   # REQUIRED - cross the book, or rest
        #    "size": <int>,               # optional contracts
        #    "sizeUsd": <float>,          # optional dollars (ignored if size)
        #    "reason": "<short note>"}
        # `market`: {ticker, eventTicker, title, category, slug, closeTime,
        # hoursToClose, status, yesBid, yesAsk, noBid, noAsk, yesMid, noMid,
        # lastPrice, prevPrice, priceChange, spreadCents, volume, volume24h,
        # openInterest} — prices are FRACTIONS 0..1 and come from the app's
        # last cached quote; the REAL book is fetched only when you actually
        # return an intent. At most ONE entry per market per script.
        #   hoursToClose — hours until settlement (None if unknown). Gate on
        #     this: many markets priced 90-99c are long-dated futures, so
        #     "hold to settlement" can mean months of locked capital.
        #   spreadCents  — None unless the row carries a real two-sided book,
        #     which the market list usually does NOT. The real spread is
        #     enforced at submit by the "Max spread" rail at the top of this
        #     page (script_market_max_spread_cents, default 2c, 0 = off).
        #   volume24h    — prefer over `volume` (lifetime) to find LIVE events.
        # NOTE: decide_market() is NOT simulated in backtests (the recorded
        # corpus only covers crypto windows) — use SHADOW mode to validate it.

    def decide_signal(signal):
        # Called for each NEW whale/momentum signal the scanner records.
        # Return None to skip, True to follow it, or {"follow": True,
        # "sizeUsd": 10} to size it. Follows buy the SIGNAL'S side (you
        # filter and size; side-flipping isn't supported because it can't
        # be backtested honestly). `signal`: {source: "whale"|"momentum",
        # ticker, category, title, price (0..1), side, dollarValue,
        # confidence, edgePts, costCents, signalType, hourUtc, createdAt}.

    def supervise(app):
        # Called once per engine tick. Return None or {"set": {key: value}}
        # to change WHITELISTED app config — this is how a script switches
        # engines/strategy posture dynamically ("volatility high -> model
        # mode", "past 2am UTC -> disable momentum"). Whitelisted keys:
        # enable_trading, trade_whales, trade_momentum, crypto15m_enabled,
        # copy_enabled (booleans); crypto15m_direction_mode
        # ("favorite"|"contrarian"|"model"); crypto15m_entry_threshold,
        # crypto15m_entry_max, crypto15m_min_delta_pct,
        # crypto15m_time_delay_min (numbers). Anything else is ignored.
        # Rate-limited to one change per 30s; every change is logged.
        # `app`: {hourUtc, balanceUsd, scriptTodayPnlUsd, engines: {...},
        # config: {current whitelisted values}, assets: [{asset, minsLeft,
        # sigma1m, modelProb, favoritePrice}]}.
        # NOTE: supervise() is NOT simulated in backtests, and it does NOT
        # run while the script is in shadow mode — it is the one hook that
        # changes the REAL engine, so shadow skips it (the heartbeat says so).
        # Arm the script to let it supervise.

    def on_start(state):            # once when the script loads
    def on_fill(position, state):   # an entry order filled
    def on_settle(position, state): # a position exited or settled

Pre-injected globals (no import needed): `math`, `statistics`, `state` (a
persistent dict that survives between ticks — use it for cross-tick memory),
and `log(msg)` (shows in the app's Script log panel; print() is aliased to
it). Scripts are ordinary Python and MAY import from the standard library —
but see the rules below, because the app audits what you import.
'''

EXAMPLE_SIMPLE = '''\
# rom-script v1
# name: Late Favorite Follow
# description: Buys the favorite in the last 3 minutes when it is 80-95c with a real book.

def decide(ctx):
    ml = ctx["minsLeft"]
    if ml is None or ml > 3.0:
        return None
    fav = ctx["favorite"]
    if fav not in ("up", "down"):
        return None
    ask = ctx["upAsk"] if fav == "up" else ctx["downAsk"]
    if ask is None:
        return None          # no real book this tick - never trade a phantom quote
    if 0.80 <= ask <= 0.95:
        return {"side": fav, "price": "ask", "reason": "late favorite"}
    return None
'''

EXAMPLE_STATEFUL = '''\
# rom-script v1
# name: Momentum Confirm
# description: Buys the direction of a sustained 5-minute move, confirmed across two ticks, with a stop.

def on_start(state):
    state["last_dir"] = {}

def decide(ctx):
    ch = ctx["change5mPct"]
    ml = ctx["minsLeft"]
    if ch is None or ml is None or ml > 8.0 or ml < 2.0:
        return None
    direction = "up" if ch > 0.05 else ("down" if ch < -0.05 else None)
    prev = state["last_dir"].get(ctx["asset"])
    state["last_dir"][ctx["asset"]] = direction
    if direction is None or prev != direction:
        return None          # need two consecutive ticks agreeing
    ask = ctx["upAsk"] if direction == "up" else ctx["downAsk"]
    if ask is None or ask > 0.65:
        return None          # only take it while the book still prices doubt
    return {"side": direction, "price": "ask",
            "stop_loss_cents": 20, "reason": "5m momentum x2"}
'''


EXAMPLE_MANAGE = '''\
# rom-script v1
# name: Trailing Exit
# description: Buys cheap momentum, then trails a stop up behind the bid instead of holding to settlement.

def decide(ctx):
    ml = ctx["minsLeft"]
    ch = ctx["change5mPct"]
    if ml is None or ch is None or ml > 10.0 or ml < 4.0:
        return None
    direction = "up" if ch > 0.1 else ("down" if ch < -0.1 else None)
    if direction is None:
        return None
    ask = ctx["upAsk"] if direction == "up" else ctx["downAsk"]
    if ask is None or ask > 0.55:
        return None
    return {"side": direction, "price": "ask",
            "stop_loss_cents": 25, "reason": "cheap momentum"}

def manage(position, ctx):
    bid = position["curBidCents"]
    if bid is None:
        return None
    sl = position["slCents"] or 0
    trail = int(bid) - 12            # keep the stop ~12c under the bid
    if trail > sl:
        return {"action": "update", "stop_loss_cents": trail}
    if position["minsLeft"] is not None and position["minsLeft"] < 1.0 and bid >= 85:
        return "sell"                # bank a near-certain win before the wire
    return None
'''

EXAMPLE_SUPERVISOR = '''\
# rom-script v1
# name: Night Shift
# description: Runs the crypto engine in model mode only when volatility is high, and pauses momentum overnight.

def supervise(app):
    changes = {}
    vols = [a["sigma1m"] for a in app["assets"] if a["sigma1m"] is not None]
    if vols:
        hot = max(vols) > 0.002
        want_mode = "model" if hot else "favorite"
        if app["config"]["crypto15m_direction_mode"] != want_mode:
            changes["crypto15m_direction_mode"] = want_mode
    quiet = 2 <= app["hourUtc"] < 8
    if app["engines"]["momentum"] == quiet:
        changes["trade_momentum"] = not quiet
    return {"set": changes} if changes else None
'''


def _inventory(env: str) -> str:
    lines: list[str] = []
    try:
        with dbmod.get_db() as conn:
            rows = conn.execute(
                """SELECT COALESCE(s.interval,'15m') AS iv,
                          COUNT(DISTINCT s.ticker) AS windows,
                          SUM(CASE WHEN s.resolved=1 AND s.up_won IS NOT NULL
                              THEN 1 ELSE 0 END) AS resolved,
                          MIN(s.observed_at) AS a, MAX(s.observed_at) AS b
                   FROM crypto15m_signals s WHERE s.network=?
                   GROUP BY COALESCE(s.interval,'15m')""",
                (env,),
            ).fetchall()
            ticks = conn.execute(
                """SELECT COALESCE(interval,'15m') AS iv, COUNT(*) AS n
                   FROM crypto15m_ticks WHERE network=?
                   GROUP BY COALESCE(interval,'15m')""",
                (env,),
            ).fetchall()
        tick_by_iv = {r["iv"]: int(r["n"] or 0) for r in ticks}
        for r in rows:
            iv = r["iv"]
            lines.append(
                f"- {iv} windows: {int(r['resolved'] or 0)} resolved of "
                f"{int(r['windows'] or 0)} recorded, {tick_by_iv.get(iv, 0)} ticks, "
                f"spanning {str(r['a'] or '?')[:10]} to {str(r['b'] or '?')[:10]}"
            )
    except Exception:
        pass
    if not lines:
        lines.append("- (no recorded windows yet — backtests will be empty until "
                     "the app has run and collected data)")
    return "\n".join(lines)


def build_context_pack(cfg: dict, env: str = "mainnet") -> str:
    interval = str(cfg.get("crypto15m_interval") or "15m")
    fields = []
    for name, doc in FIELD_DOCS.items():
        bt_ok = name in replay._DERIVABLE
        flag = "" if bt_ok else "  [LIVE-ONLY: None during backtests]"
        fields.append(f"- ctx[\"{name}\"]: {doc}{flag}")
    rails = (
        f"- Max entry price: {int(cfg.get('script_max_entry_cents') or 97)}c\n"
        f"- Max contracts per order: {int(cfg.get('script_max_contracts') or 20)}\n"
        f"- Max open positions for this script: {int(cfg.get('script_max_open') or 2)}\n"
        f"- Per-script daily loss auto-disable: ${float(cfg.get('script_daily_loss_usd') or 25.0):.0f}\n"
        f"- Default order size: {int(cfg.get('crypto15m_order_size') or 1)} contracts\n"
        "- Every new script starts in SHADOW mode: it runs against live ticks\n"
        "  and records the orders it WOULD have placed (settled from the real\n"
        "  window outcome, fees charged) without sending anything to the\n"
        "  exchange. The user arms it explicitly. Shadow simulates ENTRIES\n"
        "  only — exits are held to settlement — so don't rely on a shadow\n"
        "  record to validate a manage()-driven exit strategy."
    )
    return f"""You are writing a trading strategy script for ROM PolyBot, a
Polymarket desktop bot. The script trades short-window crypto "Up/Down"
markets (will BTC/ETH/SOL/... close this {interval} window above its open
price?). Each side is a binary contract: win = $1.00, lose = $0.00.

{CONTRACT_DOC}

MARKET CONTEXT FIELDS (every field can be None — ALWAYS check before
comparing; a None you don't check will crash and disable the script):

{chr(10).join(fields)}

EXECUTION RULES:
- The script runs as FULL PYTHON. There is no language sandbox. You may
  import from the standard library, define classes, and use any builtin.
- But the app STATICALLY AUDITS every script and shows the user any network,
  filesystem, subprocess, credential or dynamic-execution access it finds,
  flagged as critical. A strategy needs NONE of those. Do not import
  requests/urllib/socket/os/subprocess/base64/pickle, do not read or write
  files, do not call eval/exec/getattr-with-a-computed-name, and do not
  reference the app's own modules. A script that trips the audit will be
  shown to the user as suspicious, and rightly so — write a plain strategy.
- Hooks are called SYNCHRONOUSLY on the engine loop and must return fast:
  the per-call ceiling is ~1 second of wall clock and the whole trading loop
  waits behind you. No sleeping, no network calls, no heavy loops per tick —
  precompute into `state` incrementally instead. Use `def`, never
  `async def`.

THE USER'S SAFETY RAILS (applied to every intent — your script cannot
override these):
{rails}

THE USER'S RECORDED DATA (what a backtest can replay, {interval} is the
currently selected interval):
{_inventory(env)}

STRATEGY NOTES (hard-won, respect them):
- upAsk/downAsk are the REAL order book. When they are None there is no
  executable quote and returning an intent does nothing useful — check them.
- These markets are efficiently priced most of the time; blindly buying the
  favorite loses the fee. An edge needs a reason: spot has moved and the
  book lags, momentum persistence, model-vs-book divergence (modelProb vs
  the ask), timing (minsLeft), regime filters (sigma1m, RSI).
- Backtest fills are at the recorded ask, ticks are ~25s apart, and the
  panel is in-sample — a green backtest is a hypothesis, not a promise.
- Positions hold to settlement unless you set take_profit_pct /
  stop_loss_cents; these markets can gap to zero, so size for full loss.

THREE VALID EXAMPLES (format + None-checking to imitate):

```python
{EXAMPLE_SIMPLE}```

```python
{EXAMPLE_STATEFUL}```

```python
{EXAMPLE_MANAGE}```

Now write ONE script implementing the strategy the user describes below (or
if they described none, propose a sensible one using the fields above).
Reply with ONLY the fenced python block.
"""
