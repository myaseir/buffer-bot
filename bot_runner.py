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

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
API_WS_URL = os.getenv("API_WS_URL") 
BOT_SECRET_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# Initialize Redis client
try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    # Test connection immediately
    r.ping()
    print("✅ Connected to Upstash Redis")
except Exception as e:
    print(f"❌ Redis Connection Failed: {e}")
    exit(1) # Stop the script if we can't talk to Redis

# --- 🧹 THE KILL SWITCH (CLEANER) ---
def run_redis_janitor():
    """Wipes active matches and queues on startup to prevent ghosting."""
    print("🧹 Starting Redis Janitor...")
    try:
        # We only use .keys() here because it runs ONCE at startup.
        match_keys = r.keys("match:live:*")
        if match_keys: r.delete(*match_keys)
        
        # Also clean our new worker queue
        r.delete("pending_bot_matches")
        print(f"✨ Redis Cleaned.")
    except Exception as e:
        print(f"⚠️ Janitor Error: {e}")

# --- 🌐 RENDER HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"BrainBuffer Bot Scaling Service is Online")
    def log_message(self, format, *args): return

def run_health_check():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"📡 Health Check server listening on port {PORT}")
    httpd.serve_forever()

# --- 🎮 BOT GAMEPLAY LOGIC ---
async def simulate_gameplay(match_id, bot_id):
    """Handles a single match with balanced speed."""
    uri = f"{API_WS_URL}/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    try:
        async with websockets.connect(uri, open_timeout=15) as websocket:
            print(f"✅ {bot_id} joined Match {match_id}")
            
            # Wait for Start Signal
            rounds = []
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=25)
                data = json.loads(msg)
                if data.get("type") == "GAME_START":
                    rounds = data.get("rounds", [])
                    break

            await asyncio.sleep(4.0) # Countdown sync

            current_score = 0
            for i in range(len(rounds)):
                await asyncio.sleep(random.uniform(1.2, 2.2))
                current_score += 10 
                await websocket.send(json.dumps({"type": "SCORE_UPDATE", "score": current_score}))

            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            print(f"⌛ {bot_id} finished Match {match_id}")
            
    except Exception as e:
        print(f"❌ Match {match_id} Error: {e}")

# --- 👀 THE OBSERVER LOOP (NEW EFFICIENT VERSION) ---
async def watch_matches():
    print(f"🚀 Scaling Mode: Listening for human-led matches via 'pending_bot_matches'...")
    while True:
        try:
            # SPOP is $O(1)$ and won't spam your Upstash logs like .keys() did
            match_id = r.spop("pending_bot_matches")
            
            if match_id:
                match_key = f"match:live:{match_id}"
                data = r.hgetall(match_key)
                p2_id = data.get("p2_id")

                if p2_id and p2_id.startswith("BOT"):
                    print(f"🎯 Human Found! Match {match_id} assigned to {p2_id}")
                    asyncio.create_task(simulate_gameplay(match_id, p2_id))
            
            await asyncio.sleep(1.0) 
        except Exception as e:
            print(f"⚠️ Worker Error: {e}")
            await asyncio.sleep(2)

# --- 🏁 START ENGINE ---
if __name__ == "__main__":
    # 1. Clean up old data
    run_redis_janitor()
    
    # 2. Start Health Check (so Render doesn't kill the app)
    health_thread = threading.Thread(target=run_health_check, daemon=True)
    health_thread.start()
    
    # 3. Start the Bot Worker
    try:
        asyncio.run(watch_matches())
    except KeyboardInterrupt:
        print("🛑 Stopped.")