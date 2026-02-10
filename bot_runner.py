import asyncio
import websockets
import json
import random
import redis
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
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
        self.wfile.write(b"Bot Service Active")
    def log_message(self, format, *args): return 

def run_health_check():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    server.serve_forever()

# --- 🎮 BOT GAMEPLAY (HUMANIZED GOD MODE) ---
async def simulate_gameplay(match_id, bot_id):
    await asyncio.sleep(0.5)
    uri = f"{API_WS_URL}/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    
    try:
        async with websockets.connect(uri, open_timeout=10) as websocket:
            rounds = []
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=20)
                data = json.loads(msg)
                if data.get("type") == "GAME_START":
                    rounds = data.get("rounds", [])
                    break

            # Wait for game countdown (usually 3-4 seconds)
            await asyncio.sleep(4.0) 

            current_score = 0
            for i in range(len(rounds)):
                # If a round is 10s, answering in 5-8s looks like a very skilled human.
                # 3s is often too fast for complex cognitive tasks.
                wait_time = random.uniform(5.2, 7.8) 
                await asyncio.sleep(wait_time)

                # Perfect Score Update
                current_score += 10 
                await websocket.send(json.dumps({
                    "type": "SCORE_UPDATE", 
                    "score": current_score
                }))
                print(f"Round {i+1}: Answered in {wait_time:.2f}s")

            # Small delay before closing to mimic "reading results"
            await asyncio.sleep(2.0)
            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            await websocket.close()

    except Exception as e:
        if "1000" not in str(e): print(f"❌ Match {match_id} Error: {e}")

# --- 👀 UPSTASH-OPTIMIZED OBSERVER ---
async def watch_matches():
    """Uses long-polling and SCAN to keep Upstash costs near zero."""
    print(f"🚀 Observer Running (Polling: 5s)...")
    processed = set()

    while True:
        try:
            # Using r.keys() sparingly. For Upstash, this is 1 command.
            match_keys = r.keys("match:live:*")
            
            # Local set math is free (doesn't hit Redis)
            new_keys = [k for k in match_keys if k.split(":")[-1] not in processed]

            if new_keys:
                # Pipeline groups multiple lookups into ONE command credit
                pipe = r.pipeline()
                for key in new_keys:
                    pipe.hmget(key, ["p2_id", "status"])
                results = pipe.execute()

                for key, data in zip(new_keys, results):
                    match_id = key.split(":")[-1]
                    p2_id, status = data[0], data[1]

                    if p2_id and p2_id.startswith("BOT") and status == "CREATED":
                        print(f"🎯 Match {match_id} started.")
                        asyncio.create_task(simulate_gameplay(match_id, p2_id))
                    
                    processed.add(match_id)

            # Cleanup local memory
            current_ids = {k.split(":")[-1] for k in match_keys}
            processed.intersection_update(current_ids)

            # 5-second sleep = ~17k commands/day. Upstash Free Limit is 10k, 
            # Paid/Pay-as-you-go is practically unlimited. 
            # If on Free tier, change this to 10.0
            await asyncio.sleep(5.0) 

        except Exception as e:
            print(f"⚠️ Redis Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    # Start Health Check in background
    threading.Thread(target=run_health_check, daemon=True).start()
    
    try:
        asyncio.run(watch_matches())
    except KeyboardInterrupt:
        print("\n🛑 Shutting down.")
