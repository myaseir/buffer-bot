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
REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
API_WS_URL = os.getenv("API_WS_URL") 
BOT_SECRET_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

r = redis.from_url(REDIS_URL, decode_responses=True, retry_on_timeout=True, ssl_cert_reqs=None)

# --- 🤖 BOT POOL SETUP ---
BOT_POOL = [f"BOT_{str(i).zfill(3)}" for i in range(1, 21)]
random.shuffle(BOT_POOL)
bot_index = 0

def get_next_bot():
    global bot_index
    bot = BOT_POOL[bot_index]
    bot_index = (bot_index + 1) % len(BOT_POOL)
    if bot_index == 0: random.shuffle(BOT_POOL)
    return bot

# --- 🌐 HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"BrainBuffer Bot: Admin-Controlled Mode")
    def log_message(self, format, *args): return 

def run_health_check():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    server.serve_forever()

# --- 🎮 GAMEPLAY LOGIC ---
async def play_as_god_bot(match_id, bot_id):
    lock_key = f"bot_lock:{match_id}"
    if not r.set(lock_key, bot_id, nx=True, ex=120): return 

    uri = f"{API_WS_URL}/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    match_key = f"match:live:{match_id}"
    headers = {"Origin": "https://brainbufferonline.onrender.com", "User-Agent": f"BB-Bot-{bot_id}"}
    
    websocket = None
    try:
        params = {"open_timeout": 25, "ping_interval": 20, "ping_timeout": 60}
        try:
            websocket = await websockets.connect(uri, additional_headers=headers, **params)
        except TypeError:
            websocket = await websockets.connect(uri, extra_headers=headers, **params)
            
        print(f"✅ {bot_id} entered {match_id[:12]}")

        # 1. Start Detection
        while True:
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=1.5)
                if json.loads(msg).get("type") == "GAME_START": break
            except:
                if r.hexists(match_key, "rounds"): break
                continue

        # 2. Identify Target
        m_data = r.hgetall(match_key)
        p1, p2 = m_data.get("p1_id"), m_data.get("p2_id")
        human_id = p2 if str(p1) == str(bot_id) else p1
        if not human_id: return

        print(f"🔗 {bot_id} vs {human_id[:8]}...")
        await asyncio.sleep(5.0) 

        # 3. Shadow Loop with Global Difficulty Toggle
        current_score = 0
        last_pushed_score = -1
        patience = 0
        
        while True:
            # EFFICIENCY: Read human data AND the Admin's global difficulty key
            # We use a pipeline or multiple gets to check the global toggle
            h_data = r.hmget(match_key, f"score:{human_id}", f"status:{human_id}")
            h_score = int(h_data[0]) if h_data[0] else 0
            h_status = h_data[1]

            # ✅ READ THE ADMIN TOGGLE FROM REDIS
            difficulty = r.get("bot_settings:difficulty") or "god"

            if difficulty == "god":
                # --- 🔥 GOD MODE: UNBEATABLE ---
                if current_score < (h_score + 20):
                    current_score += 10
                    wait_time = 0.3 
                else:
                    wait_time = 1.2 
            else:
                # --- 🧠 HUMAN MODE: CHALLENGING BUT BEATABLE ---
                # Bot mimics a fast human but doesn't cheat with 20pt lead
                if current_score < (h_score - 10):
                    current_score += 10
                    wait_time = random.uniform(2.0, 4.0) # Slower reaction
                else:
                    wait_time = 1.5

            # Sync Score
            if current_score != last_pushed_score:
                await websocket.send(json.dumps({"type": "SCORE_UPDATE", "score": current_score}))
                r.hset(match_key, f"score:{bot_id}", str(current_score))
                last_pushed_score = current_score
                print(f"📡 {bot_id} [{difficulty.upper()}]: {current_score} | Target: {h_score}")

            await asyncio.sleep(wait_time)

            if h_status == "FINISHED": patience += 1
            if h_status == "FINISHED" and patience > 4: break
            if not r.exists(match_key): break

        await asyncio.sleep(0.5)
        await websocket.send(json.dumps({"type": "GAME_OVER"}))
        print(f"🏆 {bot_id} finished match_{match_id[:8]}")

    except Exception as e:
        print(f"❌ {bot_id} Error: {e}")
    finally:
        if websocket: await websocket.close()
        r.delete(lock_key)

# --- 👀 OBSERVER ---
async def watch_and_scale():
    print(f"🚀 Bot Observer Online (Admin-Controlled Mode)")
    active_matches = set()
    while True:
        try:
            match_keys = [k for k in r.scan_iter("match:live:*")]
            for key in match_keys:
                match_id = key.split(":")[-1]
                if match_id not in active_matches:
                    m_data = r.hmget(key, "p2_id", "status")
                    if m_data[0] and str(m_data[0]).startswith("BOT") and m_data[1] == "CREATED":
                        active_matches.add(match_id)
                        asyncio.create_task(play_as_god_bot(match_id, get_next_bot()))
            
            active_matches = {k.split(":")[-1] for k in match_keys if k.split(":")[-1] in active_matches}
            await asyncio.sleep(2.5) 
        except:
            await asyncio.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_health_check, daemon=True).start()
    asyncio.run(watch_and_scale())