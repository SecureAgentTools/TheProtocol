# POLISH-001: Unified Error Schema Implementation
# agentvault_registry/src/agentvault_registry/errors.py

import json
import logging
import re
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """Unified error response schema for all API errors."""
    detail: str
    type: Optional[str] = None
    code: Optional[str] = None
    field: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standard error response wrapper."""
    error: ErrorDetail


# §pass56 PR-9: status → human title (RFC 7807 'title' field)
_STATUS_TITLE_MAP = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    422: "Validation Error",
    # §COCKPIT P4 — the read floor refuses with 425. Without a title here the body
    # said `"title": "Error"`, which is a dual-emit that carries no information: R3's
    # whole point is that the desk renders WHY ("you can confirm in 0.4 s"), never a
    # bare code, and a generic title makes every 425 look like a server fault.
    425: "Too Early",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}

# §FESUITE (V0600): the raised headers http_exception_handler puts on the wire (lowercased name -> the name it sends).
# Every raised header stays in the body's error.context.headers as well.
_WIRE_HEADERS = {
    "retry-after": "Retry-After",
    "www-authenticate": "WWW-Authenticate",
}


def create_error_response(
    detail: str,
    status_code: int,
    error_type: Optional[str] = None,
    error_code: Optional[str] = None,
    field: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> JSONResponse:
    """Create a standardized JSON error response.

    §pass56 PR-9 — DUAL-EMIT (sandbox test). Body carries BOTH the legacy nested
    shape (`{error: {detail, type, code, field, context}}`) AND RFC 7807 top-level
    keys (`type`, `title`, `status`, `detail`, `instance`). Content-Type is set
    to `application/problem+json` so RFC 7807 clients can dispatch on it; legacy
    JSON clients reading the body field-by-field still work because the nested
    `error` key is unchanged.

    Pivot condition (per Commander): if dual-emit causes frontend toast crashes or
    SDK regressions on sandbox, switch to hard-cut RFC 7807 (drop the nested
    `error` block, keep only the top-level RFC 7807 keys). Documented in
    PLAN_2026-05-20_PASS56_SANDBOX.md.
    """
    error_detail = ErrorDetail(
        detail=detail,
        type=error_type,
        code=error_code,
        field=field,
        context=context,
    )

    body: Dict[str, Any] = {
        # Legacy nested wrapper — preserved for transition
        "error": error_detail.model_dump(exclude_none=True),
        # RFC 7807 standard fields at top level
        "type":   f"https://docs.theprotocol.cloud/errors/{error_type or 'error'}",
        "title":  _STATUS_TITLE_MAP.get(status_code, "Error"),
        "status": status_code,
        "detail": detail,
    }
    if request is not None:
        try:
            body["instance"] = str(request.url.path)
        except Exception:
            pass

    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException with unified error schema.

    §pass16 (2026-05-16) — Health-probe noise filter. The agent_health_checker
    and external monitors probe agents at paths like `/a2a/health`,
    `/wallet/<did>/health`, `/agents/<hri>/health`, `/showcase/health`,
    `/ppaomobile/health`. When those agents aren't registered on this
    registry, the probe 404s — which is EXPECTED, not a real error. We
    demote these to DEBUG so logs don't drown in monitoring chatter.
    All other 4xx/5xx stay at WARNING so genuine misconfigurations are
    still visible.
    """
    path = request.url.path
    # §MCPTEST30 (V0525): a 5xx a route raised around a database error never carries the database's own words.
    _withheld = withheld_db_words(
        request, exc.status_code, exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, default=str),
        keep_prefix=isinstance(exc.detail, str))
    if _withheld is not None:
        return _withheld
    is_probe_404 = (
        exc.status_code == 404
        and request.method in ('GET', 'HEAD')
        and path.endswith('/health')
        and any(seg in path for seg in (
            '/a2a/', '/wallet/', '/agents/',
            '/showcase', '/ppaomobile',
        ))
    )
    if is_probe_404:
        logger.debug(
            f"HTTP exception on {request.method} {path}: "
            f"{exc.status_code} - {exc.detail}"
        )
    else:
        logger.warning(
            f"HTTP exception on {request.method} {path}: "
            f"{exc.status_code} - {exc.detail}"
        )
    
    # Map common status codes to error types
    error_type_map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        425: "too_early",
        429: "rate_limit_exceeded",
        500: "internal_server_error",
        503: "service_unavailable"
    }
    
    error_type = error_type_map.get(exc.status_code, "error")
    
    # Extract additional context from headers if present
    context = {}
    if hasattr(exc, 'headers') and exc.headers:
        context['headers'] = dict(exc.headers)
    
    # Handle cases where exc.detail is a dict (e.g., token reuse errors)
    detail = exc.detail
    if isinstance(detail, dict):
        detail_str = json.dumps(detail)
    else:
        detail_str = str(detail)
    
    resp = create_error_response(
        detail=detail_str,
        status_code=exc.status_code,
        error_type=error_type,
        context=context if context else None,
        request=request,
    )
    # §LEDGERGATE (V0597) + §FESUITE (V0600): the headers a route raised that promise something to the caller go on the
    # wire, not only into the body's context. Retry-After on a 503 or a 429 (the TEG's ledger refusal passed on, the
    # credential store, the liability floor); WWW-Authenticate on a 401, which must name its challenge (RFC 9110 15.5.2)
    # and which OAuth and docker clients read from the wire, never from a body. Until V0597 both reached only
    # error.context.headers; V0597 lifted Retry-After alone. The body keeps every header as before (the console reads
    # X-Verification-Required there, and only there).
    for k, v in (getattr(exc, "headers", None) or {}).items():
        wire_name = _WIRE_HEADERS.get(str(k).lower())
        if wire_name and v:
            resp.headers[wire_name] = str(v)
    return resp


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors with unified error schema."""
    logger.warning(
        f"Validation error on {request.method} {request.url.path}: {exc.errors()}"
    )
    
    # Format validation errors
    errors = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error['loc'])
        errors.append({
            "field": field_path,
            "message": error['msg'],
            "type": error['type']
        })
    
    # Use the first error as the main detail
    main_error = errors[0] if errors else {"message": "Validation error"}
    
    return create_error_response(
        detail=main_error.get("message", "Validation error"),
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_type="validation_error",
        error_code="VALIDATION_FAILED",
        field=main_error.get("field"),
        context={"errors": errors} if len(errors) > 1 else None,
        request=request,
    )


async def starlette_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle Starlette HTTPException with unified error schema."""
    return await http_exception_handler(request, HTTPException(status_code=exc.status_code, detail=exc.detail,
                                                               headers=getattr(exc, "headers", None)))


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Handle database integrity errors with unified error schema."""
    logger.error(f"Database integrity error on {request.method} {request.url.path}: {exc}")
    
    # Parse common integrity constraints
    detail = "Database constraint violation"
    error_code = "INTEGRITY_ERROR"
    
    if "unique constraint" in str(exc).lower():
        detail = "A record with this value already exists"
        error_code = "DUPLICATE_ENTRY"
    elif "foreign key constraint" in str(exc).lower():
        detail = "Referenced record does not exist"
        error_code = "FOREIGN_KEY_VIOLATION"
    elif "not null constraint" in str(exc).lower():
        detail = "Required field is missing"
        error_code = "NULL_CONSTRAINT_VIOLATION"
    
    return create_error_response(
        detail=detail,
        status_code=status.HTTP_409_CONFLICT,
        error_type="conflict",
        error_code=error_code,
        request=request,
    )


# §MCPTEST30 (V0525, 2026-10-01): the words a database driver puts in an exception's text. A route that catches every
# exception and raises HTTPException(500, detail=f"Failed to ...: {e}") hands the caller the driver's own sentence: the
# SQL statement, a parameter's value, a column or table name. Measured on sbx-alpha (V0521): getProposalDetail with an id
# past int32 answered 500 "Failed to retrieve proposal: (sqlalchemy.dialects.postgresql.asyncpg.Error) invalid input for
# query argument $1: 2147483648 (value out of int32 range)". The route's catch-all also pre-empted the SQLAlchemy handler
# below, which answers exactly that error 422. 93 route catch-alls turn any exception into a 500 and 30 of them echo it.
_DB_ERROR_WORDS = re.compile(
    r"\((?:sqlalchemy|psycopg2?|asyncpg)\.[\w.]+\)"          # "(sqlalchemy.dialects.postgresql.asyncpg.Error) ..."
    r"|\[SQL: "                                                # SQLAlchemy's statement echo
    r"|\b(?:asyncpg\.exceptions|psycopg2?\.errors|sqlalchemy\.exc)\.")

try:  # metrics are optional; their absence must never change an answer
    from prometheus_client import Counter as _Counter
    DB_WORDS_WITHHELD_TOTAL = _Counter(
        "registry_db_words_withheld_total",
        "5xx answers whose detail carried a database error's own words, withheld (by the status answered)",
        ["status"],
    )
except Exception:  # pragma: no cover
    DB_WORDS_WITHHELD_TOTAL = None


# §MCPTEST30 (V0529, 2026-10-01): the database could not take the call at all: its connection ceiling ("too many clients
# already", measured on sbx-alpha twice on 2026-10-01: 100 of 100 connections idle in the registry's pools), a refused or
# dropped connection, a pool checkout that timed out, a server starting or stopping. The registry's trouble, and it
# passes: 503 with Retry-After tells a client to try again; a 500 tells it the request is broken (agentvault2-21).
_DB_CAPACITY = re.compile(
    r"too many clients|remaining connection slots|connection refused|could not connect to server|"
    r"connection (?:was|is) closed|server closed the connection unexpectedly|terminating connection|QueuePool limit|"
    r"TooManyConnectionsError|CannotConnectNowError|the database system is (?:starting up|shutting down|in recovery mode)",
    re.I)
DB_RETRY_AFTER_S = "5"


def db_capacity_error(text: str) -> bool:
    """Is this database error the database not taking the call (capacity, connection), not the call being wrong?"""
    return bool(_DB_CAPACITY.search(text or ""))


def db_busy_response(request: Optional[Request], prefix: str = "") -> JSONResponse:
    """503 + Retry-After for a database that could not take the call; one answer for both handlers. `prefix` keeps a
    route's own sentence in front (the 5xx guard)."""
    said = (f"{prefix}: the registry's database is busy right now; try again shortly" if prefix
            else "The registry's database is busy right now; try again shortly.")
    resp = create_error_response(detail=said,
                                 status_code=status.HTTP_503_SERVICE_UNAVAILABLE, error_type="service_unavailable",
                                 error_code="DATABASE_BUSY", request=request)
    resp.headers["Retry-After"] = DB_RETRY_AFTER_S
    return resp


