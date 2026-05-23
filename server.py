import os
import asyncio
import threading
from api import app
import bot

def run_bot():
    asyncio.run(bot.run_async())

if __name__ == "__main__":
    # Run bot in background thread
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    print("Bot thread started", flush=True)
    
    # Flask runs in main thread (required for Railway web process)
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Flask on port {port}", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
