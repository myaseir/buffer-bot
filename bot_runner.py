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

REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
API_WS_URL = os.getenv("API_WS_URL") 
BOT_SECRET_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# Enhanced Connection for unstable local networks
r = redis.from_url(
    REDIS_URL, 
    decode_responses=True,
    socket_connect_timeout=20, # Give it plenty of time to resolve DNS
    retry_on_timeout=True,
    health_check_interval=30
)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brain Buffer: God-Mode Multi-Bot Service Active")
    def log_message(self, format, *args): return 

def run_health_check():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    server.serve_forever()

async def play_as_god_bot(match_id, bot_id):
    uri = f"{API_WS_URL}/match/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    try:
        async with websockets.connect(uri, open_timeout=20) as websocket:
            print(f"🤖 {bot_id} entered Arena: {match_id}")
            rounds = []
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=45)
                data = json.loads(msg)
                if data.get("type") == "GAME_START":
                    rounds = data.get("rounds", [])
                    break

            await asyncio.sleep(4.2) 

            current_score = 0
            for i in range(len(rounds)):
                # God-Mode Rhythm
                delay = random.uniform(3.5, 5.0) if random.random() < 0.20 else random.uniform(1.2, 1.9)
                await asyncio.sleep(delay)

                current_score += 10 
                await websocket.send(json.dumps({"type": "SCORE_UPDATE", "score": current_score}))
                
                # Update Redis
                r.hset(f"match:live:{match_id}", mapping={
                    f"score:{bot_id}": str(current_score),
                    f"last_seen:{bot_id}": str(time.time())
                })
                
            await asyncio.sleep(1.0)
            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            print(f"🏆 {bot_id} Finished Unbeaten in {match_id}")
    except Exception as e:
        print(f"❌ {bot_id} Error: {e}")

async def watch_and_scale():
    print(f"🚀 Scaling Mode: Monitoring all Bots in the DB...")
    active_matches = set()
    while True:
        try:
            # Check connection first
            r.ping() 
            
            match_keys = [k for k in r.scan_iter("match:live:*")]
            pending_keys = [k for k in match_keys if k.split(":")[-1] not in active_matches]

            if pending_keys:
                pipe = r.pipeline()
                for key in pending_keys:
                    pipe.hmget(key, "p2_id", "status")
                results = pipe.execute()

                for key, data in zip(pending_keys, results):
                    match_id = key.split(":")[-1]
                    if not data or len(data) < 2: continue
                    p2_id, status = data[0], data[1]

                    if p2_id and str(p2_id).startswith("BOT") and status == "CREATED":
                        active_matches.add(match_id)
                        asyncio.create_task(play_as_god_bot(match_id, p2_id))
            
            current_ids = {k.split(":")[-1] for k in match_keys}
            active_matches.intersection_update(current_ids)
            await asyncio.sleep(4.0) 
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            print("⏳ Network unstable... retrying in 10s")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"⚠️ Observer Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    try:
        asyncio.run(watch_and_scale())
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")