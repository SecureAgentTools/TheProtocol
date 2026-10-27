"""§RELEASEHARDEN D2 (2026-09-14) — mask credentials that ride in a query string before an access line is written.

uvicorn logs every request line with its full query string (`uvicorn.access` for HTTP; the
`"WebSocket /path?..." [accepted]` line goes through `uvicorn.error`), and gunicorn's own access log does the
same through its `%(r)s` atom. The container log is what Dozzle reads, and the night of 2026-09-13/14 one
console websocket's JWT was read out of exactly such a line (`FINDINGS_2026-09-14_FRAMESHOWCASE.md`).

The websocket JWT no longer rides the query string (routers/websocket.py: the subprotocol list) and the SSE
streams refuse `access_token=` (routers/mcp_tester.py), but a stale bundle, an old script, or the next route
that takes a secret as a query parameter would put one back. This filter is the floor under all of them:
any `<name>=<value>` whose name is in SECRET_QUERY_KEYS is written as `<name>=***`. It rewrites the
record's ARGS (uvicorn: a tuple whose path element carries the query; gunicorn: a dict of atoms, mutated in
place because gunicorn's SafeAtoms answers "-" for a missing key), never the request, so nothing else changes.

Installed twice on purpose: at app import (`main.py`, so a bare `uvicorn` launch is covered) and in the
gunicorn worker's `post_fork` hook (`gunicorn_conf.py`, so the worker that replaces the uvicorn loggers'
HANDLERS still carries the filter, which lives on the LOGGER). `install_access_log_mask` is idempotent.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

SECRET_QUERY_KEYS = (
    "token", "access_token", "refresh_token", "ticket", "api_key", "apikey",
    "key", "secret", "client_secret", "password", "code",
)
# the name must follow a `?` or `&` and be followed by `=` at once: `token_type=bearer` is not a secret
_PATTERN = re.compile(r"(?i)([?&](?:%s)=)([^&\s\"']+)" % "|".join(re.escape(k) for k in SECRET_QUERY_KEYS))

LOGGERS = ("uvicorn.access", "uvicorn.error", "gunicorn.access", "gunicorn.error")


def mask_query_secrets(text):
    """`?a=1&token=eyJ...` -> `?a=1&token=***`; anything that is not a str is returned as is."""
    if not isinstance(text, str) or "=" not in text:
        return text
    return _PATTERN.sub(r"\1***", text)


class QueryStringSecretsFilter(logging.Filter):
    """A logging filter that never drops a record; it only masks secrets inside the record's args."""

    TAG = "query-string-secrets"

    def __init__(self) -> None:
        super().__init__()
        self.tag = self.TAG

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — the logging API's name
        try:
            args = record.args
            if isinstance(args, tuple):
                record.args = tuple(mask_query_secrets(a) for a in args)
            elif isinstance(args, dict):
                for k, v in list(args.items()):
                    if isinstance(v, str) and "=" in v:
                        args[k] = mask_query_secrets(v)
            if isinstance(record.msg, str) and "=" in record.msg:
                record.msg = mask_query_secrets(record.msg)
        except Exception:  # noqa: BLE001 — a masking failure must never lose the log line
            pass
        return True


def is_installed(logger: logging.Logger) -> bool:
    return any(getattr(f, "tag", None) == QueryStringSecretsFilter.TAG for f in logger.filters)


def install_access_log_mask(logger_names: Iterable[str] = LOGGERS) -> int:
    """Attach the filter to each named logger once. Returns how many loggers gained it on this call."""
    added = 0
    for name in logger_names:
        lg = logging.getLogger(name)
        if not is_installed(lg):
            lg.addFilter(QueryStringSecretsFilter())
            added += 1
    return added
