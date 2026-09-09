from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

import polymarket_auth as auth
import polymarket_api as api
from polymarket_api import PolymarketAPIError

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("volume_farm")


@dataclass
class Progress:
    volume_usd: float = 0.0
    cost_usd: float = 0.0
    round_trips: int = 0
    stuck_shares: float = 0.0

    def add(self, vol: float, cost: float) -> None:
        self.volume_usd += vol
        self.cost_usd += cost
        self.round_trips += 1


def _state_path(args) -> Path:
    if args.state_file:
        return Path(args.state_file)
    base = os.environ.get("ROM_POLYBOT_USERDATA")
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / "volume_farm_state.json"


def _load_progress(args) -> Progress:
    if args.reset:
        return Progress()
    p = _state_path(args)
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            prog = Progress(**{k: d.get(k, 0) for k in Progress().__dict__})
            if prog.stuck_shares > 0:
                log.warning(
                    f"prior run left {prog.stuck_shares:.0f} un-sold shares; clearing "
                    "the block. (They settle on their own — flatten manually if you want.)"
                )
                prog.stuck_shares = 0.0
            return prog
        except Exception as e:
            log.warning(f"could not read state file ({e}); starting fresh")
    return Progress()


def _save_progress(args, prog: Progress) -> None:
    if not args.live:
        return
    p = _state_path(args)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(prog), indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"could not write state file: {e}")


async def _yes_book(ticker: str) -> dict | None:
    meta = await api.get_market_meta(ticker)
    if not meta or not meta.get("yes_token"):
        return None
    try:
        book = await api._book(ticker)
        data = {key: [{"price": row["px"]["value"], "size": row["qty"]}
                      for row in book.get(source, [])]
                for key, source in (("bids", "bids"), ("asks", "offers"))}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    def _rows(key: str) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for r in (data.get(key) or []):
            try:
                out.append((float(r["price"]), float(r["size"])))
            except (TypeError, ValueError, KeyError):
                continue
        return out

    bids, asks = _rows("bids"), _rows("asks")
    if not bids or not asks:
        return None
    bb = max(bids, key=lambda x: x[0])
    ba = min(asks, key=lambda x: x[0])
    bid_c, ask_c = int(round(bb[0] * 100)), int(round(ba[0] * 100))
    if not (1 <= bid_c < ask_c <= 99):
        return None
    return {
        "bid": bid_c, "ask": ask_c,
        "bid_size": bb[1], "ask_size": ba[1],
        "min_size": int(float(meta.get("min_size") or 5)),
    }


async def pick_market(args) -> dict | None:
    if args.ticker:
        bk = await _yes_book(args.ticker)
        meta = await api.get_market_meta(args.ticker)
        if not bk or not meta:
            log.error(f"no usable two-sided book for {args.ticker}")
            return None
        return {"ticker": args.ticker, "title": (meta.get("title") or args.ticker)[:70], **bk}

    log.info("scanning the most-liquid markets for the tightest spread...")
    markets = await api.fetch_markets(limit=100)
    best: dict | None = None
    checked = 0
    for m in markets:
        if checked >= args.scan_depth:
            break
        tkr = m.get("ticker")
        if not tkr:
            continue
        bk = await _yes_book(tkr)
        checked += 1
        if not bk:
            continue
        spread = bk["ask"] - bk["bid"]
        mid = (bk["ask"] + bk["bid"]) / 2
        if mid < args.min_mid or mid > args.max_mid:
            continue
        if min(bk["bid_size"], bk["ask_size"]) < args.min_depth:
            continue
        vol24 = float(m.get("volume_24h_fp") or m.get("volume_24h") or 0)
        score = (spread, abs(mid - args.target_mid), -vol24)
        cand = {
            "ticker": tkr, "title": (m.get("title") or tkr)[:70],
            "spread": spread, "vol24": vol24, "_score": score, **bk,
        }
        if best is None or cand["_score"] < best["_score"]:
            best = cand
        await asyncio.sleep(0.05)
    if best:
        log.info(
            f"picked: {best['title']}  spread={best['spread']}c "
            f"bid/ask={best['bid']}/{best['ask']}c  24h_vol=${best['vol24']:,.0f}  "
            f"depth~{min(best['bid_size'], best['ask_size']):,.0f}"
        )
    else:
        log.error("found no market with a usable two-sided book in the scan window")
    return best


