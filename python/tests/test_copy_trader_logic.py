"""Test pure logic functions in copy_trader.py not covered by integration tests."""
from __future__ import annotations

import pytest

import copy_trader
import db


# ====================================================================
# Fixtures
# ====================================================================


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """A fresh, isolated DB for each test."""
    dbfile = tmp_path / "test-copy-logic.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture
def cfg_fixed():
    """Fixed-size copy config."""
    return {
        "copy_sizing_mode": "fixed",
        "copy_fixed_usd": 10.0,
        "copy_balance_pct": 0.02,
    }


@pytest.fixture
def cfg_balance_pct():
    """Balance-percentage copy config."""
    return {
        "copy_sizing_mode": "balance_pct",
        "copy_fixed_usd": 10.0,
        "copy_balance_pct": 0.05,
    }


def _seed_pnl_copy(ticker="T-A", direction="yes", pnl=0.0, *, nid=1,
                   resolved=True, source="copy", resolved_at=None):
    """Insert a resolved copy/other position with the given PnL for PnL-sum tests."""
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, {
            "signal_source": source, "signal_id": nid,
            "ticker": ticker, "direction": direction,
            "target_contracts": 10, "limit_price_cents": 50,
            "filled_contracts": 10, "cost_usd": 50.0,
            "client_order_id": f"seed-{ticker}-{nid}", "status": "filled",
            "network": "mainnet",
        })
        # insert_bot_position does not write pnl_usd/resolved — set them explicitly.
        conn.execute(
            "UPDATE bot_positions SET pnl_usd=?, resolved=? WHERE id=?",
            (pnl, 1 if resolved else 0, pid),
        )
        if resolved_at is not None:
            conn.execute(
                "UPDATE bot_positions SET resolved_at=? WHERE id=?",
                (resolved_at, pid),
            )
        return pid


# ====================================================================
# _compute_copy_contracts
# ====================================================================


def test_compute_contracts_fixed_mode_normal(cfg_fixed):
    """Fixed mode at 50c with 10 USD budget yields 20 contracts."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=50, balance_usd=100.0
    )
    assert result == 20


def test_compute_contracts_fixed_mode_low_price(cfg_fixed):
    """Fixed mode at 10c with 10 USD budget yields 100 contracts (no float 99)."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=10, balance_usd=100.0
    )
    assert result == 100


def test_compute_contracts_fixed_mode_high_price(cfg_fixed):
    """Fixed mode at 95c with 10 USD budget yields 10 contracts."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=95, balance_usd=100.0
    )
    assert result == 10


def test_compute_contracts_balance_pct_mode(cfg_balance_pct):
    """Balance pct mode uses 5% of balance."""
    result = copy_trader._compute_copy_contracts(
        cfg_balance_pct, price_cents=50, balance_usd=200.0
    )
    # 5% of 200 = 10 USD, 10 / 0.50 = 20 contracts
    assert result == 20


def test_compute_contracts_balance_pct_zero_balance(cfg_balance_pct):
    """Balance pct mode with zero balance uses fixed fallback."""
    result = copy_trader._compute_copy_contracts(
        cfg_balance_pct, price_cents=50, balance_usd=0.0
    )
    # fallback to fixed 10 USD, 10 / 0.50 = 20 contracts
    assert result == 20


def test_compute_contracts_respects_98pct_cap(cfg_fixed):
    """Budget capped at 98% of available balance to avoid overdraft."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=50, balance_usd=10.0
    )
    # fixed 10 USD, but balance is only 10, so budget = 10 * 0.98 = 9.8
    # 9.8 / 0.50 = 19 contracts
    assert result == 19


def test_compute_contracts_respects_cap_usd(cfg_fixed):
    """Explicit cap_usd overrides configured budget."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=50, balance_usd=1000.0, cap_usd=5.0
    )
    # cap is 5 USD, price 0.50 => 10 contracts
    assert result == 10


def test_compute_contracts_negative_cap_usd(cfg_fixed):
    """Negative cap_usd yields zero contracts."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=50, balance_usd=1000.0, cap_usd=-1.0
    )
    assert result == 0


def test_compute_contracts_zero_cap_usd(cfg_fixed):
    """Zero cap_usd yields zero contracts."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=50, balance_usd=1000.0, cap_usd=0.0
    )
    assert result == 0


def test_compute_contracts_price_floor_at_1c(cfg_fixed):
    """Price is floored at 1c to prevent div-by-zero."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=0, balance_usd=100.0
    )
    # price = max(0.01, 0.0) = 0.01, budget 10 => 1000 contracts
    assert result == 1000


