"""A mock ERP for the HANSA recipe: receives the proxy's signed POSTs, checks X-Signature-256 against ERP_HMAC, keeps
each event once by its Idempotency-Key, and appends what it kept to a JSONL file (what an ERP's import would hold).

    ERP_HMAC=... python mock_erp.py --listen 127.0.0.1:8720 --out /data/erp-received.jsonl
"""
import argparse
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:8720")
    ap.add_argument("--out", default="erp-received.jsonl")
    a = ap.parse_args()
    secret = os.environ["ERP_HMAC"].encode()
    seen = set()

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            want = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, self.headers.get("X-Signature-256") or ""):
                self.send_response(401); self.end_headers(); return
            key = self.headers.get("Idempotency-Key") or ""
            if key and key not in seen:
                seen.add(key)
                with open(a.out, "a") as f:
                    f.write(json.dumps({"key": key, "event": json.loads(body)}) + "\n")
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok": true}')

        def log_message(self, *_):
            pass

    host, port = a.listen.rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), H).serve_forever()


if __name__ == "__main__":
    main()
