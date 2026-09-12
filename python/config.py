from __future__ import annotations
from typing import Any

import re as _re

import rules as rules_engine

# pylint: disable=invalid-name

CRYPTO15M_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"]

C15_RULE_FIELDS = (
    "favoritePrice", "entryCost", "upProb", "bookImbalance",
    "arbEdgeCents", "deltaPct", "minsLeft",
    "hourUtc", "peersAgree", "marketBias",
    "macd", "macdSignal", "macdHist", "macdCross", "rsi",
    "deltaSignedPct", "upAsk", "downAsk", "sigma1m", "modelProb", "edgeNetCents",
    "vwap1h", "ema12", "sma20", "sma50", "priceVsVwapPct",
    "ema12VsSma20Pct", "ema1VsSma5Pct", "velocity1mPct",
    "change5mPct", "change15mPct",
)
C15_RULE_OPS = (">=", "<=", ">", "<")

BOT_RULE_FIELDS = ("confidence", "edge", "costCents")

DEFAULT_CONFIG: dict[str, Any] = {
    "network": "mainnet",
    "enable_trading": False,
    "main_paper_trading": False,
    "main_paper_bankroll_usd": 1000.0,

    "trade_whales": True,
    "trade_momentum": True,
    "trade_convergence": False,

    "min_edge_pts_whale": 5.0,
    "min_edge_pts_momentum": 5.0,
    "min_confidence_whale": 55.0,
    "min_confidence_momentum": 55.0,
    "min_entry_price_cents": 15,
    "max_entry_price_cents": 85,
    "max_resolution_days": 0,
    "allowed_momentum_signal_types": ["trade_cluster"],
    "allowed_categories": None,
    "allowed_whale_categories": None,
    "allowed_momentum_categories": None,
    "contrarian_only": True,

    "use_rules": False,
    "rules": [],

    "sizing_mode": "percent",
    "base_size_fraction": 0.03,
    "min_size_fraction": 0.02,
    "max_size_fraction": 0.06,
    "min_contracts": 5,
    "max_contracts": 20,
    "sizing_base_edge": 5.0,
    "sizing_max_edge": 20.0,
    "kelly_fraction": 0.25,
    # Optional live-only capital adjustment from rolling practice evidence.
    # Practice sizing is intentionally unchanged so it remains a fair record.
    "evidence_allocation_enabled": False,
    "hard_max_position_usd": 50.0,
    "min_cash_reserve_fraction": 0.05,

    "order_style": "limit_cross",
    "cross_spread_fallback_offset": 2,
    "order_expiration_sec": 300,

    "max_open_positions": 25,
    "max_positions_per_event": 1,
    "max_daily_new_positions": 40,
    "unlimited_daily_new_positions": False,
    "max_total_exposure_fraction": 0.75,
    # Correlated-outcome cap and peak-equity drawdown pause. Both default to
    # off so an existing installation keeps its current behaviour until the
    # user opts in; zero disables each control.
    "max_group_exposure_fraction": 0.0,
    "max_drawdown_fraction": 0.0,
    # Require displayed depth to support the order size before entering.
    "require_entry_depth": True,
    # Cents below the touch an exit may concede. Exits are never priced
    # without a live quote.
    "exit_price_loss_budget_cents": 2,

    "trade_scan_interval": 20,
    "position_poll_interval": 30,
    "balance_poll_interval": 60,
    "resolution_check_interval": 300,
    "whale_scan_interval": 120,
    "momentum_scan_interval": 90,
    "market_refresh_interval": 300,
    "db_cleanup_interval": 3600,

    "max_signal_age_sec": 120,

    "start_bankroll_usd": 0.0,
    "stop_loss_on_day": -50.0,
    "take_profit_on_day": 0.0,
    "take_profit_pct": 0.0,
    "flatten_on_daily_stop": False,
    "lifetime_loss_limit_pct": 0.5,
    "lifetime_loss_limit_usd": 0.0,

    "trading_hours_enabled": False,
    "trading_hours_start": "00:00",
    "trading_hours_end": "23:59",
    "trading_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "trading_timezone_offset_min": 0,

    "min_whale_usd": 2500.0,
    "min_whale_confidence": 30.0,
    "min_whale_edge": 2.0,
    "min_momentum_confidence": 0.0,
    "min_momentum_edge": 5.0,
    "min_entry_price_frac": 0.50,

    "crypto15m_interval": "15m",
    "crypto15m_assets": None,
    "crypto15m_arb_detect": True,
    "crypto15m_arb_min_edge_cents": 1.0,
    "crypto15m_imbalance_detect": True,
    "crypto15m_imbalance_levels": 3,
    "crypto15m_imbalance_gate": False,
    "crypto15m_imbalance_gate_min": 0.2,
    "crypto15m_indicator_detect": True,
    "crypto15m_min_rsi": 0.0,
    "crypto15m_min_macd_hist": 0.0,
    "crypto15m_ws_book": True,
    "crypto15m_use_rules": False,
    "crypto15m_rules": [],
    "crypto15m_rules_no": [],
    "crypto15m_time_delay_min": 8.0,
    "crypto15m_entry_threshold": 0.95,
    "crypto15m_entry_max": 0.98,
    "crypto15m_exit_threshold": 0.40,
    "crypto15m_take_profit": 0.0,
    "crypto15m_stop_loss_pct": 0.0,
    "crypto15m_take_profit_pct": 0.0,
    "crypto15m_min_delta_pct": 0.0,
    "crypto15m_entry_diff": 0.02,
    "crypto15m_entry_style": "taker",
    "crypto15m_taker_fak": True,
    "crypto15m_maker_cancel_min": 1.0,
    "crypto15m_maker_escalate": True,
    "crypto15m_maker_fill_sec": 4.0,
    "crypto15m_hours_start_utc": 0,
    "crypto15m_hours_end_utc": 24,
    "crypto15m_enabled": False,
    "crypto15m_sizing_mode": "fixed",
    "crypto15m_order_size": 5,
    "crypto15m_balance_pct": 0.02,
    "crypto15m_max_loss_pct": 0.0,
    "crypto15m_streak_sizing": False,
    "crypto15m_streak_loss_pct": 20.0,
    "crypto15m_streak_win_pct": 0.0,
    "crypto15m_streak_max_mult": 4.0,
    "crypto15m_max_concurrent": 7,
    "crypto15m_daily_loss_limit": -50.0,
    "crypto15m_lifetime_loss_limit_pct": 0.5,
    "crypto15m_lifetime_loss_limit_usd": 0.0,
    "crypto15m_take_profit_total": 0.0,
    "crypto15m_poll_sec": 4,
    "crypto15m_direction_mode": "favorite",
    "crypto15m_model_min_prob": 0.97,
    "crypto15m_model_min_edge_cents": 2.0,
    "crypto15m_model_final_minute": True,
    "crypto15m_model_autopause": True,
    "crypto15m_model_max_book_gap_cents": 25.0,
    "crypto15m_model_fm_max_book_gap_cents": 75.0,
    "crypto15m_autosize_to_min_notional": False,
    "crypto15m_spot_ws": True,
    "crypto15m_rtds_ws": True,
    "crypto15m_paired_mode": False,
    "crypto15m_paired_max_combined_cents": 100.0,
    "crypto15m_paired_tilt1_cents": 3.0,
    "crypto15m_paired_tilt2_cents": 6.0,
    "crypto15m_paired_tilt3_cents": 10.0,
    "crypto15m_sell_into_strength": False,
    "crypto15m_sell_strength_cents": 80.0,
    "crypto15m_record_signals": True,
    "main_record_signals": True,

    "copy_enabled": False,
    "copy_wallets": [],
    "copy_sizing_mode": "fixed",
    "copy_fixed_usd": 10.0,
    "copy_balance_pct": 0.02,
    "copy_min_trade_usd": 25.0,
    "copy_max_concurrent": 10,
    "copy_entry_max_cents": 95,
    "copy_daily_loss_limit": -50.0,
    "copy_lifetime_loss_limit_pct": 0.5,
    "copy_lifetime_loss_limit_usd": 0.0,
    "copy_poll_sec": 10,
    "copy_fast_poll_sec": 5,
    "copy_activity_ws": True,
    "copy_mirror_reductions": True,
    "copy_reduce_threshold": 0.25,
    "copy_only_new_entries": True,
    "copy_allow_reentries": False,

    "scripts_live_enabled": False,
    "script_poll_sec": 5,
    "script_hook_timeout_sec": 1.0,
    "script_max_entry_cents": 97,
    "script_max_contracts": 20,
    "script_max_open": 2,
    "script_daily_loss_usd": 25.0,
    "script_max_enabled": 10,
    "script_market_limit": 150,
    "script_market_min_volume": 5000.0,
    "script_market_max_spread_cents": 2.0,

    "event_webhook_url": "",
    "stats_webhook_url": "",
    "whale_webhook_url": "",
    "momentum_webhook_url": "",
    "stats_push_interval": 3600,
    "stats_chart_window_hours": 168,
    "enable_discord": True,
}


