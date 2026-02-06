import asyncio
import websockets
import json
import random
import redis
import os
import time
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
REDIS_URL = os.getenv("UPSTASH_REDIS_URL", "rediss://default:your_token@your_endpoint:6379")
API_WS_URL = os.getenv("API_WS_URL", "wss://brainbufferonline.onrender.com/api/game/ws/match")
BOT_SECRET_TOKEN = os.getenv("BOT_TOKEN", "697b11d212267043f3c25731697b392a0a7f2c914a954987")

# Initialize Redis client
r = redis.from_url(REDIS_URL, decode_responses=True)

async def simulate_gameplay(match_id, bot_id):
    """Handles the actual connection and gameplay for a single bot."""
    print(f"⏳ {bot_id} joining in 1.5s...")
    await asyncio.sleep(1.5)

    uri = f"{API_WS_URL}/{match_id}?token={BOT_SECRET_TOKEN}&bot_id={bot_id}"
    
    try:
        async with websockets.connect(uri, open_timeout=15) as websocket:
            print(f"✅ {bot_id} successfully JOINED match: {match_id}")

            # 1. Wait for GAME_START
            rounds = []
            while True:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=25)
                    data = json.loads(msg)
                    if data.get("type") == "GAME_START":
                        rounds = data.get("rounds", [])
                        opponent_name = data.get("opponent_name", "Human")
                        print(f"🎮 {bot_id} vs {opponent_name} | {len(rounds)} rounds...")
                        break
                except asyncio.TimeoutError:
                    print(f"⚠️ {bot_id} timed out waiting for GAME_START")
                    return

            # 2. Simulate Gameplay
            current_score = 0
            for i in range(len(rounds)):
                await asyncio.sleep(random.uniform(1.0, 2.8))
                
                # 85% accuracy logic
                if random.random() > 0.15:
                    current_score += 10 
                    await websocket.send(json.dumps({
                        "type": "SCORE_UPDATE",
                        "score": current_score
                    }))

            # 3. Request Game End
            await asyncio.sleep(2)
            await websocket.send(json.dumps({"type": "GAME_OVER"}))
            
            # 🚀 4. LISTEN FOR WINNER RESULT
            try:
                # Wait up to 10 seconds for the backend to finalize and send results
                while True:
                    res_msg = await asyncio.wait_for(websocket.recv(), timeout=10)
                    res_data = json.loads(res_msg)
                    
                    if res_data.get("type") == "RESULT":
                        status = res_data.get("status") # WON, LOST, or DRAW
                        op_name = res_data.get("opponent_name", "Human")
                        my_final = res_data.get("my_score", 0)
                        op_final = res_data.get("op_score", 0)

                        print("\n" + "="*40)
                        print(f"🏁 MATCH FINISHED: {match_id}")
                        print(f"🤖 {bot_id}: {my_final}")
                        print(f"👤 {op_name}: {op_final}")
                        
                        if status == "WON":
                            print(f"🏆 WINNER: {bot_id} (Bot)")
                        elif status == "LOST":
                            print(f"🏆 WINNER: {op_name} (Human)")
                        else:
                            print("🤝 RESULT: IT'S A DRAW!")
                        print("="*40 + "\n")
                        break
            except Exception as e:
                print(f"ℹ️ Could not fetch final result for {bot_id}: {e}")

            await websocket.close()

    except Exception as e:
        if "1000 (OK)" not in str(e):
            print(f"❌ WebSocket Error for {bot_id}: {e}")

async def watch_matches():
    """Polls Redis for new matches and spawns bot tasks."""
    print(f"👀 Bot Service Active | Winner-Tracking Mode...")
    processed_matches = set()

    while True:
        try:
            keys = r.keys("match:live:*")
            current_time = time.time()
            
            for key in keys:
                match_id = key.split(":")[-1]
                if match_id in processed_matches:
                    continue

                match_data = r.hgetall(key)
                p2_id = match_data.get("p2_id")
                status = match_data.get("status")
                
                # 🔥 HANDLES BOTH FLOAT AND STRING TIMESTAMPS
                created_at_raw = match_data.get("created_at", "0")
                try:
                    created_at = float(created_at_raw)
                except ValueError:
                    try:
                        dt = datetime.strptime(created_at_raw, '%Y-%m-%d %H:%M:%S.%f')
                        created_at = dt.timestamp()
                    except:
                        try:
                            dt = datetime.strptime(created_at_raw, '%Y-%m-%d %H:%M:%S')
                            created_at = dt.timestamp()
                        except:
                            created_at = 0

                # Ghost Filter: Skip matches older than 2 minutes
                if created_at > 0 and (current_time - created_at) > 120:
                    processed_matches.add(match_id)
                    continue

                # Trigger Bot if status is CREATED and assigned to a BOT
                if p2_id and p2_id.startswith("BOT") and status == "CREATED":
                    processed_matches.add(match_id)
                    print(f"🎯 Match {match_id} assigned to {p2_id}. Spawning bot...")
                    asyncio.create_task(simulate_gameplay(match_id, p2_id))
            
            # Prevent memory leak
            if len(processed_matches) > 200:
                processed_matches.clear()

            await asyncio.sleep(0.5) 
        except Exception as e:
            print(f"⚠️ Service Error: {e}")
            await asyncio.sleep(2)

# --- 🔥 THE ENTRY POINT (CRITICAL) ---
if __name__ == "__main__":
    print("🚀 Starting BrainBuffer Bot Service...")
    try:
        asyncio.run(watch_matches())
    except KeyboardInterrupt:
        print("\n🛑 Bot Service Stopped by User.")
    except Exception as e:
        print(f"💥 Fatal Error: {e}")