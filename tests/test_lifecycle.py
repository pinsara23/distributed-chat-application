"""Startup retry, readiness and graceful shutdown."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI

from app import main as app_main
from app.messaging.rabbitmq import workers
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.services.health_service import HealthService


async def test_workers_retry_until_rabbitmq_is_reachable(monkeypatch):
    monkeypatch.setattr(workers, "RETRY_MIN_DELAY", 0.01)
    connect = AsyncMock(side_effect=[ConnectionError("down"), ConnectionError("down"), None])
    monkeypatch.setattr(rabbitmq_manager, "connect", connect)
    monkeypatch.setattr(rabbitmq_manager, "disconnect", AsyncMock())
    monkeypatch.setattr(rabbitmq_manager, "setup_topology", AsyncMock())
    consumer_started, outbox_started = AsyncMock(), AsyncMock()
    monkeypatch.setattr(workers, "start_consumer", consumer_started)
    monkeypatch.setattr(workers, "process_outbox", outbox_started)

    await asyncio.wait_for(workers.run_rabbitmq_workers(), timeout=5)

    assert connect.await_count == 3          # two failures, then success
    consumer_started.assert_awaited_once()
    outbox_started.assert_awaited_once()     # publisher only starts after the broker is up


async def test_readiness_reports_rabbitmq(monkeypatch):
    service = HealthService(db=None)

    monkeypatch.setattr(rabbitmq_manager, "connection", None)
    assert await service.check_rabbitmq() == (False, "disconnected")

    monkeypatch.setattr(rabbitmq_manager, "connection", MagicMock(is_closed=True))
    ok, message = await service.check_rabbitmq()
    assert not ok and "closed" in message

    monkeypatch.setattr(rabbitmq_manager, "connection", MagicMock(is_closed=False))
    assert await service.check_rabbitmq() == (True, "ok")


async def test_shutdown_awaits_cancelled_tasks_and_releases_resources(monkeypatch):
    finished = []

    async def long_running(*_a, **_k):
        try:
            await asyncio.sleep(999)
        finally:
            await asyncio.sleep(0.05)       # cleanup that must be awaited, not abandoned
            finished.append("done")

    calls = []
    monkeypatch.setattr(app_main.redis_manager, "connect", AsyncMock())
    monkeypatch.setattr(app_main.redis_manager, "subscribe_and_listen", long_running)
    monkeypatch.setattr(app_main, "run_rabbitmq_workers", long_running)
    monkeypatch.setattr(app_main.websocket_manager, "close_all", AsyncMock(side_effect=lambda: calls.append("ws")))
    monkeypatch.setattr(app_main.rabbitmq_manager, "disconnect", AsyncMock(side_effect=lambda: calls.append("rabbit")))
    monkeypatch.setattr(app_main.redis_manager, "disconnect", AsyncMock(side_effect=lambda: calls.append("redis")))
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock(side_effect=lambda: calls.append("engine"))
    monkeypatch.setattr(app_main, "engine", fake_engine)

    async with app_main.lifespan(FastAPI()):
        await asyncio.sleep(0.05)           # let the background tasks start

    assert finished == ["done", "done"]     # both tasks finished their cleanup before shutdown ended
    assert calls == ["ws", "rabbit", "redis", "engine"]
