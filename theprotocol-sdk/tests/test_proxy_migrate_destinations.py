"""V0664 Migrate (M11): a template never sends your data anywhere you did not name.

check, plan and load list every destination (each writer) and each source's location after the parameters are filled,
with who named it: "you" (a parameter you set) or "named by the template, not by you" (a literal in proxy.yaml, or a
parameter's default). load starts only once the list is confirmed (--confirm-destinations, or a yes); for a kit that
came from a library, a destination the template named refuses the load until you set that parameter yourself.
Red before M11: load runs without any confirmation and nothing lists a destination.
"""
from __future__ import annotations

import json
import os
import sqlite3

import test_proxy_migrate_run as RUN
from theprotocol.proxy.migrate.destinations import NAMED_BY_TEMPLATE, listing

sqlkit = RUN.sqlkit
tpj = RUN.tpj


def _doc(sinks, sources=None):
    return {"sinks": sinks, "sources": sources or {}}


def test_every_writer_and_source_is_listed_with_who_named_it():
    raw = _doc({
        "pg": {"type": "sql_upsert", "config": {"engine": "postgresql", "host": "${H}", "database": "${DB}",
                                                 "table": "public.customers", "key": ["id"]}},
        "lite": {"type": "sql_upsert", "config": {"engine": "sqlite", "path": "${P}", "table": "c", "key": ["id"]}},
        "api": {"type": "rest", "config": {"url": "https://${API}:8443/v1/customers/{id}", "method": "PUT"}},
        "evil": {"type": "rest", "config": {"url": "https://collect.example.invalid/in?k=${K}"}},
        "sub": {"type": "rest", "config": {"url": "https://api.${DOMAIN}/x"}},
        "files": {"type": "file_out", "config": {"path": "${OUT}", "format": "csv", "columns": ["a"],
                                                  "sftp": {"host": "${SFTP}", "user": "u", "path": "/drop"}}},
    }, {
        "db": {"type": "sqlpoll", "config": {"engine": "mysql", "host": "${SRC}", "port": 3306, "database": "erp",
                                             "table": "orders", "cursor": "id"}},
        "drop": {"type": "filedrop", "config": {"path": "${IN}"}},
        "box": {"type": "sftp", "config": {"host": "sftp.partner.invalid", "path": "out"}},
        "hook": {"type": "webhook", "config": {"path": "/in"}},
    })
    vals = {"H": "db.mine.invalid", "DB": "crm", "P": "/srv/new.db", "API": "api.mine.invalid",
            "K": "1", "DOMAIN": "mine.invalid", "OUT": "/srv/out", "SFTP": "files.mine.invalid", "SRC": "erp.local",
            "IN": "/srv/in"}
    from theprotocol.proxy.migrate.params import fill
    filled = fill(raw, vals)
    # the user set H, DB, API, K, DOMAIN, OUT, SRC; P, SFTP and IN are defaults
    got = {d["name"]: d for d in listing(filled, raw, {"H", "DB", "API", "K", "DOMAIN", "OUT", "SRC"})}
    assert got["pg"]["where"] == "postgresql://db.mine.invalid/crm/public.customers" and got["pg"]["origin"] == "you"
    assert got["lite"]["where"] == "sqlite:/srv/new.db table c" and got["lite"]["origin"] == "template"
    assert got["lite"]["parameter"] == "P" and got["lite"]["note"] == NAMED_BY_TEMPLATE
    assert got["api"]["where"] == "PUT https://api.mine.invalid:8443/v1/customers/{id}" and got["api"]["origin"] == "you"
    # a literal host is the template's, even when a parameter you set sits in its query; the query is never shown
    assert got["evil"]["where"] == "POST https://collect.example.invalid/in" and got["evil"]["origin"] == "template"
    assert got["evil"]["parameter"] is None
    assert got["sub"]["origin"] == "template"            # api.${DOMAIN}: the template wrote part of the host
    assert got["files"]["where"] == "folder /srv/out, then sftp://files.mine.invalid/drop"
    assert got["files"]["origin"] == "template" and got["files"]["parameter"] == "SFTP"
    assert got["db"]["role"] == "source" and got["db"]["where"] == "mysql://erp.local:3306/erp/orders"
    assert got["drop"]["where"] == "folder /srv/in" and got["drop"]["origin"] == "template"
    assert got["box"]["where"] == "sftp://sftp.partner.invalid/out" and got["box"]["origin"] == "template"
    assert got["hook"]["where"] == "receives POSTs on /in"


def test_a_url_never_shows_its_userinfo():
    raw = _doc({"api": {"type": "rest", "config": {"url": "${URL}"}}})
    filled = _doc({"api": {"type": "rest", "config": {"url": "https://user:hunter22@api.mine.invalid/x?token=t0k"}}})
    d = listing(filled, raw, {"URL"})[0]
    assert d["where"] == "POST https://api.mine.invalid/x" and d["origin"] == "you"
    assert "hunter22" not in json.dumps(d) and "t0k" not in json.dumps(d)


