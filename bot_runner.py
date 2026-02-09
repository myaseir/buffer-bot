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

            rounds = []
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=25)
                data = json.loads(msg)
                if data.get("type") == "GAME_START":
                    rounds = data.get("rounds", [])
                    print(f"🕹️ {bot_id} vs Human | {len(rounds)} Rounds | Start!")
                    break

            await asyncio.sleep(4.0) 

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

            print(f"⌛ {bot_id} finished rounds. Requesting results...")
            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            
            try:
                while True:
                    res_msg = await asyncio.wait_for(websocket.recv(), timeout=20)
                    res_data = json.loads(res_msg)
                    
                    if res_data.get("type") != "SCORE_UPDATE":
                        print(f"📩 Incoming Signal: {res_data.get('type')}")
                    
                    if res_data.get("type") == "RESULT":
                        status = res_data.get("status")
                        op_name = res_data.get("opponent_name", "Human")
                        my_final = res_data.get("my_score", 0)
                        op_final = res_data.get("op_score", 0)

                        print("\n" + "█"*45)
                        print(f"🏁 MATCH FINISHED: {match_id}")
                        print(f"🤖 {bot_id} Score: {my_final}")
                        print(f"👤 {op_name} Score: {op_final}")
                        
                        if status == "WON":
                            print(f"🏆 RESULT: BOT WON")
                        elif status == "LOST":
                            print(f"🏆 RESULT: HUMAN WON")
                        else:
                            print("🤝 RESULT: DRAW")
                        print("█"*45 + "\n")
                        break
            except Exception as e:
                print(f"ℹ️ {bot_id} result listener timed out or closed: {e}")

            await websocket.close()

    except Exception as e:
        if "1000" not in str(e): 
            print(f"❌ Match {match_id} Error: {e}")

# --- 👀 THE OPTIMIZED OBSERVER LOOP ---
async def watch_matches():
    """Polls Redis efficiently using Pipelines to save bandwidth/costs."""
    print(f"🚀 Scaling Mode: Listening for human-led matches...")
    
    # Track matches we have already handled to avoid re-querying Redis
    processed = set()

    while True:
        try:
            # 1. Fetch all keys (1 Command)
            match_keys = r.keys("match:live:*")
            
            # 2. Filter locally (0 Commands)
            # Find keys that we haven't processed yet
            new_keys = [k for k in match_keys if k.split(":")[-1] not in processed]

            if new_keys:
                # 3. PIPELINE FETCH (1 Command for ALL new keys)
                # Instead of sending 10 requests for 10 matches, we send 1.
                pipe = r.pipeline()
                for key in new_keys:
                    # hmget is cheaper than hgetall (fetches only needed fields)
                    pipe.hmget(key, ["p2_id", "status"])
                
                results = pipe.execute()

                # 4. Process Results
                for key, data in zip(new_keys, results):
                    match_id = key.split(":")[-1]
                    p2_id = data[0]
                    status = data[1]

                    # If it's a new match waiting for a bot
                    if p2_id and p2_id.startswith("BOT") and status == "CREATED":
                        print(f"🎯 Human Found! Match {match_id} assigned to {p2_id}")
                        asyncio.create_task(simulate_gameplay(match_id, p2_id))
                    
                    # Add to processed so we don't fetch it again
                    processed.add(match_id)

            # 5. Smart Cleanup (Pure Python)
            # Remove IDs from 'processed' that are no longer in Redis (matches deleted by backend)
            # This prevents memory leaks without the need to "wipe and re-read" everything
            current_live_ids = {k.split(":")[-1] for k in match_keys}
            processed.intersection_update(current_live_ids)

            # 6. Throttling (Saves Cost)
            # Increased from 0.5s to 2.0s. 
            # This reduces idle command usage by 4x.
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