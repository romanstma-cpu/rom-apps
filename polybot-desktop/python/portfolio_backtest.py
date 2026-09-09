"""Portfolio-level backtest for the main engine.

`backtest.py` answers "does a signal have an edge?" by averaging net P&L over
one contract per signal. That deliberately ignores everything an account
actually runs into: a finite bankroll, position sizing, capital locked up in
open positions, and the concurrency and daily caps that stop the bot taking
every signal it likes. A strategy with a positive per-contract edge can still
lose money once those bind, and a strategy that looks marginal can compound
well if its winners free capital quickly.

This module replays resolved signals in chronological order against a
simulated account, sizing each entry through the *live* code path
(`trader._compute_target_usd`, so percent / contracts / Kelly all behave as
configured) and charging the US taker fee in force at each entry.

Known limits, stated rather than hidden:

* Entry is at the recorded signal cost. There is no order book, so no partial
  fills, no slippage beyond what the signal already reflects, and no queue.
* Positions are held to settlement. Take-profit and stop-loss are not
  simulated because main-bot signals carry no post-entry price series.
* Equity between entry and settlement is carried at cost. Drawdown is
  therefore measured on realised settlements, not on marked-to-market swings.
* Daily and lifetime loss guards are not simulated; the caps modelled here are
  the structural ones (concurrency, per-event, daily new positions, exposure
  and cash reserve).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import backtest as bt
import fees_us
import trader

SKIP_REASONS = (
    "max_open_positions",
    "max_daily_new_positions",
    "max_positions_per_event",
    "market_already_open",
    "exposure_cap",
    "cash_reserve",
    "below_minimum_size",
)


def _pricing_at(at: float) -> float:
    """Timestamp used to choose the fee schedule.

    `fees_us` deliberately refuses to price a moment before the first
    published US schedule - live trading must never invent a rate. A backtest
    over older data still has to produce a number, so clamp into the published
    range here and let `count_unpriced_signals` report how many were clamped.
    """
    return max(float(at), fees_us.EARLIEST_START)


def _day_index(at: float, offset_min: int) -> int:
    """Which trading day `at` falls in, honouring the configured UTC offset."""
    return int((at + offset_min * 60.0) // 86400.0)


def _edge_points(confidence: float, cost: float) -> float:
    """Edge in percentage points, matching `trader._compute_edge`."""
    implied = max(5.0, min(cost * 100.0, 95.0))
    return float(confidence) - implied


def _limit_cents(cost: float) -> int:
    return max(1, min(99, int(round(cost * 100.0))))


class Account:
    """A simulated account: cash, open positions, and the caps that bind."""

    def __init__(self, cfg: dict, start_bankroll_usd: float) -> None:
        self.cfg = cfg
        self.start = float(start_bankroll_usd)
        self.cash = float(start_bankroll_usd)
        self.open: list[dict] = []
        self.day_counts: dict[int, int] = {}
        self.offset_min = trader.trading_day_offset_min(cfg)
        self.fees_paid = 0.0
        self.entered_usd = 0.0
        self.entries = 0
        self.wins = 0
        self.losses = 0
        self.peak_concurrent = 0
        self.skips: dict[str, int] = {r: 0 for r in SKIP_REASONS}
        self.equity_curve: list[tuple[float, float]] = []

    # -- accounting ------------------------------------------------------

    @property
    def exposure(self) -> float:
        return sum(p["cost_usd"] for p in self.open)

    @property
    def equity(self) -> float:
        """Cash plus open positions at cost. See the module docstring."""
        return self.cash + self.exposure

    @property
    def bankroll(self) -> float:
        return self.cash + self.exposure

    def _record_equity(self, at: float) -> None:
        self.equity_curve.append((at, self.equity))

    # -- entry -----------------------------------------------------------

    def _blocked(self, signal: dict, at: float) -> Optional[str]:
        cfg = self.cfg
        if len(self.open) >= int(cfg["max_open_positions"]):
            return "max_open_positions"
        if not cfg.get("unlimited_daily_new_positions"):
            day = _day_index(at, self.offset_min)
            if self.day_counts.get(day, 0) >= int(cfg["max_daily_new_positions"]):
                return "max_daily_new_positions"
        event = signal.get("event") or ""
        if event:
            per_event = int(cfg.get("max_positions_per_event", 1) or 1)
            if sum(1 for p in self.open if p["event"] == event) >= per_event:
                return "max_positions_per_event"
        ticker = signal.get("ticker") or ""
        if ticker and any(p["ticker"] == ticker for p in self.open):
            return "market_already_open"
        return None

    def try_enter(self, signal: dict, at: float) -> Optional[dict]:
        blocked = self._blocked(signal, at)
        if blocked:
            self.skips[blocked] += 1
            return None

        cfg = self.cfg
        cost = float(signal["cost"])
        limit_cents = _limit_cents(cost)
        edge_pts = _edge_points(float(signal.get("confidence") or 0.0), cost)
        bankroll = self.bankroll

        target = trader._compute_target_usd(bankroll, edge_pts, limit_cents, cfg)
        headroom = bankroll * float(cfg["max_total_exposure_fraction"]) - self.exposure
        spendable = self.cash - bankroll * float(cfg["min_cash_reserve_fraction"])

        # Whichever of these is smallest is the constraint that actually
        # stopped the trade. Reporting "position too small" when the real
        # answer is "you were at your exposure cap" would hide the finding
        # this whole report exists to surface.
        limits = {
            "below_minimum_size": min(target, float(cfg["hard_max_position_usd"])),
            "exposure_cap": headroom,
            "cash_reserve": spendable,
        }
        binding = min(limits, key=lambda k: limits[k])
        budget = max(0.0, limits[binding])

        priced_at = _pricing_at(at)
        contracts = fees_us.affordable_contracts(budget, cost, priced_at)
        if contracts < 1:
            self.skips[binding] += 1
            return None

        fee = fees_us.fee(contracts, cost, priced_at)
        cost_usd = contracts * cost + fee
        if cost_usd > self.cash:
            self.skips["cash_reserve"] += 1
            return None

        self.cash -= cost_usd
        self.fees_paid += fee
        self.entered_usd += cost_usd
        self.entries += 1
        day = _day_index(at, self.offset_min)
        self.day_counts[day] = self.day_counts.get(day, 0) + 1
        position = {
            "ticker": signal.get("ticker") or "",
            "event": signal.get("event") or "",
            "contracts": contracts,
            "cost": cost,
            "cost_usd": cost_usd,
            "fee": fee,
            "correct": bool(signal["correct"]),
            "entered_at": at,
            "resolves_at": float(signal.get("resolved_at") or at),
        }
        self.open.append(position)
        self.peak_concurrent = max(self.peak_concurrent, len(self.open))
        self._record_equity(at)
        return position

    # -- settlement ------------------------------------------------------

    def settle(self, position: dict, at: float) -> float:
        self.open.remove(position)
        payout = position["contracts"] * (1.0 if position["correct"] else 0.0)
        self.cash += payout
        if position["correct"]:
            self.wins += 1
        else:
            self.losses += 1
        self._record_equity(at)
        return payout - position["cost_usd"]


def _max_drawdown(curve: list[tuple[float, float]]) -> float:
    """Largest peak-to-trough fall in equity, as a fraction of the peak."""
    peak = -math.inf
    worst = 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def simulate(
    signals: list[dict], cfg: dict, start_bankroll_usd: float = 1000.0,
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    """Replay `signals` chronologically against a simulated account.

    `min_confidence` stands in for the live entry filters; the structural caps
    come from `cfg`. Signals without a usable timestamp are dropped rather
    than guessed into an arbitrary point in the sequence.
    """
    usable = [
        s for s in signals
        if float(s.get("at") or 0.0) > 0
        and float(s.get("confidence") or 0.0) >= min_confidence
    ]
    account = Account(cfg, start_bankroll_usd)
    account._record_equity(min((float(s["at"]) for s in usable), default=0.0))

    # One chronological timeline: an entry can only use capital that earlier
    # settlements have already returned.
    events: list[tuple[float, int, Any]] = [
        (float(s["at"]), 0, s) for s in usable
    ]
    events.sort(key=lambda e: (e[0], e[1]))

    pending: list[dict] = []
    realised: list[float] = []
    i = 0
    while i < len(events) or pending:
        next_entry = events[i][0] if i < len(events) else math.inf
        next_settle = min((p["resolves_at"] for p in pending), default=math.inf)

        if next_settle <= next_entry:
            due = [p for p in pending if p["resolves_at"] == next_settle]
            for position in due:
                pending.remove(position)
                realised.append(account.settle(position, next_settle))
            continue

        _, _, signal = events[i]
        i += 1
        opened = account.try_enter(signal, float(signal["at"]))
        if opened is not None:
            pending.append(opened)

    considered = len(usable)
    settled = account.wins + account.losses
    final = account.equity
    return {
        "n_signals": considered,
        "n_entered": account.entries,
        "n_settled": settled,
        "wins": account.wins,
        "losses": account.losses,
        "win_rate": (account.wins / settled) if settled else 0.0,
        "fill_rate": (account.entries / considered) if considered else 0.0,
        "start_bankroll": account.start,
        "final_equity": final,
        "total_return": ((final / account.start) - 1.0) if account.start > 0 else 0.0,
        "total_pnl": final - account.start,
        "fees_paid": account.fees_paid,
        "max_drawdown": _max_drawdown(account.equity_curve),
        "peak_concurrent": account.peak_concurrent,
        "avg_position_usd": (
            account.entered_usd / account.entries if account.entries else 0.0
        ),
        "best_trade": max(realised, default=0.0),
        "worst_trade": min(realised, default=0.0),
        "skips": dict(account.skips),
        "unpriced_signals": bt.count_unpriced_signals(usable),
        "equity_curve": account.equity_curve,
    }


def _money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.2f}"


SKIP_LABELS = {
    "max_open_positions": "at max open positions",
    "max_daily_new_positions": "daily new-position cap reached",
    "max_positions_per_event": "event already had a position",
    "market_already_open": "same market already open",
    "exposure_cap": "total exposure cap reached",
    "cash_reserve": "cash reserve would be breached",
    "below_minimum_size": "sized below one contract",
}


def format_portfolio_report(
    result: dict, cfg: dict, source_label: str, config_label: str = "",
) -> str:
    """Render a simulation as a report whose caveats are on the page."""
    L: list[str] = []
    L.append("=== ROM PolyBot - portfolio backtest ===")
    L.append(f"source: {source_label}")
    if config_label:
        L.append(f"config: {config_label}")

    mode = (cfg.get("sizing_mode") or "percent").lower()
    if mode == "kelly":
        sizing = (f"kelly at {float(cfg['kelly_fraction']) * 100:.0f}% of full, "
                  f"clamped {float(cfg['min_size_fraction']) * 100:.1f}%"
                  f"-{float(cfg['max_size_fraction']) * 100:.1f}% of bankroll")
    elif mode == "contracts":
        sizing = f"{cfg['min_contracts']}-{cfg['max_contracts']} contracts by edge"
    else:
        sizing = (f"{float(cfg['min_size_fraction']) * 100:.1f}%"
                  f"-{float(cfg['max_size_fraction']) * 100:.1f}% of bankroll by edge")
    offset = trader.trading_day_offset_min(cfg)
    L.append(f"sizing: {sizing}, {_money(float(cfg['hard_max_position_usd']))} hard cap")
    L.append(
        f"caps:   {cfg['max_open_positions']} open - "
        f"{cfg['max_positions_per_event']} per event - "
        f"{cfg['max_daily_new_positions']}/day (UTC{offset / 60:+.0f}) - "
        f"{float(cfg['max_total_exposure_fraction']) * 100:.0f}% max exposure - "
        f"{float(cfg['min_cash_reserve_fraction']) * 100:.0f}% cash reserve"
    )
    L.append("fees:   US taker fee, theta from the schedule in force at each entry")
    if result.get("unpriced_signals"):
        L.append(f"        ({result['unpriced_signals']} signal(s) predate the first "
                 f"published schedule; priced at the earliest known theta)")
    L.append("")

    if result["n_signals"] == 0:
        L.append("No timestamped resolved signals found. Let the bot run until")
        L.append("signals settle, then re-run this.")
        return "\n".join(L)

    L.append("ACCOUNT")
    L.append(f"  starting bankroll   {_money(result['start_bankroll'])}")
    L.append(f"  final equity        {_money(result['final_equity'])}")
    L.append(f"  total P&L           {_money(result['total_pnl'])}")
    L.append(f"  total return        {result['total_return'] * 100:+.1f}%")
    L.append(f"  max drawdown        {-result['max_drawdown'] * 100:.1f}%")
    L.append(f"  fees paid           {_money(result['fees_paid'])}")
    L.append("")

    L.append("ACTIVITY")
    L.append(f"  signals considered  {result['n_signals']}")
    L.append(f"  entered             {result['n_entered']}"
             f"  ({result['fill_rate'] * 100:.0f}% of signals)")
    L.append(f"  settled             {result['n_settled']}"
             f"  (win rate {result['win_rate'] * 100:.0f}%)")
    L.append(f"  avg position        {_money(result['avg_position_usd'])}")
    L.append(f"  peak concurrent     {result['peak_concurrent']}")
    L.append(f"  best / worst trade  {_money(result['best_trade'])}"
             f" / {_money(result['worst_trade'])}")

    skipped = result["n_signals"] - result["n_entered"]
    if skipped > 0:
        L.append("")
        L.append(f"WHY {skipped} SIGNAL(S) WERE NOT TAKEN")
        for reason, count in sorted(
            result["skips"].items(), key=lambda kv: -kv[1]
        ):
            if count:
                L.append(f"  {SKIP_LABELS.get(reason, reason):<34} {count}")
        L.append("")
        L.append("  A high count here means the strategy found more edge than the")
        L.append("  account could act on. Per-contract backtests never show this.")

    L.append("")
    L.append("CAVEATS")
    L.append("  - Entry at the recorded signal price; no book, no partial fills.")
    L.append("  - Held to settlement; take-profit and stop-loss are not simulated.")
    L.append("  - Equity carried at cost between entry and settlement, so drawdown")
    L.append("    reflects realised settlements only.")
    L.append("  - Daily and lifetime loss guards are not simulated.")
    L.append("  - Past settlement outcomes are not a forecast.")
    return "\n".join(L)
