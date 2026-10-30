import logging
import asyncio
import os
from fastapi import FastAPI, Request, Response, status, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pathlib import Path
import json


# --- Rate Limiting Imports ---
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
# Import our enhanced rate limiter
from agentvault_registry.middleware.rate_limiter import (
    create_enhanced_limiter, admin_api_key_middleware, get_user_role_from_request,
    rate_limit_lane_middleware,
)
# --- End Rate Limiting Imports ---

# Import settings - this also triggers loading from .env
from agentvault_registry.config import settings
# §DIDWIDEN item 1 (2026-09-06, his approval) — G2: a registry whose DID_ISSUER_NAMESPACE is not its own
# SPIFFE trust domain refuses to boot (it would mint DIDs every peer's guard drops). Unset = byte-inert.
from agentvault_registry.identifiers import assert_issuer_posture as _assert_issuer_posture
_assert_issuer_posture()
# Import the router
from agentvault_registry.routers import (
    agent_cards, utils, auth, developers, agent_builder, teg_integration,
    federation_peers, admin_federation, federation_public, federation_sync, federation_query, federation_topology, onboarding, agents, admin,
    attestations, disputes, staking, governance, contracts, system, reputation_signal,
    fiat_onramp,                    # PB-1: Stripe Fiat → AVT on-ramp (mainframe-only, env-gated)
    account_deletion,               # W2 (2026-05-09): GDPR Art. 17 user-initiated account erasure
    auth_secure,  # Enhanced authentication (no longer a stub)
    oauth_federation,  # OAuth federation for cross-registry auth
    auth_2fa,  # Two-Factor Authentication endpoints
    organizations,                  # Organizations and teams management
    agents_export_import,           # Agent export/import functionality
    agent_cicd,                     # Agent CI/CD infrastructure
    disputes_enhanced,  # Beta Strike disputes
    staking_enhanced,  # Enhanced staking with idempotency (REAL IMPLEMENTATION ACTIVE)
    staking_rewards,                # Automatic staking reward distribution
    teg_summary_enhanced,  # Real TEG data
    # teg_integration_jwt_svid,     # TEG with JWT-SVID auth — UNMOUNTED: future work, all 503
    # teg_integration_mtls,         # TEG with mTLS auth — UNMOUNTED: future work, all 503
    # teg_integration_oauth,        # TEG with OAuth auth — UNMOUNTED: future work, all 503
    websocket,                      # WebSocket for real-time updates
    metrics,                        # Agent metrics and analytics
    agent_logs,                     # Agent logging system
    agent_discovery,                # Agent DID lookup endpoints
    track_record,                   # §AGENTDISC — registry-attested guild work history (public)
    teg_transactions,               # TEG advanced transactions
    admin_health,                   # Health monitoring for all endpoints
    admin_api_test,                 # Comprehensive API testing suite
    admin_tutorial,                  # Tutorial sandbox proxy (lightweight)
    admin_invite_codes,              # Beta invite code management
    admin_broadcast,                 # f034: Admin notification broadcast channel
    support,                         # f042: Support ticket system
    endpoints_tokenomics_proxy,     # Tokenomics proxy endpoints for TEG integration
    federation_disputes,             # OWL25: Cross-registry dispute settlement
    enforcement_admin,               # TITANIUM VAULT D2: Enforcement admin endpoints
    enforcement_agent,               # TITANIUM VAULT D2: Enforcement agent self-service
    reputation_bond,                 # §REPBOND: bond config/public block, wallet + backstop rails, admin backstop
    agent_bundle,                    # Agent bundle download (ZIP generation)
    sandbox_proxy,                   # Sandbox proxy for external agent templates
)
from agentvault_registry.routers import federation_admission  # Phase 1: Policy admission pipeline
from agentvault_registry.routers import assistant as assistant_router  # §POCKETBRIDGE3 WS-D
from agentvault_registry.routers import registry_health        # Phase 1: Registry health profiles
from agentvault_registry.routers import reputation_trust  # EigenTrust++ Phase 2
from agentvault_registry.routers import federation_licenses  # f043: Federation license key system
from agentvault_registry.routers import mcp_audit_log  # §pass68 (2026-05-23): per-tool MCP audit log query surface
from agentvault_registry.routers import agent_authz_api  # IRONKEY agent authorization API
from agentvault_registry.routers import agent_delegation_api  # IRONKEY L3/L4 delegation + capability tokens
from agentvault_registry.routers import forge  # GÖDEL FORGE — self-improving-harness arena
from agentvault_registry.routers import federation_license_self  # BL-1: Self-serve license rotation
from agentvault_registry.routers import federation_cli_audit  # BL-1 P8: CLI audit event emission
from agentvault_registry.routers import federation_blocklist  # Phase 10 #4: cross-frame agent blocklist proxy
from agentvault_registry.routers import federation_operator_rename  # §2026-06-14: cross-frame operator-rename apply (event-sourced)
from agentvault_registry.routers import spire_jwks  # Phase 12.1: SPIRE JWT-SVID JWKS endpoint for ES validation
from agentvault_registry.routers import registry_card  # Registry Card v0.3 — public well-known + JWKS + schema
from agentvault_registry.routers import stock_card  # Federated Stock Card — public well-known + API alias (AGORA catalog)
from agentvault_registry.routers import solvency_card  # AGORA Solvency Card (P4) — public well-known + API alias (signed solvency/float attestation)
from agentvault_registry.routers import admin_registry_card  # Registry Card v0.3 — admin CRUD + icon + key rotate
from agentvault_registry.routers import operator_applications  # Operator registry application form
from agentvault_registry.routers import operator_lifecycle  # Option D-light Phase D5: read-only lifecycle + drift endpoints
from agentvault_registry.routers import frame_invitations  # f058 WS3: Sovereign frame bilateral handshake
from agentvault_registry.routers import public_reach_probe  # §EXTREACH design A: the dial-back a self-hosted frame asks for
from agentvault_registry.routers import federation_licence  # §FEDLICENCE: signed network + operator licences
# OWL-22: Agent-own MCP server bundle generator
from agentvault_registry.routers import agent_builder_templates
from agentvault_registry.routers import admin_simulation
# MCP Server
from agentvault_registry.mcp.server import router as mcp_router
from agentvault_registry.mcp.server_admin import router as admin_mcp_router
from agentvault_registry.mcp.oauth import router as mcp_oauth_router
# from agentvault_registry.routers.beta_access import router as beta_access_router, beta_access_worker  # DEPRECATED
from agentvault_registry.routers.funding_requests import agent_router as funding_agent_router, admin_router as funding_admin_router
from agentvault_registry.routers.a2a_payment import router as a2a_payment_router
from agentvault_registry.routers.teg_send import router as teg_send_router
from agentvault_registry.arena.mcp_server import router as arena_mcp_router
from agentvault_registry.arena.spectator import router as arena_spectator_router
from agentvault_registry.arena.td_mcp_server import router as td_mcp_router
from agentvault_registry.arena.snake_mcp_server import router as snake_mcp_router
from agentvault_registry.arena.trading_mcp_server import router as trading_mcp_router
from agentvault_registry.arena.lobby_mcp_server import router as lobby_mcp_router
from agentvault_registry.routers.exchange import router as exchange_router  # AGORA (2026-06-12)
from agentvault_registry.routers.dev_card import dev_router as dev_card_dev_router  # §V0064 Settings: preview/disclosures/consent
from agentvault_registry.routers.dev_card import router as dev_card_router  # AGORA Passport / DevCard v0.1
from agentvault_registry.routers.exchange_federation import router as exchange_federation_router  # AGORA Passport venue endpoints
from agentvault_registry.routers.contract_federation import router as contract_federation_router  # cross-frame contract digest + command rail
from agentvault_registry.routers.federation_operator_purge import router as federation_operator_purge_router  # §F6 WP6.2: a peer frame's operator purge, each frame its own rows
from agentvault_registry.routers.mail_relay import router as mail_relay_router  # §FRAMEMAIL-4 parent-side mail relay (dark unless MAIL_RELAY_ENABLED)
# §pass63 (2026-05-22) — Astraeus subsystem removed. Was an isolated Phase-1
# space MMO with 10 background workers + REST/WS/MCP routers. The isolation
# contract (no AVT mint without going through TEG) held throughout, but the
# subsystem was env-gated dormant since 2026-05-21 and represented ~15K LOC
# of dead weight in every registry image. Full removal per
# sessionlogs2026/PLAN_2026-05-22_ASTRAEUS_RIP_EXECUTION.md.
from agentvault_registry.routers.webhooks import router as webhooks_router
# Import error handlers for unified error schema (POLISH-001)
from agentvault_registry.errors import register_error_handlers
# Import background tasks
from agentvault_registry.background_tasks.leader import get_redis, close_redis
from agentvault_registry.background_tasks.federation_sync import start_federation_sync, stop_federation_sync
from agentvault_registry.background_tasks.auditor_worker import auditor_worker
from agentvault_registry.background_tasks.staking_distributor import start_staking_distributor, stop_staking_distributor
from agentvault_registry.background_tasks.saga_timeout_checker import start_saga_timeout_checker, stop_saga_timeout_checker
from agentvault_registry.background_tasks.peer_activation_keeper import start_peer_activation_keeper, stop_peer_activation_keeper
# §bc2 (2026-05-19) — broadcast scheduler + per-batch email retry worker
from agentvault_registry.background_tasks.broadcast_scheduler import get_broadcast_scheduler
from agentvault_registry.background_tasks.broadcast_email_retry_worker import get_broadcast_email_retry_worker
from agentvault_registry.background_tasks.es_emit_outbox_drainer import get_es_emit_outbox_drainer  # §SOVKIT K1 / V0372
from agentvault_registry.background_tasks.genesis_grant_retry import get_genesis_grant_retry  # §LEDGERGATE V0598
from agentvault_registry.background_tasks.fiat_credit_retry import get_fiat_credit_retry  # §LEDGERGATE V0599
from agentvault_registry.background_tasks.forfeiture_retry import get_forfeiture_retry  # §LEDGERGATE V0599
from agentvault_registry.background_tasks.xreg_revoke_retry import get_xreg_revoke_retry  # D6-272
from agentvault_registry.background_tasks.idempotency_kept_sweeper import get_idempotency_kept_sweeper  # §REPATLANE-8 V0610
from agentvault_registry.background_tasks.agent_card_pullsync import (
    start_agent_card_pullsync, stop_agent_card_pullsync,
)
from agentvault_registry.background_tasks.canary_runner import start_canary_runner, stop_canary_runner
from agentvault_registry.background_tasks.revocation_drill import (
    start_revocation_drill,
    stop_revocation_drill,
)
from agentvault_registry.background_tasks.canary_judge import start_canary_judge, stop_canary_judge
from agentvault_registry.background_tasks.canary_rebalancer import start_canary_rebalancer, stop_canary_rebalancer
from agentvault_registry.background_tasks.fx_router_keeper import start_fx_router_keeper, stop_fx_router_keeper  # AAA+ op→op FX suspense liquidity manager (0085)
from agentvault_registry.background_tasks.fx_reserve_keeper import start_fx_reserve_keeper, stop_fx_reserve_keeper  # cross-frame FX peg keeper (0092)
from agentvault_registry.background_tasks.gateway_float_keeper import start_gateway_float_keeper, stop_gateway_float_keeper  # AGORA gateway solvency keeper (0096)
from agentvault_registry.background_tasks.treasury_market_maker import start_treasury_market_maker, stop_treasury_market_maker  # AGORA treasury MM (P2.1, 0098)
from agentvault_registry.background_tasks.forensic_scanner import start_forensic_scanner, stop_forensic_scanner  # Ledger Forensics scanner (default-OFF)
from agentvault_registry.background_tasks.eigentrust_worker import start_eigentrust_worker, stop_eigentrust_worker  # EigenTrust++ Phase 2
from agentvault_registry.background_tasks.eventstore_balance_sync import start as start_balance_sync, stop as stop_balance_sync
from agentvault_registry.background_tasks.liquid_balance_reconciler import start_liquid_balance_reconciler, stop_liquid_balance_reconciler  # §FRAMELIC row 165: the backstop for agents.liquid_balance
from agentvault_registry.background_tasks.velocity_snapshot import start_velocity_snapshot, stop_velocity_snapshot  # Sprint 9: velocity metrics
from agentvault_registry.background_tasks.collusion_worker import start_collusion_worker, stop_collusion_worker  # Sprint 10: Bayesian decay + SCC detection
from agentvault_registry.background_tasks.compliance_poller import start_compliance_poller, stop_compliance_poller  # Phase 2a: Federation policy compliance polling
from agentvault_registry.background_tasks.license_drift_monitor import start_license_drift_monitor, stop_license_drift_monitor  # Option D-light Phase D4: license/operator/peer state drift detection
from agentvault_registry.background_tasks.supply_auditor import start_supply_auditor, stop_supply_auditor  # Phase 2b: Supply invariant auditor
from agentvault_registry.background_tasks.balance_reconciliation_guard import start_balance_reconciliation_guard, stop_balance_reconciliation_guard  # §pass73.3.19 L3b: ES↔TEG balance reconciliation guard
from agentvault_registry.background_tasks.webhook_retry_worker import start_webhook_retry_worker, stop_webhook_retry_worker  # f040: Webhook retry
from agentvault_registry.background_tasks.agent_health_checker import start_agent_health_checker, stop_agent_health_checker  # f040: Agent health
from agentvault_registry.background_tasks.auto_tally import start_auto_tally, stop_auto_tally  # f042: Auto-tally expired governance proposals
from agentvault_registry.background_tasks.account_deletion_worker import start_account_deletion_worker, stop_account_deletion_worker  # W2 (2026-05-09): GDPR account deletion anonymizer
from agentvault_registry.background_tasks.fiat_routed_reconciler import start_fiat_routed_reconciler, stop_fiat_routed_reconciler  # PB-2 (2026-05-09): mainframe-side routed-fiat reconciler
from agentvault_registry.background_tasks.fiat_routed_local_reconciler import start_fiat_routed_local_reconciler, stop_fiat_routed_local_reconciler  # PB-2 (2026-05-09): operator-side routed-fiat reconciler
from agentvault_registry.background_tasks.fiat_provider_reconciler import start_fiat_provider_reconciler, stop_fiat_provider_reconciler  # PB-3 W5 (2026-05-12): generic PSP reconciler (non-Stripe)
# Import metrics middleware
from agentvault_registry.middleware.metrics_collector import MetricsCollectionMiddleware, metrics_processor
from agentvault_registry.middleware.admission_control import AdmissionControlMiddleware  # 2026-06-09: load-shedding
from agentvault_registry.middleware.readonly_mode import ReadOnlyModeMiddleware  # §29 2026-07-28: break-glass write freeze
from agentvault_registry.middleware.nul_refusal import NulRefusalMiddleware  # §MCPTEST30 2026-10-01: a NUL in a path or query is refused, 400
# Import Event Store integration
from agentvault_registry.event_store_integration import initialize_event_store_integration, get_event_store_status
# Phase 1 Scaling: TEG Bulk Proxy
from agentvault_registry.routers.teg_integration import start_teg_bulk_proxy, stop_teg_bulk_proxy
# 2026-05-01 LIGHTNING-2: TEG Stream Proxy (cross-worker shared buffer batching)
from agentvault_registry.services.teg_stream_proxy import (
    start_teg_stream_proxy,
    stop_teg_stream_proxy,
)
from agentvault_registry.es_ssl_helper import get_httpx_verify


# --- Logging Setup ---
logger = logging.getLogger(__name__)
# §BAFIN (2026-10-01): the switches registry-config reports (core/staking_gate.py, core/agora_gate.py)
from agentvault_registry.core.staking_gate import (  # noqa: E402
    staking_enabled as _staking_enabled, staking_rewards_enabled as _staking_rewards_enabled,
)
from agentvault_registry.core.agora_gate import distributions_enabled as _agora_distributions_enabled  # noqa: E402
from agentvault_registry.services.membership import (  # noqa: E402  §MEMBERSHIP
    weight_mode as _membership_weight_mode, presence_mode as _membership_presence_mode,
)
from agentvault_registry.services.commons import commons_enabled as _commons_enabled  # noqa: E402  §MEMBERSHIP B
from agentvault_registry.services.federation_ballot import ballot_mode as _federation_ballot_mode  # noqa: E402  §MEMBERSHIP D2
# §RELEASEHARDEN D2 (2026-09-14) — never write a query-string credential into an access line. Installed here
# so a bare `uvicorn` launch is covered; gunicorn_conf.py installs the same filter in post_fork (idempotent).
from agentvault_registry.core.access_log_mask import install_access_log_mask as _install_access_log_mask  # noqa: E402
_install_access_log_mask()

# --- Define path to static files ---
# OLD FRONTEND (preserved for rollback): Path(__file__).parent / "static"
# NEW FRONTEND: Serving from the Vue.js build output
STATIC_DIR = Path(__file__).parent / "static" / "new_registry_frontend" / "dist"


# --- ADDED: Dependency Class for Static File Reading ---
class StaticFileReader:
    """Dependency class to handle reading static files."""
    def __init__(self, base_dir: Path = STATIC_DIR):
        # Store base_dir on the instance
        self.base_dir = base_dir
        logger.debug(f"StaticFileReader initialized with base_dir: {self.base_dir}")

    def get_content(self, filename: str) -> str:
        """Reads content of a file in the static directory."""
        file_path = self.base_dir / filename
        logger.debug(f"Attempting to read static file: {file_path}")
        if not file_path.is_file():
            logger.error(f"Static file '{filename}' not found in {self.base_dir}")
            raise FileNotFoundError(f"{filename} not found")
        try:
            content = file_path.read_text(encoding="utf-8")
            logger.debug(f"Successfully read static file: {filename}")
            return content
        except Exception as e:
            logger.exception(f"Error reading static file '{filename}': {e}")
            raise IOError(f"Could not read {filename}")
# --- END ADDED ---


_KIT_BUILD_INFO_CACHE: dict = {}


def _kit_build_info() -> "dict | None":
    """The build's provenance from /app/BUILD_INFO.json (KIT_BUILD_INFO_PATH), read once; the fields a report needs."""
    if "v" not in _KIT_BUILD_INFO_CACHE:
        import json as _json
        import os as _os
        doc = None
        try:
            with open(_os.getenv("KIT_BUILD_INFO_PATH", "/app/BUILD_INFO.json"), encoding="utf-8") as _f:
                raw = _json.load(_f)
            if isinstance(raw, dict):
                doc = {k: raw.get(k) for k in ("kit_version", "tree_digest", "release_digest", "modified",
                                               "changed_files", "built_at") if k in raw}
        except (OSError, ValueError):
            doc = None
        _KIT_BUILD_INFO_CACHE["v"] = doc
    return _KIT_BUILD_INFO_CACHE["v"]


def metrics_enabled() -> bool:
    """METRICS_ENABLED (default true): whether this registry serves GET /metrics.

    §SECFIX D6-254 (2026-10-16, his word: keep /metrics, as a switch per registry an operator can turn off). /metrics
    answers whoever reaches the registry's address, a console that proxies every path to the registry included. Off
    (false, 0, no, off), the route does not exist: nothing can scrape the registry, its own Prometheus included."""
    return (os.getenv("METRICS_ENABLED", "true") or "true").strip().lower() not in ("0", "false", "no", "off")


