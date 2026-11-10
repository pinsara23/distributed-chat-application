import asyncio
import websockets
import httpx
import json
import random
import aiohttp
from crypto import crypto_service

# TODO: Paste Alice's token here!
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzk0MzQzNTMyfQ.XpYPqQ31P4eWOTPzAm2w0Busvu2BSzAigX64uiEAcsI"
WS_URL = f"ws://127.0.0.1:8000/ws/chat?token={TOKEN}"
REST_URL = "http://127.0.0.1:8000"

last_message_id = 0
conversation_id = 1 

# --- STAGE 4: Client-Side Deduplication Set ---
seen_messages = set()
# ----------------------------------------------

async def heartbeat(websocket):
    try:
        while True:
            await asyncio.sleep(10)
            await websocket.send(json.dumps({"type": "ping"}))
    except Exception:
        pass

async def sync_missed_messages():
    """Fetches and deduplicates missed messages."""
    global last_message_id, seen_messages
    url = f"{REST_URL}/conversations/{conversation_id}/messages?after_id={last_message_id}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            messages = response.json()
            synced_count = 0
            
            for msg in messages:
                msg_id = msg["id"]
                
                # --- DEDUPLICATION CHECK ---
                if msg_id not in seen_messages:
                    seen_messages.add(msg_id)
                    print(f"   -> Recovered DB Message: {msg['content']}")
                    synced_count += 1
                # ---------------------------
                
                # Always update the cursor, even if it was a duplicate
                last_message_id = max(last_message_id, msg_id)
                
            if synced_count > 0:
                print(f"\n[Client] 🔄 Synced {synced_count} unique missed messages!\n")

async def listen(websocket):
    """Listens for live messages and drops duplicates."""
    global last_message_id, seen_messages
    try:
        async for message in websocket:
            data = json.loads(message)
            
            if data.get("type") == "pong":
                continue 
            
            msg_id = data.get("id")
            
            # --- DEDUPLICATION CHECK ---
            if msg_id and msg_id not in seen_messages:
                seen_messages.add(msg_id)
                print(f"[Client] Live WebSocket Message: {data.get('content')}")
                
                last_message_id = max(last_message_id, msg_id)
            elif msg_id:
                print(f"[Client] 🛡️ Blocked duplicate message ID: {msg_id}")
            # ---------------------------
                
    except websockets.exceptions.ConnectionClosed:
        pass


async def register_public_key():
    """Generates local keys and uploads the public key to the server."""
    # 1. Generate or load keys
    crypto_service.load_or_generate_keys()
    
    # 2. Print our Security Fingerprint
    fingerprint = crypto_service.get_fingerprints(crypto_service.public_key_pem)
    print(f"\n==================================================")
    print(f"🔐 MY SECURITY FINGERPRINT:")
    print(f"{fingerprint}")
    print(f"==================================================\n")

    # 3. Upload public key to server
    headers = {"Authorization": f"Bearer {TOKEN}"}
    payload = {"public_key_pem": crypto_service.public_key_pem}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{REST_URL}/keys/", headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"[Client] Public Key (v{data['key_version']}) successfully registered with server.")
                else:
                    print(f"[Client] ⚠️ Failed to register Public Key: {await resp.text()}")
    except Exception as e:
        print(f"[Client] ⚠️ API Connection error: {e}")


async def connect_with_retry():
    base_delay = 1
    max_delay = 16

    while True:
        try:
            print("[Client] Attempting to connect to the server...")
            async with websockets.connect(WS_URL) as websocket:
                print("[Client] Successfully connected! 🟢")
                base_delay = 1
                
                await sync_missed_messages()
                
                heartbeat_task = asyncio.create_task(heartbeat(websocket))
                await listen(websocket)
                heartbeat_task.cancel()

        except Exception:
            pass
        
        jitter = random.uniform(0, 0.5)
        delay = base_delay + jitter
        print(f"[Client] 🔴 Disconnected. Reconnecting in {delay:.2f} seconds...")
        await asyncio.sleep(delay)
        base_delay = min(base_delay * 2, max_delay)


async def start_client():
    await register_public_key()
    await connect_with_retry()

if __name__ == "__main__":
    try:
        asyncio.run(start_client())
    except KeyboardInterrupt:
        print("\n[Client] Exiting...")