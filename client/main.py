import asyncio
import json
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed
from crypto import STATE_PREFIX, crypto_service, build_aad
import os
import getpass
import uuid

# --- CONFIGURATION ---
# Credentials are never stored in source. Set CHAT_USERNAME / CHAT_PASSWORD in
# the environment (or type them when prompted). A fresh JWT is requested on
# every (re)connect, so an expired token can never wedge the client.
USER_ID = int(os.environ.get("CHAT_USER_ID", "1"))
TARGET_USER_ID = int(os.environ.get("CHAT_TARGET_USER_ID", "2"))
CONVERSATION_ID = int(os.environ.get("CHAT_CONVERSATION_ID", "1"))

SERVER_HOST = os.environ.get("CHAT_SERVER_HOST", "localhost:8000")
REST_URL = f"http://{SERVER_HOST}"
WS_BASE_URL = f"ws://{SERVER_HOST}/ws/chat"

TOKEN = None
_CREDENTIALS = None


def _get_credentials() -> tuple[str, str]:
    global _CREDENTIALS
    if _CREDENTIALS is None:
        username = os.environ.get("CHAT_USERNAME") or input("Username: ")
        password = os.environ.get("CHAT_PASSWORD") or getpass.getpass("Password: ")
        _CREDENTIALS = (username, password)
    return _CREDENTIALS


async def login() -> str:
    """Authenticate against /auth/login and store a fresh access token."""
    global TOKEN
    username, password = _get_credentials()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{REST_URL}/auth/login",
            data={"username": username, "password": password},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Login failed: {resp.status} {await resp.text()}")
            TOKEN = (await resp.json())["access_token"]
    print("[Auth] Obtained a fresh access token.")
    return TOKEN


# --- STEP 22: TOFU STORAGE ---
KNOWN_HOSTS_FILE = f"{STATE_PREFIX}_known_hosts.json"

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
MESSAGE_CURSOR_FILE = f"{STATE_PREFIX}_message_cursor.json"

SEEN_HISTORY_LIMIT = 2000   # how many recent message ids are remembered on disk
SYNC_OVERLAP = 500          # re-request this many ids below the cursor on sync


def _load_state() -> dict:
    if not os.path.exists(MESSAGE_CURSOR_FILE):
        return {}
    try:
        with open(MESSAGE_CURSOR_FILE, "r") as f:
            state = json.load(f)
        if state.get("conversation_id") != CONVERSATION_ID:
            return {}
        return state
    except (ValueError, json.JSONDecodeError, OSError):
        return {}


_STATE = _load_state()
LAST_MESSAGE_ID = int(_STATE.get("last_message_id", 0))
# Duplicate suppression is by message id, NOT by "id <= cursor": ids can arrive
# out of order (broker retries), and a late lower id must still be shown.
SEEN_MESSAGE_IDS = {int(i) for i in _STATE.get("seen_ids", [])}


def _save_state():
    recent = sorted(SEEN_MESSAGE_IDS)[-SEEN_HISTORY_LIMIT:]
    with open(MESSAGE_CURSOR_FILE, "w") as f:
        json.dump({
            "conversation_id": CONVERSATION_ID,
            "last_message_id": LAST_MESSAGE_ID,
            "seen_ids": recent,
        }, f, indent=4)


def mark_seen(message_id):
    """Record a processed message and advance the (max-id) sync cursor."""
    global LAST_MESSAGE_ID

    if message_id is None:
        return

    SEEN_MESSAGE_IDS.add(message_id)
    if message_id > LAST_MESSAGE_ID:
        LAST_MESSAGE_ID = message_id
    _save_state()


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
                        
                        accept = await ask_user("Do you want to trust this new key? (yes/no): ")
                        
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

    message_id = data.get("id")
    sender_id = data.get("sender_id")

    # The server echoing our own message back means it is durably stored.
    if sender_id == USER_ID:
        PENDING.pop(data.get("message_uuid"), None)

    if message_id is not None:
        message_id = int(message_id)

        if message_id in SEEN_MESSAGE_IDS:
            return True

    if "ciphertext" in data and "nonce" in data:

        decrypt_target_id = (
            TARGET_USER_ID if sender_id == USER_ID else sender_id
        )

        shared_key = await get_shared_key(decrypt_target_id)

        if not shared_key:
            print(f"[Crypto] Cannot decrypt message {message_id}: key unavailable.")
            return False

        try:
            aad = build_aad(
                data["message_uuid"],
                int(data["conversation_id"]),
                int(sender_id),
            )
            plaintext = crypto_service.decrypt_message(
                data["ciphertext"],
                data["nonce"],
                shared_key,
                aad,
            )

            print(f"\n[User {sender_id} 🔒]: {plaintext}")

        except Exception as e:
            # Authentication failed (tampered or wrong key): this is permanent,
            # so flag it and move on instead of blocking every later message.
            print(f"\n[Crypto] ⚠️ Message {message_id} from User {sender_id} "
                  f"failed authentication and was skipped: {e!r}")
            mark_seen(message_id)
            return True

    else:
        print(f"[Sync] Ignoring message {message_id}: not an E2EE envelope.")

    mark_seen(message_id)

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
                # A permanent rejection of one of our messages: stop resending it.
                failed_id = data.get("message_id")
                if failed_id and not data.get("retryable", False):
                    if PENDING.pop(failed_id, None) is not None:
                        print(f"[Send] Message {failed_id} was rejected and discarded.")
                continue

            await handle_message(data)

    except ConnectionClosed as e:
        print(f"\n[Client] Connection closed: {e.code} {e.reason}")


