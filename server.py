import threading
import api
import bot

def run_api():
    api.run_api()

if __name__ == "__main__":
    t = threading.Thread(target=run_api, daemon=True)
    t.start()
    print("API thread started, launching bot...", flush=True)
    bot.main()