# --- Application Factory Pattern ---
def create_app() -> FastAPI:
    """
    Application factory for creating a configured FastAPI instance.
    This allows for clean testing by deferring app initialization.
    """
    # --- Enhanced Rate Limiter Setup ---
    limiter = create_enhanced_limiter()
    logger.info("Enhanced rate limiter initialized with role-based limits")

    # --- FastAPI App Initialization ---
    # §LEGALKIT: the API documentation names who runs this frame and under what terms, from the provider
    # facts, never from a literal. On a frame that has published no provider the fields stay absent.
    from agentvault_registry.core import provider_facts as _pf
    from agentvault_registry.core.public_url import public_ui_origin as _ui_origin
    _pf.validate_at_boot()
    _facts = _pf.provider_facts()
    _origin = (_ui_origin() or "").rstrip("/")
    _api_meta = {}
    if _pf.suite_mode() == _pf.MODE_THEPROTOCOL and _origin:
        _api_meta["terms_of_service"] = f"{_origin}/#/legal/terms"
    elif _pf.operator_links().get("terms_url"):
        _api_meta["terms_of_service"] = _pf.operator_links()["terms_url"]
    if _pf.has_provider_identity(_facts):
        _api_meta["contact"] = {"name": _facts.legal_name, "email": _facts.legal_email or _facts.support_email}
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="API for discovering and managing Agent Cards in TheProtocol ecosystem.",
        version="0.1.0",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=None,   # §LEGALKIT V0413: served below from this origin (no CDN, no font provider)
        redoc_url=None,
        license_info={"name": "AGPL-3.0-or-later", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
        **_api_meta,
    )

    # --- §LEGALKIT V0413: the API documentation loads nothing from a third party ---
    # FastAPI's stock /docs and /redoc pull Swagger UI and ReDoc from cdn.jsdelivr.net, their favicon from
    # fastapi.tiangolo.com and (ReDoc) fonts from fonts.googleapis.com: three third parties learning every
    # reader's address on a page the Privacy Policy describes as free of them (§ 5.1, § 8). The bundles are
    # vendored under the console's public/vendor and served by the /static mount of this origin.
    from fastapi.openapi.docs import get_redoc_html as _redoc_html, get_swagger_ui_html as _swagger_html

    @app.get("/docs", include_in_schema=False)
    async def _api_docs_page():
        return _swagger_html(
            openapi_url=f"{settings.API_V1_STR}/openapi.json", title=f"{app.title} - Swagger UI",
            swagger_js_url="/static/vendor/swagger-ui-bundle.js", swagger_css_url="/static/vendor/swagger-ui.css",
            swagger_favicon_url="/favicon.ico",
        )

    @app.get("/redoc", include_in_schema=False)
    async def _api_redoc_page():
        return _redoc_html(
            openapi_url=f"{settings.API_V1_STR}/openapi.json", title=f"{app.title} - ReDoc",
            redoc_js_url="/static/vendor/redoc.standalone.js", redoc_favicon_url="/favicon.ico", with_google_fonts=False,
        )

    # --- §pass52 PR-1: cluster-wide securitySchemes library + servers block ---
    # Declares all 7 runtime auth schemes for SDK generators (was 2 of 7).
    # See sessionlogs2026/swagger_audit_2026-05-16/04_CROSS_SERVICE_AUDIT.md X-P0-4.
    from fastapi.openapi.utils import get_openapi as _get_openapi
    _OPENAPI_SECURITY_SCHEMES = {
        "DeveloperJWT":      {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                              "description": "Developer JWT from POST /api/v1/auth/login"},
        "AgentJWT":          {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                              "description": "Agent JWT from POST /api/v1/auth/agent/token"},
        "AdminDeveloperJWT": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                              "description": "Developer JWT with is_admin=True"},
        "BootstrapToken":    {"type": "apiKey", "in": "header", "name": "Bootstrap-Token",
                              "description": "5-min one-shot token from /onboard/bootstrap/request-token"},
        "APIKey":            {"type": "http", "scheme": "bearer", "bearerFormat": "avreg_…",
                              "description": "Persistent API key for SDK / MCP bridges"},
        "mTLSPeer":          {"type": "mutualTLS",
                              "description": "SPIFFE-issued X.509 SVID; trust-domain pinned"},
        "FederationLicense": {"type": "apiKey", "in": "header", "name": "X-Federation-License",
                              "description": "Operator license, revocable"},
        # Lets Swagger's Authorize dialog take an email + password directly and keep the
        # resulting JWT, instead of only offering a paste-a-bearer-token box. /auth/login
        # already IS an OAuth2 password grant (it takes OAuth2PasswordRequestForm and
        # returns {access_token, token_type}) — this just declares that fact so the UI
        # can drive it. tokenUrl is RELATIVE so it resolves against whichever server the
        # user picked, never a hardcoded frame.
        "DeveloperLogin":    {"type": "oauth2",
                              "flows": {"password": {"tokenUrl": "api/v1/auth/login", "scopes": {}}},
                              "description": "Log in with your developer email + password. "
                                             "Swagger stores the JWT and sends it as Bearer."},
    }
    # ORDER MATTERS: the first entry is what Swagger's "Try it out" targets by default.
    # It MUST be the registry serving this page — every registry ships this same image,
    # so an absolute first entry pointed every operator's Swagger at Frame A and their
    # own credentials 401'd there. A relative "/" is correct on all 18 registries, on
    # cloud-ops (which have an EMPTY BASE_URL by design, §V0160) and on any frame a
    # third party stands up later, with no env var to set. (§OPGUIDE-5)
    # §DOCSFIX D6-062/D6-713: it is also the ONLY entry. The list went on to name the former network's hosts (Frame A,
    # frame-b, frame-c, the Hetzner frame, two sandboxes) as production registries in every registry's /docs; an
    # absolute entry here is someone else's address in everyone's documentation.
    _OPENAPI_SERVERS = [
        {"url": "/", "description": "This registry (the one serving these docs)"},
    ]

    def _rewrite_security_to_named_schemes(schema_in: dict) -> None:
        """§pass56 PR-1F — make the PR-1 securitySchemes library actually used.

        Without this, the 7 declared library schemes (DeveloperJWT, AdminDeveloperJWT,
        AgentJWT, etc.) are decorative: FastAPI auto-generates legacy 'OAuth2PasswordBearer'
        / 'HTTPBearer' / generic 'APIKeyHeader' scheme refs on each operation and SDK
        generators never see the tier hierarchy. We post-process here, rewriting
        per-operation security entries to point at named library schemes:
          /api/v1/admin/*                        → AdminDeveloperJWT
          an agent-token route (the dependency
          tree, core/auth_tiers.py, §FEFRAME W3) → AgentJWT
          an either-token route                  → DeveloperJWT OR AgentJWT
          (otherwise)                            → DeveloperJWT

        Named API-key scheme refs (APIKeyHeader, ServiceToken, etc.) are preserved.
        BootstrapToken / FederationLicense / mTLSPeer references are preserved.
        """
        # §FEFRAME W3 (V0504): the agent label comes from the dependency tree (core/auth_tiers.py), the same walk the
        # console's token choice is generated from. The hand list of path hints it replaces labelled 14 of 1,298
        # operations AgentJWT and missed POST /agora/orders and POST /agents/spawn. An operation that takes either
        # token (the read-actor resolvers) is labelled DeveloperJWT OR AgentJWT.
        try:
            from agentvault_registry.core import auth_tiers as _auth_tiers
            _op_tiers = _auth_tiers.operation_tiers(app)
        except Exception as _exc:  # noqa: BLE001 — the document is served either way; the labels say developer
            logger.warning("[openapi] the auth-tier walk failed (%s); every bearer operation reads DeveloperJWT",
                           _exc.__class__.__name__)
            _op_tiers = {}

        def _target_for_path(p: str, verb: str = "") -> str:
            if p.startswith("/api/v1/admin"):
                return "AdminDeveloperJWT"
            if _op_tiers.get((p, verb)) == "agent":
                return "AgentJWT"
            return "DeveloperJWT"

        # §pass58.5 — APIKeyHeader target: every Registry path that references this
        # auto-generated scheme is a federation/cross-frame mTLS endpoint:
        #   /federation/*, /admin/ironhand/*, /bridge/{mint-wrapped,unlock,confirm-lock}, /teg/cross-teg-balance-sync
        #   (§TWOAGENT V0437: /contracts/{id}/{accept,submit}-federated were retired to a 410 with no auth, so they
        #   carry no scheme and left this list)
        # All use get_federation_identity (SPIFFE X.509 SVID); the right named scheme is mTLSPeer.
        def _apikey_target_for_path(p: str) -> str:
            FED_PREFIXES = (
                "/api/v1/federation",
                "/api/v1/admin/ironhand",
                "/api/v1/bridge/mint-wrapped",
                "/api/v1/bridge/unlock",
                "/api/v1/bridge/confirm-lock",   # SEC-04: the target frame asks the source frame
                "/api/v1/teg/cross-teg",
            )
            if any(p.startswith(pfx) for pfx in FED_PREFIXES):
                return "mTLSPeer"
            # Fallback: FederationLicense (revocable apiKey scheme) for safety on any unexpected case
            return "FederationLicense"

        # §pass58.5 — split bearer-legacy from apikey-legacy so the mapping is type-correct.
        # Without this, ~32 APIKeyHeader endpoint refs (federation/bridge/ironhand mTLS surfaces)
        # are dangling — Swagger UI shows the route as "secured" but cannot resolve to a declared scheme.
        bearer_legacy_names = {"OAuth2PasswordBearer", "HTTPBearer"}
        apikey_legacy_names = {"APIKeyHeader"}
        legacy_names = bearer_legacy_names | apikey_legacy_names  # kept for back-compat (unused now)
        paths = schema_in.get("paths") or {}
        for p, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            apikey_target = _apikey_target_for_path(p)
            for verb, op in methods.items():
                if verb not in ("get", "post", "put", "patch", "delete"):
                    continue
                if not isinstance(op, dict):
                    continue
                target = _target_for_path(p, verb)
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
                            new_entry[target] = scopes or []
                            changed = True
                        elif sname in apikey_legacy_names:
                            new_entry[apikey_target] = scopes or []
                            changed = True
                        else:
                            new_entry[sname] = scopes
                    new_sec.append(new_entry)
                # Offer "log in with email + password" as an ALTERNATIVE to pasting a
                # bearer token on every developer/admin-tier route. A list of security
                # requirement objects is an OR in OpenAPI, so this widens what Swagger
                # can drive without changing what the server accepts — the runtime gate
                # is unchanged, it still just sees a Bearer JWT. Swagger only surfaces a
                # scheme in the Authorize dialog if some operation references it, which
                # is why declaring it in the library alone was not enough.
                if changed and target in ("DeveloperJWT", "AdminDeveloperJWT"):
                    if not any("DeveloperLogin" in e for e in new_sec if isinstance(e, dict)):
                        new_sec.append({"DeveloperLogin": []})
                if changed and _op_tiers.get((p, verb)) == "either":
                    if not any("AgentJWT" in e for e in new_sec if isinstance(e, dict)):
                        new_sec.append({"AgentJWT": []})
                if changed:
                    op["security"] = new_sec

        # Drop the legacy auto-generated schemes from components.securitySchemes —
        # they're no longer referenced (replaced by the named library above).
        comps = schema_in.setdefault("components", {})
        sec_schemes = comps.setdefault("securitySchemes", {})
        for ln in list(legacy_names):
            if ln in sec_schemes and ln not in _OPENAPI_SECURITY_SCHEMES:
                # Only drop if the LIBRARY doesn't also define a scheme by this
                # name (defensive — the library doesn't, but be careful).
                sec_schemes.pop(ln, None)

    def _documented_routes():
        """W3 (2026-10-25): the routes the registry's switches refuse are left out of the schema
        (core/staking_gate.route_documented); they still answer, with the switch's sentence, when called."""
        from .core.staking_gate import route_documented

        def calls(dependant):
            out, stack = [], list(getattr(dependant, "dependencies", []) or [])
            while stack:
                d = stack.pop()
                out.append(getattr(d, "call", None))
                stack.extend(getattr(d, "dependencies", []) or [])
            return out
        try:   # FastAPI 0.141 keeps included routers lazy: expand them the way get_openapi does, then filter
            from fastapi import routing as _fr
            from fastapi.openapi.utils import _get_api_route_for_openapi as _api_route
        except Exception:  # noqa: BLE001 — an older FastAPI flattens app.routes itself
            return [r for r in app.routes
                    if route_documented(getattr(r, "path", ""), calls(getattr(r, "dependant", None)))]
        kept = []
        for rc in _fr.iter_route_contexts(app.routes):
            r = _api_route(rc)
            if r is None or route_documented(getattr(r, "path_format", "") or getattr(r, "path", ""),
                                             calls(getattr(r, "dependant", None))):
                kept.append(rc)
        return kept

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        # §LEGALKIT V0413: the terms, the contact and the licence the app was built with (from the provider
        # facts). The literal contact block that used to sit below overwrote them on every frame, so V0412's
        # openapi.json named an engineering mailbox that is nobody's and carried no termsOfService at all.
        # The OpenAPI model validates the contact mailbox (special-use domains are refused): a frame whose facts
        # carry one still serves its documentation, without the contact, and says so once.
        _meta = dict(terms_of_service=app.terms_of_service, contact=app.contact, license_info=app.license_info)
        try:
            schema = _get_openapi(title=app.title, version=app.version, description=app.description,
                                  routes=_documented_routes(), servers=_OPENAPI_SERVERS, **_meta)
        except Exception as exc:  # pydantic ValidationError on info.contact.email, nothing else reaches here
            logger.warning("[openapi] the provider contact was refused by the OpenAPI validator (%s); "
                           "the documentation is served without it", exc.__class__.__name__)
            _meta["contact"] = None
            schema = _get_openapi(title=app.title, version=app.version, description=app.description,
                                  routes=_documented_routes(), servers=_OPENAPI_SERVERS, **_meta)
        schema.setdefault("components", {})["securitySchemes"] = _OPENAPI_SECURITY_SCHEMES
        # §pass56 PR-1F: make the library actually used (post-process rename)
        _rewrite_security_to_named_schemes(schema)
        # The contact and the licence come from the app metadata above (the facts); nothing is written here.
        schema.setdefault("info", {})
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    # --- §pass52 PR-12: /openapi.json redirect to the canonical versioned URL ---
    from fastapi.responses import RedirectResponse as _RedirectResponse
    @app.get("/openapi.json", include_in_schema=False)
    async def _openapi_root_redirect():
        return _RedirectResponse(url=f"{settings.API_V1_STR}/openapi.json", status_code=308)

    # --- SPA Cache Control Middleware ---
    # Prevent stale chunk errors: index.html must never be cached (it references
    # content-hashed asset filenames that change on every build). Hashed assets
    # under /assets/ are immutable and safe to cache forever.
    @app.middleware("http")
    async def spa_cache_control(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        ct = response.headers.get("content-type", "")
        if "text/html" in ct:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        elif path.startswith("/assets/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    # --- Admin Path Protection for Non-Admin Users ---
    # Non-admin users hitting /admin/ paths get a tight rate limit (10/min).
    # Uses Redis for cross-worker consistency (4 workers share one counter).
    _ADMIN_PATH_LIMIT = 10
    _ADMIN_PATH_WINDOW = 60  # seconds

    def _admin_throttled() -> Response:
        return Response(
            content='{"detail":"Admin endpoints rate limit exceeded. Try again later."}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": str(_ADMIN_PATH_WINDOW)}
        )

    def _admin_caller_verified(request: Request) -> bool:
        """D6-716: a caller whose credential verifies before the route runs. A JWT this registry signed and that has not
        expired (the route still decides what it may do), a peer certificate this frame's terminator vouched for
        (§MTLSHOPS G2), or the internal federation secret from inside this host (Mode 2's own terms). Never the mere
        presence of a header: a Bearer of any 21 characters, X-Federation-Secret or X-Federation-SPIFFE-ID used to
        exempt any caller that sent one.

        §SUITES1018 (2026-10-18): the tester key a console sends to the frame its tester targets (X-Internal-Key,
        core/api_test_proxy_key: no default, refused by shape, compared in constant time) verifies here too. The routes
        that accept it never told this throttle, so a sweep a console proxied here was counted per address AFTER it had
        run, beside the console's progress polls, and a flow that ended past ten calls in a window came back as 429
        (measured on V0623: the cloud-op sandboxdelta flow, about 65 s, refused on every run). The routes still decide
        what the key may do: only the tester's own routes accept it."""
        from agentvault_registry.core.mtls_auth import forwarded_cert_vouched as _forwarded_cert_vouched
        from agentvault_registry.core.federation_auth import internal_secret_verified as _internal_secret_verified
        from agentvault_registry.core.api_test_proxy_key import presented_key_ok as _tester_key_ok
        if _forwarded_cert_vouched(request.headers) or _internal_secret_verified(request):
            return True
        if _tester_key_ok(request.headers.get("X-Internal-Key")):
            return True
        auth = request.headers.get("Authorization", "")
        if auth[:7].lower() == "bearer ":
            token = auth[7:].strip()
            if token.count(".") == 2:
                import jwt as _pyjwt
                from agentvault_registry.security import SECRET_KEY as _SK, ALGORITHM as _ALG
                try:
                    _pyjwt.decode(token, _SK, algorithms=[_ALG])
                    return True
                except Exception:  # noqa: BLE001 - an unverifiable token is no exemption
                    return False
        return False

    @app.middleware("http")
    async def admin_path_throttle(request: Request, call_next):
        path = request.url.path
        if "/admin/" not in path:
            return await call_next(request)
        # The endpoint itself enforces admin-only; this throttle catches probing. D6-716: no request SHAPE exempts a
        # caller. A caller verified before the route runs passes (_admin_caller_verified, which keeps the federation
        # peers of Phase C1 passing: the federation_blocklist fanout arrives on vouched mTLS). Any other request is
        # counted per client address unless its route verified the credential (an API key: the verifiers stash
        # request.state.rl_principal), and an address past the limit gets 429. A request that carries no credential at
        # all is refused before the route once its address is past the limit.
        if _admin_caller_verified(request):
            return await call_next(request)
        from agentvault_registry.core.client_ip import effective_client_ip
        redis_key = f"admin_throttle:{effective_client_ip(request) or 'unknown'}"
        r = None
        try:
            from agentvault_registry.background_tasks.leader import get_redis
            r = await get_redis()
        except Exception:
            r = None  # Redis unavailable — degrade gracefully, allow request
        if r is not None and not (request.headers.get("Authorization") or request.headers.get("X-Api-Key")):
            try:
                if int(await r.get(redis_key) or 0) >= _ADMIN_PATH_LIMIT:
                    return _admin_throttled()
            except Exception:
                pass
        response = await call_next(request)
        if getattr(request.state, "rl_principal", None):
            return response  # the route verified the credential (an API key): never counted
        if r is not None:
            try:
                count = await r.incr(redis_key)
                if count == 1:
                    await r.expire(redis_key, _ADMIN_PATH_WINDOW)
                if count > _ADMIN_PATH_LIMIT:
                    return _admin_throttled()
            except Exception:
                pass  # Redis unavailable — degrade gracefully, allow request
        return response

    # --- Apply Rate Limiting Middleware ---
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    # §RATEFIX — classify the lane BEFORE SlowAPIMiddleware runs. Starlette
    # executes the LAST-added middleware first, so registering this after
    # SlowAPIMiddleware is what puts it outside (i.e. earlier). slowapi calls
    # its request filters with no arguments, so a ContextVar set here is the
    # only way the internal-lane exemption can see the request.
    app.middleware("http")(rate_limit_lane_middleware)
    logger.info("SlowAPI rate limiting middleware added (shared limiter, lane-aware).")
    
    # --- Add Admin API Key Middleware ---
    app.middleware("http")(admin_api_key_middleware)
    logger.info("Admin API key middleware added for rate limit exemptions.")
    
    # --- Add Metrics Collection Middleware ---
    app.add_middleware(MetricsCollectionMiddleware)
    logger.info("Metrics collection middleware added.")
    
    # --- Register Unified Error Handlers (POLISH-001) ---
    register_error_handlers(app)
    logger.info("Unified error handlers registered for consistent API error responses.")

    # --- Admission Control / Load-Shedding Middleware (2026-06-09) ---
    # Bounds concurrent HEAVY (mutating, cross-service) requests per worker and
    # sheds 503 instead of crash-looping under overload (incident 2026-06-09:
    # registry-a 782% CPU / health 000 under the fx/route-hop flood). Placed here
    # so it is INSIDE CORS (503s carry CORS headers) but OUTSIDE
    # MetricsCollectionMiddleware (rejects before its per-request JWT-decode).
    # Env-gated: REGISTRY_ADMISSION_ENABLED=false (default) => pure no-op.
    app.add_middleware(AdmissionControlMiddleware)
    logger.info("Admission-control middleware added.")

    # --- READONLY_MODE break-glass write freeze (§29, 2026-07-28) ---
    # Added AFTER admission control so it ends up OUTSIDE it: while frozen there is no reason to
    # spend an admission slot on a request that is about to be refused. Still inside CORS, so the
    # 503 carries CORS headers (same reasoning as admission control above).
    # READONLY_MODE=false (default) => a single boolean test per request, nothing else.
    app.add_middleware(ReadOnlyModeMiddleware)
    logger.info("Read-only-mode middleware added (READONLY_MODE=%s).",
                os.environ.get("READONLY_MODE", "false"))

    # --- A NUL in a request path or query string is refused, 400 (§MCPTEST30, 2026-10-01) ---
    # Postgres refuses a NUL in any text value, so a route that hands one to its SQL unchecked answered 500 (measured
    # with no login on /api/v1/discover and /api/v1/fiat/flare/agent/{did}). Added AFTER the read-only freeze so it
    # ends up OUTSIDE it, and still inside CORS, so the 400 carries CORS headers.
    app.add_middleware(NulRefusalMiddleware)

    # --- CORS Middleware ---
    # §FEFRAME W2 (2026-10-01): CORS FOLLOWS FEDERATION MEMBERSHIP, NEVER CREDENTIALS (core/federation_cors.py). The
    # allowlist is derived per worker, every CORS_REFRESH_SEC, from the frame manifest: this registry's own origins,
    # every origin ALLOWED_ORIGINS names (an addition, never a replacement) and the console + public origins of every
    # ACTIVE peer; allow_credentials is False (the API authenticates with bearer tokens, never cookies). Before W2 the
    # frames each carried a hand-kept list (EU could not be read from ASIA's console, nor the reverse) and every
    # operator ran the config default ["*"] WITH credentials. A wildcard stays an explicit choice
    # (CORS_ALLOW_ALL_ORIGINS=true, or ALLOWED_ORIGINS literally containing "*"), still without credentials.
    # settings.ALLOWED_ORIGINS is untouched: routers/liability.py reads it as the WebAuthn RP-ID candidate list.
    from agentvault_registry.core import federation_cors as _federation_cors
    logger.info(_federation_cors.install(app))

    # --- API Routers ---
    app.include_router(
        agent_cards.router,
        prefix=settings.API_V1_STR + "/agent-cards",
        tags=["Agent Cards"]
    )
    app.include_router(
        utils.router,
        prefix=settings.API_V1_STR + "/utils",
        tags=["Utilities"]
    )
    # Mount the enhanced auth_secure router - it has internal prefix="/auth"
    app.include_router(
        auth_secure.router,
        prefix=settings.API_V1_STR,
        tags=["Authentication"]
    )
    
    # Mount 2FA router
    app.include_router(
        auth_2fa.router,
        prefix=settings.API_V1_STR,
        tags=["Two-Factor Authentication"]
    )
    logger.info("2FA authentication endpoints mounted")
    # Mount OAuth federation router for cross-registry authentication
    if settings.OAUTH_TOKEN_EXCHANGE_ENABLED:
        app.include_router(
            oauth_federation.router,
            prefix=settings.API_V1_STR,
            tags=["OAuth Federation"]
        )
        logger.info("OAuth federation endpoints enabled for cross-registry authentication")
    
    # Mount organizations and teams router
    app.include_router(
        organizations.router,
        tags=["Organizations"]
    )
    logger.info("Organizations and teams management endpoints enabled")
    
    app.include_router(agents.router)  # Agent-specific endpoints - already has full prefix
    app.include_router(agent_authz_api.router, prefix=settings.API_V1_STR, tags=["Agent Authz"])  # IRONKEY
    app.include_router(agent_delegation_api.router, prefix=settings.API_V1_STR, tags=["Agent Delegation"])  # IRONKEY L3/L4
    app.include_router(forge.router, prefix=settings.API_V1_STR, tags=["GÖDEL FORGE"])  # self-improving-harness arena
    
    # Mount agent export/import endpoints
    app.include_router(
        agents_export_import.router,
        prefix=settings.API_V1_STR,
        tags=["Agent Export/Import"]
    )
    logger.info("Agent export/import endpoints enabled")
    app.include_router(developers.router, prefix=settings.API_V1_STR)
    # §LEGALKIT: the legal posture of this frame (public config, acceptance record) and the geocode relay.
    from agentvault_registry.routers import legal as _legal_router, geocode as _geocode_router
    app.include_router(_legal_router.router, prefix=settings.API_V1_STR)
    app.include_router(_geocode_router.router, prefix=settings.API_V1_STR)
    # §POCKETBRIDGE3: assistant panel seams (status + the flag-gated personal Claude bridge)
    app.include_router(assistant_router.router, prefix=settings.API_V1_STR)
    app.include_router(agent_builder.router, prefix=settings.API_V1_STR)
    # §pass68 — per-tool MCP audit log query endpoints (developer-scoped + admin self-watched)
    app.include_router(mcp_audit_log.router, prefix=settings.API_V1_STR)

    # OWL-22: Agent-own MCP server bundle generator (generate-template + templates list)
    app.include_router(agent_builder_templates.router, prefix=settings.API_V1_STR)
    logger.info("Agent builder templates endpoint enabled: POST /api/v1/agent-builder/generate-template")

    app.include_router(
        teg_integration.router,
        prefix="/api/v1",
        tags=["TEG Integration"]
    )
    # Federation routers
    app.include_router(federation_peers.router, prefix=settings.API_V1_STR)
    app.include_router(admin_federation.router, prefix=settings.API_V1_STR)
    app.include_router(federation_public.router, prefix=settings.API_V1_STR)  # Public federation endpoints
    app.include_router(federation_sync.router)  # Federation sync protocol endpoints
    app.include_router(federation_query.router)  # Internal federation query endpoints
    app.include_router(federation_topology.router, prefix=settings.API_V1_STR)  # WS1.5: tier-bucketed admin topology
    app.include_router(frame_invitations.router)  # f058 WS3: prefix built into router (/api/v1)
    app.include_router(public_reach_probe.router)  # §EXTREACH design A: POST /api/v1/public/reach-probe (REACH_PROBE_ENABLED)
    app.include_router(federation_licence.router)  # §FEDLICENCE: /.well-known + /api/v1 paths built into the router
    app.include_router(spire_jwks.router)  # Phase 12.1: SPIRE JWT-SVID JWKS endpoint
    # --- Registry Card v0.3 (2026-05-21) ---
    # Public well-known endpoints — NO prefix so they land at /.well-known/...
    # MUST register BEFORE any SPA catch-all (feedback_serve_well_known_card_pattern.md rule 3).
    app.include_router(registry_card.router)
    # Public status: /.well-known/security.txt (RFC 9116) + /api/v1/public/badge/supply
    # (shields.io Δ=0 badge). Unauthenticated, safe on every operator. Same pre-SPA rule.
    from agentvault_registry.routers import public_badge
    app.include_router(public_badge.router)
    # Federated Stock Card (AGORA catalog) — NO prefix; /.well-known/stock-card.json
    # + /api/v1/exchange/stock-card. Register before any SPA catch-all (same rule).
    app.include_router(stock_card.router)
    # AGORA Solvency Card (P4) — NO prefix; /.well-known/solvency-card.json
    # + /api/v1/exchange/solvency-card. Double-gated (EXCHANGE_ENABLED +
    # EXCHANGE_SOLVENCY_CARD_ENABLED). Register before any SPA catch-all.
    app.include_router(solvency_card.router)
    # Admin CRUD under /api/v1/admin/registry-card (router carries /admin prefix).
    app.include_router(admin_registry_card.router, prefix=settings.API_V1_STR)
    # --- END Registry Card v0.3 ---

    # §NIGHTLYPROV (his decision 2026-09-27): the four Frame-A-era provisioner tests (sandbox provisioner-lifecycle,
    # chained frame, dual frame, cross-registry transfer) and their ENABLE_SANDBOX_PROVISIONER_TEST gate are RETIRED,
    # never revived: they drove retired Frame-A hosts, bypassed the rails (psql writes, a direct TEG mint) and could
    # not pass template validation. Provisioning is tested nightly on a throwaway pair (scripts/nightly/).
    # Onboarding router
    app.include_router(onboarding.router, prefix=settings.API_V1_STR)
    # §pass66.8 (2026-05-23) — Public downloads (MCP stdio bridge JS files
    # for Claude Code / Desktop integration). Router carries its own
    # /api/v1/downloads prefix. Files copied into the image at /app/downloads/.
    from .routers import downloads as _downloads_router
    app.include_router(_downloads_router.router, tags=["Downloads"])
    # §pass66.9 (2026-05-23) — Operator portal actions (cloud-op-side proxy
    # endpoints that let an op admin restart their own stack via the
    # mainframe with their FEDERATION_LICENSE_KEY env). Cloud-ops only —
    # returns 503 on mainframes via internal gate.
    from .routers import operator_portal_actions as _op_portal_actions
    app.include_router(_op_portal_actions.router, tags=["Operator Portal Actions"])
    # PB-1 fiat onramp (Stripe Checkout → AVT). Mainframe-only at runtime via
    # FIAT_GENESIS_REGISTRY env. Master kill switch FIAT_ONRAMP_ENABLED=false.
    # Router carries its own /api/v1/fiat prefix.
    app.include_router(fiat_onramp.router, tags=["Fiat On-Ramp"])
    # PB-1 admin endpoints — pricing config + history + simulate. admin_treasury gated.
    app.include_router(fiat_onramp.admin_router, tags=["Fiat On-Ramp Admin"])
    # PB-2 (2026-05-10) — operator-side routed-settle callback receiver. Hosted
    # under /api/v1/federation/ so it traverses operator nginx-federation's
    # existing mTLS-terminated proxy (no new nginx config; HMAC inside).
    app.include_router(fiat_onramp.federation_router, tags=["Fiat On-Ramp Federation"])
    # §FLARESHOP (2026-08-16) — the SECOND origination lane for cosmetic flares:
    # paid in this frame's own currency instead of euros, so a registry with the
    # fiat onramp off can still distribute them. Byte-inert unless the operator
    # sets FLARE_LOCAL_PURCHASE_ENABLED=true (catalog reads as a gallery, the
    # purchase endpoint 503s). Router carries its own /api/v1/flare-shop prefix.
    from agentvault_registry.routers import flare_shop as _flare_shop
    app.include_router(_flare_shop.router)
    # W2 (2026-05-09) — User-initiated GDPR Art. 17 account deletion / anonymization.
    # Router carries its own /api/v1/account prefix. Caller-only auth — no admin gate.
    app.include_router(account_deletion.router, tags=["Account Deletion"])
    # Agent bundle download (ZIP generation for new agents)
    app.include_router(agent_bundle.router, prefix=settings.API_V1_STR)
    # §pass51 — Bundles feature: per-dev signing keys + JWKS endpoints + bundles API + admin moderation
    from agentvault_registry.routers import developers_signing
    from agentvault_registry.routers import bundles as bundles_router
    from agentvault_registry.routers import bundles_admin
    app.include_router(developers_signing.router, prefix=settings.API_V1_STR)
    # §pass63 follow-up (2026-05-22) — root-mounted (no prefix) well-known
    # JWKS endpoint so /.well-known/dev-jwks.json lives where verifiers expect
    # (not /api/v1/.well-known/dev-jwks.json).
    app.include_router(developers_signing.well_known_router)
    app.include_router(bundles_router.router, prefix=settings.API_V1_STR)
    app.include_router(bundles_admin.router, prefix=settings.API_V1_STR)
    # Admin router
    app.include_router(admin.router)
    # Attestations router + circuit distribution (ACIR/source for SDK agents)
    app.include_router(attestations.router)
    app.include_router(attestations.circuits_router)
    # Phase 1 ZKP maturation: public agent-profile augmentation
    app.include_router(attestations.attestations_by_agent_router)
    # Phase 4 ZKP maturation: public verify-bundle
    app.include_router(attestations.public_attestations_router)
    # Disputes router for DDR system
    app.include_router(disputes.router)
    # Replace existing staking router with enhanced version
    app.include_router(
        staking_enhanced.router,
        prefix=settings.API_V1_STR + "/staking",
        tags=["Locks"]
    )
    # Add staking rewards auto-distribution endpoints
    app.include_router(
        staking_rewards.router,
        tags=["Staking Rewards"]
    )
    # Agent CI/CD infrastructure endpoints
    # §pass52 PR-7: dropped tags= here — agent_cicd.py declares tags=["Agent CI/CD"]
    # on the APIRouter already; declaring on include_router too caused duplicate
    # tag arrays (R-NEW-1). Tag stays on APIRouter (single source of truth).
    app.include_router(
        agent_cicd.router,
        prefix=settings.API_V1_STR,
    )
    # Governance router for Agent Senate
    app.include_router(governance.router, prefix=settings.API_V1_STR + "/governance", tags=["Governance"])
    # THE CONTRACT SPINE (2026-07-25) — MUST register BEFORE the legacy contracts router: its
    # static /api/v1/contracts/v2/... segments would otherwise be swallowed by the legacy
    # /{contract_id} path param. Routes 503 while CONTRACTS_V2_ENABLED=false (guild pattern).
    from agentvault_registry.routers import contracts_v2 as contracts_v2_router
    app.include_router(contracts_v2_router.router)
    from agentvault_registry.routers import contract_templates as contract_templates_router
    app.include_router(contract_templates_router.router)
    from agentvault_registry.routers import liability as liability_router
    app.include_router(liability_router.router)  # COCKPIT CARD (dark unless LIABILITY_MODE≠off)
    # §COCKPITA R4 — the two desk<->agent channels. Mounted UNCONDITIONALLY and gated by
    # OWNERSHIP rather than by a flag: progress is an agent talking about itself, and
    # instruct already refuses anything that is not the caller's own active agent. The
    # router spells its own /api/v1 prefix (this app mounts routers with no prefix — the
    # mistake that cost a P8 debugging round when both probe and control returned 404).
    from agentvault_registry.routers import agent_channels as agent_channels_router
    app.include_router(agent_channels_router.router)
    from agentvault_registry.routers import push_login as push_login_router
    app.include_router(push_login_router.router)  # PUSH LOGIN (opt-in per developer)
    # Contracts router for Agent Workshop (LEGACY RUC surface — adapter over the spine since P2)
    # D8: retired behind a flag (default on; the fresh frame's template sets it off)
    from agentvault_registry.core.legacy_surfaces import surface_enabled as _surface_enabled
    if _surface_enabled("LEGACY_CONTRACTS_ENABLED"):
        app.include_router(contracts.router)
    else:
        logger.info("D8: legacy contracts surface NOT mounted (LEGACY_CONTRACTS_ENABLED=false)")
    # System router for activity feed and public information
    app.include_router(system.router, prefix=settings.API_V1_STR)
    # Reputation Signal router for transaction feedback
    app.include_router(reputation_signal.router, prefix=settings.API_V1_STR, tags=["Reputation"])
    
    # Mount enhanced disputes (keep original disputes too)
    app.include_router(
        disputes_enhanced.router,
        prefix=settings.API_V1_STR + "/disputes/enhanced",
        tags=["Disputes Enhanced"]
    )
    
    # Mount enhanced TEG summary under developers
    app.include_router(
        teg_summary_enhanced.router,
        prefix=settings.API_V1_STR + "/developers",
        tags=["Developers Enhanced"]
    )
    
    # TEG auth variants — unmounted (future work, all return 503)
    # app.include_router(teg_integration_jwt_svid.router, prefix=settings.API_V1_STR + "/teg-jwt-svid", tags=["TEG JWT-SVID"])
    # app.include_router(teg_integration_mtls.router, prefix=settings.API_V1_STR + "/teg-mtls", tags=["TEG mTLS"])
    # app.include_router(teg_integration_oauth.router, prefix=settings.API_V1_STR + "/teg-oauth", tags=["TEG OAuth"])
    
    # WebSocket router for real-time updates
    app.include_router(
        websocket.router,
        prefix=settings.API_V1_STR,
        tags=["WebSocket"]
    )
    
    # Metrics router for agent analytics
    app.include_router(
        metrics.router,
        prefix=settings.API_V1_STR,
        tags=["Metrics"]
    )
    
    # Agent logs router for log management
    app.include_router(
        agent_logs.router,
        prefix=settings.API_V1_STR,
        tags=["Agent Logs"]
    )
    
    # Agent discovery endpoints (no auth required for public discovery)
    app.include_router(
        agent_discovery.router,
        prefix=settings.API_V1_STR,
        tags=["Agent Discovery"]
    )
    # §AGENTDISC (2026-08-16) — public track-record attestation (registry-attested
    # guild work history + verifiable per-engagement receipts). Suffixed routes only
    # (/agents/{did:path}/track-record[...]) — no bare greedy /agents/{did} anywhere,
    # so nothing shadows and nothing is shadowed (checked routers/agents.py + here).
    app.include_router(
        track_record.router,
        prefix=settings.API_V1_STR,
        tags=["Agent Discovery"]
    )

    # Agent Evals (feature-gated EVALS_ENABLED; tables empty when off).
    from agentvault_registry.routers import evals as _evals, admin_evals as _admin_evals
    app.include_router(_evals.router, prefix=settings.API_V1_STR)
    app.include_router(_admin_evals.router, prefix=settings.API_V1_STR)

    # Internal sibling-service endpoints (TEG, EventStore on same docker network)
    from agentvault_registry.routers import internal_agents
    app.include_router(
        internal_agents.router,
        prefix=settings.API_V1_STR,
        tags=["Internal"],
    )

    # TEG advanced transaction endpoints
    app.include_router(
        teg_transactions.router,
        prefix=settings.API_V1_STR + "/teg",
        tags=["TEG Transactions"]
    )
    
    # Admin health monitoring endpoints (§pass58 PR-6b: admin_platform feature area)
    app.include_router(
        admin_health.router,
        prefix=settings.API_V1_STR,
        tags=["Admin — Platform"]
    )
    
    # Admin API testing endpoints (§pass58 PR-6b: feature-area tag)
    app.include_router(
        admin_api_test.router,
        prefix=settings.API_V1_STR,
        tags=["Admin — API Testing"]
    )

    # MCP Tester — Phase 5 + 6 frontend wrapper (sandbox-only sweep)
    try:
        from agentvault_registry.routers import mcp_tester
        app.include_router(
            mcp_tester.router,
            prefix=settings.API_V1_STR,
            tags=["Admin — MCP Tester"]
        )
    except Exception as _e:  # pragma: no cover — keep registry boot resilient
        logger.warning(f"mcp_tester router not loaded: {_e!r}")

    # §MCPTEST30 (V0555): the console suite's history, apart from the MCP tester's (its own cap; the runner records)
    from agentvault_registry.routers import console_suite
    app.include_router(console_suite.router, prefix=settings.API_V1_STR, tags=["Admin — Console Suite"])

    # Tutorial sandbox proxy (lightweight — separate from admin_api_test)
    app.include_router(
        admin_tutorial.router,
        prefix=settings.API_V1_STR,
        tags=["Tutorial"]
    )

    # Sandbox proxy — forwards requests to internal sandbox registries (for agent templates)
    app.include_router(
        sandbox_proxy.router,
        prefix=settings.API_V1_STR,
        tags=["Sandbox Proxy"]
    )
    logger.info("Sandbox proxy enabled: /api/v1/sandbox/a/*, /api/v1/sandbox/b/*")

    # Beta invite code management (admin-gated generate/list/revoke + public validate)
    app.include_router(
        admin_invite_codes.router,
        prefix=settings.API_V1_STR,
        tags=["Admin — Invite Codes"]
    )

    # EigenTrust simulation command center
    app.include_router(
        admin_simulation.router,
        prefix=settings.API_V1_STR,
        tags=["Admin — Simulation"]
    )

    # f034: Admin notification broadcast channel
    # §pass53 (PR-19): /api/v1 prefix now applied via include_router (was inline in
    # each @router.{method} decorator — R-NEW-4 from swagger audit refresh).
    # §NOTIFV2 — notification catalog + preference matrix (2026-07-26). MUST be registered
    # BEFORE admin_broadcast: that router owns /notifications/{broadcast_id} (int), and
    # FastAPI matches in registration order — registered after, /notifications/catalog is
    # swallowed by the int route and 422s (found live on the registry-a canary).
    from agentvault_registry.routers.notifications import router as notifications_router
    app.include_router(notifications_router)
    app.include_router(admin_broadcast.router, prefix=settings.API_V1_STR)
    # §RELEASECHANNEL (2026-09-21): the admin's view of the signed release channel and the rollout they schedule.
    from agentvault_registry.routers import admin_release_channel as _admin_release_channel
    app.include_router(_admin_release_channel.router, prefix=settings.API_V1_STR)
    logger.info("Admin broadcast endpoints enabled: /admin/broadcasts + /notifications/*")

    # Email template preview (admin-only) — renders any themed template with
    # sample context; useful for design iteration without spamming.
    from agentvault_registry.routers import admin_email_preview
    app.include_router(admin_email_preview.router, prefix=settings.API_V1_STR)
    # §FRAMEMAIL-5 — fleet mail console. 404s on any node that holds no mail
    # credentials, so it only exists where it can actually be acted on.
    from agentvault_registry.routers import admin_mail_fleet
    app.include_router(admin_mail_fleet.router, prefix=settings.API_V1_STR)
    logger.info("Admin email preview endpoints enabled: /admin/email/preview")

    # f042: Support ticket system
    app.include_router(support.router)
    logger.info("Support ticket endpoints enabled: /support/tickets + /admin/support/tickets")

    # AgentWorld geolocation API (public GET + developer PUT /me)
    from agentvault_registry.routers import agent_locations
    app.include_router(
        agent_locations.router,
        prefix=settings.API_V1_STR + "/agents/locations",
        tags=["AgentWorld"]
    )
    
    # f038: Achievement System
    from agentvault_registry.routers import achievements
    app.include_router(
        achievements.router,
        prefix=settings.API_V1_STR + "/achievements",
        tags=["Achievements"]
    )

    # OWL29: Sandbox self-reset (no auth middleware, uses secret header)
    app.include_router(
        admin_api_test.sandbox_internal_router,
        prefix=settings.API_V1_STR,
    )
    
    # Tokenomics proxy endpoints for TEG integration
    app.include_router(
        endpoints_tokenomics_proxy.router,
        prefix=settings.API_V1_STR,
        tags=["Units and Fees", "TEG Integration"]
    )
    
    # OWL25: Federation dispute settlement (cross-registry slash + mint)
    app.include_router(federation_disputes.router)
    logger.info("Federation dispute settlement endpoints enabled")
    
    # TITANIUM VAULT D2: Enforcement admin endpoints
    app.include_router(enforcement_admin.router)
    logger.info("Enforcement admin endpoints enabled")

    # M1 2026-04-20: Admin developer management (list/detail/suspend/reset/delete)
    from agentvault_registry.routers import admin_developers
    app.include_router(admin_developers.router)
    logger.info("Admin developer management endpoints enabled at /api/v1/admin/developers/*")

    # M2 2026-04-20: Admin agent management (list/detail/orphans/transfer/rotate/delete/bulk-suspend)
    from agentvault_registry.routers import admin_agents
    app.include_router(admin_agents.router)

    # Canary system admin (Phase 8 — 2026-05-04)
    from agentvault_registry.routers import admin_canary
    app.include_router(admin_canary.router, prefix=settings.API_V1_STR)

    # §pass26 (2026-05-17) — cross-TEG 2PC sweeper observability
    from agentvault_registry.routers import cross_teg_sweeper_admin
    app.include_router(cross_teg_sweeper_admin.router, prefix=settings.API_V1_STR)

    # §pass27 Phase 1 (2026-05-17) — canary_judge Tier-3 modal feed
    # Lives alongside legacy /admin/canary/* (admin_canary.router) which still
    # backs AdminCanaries.vue; this one is consumed by CanaryJudgeModal.vue.
    from agentvault_registry.routers import canary_judge_admin
    app.include_router(canary_judge_admin.router, prefix=settings.API_V1_STR)

    # §pass27 Phase 2 (2026-05-17) — canary_rebalancer Tier-3 modal feed
    from agentvault_registry.routers import canary_rebalancer_admin
    app.include_router(canary_rebalancer_admin.router, prefix=settings.API_V1_STR)

    # §pass27 Phase 3 (2026-05-17) — saga_timeout_checker Tier-3 modal feed
    # Aggregates BOTH registry-a and frame-b-registry via Prom registry_id label.
    from agentvault_registry.routers import saga_timeout_admin
    app.include_router(saga_timeout_admin.router, prefix=settings.API_V1_STR)

    # §pass36 Phase 3 (2026-05-17) — agent_card_pullsync Tier-3 modal feed
    # Pull-sync of native agents' /.well-known/agent-card.json on a 6h cadence.
    from agentvault_registry.routers import agent_card_pullsync_admin
    app.include_router(agent_card_pullsync_admin.router, prefix=settings.API_V1_STR)

    # §pass36 Phase 6 (2026-05-17) — agent-card drift admin surface
    # GET/POST /admin/agent-card-drift/* for side-by-side diff + force-pull +
    # operator drift flagging. Companion to pull-sync (Phase 3).
    from agentvault_registry.routers import agent_card_drift_admin
    app.include_router(agent_card_drift_admin.router, prefix=settings.API_V1_STR)

    # §pass36 Phase 9.a (2026-05-17) — agent signing-key rotation admin.
    # POST /admin/agents/{did}/rotate-signing-key + GET signing-keys history.
    from agentvault_registry.routers import agent_signing_keys_admin
    app.include_router(agent_signing_keys_admin.router, prefix=settings.API_V1_STR)

    # §pass49 B1 (2026-05-19) — agent_flags admin endpoints
    from agentvault_registry.routers import agent_flags_admin
    app.include_router(agent_flags_admin.router, prefix=settings.API_V1_STR)

    # §pass49 — admin fleet CI/CD + audit log endpoints
    from agentvault_registry.routers import admin_cicd
    app.include_router(admin_cicd.router, prefix=settings.API_V1_STR)

    # §pass28 Phase 4 (2026-05-17) — supply_auditor Tier-3 modal feed
    # Wraps EventStore /projections/supply-audit with worker-cycle context +
    # per-registry breakdown via Prom registry_id label.
    from agentvault_registry.routers import supply_auditor_admin
    app.include_router(supply_auditor_admin.router, prefix=settings.API_V1_STR)

    # Galactic Command Center (2026-06-10, GCC Phase 1) — canonical registry
    # directory + credential-free fleet health probes for the map cockpit.
    from agentvault_registry.routers import admin_command
    app.include_router(admin_command.router, prefix=settings.API_V1_STR)

    # Balance Reconcile (2026-06-18) — multi-op-aware ES↔TEG drift legs for the GCC.
    # /local = this op's TEG balances; /es-balances = this frame's ES aggregate.
    # The GCC sums an agent's balance across a frame's op TEGs (multi-op aware) vs ES.
    # Depends on TEG primitive GET /api/v1/admin/all-agent-balances.
    from agentvault_registry.routers import balance_reconcile
    app.include_router(balance_reconcile.router, prefix=settings.API_V1_STR)

    # §pass28 Phase 5 (2026-05-17) — collusion_worker Tier-3 modal feed
    # Surfaces AuditorFlagLog CollusionRingDetected rows + 24h cadence stats.
    from agentvault_registry.routers import collusion_admin
    app.include_router(collusion_admin.router, prefix=settings.API_V1_STR)

    # §pass29 Phase 6 (2026-05-17) — federation_sync Tier-3 modal feed
    # Surfaces per-peer freshness + cycle health + 3 new Prom metrics
    # (cycle/attempts/errors) on top of the 4 pre-existing federation gauges.
    from agentvault_registry.routers import federation_sync_admin
    app.include_router(federation_sync_admin.router, prefix=settings.API_V1_STR)

    # §pass29 Phase 7 (2026-05-17) — agent_health_checker Tier-3 modal feed
    # Surfaces probe history + transition matrix + currently-down agents.
    from agentvault_registry.routers import agent_health_admin
    app.include_router(agent_health_admin.router, prefix=settings.API_V1_STR)
    # §STATUSPAGE (2026-09-02) — the public status page's rail + the curated incident list (admin).
    from agentvault_registry.routers import public_status
    from agentvault_registry.routers import public_fresh_network  # §BATCH7
    app.include_router(public_status.router, prefix=settings.API_V1_STR)
    app.include_router(public_fresh_network.router)  # §BATCH7: the fresh network on the landing page
    # §MTLSGAP (2026-09-08) — the federated index, read THROUGH this registry over mTLS. The console
    # used to reach it via a hand-added `/directory/` proxy on the host vhost (plain http on
    # loopback, no identity either end); addressing it here means the vhost needs no Directory lane
    # at all, which is one fewer thing a clean standup can silently drop (§FRAMELIC).
    from agentvault_registry.routers import public_directory  # §MTLSGAP
    app.include_router(public_directory.router)

    # §pass30 (2026-05-17) — canary IRONHAND mTLS Tier-3 modal feed (Pattern A)
    # Surfaces per-path mTLS canary stats + failure breakdown + SPIRE crossref.
    from agentvault_registry.routers import canary_ironhand_admin
    app.include_router(canary_ironhand_admin.router, prefix=settings.API_V1_STR)
    logger.info("Canary admin endpoints mounted at /admin/canary/*")
    logger.info("Admin agent management endpoints enabled at /api/v1/admin/agents/*")

    # TITANIUM VAULT D2: Enforcement agent self-service endpoints
    app.include_router(enforcement_agent.router)
    app.include_router(reputation_bond.router)
    # §MEMBERSHIP (2026-10-02): membership derived from the bond (reads only; services/membership.py)
    from agentvault_registry.routers import membership as _membership_router
    app.include_router(_membership_router.router)
    # §MEMBERSHIP phase B (2026-10-02): the commons, behind COMMONS_ENABLED (services/commons.py)
    from agentvault_registry.routers import commons as _commons_router
    app.include_router(_commons_router.router)
    # §MEMBERSHIP phase D2 (2026-10-02): federal ballots, one per registry (services/federation_ballot.py)
    from agentvault_registry.routers import federation_ballots as _federation_ballots_router
    app.include_router(_federation_ballots_router.router)
    logger.info("Enforcement agent endpoints enabled")

    # ANP (Agent Network Protocol) discovery endpoints
    from agentvault_registry.routers import anp_discovery
    app.include_router(
        anp_discovery.router,
        prefix=settings.API_V1_STR,
        tags=["ANP Discovery"],
    )
    app.include_router(
        anp_discovery.well_known_router,
        tags=["ANP Discovery"],
    )
    logger.info("ANP discovery endpoints enabled: /agents/{did}/did.json, /agents/{did}/ad.json, /.well-known/agent-descriptions")

    # EigenTrust++ Phase 2: Reputation trust graph endpoints
    app.include_router(reputation_trust.router)
    logger.info("EigenTrust++ reputation endpoints enabled at /api/v1/reputation")

    # Phase 1 Federation: Policy admission pipeline + Registry health profiles
    app.include_router(federation_admission.router)
    logger.info("Federation admission endpoints enabled at /api/v1/admin/federation/*")
    app.include_router(registry_health.router)
    logger.info("Registry health endpoints enabled at /api/v1/federation/*")

    # CONSUL — Federation compliance monitoring dashboard (2026-04-19)
    from agentvault_registry.routers import consul_admin
    app.include_router(consul_admin.router)
    logger.info(
        "CONSUL compliance admin endpoints enabled at "
        "/api/v1/admin/federation/compliance/*"
    )

    # f043: Federation License Key System
    app.include_router(federation_licenses.router)
    logger.info("Federation license endpoints enabled at /api/v1/admin/federation/licenses/*")

    # BL-1 (2026-05-11): Self-serve license rotation (federation-license-auth)
    app.include_router(federation_license_self.router)
    logger.info("Federation license self-serve rotation enabled at /api/v1/federation/license/rotate-self")

    # BL-1 P8 (2026-05-11): CLI audit event receiver (Q7-approved)
    app.include_router(federation_cli_audit.router)
    logger.info("Federation CLI audit event receiver enabled at /api/v1/federation/cli-audit")

    # Phase 10 #4: Cross-frame agent blocklist proxy (peer registries call us
    # over Mode 2 federation auth; we proxy to local TEG with our own admin key)
    app.include_router(federation_blocklist.router)
    # §2026-06-14: Cross-frame operator-rename apply (event-sourced). Peers POST
    # here over Mode-2 federation auth; each applies the rename to its own rows.
    app.include_router(federation_operator_rename.router)
    logger.info(
        "Federation blocklist proxy enabled at /api/v1/federation/admin/agents/{did}/{block,unblock}"
    )

    # Operator application form (landing page)
    app.include_router(operator_applications.router)
    app.include_router(operator_lifecycle.router, prefix=settings.API_V1_STR)
    logger.info("Operator application endpoint enabled at /api/v1/operator-applications")

    # f051: Cloud-hosted operator admin endpoints
    from agentvault_registry.routers import cloud_operators
    app.include_router(cloud_operators.router)
    app.include_router(cloud_operators.federation_router)   # §OPLANE: the same self-service on the federation lane
    logger.info("Cloud operator admin endpoints enabled at /api/v1/admin/cloud-operators/* (+ /api/v1/federation/operator-self/*)")

    # §FRAMEPROV P3 (2026-09-13): a frame is stood up by the HOST frame runner (a root service on a unix socket,
    # tools/frame-runner/ in the stack repo), never from this process; this router passes admin_platform acts to it
    # (mainframe-only). The nsenter launcher of 2026-07-27 is retired. Carries its own full prefix.
    from agentvault_registry.routers import frame_runner_admin
    app.include_router(frame_runner_admin.router)
    logger.info("Frame runner admin endpoints enabled at /api/v1/admin/frame-runner/*")

    # §TESTBED (2026-09-19): the MCP tester view provisions this frame's sandbox through the same runner, on the operator
    # socket a kit frame mounts (the runner offers it only where its policy says so, and acts for the calling frame only).
    from agentvault_registry.routers import mcp_tester_sandbox
    app.include_router(mcp_tester_sandbox.router)

    # §FRAMEFORM (2026-09-04): the admin review of the public frame request (the public POST is
    # routers/operator_self_service.py's /operators/request-frame); mainframe-only, carries its own /api/v1 prefix.
    # 2026-09-13 (V0363): imported directly. The §BATCH6 guard that let a checkout without this then-untracked file
    # boot also let every clean image ship WITHOUT the router for nine days (Frame Management's request list answered
    # 404 on every frame, one WARNING line per worker); a missing router now fails the boot-import gate instead.
    from agentvault_registry.routers import frame_requests
    app.include_router(frame_requests.router)
    logger.info("Frame request review enabled at /api/v1/admin/frame-requests/*")
    # §HELLOFRAME (2026-09-19): the applicant's frame page and the frame kit download; every route answers 404 unless
    # FRAME_KIT_ENABLED is true (off by default), mainframe-only like the request review above.
    from agentvault_registry.routers import frame_kit
    app.include_router(frame_kit.router)

    # PB-1 §67 (2026-05-11): Operator self-service — flare-gated cloud-op
    # provisioning. GET /me/provisioning-eligibility + POST /operators/self-provision.
    # Mainframe-only at runtime (FIAT_GENESIS_REGISTRY=true gate inside the router).
    from agentvault_registry.routers import operator_self_service
    app.include_router(operator_self_service.router)
    logger.info(
        "Operator self-service endpoints enabled at /api/v1/me/provisioning-eligibility "
        "+ /api/v1/operators/self-provision (mainframe-only)"
    )

    # f052: Agent mTLS enrollment + monitoring endpoints (IRONHAND)
    from agentvault_registry.routers import agent_mtls
    app.include_router(agent_mtls.router)
    app.include_router(agent_mtls.admin_router)
    app.include_router(agent_mtls.federation_router)   # §OPLANE: the operator proxies on the federation lane
    logger.info("IRONHAND endpoints enabled: /api/v1/agent/*, /api/v1/admin/ironhand/* (+ /api/v1/federation/ironhand/*)")

    # SF-3: Token Bridge (cross-frame wrapped token transfers)
    from agentvault_registry.routers import token_bridge
    if _surface_enabled("TOKEN_BRIDGE_ENABLED"):  # D8
        app.include_router(token_bridge.router)
        logger.info("Token Bridge enabled: /api/v1/bridge/*")
    else:
        logger.info("D8: token bridge NOT mounted (TOKEN_BRIDGE_ENABLED=false)")

    # Command Center diagnostics (admin-only)
    from agentvault_registry.routers import admin_diagnostics
    app.include_router(admin_diagnostics.router)
    logger.info("Command Center enabled at /api/v1/admin/diagnostics/*")

    # §29 OPA policy console (admin-only). Read-only + a simulate endpoint; cannot change
    # enforcement. Distinct /opa prefix, so no path-swallowing risk (§NOTIFV2: FastAPI
    # registration order beats path specificity).
    from agentvault_registry.routers import admin_opa
    app.include_router(admin_opa.router)
    logger.info("OPA policy console enabled at /api/v1/admin/opa/*")

    # Jurisdiction Profiles v1 (SPEC 2026-07-31): admin declaration API. Distinct
    # /jurisdiction-profile prefix, no path-swallowing risk. Gates are downstream
    # in services/jurisdiction.py and byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.routers import admin_jurisdiction
    app.include_router(admin_jurisdiction.router)
    # REGAUTH (SPEC 2026-08-15): public read-only proof surface for recorded
    # regulatory authorizations — the same LIVE set the signed card publishes.
    app.include_router(admin_jurisdiction.public_router)
    logger.info("Jurisdiction profile API enabled at /api/v1/admin/jurisdiction-profile (mode=%s)", settings.JURISDICTION_MODE)

    # f050: Docker Registry v2 Token Auth
    from agentvault_registry.routers import docker_token_auth
    app.include_router(docker_token_auth.router)
    docker_token_auth.load_signing_key()
    logger.info("Docker Registry token auth enabled at /api/v1/docker-registry/token")

    # MCP Server — mount at /mcp (last, after all API routes)
    app.include_router(mcp_router, prefix="/mcp")
    logger.info("TheProtocol MCP Server enabled at /mcp (14 tools, JSON-RPC 2.0)")
    
    # MCP Admin Server — mount at /mcp/admin (Commander-only, 3 tools)
    app.include_router(admin_mcp_router, prefix="/mcp/admin")
    logger.info("TheProtocol MCP Admin Server enabled at /mcp/admin (3 tools, admin JWT required)")

    # MCP OAuth 2.0 — Claude Custom Connector support
    app.include_router(mcp_oauth_router)
    logger.info("MCP OAuth 2.0 enabled (/.well-known/oauth-authorization-server, /oauth/*)")

    # Beta Access Request system — DEPRECATED
    # app.include_router(beta_access_router)
    app.include_router(webhooks_router)
    # §MCPTEST30 V0637: the sandbox's webhook receiver for its own tests, mounted only behind its positive flag
    # (SANDBOX_WEBHOOK_SINK_ENABLED); off, the path stays an unknown route
    from agentvault_registry.routers import sandbox_webhook_sink
    if sandbox_webhook_sink.mount(app):
        logger.info("Sandbox webhook sink mounted at /api/v1/sandbox/webhook-sink/{webhook_id}")

    # AVT Funding Request system (f041)
    app.include_router(funding_agent_router)
    app.include_router(funding_admin_router)
    app.include_router(a2a_payment_router)
    app.include_router(teg_send_router)
    logger.info("AVT Funding Request system enabled (/api/v1/funding/*, /api/v1/admin/funding/*) + TEG smart send (/api/v1/teg/send)")

    # Robo Wars Arena — MCP server + spectator API
    app.include_router(arena_mcp_router, prefix="/mcp/arena")
    app.include_router(arena_spectator_router)
    app.include_router(td_mcp_router, prefix="/mcp/td")
    app.include_router(snake_mcp_router, prefix="/mcp/snake")
    app.include_router(trading_mcp_router, prefix="/mcp/trading")
    app.include_router(lobby_mcp_router, prefix="/mcp/lobby")
    logger.info("Game Arena enabled: /mcp/arena (12) + /mcp/td (10) + /mcp/snake (6) + /mcp/trading (11) + /mcp/lobby (5)")

    # §pass63 (2026-05-22) — Astraeus router mounts removed entirely.

    # AGORA (2026-06-12): the organization market. Routes always mounted
    # (reads work everywhere); money paths self-gate on EXCHANGE_ENABLED.
    # §AGORAWORDS (V0419): mounted TWICE. /api/v1/agora is the documented name (in the schema);
    # /api/v1/exchange stays live and hidden, because a roll mixes versions for hours and every
    # cross-frame caller (FE home-registry routing, the passport, the venue probe, MCP, the sim,
    # the directory, the SDK) keeps the old paths until every frame runs V0419 or newer.
    app.include_router(exchange_router, prefix="/api/v1/agora")
    from agentvault_registry.mcp.tool_aliases import count_legacy as _count_legacy
    async def _count_legacy_agora_http() -> None:
        _count_legacy("http")   # agora_legacy_name_total{kind="http"}: the instrument for dropping this mount later
    app.include_router(exchange_router, prefix="/api/v1/exchange", include_in_schema=False,
                       dependencies=[Depends(_count_legacy_agora_http)])
    logger.info("AGORA router mounted (/api/v1/agora/* + legacy /api/v1/exchange/*; venue gate EXCHANGE_ENABLED=%s)",
                os.getenv("EXCHANGE_ENABLED", "false"))

    # AGORA Passport (§9): DevCard home-side serve + venue federation endpoints.
    app.include_router(dev_card_router)
    app.include_router(dev_card_dev_router)
    app.include_router(exchange_federation_router)
    app.include_router(contract_federation_router)
    app.include_router(federation_operator_purge_router)
    # §FRAMEMAIL-4 — parent-side mail relay so a node holding no SMTP token can
    # still send verification mail. 503s for everyone unless MAIL_RELAY_ENABLED.
    app.include_router(mail_relay_router)
    # POCKET FRAME — device push registration (f-mobile, 2026-07-07)
    from agentvault_registry.routers.device_push import router as device_push_router
    app.include_router(device_push_router)
    # PHONE FABRIC — capability-gated agent computer-use (2026-07-07; PHONE_FABRIC_ENABLED gate)
    from agentvault_registry.routers.phone_fabric import router as phone_fabric_router
    app.include_router(phone_fabric_router)
    # THE GUILD — agent work exchange (2026-07-07; GUILD_ENABLED gate)
    from agentvault_registry.routers.guild import router as guild_router
    app.include_router(guild_router)

    # §OURSTATE-1 — OurChat chat (2026-08-24; mig 0155_chat_core). Dual-auth,
    # no money code: economic acts are typed cards over EXISTING rails.
    from agentvault_registry.routers.chat import router as chat_router
    app.include_router(chat_router)
    # §OURSTATE-3b — the peer-facing relay (mTLS/license/secret authenticated).
    from agentvault_registry.routers.chat_federation import router as chat_fed_router
    app.include_router(chat_fed_router)
    logger.info("AGORA Passport routers mounted (dev-card + agora-order; EXCHANGE_PASSPORT_ENABLED=%s)",
                os.getenv("EXCHANGE_PASSPORT_ENABLED", "false"))

    logger.info("Included API routers.")

    # Public EventStore stats proxy — no auth, used by Mission Control live ledger
    # Cached for 30s to avoid hammering slow projection queries under sim load
    # §BRIDGE — 30s cache for the public supply-invariant seal.
    _supply_inv_cache: dict = {"v": None, "ts": 0.0}
    _es_stats_cache: dict = {"a": None, "a_ts": 0.0}

    def _es_cache_put(slot: str, fresh: dict) -> dict:
        """Cache a fresh ES stats payload, but NEVER let an empty event_counts
        overwrite a previously-populated one — EventStore runs N uvicorn workers and,
        until the Redis-shared event_counts converges, a non-leader worker can answer
        {}. Also: don't latch an empty event_counts for the full 30s — leave it stale
        (ts=0) so the next request re-fetches and self-heals within seconds."""
        import time as _t
        prior = _es_stats_cache.get(slot)
        fresh = dict(fresh or {})
        if not fresh.get("event_counts") and prior and prior.get("event_counts"):
            fresh["event_counts"] = prior["event_counts"]
        _es_stats_cache[slot] = fresh
        _es_stats_cache[slot + "_ts"] = _t.time() if fresh.get("event_counts") else 0.0
        return fresh

    def _es_verify_for(url: str):
        """TLS verify mode by ES host: internal SPIRE-mTLS endpoints
        (…-nginx-event-store:8443) use the SPIRE context; public
        events-*.theprotocol.cloud (Let's Encrypt) use the system CA bundle (True).
        This lets ANY node — including mainframes that can't network-reach a peer
        frame's INTERNAL ES (separate docker nets) — read cross-frame ledger stats
        over the public events-* host. So cross-frame columns are wired to the
        public URL; a node's OWN frame keeps its internal mTLS URL."""
        return get_httpx_verify() if "nginx-event-store" in (url or "") else True

    @app.get("/api/v1/public/eventstore-stats", tags=["Public"])
    async def public_eventstore_stats():
        """Public proxy for EventStore projection stats (Mission Control)."""
        import httpx as _httpx
        import os as _os
        import time as _time
        if _es_stats_cache["a"] and _time.time() - _es_stats_cache["a_ts"] < 30:
            return _es_stats_cache["a"]
        # EVENT_STORE_A_URL lets a non-frame-A node point its "Frame A" column at the
        # real frame-a ES (public events host); default = this node's own ES.
        event_store_url = _os.getenv("EVENT_STORE_A_URL") or settings.EVENT_STORE_URL
        internal_key = _os.getenv("EVENT_STORE_A_API_KEY") or settings.EVENT_STORE_API_KEY
        try:
            async with _httpx.AsyncClient(timeout=5.0, verify=_es_verify_for(event_store_url)) as client:
                response = await client.get(
                    f"{event_store_url}/api/v1/projections/stats",
                    headers={"X-Internal-Key": internal_key},
                )
                if response.status_code == 200:
                    return _es_cache_put("a", response.json())
        except Exception:
            pass
        if _es_stats_cache["a"]:
            return _es_stats_cache["a"]
        return {"total_events": 0, "unique_agents": 0, "event_counts": {}}

    _es_peer_stats_cache: dict = {}

    @app.get("/api/v1/public/eventstore-stats/{key}", tags=["Public"])
    async def public_eventstore_stats_for(key: str):
        """§FEFRAME W2 (2026-10-01) — one frame's ledger stats, by the frame manifest's key (never a letter).

        This registry's own key (or `local`) reads its own store, as `/eventstore-stats` always did. A peer FRAME's
        key reads that frame's OWN public stats endpoint on its public origin (core/federation_view.py), server-side:
        no EVENT_STORE_B_URL, no peer store key, no CORS. An operator's key answers its parent frame's ledger (an
        operator has no store). An unknown key is a 404, never another frame's numbers. The retired frames' `-b`/`-c`
        aliases are gone since V0509 (§FEFRAME W4)."""
        import httpx as _httpx
        import time as _time
        from agentvault_registry.core import federation_view as _fv
        k = (key or "").strip().lower()
        _m = await _fv.manifest_now()
        me = (_m or {}).get("self") or {}
        if k in ("local", me.get("key")):
            return await public_eventstore_stats()
        peers = {p.get("key"): p for p in ((_m or {}).get("peers") or [])}
        e = peers.get(k)
        if e is not None and e.get("role") == "operator":
            e = peers.get(e.get("parent")) if e.get("parent") != me.get("key") else None
            if e is None:
                return await public_eventstore_stats()      # an operator of THIS frame: this frame's ledger
        if e is None or not e.get("public_url"):
            raise HTTPException(status_code=404, detail=f"no frame '{k}' in this registry's federation")
        hit = _es_peer_stats_cache.get(e["key"])
        if hit and _time.time() - hit["ts"] < 30:
            return hit["data"]
        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{e['public_url']}/api/v1/public/eventstore-stats", follow_redirects=False)
            d = r.json() if r.status_code == 200 else None
            if isinstance(d, dict) and "event_counts" in d:
                _es_peer_stats_cache[e["key"]] = {"ts": _time.time(), "data": d}
                return d
        except Exception:
            pass
        if hit:
            return hit["data"]
        return {"total_events": 0, "unique_agents": 0, "event_counts": {}, "unreachable": True}

    @app.get("/api/v1/public/supply-invariant", tags=["Public"])
    async def public_supply_invariant():
        """This node's OWN supply invariant. Public, read-only, no secrets.

        §BRIDGE 2026-08-18 — the delta is the prime directive of the whole
        system, and until now the only way to see it in the app was an ADMIN
        endpoint (`/admin/command/auditor-latest`). Mission Control shows it to
        every logged-in developer as a standing seal, so it needs a public read.

        Returns ONLY the invariant fields, never balances or account detail:
          {delta, status, net_supply, total_circulating, checked_at, source}

        Honest failure: if the EventStore cannot be reached the response says
        `status: "UNKNOWN"` with a null delta. A seal that cannot verify must
        say so rather than show a comforting zero.
        """
        import httpx as _httpx
        import time as _time
        import datetime as _dt
        _now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
        cached = _supply_inv_cache.get("v")
        if cached and _time.time() - _supply_inv_cache.get("ts", 0) < 30:
            return cached
        try:
            async with _httpx.AsyncClient(
                timeout=5.0, verify=_es_verify_for(settings.EVENT_STORE_URL)
            ) as client:
                r = await client.get(
                    f"{settings.EVENT_STORE_URL}/api/v1/projections/supply-audit",
                    headers={"X-Internal-Key": settings.EVENT_STORE_API_KEY},
                )
                if r.status_code == 200:
                    d = r.json() or {}
                    out = {
                        "delta": d.get("delta"),
                        "status": d.get("status") or "UNKNOWN",
                        "net_supply": d.get("net_supply"),
                        "total_circulating": d.get("total_circulating"),
                        "checked_at": _now_iso,
                        "source": "eventstore",
                    }
                    _supply_inv_cache["v"] = out
                    _supply_inv_cache["ts"] = _time.time()
                    return out
        except Exception:
            pass
        return {
            "delta": None, "status": "UNKNOWN", "net_supply": None,
            "total_circulating": None, "checked_at": _now_iso, "source": "unreachable",
        }

    # §FEFRAME W4 (V0509): the retired frames' aliases /api/v1/public/eventstore-stats-b and -c are gone. They read
    # EVENT_STORE_B_URL / EVENT_STORE_C_URL (set on no live registry, so every call logged a warning and answered zeros),
    # the console stopped reading them in V0503 (each frame's stats come from the keyed stats route by manifest key), and their
    # MCP tool left in V0508.

    @app.get("/api/v1/public/eventstore-recent", tags=["Public"])
    async def public_eventstore_recent(limit: int = 60):
        """
        This FRAME's most recent events, newest first. O(1).

        §BRIDGE R7 (2026-08-19) — approved by the Commander as a public endpoint.
        Read the shape carefully, because the shape IS the design:

        * It serves a bounded RING held in Redis, written once per emitted event.
          One list, one copy, shared by every client and every gunicorn worker —
          so a hundred browsers cost the EventStore nothing and this endpoint one
          `LRANGE`. That is the whole scale story, and it is why the fan-in lives
          on the registry instead of in each client.
        * It is THIS FRAME'S OWN EventStore, and nothing else. The ring is fed by
          `background_tasks/recent_events_ring`, which listens to the local
          EventStore's existing Redis broadcast — so it carries everything stored
          on this frame, whoever emitted it, not just what the registry itself
          emitted. That distinction is the point: measured on frame-c over 20
          minutes, the TEG balance outbox emitted 813 events and the registry 350,
          so a registry-only seed showed roughly 30% of the frame and silently
          omitted the rest. No FOREIGN EventStore is read, subscribed to, or
          proxied; the boundary the rest of the system keeps ("registries only
          subscribe to their own eventstore by design") is kept exactly. Whether
          that ever widens — and under what policy — is a decision the Commander
          reserved; nothing here pre-empts it.
        * Each event appears ONCE. The wire is at-least-once (the EventStore
          broadcasts at accept time and again after its Kafka consumer stores the
          event), so the writer refuses repeats by event id. A 400-entry ring half
          full of repeats would be a 200-event window advertising 400.
        * It is a SEED, not history. The response says so in its own body:
          `count`, `ring` and `is_seed` are returned alongside the events so no
          client can quietly present it as a complete record. The bridge's pulse
          bar, for instance, must keep drawing minutes it did not witness as
          ABSENCE even when it has been seeded.

        The legacy shape (a bare JSON array) is preserved at the separate
        hidden route `/api/v1/public/eventstore-recent-legacy` because the
        landing page's event feed already consumes it that way. (There is no
        `?legacy=1` parameter — an earlier docstring claimed one.)
        """
        import json as _json
        # Imported here, matching how this module reaches the emitter elsewhere.
        from agentvault_registry.event_emitter import RECENT_EVENTS_RING
        n = max(1, min(int(limit or 60), 500))
        events = []
        try:
            from agentvault_registry.background_tasks.leader import get_redis
            r = await get_redis()
            if r:
                raw = await r.lrange("recent_events", 0, n - 1)
                for item in raw:
                    try:
                        events.append(_json.loads(item))
                    except Exception:
                        continue  # one poisoned entry must not empty the seed
        except Exception:
            pass
        # §SECFIX D6-606 (2026-10-16): events carry account ids built from e-mail addresses (a developer's TEG account)
        # and an invitation's address; this answer is public, so both are withheld here (the ledger keeps them).
        from agentvault_registry.identifiers import withhold_personal_ids
        events = withhold_personal_ids(events)
        return {
            "events": events,
            "count": len(events),
            "requested": n,
            "ring": RECENT_EVENTS_RING,
            "scope": "local-frame-eventstore",
            "is_seed": True,
            "note": (
                "A bounded seed of this frame's own EventStore — every event stored "
                "here, whoever emitted it, each appearing once. Not a ledger history: "
                "events older than the ring are not retrievable here, and no foreign "
                "frame is read."
            ),
        }

    @app.get("/api/v1/public/eventstore-recent-legacy", tags=["Public"], include_in_schema=False)
    async def public_eventstore_recent_legacy():
        """The pre-R7 bare-array shape, kept for the landing page's event feed."""
        res = await public_eventstore_recent(limit=15)
        return res["events"]

    # Federation topology — Redis-shared + union-grow + background refresh.
    # Ported from routers/agent_locations.py (2026-04-18 BFS hardening) so the
    # Galactic Map's topology source has the same reliability as AgentWorld's.
    # Before: 60s per-worker cache, first-write-wins, 2s timeout, no retries,
    # no union-grow → 3 registries surfaced instead of the actual 10.
    _topology_cache: dict = {"data": None, "ts": 0.0}
    _TOPOLOGY_TTL = 1800             # 30 min shared cache
    _TOPOLOGY_REFRESH_INTERVAL = 60  # Stale threshold → background refresh
    _TOPOLOGY_REDIS_KEY = "registry:topology:public"
    # 2026-05-05 audit Tier 1C: replaced [False] flag with Task ref. Two
    # concurrent requests could both see False and schedule a BFS each. With
    # a Task ref, `done()` is atomic in single-threaded asyncio so concurrent
    # requests either share a running task or schedule one. List is used as
    # a mutable closure cell since the task is created inside an async fn.
    _topology_refresh_task: list = [None]  # [Optional[asyncio.Task]]

    def _topo_domain_key(url_or_domain: str) -> str:
        from urllib.parse import urlparse
        try:
            p = urlparse(url_or_domain if url_or_domain.startswith("http") else f"https://{url_or_domain}")
            return (p.hostname or url_or_domain).lower()
        except Exception:
            return url_or_domain.lower()

    def _topo_public_url(base: str) -> str:
        from urllib.parse import urlparse
        try:
            p = urlparse(base)
            if p.hostname and "." in p.hostname:
                return f"{p.scheme}://{p.hostname}"
        except Exception:
            pass
        return ""

    def _topo_edge_key(a: str, b: str) -> str:
        return "::".join(sorted([a, b]))

    def _union_topology(existing: dict, fresh: dict) -> dict:
        """Merge two topology payloads — SELF-CLEANING so the shared cache can
        never accumulate stale registries/edges (the old union-grow "never
        shrinks" footgun that stranded dead frame↔op edges on every globe and
        is a scaling death-sentence). Every registry (by domain) and every edge
        carries a last-seen timestamp, refreshed whenever a BFS cycle re-observes
        it; anything not re-observed within its TTL is auto-pruned. Fresh values
        still replace when non-empty; hopDepth takes the minimum. TTLs are
        env-tunable. A degenerate/empty fresh crawl (all peers timed out) NEVER
        prunes, so a transient bad cycle can't nuke the graph."""
        import time as _t, os as _o
        now = _t.time()
        EDGE_TTL = float(_o.getenv("TOPOLOGY_EDGE_TTL_SEC", "300") or 300)    # edge unseen 5m  -> drop
        REG_TTL = float(_o.getenv("TOPOLOGY_REG_TTL_SEC", "1800") or 1800)    # registry unseen 30m -> drop
        fresh_regs = [r for r in (fresh.get("registries") or []) if r.get("domain")]
        # Only prune when this crawl actually observed real peers — protects the
        # cache against a transient all-timeout / DB-error cycle.
        substantive = any(r.get("domain") != "__local__" for r in fresh_regs)

        # --- registries: union by domain + per-domain freshness ---
        er: dict = {}
        reg_seen: dict = dict(existing.get("reg_seen") or {})
        for r in (existing.get("registries") or []):
            dk = r.get("domain")
            if dk:
                er[dk] = dict(r)
                reg_seen.setdefault(dk, now)        # legacy rows: seed as just-seen
        for r in fresh_regs:
            dk = r["domain"]
            reg_seen[dk] = now                       # observed this cycle
            prev = er.get(dk)
            if not prev:
                er[dk] = dict(r)
            else:
                combined = dict(prev)
                for k, v in r.items():
                    if v not in (None, ""):
                        combined[k] = v
                if prev.get("hopDepth") is not None and r.get("hopDepth") is not None:
                    combined["hopDepth"] = min(prev["hopDepth"], r["hopDepth"])
                er[dk] = combined
        reg_seen["__local__"] = now                  # local is always live
        if substantive:
            live = {dk for dk in er if (now - reg_seen.get(dk, now)) <= REG_TTL}
        else:
            live = set(er.keys())
        er = {dk: r for dk, r in er.items() if dk in live}
        reg_seen = {dk: ts for dk, ts in reg_seen.items() if dk in live}
        regs = sorted(er.values(), key=lambda x: (x.get("hopDepth") or 99, x.get("name") or ""))

        # --- edges: union + per-edge freshness (this is what kills the stale hub) ---
        edge_ts: dict = dict(existing.get("edge_ts") or {})
        for e in (existing.get("edges") or []):
            edge_ts.setdefault(e, now)               # legacy edges: seed as just-seen
        for e in (fresh.get("edges") or []):
            edge_ts[e] = now                         # observed this cycle
        if substantive:
            edges = [e for e, ts in edge_ts.items() if (now - ts) <= EDGE_TTL]
        else:
            edges = list(edge_ts.keys())
        edge_ts = {e: edge_ts[e] for e in edges}
        return {"registries": regs, "edges": edges, "reg_seen": reg_seen, "edge_ts": edge_ts}

    async def _load_topology_from_redis():
        import json as _json
        try:
            from agentvault_registry.background_tasks.leader import get_redis
            r = await get_redis()
            if r is None:
                d = _topology_cache["data"] or {"registries": [], "edges": []}
                return d, float(_topology_cache["ts"] or 0)
            raw = await r.get(_TOPOLOGY_REDIS_KEY)
            if raw:
                data = _json.loads(raw)
                return (data.get("data") or {"registries": [], "edges": []}), float(data.get("ts") or 0)
        except Exception as e:
            logger.debug(f"[topology] Redis read failed, falling back to in-memory: {e}")
        d = _topology_cache["data"] or {"registries": [], "edges": []}
        return d, float(_topology_cache["ts"] or 0)

    async def _save_topology_to_redis(data: dict, ts: float):
        import json as _json
        _topology_cache["data"] = data
        _topology_cache["ts"] = ts
        try:
            from agentvault_registry.background_tasks.leader import get_redis
            r = await get_redis()
            if r is None:
                return
            await r.set(_TOPOLOGY_REDIS_KEY, _json.dumps({"data": data, "ts": ts}), ex=_TOPOLOGY_TTL)
        except Exception as e:
            logger.debug(f"[topology] Redis write failed (non-fatal): {e}")

    async def _run_topology_bfs() -> dict:
        """Full federation BFS, union-merged into the shared cache. Safe under
        concurrency — the cache only ever grows."""
        import time as _time
        import asyncio as _asyncio
        import os as _os
        from sqlalchemy import select as _sel, func as _sa_func
        from .models import PeerRegistry as _PR
        from .database import AsyncSessionLocal as _ASL

        now = _time.time()
        # §2026-06-29 — the local topology entry showed a generic "Local Registry"
        # on every frame because it only read REGISTRY_DISPLAY_NAME (unset). Fall
        # back to REGISTRY_NAME (set per-frame: "Registry-A"/"Frame-C"/…) so the
        # Discovery "Local" filter + the Fed-Discover local card show the real name.
        local_name = _os.getenv("REGISTRY_DISPLAY_NAME") or _os.getenv("REGISTRY_NAME") or "Local Registry"
        registries: dict = {
            "__local__": {"name": local_name, "publicUrl": "", "domain": "__local__", "hopDepth": 0}
        }
        edges: set = set()

        try:
            async with _ASL() as db:
                # Only seed BFS from truly-configured peers (frame / direct_peer /
                # cloud_operator). Discovered peers must NOT be seeded — they'd
                # get clobbered to hop=1 on every crawl, destroying the true
                # discovery depth. BFS still reaches them by crawling the
                # direct peers they're reachable through.
                rows = (await db.execute(
                    _sel(_PR).where(
                        _sa_func.lower(_PR.status) == "active",
                        _PR.peer_type != "discovered",
                    )
                )).scalars().all()
                local_peers = [{"base_url": r.base_url, "name": r.name} for r in rows]
        except Exception as _db_exc:
            logger.warning(f"[topology] local peer query failed: {_db_exc}")
            local_peers = []

        # Self-reference filter: peers reachable from other registries tag us as
        # REGISTRY_DISPLAY_NAME / REGISTRY_NAME. Skip those echoes when building
        # the graph so we don't end up with a "Registry-A" node sitting at hop 2.
        _self_names = {
            (_os.getenv("REGISTRY_DISPLAY_NAME") or "").strip().lower(),
            (_os.getenv("REGISTRY_NAME") or "").strip().lower(),
            (local_name or "").strip().lower(),
            "local registry",
        }
        _self_names.discard("")
        _self_hint = (_os.getenv("REGISTRY_PUBLIC_URL") or _os.getenv("BASE_URL") or "").strip()
        _self_domains: set = set()
        if _self_hint:
            try:
                _self_domains.add(_topo_domain_key(_self_hint))
            except Exception:
                pass
        # Also derive self-domains from env-var hostnames if set.
        # §2026-06-03: FEDERATION_BASE_URL added — sandbox frames advertise on
        # nginx-test-{a,b,c}:8443 via FEDERATION_BASE_URL, but their REGISTRY_NAME
        # ("Registry-Test-C") differs in spacing from the discovered peer name
        # ("Registry Test C") AND their BASE_URL is localhost:PORT, so neither the
        # name nor BASE_URL self-filter caught the registry's own nginx host →
        # the frame federated with ITSELF. Deriving the self-domain from
        # FEDERATION_BASE_URL closes that (domain-based, immune to name spacing).
        for var in ("REGISTRY_PUBLIC_URL", "BASE_URL", "FEDERATION_BASE_URL"):
            v = (_os.getenv(var) or "").strip()
            if v:
                try:
                    _self_domains.add(_topo_domain_key(v))
                except Exception:
                    pass
        # Last resort: if REGISTRY_NAME is "Registry-A", the canonical domain is
        # api.theprotocol.cloud — hardcode the Frame A mainframe case.
        if (_os.getenv("REGISTRY_NAME") or "").strip().lower() == "registry-a":
            _self_domains.add("api.theprotocol.cloud")

        # §2026-06-03 cross-environment guard. A sandbox registry (.test trust
        # domain) must never ingest/advertise PROD peers, and vice-versa. The
        # BFS crawls federation peers transitively and the union cache never
        # forgets, so one historical sandbox→prod sighting otherwise propagates
        # fleet-wide (op-*/Registry-A/Frame-B leaking into sandbox topology —
        # the exact contamination seen 2026-06-03). Classify by domain; the
        # internal sandbox hosts (nginx-test-c, *.op-sandbox.internal) classify
        # 'unknown' and are NEVER blocked, so legit sandbox peers survive.
        def _domain_env(dk: str) -> str:
            d = (dk or "").lower()
            if not d:
                return "unknown"
            if ".test" in d or "sandbox" in d or "op-sandbox" in d:
                return "sandbox"
            if "theprotocol.cloud" in d or "agentvault.com" in d or ".op.theprotocol" in d:
                return "prod"
            return "unknown"
        _lenv_hint = (
            _os.getenv("SPIRE_TRUST_DOMAIN")
            or _os.getenv("FEDERATION_BASE_URL")
            or _os.getenv("REGISTRY_NAME")
            or ""
        ).strip()
        _local_env = _domain_env(
            _topo_domain_key(_lenv_hint) if _lenv_hint.startswith("http") else _lenv_hint
        )
        if _local_env == "unknown" and (
            (_os.getenv("REGISTRY_NAME") or "").strip().lower().startswith("registry-test")
        ):
            _local_env = "sandbox"

        def _is_cross_env(dk: str) -> bool:
            if _local_env == "unknown":
                return False
            de = _domain_env(dk)
            return de != "unknown" and de != _local_env

        def _filter_cross_env(topo: dict) -> dict:
            """Drop registries (and any edge touching them) whose environment
            differs from ours. No-op when our own env is unknown."""
            if _local_env == "unknown":
                return topo
            regs = [r for r in (topo.get("registries") or []) if not _is_cross_env(r.get("domain"))]
            edges = [
                e for e in (topo.get("edges") or [])
                if not any(_is_cross_env(p) for p in str(e).split("::"))
            ]
            return {"registries": regs, "edges": edges}

        def _is_self_reference(dk: str, name: str) -> bool:
            if dk in _self_domains:
                return True
            if (name or "").strip().lower() in _self_names:
                return True
            return False

        # CB-499: the crawl's client and request come from agent_locations, the trusted-registries crawl's own: TLS
        # verified with this registry's trust (SPIRE bundle and public roots), no redirect followed, and the DNS bypass
        # (a peer's name resolving to this host) verifies the certificate for the peer's NAME. The rows this crawl
        # writes back are peer rows that federation sync dials and transfer routing reads.
        from agentvault_registry.routers.agent_locations import _crawl_client, _crawl_get

        queue: list = []
        for peer in local_peers:
            raw_url = (peer.get("base_url") or "").rstrip("/")
            pub = _topo_public_url(raw_url)
            if not pub:
                continue
            dk = _topo_domain_key(pub)
            if dk not in registries:
                # §FRAMELIC row 157 — `federationUrl` is the DIALABLE address; `publicUrl` is
                # the port-stripped one for display. The DB writeback below stores base_url,
                # which federation_sync DIALS, so it must have the port.
                registries[dk] = {"name": peer.get("name", dk), "publicUrl": pub,
                                  "federationUrl": raw_url, "domain": dk, "hopDepth": 1}
            edges.add(_topo_edge_key("__local__", dk))
            # rawUrl preserves the :8443 federation port used by Frame-B and
            # some operator nginxes. publicUrl (port-stripped) is for display.
            queue.append({"domain": dk, "publicUrl": pub, "rawUrl": raw_url, "hop": 1})

        visited: set = set()
        MAX_HOPS = 8  # Matches trusted-registries depth — covers Seoul→Tokyo→A→SaoPaulo→... chains

        async with _crawl_client(6.0) as client:
            while queue:
                level = [it for it in queue if it["domain"] not in visited]
                queue = []
                for it in level:
                    visited.add(it["domain"])

                async def _fetch(it):
                    for attempt in range(2):  # initial + 1 retry
                        try:
                            r = await _crawl_get(client, it["rawUrl"], "/api/v1/federation/peers/")
                            if r.status_code == 200:
                                body = r.json()
                                if isinstance(body, dict):
                                    peers = body.get("items", [])
                                elif isinstance(body, list):
                                    peers = body
                                else:
                                    peers = []
                                return (it, peers)
                        except Exception:
                            if attempt == 0:
                                await _asyncio.sleep(0.3)
                                continue
                    return (it, [])

                results = await _asyncio.gather(*[_fetch(it) for it in level], return_exceptions=False)
                for src, peers in results:
                    for peer in peers:
                        raw = (peer.get("base_url") or peer.get("url") or "").rstrip("/")
                        pub = _topo_public_url(raw)
                        if not pub:
                            continue
                        dk = _topo_domain_key(pub)
                        if not dk:
                            continue
                        # §2026-06-03 cross-env guard: never cross sandbox⊥prod
                        if _is_cross_env(dk):
                            continue
                        peer_name = peer.get("name", dk)
                        # Skip self-reference echoes: peers reporting us back
                        if _is_self_reference(dk, peer_name):
                            continue
                        new_hop = src["hop"] + 1
                        existing = registries.get(dk)
                        if not existing:
                            registries[dk] = {
                                "name": peer_name,
                                "publicUrl": pub,
                                "federationUrl": raw,      # §FRAMELIC row 157 — keeps the port
                                "domain": dk,
                                "hopDepth": new_hop,
                            }
                        elif new_hop < existing["hopDepth"]:
                            existing["hopDepth"] = new_hop
                        edges.add(_topo_edge_key(src["domain"], dk))
                        if src["hop"] < MAX_HOPS and dk not in visited:
                            queue.append({"domain": dk, "publicUrl": pub, "rawUrl": raw, "hop": src["hop"] + 1})

        fresh = {"registries": list(registries.values()), "edges": list(edges)}
        # §2026-06-03 purge any cross-env leak from the fresh crawl.
        fresh = _filter_cross_env(fresh)

        # Track which domains BFS actually observed this cycle (pre-union).
        # Used below to bump `last_seen_in_topology_at` only for peers that
        # truly appeared in the fresh fetch — stale cached entries in the
        # union must NOT get a fresh timestamp, or chain-aware drift breaks.
        fresh_domains = {
            r.get("domain") for r in fresh["registries"]
            if r.get("domain") and r.get("domain") != "__local__"
        }

        cached_data, _ts = await _load_topology_from_redis()
        # §2026-06-03 purge cross-env leak that the never-shrinking union cache
        # accumulated BEFORE this guard shipped — so prod self-evicts from the
        # sandbox cache (and vice-versa) on the next refresh instead of forever.
        cached_data = _filter_cross_env(cached_data)
        cached_regs = cached_data.get("registries") or []
        unioned = _union_topology(cached_data, fresh)

        if len(unioned["registries"]) >= len(cached_regs):
            await _save_topology_to_redis(unioned, now)
            out = unioned
        else:
            logger.warning(
                f"[topology] BFS regressed ({len(cached_regs)} cached → "
                f"{len(fresh['registries'])} fresh), keeping previous cache"
            )
            out = cached_data

        # --- 2026-04-21 (0016): writeback discovered topology to peer_registries ---
        # Persist hop_distance, parent_registry_id, discovered_at on every known
        # peer. Additive + defensive: any failure is logged and swallowed so the
        # cache-refresh cycle never breaks. Emits PeerTopologyRefreshed once per
        # hour (deduped via idempotency_key) when any rows changed.
        _wb_updated = 0
        _wb_inserted = 0
        try:
            import datetime as _dt_wb
            now_utc = _dt_wb.datetime.now(_dt_wb.timezone.utc)
            async with _ASL() as db_wb:
                existing_rows = (await db_wb.execute(_sel(_PR))).scalars().all()
                by_dk: dict = {}
                for r in existing_rows:
                    dk = _topo_domain_key(r.base_url or "")
                    if dk:
                        by_dk[dk] = r

                # Live cloud operators → name set. Used to auto-tag BFS-discovered
                # rows as 'cloud_operator' on insert instead of 'discovered', so
                # a newly-provisioned op discovered before its peer row exists
                # (via cross-registry federation) still lands in the right tier.
                from .models import OperatorApplication as _OA
                cloud_op_rows = (await db_wb.execute(
                    _sel(_OA).where(
                        _OA.cloud_hosted == True,
                        _OA.cloud_torn_down_at.is_(None),
                    )
                )).scalars().all()
                cloud_op_names = {a.name for a in cloud_op_rows}

                hop_by_dk: dict = {
                    reg.get("domain"): reg.get("hopDepth")
                    for reg in out.get("registries", [])
                    if reg.get("domain")
                }

                def _resolve_parent_id(dk: str, hop: int):
                    for edge in out.get("edges", []):
                        if dk not in edge:
                            continue
                        a, b = edge.split("::", 1)
                        other = b if a == dk else a
                        if other == "__local__":
                            continue
                        other_hop = hop_by_dk.get(other)
                        if other_hop is not None and other_hop < hop:
                            other_row = by_dk.get(other)
                            if other_row is not None:
                                return other_row.id
                    return None

                admin_dev_row = (await db_wb.execute(
                    _sel(_PR.owner_developer_id).limit(1)
                )).scalar_one_or_none()

                # Name-or-domain guards to prevent self-discovery rows:
                # peers reachable from other registries tag us as
                # REGISTRY_DISPLAY_NAME / REGISTRY_NAME, and we would otherwise
                # ingest that echo as a "discovered" peer pointing at ourselves.
                # §ONESHOT (2026-09-12) — ONE rule for "this is us" (core/operator_names.topology_self_names):
                # the display name, REGISTRY_NAME and its `cloud-op-` slug, the bilateral self-name, and the hosts of
                # REGISTRY_PUBLIC_URL / BASE_URL / FEDERATION_BASE_URL / PUBLIC_URL. The inline set that stood here
                # lacked the slug and PUBLIC_URL — the two things a cloud operator is listed by — so every fresh
                # operator inserted ITSELF as a discovered peer at every boot and dialed itself each cycle.
                from agentvault_registry.core.operator_names import topology_self_names as _topo_self_names
                _self_names = _topo_self_names(dict(_os.environ), local_name)

                for reg in out.get("registries", []):
                    dk = reg.get("domain")
                    if not dk or dk == "__local__":
                        continue
                    hop = reg.get("hopDepth") or 1
                    public_url = reg.get("publicUrl") or ""
                    # §FRAMELIC (2026-09-07, findings row 157) — the address this row will be
                    # DIALED at, not the one it is displayed as. The BFS strips the port for
                    # display and has said so since it was written ("rawUrl preserves the :8443
                    # federation port … publicUrl (port-stripped) is for display") — and then the
                    # INSERT below stored the display value in `base_url`, which is the field
                    # `federation_sync` dials. Every cross-frame operator this frame discovered
                    # therefore landed on the :443 console, where the mTLS edge answers
                    # `400 No required SSL certificate was sent`, and never synced.
                    federation_url = reg.get("federationUrl") or public_url
                    name = (reg.get("name") or dk)[:255]
                    # Skip self-reference echoes
                    if (name or "").strip().lower() in _self_names:
                        continue
                    if dk in _self_names:
                        continue
                    existing = by_dk.get(dk)
                    parent_id = _resolve_parent_id(dk, hop) if hop >= 2 else None

                    # Whether this peer matches a live cloud operator application
                    _is_cloud_op = name in cloud_op_names

                    if existing is not None:
                        changed = False
                        # §pass62.5 (2026-05-21) — DO NOT OVERWRITE hop_distance
                        # / parent_registry_id on existing rows. The original
                        # "replace on every sighting" logic (2026-04-21) flattened
                        # the chained-sibling parents that the Federation Network
                        # tab tree renderer relies on for stable, hierarchical
                        # topology visualization. Commander explicitly rejected
                        # the flat-tree outcome (see §pass62.3 incident log) —
                        # the chain encodes discovery order from cloud_provisioner
                        # registration sequence and is the load-bearing source of
                        # truth for the tree shape. New peer rows still get
                        # hop/parent on INSERT (lines below); only the UPDATE
                        # path is disabled here.
                        #
                        # Trade-off: if a peer's real hop changes (rare; happens
                        # only when topology routes change), the DB stays stale
                        # until an admin manually corrects via SQL. Acceptable
                        # because topology routes are stable post-provisioning.
                        # Original code preserved below for reference / future
                        # re-enable behind a feature flag if BFS staleness
                        # becomes a real problem:
                        # if hop is not None and existing.hop_distance != hop:
                        #     existing.hop_distance = hop
                        #     changed = True
                        # if parent_id and existing.parent_registry_id != parent_id:
                        #     existing.parent_registry_id = parent_id
                        #     changed = True
                        # Chain-reachability signal (0017): bump timestamp only
                        # for peers BFS actually observed in the fresh fetch.
                        # Stale union entries stay untouched so they can age
                        # out and become drift.
                        if dk in fresh_domains:
                            existing.last_seen_in_topology_at = now_utc
                            changed = True
                        # If the peer corresponds to a live cloud op, ensure the
                        # tier is 'cloud_operator' (covers rows created by BFS
                        # before cloud_provisioner seeded one, or mis-classified
                        # legacy rows).
                        if _is_cloud_op and existing.peer_type not in ('cloud_operator', 'frame'):
                            existing.peer_type = 'cloud_operator'
                            changed = True
                        # Tag as 'discovered' only if still on the default, not a
                        # cloud op, and we found it via BFS.
                        elif (
                            hop >= 2
                            and existing.peer_type == 'direct_peer'
                            and existing.discovered_at is None
                            and not _is_cloud_op
                        ):
                            existing.peer_type = 'discovered'
                            existing.discovered_at = now_utc
                            changed = True
                        if changed:
                            _wb_updated += 1
                    elif hop >= 2 and public_url and admin_dev_row is not None:
                        # INSERT — cloud op rows land in 'cloud_operator' directly.
                        # New discoveries are fresh by definition (we just saw them),
                        # so last_seen_in_topology_at is set unconditionally.
                        insert_type = 'cloud_operator' if _is_cloud_op else 'discovered'
                        db_wb.add(_PR(
                            owner_developer_id=admin_dev_row,
                            name=name,
                            base_url=federation_url,   # §FRAMELIC row 157 — dialable, not display
                            admin_contact_email='bfs-discovered@theprotocol.cloud',
                            status='ACTIVE',
                            discovery_auth_info={},
                            peer_type=insert_type,
                            hop_distance=hop,
                            parent_registry_id=parent_id,
                            discovered_at=now_utc if insert_type == 'discovered' else None,
                            last_seen_in_topology_at=now_utc,
                        ))
                        _wb_inserted += 1
                await db_wb.commit()
        except Exception as _wb_exc:
            logger.warning(f"[topology] DB writeback failed (non-fatal): {_wb_exc}")

        # --- 2026-06-04 — Sovereign-mesh topology reconcile (durable, prod-safe) ---
        # Deterministically heal rows that NON-BFS paths (federation_sync / frame
        # data-plane / re-provision) leave malformed, so the GalacticMap + Federation
        # tab chain can never silently regress to hub-and-spoke (the flat-topology
        # class Commander has fought repeatedly). Three idempotent passes, each a
        # strict no-op on an already-correct frame (so PROD — whose chains are tuned —
        # is untouched):
        #   (1) reclassify: any ACTIVE peer whose SIGNED card tier is
        #       'sovereign-mainframe' AND trust_domain != ours → peer_type='frame'
        #       (the golden-bridge counterpart frames; fixes Frame-B/C mislabeled
        #       'discovered' on the sibling sandbox frame).
        #   (2) dedup + self-echo: keep one frame row per trust_domain; deactivate
        #       name-variant duplicates AND any mainframe row carrying OUR OWN
        #       trust_domain (a self-echo mis-ingested as a peer).
        #   (3) chain backfill: an ACTIVE non-frame peer with parent_registry_id IS
        #       NULL whose trust_domain matches a frame's → parent = that frame,
        #       hop = 2. NEVER overwrites a non-NULL parent — the §pass62.5 invariant
        #       that protects prod's hand-tuned chains stays intact.
        # Bails if we can't establish our own trust domain (avoids mis-chaining).
        try:
            _local_td = (_os.getenv("SPIRE_TRUST_DOMAIN") or "").strip().lower()
            if _local_td:
                # §pass78.2 — the self-echo dedup below is MAINFRAME-only (see its comment).
                from agentvault_registry.core.mainframe_gate import is_mainframe as _is_mainframe
                from agentvault_registry.core.peer_group import frame_row_keep_rank as _frame_row_keep_rank
                _local_is_mainframe = _is_mainframe()
                def _row_is_mainframe(r) -> bool:
                    rc = r.cached_registry_card if isinstance(r.cached_registry_card, dict) else None
                    return bool(rc and (((rc.get("identity") or {}).get("tier")) == "sovereign-mainframe"))
                async with _ASL() as db_rc:
                    rc_rows = (await db_rc.execute(_sel(_PR))).scalars().all()
                    _rc_changed = 0
                    frame_by_td: dict = {}
                    seen_frame_td: set = set()
                    # Pass 1+2: frame reclassify, self-echo + duplicate dedup.
                    # §FRAMETWIN (2026-09-29): the dedup keeps the FIRST frame row it meets per trust domain, so the
                    # iteration order decides which twin survives. It was the unordered SELECT's order, and on 09-07
                    # the 443 twin won on shenzhen and hochiminh. The keep rule lives in core/peer_group.py.
                    for r in sorted(rc_rows, key=_frame_row_keep_rank):
                        if (r.status or "").upper() != "ACTIVE":
                            continue
                        td = (r.trust_domain or "").strip().lower()
                        if not _row_is_mainframe(r):
                            continue
                        # self-echo dedup is MAINFRAME-only: a mainframe can mis-ingest its
                        # OWN sovereign identity as a peer (drop it). A cloud-op SHARES its
                        # parent frame's trust_domain, so a same-td sovereign-mainframe row is
                        # its LEGITIMATE parent — required for WS-C cross-TEG currency
                        # resolution. §pass78.2: the un-gated check deactivated cloud-op
                        # parent-frame rows → the FX guard then 409'd every cross-TEG transfer
                        # to that frame (prod incident 2026-06-04). Gate on is_mainframe so a
                        # cloud-op falls through → reclassify to frame + keep ACTIVE.
                        if td and td == _local_td:
                            if _local_is_mainframe:
                                r.status = "INACTIVE"; _rc_changed += 1
                                r.deactivated_reason = "self_echo"  # guard-set (RCA 2026-07-10)
                                import datetime as _dt_rc; r.deactivated_at = _dt_rc.datetime.now(_dt_rc.timezone.utc)
                                continue
                            # cloud-op: legit parent frame — fall through to reclassify + keep.
                        if not td:
                            continue
                        if r.peer_type != "frame":
                            r.peer_type = "frame"; _rc_changed += 1
                        if r.hop_distance is None:
                            r.hop_distance = 1; _rc_changed += 1
                        if td in seen_frame_td:
                            # duplicate frame (name variant of the same trust_domain)
                            r.status = "INACTIVE"; _rc_changed += 1
                            r.deactivated_reason = "duplicate_frame"  # guard-set (RCA 2026-07-10)
                            import datetime as _dt_rc; r.deactivated_at = _dt_rc.datetime.now(_dt_rc.timezone.utc)
                            _kept_fr = frame_by_td.get(td)
                            logger.warning(
                                "[topology] duplicate frame row #%s %r (%s) parked as duplicate_frame; kept #%s %r (%s) "
                                "for trust domain %s", r.id, r.name, r.base_url, getattr(_kept_fr, "id", None),
                                getattr(_kept_fr, "name", None), getattr(_kept_fr, "base_url", None), td)
                            continue
                        seen_frame_td.add(td)
                        frame_by_td[td] = r
                    # Pass 3: chain NULL-parent cross-frame operators under their frame.
                    for r in rc_rows:
                        if (r.status or "").upper() != "ACTIVE":
                            continue
                        if r.peer_type == "frame" or r.parent_registry_id is not None:
                            continue
                        td = (r.trust_domain or "").strip().lower()
                        if not td or td == _local_td:
                            continue
                        fr = frame_by_td.get(td)
                        if fr is not None and fr.id != r.id:
                            r.parent_registry_id = fr.id
                            if r.hop_distance is None:
                                r.hop_distance = (fr.hop_distance or 1) + 1
                            _rc_changed += 1
                    if _rc_changed:
                        await db_rc.commit()
                        logger.info(f"[topology] sovereign-mesh reconcile healed {_rc_changed} peer row(s)")
        except Exception as _rc_exc:
            logger.warning(f"[topology] sovereign-mesh reconcile failed (non-fatal): {_rc_exc}")

        # Emit summary event once per hour when something changed.
        if _wb_updated or _wb_inserted:
            try:
                from .event_emitter import get_event_emitter as _get_emitter
                import datetime as _dt_e
                hour_key = _dt_e.datetime.now(_dt_e.timezone.utc).strftime("%Y-%m-%d-%H")
                emitter = _get_emitter()
                await emitter.emit(
                    event_type="PeerTopologyRefreshed",
                    aggregate_id="registry:topology",
                    aggregate_type="FederationTopology",
                    data={
                        "peers_updated": _wb_updated,
                        "new_peers_discovered": _wb_inserted,
                        "total_registries": len(out.get("registries", [])),
                        "edge_count": len(out.get("edges", [])),
                        "refreshed_at": _dt_e.datetime.now(_dt_e.timezone.utc).isoformat(),
                    },
                    idempotency_key=f"topology-refresh-{hour_key}",
                )
            except Exception as _emit_exc:
                logger.debug(f"[topology] PeerTopologyRefreshed emit failed (non-fatal): {_emit_exc}")

        logger.info(
            f"[topology] Discovered {len(fresh['registries'])} fresh, "
            f"serving {len(out['registries'])} after union "
            f"(writeback: {_wb_updated} updated, {_wb_inserted} inserted)"
        )
        return out

    async def _build_topology_tiers(flat_data: dict) -> dict:
        """Assemble tier-bucketed topology (frames / direct_peers / discovered /
        cloud_operators) from peer_registries rows. Additive to the existing flat
        ``registries`` + ``edges`` shape — callers that want graph data keep the
        old keys; callers that want hierarchy use the new tier keys.

        Non-fatal: any DB failure returns the flat_data unchanged."""
        from sqlalchemy import select as _sel_t
        from .database import AsyncSessionLocal as _ASL_T
        from .models import (
            PeerRegistry as _PR_T,
            FederationLicense as _FL_T,
            OperatorApplication as _OA_T,
        )

        def _peer_base(r) -> dict:
            # Registry Card v0.3 slice (2026-05-21) — lift visual + fees + lifecycle
            # subset out of the cached card so frontend consumers (AgentWorldCesium,
            # LandingPage) can render per-peer orb color + icon + cost-display widget
            # without a separate fetch per peer.
            rc = r.cached_registry_card if isinstance(r.cached_registry_card, dict) else None
            visual_slice = None
            fees_slice = None
            lifecycle_slice = None
            rc_signature_verified = bool(getattr(r, "card_signature_verified", False))
            if rc:
                visual_slice = rc.get("visual") or None
                _fees = rc.get("fees") or {}
                fees_slice = {
                    "intra_registry":  (_fees.get("intra_registry")  or {}).get("base_rate_percent"),
                    "cross_registry":  (_fees.get("cross_registry")  or {}).get("base_rate_percent"),
                    "hosting_enabled": bool((_fees.get("hosting") or {}).get("enabled")),
                    "hosting_rate":    (_fees.get("hosting") or {}).get("rate_percent_of_agent_service_fee"),
                }
                _lc = rc.get("lifecycle") or {}
                lifecycle_slice = {
                    "status":             _lc.get("status"),
                    "card_etag":          _lc.get("card_etag"),
                    "card_updated_at":    _lc.get("card_updated_at"),
                    "quarantine_reason":  _lc.get("quarantine_reason"),
                }
            return {
                "id": r.id,
                "name": r.name,
                "base_url": r.base_url,
                "status": r.status,
                "peer_type": r.peer_type,
                "hop_distance": r.hop_distance,
                "discovered_at": r.discovered_at.isoformat() if r.discovered_at else None,
                "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
                "operator_did": r.operator_did,
                "trust_domain": r.trust_domain,
                "parent_registry_id": r.parent_registry_id,
                # --- Registry Card v0.3 slice ---
                "visual": visual_slice,
                "fees": fees_slice,
                "lifecycle": lifecycle_slice,
                "card_signature_verified": rc_signature_verified,
                "card_last_pulled_at": r.card_last_pulled_at.isoformat() if r.card_last_pulled_at else None,
                # 2026-06-04 — authoritative mainframe flag for the topology views.
                # peer_type is unreliable across frames (a sovereign mainframe can be
                # cached as 'discovered' when reached via cross-frame federation, while
                # operators of a sibling frame share their parent's trust_domain) so the
                # GalacticMap can't tell a mainframe from an operator by peer_type alone.
                # The peer's own SIGNED registry card carries the truth: identity.tier
                # == 'sovereign-mainframe' for frames, 'sandbox'/'cloud-operator' for ops.
                # The map golds the inter-frame bridge ONLY between is_mainframe nodes.
                "is_mainframe": (((rc.get("identity") if rc else None) or {}).get("tier")) == "sovereign-mainframe",
            }

        try:
            async with _ASL_T() as db_t:
                # §pass66 (2026-05-22) — stale operator cleanup. Same filter
                # as the admin topology overview (federation_topology.py): only
                # ACTIVE peers + non-torn-down applications surface here. This
                # cascades to LandingPage globe + AgentWorld Cesium globe +
                # Federation Network tab (all consume /public/topology).
                peer_rows = (await db_t.execute(
                    _sel_t(_PR_T).where(_PR_T.status == "ACTIVE")
                )).scalars().all()
                lic_rows = (await db_t.execute(_sel_t(_FL_T))).scalars().all()
                app_rows = (await db_t.execute(
                    _sel_t(_OA_T).where(_OA_T.cloud_torn_down_at.is_(None))
                )).scalars().all()

                # §pass66 (2026-05-22) — additional safety net for the flat
                # `registries` list. The BFS-derived list (`flat_data.registries`)
                # includes peers DISCOVERED via crawling other peers' federation
                # exports. A peer torn-down here may still be reported as a peer
                # by a cloud-op that hasn't received the deactivation event yet
                # → leaked into our topology with status looking healthy. Build
                # a set of known-INACTIVE names and filter them out of the flat
                # list during augmentation below. Mission Control + LandingPage
                # + AgentWorld globe consume the flat list, so this is the
                # actual user-visible filter.
                _inactive_names_rows = (await db_t.execute(
                    _sel_t(_PR_T.name).where(_PR_T.status != "ACTIVE")
                )).all()
                inactive_names_lower = {
                    (n[0] or "").strip().lower() for n in _inactive_names_rows
                }
                # §pass66.2 (2026-05-23) — ALSO filter peers that have NO local
                # row at all (hard-deleted, not just inactive). The in-memory
                # `_topology_cache` survives across Redis purges + container
                # restarts on long-lived workers — so a stale entry that lost
                # its DB row can linger in cached_data forever. Build the set
                # of currently-ACTIVE local peer names and only let those (+
                # our own identity) survive the augmentation filter below.
                _active_local_names = {
                    (r.name or "").strip().lower() for r in peer_rows
                }
                import os as _os_act
                for _env_key in ("REGISTRY_NAME", "REGISTRY_FEDERATION_NAME", "REGISTRY_DISPLAY_NAME"):
                    _v = (_os_act.environ.get(_env_key) or "").strip().lower()
                    if _v:
                        _active_local_names.add(_v)
                _active_local_names.add("local registry")

                lic_by_did = {l.operator_did: l for l in lic_rows if l.operator_did}
                app_by_name = {a.name: a for a in app_rows}
                peers_by_id = {p.id: p for p in peer_rows}

                frames, direct_peers, discovered, cloud_operators = [], [], [], []
                peers_by_type: dict = {"frame": 0, "direct_peer": 0, "discovered": 0, "cloud_operator": 0}
                license_breakdown: dict = {"active": 0, "suspended": 0, "revoked": 0, "none": 0}

                for r in peer_rows:
                    base = _peer_base(r)
                    lic = lic_by_did.get(r.operator_did) if r.operator_did else None
                    app = app_by_name.get(r.name)
                    pt = r.peer_type or "direct_peer"
                    peers_by_type[pt] = peers_by_type.get(pt, 0) + 1

                    lic_status_key = lic.status if lic else "none"
                    license_breakdown[lic_status_key] = license_breakdown.get(lic_status_key, 0) + 1

                    if pt == "frame":
                        frames.append({**base, "trust_domain": r.trust_domain})
                    elif pt == "cloud_operator":
                        cloud_operators.append({
                            **base,
                            "application_id": app.id if app else None,
                            "cloud_url": app.cloud_url if app else None,
                            "cloud_provisioned_at": (
                                app.cloud_provisioned_at.isoformat()
                                if app and app.cloud_provisioned_at else None
                            ),
                            "license_status": lic.status if lic else None,
                            "healthy": (r.health_check_failure_count or 0) < 3,
                        })
                    elif pt == "discovered":
                        parent = peers_by_id.get(r.parent_registry_id) if r.parent_registry_id else None
                        discovered.append({
                            **base,
                            "parent_name": parent.name if parent else None,
                        })
                    else:
                        direct_peers.append({
                            **base,
                            "license_status": lic.status if lic else None,
                        })

                import time as _time_t

                # Augment legacy flat `registries` list with trust_domain
                # (2026-05-05 audit Theme #1). The tier buckets above already
                # carry trust_domain via _peer_base; the flat list is the
                # legacy domain-keyed graph the older frontend code reads,
                # so we copy the value across by joining on base_url's
                # domain or peer name (whichever matches first). Frame B
                # operators have multiple aliases (.op.theprotocol.cloud
                # vs .frame-b.theprotocol.cloud) so domain-only join misses
                # half — name fallback covers them.
                td_by_domain: dict = {}
                td_by_name: dict = {}
                for r in peer_rows:
                    if not r.trust_domain:
                        continue
                    if r.base_url:
                        try:
                            from urllib.parse import urlparse as _td_urlparse
                            host = (_td_urlparse(r.base_url).hostname or "").lower().split(":")[0]
                            if host:
                                td_by_domain[host] = r.trust_domain
                        except Exception:
                            pass
                    if r.name:
                        td_by_name[r.name.strip().lower()] = r.trust_domain
                # Local registry maps to our own SPIRE trust_domain.
                import os as _os_td
                _own_td = _os_td.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com").lower()
                # §pass66.1 (2026-05-23) — decouple RC slice merge from trust_domain gate.
                # On cloud-ops, peer rows ingested via the §pass66 fan-out path may
                # have empty trust_domain (the federation BFS that originally
                # discovered them doesn't populate it, and the fan-out update
                # branch doesn't either). That left every peer row with td=NULL
                # → both td_by_* dicts empty → this gate failed → RC slice merge
                # skipped → frontend rendered cards without avatars/flares even
                # though cached_registry_card was populated. Gate now also fires
                # when AT LEAST ONE peer has a cached card, so the visual identity
                # surfaces independent of trust_domain availability.
                # §2026-07-27 — gate REMOVED (was: `td_by_domain or td_by_name or
                # _any_cached_card`). This block does two jobs: build PEER card
                # slices *and* attach the LOCAL registry's own slice (display_name /
                # visual / geo / trust_domain). A brand-new sovereign frame has ZERO
                # peers, so the peer-shaped gate skipped the local work too and the
                # frame served its OWN globe with no logo, no flare and a null
                # trust_domain — reported as "the logo doesn't appear on the globe".
                # Every peer lookup below iterates peer_rows and no-ops safely when
                # it is empty, so the gate only ever bought a microsecond and cost
                # correctness on exactly the node that is always present: self.
                _build_rc_slices = True
                if _build_rc_slices:
                    # Registry Card v0.3 (§pass60.4 fix) — build lookups for the
                    # peer RC slices keyed by NAME + by domain (not just trust_domain).
                    # The previous trust_domain key collapsed all peers sharing a
                    # trust_domain (e.g., all Frame B cloud-ops on frame-b.theprotocol.cloud)
                    # to the LAST one iterated — visually merging them into one combo.
                    # Name + domain are unique per peer so the lookup resolves correctly.
                    def _rc_slice(r, rc):
                        return {
                            # §2026-06-14 — operator-editable display name (card identity).
                            # Threaded so hover cards / map labels render the rebranded
                            # name (e.g. "Cyberdime Systems") instead of the load-bearing
                            # slug. Falls back to the slug client-side when null.
                            "display_name": (rc.get("identity") or {}).get("display_name"),
                            # §FOREIGNDEV 2026-08-21 — the registry's OWN signed
                            # statement of its browser-facing address. Everything
                            # else here derives a URL from `base_url`, which is the
                            # FEDERATION endpoint (:8443 mTLS) and, for a renamed
                            # operator, a hostname that may not answer at all:
                            # measured this day, op-singapore's derived host
                            # `op-singapore.frame-b.theprotocol.cloud` returns 000
                            # while the host its card declares
                            # (`op-losangeles.op.theprotocol.cloud`) returns 200.
                            # A client that needs to SEND A USER somewhere must use
                            # the card, not our arithmetic on someone else's URL.
                            "public_url": (rc.get("identity") or {}).get("public_url"),
                            "visual": rc.get("visual"),
                            "fees_summary": {
                                "intra_registry":  (rc.get("fees", {}).get("intra_registry")  or {}).get("base_rate_percent"),
                                "cross_registry": (rc.get("fees", {}).get("cross_registry") or {}).get("base_rate_percent"),
                                "hosting_enabled": bool((rc.get("fees", {}).get("hosting") or {}).get("enabled")),
                                "hosting_rate":    (rc.get("fees", {}).get("hosting") or {}).get("rate_percent_of_agent_service_fee"),
                            },
                            # §2026-06-14 — operator-set geo (AUTHORITATIVE) so the
                            # AgentWorld globe places this registry from the CARD,
                            # not a cross-origin /agents/locations/operator probe.
                            "latitude": (rc.get("operator") or {}).get("latitude"),
                            "longitude": (rc.get("operator") or {}).get("longitude"),
                            "location_label": (rc.get("operator") or {}).get("location_label"),
                            # §2026-06-14 — AGORA venue capability (from fees.exchange)
                            # so the globe / GCC deck can badge venues without a full
                            # card fetch. Capability only; live counts ride federation-tickers.
                            "exchange": {
                                "enabled": bool((rc.get("fees", {}).get("exchange") or {}).get("enabled")),
                                "currency": (rc.get("fees", {}).get("exchange") or {}).get("currency"),
                                "passport_enabled": bool((rc.get("fees", {}).get("exchange") or {}).get("passport_enabled")),
                            },
                            "card_etag": (rc.get("lifecycle") or {}).get("card_etag"),
                            "card_signature_verified": bool(getattr(r, "card_signature_verified", False)),
                        }
                    rc_by_name: dict = {}
                    rc_by_domain: dict = {}
                    for r in peer_rows:
                        if not isinstance(r.cached_registry_card, dict):
                            continue
                        slice_ = _rc_slice(r, r.cached_registry_card)
                        nm = (r.name or "").strip().lower()
                        if nm:
                            rc_by_name[nm] = slice_
                        if r.base_url:
                            try:
                                from urllib.parse import urlparse as _rc_urlparse
                                host = (_rc_urlparse(r.base_url).hostname or "").lower().split(":")[0]
                                if host:
                                    rc_by_domain[host] = slice_
                            except Exception:
                                pass
                    # Build local RC slice from registry_card singleton + builder.
                    local_rc_slice = None
                    try:
                        from .models import RegistryCard as _RC_local
                        from .services.registry_card_builder import build_registry_card as _build_rc
                        local_card = await _build_rc(db_t, sign=False)
                        local_rc_slice = {
                            "display_name": (local_card.get("identity") or {}).get("display_name"),
                            # symmetry with the peer slice above: self declares its
                            # own public address too, so a client never has to guess
                            # which of its hostnames is the browser-facing one.
                            "public_url": (local_card.get("identity") or {}).get("public_url"),
                            "visual": local_card.get("visual"),
                            "fees_summary": {
                                "intra_registry":  (local_card.get("fees", {}).get("intra_registry")  or {}).get("base_rate_percent"),
                                "cross_registry":  (local_card.get("fees", {}).get("cross_registry")  or {}).get("base_rate_percent"),
                                "hosting_enabled": bool((local_card.get("fees", {}).get("hosting") or {}).get("enabled")),
                                "hosting_rate":    (local_card.get("fees", {}).get("hosting") or {}).get("rate_percent_of_agent_service_fee"),
                            },
                            # §2026-06-14 — local registry's own card geo + AGORA venue.
                            "latitude": (local_card.get("operator") or {}).get("latitude"),
                            "longitude": (local_card.get("operator") or {}).get("longitude"),
                            "location_label": (local_card.get("operator") or {}).get("location_label"),
                            "exchange": {
                                "enabled": bool((local_card.get("fees", {}).get("exchange") or {}).get("enabled")),
                                "currency": (local_card.get("fees", {}).get("exchange") or {}).get("currency"),
                                "passport_enabled": bool((local_card.get("fees", {}).get("exchange") or {}).get("passport_enabled")),
                            },
                            "card_etag": (local_card.get("lifecycle") or {}).get("card_etag"),
                            # §pass60.4: topology builds local card with sign=False
                            # (perf — skips JWS per-topology-serve). But the public
                            # /.well-known/registry-card.json IS always signed at serve
                            # time (auto-minted via registry_card_signer). The trust
                            # signal in topology should reflect that reality, not the
                            # perf-skip artefact.
                            "card_signature_verified": True,
                        }
                    except Exception:
                        pass

                    flat_regs = list(flat_data.get("registries") or [])
                    augmented = []
                    for reg in flat_regs:
                        if "trust_domain" in reg and reg.get("visual") is not None:
                            augmented.append(reg)
                            continue
                        if reg.get("domain") == "__local__":
                            merged = {**reg, "trust_domain": _own_td}
                            if local_rc_slice:
                                merged.update(local_rc_slice)
                            augmented.append(merged)
                            continue
                        dom = (reg.get("domain") or "").lower()
                        nm = (reg.get("name") or "").strip().lower()
                        # §pass66 (2026-05-22) — stale operator cleanup safety net.
                        # If THIS registry knows the peer is INACTIVE (torn down),
                        # drop it from the flat list even if BFS discovered it
                        # via another peer that hasn't received the deactivation
                        # event yet. Authoritative local DB state wins over
                        # stale federation crawl results.
                        if nm in inactive_names_lower:
                            continue
                        # §pass66.2 (2026-05-23) — also drop hard-deleted entries
                        # that live only in the in-memory `_topology_cache` dict
                        # (process-local, survives Redis purges). The local DB
                        # is the authoritative truth — if a peer isn't in our
                        # `peer_registries` table as ACTIVE, it shouldn't appear
                        # on Mission Control / LandingPage / AgentWorld panels.
                        # New BFS discoveries get inserted into peer_registries
                        # in the writeback block above (lines 1530-1548), so
                        # legitimate fresh peers reappear after the next refresh
                        # cycle (max ~5 min).
                        if nm and nm not in _active_local_names:
                            continue
                        td = td_by_domain.get(dom) or td_by_name.get(nm)
                        merged = dict(reg)
                        if td:
                            merged["trust_domain"] = td
                        # Lookup the per-peer RC slice by NAME first (unique per peer),
                        # then by domain. Fixes the trust_domain-collision bug where
                        # multiple peers shared a trust_domain and ended up all
                        # rendered with the last-iterated peer's visual+fees.
                        rc_slice = rc_by_name.get(nm) or rc_by_domain.get(dom)
                        if rc_slice:
                            merged.update(rc_slice)
                        augmented.append(merged)
                    flat_data = {**flat_data, "registries": augmented}

                enrich = {
                    "frames": frames,
                    "direct_peers": direct_peers,
                    "discovered": discovered,
                    "cloud_operators": cloud_operators,
                    "peers_by_type": peers_by_type,
                    "license_status_breakdown": license_breakdown,
                    "topology_version": int(_time_t.time() * 1000),
                }
                return {**flat_data, **enrich}
        except Exception as _t_exc:
            logger.debug(f"[topology] tier enrichment failed (non-fatal): {_t_exc}")
            return flat_data

    @app.get("/api/v1/public/topology", tags=["Public"])
    async def public_topology():
        """Federation topology graph (registries + edges) + tier buckets
        (frames / direct_peers / discovered / cloud_operators). Shared via Redis,
        union-grown across BFS runs, refreshed in the background when stale.

        Backward-compatible: legacy consumers use ``registries`` + ``edges``;
        hierarchy consumers use the tier buckets."""
        import time as _time
        import asyncio as _asyncio

        now = _time.time()
        cached_data, cached_ts = await _load_topology_from_redis()
        regs = cached_data.get("registries") or []
        cache_age = now - cached_ts

        # Cold start — synchronous BFS so first callers get something.
        if not regs:
            data = await _run_topology_bfs()
            enriched = await _build_topology_tiers(data)
            return {**enriched, "discovered_at": now}

        # Warm but stale — kick off non-blocking refresh, return cached now.
        if cache_age > _TOPOLOGY_REFRESH_INTERVAL:
            existing = _topology_refresh_task[0]
            if existing is None or existing.done():
                async def _bg():
                    try:
                        await _run_topology_bfs()
                    except Exception as e:
                        logger.debug(f"[topology] Background refresh failed: {e}")
                try:
                    _topology_refresh_task[0] = _asyncio.create_task(_bg())
                except RuntimeError:
                    _topology_refresh_task[0] = None

        enriched = await _build_topology_tiers(cached_data)
        return {**enriched, "discovered_at": cached_ts}

    # §DOCSFIX D6-710: GET /api/v1/public/registry-card is served by routers/registry_card.py (`peer`, an envelope
    # around the card), included above. A second handler here (`registry`, the bare card) was never reached at run
    # time, while the OpenAPI document described it instead of the one that answers; it is gone.

    # --- Showcase Services Proxy (public, no auth, rate-limited) ---
    # Proxies requests to TheProtocol agents via a dedicated showcase agent.
    # Rate limited per IP to prevent abuse.
    _showcase_rate: dict = {}  # ip -> {count, window_start} — FALLBACK only (see _showcase_budget_ok)
    _SHOWCASE_LIMIT = 50  # requests per hour per IP
    # §SHOWCASEFED — sessions are cheaper to mint than calls are to serve,
    # but they hand out a real token, so they get their OWN tighter counter
    # rather than sharing the call budget.
    _showcase_session_rate: dict = {}  # ip -> {count, start} — FALLBACK only
    _SHOWCASE_SESSION_LIMIT = 20  # sessions per hour per IP
    _SHOWCASE_WINDOW = 3600  # 1 hour

    # §FINDFIX F4 (2026-08-29) — ONE shared budget across all workers. The old
    # per-worker dicts multiplied the written cap by the worker count (50/h on
    # paper was ~50×38 on registry-a). Fixed one-hour window in Redis keyed
    # showcase:rl:{kind}:{ip}; INCR is atomic so two workers cannot double-mint
    # a slot. Redis unreachable ⇒ fall back to the old per-worker dict — a
    # public demo prefers availability, and the fallback still caps per worker.
    _showcase_redis = {"client": None}

    async def _showcase_budget_ok(kind: str, ip: str, limit: int,
                                  fallback: dict) -> bool:
        import time as _t
        try:
            r = _showcase_redis["client"]
            if r is None:
                _redis_url = _os.getenv("REDIS_URL")
                if _redis_url:
                    import redis.asyncio as _aioredis
                    r = _aioredis.from_url(_redis_url, decode_responses=True,
                                           socket_connect_timeout=2, socket_timeout=2)
                    _showcase_redis["client"] = r
            if r is not None:
                key = f"showcase:rl:{kind}:{ip}"
                n = await r.incr(key)
                if n == 1 or await r.ttl(key) < 0:
                    await r.expire(key, _SHOWCASE_WINDOW)
                return n <= limit
        except Exception:
            pass  # fall through to the per-worker dict
        now = _t.time()
        entry = fallback.get(ip)
        if not entry or now - entry["start"] > _SHOWCASE_WINDOW:
            fallback[ip] = {"count": 1, "start": now}
            return True
        entry["count"] += 1
        return entry["count"] <= limit
    import os as _os
    # §SHOWCASEFED 2026-08-25 — NO DEFAULTS. These used to carry the retired
    # PPAO agent's real client_secret as a literal, which meant a working
    # credential shipped inside every registry image on all 16 nodes and sat in
    # git history — the §SBROTATE class ("every one of the 18 images shipped a
    # working login"). PPAO is retired: funds clawed back to treasury, identity
    # suspended (registry + TEG + cross-TEG).
    #
    # A frame with no payer configured is NOT broken. It reaches the agent over
    # the public endpoint, gets a 402, and RELAYS to the hosting frame, which
    # pays with its own agent. That is why removing the fallback is safe: the
    # relay is the answer, not a shared credential. registry-a, frame-b and
    # frame-c each carry their own payer in their own gitignored env file.
    # §MCPTEST30 (V0641, D6-831): it relays only to a frame it NAMES (SHOWCASE_RELAY_URL, none by default); with
    # neither a payer nor a relay, its paid showcase calls are refused up front and the catalogue says so
    # (_showcase_call_refusals below).
    _SHOWCASE_AGENT_DID = _os.getenv("SHOWCASE_PPAO_DID", "")
    _SHOWCASE_CLIENT_ID = _os.getenv("SHOWCASE_PPAO_CLIENT_ID", "")
    _SHOWCASE_CLIENT_SECRET = _os.getenv("SHOWCASE_PPAO_CLIENT_SECRET", "")

    # Showcase services (§SHOWCASE-FRAMES R1/R3, 2026-08-09).
    #   url    = the resident A2A endpoint, resolvable only on the HOSTING frame
    #   public = the endpoint the agent's card advertises: reachable from any
    #            frame, cloud operator or third party, and payment-gated (an
    #            unpaid call is refused with JSON-RPC -32099)
    # Kill switch. The showcase is a DEMONSTRATION: in a real production
    # deployment these service agents do not exist and the page should not
    # advertise them. Default true preserves today's behaviour on this network;
    # set SHOWCASE_ENABLED=false and both endpoints refuse honestly instead of
    # half-answering. Two-flag doctrine, like the fiat lane.
    # §CARDLINK (2026-09-08) — A NODE MUST NOT ADVERTISE ANOTHER DEPLOYMENT'S AGENTS.
    # Measured on all four cloud operators: `/api/v1/public/showcase/agents` answered 200 with
    # ELEVEN entries — Frame A's DIDs, Frame A's prices, `https://api.theprotocol.cloud/agents/…`
    # addresses — on nodes that run no showcase agent at all and were never homed on Frame A.
    # Nothing was set wrong; the built-in catalog IS Frame A's and the provisioner sets no
    # override, so the default published a neighbour's shop window. §SHOWCASEOWN fixed this for
    # frames by adding SHOWCASE_CATALOG_JSON and every frame sets it; an operator sets nothing,
    # so the default is what it gets, and a default that names another deployment is a claim.
    # Derived, not hand-set on four nodes: if the catalog is the built-in one and this node is
    # not the deployment it describes, there is no showcase here. A hand-set env would be the
    # §FRAMELIC class again — the half a clean standup silently drops.
    _showcase_state = {"foreign_catalog": False}

    def _showcase_enabled() -> bool:
        if _showcase_state["foreign_catalog"]:
            return False
        return (_os.getenv("SHOWCASE_ENABLED", "true") or "true").strip().lower() in ("1", "true", "yes", "on")

    def _showcase_off_sentence() -> str:
        # §MCPTEST30 (V0640): which of the two off states this is, said by every showcase refusal below
        from agentvault_registry.services.showcase_visitor import showcase_off_sentence
        return showcase_off_sentence(bool(_showcase_state["foreign_catalog"]))

    # §MCPTEST30 (V0641, D6-831, agentvault2-66 2026-10-25): a relay only where a deployment names one, and a paid
    # showcase call this frame cannot make is refused up front and listed without a run; the rules live in
    # services/showcase_visitor.py (relay_base, call_refusals: why there, measured on sbx-alpha). These are the wiring.
    from agentvault_registry.services import showcase_visitor as _sv

    def _showcase_relay_base() -> str:
        return _sv.relay_base()

    def _showcase_has_payer() -> bool:
        return bool(_SHOWCASE_CLIENT_ID and _SHOWCASE_CLIENT_SECRET)

    def _showcase_calls_tail() -> str:
        return _sv.calls_tail(_sv.relay_base())

    def _showcase_entry_paid(info: dict) -> bool:
        return _sv.entry_paid(info)

    async def _showcase_call_refusals(keys) -> dict:
        """key -> (HTTP status, sentence) for each showcase entry this frame cannot make a paid call to (the payee is
        asked authorize's own question, routers.a2a_payment.payee_refusal; then whether this frame can pay at all)."""
        keys = list(keys)
        if not any(_sv.entry_paid(_SHOWCASE_AGENTS.get(k) or {}) for k in keys):
            return {}
        from agentvault_registry.routers.a2a_payment import payee_refusal as _payee_refusal
        from agentvault_registry.database import AsyncSessionLocal as _ASLr
        async with _ASLr() as _db:
            return await _sv.call_refusals(_db, keys, agents=_SHOWCASE_AGENTS, dids=_SHOWCASE_DIDS,
                                           has_payer=_showcase_has_payer(), relay=_sv.relay_base(),
                                           payee_refusal=_payee_refusal)

    # §SHOWCASEGATE (2026-09-09) — WHY the visitor rail cannot run here, in ONE place.
    #
    # His report: the OurChat showcase renders on EU/ASIA and does not work, because
    # neither frame has a showcase IDENTITY onboarded. Measured: `/showcase/agents`
    # answers 200 with each frame's own catalog (correct), while `/showcase/onboard`
    # answers 503 `configured:false` — the server already knew. The page mounted the
    # panel anyway, so the reader met a broken demonstration.
    #
    # The gate is RUNTIME and SERVER-DERIVED rather than a frame list in the frontend,
    # because his instruction was that it "should work in future with other frames
    # automatically": a frame that gains an identity tomorrow starts showing the panel
    # with no rebuild, and one that loses it stops. A hardcoded list is the §FRAMELIC
    # class — the half a clean standup silently drops.
    #
    # This returns the REASON, not a bool, because the two states are genuinely
    # different and the endpoint says so on screen: "disabled" is a deployment that
    # switched the showcase off, "unconfigured" is one that has no payer of its own
    # (its service calls still work — they relay). Collapsing them would be the
    # §29e class: a verdict that cannot tell two states apart.
    def _showcase_chat_unavailable_reason():
        """None = the visitor rail can run here; else 'disabled' | 'unconfigured'."""
        from agentvault_registry.services.showcase_visitor import visitor_enabled as _v_en
        if not _showcase_enabled() or not _v_en():
            return "disabled"
        if not (_SHOWCASE_CLIENT_ID and _SHOWCASE_CLIENT_SECRET and _SHOWCASE_AGENT_DID):
            return "unconfigured"
        return None

    # All eleven services stay listed: the page is the shop window, so an agent
    # that runs belongs on it. If one ever stops working it comes off the page
    # deliberately, never by quietly leaving it listed and broken.
    _AGENT_PUBLIC_BASE = _os.getenv("SHOWCASE_AGENT_PUBLIC_BASE", "https://api.theprotocol.cloud/agents")

    async def _fx_pair_rate(native_ccy: str, local_ccy: str):
        """Units of local_ccy per 1 native_ccy, from the ALL-PAIRS rail.
        /fx/rate (singular) prices only AVT/BVT; /fx/rates prices the whole
        triangle, so the singular one silently mis-prices every other pair."""
        if native_ccy == local_ccy:
            return "1"
        import httpx as _hx_mod
        try:
            async with _hx_mod.AsyncClient(timeout=6.0) as _c:
                r = await _c.get("http://localhost:8000/api/v1/teg/fx/rates")
            if r.status_code != 200:
                return None
            d = r.json()
            if not d.get("available"):
                return None
            for pair in d.get("pairs") or []:
                a, b = pair.get("a"), pair.get("b")
                # b_per_a = units of b per 1 a; a_per_b is the reverse.
                if a == native_ccy and b == local_ccy:
                    return str(pair.get("b_per_a"))
                if b == native_ccy and a == local_ccy:
                    return str(pair.get("a_per_b"))
        except Exception as e:
            logger.debug(f"[Showcase] fx/rates lookup failed: {e}")
        return None

    def _local_charge(native_price: str, rate: str, fee_rate: str) -> str:
        """The amount in THIS frame's currency that delivers `native_price` to
        the agent. The FX booth takes a fee off the converted amount, so paying
        the bare number underpays: 0.5 sent as BVT arrives as ~0.41 AVT for a
        0.5 AVT service. Gross up by the fee and round UP, so rounding is never
        at the agent's expense. One helper serves the price list AND the
        authorize call, so what the page quotes is what the payer sends."""
        from decimal import Decimal as _D, ROUND_CEILING as _RC
        fee = _D(fee_rate or "0")
        gross = _D(native_price) * _D(rate) / (_D("1") - fee)
        return str(gross.quantize(_D("0.000001"), rounding=_RC))

    # The DID of each showcase agent, so anything that must ADDRESS one (an
    # OurChat thread, an agent.card, a payee) can. Same set as the showcase
    # payer's counterparty allowlist - deliberately, since these are exactly
    # the parties that identity is permitted to pay.
    _SHOWCASE_DIDS = {
        "weather":   "did:theprotocol:ce1031a8-292b-4ab6-52d9",
        "currency":  "did:cos:75c219c0-376d-3d90-a8e0",
        "news":      "did:cos:a6ce83ca-50dd-3de8-cfcb",
        "ip":        "did:cos:d7bd8c87-8ab3-eca6-75e1",
        "dns":       "did:cos:1bb11097-829d-4093-0d67",
        "timezone":  "did:cos:6210246c-fb86-f347-829b",
        "units":     "did:cos:e87f8b23-3ce7-24e8-16a2",
        "text":      "did:cos:1581f847-92e7-b7e7-3f5b",
        "cron":      "did:cos:f42c0acf-429f-c268-cf06",
        "password":  "did:cos:6d7466bc-c8c1-2bdc-2c9f",
        "converter": "did:theprotocol:efc75ad2-4300-71e9-2450",
    }

    def _svc(host, port, slug, price, name, key=None):
        return {"url": f"http://{host}:{port}/a2a", "public": f"{_AGENT_PUBLIC_BASE}/{slug}/a2a",
                "price": price, "name": name}

    # §SHOWCASEOWN (2026-09-07, his word "showcase shows its own agents"). The dict below is
    # FRAME A's catalog and nothing else: eleven DIDs minted on registry-a, endpoints under
    # api.theprotocol.cloud, and container names (`weather-agent:8055`) that resolve on ONE
    # docker network. A frame stood up fresh inherited all of it and published another frame's
    # agents, priced in another frame's currency, dialling hosts it cannot reach — measured on
    # EU 2026-09-07. A catalog is DATA about this deployment, so it is configuration:
    # SHOWCASE_CATALOG_JSON replaces both maps wholesale when set, and the hardcoded pair below
    # stays as Frame A's default so nothing about registry-a changes.
    #
    # Shape: {"<key>": {"did": "...", "url": "http://host:port/a2a",
    #                   "public": "https://…/a2a", "price": "0.5", "name": "WeatherAgent"}}
    # `public` defaults to <SHOWCASE_AGENT_PUBLIC_BASE>/<key>/a2a when omitted.
    _SHOWCASE_AGENTS = {
        "weather":   _svc("weather-agent", 8055, "weather-agent", "0.5", "WeatherAgent"),
        "currency":  _svc("currency-agent", 8056, "currency-agent", "0.5", "CurrencyAgent"),
        "news":      _svc("news-agent", 8057, "news-agent", "0.5", "NewsAgent"),
        "ip":        _svc("ip-info-agent", 8058, "ip-info-agent", "0.1", "IPInfoAgent"),
        "dns":       _svc("dns-ssl-agent", 8059, "dns-ssl-agent", "1.0", "DnsSSLAgent"),
        "timezone":  _svc("timezone-agent", 8065, "timezone-agent", "0.1", "TimezoneAgent"),
        "units":     _svc("unit-converter-agent", 8066, "unit-converter-agent", "0.1", "UnitConverterAgent"),
        "text":      _svc("text-utility-agent", 8067, "text-utility-agent", "0.1", "TextUtilityAgent"),
        "cron":      _svc("cron-agent", 8068, "cron-agent", "0.1", "CronAgent"),
        "password":  _svc("password-gen-agent", 8069, "password-gen-agent", "0.1", "PasswordGenAgent"),
        "converter": _svc("converter-hub", 8070, "converter-hub", "0.1", "ConverterHub"),
    }

    _catalog_raw = (_os.getenv("SHOWCASE_CATALOG_JSON") or "").strip()
    if _catalog_raw:
        try:
            import json as _json_cat
            _cat = _json_cat.loads(_catalog_raw)
            if not isinstance(_cat, dict) or not _cat:
                raise ValueError("SHOWCASE_CATALOG_JSON must be a non-empty object")
            _dids, _agents = {}, {}
            for _k, _v in _cat.items():
                if not isinstance(_v, dict):
                    raise ValueError(f"entry {_k!r} is not an object")
                for _req in ("did", "url", "price", "name"):
                    if not str(_v.get(_req) or "").strip():
                        raise ValueError(f"entry {_k!r} is missing {_req}")
                _dids[_k] = str(_v["did"]).strip()
                _agents[_k] = {
                    "url": str(_v["url"]).strip(),
                    "public": str(_v.get("public") or f"{_AGENT_PUBLIC_BASE}/{_k}/a2a").strip(),
                    "price": str(_v["price"]).strip(),
                    "name": str(_v["name"]).strip(),
                }
            _SHOWCASE_DIDS = _dids
            _SHOWCASE_AGENTS = _agents
            # §SHOWCASEDID (2026-09-26): a catalog written for this frame (reonboard_showcase.py) prices each agent in
            # THIS frame's currency, from the agent's own card; the built-in catalog below is Frame A's, in AVT.
            _showcase_state["catalog_local"] = True
            logger.info(
                f"[Showcase] catalog from SHOWCASE_CATALOG_JSON: {len(_agents)} agents "
                f"({', '.join(sorted(_agents))})"
            )
        except Exception as _cat_err:
            # REFUSE rather than half-apply. A catalog that parsed halfway would publish a
            # mixture of this frame's agents and Frame A's, which is worse than either.
            logger.error(
                f"[Showcase] SHOWCASE_CATALOG_JSON is set but unusable ({_cat_err}) — "
                f"the showcase stays on the built-in catalog. FIX THE ENV."
            )

    # §CARDLINK — decide whether the built-in (Frame A) catalog belongs to THIS node.
    # The test is the catalog's own advertised host against this node's own public host: a
    # deployment that does not answer on `api.theprotocol.cloud` is not the one those eleven
    # cards describe. `SHOWCASE_CATALOG_JSON` is how a deployment says which agents are its own,
    # so setting it is the way to have a showcase — never a flag that re-enables someone else's.
    if not _catalog_raw:
        from urllib.parse import urlsplit as _usp_sc
        _own = set()
        for _k in ("PUBLIC_UI_URL", "BASE_URL", "PUBLIC_URL"):
            _v = (_os.getenv(_k) or "").strip()
            if _v:
                _h = _usp_sc(_v).hostname if "//" in _v else _v.split("/")[0]
                if _h:
                    _own.add(str(_h).lower())
        _cat_host = (_usp_sc(_AGENT_PUBLIC_BASE).hostname or "").lower()
        if _own and _cat_host and _cat_host not in _own:
            _showcase_state["foreign_catalog"] = True
            logger.warning(
                f"[Showcase] the built-in catalog describes {_cat_host} and this node answers on "
                f"{sorted(_own)} — publishing another deployment's agents would be a false claim, "
                f"so the showcase is OFF here. Set SHOWCASE_CATALOG_JSON to publish this node's own."
            )

    # §SHOWCASEFED 2026-08-25 — THE SESSION RAIL.
    #
    # Hands an anonymous visitor a SHORT-LIVED agent token so the landing page
    # can act on the real network the way the Bridge does with imported
    # credentials: buy a showcase service, buy from an IPO float, and watch the
    # resulting events arrive on the public ledger stream.
    #
    # 🔴 IT TAKES NO AGENT PARAMETER, BY DESIGN. There is exactly one showcase
    # identity per frame, read from this frame's own env. An endpoint that
    # accepted a DID would be a "mint me a token for any agent" oracle, which is
    # the one thing a public rail must never be. The Commander's constraint,
    # stated plainly: only for this one agent identity.
    #
    # WHY HANDING OUT A REAL TOKEN IS SAFE HERE, and it is not a matter of
    # nobody finding it. The showcase identity is CONTAINED at two layers that
    # both pre-date this endpoint:
    #   * IRONKEY bare permissions — it holds exactly {a2a.pay, exchange.ipo}
    #     on top of BASE, and NOT teg.transfer / teg.transfer_xreg. Measured:
    #     a transfer attempt answers 403 "Agent lacks required permission:
    #     teg.transfer". A leaked token can buy demos. It cannot move money.
    #   * a spend policy — max_per_tx / max_per_day / rate_per_hour, enforced on
    #     both showcase paths (a2a_payment.py:420, exchange.py:1057).
    # Plus the per-IP limit below. The blast radius of this token being public
    # is "somebody bought some demos", which is what a showcase is for.
    #
    # The client_secret NEVER leaves the server. Only a minutes-long JWT does,
    # so rotating the identity needs no rebuild and no redeploy of the page.
    @app.post("/api/v1/public/showcase/session", tags=["Showcase"])
    async def showcase_session(request: Request):
        """Issue a short-lived token for THIS frame's one showcase agent (public)."""
        import time as _t, httpx as _hx, uuid as _uid
        if not _showcase_enabled():
            return Response(content=json.dumps({"error": _showcase_off_sentence(), "enabled": False}),
                            status_code=503, media_type="application/json")
        if not (_SHOWCASE_CLIENT_ID and _SHOWCASE_CLIENT_SECRET):
            # Said honestly rather than half-answered: a frame with no payer of
            # its own cannot hand out a session, and the visitor is told which
            # of the two it is. Calls still work there where it names a relay (V0641).
            return Response(
                content=json.dumps({"error": "This registry has no showcase identity configured, so it cannot "
                                             "issue a session. " + _showcase_calls_tail(),
                                    "configured": False}),
                status_code=503, media_type="application/json")

        ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")
        if not await _showcase_budget_ok("session", ip, _SHOWCASE_SESSION_LIMIT, _showcase_session_rate):
            return Response(
                content='{"error":"Too many showcase sessions from this address. Try again later.",'
                        f'"limit":"{_SHOWCASE_SESSION_LIMIT}/hour"}}',
                status_code=429, media_type="application/json")

        try:
            async with _hx.AsyncClient(timeout=15.0) as _c:
                r = await _c.post("http://localhost:8000/api/v1/auth/agent/token",
                                  data={"username": _SHOWCASE_CLIENT_ID,
                                        "password": _SHOWCASE_CLIENT_SECRET})
            if r.status_code != 200:
                logger.warning("[Showcase] session mint failed: %s", r.status_code)
                return Response(content='{"error":"Could not issue a showcase session right now."}',
                                status_code=503, media_type="application/json")
            tok = r.json()
        except Exception as e:
            logger.warning("[Showcase] session mint error: %s", e)
            return Response(content='{"error":"Could not issue a showcase session right now."}',
                            status_code=503, media_type="application/json")

        return {
            "agent_did": _SHOWCASE_AGENT_DID,
            "access_token": tok.get("access_token"),
            "token_type": "bearer",
            "expires_in": tok.get("expires_in"),
            # The visitor's OWN correlation handle. The page tags what it does
            # with this and filters the public ledger to its own work, so one
            # visitor never reads another's session off a SHARED identity.
            # Generated per call and never stored: it is a client-side scope,
            # not an authorization.
            "session_ref": f"scs-{_uid.uuid4().hex[:16]}",
            # Stated, not implied - the page shows these words to the visitor.
            #
            # ⚠ THIS LIST WAS WRONG ONCE AND THE FIX MATTERS. It used to claim
            # the identity "cannot transfer", which was false the moment the
            # agent was given back teg.transfer - and it had to be, because
            # SETTLING A PURCHASE IS A TRANSFER. A disclosure that overstates
            # the containment is worse than none: it teaches a reader to trust
            # a boundary that is not there. What is actually true is narrower
            # and still strong: it may only ever pay the showcase agents, and
            # only in small amounts.
            "scope": ["a2a.pay", "exchange.ipo", "teg.transfer (allowlisted payees only)"],
            "cannot": ["pay any address outside the showcase allowlist",
                       "staking.manage", "authz.delegate", "exchange.trade"],
            "limits": {"max_per_tx": 5.0, "max_per_day": 100.0, "rate_per_hour": 60},
            "shared_identity": True,
            "notice": ("This is a shared demonstration identity. It can buy showcase services and "
                       "AGORA points at launch, and it can pay ONLY the showcase agents - a payment "
                       "to any other address is refused, and every payment is capped. Everything it "
                       "does moves real units on the public ledger, not a simulation."),
        }

    # §SHOWCASEVISITOR 2026-08-25 — THE ONBOARDING RAIL.
    #
    # The Commander's ruling, and it changes the shape of the feature: the
    # onboarding is PART OF THE DEMONSTRATION and must be VISIBLE IN THE CHAT,
    # and it may fire ONLY on a deliberate interaction - a button, or the first
    # click into the composer - "so it doesnt spam".
    #
    # So this endpoint is never called on page load. A visitor who never types
    # gets no agent and costs this registry one static page. A visitor who acts
    # watches an identity be created, bounded, funded and signed in, in four
    # narrated lines, which is a better argument for the platform than the
    # paragraph next to it.
    #
    # It also fixes the ledger. The chat sits beside a live event ledger
    # filtered by the Bridge's own `involvesDids()` predicate (the MINE button).
    # Pointed at a SHARED identity that predicate matches every visitor's
    # events, so the filter was correct and still read as unfiltered. Pointed at
    # an identity belonging to exactly one visitor, "these are the events your
    # actions caused" becomes a true sentence.
    _showcase_onboard_rate: dict = {}  # ip -> {count, start}
    _SHOWCASE_ONBOARD_LIMIT = 5  # agents per hour per IP: this one creates rows AND moves money

    async def _showcase_funder_jwt() -> str:
        """The funder's token, cached in-process. 🔴 It is minted HERE and never
        leaves the server: before this change the browser held it. That single
        move is what makes the funder's `authz.delegate` acceptable."""
        import time as _t, httpx as _hx
        cached = getattr(_showcase_funder_jwt, "_jwt", None)
        ts = getattr(_showcase_funder_jwt, "_ts", 0)
        if cached and (_t.time() - ts) < 1500:
            return cached
        async with _hx.AsyncClient(timeout=15.0) as _c:
            r = await _c.post("http://localhost:8000/api/v1/auth/agent/token",
                              data={"username": _SHOWCASE_CLIENT_ID,
                                    "password": _SHOWCASE_CLIENT_SECRET})
        if r.status_code != 200:
            raise RuntimeError(f"funder token mint failed: {r.status_code}")
        jwt = r.json().get("access_token")
        _showcase_funder_jwt._jwt = jwt
        _showcase_funder_jwt._ts = _t.time()
        return jwt

    @app.post("/api/v1/public/showcase/onboard", tags=["Showcase"])
    async def showcase_onboard(request: Request):
        """Create, scope and fund ONE agent for this visitor (public, deliberate)."""
        import time as _t
        from agentvault_registry.services.showcase_visitor import onboard_visitor as _onboard
        # §SHOWCASEGATE — ONE predicate, shared with public/registry-config, so the
        # panel the console mounts and the rail it then calls cannot disagree.
        _why = _showcase_chat_unavailable_reason()
        if _why == "disabled":
            return Response(content='{"error":"Showcase onboarding is disabled on this deployment.","enabled":false}',
                            status_code=503, media_type="application/json")
        if _why == "unconfigured":
            return Response(
                content=json.dumps({"error": "This registry has no showcase identity configured, so it cannot "
                                             "create a visitor agent. " + _showcase_calls_tail(),
                                    "configured": False}),
                status_code=503, media_type="application/json")

        ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")
        now = _t.time()
        entry = _showcase_onboard_rate.get(ip)
        if not entry or now - entry["start"] > _SHOWCASE_WINDOW:
            _showcase_onboard_rate[ip] = {"count": 1, "start": now}
        else:
            entry["count"] += 1
            if entry["count"] > _SHOWCASE_ONBOARD_LIMIT:
                return Response(
                    content='{"error":"Too many showcase agents from this address. The one you '
                            'already have is still valid.","limit":"'
                            f'{_SHOWCASE_ONBOARD_LIMIT}/hour"}}',
                    status_code=429, media_type="application/json")

        from agentvault_registry.database import AsyncSessionLocal as _ASL_V
        from agentvault_registry.routers.teg_integration import _local_frame_currency as _lfc_v
        try:
            currency = _lfc_v()
        except Exception:  # noqa: BLE001
            currency = "AVT"
        try:
            funder_jwt = await _showcase_funder_jwt()
        except Exception as e:  # noqa: BLE001
            logger.warning("[ShowcaseVisitor] funder token unavailable: %s", e)
            return Response(content='{"error":"Could not reach the showcase agent to create yours."}',
                            status_code=503, media_type="application/json")

        async with _ASL_V() as _db:
            ok, payload = await _onboard(
                _db, funder_jwt, _SHOWCASE_AGENT_DID,
                [d for d in _SHOWCASE_DIDS.values() if d], currency)
        if not ok:
            return Response(content=__import__("json").dumps(payload),
                            status_code=503, media_type="application/json")
        return payload

    @app.get("/api/v1/public/showcase/agents", tags=["Showcase"])
    async def showcase_list_agents():
        """List available showcase services (public, no auth)."""
        if not _showcase_enabled():
            return {"agents": [], "count": 0, "enabled": False,
                    "reason": _showcase_off_sentence()}
        # Price truth (§SHOWCASE-FX, 2026-08-09). The agent's own CARD carries
        # the charge and the currency it is charged in; this endpoint reads the
        # card rather than trusting the local map, so the page cannot drift from
        # what the agent actually bills. The charge is in the HOSTING frame's
        # currency (AVT). A viewer on another frame is quoted in their own
        # currency at the LIVE cross-frame rate, never by relabelling the
        # number: 0.5 AVT is 0.60 BVT, not "0.5 BVT".
        from agentvault_registry.routers.teg_integration import _local_frame_currency as _lfc
        local_ccy = _lfc()

        # Card pricing, one query, by AGENT DID.
        #
        # §FRAMELIC (2026-09-07, findings row 148) — this keyed on the lowercase agent NAME and
        # selected EVERY row in `agent_cards`, natives and MIRRORED FOREIGN cards alike. Agent
        # names are not unique across a federation and showcase agents are named identically on
        # every frame by design, so the moment EU and ASIA federated, ASIA's mirrored
        # `WeatherAgent` (ACU) overwrote EU's own (ECU) in this dict and EU's landing page quoted
        # a currency it does not issue. It passed every check before federation and broke the
        # instant the pair joined — the §FOREIGNACT class exactly: a label attached to a price,
        # derived from the wrong frame.
        #
        # The catalog already names the exact DID it means, so ask for THAT. A DID is unique per
        # frame by construction, which makes this correct without needing a natives-only filter.
        card_price: dict = {}
        try:
            from sqlalchemy import select as _sq
            from agentvault_registry.database import AsyncSessionLocal as _ASL
            from agentvault_registry.models import AgentCard as _CM
            _by_did = {str(d): k for k, d in _SHOWCASE_DIDS.items() if d}
            async with _ASL() as _db:
                _rows = await _db.execute(
                    _sq(_CM.agent_did, _CM.card_data).where(_CM.agent_did.in_(list(_by_did)))
                    if _by_did else _sq(_CM.agent_did, _CM.card_data).where(False)
                )
                for _did, _cd in _rows.all():
                    _key = _by_did.get(str(_did or ""))
                    if not _key or not isinstance(_cd, dict):
                        continue
                    _p = _cd.get("pricing") or {}
                    if _p.get("base_rate"):
                        card_price[_key] = (str(_p["base_rate"]), str(_p.get("currency") or local_ccy).upper())
        except Exception as _cp_err:
            logger.warning(f"[Showcase] card pricing lookup failed: {_cp_err}")

        # One live quote for the whole list, through the SAME rail a real
        # cross-frame payment would take: smart transfer's indicative FX quote
        # (public /fx/rate + the booth's fee). Hand-rolling the conversion here
        # would let the page and the money disagree.
        fx_quote = None
        fx_rate = fx_as_of = None
        fx_fee = _os.getenv("FX_FEE_RATE", "0.005") or "0.005"
        if any(c != local_ccy for _, c in card_price.values()) or not card_price:
            fx_rate = await _fx_pair_rate("AVT", local_ccy)
            try:
                from agentvault_registry.routers.teg_send import _indicative_fx_quote
                fx_quote = await _indicative_fx_quote("AVT", "1")
                fx_as_of = (fx_quote or {}).get("as_of")
                fx_fee = (fx_quote or {}).get("fee_rate") or fx_fee
            except Exception as _fx_err:
                logger.debug(f"[Showcase] fx quote metadata unavailable: {_fx_err}")

        from decimal import Decimal as _Dec, ROUND_HALF_UP as _RHU
        # §MCPTEST30 (V0641, D6-831): which entries this frame can make a paid call to, asked as the call asks it
        # (authorize's payee rule; a payer or a named relay). The list never fails for a check it could not run: then
        # it says nothing either way rather than guess.
        try:
            _refused = await _showcase_call_refusals(list(_SHOWCASE_AGENTS))
            _checked = True
        except Exception as _rf_err:  # noqa: BLE001
            logger.warning(f"[Showcase] the call check could not run: {_rf_err}")
            _refused, _checked = {}, False
        agents = []
        for key, info in _SHOWCASE_AGENTS.items():
            # §SHOWCASEOWN — the fallback currency is THIS frame's, not a literal 'AVT'.
            # A card-less entry on an ECU frame was quoting ECU prices labelled AVT.
            native_price, native_ccy = card_price.get(key, (info["price"], local_ccy))
            entry = {
                "id": key, "name": info["name"],
                "price": native_price, "currency": native_ccy,
                "price_avt": native_price,  # legacy field, unchanged shape
                # The address the agent's card advertises. Publishing it here
                # lets a reader call the agent directly instead of through this
                # page, which is the point of a discoverable agent.
                "endpoint": info.get("public"),
                # §SHOWCASEFED — the DID, so a caller can ADDRESS this agent
                # (open a thread with it, share its card, pay it) rather than
                # only invoke it through this page.
                "did": _SHOWCASE_DIDS.get(key),
            }
            if _checked:
                # the page offers no run for an entry the call would refuse, and says why in the call's own words
                entry["callable"] = key not in _refused
                entry["reason"] = _refused[key][1] if key in _refused else None
            if native_ccy == local_ccy:
                entry["price_local"], entry["currency_local"] = native_price, local_ccy
            elif fx_rate:
                _q = _Dec(_local_charge(native_price, fx_rate, fx_fee or "0")).quantize(_Dec("0.01"), rounding=_RHU)
                entry.update({
                    "price_local": str(_q), "currency_local": local_ccy,
                    "price_local_exact": _local_charge(native_price, fx_rate, fx_fee or "0"),
                    "fx_rate": fx_rate, "fx_pair": f"{native_ccy}/{local_ccy}",
                    "fx_as_of": fx_as_of, "fx_fee_rate": fx_fee,
                })
            else:
                # No live rate: quote the true charge in its own currency and
                # say the conversion is unavailable. Never relabel the number.
                entry.update({"price_local": None, "currency_local": local_ccy, "fx_unavailable": True})
            agents.append(entry)
        return {"agents": agents, "count": len(agents), "local_currency": local_ccy,
                "fx_rate": fx_rate, "fx_as_of": fx_as_of}

    @app.post("/api/v1/public/showcase/call", tags=["Showcase"])
    async def showcase_call(request: Request):
        """Call a showcase agent service (public, rate-limited per IP, no auth required)."""
        import time as _t, httpx as _hx, uuid as _uid, asyncio as _asyncio
        if not _showcase_enabled():
            return Response(
                content=json.dumps({"error": _showcase_off_sentence(), "enabled": False}),
                status_code=503, media_type="application/json",
            )
        ip = request.headers.get("X-Real-IP", request.client.host if request.client else "unknown")

        # Rate limit check — shared budget across workers (§FINDFIX F4)
        if not await _showcase_budget_ok("call", ip, _SHOWCASE_LIMIT, _showcase_rate):
            return Response(
                content='{"error":"Rate limit exceeded. Try again later.","limit":"50/hour"}',
                status_code=429, media_type="application/json",
            )

        try:
            body = await request.json()
        except Exception:
            return Response(content='{"error":"Invalid JSON"}', status_code=400, media_type="application/json")

        service = body.get("service", "")
        input_data = body.get("input", "")
        task_type = body.get("task_type", "")

        agent_info = _SHOWCASE_AGENTS.get(service)
        if not agent_info:
            return Response(
                content=f'{{"error":"Unknown service: {service}","available":{list(_SHOWCASE_AGENTS.keys())}}}',
                status_code=400, media_type="application/json",
            )

        # §MCPTEST30 (V0641, D6-831): a paid call this frame cannot make is refused here, in the words the catalogue
        # shows (authorize's payee rule; a payer or a named relay), before the agent is dialled and before any relay.
        try:
            _refused = (await _showcase_call_refusals([service])).get(service)
        except Exception as _rf_err:  # noqa: BLE001 - the payment steps below still decide
            logger.warning(f"[Showcase] the call check could not run for {service}: {_rf_err}")
            _refused = None
        if _refused:
            return Response(content=json.dumps({"error": _refused[1], "service": service, "callable": False}),
                            status_code=_refused[0], media_type="application/json")

        # Build A2A request — preprocess inputs to be fault-tolerant
        import re as _re
        raw = str(input_data).strip()
        parts = [{"text": raw}]
        data_part = {"task_type": task_type} if task_type else {}

        if service == "weather":
            # Strip country suffixes — geocoder works better with just city
            city = _re.sub(r',?\s*(germany|deutschland|usa|us|uk|france|japan|china|india|spain|italy|australia|canada|brazil|mexico|russia|turkey|netherlands|sweden|norway|switzerland|austria|poland|belgium|czech|denmark|finland|greece|hungary|ireland|portugal|romania|thailand|vietnam|indonesia|philippines|malaysia|singapore|korea|south\s*korea|new\s*zealand|south\s*africa|egypt|morocco|argentina|chile|colombia|peru|israel|uae|saudi\s*arabia)\s*$', '', raw, flags=_re.IGNORECASE).strip()
            city = _re.sub(r',?\s*\w{2}$', '', city).strip() if ',' in city else city  # Strip 2-letter country codes after comma
            data_part["city"] = city or raw

        elif service == "currency":
            # Parse natural language: "100 USD to EUR", "100", "USD EUR", "convert 50 euros to dollars"
            raw_up = raw.upper()
            # Common currency name mapping
            _cnames = {"DOLLAR": "USD", "DOLLARS": "USD", "EURO": "EUR", "EUROS": "EUR",
                       "POUND": "GBP", "POUNDS": "GBP", "YEN": "JPY", "YUAN": "CNY",
                       "FRANC": "CHF", "FRANCS": "CHF", "RUPEE": "INR", "RUPEES": "INR",
                       "KRONA": "SEK", "KRONE": "NOK", "WON": "KRW", "REAL": "BRL", "REAIS": "BRL"}
            for name, code in _cnames.items():
                raw_up = raw_up.replace(name, code)
            # Try pattern: amount FROM to TO
            m = _re.search(r'(\d+(?:[.,]\d+)?)\s*([A-Z]{3})\s+(?:TO|IN|INTO|->|→)\s*([A-Z]{3})', raw_up)
            if not m:
                # Try: FROM to TO (no amount)
                m2 = _re.search(r'([A-Z]{3})\s+(?:TO|IN|INTO|->|→)\s*([A-Z]{3})', raw_up)
                if m2:
                    data_part["currency_from"] = m2.group(1)
                    data_part["currency_to"] = m2.group(2)
                    data_part["amount"] = 1.0
                else:
                    # Try: just amount + currency (assume USD to EUR)
                    m3 = _re.search(r'(\d+(?:[.,]\d+)?)\s*([A-Z]{3})?', raw_up)
                    if m3:
                        amt = float(m3.group(1).replace(',', '.'))
                        frm = m3.group(2) or "USD"
                        data_part["currency_from"] = frm
                        data_part["currency_to"] = "EUR" if frm == "USD" else "USD"
                        data_part["amount"] = amt
                    else:
                        data_part["currency_from"] = "USD"
                        data_part["currency_to"] = "EUR"
                        data_part["amount"] = 1.0
            else:
                data_part["amount"] = float(m.group(1).replace(',', '.'))
                data_part["currency_from"] = m.group(2)
                data_part["currency_to"] = m.group(3)
            data_part["task_type"] = "currency_convert"
            data_part["query"] = raw

        elif service == "ip":
            # Clean IP — strip "ip:", whitespace, etc.
            ip_clean = _re.sub(r'^(?:ip[:\s]+|address[:\s]+)', '', raw, flags=_re.IGNORECASE).strip()
            data_part["ip"] = ip_clean or raw

        elif service == "dns":
            # Clean domain — strip protocols, paths, whitespace
            domain = _re.sub(r'^(?:https?://)', '', raw, flags=_re.IGNORECASE).split('/')[0].strip().rstrip('.')
            data_part["domain"] = domain or raw

        elif service == "timezone":
            # Strip country suffixes same as weather
            city = _re.sub(r',?\s*(germany|deutschland|usa|us|uk|france|japan|china|india|spain|italy|australia|canada|brazil)\s*$', '', raw, flags=_re.IGNORECASE).strip()
            data_part["city"] = city or raw

        elif service == "units":
            data_part["query"] = raw

        elif service == "text":
            data_part["text"] = raw

        elif service == "cron":
            # Auto-detect if it's an expression or description
            if _re.match(r'^[\d*/,\-]+(\s+[\d*/,\-]+){4}$', raw.strip()):
                data_part["expression"] = raw.strip()
                data_part["task_type"] = "cron_explain"
            else:
                data_part["description"] = raw

        elif service == "password":
            ptype = raw.lower().strip()
            data_part["type"] = ptype if ptype in ("password", "passphrase", "api_key", "uuid") else "password"
            data_part["length"] = 24

        elif service == "converter":
            data_part["converter"] = task_type
            data_part["content"] = raw

        if data_part:
            # Put data part FIRST so agents that iterate parts pick structured data before raw text
            parts.insert(0, {"data": data_part})

        payload = {
            "jsonrpc": "2.0",
            "id": f"showcase-{_uid.uuid4().hex[:8]}",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": parts}},
        }

        try:
            async with _hx.AsyncClient(timeout=30.0) as client:
                # ── Step 1: Authenticate showcase agent (cached) ──
                _showcase_jwt_cache = getattr(showcase_call, '_jwt_cache', None)
                _cache_ts = getattr(showcase_call, '_jwt_ts', 0)
                if not _showcase_jwt_cache or (_t.time() - _cache_ts > 1800):  # refresh every 30 min
                    auth_resp = await client.post(
                        "http://localhost:8000/api/v1/auth/agent/token",
                        data=f"grant_type=password&username={_SHOWCASE_CLIENT_ID}&password={_SHOWCASE_CLIENT_SECRET}",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if auth_resp.status_code == 200:
                        _showcase_jwt_cache = auth_resp.json().get("access_token")
                        showcase_call._jwt_cache = _showcase_jwt_cache
                        showcase_call._jwt_ts = _t.time()
                    else:
                        logger.warning(f"[Showcase] Agent auth failed: {auth_resp.status_code}")
                        _showcase_jwt_cache = None

                # ── Step 2: Get payment token ──
                payment_token = None
                pay_refused = None   # (status, words) when authorize was asked and refused (V0641)
                # bound BEFORE the branch: the reply reads both on every path, and an agent that answers without a
                # token (PAYMENT_REQUIRED off) would otherwise reach it with neither bound (§SHOWCASEDID)
                charge_amount = agent_info["price"]
                charge_ccy = "AVT"
                if _showcase_jwt_cache:
                    # Find target agent DID from registry
                    _svc_did_map = getattr(showcase_call, '_did_map', {})
                    # §SHOWCASEDID (2026-09-26): the catalog names the exact DID each service means (§FRAMELIC row 148
                    # made the LIST read it). This path matched by NAME across every card, natives and MIRRORED foreign
                    # cards alike, and paid the first match: measured on EU, weather and timezone paid ASIA's mirrored
                    # agents, so EU's own agents refused the token (402) while ip and password happened to match EU's
                    # own. The catalog's DID first; the name lookup only for an entry without one, over this frame's
                    # OWN agents (a mirrored card has no `agents` row here).
                    target_did = _SHOWCASE_DIDS.get(service) or _svc_did_map.get(service)
                    if not target_did:
                        # Look up agent DID by name via AgentCard.card_data
                        from sqlalchemy import select as _sq_select
                        from agentvault_registry.database import AsyncSessionLocal as _ASL
                        from agentvault_registry.models import AgentCard as _CardModel, Agent as _AgentModel
                        async with _ASL() as _lookup_db:
                            _cards = await _lookup_db.execute(
                                _sq_select(_CardModel.agent_did, _CardModel.card_data)
                                .where(_CardModel.agent_did.isnot(None))
                                .where(_CardModel.agent_did.in_(_sq_select(_AgentModel.did)))
                            )
                            _target_name = agent_info["name"].lower().replace(" ", "")
                            for _row in _cards.all():
                                _cd = _row[1] or {}
                                _cname = (_cd.get("name") or "").lower().replace(" ", "")
                                if _cname and _target_name in _cname:
                                    target_did = _row[0]
                                    break
                        if target_did:
                            _svc_did_map[service] = target_did
                            showcase_call._did_map = _svc_did_map

                    # The agent bills in ITS currency (the card's). If this frame
                    # settles in another, authorize the grossed-up local amount so
                    # the agent nets its full price after the FX booth's fee.
                    try:
                        from agentvault_registry.routers.teg_integration import _local_frame_currency as _lfc2
                        _local = _lfc2()
                        if _showcase_state.get("catalog_local"):
                            charge_ccy = _local   # §SHOWCASEDID: priced in this frame's currency already
                        elif _local != charge_ccy:
                            _pair = await _fx_pair_rate(charge_ccy, _local)
                            _fee = _os.getenv("FX_FEE_RATE", "0.005") or "0.005"
                            if _pair:
                                charge_amount = _local_charge(agent_info["price"], _pair, _fee)
                                charge_ccy = _local
                                logger.info(f"[Showcase] {service}: {agent_info['price']} AVT billed as {charge_amount} {_local} (pair rate {_pair}, fee {_fee})")
                    except Exception as _ce:
                        logger.warning(f"[Showcase] local charge conversion failed, sending native amount: {_ce}")

                    if target_did:
                        try:
                            pay_resp = await client.post(
                                "http://localhost:8000/api/v1/a2a-payment/authorize",
                                json={
                                    "target_agent_did": target_did,
                                    "amount": charge_amount,
                                    "ttl_seconds": 300,
                                },
                                headers={"Authorization": f"Bearer {_showcase_jwt_cache}"},
                            )
                            if pay_resp.status_code == 200:
                                payment_token = pay_resp.json().get("token")
                            else:
                                from agentvault_registry.services.service_purchase import error_words as _ew
                                try:
                                    _pw = _ew(pay_resp.json())
                                except Exception:  # noqa: BLE001
                                    _pw = ""
                                pay_refused = (pay_resp.status_code, _pw or f"HTTP {pay_resp.status_code}")
                        except Exception as pay_err:
                            logger.warning(f"[Showcase] Payment auth failed: {pay_err}")

                # §MCPTEST30 (V0641, D6-831): this frame's own refusal is the answer to a paid call. Dialling the agent
                # without a token only fetched its 402, which the relay below then handed to another frame.
                if pay_refused is not None and _showcase_entry_paid(agent_info):
                    _pst, _pwhy = pay_refused
                    return Response(
                        content=json.dumps({"error": f"This frame could not pay for the call: {_pwhy}",
                                            "service": service, "payment_status": "authorize_refused"}),
                        status_code=_pst if 400 <= _pst < 500 else 502, media_type="application/json")

                # ── Step 3: Call agent A2A (with payment token if available) ──
                a2a_headers = {}
                if payment_token:
                    a2a_headers["X-Payment-Token"] = payment_token
                    # 🔴 The issuer must name the registry that MINTED this token.
                    # Hardcoding localhost:8000 is correct ONLY when this registry is
                    # also the agent's home. A cloud-op with its own showcase funder
                    # mints locally and then reaches the agent's RESIDENT endpoint
                    # (same docker host), so it was telling the agent to verify at the
                    # AGENT's registry — where the token does not exist. The agent
                    # answered "Token not found" and the reservation was released, so
                    # nobody was charged; the call simply never worked from an op.
                    # This registry's own declared public URL is the honest answer, and
                    # the SDK verifier accepts any issuer in the agent's trusted list.
                    a2a_headers["X-Payment-Issuer"] = (
                        _os.getenv("SHOWCASE_PAYMENT_ISSUER", "").strip()
                        or "http://localhost:8000"
                    )

                # Resident endpoint first (the hosting frame). If this registry
                # is not the host, the agent is unreachable by docker name, so
                # call the PUBLIC endpoint its card advertises and present THIS
                # registry as the payment issuer: the SDK verifier accepts a
                # foreign issuer that appears in the agent's trusted list, so a
                # frame pays in its OWN currency and the cross-frame leg settles
                # through smart transfer. No relay, no prepaid Frame-A purse.
                try:
                    resp = await client.post(agent_info["url"], json=payload, headers=a2a_headers)
                except (_hx.ConnectError, _hx.ConnectTimeout):
                    pub = agent_info.get("public")
                    if not pub:
                        raise
                    issuer = _os.getenv("SHOWCASE_PAYMENT_ISSUER", "").strip()
                    if issuer:
                        a2a_headers["X-Payment-Issuer"] = issuer
                    logger.info(f"[Showcase] {service}: resident endpoint unreachable, calling public endpoint as issuer {issuer or '(unset)'}")
                    resp = await client.post(pub, json=payload, headers=a2a_headers)
                resp.raise_for_status()
                result = resp.json()

                # Extract artifacts
                r = result.get("result", {})
                artifacts = r.get("artifacts", [])
                state = r.get("state", "?")

                # ── Step 4: Settle payment and report the TRUE outcome ──
                # Bound BEFORE the branch: the response reads them even when the
                # task did not complete, and an unbound name is a 502 that looks
                # like the agent failed.
                native_ccy_for_log = charge_ccy
                settle_status = ""
                task_id = ""
                settle_tx = ""
                settled = False
                if payment_token and _showcase_jwt_cache and "COMPLETED" in str(state):
                    try:
                        task_id = r.get("id", "")
                        settle_resp = await client.post(
                            "http://localhost:8000/api/v1/a2a-payment/settle",
                            json={"token": payment_token, "task_id": task_id, "success": True},
                            headers={"Authorization": f"Bearer {_showcase_jwt_cache}"},
                        )
                        # `paid` must mean SETTLED, not accepted. Settlement is
                        # asynchronous: the endpoint answers 200 with
                        # status="settling" and a background task does the
                        # transfer, so trusting the status code reported a
                        # payment that had not happened (and, while the payer
                        # lacked teg.transfer_xreg, never would). Read the
                        # terminal state; poll briefly because the cross-frame
                        # FX leg takes about a second.
                        settle_status = ""
                        settle_tx = ""
                        if settle_resp.status_code == 200:
                            try:
                                _sj = settle_resp.json()
                                settle_status = str(_sj.get("status", "")).lower()
                                settle_tx = str(_sj.get("transaction_id") or _sj.get("tx") or "")
                            except Exception:
                                settle_status = ""
                            token_id = None
                            try:
                                token_id = settle_resp.json().get("token_id")
                            except Exception:
                                pass
                            if settle_status == "settling" and token_id:
                                for _ in range(6):
                                    await _asyncio.sleep(0.5)
                                    try:
                                        _tr = await client.get(
                                            "http://localhost:8000/api/v1/a2a-payment/my-tokens",
                                            headers={"Authorization": f"Bearer {_showcase_jwt_cache}"},
                                        )
                                        if _tr.status_code != 200:
                                            continue
                                        for _tok in _tr.json() or []:
                                            # The listing keys it as token_id, not id.
                                            if str(_tok.get("token_id")) == str(token_id):
                                                settle_status = str(_tok.get("status", "")).lower()
                                                break
                                    except Exception:
                                        continue
                                    if settle_status not in ("settling", "consumed", ""):
                                        break
                        settled = settle_status == "settled"
                        if settled:
                            logger.info(f"[Showcase] Payment settled for {service}: {agent_info['price']} {native_ccy_for_log}")
                        else:
                            logger.warning(f"[Showcase] Payment NOT settled for {service}: status={settle_status or settle_resp.status_code}")
                    except Exception as settle_err:
                        logger.warning(f"[Showcase] Settlement failed: {settle_err}")

                return {
                    "service": service,
                    "agent": agent_info["name"],
                    "price_avt": agent_info["price"],
                    "state": state,
                    "result": artifacts[0].get("data", {}) if artifacts else r,
                    "paid": settled,
                    # The honest detail behind the boolean: "settled" means the
                    # transfer completed, anything else says so plainly.
                    "payment_status": (settle_status or "not_attempted") if payment_token else "no_payment_token",
                    # What the agent bills, and what this frame actually sent.
                    "charged_amount": charge_amount, "charged_currency": charge_ccy,
                    # §SHOWCASEFED — CORRELATION HANDLES, so a visitor's page can
                    # scope the public ledger to work IT caused.
                    #
                    # Without these the only way to say "this event is mine" is
                    # "it involves the showcase agent and happened just now" —
                    # and since the identity is SHARED, two visitors clicking in
                    # the same second would read each other's work as their own.
                    # That is precisely the cross-visitor leak this feature must
                    # not have, so the scoping is made exact rather than
                    # temporal: the page matches on ids it was handed.
                    #
                    # They identify work, not authority: knowing a task id grants
                    # nothing, and the ledger they are matched against is public
                    # to everyone anyway.
                    "task_id": task_id or None,
                    "settle_tx": (settle_tx or None),
                    # D6-835 (agentvault2-66's find): the amount and unit charged, not the catalog price in AVT on every frame
                    "showcase_note": f"This call used {charge_amount} {charge_ccy} on TheProtocol. Build your own: pip install theprotocol-orchestrator",
                }
        except Exception as e:
            # The service agents are residents of ONE frame (their A2A endpoints
            # are that frame's internal network). A non-hosting frame cannot
            # resolve them, and issuing a payment token here would be worthless
            # to an agent that validates against the hosting frame. Rather than
            # report a dead service, relay the call to the hosting frame's own
            # public showcase rail and SAY SO in the response: the visitor is
            # told the service runs elsewhere and their frame reached it over
            # the public network. §MCPTEST30 (V0641, D6-831): only to a frame
            # this deployment NAMES in SHOWCASE_RELAY_URL; none by default
            # (_showcase_relay_base above says why).
            relay_base = _showcase_relay_base()
            unreachable = isinstance(e, (_hx.ConnectError, _hx.ConnectTimeout))
            # §SHOWCASEFED (2026-08-25) — THE RELAY MODELLED THE WRONG FAILURE.
            # It fired only when the agent could not be REACHED. But a frame
            # with no showcase payer of its own reaches the agent perfectly
            # well over the public endpoint and fails on PAYMENT: the agent
            # answers 402, which httpx raises as HTTPStatusError, not
            # ConnectError. So the relay never fired for the failure every
            # cloud-op actually hits, and all 13 of them served a 502 for a
            # service that was reachable the whole time. Measured on op-doha:
            #   auth 401 (the fallback credential belongs to another frame)
            #   -> no payment token -> public endpoint -> 402 -> 502.
            # "Cannot pay for it" and "cannot reach it" are the same fact from
            # the visitor's side: THIS frame cannot complete the call, and the
            # hosting frame can. Both relay.
            cannot_pay = (isinstance(e, _hx.HTTPStatusError)
                          and getattr(e, "response", None) is not None
                          and e.response.status_code == 402)
            # A relayed call never relays again: the hosting frame is the end of
            # the chain, so a misconfigured base can cost one hop, never a loop.
            already_relayed = request.headers.get("X-Showcase-Relay") == "1"
            if relay_base and (unreachable or cannot_pay) and not already_relayed:
                try:
                    async with _hx.AsyncClient(timeout=35.0) as _relay:
                        rr = await _relay.post(
                            f"{relay_base}/api/v1/public/showcase/call",
                            json={"service": service, "input": input_data, "task_type": task_type},
                            headers={"X-Showcase-Relay": "1"},
                        )
                    if rr.status_code == 200:
                        data = rr.json()
                        data["relayed_from"] = relay_base
                        data["relay_reason"] = "payment" if cannot_pay else "unreachable"
                        data["showcase_note"] = (
                            f"{data.get('showcase_note', '')} This agent resides on another frame; "
                            "this registry reached it over the public network."
                        ).strip()
                        return data
                    logger.warning(f"[Showcase] relay for {service} returned {rr.status_code}")
                except Exception as relay_err:
                    logger.warning(f"[Showcase] relay for {service} failed: {relay_err}")
            logger.error(f"[Showcase] {service} call failed: {e}")
            return Response(
                content=f'{{"error":"Service temporarily unavailable: {service}","detail":"{str(e)[:100]}"}}',
                status_code=502, media_type="application/json",
            )


    # ─── §CARDLINK (2026-09-08) — SERVE THE ADDRESS THE CARD ADVERTISES ────────────────
    #
    # His report: *"the link on the registry cards are wrong … dont provide a link for them
    # that is dead."* Measured: every showcase card on EU and ASIA published
    # `https://<frame>.theprotocol.cloud/agents/<slug>/a2a` and every one of them answered 404.
    #
    # The address was NOT invented. It is Frame A's convention — and Frame A implements it with
    # ELEVEN HAND-ADDED `location /agents/<slug>/` blocks in `/etc/nginx/sites-enabled/
    # api-theprotocol`, proxying to host ports 8060-8070. The frame template renders none of
    # them, so every frame stood up from it published the convention with no routing behind it.
    # The §FRAMELIC class again: a capability whose halves live in different places loses the
    # ones nobody templated, and nothing errors — the address simply is not there.
    #
    # ⚠ THE AGENTS ARE REAL AND RUNNING. EU and ASIA each run all eleven containers
    # (`eu-weather-agent:8055` … `eu-converter-hub:8070`), reachable on the frame's own docker
    # network and nowhere else — they publish no host ports. So the honest fix is not to
    # re-point the cards at some other rail; it is to make the advertised address TRUE. The
    # registry is already on that network and is already what `location /` proxies to, so it
    # can serve the convention itself: no vhost edit, nothing for a standup to drop, and the
    # same answer on every frame including any future one.
    #
    # ⚠ NOT AN OPEN PROXY. The slug map is derived from the CATALOG's own `public` URLs, so the
    # only reachable targets are the entries this deployment publishes — a fixed allowlist, and
    # by construction it serves exactly the addresses the cards claim and no others.
    # Frame A is unaffected: its nginx matches `/agents/<slug>/` first and never reaches here.
    def _showcase_slug_map() -> dict:
        """advertised slug -> catalog key, read from each entry's own `public` URL.

        Derived, never guessed: if an entry's `public` is not `…/agents/<slug>/a2a` it is not
        served here at all, because then the registry does not know what address that agent
        claims and inventing one is the defect this closes.
        """
        from urllib.parse import urlsplit as _usp
        out = {}
        for _k, _info in _SHOWCASE_AGENTS.items():
            _pub = str((_info or {}).get("public") or "")
            if not _pub:
                continue
            _parts = [p for p in _usp(_pub).path.split("/") if p]
            if len(_parts) == 3 and _parts[0] == "agents" and _parts[2] == "a2a":
                out[_parts[1]] = _k
        return out

    _SHOWCASE_SLUGS = _showcase_slug_map()
    if _SHOWCASE_SLUGS:
        logger.info(f"[Showcase] serving {len(_SHOWCASE_SLUGS)} advertised agent addresses "
                    f"at /agents/<slug>/a2a ({', '.join(sorted(_SHOWCASE_SLUGS))})")

    @app.api_route("/agents/{slug}/a2a", methods=["GET", "HEAD", "POST", "OPTIONS"],
                   include_in_schema=False)
    async def showcase_agent_address(slug: str, request: Request):
        """The per-agent address published on every showcase card, served by the registry.

        A transparent pass-through to the agent's own A2A endpoint: the agent answers, so an
        unpaid call gets the agent's own 402 exactly as it does on Frame A. The registry adds
        no payment logic here — `/api/v1/public/showcase/call` is the demo rail and stays
        separate; this is the address a caller integrating against the CARD dials.
        """
        import httpx as _hx, json as _json
        if not _showcase_enabled():
            return Response(content=json.dumps({"error": _showcase_off_sentence()}),
                            status_code=404, media_type="application/json")
        _key = _SHOWCASE_SLUGS.get(slug)
        if not _key:
            # Honest, and it names the population rather than only saying no.
            return Response(
                content=('{"error":"No agent is published at this address on this registry.",'
                         f'"slug":"{slug[:64]}","published":{_json.dumps(sorted(_SHOWCASE_SLUGS))}}}'),
                status_code=404, media_type="application/json")
        _upstream = str((_SHOWCASE_AGENTS.get(_key) or {}).get("url") or "")
        if not _upstream:
            return Response(content='{"error":"This agent has no endpoint configured."}',
                            status_code=502, media_type="application/json")
        if request.method in ("GET", "HEAD", "OPTIONS"):
            # The A2A endpoint is JSON-RPC over POST. Answering 405 (not 404) is the difference
            # between "wrong method here" and "nothing here" — and it is what makes a probe able
            # to tell an address that EXISTS from one that does not.
            return Response(content='{"error":"This endpoint accepts POST (JSON-RPC 2.0)."}',
                            status_code=405, media_type="application/json",
                            headers={"Allow": "POST"})
        try:
            _body = await request.body()
        except Exception:
            _body = b""
        if len(_body) > 256 * 1024:
            return Response(content='{"error":"Request body too large."}',
                            status_code=413, media_type="application/json")
        _fwd = {"Content-Type": request.headers.get("content-type", "application/json")}
        for _h in ("authorization", "x-payment-token", "x-a2a-payment-token", "accept"):
            _v = request.headers.get(_h)
            if _v:
                _fwd[_h] = _v
        try:
            async with _hx.AsyncClient(timeout=45.0, follow_redirects=False) as _c:
                _r = await _c.post(_upstream, content=_body, headers=_fwd)
            return Response(content=_r.content, status_code=_r.status_code,
                            media_type=_r.headers.get("content-type", "application/json"))
        except Exception as _pt_err:
            logger.warning(f"[Showcase] address pass-through {slug} -> {_upstream}: {_pt_err}")
            return Response(
                content=f'{{"error":"The agent behind this address did not answer.","agent":"{_key}"}}',
                status_code=502, media_type="application/json")

    # --- Prometheus Instrumentation (OWL-MON Phase 2) ---
    # Exposes /metrics endpoint with request-level metrics:
    #   http_request_duration_seconds, http_requests_total,
    #   http_request_size_bytes, http_response_size_bytes
    from prometheus_fastapi_instrumentator import Instrumentator
    _instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_group_untemplated=True,
        excluded_handlers=[
            "/metrics", "/health", "/docs", "/redoc",
            "/openapi.json", "/favicon.ico",
            "/assets/.*", "/static/.*",
        ],
    ).instrument(app)
    if metrics_enabled():
        _instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)
        # §SECFIX D6-823: through a proxy (a console vhost), /metrics carries no system balance (core/metrics_public.py)
        from agentvault_registry.core.metrics_public import PublicMetricsMiddleware
        app.add_middleware(PublicMetricsMiddleware)
        logger.info("Prometheus FastAPI instrumentation enabled at /metrics")
    else:
        logger.info("METRICS_ENABLED is off: this registry serves no /metrics")

    # --- §MTLSHOPS V0379: a unix-socket request takes the address its door named (core/client_ip.py) ---
    # Added LAST so it runs FIRST: every middleware and route that reads request.client sees the door's caller. Over TCP
    # every request has a peer, and this changes nothing.
    from agentvault_registry.core.client_ip import SocketPeerClientMiddleware
    app.add_middleware(SocketPeerClientMiddleware)

    # --- Mount Static Files (Direct Access) ---
    if STATIC_DIR.is_dir():
        # Mount the entire dist directory at root to serve assets
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False), name="assets")
        # Also mount at /static for backward compatibility
        app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
        logger.info(f"Mounted static files directory for direct access: {STATIC_DIR}")
    else:
        logger.error(f"Static files directory not found at: {STATIC_DIR}. Direct static file serving will fail.")
    
    # --- Favicon Route ---
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Serve favicon.ico from static directory or return 204 No Content if not found."""
        favicon_path = STATIC_DIR / "favicon.ico"
        if favicon_path.exists():
            return FileResponse(favicon_path)
        # If no favicon exists, return 204 No Content
        return Response(status_code=204)

    # POCKET FRAME P0 (2026-07-07): the PWA service worker MUST be served from the
    # root path so its scope covers /ui (a SW served under /static/ could only
    # control /static/*). Both files are emitted into dist root by vite-plugin-pwa.
    @app.get("/sw.js", include_in_schema=False)
    async def pwa_service_worker():
        p = STATIC_DIR / "sw.js"
        if p.exists():
            return FileResponse(p, media_type="text/javascript",
                                headers={"Cache-Control": "no-cache"})
        return Response(status_code=204)

    @app.get("/push-sw.js", include_in_schema=False)
    async def pwa_push_worker():
        """Web Push handlers, imported by the generated service worker. Must be root-served for
        the same scope reason as sw.js itself."""
        p = STATIC_DIR / "push-sw.js"
        if p.exists():
            return FileResponse(p, media_type="text/javascript",
                                headers={"Cache-Control": "no-cache"})
        return Response(status_code=204)

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def pwa_manifest():
        p = STATIC_DIR / "manifest.webmanifest"
        if p.exists():
            # §FEFRAME W2: the installed app carries THIS frame's name (core/frame_head.render_webmanifest)
            try:
                from agentvault_registry.core import frame_head as _fh
                me = (await _frame_manifest_fields()).get("self")
                body = _fh.render_webmanifest(p.read_text(encoding="utf-8"), me)
                return Response(content=body, media_type="application/manifest+json")
            except Exception as _e_wm:  # noqa: BLE001
                logger.warning(f"[FrameHead] web manifest served as built: {_e_wm}")
            return FileResponse(p, media_type="application/manifest+json")
        return Response(status_code=204)

    @app.get("/registerSW.js", include_in_schema=False)
    async def pwa_register_sw():
        p = STATIC_DIR / "registerSW.js"
        if p.exists():
            return FileResponse(p, media_type="text/javascript",
                                headers={"Cache-Control": "no-cache"})
        return Response(status_code=204)

    # --- UI Routes (Simplified Unified Interface) ---
    
    # IMPORTANT: Specific routes MUST be defined BEFORE catch-all routes
    
    # --- Direct Routes for Views (No /ui prefix) ---
    # Mission Control
    @app.get("/mission-control", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_mission_control(reader: StaticFileReader = Depends()):
        """Serves the main index.html for mission control."""
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    # Discovery
    @app.get("/discovery", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_discovery(reader: StaticFileReader = Depends()):
        """Serves the main index.html for discovery."""
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    # My Agents
    @app.get("/my-agents", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_my_agents(reader: StaticFileReader = Depends()):
        """Serves the main index.html for my agents."""
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    # Other views
    @app.get("/staking", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_staking(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    @app.get("/federation", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_federation(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    @app.get("/api-keys", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_api_keys(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    @app.get("/agent-builder", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_agent_builder(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    @app.get("/teg-wallet", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_teg_wallet(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    @app.get("/settings", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_settings(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    @app.get("/governance", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_governance(reader: StaticFileReader = Depends()):
        try:
            return HTMLResponse(content=await _frame_index_html(reader))
        except:
            raise HTTPException(status_code=500, detail="Could not load UI.")
    
    # --- Authentication Pages (Still Separate for Non-SPA Flow) ---
    @app.get("/ui/register", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_register_ui(reader: StaticFileReader = Depends()):
        """Serves the registration HTML page."""
        try:
            html_content = reader.get_content("register.html")
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Registration page file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load registration page.")

    @app.get("/ui/login", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_login_ui(reader: StaticFileReader = Depends()):
        """Serves the login HTML page."""
        try:
            html_content = reader.get_content("login.html")
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Login page file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load login page.")

    @app.get("/ui/forgot-password", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_forgot_password_ui(reader: StaticFileReader = Depends()):
        """Serves the forgot password HTML page."""
        try:
            html_content = reader.get_content("forgot-password.html")
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Forgot password page file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load forgot password page.")

    @app.get("/ui/recover-with-key", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_recover_with_key_ui(reader: StaticFileReader = Depends()):
        """Serves the recover account with key HTML page."""
        try:
            html_content = reader.get_content("recover-with-key.html")
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Account recovery page file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load account recovery page.")

    @app.get("/ui/set-new-password", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_set_new_password_ui(reader: StaticFileReader = Depends()):
        """Serves the set new password HTML page (used after recovery)."""
        try:
            html_content = reader.get_content("set-new-password.html")
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Set new password page file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load set new password page.")
            
    # Email verification now redirects to /#/email-verification?status=... (Vue SPA route)
    # Old /ui/verify-success and /ui/verify-failed static pages removed.

    @app.get("/ui/reset-requested", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_reset_requested_ui(reader: StaticFileReader = Depends()):
        """Serves the password reset requested confirmation page."""
        try:
            return HTMLResponse(content=reader.get_content("reset-requested.html"))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Reset requested page not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load reset requested page.")

    @app.get("/ui/reset-success", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_reset_success_ui(reader: StaticFileReader = Depends()):
        """Serves the password reset success page."""
        try:
            return HTMLResponse(content=reader.get_content("reset-success.html"))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Reset success page not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load reset success page.")

    @app.get("/ui/reset-failed", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_reset_failed_ui(reader: StaticFileReader = Depends()):
        """Serves the password reset failed page."""
        try:
            return HTMLResponse(content=reader.get_content("reset-failed.html"))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Reset failed page not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load reset failed page.")
            
    @app.get("/auth/verify-email", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def read_verify_email_ui(reader: StaticFileReader = Depends()):
        """Serves the email verification HTML page."""
        try:
            html_content = reader.get_content("verify-email.html")
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Email verification page file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load email verification page.")

    # --- Catch-all UI Route (MUST be defined AFTER specific routes) ---
    @app.get("/ui", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    @app.get("/ui/{path:path}", response_class=HTMLResponse, tags=["UI"], include_in_schema=False)
    async def serve_ui(path: str = "", reader: StaticFileReader = Depends()):
        """Serves the unified HTML interface for all users."""
        try:
            # Always serve the main index.html for SPA routing
            html_content = await _frame_index_html(reader)
            return HTMLResponse(content=html_content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="UI index file not found.")
        except IOError:
            raise HTTPException(status_code=500, detail="Could not load UI.")
        except Exception as e:
            logger.exception(f"Unexpected error in UI route: {e}")
            raise HTTPException(status_code=500, detail="Internal server error loading UI.")

    # --- Legacy Path Redirects ---
    @app.get("/", tags=["Status"], include_in_schema=False)
    async def redirect_root():
        """Redirects root path to the UI."""
        return RedirectResponse(url="/ui", status_code=301)
    
    @app.get("/developer", tags=["Status"], include_in_schema=False)
    async def redirect_developer():
        """Redirects legacy /developer path to unified UI."""
        return RedirectResponse(url="/ui", status_code=301)
    
    @app.get("/ui/developer", tags=["Status"], include_in_schema=False)
    async def redirect_ui_developer():
        """Redirects legacy /ui/developer path to unified UI."""
        return RedirectResponse(url="/ui", status_code=301)
    
    @app.get("/ui/admin", tags=["Status"], include_in_schema=False)
    async def redirect_ui_admin():
        """Redirects legacy /ui/admin path to unified UI."""
        return RedirectResponse(url="/ui", status_code=301)

    # --- Health Check Endpoint ---
    # Dual-mounted: bare /health (canonical) + /api/v1/health (alias for legacy
    # clients that prepend /api/v1 to every path). The alias is hidden from the
    # OpenAPI schema to avoid duplicating the route in docs. Item 15 fix.
    @app.get("/health", tags=["Status"])
    @app.get("/api/v1/health", tags=["Status"], include_in_schema=False)
    async def health_check(request: Request):
        """Simple health check endpoint."""
        health_status = {"status": "ok"}

        # Add Event Store status
        try:
            health_status["event_store"] = get_event_store_status()
        except Exception:
            health_status["event_store"] = {"status": "unavailable"}

        # §TESTBED P5 (2026-09-19): what this image was built FROM, when its build says so (the kit's build.sh writes
        # /app/BUILD_INFO.json): the kit version, the tree's digest and whether it differs from the release, so a test
        # run can record which code it measured. Absent on images built without it.
        _build = _kit_build_info()
        if _build:
            health_status["build"] = _build

        return health_status

    # --- Stack-wide Health Probes (public — used by landing page health wall) ---
    @app.get("/api/v1/stack-health", tags=["Status"])
    async def stack_health():
        """Probe all internal services and return aggregated health status.

        Public endpoint — no auth required.  The landing-page health wall
        calls this instead of trying to reach each service port directly
        (which are internal-only on production).
        """
        import httpx as _httpx

        # Detect operator mode — operators only probe their own local services
        import os as _os_sh
        import re as _re_sh
        _is_federated_operator = _os_sh.environ.get("MINTING_AUTHORITY") == "disabled"

        # Public URLs surfaced to the landing-page tiles. Operators' URLs are
        # discovered via BFS below; only mainframe-core entries need a static
        # map. None = internal-only (TEG / Event Store / OPA / sandbox stack).
        _self_public = (
            _os_sh.environ.get("REGISTRY_PUBLIC_URL")
            or _os_sh.environ.get("BASE_URL")
            or "https://api.theprotocol.cloud"
        ).rstrip("/")

        # §pass62.9 (2026-05-22) — Frame B mainframe detection. Frame B has its
        # own component stack (frame-b-registry / frame-b-teg / frame-b-event-store /
        # frame-b-spire) and does NOT run the Frame A sandbox replicas. Without
        # this branch Frame B's /stack-health returned Frame A's service names +
        # hostnames, so Frame B's MissionControl showed "Registry A" / "TEG Layer A"
        # / 5 sandbox probes — all wrong from Frame B's perspective.
        # Detection via REGISTRY_NAME (already read elsewhere in main.py).
        _is_frame_b = (_os_sh.environ.get("REGISTRY_NAME") or "").strip().lower() in (
            "frame-b", "frame-b-registry", "frame b"
        )

        # §HETZNERLOCK-12 (2026-07-29) — ANY OTHER sovereign frame used to fall into
        # the `else` below and was handed FRAME A's container list as its own. On the
        # Hetzner frame that read as a wall of red (registry-a / teg-layer / event-store
        # / opa do not exist on its network). On FRAME C it was worse: frame-c shares
        # agentvault_main_network, so Frame A's containers ANSWERED and frame-c's
        # Mission Control reported Frame A's stack as healthy — silently wrong, and it
        # looked fine. Frame B only escaped because someone had already hardcoded a
        # second special case for it (§pass62.9).
        #
        # Fix the CLASS: derive the probe set from this registry's OWN name. The frame
        # provisioner names every container `{slug}-<component>` (frame_test_provisioner
        # uses ctx.registry_name as the prefix for -registry / -teg / -event-store /
        # -spire-server), and those names are real network aliases — verified live on
        # both hetzner-frame and frame-c before this shipped.
        #
        # REGISTRY_NAME carries a DISPLAY name ("Hetzner Frame"), so slugify rather than
        # string-match: lowercase, non-alphanumerics to hyphens.
        _reg_name_raw = (_os_sh.environ.get("REGISTRY_NAME") or "").strip()
        # §FRAMEKIT P3.1 (2026-09-12): the slug is READ from TEG_LAYER_URL's host (`<slug>-teg`), the prefix the
        # provisioner gave every container; slugifying the display name is the fallback. "Sandbox Alpha"
        # slugified to sandbox-alpha while its containers are sbx-alpha-*: its own TEG and Event Store tiles
        # read DOWN for nine days (4/7 healthy) with both scraped as up. One rule: core/frame_slug.py.
        from .core.frame_slug import frame_slug as _frame_slug
        _reg_slug = _frame_slug(dict(_os_sh.environ))

        # Frame A's own stack keeps its historical 9-probe list VERBATIM — including the
        # three sandbox registries, which live inside Frame A's compose and legitimately
        # share its containers (registry-test has no `registry-test-teg` of its own).
        # This set is the negative control: if Frame A's tile list changes, the fix is wrong.
        _FRAME_A_SLUGS = {"", "registry-a", "registry-test", "registry-test-b", "registry-test-c"}

        if _is_federated_operator:
            # Operator: probe local services only (registry + TEG)
            services = [
                {"name": "Registry",   "url": "http://localhost:8000/health", "group": "core", "publicUrl": _self_public},
                {"name": "TEG Layer",  "url": "http://teg-layer:8080/health", "group": "core", "publicUrl": None},
            ]
        elif _is_frame_b:
            # Frame B sovereign mainframe — its OWN containers (NOT Frame A's).
            # No sandbox replicas on Frame B. Container hostnames per
            # docker-compose.frame-b.yml. SPIRE probe uses the public
            # `spire-b.theprotocol.cloud` vhost (already exists, serves the
            # SPIRE federation bundle endpoint via nginx; /health returns 200
            # on the same chain so it's a valid liveness signal for the
            # whole SPIRE public surface — DNS + cert + nginx + backend up).
            services = [
                {"name": "Frame B Registry",    "url": "http://localhost:8000/health",                "group": "core", "publicUrl": _self_public},
                {"name": "Frame B TEG",         "url": "http://frame-b-teg:8080/health",              "group": "core", "publicUrl": None},
                {"name": "Frame B Event Store", "url": "http://frame-b-event-store:8200/health",      "group": "core", "publicUrl": None},
                {"name": "Frame B SPIRE",       "url": "https://spire-b.theprotocol.cloud/health",    "group": "core", "publicUrl": None},
            ]
        elif _reg_slug in _FRAME_A_SLUGS:
            # Frame A mainframe: probe core infrastructure
            services = [
                {"name": "Registry A",    "url": "http://registry-a:8000/health", "group": "core", "publicUrl": _self_public},
                {"name": "TEG Layer A",   "url": "http://teg-layer:8080/health", "group": "core", "publicUrl": None},
                {"name": "Event Store",   "url": "http://event-store:8200/health", "group": "core", "publicUrl": None},
                {"name": "OPA Engine",    "url": "http://opa:8181/health", "group": "core", "publicUrl": None},
                # §BRIDGE 2026-08-18 — the sandbox tier is OFF BY DEFAULT by doctrine,
                # so it is expected-down and must never be scored as a spine failure.
                # It carried "group": "core", which is why Frame A's Mission Control
                # read "80.0% GOOD" next to "5 DOWN" (measured live: 19/25 healthy on
                # registry-a, five of the six down being exactly these). `tier` states
                # the truth so no consumer has to match on a name to find it out.
                # §TRUSTCHAIN P4.6 (2026-09-12): the five old-tier sandbox targets (registry-test, registry-test-b,
                # teg-layer-test{,-b}, event-store-test) are gone — that tier left docker-compose.production.yml at
                # §BATCH3 — so probing them reported a dead hostname as an expected-down service. The live
                # sandbox pair (sbx-alpha/-beta) is its own stack with its own targets.
            ]
        else:
            # Any OTHER sovereign frame — probe ITS OWN stack, derived from its slug.
            # Self is always reached over localhost: a frame that cannot answer its own
            # health check has nothing left to report, and this needs no name at all.
            _label = _reg_name_raw or _reg_slug
            # §OPDIST (2026-09-16), the second half of the spine fix: PROBE THE ADDRESS THE APP ITSELF USES. The
            # certificate half landed this morning and these two tiles STILL read DOWN, because the URLs were
            # composed from the slug — `http://<slug>-teg:8080` and `http://<slug>-event-store:8200` — and a T3
            # frame exposes neither to its registry: its TEG is behind `<slug>-nginx-teg:8443` and its store behind
            # its own mTLS gateway. Measured on lantern: the composed names answer nothing, while
            # `${TEG_LAYER_URL}/health` and `${EVENT_STORE_URL}/health` answer 200 with the registry's own SVID —
            # so the frame's PUBLIC status page read `outage` and told visitors its TEG and its ledger were down
            # while both were healthy, and a roll driver refused two correct rolls on the same tiles.
            #
            # The rule was already written a few lines below, for OPA: "Probe the URL the app itself is configured
            # to call". These two did not follow it. A probe's address is a property of the thing measured, not of
            # the name its container happens to carry. The slug form stays as the FALLBACK, because Frame A and the
            # older frames really do reach their TEG and store that way and nothing changes for them.
            _teg_base = (_os_sh.environ.get("TEG_LAYER_URL") or "").strip().rstrip("/")
            _es_base = (_os_sh.environ.get("EVENT_STORE_URL") or "").strip().rstrip("/")
            services = [
                {"name": f"{_label} Registry",    "url": "http://localhost:8000/health",                 "group": "core", "publicUrl": _self_public},
                {"name": f"{_label} TEG",
                 "url": f"{_teg_base}/health" if _teg_base else f"http://{_reg_slug}-teg:8080/health",
                 "group": "core", "publicUrl": None},
                {"name": f"{_label} Event Store",
                 "url": f"{_es_base}/health" if _es_base else f"http://{_reg_slug}-event-store:8200/health",
                 "group": "core", "publicUrl": None},
            ]
            # OPA is optional per frame (frame-c has a sidecar, the Hetzner frame does
            # not). Probe the URL the app itself is configured to call, and add NO tile
            # when there is no sidecar — an always-red tile for a component the frame
            # was never meant to run is noise, not monitoring.
            _opa_url = (_os_sh.environ.get("OPA_URL") or "").strip().rstrip("/")
            if _opa_url:
                services.append(
                    {"name": f"{_label} OPA", "url": f"{_opa_url}/health", "group": "core", "publicUrl": None}
                )

        # Federated registries — discovered via BFS topology.
        # §pass62.9.1 (2026-05-22) — removed `not _is_federated_operator` gate so
        # cloud-ops ALSO populate the "FEDERATED OPERATOR REGISTRIES" panel on
        # their MissionControl (showed 0/0 ONLINE previously). Operators are
        # part of the federation graph — surfacing the peers they know about is
        # the right UX. Self-reference is filtered below via several env vars
        # (cloud-ops have REGISTRY_NAME=cloud-op-op-X but appear in topology
        # as op-X via REGISTRY_FEDERATION_NAME — both must be checked).
        _self_names_lower = {
            (_os_sh.environ.get("REGISTRY_NAME") or "").strip().lower(),
            (_os_sh.environ.get("REGISTRY_FEDERATION_NAME") or "").strip().lower(),
            (_os_sh.environ.get("REGISTRY_DISPLAY_NAME") or "").strip().lower(),
            "local registry",
        }
        _self_names_lower.discard("")
        try:
            from .routers.agent_locations import _compute_trusted_registries
            from .database import AsyncSessionLocal
            async with AsyncSessionLocal() as _db:
                _discovered = await _compute_trusted_registries(_db)
                _seen_names: set = set()
                for _reg in _discovered:
                    _pub = _reg.get("public_url", "")
                    _name = _reg.get("name", "")
                    # §pass62.9.1 — drop self-reference echoes (op-london sees
                    # itself at hopDepth=2 in its own BFS export; don't add a
                    # tile pointing at ourselves).
                    if _name and _name.strip().lower() in _self_names_lower:
                        continue
                    if _pub and _name and _name not in _seen_names:
                        _seen_names.add(_name)
                        # Only surface URL as publicUrl if the hostname is
                        # plausibly browseable from a public client — exclude
                        # internal/local sandbox TLDs which would fail to
                        # resolve outside the docker network.
                        from urllib.parse import urlparse as _up_check
                        _host = (_up_check(_pub).hostname or "").lower()
                        _is_internal_host = (
                            _host.endswith(".internal")
                            or _host.endswith(".local")
                            or _host in ("localhost", "127.0.0.1")
                        )
                        from .core.peer_group import peer_group as _peer_group
                        services.append({
                            "name": _name,
                            "url": f"{_pub}/health",
                            # §RESIDUES C1: a peer FRAME is a frame, not an operator (ASIA sat under `operator` on EU's page)
                            "group": _peer_group(_reg),
                            "publicUrl": None if _is_internal_host else _pub.rstrip("/"),
                        })
        except Exception as _e:
            logger.warning(f"[stack-health] BFS topology discovery failed: {_e}")

        # §SLUGCONVERGE (2026-09-02) — a renamed operator can arrive under its container LABEL (a `discovered`
        # ghost named op-singapore beside the identity op-losangeles: fourteen tiles for thirteen operators,
        # measured on every node). Name each node once, by its IDENTITY, and stamp the label as a hint; the
        # ONE rule lives in core/operator_names.py and the status rail shares it. `drop` = our own faces.
        from .core.operator_names import collapse_to_identity
        services = collapse_to_identity(services, drop=_self_names_lower)

        from .routers.agent_locations import _get_host_public_ip, _needs_dns_bypass

        def _tier_of(svc: dict) -> str:
            """spine = this node's own stack · federation = peers · sandbox = expected-down.

            Explicit `tier` wins; otherwise it derives from the existing group, so
            every probe definition that predates this field still reports honestly.
            """
            t = svc.get("tier")
            if t:
                return str(t)
            from .core.peer_group import tier_for_group as _tier_for_group
            return _tier_for_group(svc.get("group"))

        async def _probe(svc: dict) -> dict:
            import time as _time
            from urllib.parse import urlparse as _urlparse
            t0 = _time.monotonic()
            try:
                url = svc["url"]
                from .core.peer_group import is_peer_group as _is_peer_group
                if _is_peer_group(svc.get("group")) and url.startswith("https://"):
                    parsed = _urlparse(url)
                    host_ip = _get_host_public_ip()
                    if host_ip and parsed.hostname and _needs_dns_bypass(parsed.hostname):
                        connect_url = f"https://{host_ip}{parsed.path or '/health'}"
                        async with _httpx.AsyncClient(
                            timeout=4.0, verify=False,
                            headers={"Host": parsed.hostname}
                        ) as client:
                            r = await client.get(connect_url)
                    else:
                        async with _httpx.AsyncClient(timeout=4.0, verify=False) as client:
                            r = await client.get(url)
                else:
                    # §OPDIST (2026-09-16) — THIS PROBE NEVER PRESENTED A CLIENT CERTIFICATE, and on a T3 frame every
                    # internal hop requires one, so a healthy TEG, event store and OPA all read as DOWN on the frame's
                    # own status page: 3 of 4 spine tiles false, measured on lantern (plain 000 / 000 / 000, the same
                    # three with the registry's SVID 200 / 200 / 200). The §V0378 pass converted the in-frame clients
                    # and missed this one; `es_ssl_helper.get_httpx_verify()` appeared zero times in stack_health.
                    #
                    # The original comment below explained verify=False as a SERVER-cert mismatch workaround, which is
                    # a different axis: the shared context is DUAL-TRUST (SPIRE bundle AND system CAs) and carries the
                    # SVID, so it verifies what verify=False used to skip AND presents what the hop now demands.
                    # §pass62.9 (2026-05-22) — verify=False on core probes too.
                    # Some public-host probes (e.g., Frame B SPIRE via spire-b.theprotocol.cloud)
                    # currently hit nginx default-vhost cert mismatches. Probe is internal
                    # (registry → public URL), no security exposure from skipping verify.
                    from .es_ssl_helper import get_httpx_verify as _spine_verify
                    async with _httpx.AsyncClient(timeout=4.0, verify=_spine_verify()) as client:
                        r = await client.get(url)
                ms = round((_time.monotonic() - t0) * 1000)
                return {"name": svc["name"], "status": "healthy" if r.status_code < 400 else "down", "ms": ms, "group": svc.get("group", "core"), "tier": _tier_of(svc), "publicUrl": svc.get("publicUrl"), "infra_label": svc.get("infra_label")}
            except Exception:
                ms = round((_time.monotonic() - t0) * 1000)
                return {"name": svc["name"], "status": "down", "ms": ms, "group": svc.get("group", "core"), "tier": _tier_of(svc), "publicUrl": svc.get("publicUrl"), "infra_label": svc.get("infra_label")}

        results = await asyncio.gather(*[_probe(s) for s in services])
        healthy = sum(1 for r in results if r["status"] == "healthy")
        # §BRIDGE — the headline the landing page should show. `healthy`/`total`
        # stay exactly as they were (other consumers depend on them); these are
        # additive and count only what is SUPPOSED to be up.
        _scored = [r for r in results if r.get("tier") != "sandbox"]
        return {
            "services": list(results),
            "healthy": healthy,
            "total": len(results),
            "scored_healthy": sum(1 for r in _scored if r["status"] == "healthy"),
            "scored_total": len(_scored),
            "sandbox_total": len(results) - len(_scored),
            "timestamp": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        }

    @app.get("/api/v1/public/env-catalog", tags=["Public"])
    async def public_env_catalog():
        """What this registry can choose to run, in the words the application forms show (§FESUITE V0595, his word
        2026-10-11 "we need env setup in the application forms"): every catalog entry (services/env_catalog.py) with its
        options and scope, and this registry's own option read from its env (set / default / unknown, never a guess).
        A frame-scope entry is the frame's: an operator application shows it greyed with this value and cannot choose
        it. Public, like registry-config: what a registry runs is no secret, and the forms are filled in signed out."""
        import os as _os
        from agentvault_registry.services.env_catalog import public_view
        role = "operator" if _os.environ.get("MINTING_AUTHORITY") == "disabled" else "frame"
        return public_view(_os.environ, role)

    @app.get("/api/v1/public/registry-config", tags=["Public"])
    async def public_registry_config():
        """Registry mode configuration. Public — no auth required.
        Used by frontend to conditionally show/hide features based on registry type."""
        import os as _os
        from agentvault_registry.core.journal import journal_enabled as _journal_enabled
        from agentvault_registry.core.legacy_surfaces import surface_enabled as _legacy_surface_on
        from agentvault_registry.routers.liability import liability_mode as _liability_mode
        from agentvault_registry.routers.contract_templates import templates_enabled as _contract_templates_enabled
        from agentvault_registry.routers.sandbox_proxy import configured_sandboxes as _sandbox_proxies
        from agentvault_registry.core.phone_fabric_gate import phone_fabric_enabled as _phone_fabric_enabled
        from agentvault_registry.core.registry_environment import registry_environment as _registry_environment
        is_federated_operator = _os.environ.get("MINTING_AUTHORITY") == "disabled"
        return {
            "is_federated_operator": is_federated_operator,
            "registry_name": _os.environ.get("REGISTRY_NAME", "TheProtocol Registry"),
            # §COCKPIT P1 (2026-08-31) — is the Cockpit DESK live on this registry?
            # A FIELD on the existing public builder, never a new route: the desk's
            # router guard and its sidebar entry must agree, and they can only agree
            # if they read one answer. Default FALSE everywhere (absent env = off),
            # so every node but the frame-c canary is byte-unchanged in behaviour.
            "cockpit_desk_enabled": _os.environ.get("COCKPIT_DESK_ENABLED", "").strip().lower() == "true",
            # §HELLOFRAME (2026-09-19): the applicant's frame page (/frame-kit) and its sidebar entry; off by default
            "frame_kit_enabled": _os.environ.get("FRAME_KIT_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"),
            # D6-841 (agentvault2-5b, 2026-10-25): is the Phone Fabric on here (core/phone_fabric_gate.py,
            # the switch its rails answer 503 without)? Pocket Approvals reads an owner's phone sessions only where it is:
            # once owned agents act through the session (V0641), the read went out on every visit where it is off
            "phone_fabric_enabled": _phone_fabric_enabled(),
            # §FEFRAME W3: can the simulation console run here? The same switch routers/admin_simulation.py enforces
            # (503 without it): the EigenTrust console and its sidebar entry follow it instead of offering controls that
            # every node but the simulation's own refuses
            "simulation_enabled": (_os.environ.get("ADMIN_SIMULATION_ENABLED") or "false").strip().lower() in ("true", "1", "yes"),
            # §HELLOFRAME (2026-09-19, "Ship without it"): the journal is on where the served console carries its
            # media (core/journal.py); an export frame ships none, so its console offers no journal
            "journal_enabled": _journal_enabled(STATIC_DIR),
            # §SHOWCASEGATE (2026-09-09) — can the OurChat showcase panel actually WORK here?
            # Read from `_showcase_chat_unavailable_reason()`, the same predicate
            # `/public/showcase/onboard` refuses on, so the console never mounts a panel whose
            # first call is a 503. Runtime and derived: a frame that gains a showcase identity
            # starts showing it without a rebuild, which is what makes it scale to new frames.
            "showcase_chat_enabled": _showcase_chat_unavailable_reason() is None,
            # §FRESHFRAME (2026-09-14) — this frame's SPIFFE trust domain, so a code sample on the front door
            # (the SDK snippets' trusted_domains) names THIS frame; the card publishes the same value in
            # identity.trust_domain. Empty when the deployment has none configured.
            "trust_domain": (_os.environ.get("SPIRE_TRUST_DOMAIN", "") or "").strip(),
            # §MCPTEST30 (V0644): what this registry states it is (core/registry_environment.py; "production" when
            # unset), so the MCP tester stages a money-moving fixture only where the target itself says "sandbox"
            "environment": _registry_environment(),
            # §DIRFEED (2026-09-06) — the federated INDEX (the Directory), advertised exactly the way the desk and
            # the flare lanes are: an address a browser can reach, plus a flag saying whether this console should
            # offer it beside its own discovery. The flag is FALSE unless an address is configured — a promise
            # with no address is the blank-promise shape, and a node never told about a Directory is unchanged.
            # The index FINDS; the home registry still decides, still serves, and stays the control on screen.
            "directory_url": (_os.environ.get("DIRECTORY_PUBLIC_URL", "") or "").strip(),
            "directory_discovery_enabled": (
                _os.environ.get("DISCOVERY_VIA_DIRECTORY", "false").strip().lower() in ("1", "true", "yes", "on")
                and bool((_os.environ.get("DIRECTORY_PUBLIC_URL", "") or "").strip())
            ),
            # §WALLETAGENT (2026-09-02) — the first agent's grant, stated by the registry itself, so no
            # welcome tile can promise "5k AVT" where the config grants 1000 or nothing. Same defaults as
            # config.py (enabled, 1000.0); the amount is a string on the wire like every DecimalStr here.
            "genesis_grant_enabled": _os.environ.get("GENESIS_GRANT_ENABLED", "true").strip().lower() in ("true", "1", "yes", "on"),
            "genesis_grant_amount": _os.environ.get("GENESIS_GRANT_AMOUNT", "1000.0").strip(),
            # FX exchange-rate strip visibility — durable, env-driven. Shown when this
            # node has a local FX pool (FX_ENABLED=true: frame-a, frame-c) OR when it
            # routes FX through a parent frame (FX_ROUTE_ENABLED=true: ME operators like
            # doha) — the latter DISPLAY the parent's rate via the server-side proxy in
            # fx_rate_public. Hidden for frame-b + non-FX operators.
            "fx_enabled": (
                _os.environ.get("FX_ENABLED", "").strip().lower() == "true"
                or _os.environ.get("FX_ROUTE_ENABLED", "").strip().lower() == "true"
            ),
            # §HETZNERLOCK-16 (2026-07-30) — does a Frame B/C exist in THIS deployment?
            #
            # The UI used to answer that with `!fx_enabled && !is_federated_operator`,
            # which can never be true for an operator — so EVERY operator rendered the
            # cluster's three ledger panes, including one whose parent is a standalone
            # sovereign frame. op-demo and op-london returned byte-identical config, so
            # the frontend could not tell them apart even in principle.
            #
            # The honest signal is whether this registry is actually CONFIGURED to reach
            # a second/third frame's EventStore. It is derived from live config, never a
            # name match or a role flag, so it is correct for a mainframe, a cluster
            # operator, a sovereign frame, and an operator under a sovereign frame alike
            # — including deployments that are not ours at all.
            "multi_frame": bool(
                (_os.environ.get("EVENT_STORE_B_URL", "") or "").strip()
                or (_os.environ.get("EVENT_STORE_C_URL", "") or "").strip()
            ),
            # §FLARESHOP (2026-08-16) — the two cosmetic-flare distribution lanes,
            # advertised the same way fx_enabled is. The frontend needs BOTH to
            # decide what to show: with fiat off, "Become a Backer" has nothing to
            # sell and must gate itself; with the local lane on, the Flare Shop is
            # the way in. Neither flag is a secret — the endpoint is public and a
            # visitor can see what this registry offers before signing up.
            "fiat_onramp_enabled": (
                _os.environ.get("FIAT_ONRAMP_ENABLED", "false").strip().lower() == "true"
            ),
            # §BAFIN (2026-10-01) — is staking live here, and are its rewards (core/staking_gate.py)? The console hides
            # the staking surfaces (nav, route, Pocket, the Senate's stake door) where staking_enabled is false, and
            # every rate where staking_rewards_enabled is false. Both default true: a registry that set neither is unchanged.
            "staking_enabled": _staking_enabled(),
            "staking_rewards_enabled": _staking_rewards_enabled(),
            # §BAFIN — may AGORA distributions be declared here (core/agora_gate.py)? The console hides the door if not.
            "agora_distributions_enabled": _agora_distributions_enabled(),
            # D8 (core/legacy_surfaces.py) — a retired legacy surface is not mounted at all, so its routes answer a plain
            # 404 that names nothing: only this says "retired here" rather than "broken" (the MCP tester's bridge rows on
            # the nightly pair nt261008, whose template retires the bridge, 2026-10-08). Both default true.
            "token_bridge_enabled": _legacy_surface_on("TOKEN_BRIDGE_ENABLED"),
            "legacy_contracts_enabled": _legacy_surface_on("LEGACY_CONTRACTS_ENABLED"),
            # §MEMBERSHIP (2026-10-02) — what weighs a vote here (lock | member) and whether a member's vote is
            # confirmed on a device (off | conditional | required). The console shows the Membership panel and
            # the vote confirmation where these say so (services/membership.py).
            "governance_weight_mode": _membership_weight_mode(),
            "governance_presence_mode": _membership_presence_mode(),
            # §MEMBERSHIP phase B — is the commons open here (seasons, submissions, ballots)? Default false.
            "commons_enabled": _commons_enabled(),
            # §MEMBERSHIP phase D2 — are federation proposals here decided by one ballot per registry? Default off.
            "federation_ballot_mode": _federation_ballot_mode(),
            # §FESUITE (2026-10-10, the operator batch; his word: "operators will choose what they want to run
            # ultimately in frames allowed configuration") — what this registry runs, read from the SAME functions its
            # routes refuse on, so the console says "not run here" instead of asking a route that refuses: liability
            # mandates (off | shadow | enforce; off = the Cockpit Card's routes answer 404), the contract template
            # library (off = 503), and which sandbox registries the /sandbox/{a,b} proxy reaches (none = 503).
            "liability_mode": _liability_mode(),
            "contract_templates_enabled": _contract_templates_enabled(),
            "sandbox_proxy": _sandbox_proxies(),
            "flare_local_purchase_enabled": (
                _os.environ.get("FLARE_LOCAL_PURCHASE_ENABLED", "false").strip().lower()
                in ("1", "true", "yes", "on")
            ),
            # The frame's settlement currency, so a price can be rendered without a
            # second round trip (same source of truth as the FX desk: FRAME_CURRENCY).
            "local_currency": (_os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT",
            # §FEFRAME W2 (2026-10-01) — THE FRAME MANIFEST: who this registry is (`self`) and who its federation peers
            # are (`peers`), from one resolver over the ACTIVE peer rows and their verified cards
            # (core/federation_view.py). The console reads identity, peers, currencies and ledger sockets from here,
            # never from a seed; `multi_frame` now means "this federation has two or more frames" (it meant
            # "EVENT_STORE_B_URL is set" and drew EU's one peer as "Frame B"). An unreadable manifest leaves the old
            # fields and says so (`manifest_version` 0), so a console never guesses a peer.
            **(await _frame_manifest_fields()),
        }

    _frame_head_cache: dict = {"key": None, "html": None}

    async def _frame_index_html(reader) -> str:
        """§FEFRAME W2: index.html with THIS frame's head (core/frame_head.py): title, description, canonical, og:*,
        twitter:* and the frame theme meta. Cached per worker on (the built file, the manifest's self block); any
        failure serves the page as built."""
        html = reader.get_content("index.html")
        try:
            from agentvault_registry.core import frame_head as _fh
            me = (await _frame_manifest_fields()).get("self")
            key = (len(html), hash(html), json.dumps(me, sort_keys=True, default=str) if me else "")
            if _frame_head_cache["key"] != key:
                _frame_head_cache.update(key=key, html=_fh.render_index(html, me))
            return _frame_head_cache["html"]
        except Exception as _e_fh:  # noqa: BLE001
            logger.warning(f"[FrameHead] serving index.html as built: {_e_fh}")
            return html

    async def _frame_manifest_fields() -> dict:
        from agentvault_registry.core import federation_view as _fv
        # bounded: this sits on the console's boot path (registry-config, every SPA route), and a slow database must
        # cost the page its manifest (served as `manifest_version` 0, the console's identity-unknown state), never
        # its load
        try:
            _m = await asyncio.wait_for(_fv.manifest_now(), timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning("[FrameManifest] not built within 3 s: served without it")
            _m = None
        if _m is None:
            return {"manifest_version": 0}
        return {"manifest_version": _m["manifest_version"], "self": _m["self"], "peers": _m["peers"],
                "multi_frame": _m["multi_frame"]}

    # --- Startup and Shutdown Events ---
    @app.on_event("startup")
    async def startup_event():
        """Initialize background tasks on startup."""
        logger.info("Starting up AgentVault Registry...")

        # §COVERAGE 2026-07-26 — count WARNING+ log records by category. The DNS incident ran
        # five hours unseen because every alert watches Δ, health or stuck-state, and the only
        # signal was WARNING-level log volume, which nothing measured. Install FIRST so startup
        # warnings are captured too.
        try:
            from agentvault_registry.services.log_metrics import install as _install_log_metrics
            _install_log_metrics()
        except Exception as _e:
            logger.warning(f"[LogMetrics] not installed (non-fatal): {_e}")

        # §BATCH0911 — the operating-state SINGLETON, seeded idempotently on every boot. The squashed
        # initial migration (0001) creates `registry_operating_state` but the old f036 seed was lost in
        # the squash, so a frame built from the squashed history had NO row until someone opened the
        # CONSUL page (which creates it lazily). Measured 2026-09-11: EU 1 row (its CONSUL page had been
        # photographed), ASIA 0 — the compliance poller logged an ERROR every cycle and the
        # treasury-health monitor returned before counting anything. Every NOT NULL column has a server
        # default, and they are exactly the state every reader assumes for a missing row ('off', 0,
        # false), so the insert changes no decision; ON CONFLICT makes it safe across all workers.
        try:
            from sqlalchemy import text as _t_ops
            from .database import AsyncSessionLocal as _ASL_OPS
            from .models import REGISTRY_STATE_SINGLETON_ID as _OPS_ID
            async with _ASL_OPS() as _db_ops:
                _r_ops = await _db_ops.execute(_t_ops(
                    "INSERT INTO registry_operating_state (id) VALUES (:id) ON CONFLICT (id) DO NOTHING RETURNING id"),
                    {"id": str(_OPS_ID)})
                _created_ops = _r_ops.first() is not None   # a row comes back ONLY when this worker inserted
                await _db_ops.commit()
                if _created_ops:
                    logger.warning("[OperatingState] the singleton row was missing and has been created "
                                   "(defaults: compliance mode off, 0 treasury zero-days)")
        except Exception as _e:
            logger.warning(f"[OperatingState] singleton seed skipped (non-fatal): {_e}")

        # §HETZNERLOCK-14 (2026-07-29) — restore the registry-card icon/avatar from the DB.
        # Their only copy used to be a file inside the BUILT FRONTEND dir, so every container
        # recreate and every image rebuild deleted the operator's logo while card_json kept
        # pointing at it — a broken image with no error in any log. Migration 0141 makes the
        # DB the source of truth; this puts the bytes back on disk. Content-addressed, so it
        # is a no-op on a warm container, and it never raises.
        try:
            from .database import AsyncSessionLocal as _ASL_ICON
            from .routers.admin_registry_card import rehydrate_card_assets as _rehydrate_assets
            async with _ASL_ICON() as _db_icon:
                _n = await _rehydrate_assets(_db_icon)
                if _n:
                    logger.info(f"[RegistryCardAssets] restored {_n} card asset(s) from DB")
        except Exception as _e:
            logger.warning(f"[RegistryCardAssets] rehydrate skipped (non-fatal): {_e}")

        # Initialize Redis for leader election (multi-worker coordination)
        try:
            redis_conn = await get_redis()
            if redis_conn:
                logger.info("Redis connected — leader election enabled for background tasks")
            else:
                logger.info("Redis not available — single-worker mode (all tasks run locally)")
        except Exception as e:
            logger.warning(f"Redis init failed: {e} — single-worker mode")

        # Phase 12.1 (2026-04-28): initialize svid_client before reactors start.
        # The reactor's _ws_url() may call svid_client.get_jwt_svid() during the
        # JWT-SVID handshake mode; that codepath needs SPIFFE_ENDPOINT_SOCKET
        # normalized, which is only done inside svid_client.initialize().
        # Federation_sync used to lazy-init it, but reactors run earlier.
        try:
            from agentvault_registry.identity.svid_client import svid_client
            if not svid_client._initialized:
                if svid_client.initialize():
                    logger.info("svid_client initialized at startup (early for reactors)")
                else:
                    logger.warning("svid_client.initialize() returned False — reactor JWT-SVID mint may fall back")
        except Exception as e:
            logger.warning(f"svid_client startup init failed: {e} — reactor JWT-SVID mint may fall back")

        # Pre-warm the EventStore stats cache so the first browser visit
        # doesn't pay a cold proxy hit. EventStore /stats now reads from
        # an in-process cache (~50ms), so this is fast.
        async def _prewarm_es_stats():
            try:
                await asyncio.sleep(2)  # let EventStore finish booting
                await public_eventstore_stats()
                logger.info("EventStore stats cache pre-warmed (this frame's store)")
            except Exception as _pw_exc:
                logger.debug(f"EventStore stats pre-warm skipped: {_pw_exc}")
        asyncio.create_task(_prewarm_es_stats())

        # Pre-warm the federation topology cache. First user visit to /ui/
        # would otherwise trigger a cold BFS (~4s for 22 operators × 2 hops).
        # With pre-warm, the first /api/v1/public/topology returns instantly
        # from the 60s-TTL cache.
        async def _prewarm_topology():
            try:
                await asyncio.sleep(3)
                await public_topology()
                logger.info("Federation topology cache pre-warmed")
            except Exception as _pw_exc:
                logger.debug(f"Federation topology pre-warm skipped: {_pw_exc}")
        asyncio.create_task(_prewarm_topology())

        # 2026-05-06 — sandbox canary auto-onboard + re-fund.
        # Only runs on registry-test (sandbox A mainframe). Idempotent — safe
        # to run on every boot. Leader-elected via Redis so multiple workers
        # don't race on first-time onboarding (which would create duplicates).
        # Runs as a startup task (post-uvicorn-up) so HTTP self-onboarding
        # works against http://registry-test:8000 / http://localhost:8000.
        async def _run_sandbox_canary_bootstrap():
            import os as _cb_os
            if _cb_os.environ.get("REGISTRY_NAME") != "Registry-Test":
                return
            try:
                # Let the server fully bind before issuing self-loopback HTTP
                await asyncio.sleep(5)
                from .background_tasks.leader import try_acquire_leadership
                got_lock = await try_acquire_leadership("sandbox_canary_bootstrap")
                if not got_lock:
                    logger.info("sandbox_canary_bootstrap: another worker holds lock — skip")
                    return
                from .sandbox_canary_bootstrap import run_bootstrap
                rc = await run_bootstrap()
                logger.info(f"sandbox_canary_bootstrap finished rc={rc}")
            except Exception as _cb_exc:
                logger.warning(f"sandbox_canary_bootstrap startup task failed (non-fatal): {_cb_exc}")
        asyncio.create_task(_run_sandbox_canary_bootstrap())

        # Initialize Event Store integration
        try:
            event_store_initialized = initialize_event_store_integration()
            if event_store_initialized:
                logger.info("Event Store integration initialized - Events will be emitted to Event Store")
            else:
                logger.warning("Event Store integration failed - Registry will operate without event emission")
        except Exception as e:
            logger.error(f"Event Store integration error: {str(e)}")
            logger.warning("Continuing without Event Store integration")
        
        # Start the federation sync worker
        logger.info("Starting federation sync worker")
        await start_federation_sync()

        # §FEFRAME W2 (2026-10-01): the derived CORS allowlist (per worker, not leader-elected: every worker answers
        # preflights) and the peer-manifest read (leader-elected: each ACTIVE peer's own registry-config, for its
        # console address, currency name and ledger socket).
        from agentvault_registry.core.federation_cors import run_refresher as _cors_refresher
        asyncio.create_task(_cors_refresher())
        # §OPLANE (V0614): on a cloud operator every worker keeps its parent frame's federation lane current (the peer
        # table's ACTIVE frame row on the configured parent host): its licence-carrying calls dial it with this node's SVID.
        from agentvault_registry.core.mainframe_gate import is_mainframe as _oplane_is_mainframe
        if not _oplane_is_mainframe():
            from agentvault_registry.core.parent_lane import refresher as _oplane_refresher
            asyncio.create_task(_oplane_refresher())
        from agentvault_registry.background_tasks.federation_manifest_sync import (
            start_federation_manifest_sync,
        )
        asyncio.create_task(start_federation_manifest_sync())

        # W4 (2026-05-05): defunct-card GC. Leader-elected, gated by
        # FEDERATION_CARD_GC_ENABLED env (default off, ship dark).
        from agentvault_registry.background_tasks.federation_card_gc import (
            start_federation_card_gc,
        )
        asyncio.create_task(start_federation_card_gc())

        # Start the algorithmic auditor worker
        logger.info("Starting algorithmic auditor worker")
        auditor_worker.start()
        
        # Start WebSocket metrics updater
        logger.info("Starting WebSocket metrics updater")
        from agentvault_registry.routers.websocket import metrics_updater
        asyncio.create_task(metrics_updater())
        
        # Start metrics processor for real-time metrics collection
        logger.info("Starting metrics processor for agent request tracking")
        asyncio.create_task(metrics_processor())
        
        # Start staking rewards auto-distribution
        logger.info("Starting staking rewards auto-distribution scheduler")
        await start_staking_distributor()

        # AGORA (2026-06-12): exchange settlement worker (self-gates on EXCHANGE_ENABLED)
        logger.info("Starting AGORA exchange settlement worker")
        from agentvault_registry.background_tasks.exchange_settlement import start_exchange_settlement
        await start_exchange_settlement()
        
        # OWL25 Phase 2: Start settlement reconciliation background task
        logger.info("Starting settlement reconciliation task")
        from agentvault_registry.tasks.settlement_reconciliation import settlement_reconciliation_loop
        asyncio.create_task(settlement_reconciliation_loop())
        
        # TITANIUM VAULT D3: Start saga timeout background checker
        logger.info("Starting saga timeout checker")
        await start_saga_timeout_checker()

        # Phase D (2026-05-26): sandbox-only peer activation keeper (band-aid).
        # No-ops on non-sandbox registries (gated by REGISTRY_NAME).
        logger.info("Starting peer activation keeper (sandbox-only band-aid)")
        await start_peer_activation_keeper()

        # §pass36 Option C Phase 3 (2026-05-17): agent_card_pullsync worker.
        # Pulls each native agent's /.well-known/agent-card.json every 6h and
        # reconciles drift. Preserves registry-owned `federation_metadata` +
        # `flare` per ownership split. Gated by AGENT_CARD_PULLSYNC_ENABLED.
        logger.info("Starting agent_card_pullsync worker")
        await start_agent_card_pullsync()

        # §bc2 T2.2 (2026-05-19): broadcast_scheduler — fires admin broadcasts
        # whose scheduled_for has come due. Leader-elected, 30s cadence.
        # Gated REACTOR_BROADCAST_SCHEDULER_ENABLED (default true).
        logger.info("Starting broadcast_scheduler worker")
        await get_broadcast_scheduler().start()

        # §bc2 T2.5 (2026-05-19): broadcast_email_retry_worker — retries
        # `broadcast_email_failed` rows with exponential backoff.
        # Gated REACTOR_BROADCAST_EMAIL_RETRY_ENABLED (default true).
        logger.info("Starting broadcast_email_retry worker")
        await get_broadcast_email_retry_worker().start()
        # §SOVKIT K1 / V0372 (2026-09-14): the durable ledger-emit outbox drainer. K1 deleted the Kafka producer that
        # had buffered the registry's emits through a store restart; the emitter now defers what the store could not
        # take into es_emit_outbox (migration 0178) and this worker re-emits it when the store answers again.
        logger.info("Starting es_emit_outbox drainer")
        await get_es_emit_outbox_drainer().start()
        await get_genesis_grant_retry().start()   # §LEDGERGATE V0598: owed genesis grants, paid once the ledger records
        await get_fiat_credit_retry().start()   # §LEDGERGATE V0599: owed fiat credits, paid with the purchase's own key
        await get_forfeiture_retry().start()   # §LEDGERGATE V0599: owed deletion forfeitures, drained with their own key
        await get_xreg_revoke_retry().start()   # D6-272: cross-registry revokes not yet delivered, sent again
        await get_idempotency_kept_sweeper().start()   # §REPATLANE-8 V0610: expired durable Idempotency-Key records

        # §pass51 (2026-05-20): bundle retention + storage GC workers
        # Gated BUNDLE_RETENTION_ENABLED + BUNDLE_STORAGE_GC_ENABLED (default true).
        try:
            from agentvault_registry.background_tasks.bundle_retention import bundle_retention_worker
            from agentvault_registry.background_tasks.bundle_storage_gc import bundle_storage_gc_worker
            logger.info("Starting bundle_retention worker")
            await bundle_retention_worker.start()
            logger.info("Starting bundle_storage_gc worker")
            await bundle_storage_gc_worker.start()
        except Exception as e:
            logger.warning(f"Bundle workers failed to start (non-fatal): {e}")

        # §NOTIFLOG (2026-07-27): prune the per-decision notification history (mig 0138).
        # Gated NOTIFICATION_LOG_ENABLED (default true) + NOTIFICATION_LOG_RETENTION_DAYS.
        try:
            from agentvault_registry.background_tasks.notification_log_retention import (
                notification_log_retention_worker,
            )
            logger.info("Starting notification_log_retention worker")
            await notification_log_retention_worker.start()
        except Exception as e:
            logger.warning(f"notification_log_retention failed to start (non-fatal): {e}")

        # §MONEY-R43 (2026-09-04): "the treasury is running low" reaches a person BEFORE it
        # reaches a caller. Publishes whether the treasury is below its floor (registry_treasury_low_active; never the
        # balance itself, §SECFIX D6-254) every cycle; notifies the admin
        # audience once on crossing TREASURY_LOW_NOTIFY_THRESHOLD (0 = disabled, today's fleet;
        # the network profile owns it) and once on recovery; org owners/admins likewise for orgs
        # that set `treasury_low_notify_threshold`. Gated TREASURY_LOW_WATCH_ENABLED.
        try:
            from agentvault_registry.background_tasks.treasury_low_watch import (
                treasury_low_watch_worker,
            )
            logger.info("Starting treasury_low_watch worker")
            await treasury_low_watch_worker.start()
        except Exception as e:
            logger.warning(f"treasury_low_watch failed to start (non-fatal): {e}")

        # §RELEASECHANNEL (2026-09-21): the signed release channel, read every 6 h; a newer stable release or a
        # hotfix reaches the admin audience once per version so they can schedule the rollout themselves. Gated
        # RELEASE_CHANNEL_CHECK_ENABLED (default off); registers as DISABLED in the vitals roster when off.
        try:
            from agentvault_registry.background_tasks.release_channel_checker import release_channel_checker
            logger.info("Starting release_channel_checker worker")
            await release_channel_checker.start()
        except Exception as e:
            logger.warning(f"release_channel_checker failed to start (non-fatal): {e}")

        # Canary system Phase 3: continuous synthetic-transaction monitor
        # Self-gates via CANARY_RUNNER_ENABLED env (default false). Only
        # registry-a sets it to true since canary_paths lives only there.
        logger.info("Starting canary runner")
        await start_canary_runner()

        # §pass31 Phase 4 (2026-05-17): IRONHAND revocation propagation drill.
        # Self-gates via REVOCATION_DRILL_ENABLED env (default false).
        # Periodically revokes a dedicated victim agent and measures the
        # /revoked-identities endpoint propagation lag → feeds the
        # canary_ironhand_revocation_propagation_seconds histogram.
        logger.info("Starting revocation drill")
        await start_revocation_drill()

        # Canary system Phase 5: outcome judge (sweeps Redis state, marks pass/fail)
        # Self-gates via CANARY_JUDGE_ENABLED. Only registry-a runs this since
        # canary_test_results lives there.
        logger.info("Starting canary judge")
        await start_canary_judge()

        # Canary system §pass24 (2026-05-16): auto-rebalancer keeps every canary
        # agent above FLOOR_AVT (default 5000). Self-gates via
        # CANARY_REBALANCER_ENABLED (default false). Closes the manual-rebalance
        # gap that caused the 03:00–11:00 UTC paris starvation incident.
        logger.info("Starting canary rebalancer")
        await start_canary_rebalancer()

        # §2026-06-15 Self-healing DB janitor: terminate stuck idle-in-transaction
        # sessions + cancel long lock-waiters (active backstop to the DB-level
        # idle_in_transaction_session_timeout / lock_timeout guards). Leader-elected,
        # env-gated IDLE_TXN_REAPER_ENABLED (default true).
        from agentvault_registry.background_tasks.idle_txn_reaper import start_idle_txn_reaper
        logger.info("Starting idle-txn reaper (self-healing lock/idle-tx janitor)")
        await start_idle_txn_reaper()

        # AAA+ op→op FX router liquidity manager (suspense-account keeper + dead-letter
        # auto-refund). Gated by FX_ROUTER_KEEPER_ENABLED + FX_ROUTER_DID + FX_ENABLED →
        # only acts on reserve frames (registry-a / frame-c); self-skips everywhere else.
        logger.info("Starting FX router keeper")
        await start_fx_router_keeper()

        # Cross-frame FX peg keeper (0092) — holds each @fx_reserve in a [min,target,max]
        # band (ratio-peg, MOVE-ONLY treasury↔reserve, never mints). Gated by
        # FX_RESERVE_KEEPER_ENABLED + FX_ENABLED + DB toggle; self-skips otherwise.
        logger.info("Starting FX reserve peg keeper")
        await start_fx_reserve_keeper()

        # AGORA gateway-float keeper (0096) — keeps each venue's passport gateway solvent
        # (liquid >= outstanding repat obligations + buffer; MOVE-ONLY treasury→gateway via the
        # reward-funding waterfall, never mints) so refund/dividend repats never strand. Gated by
        # GATEWAY_KEEPER_ENABLED + EXCHANGE_PASSPORT_ENABLED + DB toggle; self-skips otherwise.
        logger.info("Starting AGORA gateway-float keeper")
        await start_gateway_float_keeper()

        # §P2.1 AGORA treasury market-maker — two-sided treasury quotes per opted-in listing
        # (Δ-safe, rides place_order). Gated EXCHANGE_ENABLED + TREASURY_MM_ENABLED + per-listing
        # DB row; default OFF, self-skips otherwise.
        logger.info("Starting AGORA treasury market-maker")
        await start_treasury_market_maker()

        # Ledger Forensics scanner — default-OFF (FORENSIC_SCANNER_ENABLED). Read-only
        # inventory + ES detector scan → Open Findings inbox. Self-skips when disabled.
        logger.info("Starting Ledger Forensics scanner")
        await start_forensic_scanner()

        # Canary system Phase 4: per-frame validator reactors (5 event types)
        # Self-gates via CANARY_VALIDATOR_ENABLED (default true cluster-wide —
        # safe because non-canary events fall through to a Redis miss).
        if os.getenv("CANARY_VALIDATOR_ENABLED", "true").lower() == "true":
            from agentvault_registry.background_tasks.reactor_canary_validator import (
                start_all as start_canary_validator,
            )
            logger.info("Starting canary validator reactors (5 event types)")
            asyncio.create_task(start_canary_validator())

        # EventStore WS balance sync (real-time cross-TEG balance updates)
        logger.info("Starting EventStore balance sync worker")
        asyncio.create_task(start_balance_sync())

        # §FRAMELIC row 165 — the BACKSTOP for the same column. The sync above is event-driven,
        # so it is only ever as complete as the event types it subscribes to (row 164 is what
        # happens when that set is wrong). This notices, heals through the same one writer, and
        # WARNS when an agent keeps needing it — which means the real-time path is broken again.
        logger.info("Starting liquid balance reconciler (backstop)")
        asyncio.create_task(start_liquid_balance_reconciler())

        # PB-2 (2026-05-10): Routed-fiat event-sourced settlement reactors.
        # These run UNCONDITIONALLY (not gated by REACTOR_FRAMEWORK_ENABLED)
        # because routed-fiat depends on them. Same approach as
        # eventstore_balance_sync above. Each reactor gates internally on
        # FIAT_GENESIS_REGISTRY (mainframe vs operator role) so only the
        # right side acts on each event. Mirrors prod cross-frame async
        # transfer pattern (CrossFrameInitiated/Settled/Refunded).
        if os.getenv("REACTOR_FIAT_ROUTED_SETTLEMENT_INITIATED_ENABLED", "true").lower() == "true":
            from agentvault_registry.background_tasks.reactor_fiat_routed_settlement_initiated import (
                start as start_reactor_fiat_routed_initiated,
            )
            logger.info("Starting reactor: FiatRoutedSettlementInitiated → operator settle (PB-2 fallback)")
            asyncio.create_task(start_reactor_fiat_routed_initiated())
        else:
            logger.info("Reactor FiatRoutedSettlementInitiated DISABLED via env var")

        if os.getenv("REACTOR_FIAT_ROUTED_SETTLEMENT_COMPLETED_ENABLED", "true").lower() == "true":
            from agentvault_registry.background_tasks.reactor_fiat_routed_settlement_completed import (
                start as start_reactor_fiat_routed_completed,
            )
            logger.info("Starting reactor: FiatRoutedSettlementCompleted → mainframe close-loop (PB-2 fallback)")
            asyncio.create_task(start_reactor_fiat_routed_completed())
        else:
            logger.info("Reactor FiatRoutedSettlementCompleted DISABLED via env var")

        # Phase 10 #3: Redis pub/sub cache invalidation listeners. Each worker
        # subscribes to the relevant channels so admin updates propagate to all
        # workers within milliseconds (eliminates the per-uvicorn-worker stale
        # view window — the existing 60s TTL is the safety net).
        try:
            from agentvault_registry.event_emitter import (
                start_emission_policy_invalidation_listener,
            )
            start_emission_policy_invalidation_listener()
            logger.info("Started emission_policy invalidation listener")
        except Exception as exc:
            logger.warning(
                f"Emission policy invalidation listener startup failed: {exc}"
            )
        # W3 (2026-10-25): the emitted types this frame's policy table has no row for, named at boot (a task: never
        # delays the startup; it reads the table once and logs one line).
        try:
            from agentvault_registry.event_emitter import emission_policy_boot_check
            asyncio.create_task(emission_policy_boot_check())
        except Exception as exc:
            logger.warning(f"Emission policy boot check not started: {exc}")

        # Reactor framework — Phase 1 + Phase 2
        # Master kill switch + per-reactor kill switch, both default ON.
        # Flip any env var + restart to disable without code change.
        if os.getenv("REACTOR_FRAMEWORK_ENABLED", "true").lower() == "true":
            # Phase 1: PeerRegistryDeactivated → TEG partner cleanup
            if os.getenv("REACTOR_PEER_DEACTIVATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_peer_deactivated import (
                    start as start_reactor_peer_deactivated,
                )
                logger.info(
                    "Starting reactor: PeerRegistryDeactivated → TEG partner cleanup"
                )
                asyncio.create_task(start_reactor_peer_deactivated())
            else:
                logger.info("Reactor PeerRegistryDeactivated DISABLED via env var")

            # §bc3 T3.1 (2026-05-19): AdminBroadcast{Sent,Edited,Retracted} →
            # local materialization of federated broadcasts.
            # Gated REACTOR_ADMIN_BROADCAST_RECEIVED_ENABLED (default true).
            if os.getenv("REACTOR_ADMIN_BROADCAST_RECEIVED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_admin_broadcast_received import (
                    start as start_reactor_admin_broadcast_received,
                )
                logger.info("Starting reactor: AdminBroadcast{Sent,Edited,Retracted} → local materialize")
                asyncio.create_task(start_reactor_admin_broadcast_received())
            else:
                logger.info("Reactor AdminBroadcastReceived DISABLED via env var")

            # §bc4 T4.5 (2026-05-19): Org-lifecycle → user-targeted notifications.
            # Gated REACTOR_ORG_LIFECYCLE_NOTIFICATION_ENABLED (default true).
            if os.getenv("REACTOR_ORG_LIFECYCLE_NOTIFICATION_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_org_lifecycle_notification import (
                    start as start_reactor_org_lifecycle_notification,
                )
                logger.info("Starting reactor: OrgMember{Invited,Joined,Removed} → user notification")
                asyncio.create_task(start_reactor_org_lifecycle_notification())
            else:
                logger.info("Reactor OrgLifecycleNotification DISABLED via env var")

            # §bc5 T5.1 (2026-05-19): CI/CD deployment events → owner / org-admin notifications.
            # Gated REACTOR_CICD_NOTIFICATION_ENABLED (default true).
            if os.getenv("REACTOR_CICD_NOTIFICATION_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_cicd_notification import (
                    start as start_reactor_cicd_notification,
                )
                logger.info("Starting reactor: Deployment{Triggered,StatusUpdated,WebhookExhausted} → owner/org-admin notification")
                asyncio.create_task(start_reactor_cicd_notification())
            else:
                logger.info("Reactor CICDNotification DISABLED via env var")

            # Phase 2: FederationLicenseSuspended → TEG partner cleanup
            if os.getenv("REACTOR_LICENSE_SUSPENDED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_federation_license_suspended import (
                    start as start_reactor_license_suspended,
                )
                logger.info(
                    "Starting reactor: FederationLicenseSuspended → TEG partner cleanup"
                )
                asyncio.create_task(start_reactor_license_suspended())
            else:
                logger.info("Reactor FederationLicenseSuspended DISABLED via env var")

            # Phase 2: RegistryQuarantined → TEG partner cleanup
            if os.getenv("REACTOR_REGISTRY_QUARANTINED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_registry_quarantined import (
                    start as start_reactor_registry_quarantined,
                )
                logger.info(
                    "Starting reactor: RegistryQuarantined → TEG partner cleanup"
                )
                asyncio.create_task(start_reactor_registry_quarantined())
            else:
                logger.info("Reactor RegistryQuarantined DISABLED via env var")

            # Phase 5: SupplyInvariantBreach → webhook + email + critical log
            if os.getenv("REACTOR_SUPPLY_BREACH_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_supply_invariant_breach import (
                    start as start_reactor_supply_breach,
                )
                logger.info(
                    "Starting reactor: SupplyInvariantBreach → alert dispatch"
                )
                asyncio.create_task(start_reactor_supply_breach())
            else:
                logger.info("Reactor SupplyInvariantBreach DISABLED via env var")

            # Phase 6: Coordinated suspension reactors (out-of-process propagation only;
            # inline coupling already happens in the suspend/reinstate handlers).
            if os.getenv("REACTOR_AGENT_SUSPENDED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_agent_suspended import (
                    start as start_reactor_agent_suspended,
                )
                logger.info("Starting reactor: AgentSuspended → webhook propagation")
                asyncio.create_task(start_reactor_agent_suspended())
            else:
                logger.info("Reactor AgentSuspended DISABLED via env var")

            # §2026-06-14: OperatorRenamed → cross-frame fanout of an operator
            # identity rename (home frame emits; this reactor pushes to peers).
            if os.getenv("REACTOR_OPERATOR_RENAMED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_operator_renamed import (
                    start as start_reactor_operator_renamed,
                )
                logger.info("Starting reactor: OperatorRenamed → cross-frame rename fanout")
                asyncio.create_task(start_reactor_operator_renamed())
            else:
                logger.info("Reactor OperatorRenamed DISABLED via env var")

            if os.getenv("REACTOR_AGENT_REINSTATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_agent_reinstated import (
                    start as start_reactor_agent_reinstated,
                )
                logger.info("Starting reactor: AgentReinstated → webhook propagation")
                asyncio.create_task(start_reactor_agent_reinstated())
            else:
                logger.info("Reactor AgentReinstated DISABLED via env var")

            if os.getenv("REACTOR_DEVELOPER_SUSPENDED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_developer_suspended import (
                    start as start_reactor_developer_suspended,
                )
                logger.info(
                    "Starting reactor: DeveloperSuspended → cascade webhook fan-out"
                )
                asyncio.create_task(start_reactor_developer_suspended())
            else:
                logger.info("Reactor DeveloperSuspended DISABLED via env var")

            # A3 (2026-07-24): the reinstate mirror — the cascade itself is inline in
            # admin_developers.reinstate_developer; this fans out the webhooks that
            # never fired (developer.reinstated + per-agent agent.reinstated).
            if os.getenv("REACTOR_DEVELOPER_REINSTATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_developer_reinstated import (
                    start as start_reactor_developer_reinstated,
                )
                logger.info(
                    "Starting reactor: DeveloperReinstated → cascade webhook fan-out"
                )
                asyncio.create_task(start_reactor_developer_reinstated())
            else:
                logger.info("Reactor DeveloperReinstated DISABLED via env var")

            # A4 (2026-07-24): FederationPolicyUpdated finally has a consumer — an
            # immediate compliance re-poll (central registries) instead of the 6h wait.
            if os.getenv("REACTOR_FEDERATION_POLICY_UPDATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_federation_policy_updated import (
                    start as start_reactor_federation_policy_updated,
                )
                logger.info(
                    "Starting reactor: FederationPolicyUpdated → immediate compliance re-poll"
                )
                asyncio.create_task(start_reactor_federation_policy_updated())
            else:
                logger.info("Reactor FederationPolicyUpdated DISABLED via env var")

            # §pass47 A6 (2026-05-19): AgentCardJWSVerifyFailed → throttle + flag
            if os.getenv("REACTOR_JWS_VERIFY_FAILED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_jws_verify_failed_throttle import (
                    start as start_reactor_jws_verify_failed,
                )
                logger.info(
                    "Starting reactor: AgentCardJWSVerifyFailed → throttle (N-in-1h flag)"
                )
                asyncio.create_task(start_reactor_jws_verify_failed())
            else:
                logger.info("Reactor JWSVerifyFailedThrottle DISABLED via env var")

            # §pass47 B5 (2026-05-19): AgentCardPulled (drift) → persistent-drift flag
            if os.getenv("REACTOR_AGENT_CARD_DRIFT_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_agent_card_drift import (
                    start as start_reactor_agent_card_drift,
                )
                logger.info(
                    "Starting reactor: AgentCardPulled → persistent-drift flag (N-in-24h)"
                )
                asyncio.create_task(start_reactor_agent_card_drift())
            else:
                logger.info("Reactor AgentCardDriftFlag DISABLED via env var")

            # Phase 7: FederationLicenseReinstated → TEG partner re-add (mirror)
            if os.getenv("REACTOR_LICENSE_REINSTATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_federation_license_reinstated import (
                    start as start_reactor_license_reinstated,
                )
                logger.info(
                    "Starting reactor: FederationLicenseReinstated → TEG partner re-add"
                )
                asyncio.create_task(start_reactor_license_reinstated())
            else:
                logger.info("Reactor FederationLicenseReinstated DISABLED via env var")

            # Phase 7: FrameFederationRevoked → audit propagation
            if os.getenv("REACTOR_FRAME_FEDERATION_REVOKED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_frame_federation_revoked import (
                    start as start_reactor_frame_federation_revoked,
                )
                logger.info(
                    "Starting reactor: FrameFederationRevoked → webhook propagation"
                )
                asyncio.create_task(start_reactor_frame_federation_revoked())
            else:
                logger.info("Reactor FrameFederationRevoked DISABLED via env var")

            # FrameInvitationApproved and FrameFederationEstablished → TEG partner add (2026-10-21): two frames that
            # federate through the invitation rail register each other as TEG partners, each side on its own event
            # (the partner rule runs a cross-TEG leg only with a current partner; the revoke releases it through
            # PeerRegistryDeactivated). One module starts both reactors.
            if os.getenv("REACTOR_FRAME_FEDERATION_ESTABLISHED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_frame_federation_established import (
                    start as start_reactor_frame_federation_established,
                )
                logger.info(
                    "Starting reactors: FrameInvitationApproved + FrameFederationEstablished → TEG partner add"
                )
                asyncio.create_task(start_reactor_frame_federation_established())
            else:
                logger.info("Reactor FrameFederationEstablished DISABLED via env var")

            # Phase 7.1: FederationStateDriftDetected → webhook propagation
            # Emitter (license_drift_monitor) only runs when IS_CENTRAL_REGISTRY=True,
            # but the reactor itself runs on every registry — peers can subscribe to
            # `federation.drift_detected` regardless of central-registry status.
            if os.getenv("REACTOR_DRIFT_DETECTED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_drift_detected import (
                    start as start_reactor_drift_detected,
                )
                logger.info(
                    "Starting reactor: FederationStateDriftDetected → webhook propagation"
                )
                asyncio.create_task(start_reactor_drift_detected())
            else:
                logger.info("Reactor FederationStateDriftDetected DISABLED via env var")

            # 2026-04-28: peer_url_misconfigured drift → self-healing UPDATE.
            # Listens to the same FederationStateDriftDetected event but only acts
            # when drift_type=peer_url_misconfigured. Probes mTLS-federation port
            # candidates with the local SVID and rewrites peer.base_url on first
            # 200 response. Audit event: PeerRegistryUrlAutoCorrected.
            if os.getenv("REACTOR_PEER_URL_SELF_HEAL_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_peer_url_self_heal import (
                    start as start_reactor_peer_url_self_heal,
                )
                logger.info(
                    "Starting reactor: peer_url_misconfigured → self-healing UPDATE"
                )
                asyncio.create_task(start_reactor_peer_url_self_heal())
            else:
                logger.info("Reactor PeerUrlSelfHeal DISABLED via env var")

            # 2026-04-28: OperatorApplicationRevoked → peer_registries cascade.
            # Closes the cascade gap when revoke fires on an operator with no
            # federation_license (phantom operators administratively approved
            # but never provisioned). Flips peer_registries.status to INACTIVE
            # and emits PeerRegistryDeactivated.
            if os.getenv("REACTOR_OPERATOR_APPLICATION_REVOKED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_operator_application_revoked import (
                    start as start_reactor_operator_application_revoked,
                )
                logger.info(
                    "Starting reactor: OperatorApplicationRevoked → peer_registries cascade"
                )
                asyncio.create_task(start_reactor_operator_application_revoked())
            else:
                logger.info("Reactor OperatorApplicationRevoked DISABLED via env var")

            # RCA 2026-07-10 (federation-peer ratchet): INACTIVE-peer revival prober.
            # Symmetric peer lifecycle — identity-verified auto-revival of peers that
            # were deactivated transiently (restart windows, sync races). Guard-set
            # reasons (admin/revoked/debris…) are never revived. Leader-elected.
            if os.getenv("PEER_REVIVAL_PROBER_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.peer_revival_prober import (
                    start as start_peer_revival_prober,
                )
                logger.info(
                    "Starting worker: peer_revival_prober (INACTIVE-peer auto-revival)"
                )
                asyncio.create_task(start_peer_revival_prober())
            else:
                logger.info("Worker peer_revival_prober DISABLED via env var")

            # Phase 9.1: ComplianceDryRunDrift → webhook propagation (cross-frame
            # poller-emitted drift; mirror of FederationStateDriftDetected for the
            # HTTP-based detection path).
            if os.getenv("REACTOR_COMPLIANCE_DRY_RUN_DRIFT_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_compliance_dry_run_drift import (
                    start as start_reactor_compliance_dry_run_drift,
                )
                logger.info(
                    "Starting reactor: ComplianceDryRunDrift → webhook propagation"
                )
                asyncio.create_task(start_reactor_compliance_dry_run_drift())
            else:
                logger.info("Reactor ComplianceDryRunDrift DISABLED via env var")

            # Phase 9.2: EventEmissionPolicyUpdated → cache invalidation (registry +
            # TEG) + webhook fanout. Closes the f037 cache TTL window.
            if os.getenv("REACTOR_EMISSION_POLICY_UPDATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_emission_policy_updated import (
                    start as start_reactor_emission_policy_updated,
                )
                logger.info(
                    "Starting reactor: EventEmissionPolicyUpdated → cache invalidation"
                )
                asyncio.create_task(start_reactor_emission_policy_updated())
            else:
                logger.info("Reactor EventEmissionPolicyUpdated DISABLED via env var")

            # Phase 9.3 — Reactor batch 2 (#14-19)
            # Six new reactors: webhook exhaustion / agent slash / bridge expiry /
            # proposal tally / registry federation / balance correction.

            # #14 WebhookRetryExhausted → meta-webhook + sovereign-themed dev email
            if os.getenv("REACTOR_WEBHOOK_EXHAUSTED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_webhook_retry_exhausted import (
                    start as start_reactor_webhook_exhausted,
                )
                logger.info(
                    "Starting reactor: WebhookRetryExhausted → developer notification"
                )
                asyncio.create_task(start_reactor_webhook_exhausted())
            else:
                logger.info("Reactor WebhookRetryExhausted DISABLED via env var")

            # #15 DisputeSlash → owning-dev email + agent.slashed webhook
            if os.getenv("REACTOR_AGENT_SLASHED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_agent_slashed import (
                    start as start_reactor_agent_slashed,
                )
                logger.info("Starting reactor: AgentSlashed → owning-dev notification")
                asyncio.create_task(start_reactor_agent_slashed())
            else:
                logger.info("Reactor AgentSlashed DISABLED via env var")

            # #16 BridgeTransferExpired → originator notification + webhook
            if os.getenv("REACTOR_BRIDGE_EXPIRED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_bridge_transfer_expired import (
                    start as start_reactor_bridge_expired,
                )
                logger.info(
                    "Starting reactor: BridgeTransferExpired → originator notification"
                )
                asyncio.create_task(start_reactor_bridge_expired())
            else:
                logger.info("Reactor BridgeTransferExpired DISABLED via env var")

            # #17 ProposalTallied → governance.proposal_passed/_failed webhook
            if os.getenv("REACTOR_PROPOSAL_OUTCOME_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_proposal_tallied import (
                    start as start_reactor_proposal_tallied,
                )
                logger.info(
                    "Starting reactor: ProposalTallied → governance outcome fan-out"
                )
                asyncio.create_task(start_reactor_proposal_tallied())
            else:
                logger.info("Reactor ProposalTallied DISABLED via env var")

            # #18 RegistryFederated → policy-hash refresh + federation.peer_added
            if os.getenv("REACTOR_REGISTRY_FEDERATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_registry_federated import (
                    start as start_reactor_registry_federated,
                )
                logger.info(
                    "Starting reactor: RegistryFederated → policy refresh + webhook"
                )
                asyncio.create_task(start_reactor_registry_federated())
            else:
                logger.info("Reactor RegistryFederated DISABLED via env var")

            # #19 BalanceCorrected → critical log + webhook + sovereign-themed audit email
            if os.getenv("REACTOR_BALANCE_CORRECTED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_balance_corrected import (
                    start as start_reactor_balance_corrected,
                )
                logger.info(
                    "Starting reactor: BalanceCorrected → security audit alert"
                )
                asyncio.create_task(start_reactor_balance_corrected())
            else:
                logger.info("Reactor BalanceCorrected DISABLED via env var")

            # §TWOAGENT G3 (2026-09-23): LedgerBalanceChanged → `payment.received` to the receiving agent's owner
            # (webhook, owner-scoped, once per credit). The frame's own ledger is the only record every credit
            # leaves, including an FX-pool arrival, which has no other event on the receiver's store.
            if os.getenv("REACTOR_PAYMENT_RECEIVED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_payment_received import (
                    start as start_reactor_payment_received,
                )
                logger.info("Starting reactor: LedgerBalanceChanged → payment.received webhook")
                asyncio.create_task(start_reactor_payment_received())
            else:
                logger.info("Reactor PaymentReceived DISABLED via env var")

            # #5 (2026-05-08): DisputeFiled → enforcement-admin toast.
            # Audience-filtered via the WS manager so only admin_enforcement
            # users see the live notification.
            if os.getenv("REACTOR_DISPUTE_FILED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_dispute_filed import (
                    start as start_reactor_dispute_filed,
                )
                logger.info("Starting reactor: DisputeFiled → enforcement-admin toast")
                asyncio.create_task(start_reactor_dispute_filed())
            else:
                logger.info("Reactor DisputeFiled DISABLED via env var")

            # #5 (2026-05-08): FundingRequestCreated → treasury-admin toast.
            # Emission was added to routers/funding_requests.py:create_funding_request
            # in the same patch.
            if os.getenv("REACTOR_FUNDING_REQUEST_CREATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_funding_request_created import (
                    start as start_reactor_funding_request_created,
                )
                logger.info("Starting reactor: FundingRequestCreated → treasury-admin toast")
                asyncio.create_task(start_reactor_funding_request_created())
            else:
                logger.info("Reactor FundingRequestCreated DISABLED via env var")

            # PB-2 reactors registered OUTSIDE master gate (see below) — they
            # are essential for routed-fiat operation and have their own
            # internal gating (FIAT_GENESIS_REGISTRY / FEDERATION_OPERATOR_DID).
            pass

            # ZKP Phase 2 — AttestationRevoked + AttestationExpired (gated by
            # ZKP_PHASE_2_ENABLED so the reactors no-op on production where
            # Phase 2 is kill-switched until Commander signs off).
            if (
                os.getenv("ZKP_PHASE_2_ENABLED", "true").lower() == "true"
                and os.getenv("REACTOR_ATTESTATION_REVOKED_ENABLED", "true").lower() == "true"
            ):
                from agentvault_registry.background_tasks.reactor_attestation_revoked import (
                    start as start_reactor_attestation_revoked,
                )
                logger.info(
                    "Starting reactor: AttestationRevoked → webhook + sovereign email"
                )
                asyncio.create_task(start_reactor_attestation_revoked())
            else:
                logger.info("Reactor AttestationRevoked DISABLED via env var")

            if (
                os.getenv("ZKP_PHASE_2_ENABLED", "true").lower() == "true"
                and os.getenv("REACTOR_ATTESTATION_EXPIRED_ENABLED", "true").lower() == "true"
            ):
                from agentvault_registry.background_tasks.reactor_attestation_expired import (
                    start as start_reactor_attestation_expired,
                )
                logger.info(
                    "Starting reactor: AttestationExpired → webhook (lightweight)"
                )
                asyncio.create_task(start_reactor_attestation_expired())
            else:
                logger.info("Reactor AttestationExpired DISABLED via env var")

            # ZKP Phase 5 — AttestationDueReminder (gated by ZKP_PHASE_5_ENABLED).
            if (
                os.getenv("ZKP_PHASE_5_ENABLED", "true").lower() == "true"
                and os.getenv("REACTOR_ATTESTATION_DUE_REMINDER_ENABLED", "true").lower() == "true"
            ):
                from agentvault_registry.background_tasks.reactor_attestation_due_reminder import (
                    start as start_reactor_attestation_due_reminder,
                )
                logger.info(
                    "Starting reactor: AttestationDueReminder → webhook (lightweight)"
                )
                asyncio.create_task(start_reactor_attestation_due_reminder())
            else:
                logger.info("Reactor AttestationDueReminder DISABLED via env var")

            # POCKET FRAME — IRONKEY delegation/capability → device push (f-mobile,
            # 2026-07-07). Default OFF fleet-wide; canary = frame-c compose env.
            if os.getenv("PUSH_NOTIFY_ENABLED", "false").lower() == "true":
                from agentvault_registry.background_tasks.reactor_push_notify import (
                    start as start_reactor_push_notify,
                )
                logger.info("Starting reactors: PushNotify (delegation/capability → device push)")
                asyncio.create_task(start_reactor_push_notify())
            else:
                logger.info("Reactors PushNotify DISABLED (PUSH_NOTIFY_ENABLED=false)")

            # CROSS-FRAME CONTRACTS — inbound mirror reactor. Idle unless the mode flag is
            # shadow/enforce; the handler itself re-checks, so no restart is needed to ratchet.
            if (os.getenv("CONTRACTS_XFRAME_MODE", "off") or "off").lower() in ("shadow", "enforce"):
                from agentvault_registry.background_tasks.reactor_contract_mirrored import (
                    start as start_reactor_contract_mirrored,
                )
                logger.info("Starting reactors: XFrame:ContractMirrored (peer replica materialisation)")
                asyncio.create_task(start_reactor_contract_mirrored())

            # PHONE FABRIC — session reaper (TTL/token-death auto-end). Gated PHONE_FABRIC_ENABLED.
            if os.getenv("PHONE_FABRIC_ENABLED", "false").lower() == "true":
                from agentvault_registry.background_tasks.phone_session_reaper import (
                    start_phone_session_reaper,
                )
                logger.info("Starting worker: phone_session_reaper (PHONE FABRIC)")
                asyncio.create_task(start_phone_session_reaper())
            else:
                logger.info("Phone Fabric DISABLED (PHONE_FABRIC_ENABLED=false)")

            # THE GUILD — order reaper (deadline auto-refund / ETA flag). Gated GUILD_ENABLED.
            if os.getenv("GUILD_ENABLED", "false").lower() == "true":
                from agentvault_registry.background_tasks.guild_order_reaper import (
                    start_guild_order_reaper,
                )
                logger.info("Starting worker: guild_order_reaper (THE GUILD)")
                asyncio.create_task(start_guild_order_reaper())
            else:
                logger.info("The Guild DISABLED (GUILD_ENABLED=false)")

            # THE CONTRACT SPINE — reaper (expiry / stuck-escrow revert / releasing re-drive /
            # deadline auto-dispute). Gated CONTRACTS_V2_ENABLED; Redis leader-elected inside.
            if os.getenv("CONTRACTS_V2_ENABLED", "false").lower() == "true":
                from agentvault_registry.background_tasks.contract_reaper import (
                    start_contract_reaper,
                )
                logger.info("Starting worker: contract_reaper (CONTRACT SPINE)")
                asyncio.create_task(start_contract_reaper())
            else:
                logger.info("Contract spine DISABLED (CONTRACTS_V2_ENABLED=false)")

            # 2026-05-03: Async cross-frame transfer reactors (3 total).
            # Triggered when TEG_CROSS_FRAME_BACKEND=async on any registry.
            # All three subscribe to local ES; SF-4 + foreign_events Pub/Sub
            # bridge ensures cross-frame events propagate to local WS within
            # ~500ms. See plans/snappy-stirring-wreath.md.
            if os.getenv("REACTOR_CROSS_FRAME_INITIATED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_cross_frame_initiated import (
                    start as start_reactor_cross_frame_initiated,
                )
                logger.info(
                    "Starting reactor: CrossFrameTransferInitiated → receiver TEG credit + Settled emit"
                )
                asyncio.create_task(start_reactor_cross_frame_initiated())
            else:
                logger.info("Reactor CrossFrameTransferInitiated DISABLED via env var")

            if os.getenv("REACTOR_CROSS_FRAME_SETTLED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_cross_frame_settled import (
                    start as start_reactor_cross_frame_settled,
                )
                logger.info(
                    "Starting reactor: CrossFrameTransferSettled → sender pending clear"
                )
                asyncio.create_task(start_reactor_cross_frame_settled())
            else:
                logger.info("Reactor CrossFrameTransferSettled DISABLED via env var")

            # §TRUSTWIRE (2026-09-10) — ONE reactor over EVERY cross-registry settlement event,
            # feeding the Bayesian peer-trust model its evidence half. Replaces two hand-wired
            # call sites that between them missed the FX pool swap, which is the only settlement
            # path that actually runs between frames on this network.
            if os.getenv("REACTOR_PEER_TRUST_OBSERVED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_peer_trust_observed import (
                    start as start_reactor_peer_trust_observed,
                )
                logger.info(
                    "Starting reactor: FxSwapSettled + CrossFrameTransferSettled + "
                    "CrossRegistryTransferCompleted → peer trust observation"
                )
                asyncio.create_task(start_reactor_peer_trust_observed())
            else:
                logger.info("Reactor PeerTrustObserved DISABLED via env var")

            if os.getenv("REACTOR_CROSS_FRAME_REFUNDED_ENABLED", "true").lower() == "true":
                from agentvault_registry.background_tasks.reactor_cross_frame_refunded import (
                    start as start_reactor_cross_frame_refunded,
                )
                logger.info(
                    "Starting reactor: CrossFrameTransferRefunded → receiver compensating reverse"
                )
                asyncio.create_task(start_reactor_cross_frame_refunded())
            else:
                logger.info("Reactor CrossFrameTransferRefunded DISABLED via env var")
        else:
            logger.info("Reactor framework DISABLED via REACTOR_FRAMEWORK_ENABLED=false")

        # EigenTrust++ Phase 2: Start trust computation worker
        logger.info("Starting EigenTrust++ worker")
        asyncio.create_task(start_eigentrust_worker())

        # Agent Evals runner (leader-elected; no-op unless EVALS_ENABLED).
        try:
            from agentvault_registry.background_tasks.eval_runner import start_eval_runner
            asyncio.create_task(start_eval_runner())
        except Exception as _e:
            logger.warning("Eval runner not started: %s", _e)

        # Sprint 9: Start velocity snapshot worker (hourly EventStore aggregation)
        logger.info("Starting velocity snapshot worker")
        asyncio.create_task(start_velocity_snapshot())

        # Sprint 10: Start collusion worker (daily Bayesian decay + SCC ring detection)
        logger.info("Starting collusion/Bayesian worker")
        asyncio.create_task(start_collusion_worker())

        # Beta access request processor (5-minute cycle)
        # Beta access worker — DEPRECATED
        # asyncio.create_task(beta_access_worker())

        # Phase 2a: Start compliance poller (central registry only)
        if settings.IS_CENTRAL_REGISTRY:
            logger.info("Starting federation compliance poller (IS_CENTRAL_REGISTRY=True)")
            asyncio.create_task(start_compliance_poller())
            # Option D-light Phase D4: license/operator/peer state drift monitor
            logger.info("Starting license drift monitor (IS_CENTRAL_REGISTRY=True)")
            asyncio.create_task(start_license_drift_monitor())
        else:
            logger.info(
                "Compliance poller + license drift monitor SKIPPED "
                "(IS_CENTRAL_REGISTRY=False). Manual drift scans still available "
                "via POST /api/v1/admin/federation/drift-scan."
            )

        # Phase 2b: Start supply invariant auditor (always runs)
        logger.info("Starting supply invariant auditor (60-second cycle)")
        asyncio.create_task(start_supply_auditor())

        # §pass73.3.19 L3b: balance reconciliation guard — forces ES projection → TEG profile (truth)
        logger.info("Starting balance reconciliation guard")
        asyncio.create_task(start_balance_reconciliation_guard())

        # f045: A2A payment token expiry worker
        from agentvault_registry.background_tasks.a2a_payment_expiry import a2a_payment_expiry_loop
        asyncio.create_task(a2a_payment_expiry_loop())
        logger.info("Started A2A payment token expiry worker")

        # COCKPIT CARD: lapsed confirmations and sign-in approvals reach a terminal state on
        # their own, and a lapsed confirmation appends the denial that expiry-is-a-denial owes it.
        from agentvault_registry.background_tasks.liability_expiry import liability_expiry_loop
        asyncio.create_task(liability_expiry_loop())
        logger.info("Started liability/login expiry sweeper")

        # §VCSIGN-2: countersign-break watcher — alarms the recording admin when a
        # contract backing a LIVE regulatory authorization leaves the agreed state
        # (observes the derived state; immune to the missed-transition-site class).
        if (os.getenv("REGAUTH_COUNTERSIGN_WATCH_ENABLED", "true").lower() in ("1", "true", "yes")):
            from agentvault_registry.background_tasks.regauth_countersign_watch import regauth_countersign_watch_loop
            asyncio.create_task(regauth_countersign_watch_loop())
            logger.info("Started regauth countersign-break watcher")

        # §POCKETBRIDGE3 (D3-4): server half of Pocket price alerts — reads the
        # pocket.price_alerts pref rows and fires exchange.price_alert (push only
        # for opted-in developers; the category defaults push-OFF). Local venue
        # only; inert with zero alert rows (one indexed query per cycle).
        if (os.getenv("PRICE_ALERT_WATCHER_ENABLED", "true").lower() in ("1", "true", "yes")):
            from agentvault_registry.background_tasks.price_alert_watcher import price_alert_watcher_loop
            asyncio.create_task(price_alert_watcher_loop())
            logger.info("Started pocket price-alert watcher")

        # §OURSTATE-3b: the host's federated-chat delivery worker. Structurally
        # INERT unless CHAT_FEDERATION_ENABLED — the loop returns immediately,
        # so a registry that has not opted into cross-registry chat pays
        # nothing for the code being present.
        from agentvault_registry.background_tasks.chat_federation_outbox import (
            chat_federation_outbox_loop,
        )
        asyncio.create_task(chat_federation_outbox_loop())
        logger.info("Started OurChat federation outbox worker (idle unless enabled)")

        # §OURSTATE-6: the retention sweeper — the half of a disappearing timer
        # that makes it true. Visits ONLY threads that set a window, so a
        # registry where nobody uses timers pays one cheap indexed query a
        # quarter hour.
        from agentvault_registry.background_tasks.chat_retention_sweeper import (
            chat_retention_loop,
        )
        asyncio.create_task(chat_retention_loop())
        logger.info("Started OurChat retention sweeper")

        # CROSS-FRAME CONTRACTS: outbox mirror emitter (home) + digest reconciler (peer).
        # Idle unless CONTRACTS_XFRAME_MODE is shadow/enforce; re-reads the flag each cycle.
        from agentvault_registry.background_tasks.contract_xframe_worker import contract_xframe_loop
        asyncio.create_task(contract_xframe_loop())
        logger.info("Started cross-frame contract worker")

        # f040: Webhook retry worker + agent health checker
        asyncio.create_task(start_webhook_retry_worker())
        # §BRIDGE R7-B — keep the public event SEED complete. Listens to THIS
        # frame's own EventStore broadcasts (Redis pub/sub, already published)
        # so the ring covers everything on the frame, not just what the registry
        # itself emitted (measured 350 registry vs 813 teg-outbox per 20 min).
        from agentvault_registry.background_tasks.recent_events_ring import start_recent_events_ring
        asyncio.create_task(start_recent_events_ring())
        asyncio.create_task(start_agent_health_checker())
        logger.info("Started webhook retry worker + agent health checker")

        # f042: Auto-tally expired governance proposals
        logger.info("Starting auto-tally worker for expired governance proposals")
        asyncio.create_task(start_auto_tally())

        # W2 (2026-05-09): Account-deletion anonymizer (daily cycle, leader-elected).
        # Anonymizes Developer rows whose 14-day cooling-off has elapsed.
        # Disabled via ACCOUNT_DELETION_WORKER_ENABLED=false.
        logger.info("Starting account-deletion anonymizer worker (daily cycle)")
        asyncio.create_task(start_account_deletion_worker())

        # §LEGALKIT (F5): the 12-month cap Privacy § 4.2 publishes on security and MCP audit records.
        from agentvault_registry.background_tasks.audit_retention_worker import start_audit_retention_worker
        logger.info("Starting audit-retention worker (daily cycle)")
        asyncio.create_task(start_audit_retention_worker())

        # PB-2 (2026-05-09): routed-fiat reconcilers. Both run on every
        # registry — internal gates exit early if the registry is the wrong
        # role for that worker (mainframe-side reconciler is a no-op on
        # operators because the partial-index scan returns 0 rows; operator-
        # side reconciler exits early on mainframe via FIAT_GENESIS_REGISTRY).
        logger.info("Starting routed-fiat mainframe reconciler (hourly)")
        asyncio.create_task(start_fiat_routed_reconciler())
        logger.info("Starting routed-fiat operator reconciler (hourly)")
        asyncio.create_task(start_fiat_routed_local_reconciler())
        # PB-3 W5 (2026-05-12): generic PSP reconciler for non-Stripe providers
        # (Mollie 26h retry window etc.). Gated by REACTOR_FIAT_PROVIDER_RECONCILER_ENABLED
        # + FIAT_GENESIS_REGISTRY; safe to no-op start always.
        logger.info("Starting fiat-provider reconciler (PB-3 W5; non-Stripe PSPs)")
        asyncio.create_task(start_fiat_provider_reconciler())

        # ZKP Phase 2: daily attestation expiry sweep (no-op when
        # ZKP_PHASE_2_ENABLED=false — see attestation_expiry._is_enabled).
        from agentvault_registry.background_tasks.attestation_expiry import (
            start_attestation_expiry,
        )
        logger.info("Starting ZKP attestation expiry worker (daily cycle)")
        asyncio.create_task(start_attestation_expiry())

        # ZKP Phase 5: hourly attestation schedule cron (no-op when
        # ZKP_PHASE_5_ENABLED=false — see attestation_schedule_cron._is_enabled).
        from agentvault_registry.background_tasks.attestation_schedule_cron import (
            start_attestation_schedule_cron,
        )
        logger.info("Starting ZKP attestation schedule cron worker (hourly cycle)")
        asyncio.create_task(start_attestation_schedule_cron())

        # Phase 1 Scaling: TEG Bulk Proxy (batches transfer proxy calls)
        logger.info("Initializing TEG Bulk Proxy")
        await start_teg_bulk_proxy()

        # LIGHTNING-2 (2026-05-01): TEG Stream Proxy — cross-worker Redis-Streams
        # batching, leader-elected flusher per registry. Activated only when
        # TEG_BULK_PROXY_BACKEND=stream; otherwise no-op (logs disabled).
        logger.info("Initializing TEG Stream Proxy (gated by TEG_BULK_PROXY_BACKEND=stream)")
        await start_teg_stream_proxy()

        # SF-3: Bridge expiry worker (unlocks timed-out bridge escrows)
        from agentvault_registry.background_tasks.bridge_expiry import bridge_expiry_loop
        asyncio.create_task(bridge_expiry_loop())
        logger.info("Bridge expiry worker started")

        # §SHOWCASEVISITOR (2026-08-25) — retire expired per-visitor showcase
        # agents and return what is left on them. One agent per visitor on a
        # public endpoint is unbounded rows and scattered float; this is the
        # other half of that feature, not an optimisation.
        # ⚠ Leader-elected via run_with_leadership, NOT is_leader(): that call's
        # own docstring says it does not acquire, and a task gated on it runs
        # forever doing nothing (§BRIDGE R7-B, the recent_events_ring class).
        from agentvault_registry.background_tasks.showcase_visitor_sweeper import (
            run_showcase_visitor_sweeper,
        )
        asyncio.create_task(run_showcase_visitor_sweeper())
        logger.info("Showcase visitor sweeper started")

        # §pass63 (2026-05-22) — Astraeus 10-worker spawn block removed entirely.

        logger.info("Startup complete")

    @app.on_event("shutdown")
    async def shutdown_event():
        """Clean up resources on shutdown."""
        logger.info("Shutting down AgentVault Registry...")
        
        await stop_federation_sync()
        
        logger.info("Stopping algorithmic auditor worker")
        auditor_worker.stop()
        
        logger.info("Stopping staking rewards distributor")
        await stop_staking_distributor()

        logger.info("Stopping AGORA exchange settlement worker")
        try:
            from agentvault_registry.background_tasks.exchange_settlement import stop_exchange_settlement
            await stop_exchange_settlement()
        except Exception as _agora_stop_err:
            logger.warning(f"AGORA settlement stop: {_agora_stop_err}")
        
        logger.info("Stopping saga timeout checker")
        await stop_saga_timeout_checker()

        logger.info("Stopping peer activation keeper")
        await stop_peer_activation_keeper()

        logger.info("Stopping agent_card_pullsync worker")
        await stop_agent_card_pullsync()

        logger.info("Stopping broadcast_scheduler worker")
        try:
            await get_broadcast_scheduler().stop()
        except Exception as e:
            logger.warning(f"broadcast_scheduler stop error: {e}")

        logger.info("Stopping es_emit_outbox drainer")
        try:
            await get_es_emit_outbox_drainer().stop()
            await get_genesis_grant_retry().stop()
            await get_fiat_credit_retry().stop()
            await get_forfeiture_retry().stop()
            await get_xreg_revoke_retry().stop()
            await get_idempotency_kept_sweeper().stop()
        except Exception as e:
            logger.warning(f"es_emit_outbox drainer stop error: {e}")
        logger.info("Stopping broadcast_email_retry worker")
        try:
            await get_broadcast_email_retry_worker().stop()
        except Exception as e:
            logger.warning(f"broadcast_email_retry stop error: {e}")

        logger.info("Stopping canary runner")
        await stop_canary_runner()
        await stop_revocation_drill()

        logger.info("Stopping canary judge")
        await stop_canary_judge()

        logger.info("Stopping canary rebalancer")
        await stop_canary_rebalancer()

        logger.info("Stopping FX router keeper")
        await stop_fx_router_keeper()

        logger.info("Stopping FX reserve peg keeper")
        await stop_fx_reserve_keeper()

        logger.info("Stopping AGORA gateway-float keeper")
        await stop_gateway_float_keeper()
        await stop_treasury_market_maker()

        logger.info("Stopping Ledger Forensics scanner")
        await stop_forensic_scanner()

        logger.info("Stopping canary validator reactors")
        try:
            from agentvault_registry.background_tasks.reactor_canary_validator import stop_all as stop_canary_validator
            await stop_canary_validator()
        except Exception as e:
            logger.warning(f"Canary validator stop error: {e}")

        logger.info("Stopping EventStore balance sync")
        await stop_balance_sync()

        logger.info("Stopping liquid balance reconciler")
        await stop_liquid_balance_reconciler()

        logger.info("Stopping EigenTrust++ worker")
        await stop_eigentrust_worker()

        logger.info("Stopping velocity snapshot worker")
        await stop_velocity_snapshot()

        logger.info("Stopping collusion/Bayesian worker")
        await stop_collusion_worker()

        # Phase 2a/2b: Stop compliance poller + supply auditor
        logger.info("Stopping compliance poller")
        await stop_compliance_poller()

        # Option D-light Phase D4: Stop license drift monitor
        logger.info("Stopping license drift monitor")
        await stop_license_drift_monitor()

        logger.info("Stopping supply auditor")
        await stop_supply_auditor()

        logger.info("Stopping balance reconciliation guard")
        await stop_balance_reconciliation_guard()

        logger.info("Stopping auto-tally worker")
        await stop_auto_tally()

        logger.info("Stopping account-deletion worker")
        await stop_account_deletion_worker()

        from agentvault_registry.background_tasks.audit_retention_worker import stop_audit_retention_worker
        logger.info("Stopping audit-retention worker")
        await stop_audit_retention_worker()

        # PB-2 (2026-05-09): stop both routed-fiat reconcilers
        logger.info("Stopping routed-fiat mainframe reconciler")
        await stop_fiat_routed_reconciler()
        await stop_fiat_provider_reconciler()
        logger.info("Stopping routed-fiat operator reconciler")
        await stop_fiat_routed_local_reconciler()

        # Phase 1 Scaling: Stop TEG Bulk Proxy
        logger.info("Stopping TEG Bulk Proxy")
        await stop_teg_bulk_proxy()

        # LIGHTNING-2: Stop TEG Stream Proxy (no-op when never started)
        logger.info("Stopping TEG Stream Proxy")
        await stop_teg_stream_proxy()

        # Phase 1 Scaling: Shutdown Kafka producer
        try:
            from agentvault_registry.event_emitter import shutdown_kafka
            await shutdown_kafka()
        except Exception as e:
            logger.warning(f"Kafka shutdown error: {e}")

        # OPA shadow-mode httpx client (sandbox-only, no-op when never instantiated)
        try:
            from agentvault_registry.opa_client import close_client as close_opa_client
            await close_opa_client()
        except Exception as e:
            logger.debug(f"OPA client close error (non-fatal): {e}")

        # Close Redis connection
        await close_redis()

        logger.info("Shutdown complete")

    logger.info(f"{settings.PROJECT_NAME} application initialized.")
    
    return app


# Create the application instance for production use
# This ensures backward compatibility while allowing tests to use the factory
app = create_app()