STRATEGY_PRESETS: list[dict[str, Any]] = [
    {
        "id": "rom-balanced",
        "name": "ROM Balanced",
        "tagline": "Whales + momentum, both gates active.",
        "description": (
            "Our default everyday strategy. Trades both whale signals and "
            "trade-cluster momentum signals with edge ≥ 5pts and "
            "confidence ≥ 55%. 2-6% sizing, $50 hard cap. Best fit for "
            "most users — let it run a few weeks and check the stats."
        ),
        "riskLabel": "balanced",
        "badge": "recommended",
        "config": {},
    },
    {
        "id": "rom-conservative",
        "name": "ROM Conservative",
        "tagline": "Tight sizing, high-edge only, capital-preservation mode.",
        "description": (
            "Only trades signals with edge ≥ 8pts and confidence ≥ 65%. "
            "Smaller sizing (1-3% of bankroll), $25 hard cap. Daily "
            "stop-loss at -$25. Designed to ride out variance with "
            "minimum drawdown."
        ),
        "riskLabel": "safe",
        "config": {
            "min_edge_pts_whale": 8.0,
            "min_edge_pts_momentum": 8.0,
            "min_confidence_whale": 65.0,
            "min_confidence_momentum": 65.0,
            "base_size_fraction": 0.015,
            "min_size_fraction": 0.01,
            "max_size_fraction": 0.03,
            "hard_max_position_usd": 25.0,
            "max_open_positions": 10,
            "max_daily_new_positions": 15,
            "stop_loss_on_day": -25.0,
            "max_total_exposure_fraction": 0.50,
        },
    },
    {
        "id": "rom-aggressive",
        "name": "ROM Aggressive",
        "tagline": "More signals, larger sizing, higher variance.",
        "description": (
            "Loosens edge gates to 3pts and confidence to 50%. Sizing "
            "scales 4-10% of bankroll, $100 cap. Higher max-open count. "
            "Use only with a bankroll you can stand to drop 30% on a "
            "bad day."
        ),
        "riskLabel": "aggressive",
        "config": {
            "min_edge_pts_whale": 3.0,
            "min_edge_pts_momentum": 3.0,
            "min_confidence_whale": 50.0,
            "min_confidence_momentum": 50.0,
            "base_size_fraction": 0.06,
            "min_size_fraction": 0.04,
            "max_size_fraction": 0.10,
            "hard_max_position_usd": 100.0,
            "max_open_positions": 40,
            "max_daily_new_positions": 80,
            "max_total_exposure_fraction": 0.85,
            "stop_loss_on_day": -100.0,
        },
    },
    {
        "id": "rom-whale-only",
        "name": "Whale Hunter",
        "tagline": "Follows large taker orders. No momentum signals.",
        "description": (
            "Pure whale-following. Disables momentum entirely and only "
            "trades when a $2.5k+ taker order hits a market with a "
            "scored edge ≥ 5pts. Best when you trust 'smart money' "
            "patterns more than crowd contrarian setups."
        ),
        "riskLabel": "balanced",
        "config": {
            "trade_whales": True,
            "trade_momentum": False,
            "min_edge_pts_whale": 5.0,
            "min_confidence_whale": 55.0,
        },
    },
    {
        "id": "rom-momentum-only",
        "name": "Crowd Contrarian",
        "tagline": "Mean-reversion on trade clusters. No whale signals.",
        "description": (
            "Only fades clusters of trades against the underdog. "
            "Empirically the highest-edge zone in the data: NO clusters "
            "when YES is heavy favourite, YES clusters when YES is deep "
            "underdog. Disables whale-following entirely."
        ),
        "riskLabel": "balanced",
        "config": {
            "trade_whales": False,
            "trade_momentum": True,
            "contrarian_only": True,
            "min_edge_pts_momentum": 7.0,
            "min_confidence_momentum": 50.0,
            "allowed_momentum_signal_types": ["trade_cluster"],
        },
    },
    {
        "id": "rom-edge-hunter",
        "name": "Edge Hunter",
        "tagline": "Top-decile edge only. Few but high-quality trades.",
        "description": (
            "Only fires on signals with edge ≥ 12pts. Sizes more "
            "aggressively on high-edge picks (4-8% scaled). Expect "
            "long quiet periods between trades, but a higher hit rate "
            "when they happen."
        ),
        "riskLabel": "balanced",
        "config": {
            "min_edge_pts_whale": 12.0,
            "min_edge_pts_momentum": 12.0,
            "min_confidence_whale": 60.0,
            "min_confidence_momentum": 55.0,
            "base_size_fraction": 0.04,
            "min_size_fraction": 0.04,
            "max_size_fraction": 0.08,
            "sizing_base_edge": 12.0,
            "sizing_max_edge": 25.0,
            "max_open_positions": 15,
        },
    },
    {
        "id": "rom-crypto-whale",
        "name": "Crypto Whale",
        "tagline": "Whale-following, crypto markets only.",
        "description": (
            "DID NOT HOLD UP: the June sample (+9.3c/contract, n=36) reversed "
            "on 12 days of new data — crypto whales measured -3.9c/contract "
            "(n=143, t=-1.7). Kept so existing users can see the update; not "
            "recommended. The whale edge that IS holding lives in soccer "
            "match markets at 50-85c entries (see Edge Stack)."
        ),
        "riskLabel": "experimental",
        "badge": "",
        "config": {
            "trade_whales": True,
            "trade_momentum": False,
            "allowed_categories": ["crypto"],
            "min_confidence_whale": 55.0,
            "min_edge_pts_whale": 5.0,
            "min_entry_price_cents": 15,
            "max_entry_price_cents": 98,
        },
    },
    {
        "id": "rom-sports-momentum",
        "name": "Sports Momentum",
        "tagline": "Contrarian trade-clusters, sports only.",
        "description": (
            "Held up on 12 days of new data: momentum in US-sports markets "
            "measured +5.9c/contract (n=598, per-event t=+2.0; the 30-50c "
            "entry band was the best pocket at +7.9c). The mirror finding "
            "still holds too — momentum in soccer/world markets is strongly "
            "NEGATIVE (-16.9c/ct, t=-7.7), which this preset's category "
            "filter excludes. EXPERIMENTAL / in-sample — validate forward."
        ),
        "riskLabel": "experimental",
        "badge": "new",
        "config": {
            "trade_whales": False,
            "trade_momentum": True,
            "contrarian_only": True,
            "allowed_categories": ["sports"],
            "allowed_momentum_signal_types": ["trade_cluster"],
            "min_confidence_momentum": 40.0,
            "min_entry_price_cents": 15,
            "max_entry_price_cents": 70,
        },
    },
    {
        "id": "rom-edge",
        "name": "Edge Stack",
        "tagline": "Both live edges at once — sports whales + sports momentum.",
        "description": (
            "Our recommended pick, re-tuned 2026-07-05 on 12 days of data "
            "(4,152 resolved whale + 866 momentum signals). Whales follow "
            "informed money in SPORTS match markets — currently dominated by "
            "World Cup soccer, +13.8c/contract at 50-85c entries (52 matches, "
            "per-event t=+3.6); US-sports whales are ~flat, so the blended "
            "sports-whale edge is ~+4.4c/ct. Momentum stays SPORTS-only "
            "(+5.9c/ct, n=598). The old crypto-whale leg was dropped: it "
            "reversed to -3.9c/ct on the bigger sample. Expect the soccer "
            "component to fade after the World Cup final (Jul 19) — check "
            "the Backtest page's category breakdown as data accrues. "
            "EXPERIMENTAL / in-sample."
        ),
        "riskLabel": "experimental",
        "badge": "recommended",
        "config": {
            "trade_whales": True,
            "trade_momentum": True,
            "contrarian_only": True,
            "allowed_categories": None,
            "allowed_whale_categories": ["sports"],
            "allowed_momentum_categories": ["sports"],
            "allowed_momentum_signal_types": ["trade_cluster"],
            "min_confidence_whale": 55.0,
            "min_edge_pts_whale": 5.0,
            "min_confidence_momentum": 40.0,
            "min_entry_price_cents": 15,
            "max_entry_price_cents": 85,
        },
    },
]


