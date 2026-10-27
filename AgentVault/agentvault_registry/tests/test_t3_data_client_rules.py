"""§MTLSHOPS V0379 (2026-09-15): the registry's data clients leave TLS to the environment, so T3 can turn it on by env alone.

agentvault2-b5's T3 (Postgres and Redis TLS) sets PGSSLMODE=verify-full with the PGSSL* paths and moves REDIS_URL to rediss://
with its ssl_* query parameters. asyncpg, libpq and redis-py take their TLS from that environment alone, so two shapes in code
would silently override it: an ssl argument on a database connection, and a Redis client built from anything but REDIS_URL.

  1. no create_async_engine / create_engine call, and no asyncpg or psycopg connect / create_pool call, passes `ssl` or a libpq
     ssl keyword (sslmode, sslrootcert, sslcert, sslkey, sslcrl), and no `connect_args` dict carries one of those keys;
  2. no Redis, StrictRedis, RedisCluster, ConnectionPool or BlockingConnectionPool is constructed directly; the allowed shapes
     are from_url(...) and Redis(connection_pool=<a pool from from_url>). The scan covers the modules AND the Python scripts
     they embed as `*_SCRIPT` string constants, because a module-level parse cannot see inside one (the chained tester's API
     script was the case; it is retired, §NIGHTLYPROV 2026-09-27).

Controls: the synthetic cases in the last test must be refused and accepted exactly as named, and the embedded-script case
proves the module-level parse alone would have missed it. T3_RULES_SRC=<a pre-V0379 copy of agentvault_registry> turns 2 RED
on the chained tester's host fallback.
"""
from __future__ import annotations

