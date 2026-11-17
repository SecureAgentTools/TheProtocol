#!/usr/bin/env python3
"""The three M7 starter kits' synthetic samples (session-tester, V0664 M7). Deterministic (a fixed seed), every value
invented: "Customer 0001" style names, example.invalid addresses, no real person or company.

    python3 proxy/migrations/make_samples.py     (from the SDK folder; it rewrites the three sample/ files)
"""
import csv
import io
import json
import random
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
rnd = random.Random(20261114)

# 1. sql-to-postgres: 480 customers; 4 dates not dd.mm.yyyy and 3 unknown status codes are refused on purpose
BAD_DATES = {37: "31.02.2021", 113: "2021-05-04", 254: "13.13.2020", 391: "00.01.2022"}
BAD_STATUS = {58: "X", 222: "Q", 444: "Z"}
rows = []
for i in range(1, 481):
    d = f"{rnd.randint(1, 28):02d}.{rnd.randint(1, 12):02d}.{rnd.randint(2015, 2024)}"
    name = f"Customer {i:04d}"
    if i % 7 == 0:
        name = f"  {name} "                       # the old system kept padding: trimmed by the mapping
    status = rnd.choice(["A", "A", "A", "I", "B", "a", " i"])
    rows.append({"id": i, "name": name, "email": f"customer{i:04d}@example.invalid",
                 "signup_date": BAD_DATES.get(i, d), "status": BAD_STATUS.get(i, status)})
(root / "sql-to-postgres/sample/customers.jsonl").write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

# 2. csv-to-postgres: 360 orders; 3 amounts that are no number and 2 local times not YYYY-MM-DD HH:MM are refused
BAD_AMOUNT = {100019: "n/a", 100144: "n/a", 100301: "n/a"}
BAD_TIME = {100077: "05/03/2024 14:22", 100250: "2024-07-01T09:15"}
buf = io.StringIO()
w = csv.writer(buf, lineterminator="\n")
w.writerow(["order_no", "customer_id", "ordered_at", "amount", "currency", "status"])
for n in range(100001, 100361):
    at = f"2024-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d} {rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}"
    cents = rnd.randint(150, 250000)
    amount = f"{cents / 100:.2f}" if n % 3 else f"{cents / 100 + rnd.choice([0.004, 0.005, 0.006]):.3f}"
    w.writerow([n, rnd.randint(1, 480), BAD_TIME.get(n, at), BAD_AMOUNT.get(n, amount),
                rnd.choice(["EUR", "eur", " EUR"]), rnd.choice(["open", "paid", "paid", "shipped"])])
(root / "csv-to-postgres/sample/orders.csv").write_text(buf.getvalue(), encoding="utf-8")

# 3. sql-to-rest: 240 products; 3 prices that are no number and 2 active flags that are no boolean are refused
BAD_PRICE = {17: "TBD", 88: "TBD", 199: "TBD"}
BAD_ACTIVE = {45: 2, 160: 2}
rows = []
for i in range(1, 241):
    rows.append({"id": i, "sku": f" sku-{i:04d}" if i % 5 == 0 else f"SKU-{i:04d}", "name": f"Product {i:04d}",
                 "price_text": BAD_PRICE.get(i, f"{rnd.randint(99, 99999) / 100:.2f}"),
                 "active": BAD_ACTIVE.get(i, rnd.choice([1, 1, 1, 0]))})
(root / "sql-to-rest/sample/products.jsonl").write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
print("written")