CRYPTO15M_PRESETS: list[dict[str, Any]] = [
    {
        "id": "c15-favorite",
        "name": "Deep Favorite",
        "tagline": "Only the deepest favorites: buy at 95-98c.",
        "description": (
            "Buy the favorite only when it is already >=95c — the single "
            "price band that did not lose money in this app's replay of "
            "531 settled 15-minute markets (+2.8c/contract net of fees, "
            "16/16 wins). CAUTION: that sample is far too small to prove "
            "an edge; one loss at 97c wipes out ~35 wins. Paper-trade "
            "first."
        ),
        "config": {
            "crypto15m_direction_mode": "favorite",
            "crypto15m_entry_threshold": 0.95,
            "crypto15m_entry_max": 0.98,
            "crypto15m_exit_threshold": 0.40,
            "crypto15m_entry_style": "taker",
        },
    },
    {
        "id": "c15-contrarian",
        "name": "Contrarian Fade",
        "tagline": "Fade extreme favorites — buy the cheap underdog.",
        "description": (
            "When a side is an extreme favorite (>=90c), buy the CHEAP "
            "opposite side, betting the 15-minute move reverts before "
            "close. Low win rate, high payoff (longshot); holds to "
            "settlement, no stop. Measured roughly break-even (+1.0c/"
            "contract, t=0.3, n=64) on the recorded data — no proven "
            "edge. Paper-trade hard."
        ),
        "config": {
            "crypto15m_direction_mode": "contrarian",
            "crypto15m_entry_threshold": 0.90,
            "crypto15m_entry_max": 0.98,
            "crypto15m_exit_threshold": 0.0,
            "crypto15m_entry_style": "taker",
        },
    },
]