def _parse_order(order: dict) -> tuple[int, float, str]:
    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    filled = int(round(f(order.get("size_matched"))))
    price = f(order.get("price"))
    avg_cents = price * 100
    raw = (order.get("status") or "").lower()
    if "match" in raw:
        status = "filled"
    elif "cancel" in raw or "invalid" in raw:
        status = "canceled"
    elif "live" in raw:
        status = "resting"
    else:
        status = raw or "resting"
    return filled, avg_cents, status


async def _poll_fill(order_id: str, target: int, timeout: float) -> tuple[int, float]:
    if not order_id:
        return 0, 0.0
    deadline = time.time() + timeout
    filled, avg = 0, 0.0
    while time.time() < deadline:
        try:
            resp = await api.get_order(order_id)
            order = (resp.get("order") if isinstance(resp, dict) else resp) or {}
            filled, avg, status = _parse_order(order)
            if filled >= target or status in ("filled", "canceled"):
                break
        except PolymarketAPIError as e:
            log.debug(f"poll {order_id}: HTTP {e.status}")
        except Exception as e:
            log.debug(f"poll {order_id}: {e}")
        await asyncio.sleep(0.8)
    return filled, avg


async def _place(ticker: str, action: str, count: int, price_cents: int) -> str | None:
    coid = f"rom-vol-{uuid.uuid4().hex[:10]}"
    resp = await api.place_limit_order(
        ticker=ticker, side="yes", action=action,
        count=count, price_cents=price_cents, client_order_id=coid,
    )
    order = (resp.get("order") if isinstance(resp, dict) else None) or {}
    return order.get("order_id")


async def round_trip_live(mkt: dict, shares: int, args) -> tuple[float, float, float]:
    ticker = mkt["ticker"]
    bk = await _yes_book(ticker)
    if not bk:
        log.warning("no book; skipping trip")
        return 0.0, 0.0, 0.0
    bid, ask = bk["bid"], bk["ask"]
    if shares > bk["ask_size"]:
        log.warning(f"trip size {shares} > top-ask depth {bk['ask_size']:.0f}; skipping")
        return 0.0, 0.0, 0.0

    buy_px = min(99, ask + args.cross)
    try:
        buy_oid = await _place(ticker, "buy", shares, buy_px)
    except PolymarketAPIError as e:
        log.error(f"buy rejected: HTTP {e.status}: {str(e.body)[:160]}")
        return 0.0, 0.0, 0.0
    bought, _buy_avg = await _poll_fill(buy_oid, shares, args.poll)
    if bought <= 0:
        if buy_oid:
            try:
                await api.cancel_order(buy_oid)
            except Exception:
                pass
        log.warning("buy did not fill; canceled. (book too thin / moved)")
        return 0.0, 0.0, 0.0
    if buy_oid and bought < shares:
        try:
            await api.cancel_order(buy_oid)
        except Exception:
            pass
    buy_notional = bought * ask / 100.0

    await asyncio.sleep(args.settle)

    remaining = bought
    sell_notional = 0.0
    last_err = ""
    for attempt in range(args.sell_retries):
        bk2 = await _yes_book(ticker)
        if not bk2:
            await asyncio.sleep(args.settle)
            continue
        sell_px = max(1, bk2["bid"] - args.cross - attempt)
        try:
            sell_oid = await _place(ticker, "sell", remaining, sell_px)
        except PolymarketAPIError as e:
            last_err = f"HTTP {e.status}: {str(e.body)[:160]}"
            log.warning(f"sell attempt {attempt + 1}/{args.sell_retries} rejected: {last_err}")
            await asyncio.sleep(args.settle * (attempt + 1))
            continue
        sold, _sell_avg = await _poll_fill(sell_oid, remaining, args.poll)
        if sold > 0:
            sell_notional += sold * bk2["bid"] / 100.0
            remaining -= sold
        if remaining <= 0:
            break
        if sell_oid:
            try:
                await api.cancel_order(sell_oid)
            except Exception:
                pass

    volume = buy_notional + sell_notional
    cost = buy_notional - sell_notional
    if remaining > 0:
        log.warning(f"[!] left holding {remaining} shares; could not sell back.")
        if "balance" in last_err.lower() or "allowance" in last_err.lower():
            log.error(
                "sell kept failing on a BALANCE/ALLOWANCE error. Most likely one of:\n"
                "  1) settlement lag — raise --settle (e.g. --settle 8) and retry; or\n"
                "  2) your wallet has never granted the one-time CONDITIONAL-TOKEN\n"
                "     (CTF) approval needed to SELL. The buy-only main bot never\n"
                "     needs it, so a sell-only account can be missing it.\n"
                "  DEFINITIVE TEST: try selling the stuck shares MANUALLY in the\n"
                "  Polymarket app. If that also fails -> it's the approval (fix it\n"
                "  in Polymarket's UI). If it works -> it was lag (raise --settle)."
            )
        else:
            log.warning("Exit the leftover shares manually in the app.")
    return volume, cost, float(remaining)