def db_error_answer(text: str) -> Optional[Dict[str, Any]]:
    """create_error_response's arguments for a database error the CALLER's value caused, or None.

    One classification for the SQLAlchemy handler and for a 5xx a route raised around a database error."""
    if (
        "out of int32 range" in text
        or "out of range" in text
        or "invalid input for query argument" in text
        or "invalid input syntax" in text
    ):
        return dict(detail="A path or query parameter value is out of range or invalid.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, error_type="validation_error",
                    error_code="PARAM_OUT_OF_RANGE")
    if ("invalid byte sequence for encoding" in text and "0x00" in text) or "unsupported Unicode escape sequence" in text:
        return dict(detail="A text value carries a NUL character, which this registry cannot store or search for.",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, error_type="validation_error",
                    error_code="NUL_IN_TEXT")
    return None


def withheld_db_words(request: Request, status_code: int, detail: str, keep_prefix: bool = True) -> Optional[JSONResponse]:
    """The answer for a 5xx whose detail carries a database error's own words, or None when it carries none.

    The words are logged here, never returned. A database error the caller's value caused gets the caller's answer (the
    SQLAlchemy handler's 422); any other keeps its status and the route's own sentence up to the driver's words
    (`keep_prefix=False` for a structured detail, whose text before the words is a fragment of JSON)."""
    if status_code < 500 or not isinstance(detail, str):
        return None
    m = _DB_ERROR_WORDS.search(detail)
    if not m:
        return None
    logger.error(f"Database error inside a {status_code} on {request.method} {request.url.path}: {detail}")
    ans = db_error_answer(detail)
    busy = ans is None and db_capacity_error(detail)   # §MCPTEST30 V0529: answered 503 below
    st = ans["status_code"] if ans else (status.HTTP_503_SERVICE_UNAVAILABLE if busy else status_code)
    if DB_WORDS_WITHHELD_TOTAL is not None:
        try:
            DB_WORDS_WITHHELD_TOTAL.labels(str(st)).inc()
        except Exception:
            pass
    if ans:
        return create_error_response(**ans, request=request)
    prefix = detail[:m.start()].rstrip(" :;,-(") if keep_prefix else ""
    if busy:   # §MCPTEST30 V0529: the database could not take the call: 503 + Retry-After
        return db_busy_response(request, prefix)
    said = f"{prefix}: a database error occurred" if prefix else "A database error occurred"
    return create_error_response(detail=said, status_code=status_code,
                                 error_type="service_unavailable" if status_code == 503 else "internal_server_error",
                                 error_code="DATABASE_ERROR", request=request)


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Handle general SQLAlchemy errors with unified error schema.

    §pass73.1 task H finding (2026-05-26): asyncpg raises DataError on int32
    overflow (any path-param `int` >= 2**31). Without explicit handling, this
    bubbles to a 500. Surface as 422 with the canonical "out of range" detail
    so MCP clients (and fuzzers) see it as a validation error, not a server
    crash. Other DBAPI input-data errors get the same treatment.
    """
    exc_str = str(exc)
    logger.error(f"Database error on {request.method} {request.url.path}: {exc}")

    # asyncpg DataError surfaces as "invalid input for query argument $N: <val>"
    # with messages like "value out of int32 range", "invalid input syntax",
    # "integer out of range", etc. All of these are CLIENT-side input bugs,
    # not server bugs. Return 422 instead of 500.
    # §MCPTEST30 (V0524): Postgres refuses a NUL in a text value ("invalid byte sequence for encoding "UTF8": 0x00") and in
    # jsonb ("unsupported Unicode escape sequence", \u0000 cannot be converted to text). A value the caller sent did
    # that, so it is the caller's 422, never a 500: V0523 refuses a NUL in a path or a query at the edge, and this is the
    # same answer for one that arrives in a body (a write's text field) or by any other road to the database.
    # §MCPTEST30 (V0525): both classifications live in db_error_answer, shared with the 5xx guard (withheld_db_words).
    ans = db_error_answer(exc_str)
    if ans:
        return create_error_response(**ans, request=request)
    if db_capacity_error(exc_str):   # §MCPTEST30 V0529: the database could not take the call: 503 + Retry-After
        return db_busy_response(request)

    return create_error_response(
        detail="A database error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="database_error",
        error_code="DATABASE_ERROR",
        request=request,
    )


# ── §DISCONNECTSPAM (2026-08-31) — a client hanging up is not a server fault ────────
# Starlette's BaseHTTPMiddleware raises RuntimeError("No response returned.") when the
# downstream app finishes WITHOUT sending a response. Its own source (middleware/base.py):
#
#     except anyio.EndOfStream:
#         if app_exc is not None:
#             raise app_exc                       # a REAL error surfaces as ITSELF
#         raise RuntimeError("No response returned.")
#
# 🔴 That `if app_exc is not None` is the whole safety argument: a genuine application
# exception is re-raised as itself on the line ABOVE, so this specific RuntimeError can
# only mean "the app stopped cleanly without sending" — the client-disconnect path, where
# `receive_or_disconnect` yields http.disconnect and `send_no_error` swallows the send.
# Suppressing its traceback therefore cannot hide a real fault.
#
# Why it matters: measured on registry-a 2026-08-31, **7,371 of these per hour**, each
# logging a full ExceptionGroup traceback through `logger.exception`. Formatting and
# writing thousands of multi-frame tracebacks an hour is real CPU and real I/O, on the
# one node the whole federation polls — a self-inflicted amplifier that got loudest
# exactly when the box was already struggling. It had been running ~1,000-2,000/hour all
# day, on all three mainframes.
#
# NOT silenced — DOWNGRADED and COUNTED. A disappearing error is worse than a noisy one,
# so the rate stays visible as a metric and a one-line INFO, and nothing about the
# response changes.
_DISCONNECT_MSG = "No response returned."
try:
    from prometheus_client import Counter as _PCounter
    _client_disconnect_total = _PCounter(
        "registry_client_disconnect_total",
        "Requests where the client hung up before the response was sent "
        "(Starlette BaseHTTPMiddleware 'No response returned.')",
        ["path"],
    )
except Exception:  # noqa: BLE001 — metrics are never allowed to break error handling
    _client_disconnect_total = None


def _is_client_disconnect(exc: Exception) -> bool:
    """EXACT match only. A substring test here would eventually swallow a real RuntimeError."""
    if isinstance(exc, RuntimeError) and str(exc) == _DISCONNECT_MSG:
        return True
    try:
        from starlette.requests import ClientDisconnect
        if isinstance(exc, ClientDisconnect):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle any unhandled exceptions with unified error schema."""
    if _is_client_disconnect(exc):
        # The caller is already gone; there is nobody to serve and nothing we did wrong.
        if _client_disconnect_total is not None:
            try:
                _client_disconnect_total.labels(path=request.url.path).inc()
            except Exception:  # noqa: BLE001
                pass
        logger.info(
            "Client disconnected before response on %s %s (no server error; "
            "see registry_client_disconnect_total)",
            request.method, request.url.path,
        )
    else:
        logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    
    return create_error_response(
        detail="An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="internal_server_error",
        error_code="INTERNAL_ERROR",
        request=request,
    )


