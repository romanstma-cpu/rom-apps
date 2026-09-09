from __future__ import annotations

import asyncio
import json

import pytest

import polymarket_api as api


def test_normalize_market_parses_gamma_json_strings():
    raw = {
        "conditionId": "0xabc",
        "question": "Will X happen?",
        "slug": "will-x-happen",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "clobTokenIds": json.dumps(["111", "222"]),
        "volumeNum": 1234.5,
        "volume24hr": 50.0,
        "liquidityNum": 999.0,
        "negRisk": False,
        "orderPriceMinTickSize": 0.01,
        "active": True,
        "closed": False,
        "endDate": "2026-07-01T00:00:00Z",
        "events": [{"slug": "evt-x", "tags": [{"slug": "crypto"}]}],
    }
    m = api._normalize_market(raw)
    assert m["ticker"] == "0xabc"
    assert m["yes_token"] == "111" and m["no_token"] == "222"
    assert m["yes_bid_dollars"] == 0.62 and m["no_price_dollars"] == 0.38
    assert m["category"] == "crypto"
    assert m["event_ticker"] == "evt-x"
    assert m["volume_fp"] == 1234.5
    assert m["status"] == "open"
    meta = api._meta["0xabc"]
    assert meta["yes_token"] == "111" and meta["neg_risk"] is False


def test_normalize_market_resolution_yes_wins():
    raw = {
        "conditionId": "0xdef",
        "question": "q", "slug": "s",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["1", "0"]),
        "clobTokenIds": json.dumps(["1", "2"]),
        "closed": True,
        "umaResolutionStatus": "resolved",
    }
    m = api._normalize_market(raw)
    assert m["result"] == "yes"
    assert m["settlement_value_dollars"] == 1.0
    assert m["status"] == "settled"


def test_normalize_market_missing_condition_id_is_none():
    assert api._normalize_market({"question": "no id"}) is None
    assert api._normalize_market(None) is None


def test_fee_schedule_passthrough_from_gamma():
    base = {
        "conditionId": "0xfee", "question": "q", "slug": "s",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.5", "0.5"]),
        "clobTokenIds": json.dumps(["1", "2"]),
    }
    m = api._normalize_market({
        **base,
        "feesEnabled": True,
        "feeSchedule": {"rate": 0.07, "exponent": 1, "takerOnly": True},
    })
    assert m["fee_schedule"] == {"enabled": True, "rate": 0.07, "exponent": 1.0}
    m2 = api._normalize_market({**base, "feesEnabled": False})
    assert m2["fee_schedule"] == {"enabled": False}
    m3 = api._normalize_market(base)
    assert m3["fee_schedule"] is None


def test_refresh_balance_allowance_once_per_session(monkeypatch):
    calls = []

    async def _authed(method, path, **kw):
        calls.append((method, path, kw.get("params")))
        return {}

    monkeypatch.setattr(api, "_authed_request", _authed)
    monkeypatch.setattr(api.auth, "get_signature_type", lambda env=None: 0)
    monkeypatch.setattr(api, "_allowance_synced", False)

    assert asyncio.run(api.refresh_balance_allowance()) is True
    assert calls == [("GET", "/balance-allowance/update",
                      {"asset_type": "COLLATERAL", "signature_type": "0"})]
    assert asyncio.run(api.refresh_balance_allowance()) is True
    assert len(calls) == 1
    assert asyncio.run(api.refresh_balance_allowance(force=True)) is True
    assert len(calls) == 2


def test_refresh_balance_allowance_failure_is_nonfatal(monkeypatch):
    async def _authed(method, path, **kw):
        raise api.PolymarketAPIError(500, "boom")

    monkeypatch.setattr(api, "_authed_request", _authed)
    monkeypatch.setattr(api.auth, "get_signature_type", lambda env=None: 0)
    monkeypatch.setattr(api, "_allowance_synced", False)
    assert asyncio.run(api.refresh_balance_allowance()) is False
    assert api._allowance_synced is False


