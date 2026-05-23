import os
import sys
import threading

# Change to the directory where this script lives
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from http.server import HTTPServer, BaseHTTPRequestHandler

class StaticHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/webapp.html'):
            try:
                filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webapp.html')
                with open(filepath, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                print(f"Error serving file: {e}", flush=True)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), StaticHandler)
    print(f"Web server started on port {port}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=run_web, daemon=True)
    t.start()
    print("Web thread started, launching bot...", flush=True)
    import bot
    bot.main()
