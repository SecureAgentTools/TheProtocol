"""§MTLSHOPS G3 prep (2026-09-15) — the event store never writes its Redis URL to a log with credentials.

G3 gives each Redis client its own ACL user, so REDIS_URL carries a password. The store logged the URL whole on connect in two
places (src/leader.py, src/services/websocket_publisher.py). This census walks every logging call under src/ and refuses one
that formats a variable holding a Redis URL without cutting it first (the masked form is a call, such as
redis_url.rsplit('@', 1)[-1]); the second half proves the census finds a raw use when one exists.
RED control: against the tree before this change it names both files.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
REDIS_URL_NAMES = {"redis_url", "_redis_url", "REDIS_URL"}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
LOGGERS = {"logger", "log", "_logger", "LOGGER"}


def _violations(root: pathlib.Path):
    found = []
    for path in root.rglob("*.py"):
        for call in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in LOG_METHODS
                    and isinstance(call.func.value, ast.Name) and call.func.value.id in LOGGERS):
                continue
            for arg in call.args:
                bare = isinstance(arg, (ast.Name, ast.Attribute)) and getattr(arg, "id", getattr(arg, "attr", None)) in REDIS_URL_NAMES
                inner = any(isinstance(n, ast.FormattedValue) and isinstance(n.value, (ast.Name, ast.Attribute))
                            and getattr(n.value, "id", getattr(n.value, "attr", None)) in REDIS_URL_NAMES for n in ast.walk(arg))
                if bare or inner:
                    found.append(f"{path.relative_to(root).as_posix()}:{call.lineno}")
    return sorted(set(found))


def test_no_logging_call_prints_a_raw_redis_url(tmp_path):
    assert _violations(SRC) == []
    (tmp_path / "bad.py").write_text(
        "import logging\nlogger = logging.getLogger(__name__)\nclass P:\n    _redis_url = 'redis://u:p@h:6379/1'\n"
        "    def go(self):\n        logger.info('connected: %s', self._redis_url)\n"
        "        logger.info('connected: %s', self._redis_url.rsplit('@', 1)[-1])\n")
    assert _violations(tmp_path) == ["bad.py:6"], "the census must see a raw use when one exists"
