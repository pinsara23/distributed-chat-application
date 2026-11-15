import json
import pytest
import asyncio
from unittest.mock import AsyncMock

from app.messaging.redis_client import RedisPubSubManager

@pytest.mark.asyncio
async def test_redis_publish_message():
    # 1. setup the manager and fake redis client
    manager = RedisPubSubManager()
    manager.redis = AsyncMock()

    target_user_id = 5
    payload = {
        "id": 100,
        "ciphertext": "Zm9v"
        }

    # 2. Call the publish_message method
    await manager.publish_message(target_user_id, payload)

    # 3. verify it published to the exact right channel with the right json strings
    expected_channel = "chat:user:5"
    expected_data = json.dumps(payload)
    manager.redis.publish.assert_called_once_with(expected_channel, expected_data)

@pytest.mark.asyncio
async def test_redis_client_local_delivery():
    manager = RedisPubSubManager()
    pubsub = AsyncMock()
    manager._new_pubsub = lambda: pubsub

    # 1. create fake incomming message from redis
    fake_payload = {
        "id": 101,
        "ciphertext": "Zm9v"
    }
    fake_message = {
        "type": "pmessage",
        "channel": "chat:user:42",
        "data": json.dumps(fake_payload)
    }

    # 2. make pubsub.listen() yield the fake message and then stop forever so the loop doesnt crash
    async def fake_listen():
        yield fake_message
        await asyncio.sleep(999)

    pubsub.listen = fake_listen

    # 3,. create fake websocket manager
    mock_ws_manager = AsyncMock()

    # 4. start listner in the background
    listner_task = asyncio.create_task(manager.subscribe_and_listen(mock_ws_manager))

    await asyncio.sleep(0.1)  # give it a moment to start

    # 5. verify the listner successfully handed the message to the local ws manager
    mock_ws_manager.send_personal_message.assert_called_once_with(
        json.dumps(fake_payload),
        42
    )

    # clean the background task
    listner_task.cancel()


@pytest.mark.asyncio
async def test_listener_resubscribes_after_redis_failure(monkeypatch):
    """A connection error must not kill the listener; it resubscribes and delivers."""
    from app.messaging import redis_client as module

    monkeypatch.setattr(module, "RESUBSCRIBE_MIN_DELAY", 0.01)
    manager = RedisPubSubManager()
    attempts = []

    class Broken:
        async def psubscribe(self, *_):
            raise ConnectionError("redis is down")

        async def aclose(self):
            pass

    class Healthy:
        async def psubscribe(self, *_):
            pass

        async def aclose(self):
            pass

        async def listen(self):
            yield {"type": "pmessage", "channel": "chat:user:9", "data": json.dumps({"id": 1})}
            await asyncio.sleep(999)

    def new_pubsub():
        attempts.append(1)
        return Broken() if len(attempts) < 3 else Healthy()

    manager._new_pubsub = new_pubsub
    ws = AsyncMock()

    task = asyncio.create_task(manager.subscribe_and_listen(ws))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(attempts) == 3  # two failures, then a working subscription
    ws.send_personal_message.assert_called_once_with(json.dumps({"id": 1}), 9)
