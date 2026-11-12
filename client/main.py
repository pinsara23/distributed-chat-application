import asyncio
import json
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed
from crypto import crypto_service
import os

# --- CONFIGURATION ---
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzk0NDcyMTgzfQ.Rm3Y-oNbE7D0zVnU2z6HwhvhPzrkEOEw7ZxANHmEA4E" 
USER_ID = 1
TARGET_USER_ID = 2
CONVERSATION_ID = 1

REST_URL = "http://127.0.0.1:8001"
WS_URL = f"ws://127.0.0.1:8001/ws/chat?token={TOKEN}"

# --- STEP 22: TOFU STORAGE ---
KNOWN_HOSTS_FILE = "known_hosts.json"

def load_known_hosts() -> dict:
    if os.path.exists(KNOWN_HOSTS_FILE):
        with open(KNOWN_HOSTS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_known_hosts(hosts_data: dict):
    with open(KNOWN_HOSTS_FILE, "w") as f:
        json.dump(hosts_data, f, indent=4)

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
    """Fetches peer's public key from the server, verifies identity, and derives AES key."""
    if peer_id in shared_keys_cache:
        return shared_keys_cache[peer_id]

    print(f"[Crypto] Fetching Public Key for User {peer_id} from server...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{REST_URL}/keys/{peer_id}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                peer_pem = data["public_key_pem"]
                peer_version = data["key_version"]
                
                new_fingerprint = crypto_service.get_fingerprint(peer_pem)
                
                # --- STEP 22: IDENTITY VERIFICATION (TOFU) ---
                known_hosts = load_known_hosts()
                str_peer_id = str(peer_id)
                
                if str_peer_id in known_hosts:
                    saved_fingerprint = known_hosts[str_peer_id]["fingerprint"]
                    saved_version = known_hosts[str_peer_id]["version"]
                    
                    if new_fingerprint != saved_fingerprint:
                        print("\n🚨🚨🚨 SECURITY ALERT 🚨🚨🚨")
                        print(f"User {peer_id}'s public key has CHANGED (Version {saved_version} -> {peer_version}).")
                        print(f"Old Fingerprint: {saved_fingerprint}")
                        print(f"New Fingerprint: {new_fingerprint}")
                        print("This could be a new device, or a Man-In-The-Middle attack!")
                        
                        loop = asyncio.get_running_loop()
                        accept = await loop.run_in_executor(None, input, "Do you want to trust this new key? (yes/no): ")
                        
                        if accept.strip().lower() != "yes":
                            print("[Crypto] Connection aborted to protect your security.")
                            return None
                        
                        # User accepted the risk, update known hosts
                        known_hosts[str_peer_id] = {"fingerprint": new_fingerprint, "version": peer_version}
                        save_known_hosts(known_hosts)
                        print("[Crypto] New key trusted and saved.")
                else:
                    # First time seeing this user (Trust On First Use)
                    print(f"[Crypto] 🆕 First time connecting with User {peer_id}.")
                    print(f"Saving their fingerprint: {new_fingerprint}")
                    known_hosts[str_peer_id] = {"fingerprint": new_fingerprint, "version": peer_version}
                    save_known_hosts(known_hosts)
                # ---------------------------------------------
                
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
                
                # FIX: If it is our own echoed message, use the Target User's key to decrypt it.
                # If it is a message from someone else, use their key.
                decrypt_target_id = TARGET_USER_ID if sender_id == USER_ID else sender_id
                
                shared_key = await get_shared_key(decrypt_target_id)
                
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