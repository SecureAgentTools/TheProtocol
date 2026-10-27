"""§DEPS sqla-driver-pin (2026-09-29): every SYNC engine names its driver, psycopg2, on SQLAlchemy 2.0 and 2.1 alike.

A plain `postgresql://` is psycopg2 on SQLAlchemy 2.0 and psycopg (3) on 2.1 (its `postgresql` extra became psycopg).
The registry image installs both drivers, so on 2.1 the migration bridge (every boot) and alembic would switch to
psycopg 3 silently, behind pgbouncer's transaction pooling. `core.dsn.sync_engine_url` names psycopg2 at each sync site
(the bridge, alembic's offline and online paths), so today's driver stays whichever SQLAlchemy is installed.

The CONTROL is the second test: SQLAlchemy's own `make_url(...).get_dialect()` names the driver a URL resolves to (no
database needed). The bare form resolves to psycopg on 2.1: that is the change these sites exist to absorb. The AST gate
at the end carries its own control: the pre-pin form of alembic/env.py must be refused.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
import sqlalchemy
from sqlalchemy.engine import make_url

from agentvault_registry.core.dsn import SYNC_PG_DRIVER, sync_engine_url

HERE = pathlib.Path(__file__).resolve()
ENV_PY = HERE.parents[1] / "alembic" / "env.py"

_SA_21 = tuple(int(p) for p in sqlalchemy.__version__.split(".")[:2]) >= (2, 1)


@pytest.mark.parametrize(
    "given, expected",
    [
        ("postgresql://u:p@db:5432/reg", "postgresql+psycopg2://u:p@db:5432/reg"),
        ("postgresql+asyncpg://u:p@pgbouncer:6432/reg", "postgresql+psycopg2://u:p@pgbouncer:6432/reg"),
        # a driver already named is a choice, never overridden
        ("postgresql+psycopg2://u:p@db/reg", "postgresql+psycopg2://u:p@db/reg"),
        ("postgresql+psycopg://u:p@db/reg", "postgresql+psycopg://u:p@db/reg"),
        ("postgresql+pg8000://u:p@db/reg", "postgresql+pg8000://u:p@db/reg"),
        # other databases and the empty value pass through
        ("sqlite:///./x.db", "sqlite:///./x.db"),
        ("sqlite://", "sqlite://"),
        ("", ""),
        # only the scheme changes: the rest comes back byte for byte (the doctrine's safe special set, a quoted @,
        # a query string); nothing is parsed and re-rendered, so nothing is re-quoted
        ("postgresql://reg:a!b%40c^d*(e)_f+g-h=i?@db:5432/reg?sslmode=verify-full&application_name=x",
         "postgresql+psycopg2://reg:a!b%40c^d*(e)_f+g-h=i?@db:5432/reg?sslmode=verify-full&application_name=x"),
        # a scheme that merely CONTAINS the word is not rewritten
        ("postgresqlx://u:p@db/reg", "postgresqlx://u:p@db/reg"),
    ],
)
def test_sync_engine_url_names_psycopg2_and_changes_nothing_else(given, expected):
    assert sync_engine_url(given) == expected
    assert sync_engine_url(sync_engine_url(given)) == expected  # idempotent: a second pass changes nothing


def test_control_the_bare_form_is_psycopg3_on_21_and_the_pinned_form_is_psycopg2_on_both():
    bare = "postgresql://u:p@db:5432/reg"
    # SQLAlchemy's own answer, no database: which driver does each form resolve to on the INSTALLED SQLAlchemy?
    bare_driver = make_url(bare).get_dialect().driver
    pinned_driver = make_url(sync_engine_url(bare)).get_dialect().driver
    assert bare_driver == ("psycopg" if _SA_21 else "psycopg2"), (sqlalchemy.__version__, bare_driver)
    assert pinned_driver == "psycopg2", (sqlalchemy.__version__, pinned_driver)
    asyncpg_form = "postgresql+asyncpg://u:p@db:5432/reg"
    assert make_url(sync_engine_url(asyncpg_form)).get_dialect().driver == "psycopg2"
    assert SYNC_PG_DRIVER == "postgresql+psycopg2"


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"DATABASE_URL_SYNC": "postgresql://reg:p@pgbouncer:6432/reg"}, "postgresql+psycopg2://reg:p@pgbouncer:6432/reg"),
        ({"DATABASE_URL": "postgresql+asyncpg://reg:p@pgbouncer:6432/reg"}, "postgresql+psycopg2://reg:p@pgbouncer:6432/reg"),
    ],
)
def test_migration_bridge_builds_its_engine_on_psycopg2(monkeypatch, env, expected):
    import agentvault_registry.migration_bridge as mb

    class _Stop(Exception):
        pass

    seen = []

    def _fake_create_engine(url, *a, **k):
        seen.append(url)
        raise _Stop()

    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(mb, "create_engine", _fake_create_engine)
    with pytest.raises(_Stop):
        mb.run()
    assert seen == [expected]
    assert make_url(seen[0]).get_dialect().driver == "psycopg2"


def _alembic_env_findings(source: str) -> list[str]:
    """Every URL alembic's env hands SQLAlchemy must come from sync_engine_url(...) in the same function.

    Checked: context.configure(url=<name>) (offline) and <cfg>["sqlalchemy.url"] = <name> (online, engine_from_config).
    """
    out: list[str] = []
    tree = ast.parse(source)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        pinned = set()
        for n in ast.walk(fn):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                    and getattr(n.value.func, "id", None) == "sync_engine_url"):
                pinned |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "configure":
                for kw in n.keywords:
                    if kw.arg == "url" and not (isinstance(kw.value, ast.Name) and kw.value.id in pinned):
                        out.append(f"{fn.name}:{n.lineno} context.configure(url=...) not from sync_engine_url")
            if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Subscript)
                    and isinstance(n.targets[0].slice, ast.Constant) and n.targets[0].slice.value == "sqlalchemy.url"):
                v = n.value
                ok = (isinstance(v, ast.Name) and v.id in pinned) or (
                    isinstance(v, ast.Call) and getattr(v.func, "id", None) == "sync_engine_url")
                if not ok:
                    out.append(f"{fn.name}:{n.lineno} sqlalchemy.url not from sync_engine_url")
    return out


def test_alembic_env_names_the_sync_driver_offline_and_online():
    src = ENV_PY.read_text(encoding="utf-8")
    findings = _alembic_env_findings(src)
    assert findings == [], findings
    # both paths were looked at: an empty finding list over a file with no sites would prove nothing
    tree = ast.parse(src)
    fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {"run_migrations_offline", "run_migrations_online"} <= fns
    assert src.count("sync_engine_url(") >= 2


def test_control_the_pre_pin_alembic_env_is_refused():
    pre_pin = '''
def run_migrations_offline():
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

def run_migrations_online():
    db_url = settings.DATABASE_URL
    sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    connectable_config = {}
    connectable_config["sqlalchemy.url"] = sync_db_url
'''
    findings = _alembic_env_findings(pre_pin)
    assert len(findings) == 2, findings
