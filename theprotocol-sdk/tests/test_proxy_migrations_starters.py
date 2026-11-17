"""V0664 Migrate (M7): the three free starter kits in proxy/migrations/ (sql-to-postgres, csv-to-postgres, sql-to-rest).

Each kit is copied into a temporary folder first (a dry run writes KIT/.migrate/), then driven through `tp-proxy migrate`:

- `check` passes: the manifest, the spec with its parameters filled, the caps, and no secret written as a value;
- `dry-run --sample` exits 0 with the counts the samples were made for: rows mapped, and rows refused per reason (each
  sample refuses a few rows on purpose, so a first dry run shows rejected_by_reason); no sample value in any report;
- load, reconcile and rollback against stand-ins: a SQLite file for the PostgreSQL targets, a folder of CSV exports,
  and the sql-to-rest kit's own fake API (fake/products_api.py, POST /products and GET /products?ids=);
- the same against a real PostgreSQL when TP_PROXY_TEST_POSTGRESQL names one (skipped, saying why, when not).

Red before M7: there is no proxy/migrations/.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import threading
import uuid
from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("jsonschema")

KITS = Path(__file__).resolve().parents[1] / "proxy" / "migrations"
NAMES = ("sql-to-postgres", "csv-to-postgres", "sql-to-rest")

# what each sample was made for (proxy/migrations' samples: invented rows, a few refused on purpose)
EXPECT = {
    "sql-to-postgres": {"source": "legacy", "mapping": "customers", "target": "crm", "rows": 480, "mapped": 473,
                        "reasons": {"signed_up: not a date in the format %d.%m.%Y": 4,
                                    "status: no map entry and no map_default": 3}},
    "csv-to-postgres": {"source": "exports", "mapping": "orders", "target": "shop", "rows": 360, "mapped": 355,
                        "reasons": {"amount: not a number": 3,
                                    "ordered_at: not a datetime in the format %Y-%m-%d %H:%M": 2}},
    "sql-to-rest": {"source": "legacy", "mapping": "products", "target": "catalog", "rows": 240, "mapped": 235,
                    "reasons": {"price: not a number": 3, "active: not a boolean": 2}},
}
# a secret is a reference given when the kit runs (never a default, never a value)
SECRETS = {
    "sql-to-postgres": ["--set", "SOURCE_PASSWORD=env:LEGACY_DB_PASSWORD", "--set", "TARGET_PASSWORD=env:TARGET_DB_PASSWORD"],
    "csv-to-postgres": ["--set", "TARGET_PASSWORD=env:TARGET_DB_PASSWORD"],
    "sql-to-rest": ["--set", "SOURCE_PASSWORD=env:LEGACY_DB_PASSWORD", "--set", "PRODUCTS_TOKEN=env:PRODUCTS_API_TOKEN"],
}
# values that sit in the samples and must never appear in a report (counts, names and hashes only)
VALUES = ["Customer 0007", "customer0001@example.invalid", "Product 0003", "SKU-0004", "100002", "n/a", "TBD",
          "31.02.2021"]


def tp(argv, capsys):
    from theprotocol.proxy.cli import main
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def tpj(argv, capsys):
    code, out, err = tp([*argv, "--json"], capsys)
    try:
        return code, json.loads(out)
    except ValueError:
        raise AssertionError(f"not JSON (exit {code}): {out[:400]!r} {err[:400]!r}")


def _module(path: Path):
    was, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # a __pycache__ in the kit would fail its check
    try:
        spec = importlib.util.spec_from_file_location(f"m7_{path.stem}_{uuid.uuid4().hex[:6]}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = was


@pytest.fixture
def kit(tmp_path):
    def copy(name: str) -> Path:
        d = tmp_path / name
        shutil.copytree(KITS / name, d)
        return d
    return copy


def _reports(kit_dir: Path):
    d = kit_dir / ".migrate" / "reports"
    return [p.read_text(encoding="utf-8") for p in sorted(d.iterdir())] if d.is_dir() else []


def _no_values(kit_dir: Path):
    for text in _reports(kit_dir):
        for v in VALUES:
            assert v not in text, f"a sample value is in a report: {v!r}"


# ── the kits are there, each with its five parts, and the folder's README lists them ─────────────────────────────────

def test_the_three_kits_are_there_and_listed():
    readme = (KITS / "README.md").read_text(encoding="utf-8")
    for name in NAMES:
        d = KITS / name
        for part in ("migration.yaml", "proxy.yaml", "README.md"):
            assert (d / part).is_file(), f"{name}/{part}"
        for part in ("sample", "fake"):
            assert (d / part).is_dir() and any((d / part).iterdir()), f"{name}/{part}/"
        assert f"{name}/" in readme, f"proxy/migrations/README.md does not list {name}"
        text = (d / "README.md").read_text(encoding="utf-8")
        for heading in ("What it moves", "What it needs", "Try it free", "The real run", "Check it"):
            assert heading in text, f"{name}/README.md has no {heading!r}"
        assert f"tp-proxy migrate dry-run proxy/migrations/{name} --sample" in text


@pytest.mark.parametrize("name", NAMES)
def test_every_secret_is_a_secret_parameter_given_when_the_kit_runs(name):
    import yaml
    from theprotocol.proxy.spec import SECRET_KEY
    manifest = yaml.safe_load((KITS / name / "migration.yaml").read_text(encoding="utf-8"))
    doc = yaml.safe_load((KITS / name / "proxy.yaml").read_text(encoding="utf-8"))
    params = manifest["parameters"]
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and SECRET_KEY.search(str(k)):
                    found.append((f"{path}.{k}", v))
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(doc, "proxy.yaml")
    assert found, f"{name}: no secret key in proxy.yaml (the kit needs a login)"
    for where, v in found:
        assert v.startswith("${") and v.endswith("}"), f"{where} is not a parameter"
        p = params[v[2:-1]]
        assert p.get("secret") is True, f"{where}: {v} is not a secret parameter"
        assert "default" not in p and "env:" in p.get("description", ""), f"{where}: {v} names no reference to give"


# the contract's DESTINATIONS rule (section D): a published kit names no destination of its own
DESTINATION_KEYS = {"sqlpoll": ("host", "database", "path"), "sql_upsert": ("host", "database", "path"),
                    "rest": ("url",), "file_out": ("path",), "filedrop": ("path",), "sftp": ("host", "path")}
LOCAL = ("localhost", "127.0.0.1", "::1")


def _is_local(v) -> bool:
    from urllib.parse import urlsplit
    v = str(v)
    if "://" in v:
        return urlsplit(v).hostname in LOCAL
    if v in LOCAL:
        return True
    return not v.startswith(("/", "~", "..")) and ".." not in v.split("/") and ":" not in v


@pytest.mark.parametrize("name", NAMES)
def test_every_destination_is_a_parameter_with_a_local_default(name):
    import yaml
    manifest = yaml.safe_load((KITS / name / "migration.yaml").read_text(encoding="utf-8"))
    doc = yaml.safe_load((KITS / name / "proxy.yaml").read_text(encoding="utf-8"))
    params, seen = manifest["parameters"], 0
    for section in ("sources", "sinks"):
        for n, part in (doc.get(section) or {}).items():
            for k in DESTINATION_KEYS.get(part["type"], ()):
                if k not in part["config"]:
                    continue
                v, seen = part["config"][k], seen + 1
                assert isinstance(v, str) and v.startswith("${") and v.endswith("}"), f"{section}.{n}.{k} is not a ${{PARAM}}"
                p = params[v[2:-1]]
                assert "default" not in p or _is_local(p["default"]), f"{section}.{n}.{k}: {v}'s default is not local"
    for i, r in enumerate(manifest.get("reconcile") or []):
        read = (r.get("target") or {}).get("read")
        if read:
            seen += 1
            assert read["url"].startswith("${"), f"reconcile[{i}].target.read.url is not a ${{PARAM}}"
            assert _is_local(params[read["url"][2:-1]]["default"])
    assert seen >= 2, f"{name}: fewer destinations than a source and a sink"


def test_the_readme_sftp_variant_of_csv_to_postgres_checks_and_dry_runs(kit, tmp_path, capsys):
    pytest.importorskip("paramiko")
    import re
    d, e = kit("csv-to-postgres"), EXPECT["csv-to-postgres"]
    readme = (d / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", readme, re.S).group(1)
    spec = (d / "proxy.yaml").read_text(encoding="utf-8")
    i, j = spec.index("  exports:\n"), spec.index("sinks:\n")
    (d / "proxy.yaml").write_text(spec[:i] + block + spec[j:], encoding="utf-8")
    m = (d / "migration.yaml").read_text(encoding="utf-8")
    extra = ("  SFTP_HOST: {description: the SFTP server, default: localhost}\n"
             "  SFTP_USER: {description: a read-only account, default: exports}\n"
             "  SFTP_KEY: {description: 'its private key, as a reference such as file:/path', secret: true}\n"
             "  SFTP_KNOWN_HOSTS: {description: the server's host key file (an absolute path)}\n")
    (d / "migration.yaml").write_text(m.replace("parameters:\n", "parameters:\n" + extra, 1), encoding="utf-8")
    (tmp_path / "known_hosts").write_text("", encoding="utf-8")
    sets = ["--set", f"SFTP_KNOWN_HOSTS={tmp_path / 'known_hosts'}"]
    code, ans = tpj(["migrate", "check", str(d), *sets], capsys)
    assert code == 0 and ans["sources"] == {"exports": "sftp"}, ans
    code, rep = tpj(["migrate", "dry-run", str(d), "--sample", *sets], capsys)
    assert code == 0, rep
    m = rep["mappings"][e["mapping"]]
    assert (m["mapped"], m["rejected_by_reason"]) == (e["mapped"], e["reasons"])
    assert rep["reconcile"][e["mapping"]]["verdict"] == "pass"


@pytest.mark.parametrize("name", NAMES)
def test_check_passes(name, kit, capsys):
    d = kit(name)
    code, ans = tpj(["migrate", "check", str(d)], capsys)
    assert code == 0, ans
    assert ans["valid"] is True and ans["kit"] == name and ans["notes"] == []
    assert ans["files"] <= 64 and ans["bytes"] <= 2 * 1024 * 1024
    assert ans["template"] == {"local": ans["content_hash"]}


# ── dry-run --sample: no account, no system ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", NAMES)
def test_dry_run_on_the_sample_gives_the_counts_it_was_made_for(name, kit, capsys):
    d, e = kit(name), EXPECT[name]
    code, rep = tpj(["migrate", "dry-run", str(d), "--sample"], capsys)
    assert code == 0, rep
    assert rep["step"] == "dry_run" and rep["sample"] is True and rep["verdict"] == "pass"
    assert rep["sources"][e["source"]]["rows"] == e["rows"]
    m = rep["mappings"][e["mapping"]]
    assert (m["taken"], m["mapped"], m["rejected"]) == (e["rows"], e["mapped"], e["rows"] - e["mapped"])
    assert m["rejected_by_reason"] == e["reasons"]
    t = rep["targets"][e["target"]]
    assert (t["written"], t["failed"], t["pending"], t["scratch"]) == (e["mapped"], 0, 0, True)
    r = rep["reconcile"][e["mapping"]]
    assert (r["source"], r["target"], r["missing"], r["extra"], r["mismatched"], r["verdict"]) == \
        (e["mapped"], e["mapped"], 0, 0, 0, "pass")
    _no_values(d)


def test_the_plan_on_the_sample_leaves_no_target_field_without_a_source(kit, capsys):
    for name in NAMES:
        d, e = kit(name), EXPECT[name]
        code, rep = tpj(["migrate", "plan", str(d), "--sample"], capsys)
        assert code == 0, (name, rep)
        m = rep["mappings"][e["mapping"]]
        assert m["no_source"] == [], (name, m)


# ── the real run against stand-ins ───────────────────────────────────────────────────────────────────────────────────

def _sqlite_target(path: Path, ddl: Path) -> None:
    c = sqlite3.connect(path)
    try:
        c.executescript(ddl.read_text(encoding="utf-8"))
        c.commit()
    finally:
        c.close()


def _count(db: Path, table: str) -> int:
    c = sqlite3.connect(db)
    try:
        return c.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    finally:
        c.close()


def _run_load_reconcile_rollback(d: Path, sets, e, capsys, *, rows_before, rows_now):
    code, rep = tpj(["migrate", "load", str(d), *sets, "--confirm-destinations"], capsys)
    assert code == 0, rep
    assert rep["targets"][e["target"]]["written"] == e["mapped"], rep["targets"]
    assert rep["mappings"][e["mapping"]]["rejected_by_reason"] == e["reasons"]
    assert rows_now() == rows_before + e["mapped"]
    code, rep = tpj(["migrate", "load", str(d), *sets, "--confirm-destinations"], capsys)          # exactly once: a second load moves nothing
    assert code == 0, rep
    assert rows_now() == rows_before + e["mapped"]
    code, rep = tpj(["migrate", "reconcile", str(d), *sets], capsys)
    assert code == 0, rep
    r = rep["reconcile"][e["mapping"]]
    assert (r["source"], r["target"], r["missing"], r["extra"], r["mismatched"]) == (e["mapped"], e["mapped"], 0, 0, 0)
    _no_values(d)
    return rep


def test_sql_to_postgres_loads_reconciles_and_rolls_back_on_sqlite_stand_ins(kit, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LEGACY_DB_PASSWORD", "unused-by-sqlite")
    monkeypatch.setenv("TARGET_DB_PASSWORD", "unused-by-sqlite")
    d, e = kit("sql-to-postgres"), EXPECT["sql-to-postgres"]
    legacy, target = tmp_path / "legacy.db", tmp_path / "target.db"
    _module(d / "fake" / "make_legacy.py").build(d / "sample" / "customers.jsonl", legacy)
    _sqlite_target(target, d / "fake" / "target_sqlite.sql")
    sets = ["--set", "SOURCE_ENGINE=sqlite", "--set", f"SOURCE_PATH={legacy}", *SECRETS["sql-to-postgres"],
            "--set", "TARGET_ENGINE=sqlite", "--set", f"TARGET_PATH={target}", "--set", "TARGET_TABLE=customers"]
    _run_load_reconcile_rollback(d, sets, e, capsys, rows_before=0, rows_now=lambda: _count(target, "customers"))
    c = sqlite3.connect(target)
    try:
        assert c.execute("SELECT full_name FROM customers WHERE legacy_id = 7").fetchone() == ("Customer 0007",)
        names = [r[0] for r in c.execute("SELECT full_name FROM customers")]
        assert names and all(n == n.strip() for n in names)                   # the trim
        assert {r[0] for r in c.execute("SELECT status FROM customers")} <= {"active", "inactive", "blocked"}
        dates = [r[0] for r in c.execute("SELECT signed_up FROM customers")]
        assert all(len(x) == 10 and x[4] == "-" and x[7] == "-" for x in dates)  # dd.mm.yyyy became ISO dates
    finally:
        c.close()
    code, rep = tpj(["migrate", "rollback", str(d), "--yes", *sets], capsys)
    assert code == 0, rep
    assert rep["restored"] == e["mapped"] and _count(target, "customers") == 0


def test_csv_to_postgres_loads_a_folder_of_exports_and_rolls_back(kit, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TARGET_DB_PASSWORD", "unused-by-sqlite")
    d, e = kit("csv-to-postgres"), EXPECT["csv-to-postgres"]
    export, target = tmp_path / "export", tmp_path / "target.db"
    _module(d / "fake" / "make_export.py").split(d / "sample" / "orders.csv", export, files=3)
    assert len(list(export.glob("*.csv"))) == 3
    _sqlite_target(target, d / "fake" / "target_sqlite.sql")
    c = sqlite3.connect(target)
    c.execute("INSERT INTO orders VALUES (100005, 1, '2020-01-01T00:00:00Z', '1.00', 'EUR', 'open')")   # already there
    c.commit()
    c.close()
    sets = ["--set", f"EXPORT_DIR={export}", *SECRETS["csv-to-postgres"], "--set", "TARGET_ENGINE=sqlite", "--set", f"TARGET_PATH={target}",
            "--set", "TARGET_TABLE=orders"]
    code, rep = tpj(["migrate", "load", str(d), *sets, "--confirm-destinations"], capsys)
    assert code == 0, rep
    assert rep["targets"][e["target"]]["written"] == e["mapped"]
    assert _count(target, "orders") == e["mapped"]                         # 100005 was updated, not added
    c = sqlite3.connect(target)
    try:
        amounts = [r[0] for r in c.execute("SELECT amount FROM orders")]
        assert all(len(str(a).split(".")[1]) == 2 for a in amounts)        # rounded to 2
        ats = [r[0] for r in c.execute("SELECT ordered_at FROM orders")]
        assert all(str(a).endswith("Z") for a in ats)                      # Europe/Berlin to UTC
        assert {r[0] for r in c.execute("SELECT currency FROM orders")} == {"EUR"}
    finally:
        c.close()
    code, rep = tpj(["migrate", "reconcile", str(d), *sets], capsys)
    assert code == 0, rep
    r = rep["reconcile"][e["mapping"]]
    assert (r["source"], r["target"], r["missing"], r["extra"], r["mismatched"]) == (e["mapped"], e["mapped"], 0, 0, 0)
    code, rep = tpj(["migrate", "rollback", str(d), "--yes", *sets], capsys)
    assert code == 0, rep
    c = sqlite3.connect(target)
    try:
        assert c.execute("SELECT * FROM orders").fetchall() == [(100005, 1, "2020-01-01T00:00:00Z", "1.00", "EUR", "open")]
    finally:
        c.close()
    _no_values(d)


@pytest.fixture
def products_api(kit):
    """The sql-to-rest kit's fake API on a free port (PRODUCTS_URL names it, for the load and the read-back)."""
    def start(d: Path, token: str):
        mod = _module(d / "fake" / "products_api.py")
        srv = mod.make_server("127.0.0.1", 0, token=token)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        started.append(srv)
        return srv, f"http://127.0.0.1:{port}/products"
    started = []
    yield start
    for s in started:
        s.shutdown()
        s.server_close()


