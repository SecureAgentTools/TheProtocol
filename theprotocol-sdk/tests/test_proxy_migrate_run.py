"""V0664 Migrate (M3): dry-run, load, reconcile and rollback on a SQLite kit and a CSV kit, through `tp-proxy migrate`.

- dry-run --sample writes only under KIT/.migrate/ (scratch and reports), never the real target, and reports the counts;
- load then reconcile passes; one target row changed afterwards fails reconcile with mismatched 1 (exit 1);
- rollback (with --yes) restores the target as it was before the load; rollback: manual refuses naming the README;
- --json on each command; no record value in any report.
Red before M3: no `migrate` command.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

SAMPLE = [
    {"id": 1, "name": "Ada Lovecraft-Sample", "email": "ada.sample@example.invalid", "created_at": "2024-01-05"},
    {"id": 2, "name": "Bert Quasimodo-Sample", "email": "bert.sample@example.invalid", "created_at": "2024-02-11"},
    {"id": 3, "name": "Cleo Zanzibar-Sample", "created_at": "2024-03-19"},         # no email: the mapping refuses it
]
VALUES = ["Lovecraft", "Quasimodo", "Zanzibar", "ada.sample", "bert.sample", "2024-01-05", "2024-02-11"]

MANIFEST = """schema: theprotocol.migration/v1
name: crm-to-sql
title: Customers to a new table
from: {kind: sql, engines: [sqlite]}
to: {kind: sql, engines: [sqlite]}
parameters:
  SOURCE_PATH: {description: the old database}
  TARGET_PATH: {description: the new database}
load: {mappings: [customers], batch_rows: 2}
reconcile:
  - mapping: customers
    source: {key: [id], fields: [name, email, created_at]}
    target: {key: [legacy_id], fields: [full_name, email, created]}
    pairs: {name: full_name, email: email, created_at: created}
sample:
  old: {file: sample/customers.jsonl, format: jsonl}
rollback: ROLLBACK
"""
PROXY = """version: 1
name: crm-to-sql
sources:
  old:
    type: sqlpoll
    config: {engine: sqlite, path: "${SOURCE_PATH}", table: customers, cursor: id, poll_seconds: 0, settle_seconds: 0}
sinks:
  new:
    type: sql_upsert
    config: {engine: sqlite, path: "${TARGET_PATH}", table: customers, key: [legacy_id]}
mappings:
  - name: customers
    version: 1
    from: old
    to: new
    fields: {legacy_id: $.payload.id, full_name: $.payload.name, email: $.payload.email, created: $.payload.created_at}
