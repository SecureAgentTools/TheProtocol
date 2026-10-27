"""§MTLSHOPS G3 prep (2026-09-15) — a Redis URL is never written to a log with its credentials.

G3 gives each Redis client its own ACL user, so REDIS_URL carries a password (redis://<user>:<password>@<host>:6379/<db>).
Every client passes the URL unchanged to redis-py, which is right; the registry's leader pool also logged it whole on
connect. This census walks every logging call in the registry package and refuses one that formats a variable holding a
Redis URL without cutting it first (the masked form is a call, such as redis_url.rsplit('@', 1)[-1]).
RED control: against the tree before this change it names background_tasks/leader.py.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib

PKG = pathlib.Path(importlib.util.find_spec("agentvault_registry").submodule_search_locations[0])
REDIS_URL_NAMES = {"redis_url", "_redis_url", "REDIS_URL"}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
LOGGERS = {"logger", "log", "_logger", "LOGGER"}


def _raw_url_uses(node: ast.AST):
    """Bare Names or Attributes named like a Redis URL, not wrapped in a call."""
    for child in ast.walk(node):
        values = []
        if isinstance(child, ast.FormattedValue):
            values.append(child.value)
        for v in values:
            if isinstance(v, ast.Name) and v.id in REDIS_URL_NAMES:
                yield v
            if isinstance(v, ast.Attribute) and v.attr in REDIS_URL_NAMES:
                yield v


def _violations(root: pathlib.Path, skip=("static/",)):
    found = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(skip) or "node_modules" in rel:
            continue
        for call in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in LOG_METHODS
                    and isinstance(call.func.value, ast.Name) and call.func.value.id in LOGGERS):
                continue
            for arg in call.args:
                if isinstance(arg, (ast.Name, ast.Attribute)) and getattr(arg, "id", getattr(arg, "attr", None)) in REDIS_URL_NAMES:
                    found.append(f"{rel}:{call.lineno}")
                elif any(True for _ in _raw_url_uses(arg)):
                    found.append(f"{rel}:{call.lineno}")
    return sorted(set(found))


def test_no_logging_call_prints_a_raw_redis_url():
    assert _violations(PKG) == []


def test_the_census_sees_a_raw_url_when_one_is_there(tmp_path):
    (tmp_path / "bad.py").write_text(
        "import logging\nlogger = logging.getLogger(__name__)\nredis_url = 'redis://u:p@h:6379/0'\n"
        "logger.info(f'connected ({redis_url})')\nlogger.info('connected %s', redis_url)\n"
        "logger.info(f\"connected ({redis_url.rsplit('@', 1)[-1]})\")\n")
    assert _violations(tmp_path) == ["bad.py:4", "bad.py:5"]
