"""
Enhanced main application entry point for TEG Core Service

Production-grade FastAPI application with:
- Structured logging
- Security headers
- Request tracking
- Comprehensive error handling
- Performance monitoring
- Graceful shutdown
"""
import asyncio
import time
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core.secure_config import get_settings
from .core.enhanced_security import SecurityHeadersMiddleware
from .core.logging import (
    setup_logging, get_logger, log_request_middleware,
    SecurityLogger, request_id_var
)
from .database.db_session import engine, get_db
from .database.models import Base
# Import the master router - OPERATION ARCHITECT'S RAZOR
from .api.v1.api import api_router
from .api.v1.enhanced_schemas import ErrorResponse as LegacyErrorResponse, ErrorCode
# Import unified error handlers (POLISH-001)
from .errors import register_error_handlers
# Import OAuth federation auth if enabled
from .api.auth_enhanced import initialize_multi_issuer_auth, cleanup_multi_issuer_auth
# Import Cross-TEG components
from .core.cross_teg import CrossTEGTransferProtocol, DistributedTransactionCoordinator
from .core.cross_teg.client import CrossTEGClientFactory
from .core.cross_teg.sweeper import start_sweeper, stop_sweeper
from .core.balance_outbox import start_balance_outbox, stop_balance_outbox
from .core.escrow_lock_reconciler import start_escrow_reconciler, stop_escrow_reconciler
from .api.cross_teg_router import router as cross_teg_router, init_cross_teg_router, resolve_partner_url
from .core.cross_teg_security import initialize_security_monitor, default_alert_handler
# Import Event Store integration
from .event_store_integration import initialize_event_store_integration, get_event_store_status

