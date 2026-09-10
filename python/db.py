from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    base = os.environ.get("ROM_POLYBOT_USERDATA")
    if base:
        d = Path(base) / "data"
    else:
        d = Path(__file__).resolve().parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _vault_dir() -> Path | None:
    try:
        override = os.environ.get("ROM_POLYBOT_VAULT")
        if override:
            base = Path(override)
        else:
            local = os.environ.get("LOCALAPPDATA")
            base = (
                Path(local) / "ROM PolyBot Vault"
                if local else Path.home() / ".rom-polybot-vault"
            )
        tag = "default"
        ud = os.environ.get("ROM_POLYBOT_USERDATA")
        if ud:
            p = Path(ud)
            if p.parent.name.lower() == "accounts" and p.name:
                tag = p.name
        d = base / tag
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return None


_restore_checked = False


def _restore_latest_backup(dest: Path) -> None:
    candidates: list[Path] = []
    bdir = dest.parent / "backups"
    if bdir.is_dir():
        candidates += sorted(bdir.glob("research-*.db"), reverse=True)
    v = _vault_dir()
    if v is not None:
        vf = v / "research-latest.db"
        if vf.exists():
            candidates.append(vf)
    for c in candidates:
        try:
            if c.stat().st_size <= 0:
                continue
            for side in (".db-wal", ".db-shm"):
                sp = dest.with_name(dest.stem + side)
                if sp.exists():
                    sp.unlink()
            shutil.copy2(c, dest)
            logger.warning(f"database missing — restored {c.name} from {c.parent}")
            return
        except OSError:
            continue


def db_path() -> Path:
    global _restore_checked
    p = _data_dir() / "rom-polybot.db"
    if not _restore_checked:
        _restore_checked = True
        if not p.exists():
            _restore_latest_backup(p)
    return p


@contextmanager
def get_db():
    conn = sqlite3.connect(str(db_path()), timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
    except BaseException:
        conn.close()
        raise
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    event_ticker TEXT DEFAULT '',
    series_ticker TEXT DEFAULT '',
    slug TEXT DEFAULT '',
    title TEXT DEFAULT '',
    yes_sub_title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    close_time TEXT DEFAULT '',
    volume REAL DEFAULT 0,
    volume_24h REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    yes_bid REAL DEFAULT 0,
    yes_ask REAL DEFAULT 0,
    last_price REAL DEFAULT 0,
    prev_yes_bid REAL DEFAULT 0,
    prev_price REAL DEFAULT 0,
    result TEXT DEFAULT '',
    settlement_value REAL DEFAULT NULL,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_ticker TEXT PRIMARY KEY,
    series_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    sub_title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    count_fp REAL DEFAULT 0,
    yes_price REAL DEFAULT 0,
    no_price REAL DEFAULT 0,
    taker_side TEXT DEFAULT '',
    dollar_value REAL DEFAULT 0,
    category TEXT DEFAULT '',
    created_time TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    signal_type TEXT DEFAULT '',
    direction TEXT DEFAULT '',
    volume_24h REAL DEFAULT 0,
    price REAL DEFAULT 0,
    price_change REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    score_version TEXT DEFAULT '',
    window_trades INTEGER DEFAULT NULL,
    window_dollars REAL DEFAULT NULL,
    observed_at REAL DEFAULT NULL,
    discord_sent INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    resolved_price REAL DEFAULT NULL,
    pnl_estimate REAL DEFAULT NULL,
    resolved_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS whale_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    yes_sub_title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    taker_side TEXT DEFAULT '',
    count_fp REAL DEFAULT 0,
    price REAL DEFAULT 0,
    dollar_value REAL DEFAULT 0,
    market_volume REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    discord_sent INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    resolved_price REAL DEFAULT NULL,
    pnl_estimate REAL DEFAULT NULL,
    resolved_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    volume REAL DEFAULT 0,
    volume_24h REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    yes_bid REAL DEFAULT 0,
    last_price REAL DEFAULT 0,
    snapshot_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_source TEXT NOT NULL,
    signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    direction TEXT NOT NULL,
    action TEXT DEFAULT 'buy',
    target_contracts INTEGER NOT NULL,
    limit_price_cents INTEGER NOT NULL,
    filled_contracts INTEGER DEFAULT 0,
    avg_fill_price_cents REAL DEFAULT NULL,
    cost_usd REAL DEFAULT 0,
    fees_usd REAL DEFAULT 0,
    client_order_id TEXT UNIQUE NOT NULL,
    order_id TEXT DEFAULT NULL,
    status TEXT NOT NULL,
    confidence REAL DEFAULT 0,
    edge_pts REAL DEFAULT 0,
    signal_price REAL DEFAULT 0,
    error TEXT DEFAULT NULL,
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    settlement_usd REAL DEFAULT NULL,
    pnl_usd REAL DEFAULT NULL,
    closed_early INTEGER DEFAULT 0,
    exit_reason TEXT DEFAULT NULL,
    balance_before_usd REAL DEFAULT NULL,
    mark_price_cents REAL DEFAULT NULL,
    network TEXT DEFAULT 'mainnet',
    created_at TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now')),
    resolved_at TEXT DEFAULT NULL,
    UNIQUE(signal_source, signal_id, network)
);

CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    order_status TEXT DEFAULT NULL,
    filled_contracts INTEGER DEFAULT NULL,
    fill_cost_cents INTEGER DEFAULT NULL,
    note TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_stats (
    day TEXT NOT NULL,
    network TEXT NOT NULL,
    opened INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    realized_pnl_usd REAL DEFAULT 0,
    ending_balance_usd REAL DEFAULT 0,
    last_updated TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(day, network)
);

CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT DEFAULT (datetime('now')),
    network TEXT DEFAULT 'mainnet',
    cash_usd REAL NOT NULL,
    portfolio_usd REAL NOT NULL,
    total_usd REAL NOT NULL,
    realized_pnl_usd REAL DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    open_positions INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crypto15m_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,
    series TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                 -- 'up' | 'down' (display)
    direction TEXT NOT NULL,            -- 'yes' | 'no' (Polymarket side bought)
    target_contracts INTEGER NOT NULL,
    filled_contracts INTEGER DEFAULT 0,
    entry_limit_cents INTEGER NOT NULL,
    avg_entry_cents REAL DEFAULT NULL,
    cost_usd REAL DEFAULT 0,
    client_order_id TEXT UNIQUE NOT NULL,
    order_id TEXT DEFAULT NULL,
    -- stop-loss exit leg
    exit_client_order_id TEXT DEFAULT NULL,
    exit_order_id TEXT DEFAULT NULL,
    exit_limit_cents INTEGER DEFAULT NULL,
    exit_filled_contracts INTEGER DEFAULT 0,
    proceeds_usd REAL DEFAULT NULL,
    -- lifecycle
    status TEXT NOT NULL,               -- dry_run|submitted|filled|exiting|exited|settled|canceled|error
    exit_reason TEXT DEFAULT NULL,      -- 'stop_loss' | 'settlement' | 'unfilled_expired'
    close_time TEXT DEFAULT '',
    confidence REAL DEFAULT 0,          -- favorite prob at entry (×100)
    entry_delta_usd REAL DEFAULT NULL,
    outcome_correct INTEGER DEFAULT NULL,
    settlement_usd REAL DEFAULT NULL,
    pnl_usd REAL DEFAULT NULL,
    resolved INTEGER DEFAULT 0,
    network TEXT DEFAULT 'mainnet',
    dry_run INTEGER DEFAULT 0,
    error TEXT DEFAULT NULL,
    strategy TEXT DEFAULT NULL,         -- which strategy opened it (favorite|contrarian|rules)
    fees_usd REAL DEFAULT 0,            -- venue-reported entry fees (0 if none reported)
    exit_fees_usd REAL DEFAULT 0,       -- venue-reported exit fees
    created_at TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now')),
    resolved_at TEXT DEFAULT NULL
);

-- crypto15m_signals: a passive research log for the 15-min crypto
-- strategy. One row per market (quarter window): a decision-point
-- snapshot captured live (favorite side + price + underlying delta a few
-- minutes before close), then the settled outcome filled in afterward.
-- This is what makes the 15m strategy backtestable — independent of
-- whether the user ever enables the executor. No orders, no money.
CREATE TABLE IF NOT EXISTS crypto15m_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    asset TEXT NOT NULL,
    series TEXT DEFAULT '',
    close_time TEXT DEFAULT '',
    observed_at TEXT DEFAULT (datetime('now')),
    mins_left REAL,                    -- minutes to close at the observation
    favorite TEXT,                     -- 'up' | 'down' at the decision point
    favorite_price REAL,               -- favorite mid probability (fraction)
    entry_cost REAL,                   -- cost to BUY the favorite (fraction)
    up_prob REAL,                      -- yes/up mid probability (fraction)
    delta_pct REAL,                    -- abs(open-live)/open underlying move
    open_spot REAL,
    obs_spot REAL,
    book_imbalance REAL,               -- (bid-ask)/(bid+ask) vol on the up token, [-1,1]
    macd REAL,                         -- underlying MACD line (1-min closes)
    macd_signal REAL,                  -- MACD signal line
    macd_hist REAL,                    -- MACD histogram = macd - signal
    macd_cross INTEGER,                -- +1 bullish / -1 bearish / 0 no cross on this bar
    rsi REAL,                          -- Wilder RSI(14), 0..100
    resolved INTEGER DEFAULT 0,
    up_won INTEGER DEFAULT NULL,       -- 1 if the up/yes side settled true
    settled_at TEXT DEFAULT NULL,
    strike REAL,                       -- window-open reference at the decision point (USD)
    model_prob REAL,                   -- terminal-spot model P(up) at the decision point
    edge_net_cents REAL,               -- model's fee-net edge at the decision point (cents)
    network TEXT DEFAULT 'mainnet'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_c15sig_ticker ON crypto15m_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_c15sig_resolved ON crypto15m_signals(resolved, close_time);

