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

load_dotenv()

# --- CONFIGURATION ---
# Use UPSTASH_REDIS_REST_URL for the redis-py client if not using the REST wrapper
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("REDIS_URL")
API_WS_URL = os.getenv("API_WS_URL") 
BOT_SECRET_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# Connection with retry logic for Upstash stability
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- 🌐 HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brain Buffer Bot Service Active")
    def log_message(self, format, *args): return 

def run_health_check():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    print(f"📡 Health check server running on port {PORT}")
    server.serve_forever()

# --- 🎮 BOT GAMEPLAY (HUMANIZED SKILL) ---
async def simulate_gameplay(match_id, bot_id):
    """
    Connects to the match via WebSocket and simulates a human player.
    """
    await asyncio.sleep(0.5)
    # Standardized match URL structure
    uri = f"{API_WS_URL}/match/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    
    try:
        async with websockets.connect(uri, open_timeout=15) as websocket:
            rounds = []
            # 1. Wait for Game Start Signal
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=30)
                data = json.loads(msg)
                if data.get("type") == "GAME_START":
                    rounds = data.get("rounds", [])
                    break

            # 2. Wait for UI countdown (3-4 seconds)
            await asyncio.sleep(4.2) 

            current_score = 0
            for i in range(len(rounds)):
                # 3. Humanized Delay: Skilled but not instant (5.2s - 7.5s)
                wait_time = random.uniform(5.2, 7.5) 
                await asyncio.sleep(wait_time)

                # 4. Score Logic: 10 points per round
                current_score += 10 
                
                # Update WebSocket score
                await websocket.send(json.dumps({
                    "type": "SCORE_UPDATE", 
                    "score": current_score
                }))
                
                # Update Redis Heartbeat (Stringified for Upstash compatibility)
                # Note: We use values={} dictionary for Upstash compatibility
                match_key = f"match:live:{match_id}"
                r.hset(match_key, mapping={
                    f"score:{bot_id}": str(current_score),
                    f"last_seen:{bot_id}": str(time.time())
                })
                
                print(f"Match {match_id} | Round {i+1}: Bot scored. Total: {current_score}")

            # 5. Finalize
            await asyncio.sleep(1.5)
            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            print(f"✅ Match {match_id} completed by Bot.")

    except Exception as e:
        if "1000" not in str(e): 
            print(f"❌ Match {match_id} Error: {e}")

# --- 👀 UPSTASH-OPTIMIZED OBSERVER ---
async def watch_matches():
    """
    Polls Redis to find matches where Player 2 is a BOT and status is CREATED.
    """
    print(f"🚀 Brain Buffer Bot Observer Running...")
    processed = set()

    while True:
        try:
            # Get all live match keys
            match_keys = r.keys("match:live:*")
            
            # Filter for keys we haven't seen in this session
            new_keys = [k for k in match_keys if k.split(":")[-1] not in processed]

            if new_keys:
                pipe = r.pipeline()
                for key in new_keys:
                    pipe.hmget(key, ["p2_id", "status"])
                results = pipe.execute()

                for key, data in zip(new_keys, results):
                    match_id = key.split(":")[-1]
                    # Upstash might return None or empty lists
                    if not data or len(data) < 2:
                        continue
                        
                    p2_id, status = data[0], data[1]

                    # Trigger bot if P2 is a BOT and match is just created
                    if p2_id and str(p2_id).startswith("BOT") and status == "CREATED":
                        print(f"🎯 Bot {p2_id} assigned to Match {match_id}")
                        asyncio.create_task(simulate_gameplay(match_id, p2_id))
                    
                    processed.add(match_id)

            # Cleanup 'processed' set to prevent memory leaks
            current_ids = {k.split(":")[-1] for k in match_keys}
            processed.intersection_update(current_ids)

            # Polling frequency (5s for balanced performance/cost)
            await asyncio.sleep(5.0) 

        except Exception as e:
            print(f"⚠️ Redis Observer Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    # Start Health Check for Render/Deployment
    threading.Thread(target=run_health_check, daemon=True).start()
    
    try:
        asyncio.run(watch_matches())
    except KeyboardInterrupt:
        print("\n🛑 Bot Service Shutting down.")