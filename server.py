import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class StaticHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/' or path == '/webapp.html':
            try:
                with open('webapp.html', 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(content))
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not found')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), StaticHandler)
    print(f"Web server running on port {port}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=run_web, daemon=True)
    t.start()
    
    # Run bot
    import bot
    bot.main()
