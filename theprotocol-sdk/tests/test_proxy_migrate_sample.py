"""V0664 Migrate (M3): migrate_sample yields exactly the records the source it stands in for yields over the same rows (the
contract, section C): sqlpoll over a SQLite table, filedrop over a folder, and webhook items. Red before M3: no
migrate_sample source."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

from theprotocol.proxy.plugins import load

ROWS = [
    {"id": 3, "name": "Cleo", "email": None, "n": 7},
    {"id": 1, "name": "Ada", "email": "ada@example.invalid", "n": 1},
    {"id": 2, "name": "Bert", "email": "bert@example.invalid", "n": -4},
]


class Ctx:
    def __init__(self):
        self.proxy_name, self.agent_did, self.registry_url, self.dry_run = "t", "", "", False
        self.logger = logging.getLogger("t")
        self._m = {}
        self.state = self

    async def get(self, k, d=None):
        return self._m.get(k, d)

    async def set(self, k, v):
        self._m[k] = v

    def secret(self, ref):
        raise AssertionError("nothing here resolves a secret")


def _read(src):
    async def go():
        await src.start()
        try:
            return [(r.record_id, r.payload, r.meta) async for r in src.records()]
        finally:
            await src.stop()
    return asyncio.run(go())


def _sample(tmp_path, kind, cfg, rows_text, fmt):
    f = tmp_path / ("sample." + fmt)
    f.write_text(rows_text, encoding="utf-8")
    return load("source", "migrate_sample")({"file": str(f), "format": fmt, "stands_in_for": kind, "config": cfg},
                                            Ctx())


def test_it_stands_in_for_sqlpoll_with_the_same_ids_payload_and_meta(tmp_path):
    db = tmp_path / "legacy.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, n INTEGER)")
    c.executemany("INSERT INTO customers VALUES (:id, :name, :email, :n)", ROWS)
    c.commit()
    c.close()
    for cfg in ({"engine": "sqlite", "path": str(db), "table": "customers", "cursor": "id", "poll_seconds": 0,
                 "settle_seconds": 0},
                {"engine": "sqlite", "path": str(db), "table": "customers", "cursor": "n", "key": ["id"],
                 "columns": ["id", "email"], "poll_seconds": 0, "settle_seconds": 0},
                # M2: no cursor, the key alone orders the rows
                {"engine": "sqlite", "path": str(db), "table": "customers", "key": ["id"], "poll_seconds": 0,
                 "settle_seconds": 0}):
        real = _read(load("source", "sqlpoll")(cfg, Ctx()))
        stand = _read(_sample(tmp_path, "sqlpoll", cfg, "".join(json.dumps(r) + "\n" for r in ROWS), "jsonl"))
        assert len(real) == 3
        assert stand == real


def test_it_stands_in_for_filedrop_over_a_folder(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    text = "id,name,email\n1,Ada,ada@example.invalid\n2,Bert,\n"
    (drop / "customers.csv").write_text(text, encoding="utf-8")
    for cfg in ({"path": str(drop), "format": "csv", "settle_seconds": 0},
                {"path": str(drop), "format": "csv", "settle_seconds": 0, "id_field": "id"}):
        real = _read(load("source", "filedrop")(cfg, Ctx()))
        side = tmp_path / "s"
        side.mkdir(exist_ok=True)
        (side / "customers.csv").write_text(text, encoding="utf-8")
        stand = _read(load("source", "migrate_sample")({"file": str(side / "customers.csv"), "stands_in_for":
                                                        "filedrop", "config": cfg}, Ctx()))
        assert len(real) == 2 and stand == real


def test_it_stands_in_for_a_webhook_by_its_id_field(tmp_path):
    cfg = {"path": "/in", "id_field": "ref"}
    src = _sample(tmp_path, "webhook", cfg, '{"ref": "a1", "x": 1}\n{"ref": "b2", "x": 2}\n', "jsonl")
    got = _read(src)
    hook = load("source", "webhook")(cfg, Ctx())
    want = [(r.record_id, r.payload, r.meta) for r in hook.records_from([{"ref": "a1", "x": 1}, {"ref": "b2", "x": 2}],
                                                                        {}, b"")[0]]
    assert got == want


def test_it_finishes_and_honours_a_limit(tmp_path):
    cfg = {"engine": "sqlite", "path": "unused.db", "table": "t", "cursor": "id"}
    src = load("source", "migrate_sample")({"file": str(tmp_path / "s.jsonl"), "stands_in_for": "sqlpoll",
                                            "config": cfg, "limit": 2}, Ctx())
    (tmp_path / "s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    assert [r[0] for r in _read(src)] == ["1", "2"]