def test_compute_contracts_truncates_to_int(cfg_fixed):
    """Result is truncated to integer (no rounding up)."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=33, balance_usd=100.0
    )
    # 10 / 0.33 = 30.303... => 30 contracts
    assert result == 30


def test_compute_contracts_handles_none_balance_as_zero(cfg_fixed):
    """None balance treated as 0.0; fixed budget still applies (no balance cap)."""
    result = copy_trader._compute_copy_contracts(
        cfg_fixed, price_cents=50, balance_usd=None
    )
    assert result == 20


def test_compute_contracts_balance_pct_exceeds_100pct_clamp(cfg_balance_pct):
    """Balance pct config > 1.0 is clamped to 1.0."""
    cfg = dict(cfg_balance_pct)
    cfg["copy_balance_pct"] = 2.5
    result = copy_trader._compute_copy_contracts(
        cfg, price_cents=50, balance_usd=100.0
    )
    # pct clamped to 1.0 => 100 USD budget, but 98% cap => 98 USD
    # 98 / 0.50 = 196 contracts
    assert result == 196


def test_compute_contracts_balance_pct_negative_clamp(cfg_balance_pct):
    """Negative balance pct clamped to 0.0."""
    cfg = dict(cfg_balance_pct)
    cfg["copy_balance_pct"] = -0.1
    result = copy_trader._compute_copy_contracts(
        cfg, price_cents=50, balance_usd=100.0
    )
    # pct clamped to 0.0 => 0 USD budget => 0 contracts
    assert result == 0


# ====================================================================
# _lifetime_loss_tripped
# ====================================================================


def test_lifetime_loss_tripped_no_limit_returns_false(tmp_db):
    """No limit configured => not tripped."""
    cfg = {"copy_lifetime_loss_limit_usd": 0, "copy_lifetime_loss_limit_pct": 0}
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert not tripped
    assert msg == ""


def test_lifetime_loss_tripped_usd_limit_not_hit(tmp_db):
    """Lifetime loss below USD limit => not tripped."""
    cfg = {"copy_lifetime_loss_limit_usd": 100.0, "copy_lifetime_loss_limit_pct": 0}
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-50.0, nid=1)
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert not tripped


def test_lifetime_loss_tripped_usd_limit_exactly_hit(tmp_db):
    """Lifetime loss exactly equals USD limit => tripped."""
    cfg = {"copy_lifetime_loss_limit_usd": 50.0, "copy_lifetime_loss_limit_pct": 0}
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-50.0, nid=1)
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert tripped
    assert "lifetime loss limit reached" in msg
    assert "-50.00" in msg


def test_lifetime_loss_tripped_usd_limit_exceeded(tmp_db):
    """Lifetime loss exceeds USD limit => tripped."""
    cfg = {"copy_lifetime_loss_limit_usd": 30.0, "copy_lifetime_loss_limit_pct": 0}
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-50.0, nid=1)
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert tripped


def test_lifetime_loss_tripped_pct_limit_hit(tmp_db):
    """Lifetime loss >= pct * bankroll => tripped."""
    cfg = {
        "copy_lifetime_loss_limit_usd": 0,
        "copy_lifetime_loss_limit_pct": 0.25,
        "start_bankroll_usd": 200.0,
    }
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-50.0, nid=1)
    # cap = 200 * 0.25 = 50, loss = 50 => tripped
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert tripped
    assert "50.00" in msg


def test_lifetime_loss_tripped_pct_limit_not_hit(tmp_db):
    """Lifetime loss < pct * bankroll => not tripped."""
    cfg = {
        "copy_lifetime_loss_limit_usd": 0,
        "copy_lifetime_loss_limit_pct": 0.5,
        "start_bankroll_usd": 200.0,
    }
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-50.0, nid=1)
    # cap = 200 * 0.5 = 100, loss = 50 => not tripped
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert not tripped


def test_lifetime_loss_tripped_pct_limit_zero_bankroll(tmp_db):
    """Pct limit with zero bankroll => not tripped."""
    cfg = {
        "copy_lifetime_loss_limit_usd": 0,
        "copy_lifetime_loss_limit_pct": 0.25,
        "start_bankroll_usd": 0.0,
    }
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-50.0, nid=1)
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert not tripped


def test_lifetime_loss_tripped_pct_clamped_above_100(tmp_db):
    """Pct > 1.0 clamped to 1.0."""
    cfg = {
        "copy_lifetime_loss_limit_usd": 0,
        "copy_lifetime_loss_limit_pct": 2.5,
        "start_bankroll_usd": 100.0,
    }
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=-101.0, nid=1)
    # pct clamped to 1.0 => cap = 100, loss = 101 => tripped
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert tripped


def test_lifetime_loss_tripped_profit_never_trips(tmp_db):
    """Positive PnL never trips the loss limit."""
    cfg = {"copy_lifetime_loss_limit_usd": 10.0, "copy_lifetime_loss_limit_pct": 0}
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=100.0, nid=1)
    tripped, msg = copy_trader._lifetime_loss_tripped(cfg, "mainnet")
    assert not tripped


# ====================================================================
# _today_copy_pnl
# ====================================================================


def test_today_copy_pnl_empty_db(tmp_db):
    """Empty DB => zero PnL."""
    result = copy_trader._today_copy_pnl("mainnet")
    assert result == 0.0


def test_today_copy_pnl_sums_resolved_today(tmp_db):
    """Today's resolved copy positions are summed."""
    pid = _seed_pnl_copy(ticker="T-A", direction="yes", pnl=25.0, nid=1)
    with db.get_db() as conn:
        conn.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))
    pid2 = _seed_pnl_copy(ticker="T-B", direction="no", pnl=-15.0, nid=2)
    with db.get_db() as conn:
        conn.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid2,))

    result = copy_trader._today_copy_pnl("mainnet")
    assert result == pytest.approx(10.0)


