import asyncio
import httpx
import pytest
import polymarket_api as api

@pytest.mark.parametrize('method',['POST','GET'])
@pytest.mark.parametrize('failure',['timeout','server'])
def test_transport_failure_is_surfaced_without_duplicate_request(monkeypatch,method,failure):
    calls=[]
    def handle(request):
        calls.append(request)
        if failure=='timeout':raise httpx.ReadTimeout('simulated timeout')
        return httpx.Response(503)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(api,'_client',client)
            with pytest.raises((httpx.ReadTimeout,api.PolymarketAPIError)):
                await api._request(method,'/v1/orders')
    asyncio.run(run())
    assert len(calls)==1
