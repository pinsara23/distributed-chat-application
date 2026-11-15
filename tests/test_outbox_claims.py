"""Outbox claim/lease SQL against the real test database."""
import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.messaging.rabbitmq import publisher
from app.models.outbox_events import OutboxEvent
from tests.conftest import TestingSessionLocal


@pytest.fixture(autouse=True)
async def isolated_outbox(monkeypatch):
    monkeypatch.setattr(publisher, "AsyncSessionLocal", TestingSessionLocal)
    async with TestingSessionLocal() as session:
        await session.execute(OutboxEvent.__table__.delete())
        await session.commit()
    yield


async def _add(n):
    async with TestingSessionLocal() as session:
        for _ in range(n):
            session.add(OutboxEvent(event_id=uuid.uuid4(), event_type="message.created", payload={"x": 1}))
        await session.commit()


async def _rows():
    async with TestingSessionLocal() as session:
        return (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()


async def test_concurrent_claims_never_overlap():
    await _add(10)
    first, second = await asyncio.gather(publisher._claim_batch(6), publisher._claim_batch(6))

    ids = [e.id for e in first] + [e.id for e in second]
    assert len(ids) == len(set(ids))      # no event handed to two publishers
    assert len(ids) == 10                 # and none lost


async def test_claimed_rows_are_leased_until_released_or_expired():
    await _add(2)
    assert len(await publisher._claim_batch(10)) == 2
    assert await publisher._claim_batch(10) == []       # leased: invisible to others

    await publisher._release([e.id for e in await _rows()])
    assert len(await publisher._claim_batch(10)) == 2   # released: claimable again


async def test_expired_lease_is_reclaimed_after_a_publisher_crash():
    await _add(1)
    await publisher._claim_batch(10)                    # "crashes" without marking
    async with TestingSessionLocal() as session:
        await session.execute(update(OutboxEvent).values(locked_until=datetime.utcnow() - timedelta(seconds=1)))
        await session.commit()

    assert len(await publisher._claim_batch(10)) == 1


async def test_published_rows_are_never_claimed_again():
    await _add(1)
    (event,) = await publisher._claim_batch(10)
    await publisher._mark_published(event.id)

    assert await publisher._claim_batch(10) == []
    (row,) = await _rows()
    assert row.published_at is not None and row.locked_until is None
