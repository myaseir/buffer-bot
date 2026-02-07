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
# Render provides the PORT environment variable automatically
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

# --- 🌐 RENDER HEALTH CHECK (For Web Service Tier) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"BrainBuffer Bot Scaling Service is Online")

    def log_message(self, format, *args):
        return # Keep console clean by not logging every ping

def run_health_check():
    """Runs a tiny HTTP server so Render knows the service is alive."""
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"📡 Health Check server listening on port {PORT}")
    httpd.serve_forever()

# --- 🎮 BOT GAMEPLAY LOGIC ---
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

            # 2. Countdown Stalling (Sync with Human UI)
            await asyncio.sleep(4.0) 

            # 3. Balanced Gameplay Loop
            current_score = 0
            accuracy = 0.88 
            
            for i in range(len(rounds)):
                # Balanced speed: 1.2s to 2.2s per update
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
            
            # 🚀 RESULT LISTENER
            try:
                # We wait 20 seconds to allow Render's DB to update and send the payout
                while True:
                    res_msg = await asyncio.wait_for(websocket.recv(), timeout=20)
                    res_data = json.loads(res_msg)
                    
                    # Log message type for debugging
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

# --- 👀 THE OBSERVER LOOP ---
async def watch_matches():
    print(f"🚀 Scaling Mode: Listening for human-led matches...")
    while True:
        try:
            # 1. Pop a match ID from the set (Atomic and Fast)
            match_id = r.spop("pending_bot_matches")
            
            if match_id:
                # 2. Get the match data directly by its key
                match_key = f"match:live:{match_id}"
                data = r.hgetall(match_key)
                
                p2_id = data.get("p2_id")
                status = data.get("status")

                if p2_id and p2_id.startswith("BOT") and status == "CREATED":
                    print(f"🎯 Human Found! Match {match_id} assigned to {p2_id}")
                    asyncio.create_task(simulate_gameplay(match_id, p2_id))
            
            # 3. You can keep this sleep or even lower it slightly 
            # because SPOP is much lighter than KEYS.
            await asyncio.sleep(1.0) 
        except Exception as e:
            print(f"⚠️ Service Error: {e}")
            await asyncio.sleep(2)