def project(mkt: dict, shares: int, prog: Progress, args) -> None:
    bid, ask = mkt["bid"], mkt["ask"]
    spread = ask - bid
    vol_per_trip = shares * (ask + bid) / 100.0
    cost_per_trip = shares * spread / 100.0
    remaining_vol = max(0.0, args.target - prog.volume_usd)
    trips = int(remaining_vol / vol_per_trip) + 1 if remaining_vol > 0 else 0
    proj_cost = trips * cost_per_trip
    eta_min = trips * (args.poll * 1.4 + 1.0) / 60.0

    bar = "=" * 56
    print()
    print(bar)
    print("  DRY-RUN PROJECTION (no orders placed)")
    print(bar)
    print(f" market        : {mkt['title']}")
    print(f" ticker        : {mkt['ticker']}")
    print(f" top-of-book   : bid {bid}c / ask {ask}c   (spread {spread}c)")
    print(f" trip size     : {shares} shares")
    print(f" per round trip: +${vol_per_trip:,.2f} volume   ~${cost_per_trip:,.4f} cost")
    print(f" already done  : ${prog.volume_usd:,.2f} volume / ${prog.cost_usd:,.2f} cost"
          f" ({prog.round_trips} trips)")
    print(f" target        : ${args.target:,.0f} volume   budget ${args.budget:,.2f}")
    print(" " + "-" * 52)
    print(f" need ~{trips:,} more round trips")
    print(f" projected cost: ${proj_cost:,.2f}   (budget ${args.budget:,.2f})")
    print(f" projected time: ~{eta_min:,.0f} min at poll={args.poll}s")
    if proj_cost > args.budget:
        max_vol = prog.volume_usd + (args.budget - prog.cost_usd) / max(cost_per_trip, 1e-9) * vol_per_trip
        print(f" [!] projection EXCEEDS budget. Within ${args.budget:,.0f} you'd reach")
        print(f"     about ${max_vol:,.0f} volume. Pick a tighter-spread market, lower")
        print(f"     the trip size, or raise --budget. (Top-of-book estimate; real")
        print(f"     slippage on deeper fills makes it cost MORE, not less.)")
    else:
        print(f" [ok] fits the budget with ${args.budget - proj_cost:,.2f} to spare"
              f" (top-of-book estimate; real slippage adds cost).")
    print(bar)
    print("\nHappy with this? Re-run with  --live --yes  to place real orders.\n")