def test_fetch_recent_trades_buy_yes(monkeypatch):
    async def _get(url, params=None):
        return [{
            "price": 0.30, "size": 100, "outcomeIndex": 0, "side": "BUY",
            "conditionId": "0xc", "transactionHash": "0xtx", "asset": "tok",
            "slug": "m", "title": "t", "outcome": "Yes", "eventSlug": "e",
            "timestamp": 1782000000,
        }]
    monkeypatch.setattr(api, "_get", _get)
    rows = asyncio.run(api.fetch_recent_trades(limit=10))
    r = rows[0]
    assert r["taker_side"] == "yes"
    assert r["yes_price_dollars"] == 0.30
    assert r["count_fp"] == 100
    assert r["ticker"] == "0xc"


def test_fetch_recent_trades_sell_is_long_opposite(monkeypatch):
    async def _get(url, params=None):
        return [{
            "price": 0.30, "size": 50, "outcomeIndex": 0, "side": "SELL",
            "conditionId": "0xc", "transactionHash": "0xtx2", "asset": "tok",
            "slug": "m", "title": "t", "outcome": "Yes",
        }]
    monkeypatch.setattr(api, "_get", _get)
    r = asyncio.run(api.fetch_recent_trades(limit=10))[0]
    assert r["taker_side"] == "no"
    assert r["no_price_dollars"] == 0.70


def test_snap_price_to_tick():
    assert api._snap_price_to_tick(0.376, 0.01) == 0.38
    assert api._snap_price_to_tick(0.37, 0.1) == 0.4
    assert api._snap_price_to_tick(0.6234, 0.001) == 0.623
    assert api._snap_price_to_tick(0.97, 0.1) == 0.9
    assert api._snap_price_to_tick(0.02, 0.1) == 0.1


def test_get_quote_reads_clob_prices(monkeypatch):
    async def _meta(_t):
        return {"yes_token": "111", "no_token": "222"}

    async def _price(_token, side):
        return 0.58 if side == "BUY" else 0.62

    monkeypatch.setattr(api, "get_market_meta", _meta)
    monkeypatch.setattr(api, "_clob_price", _price)
    q = asyncio.run(api.get_quote("0xc", "yes"))
    assert q == {"bid_cents": 58, "ask_cents": 62}


_TOK = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
_ADDR = "0x7a4043DE8fa7C458eD701Ebe487E7203eeF72197"


def test_balance_read_returns_first_valid_despite_dead_rpcs(monkeypatch):
    good = api.POLYGON_RPCS[3]

    class _R:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    class _Client:
        async def post(self, url, json=None, timeout=None):
            if url == good:
                return _R({"result": hex(1_000_000)})
            raise RuntimeError("rpc down")

    async def _fake_client():
        return _Client()
    monkeypatch.setattr(api, "_get_client", _fake_client)
    assert asyncio.run(api._erc20_balance_usd(_TOK, _ADDR)) == 1.0


def test_balance_read_all_fail_returns_none(monkeypatch):
    class _Client:
        async def post(self, url, json=None, timeout=None):
            raise RuntimeError("rpc down")

    async def _fake_client():
        return _Client()
    monkeypatch.setattr(api, "_get_client", _fake_client)
    assert asyncio.run(api._erc20_balance_usd(_TOK, _ADDR)) is None


def test_balance_read_rejects_bad_address():
    assert asyncio.run(api._erc20_balance_usd(_TOK, "not-an-address")) is None


def test_net_fail_streak_recycles_client(monkeypatch):
    recycled = {"n": 0}

    async def _fake_recycle():
        recycled["n"] += 1

    monkeypatch.setattr(api, "_recycle_client", _fake_recycle)
    monkeypatch.setattr(api, "_net_fail_streak", 0)
    monkeypatch.setattr(api, "_last_client_recycle", 0.0)
    monkeypatch.setattr(api, "_last_net_ok", 0.0)
    monkeypatch.setattr(api.time, "monotonic", lambda: 10_000.0)

    async def _run():
        for _ in range(api._NET_FAIL_RECYCLE - 1):
            await api._note_net_fail()
        assert recycled["n"] == 0
        await api._note_net_fail()
        assert recycled["n"] == 1

    asyncio.run(_run())