class _DisconnectNoiseFilter(logging.Filter):
    """Drop uvicorn's "Exception in ASGI application" for a client disconnect.

    🔴 THERE ARE TWO LOGGERS, NOT ONE. Fixing `general_exception_handler` removed our
    traceback and MEASURED ONLY HALF THE COST: after the roll, registry-a showed
    ERROR=0 from us and still 18 ExceptionGroup tracebacks, emitted by `uvicorn.error`
    when the exception escapes the app (our handler builds a response, the client is
    already gone, the send fails, and it propagates). Counting only our own log line
    would have let me call this fixed while the expensive half continued.

    The predicate is the same exact-match one, walked through ExceptionGroup because
    that is the shape Starlette's BaseHTTPMiddleware produces. Anything else passes
    through untouched — this filter can only ever remove a client disconnect.
    """

    @staticmethod
    def _is_disconnect(exc: BaseException, depth: int = 0) -> bool:
        if depth > 4 or exc is None:
            return False
        if isinstance(exc, RuntimeError) and str(exc) == _DISCONNECT_MSG:
            return True
        subs = getattr(exc, "exceptions", None)  # BaseExceptionGroup
        if subs:
            return all(_DisconnectNoiseFilter._is_disconnect(e, depth + 1) for e in subs)
        return False

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.exc_info:
            return True
        exc = record.exc_info[1]
        try:
            if self._is_disconnect(exc):
                return False          # drop the record entirely
        except Exception:  # noqa: BLE001 — a filter must never break logging
            return True
        return True