def test_today_copy_pnl_ignores_unresolved(tmp_db):
    """Unresolved positions not counted."""
    with db.get_db() as conn:
        _seed_pnl_copy(ticker="T-A", direction="yes", pnl=100.0, nid=1, resolved=False)

    result = copy_trader._today_copy_pnl("mainnet")
    assert result == 0.0


def test_today_copy_pnl_ignores_other_engines(tmp_db):
    """Non-copy positions ignored."""
    with db.get_db() as conn:
        pid = _seed_pnl_copy(ticker="T-A", direction="yes", pnl=50.0, nid=1, source="whale")
        conn.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))

    result = copy_trader._today_copy_pnl("mainnet")
    assert result == 0.0


# ====================================================================
# _filter_new_entries dedup rules
# ====================================================================


def test_filter_new_entries_baselines_first_see(tmp_db):
    """First time seeing a wallet's position => baseline, not eligible."""
    followed = {
        ("T-A", "yes"): {
            "ticker": "T-A", "side": "yes",
            "wallets": ["0xAAA"],
        },
    }
    cfg = {"copy_wallets": ["0xAAA"]}
    
    result = copy_trader._filter_new_entries(followed, "mainnet", cfg)
    assert result == {}
    
    # Verify seen was saved
    seen = copy_trader._load_seen("mainnet")
    assert "0xAAA|T-A|yes" in seen


def test_filter_new_entries_detects_new_entry_after_baseline(tmp_db):
    """Second position on same wallet => eligible."""
    cfg = {"copy_wallets": ["0xAAA"]}
    
    # First call: baseline T-A
    followed1 = {
        ("T-A", "yes"): {
            "ticker": "T-A", "side": "yes",
            "wallets": ["0xAAA"],
        },
    }
    copy_trader._filter_new_entries(followed1, "mainnet", cfg)
    
    # Second call: adds T-B
    followed2 = {
        ("T-A", "yes"): {
            "ticker": "T-A", "side": "yes",
            "wallets": ["0xAAA"],
        },
        ("T-B", "no"): {
            "ticker": "T-B", "side": "no",
            "wallets": ["0xAAA"],
        },
    }
    result = copy_trader._filter_new_entries(followed2, "mainnet", cfg)
    
    assert ("T-B", "no") in result
    assert ("T-A", "yes") not in result


def test_filter_new_entries_dedup_across_wallets(tmp_db):
    """Multiple wallets holding same ticker => new wallet baselines, not eligible."""
    cfg = {"copy_wallets": ["0xAAA", "0xBBB"]}

    # Wallet A holds T-A
    followed1 = {
        ("T-A", "yes"): {
            "ticker": "T-A", "side": "yes",
            "wallets": ["0xAAA"],
        },
    }
    copy_trader._filter_new_entries(followed1, "mainnet", cfg)

    # Now both wallets hold T-A
    followed2 = {
        ("T-A", "yes"): {
            "ticker": "T-A", "side": "yes",
            "wallets": ["0xAAA", "0xBBB"],
        },
    }
    result = copy_trader._filter_new_entries(followed2, "mainnet", cfg)

    # Wallet B was never followed before => added to seen as baseline, NOT eligible
    assert ("T-A", "yes") not in result
    seen = copy_trader._load_seen("mainnet")
    assert "0xBBB|T-A|yes" in seen


