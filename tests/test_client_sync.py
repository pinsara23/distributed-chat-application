import importlib.util
import os

import pytest

CLIENT_DIR = os.path.join(os.path.dirname(__file__), "..", "client")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Load client/main.py in isolation, pointing its state file at tmp_path."""
    monkeypatch.syspath_prepend(CLIENT_DIR)
    spec = importlib.util.spec_from_file_location("chat_client_main", os.path.join(CLIENT_DIR, "main.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "MESSAGE_CURSOR_FILE", str(tmp_path / "cursor.json"))
    module.SEEN_MESSAGE_IDS.clear()
    module.LAST_MESSAGE_ID = 0

    async def fake_key(_peer):
        return b"\x00" * 32

    # Stub decryption so these tests exercise only dedup/cursor behaviour.
    monkeypatch.setattr(module, "get_shared_key", fake_key)
    monkeypatch.setattr(
        module.crypto_service, "decrypt_message",
        lambda ct, nonce, key, aad: "stub",
    )
    return module


def _envelope(msg_id):
    return {
        "id": msg_id,
        "message_uuid": f"00000000-0000-4000-8000-{msg_id:012d}",
        "conversation_id": 1,
        "sender_id": 2,
        "ciphertext": "AAAA",
        "nonce": "AAAAAAAAAAAAAAAA",
    }


async def test_late_lower_id_message_is_still_delivered(client, capsys):
    await client.handle_message(_envelope(10))
    await client.handle_message(_envelope(7))  # arrives late, lower id

    out = capsys.readouterr().out
    assert out.count("stub") == 2
    assert client.LAST_MESSAGE_ID == 10


async def test_duplicate_is_suppressed(client, capsys):
    await client.handle_message(_envelope(5))
    await client.handle_message(_envelope(5))

    assert capsys.readouterr().out.count("stub") == 1


async def test_seen_ids_survive_restart(client):
    await client.handle_message(_envelope(3))
    await client.handle_message(_envelope(9))

    import json
    with open(client.MESSAGE_CURSOR_FILE) as f:
        saved = json.load(f)
    assert saved["last_message_id"] == 9
    assert set(saved["seen_ids"]) == {3, 9}


async def test_tampered_message_is_skipped_not_blocking(client, monkeypatch, capsys):
    def boom(*_a):
        raise ValueError("bad tag")

    monkeypatch.setattr(client.crypto_service, "decrypt_message", boom)
    bad = _envelope(4)

    assert await client.handle_message(bad) is True  # does not abort sync
    assert 4 in client.SEEN_MESSAGE_IDS
    assert "failed authentication" in capsys.readouterr().out


async def test_decrypt_receives_canonical_aad(client, monkeypatch):
    """The receiver must rebuild AAD from server-supplied ids via build_aad."""
    from crypto import build_aad

    seen = {}

    def spy(_ct, _nonce, _key, aad):
        seen["aad"] = aad
        return "stub"

    monkeypatch.setattr(client.crypto_service, "decrypt_message", spy)
    env = _envelope(12)
    await client.handle_message(env)

    assert seen["aad"] == build_aad(env["message_uuid"], env["conversation_id"], env["sender_id"])


# --- outbound queue --------------------------------------------------------------
import asyncio
import json as _json


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(_json.loads(text))


@pytest.fixture
def outbound(client, monkeypatch):
    client.TEXT_QUEUE = asyncio.Queue()
    client.PENDING.clear()
    client.USER_ID = 1

    async def fake_prepare(text):
        return {"message_id": f"id-{text}", "ciphertext": text}

    monkeypatch.setattr(client, "prepare_payload", fake_prepare)
    return client


async def _run_sender(client, ws, settle=0.05):
    task = asyncio.create_task(client.send_messages(ws))
    await asyncio.sleep(settle)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_unacknowledged_message_is_resent_after_reconnect(outbound):
    first_connection = FakeWebSocket()
    outbound.TEXT_QUEUE.put_nowait("hello")
    await _run_sender(outbound, first_connection)
    assert [m["message_id"] for m in first_connection.sent] == ["id-hello"]
    assert "id-hello" in outbound.PENDING          # no echo yet: still pending

    second_connection = FakeWebSocket()            # reconnect
    await _run_sender(outbound, second_connection)
    assert [m["message_id"] for m in second_connection.sent] == ["id-hello"]


async def test_echo_clears_pending_so_it_is_not_resent(outbound):
    outbound.TEXT_QUEUE.put_nowait("hello")
    await _run_sender(outbound, FakeWebSocket())

    echo = _envelope(1)
    echo.update(sender_id=1, message_uuid="id-hello")
    await outbound.handle_message(echo)
    assert outbound.PENDING == {}

    reconnected = FakeWebSocket()
    await _run_sender(outbound, reconnected)
    assert reconnected.sent == []


async def test_text_typed_while_disconnected_is_sent_on_next_connection(outbound):
    outbound.TEXT_QUEUE.put_nowait("typed while offline")  # queued, no websocket yet

    ws = FakeWebSocket()
    await _run_sender(outbound, ws)
    assert [m["message_id"] for m in ws.sent] == ["id-typed while offline"]


async def test_text_is_not_lost_if_cancelled_while_encrypting(outbound, monkeypatch):
    async def slow_prepare(_text):
        await asyncio.sleep(10)

    monkeypatch.setattr(outbound, "prepare_payload", slow_prepare)
    outbound.TEXT_QUEUE.put_nowait("precious")

    await _run_sender(outbound, FakeWebSocket())        # cancelled mid-encryption

    assert outbound.TEXT_QUEUE.get_nowait() == "precious"


async def test_prompt_answer_comes_from_the_stdin_queue_not_a_second_input(client, monkeypatch, capsys):
    """The stdin reader thread owns the terminal; a prompt must not race it with input()."""
    def forbidden(*_a):
        raise AssertionError("ask_user must not call input() while the reader owns stdin")

    monkeypatch.setattr("builtins.input", forbidden)
    client.TEXT_QUEUE = asyncio.Queue()
    client.TEXT_QUEUE.put_nowait("yes")

    assert await client.ask_user("Trust this key? (yes/no): ") == "yes"
    assert "Trust this key?" in capsys.readouterr().out
    assert client.TEXT_QUEUE.empty()                     # the answer was consumed, not sent as chat