def _install_disconnect_filter() -> None:
    """Attach to uvicorn's error logger. Idempotent across worker respawns."""
    for name in ("uvicorn.error", "uvicorn"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _DisconnectNoiseFilter) for f in lg.filters):
            lg.addFilter(_DisconnectNoiseFilter())


def register_error_handlers(app: FastAPI) -> None:
    """Register all error handlers with the FastAPI application."""
    _install_disconnect_filter()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    logger.info("Unified error handlers registered")


# Custom exception classes for specific error scenarios
class RegistryException(HTTPException):
    """Base exception for registry-specific errors."""
    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: Optional[str] = None
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class AuthenticationError(RegistryException):
    """Raised when authentication fails."""
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_FAILED"
        )


class AuthorizationError(RegistryException):
    """Raised when authorization fails."""
    def __init__(self, detail: str = "Access denied"):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="ACCESS_DENIED"
        )


class ResourceNotFoundError(RegistryException):
    """Raised when a requested resource is not found."""
    def __init__(self, resource_type: str, identifier: str):
        super().__init__(
            detail=f"{resource_type} with identifier '{identifier}' not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="RESOURCE_NOT_FOUND"
        )


class ValidationError(RegistryException):
    """Raised when validation fails."""
    def __init__(self, detail: str, field: Optional[str] = None):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR"
        )
        self.field = field


class ConflictError(RegistryException):
    """Raised when there's a conflict with existing data."""
    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_409_CONFLICT,
            error_code="CONFLICT"
        )


class ServiceUnavailableError(RegistryException):
    """Raised when a service is temporarily unavailable."""
    def __init__(self, detail: str = "Service temporarily unavailable"):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="SERVICE_UNAVAILABLE"
        )
