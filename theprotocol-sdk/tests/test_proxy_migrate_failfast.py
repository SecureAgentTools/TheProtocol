"""V0664 Migrate (M12): a migrate command fails fast with its reason, never hangs in silence (session-tester, seq 3838:
`load` on a sqlpoll source whose sqlite file does not exist printed nothing and never ended).

- a missing source, an unreachable target and a missing target table refuse at once (exit 1, the reason, its class);
- a writer that starts refusing mid-run ends the command (exit 1, the reason, the report so far, verdict fail), and a
  load again after the fix resumes and sends the refused rows;
- a source that keeps failing ends the command;
- on a terminal a progress line, none with --json.
Red before M12: the first load waits forever.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

import test_proxy_migrate_run as RUN

sqlkit = RUN.sqlkit
tpj, tp = RUN.tpj, RUN.tp


def _sets(sqlkit, source=None, target=None):
    return ["--set", f"SOURCE_PATH={source or sqlkit['legacy']}", "--set", f"TARGET_PATH={target or sqlkit['target']}"]


def test_a_missing_source_refuses_at_once_with_its_reason(sqlkit, capsys, tmp_path):
    gone = tmp_path / "no-such.db"
    for argv in (["load", "--confirm-destinations"], ["dry-run"], ["reconcile"]):
        t0 = time.monotonic()
        code, ans = tpj(["migrate", argv[0], sqlkit["kit"], *argv[1:], *_sets(sqlkit, source=gone)], capsys)
        assert code == 1 and time.monotonic() - t0 < 10, (argv, ans)
        assert any(f"source old (sqlpoll) cannot be read: the database file {gone} does not exist" == p
                   for p in ans["problems"]), ans
    assert not os.path.exists(os.path.join(sqlkit["kit"], ".migrate", "state.db"))


def test_an_unreachable_target_and_a_missing_table_refuse_at_once(sqlkit, capsys, tmp_path):
    code, ans = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"],
                     *_sets(sqlkit, target=tmp_path / "nowhere.db")], capsys)
    assert code == 1 and any(p.startswith("writer new (sql_upsert) cannot be reached: the database file")
                             for p in ans["problems"]), ans
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    code, ans = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *_sets(sqlkit, target=empty)], capsys)
    assert code == 1
    assert "writer new (sql_upsert) cannot be reached: the table customers could not be read (OperationalError)" \
        in ans["problems"], ans


def _strict_target(path):
    """A target that refuses every name longer than 3 letters (a CHECK the writer runs into row after row)."""
    if os.path.exists(path):
        os.unlink(path)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE customers (legacy_id INTEGER PRIMARY KEY, full_name TEXT CHECK (length(full_name) <= 3), "
              "email TEXT, created TEXT)")
    c.commit()
    c.close()


def test_a_writer_refusing_mid_run_ends_the_command_and_a_load_again_resumes(sqlkit, capsys):
    c = sqlite3.connect(sqlkit["legacy"])
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)",
                  [(i, f"Name{i}", f"n{i}@example.invalid", "2023-05-05") for i in range(5, 12)])
    c.commit()
    c.close()
    _strict_target(sqlkit["target"])
    t0 = time.monotonic()
    code, ans = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *_sets(sqlkit)], capsys)
    assert code == 1 and time.monotonic() - t0 < 30, ans
    assert ans["verdict"] == "fail" and ans["stopped"] == {"kind": "breaker", "name": "customers"}
    assert ans["problems"][0].startswith("ended early: the writer refused 5 rows of the mapping customers in a row")
    assert "IntegrityError" in ans["problems"][0]
    assert ans["targets"]["new"]["failed"] >= 5
    rep = json.load(open(ans["written"]))
    assert rep["stopped"] == {"kind": "breaker", "name": "customers"} and "problems" not in rep
    assert "Name1" not in open(ans["written"]).read()
    # the target is fixed; a load again resumes, and the rows the writer refused go again under the same keys
    kept = RUN._rows(sqlkit["target"])                        # what the first load wrote stays (it is not sent again)
    assert kept
    c = sqlite3.connect(sqlkit["target"])
    c.execute("DROP TABLE customers")
    c.execute("CREATE TABLE customers (legacy_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, created TEXT)")
    c.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", kept)
    c.commit()
    c.close()
    code, ans = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *_sets(sqlkit)], capsys)
    assert code == 0, ans
    assert len(RUN._rows(sqlkit["target"])) == 11
    code, ans = tpj(["migrate", "reconcile", sqlkit["kit"], *_sets(sqlkit)], capsys)
    assert code == 0 and ans["reconcile"]["customers"]["source"] == 11


def test_a_source_that_keeps_failing_ends_the_command(sqlkit, capsys, monkeypatch, tmp_path):
    from theprotocol.proxy.migrate import commands as C
    from theprotocol.proxy.migrate import guard
    monkeypatch.setattr(guard, "SOURCE_FAILURES", 2)
    monkeypatch.setattr(C, "_preflight", lambda spec, **kw: None)     # past the preflight: fails while running
    t0 = time.monotonic()
    code, ans = tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"],
                     *_sets(sqlkit, source=tmp_path / "gone.db")], capsys)
    assert code == 1 and time.monotonic() - t0 < 30, ans
    assert ans["stopped"] == {"kind": "source", "name": "old"}
    assert "the source old failed 2 times in a row" in ans["problems"][0]


def test_a_progress_line_on_a_terminal_and_none_with_json(sqlkit, capsys, monkeypatch):
    from theprotocol.proxy.migrate import commands as C
    from theprotocol.proxy.migrate import guard
    monkeypatch.setattr(guard, "PROGRESS_S", 0.0)
    lines = []
    code, ans = C.cmd_load(sqlkit["kit"], sets=_sets(sqlkit)[1::2], confirm_destinations=True, progress=lines.append)
    assert code == 0 and lines and all(l.startswith("read ") and "written" in l and "pending" in l for l in lines)
    assert not any("ada" in l.lower() for l in lines)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    code, out, err = tp(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *_sets(sqlkit), "--json"], capsys)
    assert code == 0 and "tp-proxy migrate: read" not in err
    json.loads(out)
    os.rename(os.path.join(sqlkit["kit"], ".migrate", "state.db"), os.path.join(sqlkit["kit"], ".migrate", "old.db"))
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    code, out, err = tp(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *_sets(sqlkit)], capsys)
    assert code == 0 and "tp-proxy migrate: read" in err


def test_a_rollback_that_stops_ends_with_exit_1_and_its_report_never_a_traceback(sqlkit, capsys, monkeypatch):
    # session-lead seq 3855, point 4
    assert tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *_sets(sqlkit)], capsys)[0] == 0
    from theprotocol.proxy.plugins import PluginError
    from theprotocol.proxy.sinks import sql_upsert

    async def broken(*a, **k):
        raise PluginError("sql_upsert: customers: a pre-image could not be put back (IntegrityError)")
    monkeypatch.setattr(sql_upsert, "restore_preimages", broken)
    code, out, err = tp(["migrate", "rollback", sqlkit["kit"], "--yes", *_sets(sqlkit), "--json"], capsys)
    assert code == 1 and "Traceback" not in out + err
    ans = json.loads(out)
    assert ans["verdict"] == "fail" and ans["stopped"] == {"kind": "rollback", "name": "new"}
    assert "a pre-image could not be put back (IntegrityError)" in ans["problems"][0]
    rep = json.load(open(ans["written"]))
    assert rep["step"] == "rollback" and rep["targets"]["new"] == {"restored": None} and "problems" not in rep
    assert os.path.exists(os.path.join(sqlkit["kit"], ".migrate", "state.db"))      # kept: a rollback again takes it

    async def odd(*a, **k):
        raise RuntimeError("anything at all, e.g. a value 'ada@example.invalid'")
    monkeypatch.setattr(sql_upsert, "restore_preimages", odd)
    code, out, err = tp(["migrate", "rollback", sqlkit["kit"], "--yes", *_sets(sqlkit), "--json"], capsys)
    assert code == 1 and "Traceback" not in out + err and "ada@" not in out + err
    assert "(RuntimeError)" in json.loads(out)["problems"][0]