def test_load_waits_for_the_destinations_to_be_confirmed(sqlkit, capsys):
    before = RUN._rows(sqlkit["target"])
    code, ans = tpj(["migrate", "load", sqlkit["kit"], *sqlkit["sets"]], capsys)
    assert code == 1 and "--confirm-destinations" in ans["problems"][0]
    assert any(str(sqlkit["target"]) in p for p in ans["problems"][1:])
    assert [d["where"] for d in ans["destinations"] if d["role"] == "writer"] == [f"sqlite:{sqlkit['target']} table customers"]
    assert RUN._rows(sqlkit["target"]) == before and not os.path.exists(os.path.join(sqlkit["kit"], ".migrate",
                                                                                     "state.db"))
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"]], capsys)
    assert code == 0 and ans["targets"]["new"]["written"] == 4
    assert {d["origin"] for d in ans["destinations"]} == {"you"}


def test_an_interactive_yes_confirms_and_a_no_refuses(sqlkit):
    from theprotocol.proxy.migrate import commands as C
    seen = []
    try:
        C.cmd_load(sqlkit["kit"], sets=sqlkit["sets"][1::2], ask=lambda lines: seen.append(lines) or False)
        raise AssertionError("a no must refuse")
    except C.Stop as e:
        assert e.code == 1
    assert any(str(sqlkit["target"]) in x for x in seen[0])
    code, ans = C.cmd_load(sqlkit["kit"], sets=sqlkit["sets"][1::2], ask=lambda lines: True)
    assert code == 0 and ans["targets"]["new"]["written"] == 4


def test_check_and_plan_carry_the_list_in_json(sqlkit, capsys):
    for cmd in ("check", "plan"):
        code, ans = tpj(["migrate", cmd, sqlkit["kit"], *sqlkit["sets"]], capsys)
        assert code == 0
        roles = sorted((d["role"], d["name"], d["origin"]) for d in ans["destinations"])
        assert roles == [("source", "old", "you"), ("writer", "new", "you")]


def _default_target(kit, target):
    """The kit's TARGET_PATH gets a default: the template, not the user, names where the rows go."""
    p = os.path.join(kit, "migration.yaml")
    m = open(p).read().replace("TARGET_PATH: {description: the new database}",
                               f"TARGET_PATH: {{description: the new database, default: '{target}'}}")
    open(p, "w").write(m)


def _from_library(kit):
    """The kit as `get` leaves it: template.json, and the files as they came under .migrate/template/."""
    from theprotocol.proxy.migrate import load_kit
    k = load_kit(kit)
    os.makedirs(os.path.join(kit, ".migrate"), exist_ok=True)
    json.dump({"id": "wtpl_9", "version": 1, "content_hash": k.content_hash, "registry": "https://registry.test"},
              open(os.path.join(kit, ".migrate", "template.json"), "w"))
    for rel, text in k.files.items():
        p = os.path.join(kit, ".migrate", "template", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)


def test_a_library_kit_refuses_a_destination_the_template_named_until_you_set_it(sqlkit, capsys, tmp_path):
    other = tmp_path / "someone-elses.db"
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE customers (legacy_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, created TEXT)")
    c.commit()
    c.close()
    _default_target(sqlkit["kit"], other)
    _from_library(sqlkit["kit"])
    src_only = sqlkit["sets"][:2]                                  # SOURCE_PATH set, TARGET_PATH left to its default
    code, ans = tpj(["migrate", "check", sqlkit["kit"], *src_only], capsys)
    w = next(d for d in ans["destinations"] if d["role"] == "writer")
    assert w["origin"] == "template" and w["parameter"] == "TARGET_PATH" and w["note"] == NAMED_BY_TEMPLATE
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *src_only], capsys)
    assert code == 1 and "set TARGET_PATH yourself" in ans["problems"][0]
    assert RUN._rows(other) == []
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"]], capsys)
    assert code == 0 and ans["targets"]["new"]["written"] == 4 and RUN._rows(other) == []


def test_a_library_kit_with_a_literal_destination_refuses_even_when_everything_is_set(sqlkit, capsys):
    p = os.path.join(sqlkit["kit"], "proxy.yaml")
    text = open(p).read().replace('path: "${TARGET_PATH}"', f'path: "{sqlkit["target"]}"')
    open(p, "w").write(text)
    m = os.path.join(sqlkit["kit"], "migration.yaml")
    text = open(m).read().replace("  TARGET_PATH: {description: the new database}\n", "")
    open(m, "w").write(text)
    _from_library(sqlkit["kit"])
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"][:2]], capsys)
    assert code == 1 and "written into the kit's proxy.yaml by the template" in ans["problems"][0]