async def run(args) -> int:
    prog = _load_progress(args)
    mkt = await pick_market(args)
    if not mkt:
        return 2

    shares = max(args.size, mkt.get("min_size", 5))

    if not args.live:
        project(mkt, shares, prog, args)
        return 0

    if not auth.credentials_present():
        log.error(
            "no Polymarket wallet key found. Connect your wallet in the app "
            "first (Wallet tab), or set ROM_POLYBOT_USERDATA to its data dir."
        )
        log.error(f"(looked in: {os.environ.get('ROM_POLYBOT_USERDATA', '<unset>')})")
        return 2
    auth.prime_credentials()
    if not args.yes:
        log.error("refusing to trade live without --yes (safety). Re-run with --live --yes.")
        return 2

    try:
        bal = await api.get_balance()
        cash = int(bal.get("balance", 0)) / 100.0
        need = shares * mkt["ask"] / 100.0
        if cash < need:
            log.error(f"cash ${cash:.2f} < one trip's ${need:.2f} notional. Add funds.")
            return 2
        log.info(f"cash balance: ${cash:,.2f}")
    except Exception as e:
        log.warning(f"could not read balance ({e}); continuing anyway")

    log.info(
        f"LIVE volume farm -> target ${args.target:,.0f} / budget ${args.budget:,.2f}. "
        f"Ctrl-C to stop (progress is saved)."
    )
    log.info(
        "trip 1 is a self-test: it buys then sells back a tiny stake. If the sell "
        "fails, the run aborts cleanly (no runaway buying) and tells you the fix."
    )
    try:
        while prog.volume_usd < args.target and prog.cost_usd < args.budget:
            if prog.stuck_shares > 0:
                log.error("stopping: holding un-sold inventory from a prior trip.")
                break
            worst = shares * (mkt["ask"] - mkt["bid"] + 2 * args.cross) / 100.0
            if prog.cost_usd + worst > args.budget:
                log.info("next trip could exceed budget; stopping cleanly.")
                break

            vol, cost, stuck = await round_trip_live(mkt, shares, args)
            if vol <= 0:
                await asyncio.sleep(args.idle)
                continue
            prog.add(vol, cost)
            prog.stuck_shares += stuck
            _save_progress(args, prog)
            log.info(
                f"trip {prog.round_trips}: +${vol:,.2f} vol (${cost:+.3f} cost)  ->  "
                f"${prog.volume_usd:,.2f}/{args.target:,.0f} vol, "
                f"${prog.cost_usd:,.2f}/{args.budget:,.0f} budget"
            )
            await asyncio.sleep(args.gap)
    except KeyboardInterrupt:
        log.info("interrupted - saving progress.")
    finally:
        _save_progress(args, prog)

    print()
    log.info(
        f"DONE. volume=${prog.volume_usd:,.2f}  cost=${prog.cost_usd:,.2f}  "
        f"trips={prog.round_trips}"
        + (f"  [!] stuck_shares={prog.stuck_shares:.0f}" if prog.stuck_shares else "")
    )
    if prog.volume_usd >= args.target:
        log.info("[done] target volume reached.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TEMP Polymarket volume farmer (round-trips a tiny stake).",
    )
    p.add_argument("--target", type=float, default=10_000, help="target cumulative volume USD (default 10000)")
    p.add_argument("--budget", type=float, default=100.0, help="max spread cost USD before stopping (default 100)")
    p.add_argument("--size", type=int, default=10, help="shares per leg (bumped to market min, usually 5)")
    p.add_argument("--ticker", type=str, default="", help="market conditionId (default: auto-pick deepest/tightest)")
    p.add_argument("--live", action="store_true", help="place REAL orders (default: dry-run projection only)")
    p.add_argument("--yes", action="store_true", help="confirm live trading (required with --live)")
    p.add_argument("--reset", action="store_true", help="reset saved volume/cost progress to zero")
    p.add_argument("--cross", type=int, default=1, help="cents to cross through the spread per leg (default 1)")
    p.add_argument("--poll", type=float, default=6.0, help="seconds to wait for each leg to fill (default 6)")
    p.add_argument("--settle", type=float, default=4.0, help="seconds to let a buy settle before selling it back (default 4)")
    p.add_argument("--gap", type=float, default=1.0, help="seconds between round trips (default 1)")
    p.add_argument("--idle", type=float, default=5.0, help="seconds to back off when the book is thin (default 5)")
    p.add_argument("--sell-retries", type=int, default=4, help="attempts to fully sell back per trip (default 4)")
    p.add_argument("--scan-depth", type=int, default=45, help="how many top markets to book-check when auto-picking")
    p.add_argument("--min-mid", type=float, default=15, help="skip markets priced below this (cents)")
    p.add_argument("--max-mid", type=float, default=85, help="skip markets priced above this (cents)")
    p.add_argument("--target-mid", type=float, default=80, help="prefer markets priced near this (cents) — cost-efficient sweet spot")
    p.add_argument("--min-depth", type=float, default=200, help="require this many shares resting at top-of-book each side")
    p.add_argument("--state-file", type=str, default="", help="override progress file path")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