def test_filter_new_entries_prunes_stale_wallets(tmp_db):
    """Wallets removed from config => their seen keys pruned."""
    cfg1 = {"copy_wallets": ["0xAAA", "0xBBB"]}
    
    followed1 = {
        ("T-A", "yes"): {"ticker": "T-A", "side": "yes", "wallets": ["0xAAA"]},
        ("T-B", "no"): {"ticker": "T-B", "side": "no", "wallets": ["0xBBB"]},
    }
    copy_trader._filter_new_entries(followed1, "mainnet", cfg1)
    
    seen = copy_trader._load_seen("mainnet")
    assert "0xAAA|T-A|yes" in seen
    assert "0xBBB|T-B|no" in seen
    
    # Remove wallet B from config
    cfg2 = {"copy_wallets": ["0xAAA"]}
    copy_trader._filter_new_entries({}, "mainnet", cfg2)
    
    seen = copy_trader._load_seen("mainnet")
    assert "0xAAA|T-A|yes" in seen
    assert "0xBBB|T-B|no" not in seen


def test_filter_new_entries_respects_5k_cap(tmp_db):
    """Seen dict capped at 5000 keys."""
    cfg = {"copy_wallets": ["0xAAA"]}
    
    # Seed seen with 5010 entries
    seen_dict = {f"0xAAA|T-{i}|yes": None for i in range(5010)}
    copy_trader._save_seen("mainnet", seen_dict)
    
    # Filter with empty followed => prune
    copy_trader._filter_new_entries({}, "mainnet", cfg)
    
    seen = copy_trader._load_seen("mainnet")
    assert len(seen) == 5000


def test_filter_new_entries_distinguishes_yes_no(tmp_db):
    """Same ticker, different side => separate seen keys."""
    cfg = {"copy_wallets": ["0xAAA"]}
    
    followed1 = {
        ("T-A", "yes"): {"ticker": "T-A", "side": "yes", "wallets": ["0xAAA"]},
    }
    copy_trader._filter_new_entries(followed1, "mainnet", cfg)
    
    followed2 = {
        ("T-A", "yes"): {"ticker": "T-A", "side": "yes", "wallets": ["0xAAA"]},
        ("T-A", "no"): {"ticker": "T-A", "side": "no", "wallets": ["0xAAA"]},
    }
    result = copy_trader._filter_new_entries(followed2, "mainnet", cfg)
    
    assert ("T-A", "no") in result
    assert ("T-A", "yes") not in result


# ====================================================================
# _seen_key, _load_seen, _save_seen persistence roundtrip
# ====================================================================


def test_seen_key_format():
    """Seen key includes env."""
    key = copy_trader._seen_key("mainnet")
    assert key == "copy_seen:mainnet"
    
    key2 = copy_trader._seen_key("testnet")
    assert key2 == "copy_seen:testnet"


def test_seen_roundtrip_empty(tmp_db):
    """Save and load empty seen dict."""
    copy_trader._save_seen("mainnet", {})
    result = copy_trader._load_seen("mainnet")
    assert result == {}


def test_seen_roundtrip_single_entry(tmp_db):
    """Save and load single seen key."""
    copy_trader._save_seen("mainnet", {"0xAAA|T-A|yes": None})
    result = copy_trader._load_seen("mainnet")
    assert "0xAAA|T-A|yes" in result


def test_seen_roundtrip_multiple_entries(tmp_db):
    """Save and load multiple seen keys."""
    seen = {
        "0xAAA|T-A|yes": None,
        "0xBBB|T-B|no": None,
        "0xCCC|T-C|yes": None,
    }
    copy_trader._save_seen("mainnet", seen)
    result = copy_trader._load_seen("mainnet")
    
    assert len(result) == 3
    assert all(k in result for k in seen)


def test_seen_roundtrip_overwrites_previous(tmp_db):
    """Second save replaces first."""
    copy_trader._save_seen("mainnet", {"0xAAA|T-A|yes": None})
    copy_trader._save_seen("mainnet", {"0xBBB|T-B|no": None})
    
    result = copy_trader._load_seen("mainnet")
    assert "0xBBB|T-B|no" in result
    assert "0xAAA|T-A|yes" not in result