def test_net_ok_resets_streak_so_one_bad_endpoint_never_recycles(monkeypatch):
    recycled = {"n": 0}

    async def _fake_recycle():
        recycled["n"] += 1

    monkeypatch.setattr(api, "_recycle_client", _fake_recycle)
    monkeypatch.setattr(api, "_net_fail_streak", 0)
    monkeypatch.setattr(api, "_last_client_recycle", 0.0)
    monkeypatch.setattr(api, "_last_net_ok", 0.0)
    monkeypatch.setattr(api.time, "monotonic", lambda: 10_000.0)

    async def _run():
        for _ in range(api._NET_FAIL_RECYCLE * 3):
            await api._note_net_fail()
            api._note_net_ok()
        assert recycled["n"] == 0

    asyncio.run(_run())


def test_recycle_throttled_within_gap(monkeypatch):
    recycled = {"n": 0}

    async def _fake_recycle():
        recycled["n"] += 1

    clock = {"t": 10_000.0}
    monkeypatch.setattr(api, "_recycle_client", _fake_recycle)
    monkeypatch.setattr(api, "_net_fail_streak", 0)
    monkeypatch.setattr(api, "_last_client_recycle", 0.0)
    monkeypatch.setattr(api, "_last_net_ok", 0.0)
    monkeypatch.setattr(api.time, "monotonic", lambda: clock["t"])

    async def _run():
        for _ in range(api._NET_FAIL_RECYCLE):
            await api._note_net_fail()
        assert recycled["n"] == 1
        for _ in range(api._NET_FAIL_RECYCLE):
            await api._note_net_fail()
        assert recycled["n"] == 1
        clock["t"] += api._CLIENT_RECYCLE_MIN_GAP + 1
        for _ in range(api._NET_FAIL_RECYCLE):
            await api._note_net_fail()
        assert recycled["n"] == 2

    asyncio.run(_run())


def test_recent_success_blocks_recycle(monkeypatch):
    recycled = {"n": 0}

    async def _fake_recycle():
        recycled["n"] += 1

    clock = {"t": 10_000.0}
    monkeypatch.setattr(api, "_recycle_client", _fake_recycle)
    monkeypatch.setattr(api, "_net_fail_streak", 0)
    monkeypatch.setattr(api, "_last_client_recycle", 0.0)
    monkeypatch.setattr(api.time, "monotonic", lambda: clock["t"])

    async def _run():
        api._note_net_ok()
        for _ in range(api._NET_FAIL_RECYCLE * 2):
            await api._note_net_fail()
        assert recycled["n"] == 0
        clock["t"] += api._NET_STALL_SECS + 1
        for _ in range(api._NET_FAIL_RECYCLE):
            await api._note_net_fail()
        assert recycled["n"] == 1

    asyncio.run(_run())


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


def _wire_authed(monkeypatch, responses, state):
    class _Client:
        async def request(self, *a, **k):
            r = responses[state["i"]]
            state["i"] += 1
            return r

    async def _noop_ensure():
        return None

    async def _fake_client():
        return _Client()

    monkeypatch.setattr(api, "ensure_api_creds", _noop_ensure)
    monkeypatch.setattr(api, "_get_client", _fake_client)
    monkeypatch.setattr(api.auth, "l2_headers", lambda *a, **k: {})
    monkeypatch.setattr(api.auth, "clear_api_creds",
                        lambda env=None: state.__setitem__("cleared", state["cleared"] + 1))


def test_is_stale_creds_error():
    assert api._is_stale_creds_error(
        {"error": "the order signer address has to be the address of the api key"})
    assert api._is_stale_creds_error("Unauthorized")
    assert not api._is_stale_creds_error({"error": "min tick size violation"})


def test_authed_request_self_heals_stale_creds(monkeypatch):
    state = {"i": 0, "cleared": 0}
    _wire_authed(monkeypatch, [
        _Resp(400, {"error": "the order signer address has to be the address of the api key"}),
        _Resp(200, {"ok": True}),
    ], state)
    out = asyncio.run(api._authed_request("POST", "/order", json_body={"x": 1}))
    assert out == {"ok": True}
    assert state["i"] == 2 and state["cleared"] == 1


def test_authed_request_non_auth_400_does_not_rederive(monkeypatch):
    state = {"i": 0, "cleared": 0}
    _wire_authed(monkeypatch, [_Resp(400, {"error": "min tick size violation"})], state)
    with pytest.raises(api.PolymarketAPIError):
        asyncio.run(api._authed_request("POST", "/order", json_body={"x": 1}))
    assert state["cleared"] == 0


