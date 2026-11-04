import asyncio
import websockets
import json
import random

# TODO: Paste the exact JWT token you use for Alice in Postman right here
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkzODIzMTk0fQ.qMvbXiWNY08rpfkmMa9dVHRv5FX1RkJGlawXWmpfoek"
WS_URL = f"ws://127.0.0.1:8001/ws/chat?token={TOKEN}"

async def heartbeat(websocket):
    """Sends a ping every 10 seconds to keep the connection alive."""
    try:
        while True:
            await asyncio.sleep(10)
            ping_msg = json.dumps({"type": "ping"})
            await websocket.send(ping_msg)
            print("[Client] Sent: ping")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[Client] Heartbeat stopped: {e}")

async def listen(websocket):
    """Listens for incoming messages from the server."""
    try:
        async for message in websocket:
            print(f"[Client] Received: {message}")
            
            # If we receive a ping/pong, we don't necessarily need to alert the user
            # but it proves our connection is alive!
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[Client] Connection closed by server: {e}")

"""
To prevent this, clients use Exponential Backoff with Jitter.

Exponential Backoff: If the first retry fails, wait 1 second. If that fails, wait 2 seconds, then 4, then 8, up to a maximum 
(like 16 seconds).

Jitter: Add a random fraction of a second (e.g., + 0.34s) to the delay so that no two clients retry at the exact same time.

"""

async def connect_with_retry():
    """Connects to the server and handles automatic reconnection with Backoff + Jitter."""
    base_delay = 1
    max_delay = 16

    while True:
        try:
            print(f"[Client] Attempting to connect to the server...")
            async with websockets.connect(WS_URL) as websocket:
                print("[Client] Successfully connected! 🟢")
                
                # Reset our backoff delay because we successfully connected
                base_delay = 1
                
                # Start the heartbeat in the background
                heartbeat_task = asyncio.create_task(heartbeat(websocket))
                
                # Block here and listen for messages until the socket dies
                await listen(websocket)
                
                # If listen() finishes, the socket died. Cancel the heartbeat.
                heartbeat_task.cancel()

        except (websockets.exceptions.WebSocketException, ConnectionRefusedError, OSError) as e:
            print(f"[Client] Connection failed or dropped: {e}")
        
        # --- EXPONENTIAL BACKOFF + JITTER ---
        jitter = random.uniform(0, 0.5) # Add between 0 and 0.5 seconds of randomness
        delay = base_delay + jitter
        print(f"[Client] 🔴 Reconnecting in {delay:.2f} seconds...\n")
        
        await asyncio.sleep(delay)
        
        # Double the delay for the next failure, but cap it at max_delay (16s)
        base_delay = min(base_delay * 2, max_delay)

if __name__ == "__main__":
    if TOKEN == "PASTE_ALICE_TOKEN_HERE":
        print("ERROR: Please paste Alice's JWT token into the TOKEN variable in client/main.py!")
    else:
        asyncio.run(connect_with_retry())



"""
asyncio.create_task(heartbeat(websocket)) spawns a background thread that automatically fires our {"type": "ping"} every 10 seconds. You no longer have to type it manually!

The while True: loop inside connect_with_retry ensures the script never gives up if it gets disconnected. It just catches the error, calculates the exponential delay (base_delay * 2), sleeps, and loops back to try again.
"""