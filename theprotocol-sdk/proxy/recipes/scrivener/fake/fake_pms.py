"""A fake practice-management system for the SCRIVENER recipe: posts one matter's life (opened, a filing with the filed
document's SHA-256, a deadline met, closed), HMAC-signed with PMS_HMAC, to the proxy's webhook.

    PMS_HMAC=... python fake_pms.py http://127.0.0.1:8711/in/matters --matter M-2026-0042
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import urllib.request


def events(matter: str):
    life = [("opened", None), ("filing", hashlib.sha256(b"statement of claim, v3").hexdigest()),
            ("deadline_met", None), ("closed", None)]
    for i, (kind, doc) in enumerate(life):
        yield {"event_id": f"{matter}-{i:02d}", "matter_id": matter, "type": kind, "document_sha256": doc,
               "fee_earner": "A. Brandt", "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--matter", default="M-" + dt.datetime.now(dt.timezone.utc).strftime("%Y-%H%M%S"))
    a = ap.parse_args()
    secret = os.environ["PMS_HMAC"].encode()
    for ev in events(a.matter):
        body = json.dumps(ev).encode()
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(a.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Signature-256": sig})
        with urllib.request.urlopen(req, timeout=15) as r:
            print(ev["event_id"], ev["type"], r.status)


if __name__ == "__main__":
    main()