import ast
import os
import pathlib

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["T3_RULES_SRC"]) if os.environ.get("T3_RULES_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())

ENGINE_CALLS = {"create_async_engine", "create_engine"}
DRIVER_CALLS = {"connect", "create_pool"}
DRIVER_OWNERS = {"asyncpg", "psycopg2", "psycopg"}
SSL_KEYS = {"ssl", "sslmode", "sslrootcert", "sslcert", "sslkey", "sslcrl"}
REDIS_CTORS = {"Redis", "StrictRedis", "RedisCluster", "ConnectionPool", "BlockingConnectionPool"}


def _name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _owner(call):
    f = call.func
    return f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""


def engine_ssl_findings(tree, where):
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = _name(n)
        if name not in ENGINE_CALLS and not (name in DRIVER_CALLS and _owner(n) in DRIVER_OWNERS):
            continue
        for k in n.keywords:
            if k.arg in SSL_KEYS:
                out.append(f"{where}:{n.lineno} {name}({k.arg}=...)")
            elif k.arg == "connect_args" and isinstance(k.value, ast.Dict):
                keys = sorted(key.value for key in k.value.keys if isinstance(key, ast.Constant) and key.value in SSL_KEYS)
                if keys:
                    out.append(f"{where}:{n.lineno} {name}(connect_args={{{keys[0]!r}: ...}})")
    return out


def redis_direct_findings(tree, where):
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or _name(n) not in REDIS_CTORS:
            continue
        if _name(n) in ("Redis", "StrictRedis") and not n.args and any(k.arg == "connection_pool" for k in n.keywords):
            continue  # the pool it is handed is checked on its own: a pool built by hand is refused where it is built
        out.append(f"{where}:{n.lineno} {_name(n)}(...) built directly, not from REDIS_URL")
    return out


def embedded_scripts(tree):
    """Module-level `NAME_SCRIPT = '...'` string constants that parse as Python."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.endswith("_SCRIPT") and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            try:
                yield node.targets[0].id, ast.parse(node.value.value), node.lineno
            except SyntaxError:
                continue


def scan(text, rel):
    tree = ast.parse(text)
    engine, redis = engine_ssl_findings(tree, rel), redis_direct_findings(tree, rel)
    scripts = 0
    for name, script, lineno in embedded_scripts(tree):
        scripts += 1
        where = f"{rel}:{name}@{lineno}"
        engine += engine_ssl_findings(script, where)
        redis += redis_direct_findings(script, where)
    return engine, redis, scripts


def _tree():
    engine, redis, modules, scripts = [], [], 0, 0
    for path in sorted(SRC.rglob("*.py")):
        if "tests" in path.parts:
            continue
        try:
            e, r, s = scan(path.read_text(), path.relative_to(SRC).as_posix())
        except SyntaxError:
            continue
        modules, scripts = modules + 1, scripts + s
        engine += e
        redis += r
    return engine, redis, modules, scripts


def test_no_database_engine_or_pool_passes_its_own_ssl():
    engine, _, modules, _ = _tree()
    assert modules >= 200, f"only {modules} modules parsed: the scan is not looking at the tree"
    assert not engine, "\n".join(engine)


def test_every_redis_client_is_built_from_a_url_including_embedded_scripts():
    # The one embedded script this floor once counted was the chained tester's API script, retired with the Frame-A-era
    # provisioner tests (§NIGHTLYPROV 2026-09-27): the tree embeds none today, so the floor is the module count, and the
    # last test's embedded case proves the scan still reads inside a *_SCRIPT constant when one appears.
    _, redis, modules, _ = _tree()
    assert modules >= 200, f"only {modules} modules parsed: the scan is not looking at the tree"
    assert not redis, "\n".join(redis)


def test_the_rules_refuse_and_accept_as_named():
    engine_refused = {
        "engine connect_args ssl": "from sqlalchemy.ext.asyncio import create_async_engine\ne = create_async_engine(u, connect_args={'ssl': c})\n",
        "engine connect_args sslmode": "from sqlalchemy import create_engine\ne = create_engine(u, connect_args={'sslmode': 'disable'})\n",
        "asyncpg pool ssl": "import asyncpg\nasync def f():\n    return await asyncpg.create_pool(dsn, ssl=c)\n",
        "psycopg2 sslmode": "import psycopg2\nc = psycopg2.connect(dsn, sslmode='require')\n",
    }
    engine_allowed = {
        "engine options": "from sqlalchemy.ext.asyncio import create_async_engine\ne = create_async_engine(u, pool_size=5)\n",
        "another library's connect": "import sqlite3\nc = sqlite3.connect(path)\n",
    }
    redis_refused = {
        "host keyword": "from redis import asyncio as aioredis\nr = aioredis.Redis(host='x', port=6379)\n",
        "no arguments (localhost)": "import redis\nr = redis.Redis()\n",
        "positional host": "import redis\nr = redis.StrictRedis('x', 6379)\n",
        "a pool built by hand": "import redis\np = redis.ConnectionPool(host='x')\n",
    }
    redis_allowed = {
        "from_url": "from redis import asyncio as aioredis\nr = aioredis.from_url(url)\n",
        "the class's from_url": "import redis\nr = redis.Redis.from_url(url)\n",
        "a pool from a url": "import redis\nr = redis.Redis(connection_pool=redis.ConnectionPool.from_url(url))\n",
    }
    for label, src in engine_refused.items():
        assert len(scan(src, "x.py")[0]) == 1, label
    for label, src in engine_allowed.items():
        assert scan(src, "x.py")[0] == [], label
    for label, src in redis_refused.items():
        assert len(scan(src, "x.py")[1]) == 1, label
    for label, src in redis_allowed.items():
        assert scan(src, "x.py")[1] == [], label
    embedded = "S_SCRIPT = r'''\nfrom redis import asyncio as aioredis\nr = aioredis.Redis(host='x')\n'''\n"
    _, redis, scripts = scan(embedded, "f.py")
    assert scripts == 1 and len(redis) == 1, (redis, scripts)
    assert redis_direct_findings(ast.parse(embedded), "f.py") == [], "the module-level parse alone must not see inside the string"
