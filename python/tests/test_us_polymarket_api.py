import base64
import json
import uuid
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import polymarket_auth as auth
import polymarket_api as api
import us_market_stream as stream

@pytest.fixture
def creds(tmp_path, monkeypatch):
    monkeypatch.setenv('ROM_POLYBOT_USERDATA',str(tmp_path))
    key=Ed25519PrivateKey.generate()
    kid=str(uuid.uuid4())
    secret=base64.b64encode(key.private_bytes_raw()).decode()
    auth.save_credentials(kid,secret)
    return key,kid,secret

def test_secret_encrypted_and_never_in_status(creds):
    key,kid,secret=creds
    assert secret.encode() not in auth._api_creds_file().read_bytes()
    assert secret not in json.dumps(auth.credentials_status_all())
    assert auth.get_api_creds()['keyId']==kid
    auth.clear_credentials()
    assert not auth.credentials_present()

def test_us_signature(creds):
    key,kid,_=creds
    h=auth.l2_headers('get','/v1/portfolio/positions?limit=100')
    key.public_key().verify(base64.b64decode(h['X-PM-Signature']),
        (h['X-PM-Timestamp']+'GET/v1/portfolio/positions').encode())
    assert h['X-PM-Access-Key']==kid

@pytest.mark.parametrize('kid,secret',[('0xabc','wallet'),(str(uuid.uuid4()),base64.b64encode(b'short').decode())])
def test_reject_wallet_credentials(kid,secret):
    with pytest.raises(ValueError):auth.save_credentials(kid,secret)

@pytest.mark.asyncio
async def test_readiness_never_places_order(creds,monkeypatch):
    calls=[]
    def handle(request):
        calls.append((request.method,request.url.path))
        assert request.url.host=='api.polymarket.us'
        return httpx.Response(200,json={'balances':[{'currency':'USD','buyingPower':12.34,'assetNotional':5}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(api,'_client',client)
        result=await api.check_trading_ready()
    assert result['balanceUsd']==12.34
    assert calls==[('GET','/v1/account/balances')]

@pytest.mark.asyncio
async def test_invalid_api_not_connected(creds,monkeypatch):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(401))) as client:
        monkeypatch.setattr(api,'_client',client)
        with pytest.raises(api.PolymarketAPIError):await api.ensure_api_creds()

@pytest.mark.asyncio
@pytest.mark.parametrize('side,action,expected',[('yes','buy','0.83'),('no','buy','0.17'),('yes','sell','0.83'),('no','sell','0.17')])
async def test_order_intent_and_yes_price(creds,monkeypatch,side,action,expected):
    calls=[]
    monkeypatch.setitem(api._meta,'example',{'min_size':1,'tick_size':.01})
    def handle(request):
        calls.append(request)
        body=json.loads(request.content)
        assert body['price']['value']==expected
        assert body['intent']=='ORDER_INTENT_'+action.upper()+('_LONG' if side=='yes' else '_SHORT')
        assert body['tif']=='TIME_IN_FORCE_FILL_OR_KILL'
        return httpx.Response(200,json={'id':'order-123'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(api,'_client',client)
        r=await api.place_limit_order(ticker='example',side=side,action=action,count=2,price_cents=83,order_type='FOK')
    assert r['order']['order_id']=='order-123'
    assert len(calls)==1

def test_order_reconciliation_uses_filled_average():
    p=api._normalize_order({'id':'o','quantity':10,'cumQuantity':3,'price':{'value':'.2'},
        'avgPx':{'value':'.18'},'intent':'ORDER_INTENT_BUY_SHORT','state':'ORDER_STATE_PARTIALLY_FILLED'})
    assert p['size_matched']==3
    assert p['price']==pytest.approx(.82)
    assert p['status']=='live'

@pytest.mark.asyncio
async def test_positions_follow_all_pages(creds,monkeypatch):
    def handle(request):
        second='cursor' in request.url.params
        return httpx.Response(200,json={'positions':{('b' if second else 'a'):{'netPositionDecimal':'-2','cost':{'value':'1.6'}}},
            'nextCursor':'' if second else 'next','eof':second})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(api,'_client',client)
        positions=await api.get_positions()
    assert [p['ticker'] for p in positions]==['a','b']
    assert positions[0]['position_fp']==-2

@pytest.mark.asyncio
async def test_no_quotes_complement_yes_book(monkeypatch):
    async def book(ticker):return {'bids':[{'px':{'value':'.61'},'qty':'2'}],'offers':[{'px':{'value':'.65'},'qty':'3'}]}
    monkeypatch.setattr(api,'_book',book)
    q=await api.get_quote('a','no')
    assert q['bid_cents']==35 and q['ask_cents']==39
    # Buying NO consumes the YES bid ladder, so its size comes from that side.
    assert q['ask_levels']==[[39,2.0]] and q['bid_levels']==[[35,3.0]]

@pytest.mark.asyncio
async def test_quote_reports_depth_in_improving_order(monkeypatch):
    async def book(ticker):return {'bids':[{'px':{'value':'.60'},'qty':'5'},{'px':{'value':'.58'},'qty':'9'}],
                                   'offers':[{'px':{'value':'.64'},'qty':'4'},{'px':{'value':'.62'},'qty':'7'}]}
    monkeypatch.setattr(api,'_book',book)
    q=await api.get_quote('a','yes')
    assert q['bid_cents']==60 and q['ask_cents']==62
    assert q['ask_levels']==[[62,7.0],[64,4.0]]
    assert q['bid_levels']==[[60,5.0],[58,9.0]]

@pytest.mark.asyncio
async def test_zero_size_levels_are_not_quotable(monkeypatch):
    async def book(ticker):return {'bids':[{'px':{'value':'.60'},'qty':'0'}],
                                   'offers':[{'px':{'value':'.62'},'qty':'0'}]}
    monkeypatch.setattr(api,'_book',book)
    q=await api.get_quote('a','yes')
    assert q['bid_cents'] is None and q['ask_cents'] is None
    assert q['ask_levels']==[] and q['bid_levels']==[]

def test_us_trade_stream_normalizes_taker():
    stream.ingest({'trade':{'marketSlug':'example','price':{'value':'.6'},'quantity':{'value':'50'},
        'tradeTime':'2026-09-08T00:00:00Z','taker':{'side':'ORDER_SIDE_SELL'}}})
    t=stream.recent(1)[0]
    assert t['taker_side']=='no' and t['count_fp']==50
    assert t['no_price_dollars']==.4