"""


def tp(argv, capsys):
    from theprotocol.proxy.cli import main
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def tpj(argv, capsys):
    code, out, err = tp([*argv, "--json"], capsys)
    return code, json.loads(out)


@pytest.fixture
def sqlkit(tmp_path):
    k = tmp_path / "kit"
    (k / "sample").mkdir(parents=True)
    (k / "migration.yaml").write_text(MANIFEST.replace("ROLLBACK", "auto"))
    (k / "proxy.yaml").write_text(PROXY)
    (k / "README.md").write_text("# Customers\n")
    (k / "sample" / "customers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in SAMPLE))
    legacy, target = tmp_path / "legacy.db", tmp_path / "target.db"
    c = sqlite3.connect(legacy)
    c.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at TEXT)")
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)",
                  [(1, "Ada", "ada@example.invalid", "2023-01-01"), (2, "Bert", "bert@example.invalid", "2023-02-02"),
                   (3, "Cleo", "cleo@example.invalid", "2023-03-03"), (4, "Dora", "dora@example.invalid", "2023-04-04")])
    c.commit()
    c.close()
    c = sqlite3.connect(target)
    c.execute("CREATE TABLE customers (legacy_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, created TEXT)")
    c.execute("INSERT INTO customers VALUES (2, 'Bert (already there)', 'old@example.invalid', '2020-01-01')")
    c.commit()
    c.close()
    sets = ["--set", f"SOURCE_PATH={legacy}", "--set", f"TARGET_PATH={target}"]
    return {"kit": str(k), "legacy": legacy, "target": target, "sets": sets}


def _rows(db):
    c = sqlite3.connect(db)
    try:
        return c.execute("SELECT * FROM customers ORDER BY legacy_id").fetchall()
    finally:
        c.close()


def _tree(d):
    return sorted(os.path.relpath(os.path.join(r, f), d) for r, _, fs in os.walk(d) for f in fs)


def _reports(kit):
    d = os.path.join(kit, ".migrate", "reports")
    return [open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d))]


def test_dry_run_on_the_sample_writes_only_scratch_and_reports_the_counts(sqlkit, capsys):
    before_target = _rows(sqlkit["target"])
    kit_before = _tree(sqlkit["kit"])
    code, rep = tpj(["migrate", "dry-run", sqlkit["kit"], "--sample", *sqlkit["sets"]], capsys)
    assert code == 0, rep
    assert rep["schema"] == "theprotocol.migration.report/v1" and rep["step"] == "dry_run" and rep["sample"] is True
    assert rep["sources"]["old"]["rows"] == 3
    assert sorted(rep["sources"]["old"]["fields"]) == ["created_at", "email", "id", "name"]
    m = rep["mappings"]["customers"]
    assert (m["taken"], m["mapped"], m["rejected"]) == (3, 2, 1)
    assert m["rejected_by_reason"] == {"the record has no $.payload.email (the mapping's field email)": 1}
    assert m["fields"]["full_name"] == {"filled": 2, "null": 0}
    assert rep["targets"]["new"] == {"written": 2, "unchanged": 0, "failed": 0, "pending": 0, "scratch": True}
    r = rep["reconcile"]["customers"]
    assert (r["source"], r["target"], r["missing"], r["extra"], r["mismatched"], r["verdict"]) == (2, 2, 0, 0, 0, "pass")
    assert [b["count"] for b in rep["batches"]] == [2]
    assert rep["verdict"] == "pass" and rep["template"] == {"local": rep["template"]["local"]}
    # nothing but the kit's own working state changed; the real target is as it was
    assert _rows(sqlkit["target"]) == before_target
    new = sorted(set(_tree(sqlkit["kit"])) - set(kit_before))
    assert new and all(p.startswith(".migrate/scratch/") or p.startswith(".migrate/reports/") for p in new), new
    sc = sqlite3.connect(os.path.join(sqlkit["kit"], ".migrate", "scratch", "scratch.sqlite"))
    assert sc.execute("SELECT count(*) FROM customers").fetchone()[0] == 2


def test_dry_run_against_the_real_source_reads_it_and_writes_only_scratch(sqlkit, capsys):
    before = _rows(sqlkit["target"])
    code, rep = tpj(["migrate", "dry-run", sqlkit["kit"], "--limit", "3", *sqlkit["sets"]], capsys)
    assert code == 0, rep
    assert rep["sample"] is False and rep["sources"]["old"]["rows"] == 3
    # its reconcile compares the same first 3 records, not the whole source (which would read 1 missing)
    r = rep["reconcile"]["customers"]
    assert (r["source"], r["target"], r["missing"], r["verdict"]) == (3, 3, 0, "pass")
    assert _rows(sqlkit["target"]) == before


def test_load_then_reconcile_passes_and_a_changed_row_fails_with_mismatched_1(sqlkit, capsys):
    code, rep = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 0, rep
    assert rep["step"] == "load" and rep["targets"]["new"]["written"] == 4 and rep["mappings"]["customers"]["mapped"] == 4
    assert [r[1] for r in _rows(sqlkit["target"])] == ["Ada", "Bert", "Cleo", "Dora"]
    code, rep = tpj(["migrate", "reconcile", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 0, rep
    r = rep["reconcile"]["customers"]
    assert (r["source"], r["target"], r["missing"], r["extra"], r["mismatched"]) == (4, 4, 0, 0, 0)
    assert r["checksum_source"] == r["checksum_target"]
    # a load again moves nothing twice
    code, rep = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 0 and rep["sources"]["old"]["rows"] == 0
    c = sqlite3.connect(sqlkit["target"])
    c.execute("UPDATE customers SET email = 'changed@example.invalid' WHERE legacy_id = 3")
    c.commit()
    c.close()
    code, rep = tpj(["migrate", "reconcile", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 1
    r = rep["reconcile"]["customers"]
    assert (r["missing"], r["extra"], r["mismatched"], r["verdict"]) == (0, 0, 1, "fail")
    assert r["checksum_source"] != r["checksum_target"]


def test_reconcile_with_an_extra_target_row_and_one_missing(sqlkit, capsys):
    assert tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)[0] == 0
    c = sqlite3.connect(sqlkit["target"])
    c.execute("DELETE FROM customers WHERE legacy_id = 1")
    c.execute("INSERT INTO customers VALUES (99, 'Zed', 'z@example.invalid', '2023-09-09')")
    c.commit()
    c.close()
    code, rep = tpj(["migrate", "reconcile", sqlkit["kit"], *sqlkit["sets"]], capsys)
    r = rep["reconcile"]["customers"]
    assert code == 1 and (r["missing"], r["extra"], r["mismatched"]) == (1, 1, 0)


def test_rollback_restores_the_target_as_it_was(sqlkit, capsys):
    before = _rows(sqlkit["target"])
    assert tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)[0] == 0
    assert _rows(sqlkit["target"]) != before
    code, rep = tpj(["migrate", "rollback", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 2 and "give --yes" in rep["problems"][0]
    code, rep = tpj(["migrate", "rollback", sqlkit["kit"], "--yes", *sqlkit["sets"]], capsys)
    assert code == 0, rep
    assert rep["restored"] == 4 and _rows(sqlkit["target"]) == before
    # the state was moved aside: a load after a rollback writes again
    assert tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)[1]["targets"]["new"]["written"] == 4
    code, rep = tpj(["migrate", "rollback", sqlkit["kit"], "--yes", *sqlkit["sets"]], capsys)
    assert code == 0 and _rows(sqlkit["target"]) == before


def test_a_rollback_that_cannot_finish_says_so_writes_a_report_and_can_run_again(sqlkit, capsys):
    """M8's real-type check (room seq 3853): a restore the database refuses used to end in a traceback with no report. It is exit 1,
    a rollback report whose verdict is fail naming the sink, no value, and the state file kept, so the same command runs again
    once the cause is fixed. (M12 tests the report shape with a stand-in; this one has the database refuse and then run again.)"""
    before = _rows(sqlkit["target"])
    assert tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)[0] == 0
    c = sqlite3.connect(sqlkit["target"])
    c.execute("ALTER TABLE customers RENAME TO customers_moved")
    c.commit()
    c.close()
    code, rep = tpj(["migrate", "rollback", sqlkit["kit"], "--yes", *sqlkit["sets"]], capsys)
    assert code == 1 and rep["stopped"] == {"kind": "rollback", "name": "new"}      # M12's report shape: a real refusal this time
    assert os.path.exists(os.path.join(sqlkit["kit"], ".migrate", "state.db"))             # kept: it can run again
    written = [t for t in _reports(sqlkit["kit"]) if '"step": "rollback"' in t]
    assert len(written) == 1 and '"verdict": "fail"' in written[0]
    for v in VALUES:
        assert v not in written[0]
    c = sqlite3.connect(sqlkit["target"])
    c.execute("ALTER TABLE customers_moved RENAME TO customers")
    c.commit()
    c.close()
    code, rep = tpj(["migrate", "rollback", sqlkit["kit"], "--yes", *sqlkit["sets"]], capsys)
    assert code == 0 and _rows(sqlkit["target"]) == before


def test_rollback_manual_refuses_naming_the_readme(sqlkit, capsys):
    p = os.path.join(sqlkit["kit"], "migration.yaml")
    open(p, "w").write(MANIFEST.replace("ROLLBACK", "manual"))
    code, rep = tpj(["migrate", "rollback", sqlkit["kit"], "--yes", *sqlkit["sets"]], capsys)
    assert code == 1 and "README.md" in rep["problems"][0]


def test_no_record_value_reaches_any_report(sqlkit, capsys):
    for argv in (["dry-run", "--sample"], ["plan", "--sample"], ["load", "--confirm-destinations"], ["reconcile"]):
        tpj(["migrate", argv[0], sqlkit["kit"], *argv[1:], *sqlkit["sets"]], capsys)
    texts = _reports(sqlkit["kit"])
    assert len(texts) == 4
    for t in texts:
        for v in VALUES + ["ada@example", "Dora", "dora@"]:
            assert v not in t, (v, t[:300])
        doc = json.loads(t)
        from theprotocol.proxy.migrate.reports import hash_holds
        assert hash_holds(doc)


def test_plan_counts_rows_and_fields_and_names_coverage(sqlkit, capsys):
    code, rep = tpj(["migrate", "plan", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 0, rep
    assert rep["step"] == "inventory" and rep["sources"]["old"] == {"rows": 4, "fields": ["id", "name", "email",
                                                                                          "created_at"]}
    assert rep["mappings"]["customers"]["unused"] == [] and rep["mappings"]["customers"]["no_source"] == []


def test_check_new_and_every_command_answer_json(tmp_path, sqlkit, capsys):
    code, ans = tpj(["migrate", "check", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 0 and ans["valid"] is True and ans["exit"] == 0 and ans["sinks"] == {"new": "sql_upsert"}
    for pair in (("sql", "sql"), ("file", "sql"), ("sql", "rest")):
        d = tmp_path / f"new-{pair[0]}-{pair[1]}"
        code, ans = tpj(["migrate", "new", d.name, "--from", pair[0], "--to", pair[1], "--out", str(d)], capsys)
        assert code == 0 and "migration.yaml" in ans["files"]
        assert tpj(["migrate", "check", str(d)], capsys)[0] == 0
        code, rep = tpj(["migrate", "dry-run", str(d), "--sample"], capsys)
        assert code == 0 and rep["verdict"] == "pass" and rep["reconcile"]["customers"]["source"] == 3, rep
    code, ans = tpj(["migrate", "new", "x", "--from", "rest", "--to", "sql", "--out", str(tmp_path / "x")], capsys)
    assert code == 2 and ans["problems"]


def test_a_csv_kit_dry_runs_and_loads_into_a_folder(tmp_path, capsys):
    k = tmp_path / "csvkit"
    (k / "sample").mkdir(parents=True)
    (k / "migration.yaml").write_text("""schema: theprotocol.migration/v1
