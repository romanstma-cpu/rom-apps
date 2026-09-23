from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import db
import scanner
import polymarket_api as api


def test_us_market_without_reported_volume_is_kept_and_watched(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: tmp_path / 'polybot.db')
    db.init_db()
    watched = []

    async def markets(*_args, **_kwargs):
        return [{
            'ticker': 'us-market', 'slug': 'us-market', 'event_ticker': '',
            'title': 'US market', 'yes_sub_title': 'Yes', 'category': 'sports',
            'status': 'open', 'close_time': '2027-01-01T00:00:00Z',
            'volume_fp': 0, 'volume_24h_fp': 0, 'open_interest_fp': 0,
            'yes_bid_dollars': .49, 'yes_ask_dollars': .51, 'last_price_dollars': .5,
            'result': '', 'settlement_value_dollars': None,
        }]

    monkeypatch.setattr(api, 'fetch_all_open_markets', markets)
    import us_market_stream
    monkeypatch.setattr(us_market_stream, 'set_scanner_universe', lambda tickers: watched.extend(tickers))
    monkeypatch.setattr(us_market_stream, 'start', lambda: None)
    assert asyncio.run(scanner.sync_markets()) == 1
    with db.get_db() as conn:
        assert db.get_active_markets(conn, min_volume=0) [0]['ticker'] == 'us-market'
    assert watched == ['us-market']


def test_market_catalog_sync_does_not_start_private_stream_when_auth_is_down(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(db, 'db_path', lambda: tmp_path / 'polybot.db')
    db.init_db()

    async def markets(*_args, **_kwargs):
        return [{
            'ticker': 'public-market', 'slug': 'public-market',
            'event_ticker': '', 'title': 'Public market',
            'yes_sub_title': 'Yes', 'category': 'sports', 'status': 'open',
            'close_time': '2027-01-01T00:00:00Z', 'volume_fp': 0,
            'volume_24h_fp': 0, 'open_interest_fp': 0,
            'yes_bid_dollars': .49, 'yes_ask_dollars': .51,
            'last_price_dollars': .5, 'result': '',
            'settlement_value_dollars': None,
        }]

    monkeypatch.setattr(api, 'fetch_all_open_markets', markets)
    import us_market_stream
    monkeypatch.setattr(
        us_market_stream, 'start',
        lambda: (_ for _ in ()).throw(AssertionError('stream must stay stopped')),
    )
    assert asyncio.run(scanner.sync_markets(connect_stream=False)) == 1
    with db.get_db() as conn:
        assert db.get_active_markets(conn, min_volume=0)[0]['ticker'] == 'public-market'


def test_scanner_and_stream_share_ranked_nonexpired_market_universe(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: tmp_path / 'polybot.db')
    db.init_db()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

    async def markets(*_args, **_kwargs):
        def row(ticker, volume, close_time):
            return {'ticker': ticker, 'slug': ticker, 'status': 'open',
                    'close_time': close_time, 'volume_fp': volume,
                    'volume_24h_fp': volume, 'yes_bid_dollars': .4,
                    'yes_ask_dollars': .6, 'last_price_dollars': .5}
        return [row('quiet', 1, future), row('closed', 1000, past),
                row('busy', 100, future)]

    monkeypatch.setattr(api, 'fetch_all_open_markets', markets)
    import us_market_stream
    watched = []
    monkeypatch.setattr(us_market_stream, 'set_scanner_universe',
                        lambda tickers: watched.extend(tickers))
    monkeypatch.setattr(us_market_stream, 'start', lambda: None)
    assert asyncio.run(scanner.sync_markets()) == 2
    with db.get_db() as conn:
        assert [m['ticker'] for m in db.get_active_markets(conn)] == watched == ['busy', 'quiet']