def test_sql_to_rest_loads_into_its_fake_api_reconciles_and_its_rollback_is_manual(kit, tmp_path, capsys,
                                                                                  monkeypatch, products_api):
    import httpx
    token = uuid.uuid4().hex
    monkeypatch.setenv("LEGACY_DB_PASSWORD", "unused-by-sqlite")
    monkeypatch.setenv("PRODUCTS_API_TOKEN", token)
    d, e = kit("sql-to-rest"), EXPECT["sql-to-rest"]
    legacy = tmp_path / "legacy.db"
    _module(d / "fake" / "make_legacy.py").build(d / "sample" / "products.jsonl", legacy)
    srv, url = products_api(d, token)
    sets = ["--set", "SOURCE_ENGINE=sqlite", "--set", f"SOURCE_PATH={legacy}", "--set", f"PRODUCTS_URL={url}",
            *SECRETS["sql-to-rest"]]
    code, rep = tpj(["migrate", "load", str(d), *sets, "--confirm-destinations"], capsys)
    assert code == 0, rep
    assert rep["targets"][e["target"]]["written"] == e["mapped"]
    assert len(srv.store) == e["mapped"]
    assert len(srv.keys) == e["mapped"] and all(k.startswith("tpx-") for k in srv.keys)   # the Idempotency-Key
    assert srv.refused_auth == 0
    one = httpx.get(f"{url}?ids=1,2,3").json()["items"]
    assert [p["id"] for p in one] == [1, 2, 3] and all(set(p) == {"id", "sku", "name", "price", "active"} for p in one)
    assert all(p["sku"].startswith("SKU-") for p in srv.store.values())       # trimmed, upper case
    assert all(isinstance(p["price"], str) and len(p["price"].split(".")[1]) == 2 for p in srv.store.values())
    assert all(isinstance(p["active"], bool) for p in srv.store.values())
    code, rep = tpj(["migrate", "load", str(d), *sets, "--confirm-destinations"], capsys)               # a second load sends nothing
    assert code == 0 and srv.posts == e["mapped"], (srv.posts, rep)
    code, rep = tpj(["migrate", "reconcile", str(d), *sets], capsys)
    assert code == 0, rep
    r = rep["reconcile"][e["mapping"]]
    assert (r["source"], r["target"], r["missing"], r["extra"], r["mismatched"]) == (e["mapped"], e["mapped"], 0, 0, 0)
    code, out, err = tp(["migrate", "rollback", str(d), "--yes", *sets], capsys)
    assert code == 1 and "README.md" in out + err
    assert len(srv.store) == e["mapped"]
    _no_values(d)