# --- OUTBOUND QUEUE -----------------------------------------------------------
# Lines typed by the user wait in TEXT_QUEUE (one stdin reader for the whole
# process, independent of the connection). Once encrypted, a message sits in
# PENDING until the server echoes it back, and is re-sent after a reconnect.
# Re-sending is safe: the server treats message_id as an idempotency key.
TEXT_QUEUE: "asyncio.Queue[str] | None" = None
PENDING: dict[str, dict] = {}


async def ask_user(prompt: str) -> str:
    """Ask a question on the terminal.

    Once the stdin reader thread is running it owns stdin, so an answer must
    come through its queue; a second input() call would race it and the answer
    would be sent as a chat message instead.
    """
    print(prompt, end="", flush=True)
    if TEXT_QUEUE is not None:
        return await TEXT_QUEUE.get()
    return await asyncio.get_running_loop().run_in_executor(None, input, "")


def start_stdin_reader(loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[str]"):
    """Read terminal lines on a daemon thread so Ctrl+C / reconnects never hang."""
    import threading

    def run():
        while True:
            try:
                line = input()
            except EOFError:
                return
            if line:
                loop.call_soon_threadsafe(queue.put_nowait, line)

    threading.Thread(target=run, daemon=True, name="stdin-reader").start()


async def prepare_payload(message_text: str) -> dict | None:
    """Encrypt locally BEFORE anything is sent to FastAPI."""
    shared_key = await get_shared_key(TARGET_USER_ID)
    if not shared_key:
        return None

    message_id = str(uuid.uuid4())
    aad = build_aad(message_id, CONVERSATION_ID, USER_ID)
    ciphertext, nonce = crypto_service.encrypt_message(message_text, shared_key, aad)
    return {
        "message_id": message_id,
        "conversation_id": CONVERSATION_ID,
        "target_user_id": TARGET_USER_ID,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "key_version": 1,
    }


async def send_messages(websocket):
    """Re-send unacknowledged messages, then send newly typed ones."""
    for payload in list(PENDING.values()):
        await websocket.send(json.dumps(payload))
        print(f"[Send] Re-sent unacknowledged message {payload['message_id']}.")

    while True:
        message_text = await TEXT_QUEUE.get()
        try:
            payload = await prepare_payload(message_text)
        except asyncio.CancelledError:
            TEXT_QUEUE.put_nowait(message_text)  # do not lose the line on reconnect
            raise

        if payload is None:
            print("⚠️ Cannot send message: E2EE not established with target user.")
            continue

        PENDING[payload["message_id"]] = payload  # kept until the server echoes it
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

            await login()  # re-authenticate on every (re)connect
            ws_url = f"{WS_BASE_URL}?token={TOKEN}"

            async with websockets.connect(ws_url) as websocket:
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
                f"[Client] 🔴 Disconnected ({e}). "
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
            # Overlap the cursor so late (out-of-order) lower ids are re-fetched;
            # already-seen ids are filtered out by handle_message.
            params = {"after_id": max(1, LAST_MESSAGE_ID - SYNC_OVERLAP)}

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
    global TEXT_QUEUE
    TEXT_QUEUE = asyncio.Queue()
    start_stdin_reader(asyncio.get_running_loop(), TEXT_QUEUE)

    await login()
    await register_public_key()
    await connect_with_retry()

if __name__ == "__main__":
    try:
        # Ask for credentials BEFORE the event loop exists: calling input() or
        # getpass inside a running asyncio loop can crash the interpreter on Windows.
        _get_credentials()
        asyncio.run(start_client())
    except KeyboardInterrupt:
        print("\n[Client] Exiting...")