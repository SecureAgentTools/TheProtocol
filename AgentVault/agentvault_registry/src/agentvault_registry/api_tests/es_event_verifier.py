"""
ES event verification for the BFF api tester.

After a test fires an endpoint, this module polls the EventStore's
`/api/v1/events/export` endpoint to confirm that the side-effect events
the endpoint is supposed to emit actually landed. This catches the
class of bugs where a test passes (HTTP 200 returned) but the event-
emission gate (f037) silently dropped the event.

Usage:
    from .es_event_verifier import verify_events, get_expected_events, get_max_wait_sec

    expected = get_expected_events(method, path)
    if expected and result["healthy"] and not result.get("expected_failure"):
        wait_sec = get_max_wait_sec(method, path)
        check = await verify_events(t_pre_action_iso, expected, max_wait_sec=wait_sec)
        result["event_check"] = check
        if not check["all_seen"]:
            result["healthy"] = False
            result["error"] = f"ES missed: {check['missing']}"
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Expected events catalogue
# -----------------------------------------------------------------------------
# Maps (method, path) tuples to a list of event-type specs.
# Each spec: {"event_type": str, "match": dict (optional, payload subset to match)}
# Path keys use the catalogue paths (with placeholders preserved — the BFF
# substitutes them before firing).
#
# Event-type values verified against:
#   - event_emission_policies table on agentvault_registry_a (47 rows, 2026-05-07)
#   - sandbox eventstore_test distinct event_type emissions (last 24h)
#   - source-code grep of `event_type=` literals in routers/
#
# Notes on emit timing (drives MAX_WAIT_OVERRIDE below):
#   - emit_background(...)       — fire-and-forget, may land 1-10s later under load
#   - await event_emitter.emit(...) — synchronous before HTTP response returns
#   - asyncio.create_task(emit)   — fire-and-forget, usually <1s but can lag
# -----------------------------------------------------------------------------
EXPECTED_EVENTS: Dict[tuple, List[Dict[str, Any]]] = {
    # ----- Token transfers (TEG router uses emit_background) ---------------
    ("POST", "/teg/transfer"): [
        {"event_type": "TokensTransferred"},
        {"event_type": "TransactionFeeCollected"},
    ],
    ("POST", "/teg/system-transfer"): [
        {"event_type": "TokensTransferred"},
    ],
    ("POST", "/teg/cross-registry-transfer"): [
        {"event_type": "TokensTransferred"},
        {"event_type": "CrossRegistryTransferCompleted"},
    ],
    ("POST", "/teg/treasury/fund-agent"): [
        {"event_type": "TokensTransferred"},
    ],
    ("POST", "/teg/treasury/mint"): [
        {"event_type": "TokensIssued"},
        {"event_type": "TokensTransferred"},
    ],

    # ----- Staking ---------------------------------------------------------
    # NB: staking_enhanced.py passes event_type="stake.completed" to
    # emit_staking_event, which translates to event_emitter.emit_tokens_staked
    # → the actual ES event_type is `TokensStaked` / `TokensUnstaked`.
    ("POST", "/staking/stake"): [
        {"event_type": "TokensStaked"},
    ],
    ("POST", "/staking/unstake"): [
        {"event_type": "TokensUnstaked"},
    ],

    # ----- Agent lifecycle -------------------------------------------------
    ("POST", "/onboard/create_agent"): [
        {"event_type": "AgentOnboarded"},
    ],
    ("POST", "/agents/heartbeat"): [
        {"event_type": "AgentHeartbeat"},
    ],

    # ----- Governance (governance.py uses emit_background) -----------------
    ("POST", "/governance/proposals"): [
        {"event_type": "ProposalCreated"},
    ],
    ("POST", "/governance/proposals/{proposal_id}/vote"): [
        {"event_type": "VoteCast"},
    ],
    ("POST", "/governance/proposals/{proposal_id}/tally"): [
        {"event_type": "ProposalTallied"},
    ],

    # ----- A2A payment (f045) ----------------------------------------------
    # Only authorize emits a dedicated event; settle's effect goes through
    # /teg/transfer's TokensTransferred (already covered above).
    ("POST", "/a2a-payment/authorize"): [
        {"event_type": "A2APaymentAuthorized"},
    ],

    # ----- Disputes / contracts (foreground create_task) -------------------
    ("POST", "/disputes/"): [
        {"event_type": "DisputeFiled"},
    ],
    ("POST", "/disputes/{dispute_id}/evidence"): [
        {"event_type": "EvidenceSubmitted"},
    ],
    ("POST", "/contracts/"): [
        {"event_type": "ContractCreated"},
    ],
    ("POST", "/contracts/{contract_id}/accept"): [
        {"event_type": "ContractAccepted"},
    ],
    ("POST", "/contracts/{contract_id}/submit"): [
        {"event_type": "ContractWorkSubmitted"},
    ],
    ("POST", "/contracts/{contract_id}/approve-completion"): [
        {"event_type": "ContractCompleted"},
    ],

    # ----- Reputation bond (foreground await) ------------------------------
    ("POST", "/agents/reputation-bond/deposit"): [
        {"event_type": "ReputationBondDeposited"},
    ],

    # ----- Attestations (foreground await) ---------------------------------
    ("POST", "/attestations/submit"): [
        {"event_type": "AttestationSubmitted"},
    ],

    # ----- IRONHAND mTLS (foreground await) --------------------------------
    ("POST", "/agent/enable-mtls"): [
        {"event_type": "AgentMtlsEnrolled"},
    ],

    # ----- Admin agent management (foreground await via _emit_admin_action)
    # All accept the {target_agent_did} placeholder which the BFF substitutes
    # to the secondary onboarded agent (agent_002_did) so the action is
    # idempotent against the throwaway counterparty.
    ("POST", "/admin/agents/{target_agent_did}/transfer-ownership"): [
        {"event_type": "AgentOwnershipTransferred"},
    ],
    ("POST", "/admin/agents/{target_agent_did}/rotate-credentials"): [
        {"event_type": "AgentCredentialsRotated"},
    ],
    ("POST", "/admin/agents/{target_agent_did}/force-mtls-enrol"): [
        {"event_type": "AgentMtlsEnrolled"},
    ],

    # ----- Funding requests (admin approve/reject foreground create_task) --
    ("POST", "/admin/funding/{request_id}/approve"): [
        {"event_type": "FundingRequestApproved"},
    ],
    ("POST", "/admin/funding/{request_id}/reject"): [
        {"event_type": "FundingRequestRejected"},
    ],

    # ----- Admin meta (foreground await) -----------------------------------
    ("POST", "/admin/projection-snapshot"): [
        {"event_type": "ProjectionSnapshot"},
    ],
    ("PUT", "/admin/event-emission-policies/{event_type}"): [
        {"event_type": "EventEmissionPolicyUpdated"},
    ],

    # ----- Frame invitations (foreground await _emit_event) ----------------
    # NB: /federation/frame-invitations (POST public) emits FrameInvitationRequested
    # but the BFF body uses synthetic trust domain → handler probes target and
    # rejects with 422 (EF). The endpoint never returns 200 so the verifier won't run.
    # /admin/federation/frame-invitations/{id}/reject is reachable via the prereq;
    # it emits FrameInvitationRejected synchronously.
    ("POST", "/admin/federation/frame-invitations/{invitation_id}/reject"): [
        {"event_type": "FrameInvitationRejected"},
    ],

    # ----- Federation admission --------------------------------------------
    ("POST", "/admin/federation/complete-admission/{admission_id}"): [
        {"event_type": "RegistryFederated"},
    ],

    # ----- Federation peer slash config ------------------------------------
    ("PUT", "/federation/disputes/peer-slash-config/{peer_id}"): [
        {"event_type": "PeerSlashConfigUpdated"},
    ],
}


# -----------------------------------------------------------------------------
# Per-endpoint max-wait-sec override
# -----------------------------------------------------------------------------
# Default is DEFAULT_MAX_WAIT_SEC (8s). Override here for endpoints whose emit
# path is async-buffered (emit_background) or otherwise prone to lag under load.
#
# Verified background-emit endpoints (teg_integration.py, governance.py):
#   /teg/transfer              line 1051 emit_background TokensTransferred
#   /teg/transfer              line 1066 emit_background TransactionFeeCollected
#   /teg/system-transfer       line 1051 emit_background TokensTransferred
#   /teg/cross-registry-transfer line 3832/3866 emit_background
#   /teg/treasury/fund-agent   uses internal /teg/transfer flow
#   /teg/treasury/mint         line 4776 await emit (TokensIssued) + 4909 await emit
#   /governance/proposals      line 203 emit_background ProposalCreated
#   /governance/proposals/{id}/vote line 388 emit_background VoteCast
#   /governance/proposals/{id}/tally line 523 emit_background ProposalTallied
DEFAULT_MAX_WAIT_SEC: float = 8.0

MAX_WAIT_OVERRIDE: Dict[tuple, float] = {
    # Background-emit (emit_background) — bump to 12-60s based on observed lag.
    # Idle spot tests land in <1s; under sweep load (sequential, ES queue
    # contention, projection lag) baseline 2026-05-07 shows lag bumps:
    #   /teg/system-transfer    v1 missed at 12s twice → 18s (v2 still missed once → 30s)
    #   /governance/.../vote    v2 missed at 30s 3× → 60s (worst observed background lag)
    #   /agent/enable-mtls      v2 missed at 15s 2× → 30s
    #   /federation/.../peer-slash-config  v2 missed default → 25s
    ("POST", "/teg/transfer"): 12.0,
    # Bumped once more after v5b: /teg/system-transfer + /teg/treasury/mint
    # still MISS at 30s under sweep load. Push to 45s — closing diminishing-
    # return gap. Idle <1s; signal still real if MISS at 45+ s.
    ("POST", "/teg/system-transfer"): 45.0,
    ("POST", "/teg/cross-registry-transfer"): 15.0,
    ("POST", "/teg/treasury/fund-agent"): 12.0,
    ("POST", "/teg/treasury/mint"): 45.0,
    ("POST", "/governance/proposals"): 12.0,
    ("POST", "/governance/proposals/{proposal_id}/vote"): 60.0,
    ("POST", "/governance/proposals/{proposal_id}/tally"): 20.0,
    # /agent/enable-mtls — emit_agent_mtls_enrolled is foreground await but
    # SPIRE registration + DB commit + ES POST stack lag past 45s under sweep
    # (v5b + v6 each MISSED twice). Bumping to 90s — closing the wait window
    # gap. If still missing at 90s, the emit is genuinely lost; investigate ES.
    ("POST", "/agent/enable-mtls"): 90.0,
    ("PUT", "/federation/disputes/peer-slash-config/{peer_id}"): 25.0,
}


# -----------------------------------------------------------------------------
# Verifier
# -----------------------------------------------------------------------------

async def verify_events(
    since_iso: str,
    expected: List[Dict[str, Any]],
    *,
    es_url: Optional[str] = None,
    api_key: Optional[str] = None,
    max_wait_sec: Optional[float] = None,
    poll_interval_sec: float = 0.5,
) -> Dict[str, Any]:
    """Poll ES `/api/v1/events/export` for each expected event_type.

    Returns:
        {
            "all_seen": bool,
            "seen": [{event_type, id, timestamp}, ...],
            "missing": [event_type, ...],
            "expected_count": int,
            "elapsed_sec": float,
            "max_wait_sec": float,   # the actual wait window used
        }

    Each expected spec may include an optional "match" dict that is matched
    against the event's payload (subset match).

    Args:
        since_iso: ISO-8601 timestamp captured BEFORE the action fired.
        expected:  List of {"event_type": str, "match": dict} specs.
        es_url:    EventStore URL. Defaults to $API_TEST_EVENT_STORE_URL or sandbox.
        api_key:   X-Internal-Key for ES auth. Defaults to $API_TEST_EVENT_STORE_API_KEY
                   or the well-known sandbox key.
        max_wait_sec: Max time to wait. None → DEFAULT_MAX_WAIT_SEC (8s).
        poll_interval_sec: Sleep between polls.
    """
    import time

    if max_wait_sec is None:
        max_wait_sec = DEFAULT_MAX_WAIT_SEC

    if not expected:
        return {
            "all_seen": True, "seen": [], "missing": [], "expected_count": 0,
            "elapsed_sec": 0.0, "max_wait_sec": max_wait_sec,
        }

    # The BFF tester targets sandbox via API_TEST_TARGET_URL (registry-test:8000),
    # so the side-effect events emit to the SANDBOX EventStore. Override the local
    # registry-a EVENT_STORE_URL (which points at prod) with the sandbox ES URL.
    if not es_url and not os.getenv("API_TEST_EVENT_STORE_URL"):
        # §TRUSTCHAIN P4.6: derive from the TARGET (§EMITDIAG), never a torn-down tier's literal.
        from agentvault_registry.core.es_url_for_target import es_url_for_target
        es_url = es_url_for_target(os.getenv("API_TEST_TARGET_URL", ""))
    es_url = es_url or os.getenv("API_TEST_EVENT_STORE_URL") or ""
    # Default to the sandbox ES api key (well-known constant from sandbox setup,
    # lives in agentvault_event_store_test's INTERNAL_API_KEY env). Override
    # via API_TEST_EVENT_STORE_API_KEY if it ever rotates.
    api_key = (
        api_key
        or os.getenv("API_TEST_EVENT_STORE_API_KEY")
        or "sandbox-event-store-api-key-2026"
    )

    seen: List[Dict[str, Any]] = []
    missing_types = {spec["event_type"] for spec in expected}
    matchers: Dict[str, Dict[str, Any]] = {
        spec["event_type"]: spec.get("match") or {} for spec in expected
    }

    t0 = time.monotonic()
    deadline = t0 + max_wait_sec

    # Use a single shared client across polls to keep connection alive.
    # §SOVKIT T5 (2026-09-14): the target store's TLS context (SPIRE bundle + system roots + the SVID); verify=False with
    # no certificate reads nothing from a store behind its frame's mTLS sidecar.
    from agentvault_registry.es_ssl_helper import get_httpx_verify
    async with httpx.AsyncClient(verify=get_httpx_verify(), timeout=4) as cli:
        while missing_types and time.monotonic() < deadline:
            for et in list(missing_types):
                # W4 (agentvault2-aa, 2026-10-25): the expected event under each name it may be written under
                for _name in ledger_names.live_names(et):
                    if et not in missing_types:
                        break
                    try:
                        r = await cli.get(
                            f"{es_url}/api/v1/events/export",
                            params={"since": since_iso, "event_type": _name, "limit": 50},
                            headers={"X-Internal-Key": api_key} if api_key else {},
                        )
                        if r.status_code == 200:
                            # ES /events/export returns a JSON array of events directly.
                            # Each event has shape: {id, event_type, data, timestamp, ...}
                            # — note the side-effect payload lives under `data`.
                            events = r.json()
                            if not isinstance(events, list):
                                events = events.get("events", []) if isinstance(events, dict) else []
                            match_spec = matchers.get(et) or {}
                            for ev in events:
                                data = ev.get("data") or {}
                                if all(data.get(k) == v for k, v in match_spec.items()):
                                    seen.append({
                                        "event_type": et,
                                        "id": ev.get("id"),
                                        "timestamp": ev.get("timestamp"),
                                    })
                                    missing_types.discard(et)
                                    break
                    except httpx.HTTPError as e:
                        logger.debug(f"[ES Verify] poll error for {_name}: {e}")
                    except Exception as e:
                        logger.warning(f"[ES Verify] unexpected error for {_name}: {e}")
            if missing_types:
                await asyncio.sleep(poll_interval_sec)

    return {
        "all_seen": len(missing_types) == 0,
        "seen": seen,
        "missing": sorted(missing_types),
        "expected_count": len(expected),
        "elapsed_sec": round(time.monotonic() - t0, 3),
        "max_wait_sec": max_wait_sec,
    }


def get_expected_events(method: str, path: str) -> Optional[List[Dict[str, Any]]]:
    """Look up the expected-events spec for a (method, path) tuple.

    Returns the spec list (possibly empty) or None if the endpoint isn't in
    the catalogue.
    """
    return EXPECTED_EVENTS.get((method.upper(), path))


def get_max_wait_sec(method: str, path: str) -> float:
    """Look up the per-endpoint max_wait_sec override.

    Returns DEFAULT_MAX_WAIT_SEC if not overridden.
    """
    return MAX_WAIT_OVERRIDE.get((method.upper(), path), DEFAULT_MAX_WAIT_SEC)