# Initialize configuration and logging
settings = get_settings()
setup_logging()
logger = get_logger(__name__)
security_logger = SecurityLogger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle with comprehensive startup/shutdown
    
    Startup:
    - Initialize logging
    - Create/verify database schema
    - Validate configuration
    - Warm up connection pools
    
    Shutdown:
    - Graceful connection closure
    - Flush pending logs
    - Resource cleanup
    """
    # Startup
    start_time = time.time()
    logger.info(f"starting_teg_core_service - environment: {settings.environment}, version: {settings.app_version}")
    
    # Validate critical configuration
    try:
        if settings.environment == "production":
            if settings.debug:
                raise ValueError("Debug mode cannot be enabled in production")
            if settings.cors_allowed_origins == ["*"]:
                logger.warning("cors_wide_open_in_production - CORS allowing all origins in production is a security risk")
    except Exception as e:
        logger.error(f"configuration_validation_failed - error: {str(e)}")
        raise
    
    # Create database tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("database_schema_verified")
    except Exception as e:
        logger.error(f"database_schema_creation_failed - error: {str(e)}")
        raise

    # §pass73.3.19 L1 — apply the balance-change journal trigger idempotently at startup
    # (complete-by-construction source for the L2 CQRS outbox). Mirrors the EventStore's startup
    # apply of materialized_balances.sql. Non-fatal: if it fails, apply the .sql manually.
    try:
        import os as _os_jrnl
        _jrnl_path = _os_jrnl.path.join(_os_jrnl.path.dirname(__file__), "migrations", "balance_journal.sql")
        with open(_jrnl_path, "r") as _jf:
            _jrnl_sql = _jf.read()
        with engine.begin() as _jconn:
            _jconn.exec_driver_sql(_jrnl_sql)
        logger.info("balance_ledger_journal_trigger_applied")
    except Exception as e:
        logger.error(f"balance_journal_apply_failed - error: {str(e)} (continuing)")
    
    # Verify database connection (sync engine)
    try:
        db = next(get_db())
        result = db.execute(text("SELECT 1"))
        db.close()
        logger.info("database_connection_verified")
    except Exception as e:
        logger.error(f"database_connection_failed - error: {str(e)}")
        raise

    # Runtime-invariant smoke test (2026-05-16 — rails-for-AI)
    # Verifies the asyncpg→pgbouncer→PG path actually works AND honors the
    # cluster-level statement_timeout=15s guard. Catches the §pass24 class
    # of mistake (config "verified" at wrong layer) automatically: if a
    # future change accidentally regresses the async path or breaks the
    # PG-level timeout, the container fails to start instead of silently
    # returning 500s on every cross-TEG async op.
    try:
        from .database.db_session import AsyncSessionLocal
        if AsyncSessionLocal is not None:
            async with AsyncSessionLocal() as s:
                # 1. Basic round-trip works
                r1 = (await s.execute(text("SELECT 1"))).scalar()
                if r1 != 1:
                    raise RuntimeError(f"async SELECT 1 returned {r1!r}, expected 1")
                # 2. statement_timeout invariant — must be 15s for cross-TEG safety
                st = (await s.execute(text("SHOW statement_timeout"))).scalar()
                if st != "15s":
                    raise RuntimeError(
                        f"asyncpg→pgbouncer→PG statement_timeout={st!r}, expected '15s'. "
                        f"Cluster-level config missing? Check docker-compose `-c statement_timeout=15000` "
                        f"on mainframe TEG DB, or postgresql.conf on cloud-op TEG DB."
                    )
            logger.info(f"async_engine_invariants_verified - statement_timeout={st}, path=asyncpg→pgbouncer→PG")
        else:
            logger.info("async_engine_invariants_skipped - AsyncSessionLocal is None (non-postgres DB)")
    except Exception as e:
        logger.error(f"async_engine_invariants_failed - error: {str(e)}")
        if settings.environment == "production":
            # Fail-fast in production: the canary class of bugs is too costly to allow
            # silent regression. Operator must investigate before serving traffic.
            raise
        else:
            logger.warning("continuing_with_broken_async_invariants - DEVELOPMENT MODE ONLY")
    
    # OWL26: Treasury auto-seed DISABLED — use admin mint endpoints or scripts/01treasury_tool.py
    # to fund treasury manually after DB wipe. Removed to prevent unaudited balance injection.
    logger.info("treasury_auto_seed_disabled - use admin mint endpoint or 01treasury_tool.py")
    
    # Initialize Event Store integration
    try:
        event_store_initialized = initialize_event_store_integration()
        if event_store_initialized:
            logger.info("event_store_integration_initialized - Events will be emitted to Event Store")
        else:
            logger.warning("event_store_integration_failed - TEG will operate without event emission")
    except Exception as e:
        logger.error(f"event_store_integration_error - error: {str(e)}")
        if settings.environment == "production":
            # In production, we might want to fail fast
            # raise
            pass
        else:
            logger.warning("continuing_without_event_store - Development mode")
    
    # Initialize batch writer if TEG_BATCH_WRITES=true (Phase 1 scaling)
    import os as _os
    if _os.environ.get("TEG_BATCH_WRITES", "").lower() in ("true", "1", "yes"):
        try:
            from .database.batch_writer import init_batch_writer
            from .database.db_session import SessionLocal
            await init_batch_writer(SessionLocal)
            logger.info("batch_writer_initialized - TEG_BATCH_WRITES=true")
        except Exception as e:
            logger.error(f"batch_writer_initialization_failed - error: {str(e)}")
            # Non-fatal: fall back to synchronous per-request transfers
    else:
        logger.info("batch_writer_disabled - TEG_BATCH_WRITES not set, using per-request transfers")

    # §pass73.3.19 L2 — start the balance outbox emitter (journal → LedgerBalanceChanged → ES).
    # Leader-elected; independent of cross-TEG init. DISABLED by default (TEG_BALANCE_OUTBOX_ENABLED)
    # until the projection single-writer cutover + re-baseline land (else double-count).
    try:
        await start_balance_outbox()
    except Exception as e:
        logger.error(f"balance_outbox_start_failed - error: {str(e)} (continuing)")

    # §P2 (2026-06-02) — orphaned-escrow-lock reconciler. Leader-elected; DISABLED by default
    # (ESCROW_RECONCILER_ENABLED) and DRY_RUN by default. Releases phantom locked_balance left
    # by the cross-TEG 2PC escrow path — pure-escrow agents only (skips stakers + bridge), Δ-safe.
    try:
        await start_escrow_reconciler(settings.teg_id, get_db)
    except Exception as e:
        logger.error(f"escrow_reconciler_start_failed - error: {str(e)} (continuing)")

    # §SECFIX-15 (2026-09-25) — every inbound cross-TEG credit checked against the source's TokensTransferred in this TEG's
    # event store (core/cross_teg/inbound_reconciler.py). Observe only, leader-elected; CROSS_TEG_INBOUND_RECONCILE_ENABLED.
    try:
        from .core.cross_teg.inbound_reconciler import start_inbound_reconciler
        await start_inbound_reconciler()
    except Exception as e:
        logger.error(f"inbound_reconciler_start_failed - error: {str(e)} (continuing)")

    startup_duration = time.time() - start_time
    logger.info(f"startup_completed - duration_seconds: {startup_duration}")

    # Initialize OAuth federation if enabled
    if settings.oauth_federation_enabled:
        try:
            await initialize_multi_issuer_auth()
            logger.info("oauth_federation_initialized - multi-issuer authentication enabled")
        except Exception as e:
            logger.error(f"oauth_federation_initialization_failed - error: {str(e)}")
            if settings.environment == "production":
                raise  # Fail fast in production
            else:
                logger.warning("continuing_without_oauth_federation - Single-issuer mode active")
    
    # Phase 11.1 (2026-04-28): wire emission-policy invalidation listener.
    # Each uvicorn worker subscribes to the namespaced channel so cross-worker
    # cache drops propagate via Redis pub/sub. TTL is the safety net.
    try:
        from .event_emitter import start_emission_policy_invalidation_listener
        start_emission_policy_invalidation_listener()
        logger.info("teg_emission_policy_invalidation_listener_started")
    except Exception as e:
        logger.warning(f"teg_emission_policy_invalidation_listener_failed - error: {str(e)}")

    # Initialize Cross-TEG functionality if enabled
    if settings.cross_teg_enabled:
        try:
            # Create Cross-TEG components
            transfer_protocol = CrossTEGTransferProtocol(
                teg_id=settings.teg_id,
                db_session_factory=get_db
            )
            
            teg_client_factory = CrossTEGClientFactory()
            
            transaction_coordinator = DistributedTransactionCoordinator(
                teg_id=settings.teg_id,
                protocol=transfer_protocol,
                teg_client_factory=lambda teg_id, url_hint=None: teg_client_factory.get_client(
                    teg_id,
                    resolve_partner_url(teg_id, url_hint=url_hint)
                )
            )
            
            # Initialize the cross-TEG router
            init_cross_teg_router(transfer_protocol, transaction_coordinator, teg_client_factory)
            
            # Initialize security monitor
            security_monitor = initialize_security_monitor(settings.teg_id)
            security_monitor.register_alert_callback(default_alert_handler)
            
            # Include the router
            app.include_router(cross_teg_router)

            logger.info(f"cross_teg_initialized - teg_id: {settings.teg_id}, partners: {len(settings.parsed_partner_tegs)}")
            logger.info("cross_teg_security_monitor_initialized")

            # §pass26 (2026-05-17) — start the durable 2PC sweeper. Periodic,
            # leader-elected per TEG; closes the stuck-coordination class
            # by sweeping expired source-side rows past expires_at.
            try:
                await start_sweeper(transaction_coordinator)
                logger.info("cross_teg_sweeper_started")
            except Exception as e:
                logger.error(f"cross_teg_sweeper_start_failed - error: {str(e)}")
                # Non-fatal: TEG continues; sweeper just isn't running. The
                # stuck-2PC class re-opens but doesn't break primary traffic.

            # §pass47 A4 (2026-05-19) — partner cache Redis sync.
            # Seed runtime partners from Redis (so a freshly-started worker
            # learns about previously-discovered partners) and start a 30s
            # background refresh that absorbs cross-worker updates.
            try:
                from .api.cross_teg_router import refresh_partners_from_redis
                seeded = await refresh_partners_from_redis(force_full=True)
                logger.info(f"partner_cache_redis_seeded - new_or_updated: {seeded}")

                async def _partner_cache_refresh_loop() -> None:
                    while True:
                        try:
                            await asyncio.sleep(30)
                            changed = await refresh_partners_from_redis()
                            if changed:
                                logger.info(f"partner_cache_refreshed - changed: {changed}")
                        except asyncio.CancelledError:
                            break
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"partner_cache_refresh_error - {e}")

                asyncio.create_task(_partner_cache_refresh_loop())
                logger.info("partner_cache_refresh_loop_started")
            except Exception as e:
                logger.warning(f"partner_cache_init_failed - error: {str(e)} (continuing without Redis sync)")

        except Exception as e:
            logger.error(f"cross_teg_initialization_failed - error: {str(e)}")
            if settings.environment == "production":
                raise
            else:
                logger.warning("continuing_without_cross_teg - Cross-TEG transfers disabled")

    # §FEDLICENCE (his word 2026-09-28 "cross-teg cut off also approved on revoke"): copy this frame's registry's licence
    # verdicts, so the certificate reader refuses a frame the registry refuses (core/licence_gate). Every worker holds
    # its own copy; a failed read keeps the last one.
    try:
        from .core.licence_gate import refresh_loop as _licence_refresh_loop
        asyncio.create_task(_licence_refresh_loop())
        logger.info("licence_verdict_refresh_loop_started")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"licence_verdict_refresh_loop_not_started - {type(e).__name__}: {e}")

    yield

    # Shutdown
    logger.info("shutting_down_teg_core_service")

    # Shutdown batch writer (drain remaining transfers)
    try:
        from .database.batch_writer import shutdown_batch_writer
        await shutdown_batch_writer()
        logger.info("batch_writer_shutdown_completed")
    except Exception as e:
        logger.error(f"batch_writer_shutdown_failed - error: {str(e)}")

    # Shutdown Kafka producer (Phase 1 scaling)
    try:
        from .event_emitter import shutdown_kafka
        await shutdown_kafka()
        logger.info("kafka_producer_shutdown_completed")
    except Exception as e:
        logger.error(f"kafka_producer_shutdown_failed - error: {str(e)}")

    # Phase 11.1: stop invalidation listeners + close Redis pool
    try:
        from .cache_invalidation import stop_all_listeners
        await stop_all_listeners()
        logger.info("teg_invalidation_listeners_stopped")
    except Exception as e:
        logger.warning(f"teg_invalidation_listeners_stop_failed - error: {str(e)}")

    try:
        from .redis_client import close_redis
        await close_redis()
        logger.info("teg_redis_closed")
    except Exception as e:
        logger.warning(f"teg_redis_close_failed - error: {str(e)}")

    # Cleanup OAuth federation resources
    if settings.oauth_federation_enabled:
        try:
            await cleanup_multi_issuer_auth()
            logger.info("oauth_federation_cleanup_completed")
        except Exception as e:
            logger.error(f"oauth_federation_cleanup_failed - error: {str(e)}")
    
    # §pass26 — stop the 2PC sweeper before client teardown so its in-flight
    # audit emits can complete cleanly.
    try:
        await stop_sweeper()
        logger.info("cross_teg_sweeper_stopped")
    except Exception as e:
        logger.error(f"cross_teg_sweeper_stop_failed - error: {str(e)}")

    # §P2 — stop the escrow-lock reconciler.
    try:
        await stop_escrow_reconciler()
        logger.info("escrow_reconciler_stopped")
    except Exception as e:
        logger.error(f"escrow_reconciler_stop_failed - error: {str(e)}")

    # §pass73.3.19 L2 — stop the balance outbox emitter.
    try:
        await stop_balance_outbox()
        try:
            from .core.cross_teg.inbound_reconciler import stop_inbound_reconciler
            await stop_inbound_reconciler()
        except Exception:
            pass
        logger.info("balance_outbox_stopped")
    except Exception as e:
        logger.error(f"balance_outbox_stop_failed - error: {str(e)}")

    # Cleanup Cross-TEG resources
    if settings.cross_teg_enabled and 'teg_client_factory' in locals():
        try:
            await teg_client_factory.close_all()
            logger.info("cross_teg_cleanup_completed")
        except Exception as e:
            logger.error(f"cross_teg_cleanup_failed - error: {str(e)}")
    
    # Graceful shutdown tasks
    try:
        # Give time for pending requests to complete
        logger.info("waiting_for_pending_requests")
        # In production, you might wait for pending requests here
        
        # Close database connections
        engine.dispose()
        logger.info("database_connections_closed")
        
    except Exception as e:
        logger.error(f"shutdown_error - error: {str(e)}")
    
    logger.info("shutdown_completed")


# Create FastAPI application with enhanced configuration
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="TheProtocol v2.0 TEG Layer Core Service - Production-Grade Token Economy Management",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else "/api/v1/openapi.json"
)

# --- §pass52 PR-1: cluster-wide securitySchemes library + servers block (TEG) ---
from fastapi.openapi.utils import get_openapi as _get_openapi
_OPENAPI_SECURITY_SCHEMES = {
    "DeveloperJWT":      {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                          "description": "Developer JWT (forwarded by Registry proxy)"},
    "AgentJWT":          {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                          "description": "Agent JWT from /api/v1/auth/token"},
    "AdminDeveloperJWT": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                          "description": "Admin developer JWT for /admin/* routes"},
    "BootstrapToken":    {"type": "apiKey", "in": "header", "name": "Bootstrap-Token",
                          "description": "Onboarding bootstrap token (proxied via Registry)"},
    "APIKey":            {"type": "http", "scheme": "bearer", "bearerFormat": "tegauth_…",
                          "description": "TEG admin API key (X-Admin-API-Key)"},
    "mTLSPeer":          {"type": "mutualTLS",
                          "description": "SPIFFE-issued X.509 SVID; for cross-TEG saga"},
    "FederationLicense": {"type": "apiKey", "in": "header", "name": "X-Federation-License",
                          "description": "Operator license, revocable"},
    # §pass54 PR-3-expansion: additional service-side APIKey schemes used by
    # /tokenomics/{lock,unlock,balance/{did}}, /reputation-signal/*, /avtp/*.
    # Runtime validation already in place; these annotations close T-P0-3.
    "ServiceToken":      {"type": "apiKey", "in": "header", "name": "X-Service-Token",
                          "description": "Service token for staking lock/unlock + reputation-signal endpoints"},
    "AgentDID":          {"type": "apiKey", "in": "header", "name": "X-Agent-DID",
                          "description": "Agent DID of the principal whose balance is being moved"},
    "AVTPSystemKey":     {"type": "apiKey", "in": "header", "name": "X-AVTP-System-Key",
                          "description": "AVTP system key for /avtp/* endpoints"},
}
_OPENAPI_SERVERS = [
    {"url": "http://agentvault_teg_layer_a:8080", "description": "TEG — Frame A (internal cluster)"},
    {"url": "http://frame-b-teg:8080",            "description": "TEG — Frame B (internal cluster)"},
    {"url": "http://localhost:8080",              "description": "Local dev"},
]

def _rewrite_security_to_named_schemes(schema_in: dict) -> None:
    """§pass56 PR-1F + §pass58.5 — Maps auto-generated FastAPI security refs to
    named library schemes.

    JWT-bearer schemes (OAuth2PasswordBearer / HTTPBearer):
        /admin/* → AdminDeveloperJWT
        /token/transfer, /staking/*, /governance/*, /disputes/*, /avtp/*,
        /reputation-signal → AgentJWT
        everything else → DeveloperJWT

    §pass58.5 — APIKeyHeader (auto-generated for `Security(api_key_header)` deps):
        /cross-teg/* → mTLSPeer  (SPIFFE JWT-SVID via verify_jwt_svid; cross-frame saga)
        /admin/* → APIKey        (X-Admin-API-Key header via verify_admin_key)
        else → APIKey            (conservative default for any other api-key surfaces)
    """
    AGENT_PATH_HINTS = (
        "/token/transfer", "/staking/", "/governance/", "/disputes/", "/avtp/",
        "/reputation-signal",
    )
    bearer_legacy_names = {"OAuth2PasswordBearer", "HTTPBearer"}
    apikey_legacy_names = {"APIKeyHeader"}
    paths = schema_in.get("paths") or {}
    for p, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        # Bearer-scheme target (existing logic)
        if p.startswith("/api/v1/admin"):
            bearer_target = "AdminDeveloperJWT"
        elif any(h in p for h in AGENT_PATH_HINTS):
            bearer_target = "AgentJWT"
        else:
            bearer_target = "DeveloperJWT"
        # §pass58.5 — APIKeyHeader target (per path family)
        if p.startswith("/api/v1/cross-teg"):
            apikey_target = "mTLSPeer"
        else:
            apikey_target = "APIKey"
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
                    if sname in bearer_legacy_names:
                        new_entry[bearer_target] = scopes or []
                        changed = True
                    elif sname in apikey_legacy_names:
                        new_entry[apikey_target] = scopes or []
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

# §LEDGERGATE (2026-10-11): a request that starts a value movement waits for a ledger that can record it
# (TEG_LEDGER_GATE_MODE, default off; core/ledger_gate.py has the route classes and the rule). Added FIRST, so it is
# the innermost middleware: the Host check runs before it and its 503 carries the security headers.
from .core.ledger_gate import LedgerGate, LedgerUnavailableError, problem_response as _ledger_problem

app.add_middleware(LedgerGate)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# §SECFIX-9 (2026-09-25): the Host check by its own posture flag (TEG_TRUSTED_HOSTS_MODE, default observe). It was
# Starlette's TrustedHostMiddleware behind `settings.environment == "production"`, which no running TEG set (24 of 24
# unset), so it never ran, and it listed Frame A's container names. core/trusted_hosts.py has the rule and the reasons.
from .core.trusted_hosts import TrustedHostsGate

app.add_middleware(TrustedHostsGate)


# Configure CORS with environment-specific settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"]
)

# Add request logging middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    return await log_request_middleware(request, call_next)

# Register unified error handlers (POLISH-001)
register_error_handlers(app)
logger.info("Unified error handlers registered for consistent API error responses")


# W2 (2026-05-05) — convert AgentNotHomeError → 409 Conflict so callers (saga,
# reactor, /teg/transfer) get a structured signal instead of a 500. Saga
# refunds at timeout on any non-2xx; this just makes the failure observable.
from .database.home_frame_resolver import AgentNotHomeError as _AgentNotHomeError
from fastapi.responses import JSONResponse as _JSONResponse


@app.exception_handler(_AgentNotHomeError)
async def _agent_not_home_handler(request: Request, exc: _AgentNotHomeError):
    return _JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "error_type": "agent_not_home",
            "agent_id": exc.agent_id,
            "home_frame": exc.home_frame,
            "this_frame": exc.this_frame,
        },
    )


@app.exception_handler(LedgerUnavailableError)
async def _ledger_unavailable_handler(request: Request, exc: LedgerUnavailableError):
    # the exchange and FX movers decide for themselves (into the account starts, out of it finishes)
    return _ledger_problem(str(request.url.path), exc.verdict)


# Note: Exception handlers are now registered via register_error_handlers() above
# This provides unified error responses across all TEG layer endpoints


# Enhanced health check endpoint
@app.get("/health", 
         tags=["health"], 
         summary="Comprehensive Health Check",
         response_model=Dict[str, Any])
async def health_check():
    """
    Comprehensive health check endpoint
    
    Returns detailed health status including:
    - Overall service health
    - Database connectivity
    - Configuration status
    - Resource availability
    """
    health_status = {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "checks": {}
    }
    
    # Database health check
    try:
        start = time.time()
        db = next(get_db())
        db.execute(text("SELECT 1"))
        db.close()
        db_latency = int((time.time() - start) * 1000)
        
        health_status["checks"]["database"] = {
            "status": "healthy",
            "latency_ms": db_latency
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        logger.error(f"health_check_database_failed - error: {str(e)}")
    
    # §MTLSHOPS G1: the forwarded-certificate posture, reported the way the event store reports its own
    # (method1_proxy_trust false: a caller presenting a certificate through nginx-teg is refused until TEG_PROXY_TRUST_SECRET is set)
    try:
        from .core.internal_auth import method1_proxy_trust, teg_mtls_required
        health_status["mtls"] = {"method1_proxy_trust": method1_proxy_trust(), "mtls_required": teg_mtls_required()}
    except Exception as e:  # noqa: BLE001
        health_status["mtls"] = {"error": type(e).__name__}

    # §FEDLICENCE: the licence verdicts this TEG copied from its registry (this worker's copy; trust domains only)
    try:
        from .core.licence_gate import status as _licence_status
        health_status["federation_licence"] = _licence_status()
    except Exception as e:  # noqa: BLE001
        health_status["federation_licence"] = {"error": type(e).__name__}

    # §LEDGERGATE: the gate's mode and this worker's reading of the ledger (the outbox leader's verdict, else the journal)
    try:
        from .core.ledger_gate import status as _ledger_status
        health_status["ledger"] = await _ledger_status()
    except Exception as e:  # noqa: BLE001
        health_status["ledger"] = {"error": type(e).__name__}

    # Configuration health check
    health_status["checks"]["configuration"] = {
        "status": "healthy",
        "debug_mode": settings.debug,
        "log_level": settings.log_level
    }
    
    # Event Store health check
    try:
        health_status["checks"]["event_store"] = get_event_store_status()
    except Exception:
        health_status["checks"]["event_store"] = {"status": "unavailable"}
    
    return health_status


# Enhanced root endpoint
@app.get("/", 
         tags=["root"], 
         summary="Service Information",
         response_model=Dict[str, Any])
async def root():
    """
    Enhanced root endpoint with comprehensive service information
    """
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "description": "AgentVault v2.0 TEG Layer Core Service - Production-Grade Token Economy Management",
        "api": {
            "v1": {
                "base_url": settings.api_v1_prefix,
                "documentation": "/api/v1/openapi.json" if settings.environment == "production" else "/docs",
                "health": "/health"
            }
        },
        "features": [
            "Token Management",
            "Attestation System",
            "Reputation Tracking",
            "Dispute Resolution",
            "AVTP Integration",
            "Auditor Rules"
        ]
    }


# OPERATION ARCHITECT'S RAZOR: Single Source of Truth
# The ONE and ONLY router inclusion for the v1 API
app.include_router(api_router, prefix=settings.api_v1_prefix)

# --- Prometheus Instrumentation (OWL-MON Phase 2) ---
# Exposes /metrics endpoint with request-level metrics
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_group_untemplated=True,
    excluded_handlers=["/metrics", "/health", "/docs", "/redoc", "/openapi.json"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
logger.info("prometheus_instrumentation_enabled - endpoint: /metrics")


# Enhanced startup event
@app.on_event("startup")
async def log_configuration():
    """Log configuration and routes on startup"""
    
    # Log non-sensitive configuration
    logger.info(f"service_configuration - environment: {settings.environment}, debug: {settings.debug}, log_level: {settings.log_level}, log_format: {settings.log_format}, api_prefix: {settings.api_v1_prefix}, cors_origins: {settings.cors_allowed_origins}, database_type: {'postgresql' if 'postgresql' in settings.database_url else 'sqlite'}")
    
    # Log registered routes
    # §DEPS (2026-09-27): since FastAPI 0.14x an included router is ONE lazily resolved entry in app.routes, so a
    # plain walk counts about fifty routes; iter_route_contexts yields every served route with its full path.
    try:
        from fastapi.routing import iter_route_contexts
        served = list(iter_route_contexts(app.routes))
    except ImportError:  # FastAPI before the lazy include: app.routes is already flat
        served = list(app.routes)
    routes = []
    for route in served:
        if hasattr(route, "methods") and hasattr(route, "path"):
            routes.append({
                "methods": list(route.methods),
                "path": route.path,
                "name": route.name
            })
    
    logger.info(f"registered_routes - route_count: {len(routes)}")
    
    # Log in debug mode
    if settings.debug:
        for route in routes:
            logger.debug(f"route_registered - methods: {route['methods']}, path: {route['path']}, name: {route['name']}")
    
    # Security check
    if settings.environment == "production":
        security_logger.log_admin_action(
            "service_started",
            details={"version": settings.app_version}
        )


if __name__ == "__main__":
    import uvicorn
    
    # Development server configuration
    uvicorn.run(
        "teg_core_service.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=settings.debug
    )