-- crypto15m_ticks: high-frequency companion to crypto15m_signals. One
-- row per active 15-min market every ~25s across the WHOLE window (not
-- just the decision point), so strategies can be tested for entry
-- timing, quote staleness vs spot, and maker-fill behaviour. Outcomes
-- come from joining crypto15m_signals on ticker. Pruned by
-- cleanup_old_data after `_C15_TICKS_KEEP_DAYS`.
CREATE TABLE IF NOT EXISTS crypto15m_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    asset TEXT NOT NULL,
    observed_at TEXT DEFAULT (datetime('now')),
    mins_left REAL,
    yes_bid REAL,                      -- fraction 0..1
    yes_ask REAL,                      -- fraction 0..1
    up_prob REAL,                      -- mid, fraction 0..1
    spot REAL,                         -- live underlying USD
    open_spot REAL,                    -- quarter-open underlying USD
    delta_pct REAL,                    -- abs(open-live)/open
    book_imbalance REAL,               -- (bid-ask)/(bid+ask) vol on the up token, [-1,1]
    macd REAL,                         -- underlying MACD line (1-min closes)
    macd_signal REAL,                  -- MACD signal line
    macd_hist REAL,                    -- MACD histogram = macd - signal
    macd_cross INTEGER,                -- +1 bullish / -1 bearish / 0 no cross on this bar
    rsi REAL,                          -- Wilder RSI(14), 0..100
    ws_bid REAL,                       -- REAL CLOB best bid (favorite side), cents — vs the Gamma mid
    ws_ask REAL,                       -- REAL CLOB best ask (favorite side), cents
    strike REAL,                       -- window-open reference the model measures against (USD)
    delta_signed_pct REAL,             -- (spot-open)/open, SIGNED
    sigma1m REAL,                      -- realized 1-min vol (fraction/√min)
    model_prob REAL,                   -- terminal-spot model P(up), 0..1
    edge_net_cents REAL,               -- model's best fee-net edge (cents)
    no_ask REAL,                       -- down/no token best ask, fraction 0..1
    spot_source TEXT,                  -- which feed supplied `spot` (coinbase-ws/rest/…)
    up_ask REAL,                       -- up/yes token best ask, REAL book only (NULL when WS cold), fraction 0..1
    -- Trend / VWAP fields (Turbine strategy library). Backfillable from
    -- Hyperliquid 1-min candles for rows recorded before they existed.
    vwap1h REAL,                       -- 1-hour volume-weighted avg price (TWAP fallback), USD
    ema12 REAL,                        -- EMA(12) of 1-min closes, USD
    sma20 REAL,                        -- SMA(20) of 1-min closes, USD
    sma50 REAL,                        -- SMA(50) of 1-min closes, USD
    price_vs_vwap_pct REAL,            -- (spot - vwap1h)/vwap1h, percent (>0 = above VWAP)
    ema12_vs_sma20_pct REAL,           -- (ema12 - sma20)/sma20, percent
    ema1_vs_sma5_pct REAL,             -- (ema1 - sma5)/sma5, percent
    velocity1m_pct REAL,               -- 1-min percent change
    change5m_pct REAL,                 -- 5-min percent change
    change15m_pct REAL,                -- 15-min percent change
    network TEXT DEFAULT 'mainnet'
);
CREATE INDEX IF NOT EXISTS idx_c15tick_ticker ON crypto15m_ticks(ticker, observed_at);
CREATE INDEX IF NOT EXISTS idx_c15tick_time ON crypto15m_ticks(observed_at);

-- clob_trades: trade prints from the market WS (last_trade_price events the
-- feed used to DISCARD — 2026-07-16). The raw tape for maker/queue/adverse-
-- selection research: source_ts_ms is the exchange stamp, ingested_at ours.
-- Recorded by the same service loop as crypto15m_ticks; pruned with them.
CREATE TABLE IF NOT EXISTS clob_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    market TEXT,                       -- condition id
    price REAL NOT NULL,               -- fraction 0..1
    size REAL,
    side TEXT,                         -- taker side: BUY / SELL
    source_ts_ms INTEGER,              -- exchange timestamp (ms epoch)
    ingested_at TEXT DEFAULT (datetime('now')),
    tx_hash TEXT,
    network TEXT DEFAULT 'mainnet'
);
CREATE INDEX IF NOT EXISTS idx_clobtr_asset ON clob_trades(asset_id, source_ts_ms);
CREATE INDEX IF NOT EXISTS idx_clobtr_time ON clob_trades(ingested_at);

