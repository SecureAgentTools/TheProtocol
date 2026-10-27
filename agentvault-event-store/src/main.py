from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from .routers import events, projections, websocket
from .routers import forensics  # Ledger Forensics read API (search/trace/scan)
from .routers import federation_governance
from .routers import admin_cross_frame  # WS3.5 SF-4: dynamic cross-frame peer registry
from .routers import admin_federation_operators  # WS3.5 SF-5: federation_operators CRUD
from .database.connection import engine, Base
from .models.federation_governance import FederationProposal, FederationVote  # noqa: F401 — ensure tables created
from prometheus_fastapi_instrumentator import Instrumentator
import asyncio
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="TheProtocol Event Store",
    description=(
        "Event sourcing for the TheProtocol ecosystem.\n\n"
        "**WebSocket contract (PR-11 partial — closes E-P1-2):**\n"
        "Subscribers connect to `/ws/events` for real-time event fanout. Auth model:\n"
        "- shared-secret: `?token=<INTERNAL_API_KEY>` (legacy)\n"
        "- SPIFFE JWT-SVID: `?token=<jwt>` (Phase 12.1+, detected by 3-segment shape).\n"
        "On connect, server pushes `{type: connected, ts: …}`. On each persisted\n"
        "event, server pushes the full Event payload. Slow consumers may have\n"
        "messages dropped (per-client 10K-message bounded queue) — re-subscribe\n"
        "via `GET /api/v1/events/foreign?since=<ts>` to backfill.\n\n"
        "**Idempotency contract:** every `POST /api/v1/events/` is dedupe-safe via\n"
        "the `idempotency_key` body field (UNIQUE constraint). Same key + same\n"
        "payload → 201 with the existing event. Different payload → 409.\n\n"
        "**Auditor:** the canonical supply-invariant view is `GET /api/v1/projections/\n"
        "supply-audit` (returns a typed `SupplyAuditResponse`). Polled by the\n"
        "auditor agent at `auditor.theprotocol.cloud` (~10s cadence)."
    ),
    version="1.0.0"
)

# --- §pass52 PR-1: cluster-wide securitySchemes library + servers block (EventStore) ---
from fastapi.openapi.utils import get_openapi as _get_openapi
_OPENAPI_SECURITY_SCHEMES = {
    "mTLSPeer":          {"type": "mutualTLS",
                          "description": "SPIFFE-issued X.509 SVID; trust-domain pinned. "
                                         "Required for cluster-internal event writes."},
    "FederationLicense": {"type": "apiKey", "in": "header", "name": "X-Federation-License",
                          "description": "Operator license, revocable; for cross-frame operator emits."},
    "InternalAPIKey":    {"type": "apiKey", "in": "header", "name": "X-Internal-Key",
                          "description": "Shared secret for in-cluster service-to-service calls."},
    "DeveloperJWT":      {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                          "description": "Developer JWT (for admin federation routes)"},
    "AdminDeveloperJWT": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                          "description": "Admin developer JWT with is_admin=True"},
}
# Relative first, so it resolves against whichever store serves these docs (as the registry's list does); no frame's
# internal container names.
_OPENAPI_SERVERS = [
    {"url": "/",                     "description": "This event store (the one serving these docs)"},
    {"url": "http://localhost:8200", "description": "Local dev"},
]

