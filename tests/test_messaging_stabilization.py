import asyncio
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.messaging.rabbitmq import consumer, publisher
from app.messaging.redis_client import RedisPubSubManager, redis_manager


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    async def exists(self, key):
        return int(key in self.values)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def eval(self, _script, _keys, key, token):
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0

    async def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True


class FakeSession:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _statement):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(
                all=lambda: [self.value] if self.value else []
            ),
            scalar_one_or_none=lambda: self.value,
        )


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class FakePublisherSession(FakeSession):
    def begin(self):
        return FakeTransaction()


class FakeExchange:
    def __init__(self):
        self.messages = []
        self.fail = False

    async def publish(self, message, routing_key, mandatory):
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.messages.append((message, routing_key, mandatory))


def event(event_id=None):
    event_id = event_id or uuid.uuid4()
    return SimpleNamespace(
        event_id=event_id,
        event_type="message.created",
        payload={
            "event_id": str(event_id),
            "event_type": "message.created",
            "payload": {
                "message_id": str(uuid.uuid4()),
                "target_user_id": 7,
            },
        },
        published_at=None,
        created_at=datetime.utcnow(),
    )


def rabbit_message(envelope):
    message = SimpleNamespace(
        body=json.dumps(envelope).encode("utf-8"),
        ack=AsyncMock(),
        nack=AsyncMock(),
    )
    return message


@pytest.mark.asyncio
async def test_concurrent_outbox_publishers_claim_distinct_events(monkeypatch):
    events = [event(), event()]
    exchange = FakeExchange()
    statements = []

    class ConcurrentSession(FakePublisherSession):
        def __init__(self):
            super().__init__(events.pop(0) if events else None)

        async def execute(self, statement):
            statements.append(statement)
            return await super().execute(statement)

    monkeypatch.setattr(publisher.rabbitmq_manager, "exchange", exchange)
    monkeypatch.setattr(publisher, "AsyncSessionLocal", ConcurrentSession)

    assert await asyncio.gather(
        publisher.publish_outbox_batch(),
        publisher.publish_outbox_batch(),
    ) == [1, 1]
    assert len(exchange.messages) == 2
    assert all(statement._for_update_arg.skip_locked for statement in statements)


@pytest.mark.asyncio
async def test_outbox_failure_leaves_event_pending(monkeypatch):
    outbox_event = event()
    exchange = FakeExchange()
    exchange.fail = True

    monkeypatch.setattr(publisher.rabbitmq_manager, "exchange", exchange)
    monkeypatch.setattr(
        publisher,
        "AsyncSessionLocal",
        lambda: FakePublisherSession(outbox_event),
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await publisher.publish_outbox_batch()
    assert outbox_event.published_at is None


@pytest.mark.asyncio
async def test_consumer_success_and_duplicate_delivery(monkeypatch):
    redis = FakeRedis()
    message_uuid = uuid.uuid4()
    db_message = SimpleNamespace(
        id=1,
        message_uuid=message_uuid,
        conversation_id=2,
        sender_id=3,
        cipertext=b"ciphertext",
        nonce=b"nonce",
        encryption_version=1,
        created_at=datetime.utcnow(),
    )
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": "message.created",
        "payload": {
            "message_id": str(message_uuid),
            "target_user_id": 7,
        },
    }

    monkeypatch.setattr(redis_manager, "redis", redis)
    monkeypatch.setattr(redis_manager, "publish_message", AsyncMock())
    monkeypatch.setattr(
        consumer,
        "AsyncSessionLocal",
        lambda: FakeSession(db_message),
    )

    first = rabbit_message(envelope)
    await consumer.on_message(first)
    second = rabbit_message(envelope)
    await consumer.on_message(second)

    first.ack.assert_awaited_once()
    second.ack.assert_awaited_once()
    redis_manager.publish_message.assert_awaited_once()
    assert redis.values[f"processed_event:{envelope['event_id']}"] == "1"


@pytest.mark.asyncio
async def test_consumer_retries_missing_database_message_then_dead_letters(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(redis_manager, "redis", redis)
    monkeypatch.setattr(
        consumer,
        "AsyncSessionLocal",
        lambda: FakeSession(None),
    )
    message_uuid = uuid.uuid4()
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": "message.created",
        "payload": {
            "message_id": str(message_uuid),
            "target_user_id": 7,
        },
    }

    messages = [rabbit_message(envelope) for _ in range(4)]
    for message in messages:
        await consumer.on_message(message)

    for message in messages[:3]:
        message.nack.assert_awaited_once_with(requeue=True)
    messages[3].nack.assert_awaited_once_with(requeue=False)
    assert not any(key.startswith("processed_event:") for key in redis.values)


@pytest.mark.asyncio
async def test_consumer_malformed_event_is_dead_lettered(monkeypatch):
    monkeypatch.setattr(redis_manager, "redis", FakeRedis())
    message = SimpleNamespace(
        body=b"{not-json",
        ack=AsyncMock(),
        nack=AsyncMock(),
    )

    await consumer.on_message(message)

    message.nack.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_publish_errors_propagate():
    manager = RedisPubSubManager()
    manager.redis_client = AsyncMock()
    manager.redis_client.publish.side_effect = RuntimeError("redis unavailable")

    with pytest.raises(RuntimeError, match="redis unavailable"):
        await manager.publish_message(5, {"id": 1})

    manager.redis_client = None
    with pytest.raises(RuntimeError, match="not connected"):
        await manager.publish_message(5, {"id": 1})
