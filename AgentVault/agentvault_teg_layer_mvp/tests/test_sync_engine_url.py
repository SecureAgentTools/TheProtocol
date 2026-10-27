"""§DEPS sqla-driver-pin (2026-09-29): every SYNC engine the TEG builds names its driver, psycopg2, on SQLAlchemy 2.0 and 2.1.

A plain `postgresql://` is psycopg2 on SQLAlchemy 2.0 and psycopg (3) on 2.1. The TEG installs psycopg2 only, so on 2.1
the engine every transfer uses (database/db_session.py) would fail at import, and the migration bridge and alembic
with it. `core/db_url.sync_engine_url` names psycopg2 at each site; no DATABASE_URL carrier changes.

The CONTROL is SQLAlchemy's own `make_url(...).get_dialect()`, which names the driver a URL resolves to without a
database or the driver module: the bare form resolves to psycopg on 2.1. The alembic gate carries its own control
(the pre-pin env.py form must be refused). No database, no network.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, "/app")
HERE = pathlib.Path(__file__).resolve()
TEG_ROOT = HERE.parents[1]
if str(TEG_ROOT) not in sys.path:
    sys.path.insert(0, str(TEG_ROOT))

import sqlalchemy  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from src.teg_core_service.core.db_url import SYNC_PG_DRIVER, sync_engine_url  # noqa: E402

ENV_PY = TEG_ROOT / "alembic" / "env.py"
_SA_21 = tuple(int(p) for p in sqlalchemy.__version__.split(".")[:2]) >= (2, 1)


@pytest.mark.parametrize(
    "given, expected",
    [
        ("postgresql://teg:p@db:5432/teg", "postgresql+psycopg2://teg:p@db:5432/teg"),
        ("postgresql+asyncpg://teg:p@pgbouncer:6432/teg", "postgresql+psycopg2://teg:p@pgbouncer:6432/teg"),
        ("postgresql+psycopg2://teg:p@db/teg", "postgresql+psycopg2://teg:p@db/teg"),
        ("postgresql+psycopg://teg:p@db/teg", "postgresql+psycopg://teg:p@db/teg"),
        ("sqlite:///./teg_database.db", "sqlite:///./teg_database.db"),
        ("", ""),
        ("postgresql://teg:a!b%40c^d*(e)_f+g-h=i@db:5432/teg?sslmode=verify-full",
         "postgresql+psycopg2://teg:a!b%40c^d*(e)_f+g-h=i@db:5432/teg?sslmode=verify-full"),
        ("postgresqlx://teg:p@db/teg", "postgresqlx://teg:p@db/teg"),
    ],
)
def test_sync_engine_url_names_psycopg2_and_changes_nothing_else(given, expected):
    assert sync_engine_url(given) == expected
    assert sync_engine_url(sync_engine_url(given)) == expected


def test_control_the_bare_form_is_psycopg3_on_21_and_the_pinned_form_is_psycopg2_on_both():
    bare = "postgresql://teg:p@db:5432/teg"
    bare_driver = make_url(bare).get_dialect().driver
    assert bare_driver == ("psycopg" if _SA_21 else "psycopg2"), (sqlalchemy.__version__, bare_driver)
    assert make_url(sync_engine_url(bare)).get_dialect().driver == "psycopg2"
    assert SYNC_PG_DRIVER == "postgresql+psycopg2"


def test_the_transfer_engine_is_built_on_psycopg2():
    # db_session builds its engines at import from settings.database_url (CI and the fleet: a plain postgresql://).
    # Building an engine opens no connection, so no database is needed.
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a postgresql URL here; the TEG suites always run with one")
    from src.teg_core_service.database import db_session
    assert db_session.engine.url.drivername == "postgresql+psycopg2"
    assert db_session.engine.dialect.driver == "psycopg2"
    # the async engine is untouched: asyncpg, named by db_session itself
    if db_session.async_engine is not None:
        assert db_session.async_engine.dialect.driver == "asyncpg"


@pytest.mark.parametrize(
    "given",
    ["postgresql://teg:p@pgbouncer:6432/teg", "postgresql+asyncpg://teg:p@pgbouncer:6432/teg"],
)
def test_migration_bridge_builds_its_engine_on_psycopg2(monkeypatch, given):
    from src.teg_core_service import migration_bridge as mb

    class _Stop(Exception):
        pass

    seen = []

    def _fake_create_engine(url, *a, **k):
        seen.append(url)
        raise _Stop()

    monkeypatch.setenv("DATABASE_URL", given)
    monkeypatch.setattr(mb, "create_engine", _fake_create_engine)
    with pytest.raises(_Stop):
        mb.run()
    assert seen == ["postgresql+psycopg2://teg:p@pgbouncer:6432/teg"]


def _alembic_env_findings(source: str) -> list[str]:
    """Every URL the TEG's alembic env hands SQLAlchemy must pass through sync_engine_url(...)."""
    out: list[str] = []
    tree = ast.parse(source)

    def _pinned(v):
        return isinstance(v, ast.Call) and getattr(v.func, "id", None) == "sync_engine_url"

    for n in ast.walk(tree):
        # config.set_main_option("sqlalchemy.url", <value>)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "set_main_option" and len(n.args) == 2:
            key = n.args[0]
            if isinstance(key, ast.Constant) and key.value == "sqlalchemy.url" and not _pinned(n.args[1]):
                out.append(f"{n.lineno} set_main_option(sqlalchemy.url) not from sync_engine_url")
        # configuration['sqlalchemy.url'] = <value>
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Subscript)
                and isinstance(n.targets[0].slice, ast.Constant) and n.targets[0].slice.value == "sqlalchemy.url"
                and not _pinned(n.value)):
            out.append(f"{n.lineno} sqlalchemy.url not from sync_engine_url")
    return out


def test_alembic_env_names_the_sync_driver():
    src = ENV_PY.read_text(encoding="utf-8")
    assert _alembic_env_findings(src) == []
    assert src.count("sync_engine_url(settings.database_url)") >= 2  # both sites were looked at


def test_control_the_pre_pin_alembic_env_is_refused():
    pre_pin = '''
config.set_main_option("sqlalchemy.url", settings.database_url)
def run_migrations_online():
    configuration = config.get_section(config.config_ini_section)
    configuration['sqlalchemy.url'] = settings.database_url
'''
    assert len(_alembic_env_findings(pre_pin)) == 2