def _rewrite_security_to_named_schemes(schema_in: dict) -> None:
    """§pass56 PR-1F + §pass58.5 — rewrite auto-generated FastAPI scheme names to
    canonical named schemes.

    EventStore mostly takes Internal/Admin auth:
    - /admin/* → AdminDeveloperJWT
    - /system/lockdown* → InternalAPIKey (already named, preserved by 'else' branch)
    - /events/* + /federation-governance/* → verify_event_auth accepts X-Internal-Key
      OR X-Federation-License OR mTLS; FastAPI auto-names it APIKeyHeader.
      Map APIKeyHeader → InternalAPIKey (the declared scheme matches the X-Internal-Key
      header path which is the canonical auth for cluster-internal event writes).
    - Everything else → DeveloperJWT default.
    """
    # §pass58.5 — adds 'APIKeyHeader' to catch FastAPI's auto-generated APIKey scheme.
    # Without this, 33 endpoint-level security refs are dangling (Swagger UI can't
    # resolve the auth requirement to a declared scheme).
    legacy_names = {"OAuth2PasswordBearer", "HTTPBearer", "APIKeyHeader"}
    paths = schema_in.get("paths") or {}
    for p, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        # §pass58.5 — EventStore is entirely cluster-internal.
        # admin_cross_frame.py + admin_federation_operators.py use _verify_internal_key
        # (X-Internal-Key header), NOT JWT. events/ + federation-governance/ same.
        # /system/lockdown* already uses InternalAPIKey (named scheme, preserved).
        if (p.startswith("/api/v1/admin")
                or p.startswith("/api/v1/events")
                or p.startswith("/api/v1/federation-governance")
                or p.startswith("/api/v1/system")):
            target = "InternalAPIKey"
        else:
            target = "DeveloperJWT"
        for verb, op in methods.items():
            if verb not in ("get", "post", "put", "patch", "delete"):
                continue
            if not isinstance(op, dict):
                continue
            sec = op.get("security")
            if not isinstance(sec, list):
                continue
            new_sec = []
            changed = False
            for entry in sec:
                if not isinstance(entry, dict):
                    new_sec.append(entry)
                    continue
                new_entry = {}
                for sname, scopes in entry.items():
                    if sname in legacy_names:
                        new_entry[target] = scopes or []
                        changed = True
                    else:
                        new_entry[sname] = scopes
                new_sec.append(new_entry)
            if changed:
                op["security"] = new_sec


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = _get_openapi(
        title=app.title, version=app.version, description=app.description,
        routes=app.routes, servers=_OPENAPI_SERVERS,
    )
    schema.setdefault("components", {})["securitySchemes"] = _OPENAPI_SECURITY_SCHEMES
    # §pass56 PR-1F: make library actually used
    _rewrite_security_to_named_schemes(schema)
    schema.setdefault("info", {})
    schema["info"]["contact"] = {
        "name": "TheProtocol Engineering",
        "url": "https://theprotocol.cloud",
        "email": "engineering@theprotocol.cloud",
    }
    schema["info"]["license"] = {
        "name": "AGPL-3.0-or-later",
        "url": "https://www.gnu.org/licenses/agpl-3.0.html",
    }
    app.openapi_schema = schema
    return schema

app.openapi = _custom_openapi


# §pass56 PR-9 — RFC 7807 application/problem+json error envelope (dual-emit).
# EventStore previously relied on FastAPI defaults (`{"detail": "..."}`); now
# emits both the legacy `detail` field AND RFC 7807 standard fields (`type`,
# `title`, `status`, `instance`). Content-Type: application/problem+json.
# Pivot to hard-cut if dual-emit causes regressions (see PLAN_2026-05-20_PASS56_SANDBOX.md).
_ES_STATUS_TITLE_MAP = {
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    409: "Conflict", 410: "Gone", 422: "Validation Error", 429: "Too Many Requests",
    500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable",
    504: "Gateway Timeout",
}
_ES_TYPE_BY_STATUS = {
    400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    409: "conflict", 422: "validation_error", 429: "rate_limit_exceeded",
    500: "internal_server_error", 503: "service_unavailable",
}


async def _problem_json_handler(request: Request, exc: HTTPException) -> JSONResponse:
    error_type = _ES_TYPE_BY_STATUS.get(exc.status_code, "error")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    body = {
        "detail": detail,
        "type":   f"https://docs.theprotocol.cloud/errors/{error_type}",
        "title":  _ES_STATUS_TITLE_MAP.get(exc.status_code, "Error"),
        "status": exc.status_code,
    }
    try:
        body["instance"] = str(request.url.path)
    except Exception:
        pass
    return JSONResponse(status_code=exc.status_code, content=body, media_type="application/problem+json")


app.add_exception_handler(HTTPException, _problem_json_handler)
app.add_exception_handler(StarletteHTTPException, _problem_json_handler)


