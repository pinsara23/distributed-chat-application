import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_conversation_lifecycle(async_client: AsyncClient):
    # 1. Register User A (Alice)
    res_a = await async_client.post(
        "/auth/register", 
        json={"username": "alice_chat", "email": "alice_chat@example.com", "password": "pass"}
    )
    assert res_a.status_code == 201

    # 2. Register User B (Bob)
    res_b = await async_client.post(
        "/auth/register", 
        json={"username": "bob_chat", "email": "bob_chat@example.com", "password": "pass"}
    )
    bob_id = res_b.json()["id"]

    # 3. Login Alice to get her JWT token
    login_res = await async_client.post(
        "/auth/login", 
        data={"username": "alice_chat", "password": "pass"}
    )
    alice_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {alice_token}"}

    # 4. Alice creates a conversation with Bob
    conv_res = await async_client.post(
        "/conversations/", 
        json={"user_id": bob_id}, 
        headers=headers
    )
    assert conv_res.status_code == 200
    conv_id = conv_res.json()["id"]

    # 5. Alice fetches her conversations
    list_res = await async_client.get("/conversations/", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["id"] == conv_id

    # 6. Alice fetches messages for this conversation (should be empty)
    msg_res = await async_client.get(f"/conversations/{conv_id}/messages", headers=headers)
    assert msg_res.status_code == 200
    assert len(msg_res.json()) == 0

@pytest.mark.asyncio
async def test_unauthorized_conversation_access(async_client: AsyncClient):
    # 1. Register User C (Charlie)
    await async_client.post(
        "/auth/register", 
        json={"username": "charlie", "email": "charlie@example.com", "password": "pass"}
    )
    
    # 2. Login Charlie
    login_res = await async_client.post(
        "/auth/login", 
        data={"username": "charlie", "password": "pass"}
    )
    charlie_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {charlie_token}"}

    # 3. Charlie attempts to view Alice and Bob's conversation (assuming ID 1 from previous test)
    # This should be rejected because Charlie is not a participant
    msg_res = await async_client.get("/conversations/1/messages", headers=headers)
    
    assert msg_res.status_code == 403
    assert "participant" in msg_res.json()["detail"]