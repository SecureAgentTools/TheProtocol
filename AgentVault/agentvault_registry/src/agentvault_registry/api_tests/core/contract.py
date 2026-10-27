"""Endpoint contract framework (AAA+ refactor 2026-05-21).

Each endpoint gets a declarative `@Endpoint`-decorated class that bundles:
  - prereqs: list of fixture names (resolved before body)
  - body: factory function (called with resolved ctx)
  - expected_status: int or list of ints
  - expected_events: list of EventSpec (ES event verification, optional)
  - failures: list of FailureMode rules
  - idempotent: True/False — drives parallel-safe bucket classification

Replaces the 4002-LOC test-endpoint handler's inline FORCE/PD3/EF chain.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from .failure_modes import FailureBucket, FailureMode, ResponseProbe, classify
from .fixtures import BootstrapContext

logger = logging.getLogger(__name__)


# ── EventSpec ────────────────────────────────────────────────────────────
@dataclass
class EventSpec:
    """A required EventStore event after the test fires."""
    event_type: str
    aggregate_id: Optional[Union[str, Callable]] = None
    match: Optional[Dict[str, Any]] = None
    max_wait_sec: float = 8.0


# ── Contract registry ────────────────────────────────────────────────────
_CONTRACTS: Dict[str, "EndpointContract"] = {}


def get_contract(method: str, path: str) -> Optional["EndpointContract"]:
    """Lookup a registered contract by (method, path). Returns None if absent."""
    return _CONTRACTS.get(f"{method.upper()} {path}")


def all_contracts() -> Dict[str, "EndpointContract"]:
    return dict(_CONTRACTS)


def contract_count() -> int:
    return len(_CONTRACTS)


# ── Endpoint contract metadata ───────────────────────────────────────────
@dataclass
class EndpointContract:
    """Declarative endpoint test specification."""
    method: str
    path: str
    auth: str = "developer"
    category: str = "other"
    tags: List[str] = field(default_factory=list)
    description: str = ""
    prereqs: List[str] = field(default_factory=list)
    body_factory: Optional[Callable[..., Awaitable[Optional[Dict[str, Any]]]]] = None
    expected_status: Union[int, List[int]] = 200
    expected_events: List[EventSpec] = field(default_factory=list)
    failures: List[FailureMode] = field(default_factory=list)
    idempotent: bool = True  # True = safe to run in parallel
    slow_timeout_sec: Optional[float] = None
    skip_es_verify: bool = False  # opt out of ES event verification

    @property
    def key(self) -> str:
        return f"{self.method.upper()} {self.path}"


# ── @Endpoint decorator ──────────────────────────────────────────────────
def Endpoint(
    *,
    method: str,
    path: str,
    auth: str = "developer",
    category: str = "other",
    tags: Optional[List[str]] = None,
    idempotent: bool = True,
    slow_timeout_sec: Optional[float] = None,
    skip_es_verify: bool = False,
):
    """Decorator: registers an EndpointContract for `(method, path)`.

    Usage:
        @Endpoint(method="POST", path="/teg/transfer", auth="agent", category="teg_integration")
        class TegTransfer:
            prereqs = ["funded_agent", "counterparty"]

            def body(self, ctx):
                return {"receiver_agent_id": ctx["counterparty"].did, "amount": "10", "currency": "AVT"}

            expected_status = 200
            expected_events = [EventSpec("TokensTransferred"), EventSpec("TransactionFeeCollected")]
            failures = [
                FailureMode.business_rule(
                    condition=lambda r: r.status == 400 and "self" in r.detail_lower(),
                    reason="self-transfer protection",
                ),
            ]
            idempotent = False
    """

    def decorator(cls):
        # Extract class-level attributes
        prereqs = list(getattr(cls, "prereqs", []))
        expected_status = getattr(cls, "expected_status", 200)
        expected_events = list(getattr(cls, "expected_events", []))
        failures = list(getattr(cls, "failures", []))
        cls_idempotent = getattr(cls, "idempotent", idempotent)
        cls_slow = getattr(cls, "slow_timeout_sec", slow_timeout_sec)
        cls_skip_es = getattr(cls, "skip_es_verify", skip_es_verify)
        description = (cls.__doc__ or "").strip().split("\n")[0]

        # body factory — class instance method "body(self, ctx)" or class function
        body_fn = getattr(cls, "body", None)
        if body_fn is not None and not inspect.iscoroutinefunction(body_fn):
            # Wrap sync body function as async
            instance = cls()
            sync_body = body_fn

            async def async_body(**deps):
                # Pass deps as ctx dict
                ctx = type("FixCtx", (), deps)
                return sync_body(instance, ctx)

            body_factory = async_body
        elif body_fn is not None:
            instance = cls()

            async def async_body(**deps):
                ctx = type("FixCtx", (), deps)
                return await body_fn(instance, ctx)

            body_factory = async_body
        else:
            body_factory = None

        contract = EndpointContract(
            method=method.upper(),
            path=path,
            auth=auth,
            category=category,
            tags=tags or [],
            description=description,
            prereqs=prereqs,
            body_factory=body_factory,
            expected_status=expected_status,
            expected_events=expected_events,
            failures=failures,
            idempotent=cls_idempotent,
            slow_timeout_sec=cls_slow,
            skip_es_verify=cls_skip_es,
        )
        _CONTRACTS[contract.key] = contract
        cls._contract = contract
        return cls

    return decorator


# ── Contract executor ────────────────────────────────────────────────────
@dataclass
class TestResult:
    """Uniform result returned by contract.run()."""
    healthy: bool
    status_code: Optional[int]
    response_time_ms: float
    expected_failure: bool = False
    expected_failure_reason: Optional[str] = None
    failure_bucket: Optional[str] = None
    response_data: Optional[Any] = None
    error: Optional[str] = None
    event_check: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "statusCode": self.status_code,
            "responseTime": self.response_time_ms,
            "expected_failure": self.expected_failure,
            "expected_failure_reason": self.expected_failure_reason,
            "failure_bucket": self.failure_bucket,
            "responseData": self.response_data,
            "error": self.error,
            "event_check": self.event_check,
        }


async def execute(
    contract: EndpointContract,
    ctx: BootstrapContext,
    *,
    http_client,  # httpx.AsyncClient or compatible
    target_url: str,
    es_verifier_fn=None,
) -> TestResult:
    """Execute a contract end-to-end.

    Steps:
      1. Resolve prereqs (fixtures) via ctx
      2. Build request body via body_factory
      3. Fire HTTP request via http_client
      4. Classify response (expected_status → healthy; else FailureMode chain → EF; else real fail)
      5. If healthy + expected_events, verify ES emission
    """
    import time

    # Resolve prereqs
    resolved_deps: Dict[str, Any] = {}
    try:
        for dep_name in contract.prereqs:
            resolved_deps[dep_name] = await ctx.resolve(dep_name, current_category=contract.category)
    except Exception as e:
        return TestResult(
            healthy=False,
            status_code=None,
            response_time_ms=0.0,
            error=f"prereq resolution failed: {e!r}",
        )

    # Build body
    body = None
    if contract.body_factory is not None:
        try:
            body = await contract.body_factory(**resolved_deps)
        except Exception as e:
            return TestResult(
                healthy=False,
                status_code=None,
                response_time_ms=0.0,
                error=f"body factory failed: {e!r}",
            )

    # Choose auth token
    if contract.auth == "developer":
        token = ctx.session_cache.get("admin_token") or ctx.extras.get("admin_token")
    elif contract.auth == "agent":
        token = ctx.session_cache.get("primary_agent_token") or ctx.extras.get("agent_token")
    else:
        token = None

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Prepend /api/v1 (catalog convention strips it; live routes need it).
    # Well-known endpoints (/.well-known/*) are mounted at nginx root and
    # MUST NOT receive the /api/v1 prefix — they'd 404 if dispatched as
    # /api/v1/.well-known/registry-card.json.
    api_path = contract.path
    if (not api_path.startswith("/api/v1")
            and not api_path.startswith("http")
            and not api_path.startswith("/.well-known/")):
        api_path = "/api/v1" + api_path

    # §SUITES1018 batch 6: a READ resolves its placeholders as the router's own rows do first (its list resolvers name a
    # real row: a circuit with ACIR, a season, a proposal), so a contract read stops asking the fallbacks below ("99999",
    # "test-circuit") and reporting the 404 they earn. Writes keep this module's map: a resolver may name a real object.
    if "{" in api_path and contract.method.upper() == "GET":
        try:
            from agentvault_registry.routers.admin_api_test import replace_path_placeholders as _router_placeholders
            prefixed = api_path.startswith("/api/v1")
            rel = await _router_placeholders(
                api_path[len("/api/v1"):] if prefixed else api_path,
                developer_token=ctx.session_cache.get("admin_token") or ctx.extras.get("admin_token"),
                agent_token=ctx.session_cache.get("primary_agent_token") or ctx.extras.get("agent_token"),
                method="GET")
            api_path = ("/api/v1" + rel) if prefixed else rel
        except Exception as _rx:  # noqa: BLE001 - the map below still applies
            logger.debug(f"router placeholders unavailable for {contract.key}: {_rx!r}")

    # Path placeholder substitution from DYNAMIC_VALUES + ctx.extras
    # (mirrors admin_api_test.py:replace_path_placeholders behaviour)
    if "{" in api_path:
        # Pull DYNAMIC_VALUES via the legacy registry (cross-worker via Redis)
        try:
            from agentvault_registry.routers.admin_api_test import (DYNAMIC_VALUES, _sandbox_tokens,
                                                                    _names_the_action_target)
            await DYNAMIC_VALUES.refresh_from_redis()
            await _sandbox_tokens.refresh_from_redis()
            # §SUITES1018 batch 8 (part 8, 8b): an admin action on one agent (enforcement, IRONHAND enrol and revoke,
            # transfer-ownership, the admin key rotation) names the sweep's action target (the router makes it before
            # the contract runs), else a DID of nothing: the V0625 suspend contract named the sweep's primary agent
            # and every later row acting as it was refused
            _own_agent = str(DYNAMIC_VALUES.get("agent_did") or _sandbox_tokens.get("agent_did") or "")
            _agent = (str(DYNAMIC_VALUES.get("enforcement_target_did") or "did:theprotocol:apitest-no-enforcement-target")
                      if _names_the_action_target(api_path) else _own_agent)
            subs = {
                "{agent_did}": _agent,
                "{did}": _agent,
                "{agent_id}": str(DYNAMIC_VALUES.get("agent_did") or _sandbox_tokens.get("agent_did") or ""),
                "{target_agent_did}": str(DYNAMIC_VALUES.get("agent_002_did") or _sandbox_tokens.get("agent_002_did") or ""),
                # §SUITES1018 batch 8: the org's member fixture on the member routes, else the sweep's own throwaway
                # developer (the router makes it before any contract runs), else an id no account holds: never "1",
                # a frame's first account and its admin (revoke-api-keys and a quota write are contracts)
                "{developer_id}": str((DYNAMIC_VALUES.get("member_developer_id") if "/members/{developer_id}" in api_path
                                       else (DYNAMIC_VALUES.get("target_dev_id")
                                             if DYNAMIC_VALUES.get("target_dev_own") else None))
                                      or "2147483647"),
                "{org_id}": str(DYNAMIC_VALUES.get("org_id") or "99999"),
                "{team_id}": str(DYNAMIC_VALUES.get("team_id") or "99999"),
                "{member_id}": str(DYNAMIC_VALUES.get("member_id") or "99999"),
                "{invitation_token}": str(DYNAMIC_VALUES.get("invitation_token") or "invalid-token"),
                "{invitation_id}": str(DYNAMIC_VALUES.get("frame_invitation_id") or "00000000-0000-0000-0000-000000000000"),
                "{request_id}": str(DYNAMIC_VALUES.get("funding_request_id") or "99999"),
                "{transaction_id}": str(DYNAMIC_VALUES.get("transaction_id") or "txn-00000"),
                "{dispute_id}": str(DYNAMIC_VALUES.get("dispute_id") or "99999"),
                "{dispute_log_id}": str(DYNAMIC_VALUES.get("dispute_log_id") or "99999"),
                "{contract_id}": str(DYNAMIC_VALUES.get("contract_id") or "99999"),
                "{proposal_id}": str(DYNAMIC_VALUES.get("proposal_id") or "99999"),
                "{policy_id}": str(DYNAMIC_VALUES.get("policy_id") or "99999"),
                "{pipeline_id}": str(DYNAMIC_VALUES.get("pipeline_id") or "99999"),
                "{version_id}": str(DYNAMIC_VALUES.get("version_id") or "99999"),
                "{deployment_id}": str(DYNAMIC_VALUES.get("deployment_id") or "99999"),
                "{template_id}": str(DYNAMIC_VALUES.get("template_id") or "99999"),
                "{webhook_id}": str(DYNAMIC_VALUES.get("webhook_id") or "99999"),
                "{broadcast_id}": str(DYNAMIC_VALUES.get("broadcast_id") or "99999"),
                "{bundle_id}": str(DYNAMIC_VALUES.get("bundle_id") or "00000000-0000-0000-0000-000000000000"),
                "{bundle_uuid}": str(DYNAMIC_VALUES.get("bundle_id") or "00000000-0000-0000-0000-000000000000"),
                "{report_id}": str(DYNAMIC_VALUES.get("report_id") or "00000000-0000-0000-0000-000000000000"),
                "{schedule_id}": str(DYNAMIC_VALUES.get("schedule_id") or "00000000-0000-0000-0000-000000000000"),
                "{attestation_id}": str(DYNAMIC_VALUES.get("attestation_id") or "00000000-0000-0000-0000-000000000000"),
                "{peer_id}": str(DYNAMIC_VALUES.get("peer_id") or "99999"),
                "{application_id}": str(DYNAMIC_VALUES.get("application_id") or "99999"),
                "{path_id}": str(DYNAMIC_VALUES.get("canary_path_id") or "99999"),
                "{ticket_id}": str(DYNAMIC_VALUES.get("ticket_id") or "99999"),
                "{action_id}": str(DYNAMIC_VALUES.get("action_id") or "00000000-0000-0000-0000-000000000000"),
                "{circuit_id:path}": "test-circuit",
                "{circuit_id}": "test-circuit",
                "{registry_url:path}": "https://placeholder.example.com",
                "{registry_url}": "https://placeholder.example.com",
                "{event_type}": "TokensTransferred",
                "{template}": "fiat_purchase_completed",
                "{flag_id}": str(DYNAMIC_VALUES.get("flag_id") or "00000000-0000-0000-0000-000000000000"),
                "{session_id}": "cs_test_placeholder",
                "{purchase_id}": str(DYNAMIC_VALUES.get("purchase_id") or "99999"),
                "{kid}": "kid-placeholder",
                "{code}": str(DYNAMIC_VALUES.get("invite_code") or "code-placeholder"),
                "{client_id}": str(DYNAMIC_VALUES.get("client_id") or "client-placeholder"),
                "{human_readable_id:path}": str(DYNAMIC_VALUES.get("human_readable_id") or "test-card"),
                "{human_readable_id}": str(DYNAMIC_VALUES.get("human_readable_id") or "test-card"),
                "{safe_name}": "api-test-operator-placeholder",
                "{key_id}": "key-placeholder",
                "{operator_id}": str(DYNAMIC_VALUES.get("operator_id") or "99999"),
                "{operator_slug}": "op-test",
                "{worker_id}": "cross_teg_sweeper",
            }
            for placeholder, value in subs.items():
                api_path = api_path.replace(placeholder, value)
        except Exception as _ph_ex:
            logger.debug(f"placeholder sub partial: {_ph_ex!r}")

    full_url = f"{target_url.rstrip('/')}{api_path}"
    timeout = contract.slow_timeout_sec or 30.0

    t0 = time.time()
    try:
        r = await http_client.request(
            contract.method,
            full_url,
            json=body if body is not None else None,
            headers=headers,
            timeout=timeout,
        )
        elapsed_ms = (time.time() - t0) * 1000.0
        try:
            body_json = r.json()
        except Exception:
            body_json = None
        body_text = r.text or ""
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000.0
        # §pass63 follow-up (2026-05-22) — when a transport error fires
        # (ReadTimeout / ConnectError / etc.) we still classify against the
        # contract's FailureMode list with status=None + empty body so contracts
        # can declare a transport-timeout as EF (e.g., docker-stats's known 90s
        # serial loop). This makes `FailureMode(condition=lambda r: r.status is None, ...)`
        # actually reachable. Previously the early return skipped classification.
        try:
            transport_probe = ResponseProbe(
                status=None,
                body_text="",
                body_json=None,
                headers={},
            )
            transport_match = classify(transport_probe, getattr(contract, 'failures', []) or [])
            if transport_match:
                return TestResult(
                    healthy=True,
                    status_code=None,
                    response_time_ms=elapsed_ms,
                    expected_failure=True,
                    expected_failure_reason=f"{transport_match.reason} (transport {type(e).__name__})",
                    failure_bucket=transport_match.bucket.value,
                    error=f"transport: {type(e).__name__}: {str(e)[:160]}",
                )
        except Exception as _classify_ex:
            logger.debug(f"transport-classify skipped: {_classify_ex!r}")
        return TestResult(
            healthy=False,
            status_code=None,
            response_time_ms=elapsed_ms,
            error=f"transport: {type(e).__name__}: {str(e)[:200]}",
        )

    # Classify
    expected_codes = (
        [contract.expected_status]
        if isinstance(contract.expected_status, int)
        else list(contract.expected_status)
    )
    is_expected = r.status_code in expected_codes

    if is_expected and r.status_code >= 400:
        # §SUITES1018: a refusal the contract accepts is an EXPECTED FAILURE, never a pass. The legacy chain was put right
        # in batch 3; a contract listing a 4xx in expected_status still counted it healthy (106 rows of the 2026-10-18
        # rehearsal, e.g. GET /governance/proposals/{proposal_id} answering 404 on the fallback id "1"). A request-
        # validation 422 among them becomes NOT MEASURED at the router's one exit (_runner_gap_is_not_measured).
        matched = classify(ResponseProbe(status=r.status_code, body_text=body_text, body_json=body_json,
                                         headers=dict(r.headers)), contract.failures)
        if isinstance(body_json, dict):
            said = body_json.get("detail") or (body_json.get("error") or {})
            said = said.get("detail") or said.get("message") if isinstance(said, dict) else said
        else:
            said = body_text
        return TestResult(
            healthy=True,  # EF stamp counts as healthy in summary
            status_code=r.status_code,
            response_time_ms=elapsed_ms,
            expected_failure=True,
            expected_failure_reason=(matched.reason if matched
                                     else f"the contract accepts {r.status_code}: {str(said or '')[:160]}"),
            failure_bucket=(matched.bucket.value if matched else "accepted_refusal"),
            response_data=body_json,
        )

    if is_expected:
        # Healthy. Optional ES event verification.
        event_check = None
        if contract.expected_events and not contract.skip_es_verify and es_verifier_fn:
            try:
                event_check = await es_verifier_fn(contract.expected_events)
                if not event_check.get("all_seen", True):
                    return TestResult(
                        healthy=False,
                        status_code=r.status_code,
                        response_time_ms=elapsed_ms,
                        response_data=body_json,
                        error=f"ES events missing: {event_check.get('missing')}",
                        event_check=event_check,
                    )
            except Exception as e:
                logger.warning(f"ES verifier failed for {contract.key}: {e!r}")
        return TestResult(
            healthy=True,
            status_code=r.status_code,
            response_time_ms=elapsed_ms,
            response_data=body_json,
            event_check=event_check,
        )

    # Non-expected status — try EF classification
    probe = ResponseProbe(
        status=r.status_code,
        body_text=body_text,
        body_json=body_json,
        headers=dict(r.headers),
    )
    matched = classify(probe, contract.failures)
    if matched:
        return TestResult(
            healthy=True,  # EF stamp counts as healthy in summary
            status_code=r.status_code,
            response_time_ms=elapsed_ms,
            expected_failure=True,
            expected_failure_reason=matched.reason,
            failure_bucket=matched.bucket.value,
            response_data=body_json,
        )

    # AAA+ fall-through: contract has no opinion on this status code → return
    # `None` so the caller can fall back to the legacy inline EF chain. This
    # makes contracts ADDITIVE — they only improve classification, never make
    # it worse than the inline baseline.
    return None  # type: ignore[return-value]