# CORS middleware — restrict to known origins
_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:8000,http://localhost:8001")
CORS_ORIGINS = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Internal-Key", "X-Federation-License", "Authorization"],
)

# Include routers
app.include_router(events.router)
app.include_router(projections.router)
app.include_router(websocket.router)
app.include_router(forensics.router)  # Ledger Forensics read API (search/trace/scan)
from .routers import system as system_router  # Phase 2b: lockdown circuit breaker
app.include_router(system_router.router)
app.include_router(federation_governance.router)  # Federation governance (cross-registry proposals)
app.include_router(admin_cross_frame.router)  # WS3.5 SF-4: dynamic cross-frame peer registry admin
app.include_router(admin_federation_operators.router)  # WS3.5 SF-5: federation_operators CRUD

@app.on_event("startup")
async def startup_event():
    """Create tables on startup, then apply any pending schema migrations."""
    # Schema migrations: only one worker runs DDL to avoid AccessExclusiveLock
    # contention (8 workers × ALTER TABLE on a busy table = indefinite blocking).
    # All DDL is idempotent (IF NOT EXISTS), so skipping is safe.
    from sqlalchemy import text
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT pg_try_advisory_xact_lock(42001)"))
        got_lock = result.scalar()
        if not got_lock:
            logging.info("Schema migrations: another worker holds the lock, skipping (idempotent)")
        else:
            await conn.run_sync(Base.metadata.create_all)

            await conn.execute(text(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255) NULL"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_events_idempotency_key "
                "ON events (idempotency_key) WHERE idempotency_key IS NOT NULL"
            ))

            # Btree expression index for single-transaction lookups
            # (GET /api/v1/events/by-transaction/{txid} → registry
            # getTegTransactionDetail). Equality on (data->>'transaction_id');
            # partial (WHERE NOT NULL) so only the ~190K balance-moving events
            # are indexed, not the full table. Idempotent like the others.
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_events_data_txid "
                "ON events ((data->>'transaction_id')) "
                "WHERE data->>'transaction_id' IS NOT NULL"
            ))

            await conn.execute(text(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS source_operator_id VARCHAR(36) NULL"
            ))

            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS federation_operators (
                    id VARCHAR(36) PRIMARY KEY,
                    operator_name VARCHAR(200) NOT NULL,
                    license_key_hash VARCHAR(64) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    max_events_per_minute INTEGER DEFAULT 1000,
                    event_count INTEGER DEFAULT 0,
                    last_event_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_federation_operators_license_key_hash "
                "ON federation_operators (license_key_hash)"
            ))

            await conn.execute(text(
                "ALTER TABLE federation_operators ADD COLUMN IF NOT EXISTS "
                "bayesian_discount DOUBLE PRECISION NOT NULL DEFAULT 1.0"
            ))
            await conn.execute(text(
                "ALTER TABLE federation_operators ADD COLUMN IF NOT EXISTS "
                "spiffe_id VARCHAR(255) NULL"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_federation_operators_spiffe_id "
                "ON federation_operators (spiffe_id) WHERE spiffe_id IS NOT NULL"
            ))
            # §MEMBERSHIP D2 (2026-10-02): federal ballots, one per registry, on federation proposals (metadata-only
            # ALTERs on PG >= 11: a constant default needs no table rewrite)
            for ddl in (
                "ALTER TABLE federation_proposals ADD COLUMN IF NOT EXISTS ballot_mode BOOLEAN NOT NULL DEFAULT false",
                "ALTER TABLE federation_proposals ADD COLUMN IF NOT EXISTS ballot_summary JSONB NULL",
                "ALTER TABLE federation_votes ADD COLUMN IF NOT EXISTS choice VARCHAR(8) NULL",
                "ALTER TABLE federation_votes ADD COLUMN IF NOT EXISTS ballot_jws TEXT NULL",
                "ALTER TABLE federation_votes ADD COLUMN IF NOT EXISTS ballot_basis JSONB NULL",
                "ALTER TABLE federation_votes ADD COLUMN IF NOT EXISTS eligibility JSONB NULL",
            ):
                await conn.execute(text(ddl))
            # D6-298 (2026-10-16): the lockdown every worker reads (one row; services/lockdown_state.py)
            from .services.lockdown_state import TABLE_DDL as _LOCKDOWN_TABLE_DDL
            await conn.execute(text(_LOCKDOWN_TABLE_DDL))
            await conn.execute(text(
                "DROP INDEX IF EXISTS idx_aggregate_timestamp"
            ))
            logging.info("Schema migrations complete (this worker held the advisory lock)")

    # Phase 1 Scaling: Materialized balance views (trigger-maintained).
    # SHA256-gate the re-apply so we only run the DDL when the SQL file
    # actually changed. CREATE OR REPLACE FUNCTION needs AccessExclusiveLock;
    # under live INSERT traffic it deadlocks once per restart (benign — old
    # body stays — but noisy). The gate keeps the first-boot-after-change
    # apply behaviour while silently skipping identical re-applies.
    _mat_enabled = os.getenv('MATERIALIZED_BALANCES', 'true').lower() == 'true'
    if _mat_enabled and got_lock:
        try:
            import pathlib
            import hashlib
            _migration_path = pathlib.Path(__file__).parent / "migrations" / "materialized_balances.sql"
            if _migration_path.exists():
                _sql = _migration_path.read_text()
                _sql_hash = hashlib.sha256(_sql.encode()).hexdigest()
                async with engine.begin() as conn:
                    # §2026-07-26 FRESH-DB FIX — the old probe cast the literal
                    # directly to ::regprocedure, which RAISES UndefinedFunction on a
                    # VIRGIN EventStore (the function is created BY the very migration
                    # we're deciding to run). The broad `except` below then swallowed
                    # it, so `materialized_balances` + `supply_summary` were NEVER
                    # created on a brand-new ES and `/projections/supply-audit` 500'd
                    # forever ("relation supply_summary does not exist"). `to_regproc`
                    # returns NULL instead of raising, so a fresh DB now falls through
                    # to the apply branch. Found standing up a fresh sovereign frame.
                    _stored_row = await conn.execute(text(
                        "SELECT obj_description(to_regproc('update_materialized_balances')::oid, 'pg_proc')"
                    ))
                    _stored_hash = _stored_row.scalar()
                if _stored_hash == _sql_hash:
                    logging.info(
                        f"Phase 1 Scaling: materialized_balances function up to date (hash={_sql_hash[:8]})"
                    )
                else:
                    async with engine.begin() as conn:
                        raw_conn = await conn.get_raw_connection()
                        await raw_conn.driver_connection.execute(_sql)
                    # Stamp the new hash in the function comment so the next
                    # boot's check short-circuits. COMMENT ON is DDL and
                    # doesn't accept bind parameters; we inline safely since
                    # the hash is a hex string from our own hashlib.
                    async with engine.begin() as conn:
                        await conn.execute(text(
                            f"COMMENT ON FUNCTION update_materialized_balances() IS '{_sql_hash}'"
                        ))
                    logging.info(
                        f"Phase 1 Scaling: applied new materialized_balances function (hash={_sql_hash[:8]})"
                    )
            else:
                logging.warning(f"Phase 1 Scaling: migration file not found at {_migration_path}")
        except Exception as _mat_exc:
            logging.warning(f"Phase 1 Scaling: materialized_balances migration warning: {_mat_exc}")

    # Start custom EventStore metrics refresh loop.
    # Pre-warm: kick off the first refresh immediately as its own task so
    # the stats cache gets populated as soon as the queries finish (~30-60s
    # on a multi-million-row table).
    #
    # §2026-08-30 — interval raised 60s -> 900s (15 min) and made env-tunable.
    # The events-by-type GROUP BY is a FULL SCAN of `events` (103.7M rows /
    # 74 GB as of this date). `hold_leadership` already makes concurrent scans
    # impossible, but a single scan now takes ~73s (was ~26s warm when the
    # leader-election comment was written), so at a 60s interval the box was
    # scanning ~55% of wall-clock and streaming 74 GB through page cache
    # continuously. That evicted the pages the registries' mmap'd workers
    # depend on; the box fell into swap thrash (~18k pages/sec) and gunicorn
    # workers on frame-b/frame-c took SIGBUS, serving 000 for 38 minutes.
    # At 900s the duty cycle drops ~55% -> ~7.5%. Overlap safety is unchanged
    # (still leader-held); this only reduces how often the scan runs.
    from .metrics_exporter import metrics_refresh_loop, refresh_eventstore_metrics
    try:
        _metrics_interval_s = int(os.getenv("ES_METRICS_REFRESH_INTERVAL_S", "900"))
    except ValueError:
        _metrics_interval_s = 900
    asyncio.create_task(refresh_eventstore_metrics())  # pre-warm
    asyncio.create_task(metrics_refresh_loop(interval_seconds=_metrics_interval_s))

    # Phase 1 Scaling: Start Kafka consumer (reads from Redpanda topics)
    # Disabled by default — set KAFKA_ENABLED=true to activate.
    from .services.kafka_consumer import start_kafka_consumer
    await start_kafka_consumer()

    # Phase 2: Kafka publisher for HTTP→Kafka pathway (dual-write fix)
    # When EVENTSTORE_HTTP_VIA_KAFKA=true, HTTP POST /events/ publishes to Kafka
    # instead of writing to DB directly, making the consumer the sole DB writer.
    from .services.kafka_publisher import start_kafka_publisher
    await start_kafka_publisher()

    # SF-4: Cross-frame event replication daemon
    if os.getenv("CROSS_FRAME_REPLICATION_ENABLED", "false").lower() == "true":
        from .services.cross_frame_replicator import start_replication
        asyncio.create_task(start_replication())
        logging.info("SF-4: Cross-frame event replication daemon started")

    # Pre-warm WS Redis Pub/Sub so the first browser doesn't pay the 3s cold
    # Redis connect + subscribe cost (previously every worker paid it lazily
    # on its first WS client, pushing landing-page first-event latency to 10s+).
    from .services.websocket_publisher import connection_manager
    try:
        await connection_manager._ensure_pubsub()
        logging.info("WebSocket Redis Pub/Sub pre-warmed")
    except Exception as e:
        logging.warning(f"WS Pub/Sub pre-warm failed (non-fatal, will lazy-init): {e}")

    logging.info("Event Store started successfully (Prometheus metrics enabled)")

