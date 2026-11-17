"""V0664 (Migrate a system, M1 + M2): a Decimal (what `as: decimal` and `round` work with, and what a plugin or a later mapping may
hand a writer) reaches every writer without a TypeError and without losing a digit.

The standard JSON encoder refuses a Decimal and SQLite's driver refuses it as a parameter, and a float would round it, which a
migration of money must not do. What is held here:
* sql_upsert on SQLite binds a Decimal as its exact text (the column keeps `12.50` as written, no float in between), also in a key
  column, and the pre-image state a restore reads is JSON with the exact text;
* rest writes it as a JSON NUMBER with its exact digits (`12.50`, not `12.5`, not `"12.50"`), in the body, inside a nested list or
  object too, and a value the encoder does not know (a date, a UUID, bytes) is text, not a TypeError;
* file_out writes it the same way in JSONL, and its exact text in CSV;
* the whole chain: a mapping's value node (`as: decimal`, then `round: 2`) into each writer, SQLite for real. That test needs
  the mapping's value nodes (M2, branch v0664/migrate-transforms) and is skipped, saying so, on a tree without them.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import sqlite3
import uuid
from decimal import Decimal

import httpx
import pytest

from theprotocol.proxy import mapping as M
from theprotocol.proxy.plugins import Event, Record
from theprotocol.proxy.testing import FakeContext

needs_value_nodes = pytest.mark.skipif(not hasattr(M, "is_value_node"),
                                       reason="the mapping's value nodes (M2, v0664/migrate-transforms) are not on this tree")


def _ev(i=1, **data):
    return Event(event_id=f"evt-{i}", event_type="migration.row", aggregate_id="orders", data=data)


# ── the encoder ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_decimal_is_a_json_number_with_its_exact_digits():
    from theprotocol.proxy.sinks._json import dumps
    text = dumps({"a": Decimal("12.50"), "b": Decimal("0.1000000000000000055511151231257827"), "c": Decimal("-0"),
                  "d": Decimal("1E+2"), "e": [Decimal("3.140"), {"f": Decimal("7")}]}, sort_keys=True)
    assert text == ('{"a": 12.50, "b": 0.1000000000000000055511151231257827, "c": -0, "d": 100, '
                    '"e": [3.140, {"f": 7}]}')
    assert json.loads(text)["a"] == 12.5                      # a reader takes it as a number


def test_a_decimal_that_is_not_a_number_and_other_unknown_values_are_text_never_an_error():
    from theprotocol.proxy.sinks._json import dumps
    day, uid = _dt.date(2026, 11, 14), uuid.UUID(int=7)
    got = json.loads(dumps({"nan": Decimal("NaN"), "inf": Decimal("-Infinity"), "day": day, "id": uid, "raw": b"\x00\x01",
                            "set": {"b", "a"}, "at": _dt.datetime(2026, 11, 14, 1, 2, 3)}))
    assert got == {"nan": "NaN", "inf": "-Infinity", "day": "2026-11-14", "id": str(uid), "raw": "AAE=",
                   "set": ["a", "b"], "at": "2026-11-14T01:02:03"}


def test_a_string_that_looks_like_the_placeholder_is_left_alone():
    from theprotocol.proxy.sinks._json import dumps
    assert dumps({"s": "tpdec0", "n": Decimal("1.0")}, sort_keys=True) == '{"n": 1.0, "s": "tpdec0"}'


# ── sql_upsert, SQLite for real ─────────────────────────────────────────────────────────────────────────────────

def _db(tmp_path):
    path = tmp_path / "target.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE orders (id NUMERIC PRIMARY KEY, total TEXT, note TEXT)")
    c.commit()
    c.close()
    return path


def _rows(path):
    c = sqlite3.connect(path)
    try:
        return [tuple(r) for r in c.execute("SELECT id, total, note FROM orders ORDER BY rowid")]
    finally:
        c.close()


def _upsert(path, ctx=None):
    from theprotocol.proxy.sinks.sql_upsert import SqlUpsertSink
    return SqlUpsertSink({"engine": "sqlite", "path": str(path), "table": "orders", "key": ["id"]}, ctx or FakeContext())


async def test_sqlite_binds_a_decimal_as_its_exact_text_and_a_restore_puts_the_old_row_back(tmp_path):
    from theprotocol.proxy.sinks.sql_upsert import restore_preimages
    path = _db(tmp_path)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO orders VALUES (1, '1.10', 'old')")
    c.commit()
    c.close()
    ctx = FakeContext()
    sink = _upsert(path, ctx)
    await sink.start()
    try:
        await sink.deliver(_ev(1, id=Decimal("1"), total=Decimal("12.50"), note="new"), key="k1", dry_run=False)
        await sink.deliver(_ev(2, id=Decimal("2.0"), total=Decimal("0.10"), note="fresh"), key="k2", dry_run=False)
    finally:
        await sink.stop()
    got = _rows(path)
    assert got[0][1] == "12.50" and got[1][1] == "0.10"          # the digits as written, no float in between
    assert [r[2] for r in got] == ["new", "fresh"]
    n = await restore_preimages(ctx.state, {"engine": "sqlite", "path": str(path), "table": "orders", "key": ["id"]})
    assert n == 2
    assert _rows(path) == [(1, "1.10", "old")]                    # the first row back as it was, the second deleted again


async def test_a_decimal_inside_a_json_column_value_is_written_as_text_not_refused(tmp_path):
    path = _db(tmp_path)
    sink = _upsert(path)
    await sink.start()
    try:
        await sink.deliver(_ev(1, id=1, total="x", note={"amount": Decimal("5.00"), "lines": [Decimal("1.5")]}),
                           key="k1", dry_run=False)
    finally:
        await sink.stop()
    assert json.loads(_rows(path)[0][2]) == {"amount": 5.0, "lines": [1.5]}
    assert '"amount":5.00' in _rows(path)[0][2]                   # and the digits are the exact ones


# ── rest ─────────────────────────────────────────────────────────────────────────────────────────────────────

class _Server:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(201, json={"id": "x-1"})


def _rest(server):
    from theprotocol.proxy.sinks.rest import RestSink

    class Wired(RestSink):
        transport = httpx.MockTransport(server)
    return Wired({"url": "https://crm.example.org/api/orders", "method": "POST"}, FakeContext())


async def test_rest_sends_a_decimal_as_a_json_number_with_its_exact_digits():
    server = _Server()
    sink = _rest(server)
    out = await sink.deliver(_ev(1, id=7, total=Decimal("12.50"), lines=[{"net": Decimal("2.000")}],
                                 day=_dt.date(2026, 11, 14)), key="k", dry_run=False)
    assert out.status == "done"
    body = server.requests[0].content.decode("utf-8")
    assert body == '{"day": "2026-11-14", "id": 7, "lines": [{"net": 2.000}], "total": 12.50}'


async def test_rest_dry_run_shows_the_body_without_a_type_error():
    server = _Server()
    out = await _rest(server).deliver(_ev(1, id=7, total=Decimal("12.50")), key="k", dry_run=True)
    assert out.status == "dry_run" and out.data["body"] == {"id": 7, "total": 12.5} and server.requests == []


# ── file_out ──────────────────────────────────────────────────────────────────────────────────────────────────

def _file_out(folder, **cfg):
    from theprotocol.proxy.sinks.file_out import FileOutSink
    base = {"path": str(folder), "format": "jsonl"}
    base.update(cfg)
    return FileOutSink(base, FakeContext())


async def test_file_out_jsonl_writes_a_decimal_as_a_number_with_its_exact_digits(tmp_path):
    folder = tmp_path / "out"
    sink = _file_out(folder)
    await sink.start()
    await sink.deliver(_ev(1, id=1, total=Decimal("12.50"), lines=[Decimal("0.10")]), key="k1", dry_run=False)
    await sink.stop()
    (f,) = sorted(folder.glob("data-*.jsonl"))
    assert f.read_text(encoding="utf-8") == '{"id":1,"lines":[0.10],"total":12.50}\n'


async def test_file_out_csv_writes_the_exact_text(tmp_path):
    folder = tmp_path / "out"
    sink = _file_out(folder, format="csv", columns=["id", "total"])
    await sink.start()
    await sink.deliver(_ev(1, id=1, total=Decimal("12.50")), key="k1", dry_run=False)
    await sink.stop()
    (f,) = sorted(folder.glob("data-*.csv"))
    assert list(csv.reader(io.StringIO(f.read_text(encoding="utf-8")))) == [["id", "total"], ["1", "12.50"]]


# ── the whole chain: a value node into each writer ──────────────────────────────────────────────────────────────

FIELDS = {
    "id": {"path": "$.payload.data.id", "as": "int"},
    "total": {"path": "$.payload.data.total", "as": "decimal", "round": 2},
    "note": {"path": "$.payload.data.note"},
}


def _mapped(total="12.345"):
    rec = Record(record_id="r1", source="legacy", payload={"data": {"id": "41", "total": total, "note": "n"}})
    return M.apply(FIELDS, rec)


@needs_value_nodes
async def test_a_value_node_into_every_writer(tmp_path):
    data = _mapped("12.345")
    # what a mapping hands an action or sink for a decimal node is its exact TEXT (mapping._steps ends in str(Decimal)), half to even
    assert data["total"] == "12.34"
    # sqlite, for real
    path = _db(tmp_path)
    sink = _upsert(path)
    await sink.start()
    try:
        await sink.deliver(_ev(1, **data), key="k1", dry_run=False)
    finally:
        await sink.stop()
    assert _rows(path) == [(41, "12.34", "n")]
    # rest
    server = _Server()
    await _rest(server).deliver(_ev(1, **data), key="k1", dry_run=False)
    assert server.requests[0].content.decode("utf-8") == '{"id": 41, "note": "n", "total": "12.34"}'
    # file_out
    folder = tmp_path / "out"
    fo = _file_out(folder)
    await fo.start()
    await fo.deliver(_ev(1, **data), key="k1", dry_run=False)
    await fo.stop()
    (f,) = sorted(folder.glob("data-*.jsonl"))
    assert f.read_text(encoding="utf-8") == '{"id":41,"note":"n","total":"12.34"}\n'


@needs_value_nodes
async def test_a_whole_number_that_rounds_keeps_its_scale_into_sqlite(tmp_path):
    data = _mapped("7")
    assert data["total"] == "7.00"
    path = _db(tmp_path)
    sink = _upsert(path)
    await sink.start()
    try:
        await sink.deliver(_ev(1, **data), key="k1", dry_run=False)
    finally:
        await sink.stop()
    assert _rows(path)[0][1] == "7.00"