def test_the_fake_api_refuses_a_write_without_its_token(kit, products_api):
    import httpx
    d = kit("sql-to-rest")
    srv, url = products_api(d, "the-right-token")
    r = httpx.post(url, json={"id": 1, "sku": "SKU-0001", "name": "Product 0001", "price": "1.00", "active": True},
                   headers={"Authorization": "Bearer the-wrong-token"})
    assert r.status_code == 401 and srv.store == {} and srv.refused_auth == 1


# ── a real PostgreSQL, when the suite has one ────────────────────────────────────────────────────────────────────────

PG = os.environ.get("TP_PROXY_TEST_POSTGRESQL", "")


def _pg_why() -> str:
    if not PG:
        return "TP_PROXY_TEST_POSTGRESQL names no PostgreSQL (postgresql://user:<password>@host:port/db)"
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return "the proxy-postgresql extra (psycopg) is not installed"
    return ""


needs_pg = pytest.mark.skipif(bool(_pg_why()), reason=_pg_why() or "-")


@pytest.fixture
def pg_db():
    """A throwaway database on the suite's PostgreSQL, dropped afterwards: (connect kwargs, its name)."""
    import psycopg
    from urllib.parse import urlsplit, unquote
    u = urlsplit(PG)
    base = {"host": u.hostname, "port": u.port or 5432, "user": unquote(u.username or ""),
            "password": unquote(u.password or ""), "dbname": (u.path or "/postgres").lstrip("/") or "postgres"}
    name = f"tp_m7_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(**base, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    try:
        yield {**base, "dbname": name}
    finally:
        with psycopg.connect(**base, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _pg_sets(db, monkeypatch, var="TARGET_DB_PASSWORD"):
    monkeypatch.setenv(var, db["password"])
    return ["--set", "TARGET_ENGINE=postgresql", "--set", f"TARGET_HOST={db['host']}",
            "--set", f"TARGET_PORT={db['port']}", "--set", f"TARGET_DATABASE={db['dbname']}",
            "--set", f"TARGET_USER={db['user']}"]


def test_a_load_lists_its_destinations_and_waits_for_the_confirmation(kit, tmp_path, capsys, monkeypatch):
    """M11: load names every place the rows go and who named it, and starts only with --confirm-destinations."""
    monkeypatch.setenv("LEGACY_DB_PASSWORD", "unused-by-sqlite")
    monkeypatch.setenv("PRODUCTS_API_TOKEN", "unused")
    d = kit("sql-to-rest")
    legacy = tmp_path / "legacy.db"
    _module(d / "fake" / "make_legacy.py").build(d / "sample" / "products.jsonl", legacy)
    url = "http://127.0.0.1:9/products"          # nothing listens: the load must not even try
    sets = ["--set", "SOURCE_ENGINE=sqlite", "--set", f"SOURCE_PATH={legacy}", "--set", f"PRODUCTS_URL={url}",
            *SECRETS["sql-to-rest"]]
    code, ans = tpj(["migrate", "load", str(d), *sets], capsys)
    assert code == 1 and "--confirm-destinations" in ans["problems"][0], ans
    w = [x for x in ans["destinations"] if x["role"] == "writer"]
    assert [(x["name"], x["type"], x["origin"]) for x in w] == [("catalog", "rest", "you")]
    assert "127.0.0.1:9/products" in w[0]["where"]
    assert not (d / ".migrate" / "state.db").exists()           # nothing was loaded
    code, ans = tpj(["migrate", "load", str(d), *sets[:4], *SECRETS["sql-to-rest"]], capsys)   # PRODUCTS_URL: its default
    assert code == 1
    w = [x for x in ans["destinations"] if x["role"] == "writer"]
    assert w[0]["origin"] == "template" and w[0]["parameter"] == "PRODUCTS_URL"


@needs_pg
def test_sql_to_postgres_on_a_real_postgresql(kit, tmp_path, capsys, monkeypatch, pg_db):
    import psycopg
    monkeypatch.setenv("LEGACY_DB_PASSWORD", "unused-by-sqlite")
    d, e = kit("sql-to-postgres"), EXPECT["sql-to-postgres"]
    legacy = tmp_path / "legacy.db"
    _module(d / "fake" / "make_legacy.py").build(d / "sample" / "customers.jsonl", legacy)
    with psycopg.connect(**pg_db, autocommit=True) as c:
        c.execute((d / "fake" / "target_postgresql.sql").read_text(encoding="utf-8"))
    sets = ["--set", "SOURCE_ENGINE=sqlite", "--set", f"SOURCE_PATH={legacy}", *SECRETS["sql-to-postgres"],
            *_pg_sets(pg_db, monkeypatch)]

    def rows():
        with psycopg.connect(**pg_db) as c:
            return c.execute("SELECT count(*) FROM public.customers").fetchone()[0]
    _run_load_reconcile_rollback(d, sets, e, capsys, rows_before=0, rows_now=rows)
    with psycopg.connect(**pg_db) as c:
        t = c.execute("SELECT pg_typeof(signed_up)::text FROM public.customers LIMIT 1").fetchone()[0]
    assert t == "date"
    code, rep = tpj(["migrate", "rollback", str(d), "--yes", *sets], capsys)
    assert code == 0 and rep["restored"] == e["mapped"] and rows() == 0


@needs_pg
def test_csv_to_postgres_on_a_real_postgresql(kit, tmp_path, capsys, monkeypatch, pg_db):
    import psycopg
    d, e = kit("csv-to-postgres"), EXPECT["csv-to-postgres"]
    export = tmp_path / "export"
    _module(d / "fake" / "make_export.py").split(d / "sample" / "orders.csv", export, files=3)
    with psycopg.connect(**pg_db, autocommit=True) as c:
        c.execute((d / "fake" / "target_postgresql.sql").read_text(encoding="utf-8"))
    sets = ["--set", f"EXPORT_DIR={export}", *SECRETS["csv-to-postgres"], *_pg_sets(pg_db, monkeypatch)]

    def rows():
        with psycopg.connect(**pg_db) as c:
            return c.execute("SELECT count(*) FROM public.orders").fetchone()[0]
    _run_load_reconcile_rollback(d, sets, e, capsys, rows_before=0, rows_now=rows)
    code, rep = tpj(["migrate", "rollback", str(d), "--yes", *sets], capsys)
    assert code == 0 and rows() == 0
