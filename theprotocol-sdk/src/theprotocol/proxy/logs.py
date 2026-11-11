"""JSON log lines with no secret in them.

Each line is one JSON object (ts, level, logger, msg, and the fields the core attached). Before a line is written, every
value the proxy knows to be secret (each credential its spec references, resolved, and the agent's current token) is
replaced by "[redacted]", wherever it appears: in the message, in a field, inside an exception's text.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, TextIO

REDACTED = "[redacted]"
_STD = set(vars(logging.LogRecord("x", 0, "", 0, "", None, None))) | {"message", "asctime"}


def redact(text: str, secrets: Iterable[str]) -> str:
    for s in sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True):
        text = text.replace(s, REDACTED)
        escaped = json.dumps(s)[1:-1]
        if escaped != s:
            text = text.replace(escaped, REDACTED)
    return text


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: Callable[[], Iterable[str]] = lambda: ()):
        super().__init__()
        self._secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        doc = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "proxy", None)
        if isinstance(fields, dict):
            for k, v in fields.items():
                doc.setdefault(k, v)
        for k, v in vars(record).items():
            if k not in _STD and k != "proxy" and not k.startswith("_"):
                doc.setdefault(k, v)
        if record.exc_info:
            doc["error"] = self.formatException(record.exc_info)
        return redact(json.dumps(doc, default=str, ensure_ascii=False), self._secrets())


class _Stderr(logging.StreamHandler):
    """A handler on whatever sys.stderr is when a line is written (not the one it was when the proxy started)."""

    def __init__(self) -> None:
        super().__init__()

    @property  # type: ignore[override]
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, _value: TextIO) -> None:
        pass


def setup(*, secrets: Callable[[], Iterable[str]], level: str = "info", stream: Optional[TextIO] = None,
          logger: str = "theprotocol.proxy") -> logging.Handler:
    """Send the proxy's logs (and its plugins') to `stream` (stderr) as redacted JSON lines."""
    handler: logging.Handler = logging.StreamHandler(stream) if stream is not None else _Stderr()
    handler.setFormatter(JsonFormatter(secrets))
    lg = logging.getLogger(logger)
    lg.handlers = [h for h in lg.handlers if not getattr(h, "_tp_proxy", False)]
    handler._tp_proxy = True  # type: ignore[attr-defined]
    lg.addHandler(handler)
    lg.setLevel(getattr(logging, level.upper(), logging.INFO))
    lg.propagate = False
    for noisy in ("httpx", "httpcore"):
        # their INFO lines print every URL; a token is never in one, but a query string might carry a reference's value
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return handler
