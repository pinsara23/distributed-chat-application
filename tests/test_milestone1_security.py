import base64
import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from fastapi import HTTPException

from app.schemas.message import serialize_message
from app.services.chat_service import ChatService


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def first(self):
        return self.values[0] if self.values else None


class FakeSession:
    def __init__(self, participant_ids):
        self.participant_ids = participant_ids
        self.added = []
        self.committed = False

    async def execute(self, _statement):
        return ScalarResult(self.participant_ids)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if hasattr(value, "message_uuid") and value.message_uuid is None:
                value.message_uuid = uuid.uuid4()
            if hasattr(value, "created_at") and value.created_at is None:
                value.created_at = datetime.utcnow()

    async def commit(self):
        self.committed = True

    async def refresh(self, _value):
        return None


def test_binary_message_fields_are_serialized_as_base64():
    message = SimpleNamespace(
        id=1,
        message_uuid=uuid.uuid4(),
        conversation_id=2,
        sender_id=3,
        cipertext=b"\x00\xffcipher",
        nonce=b"\x01\x02",
        encryption_version=1,
        created_at=datetime(2026, 1, 1),
    )

    serialized = serialize_message(message)

    assert serialized["cipertext"] == base64.b64encode(message.cipertext).decode("ascii")
    assert serialized["nonce"] == base64.b64encode(message.nonce).decode("ascii")


@pytest.mark.asyncio
async def test_participant_can_send_and_creates_message_and_outbox():
    session = FakeSession([10, 20])
    service = ChatService(session)

    saved = await service.save_message(
        conversation_id=5,
        sender_id=10,
        target_id=20,
        content="hello",
    )

    assert saved.sender_id == 10
    assert len(session.added) == 2
    assert session.committed


@pytest.mark.asyncio
async def test_non_participant_cannot_send_and_creates_no_records():
    session = FakeSession([10])
    service = ChatService(session)

    with pytest.raises(HTTPException) as exc_info:
        await service.save_message(
            conversation_id=5,
            sender_id=10,
            target_id=30,
            content="must fail",
        )

    assert exc_info.value.status_code == 403
    assert session.added == []
    assert not session.committed


@pytest.mark.asyncio
async def test_unauthorized_history_is_rejected_for_after_id():
    session = FakeSession([10])
    service = ChatService(session)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_missed_messages(user_id=30, conversation_id=5, after_id=0)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_direct_conversation_requests_return_one_conversation(
    async_client: AsyncClient,
):
    suffix = uuid.uuid4().hex[:8]
    alice = await async_client.post(
        "/auth/register",
        json={
            "username": f"alice_{suffix}",
            "email": f"alice_{suffix}@example.com",
            "password": "pass",
        },
    )
    bob = await async_client.post(
        "/auth/register",
        json={
            "username": f"bob_{suffix}",
            "email": f"bob_{suffix}@example.com",
            "password": "pass",
        },
    )
    assert alice.status_code == bob.status_code == 201

    login = await async_client.post(
        "/auth/login",
        data={"username": f"alice_{suffix}", "password": "pass"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    responses = await asyncio.gather(
        *(
            async_client.post(
                "/conversations/",
                json={"user_id": bob.json()["id"]},
                headers=headers,
            )
            for _ in range(8)
        )
    )

    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