def _stub_order_path(monkeypatch, captured):
    async def _meta(_t):
        return {"yes_token": "111", "no_token": "222",
                "tick_size": 0.01, "min_size": 5, "neg_risk": False}

    async def _ensure():
        return None

    async def _authed(method, path, *, json_body=None, idempotent=True, **_kw):
        captured["body"] = json_body
        return {"orderID": "oid-1", "status": "matched", "success": True}

    monkeypatch.setattr(api, "get_market_meta", _meta)
    monkeypatch.setattr(api, "ensure_api_creds", _ensure)
    monkeypatch.setattr(api.auth, "get_api_creds", lambda: {"apiKey": "ak"})
    monkeypatch.setattr(api.auth, "create_signed_order",
                        lambda **kw: {"salt": "1", "maker": "0x", "signature": "0x"})
    monkeypatch.setattr(api.auth, "get_funder", lambda: "0xDeposit")
    monkeypatch.setattr(api.auth, "get_address", lambda: "0xEOAsigner")
    monkeypatch.setattr(api, "_authed_request", _authed)


def test_place_limit_order_defaults_to_gtc(monkeypatch):
    cap = {}
    _stub_order_path(monkeypatch, cap)
    asyncio.run(api.place_limit_order(
        ticker="T", side="yes", action="buy", count=5, price_cents=90))
    assert cap["body"]["orderType"] == "GTC"
    assert cap["body"]["postOnly"] is False
    assert cap["body"]["deferExec"] is False


def test_place_limit_order_marketable_fak(monkeypatch):
    cap = {}
    _stub_order_path(monkeypatch, cap)
    asyncio.run(api.place_limit_order(
        ticker="T", side="yes", action="buy", count=5, price_cents=90, order_type="fak"))
    assert cap["body"]["orderType"] == "FAK"
    assert cap["body"]["postOnly"] is False


def test_place_limit_order_rejects_unknown_order_type(monkeypatch):
    _stub_order_path(monkeypatch, {})
    with pytest.raises(ValueError):
        asyncio.run(api.place_limit_order(
            ticker="T", side="yes", action="buy", count=5, price_cents=90,
            order_type="BOGUS"))


def test_is_no_match_error():
    assert api._is_no_match_error("no orders found to match with FAK order")
    assert not api._is_no_match_error("not enough balance / allowance")
    assert not api._is_no_match_error("")


def test_is_maker_not_allowed_error():
    assert api._is_maker_not_allowed_error(
        {"error": "maker address not allowed, please use the deposit wallet flow"})
    assert not api._is_maker_not_allowed_error("Invalid Order payload")
    assert not api._is_maker_not_allowed_error("")


def test_place_limit_order_refuses_eoa_maker(monkeypatch):
    cap = {}
    _stub_order_path(monkeypatch, cap)
    monkeypatch.setattr(api.auth, "get_funder", lambda: "")

    with pytest.raises(api.PolymarketAPIError) as ei:
        asyncio.run(api.place_limit_order(
            ticker="T", side="yes", action="buy", count=5, price_cents=90))
    assert ei.value.body == api._NO_DEPOSIT_WALLET_HELP
    assert "body" not in cap


def test_place_limit_order_refuses_funder_equal_to_signer(monkeypatch):
    cap = {}
    _stub_order_path(monkeypatch, cap)
    monkeypatch.setattr(api.auth, "get_funder", lambda: "0xeoasigner")

    with pytest.raises(api.PolymarketAPIError):
        asyncio.run(api.place_limit_order(
            ticker="T", side="yes", action="buy", count=5, price_cents=90))
    assert "body" not in cap


def test_fak_no_liquidity_is_clean_unmatched_not_error(monkeypatch):
    _stub_order_path(monkeypatch, {})

    async def _authed_400(method, path, *, json_body=None, idempotent=True, **_kw):
        raise api.PolymarketAPIError(400, "no orders found to match with FAK order")
    monkeypatch.setattr(api, "_authed_request", _authed_400)

    res = asyncio.run(api.place_limit_order(
        ticker="T", side="yes", action="buy", count=5, price_cents=90, order_type="FAK"))
    assert res["order"]["order_id"] == "" and res["order"]["status"] == "unmatched"

    with pytest.raises(api.PolymarketAPIError):
        asyncio.run(api.place_limit_order(
            ticker="T", side="yes", action="buy", count=5, price_cents=90, order_type="GTC"))


