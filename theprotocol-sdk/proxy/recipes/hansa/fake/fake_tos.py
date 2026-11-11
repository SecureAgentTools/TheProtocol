"""A fake terminal operating system for the HANSA recipe: posts gate events, HMAC-signed, to the proxy's webhook.
Every third event is a gate-IN (not attested); the rest are gate-OUT.

    GATE_HMAC=... python fake_tos.py http://127.0.0.1:8711/in/gate --count 6
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
        yield {"event_id": f"GATE-{run}-{i:03d}", "container_id": f"MSKU{9000000 + i}",
               "gate": f"G{1 + i % 3}", "truck_plate": f"HH-TR {100 + i}",
               "status": "IN" if i % 3 == 2 else "OUT", "seal": f"SL{70000 + i}",
               "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--run", default=dt.datetime.now(dt.timezone.utc).strftime("%H%M%S"))
    a = ap.parse_args()
    secret = os.environ["GATE_HMAC"].encode()
    for ev in events(a.count, a.run):
        body = json.dumps(ev).encode()
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(a.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Signature-256": sig})
        with urllib.request.urlopen(req, timeout=15) as r:
            print(ev["event_id"], ev["status"], r.status)


if __name__ == "__main__":
    main()
