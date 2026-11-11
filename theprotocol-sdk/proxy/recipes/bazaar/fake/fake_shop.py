"""A fake shop for the BAZAAR recipe: posts inventory changes, HMAC-signed with SHOP_HMAC, to the proxy's webhook.

    SHOP_HMAC=... python fake_shop.py http://127.0.0.1:8711/in/shop --count 4
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import urllib.request


def events(count: int, run: str):
    for i in range(count):
        yield {"event_id": f"INV-{run}-{i:03d}", "kind": "inventory", "sku": f"TEE-{i % 3}-M",
               "on_hand": 40 - i * 3, "warehouse": "WH-NORTH",
               "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--run", default=dt.datetime.now(dt.timezone.utc).strftime("%H%M%S"))
    a = ap.parse_args()
    secret = os.environ["SHOP_HMAC"].encode()
    for ev in events(a.count, a.run):
        body = json.dumps(ev).encode()
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(a.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Signature-256": sig})
        with urllib.request.urlopen(req, timeout=15) as r:
            print(ev["event_id"], ev["sku"], ev["on_hand"], r.status)


if __name__ == "__main__":
    main()
