"""A fake order-management system for the MERIDIAN recipe: writes a batch of order intents as a JSON array into the
OMS export folder, the way a nightly export job would. Released intents are attested; held ones are not.

    python fake_oms.py /data/oms-out --batch 7 --count 5
"""
import argparse
import datetime as dt
import json
import os
import pathlib


def intents(batch: int, count: int):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for i in range(count):
        yield {"intent_id": f"MER-{batch:04d}-{i:03d}", "order_no": f"PO-{batch:04d}{i:03d}",
               "buyer": "Meridian Ledger Works", "sku": f"VALVE-{100 + i}", "qty": 10 * (i + 1),
               "status": "HELD" if i % 4 == 3 else "RELEASED", "released_at": now}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--count", type=int, default=5)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".intents-{a.batch:04d}.json.part"
    tmp.write_text(json.dumps(list(intents(a.batch, a.count)), indent=1))
    os.replace(tmp, out / f"intents-{a.batch:04d}.json")      # the drop appears whole
    print(out / f"intents-{a.batch:04d}.json")


if __name__ == "__main__":
    main()
