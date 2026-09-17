from __future__ import annotations

import asyncio

import service


def test_deep_readiness_checks_dependencies_and_capacity():
    report = asyncio.run(service._deep_readiness())
    assert report["status"] in {"ready", "degraded"}
    assert report["durationMs"] < 2000
    assert report["checks"]["database"]["status"] == "up"
    assert report["checks"]["disk"]["freeMb"] > 0
    assert report["bulkheads"]["execution"]["capacity"] == 4
    assert report["bulkheads"]["marketData"]["capacity"] == 8


def test_database_failure_makes_instance_not_ready(monkeypatch):
    class BrokenDb:
        def __enter__(self):
            raise OSError("injected database failure")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(service.db, "get_db", lambda: BrokenDb())
    report = asyncio.run(service._deep_readiness())
    assert report["status"] == "not_ready"
    assert report["checks"]["database"]["status"] == "down"
    assert "injected" in report["checks"]["database"]["error"]
