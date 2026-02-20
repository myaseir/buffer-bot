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

r = redis.from_url(REDIS_URL, decode_responses=True, retry_on_timeout=True, ssl_cert_reqs=None)

# Global loop to handle bot tasks triggered by HTTP
bot_loop = asyncio.new_event_loop()

# --- 🤖 BOT POOL SETUP ---
BOT_POOL = [f"BOT_{str(i).zfill(3)}" for i in range(1, 100)]
random.shuffle(BOT_POOL)
bot_index = 0

def get_next_bot():
    global bot_index
    bot = BOT_POOL[bot_index]
    bot_index = (bot_index + 1) % len(BOT_POOL)
    if bot_index == 0: random.shuffle(BOT_POOL)
    return bot

# --- 🎮 GAMEPLAY LOGIC (Human Mimicry) ---
async def play_as_dynamic_bot(match_id, bot_id):
    lock_key = f"bot_lock:{match_id}"
    if not r.set(lock_key, bot_id, nx=True, ex=120): return 

    uri = f"{API_WS_URL}/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    match_key = f"match:live:{match_id}"
    headers = {"Origin": "https://brainbufferonline.onrender.com", "User-Agent": f"BB-Bot-{bot_id}"}
    
    websocket = None
    try:
        # --- PHASE 1: NATURAL JOIN DELAY ---
        # Humans take a moment to see the "Found Match" screen and load
        await asyncio.sleep(random.uniform(1.5, 3.5))

        params = {"open_timeout": 25, "ping_interval": 20, "ping_timeout": 60}
        try:
            websocket = await websockets.connect(uri, additional_headers=headers, **params)
        except TypeError:
            websocket = await websockets.connect(uri, extra_headers=headers, **params)
            
        print(f"✅ {bot_id} joined room {match_id[:12]}")

        # --- PHASE 2: WAIT FOR START SIGNAL ---
        # Mimics the 3-2-1 countdown logic
        while True:
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=1.5)
                if json.loads(msg).get("type") == "GAME_START": break
            except:
                if r.hexists(match_key, "rounds"): break
                continue

        # --- PHASE 3: COUNTDOWN BUFFER ---
        # Even after GAME_START, humans wait for the countdown to hit 0
        await asyncio.sleep(4.5) 

        # Identify Human Target
        m_data = r.hgetall(match_key)
        p1, p2 = m_data.get("p1_id"), m_data.get("p2_id")
        human_id = p2 if str(p1) == str(bot_id) else p1
        if not human_id: return

        print(f"🔗 {bot_id} shadowing {human_id[:8]}...")
        
        current_score = 0
        last_pushed_score = -1
        patience = 0
        target_limit = random.choice([240, 260, 290]) # Limit for Intelligent mode
        
        # --- PHASE 4: SHADOW LOOP ---
        while True:
            # Check Admin Toggle (human / intelligent / god)
            difficulty = r.get("bot_settings:difficulty") or "god"
            
            # Get Human Stats
            h_data = r.hmget(match_key, f"score:{human_id}", f"status:{human_id}")
            h_score = int(h_data[0]) if h_data[0] else 0
            h_status = h_data[1]

            if difficulty == "god":
                # GOD: Fast reaction, stays 20pts ahead
                if current_score < (h_score + 20):
                    current_score += 10
                    wait_time = random.uniform(0.4, 0.7) # Human-pro speed
                else:
                    wait_time = random.uniform(0.8, 1.2)
            
            elif difficulty == "intelligent":
                # INTELLIGENT: Skilled player speed, caps at target_limit
                if current_score < target_limit:
                    current_score += 10
                    wait_time = random.uniform(0.8, 1.8)
                else:
                    wait_time = 2.0
            
            else: # HUMAN MODE
                # HUMAN: Slow reaction, stays 10pts behind
                if current_score < (h_score - 10):
                    current_score += 10
                    wait_time = random.uniform(1.8, 3.5)
                else:
                    wait_time = 1.5

            # Push Score Update
            if current_score != last_pushed_score:
                await websocket.send(json.dumps({"type": "SCORE_UPDATE", "score": current_score}))
                r.hset(match_key, f"score:{bot_id}", str(current_score))
                last_pushed_score = current_score
                print(f"📡 {bot_id} [{difficulty.upper()}]: {current_score} vs {h_score}")

            await asyncio.sleep(wait_time)

            # End game detection
            if h_status == "FINISHED": patience += 1
            if (h_status == "FINISHED" and patience > 5) or not r.exists(match_key): 
                break

        # Natural exit delay
        await asyncio.sleep(random.uniform(1.0, 2.0))
        await websocket.send(json.dumps({"type": "GAME_OVER"}))
        print(f"🏁 {bot_id} completed {match_id[:8]}")

    except Exception as e:
        print(f"❌ {bot_id} Error: {e}")
    finally:
        if websocket: await websocket.close()
        r.delete(lock_key)

# --- 🌐 WEBHOOK SERVER (Replaces Watcher) ---
class BotServerHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/spawn-bot':
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length))
            match_id = post_data.get("match_id")
            
            if match_id:
                print(f"🔔 Wake-up signal for Match: {match_id}")
                asyncio.run_coroutine_threadsafe(
                    play_as_dynamic_bot(match_id, get_next_bot()), 
                    bot_loop
                )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Dispatched")
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Server: Awake")

    def log_message(self, format, *args): return 

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), BotServerHandler)
    print(f"📡 Webhook listener active on port {PORT}")
    server.serve_forever()

# --- 🚀 EXECUTION ---
if __name__ == "__main__":
    # Start Webhook listener in thread
    threading.Thread(target=run_http_server, daemon=True).start()
    
    # Start Async Loop in main thread
    print("💤 Bot Service Standing By for Backend Trigger...")
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_forever()