def test_a_local_kit_marks_the_template_named_destination_and_loads_once_confirmed(sqlkit, capsys, tmp_path):
    _default_target(sqlkit["kit"], sqlkit["target"])
    code, ans = tpj(["migrate", "load", sqlkit["kit"], *sqlkit["sets"][:2]], capsys)
    assert code == 1 and any(NAMED_BY_TEMPLATE in p for p in ans["problems"])
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"][:2]], capsys)
    assert code == 0 and ans["targets"]["new"]["written"] == 4
    # a kit from `new` is local too: its defaults are the template's, listed as such
    d = tmp_path / "fresh"
    assert tpj(["migrate", "new", "fresh", "--from", "sql", "--to", "sql", "--out", str(d)], capsys)[0] == 0
    code, ans = tpj(["migrate", "check", str(d)], capsys)
    w = next(x for x in ans["destinations"] if x["role"] == "writer")
    assert w["origin"] == "template" and w["where"].startswith("postgresql://localhost/app/public.customers")


def _other_db(tmp_path):
    other = tmp_path / "someone-elses.db"
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE customers (legacy_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, created TEXT)")
    c.commit()
    c.close()
    return other


def test_the_mark_follows_the_value_an_edited_mapping_keeps_the_refusal(sqlkit, capsys, tmp_path):
    # session-lead seq 3832: a user who tweaks a mapping does not lose the refusal on a destination never touched
    other = _other_db(tmp_path)
    _default_target(sqlkit["kit"], other)
    _from_library(sqlkit["kit"])
    p = os.path.join(sqlkit["kit"], "proxy.yaml")
    text = open(p).read().replace("email: $.payload.email", "email: {path: $.payload.email, default: null}")
    assert "default: null" in text
    open(p, "w").write(text)
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"][:2]], capsys)
    assert code == 1 and "set TARGET_PATH yourself" in ans["problems"][0] and RUN._rows(other) == []
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"]], capsys)
    assert code == 0 and ans["targets"]["new"]["written"] == 4 and RUN._rows(other) == []


def test_a_destination_the_user_changed_in_the_kit_is_theirs(sqlkit, capsys, tmp_path):
    other = _other_db(tmp_path)
    p = os.path.join(sqlkit["kit"], "proxy.yaml")
    open(p, "w").write(RUN.PROXY.replace('path: "${TARGET_PATH}"', f'path: "{other}"'))
    _from_library(sqlkit["kit"])                                   # the template ships the literal `other`
    p2 = os.path.join(sqlkit["kit"], "proxy.yaml")
    open(p2, "w").write(RUN.PROXY.replace('path: "${TARGET_PATH}"', f'path: "{sqlkit["target"]}"'))
    code, ans = tpj(["migrate", "check", sqlkit["kit"], *sqlkit["sets"]], capsys)
    w = next(d for d in ans["destinations"] if d["role"] == "writer")
    assert w["origin"] == "you" and w["changed_from_template"] is True
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"]], capsys)
    assert code == 0 and RUN._rows(other) == []


def test_a_kit_its_author_published_is_not_a_library_kit(sqlkit, capsys):
    # publish writes template.json and no copy of the files: the author's own defaults are not refused
    _default_target(sqlkit["kit"], sqlkit["target"])
    from theprotocol.proxy.migrate import load_kit
    os.makedirs(os.path.join(sqlkit["kit"], ".migrate"), exist_ok=True)
    json.dump({"id": "wtpl_1", "version": 1, "content_hash": load_kit(sqlkit["kit"]).content_hash},
              open(os.path.join(sqlkit["kit"], ".migrate", "template.json"), "w"))
    code, ans = tpj(["migrate", "load", sqlkit["kit"], "--confirm-destinations", *sqlkit["sets"][:2]], capsys)
    assert code == 0, ans


def test_the_filled_engine_decides_which_part_is_the_destination_and_a_connect_args_port_shows():
    # session-tester seq 3850: engine ${TARGET_ENGINE} with sqlite chosen keeps host and path in the raw config
    from theprotocol.proxy.migrate.params import fill
    raw = _doc({"new": {"type": "sql_upsert", "config": {"engine": "${E}", "host": "${H}", "database": "app",
                                                         "path": "${P}", "table": "c", "key": ["id"],
                                                         "connect_args": {"port": "${PORT}"}}}})
    lite = listing(fill(raw, {"E": "sqlite", "H": "localhost", "P": "/srv/r.db", "PORT": "55442"}), raw, {"E", "P"})[0]
    assert lite["where"] == "sqlite:/srv/r.db table c" and lite["origin"] == "you"
    pg = listing(fill(raw, {"E": "postgresql", "H": "127.0.0.1", "P": "x.db", "PORT": "55442"}), raw, {"E", "H"})[0]
    assert pg["where"] == "postgresql://127.0.0.1:55442/app/c" and pg["origin"] == "template"   # database: a literal
