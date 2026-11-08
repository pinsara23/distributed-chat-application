import asyncio
import websockets
import httpx
import json
import random

# TODO: Paste Alice's token here!
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwiZXhwIjoxNzk0MTczNzcwfQ.upFn9oXuTgU0V4irXmSUokvcjXDtr9D52movIsVPa-Y"
WS_URL = f"ws://127.0.0.1:8001/ws/chat?token={TOKEN}"
REST_URL = "http://127.0.0.1:8001"

# --- NEW: State Tracking ---
last_message_id = 0
conversation_id = 1 # Assuming we are testing conversation 1
# ---------------------------

async def heartbeat(websocket):
    try:
        while True:
            await asyncio.sleep(10)
            await websocket.send(json.dumps({"type": "ping"}))
    except Exception:
        pass

async def sync_missed_messages():
    """Fetches messages missed while the client was disconnected."""
    global last_message_id
    url = f"{REST_URL}/conversations/{conversation_id}/messages?after_id={last_message_id}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            messages = response.json()
            if messages:
                print(f"\n[Client] 🔄 Synced {len(messages)} missed messages!")
                for msg in messages:
                    print(f"   -> Recovered DB Message: {msg['content']}")
                    # Update our cursor to the latest fetched message
                    last_message_id = max(last_message_id, msg["id"])
                print()

async def listen(websocket):
    global last_message_id
    try:
        async for message in websocket:
            data = json.loads(message)
            
            # Hide pongs to keep terminal clean
            if data.get("type") == "pong":
                continue 
                
            print(f"[Client] Live WebSocket Message: {data.get('content')}")
            
            # Update our cursor when a live message arrives!
            if "id" in data:
                last_message_id = max(last_message_id, data["id"])
                
    except websockets.exceptions.ConnectionClosed:
        pass

async def connect_with_retry():
    base_delay = 1
    max_delay = 16

    while True:
        try:
            print("[Client] Attempting to connect to the server...")
            async with websockets.connect(WS_URL) as websocket:
                print("[Client] Successfully connected! 🟢")
                base_delay = 1
                
                # --- NEW: Fetch missed messages immediately upon reconnecting! ---
                await sync_missed_messages()
                # ---------------------------------------------------------------
                
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

if __name__ == "__main__":
    asyncio.run(connect_with_retry())