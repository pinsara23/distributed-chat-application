import asyncio
import json
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed
from crypto import crypto_service
import os

# --- CONFIGURATION ---
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzk0NTExMzU1fQ.pcVxjYesPcpv4r7qPAOrmDGjADH44gzquH39B_M1e6g" 
USER_ID = 1
TARGET_USER_ID = 2
CONVERSATION_ID = 1

SERVER_IP = "localhost"
REST_URL = f"http://{SERVER_IP}:8000"
WS_URL = f"ws://{SERVER_IP}:8000/ws/chat?token={TOKEN}"

# SERVER_IP = "192.168.43.47"
# REST_URL = f"http://{SERVER_IP}"
# WS_URL = f"ws://{SERVER_IP}/ws/chat?token={TOKEN}"

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
MESSAGE_CURSOR_FILE = "alice_message_cursor.json"

def load_message_cursor():
    if not os.path.exists(MESSAGE_CURSOR_FILE):
        return 0

    try:
        with open(MESSAGE_CURSOR_FILE, "r") as f:
            state = json.load(f)

        if state.get("conversation_id") != CONVERSATION_ID:
            return 0

        return int(state.get("last_message_id", 0))

    except (ValueError, json.JSONDecodeError, OSError):
        return 0


LAST_MESSAGE_ID = load_message_cursor()
SEEN_MESSAGE_IDS = set()


def update_message_cursor(message_id):
    global LAST_MESSAGE_ID

    if message_id is None or message_id <= LAST_MESSAGE_ID:
        return

    LAST_MESSAGE_ID = message_id

    with open(MESSAGE_CURSOR_FILE, "w") as f:
        json.dump({
            "conversation_id": CONVERSATION_ID,
            "last_message_id": LAST_MESSAGE_ID
        }, f, indent=4)

async def register_public_key():
    """Loads local identity and registers its public key with the server."""
    crypto_service.load_or_generate_keys()

    headers = {"Authorization": f"Bearer {TOKEN}"}
    payload = {"public_key_pem": crypto_service.public_key_pem}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{REST_URL}/keys/",
            json=payload,
            headers=headers
        ) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(
                    f"Public key registration failed: {resp.status} "
                    f"{await resp.text()}"
                )

            print("[Crypto] Public key registered successfully.")

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


async def handle_message(data):
    """Decrypts and displays a message, ignoring already processed messages."""

    global LAST_MESSAGE_ID

    message_id = data.get("id")
    sender_id = data.get("sender_id")

    if message_id is not None:
        message_id = int(message_id)

        if message_id <= LAST_MESSAGE_ID:
            return True

        if message_id in SEEN_MESSAGE_IDS:
            return True

    if "cipertext" in data and "nonce" in data:

        decrypt_target_id = (
            TARGET_USER_ID if sender_id == USER_ID else sender_id
        )

        shared_key = await get_shared_key(decrypt_target_id)

        if not shared_key:
            print(f"[Crypto] Cannot decrypt message {message_id}: key unavailable.")
            return False

        try:
            plaintext = crypto_service.decrypt_message(
                data["cipertext"],
                data["nonce"],
                shared_key
            )

            print(f"\n[User {sender_id} 🔒]: {plaintext}")

        except Exception as e:
            print(f"\n[Crypto] Failed to decrypt message {message_id}: {e}")
            return False

    elif "content" in data:
        print(f"\n[User {sender_id}]: {data['content']}")

    else:
        return False

    if message_id is not None:
        SEEN_MESSAGE_IDS.add(message_id)
        update_message_cursor(message_id)

    return True

async def receive_messages(websocket):
    """Receives live messages and decrypts them."""

    try:
        while True:
            response = await websocket.recv()
            data = json.loads(response)

            if data.get("type") == "pong":
                continue

            if "error" in data:
                print(f"[Server Error]: {data['error']}")
                continue

            await handle_message(data)

    except ConnectionClosed as e:
        print(f"\n[Client] Connection closed: {e.code} {e.reason}")

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

                # Retrieve messages missed while offline
                await sync_missed_messages()

                receive_task = asyncio.create_task(receive_messages(websocket))
                send_task = asyncio.create_task(send_messages(websocket))
                heartbeat_task = asyncio.create_task(heartbeat(websocket))

                done, pending = await asyncio.wait(
                    [receive_task, send_task, heartbeat_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

                await asyncio.gather(*pending, return_exceptions=True)

        except Exception as e:
            print(
                f"[Client] 🔴 Disconnected. "
                f"Reconnecting in {retry_delay:.2f} seconds..."
            )

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, 30.0)
            
async def sync_missed_messages():
    """Retrieves messages missed while this client was offline."""

    headers = {"Authorization": f"Bearer {TOKEN}"}

    print("\n[Sync] Checking for missed messages...")

    async with aiohttp.ClientSession() as session:

        if LAST_MESSAGE_ID > 0:
            params = {"after_id": LAST_MESSAGE_ID}

            async with session.get(
                f"{REST_URL}/conversations/{CONVERSATION_ID}/messages",
                headers=headers,
                params=params
            ) as resp:

                if resp.status != 200:
                    raise RuntimeError(
                        f"History retrieval failed: {resp.status} "
                        f"{await resp.text()}"
                    )

                messages = await resp.json()

                for message in messages:
                    if not await handle_message(message):
                        print("[Sync] Stopped because a message could not be decrypted.")
                        return

        else:
            # First synchronization: retrieve all pages.
            page = 1
            limit = 50

            while True:
                params = {"page": page, "limit": limit}

                async with session.get(
                    f"{REST_URL}/conversations/{CONVERSATION_ID}/messages",
                    headers=headers,
                    params=params
                ) as resp:

                    if resp.status != 200:
                        raise RuntimeError(
                            f"History retrieval failed: {resp.status} "
                            f"{await resp.text()}"
                        )

                    messages = await resp.json()

                if not messages:
                    break

                for message in messages:
                    if not await handle_message(message):
                        print("[Sync] Stopped because a message could not be decrypted.")
                        return

                if len(messages) < limit:
                    break

                page += 1

    print(f"[Sync] Synchronization complete. Last message ID: {LAST_MESSAGE_ID}")

async def start_client():
    await register_public_key()
    await connect_with_retry()

if __name__ == "__main__":
    try:
        asyncio.run(start_client())
    except KeyboardInterrupt:
        print("\n[Client] Exiting...")