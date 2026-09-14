from execution_quality import market_quality_multiplier


def quote(*, bid=49, ask=50, levels=None):
    return {"bid_cents": bid, "ask_cents": ask,
            "ask_levels": levels if levels is not None else [[50, 100]]}


def test_clean_taker_book_keeps_full_size():
    multiplier, reason = market_quality_multiplier(
        quote(), signal_cents=50, limit_cents=50, contracts=10,
        fee_cents=.25, maker_only=False,
    )
    assert multiplier == 0.99
    assert "spread 1c" in reason


def test_marginal_book_reduces_size_but_never_blocks_entry():
    clean, _ = market_quality_multiplier(
        quote(), signal_cents=50, limit_cents=50, contracts=10,
        fee_cents=.25, maker_only=False,
    )
    marginal, reason = market_quality_multiplier(
        quote(bid=47, ask=50, levels=[[50, 5]]), signal_cents=48,
        limit_cents=50, contracts=10, fee_cents=1.5, maker_only=False,
    )
    assert .5 <= marginal < clean
    assert "displayed depth 5/10" in reason


def test_maker_route_does_not_invent_taker_depth_penalty():
    multiplier, reason = market_quality_multiplier(
        quote(bid=48, ask=50, levels=[]), signal_cents=49, limit_cents=49,
        contracts=10, fee_cents=0, maker_only=True,
    )
    assert multiplier == .9
    assert "maker route" in reason
