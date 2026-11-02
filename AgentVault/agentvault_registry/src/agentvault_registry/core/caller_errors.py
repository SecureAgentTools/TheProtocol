"""What a caller is told about an error a route did not expect.

V0653 (am) item 2 (the hardening list in the sessions' room): a route that caught any exception and answered with its
text (detail=f"Failed to ...: {e}") sent its internals to the caller: an internal host and port from a connection error,
a database message, a file path. internal_detail keeps the route's own words, adds an error id, and logs the exception
under that id, so an operator finds it and a caller learns nothing more. A refusal the route raised itself and caught
on its way out (an HTTPException) keeps its words, as before. tests/test_route_errors_v0653.py refuses a 5xx answer
built from a caught exception any other way.

V0653's recut (the pair proof of 2026-11-02 09:02Z, session-tester's read in the sessions' room seq 961; session-lead seq
965): a DATABASE error is classified from the exception itself, before any text is withheld. Until V0653 the route's
detail carried the driver's words and the 5xx guard (errors.withheld_db_words) read them: a database error the caller's
value caused answered 422 (GET /governance/proposals/2147483648: "out of range"), a database that could not take the
call 503 with Retry-After. Item 2 took the words away first, so both answered 500. Now internal_detail answers those two
itself (it raises DatabaseAnswer, an HTTPException, in place of the route's own); any other error keeps the route's
status with only its words and the error id.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import HTTPException

_log = logging.getLogger(__name__)

# the packages a database error comes from (SQLAlchemy wraps the driver's own; a raw driver error is one too)
_DB_PACKAGES = ("sqlalchemy", "asyncpg", "psycopg", "psycopg2")


class DatabaseAnswer(HTTPException):
    """The answer to a database error decided from the exception: the caller's value (422) or a busy database (503,
    Retry-After). An HTTPException, so every path that passes a route's own refusals on keeps it whole; the HTTP handler
    puts its error code in the body (PARAM_OUT_OF_RANGE, NUL_IN_TEXT, DATABASE_BUSY), as the SQLAlchemy handler does."""

    def __init__(self, status_code: int, detail: str, error_code: str, headers: Optional[dict] = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code


def database_error(exc: BaseException) -> Optional[BaseException]:
    """The database error `exc` is, or was raised from (`raise ... from db_error`), else None. By the exception's type,
    never by its words: a connection refused by the TEG is not a busy database."""
    seen = set()
    e: Optional[BaseException] = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if (type(e).__module__ or "").split(".")[0] in _DB_PACKAGES:
            return e
        e = e.__cause__
    return None


def database_answer(exc: BaseException, label: str) -> Optional[DatabaseAnswer]:
    """422 for a database error the caller's value caused, 503 + Retry-After for a database that could not take the
    call; None for any other error (database or not). The classification is errors.py's, shared with the SQLAlchemy
    handler, read from the exception's text here and never returned."""
    db_exc = database_error(exc)
    if db_exc is None:
        return None
    from ..errors import DB_RETRY_AFTER_S, count_db_words_withheld, db_capacity_error, db_error_answer
    text = str(db_exc)
    ans = db_error_answer(text)
    if ans is not None:
        count_db_words_withheld(ans["status_code"])
        return DatabaseAnswer(ans["status_code"], ans["detail"], ans["error_code"])
    if db_capacity_error(text):
        count_db_words_withheld(503)
        return DatabaseAnswer(503, f"{label}: the registry's database is busy right now; try again shortly",
                              "DATABASE_BUSY", headers={"Retry-After": DB_RETRY_AFTER_S})
    return None


def internal_detail(exc: BaseException, label: str, log: Optional[logging.Logger] = None) -> str:
    """`label (error id <id>)`; the exception goes to the log under the same id.

    For a database error the caller caused or a busy database it does not return: it raises that error's own answer
    (DatabaseAnswer, 422 or 503), which takes the place of the route's HTTPException (every call site raises what this
    returns). A DatabaseAnswer caught again by an outer handler is raised on whole."""
    from starlette.exceptions import HTTPException as _StarletteHTTPException

    if isinstance(exc, DatabaseAnswer):                    # decided already, by an inner call: keep its status
        raise exc
    if isinstance(exc, _StarletteHTTPException):           # a refusal of the route's own, caught on its way out
        return f"{label}: {exc.detail}"
    eid = uuid.uuid4().hex[:12]
    (log or _log).error("%s (error id %s): %s: %s", label, eid, type(exc).__name__, exc, exc_info=exc)
    answer = database_answer(exc, label)
    if answer is not None:
        raise answer
    return f"{label} (error id {eid})"