def crypto15m_preset_config(preset_id: str) -> dict[str, Any] | None:
    for p in CRYPTO15M_PRESETS:
        if p["id"] == preset_id:
            return dict(p["config"])
    return None


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch.lower() if ch.isupper() else ch)
    return "".join(out)


def _as_float(v: Any, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if f != f else f


def _clampf(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:
        return default
    return max(lo, min(hi, f))


def _clampi(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


_FRACTION_KEYS = [
    "base_size_fraction", "min_size_fraction", "max_size_fraction",
    "min_cash_reserve_fraction", "max_total_exposure_fraction",
    "max_group_exposure_fraction", "max_drawdown_fraction",
]
_UNIT_KEYS = [
    "crypto15m_entry_threshold", "crypto15m_entry_max", "crypto15m_exit_threshold",
    "crypto15m_take_profit", "crypto15m_stop_loss_pct", "crypto15m_take_profit_pct",
    "crypto15m_min_delta_pct", "crypto15m_entry_diff", "min_entry_price_frac",
    "take_profit_pct",
]


def _validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    d = DEFAULT_CONFIG

    cfg["main_paper_trading"] = bool(cfg.get("main_paper_trading", d["main_paper_trading"]))
    cfg["main_paper_bankroll_usd"] = _clampf(
        cfg.get("main_paper_bankroll_usd"), 25.0, 1_000_000.0,
        d["main_paper_bankroll_usd"],
    )
    if bool(cfg.get("enable_trading")):
        cfg["main_paper_trading"] = False

    if "dry_run" in cfg:
        if bool(cfg.get("dry_run")):
            cfg["enable_trading"] = False
        cfg.pop("dry_run", None)
    if "crypto15m_live" in cfg:
        if cfg.get("crypto15m_enabled") and not cfg.get("crypto15m_live"):
            cfg["crypto15m_enabled"] = False
        cfg.pop("crypto15m_live", None)
    if "copy_live" in cfg:
        if cfg.get("copy_enabled") and not cfg.get("copy_live"):
            cfg["copy_enabled"] = False
        cfg.pop("copy_live", None)

    for k in _FRACTION_KEYS:
        cfg[k] = _clampf(cfg.get(k), 0.0, 1.0, d[k])
    for k in _UNIT_KEYS:
        cfg[k] = _clampf(cfg.get(k), 0.0, 1.0, d[k])
    if cfg["min_size_fraction"] > cfg["max_size_fraction"]:
        cfg["min_size_fraction"] = cfg["max_size_fraction"]
    if cfg.get("sizing_mode") not in ("percent", "contracts", "kelly"):
        cfg["sizing_mode"] = d["sizing_mode"]
    cfg["evidence_allocation_enabled"] = bool(cfg.get(
        "evidence_allocation_enabled", d["evidence_allocation_enabled"]
    ))
    cfg["kelly_fraction"] = _clampf(cfg.get("kelly_fraction"), 0.01, 1.0, d["kelly_fraction"])
    cfg["min_contracts"] = _clampi(cfg.get("min_contracts"), 1, 1_000_000, d["min_contracts"])
    cfg["max_contracts"] = _clampi(cfg.get("max_contracts"), 1, 1_000_000, d["max_contracts"])
    cfg["max_contracts"] = max(cfg["min_contracts"], cfg["max_contracts"])

    cfg["hard_max_position_usd"] = _clampf(cfg.get("hard_max_position_usd"), 0.0, 1e9, d["hard_max_position_usd"])
    cfg["min_entry_price_cents"] = _clampi(cfg.get("min_entry_price_cents"), 1, 99, d["min_entry_price_cents"])
    cfg["max_entry_price_cents"] = _clampi(cfg.get("max_entry_price_cents"), 1, 99, d["max_entry_price_cents"])
    if cfg["min_entry_price_cents"] > cfg["max_entry_price_cents"]:
        cfg["min_entry_price_cents"], cfg["max_entry_price_cents"] = (
            cfg["max_entry_price_cents"], cfg["min_entry_price_cents"],
        )
    cfg["use_rules"] = bool(cfg.get("use_rules", False))
    cfg["rules"] = rules_engine.sanitize_rules(cfg.get("rules"), BOT_RULE_FIELDS)
    cfg["max_open_positions"] = _clampi(cfg.get("max_open_positions"), 0, 100_000, d["max_open_positions"])
    cfg["max_resolution_days"] = _clampi(cfg.get("max_resolution_days"), 0, 100_000, d["max_resolution_days"])
    cfg["max_daily_new_positions"] = _clampi(cfg.get("max_daily_new_positions"), 0, 100_000, d["max_daily_new_positions"])
    cfg["max_positions_per_event"] = _clampi(cfg.get("max_positions_per_event"), 1, 100_000, d["max_positions_per_event"])
    cfg["stop_loss_on_day"] = _clampf(
        -abs(_as_float(cfg.get("stop_loss_on_day"), d["stop_loss_on_day"])),
        -1e9, 0.0, d["stop_loss_on_day"],
    )
    cfg["take_profit_on_day"] = _clampf(cfg.get("take_profit_on_day"), 0.0, 1e9, d["take_profit_on_day"])
    cfg["flatten_on_daily_stop"] = bool(cfg.get("flatten_on_daily_stop", d["flatten_on_daily_stop"]))
    cfg["require_entry_depth"] = bool(cfg.get("require_entry_depth", d["require_entry_depth"]))

    for _k, _lo, _hi in [
        ("crypto15m_poll_sec", 2, 3600),
        ("trade_scan_interval", 5, 86_400),
        ("position_poll_interval", 5, 86_400),
        ("balance_poll_interval", 5, 86_400),
        ("max_signal_age_sec", 10, 86_400),
        ("order_expiration_sec", 10, 86_400),
        ("resolution_check_interval", 10, 86_400),
        ("whale_scan_interval", 10, 86_400),
        ("momentum_scan_interval", 10, 86_400),
        ("market_refresh_interval", 30, 86_400),
        ("db_cleanup_interval", 60, 604_800),
        ("stats_push_interval", 60, 604_800),
    ]:
        cfg[_k] = _clampi(cfg.get(_k), _lo, _hi, d[_k])

    cfg["crypto15m_enabled"] = bool(cfg.get("crypto15m_enabled", False))
    cfg["crypto15m_order_size"] = _clampi(cfg.get("crypto15m_order_size"), 1, 10_000, d["crypto15m_order_size"])
    cfg["crypto15m_max_concurrent"] = _clampi(cfg.get("crypto15m_max_concurrent"), 1, 50, d["crypto15m_max_concurrent"])
    cfg["crypto15m_daily_loss_limit"] = _clampf(
        -abs(_as_float(cfg.get("crypto15m_daily_loss_limit"), d["crypto15m_daily_loss_limit"])),
        -1e9, 0.0, d["crypto15m_daily_loss_limit"],
    )
    cfg["crypto15m_lifetime_loss_limit_pct"] = _clampf(
        cfg.get("crypto15m_lifetime_loss_limit_pct"), 0.0, 1.0,
        d["crypto15m_lifetime_loss_limit_pct"],
    )
    cfg["crypto15m_lifetime_loss_limit_usd"] = _clampf(
        cfg.get("crypto15m_lifetime_loss_limit_usd"), 0.0, 1e9,
        d["crypto15m_lifetime_loss_limit_usd"],
    )
    cfg["lifetime_loss_limit_pct"] = _clampf(
        cfg.get("lifetime_loss_limit_pct"), 0.0, 1.0, d["lifetime_loss_limit_pct"],
    )
    cfg["lifetime_loss_limit_usd"] = _clampf(
        cfg.get("lifetime_loss_limit_usd"), 0.0, 1e9, d["lifetime_loss_limit_usd"],
    )
    cfg["crypto15m_take_profit_total"] = _clampf(
        cfg.get("crypto15m_take_profit_total"), 0.0, 1e9, d["crypto15m_take_profit_total"],
    )
    if cfg.get("crypto15m_sizing_mode") not in ("fixed", "balance_pct"):
        cfg["crypto15m_sizing_mode"] = d["crypto15m_sizing_mode"]
    cfg["crypto15m_balance_pct"] = _clampf(cfg.get("crypto15m_balance_pct"), 0.0, 1.0, d["crypto15m_balance_pct"])
    cfg["crypto15m_max_loss_pct"] = _clampf(cfg.get("crypto15m_max_loss_pct"), 0.0, 1.0, d["crypto15m_max_loss_pct"])
    cfg["crypto15m_streak_sizing"] = bool(
        cfg.get("crypto15m_streak_sizing", d["crypto15m_streak_sizing"]))
    cfg["crypto15m_streak_loss_pct"] = _clampf(
        cfg.get("crypto15m_streak_loss_pct"), -90.0, 300.0, d["crypto15m_streak_loss_pct"])
    cfg["crypto15m_streak_win_pct"] = _clampf(
        cfg.get("crypto15m_streak_win_pct"), -90.0, 300.0, d["crypto15m_streak_win_pct"])
    cfg["crypto15m_streak_max_mult"] = _clampf(
        cfg.get("crypto15m_streak_max_mult"), 1.0, 100.0, d["crypto15m_streak_max_mult"])
    _iv_raw = str(cfg.get("crypto15m_interval", d["crypto15m_interval"]))
    _iv_max_min = {"5m": 5.0, "15m": 15.0, "hourly": 60.0}.get(_iv_raw, 15.0)
    cfg["crypto15m_time_delay_min"] = _clampf(
        cfg.get("crypto15m_time_delay_min"), 0.0, _iv_max_min,
        min(float(d["crypto15m_time_delay_min"]), _iv_max_min))
    if cfg.get("crypto15m_direction_mode") not in ("favorite", "contrarian", "model"):
        cfg["crypto15m_direction_mode"] = d["crypto15m_direction_mode"]
    cfg["crypto15m_model_min_prob"] = _clampf(
        cfg.get("crypto15m_model_min_prob"), 0.5, 1.0, d["crypto15m_model_min_prob"])
    cfg["crypto15m_model_min_edge_cents"] = _clampf(
        cfg.get("crypto15m_model_min_edge_cents"), 0.0, 50.0,
        d["crypto15m_model_min_edge_cents"])
    cfg["crypto15m_model_final_minute"] = bool(
        cfg.get("crypto15m_model_final_minute", d["crypto15m_model_final_minute"]))
    cfg["crypto15m_model_max_book_gap_cents"] = _clampf(
        cfg.get("crypto15m_model_max_book_gap_cents"), 0.0, 100.0,
        d["crypto15m_model_max_book_gap_cents"])
    cfg["crypto15m_model_fm_max_book_gap_cents"] = _clampf(
        cfg.get("crypto15m_model_fm_max_book_gap_cents"), 0.0, 100.0,
        d["crypto15m_model_fm_max_book_gap_cents"])
    cfg["crypto15m_model_autopause"] = bool(
        cfg.get("crypto15m_model_autopause", d["crypto15m_model_autopause"]))
    cfg["crypto15m_spot_ws"] = bool(cfg.get("crypto15m_spot_ws", d["crypto15m_spot_ws"]))
    cfg["crypto15m_rtds_ws"] = bool(cfg.get("crypto15m_rtds_ws", d["crypto15m_rtds_ws"]))
    cfg["crypto15m_paired_mode"] = bool(
        cfg.get("crypto15m_paired_mode", d["crypto15m_paired_mode"]))
    cfg["crypto15m_paired_max_combined_cents"] = _clampf(
        cfg.get("crypto15m_paired_max_combined_cents"), 50.0, 100.0,
        d["crypto15m_paired_max_combined_cents"])
    _t1 = _clampf(cfg.get("crypto15m_paired_tilt1_cents"), 0.0, 50.0,
                  d["crypto15m_paired_tilt1_cents"])
    _t2 = _clampf(cfg.get("crypto15m_paired_tilt2_cents"), 0.0, 50.0,
                  d["crypto15m_paired_tilt2_cents"])
    _t3 = _clampf(cfg.get("crypto15m_paired_tilt3_cents"), 0.0, 50.0,
                  d["crypto15m_paired_tilt3_cents"])
    _t2 = max(_t1, _t2)
    _t3 = max(_t2, _t3)
    cfg["crypto15m_paired_tilt1_cents"] = _t1
    cfg["crypto15m_paired_tilt2_cents"] = _t2
    cfg["crypto15m_paired_tilt3_cents"] = _t3
    cfg["crypto15m_sell_into_strength"] = bool(
        cfg.get("crypto15m_sell_into_strength", d["crypto15m_sell_into_strength"]))
    cfg["crypto15m_sell_strength_cents"] = _clampf(
        cfg.get("crypto15m_sell_strength_cents"), 50.0, 99.0,
        d["crypto15m_sell_strength_cents"])
    cfg["main_record_signals"] = bool(cfg.get("main_record_signals", d["main_record_signals"]))
    if cfg.get("crypto15m_entry_style") not in ("maker", "taker"):
        cfg["crypto15m_entry_style"] = d["crypto15m_entry_style"]
    cfg["crypto15m_taker_fak"] = bool(cfg.get("crypto15m_taker_fak", True))
    if cfg.get("crypto15m_interval") not in ("5m", "15m", "hourly"):
        cfg["crypto15m_interval"] = d["crypto15m_interval"]
    aw = cfg.get("crypto15m_assets")
    if isinstance(aw, list):
        valid = {a.upper() for a in CRYPTO15M_ASSETS}
        cfg["crypto15m_assets"] = [
            a.upper() for a in aw if isinstance(a, str) and a.upper() in valid
        ]
    elif aw is not None:
        cfg["crypto15m_assets"] = None
    cfg["crypto15m_arb_detect"] = bool(cfg.get("crypto15m_arb_detect", True))
    cfg["crypto15m_arb_min_edge_cents"] = _clampf(
        cfg.get("crypto15m_arb_min_edge_cents"), 0.0, 100.0, d["crypto15m_arb_min_edge_cents"],
    )
    cfg["crypto15m_imbalance_detect"] = bool(cfg.get("crypto15m_imbalance_detect", True))
    cfg["crypto15m_imbalance_levels"] = _clampi(
        cfg.get("crypto15m_imbalance_levels"), 1, 20, d["crypto15m_imbalance_levels"],
    )
    cfg["crypto15m_imbalance_gate"] = bool(cfg.get("crypto15m_imbalance_gate", False))
    cfg["crypto15m_imbalance_gate_min"] = _clampf(
        cfg.get("crypto15m_imbalance_gate_min"), 0.0, 1.0, d["crypto15m_imbalance_gate_min"],
    )
    if cfg["crypto15m_imbalance_gate"]:
        cfg["crypto15m_imbalance_detect"] = True
    cfg["crypto15m_indicator_detect"] = bool(cfg.get("crypto15m_indicator_detect", True))
    cfg["crypto15m_min_rsi"] = _clampf(cfg.get("crypto15m_min_rsi"), 0.0, 100.0, d["crypto15m_min_rsi"])
    cfg["crypto15m_min_macd_hist"] = _clampf(cfg.get("crypto15m_min_macd_hist"), 0.0, 1e9, d["crypto15m_min_macd_hist"])
    if cfg["crypto15m_min_rsi"] > 0 or cfg["crypto15m_min_macd_hist"] > 0:
        cfg["crypto15m_indicator_detect"] = True
    cfg["crypto15m_ws_book"] = bool(cfg.get("crypto15m_ws_book", True))
    cfg["crypto15m_use_rules"] = bool(cfg.get("crypto15m_use_rules", False))
    clean_rules = rules_engine.sanitize_rules(cfg.get("crypto15m_rules"), C15_RULE_FIELDS)
    cfg["crypto15m_rules"] = clean_rules
    clean_rules_no = rules_engine.sanitize_rules(cfg.get("crypto15m_rules_no"), C15_RULE_FIELDS)
    cfg["crypto15m_rules_no"] = clean_rules_no
    if cfg["crypto15m_use_rules"]:
        rule_fields = {c["field"] for c in clean_rules} | {c["field"] for c in clean_rules_no}
        if "bookImbalance" in rule_fields:
            cfg["crypto15m_imbalance_detect"] = True
        if "arbEdgeCents" in rule_fields:
            cfg["crypto15m_arb_detect"] = True
        if rule_fields & {
            "macd", "macdSignal", "macdHist", "macdCross", "rsi", "sigma1m",
            "vwap1h", "ema12", "sma20", "sma50", "priceVsVwapPct",
            "ema12VsSma20Pct", "ema1VsSma5Pct", "velocity1mPct",
            "change5mPct", "change15mPct",
        }:
            cfg["crypto15m_indicator_detect"] = True
    cfg["crypto15m_maker_cancel_min"] = _clampf(cfg.get("crypto15m_maker_cancel_min"), 0.0, 15.0, d["crypto15m_maker_cancel_min"])
    cfg["crypto15m_maker_escalate"] = bool(cfg.get("crypto15m_maker_escalate", d["crypto15m_maker_escalate"]))
    cfg["crypto15m_maker_fill_sec"] = _clampf(cfg.get("crypto15m_maker_fill_sec"), 0.0, 900.0, d["crypto15m_maker_fill_sec"])
    cfg["crypto15m_hours_start_utc"] = _clampi(cfg.get("crypto15m_hours_start_utc"), 0, 24, d["crypto15m_hours_start_utc"])
    cfg["crypto15m_hours_end_utc"] = _clampi(cfg.get("crypto15m_hours_end_utc"), 0, 24, d["crypto15m_hours_end_utc"])

    cfg["copy_enabled"] = bool(cfg.get("copy_enabled", False))
    seen: set[str] = set()
    clean_wallets: list[str] = []
    for w in (cfg.get("copy_wallets") or []):
        if not isinstance(w, str):
            continue
        a = w.strip().lower()
        if _re.fullmatch(r"0x[0-9a-f]{40}", a) and a not in seen:
            seen.add(a)
            clean_wallets.append(a)
    cfg["copy_wallets"] = clean_wallets
    if cfg.get("copy_sizing_mode") not in ("fixed", "balance_pct"):
        cfg["copy_sizing_mode"] = d["copy_sizing_mode"]
    cfg["copy_fixed_usd"] = _clampf(cfg.get("copy_fixed_usd"), 0.0, 100_000.0, d["copy_fixed_usd"])
    cfg["copy_balance_pct"] = _clampf(cfg.get("copy_balance_pct"), 0.0, 1.0, d["copy_balance_pct"])
    cfg["copy_min_trade_usd"] = _clampf(cfg.get("copy_min_trade_usd"), 0.0, 1e9, d["copy_min_trade_usd"])
    cfg["copy_max_concurrent"] = _clampi(cfg.get("copy_max_concurrent"), 1, 200, d["copy_max_concurrent"])
    cfg["copy_entry_max_cents"] = _clampi(cfg.get("copy_entry_max_cents"), 1, 99, d["copy_entry_max_cents"])
    cfg["copy_daily_loss_limit"] = _clampf(
        -abs(_as_float(cfg.get("copy_daily_loss_limit"), d["copy_daily_loss_limit"])),
        -1e9, 0.0, d["copy_daily_loss_limit"],
    )
    cfg["copy_lifetime_loss_limit_pct"] = _clampf(
        cfg.get("copy_lifetime_loss_limit_pct"), 0.0, 1.0,
        d["copy_lifetime_loss_limit_pct"],
    )
    cfg["copy_lifetime_loss_limit_usd"] = _clampf(
        cfg.get("copy_lifetime_loss_limit_usd"), 0.0, 1e9,
        d["copy_lifetime_loss_limit_usd"],
    )
    cfg["copy_poll_sec"] = _clampi(cfg.get("copy_poll_sec"), 5, 3600, d["copy_poll_sec"])
    cfg["copy_fast_poll_sec"] = _clampi(
        cfg.get("copy_fast_poll_sec"), 2, 3600, d["copy_fast_poll_sec"])
    cfg["copy_activity_ws"] = bool(cfg.get("copy_activity_ws", True))
    cfg["copy_mirror_reductions"] = bool(cfg.get("copy_mirror_reductions", True))
    cfg["copy_reduce_threshold"] = _clampf(
        cfg.get("copy_reduce_threshold"), 0.05, 0.95, d["copy_reduce_threshold"])
    cfg["copy_only_new_entries"] = bool(cfg.get("copy_only_new_entries", True))
    cfg["copy_allow_reentries"] = bool(cfg.get("copy_allow_reentries", False))
    cfg["scripts_live_enabled"] = bool(cfg.get("scripts_live_enabled", False))
    cfg["script_poll_sec"] = _clampi(cfg.get("script_poll_sec"), 2, 3600, d["script_poll_sec"])
    cfg["script_hook_timeout_sec"] = _clampf(
        cfg.get("script_hook_timeout_sec"), 0.05, 30.0,
        d["script_hook_timeout_sec"])
    cfg["script_max_entry_cents"] = _clampi(
        cfg.get("script_max_entry_cents"), 1, 99, d["script_max_entry_cents"])
    cfg["script_max_contracts"] = _clampi(
        cfg.get("script_max_contracts"), 1, 10_000, d["script_max_contracts"])
    cfg["script_max_open"] = _clampi(cfg.get("script_max_open"), 1, 100, d["script_max_open"])
    cfg["script_daily_loss_usd"] = _clampf(
        cfg.get("script_daily_loss_usd"), 0.0, 1e6, d["script_daily_loss_usd"])
    cfg["script_max_enabled"] = _clampi(
        cfg.get("script_max_enabled"), 1, 50, d["script_max_enabled"])
    cfg["script_market_limit"] = _clampi(
        cfg.get("script_market_limit"), 0, 200, d["script_market_limit"])
    cfg["script_market_min_volume"] = _clampf(
        cfg.get("script_market_min_volume"), 0.0, 1e12,
        d["script_market_min_volume"])
    cfg["script_market_max_spread_cents"] = _clampf(
        cfg.get("script_market_max_spread_cents"), 0.0, 99.0,
        d["script_market_max_spread_cents"])
    cfg["copy_enabled"] = False
    cfg["copy_activity_ws"] = False
    cfg["crypto15m_rtds_ws"] = False
    return cfg


def merge_with_defaults(user: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_CONFIG)
    for k, v in (user or {}).items():
        if k in out:
            out[k] = v
            continue
        sk = _camel_to_snake(k)
        out[sk] = v
    return _validate_config(out)


def strategy_full_config(strategy_id: str) -> dict[str, Any] | None:
    for s in STRATEGY_PRESETS:
        if s["id"] == strategy_id:
            return merge_with_defaults(s["config"])
    return None