@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown — stop background consumers and publishers."""
    from .services.kafka_consumer import stop_kafka_consumer
    from .services.kafka_publisher import stop_kafka_publisher
    await stop_kafka_consumer()
    await stop_kafka_publisher()
    # WS3.5: stop the cross-frame replicator supervisor + cancel per-peer tasks
    try:
        from .services.cross_frame_replicator import stop_replication
        await stop_replication()
    except Exception as e:
        logging.warning(f"Cross-frame replicator stop warning: {e}")
    logging.info("Event Store shutdown complete")

# Prometheus instrumentation — exposes /metrics endpoint
# Tracks: http_request_duration_seconds, http_requests_total,
#         http_request_size_bytes, http_response_size_bytes
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_group_untemplated=True,
    excluded_handlers=["/metrics", "/health", "/docs", "/openapi.json"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

@app.get("/")
async def root():
    return {
        "service": "AgentVault Event Store",
        "status": "operational",
        "endpoints": {
            "health": "/api/v1/events/health",
            "events": "/api/v1/events",
            "projections": "/api/v1/projections",
            "websocket": "/ws/events",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health():
    from . import kafka_record_auth as _kafka_record_auth, kafka_security as _kafka_security

    # §SOVKIT T2: the posture is part of health, so Frame Management and the batteries read the store's own answer
    # instead of a second copy of its flags.
    return {
        "status": "healthy",
        "service": "event-store",
        "mtls_required": events.MTLS_REQUIRED,
        "method1_proxy_trust": events.METHOD1_PROXY_TRUST,
        # §SOVKIT-2 R1: whether the ledger takes only records this store signed, and how its Kafka clients connect
        "kafka_record_auth": _kafka_record_auth.describe(),
        "kafka_client": _kafka_security.describe(),
    }