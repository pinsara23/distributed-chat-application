"""Durable idempotency helpers against the real test database."""
import uuid

import pytest
from sqlalchemy import func, select

from app.messaging.rabbitmq import consumer
from app.models.processed_event import ProcessedEvent
from tests.conftest import TestingSessionLocal


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch):
    monkeypatch.setattr(consumer, "AsyncSessionLocal", TestingSessionLocal)


async def test_unknown_event_is_not_processed():
    assert await consumer._already_processed(str(uuid.uuid4())) is False


async def test_recording_is_durable_and_idempotent():
    event_id = str(uuid.uuid4())

    await consumer._record_processed(event_id)
    await consumer._record_processed(event_id)  # redelivery: no error, no 2nd row

    assert await consumer._already_processed(event_id) is True
    async with TestingSessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(ProcessedEvent)
            .where(ProcessedEvent.event_id == uuid.UUID(event_id))
        )
    assert count == 1
