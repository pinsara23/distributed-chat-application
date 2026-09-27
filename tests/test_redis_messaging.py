import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.messaging.redis_client import RedisPubSubManager

@pytest.mark.asyncio
async def test_redis_publish_message():
    # 1. setup the manager and fake redis client
    manager = RedisPubSubManager()
    manager.redis_client = AsyncMock()

    target_user_id = 5
    payload = {
        "id": 100,
        "content": "Distributed test message!"
        }

    # 2. Call the publish_message method
    await manager.publish_message(target_user_id, payload)

    # 3. verify it published to the exact right channel with the right json strings
    expected_channel = f"chat:user:5"
    expected_data = json.dumps(payload)
    manager.redis_client.publish.assert_called_once_with(expected_channel, expected_data)

@pytest.mark.asyncio
async def test_redis_client_local_delivery():
    manager = RedisPubSubManager()
    manager.pubsub = AsyncMock()

    # 1. create fake incomming message from redis
    fake_payload = {
        "id": 101,
        "content": "Incoming Test!"
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

    manager.pubsub.listen = fake_listen

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