def test_seen_roundtrip_env_isolation(tmp_db):
    """Different envs have separate seen stores."""
    copy_trader._save_seen("mainnet", {"0xAAA|T-A|yes": None})
    copy_trader._save_seen("testnet", {"0xBBB|T-B|no": None})
    
    main = copy_trader._load_seen("mainnet")
    test = copy_trader._load_seen("testnet")
    
    assert "0xAAA|T-A|yes" in main
    assert "0xAAA|T-A|yes" not in test
    assert "0xBBB|T-B|no" in test
    assert "0xBBB|T-B|no" not in main


def test_load_seen_missing_returns_empty(tmp_db):
    """Load before any save => empty dict."""
    result = copy_trader._load_seen("mainnet")
    assert result == {}


def test_load_seen_corrupt_json_returns_empty(tmp_db):
    """Corrupt JSON in DB => empty dict, no crash."""
    with db.get_db() as conn:
        db.kv_set(conn, "copy_seen:mainnet", "{this is not json")
    
    result = copy_trader._load_seen("mainnet")
    assert result == {}


def test_save_seen_handles_exception_gracefully(tmp_db, monkeypatch):
    """Exception during save => no crash (swallowed)."""
    def _bad_kv_set(conn, key, val):
        raise RuntimeError("DB write failed")
    
    monkeypatch.setattr(db, "kv_set", _bad_kv_set)
    
    # Should not raise
    copy_trader._save_seen("mainnet", {"0xAAA|T-A|yes": None})


# ====================================================================
# _bankroll_usd fallback behavior
# ====================================================================


@pytest.mark.asyncio
async def test_bankroll_usd_authed_uses_trader_refresh(monkeypatch):
    """Authed with good balance => return cents / 100."""
    
    async def _refresh(cfg, force):
        return (12345, [])  # cents, portfolio
    
    monkeypatch.setattr(copy_trader.trader, "refresh_balance", _refresh)
    monkeypatch.setattr(copy_trader.trader, "last_balance_read_ok", lambda: True)
    
    cfg = {"start_bankroll_usd": 500.0}
    result = await copy_trader._bankroll_usd(cfg, authed=True)
    
    assert result == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_bankroll_usd_authed_zero_balance_returns_zero(monkeypatch):
    """Authed with zero cents => return 0.0."""
    
    async def _refresh(cfg, force):
        return (0, [])
    
    monkeypatch.setattr(copy_trader.trader, "refresh_balance", _refresh)
    monkeypatch.setattr(copy_trader.trader, "last_balance_read_ok", lambda: True)
    
    cfg = {"start_bankroll_usd": 500.0}
    result = await copy_trader._bankroll_usd(cfg, authed=True)
    
    assert result == 0.0


@pytest.mark.asyncio
async def test_bankroll_usd_authed_exception_falls_back_to_config(monkeypatch):
    """Authed but refresh raises => fallback to start_bankroll_usd."""
    
    async def _refresh(cfg, force):
        raise RuntimeError("balance API down")
    
    monkeypatch.setattr(copy_trader.trader, "refresh_balance", _refresh)
    
    cfg = {"start_bankroll_usd": 500.0}
    result = await copy_trader._bankroll_usd(cfg, authed=True)
    
    assert result == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_bankroll_usd_not_authed_uses_config(monkeypatch):
    """Not authed => return configured start_bankroll_usd."""
    cfg = {"start_bankroll_usd": 250.0}
    result = await copy_trader._bankroll_usd(cfg, authed=False)
    
    assert result == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_bankroll_usd_missing_config_returns_zero(monkeypatch):
    """Missing start_bankroll_usd => 0.0."""
    cfg = {}
    result = await copy_trader._bankroll_usd(cfg, authed=False)
    
    assert result == 0.0


@pytest.mark.asyncio
async def test_bankroll_usd_negative_config_returns_zero(monkeypatch):
    """Negative start_bankroll_usd => 0.0."""
    cfg = {"start_bankroll_usd": -100.0}
    result = await copy_trader._bankroll_usd(cfg, authed=False)
    
    assert result == 0.0


@pytest.mark.asyncio
async def test_bankroll_usd_none_config_returns_zero(monkeypatch):
    """None start_bankroll_usd => 0.0."""
    cfg = {"start_bankroll_usd": None}
    result = await copy_trader._bankroll_usd(cfg, authed=False)
    
    assert result == 0.0
