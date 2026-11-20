from __future__ import annotations
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        print("[VTSB3 server] " + fmt % args)

if __name__ == "__main__":
    print("VTSB3 player extension: http://localhost:8000/extensions/vtsb3player.js")
    print("Decoder:                http://localhost:8000/extensions/vtsb3_decoder.js")
    print("Keep this window open while TurboWarp is using the extension.")
    ThreadingHTTPServer(("localhost", 8000), Handler).serve_forever()
