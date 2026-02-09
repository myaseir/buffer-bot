import asyncio
import websockets
import json
import random
import redis
import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
API_WS_URL = os.getenv("API_WS_URL") 
BOT_SECRET_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# Initialize Redis client
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- 🧹 THE KILL SWITCH (CLEANER) ---
def run_redis_janitor():
    """Wipes active matches and queues on startup to prevent ghosting."""
    print("🧹 Starting Redis Janitor...")
    try:
        match_keys = r.keys("match:live:*")
        notify_keys = r.keys("notify:*")
        pool_key = "matchmaking_pool"
        if match_keys: r.delete(*match_keys)
        if notify_keys: r.delete(*notify_keys)
        if r.exists(pool_key): r.delete(pool_key)
        print(f"✨ Redis Cleaned. Removed {len(match_keys)} old matches.")
    except Exception as e:
        print(f"⚠️ Janitor Error: {e}")

# --- 🌐 RENDER HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"BrainBuffer Bot Scaling Service is Online")

    def log_message(self, format, *args):
        return 

def run_health_check():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"📡 Health Check server listening on port {PORT}")
    httpd.serve_forever()

# --- 🎮 BOT GAMEPLAY LOGIC (Unchanged) ---
async def simulate_gameplay(match_id, bot_id):
    """Handles a single match with balanced speed and result capture."""
    await asyncio.sleep(1.0)
    uri = f"{API_WS_URL}/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    
    try:
        async with websockets.connect(uri, open_timeout=15) as websocket:
            print(f"✅ {bot_id} joined Match {match_id}")

            # 1. Wait for Start Signal
            rounds = []
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=25)
                data = json.loads(msg)
                if data.get("type") == "GAME_START":
                    rounds = data.get("rounds", [])
                    print(f"🕹️ {bot_id} vs Human | {len(rounds)} Rounds | Start!")
                    break

            # 2. Countdown Stalling
            await asyncio.sleep(4.0) 

            # 3. Balanced Gameplay Loop
            current_score = 0
            accuracy = 0.88 
            
            for i in range(len(rounds)):
                await asyncio.sleep(random.uniform(1.2, 2.2))

                if random.random() < accuracy:
                    current_score += 10 
                    await websocket.send(json.dumps({
                        "type": "SCORE_UPDATE", 
                        "score": current_score
                    }))

            # 4. Finalize & Wait for Backend
            print(f"⌛ {bot_id} finished rounds. Requesting results...")
            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            
            try:
                while True:
                    res_msg = await asyncio.wait_for(websocket.recv(), timeout=20)
                    res_data = json.loads(res_msg)
                    
                    if res_data.get("type") == "RESULT":
                        status = res_data.get("status")
                        op_name = res_data.get("opponent_name", "Human")
                        my_final = res_data.get("my_score", 0)
                        op_final = res_data.get("op_score", 0)

                        print("\n" + "█"*45)
                        print(f"🏁 MATCH FINISHED: {match_id}")
                        print(f"🤖 {bot_id} Score: {my_final}")
                        print(f"👤 {op_name} Score: {op_final}")
                        print("█"*45 + "\n")
                        break
            except Exception as e:
                print(f"ℹ️ {bot_id} result listener timed out: {e}")

            await websocket.close()

    except Exception as e:
        if "1000" not in str(e): 
            print(f"❌ Match {match_id} Error: {e}")

# --- 👀 THE OPTIMIZED OBSERVER LOOP ---
async def watch_matches():
    """Polls Redis efficiently using Pipelines and Throttling."""
    print(f"🚀 Scaling Mode: Listening for human-led matches...")
    
    # Track matches locally to avoid re-querying Redis for the same match
    processed = set()

    while True:
        try:
            # 1. GET KEYS (1 Command)
            match_keys = r.keys("match:live:*")
            
            # 2. LOCAL FILTER (0 Commands)
            # Only ask Redis about keys we haven't seen before
            new_keys = [k for k in match_keys if k.split(":")[-1] not in processed]

            if new_keys:
                # 3. PIPELINE FETCH (1 Batch Command)
                # Instead of looping and sending 10 requests, we send 1 request for 10 items.
                pipe = r.pipeline()
                for key in new_keys:
                    # hmget is cheaper/faster than hgetall
                    pipe.hmget(key, ["p2_id", "status"])
                
                results = pipe.execute()

                # 4. Process Results
                for key, data in zip(new_keys, results):
                    match_id = key.split(":")[-1]
                    p2_id = data[0]
                    status = data[1]

                    if p2_id and p2_id.startswith("BOT") and status == "CREATED":
                        print(f"🎯 Human Found! Match {match_id} assigned to {p2_id}")
                        asyncio.create_task(simulate_gameplay(match_id, p2_id))
                    
                    # Mark as processed so we don't fetch it again
                    processed.add(match_id)

            # 5. SMART CLEANUP
            # If a match is deleted from Redis (game over), remove it from our local 'processed' list
            # This prevents memory leaks without needing to wipe the list constantly
            current_live_ids = {k.split(":")[-1] for k in match_keys}
            processed.intersection_update(current_live_ids)

            # 6. THROTTLE (Saves Cost)
            # Sleep 2.0s instead of 0.5s. Reduces idle command usage by 75%.
            await asyncio.sleep(2.0) 

        except Exception as e:
            print(f"⚠️ Service Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    run_redis_janitor()
    
    health_thread = threading.Thread(target=run_health_check, daemon=True)
    health_thread.start()
    
    print("🚀 Starting BrainBuffer Bot Service (Optimized)...")
    try:
        asyncio.run(watch_matches())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by User.")
    except Exception as e:
        print(f"💥 Fatal Error: {e}")