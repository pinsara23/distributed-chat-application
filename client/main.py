import asyncio
import json
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed
from crypto import crypto_service

# --- CONFIGURATION ---
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzk0MzQ3NzM4fQ.SGA2uHkCpjBHPhmvVMUpFJ65tZ4NFhKDXLXur0fRaCU" 
USER_ID = 1
TARGET_USER_ID = 2
CONVERSATION_ID = 1

REST_URL = "http://127.0.0.1:8001"
WS_URL = f"ws://127.0.0.1:8001/ws/chat?token={TOKEN}"

# Cache to store derived AES keys so we don't have to recalculate them every message
shared_keys_cache = {}

async def register_public_key():
    """Generates local keys and uploads the public key to the server."""
    crypto_service.load_or_generate_keys()
    
    fingerprint = crypto_service.get_fingerprint(crypto_service.public_key_pem)
    print(f"\n==================================================")
    print(f"🔐 MY SECURITY FINGERPRINT: {fingerprint}")
    print(f"==================================================\n")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    payload = {"public_key_pem": crypto_service.public_key_pem}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{REST_URL}/keys/", headers=headers, json=payload) as resp:
            if resp.status == 200:
                print(f"[Client] Public Key successfully registered with server.")
            else:
                print(f"[Client] ⚠️ Failed to register Public Key: {await resp.text()}")

async def get_shared_key(peer_id: int) -> bytes:
    """Fetches peer's public key from the server and derives the AES shared secret."""
    if peer_id in shared_keys_cache:
        return shared_keys_cache[peer_id]

    print(f"[Crypto] Fetching Public Key for User {peer_id} from server...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{REST_URL}/keys/{peer_id}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                peer_pem = data["public_key_pem"]
                
                # Derive the AES key using ECDH!
                shared_key = crypto_service.derive_shared_key(peer_pem)
                shared_keys_cache[peer_id] = shared_key
                
                print(f"[Crypto] 🔒 E2EE Secured with User {peer_id}!")
                return shared_key
            else:
                print(f"[Crypto] ⚠️ Could not fetch public key for User {peer_id}")
                return None

async def receive_messages(websocket):
    """Listens for incoming WebSocket messages and decrypts them."""
    try:
        while True:
            response = await websocket.recv()
            data = json.loads(response)

            if data.get("type") == "pong":
                continue

            if "error" in data:
                print(f"⚠️ Server Error: {data['error']}")
                continue

            # --- DECRYPTION LOGIC ---
            sender_id = data.get("sender_id")
            
            # 1. E2EE Message
            if "cipertext" in data and "nonce" in data:
                shared_key = await get_shared_key(sender_id)
                if shared_key:
                    try:
                        plaintext = crypto_service.decrypt_message(
                            data["cipertext"], 
                            data["nonce"], 
                            shared_key
                        )
                        print(f"\n[User {sender_id} 🔒]: {plaintext}")
                    except Exception as e:
                        print(f"\n[User {sender_id} 🚨]: FAILED TO DECRYPT (Tampered or Wrong Key!)")
            
            # 2. Legacy Stage 3 Message Fallback
            elif "content" in data:
                print(f"\n[User {sender_id} 🔓]: {data['content']}")

    except ConnectionClosed as e:
        print(f"\n[Client] Connection closed by server: {e.code} {e.reason}")

async def send_messages(websocket):
    """Reads terminal input, encrypts it, and sends it to the server."""
    loop = asyncio.get_running_loop()
    
    # Pre-fetch Bob's key so we are ready to encrypt
    shared_key = await get_shared_key(TARGET_USER_ID)
    
    while True:
        message_text = await loop.run_in_executor(None, input, "")
        if not message_text:
            continue

        if not shared_key:
            print("⚠️ Cannot send message: E2EE not established with target user.")
            continue

        # --- ENCRYPTION LOGIC ---
        # Encrypt locally BEFORE sending to FastAPI
        cipertext, nonce = crypto_service.encrypt_message(message_text, shared_key)

        payload = {
            "conversation_id": CONVERSATION_ID,
            "target_user_id": TARGET_USER_ID,
            "cipertext": cipertext,
            "nonce": nonce,
            "key_version": 1
        }
        await websocket.send(json.dumps(payload))

async def heartbeat(websocket):
    """Sends a ping every 10 seconds to keep the connection alive."""
    while True:
        await asyncio.sleep(10)
        try:
            await websocket.send(json.dumps({"type": "ping"}))
        except ConnectionClosed:
            break

async def connect_with_retry():
    retry_delay = 1.0
    while True:
        try:
            print("[Client] Attempting to connect to the server...")
            async with websockets.connect(WS_URL) as websocket:
                print("[Client] Successfully connected! 🟢")
                retry_delay = 1.0 
                
                receive_task = asyncio.create_task(receive_messages(websocket))
                send_task = asyncio.create_task(send_messages(websocket))
                heartbeat_task = asyncio.create_task(heartbeat(websocket))

                done, pending = await asyncio.wait(
                    [receive_task, send_task, heartbeat_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                    
        except Exception as e:
            print(f"[Client] 🔴 Disconnected. Reconnecting in {retry_delay:.2f} seconds...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, 30.0)

async def start_client():
    await register_public_key()
    await connect_with_retry()

if __name__ == "__main__":
    try:
        asyncio.run(start_client())
    except KeyboardInterrupt:
        print("\n[Client] Exiting...")