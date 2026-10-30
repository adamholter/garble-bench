"""Serve site/ on :7419; rebuilds data.json on request when older than 30s."""
import http.server, importlib, os, sys, time, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402

LOCK, LAST = threading.Lock(), [0.0]


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT / "site"), **k)

    def do_GET(self):
        if self.path.split("?")[0] == "/data.json":
            with LOCK:
                if time.time() - LAST[0] > 30:
                    try:
                        importlib.reload(build_site).build()
                    except Exception as e:  # keep serving the last good file
                        print("build failed", e, flush=True)
                    LAST[0] = time.time()
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 7419))), H).serve_forever()
