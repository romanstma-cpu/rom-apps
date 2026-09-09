"""Private US updates augment the durable journal; REST recovers disconnect gaps."""
import asyncio
import json
import logging
import websockets
import polymarket_auth as auth
import order_journal

_task = None
_dirty = False
log = logging.getLogger(__name__)


def ingest(message):
    global _dirty
    if message.get('error'):
        raise ValueError('Private subscription rejected')
    for order in (message.get('orderSubscriptionSnapshot') or {}).get('orders',[]):
        order_journal.record_order(order)
    execution = (message.get('orderSubscriptionUpdate') or {}).get('execution')
    if execution:
        order_journal.record_execution(execution)
    if any(k in message for k in ('orderSubscriptionSnapshot','orderSubscriptionUpdate',
                                  'positionSubscription','accountBalancesSnapshot','accountBalancesUpdate')):
        _dirty = True


def consume_dirty():
    global _dirty
    result, _dirty = _dirty, False
    return result


def start():
    global _task
    if auth.credentials_present() and (_task is None or _task.done()):
        _task = asyncio.create_task(_run())


async def stop():
    global _task, _dirty
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task, _dirty = None, False


async def _run():
    global _dirty
    while auth.credentials_present():
        try:
            async with websockets.connect('wss://api.polymarket.us/v1/ws/private',
                    extra_headers=auth.l2_headers('GET','/v1/ws/private'),
                    ping_interval=20,ping_timeout=20) as ws:
                for kind in ('ORDER','POSITION','ACCOUNT_BALANCE'):
                    await ws.send(json.dumps({'subscribe':{'requestId':'rom-'+kind,
                        'subscriptionType':'SUBSCRIPTION_TYPE_'+kind}}))
                _dirty = True  # Always reconcile after reconnect; streams can have gaps.
                async for payload in ws:
                    ingest(json.loads(payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _dirty = True
            log.warning('Private account stream reconnecting: %s',type(exc).__name__)
            await asyncio.sleep(5)
