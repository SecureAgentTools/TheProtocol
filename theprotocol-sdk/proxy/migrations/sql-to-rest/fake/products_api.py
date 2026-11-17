#!/usr/bin/env python3
"""A fake of the new system: a products API in memory, so the kit's real run (load, reconcile) can be tried with no
API at all. Standard library only.

    PRODUCTS_API_TOKEN=<any value> python3 fake/products_api.py --port 8765

    POST   /products           one product (JSON); needs `Authorization: Bearer <token>`; an Idempotency-Key it has
                               seen before answers the first answer again and stores nothing new
    GET    /products           every product, {"items": [...]} ordered by id (the kit's reconcile reads this)
    GET    /products?ids=1,2   those products only
    DELETE /products/<id>      one product (the way back: README.md); needs the token

It keeps nothing on disk: a restart starts empty.
"""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class ProductsServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, token: str = ""):
        super().__init__(addr, _Handler)
        self.token = token
        self.store = {}          # id -> the product as it was POSTed
        self.keys = {}           # Idempotency-Key -> (status, answer)
        self.posts = 0           # POSTs that stored a product
        self.refused_auth = 0
        self.lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server: ProductsServer

    def log_message(self, *a):   # quiet: a test drives hundreds of requests
        pass

    def _send(self, status: int, doc) -> None:
        body = json.dumps(doc).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.server.token:
            return True
        if self.headers.get("Authorization", "") == f"Bearer {self.server.token}":
            return True
        with self.server.lock:
            self.server.refused_auth += 1
        self._send(401, {"detail": "a bearer token is needed"})
        return False

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path.rstrip("/") != "/products":
            return self._send(404, {"detail": "not found"})
        ids = parse_qs(u.query).get("ids")
        with self.server.lock:
            items = sorted(self.server.store.values(), key=lambda p: p["id"])
        if ids:
            want = {int(x) for x in ",".join(ids).split(",") if x.strip().lstrip("-").isdigit()}
            items = [p for p in items if p["id"] in want]
        self._send(200, {"items": items})

    def do_POST(self):
        if urlsplit(self.path).path.rstrip("/") != "/products":
            return self._send(404, {"detail": "not found"})
        if not self._authorized():
            return
        try:
            doc = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        except ValueError:
            return self._send(400, {"detail": "the body is not JSON"})
        if not isinstance(doc, dict) or not isinstance(doc.get("id"), int):
            return self._send(422, {"detail": "a product is an object with an integer id"})
        key = self.headers.get("Idempotency-Key", "")
        with self.server.lock:
            if key and key in self.server.keys:
                status, answer = self.server.keys[key]
                return self._send(status, answer)
            self.server.store[doc["id"]] = doc
            self.server.posts += 1
            answer = {"id": doc["id"]}
            if key:
                self.server.keys[key] = (201, answer)
        self._send(201, answer)

    def do_DELETE(self):
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "products" or not parts[1].isdigit():
            return self._send(404, {"detail": "not found"})
        if not self._authorized():
            return
        with self.server.lock:
            gone = self.server.store.pop(int(parts[1]), None)
        self._send(200 if gone else 404, {"deleted": bool(gone)})


def make_server(host: str = "127.0.0.1", port: int = 8765, token: str = "") -> ProductsServer:
    return ProductsServer((host, port), token=token)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A fake products API (in memory) for the sql-to-rest kit.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token-env", default="PRODUCTS_API_TOKEN",
                    help="the variable holding the bearer token it requires (unset: no token required)")
    a = ap.parse_args()
    srv = make_server(a.host, a.port, os.environ.get(a.token_env, ""))
    print(f"products API on http://{a.host}:{srv.server_address[1]}/products "
          f"({'a bearer token required' if srv.token else 'no token required'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