def _wire_signer_probe(monkeypatch, *, sig_type=3, place=None):
    monkeypatch.setattr(api, "_signer_check_cache", {})
    monkeypatch.setattr(api.auth, "get_signature_type", lambda: sig_type)
    monkeypatch.setattr(api.auth, "get_address", lambda: "0xEOAsigner")
    monkeypatch.setattr(api.auth, "get_funder", lambda: "0xDepositWallet")

    async def _markets(limit=50):
        return [{"ticker": "0xc", "yes_token": "111", "status": "open",
                 "yes_bid_dollars": 0.55}], ""

    async def _meta(_t):
        return {"yes_token": "111", "no_token": "222", "tick_size": 0.01, "min_size": 5}

    monkeypatch.setattr(api, "fetch_markets", _markets)
    monkeypatch.setattr(api, "get_market_meta", _meta)
    if place is not None:
        monkeypatch.setattr(api, "place_limit_order", place)


def test_signer_probe_raw_eoa_fails_offline(monkeypatch):
    calls = {"n": 0}

    async def _place(**k):
        calls["n"] += 1
        return {"order": {"order_id": "", "status": "unmatched"}}
    _wire_signer_probe(monkeypatch, sig_type=0, place=_place)
    out = asyncio.run(api.verify_order_signer_live())
    assert out["ok"] is False and out["tested"] is True
    assert out["reason"] == api._NO_DEPOSIT_WALLET_HELP
    assert calls["n"] == 0


def test_signer_probe_detects_mismatch_and_caches(monkeypatch):
    calls = {"n": 0}

    async def _place(**k):
        calls["n"] += 1
        raise api.PolymarketAPIError(400, api._SIGNER_MISMATCH_HELP)
    _wire_signer_probe(monkeypatch, sig_type=3, place=_place)
    out = asyncio.run(api.verify_order_signer_live())
    assert out["ok"] is False and out["tested"] is True
    assert out["reason"] == api._SIGNER_MISMATCH_HELP
    out2 = asyncio.run(api.verify_order_signer_live())
    assert out2["ok"] is False
    assert calls["n"] == 1


def test_signer_probe_passes_when_order_accepted(monkeypatch):
    captured = {}

    async def _place(**k):
        captured.update(k)
        return {"order": {"order_id": "", "status": "unmatched"}}
    _wire_signer_probe(monkeypatch, sig_type=3, place=_place)
    out = asyncio.run(api.verify_order_signer_live())
    assert out["ok"] is True and out["tested"] is True and out["reason"] == "signer verified"
    assert captured["price_cents"] == 1 and captured["order_type"] == "FAK"
    assert captured["action"] == "buy" and captured["count"] >= 110


def test_signer_probe_inconclusive_not_cached(monkeypatch):
    calls = {"n": 0}

    async def _place(**k):
        calls["n"] += 1
        raise api.PolymarketAPIError(400, "not enough balance / allowance")
    _wire_signer_probe(monkeypatch, sig_type=3, place=_place)
    out = asyncio.run(api.verify_order_signer_live())
    assert out["ok"] is True and out["tested"] is False
    asyncio.run(api.verify_order_signer_live())
    assert calls["n"] == 2


def test_unmatched_fak_reports_no_order_id(monkeypatch):
    cap = {}
    _stub_order_path(monkeypatch, cap)

    async def _authed_unmatched(method, path, *, json_body=None, idempotent=True, **_kw):
        return {"orderID": "oid-killed", "status": "unmatched", "success": True}
    monkeypatch.setattr(api, "_authed_request", _authed_unmatched)

    res = asyncio.run(api.place_limit_order(
        ticker="T", side="yes", action="buy", count=5, price_cents=90, order_type="FAK"))
    assert res["order"]["order_id"] == ""
    res2 = asyncio.run(api.place_limit_order(
        ticker="T", side="yes", action="buy", count=5, price_cents=90, order_type="GTC"))
    assert res2["order"]["order_id"] == "oid-killed"
