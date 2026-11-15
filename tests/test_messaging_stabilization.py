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


@pytest.fixture(autouse=True)
def processed_store(monkeypatch):
    """In-memory stand-in for the processed_events table."""
    store = set()

    async def already(event_id):
        return event_id in store

    async def record(event_id):
        store.add(event_id)

    monkeypatch.setattr(consumer, "_already_processed", already)
    monkeypatch.setattr(consumer, "_record_processed", record)
    return store


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


def claimed(n=1):
    return [
        publisher.ClaimedEvent(i, uuid.uuid4(), "message.created", {"payload": {}})
        for i in range(1, n + 1)
    ]


@pytest.fixture
def outbox_calls(monkeypatch):
    calls = SimpleNamespace(marked=[], released=[])

    async def mark(row_id):
        calls.marked.append(row_id)

    async def release(ids):
        calls.released.extend(ids)

    monkeypatch.setattr(publisher, "_mark_published", mark)
    monkeypatch.setattr(publisher, "_release", release)
    return calls


@pytest.mark.asyncio
async def test_outbox_publishes_then_marks_each_event(monkeypatch, outbox_calls):
    exchange = FakeExchange()
    monkeypatch.setattr(publisher.rabbitmq_manager, "exchange", exchange)

    async def claim(_size):
        return claimed(3)

    monkeypatch.setattr(publisher, "_claim_batch", claim)

    assert await publisher.publish_outbox_batch() == 3
    assert [m[1] for m in exchange.messages] == ["message.created"] * 3
    assert all(m[2] is True for m in exchange.messages)  # mandatory
    assert outbox_calls.marked == [1, 2, 3]
    assert outbox_calls.released == []


@pytest.mark.asyncio
async def test_outbox_failure_marks_nothing_and_releases_the_claim(monkeypatch, outbox_calls):
    exchange = FakeExchange()
    exchange.fail = True
    monkeypatch.setattr(publisher.rabbitmq_manager, "exchange", exchange)

    async def claim(_size):
        return claimed(2)

    monkeypatch.setattr(publisher, "_claim_batch", claim)

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await publisher.publish_outbox_batch()

    assert outbox_calls.marked == []
    assert outbox_calls.released == [1, 2]


@pytest.mark.asyncio
async def test_outbox_partial_failure_keeps_confirmed_events_published(monkeypatch, outbox_calls):
    """Event 1 is confirmed; event 2 fails. Only 2 and 3 go back to the queue."""
    exchange = FakeExchange()
    real_publish = exchange.publish

    async def flaky(message, routing_key, mandatory):
        if len(exchange.messages) == 1:
            raise RuntimeError("broker unavailable")
        await real_publish(message, routing_key, mandatory)

    exchange.publish = flaky
    monkeypatch.setattr(publisher.rabbitmq_manager, "exchange", exchange)

    async def claim(_size):
        return claimed(3)

    monkeypatch.setattr(publisher, "_claim_batch", claim)

    with pytest.raises(RuntimeError):
        await publisher.publish_outbox_batch()

    assert outbox_calls.marked == [1]
    assert outbox_calls.released == [2, 3]


@pytest.mark.asyncio
async def test_consumer_success_and_duplicate_delivery(monkeypatch, processed_store):
    redis = FakeRedis()
    message_uuid = uuid.uuid4()
    db_message = SimpleNamespace(
        id=1,
        message_uuid=message_uuid,
        conversation_id=2,
        sender_id=3,
        ciphertext=b"ciphertext",
        nonce=b"nonce",
        key_version=1,
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
    assert envelope["event_id"] in processed_store


@pytest.mark.asyncio
async def test_consumer_retries_missing_database_message_then_dead_letters(monkeypatch, processed_store):
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
    assert not processed_store


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
    manager.redis = AsyncMock()
    manager.redis.publish.side_effect = RuntimeError("redis unavailable")

    with pytest.raises(RuntimeError, match="redis unavailable"):
        await manager.publish_message(5, {"id": 1})

    manager.redis = None
    with pytest.raises(RuntimeError, match="not connected"):
        await manager.publish_message(5, {"id": 1})


@pytest.mark.asyncio
async def test_retry_bound_holds_when_redis_is_down(monkeypatch):
    """With Redis unavailable the event must still be dead-lettered, not looped."""
    monkeypatch.setattr(redis_manager, "redis", None)
    monkeypatch.setattr(consumer, "RETRY_DELAY_SECONDS", 0)
    consumer._LOCAL_ATTEMPTS.clear()
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": "message.created",
        "payload": {"message_id": str(uuid.uuid4()), "target_user_id": 7},
    }

    messages = [rabbit_message(envelope) for _ in range(consumer.MAX_RETRIES + 1)]
    for message in messages:
        await consumer.on_message(message)

    for message in messages[:-1]:
        message.nack.assert_awaited_once_with(requeue=True)
    messages[-1].nack.assert_awaited_once_with(requeue=False)
    assert envelope["event_id"] not in consumer._LOCAL_ATTEMPTS
