import pytest

from app.websocket import chat
from app.websocket.chat import ConnectionManager


class FakeSocket:
    def __init__(self):
        self.closed = False

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.closed = True


@pytest.fixture
def presence_calls(monkeypatch):
    calls = []

    async def mark_online(user_id):
        calls.append(("online", int(user_id)))

    async def mark_offline(user_id):
        calls.append(("offline", int(user_id)))

    monkeypatch.setattr(chat.presence_service, "mark_online", mark_online)
    monkeypatch.setattr(chat.presence_service, "mark_offline", mark_offline)
    return calls


async def test_stale_socket_cleanup_does_not_evict_new_connection(presence_calls):
    manager = ConnectionManager()
    old, new = FakeSocket(), FakeSocket()

    await manager.connect(1, old)
    await manager.connect(1, new)  # reconnect replaces the old socket
    assert old.closed

    await manager.disconnect(1, old)  # old handler's finally block runs late

    assert manager.active_connections[1] is new
    assert ("offline", 1) not in presence_calls


async def test_owner_disconnect_removes_connection_and_marks_offline(presence_calls):
    manager = ConnectionManager()
    sock = FakeSocket()

    await manager.connect(2, sock)
    await manager.disconnect(2, sock)

    assert 2 not in manager.active_connections
    assert ("offline", 2) in presence_calls


# --- WebSocket handler hardening -------------------------------------------
import json
import uuid
from starlette.testclient import TestClient
from app.main import app
from app.core.security import create_access_token


def _ws_token(user_id=1):
    return create_access_token({"sub": str(user_id)})


def test_ws_survives_malformed_payloads(monkeypatch):
    async def noop(*a, **k):
        pass

    monkeypatch.setattr(chat.presence_service, "mark_online", noop)
    monkeypatch.setattr(chat.presence_service, "mark_offline", noop)
    monkeypatch.setattr(chat.presence_service, "refresh_presence", noop)

    bad_payloads = [
        "[1, 2, 3]",  # not an object
        "42",
        json.dumps({"conversation_id": "abc", "target_user_id": 2, "ciphertext": "AAAA"}),
        json.dumps({"conversation_id": None, "target_user_id": 2, "ciphertext": "AAAA"}),
        # plaintext is never accepted, even alongside otherwise valid fields
        json.dumps({"message_id": str(uuid.uuid4()), "conversation_id": 1, "target_user_id": 2,
                    "ciphertext": "A" * 24, "nonce": "A" * 16, "content": "hello"}),
        "x" * (chat.MAX_WS_MESSAGE_BYTES + 1),
    ]

    # Skip lifespan so no Redis/RabbitMQ is needed.
    client = TestClient(app)
    with client.websocket_connect(f"/ws/chat?token={_ws_token()}") as ws:
        for raw in bad_payloads:
            ws.send_text(raw)
            reply = json.loads(ws.receive_text())
            assert "error" in reply
        # Socket is still usable after every bad frame.
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text()) == {"type": "pong"}


def test_ws_message_schema_requires_real_ciphertext_and_nonce():
    import base64
    from pydantic import ValidationError
    from app.schemas.message import WsMessageIn

    good = dict(
        message_id=str(uuid.uuid4()), conversation_id=1, target_user_id=2,
        ciphertext=base64.b64encode(b"c" * 32).decode(), nonce=base64.b64encode(b"n" * 12).decode(),
    )
    assert WsMessageIn(**good).key_version == 1

    for override in (
        {"content": "plaintext"},                      # unknown/plaintext field
        {"nonce": base64.b64encode(b"short").decode()},  # wrong nonce size
        {"ciphertext": base64.b64encode(b"x").decode()}, # shorter than a GCM tag
        {"ciphertext": "not base64!!"},
        {"message_id": "not-a-uuid"},
    ):
        with pytest.raises(ValidationError):
            WsMessageIn(**{**good, **override})


def _valid_frame(message_id):
    import base64
    return json.dumps(dict(
        message_id=message_id, conversation_id=1, target_user_id=2,
        ciphertext=base64.b64encode(b"c" * 32).decode(), nonce=base64.b64encode(b"n" * 12).decode(),
    ))


@pytest.mark.parametrize("failure,retryable", [
    ("forbidden", False),
    ("database", True),
])
def test_ws_errors_identify_the_message_and_say_if_retryable(monkeypatch, failure, retryable):
    from fastapi import HTTPException
    from sqlalchemy.exc import OperationalError

    async def noop(*a, **k):
        pass

    async def failing_save(self, **kwargs):
        if failure == "forbidden":
            raise HTTPException(status_code=403, detail="Message participants must belong to this conversation.")
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    for name in ("mark_online", "mark_offline", "refresh_presence"):
        monkeypatch.setattr(chat.presence_service, name, noop)
    monkeypatch.setattr(chat.ChatService, "save_message", failing_save)

    message_id = str(uuid.uuid4())
    with TestClient(app).websocket_connect(f"/ws/chat?token={_ws_token()}") as ws:
        ws.send_text(_valid_frame(message_id))
        reply = json.loads(ws.receive_text())

    assert reply["message_id"] == message_id
    assert reply["retryable"] is retryable
    assert "error" in reply


@pytest.mark.parametrize("sent_version,current_version,rejected", [(1, 2, True), (2, 2, False), (None, 2, False)])
def test_ws_rejects_messages_encrypted_to_an_old_recipient_key(monkeypatch, sent_version, current_version, rejected):
    from types import SimpleNamespace

    async def noop(*a, **k):
        pass

    saved = []

    async def fake_save(self, **kwargs):
        saved.append(kwargs)
        raise RuntimeError("stop after save")  # only checking whether save was reached

    async def fake_key(self, user_id):
        return SimpleNamespace(key_version=current_version)

    for name in ("mark_online", "mark_offline", "refresh_presence"):
        monkeypatch.setattr(chat.presence_service, name, noop)
    monkeypatch.setattr(chat.ChatService, "save_message", fake_save)
    monkeypatch.setattr(chat.KeyService, "get_key_by_user_id", fake_key)

    message_id = str(uuid.uuid4())
    frame = json.loads(_valid_frame(message_id))
    if sent_version is not None:
        frame["recipient_key_version"] = sent_version
    with TestClient(app).websocket_connect(f"/ws/chat?token={_ws_token()}") as ws:
        ws.send_text(json.dumps(frame))
        if rejected:
            reply = json.loads(ws.receive_text())
            assert reply["code"] == "stale_recipient_key"
            assert reply["message_id"] == message_id
            assert reply["current_key_version"] == current_version
    assert bool(saved) is not rejected
