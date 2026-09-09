import asyncio

import service


def test_loop_watchdog_restarts_stalled_loop(monkeypatch):
    monkeypatch.setattr(service, "_WATCHDOG_CHECK_SEC", 0.02)
    monkeypatch.setattr(service, "_LOOP_STALL_SEC", 0.05)

    async def _noop_emit(*a, **k):
        return None
    monkeypatch.setattr(service, "emit_event", _noop_emit)

    restarts = {"n": 0}

    async def _dummy_loop():
        restarts["n"] += 1
        while not (service._loop_stop and service._loop_stop.is_set()):
            service._loop_heartbeat = asyncio.get_event_loop().time()
            await asyncio.sleep(0.01)
    monkeypatch.setattr(service, "_scanner_and_trader_loop", _dummy_loop)

    async def _run():
        loop = asyncio.get_event_loop()
        service._loop_stop = asyncio.Event()

        async def _stuck():
            await asyncio.sleep(60)

        stuck = loop.create_task(_stuck())
        service._loop_task = stuck
        service._loop_heartbeat = loop.time() - 999.0

        wd = loop.create_task(service._loop_watchdog())
        for _ in range(400):
            await asyncio.sleep(0.01)
            if service._loop_task is not stuck and restarts["n"] >= 1:
                break
        new = service._loop_task

        service._loop_stop.set()
        wd.cancel()
        await asyncio.gather(wd, new, stuck, return_exceptions=True)
        return stuck, new

    stuck, new = asyncio.run(_run())
    assert stuck.cancelled() or stuck.done()
    assert new is not stuck
    assert restarts["n"] >= 1


def test_loop_watchdog_leaves_healthy_loop_alone(monkeypatch):
    monkeypatch.setattr(service, "_WATCHDOG_CHECK_SEC", 0.02)
    monkeypatch.setattr(service, "_LOOP_STALL_SEC", 0.05)

    spawned = {"n": 0}

    async def _dummy_loop():
        spawned["n"] += 1
        while not (service._loop_stop and service._loop_stop.is_set()):
            await asyncio.sleep(0.01)
    monkeypatch.setattr(service, "_scanner_and_trader_loop", _dummy_loop)

    async def _run():
        loop = asyncio.get_event_loop()
        service._loop_stop = asyncio.Event()

        async def _healthy():
            while not (service._loop_stop and service._loop_stop.is_set()):
                service._loop_heartbeat = asyncio.get_event_loop().time()
                await asyncio.sleep(0.005)

        healthy = loop.create_task(_healthy())
        service._loop_task = healthy
        service._loop_heartbeat = loop.time()

        wd = loop.create_task(service._loop_watchdog())
        await asyncio.sleep(0.2)
        same = service._loop_task is healthy
        service._loop_stop.set()
        wd.cancel()
        await asyncio.gather(wd, healthy, return_exceptions=True)
        return same

    same = asyncio.run(_run())
    assert same
    assert spawned["n"] == 0