-- bot_runs: each row is a single launch of the bot (start → stop).
-- This is what powers the user-facing "session P&L" model — every
-- restart starts a fresh run, and `start_balance` is what we benchmark
-- against. Per-run aggregates (P&L, trades opened/won/lost) get
-- updated periodically and finalised on shutdown.
CREATE TABLE IF NOT EXISTS bot_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network TEXT NOT NULL DEFAULT 'mainnet',
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at TEXT,
    start_cash_usd REAL NOT NULL DEFAULT 0,
    start_portfolio_usd REAL NOT NULL DEFAULT 0,
    start_total_usd REAL NOT NULL DEFAULT 0,
    end_cash_usd REAL,
    end_portfolio_usd REAL,
    end_total_usd REAL,
    pnl_usd REAL DEFAULT 0,
    trades_opened INTEGER DEFAULT 0,
    trades_won INTEGER DEFAULT 0,
    trades_lost INTEGER DEFAULT 0,
    -- Lifetime counters captured at run start. The run's per-session
    -- trade/W/L counts are computed as `current_lifetime - start_lifetime`
    -- on every heartbeat. Without this baseline the heartbeat just
    -- stored lifetime totals into every run, which is why every row in
    -- the History → Run history table looked the same.
    start_trades_opened INTEGER DEFAULT 0,
    start_trades_won INTEGER DEFAULT 0,
    start_trades_lost INTEGER DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_env ON bot_runs(network, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_open ON bot_runs(ended_at, network);

-- Small durable key/value store for engine state that must survive a backend
-- restart but isn't user config (e.g. the crypto15m overall take-profit
-- baseline — the realized P&L snapshot taken when the target was enabled).
CREATE TABLE IF NOT EXISTS app_kv (
    k TEXT PRIMARY KEY,
    v TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- user_scripts: user-authored strategy scripts (the Scripts tab). Code is
-- stored verbatim and runs as full Python (see script_sandbox); `state_json`
-- is the script's persistent `state` dict snapshotted by the engine so
-- restarts don't fully reset cross-tick memory; `assets` is the script's own
-- coin scope (JSON list, NULL = all). A table (not app_kv/settings) so
-- per-script live P&L joins cleanly against crypto15m_positions.script_id.
-- `trusted` is VESTIGIAL: it used to gate the language sandbox, which no
-- longer exists. Kept so an older DB still opens; nothing reads it.
CREATE TABLE IF NOT EXISTS user_scripts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    code TEXT NOT NULL,
    enabled INTEGER DEFAULT 0,
    trusted INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    state_json TEXT DEFAULT '{}',
    last_error TEXT DEFAULT NULL,
    last_error_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- script_shadow_orders: what a script in SHADOW (dry-run) mode WOULD have
-- traded. Deliberately its OWN table rather than a dry_run flag on the live
-- position tables: fake rows there would be seen by reconcile, the position
-- caps, and realized P&L, and crypto15m's manage pass
-- retires any dry_run row as a legacy "paper_removed" leftover. Settled
-- passively from the recorded window/signal outcome, so a shadow script
-- builds a real track record without ever touching the exchange.
CREATE TABLE IF NOT EXISTS script_shadow_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'crypto',   -- 'crypto' (window) | 'signal'
    signal_source TEXT DEFAULT '',           -- 'whale' | 'momentum' | 'market' when source='signal'
    signal_id INTEGER DEFAULT NULL,
    asset TEXT DEFAULT '',
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                      -- up|down (crypto), yes|no (signal)
    contracts INTEGER NOT NULL,              -- 0 = refused by a rail
    entry_cents INTEGER NOT NULL,
    order_type TEXT DEFAULT 'FAK',
    reason TEXT DEFAULT '',
    refused INTEGER DEFAULT 0,
    note TEXT DEFAULT '',                    -- refusal reason / engine note
    tp_pct REAL DEFAULT NULL,
    sl_cents INTEGER DEFAULT NULL,
    close_time TEXT DEFAULT '',
    network TEXT DEFAULT 'mainnet',
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    pnl_usd REAL DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_script ON script_shadow_orders(script_id, network, resolved);
CREATE INDEX IF NOT EXISTS idx_shadow_ticker ON script_shadow_orders(script_id, ticker);
CREATE INDEX IF NOT EXISTS idx_shadow_open ON script_shadow_orders(resolved, source);

CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(created_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts(ticker, direction, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_whale_trade_id ON whale_trades(trade_id);
CREATE INDEX IF NOT EXISTS idx_whale_cat ON whale_trades(category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_whale_convergence ON whale_trades(ticker, taker_side, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots ON market_snapshots(ticker, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_markets_vol ON markets(volume DESC);
CREATE INDEX IF NOT EXISTS idx_bp_status ON bot_positions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bp_ticker ON bot_positions(ticker, direction, status);
CREATE INDEX IF NOT EXISTS idx_bp_resolved ON bot_positions(resolved, status);
CREATE INDEX IF NOT EXISTS idx_bp_created ON bot_positions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_oe_pos ON order_events(position_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pnl_at ON pnl_snapshots(at DESC);
CREATE INDEX IF NOT EXISTS idx_pnl_env_at ON pnl_snapshots(network, at);
CREATE INDEX IF NOT EXISTS idx_c15_open ON crypto15m_positions(resolved, status);
CREATE INDEX IF NOT EXISTS idx_c15_asset ON crypto15m_positions(asset, network, resolved);
CREATE INDEX IF NOT EXISTS idx_c15_env_status ON crypto15m_positions(network, status);
CREATE INDEX IF NOT EXISTS idx_c15_env_exit ON crypto15m_positions(network, exit_reason);
"""


def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _quarantine_db() -> None:
    import time as _time
    p = db_path()
    suffix = _time.strftime("%Y%m%d-%H%M%S")
    for ext in ("", "-wal", "-shm"):
        src = Path(str(p) + ext)
        if not src.exists():
            continue
        try:
            src.replace(Path(str(p) + f".corrupt-{suffix}" + ext))
            logger.warning(f"quarantined corrupt DB file: {src.name}")
        except Exception:
            try:
                src.unlink()
                logger.warning(f"deleted corrupt DB file (rename failed): {src.name}")
            except Exception as e2:
                logger.error(f"could not quarantine/delete {src.name}: {e2}")


def init_db() -> None:
    try:
        _init_db_schema()
        return
    except sqlite3.DatabaseError as e:
        msg = str(e).lower()
        corrupt = (
            "malformed" in msg
            or "not a database" in msg
            or "file is encrypted" in msg
            or "disk image" in msg
        )
        if not corrupt:
            raise
        logger.error(f"database appears corrupt ({e}) — quarantining and recreating")
    _quarantine_db()
    global _restore_checked
    _restore_checked = False
    _init_db_schema()


def _init_db_schema() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for migration in [
            "ALTER TABLE bot_positions ADD COLUMN closed_early INTEGER DEFAULT 0",
            "ALTER TABLE alerts ADD COLUMN yes_sub_title TEXT DEFAULT ''",
            "ALTER TABLE alerts ADD COLUMN score_version TEXT DEFAULT ''",
            "ALTER TABLE alerts ADD COLUMN window_trades INTEGER DEFAULT NULL",
            "ALTER TABLE alerts ADD COLUMN window_dollars REAL DEFAULT NULL",
            "ALTER TABLE alerts ADD COLUMN observed_at REAL DEFAULT NULL",
            "ALTER TABLE bot_runs ADD COLUMN start_trades_opened INTEGER DEFAULT 0",
            "ALTER TABLE bot_runs ADD COLUMN start_trades_won INTEGER DEFAULT 0",
            "ALTER TABLE bot_runs ADD COLUMN start_trades_lost INTEGER DEFAULT 0",
            "ALTER TABLE markets ADD COLUMN slug TEXT DEFAULT ''",
            "ALTER TABLE crypto15m_signals ADD COLUMN book_imbalance REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN book_imbalance REAL",
            "ALTER TABLE bot_positions ADD COLUMN mark_price_cents REAL DEFAULT NULL",
            "ALTER TABLE bot_positions ADD COLUMN exit_reason TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd_signal REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd_hist REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd_cross INTEGER",
            "ALTER TABLE crypto15m_signals ADD COLUMN rsi REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd_signal REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd_hist REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd_cross INTEGER",
            "ALTER TABLE crypto15m_ticks ADD COLUMN rsi REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ws_bid REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ws_ask REAL",
            "ALTER TABLE crypto15m_positions ADD COLUMN avg_entry_cents REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_client_order_id TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_order_id TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_limit_cents INTEGER DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_filled_contracts INTEGER DEFAULT 0",
            "ALTER TABLE crypto15m_positions ADD COLUMN proceeds_usd REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_reason TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN entry_delta_usd REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN outcome_correct INTEGER DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN settlement_usd REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN pnl_usd REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN dry_run INTEGER DEFAULT 0",
            "ALTER TABLE crypto15m_positions ADD COLUMN error TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN strategy TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN fees_usd REAL DEFAULT 0",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_fees_usd REAL DEFAULT 0",
            "ALTER TABLE crypto15m_ticks ADD COLUMN strike REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN delta_signed_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN sigma1m REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN model_prob REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN edge_net_cents REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN no_ask REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN spot_source TEXT",
            "ALTER TABLE crypto15m_signals ADD COLUMN strike REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN model_prob REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN edge_net_cents REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN up_ask REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN vwap1h REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ema12 REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN sma20 REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN sma50 REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN price_vs_vwap_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ema12_vs_sma20_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ema1_vs_sma5_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN velocity1m_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN change5m_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN change15m_pct REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN interval TEXT DEFAULT '15m'",
            "ALTER TABLE crypto15m_ticks ADD COLUMN interval TEXT DEFAULT '15m'",
            "ALTER TABLE crypto15m_positions ADD COLUMN script_id TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN tp_pct REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN sl_cents INTEGER DEFAULT NULL",
            "ALTER TABLE bot_positions ADD COLUMN script_id TEXT DEFAULT NULL",
            "ALTER TABLE user_scripts ADD COLUMN dry_run INTEGER DEFAULT 1",
            "ALTER TABLE user_scripts ADD COLUMN assets TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(migration)
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("UPDATE crypto15m_signals SET interval='15m' WHERE interval IS NULL")
            conn.execute("UPDATE crypto15m_ticks SET interval='15m' WHERE interval IS NULL")
        except sqlite3.OperationalError:
            pass


def _protect_order_journal_on_reset():
    import order_journal
    order_journal.init()
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM us_order_intents WHERE state NOT IN ('filled','canceled','rejected') LIMIT 1").fetchone():
            raise ValueError('Cannot clear history while exchange orders require reconciliation')
        if conn.execute("SELECT 1 FROM bot_positions p JOIN us_order_intents i ON p.client_order_id=i.local_id WHERE p.resolved=0 AND p.status NOT IN ('error','canceled') LIMIT 1").fetchone():
            raise ValueError('Cannot clear history while journaled positions remain open')
        # Keep the audit evidence, but detach closed positions before IDs reset.
        conn.execute('DELETE FROM us_exit_orders')
        conn.execute('DELETE FROM us_exit_basis')


def factory_reset(*, wipe_markets: bool = False) -> dict:
    _protect_order_journal_on_reset()
    backup_research()
    try:
        with get_db() as conn:
            bank_realized_pnl_before_wipe(conn)
    except sqlite3.OperationalError:
        pass
    targets = [
        "bot_positions",
        "crypto15m_positions",
        "bot_runs",
        "pnl_snapshots",
        "daily_stats",
        "order_events",
        "alerts",
        "whale_trades",
        "app_kv",
    ]
    if wipe_markets:
        targets.extend(["markets", "events", "trades", "market_snapshots"])

    summary: dict[str, int] = {}
    errors: dict[str, str] = {}

    for t in targets:
        try:
            with get_db() as conn:
                cur = conn.execute(f"SELECT COUNT(*) FROM {t}")
                count = int(cur.fetchone()[0])
                if t == "app_kv":
                    conn.execute(
                        "DELETE FROM app_kv WHERE k NOT LIKE ? AND k NOT LIKE ?",
                        (f"{_LIFETIME_PNL_PREFIX}%", f"{_DAILY_PNL_PREFIX}%"),
                    )
                else:
                    conn.execute(f"DELETE FROM {t}")
                summary[t] = count
        except sqlite3.OperationalError as e:
            errors[t] = str(e)
            summary[t] = -1

    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('bot_positions','bot_runs','pnl_snapshots',"
                "'daily_stats','order_events','alerts','whale_trades',"
                "'markets','events','trades','market_snapshots')",
            )
    except sqlite3.OperationalError:
        pass

    try:
        conn = sqlite3.connect(str(db_path()), timeout=30)
        conn.isolation_level = None
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
        conn.close()
    except sqlite3.OperationalError:
        pass

    if errors:
        summary["_errors"] = errors  # type: ignore[assignment]
    return summary


def clear_trade_history() -> dict:
    _protect_order_journal_on_reset()
    try:
        with get_db() as conn:
            bank_realized_pnl_before_wipe(conn)
    except sqlite3.OperationalError:
        pass
    targets = [
        "bot_positions",
        "crypto15m_positions",
        "bot_runs",
        "pnl_snapshots",
        "daily_stats",
        "order_events",
    ]

    summary: dict[str, int] = {}
    errors: dict[str, str] = {}

    for t in targets:
        try:
            with get_db() as conn:
                cur = conn.execute(f"SELECT COUNT(*) FROM {t}")
                count = int(cur.fetchone()[0])
                conn.execute(f"DELETE FROM {t}")
                summary[t] = count
        except sqlite3.OperationalError as e:
            errors[t] = str(e)
            summary[t] = -1

    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('bot_positions','crypto15m_positions','bot_runs',"
                "'pnl_snapshots','daily_stats','order_events')",
            )
    except sqlite3.OperationalError:
        pass

    try:
        conn = sqlite3.connect(str(db_path()), timeout=30)
        conn.isolation_level = None
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        conn.close()
    except sqlite3.OperationalError:
        pass

    if errors:
        summary["_errors"] = errors  # type: ignore[assignment]
    return summary


def upsert_market(conn, market: dict) -> None:
    conn.execute(
        """
        INSERT INTO markets (ticker, event_ticker, series_ticker, slug, title, yes_sub_title,
            category, status, close_time, volume, volume_24h, open_interest,
            yes_bid, yes_ask, last_price, prev_yes_bid, prev_price,
            result, settlement_value, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            event_ticker=excluded.event_ticker,
            series_ticker=excluded.series_ticker,
            slug=COALESCE(NULLIF(excluded.slug,''), slug),
            title=COALESCE(excluded.title, title),
            yes_sub_title=COALESCE(excluded.yes_sub_title, yes_sub_title),
            category=COALESCE(NULLIF(excluded.category,''), category),
            status=excluded.status,
            close_time=excluded.close_time,
            prev_yes_bid=markets.yes_bid,
            prev_price=markets.last_price,
            volume=excluded.volume,
            volume_24h=excluded.volume_24h,
            open_interest=excluded.open_interest,
            yes_bid=excluded.yes_bid,
            yes_ask=excluded.yes_ask,
            last_price=excluded.last_price,
            result=excluded.result,
            settlement_value=excluded.settlement_value,
            last_updated=excluded.last_updated
        """,
        (
            market.get("ticker", ""),
            market.get("event_ticker", ""),
            market.get("series_ticker", ""),
            market.get("slug", ""),
            market.get("title", ""),
            market.get("yes_sub_title", ""),
            market.get("category", ""),
            market.get("status", "open"),
            market.get("close_time", ""),
            _to_float(market.get("volume", 0)),
            _to_float(market.get("volume_24h", 0)),
            _to_float(market.get("open_interest", 0)),
            _to_float(market.get("yes_bid", 0)),
            _to_float(market.get("yes_ask", 0)),
            _to_float(market.get("last_price", 0)),
            0,
            0,
            market.get("result", ""),
            _to_float(market.get("settlement_value")) if market.get("settlement_value") is not None else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def get_market(conn, ticker: str) -> dict | None:
    row = conn.execute("SELECT * FROM markets WHERE ticker = ?", (ticker,)).fetchone()
    return dict(row) if row else None


def get_active_markets(conn, min_volume: float = 0, limit: int = 500) -> list:
    rows = conn.execute(
        "SELECT * FROM markets WHERE status IN ('active','open') AND volume >= ? "
        "ORDER BY volume DESC LIMIT ?",
        (min_volume, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_event(conn, event: dict) -> None:
    conn.execute(
        """
        INSERT INTO events (event_ticker, series_ticker, title, sub_title, category, status, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_ticker) DO UPDATE SET
            series_ticker=excluded.series_ticker,
            title=COALESCE(excluded.title, title),
            sub_title=COALESCE(excluded.sub_title, sub_title),
            category=COALESCE(NULLIF(excluded.category,''), category),
            status=excluded.status,
            last_updated=excluded.last_updated
        """,
        (
            event.get("event_ticker", ""),
            event.get("series_ticker", ""),
            event.get("title", ""),
            event.get("sub_title", ""),
            event.get("category", ""),
            event.get("status", "open"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def trade_exists(conn, trade_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
        is not None
    )


def insert_trade(conn, trade: dict) -> bool:
    try:
        conn.execute(
            """
            INSERT INTO trades (trade_id, ticker, event_ticker, count_fp, yes_price,
                no_price, taker_side, dollar_value, category, created_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("trade_id", ""),
                trade.get("ticker", ""),
                trade.get("event_ticker", ""),
                _to_float(trade.get("count_fp", 0)),
                _to_float(trade.get("yes_price", 0)),
                _to_float(trade.get("no_price", 0)),
                trade.get("taker_side", ""),
                _to_float(trade.get("dollar_value", 0)),
                trade.get("category", ""),
                trade.get("created_time", ""),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def insert_alert(conn, alert: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO alerts (ticker, event_ticker, title, yes_sub_title, category, signal_type,
            direction, volume_24h, price, price_change, confidence,
            score_version, window_trades, window_dollars, observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert.get("ticker", ""),
            alert.get("event_ticker", ""),
            alert.get("title", ""),
            alert.get("yes_sub_title", ""),
            alert.get("category", ""),
            alert.get("signal_type", ""),
            alert.get("direction", ""),
            alert.get("volume_24h", 0),
            alert.get("price", 0),
            alert.get("price_change", 0),
            alert.get("confidence", 0),
            alert.get("score_version", ""),
            alert.get("window_trades"),
            alert.get("window_dollars"),
            alert.get("observed_at"),
        ),
    )
    return cur.lastrowid


def mark_alert_discord_sent(conn, alert_id: int) -> None:
    conn.execute("UPDATE alerts SET discord_sent = 1 WHERE id = ?", (alert_id,))


def recent_alert_exists(
    conn, ticker: str, signal_type: str, direction: str, cooldown_minutes: int = 30
) -> bool:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
    ).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """
        SELECT 1 FROM alerts
        WHERE ticker = ? AND signal_type = ? AND direction = ? AND created_at >= ?
        """,
        (ticker, signal_type, direction, cutoff),
    ).fetchone()
    return row is not None


def fetch_tradeable_momentum_signals(
    conn,
    *,
    min_confidence: float,
    max_age_sec: int,
    allowed_types: list[str],
    seen_ids: set[int],
    limit: int = 50,
) -> list[dict]:
    if not allowed_types:
        return []
    placeholders = ",".join("?" for _ in allowed_types)
    rows = conn.execute(
        f"""SELECT a.* FROM alerts a
            WHERE a.confidence >= ?
              AND a.resolved = 0
              AND (julianday('now') - julianday(a.created_at)) * 86400 <= ?
              AND a.signal_type IN ({placeholders})
            ORDER BY a.created_at DESC
            LIMIT ?""",
        [min_confidence, max_age_sec, *allowed_types, limit * 2],
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if int(d["id"]) in seen_ids:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def whale_trade_exists(conn, trade_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM whale_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        is not None
    )


def insert_whale_trade(conn, trade: dict) -> int:
    tid = str(trade.get("trade_id") or "")
    if tid and conn.execute(
        "SELECT 1 FROM whale_trades WHERE trade_id=? LIMIT 1", (tid,)
    ).fetchone():
        return 0
    try:
        cur = conn.execute(
            """
            INSERT INTO whale_trades
                (trade_id, ticker, event_ticker, title, yes_sub_title, category, taker_side,
                 count_fp, price, dollar_value, market_volume, open_interest, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("trade_id", ""),
                trade.get("ticker", ""),
                trade.get("event_ticker", ""),
                trade.get("title", ""),
                trade.get("yes_sub_title", ""),
                trade.get("category", ""),
                trade.get("taker_side", ""),
                _to_float(trade.get("count_fp", 0)),
                _to_float(trade.get("price", 0)),
                _to_float(trade.get("dollar_value", 0)),
                _to_float(trade.get("market_volume", 0)),
                _to_float(trade.get("open_interest", 0)),
                trade.get("confidence", 0),
            ),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return 0


def mark_whale_discord_sent(conn, whale_id: int) -> None:
    conn.execute("UPDATE whale_trades SET discord_sent = 1 WHERE id = ?", (whale_id,))


def fetch_tradeable_whale_signals(
    conn,
    *,
    min_confidence: float,
    max_age_sec: int,
    seen_ids: set[int],
    limit: int = 50,
) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM whale_trades
           WHERE confidence >= ?
             AND resolved = 0
             AND (julianday('now') - julianday(created_at)) * 86400 <= ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (min_confidence, max_age_sec, limit * 2),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if int(d["id"]) in seen_ids:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def get_recent_whales_for_convergence(conn, hours: int = 2) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """
        SELECT ticker, taker_side, dollar_value, confidence, price,
               count_fp, title, category, created_at
        FROM whale_trades WHERE created_at >= ?
        ORDER BY created_at DESC
        """,
        (cutoff,),
    ).fetchall()
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (r[0], r[1])
        groups.setdefault(key, []).append(
            {
                "dollar_value": r[2],
                "confidence": r[3],
                "price": r[4],
                "count_fp": r[5],
                "title": r[6],
                "category": r[7],
                "created_at": r[8],
            }
        )
    return groups


def save_snapshot(conn, ticker: str, market: dict) -> None:
    conn.execute(
        """INSERT INTO market_snapshots (ticker, volume, volume_24h, open_interest, yes_bid, last_price)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            _to_float(market.get("volume", 0)),
            _to_float(market.get("volume_24h", 0)),
            _to_float(market.get("open_interest", 0)),
            _to_float(market.get("yes_bid", 0)),
            _to_float(market.get("last_price", 0)),
        ),
    )


def save_snapshots_bulk(conn, markets: list[dict]) -> None:
    if not markets:
        return
    conn.executemany(
        """INSERT INTO market_snapshots (ticker, volume, volume_24h, open_interest, yes_bid, last_price)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                m.get("ticker", ""),
                _to_float(m.get("volume", 0)),
                _to_float(m.get("volume_24h", 0)),
                _to_float(m.get("open_interest", 0)),
                _to_float(m.get("yes_bid", 0)),
                _to_float(m.get("last_price", 0)),
            )
            for m in markets
            if m.get("ticker")
        ],
    )


def get_previous_snapshot(conn, ticker: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM market_snapshots WHERE ticker = ?
           ORDER BY snapshot_at DESC LIMIT 1 OFFSET 1""",
        (ticker,),
    ).fetchone()
    return dict(row) if row else None


def get_unresolved_alerts(conn, days: int = 30) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """SELECT id, ticker, direction, price, created_at
           FROM alerts WHERE resolved = 0 AND created_at >= ?""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_unresolved_whale_trades(conn, days: int = 30) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """SELECT id, ticker, taker_side, price, dollar_value, created_at
           FROM whale_trades WHERE resolved = 0 AND created_at >= ?""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_alert_resolved(
    conn, alert_id: int, correct: bool, resolved_price: float, pnl_est: float
) -> None:
    conn.execute(
        """UPDATE alerts SET resolved = 1, outcome_correct = ?, resolved_price = ?,
              pnl_estimate = ?, resolved_at = ? WHERE id = ?""",
        (
            1 if correct else 0,
            resolved_price,
            pnl_est,
            datetime.now(timezone.utc).isoformat(),
            alert_id,
        ),
    )


def mark_whale_resolved(
    conn, trade_id: int, correct: bool, resolved_price: float, pnl_est: float
) -> None:
    conn.execute(
        """UPDATE whale_trades SET resolved = 1, outcome_correct = ?, resolved_price = ?,
              pnl_estimate = ?, resolved_at = ? WHERE id = ?""",
        (
            1 if correct else 0,
            resolved_price,
            pnl_est,
            datetime.now(timezone.utc).isoformat(),
            trade_id,
        ),
    )


def insert_bot_position(conn, row: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO bot_positions (
            signal_source, signal_id, ticker, event_ticker, title, category,
            direction, action, target_contracts, limit_price_cents,
            filled_contracts, avg_fill_price_cents, cost_usd,
            client_order_id, order_id, status,
            confidence, edge_pts, signal_price, error,
            balance_before_usd, network, script_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            row["signal_source"],
            row["signal_id"],
            row["ticker"],
            row.get("event_ticker", ""),
            row.get("title", ""),
            row.get("category", ""),
            row["direction"],
            row.get("action", "buy"),
            int(row["target_contracts"]),
            int(row["limit_price_cents"]),
            int(row.get("filled_contracts", 0)),
            row.get("avg_fill_price_cents"),
            float(row.get("cost_usd", 0.0)),
            row["client_order_id"],
            row.get("order_id"),
            row["status"],
            float(row.get("confidence", 0.0)),
            float(row.get("edge_pts", 0.0)),
            float(row.get("signal_price", 0.0)),
            row.get("error"),
            row.get("balance_before_usd"),
            row.get("network", "mainnet"),
            row.get("script_id"),
        ),
    )
    return cur.lastrowid


def update_bot_position(conn, bot_id: int, **fields) -> None:
    if not fields:
        return
    stamp_last = fields.pop("_stamp_last_updated", True)
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(v)
    if stamp_last:
        cols.append("last_updated=datetime('now')")
    vals.append(bot_id)
    conn.execute(
        f"UPDATE bot_positions SET {', '.join(cols)} WHERE id=?", vals
    )


def log_event(
    conn,
    position_id: int,
    kind: str,
    *,
    order_status: str | None = None,
    filled_contracts: int | None = None,
    fill_cost_cents: int | None = None,
    note: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO order_events
              (position_id, kind, order_status, filled_contracts,
               fill_cost_cents, note)
           VALUES (?,?,?,?,?,?)""",
        (position_id, kind, order_status, filled_contracts, fill_cost_cents, note),
    )


def count_open_bot_positions(conn, env: str | None = None) -> int:
    sql = (
        "SELECT COUNT(*) FROM bot_positions "
        "WHERE status IN ('submitted','partial','filled','unknown') AND resolved=0"
    )
    args: tuple = ()
    if env:
        sql += " AND network = ?"
        args = (env,)
    return conn.execute(sql, args).fetchone()[0]


def count_open_paper_positions(conn, env: str) -> int:
    return int(conn.execute(
        """SELECT COUNT(*) FROM bot_positions
           WHERE status='dry_run' AND signal_id<0 AND resolved=0 AND network=?""",
        (env,),
    ).fetchone()[0])


def count_new_paper_positions_today(conn, env: str, offset_min: int = 0) -> int:
    return int(conn.execute(
        """SELECT COUNT(*) FROM bot_positions
           WHERE status='dry_run' AND signal_id<0 AND network=?
             AND created_at >= ?""",
        (env, day_start_utc(offset_min)),
    ).fetchone()[0])


def count_paper_positions_in_event(conn, event_ticker: str, env: str) -> int:
    if not event_ticker:
        return 0
    return int(conn.execute(
        """SELECT COUNT(*) FROM bot_positions
           WHERE event_ticker=? AND status='dry_run' AND signal_id<0
             AND resolved=0 AND network=?""",
        (event_ticker, env),
    ).fetchone()[0])


def exists_paper_position_in_market(conn, ticker: str, direction: str, env: str) -> bool:
    return conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE ticker=? AND direction=? AND status='dry_run' AND signal_id<0
             AND resolved=0 AND network=? LIMIT 1""",
        (ticker, direction, env),
    ).fetchone() is not None


def current_paper_exposure_usd(conn, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(cost_usd),0) FROM bot_positions
           WHERE status='dry_run' AND signal_id<0 AND resolved=0 AND network=?""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def paper_account_stats(conn, env: str, bankroll_usd: float) -> dict:
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_n,
             SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved_n,
             SUM(CASE WHEN resolved=1 AND outcome_correct=1 THEN 1 ELSE 0 END) AS wins,
             SUM(CASE WHEN resolved=1 AND outcome_correct=0 THEN 1 ELSE 0 END) AS losses,
             COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd ELSE 0 END),0) AS pnl,
             COALESCE(SUM(CASE WHEN resolved=0 THEN cost_usd ELSE 0 END),0) AS exposure
           FROM bot_positions WHERE status='dry_run' AND signal_id<0 AND network=?""",
        (env,),
    ).fetchone()
    pnl = float(row["pnl"] or 0.0)
    exposure = float(row["exposure"] or 0.0)
    return {
        "bankroll_usd": float(bankroll_usd),
        "available_usd": max(0.0, float(bankroll_usd) + pnl - exposure),
        "open": int(row["open_n"] or 0),
        "resolved": int(row["resolved_n"] or 0),
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "pnl_usd": pnl,
        "exposure_usd": exposure,
    }


def count_new_positions_today(
    conn, env: str | None = None, offset_min: int = 0
) -> int:
    sql = (
        "SELECT COUNT(*) FROM bot_positions "
        "WHERE created_at >= ? "
        "AND status IN ('submitted','partial','filled','unknown') "
        "AND COALESCE(signal_source,'') != 'external'"
    )
    args: tuple = (day_start_utc(offset_min),)
    if env:
        sql += " AND network = ?"
        args = (day_start_utc(offset_min), env)
    return conn.execute(sql, args).fetchone()[0]


def recent_resolved_position_exists(
    conn,
    ticker: str,
    direction: str,
    env: str,
    within_hours: Optional[int] = None,
) -> bool:
    sql = (
        "SELECT 1 FROM bot_positions "
        "WHERE ticker = ? AND direction = ? AND network = ? "
        "AND resolved = 1 AND resolved_at IS NOT NULL"
    )
    args: tuple = (ticker, direction, env)
    if within_hours is not None:
        sql += " AND resolved_at >= datetime('now', ?)"
        args += (f"-{int(within_hours)} hours",)
    row = conn.execute(sql + " LIMIT 1", args).fetchone()
    return row is not None


def exists_position_in_event(conn, event_ticker: str, env: str) -> bool:
    if not event_ticker:
        return False
    row = conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE event_ticker=? AND resolved=0 AND network=?
             AND status IN ('submitted','partial','filled','unknown')
           LIMIT 1""",
        (event_ticker, env),
    ).fetchone()
    return row is not None


def count_positions_in_event(conn, event_ticker: str, env: str) -> int:
    if not event_ticker:
        return 0
    return int(conn.execute(
        """SELECT COUNT(*) FROM bot_positions
           WHERE event_ticker=? AND resolved=0 AND network=?
             AND status IN ('submitted','partial','filled','unknown')""",
        (event_ticker, env),
    ).fetchone()[0])


def exists_position_in_market(
    conn, ticker: str, direction: str, env: str
) -> bool:
    row = conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE ticker=? AND direction=? AND resolved=0 AND network=?
             AND status IN ('submitted','partial','filled','unknown')
           LIMIT 1""",
        (ticker, direction, env),
    ).fetchone()
    return row is not None


def current_total_exposure_usd(conn, env: str) -> float:
    # Journaled orders include a conservative fee reserve. Older unjournaled
    # positions retain their existing notional fallback until reconciled.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='us_order_intents'").fetchone():
        return float(conn.execute("""SELECT COALESCE(SUM(
            CASE WHEN p.cost_usd>0 THEN p.cost_usd
                WHEN p.status='filled' THEN p.target_contracts*p.limit_price_cents/100.0
                ELSE p.filled_contracts*p.limit_price_cents/100.0 END
            + CASE WHEN p.status='filled' THEN 0 ELSE COALESCE(i.reserved_usd,
                MAX(0,p.target_contracts-p.filled_contracts)*p.limit_price_cents/100.0) END
            ),0) FROM bot_positions p LEFT JOIN us_order_intents i ON i.local_id=p.client_order_id
            WHERE p.resolved=0 AND p.status IN ('submitted','partial','filled','unknown') AND p.network=?""", (env,)).fetchone()[0])
    row = conn.execute(
        """SELECT COALESCE(SUM(
               CASE WHEN status='filled' THEN
                 CASE WHEN cost_usd>0 THEN cost_usd ELSE target_contracts*limit_price_cents/100.0 END
               ELSE
                 CASE WHEN cost_usd>0 THEN cost_usd ELSE filled_contracts*limit_price_cents/100.0 END
                 + MAX(0,target_contracts-filled_contracts)*limit_price_cents/100.0
               END
           ), 0) FROM bot_positions
           WHERE resolved=0 AND status IN ('submitted','partial','filled','unknown') AND network=?""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def current_filled_exposure_usd(conn, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(cost_usd), 0) FROM bot_positions
           WHERE resolved=0 AND status IN ('submitted','partial','filled','unknown')
             AND cost_usd > 0 AND network=?""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def get_pending_bot_positions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM bot_positions
           WHERE resolved=0
             AND signal_source != 'external'
             AND (
               status IN ('submitted','partial','unknown')
               OR (status='filled' AND (cost_usd IS NULL OR cost_usd=0))
               OR (status IN ('canceled','expired','gone','error')
                   AND (cost_usd IS NULL OR cost_usd=0)
                   AND (julianday('now')-julianday(created_at))*86400 < 86400)
             )
           ORDER BY created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_open_bot_positions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM bot_positions
           WHERE status IN ('submitted','partial','filled','unknown') AND resolved=0
           ORDER BY created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_unresolved_bot_positions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM bot_positions
           WHERE resolved=0 AND (
             status IN ('filled','partial','expired','canceled','gone')
             OR (status='dry_run' AND signal_id<0)
           )
           ORDER BY created_at ASC"""
    ).fetchall()
    return [dict(r) for r in rows]


def already_traded_signal_ids(conn, source: str, env: str) -> set[int]:
    rows = conn.execute(
        """SELECT signal_id FROM bot_positions
           WHERE signal_source=? AND network=?
             AND created_at >= datetime('now','-45 days')""",
        (source, env),
    ).fetchall()
    return {int(r["signal_id"]) for r in rows}


def already_paper_traded_signal_ids(conn, source: str, env: str) -> set[int]:
    rows = conn.execute(
        """SELECT signal_id FROM bot_positions
           WHERE signal_source=? AND network=? AND status='dry_run'
             AND signal_id < 0 AND created_at >= datetime('now','-45 days')""",
        (source, env),
    ).fetchall()
    return {abs(int(r["signal_id"])) for r in rows}


def fetch_position_by_id(conn, pos_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM bot_positions WHERE id=?", (pos_id,)
    ).fetchone()
    return dict(row) if row else None


def insert_crypto15m_position(conn, row: dict) -> int:
    cur = conn.execute(
        """INSERT INTO crypto15m_positions (
              asset, series, ticker, side, direction, target_contracts,
              filled_contracts, entry_limit_cents, avg_entry_cents, cost_usd,
              client_order_id, order_id, status, exit_reason, close_time,
              confidence, entry_delta_usd, network, dry_run, error, strategy,
              script_id, tp_pct, sl_cents
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["asset"], row["series"], row["ticker"], row["side"],
            row["direction"], int(row["target_contracts"]),
            int(row.get("filled_contracts", 0)),
            int(row["entry_limit_cents"]),
            row.get("avg_entry_cents"),
            float(row.get("cost_usd", 0.0)),
            row["client_order_id"], row.get("order_id"),
            row["status"], row.get("exit_reason"), row.get("close_time", ""),
            float(row.get("confidence", 0.0)),
            row.get("entry_delta_usd"),
            row.get("network", "mainnet"),
            1 if row.get("dry_run") else 0,
            row.get("error"),
            row.get("strategy"),
            row.get("script_id"),
            row.get("tp_pct"),
            row.get("sl_cents"),
        ),
    )
    return cur.lastrowid


def update_crypto15m_position(conn, pid: int, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(v)
    cols.append("last_updated=datetime('now')")
    vals.append(pid)
    conn.execute(
        f"UPDATE crypto15m_positions SET {', '.join(cols)} WHERE id=?", vals
    )


def fetch_crypto15m_by_id(conn, pid: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM crypto15m_positions WHERE id=?", (pid,)
    ).fetchone()
    return dict(row) if row else None


def get_open_crypto15m(conn, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE resolved=0 AND network=?
           ORDER BY created_at DESC""",
        (env,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_open_crypto15m_by_asset(conn, asset: str, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE resolved=0 AND asset=? AND network=?
           ORDER BY created_at DESC LIMIT 1""",
        (asset, env),
    ).fetchone()
    return dict(row) if row else None


def count_open_crypto15m(conn, env: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM crypto15m_positions WHERE resolved=0 AND network=?",
        (env,),
    ).fetchone()[0]


def list_user_scripts(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM user_scripts ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_user_script(conn, sid: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM user_scripts WHERE id=?", (sid,)
    ).fetchone()
    return dict(row) if row else None


def upsert_user_script(conn, row: dict) -> None:
    conn.execute(
        """INSERT INTO user_scripts (id, name, description, code, enabled,
              trusted, notes, state_json)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, description=excluded.description,
              code=excluded.code, notes=excluded.notes,
              updated_at=datetime('now')""",
        (
            str(row["id"]), str(row.get("name") or "Untitled script"),
            str(row.get("description") or ""), str(row.get("code") or ""),
            1 if row.get("enabled") else 0,
            1 if row.get("trusted") else 0,
            str(row.get("notes") or ""),
            str(row.get("state_json") or "{}"),
        ),
    )


def update_user_script(conn, sid: str, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if k not in ("name", "description", "code", "enabled", "trusted",
                     "notes", "state_json", "last_error", "last_error_at",
                     "dry_run", "assets"):
            continue
        cols.append(f"{k}=?")
        vals.append(v)
    if "last_error" in fields and fields["last_error"]:
        cols.append("last_error_at=datetime('now')")
    cols.append("updated_at=datetime('now')")
    vals.append(sid)
    conn.execute(f"UPDATE user_scripts SET {', '.join(cols)} WHERE id=?", vals)


def delete_user_script(conn, sid: str) -> None:
    conn.execute("DELETE FROM user_scripts WHERE id=?", (sid,))


def script_live_stats(conn, env: str) -> dict[str, dict]:
    agg = """SELECT script_id,
                    COUNT(*) AS n,
                    SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_n,
                    SUM(CASE WHEN resolved=1 AND COALESCE(pnl_usd,0) > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN resolved=1 AND COALESCE(pnl_usd,0) < 0 THEN 1 ELSE 0 END) AS losses,
                    COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd ELSE 0 END), 0) AS pnl
             FROM {table}
             WHERE script_id IS NOT NULL AND network=? AND target_contracts > 0
             GROUP BY script_id"""
    out: dict[str, dict] = {}
    for table in ("crypto15m_positions", "bot_positions"):
        for r in conn.execute(agg.format(table=table), (env,)).fetchall():
            s = out.setdefault(str(r["script_id"]), {
                "n": 0, "open": 0, "wins": 0, "losses": 0, "pnlUsd": 0.0})
            s["n"] += int(r["n"] or 0)
            s["open"] += int(r["open_n"] or 0)
            s["wins"] += int(r["wins"] or 0)
            s["losses"] += int(r["losses"] or 0)
            s["pnlUsd"] = round(s["pnlUsd"] + float(r["pnl"] or 0.0), 2)
    return out


_SHADOW_COLS = (
    "script_id", "source", "signal_source", "signal_id", "asset", "ticker",
    "side", "contracts", "entry_cents", "order_type", "reason", "refused",
    "note", "tp_pct", "sl_cents", "close_time", "network",
)


def insert_script_shadow(conn, row: dict) -> int:
    cols = ", ".join(_SHADOW_COLS)
    marks = ", ".join("?" for _ in _SHADOW_COLS)
    cur = conn.execute(
        f"INSERT INTO script_shadow_orders ({cols}) VALUES ({marks})",
        tuple(row.get(c) for c in _SHADOW_COLS),
    )
    return int(cur.lastrowid)


def shadow_already_attempted(conn, sid: str, ticker: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM script_shadow_orders WHERE script_id=? AND ticker=? LIMIT 1",
        (sid, ticker),
    ).fetchone() is not None


SHADOW_STALE_DAYS = 7


def count_open_script_shadow(conn, sid: str, env: str) -> int:
    return int(conn.execute(
        f"""SELECT COUNT(*) FROM script_shadow_orders
            WHERE script_id=? AND network=? AND resolved=0 AND contracts > 0
              AND created_at >= datetime('now', '-{SHADOW_STALE_DAYS} days')""",
        (sid, env),
    ).fetchone()[0] or 0)


def script_shadow_daily_pnl(conn, sid: str, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(pnl_usd), 0) FROM script_shadow_orders
           WHERE script_id=? AND network=? AND resolved=1
             AND date(COALESCE(resolved_at, created_at)) = date('now')""",
        (sid, env),
    ).fetchone()
    return float(row[0] or 0.0)


def list_script_shadow(conn, sid: str, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM script_shadow_orders WHERE script_id=?
           ORDER BY id DESC LIMIT ?""",
        (sid, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def script_shadow_stats(conn, env: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in conn.execute(
        """SELECT script_id,
                  COUNT(*) AS n,
                  SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_n,
                  SUM(CASE WHEN resolved=1 AND COALESCE(pnl_usd,0) > 0 THEN 1 ELSE 0 END) AS wins,
                  SUM(CASE WHEN resolved=1 AND COALESCE(pnl_usd,0) < 0 THEN 1 ELSE 0 END) AS losses,
                  COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd ELSE 0 END), 0) AS pnl
           FROM script_shadow_orders
           WHERE network=? AND contracts > 0
           GROUP BY script_id""",
        (env,),
    ).fetchall():
        out[str(r["script_id"])] = {
            "n": int(r["n"] or 0), "open": int(r["open_n"] or 0),
            "wins": int(r["wins"] or 0), "losses": int(r["losses"] or 0),
            "pnlUsd": round(float(r["pnl"] or 0.0), 2),
        }
    return out


def resolve_script_shadow(conn, fee_fn, market_results: dict | None = None,
                          stale_days: int = 7) -> int:
    settled = 0
    market_results = {str(k): str(v).lower()
                      for k, v in (market_results or {}).items()}
    open_rows = conn.execute(
        "SELECT * FROM script_shadow_orders WHERE resolved=0 AND contracts > 0"
    ).fetchall()
    for r in open_rows:
        r = dict(r)
        won: int | None = None
        if str(r.get("source")) == "crypto":
            hit = conn.execute(
                """SELECT up_won FROM crypto15m_signals
                   WHERE ticker=? AND resolved=1 AND up_won IS NOT NULL
                   LIMIT 1""",
                (r.get("ticker"),),
            ).fetchone()
            if hit is not None:
                up_won = bool(hit[0])
                won = int(up_won if r.get("side") == "up" else not up_won)
        elif str(r.get("signal_source")) == "market":
            res = market_results.get(str(r.get("ticker") or ""))
            if res not in ("yes", "no"):
                hit = conn.execute(
                    """SELECT result, settlement_value FROM markets
                       WHERE ticker=? AND (result IN ('yes', 'no')
                                           OR settlement_value IS NOT NULL)""",
                    (r.get("ticker"),),
                ).fetchone()
                if hit is not None:
                    res = str(hit[0] or "").lower()
                    if res not in ("yes", "no") and hit[1] is not None:
                        res = "yes" if float(hit[1]) >= 0.5 else "no"
            if res in ("yes", "no"):
                won = int(res == str(r.get("side") or "").lower())
        else:
            table = ("whale_trades" if r.get("signal_source") == "whale"
                     else "alerts")
            hit = conn.execute(
                f"""SELECT outcome_correct FROM {table}
                    WHERE id=? AND resolved=1 AND outcome_correct IS NOT NULL""",
                (r.get("signal_id"),),
            ).fetchone()
            if hit is not None:
                won = int(bool(hit[0]))
        if won is None:
            close_iso = str(r.get("close_time") or "")
            if close_iso and stale_days > 0:
                stale = conn.execute(
                    "SELECT ? < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
                    (close_iso, f"-{int(stale_days)} days"),
                ).fetchone()[0]
                if stale:
                    conn.execute(
                        """UPDATE script_shadow_orders
                           SET resolved=1, outcome_correct=NULL, pnl_usd=NULL,
                               note=?, resolved_at=datetime('now')
                           WHERE id=?""",
                        (f"outcome never became available ({stale_days}d after "
                         "close) — excluded from the record", r["id"]),
                    )
                    settled += 1
            continue
        cost = float(r.get("entry_cents") or 0) / 100.0
        # The taker fee is charged at entry, so the fee schedule is chosen by
        # when the shadow order was placed - not by the market's category,
        # which the US schedule does not vary on.
        try:
            fee = float(fee_fn(cost, r.get("created_at")))
        except Exception:
            fee = 0.0
        per_ct = (1.0 - cost - fee) if won else (-cost - fee)
        conn.execute(
            """UPDATE script_shadow_orders
               SET resolved=1, outcome_correct=?, pnl_usd=?,
                   resolved_at=datetime('now')
               WHERE id=?""",
            (won, round(per_ct * int(r.get("contracts") or 0), 4), r["id"]),
        )
        settled += 1
    return settled


def crypto15m_owned_keys(conn, env: str, recent_lookback_sql: str = "-6 hours") -> set:
    rows = conn.execute(
        """SELECT DISTINCT ticker, direction FROM crypto15m_positions
           WHERE network=? AND (
                 resolved=0
              OR created_at >= datetime('now', ?)
           )""",
        (env, recent_lookback_sql),
    ).fetchall()
    return {(r["ticker"], r["direction"]) for r in rows}


def crypto15m_errored_tickers(conn, env: str) -> set:
    rows = conn.execute(
        """SELECT DISTINCT ticker FROM crypto15m_positions
           WHERE network=? AND status='error' AND ticker IS NOT NULL
             AND created_at >= datetime('now','-6 hours')""",
        (env,),
    ).fetchall()
    return {r["ticker"] for r in rows}


def crypto15m_today_pnl(conn, env: str) -> float:
    return engine_today_pnl(conn, "crypto15m", env)


def crypto15m_today_open_cost(conn, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(
               CASE WHEN cost_usd > 0 THEN cost_usd
                    ELSE target_contracts * entry_limit_cents / 100.0 END
           ), 0) FROM crypto15m_positions
           WHERE network=? AND resolved=0
             AND status IN ('submitted','partial','filled','unknown')
             AND date(created_at)=date('now')""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def kv_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT v FROM app_kv WHERE k=?", (key,)).fetchone()
    return None if row is None else row[0]


def kv_set(conn, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO app_kv (k, v, updated_at)
           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(k) DO UPDATE SET
               v=excluded.v, updated_at=excluded.updated_at""",
        (key, str(value)),
    )


def kv_delete(conn, key: str) -> None:
    conn.execute("DELETE FROM app_kv WHERE k=?", (key,))


_LIFETIME_PNL_PREFIX = "lifetime_pnl_wiped:"
_DAILY_PNL_PREFIX = "daily_pnl_wiped:"


def _engine_pnl_source(engine: str) -> tuple[str, str]:
    if engine == "crypto15m":
        return "crypto15m_positions", ""
    if engine == "copy":
        return "bot_positions", "AND signal_source='copy'"
    if engine == "main":
        return "bot_positions", "AND signal_source IN ('whale','momentum')"
    raise ValueError(f"unknown engine {engine!r}")


def _engine_resolved_pnl_sum(
    conn, engine: str, env: str, *, today_only: bool = False
) -> float:
    table, extra = _engine_pnl_source(engine)
    sql = (
        f"SELECT COALESCE(SUM(pnl_usd),0) FROM {table} "
        f"WHERE network=? AND resolved=1 AND pnl_usd IS NOT NULL {extra}"
    )
    if today_only:
        sql += " AND date(resolved_at)=date('now')"
    return float(conn.execute(sql, (env,)).fetchone()[0] or 0.0)


def _daily_wiped_pnl(conn, engine: str, env: str) -> float:
    import json
    raw = kv_get(conn, f"{_DAILY_PNL_PREFIX}{engine}:{env}")
    if not raw:
        return 0.0
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return 0.0
    if d.get("date") != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        return 0.0
    return _to_float(d.get("pnl"))


def lifetime_realized_pnl(conn, engine: str, env: str) -> float:
    wiped = _to_float(kv_get(conn, f"{_LIFETIME_PNL_PREFIX}{engine}:{env}"))
    return wiped + _engine_resolved_pnl_sum(conn, engine, env)


def engine_today_pnl(conn, engine: str, env: str) -> float:
    return _daily_wiped_pnl(conn, engine, env) + _engine_resolved_pnl_sum(
        conn, engine, env, today_only=True
    )


def _known_envs(conn) -> set:
    envs = {"mainnet"}
    for tbl in ("crypto15m_positions", "bot_positions"):
        try:
            for r in conn.execute(f"SELECT DISTINCT network FROM {tbl}"):
                if r[0]:
                    envs.add(r[0])
        except sqlite3.OperationalError:
            pass
    return envs


def bank_realized_pnl_before_wipe(conn) -> None:
    import json
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for engine in ("crypto15m", "copy", "main"):
        for env in _known_envs(conn):
            all_sum = _engine_resolved_pnl_sum(conn, engine, env)
            if abs(all_sum) > 1e-9:
                key = f"{_LIFETIME_PNL_PREFIX}{engine}:{env}"
                kv_set(conn, key, repr(_to_float(kv_get(conn, key)) + all_sum))
            today_sum = _engine_resolved_pnl_sum(conn, engine, env, today_only=True)
            if abs(today_sum) > 1e-9:
                banked = _daily_wiped_pnl(conn, engine, env)
                kv_set(
                    conn, f"{_DAILY_PNL_PREFIX}{engine}:{env}",
                    json.dumps({"date": today, "pnl": banked + today_sum}),
                )


def effective_start_bankroll(conn, env: str, configured: float = 0.0) -> float:
    try:
        v = float(configured or 0.0)
    except (TypeError, ValueError):
        v = 0.0
    if v > 0:
        return v
    auto = earliest_pnl_total(conn, env)
    try:
        return float(auto) if auto and float(auto) > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def crypto15m_attempted_tickers(conn, env: str) -> set:
    rows = conn.execute(
        """SELECT DISTINCT ticker FROM crypto15m_positions
           WHERE network=? AND ticker IS NOT NULL
             AND created_at >= datetime('now','-6 hours')""",
        (env,),
    ).fetchall()
    return {r["ticker"] for r in rows}


def crypto15m_reconcile_candidates(conn, env: str, lookback_sql: str = "-6 hours") -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE network=? AND COALESCE(filled_contracts,0)=0
             AND status IN ('canceled','error')
             AND created_at >= datetime('now', ?)
           ORDER BY id DESC""",
        (env, lookback_sql),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_ticker_counts(conn, ticker: str, env: str) -> dict:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN COALESCE(filled_contracts,0)>0 THEN 1 ELSE 0 END) AS filled_rows
           FROM crypto15m_positions WHERE network=? AND ticker=?""",
        (env, ticker),
    ).fetchone()
    return {"total": int(row["total"] or 0), "filled_rows": int(row["filled_rows"] or 0)}


def recent_crypto15m(conn, env: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE network=?
           ORDER BY created_at DESC LIMIT ?""",
        (env, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_strategy_stats(conn, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT COALESCE(NULLIF(strategy, ''), 'directional') strategy,
                  COUNT(*) n,
                  SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) wins,
                  SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) losses,
                  ROUND(SUM(pnl_usd), 4) pnl_usd,
                  ROUND(SUM(COALESCE(fees_usd,0) + COALESCE(exit_fees_usd,0)), 4) fees_usd
           FROM crypto15m_positions
           WHERE network=? AND resolved=1 AND filled_contracts>0
             AND dry_run=0 AND pnl_usd IS NOT NULL
           GROUP BY 1 ORDER BY SUM(pnl_usd) DESC""",
        (env,),
    ).fetchall()
    return [dict(r) for r in rows]


def recent_crypto15m_resolved(conn, env: str, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE network=? AND resolved=1 AND filled_contracts>0 AND dry_run=0
           ORDER BY resolved_at DESC, id DESC LIMIT ?""",
        (env, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_stats(conn, env: str) -> dict:
    row = conn.execute(
        """SELECT
              SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_count,
              SUM(CASE WHEN resolved=1 AND outcome_correct=1 THEN 1 ELSE 0 END) AS wins,
              SUM(CASE WHEN resolved=1 AND outcome_correct=0 THEN 1 ELSE 0 END) AS losses,
              COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd END),0) AS realized_pnl,
              COUNT(*) AS total
           FROM crypto15m_positions WHERE network=?""",
        (env,),
    ).fetchone()
    return {
        "openCount": int(row["open_count"] or 0),
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "realizedPnlUsd": float(row["realized_pnl"] or 0.0),
        "total": int(row["total"] or 0),
    }


def insert_crypto15m_signal(conn, row: dict) -> bool:
    cur = conn.execute(
        """INSERT OR IGNORE INTO crypto15m_signals (
              ticker, asset, series, close_time, mins_left, favorite,
              favorite_price, entry_cost, up_prob, delta_pct, open_spot,
              obs_spot, book_imbalance, macd, macd_signal, macd_hist,
              macd_cross, rsi, strike, model_prob, edge_net_cents, network,
              interval
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["ticker"], row["asset"], row.get("series", ""),
            row.get("close_time", ""), row.get("mins_left"),
            row.get("favorite"), row.get("favorite_price"),
            row.get("entry_cost"), row.get("up_prob"), row.get("delta_pct"),
            row.get("open_spot"), row.get("obs_spot"),
            row.get("book_imbalance"),
            row.get("macd"), row.get("macd_signal"), row.get("macd_hist"),
            row.get("macd_cross"), row.get("rsi"),
            row.get("strike"), row.get("model_prob"), row.get("edge_net_cents"),
            row.get("network", "mainnet"),
            row.get("interval", "15m"),
        ),
    )
    return (cur.rowcount or 0) > 0


def unresolved_crypto15m_signals(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_signals
           WHERE resolved=0
           ORDER BY close_time ASC LIMIT ?""",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_crypto15m_signal(conn, ticker: str, up_won: int) -> None:
    conn.execute(
        """UPDATE crypto15m_signals
              SET resolved=1, up_won=?, settled_at=datetime('now')
            WHERE ticker=?""",
        (int(up_won), ticker),
    )


def fetch_resolved_crypto15m_signals(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_signals
           WHERE resolved=1 AND up_won IS NOT NULL"""
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_signal_counts(conn) -> dict:
    row = conn.execute(
        """SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved,
              SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS pending
           FROM crypto15m_signals"""
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "resolved": int(row["resolved"] or 0),
        "pending": int(row["pending"] or 0),
    }


_C15_TICKS_KEEP_DAYS = 60


def insert_clob_trades(conn, rows: list[dict], network: str = "mainnet") -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO clob_trades
              (asset_id, market, price, size, side, source_ts_ms, tx_hash, network)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(r.get("asset_id"), r.get("market"), r.get("price"), r.get("size"),
          r.get("side"), r.get("source_ts_ms"), r.get("tx"), network)
         for r in rows if r.get("asset_id") and r.get("price") is not None],
    )
    return len(rows)


def insert_crypto15m_tick(conn, row: dict) -> None:
    conn.execute(
        """INSERT INTO crypto15m_ticks (
              ticker, asset, mins_left, yes_bid, yes_ask, up_prob,
              spot, open_spot, delta_pct, book_imbalance, macd, macd_signal,
              macd_hist, macd_cross, rsi, ws_bid, ws_ask,
              strike, delta_signed_pct, sigma1m, model_prob, edge_net_cents,
              no_ask, spot_source, up_ask,
              vwap1h, ema12, sma20, sma50, price_vs_vwap_pct,
              ema12_vs_sma20_pct, ema1_vs_sma5_pct, velocity1m_pct,
              change5m_pct, change15m_pct,
              network, interval
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                     ?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["ticker"], row["asset"], row.get("mins_left"),
            row.get("yes_bid"), row.get("yes_ask"), row.get("up_prob"),
            row.get("spot"), row.get("open_spot"), row.get("delta_pct"),
            row.get("book_imbalance"),
            row.get("macd"), row.get("macd_signal"), row.get("macd_hist"),
            row.get("macd_cross"), row.get("rsi"),
            row.get("ws_bid"), row.get("ws_ask"),
            row.get("strike"), row.get("delta_signed_pct"), row.get("sigma1m"),
            row.get("model_prob"), row.get("edge_net_cents"),
            row.get("no_ask"), row.get("spot_source"), row.get("up_ask"),
            row.get("vwap1h"), row.get("ema12"), row.get("sma20"),
            row.get("sma50"), row.get("price_vs_vwap_pct"),
            row.get("ema12_vs_sma20_pct"), row.get("ema1_vs_sma5_pct"),
            row.get("velocity1m_pct"), row.get("change5m_pct"),
            row.get("change15m_pct"),
            row.get("network", "mainnet"),
            row.get("interval", "15m"),
        ),
    )


def crypto15m_tick_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM crypto15m_ticks").fetchone()[0])


def insert_pnl_snapshot(
    conn,
    *,
    cash_usd: float,
    portfolio_usd: float,
    realized_pnl_usd: float,
    wins: int,
    losses: int,
    open_positions: int,
    env: str,
) -> None:
    conn.execute(
        """INSERT INTO pnl_snapshots
              (network, cash_usd, portfolio_usd, total_usd, realized_pnl_usd,
               wins, losses, open_positions)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            env,
            float(cash_usd),
            float(portfolio_usd),
            float(cash_usd) + float(portfolio_usd),
            float(realized_pnl_usd),
            int(wins),
            int(losses),
            int(open_positions),
        ),
    )


def earliest_pnl_total(conn, env: str) -> float | None:
    row = conn.execute(
        """SELECT total_usd FROM pnl_snapshots
           WHERE network = ?
           ORDER BY at ASC LIMIT 1""",
        (env,),
    ).fetchone()
    if row is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def first_snapshot_of_today(conn, env: str, offset_min: int = 0) -> dict | None:
    row = conn.execute(
        """SELECT * FROM pnl_snapshots
           WHERE network = ? AND at >= ?
           ORDER BY at ASC LIMIT 1""",
        (env, day_start_utc(offset_min)),
    ).fetchone()
    return dict(row) if row else None


def latest_snapshot(conn, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM pnl_snapshots
           WHERE network = ?
           ORDER BY at DESC LIMIT 1""",
        (env,),
    ).fetchone()
    return dict(row) if row else None


_TRANSFER_MIN_JUMP_USD = 25.0


def transfer_adjustment_today(conn, env: str, offset_min: int = 0) -> float:
    row = conn.execute(
        "SELECT v FROM app_kv WHERE k = ?",
        (f"transfers:{env}:" + day_key(offset_min),),
    ).fetchone()
    try:
        return float(row[0]) if row else 0.0
    except (TypeError, ValueError):
        return 0.0


def _utc_today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def day_key(offset_min: int = 0) -> str:
    """``YYYY-MM-DD`` label for the trading day at ``offset_min`` from UTC.

    ``offset_min`` is the user's configured trading-timezone offset, so a US
    trader's day rolls at their local midnight rather than at 8pm ET.
    """
    return (
        datetime.now(timezone.utc) + timedelta(minutes=int(offset_min or 0))
    ).strftime("%Y-%m-%d")


def day_start_utc(offset_min: int = 0) -> str:
    """UTC timestamp of the start of that trading day, formatted for SQL.

    Timestamp columns here are written with ``datetime('now')``, which is UTC
    in ``'YYYY-MM-DD HH:MM:SS'`` form, so the returned string compares directly
    against ``created_at`` / ``at`` without any conversion in the query.
    """
    off = int(offset_min or 0)
    local = datetime.now(timezone.utc) + timedelta(minutes=off)
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (local_midnight - timedelta(minutes=off)).strftime("%Y-%m-%d %H:%M:%S")


def transfer_adjustment_total(conn, env: str) -> float:
    total = 0.0
    for row in conn.execute(
        "SELECT v FROM app_kv WHERE k LIKE ?", (f"transfers:{env}:%",)
    ):
        try:
            total += float(row[0])
        except (TypeError, ValueError):
            continue
    return total


def transfer_adjustment_run(conn, env: str, run_id: int) -> float:
    if not run_id:
        return 0.0
    row = conn.execute(
        "SELECT v FROM app_kv WHERE k = ?", (f"transfers_run:{env}:{int(run_id)}",)
    ).fetchone()
    try:
        return float(row[0]) if row else 0.0
    except (TypeError, ValueError):
        return 0.0


def note_transfer_if_unexplainable(
    conn, env: str, new_total: float, run_id: int = 0, offset_min: int = 0
) -> float:
    prev = latest_snapshot(conn, env)
    if not prev:
        return 0.0
    try:
        jump = float(new_total) - float(prev["total_usd"] or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if abs(jump) < _TRANSFER_MIN_JUMP_USD:
        return 0.0
    since = str(prev.get("at") or "")
    open_cost = conn.execute(
        """SELECT COALESCE((SELECT SUM(cost_usd) FROM bot_positions
                             WHERE resolved=0 AND filled_contracts>0 AND network=?),0)
                + COALESCE((SELECT SUM(cost_usd) FROM crypto15m_positions
                             WHERE resolved=0 AND filled_contracts>0 AND network=?),0)""",
        (env, env),
    ).fetchone()[0] or 0.0
    recent = conn.execute(
        """SELECT COALESCE((SELECT SUM(ABS(COALESCE(pnl_usd,0)))+SUM(COALESCE(cost_usd,0))
                             FROM bot_positions
                             WHERE network=? AND last_updated >= ?),0)
                + COALESCE((SELECT SUM(ABS(COALESCE(pnl_usd,0)))+SUM(COALESCE(cost_usd,0))
                             FROM crypto15m_positions
                             WHERE network=? AND last_updated >= ?),0)""",
        (env, since, env, since),
    ).fetchone()[0] or 0.0
    explainable = float(open_cost) + float(recent) + 5.0
    if abs(jump) <= explainable:
        return 0.0
    key = f"transfers:{env}:" + day_key(offset_min)
    row = conn.execute("SELECT v FROM app_kv WHERE k = ?", (key,)).fetchone()
    try:
        prior = float(row[0]) if row else 0.0
    except (TypeError, ValueError):
        prior = 0.0
    kv_set(conn, key, repr(prior + jump))
    if run_id:
        rkey = f"transfers_run:{env}:{int(run_id)}"
        kv_set(conn, rkey, repr(transfer_adjustment_run(conn, env, run_id) + jump))
    return jump


def start_bot_run(
    conn, *, env: str, cash_usd: float, portfolio_usd: float,
    lifetime_trades: int = 0, lifetime_wins: int = 0, lifetime_losses: int = 0,
) -> int:
    conn.execute(
        """UPDATE bot_runs
           SET ended_at = COALESCE(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
               notes    = COALESCE(notes, '') || ' [auto-closed on next start]'
           WHERE network = ? AND ended_at IS NULL""",
        (env,),
    )
    total = float(cash_usd) + float(portfolio_usd)
    cur = conn.execute(
        """INSERT INTO bot_runs (
              network, start_cash_usd, start_portfolio_usd,
              start_total_usd, end_cash_usd, end_portfolio_usd,
              end_total_usd, pnl_usd,
              start_trades_opened, start_trades_won, start_trades_lost,
              trades_opened, trades_won, trades_lost
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, 0, 0)""",
        (
            env, float(cash_usd), float(portfolio_usd), total,
            float(cash_usd), float(portfolio_usd), total,
            int(lifetime_trades), int(lifetime_wins), int(lifetime_losses),
        ),
    )
    return int(cur.lastrowid or 0)


def heartbeat_bot_run(
    conn, run_id: int, *, cash_usd: float, portfolio_usd: float,
    lifetime_trades: int = 0, lifetime_wins: int = 0, lifetime_losses: int = 0,
) -> None:
    if not run_id:
        return
    total = float(cash_usd) + float(portfolio_usd)
    conn.execute(
        """UPDATE bot_runs
              SET end_cash_usd = ?,
                  end_portfolio_usd = ?,
                  end_total_usd = ?,
                  pnl_usd = ? - start_total_usd,
                  trades_opened = MAX(0, ? - start_trades_opened),
                  trades_won    = MAX(0, ? - start_trades_won),
                  trades_lost   = MAX(0, ? - start_trades_lost)
            WHERE id = ?""",
        (
            float(cash_usd), float(portfolio_usd), total, total,
            int(lifetime_trades), int(lifetime_wins), int(lifetime_losses),
            int(run_id),
        ),
    )


def end_bot_run(conn, run_id: int) -> None:
    if not run_id:
        return
    conn.execute(
        "UPDATE bot_runs SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id = ? AND ended_at IS NULL",
        (int(run_id),),
    )


def get_active_run(conn, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM bot_runs
            WHERE network = ? AND ended_at IS NULL
            ORDER BY started_at DESC LIMIT 1""",
        (env,),
    ).fetchone()
    return dict(row) if row else None


def get_recent_runs(conn, env: str | None = None, limit: int = 50) -> list[dict]:
    if env:
        rows = conn.execute(
            """SELECT * FROM bot_runs
                WHERE network = ?
                ORDER BY started_at DESC LIMIT ?""",
            (env, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM bot_runs ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_pnl_snapshots(
    conn, *, since_hours: int = 168, env: str | None = None,
    max_points: int = 2000,
) -> list[dict]:
    since_hours = max(1, min(int(since_hours), 24 * 365))
    sql = "SELECT * FROM pnl_snapshots WHERE at >= datetime('now', ?)"
    args: list = [f"-{since_hours} hours"]
    if env:
        sql += " AND network = ?"
        args.append(env)
    sql += " ORDER BY at ASC"
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    if max_points and len(rows) > max_points:
        stride = -(-len(rows) // max_points)
        sampled = rows[::stride]
        if sampled[-1] is not rows[-1]:
            sampled.append(rows[-1])
        rows = sampled
    return rows


def recent_balance_transition(conn, env: str, within_sec: int = 180) -> bool:
    args = (env, f"-{int(within_sec)} seconds", f"-{int(within_sec)} seconds")
    for table, extra in (("bot_positions", ""),
                         ("crypto15m_positions", "AND dry_run = 0")):
        row = conn.execute(
            f"""SELECT 1 FROM {table}
                WHERE network = ? {extra}
                  AND ((resolved_at IS NOT NULL AND resolved_at >= datetime('now', ?))
                    OR (created_at >= datetime('now', ?)
                        AND status IN ('submitted', 'partial', 'filled')))
                LIMIT 1""",
            args,
        ).fetchone()
        if row:
            return True
    return False


def aggregate_stats(conn, env: str | None = None) -> dict:
    cond = ""
    args: list = []
    if env:
        cond = "AND network=?"
        args = [env]
    row = conn.execute(
        f"""SELECT
              SUM(CASE WHEN status IN ('submitted','partial') AND resolved=0 THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status='filled' AND resolved=0 THEN 1 ELSE 0 END) AS open_filled,
              SUM(CASE WHEN resolved=1 AND outcome_correct=1 THEN 1 ELSE 0 END) AS wins,
              SUM(CASE WHEN resolved=1 AND outcome_correct=0 THEN 1 ELSE 0 END) AS losses,
              COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd END),0) AS realized_pnl,
              COALESCE(SUM(CASE WHEN resolved=1 AND date(resolved_at)=date('now') THEN pnl_usd END),0) AS today_pnl,
              SUM(CASE WHEN resolved=1 AND outcome_correct=1 AND date(resolved_at)=date('now') THEN 1 ELSE 0 END) AS today_wins,
              SUM(CASE WHEN resolved=1 AND outcome_correct=0 AND date(resolved_at)=date('now') THEN 1 ELSE 0 END) AS today_losses,
              COALESCE(SUM(CASE WHEN resolved=0 AND status IN ('filled','partial') THEN cost_usd END),0) AS open_cost,
              COALESCE(SUM(fees_usd),0) AS fees,
              SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved_count,
              COUNT(*) AS total_opened
           FROM bot_positions
           WHERE status!='dry_run' {cond}""",
        args,
    ).fetchone()
    return {
        "pending": int(row["pending"] or 0),
        "open_filled": int(row["open_filled"] or 0),
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "realized_pnl": float(row["realized_pnl"] or 0.0),
        "today_pnl": float(row["today_pnl"] or 0.0),
        "today_wins": int(row["today_wins"] or 0),
        "today_losses": int(row["today_losses"] or 0),
        "open_cost": float(row["open_cost"] or 0.0),
        "fees": float(row["fees"] or 0.0),
        "resolved_count": int(row["resolved_count"] or 0),
        "total_opened": int(row["total_opened"] or 0),
    }


_DELETE_BATCH = 50_000


def _delete_batched(
    where_sql: str, params: tuple, table: str, *, batch: int = _DELETE_BATCH
) -> int:
    sql = (
        f"DELETE FROM {table} WHERE rowid IN "
        f"(SELECT rowid FROM {table} WHERE {where_sql} LIMIT ?)"
    )
    total = 0
    while True:
        with get_db() as conn:
            n = conn.execute(sql, (*params, batch)).rowcount or 0
        total += n
        if n < batch:
            return total


def cleanup_old_data(
    conn=None, *, trade_hours: int = 48, alert_days: int = 45,
    snapshot_hours: int = 6, pnl_days: int = 45,
    event_days: int = 30, c15_signal_days: int = 60,
) -> int:
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    trade_cutoff = (now - timedelta(hours=trade_hours)).strftime("%Y-%m-%d %H:%M:%S")
    alert_cutoff = (now - timedelta(days=alert_days)).strftime("%Y-%m-%d %H:%M:%S")
    snap_cutoff = (now - timedelta(hours=snapshot_hours)).strftime("%Y-%m-%d %H:%M:%S")
    pnl_cutoff = (now - timedelta(days=pnl_days)).strftime("%Y-%m-%d %H:%M:%S")
    settled_cutoff = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    event_cutoff = (now - timedelta(days=event_days)).strftime("%Y-%m-%d %H:%M:%S")
    c15sig_cutoff = (now - timedelta(days=c15_signal_days)).strftime("%Y-%m-%d %H:%M:%S")

    ticks_cutoff = (now - timedelta(days=_C15_TICKS_KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

    deleted = 0
    deleted += _delete_batched("created_time < ?", (trade_cutoff,), "trades")
    deleted += _delete_batched("snapshot_at < ?", (snap_cutoff,), "market_snapshots")
    deleted += _delete_batched("observed_at < ?", (ticks_cutoff,), "crypto15m_ticks")
    deleted += _delete_batched("ingested_at < ?", (ticks_cutoff,), "clob_trades")
    deleted += _delete_batched("created_at < ?", (event_cutoff,), "order_events")
    deleted += _delete_batched(
        "resolved = 1 AND observed_at < ?", (c15sig_cutoff,), "crypto15m_signals")
    deleted += _delete_batched(
        "status NOT IN ('active','open') AND last_updated < ?", (settled_cutoff,), "markets")
    deleted += _delete_batched(
        "close_time != '' AND close_time < ? AND last_updated < ?",
        (now_iso, settled_cutoff), "markets")
    deleted += _delete_batched("volume < 10 AND volume_24h < 5", (), "markets")
    with get_db() as c:
        deleted += c.execute(
            "DELETE FROM alerts WHERE resolved = 1 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM whale_trades WHERE resolved = 1 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM alerts WHERE resolved = 0 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM whale_trades WHERE resolved = 0 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM pnl_snapshots WHERE at < ?", (pnl_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM events WHERE last_updated < ?", (event_cutoff,)
        ).rowcount or 0
    return deleted


def _reclaimable_mb() -> float:
    with get_db() as conn:
        ps = conn.execute("PRAGMA page_size").fetchone()[0]
        fl = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return fl * ps / 1e6


def vacuum() -> None:
    conn = sqlite3.connect(str(db_path()), timeout=120)
    conn.isolation_level = None
    try:
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        conn.execute("VACUUM")
    finally:
        conn.close()


def backup_research(keep: int = 7) -> str | None:
    try:
        src = str(db_path())
        bdir = os.path.join(os.path.dirname(src), "backups")
        os.makedirs(bdir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        dest = os.path.join(bdir, f"research-{stamp}.db")
        if os.path.exists(dest):
            _mirror_to_vault(dest)
            return dest
        with get_db() as conn:
            out = sqlite3.connect(dest)
            try:
                conn.backup(out)
            finally:
                out.close()
        snaps = sorted(
            f for f in os.listdir(bdir)
            if f.startswith("research-") and f.endswith(".db")
        )
        for old_f in snaps[:-keep]:
            try:
                os.remove(os.path.join(bdir, old_f))
            except OSError:
                pass
        _mirror_to_vault(dest)
        return dest
    except Exception:
        return None


def _mirror_to_vault(snapshot: str) -> None:
    try:
        v = _vault_dir()
        if v is None:
            return
        dest = v / "research-latest.db"
        if dest.exists() and dest.stat().st_mtime >= os.path.getmtime(snapshot):
            return
        tmp = v / "research-latest.db.tmp"
        shutil.copy2(snapshot, tmp)
        os.replace(tmp, dest)
    except OSError:
        pass


def run_maintenance(*, vacuum_min_free_mb: float = 200.0, force_vacuum: bool = False) -> dict:
    deleted = cleanup_old_data()
    backed_up = backup_research()
    free_mb = _reclaimable_mb()
    vacuumed = False
    if force_vacuum or free_mb >= vacuum_min_free_mb:
        vacuum()
        vacuumed = True
    return {"deleted": deleted, "reclaimable_mb": round(free_mb, 1), "vacuumed": vacuumed,
            "backup": backed_up}