name: csv-to-files
title: CSV to JSONL
from: {kind: file}
to: {kind: file}
parameters:
  IN: {default: in}
  OUT: {default: out}
load: {mappings: [rows]}
reconcile:
  - {mapping: rows, source: {key: [sku], fields: [qty]}, target: {key: [sku], fields: [qty]}, pairs: {qty: qty}}
sample:
  drop: {file: sample/stock.csv}
rollback: manual
""")
    (k / "proxy.yaml").write_text("""version: 1
name: csv-to-files
sources:
  drop: {type: filedrop, config: {path: "${IN}", format: csv, settle_seconds: 0, poll_seconds: 30}}
sinks:
  out: {type: file_out, config: {path: "${OUT}", format: jsonl}}
mappings:
  - {name: rows, version: 1, from: drop, to: out, fields: {sku: $.payload.data.sku, qty: $.payload.data.qty}}
""")
    (k / "README.md").write_text("# Stock\nThe way back: delete the output folder.\n")
    (k / "sample" / "stock.csv").write_text("sku,qty\nA-1,3\nB-2,5\n")
    code, rep = tpj(["migrate", "dry-run", str(k), "--sample"], capsys)
    assert code == 0, rep
    assert rep["targets"]["out"]["written"] == 2 and rep["reconcile"]["rows"]["verdict"] == "pass"
    assert not (tmp_path / "out").exists()
    inn = tmp_path / "in"
    inn.mkdir()
    (inn / "stock.csv").write_text("sku,qty\nA-1,3\nB-2,5\nC-3,8\n")
    sets = ["--set", f"IN={inn}", "--set", f"OUT={tmp_path / 'out'}"]
    code, rep = tpj(["migrate", "load", "--confirm-destinations", str(k), *sets], capsys)
    assert code == 0 and rep["targets"]["out"]["written"] == 3, rep
    code, rep = tpj(["migrate", "reconcile", str(k), *sets], capsys)
    assert code == 0 and rep["reconcile"]["rows"]["source"] == 3, rep


def test_a_rest_target_with_no_read_back_is_not_measured(tmp_path, capsys):
    d = tmp_path / "rk"
    assert tpj(["migrate", "new", "rk", "--from", "sql", "--to", "rest", "--out", str(d)], capsys)[0] == 0
    legacy = tmp_path / "l.db"
    c = sqlite3.connect(legacy)
    c.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at TEXT)")
    c.commit()
    c.close()
    code, rep = tpj(["migrate", "reconcile", str(d), "--set", f"SOURCE_PATH={legacy}",
                     "--set", "TARGET_TOKEN=env:NOPE"], capsys)
    assert code == 3 and rep["verdict"] == "not_measured"
    assert "names no way to read it back" in rep["reconcile"]["customers"]["why"]


def test_usage_errors_are_exit_2(sqlkit, capsys):
    code, rep = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"]], capsys)          # no SOURCE_PATH
    assert code == 2 and any("SOURCE_PATH" in p for p in rep["problems"])
    code, rep = tpj(["migrate", "dry-run", sqlkit["kit"] + "-nope", "--sample"], capsys)
    assert code == 2


def test_a_zoned_moment_compares_in_utc_whichever_zone_it_was_read_in():
    # session-tester, seq 3806: a timestamptz written as ...T13:22:00Z reads back as ...T14:22:00+01:00 on a server in
    # Berlin; both are the same moment and must not be a mismatch. A naive time and a date stay as written.
    from datetime import datetime, timedelta, timezone
    from theprotocol.proxy.migrate.reconcile import text
    same = ["2024-03-05T13:22:00Z", "2024-03-05T14:22:00+01:00", "2024-03-05 14:22:00+01", "2024-03-05T08:22:00-0500",
            datetime(2024, 3, 5, 14, 22, tzinfo=timezone(timedelta(hours=1)))]
    assert {text(v) for v in same} == {"2024-03-05T13:22:00Z"}
    assert text("2024-03-05T13:22:00.123456789+00:00") == "2024-03-05T13:22:00.123456Z"
    assert text("2024-03-05T13:22:00") == "2024-03-05T13:22:00" and text("2024-03-05") == "2024-03-05"
    assert text("2024-03-05T13:22:00Z") != text("2024-03-05T13:22:01Z")
    assert text("not 2024-03-05T13:22:00Z") == "not 2024-03-05T13:22:00Z"


def test_a_rest_target_is_read_back_from_a_parameter_address(tmp_path, capsys):
    # session-tester, seq 3806: reconcile.target.read takes ${PARAM} like proxy.yaml does
    import http.server
    import threading
    bodies = [{"legacy_id": r["id"], "full_name": r["name"], "email": r["email"], "created": r["created_at"]}
              for r in SAMPLE[:2]]

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != "/customers":
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps({"items": bodies}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        d = tmp_path / "rk"
        assert tpj(["migrate", "new", "rk", "--from", "sql", "--to", "rest", "--out", str(d)], capsys)[0] == 0
        m = (d / "migration.yaml").read_text()
        m = m.replace("  TARGET_TOKEN:", "  READ_URL: {description: where the written customers are listed}\n"
                                         "  TARGET_TOKEN:")
        m = m.replace("target: {key: [legacy_id], fields: [full_name, email, created]}",
                      "target: {key: [legacy_id], fields: [full_name, email, created], "
                      "read: {url: '${READ_URL}', items_path: $.items}}")
        (d / "migration.yaml").write_text(m)
        legacy = tmp_path / "l.db"
        c = sqlite3.connect(legacy)
        c.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at TEXT)")
        c.executemany("INSERT INTO customers VALUES (:id, :name, :email, :created_at)", SAMPLE[:2])
        c.commit()
        c.close()
        sets = ["--set", f"SOURCE_PATH={legacy}", "--set", "TARGET_TOKEN=env:NOPE"]
        code, rep = tpj(["migrate", "reconcile", str(d), *sets], capsys)
        assert code == 2 and any("READ_URL" in p for p in rep["problems"])        # unfilled: named, exit 2
        url = f"http://127.0.0.1:{srv.server_address[1]}/customers"
        code, rep = tpj(["migrate", "reconcile", str(d), *sets, "--set", f"READ_URL={url}"], capsys)
        assert code == 0, rep
        r = rep["reconcile"]["customers"]
        assert (r["source"], r["target"], r["mismatched"], r["verdict"]) == (2, 2, 0, "pass")
    finally:
        srv.shutdown()


def test_a_numeric_target_column_compares_by_value_and_a_text_column_stays_text(tmp_path):
    # session-lead seq 3808: 12.5 equals 12.50 in a numeric column; "12.50" and "12.5" are different texts
    import asyncio
    import decimal
    from theprotocol.proxy.migrate import reconcile as REC
    from theprotocol.proxy.spec import parse
    db = tmp_path / "s.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, amount TEXT, code TEXT)")
    c.executemany("INSERT INTO t VALUES (?, ?, ?)", [(1, "12.50", "12.50"), (2, "7", "007")])
    c.commit()
    c.close()
    spec = parse({"version": 1, "name": "n",
                  "sources": {"s": {"type": "sqlpoll", "config": {"engine": "sqlite", "path": str(db), "table": "t",
                                                                  "cursor": "id", "poll_seconds": 0}}},
                  "sinks": {"o": {"type": "file_out", "config": {"path": str(tmp_path / "o"), "format": "jsonl"}}},
                  "mappings": [{"name": "m", "version": 1, "from": "s", "to": "o",
                                "fields": {"id": "$.payload.id", "amount": "$.payload.amount",
                                           "code": "$.payload.code"}}]})
    entry = {"mapping": "m", "source": {"key": ["id"], "fields": ["amount", "code"]},
             "target": {"key": ["id"], "fields": ["amount", "code"]}, "pairs": {"amount": "amount", "code": "code"}}

    def run(rows):
        return asyncio.run(REC.compare(spec, entry, iter(rows), batch_rows=10, workdir=tmp_path))[0]
    # numeric amount read back as a number: equal by value; code is text: equal only as the same text
    r = run([{"id": decimal.Decimal("1"), "amount": decimal.Decimal("12.5"), "code": "12.50"},
             {"id": 2, "amount": 7.0, "code": "007"}])
    assert (r["mismatched"], r["missing"], r["extra"]) == (0, 0, 0), r
    r = run([{"id": 1, "amount": decimal.Decimal("12.5"), "code": "12.5"}, {"id": 2, "amount": 7, "code": "7"}])
    assert r["mismatched"] == 2, r
    r = run([{"id": 1, "amount": decimal.Decimal("12.51"), "code": "12.50"}, {"id": 2, "amount": 7, "code": "007"}])
    assert r["mismatched"] == 1, r
