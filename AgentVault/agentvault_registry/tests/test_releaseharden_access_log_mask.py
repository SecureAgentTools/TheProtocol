"""§RELEASEHARDEN D2 (2026-09-14) — a query-string credential never reaches an access line.

Pins the filter against the THREE record shapes that carry a request line in this process: uvicorn's HTTP
access record (a tuple whose path element carries the query), uvicorn's websocket "[accepted]" line on the
error logger, and gunicorn's access record (a dict of atoms, mutated in place). Each has its control: the
same record without the filter prints the token.
"""
from __future__ import annotations

import logging

from agentvault_registry.core.access_log_mask import (
    LOGGERS,
    QueryStringSecretsFilter,
    install_access_log_mask,
    is_installed,
    mask_query_secrets,
)

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI3In0.abc-def_ghi"


def _record(logger_name: str, msg: str, args) -> logging.LogRecord:
    return logging.LogRecord(logger_name, logging.INFO, __file__, 1, msg, args, None)


def test_uvicorn_http_access_line_is_masked_and_the_rest_of_the_path_kept():
    rec = _record(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.7:51000", "GET", f"/api/v1/admin/mcp-tester/event-stream?frames=a,b&access_token={JWT}", "1.1", 200),
    )
    assert QueryStringSecretsFilter().filter(rec) is True
    line = rec.getMessage()
    assert JWT not in line
    assert "access_token=***" in line
    assert "frames=a,b" in line and "HTTP/1.1\" 200" in line


def test_uvicorn_websocket_accepted_line_is_masked():
    rec = _record("uvicorn.error", '%s - "WebSocket %s" [accepted]', ("10.0.0.7:51001", f"/api/v1/ws?token={JWT}"))
    QueryStringSecretsFilter().filter(rec)
    line = rec.getMessage()
    assert JWT not in line and 'WebSocket /api/v1/ws?token=***" [accepted]' in line


def test_gunicorn_atoms_are_masked_in_place_and_the_dict_object_is_kept():
    class SafeAtoms(dict):
        """gunicorn's SafeAtoms answers '-' for a missing key; a rebuilt plain dict would lose that."""

        def __getitem__(self, k):
            return dict.get(self, k, "-")

    atoms = SafeAtoms({"r": f"GET /api/v1/ws?token={JWT} HTTP/1.1", "U": "/api/v1/ws", "q": f"token={JWT}", "s": "101"})
    rec = _record("gunicorn.access", '%(h)s "%(r)s" %(s)s', atoms)
    QueryStringSecretsFilter().filter(rec)
    assert rec.args is atoms
    assert JWT not in atoms["r"] and "token=***" in atoms["r"]
    assert atoms["q"] == f"token={JWT}", "a bare `token=...` atom without a `?`/`&` before it is not a query string"
    assert rec.getMessage() == '- "GET /api/v1/ws?token=*** HTTP/1.1" 101'


def test_control_the_same_record_without_the_filter_prints_the_token():
    rec = _record("uvicorn.access", '%s - "%s %s HTTP/%s" %d', ("c", "GET", f"/api/v1/ws?token={JWT}", "1.1", 101))
    assert JWT in rec.getMessage()


def test_names_that_merely_start_with_a_secret_name_are_untouched():
    path = "/x?token_type=bearer&monkey=1&api_key_id=9&code=abc"
    assert mask_query_secrets(path) == "/x?token_type=bearer&monkey=1&api_key_id=9&code=***"


def test_every_secret_name_is_masked_case_insensitively():
    for name in ("token", "ACCESS_TOKEN", "refresh_token", "ticket", "api_key", "apikey", "key", "secret", "client_secret", "password", "code"):
        assert mask_query_secrets(f"/p?a=1&{name}=v4lue&b=2") == f"/p?a=1&{name}=***&b=2", name


def test_non_string_args_and_messages_pass_through():
    rec = _record("uvicorn.error", "worker %d up in %.2fs", (7, 0.5))
    assert QueryStringSecretsFilter().filter(rec) is True
    assert rec.getMessage() == "worker 7 up in 0.50s"


def test_install_is_idempotent_and_covers_the_four_loggers():
    names = tuple(f"test.{n}" for n in LOGGERS)
    for n in names:
        logging.getLogger(n).filters.clear()
    assert install_access_log_mask(names) == 4
    assert install_access_log_mask(names) == 0
    for n in names:
        lg = logging.getLogger(n)
        assert is_installed(lg) and len(lg.filters) == 1


def test_the_app_import_installs_the_mask_on_uvicorn_loggers():
    # main.py installs at import; the four production loggers must carry exactly one copy
    import importlib

    importlib.import_module("agentvault_registry.main")  # the import is the act

    for n in LOGGERS:
        lg = logging.getLogger(n)
        assert is_installed(lg), n
        assert sum(1 for f in lg.filters if getattr(f, "tag", None) == QueryStringSecretsFilter.TAG) == 1, n
