from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_APPDATA = os.environ.get("APPDATA") or (Path.home() / ".config")
os.environ.setdefault("ROM_POLYBOT_USERDATA", str(Path(_APPDATA) / "ROM PolyBot"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import db
import config as cfgmod
import polymarket_auth as pa
import crypto15m
import crypto15m_trader
import spot_ws
import rtds_ws

CONFIG = {
    "crypto15m_enabled": True,
    "crypto15m_interval": "15m",
    "crypto15m_use_rules": True,
    "crypto15m_rules": [
        {"field": "velocity1mPct", "op": ">", "value": 0.1},
        {"field": "upAsk", "op": ">=", "value": 0.01},
        {"field": "upAsk", "op": "<=", "value": 0.65},
    ],
    "crypto15m_rules_no": [
        {"field": "velocity1mPct", "op": "<", "value": -0.1},
        {"field": "downAsk", "op": ">=", "value": 0.01},
        {"field": "downAsk", "op": "<=", "value": 0.65},
    ],
    "crypto15m_assets": ["BTC"],
    "crypto15m_direction_mode": "contrarian",
    "crypto15m_entry_max": 0.80,
    "crypto15m_entry_style": "taker",
    "crypto15m_autosize_to_min_notional": True,
    "crypto15m_sizing_mode": "fixed",
    "crypto15m_order_size": 5,
    "crypto15m_max_concurrent": 5,
    "crypto15m_daily_loss_limit": -20.0,
    "crypto15m_take_profit_pct": 0.0,
    "crypto15m_exit_threshold": 0.0,
    "crypto15m_stop_loss_pct": 0.0,
    "crypto15m_take_profit": 0.0,
    "crypto15m_sell_into_strength": False,
}

_POLL_SEC = 4.0


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _fmt_btc(a: dict) -> str:
    def g(k):
        v = a.get(k)
        return f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
    return (f"vel1m={g('velocity1mPct')}%  upAsk={g('upAsk')}  downAsk={g('downAsk')}  "
            f"fav={a.get('favorite')}  minsLeft={a.get('minsLeft')}  spot={g('spot')}")


def _btc(snap: dict) -> dict | None:
    assets = snap.get("assets") if isinstance(snap, dict) else snap
    for a in (assets or []):
        if a.get("asset") == "BTC":
            return a
    return None


async def _warm_feeds() -> None:
    if not spot_ws.is_running():
        spot_ws.start()
    if not rtds_ws.is_running():
        rtds_ws.start()
    await asyncio.sleep(3.0)


async def preflight() -> None:
    db.init_db()
    cfg = cfgmod.merge_with_defaults(dict(CONFIG))
    print(f"[{_ts()}] creds_present={pa.credentials_present()} env={pa.get_env()}")
    print(f"[{_ts()}] is_directional={crypto15m_trader._is_directional_rules(cfg)}  "
          f"rules={len(cfg['crypto15m_rules'])} rules_no={len(cfg['crypto15m_rules_no'])} "
          f"interval={cfg.get('crypto15m_interval')}")
    await _warm_feeds()
    for i in range(5):
        snap = await crypto15m.snapshot(cfg)
        a = _btc(snap)
        if not a:
            print(f"[{_ts()}] no BTC asset in snapshot")
        else:
            side, why = crypto15m_trader._directional_rules_side(a, cfg)
            fire = "  >>> WOULD ENTER" if side else ""
            print(f"[{_ts()}] {_fmt_btc(a)}  -> side={side!r} ({why}){fire}")
        await asyncio.sleep(6.0)
    print(f"[{_ts()}] preflight done (no orders placed).")


async def live() -> None:
    db.init_db()
    cfg = cfgmod.merge_with_defaults(dict(CONFIG))
    assert pa.credentials_present(), "no credentials on this account"
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("crypto15m_trader").setLevel(logging.INFO)

    print(f"[{_ts()}] ARMED LIVE — BTC momentum, 5ct/entry, max 5 concurrent, "
          f"-$20 daily stop, 15m, taker. env={pa.get_env()}")
    await _warm_feeds()

    ticks = 0
    last_status = 0.0
    while True:
        ticks += 1
        try:
            changed = await crypto15m_trader.run_tick(cfg, authed=True)
        except Exception as e:
            print(f"[{_ts()}] run_tick ERROR: {e!r}")
            changed = []
        for row in (changed or []):
            print(f"[{_ts()}] *** POSITION CHANGE: asset={row.get('asset')} "
                  f"side={row.get('side')} status={row.get('status')} "
                  f"qty={row.get('shares') or row.get('qty')} "
                  f"price={row.get('avg_price') or row.get('price')} "
                  f"reason={row.get('exit_reason') or row.get('reason') or 'entry'}")
        now = time.time()
        if now - last_status >= 20:
            last_status = now
            try:
                snap = await crypto15m.snapshot(cfg)
                a = _btc(snap) or {}
                with db.get_db() as conn:
                    openpos = db.get_open_crypto15m(conn, pa.get_env())
                side, _ = crypto15m_trader._directional_rules_side(a, cfg) if a else (None, "")
                print(f"[{_ts()}] hb tick={ticks} open={len(openpos)} "
                      f"signal={side or '-'}  {_fmt_btc(a) if a else 'no snap'}")
            except Exception as e:
                print(f"[{_ts()}] hb error: {e!r}")
        await asyncio.sleep(_POLL_SEC)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    if mode == "live":
        asyncio.run(live())
    else:
        asyncio.run(preflight())


if __name__ == "__main__":
    main()
