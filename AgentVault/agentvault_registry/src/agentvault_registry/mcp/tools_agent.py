"""
MCP Tier 2 — Agent Operation Tools (agent JWT required).

These tools allow authenticated agents to interact with TheProtocol's
economic and governance systems. Requires a valid agent JWT in the
Authorization: Bearer header.

To get an agent JWT:
    POST /api/v1/auth/agent/token
    Content-Type: application/x-www-form-urlencoded
    Body: username=<client_id>&password=<client_secret>

Tools:
  theprotocol.getMyBalance     — Get agent token balances and veToken power
  theprotocol.transferUnits   — Transfer AVT tokens to another agent
  theprotocol.bridgeTransfer   — Cross-frame AVT bridge (SF-3)
  theprotocol.lockUnits      — Stake AVT tokens for rewards and governance power
  theprotocol.unlockUnits    — Unstake a specific staking position
  theprotocol.castVote         — Vote on an Agent Senate governance proposal
  theprotocol.getAgentToken    — Tier 0 utility: mint an agent JWT from client_id+client_secret

§pass70 (2026-05-24) — Sprint 1 migration:
  - get_my_balance: 1 DB transaction + 1 HTTP → single HTTP call to /staking/balance
    (which already includes voting_power + active_stakes_count). Live /teg/balance
    call dropped as redundant (Agent.liquid_balance is synced from TEG).
  - stake_tokens: dropped cosmetic post-mutation APY display (caller can invoke
    getLockPayoutTiers separately).
  - unstake_tokens: ownership pre-check migrated from direct Stake SELECT to
    GET /staking/my-positions + client-side filter.
  - Removed dead imports: crud_governance (never called), event_emitter (never
    called), _get_teg_agent_token helper (never invoked), Stake/Agent models,
    vetoken_calculator (now served by /staking/balance).
"""
import logging
import uuid
from decimal import Decimal
from typing import Dict, Any, List, Optional

import httpx

from ..config import settings
from .auth_bridge import MCPAuthContext, require_agent_auth, MCPAuthError, format_tool_exception, mcp_forwarded_headers
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .refusal import http_refusal, refusal_reason  # §MCPTEST30: a refusal carries its reason
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)


def _frame_unit() -> str:
    # D6-835 (2026-10-25): this frame's unit, asked where the amount is written (it said AVT on every frame)
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()

# Internal registry URL for forwarding auth'd requests to the existing API.
# In Docker: override with REGISTRY_SELF_URL=http://registry-a:8000
REGISTRY_SELF_URL = getattr(settings, "REGISTRY_SELF_URL", "http://localhost:8000")
HTTPX_TIMEOUT_SHORT = 10.0
HTTPX_TIMEOUT_MUTATE = 30.0


# ---------------------------------------------------------------------------
# Tier 0 — getAgentToken (no auth required)
# ---------------------------------------------------------------------------

async def get_agent_token(client_id: str, client_secret: str) -> Dict[str, Any]:
    """
    Obtain an agent JWT via OAuth2 client_credentials flow.

    Args:
        client_id     : Agent OAuth2 client_id (e.g. agent-90663061387409b6)
        client_secret : Agent OAuth2 client_secret (tp_secret_...)
    """
    if not client_id or not client_secret:
        return {"error": "client_id and client_secret are required"}

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            response = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/auth/agent/token",
                data={
                    "grant_type": "password",
                    "username": client_id,
                    "password": client_secret,
                    "scope": "",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code == 200:
            data = response.json()
            return {
                "access_token": data.get("access_token", ""),
                "token_type": data.get("token_type", "bearer"),
                "expires_in": data.get("expires_in"),
                "note": (
                    "Token obtained. Pass this access_token as the agent_jwt parameter "
                    "directly to any Tier 2 tool (getMyBalance, transferUnits, lockUnits, "
                    "unlockUnits, castVote). No bridge reconfiguration or restart required."
                ),
            }
        elif response.status_code == 401:
            return {"error": "Invalid client_id or client_secret"}
        else:
            return {"error": http_refusal("Auth endpoint", response)}

    except httpx.ConnectError:
        return {"error": f"Cannot reach registry at {REGISTRY_SELF_URL}"}
    except Exception as e:
        logger.error(f"getAgentToken error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.getMyBalance
# ---------------------------------------------------------------------------

async def get_my_balance(auth: MCPAuthContext) -> Dict[str, Any]:
    """
    Get your agent's balance in units, its staking positions, and the voting weight of its locked units
    (where votes count by membership, getMyVotingPower is the one to read).

    §pass70 — single HTTP call to /staking/balance which returns all needed fields
    (liquid + staked + total + voting_power + active_stakes_count + pending_rewards).
    Replaces previous DB-direct lookup + redundant /teg/balance call.

    Requires agent authentication.
    """
    require_agent_auth(auth)

    if not auth.raw_token:
        return {"error": "No authentication token available"}

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/balance",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": f"staking/balance returned HTTP {r.status_code}: {r.text[:200]}"}

        d = r.json()
        voting_power_str = str(d.get("voting_power", "0"))
        try:
            voting_power_num = float(voting_power_str)
        except (ValueError, TypeError):
            voting_power_num = 0.0

        from .pocket_links import pocket_link
        return {
            "agent_did": d.get("agent_did") or auth.agent_did,
            "open_in_app": pocket_link("/pocket/home"),
            "liquid_balance": str(d.get("liquid_balance", "0")),
            "staked_balance": str(d.get("staked_balance", "0")),
            "total_balance": str(d.get("total_balance", "0")),
            "ve_token_power": voting_power_str,
            "can_vote": voting_power_num > 0,
            "active_stakes": int(d.get("active_stakes_count", 0)),
            "pending_rewards": str(d.get("pending_rewards", "0")),
            "last_updated": d.get("last_updated"),
        }

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "getMyBalance timed out"}
    except Exception as e:
        logger.error(f"getMyBalance error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.transferUnits
# ---------------------------------------------------------------------------

async def transfer_tokens(
    auth: MCPAuthContext,
    recipient_did: str,
    amount: str,
    message: str = "",
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transfer units to another agent on this registry via the TEG layer. Pass `idempotency_key` and reuse it on a retry.

    Requires agent authentication.

    Args:
        recipient_did : DID of the receiving agent
        amount        : Amount in the frame's units (as string, e.g. "10.5")
        message       : Optional transfer memo (max 256 chars)
    """
    require_agent_auth(auth)

    if not recipient_did:
        return {"error": "recipient_did is required"}
    if not amount:
        return {"error": "amount is required"}

    try:
        Decimal(amount)
    except Exception:
        return {"error": f"Invalid amount '{amount}' — must be a numeric string"}

    if not auth.raw_token:
        return {"error": "No authentication token available for transfer"}

    payload: Dict[str, Any] = {
        "receiver_agent_id": recipient_did,
        "amount": amount,
    }
    if message:
        payload["message"] = message[:256]

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/teg/transfer",
                json=payload,
                headers={
                    "Authorization": f"Bearer {auth.raw_token}",
                    "Content-Type": "application/json",
                    **mcp_forwarded_headers(),
                    **idempotency_header(auth, idempotency_key),
                },
            )
        if r.status_code == 200:
            data = r.json()
            return {
                "transaction_id": data.get("transaction_id", ""),
                "status": data.get("status", "completed"),
                "sender_did": auth.agent_did,
                "recipient_did": recipient_did,
                "amount": amount,
                "fee_amount": data.get("fee_amount", "0"),
                "new_sender_balance": data.get("new_sender_balance", ""),
                "timestamp": data.get("timestamp", ""),
                "message": message or None,
            }
        error_detail = refusal_reason(r)
        return {"error": f"Transfer failed (HTTP {r.status_code}): {error_detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Transfer request timed out"}
    except Exception as e:
        logger.error(f"transferUnits error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.smartSend (f060 — unified auto-routed transfer)
# ---------------------------------------------------------------------------

async def smart_send_tool(
    auth: MCPAuthContext,
    receiver_did: str,
    amount: str,
    message: str = "",
    backend: str = "",
    dry_run: bool = False,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Smart transfer: one call for any destination. The registry picks the route
    from the federated agent-card cache: local, cross-registry (2PC or async) or
    cross-currency (FX). dry_run=True previews the route decision without moving
    anything. Pass `idempotency_key` and reuse it on a retry (D6-054: /teg/send
    forwards the Idempotency-Key to the rail it picks, which answers the first
    result again for 24 h instead of moving units twice; before, this tool sent
    none, so a retried call that had timed out could move units twice).

    Args:
        receiver_did : DID of the receiving agent (local or federated)
        amount       : Amount in the SENDER frame's currency (numeric string)
        message      : Optional transfer memo
        backend      : Optional same-currency remote hint: '2pc' (sync) | 'async'
        dry_run      : Preview the route; move nothing
    """
    require_agent_auth(auth)

    if not receiver_did:
        return {"error": "receiver_did is required"}
    if not amount:
        return {"error": "amount is required"}
    try:
        Decimal(amount)
    except Exception:
        return {"error": f"Invalid amount '{amount}' — must be a numeric string"}
    if not auth.raw_token:
        return {"error": "No authentication token available for smart send"}

    payload: Dict[str, Any] = {
        "receiver_did": receiver_did,
        "amount": amount,
        "dry_run": bool(dry_run),
    }
    if message:
        payload["message"] = message[:500]
    if backend:
        payload["backend"] = backend

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/teg/send",
                json=payload,
                headers={
                    "Authorization": f"Bearer {auth.raw_token}",
                    "Content-Type": "application/json",
                    **mcp_forwarded_headers(),
                    **idempotency_header(auth, idempotency_key),
                },
            )
        if r.status_code in (200, 201, 202):
            from .pocket_links import with_pocket_link
            return with_pocket_link(r.json(), "/pocket/activity")
        error_detail = refusal_reason(r)
        return {"error": f"Smart send failed (HTTP {r.status_code})", "detail": error_detail}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Smart send request timed out"}
    except Exception as e:
        logger.error(f"smartSend error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.bridgeTransfer (SF-3)
# ---------------------------------------------------------------------------

async def bridge_transfer(
    auth: MCPAuthContext,
    target_agent_did: str,
    amount: str,
    target_frame_url: str = "",
    target_trust_domain: str = "",
) -> Dict[str, Any]:
    """
    Move units to an agent on another frame through the token bridge (a switch per registry, token_bridge_enabled).
    """
    require_agent_auth(auth)

    if not target_agent_did:
        return {"error": "target_agent_did is required"}
    if not amount:
        return {"error": "amount is required"}
    try:
        Decimal(amount)
    except Exception:
        return {"error": f"Invalid amount '{amount}'"}

    if not auth.raw_token:
        return {"error": "No authentication token available"}

    payload: Dict[str, Any] = {"target_agent_did": target_agent_did, "amount": amount}
    if target_frame_url:
        payload["target_frame_url"] = target_frame_url
    if target_trust_domain:
        payload["target_trust_domain"] = target_trust_domain

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/bridge/transfer",
                json=payload,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json", **mcp_forwarded_headers()},
            )
        if r.status_code == 200:
            return r.json()
        error_detail = refusal_reason(r)
        return {"error": f"Bridge transfer failed (HTTP {r.status_code}): {error_detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Bridge transfer timed out"}
    except Exception as e:
        logger.error(f"bridgeTransfer error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.lockUnits
# ---------------------------------------------------------------------------

async def stake_tokens(
    auth: MCPAuthContext,
    amount: str,
    lock_period_days: int = 30,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lock units in a staking position (STAKING_ENABLED; off on the public network, where the route answers 403).

    §pass70 — dropped cosmetic post-success APY display read (caller can invoke
    getLockPayoutTiers separately if they want the rate).

    Requires agent authentication.

    Args:
        amount           : amount to lock, in the frame's units (as string)
        lock_period_days : Lock duration in days: 0, 7, 30, 90, 180, or 365
    """
    require_agent_auth(auth)

    if not amount:
        return {"error": "amount is required"}
    try:
        stake_amount = Decimal(amount)
        if stake_amount <= 0:
            return {"error": "amount must be positive"}
    except Exception:
        return {"error": f"Invalid amount '{amount}'"}

    valid_lock_periods = (0, 7, 30, 90, 180, 365)
    if lock_period_days not in valid_lock_periods:
        return {"error": f"Invalid lock_period_days '{lock_period_days}'. Valid: {valid_lock_periods}"}

    if not auth.raw_token:
        return {"error": "No authentication token available for locking"}

    try:
        # §MCPTEST30: a fresh random key in the BODY, which the route never reads, made no lock idempotent; a caller's
        # key now rides the header the route reads (idempotency_header)
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/staking/stake",
                json={"amount": amount, "lock_period": lock_period_days},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json",
                         **mcp_forwarded_headers(), **idempotency_header(auth, idempotency_key)},
            )

        if r.status_code in (200, 201):
            data = r.json()
            from .pocket_links import pocket_link
            return {
                "stake_id": str(data.get("stake_id") or data.get("id", "")),
                "amount": amount,
                "lock_period_days": lock_period_days,
                "status": data.get("status", "active"),
                "unlock_date": data.get("unlock_date") or data.get("unlockDate"),
                "message": f"Locked {amount} {_frame_unit()} for {lock_period_days} days",   # D6-835: not AVT on every frame
                "open_in_app": pocket_link("/pocket/payments"),
            }
        detail = refusal_reason(r)
        return {"error": f"Lock failed (HTTP {r.status_code}): {detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Lock request timed out"}
    except Exception as e:
        logger.error(f"lockUnits error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.unlockUnits
# ---------------------------------------------------------------------------

async def unstake_tokens(auth: MCPAuthContext, stake_id: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Release the named position in full, and only that position.

    §pass70 — ownership pre-check migrated from direct Stake SELECT to
    GET /staking/my-positions (which is agent-scoped via Security(get_current_agent)).
    D6-017 (2026-10-16): the call names the position (`position_id`, §FESUITE). With the amount alone the route
    released that amount from the unlocked positions oldest first, so a position other than the named one could go,
    and a still-locked named position did not stop it. Now a locked position is refused (403, with its unlock date)
    and nothing else is touched.

    Requires agent authentication.
    """
    require_agent_auth(auth)

    if not stake_id:
        return {"error": "stake_id is required"}

    if not auth.raw_token:
        return {"error": "No authentication token available for unlocking"}

    try:
        # Step 1: look up agent's positions via HTTP (instead of direct DB Stake SELECT)
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/my-positions",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("my-positions", r)}

        positions_resp = r.json()
        # /staking/my-positions returns either {positions: [...]} or [...] directly
        positions = positions_resp.get("positions", positions_resp) if isinstance(positions_resp, dict) else positions_resp
        if not isinstance(positions, list):
            return {"error": "unexpected my-positions response shape"}

        # Find the matching position. stake_id may be int or string; compare as string. my-positions lists released
        # positions too ("unstaked"): those are not positions to release.
        target_id_str = str(stake_id)
        matching = next(
            (p for p in positions if str(p.get("id") or p.get("stake_id")) == target_id_str
             and str(p.get("status", "active")).lower() != "unstaked"),
            None,
        )
        if not matching:
            return {"error": (
                f"Lock position '{stake_id}' not found, already unlocked, "
                f"or does not belong to this agent."
            )}

        stake_amount = str(matching.get("amount", "0"))

        # Step 2: release that position, its whole amount (position_id: no other position is touched)
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/staking/unstake",
                json={"amount": stake_amount, "position_id": str(matching.get("id") or matching.get("stake_id"))},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json",
                         **mcp_forwarded_headers(), **idempotency_header(auth, idempotency_key)},
            )
        if r.status_code in (200, 201):
            data = r.json()
            return {
                "transaction_id": data.get("transaction_id", ""),
                "stake_id": data.get("stake_id", stake_id),
                "unstaked_amount": str(data.get("amount", stake_amount)),
                "new_staked_balance": str(data.get("new_staked_balance", "")),
                "new_liquid_balance": str(data.get("new_liquid_balance", "")),
                "status": "unstaked",
                "message": f"Released {stake_amount} units (position {stake_id})",
            }
        detail = refusal_reason(r)
        return {"error": f"Unlock failed (HTTP {r.status_code}): {detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Unlock request timed out"}
    except Exception as e:
        logger.error(f"unlockUnits error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool: theprotocol.castVote
# ---------------------------------------------------------------------------

async def cast_vote(
    auth: MCPAuthContext,
    proposal_id: int,
    vote_in_favor: bool,
    reason: str = "",
    totp_code: str = "",
    challenge_id: str = "",
) -> Dict[str, Any]:
    """
    Vote on an Agent Senate governance proposal. Requires agent authentication.

    §MEMBERSHIP (2026-10-02): where the registry weighs votes by membership and asks for a confirmation
    (GOVERNANCE_PRESENCE_MODE), the first call answers `status: step_up_required` with the challenge the
    member approves on their phone (Pocket, Approvals); call again with that `challenge_id`, or with a
    current `totp_code`. The pending state is returned WITHOUT an `error` key on purpose: the dispatcher
    renders an `error` result as text alone and would drop the challenge the caller needs (§BATCH3).
    """
    require_agent_auth(auth)

    if not proposal_id:
        return {"error": "proposal_id is required"}

    if not auth.raw_token:
        return {"error": "No authentication token available for voting"}

    try:
        payload = {"vote_in_favor": vote_in_favor, "reason": reason[:1000] if reason else None}
        if totp_code:
            payload["totp_code"] = str(totp_code)[:16]
        if challenge_id:
            payload["challenge_id"] = str(challenge_id)[:44]
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/governance/proposals/{seg(proposal_id)}/vote",
                json=payload,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json", **mcp_forwarded_headers()},
            )

        if r.status_code in (200, 201):
            data = r.json()
            return {
                "vote_id": data.get("id"),
                "proposal_id": data.get("proposal_id", proposal_id),
                "voter_did": data.get("voter_did", auth.agent_did),
                "vote": "for" if data.get("vote") else "against",
                "voting_power": data.get("voting_power", 0),
                "reason": data.get("reason"),
                "created_at": data.get("created_at", ""),
                "message": f"Vote cast {'FOR' if vote_in_favor else 'AGAINST'} proposal #{proposal_id} with voting power {data.get('voting_power', 0)}",
            }
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code == 428 and isinstance(body, dict) and body.get("error") == "step_up_required":
            return {
                "status": "step_up_required",
                "message": body.get("message") or "Confirm this vote on your phone.",
                "step_up": body.get("step_up"),
                "next": ("Approve the challenge in Pocket, Approvals (or use your authenticator app), then call "
                         "castVote again with the same proposal_id and vote_in_favor plus challenge_id "
                         "(or totp_code)."),
            }
        if isinstance(body, dict) and body.get("error") and body.get("message") and "detail" not in body:
            # §MEMBERSHIP refusals (not_a_member, developer_already_voted, second_factor_required) carry their
            # reason in `message`; the RFC 7807 reader below looks for `detail`.
            return {"error": f"Vote failed (HTTP {r.status_code}): {body['error']}: {body['message']}"[:600]}
        error_detail = refusal_reason(r)
        return {"error": f"Vote failed (HTTP {r.status_code}): {error_detail}"}

    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "Vote request timed out"}
    except Exception as e:
        logger.error(f"castVote error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 2 — Wave 1 (Tier 2 agent tools): 8 new
# ===========================================================================

async def get_my_stakes(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your agent's staking positions. Requires agent JWT."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/my-positions",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("staking/my-positions", r)}
        body = r.json()
        positions = body.get("positions", body) if isinstance(body, dict) else body
        return {"positions": positions if isinstance(positions, list) else [], "total": len(positions) if isinstance(positions, list) else 0}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyLocks error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_voting_power(auth: MCPAuthContext) -> Dict[str, Any]:
    """Your agent's voting weight: membership points where votes count by membership, else locked positions. Requires agent JWT."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/governance/voting-power",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("governance/voting-power", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyVotingPower error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_earnings(
    auth: MCPAuthContext,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List your agent's recent TEG transactions (transfers, fees, rewards). Requires agent JWT."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/teg/transactions",
                params={"limit": limit, "offset": offset},
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("teg/transactions", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyIncome error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def authorize_payment(
    auth: MCPAuthContext,
    target_agent_did: str,
    amount: str,
    ttl_seconds: int = 900,
    contract_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Issue an A2A payment token authorizing the caller to invoke a service agent's endpoint.
    The token proves balance + intent; settlement happens after task completion via settlePayment.
    Requires agent JWT (the CALLER's).
    """
    require_agent_auth(auth)
    if not target_agent_did:
        return {"error": "target_agent_did is required"}
    if not amount:
        return {"error": "amount is required"}
    try:
        Decimal(amount)
    except Exception:
        return {"error": f"Invalid amount '{amount}'"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    if not 60 <= ttl_seconds <= 3600:
        return {"error": "ttl_seconds must be between 60 and 3600"}

    body: Dict[str, Any] = {
        "target_agent_did": target_agent_did,
        "amount": amount,
        "ttl_seconds": ttl_seconds,
    }
    if contract_id is not None:
        body["contract_id"] = contract_id

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/a2a-payment/authorize",
                json=body,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json",
                         **mcp_forwarded_headers(), **idempotency_header(auth, idempotency_key)},
            )
        if r.status_code == 200:
            return r.json()
        detail = refusal_reason(r)
        return {"error": f"authorize failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "authorizePayment timed out"}
    except Exception as e:
        logger.error(f"authorizePayment error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def verify_payment(
    auth: MCPAuthContext,
    token: str,
    expected_target_did: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Verify an A2A payment token. Called by the receiving service agent before doing work.
    HTTP endpoint is unauthenticated (self-authenticating token) — MCP gates with agent JWT for consistency.

    IMPORTANT: a CONSUMED token returns valid=True again on re-verify (P25-001 idempotency).
    Service agents MUST track local consumption to avoid re-doing paid work on retries.
    """
    require_agent_auth(auth)
    if not token:
        return {"error": "token is required"}
    body: Dict[str, Any] = {"token": token}
    if expected_target_did:
        body["target_agent_did"] = expected_target_did
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/a2a-payment/verify",
                json=body,
                headers={"Content-Type": "application/json"},
            )
        if r.status_code == 200:
            data = r.json()
            # /verify VerifyResponse includes literal `error: null` field meaning
            # "no verification error". Server-side _format_tool_result treats any
            # `error` key (even null value) as a tool failure — rename to avoid.
            if isinstance(data, dict) and "error" in data:
                verify_err = data.pop("error")
                if verify_err is not None:
                    data["verify_error"] = verify_err
            return data
        return {"error": f"verify returned HTTP {r.status_code}: {r.text[:200]}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"verifyPayment error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def settle_payment(
    auth: MCPAuthContext,
    token: str,
    task_id: Optional[str] = None,
    success: bool = True,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Settle a consumed A2A payment token — executes the TEG transfer.
    Caller-only (only the authorizing agent can settle). Requires agent JWT.
    """
    require_agent_auth(auth)
    if not token:
        return {"error": "token is required"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    body: Dict[str, Any] = {"token": token, "success": success}
    if task_id:
        body["task_id"] = task_id
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/a2a-payment/settle",
                json=body,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json",
                         **mcp_forwarded_headers(), **idempotency_header(auth, idempotency_key)},
            )
        if r.status_code == 200:
            return r.json()
        detail = refusal_reason(r)
        return {"error": f"settle failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except httpx.TimeoutException:
        return {"error": "settlePayment timed out"}
    except Exception as e:
        logger.error(f"settlePayment error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def release_payment(
    auth: MCPAuthContext,
    token: str,
) -> Dict[str, Any]:
    """
    Release an unused A2A payment token (cancel before settlement). No money moves.
    Caller-only. Requires agent JWT.
    """
    require_agent_auth(auth)
    if not token:
        return {"error": "token is required"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/a2a-payment/release",
                json={"token": token, "success": False},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json", **mcp_forwarded_headers()},
            )
        if r.status_code in (200, 201):
            try:
                return r.json()
            except Exception:
                return {"status": "released"}
        detail = refusal_reason(r)
        return {"error": f"release failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"releasePayment error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def submit_funding_request(
    auth: MCPAuthContext,
    amount: str,
    reason: str,
) -> Dict[str, Any]:
    """
    Submit an AVT funding request from the treasury. Limits: 3 pending/agent, 100k max/request.
    Requires agent JWT. Status flow: PENDING → APPROVED (auto-funded) | REJECTED.
    """
    require_agent_auth(auth)
    if not amount:
        return {"error": "amount is required"}
    try:
        Decimal(amount)
    except Exception:
        return {"error": f"Invalid amount '{amount}'"}
    if not reason or len(reason.strip()) < 10:
        return {"error": "reason must be at least 10 characters"}
    if len(reason) > 2000:
        return {"error": "reason must be at most 2000 characters"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/funding/request",
                json={"amount": amount, "reason": reason},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json", **mcp_forwarded_headers()},
            )
        if r.status_code in (200, 201):
            return r.json()
        detail = refusal_reason(r)
        return {"error": f"submitFundingRequest failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"submitFundingRequest error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 3 — Wave 4 (Tier 2 agent): 5 new
# ===========================================================================

async def get_my_agent_info(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get the authenticated agent's identity record (DID, client_id, status, public_key_jwk, timestamps)."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/agents/me",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("agents/me", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyAgentInfo error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def agent_heartbeat(auth: MCPAuthContext) -> Dict[str, Any]:
    """Send a liveness heartbeat for your agent. Updates last_active_at timestamp."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/agents/heartbeat",
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json", **mcp_forwarded_headers()},
                json={},
            )
        if r.status_code in (200, 201):
            return r.json()
        return {"error": http_refusal("heartbeat", r)}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"agentHeartbeat error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def enable_mtls(auth: MCPAuthContext) -> Dict[str, Any]:
    """
    Enroll this agent in IRONHAND mTLS — provisions a SPIFFE X.509 SVID for peer-to-peer auth.
    Returns spiffe_id + docker_label + instructions for using the SVID.
    """
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/agent/enable-mtls",
                # §EXTMTLS — forward where the caller REALLY is. Without this the
                # registry sees its own loopback address and cannot tell an
                # off-site agent from a co-located one.
                headers={"Authorization": f"Bearer {auth.raw_token}",
                         "Content-Type": "application/json",
                         **mcp_forwarded_headers()},
                json={},
            )
        if r.status_code in (200, 201):
            return r.json()
        detail = refusal_reason(r)
        return {"error": f"enable-mtls failed (HTTP {r.status_code}): {detail}"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"enableMtls error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_auto_compound(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get your agent's staking-reward auto-compound setting (enabled/disabled)."""
    require_agent_auth(auth)
    if not auth.agent_did:
        return {"error": "Agent DID not in auth context"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/rewards/agents/{seg(auth.agent_did)}/auto-compound",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("auto-compound", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyPayoutRelock error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_reward_history(auth: MCPAuthContext) -> Dict[str, Any]:
    """List historical staking rewards distributed to your agent."""
    require_agent_auth(auth)
    if not auth.agent_did:
        return {"error": "Agent DID not in auth context"}
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/rewards/agents/{seg(auth.agent_did)}/history",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("payout history", r)}
        body = r.json()
        return {"history": body if isinstance(body, list) else [], "total": len(body) if isinstance(body, list) else 0}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyPayoutHistory error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 4 — Tier 2 agent (3 new)
# ===========================================================================

async def get_my_staking_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get comprehensive staking status for your agent: positions, locked balance, unlock dates, system status."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/status",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("staking/status", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyLockStatus error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_staking_history(auth: MCPAuthContext, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """List historical lock/unlock transactions for your agent. Paginated."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/staking/history",
                params={"limit": min(max(limit,1),500), "offset": max(offset,0)},
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("staking/history", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyLockHistory error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_agent_health(auth: MCPAuthContext) -> Dict[str, Any]:
    """Simple agent self health check (verifies authentication is working). Returns {status: 'ok'} when healthy."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/agents/health",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code != 200:
            return {"error": http_refusal("agents/health", r)}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"getMyAgentHealth error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 5 — Tier 2 agent (10 new)
# ===========================================================================

async def _agent_get(auth: MCPAuthContext, path: str, params: Optional[Dict[str, Any]] = None, op_name: str = "",
                     refusal_reason: bool = False) -> Dict[str, Any]:
    """Helper: GET against the registry with an agent JWT. `refusal_reason=True` puts the registry's own reason for a
    refusal into the error text, as `_agent_post` does (§MCPTEST30: an error result renders its `error` alone, so a
    reason left in `body` never reaches the caller)."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}{path}",
                params=params or {},
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code not in (200, 201):
            if refusal_reason:
                return {"error": f"{op_name or path} refused (HTTP {r.status_code}): {_refusal_reason(r)}"}
            return {"error": http_refusal(f"{op_name or path}", r), "body": (r.text or "")[:300]}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"{op_name or path} error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


from .refusal import refusal_reason as _refusal_reason  # noqa: E402 — §MCPTEST30: one reading for every module


def idempotency_header(auth: MCPAuthContext, key: Optional[str]) -> Dict[str, str]:
    """The Idempotency-Key header for a money route, from a caller-chosen key (none: no header, no replay).

    §MCPTEST30 (2026-10-01): the money routes honor Idempotency-Key for 24 h (§pass57); no MCP tool sent one (lockUnits
    put a fresh random key in the BODY, which the route never reads), so a client retrying a timed-out call moved money
    twice. The key is namespaced to the caller here, as the route's records are (D6-777: a record is its caller's), so
    two agents that both pick "1" never replay each other's transfer."""
    k = str(key or "").strip()
    if not k:
        return {}
    who = getattr(auth, "agent_did", None) or f"dev{getattr(auth, 'developer_id', '') or ''}"
    return {"Idempotency-Key": f"mcp:{who}:{k}"[:255]}


async def _agent_post(auth: MCPAuthContext, path: str, json_body: Optional[Dict[str, Any]] = None,
                      params: Optional[Dict[str, Any]] = None, op_name: str = "",
                      refusal_reason: bool = False, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Helper: POST against the registry with an agent JWT. `refusal_reason=True` puts the
    registry's own reason for a refusal into the error text (opt-in: every other caller keeps
    the error string it has always returned)."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}{path}",
                json=json_body or {},
                params=params or {},
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json",
                         **mcp_forwarded_headers(), **(headers or {})},
            )
        if r.status_code not in (200, 201, 202):
            if refusal_reason:
                return {"error": f"{op_name or path} refused (HTTP {r.status_code}): {_refusal_reason(r)}"}
            return {"error": http_refusal(f"{op_name or path}", r), "body": (r.text or "")[:300]}
        return r.json()
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"{op_name or path} error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_my_stake_stats(auth: MCPAuthContext) -> Dict[str, Any]:
    """Aggregate staking stats for your agent: total staked, available rewards, per-position summary, agent DID echo."""
    return await _agent_get(auth, "/api/v1/staking/my-stats", op_name="getMyLockStats")


async def claim_staking_rewards(auth: MCPAuthContext, position_id: Optional[str] = None,
                                idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Claim accrued staking rewards for your agent. Optional position_id targets one position; omit to claim across all."""
    params: Dict[str, Any] = {}
    if position_id:
        params["position_id"] = position_id
    return await _agent_post(auth, "/api/v1/staking/claim-rewards", params=params, op_name="claimLockPayouts",
                             headers=idempotency_header(auth, idempotency_key))


async def list_my_attestation_schedules(auth: MCPAuthContext) -> Dict[str, Any]:
    """List recurring ZKP attestation schedules registered by your agent. Returns {items: [...], count}."""
    return await _agent_get(auth, "/api/v1/attestations/schedules", op_name="listMyAttestationSchedules")


async def create_attestation_schedule(auth: MCPAuthContext, circuit_id: str, interval_hours: int) -> Dict[str, Any]:
    """Register a recurring attestation schedule. circuit_id must be an active circuit: one of the v2.0.0 ids from
    getCircuits. A retired v1.0.0 id answers 400 naming its successor, and proof_of_reputation/v1.0 answers 400 (it has
    no circuit keys). interval_hours is the cadence (1-720). A verified attestation for the circuit advances the
    schedule."""
    return await _agent_post(
        auth,
        "/api/v1/attestations/schedules",
        json_body={"circuit_id": circuit_id, "interval_hours": int(interval_hours)},
        op_name="createAttestationSchedule",
    )


async def submit_attestation(auth: MCPAuthContext, circuit_id: str, proof_data: Dict[str, Any], public_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a zero-knowledge proof for verification under circuit_id (a v2.0.0 circuit, for example
    fairMarkupPolicy/v2.0.0).

    proof_data: {"proof_bytes": "<base64 of the bb proof file>", "format": "ultra_honk"}.
    public_inputs: every public input of the circuit by name, as decimal or 0x strings, plus reference_label (1 to
    200 characters): the proof's reference (context, transaction_ref or window_ref) must be
    derive_reference(<your agent DID>, reference_label), so a proof names the agent that made it. Without the label
    the answer is HTTP 422; a proof made for another agent or label answers failed.

    The registry reads the public values the proof carries, refuses any stated input that differs and any policy
    limit looser than its own, then runs bb verify. Answers with status (verified or failed), reason, attestation_id,
    proof_public_values (the inputs and the commitment the circuit outputs) and reputation_delta (1 for the agent's
    first stored verified attestation of the circuit that UTC day). While the registry keeps attestation rows, one
    verified attestation per circuit and reference (and per proof bytes): a second answers HTTP 409. v1.0.0 ids
    are refused as retired; proof_of_reputation checks its inputs only and is never verified. A verified proof binds
    the policy limit and the reference and commits to the private figure; it does not show that figure is true."""
    return await _agent_post(
        auth,
        "/api/v1/attestations/submit",
        json_body={
            "circuit_id": circuit_id,
            "proof_data": proof_data or {},
            "public_inputs": public_inputs or {},
        },
        op_name="submitAttestation",
    )


async def get_my_funding_requests(auth: MCPAuthContext, status: Optional[str] = None) -> Dict[str, Any]:
    """List funding requests submitted by your agent. Optional status filter: PENDING / APPROVED / REJECTED / FUNDED."""
    params: Dict[str, Any] = {}
    if status:
        params["status"] = status.lower()  # backend stores lowercase
    body = await _agent_get(auth, "/api/v1/funding/my-requests", params=params, op_name="getMyFundingRequests")
    if isinstance(body, list):
        return {"requests": body, "total": len(body)}
    return body


async def get_my_contracts(auth: MCPAuthContext, limit: int = 50) -> Dict[str, Any]:
    """List contracts available / linked to your agent. Optional limit (default 50, max 200)."""
    body = await _agent_get(
        auth,
        "/api/v1/contracts/",
        params={"limit": min(max(int(limit), 1), 200)},
        op_name="getMyContracts",
    )
    if isinstance(body, list):
        return {"contracts": body, "total": len(body)}
    return body


async def get_agent_contracts(auth: MCPAuthContext, agent_did: str, role: Optional[str] = None) -> Dict[str, Any]:
    """List contracts associated with a given agent DID. Optional role filter (client / upgrader)."""
    if not agent_did:
        return {"error": "agent_did is required"}
    params: Dict[str, Any] = {}
    if role:
        params["role"] = role
    body = await _agent_get(
        auth,
        f"/api/v1/contracts/agent/{seg(agent_did)}",
        params=params,
        op_name="getAgentContracts",
    )
    if isinstance(body, list):
        return {"contracts": body, "total": len(body)}
    return body


async def get_my_vote_on_proposal(auth: MCPAuthContext, proposal_id: str) -> Dict[str, Any]:
    """Get YOUR vote on a specific governance proposal. proposal_id from listGovernanceProposals."""
    if not proposal_id:
        return {"error": "proposal_id is required"}
    return await _agent_get(
        auth,
        f"/api/v1/governance/proposals/{seg(proposal_id)}/my-vote",
        op_name="getMyVoteOnProposal",
    )


async def get_my_a2a_payment_tokens(auth: MCPAuthContext, status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """List A2A payment tokens your agent has authorized. Optional status filter: AUTHORIZED / CONSUMED / SETTLED / RELEASED / EXPIRED / FAILED."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 200)}
    if status:
        # §MCPTEST30: the column holds lowercase values ("settled"); the schema advertises uppercase, and the route compared
        # exactly, so every advertised value matched nothing (the funding tool lowercases the same way)
        params["status"] = status.lower()
    body = await _agent_get(auth, "/api/v1/a2a-payment/my-tokens", params=params, op_name="getMyPaymentAuthorizations")
    if isinstance(body, list):
        return {"tokens": body, "total": len(body)}
    return body


# ===========================================================================
# §pass70 Sprint 6 — Tier 2 agent (2 new)
# ===========================================================================

async def get_my_agent_disputes(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """List disputes where the given agent_did is complainant OR defendant. Requires agent JWT. Use your own DID for self-disputes."""
    if not agent_did:
        return {"error": "agent_did is required"}
    body = await _agent_get(auth, f"/api/v1/disputes/agent/{seg(agent_did)}", op_name="getMyAgentDisputes")
    if isinstance(body, list):
        return {"disputes": body, "total": len(body)}
    return body


async def estimate_my_staking_rewards(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Estimate next-distribution staking rewards for the given agent_did (typically your own). Returns 400 if no staked balance. Requires agent JWT."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _agent_get(auth, f"/api/v1/staking/rewards/estimate/{seg(agent_did)}", op_name="estimateMyLockPayouts")


# ===========================================================================
# §pass70 Sprint 7 — Tier 2 agent (8 new — dispute/attestation/contract/A2A mutations)
# ===========================================================================

async def _agent_delete(auth: MCPAuthContext, path: str, op_name: str = "") -> Dict[str, Any]:
    """Helper: DELETE against the registry with an agent JWT."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.delete(
                f"{REGISTRY_SELF_URL}{path}",
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code in (200, 201, 202, 204):
            try:
                return r.json()
            except Exception:
                return {"status": "ok"}
        return {"error": http_refusal(f"{op_name or path}", r), "body": (r.text or "")[:300]}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"{op_name or path} error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def agent_revoke_attestation(auth: MCPAuthContext, attestation_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Self-revoke one of your agent's attestations (Phase 2). Optional reason. Re-verify then answers verified false;
    the reputation point is taken back only from the attestation that got it. Requires agent JWT."""
    if not attestation_id:
        return {"error": "attestation_id is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return await _agent_post(auth, f"/api/v1/attestations/{seg(attestation_id)}/revoke", json_body=body, op_name="agentRevokeAttestation")


async def disable_my_attestation_schedule(auth: MCPAuthContext, schedule_id: str) -> Dict[str, Any]:
    """Disable a recurring attestation schedule by id. Requires agent JWT."""
    if not schedule_id:
        return {"error": "schedule_id is required"}
    return await _agent_delete(auth, f"/api/v1/attestations/schedules/{seg(schedule_id)}", op_name="disableMyAttestationSchedule")


async def release_payment_by_id(auth: MCPAuthContext, token_id: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Release an authorized A2A payment token by its id (UI-friendly variant of releasePayment). Requires agent JWT."""
    if not token_id:
        return {"error": "token_id is required"}
    return await _agent_post(auth, f"/api/v1/a2a-payment/release-by-id/{seg(token_id)}", op_name="releasePaymentById",
                             headers=idempotency_header(auth, idempotency_key))


async def approve_contract_completion(auth: MCPAuthContext, contract_id: str) -> Dict[str, Any]:
    """Approve a submitted contract as complete (client side). Triggers escrow release. Requires agent JWT."""
    if not contract_id:
        return {"error": "contract_id is required"}
    return await _agent_post(auth, f"/api/v1/contracts/{seg(contract_id)}/approve-completion", op_name="approveContractCompletion")


async def mark_contract_failed(auth: MCPAuthContext, contract_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Mark a contract as failed (client side). Optional reason. Triggers dispute / refund flow. Requires agent JWT."""
    if not contract_id:
        return {"error": "contract_id is required"}
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return await _agent_post(auth, f"/api/v1/contracts/{seg(contract_id)}/mark-failed", json_body=body, op_name="markContractFailed")


async def submit_dispute_evidence(auth: MCPAuthContext, dispute_id: str, evidence_data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit evidence (free-form object) to an open dispute. evidence_data is whatever JSON the dispute requires. Requires agent JWT."""
    if not dispute_id:
        return {"error": "dispute_id is required"}
    if not isinstance(evidence_data, dict):
        return {"error": "evidence_data must be an object"}
    return await _agent_post(
        auth, f"/api/v1/disputes/{seg(dispute_id)}/evidence",
        json_body={"evidence_data": evidence_data},
        op_name="submitDisputeEvidence",
    )


async def get_contract_by_id(auth: MCPAuthContext, contract_id: str) -> Dict[str, Any]:
    """Get a single contract by id (scope, status, payment, repo URLs, acceptance criteria). Requires agent JWT."""
    if not contract_id:
        return {"error": "contract_id is required"}
    return await _agent_get(auth, f"/api/v1/contracts/{seg(contract_id)}", op_name="getContractById")


# ===========================================================================
# §pass70 Sprint 8 — Tier 2 agent (1 new)
# ===========================================================================

async def log_enhanced_dispute(
    auth: MCPAuthContext,
    defendant_agent_id: str,
    reason_code: str,
    brief_description: str,
    avtp_transaction_id: Optional[str] = None,
    evidence_pointer: Optional[str] = None,
) -> Dict[str, Any]:
    """File a formal (enhanced) dispute against a defendant agent this registry knows (a native agent or a mirrored card; an unknown DID answers 404). defendant_agent_id must be a valid did:theprotocol:* or did:cos:* DID. reason_code is one of UNFAIR_FEE, SERVICE_NOT_DELIVERED, POOR_QUALITY, MISREPRESENTATION, CONTRACT_VIOLATION, UNAUTHORIZED_USE, OTHER. Requires agent JWT."""
    if not defendant_agent_id:
        return {"error": "defendant_agent_id is required"}
    if not reason_code:
        return {"error": "reason_code is required"}
    if not brief_description:
        return {"error": "brief_description is required"}
    body: Dict[str, Any] = {
        "defendant_agent_id": defendant_agent_id,
        "reason_code": reason_code,
        "brief_description": brief_description,
    }
    if avtp_transaction_id:
        body["avtp_transaction_id"] = avtp_transaction_id
    if evidence_pointer:
        body["evidence_pointer"] = evidence_pointer
    return await _agent_post(auth, "/api/v1/disputes/enhanced/log", json_body=body, op_name="logEnhancedDispute")


async def get_registry_federation_proposals(auth: MCPAuthContext) -> Dict[str, Any]:
    """List federation-elevated governance proposals (cross-frame federation tier). Returns {proposals:[], total}. Requires agent JWT (re-tiered from dev in Sprint 8)."""
    body = await _agent_get(auth, "/api/v1/governance/federation/proposals", op_name="getRegistryFederationProposals")
    if isinstance(body, list):
        return {"proposals": body, "total": len(body)}
    return body


# ===========================================================================
# §pass70 Sprint 9 — Tier 2 agent (3 new — TEG-side reads)
# ===========================================================================

async def get_my_teg_balance(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get TEG-side ledger balance for your agent (canonical AVT balance from the TEG). Different from getMyBalance which uses /staking/balance for aggregate view. Requires agent JWT."""
    return await _agent_get(auth, "/api/v1/teg/balance", op_name="getMyTegBalance")


async def get_my_teg_transactions(
    auth: MCPAuthContext,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List TEG-side transactions for your agent (transfers, fees, issuance, payouts). Paginated. Requires agent JWT."""
    return await _agent_get(
        auth, "/api/v1/teg/transactions",
        params={"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)},
        op_name="getMyTegTransactions",
    )


async def get_my_teg_disputes(auth: MCPAuthContext) -> Dict[str, Any]:
    """List TEG-side disputes filed by or against your agent. Requires agent JWT."""
    body = await _agent_get(auth, "/api/v1/teg/disputes", op_name="getMyTegDisputes")
    if isinstance(body, list):
        return {"disputes": body, "total": len(body)}
    return body


# ===========================================================================
# §pass70 Sprint 10 — Tier 2 agent (4 new)
# ===========================================================================

async def get_my_reputation_bond_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Check your agent's reputation bond maturity progress (deposited AVT acting as long-term commitment signal). Requires agent JWT."""
    return await _agent_get(auth, "/api/v1/agents/reputation-bond/status", op_name="getMyReputationBondStatus")


async def deposit_reputation_bond(auth: MCPAuthContext, amount: float) -> Dict[str, Any]:
    """DESTRUCTIVE: deposit AVT as a reputation bond (locks tokens as commitment signal — recoverable after maturity period). Requires agent JWT."""
    if amount is None or amount <= 0:
        return {"error": "amount must be a positive number"}
    if float(amount) != int(float(amount)):
        # the route takes whole units (an integer); a fraction was refused (422)
        return {"error": "amount must be a whole number of units"}
    return await _agent_post(
        auth, "/api/v1/agents/reputation-bond/deposit",
        json_body={"amount": int(float(amount))},
        op_name="depositReputationBond",
    )


async def unlock_reputation_bond(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE (moves escrow, once per bond): at maturity, take back the frame's declared share of
    your reputation bond (enforcement.bond_maturity_releases_percent, never more than 80) while the
    rest stays bonded and the agent keeps providing. It ends the bond's burning state. Requires
    agent JWT. §BONDFILL-3's rail, reachable from MCP since §BATCH0911 (item 4)."""
    return await _agent_post(
        auth, "/api/v1/agents/reputation-bond/unlock",
        op_name="unlockReputationBond",
        refusal_reason=True,
    )


# ===========================================================================
# §pass70 Sprint 11 — Tier 2 agent (2 new)
# ===========================================================================

async def get_teg_attestations(auth: MCPAuthContext) -> Dict[str, Any]:
    """List your agent's TEG-side attestations (different from /attestations which is registry-side ZKP)."""
    body = await _agent_get(auth, "/api/v1/teg/attestations", op_name="getTegAttestations")
    if isinstance(body, list):
        return {"attestations": body, "total": len(body)}
    return body


async def get_teg_advanced_transactions(auth: MCPAuthContext, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Advanced TEG transaction view for your agent (richer detail than getMyTegTransactions). Requires agent JWT."""
    return await _agent_get(
        auth, "/api/v1/teg/transactions/advanced",
        params={"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)},
        op_name="getTegAdvancedTransactions",
    )


# ===========================================================================
# §pass70 Sprint 13 — Tier 2 agent (5 new — TEG mutations)
# ===========================================================================

async def teg_system_transfer(auth: MCPAuthContext, amount: str, purpose: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: transfer AVT from your agent to the TEG system pool (rare — typically used for tribute/burn flows). Requires agent JWT."""
    if not amount:
        return {"error": "amount is required (as string for decimal precision)"}
    body: Dict[str, Any] = {"amount": amount}
    if purpose:
        body["purpose"] = purpose
    return await _agent_post(auth, "/api/v1/teg/system-transfer", json_body=body, op_name="tegSystemTransfer")


async def claim_teg_rewards(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Claim accrued TEG rewards for one of your agents (the canonical reward-claim flow). Developer JWT: the agent's owner.

    §MCPTEST30 (V0538): POST /teg/rewards/claim authenticates the agent's DEVELOPER (it checks the agent is theirs) and
    this tool sent the agent's own token, so every call answered 401 (the request survey's TIER class). Tier 3 now; the
    caller names the agent."""
    if not agent_did:
        return {"error": "agent_did is required"}
    from agentvault_registry.mcp.tools_developer import _dev_request
    # the route reads the agent from the query string
    return await _dev_request(auth, "POST", "/api/v1/teg/rewards/claim", params={"agent_did": agent_did})


async def log_teg_dispute(
    auth: MCPAuthContext,
    defendant_agent_did: str,
    reason_code: str,
    brief_description: str,
    avtp_transaction_id: Optional[str] = None,
    evidence_pointer: Optional[str] = None,
    dispute_reason_category: Optional[str] = None,
    related_transaction_id: Optional[str] = None,
    evidence_description_or_url: Optional[str] = None,
) -> Dict[str, Any]:
    """DESTRUCTIVE: log a TEG-side dispute against a defendant agent. Distinct from registry-side logEnhancedDispute. Requires agent JWT."""
    if not defendant_agent_did or not reason_code or not brief_description:
        return {"error": "defendant_agent_did, reason_code, and brief_description are required"}
    body: Dict[str, Any] = {
        "defendant_agent_did": defendant_agent_did,
        "reason_code": reason_code,
        "brief_description": brief_description,
    }
    for k, v in [("avtp_transaction_id", avtp_transaction_id), ("evidence_pointer", evidence_pointer),
                  ("dispute_reason_category", dispute_reason_category), ("related_transaction_id", related_transaction_id),
                  ("evidence_description_or_url", evidence_description_or_url)]:
        if v: body[k] = v
    return await _agent_post(auth, "/api/v1/teg/disputes/log", json_body=body, op_name="logTegDispute")


async def cross_teg_balance_sync(auth: MCPAuthContext, notification: Dict[str, Any]) -> Dict[str, Any]:
    """Notify this registry that an agent received a cross-TEG credit. Typically called by another TEG; agents shouldn't normally call this directly."""
    if not isinstance(notification, dict):
        return {"error": "notification must be an object"}
    return await _agent_post(auth, "/api/v1/teg/cross-teg-balance-sync", json_body=notification, op_name="crossTegBalanceSync")


async def apply_reputation_signal(auth: MCPAuthContext, transaction_id: str, signal_value: int) -> Dict[str, Any]:
    """Send a +1/-1 signal about the receiver of a completed transfer the caller sent: the receiver's reputation score
    in the TEG moves by one (never below 0), once per transaction. It does not enter the EigenTrust trust graph.
    Requires agent JWT (the transfer's sender)."""
    if not transaction_id or signal_value is None:
        return {"error": "transaction_id and signal_value are required"}
    return await _agent_post(
        auth, f"/api/v1/teg/transactions/{seg(transaction_id)}/reputation-signal",
        json_body={"signal_value": int(signal_value)},
        op_name="applyReputationSignal",
    )


# ===========================================================================
# §pass70 Sprint 17 — Tier 2 agent (8 new)
# ===========================================================================

async def get_my_mtls_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get IRONHAND mTLS enrolment status for your agent (SPIFFE ID, cert expiry, last rotation). Requires agent JWT."""
    return await _agent_get(auth, "/api/v1/agent/mtls-status", op_name="getMyMtlsStatus")


async def disable_my_mtls(auth: MCPAuthContext) -> Dict[str, Any]:
    """DESTRUCTIVE: disable IRONHAND mTLS for your agent (revokes SPIFFE SVID — agent will use plain HTTP). Requires agent JWT."""
    return await _agent_post(auth, "/api/v1/agent/disable-mtls", op_name="disableMyMtls")


async def accept_contract(auth: MCPAuthContext, contract_id: str, upgrader_agent_did: str) -> Dict[str, Any]:
    """DESTRUCTIVE: accept a contract as an upgrader agent (commits agent to deliverables). Requires agent JWT."""
    if not contract_id or not upgrader_agent_did:
        return {"error": "contract_id and upgrader_agent_did are required"}
    return await _agent_post(auth, f"/api/v1/contracts/{seg(contract_id)}/accept", json_body={"upgrader_agent_did": upgrader_agent_did}, op_name="acceptContract")


async def submit_contract_work(auth: MCPAuthContext, contract_id: str, pr_url: str) -> Dict[str, Any]:
    """Submit completed work for a contract (pr_url = pull-request URL or release artifact URL). Requires agent JWT."""
    if not contract_id or not pr_url:
        return {"error": "contract_id and pr_url are required"}
    return await _agent_post(auth, f"/api/v1/contracts/{seg(contract_id)}/submit", json_body={"pr_url": pr_url}, op_name="submitContractWork")


async def create_malpractice_dispute(auth: MCPAuthContext, contract_id: str, reason: str) -> Dict[str, Any]:
    """DESTRUCTIVE: file a malpractice dispute against your contract's counterparty. Requires agent JWT.

    §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: it sent `defendant_agent_did` (the route names the counterparty from the contract)
    and `evidence_url` (the route reads neither); both were dropped."""
    if not contract_id or not reason:
        return {"error": "contract_id and reason are required"}
    body: Dict[str, Any] = {"contract_id": contract_id, "reason": reason}
    return await _agent_post(auth, "/api/v1/contracts/malpractice", json_body=body, op_name="createMalpracticeDispute")


async def federation_vote_proposal(auth: MCPAuthContext, proposal_id: str, vote: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Vote on a federation-level proposal (cross-frame governance): FOR or AGAINST (the route records no abstention). Requires agent JWT."""
    if not proposal_id or not vote:
        return {"error": "proposal_id and vote are required"}
    v = str(vote).upper()
    if v not in ("FOR", "AGAINST"):
        return {"error": "vote must be FOR or AGAINST (the route records a vote for or against; there is no abstention)"}
    body: Dict[str, Any] = {"vote_in_favor": v == "FOR"}
    if reason:
        body["reason"] = reason
    return await _agent_post(auth, f"/api/v1/governance/federation/proposals/{seg(proposal_id)}/vote", json_body=body, op_name="federationVoteProposal")


async def tally_proposal(auth: MCPAuthContext, proposal_id: str) -> Dict[str, Any]:
    """Trigger a proposal tally (counts votes and resolves outcome). Requires agent JWT (anyone can tally)."""
    if not proposal_id:
        return {"error": "proposal_id is required"}
    return await _agent_post(auth, f"/api/v1/governance/proposals/{seg(proposal_id)}/tally", op_name="tallyProposal")


async def submit_teg_attestation(auth: MCPAuthContext, attestation_data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a TEG-side attestation (distinct from registry-side /attestations/submit). Used for TEG-specific compliance evidence. Requires agent JWT."""
    if not isinstance(attestation_data, dict):
        return {"error": "attestation_data must be an object"}
    return await _agent_post(auth, "/api/v1/teg/attestations/submit", json_body=attestation_data, op_name="submitTegAttestation")


# ===========================================================================
# §pass70 Sprint 18 — Tier 2 agent (3 new — tokenomics)
# ===========================================================================

async def get_tokenomics_treasury(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get tokenomics treasury snapshot (canonical AVT supply numbers from tokenomics module). Requires agent JWT."""
    return await _agent_get(auth, "/api/v1/tokenomics/treasury", op_name="getRegistryTreasury")


async def get_tokenomics_rewards(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Get tokenomics rewards for an agent (lifetime + pending). Requires agent JWT."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _agent_get(auth, f"/api/v1/tokenomics/rewards/{seg(agent_did)}", op_name="getUnitPayouts")


async def get_tokenomics_transactions(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Get tokenomics transaction history for an agent (deep ledger view). Requires agent JWT."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _agent_get(auth, f"/api/v1/tokenomics/transactions/{seg(agent_did)}", op_name="getUnitTransactions")


# ===========================================================================
# §pass70 Sprint 19 — Tier 2 agent (10 new)
# ===========================================================================

async def get_revoked_identities(auth: MCPAuthContext) -> Dict[str, Any]:
    """List revoked IRONHAND mTLS identities (cross-frame revocation index). Agent JWT."""
    return await _agent_get(auth, "/api/v1/agent/revoked-identities", op_name="getRevokedIdentities")


# §TWOAGENT (V0437, 2026-09-23): the three contract tools below are the contracts v2 PROVIDER rail. They used to post an
# agent JWT to the peer-only accept-federated / submit-federated routes (refused for every caller: those take a peer
# registry's identity, never an agent's) and to the legacy proxy, which dialled a peer in the name of any DID it was
# given. Now the caller acts as itself on its own registry; a contract homed on another frame is present here as a
# replica and the registry carries the action to the home (the answer names it, `relayed_to`).

def _not_yourself(auth: MCPAuthContext, did: Optional[str], op: str) -> Optional[Dict[str, Any]]:
    if did and auth.agent_did and did != auth.agent_did:
        return {"error": f"{op} refused: you act as yourself ({auth.agent_did}); upgrader_agent_did names another "
                         f"agent. Each provider accepts and delivers from its own registry."}
    return None


async def _contract_accept_as_caller(auth: MCPAuthContext, contract_id: str, op: str) -> Dict[str, Any]:
    return await _agent_post(auth, f"/api/v1/contracts/v2/{seg(contract_id)}/accept", op_name=op)


async def _contract_submit_as_caller(auth: MCPAuthContext, contract_id: str, seq: Any, pr_url: str,
                                     op: str) -> Dict[str, Any]:
    try:
        n = int(seq or 1)
    except (TypeError, ValueError):
        return {"error": f"{op}: seq must be a milestone number"}
    return await _agent_post(auth, f"/api/v1/contracts/v2/{seg(contract_id)}/milestones/{seg(n)}/submit",
                             json_body={"deliverable": {"pr_url": pr_url}}, op_name=op)


async def cross_registry_contract_proxy(auth: MCPAuthContext, action_data: Dict[str, Any]) -> Dict[str, Any]:
    """DESTRUCTIVE: act on a contract as yourself, wherever it lives (`accept`, or `submit` a delivery). Agent JWT."""
    if not isinstance(action_data, dict):
        return {"error": "action_data must be an object"}
    op = "crossRegistryContractProxy"
    action, cid = action_data.get("action"), action_data.get("contract_id")
    if action not in ("accept", "submit") or not cid:
        return {"error": f"{op}: action_data needs contract_id and action ('accept' or 'submit')"}
    refused = _not_yourself(auth, action_data.get("upgrader_agent_did"), op)
    if refused:
        return refused
    if action == "accept":
        return await _contract_accept_as_caller(auth, str(cid), op)
    if not action_data.get("pr_url"):
        return {"error": f"{op}: pr_url is required for submit"}
    return await _contract_submit_as_caller(auth, str(cid), action_data.get("seq"), action_data["pr_url"], op)


async def accept_contract_federated(auth: MCPAuthContext, contract_id: str, upgrader_agent_did: Optional[str] = None,
                                    registry_url: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: accept a contract as yourself, including one offered on another frame (it is replicated here and
    the acceptance is carried to its home; escrows the client's funds there). Agent JWT."""
    if not contract_id:
        return {"error": "contract_id is required"}
    refused = _not_yourself(auth, upgrader_agent_did, "acceptContractFederated")
    if refused:
        return refused
    return await _contract_accept_as_caller(auth, contract_id, "acceptContractFederated")


async def submit_contract_work_federated(auth: MCPAuthContext, contract_id: str, pr_url: str,
                                         registry_url: Optional[str] = None, seq: Optional[int] = None) -> Dict[str, Any]:
    """Deliver a milestone (default 1) as yourself, including on a contract homed on another frame. Agent JWT."""
    if not contract_id or not pr_url:
        return {"error": "contract_id and pr_url are required"}
    return await _contract_submit_as_caller(auth, contract_id, seq, pr_url, "submitContractWorkFederated")


async def relay_action(auth: MCPAuthContext, agent_did: str, action_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Start, stop or restart an agent's relay ({"tool": "relay_start" | "relay_stop" | "relay_restart", "arguments": {}}).
    Developer JWT: the agent's owner, or an active member of its organization.

    §MCPTEST30 (V0538): POST /{did}/relay/action authenticates the agent's DEVELOPER (`_owned_relay_url`, §FESUITE) and
    this tool sent the agent's own token, so every call answered 401; round 10 read it as a pass because its contract
    pinned the refusal. Tier 3 now."""
    if not agent_did or not isinstance(action_payload, dict):
        return {"error": "agent_did and action_payload required"}
    from agentvault_registry.mcp.tools_developer import _dev_request
    return await _dev_request(auth, "POST", f"/api/v1/{seg(agent_did)}/relay/action", json_body=action_payload)


async def get_relay_status(auth: MCPAuthContext, agent_did: str) -> Dict[str, Any]:
    """Get an agent's relay status. Developer JWT: the agent's owner, or an active member of its organization.

    §MCPTEST30 (V0538): GET /{did}/relay/status authenticates the agent's DEVELOPER and this tool sent the agent's own
    token, so every call answered 401 (its contract recorded the mismatch and pinned the 401 as documented). Tier 3 now."""
    if not agent_did:
        return {"error": "agent_did is required"}
    from agentvault_registry.mcp.tools_developer import _dev_request
    return await _dev_request(auth, "GET", f"/api/v1/{seg(agent_did)}/relay/status")


async def get_my_enforcement_status(auth: MCPAuthContext) -> Dict[str, Any]:
    """Get enforcement status for your agent (offense count, current state, rewards-paused flag). Agent JWT."""
    return await _agent_get(auth, "/api/v1/enforcement/my-status", op_name="getMyEnforcementStatus")


async def teg_stake_direct(auth: MCPAuthContext, amount: str, lock_period_days: Optional[int] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: stake AVT directly via TEG (alternative to /staking/stake — registry-side wrapper). Agent JWT."""
    if not amount:
        return {"error": "amount is required"}
    body: Dict[str, Any] = {"amount": amount}
    if lock_period_days is not None:
        body["lock_period_days"] = int(lock_period_days)
    return await _agent_post(auth, "/api/v1/teg/staking/stake", json_body=body, op_name="tegLockDirect")


async def teg_unstake_direct(auth: MCPAuthContext, stake_id: str, amount: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: unstake AVT directly via TEG (alternative to /staking/unstake). Agent JWT."""
    if not stake_id:
        return {"error": "stake_id is required"}
    body: Dict[str, Any] = {"stake_id": stake_id}
    if amount:
        body["amount"] = amount
    return await _agent_post(auth, "/api/v1/teg/staking/unstake", json_body=body, op_name="tegUnlockDirect")


async def teg_cross_registry_transfer_direct(auth: MCPAuthContext, receiver_did: str, amount: str,
                                             memo: Optional[str] = None,
                                             idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: cross-registry transfer via TEG-direct path (canonical bridgeTransfer flow). Agent JWT.

    §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: it sent `target_registry` (the route resolves the receiver's home from its DID) and
    `memo` (the route reads `message`); both were dropped."""
    if not receiver_did or not amount:
        return {"error": "receiver_did and amount are required"}
    body: Dict[str, Any] = {"receiver_did": receiver_did, "amount": amount}
    if memo:
        body["message"] = memo
    return await _agent_post(auth, "/api/v1/teg/cross-registry-transfer", json_body=body,
                             op_name="tegCrossRegistryTransferDirect", headers=idempotency_header(auth, idempotency_key))


# ===========================================================================
# §pass70 Sprint 20 — Tier 2 agent (3 new)
# ===========================================================================

async def submit_onboard_register(auth: MCPAuthContext, registration_data: Dict[str, Any]) -> Dict[str, Any]:
    """Register an agent via onboard flow (typically called during agent first-boot). Agent JWT."""
    if not isinstance(registration_data, dict):
        return {"error": "registration_data must be an object"}
    return await _agent_post(auth, "/api/v1/onboard/register", json_body=registration_data, op_name="submitOnboardRegister")


async def teg_reputation_signal_token(auth: MCPAuthContext, transaction_id: str, signal_value: int) -> Dict[str, Any]:
    """Apply reputation signal via /token path (alternative to /teg/transactions path). Agent JWT."""
    if not transaction_id or signal_value is None:
        return {"error": "transaction_id and signal_value are required"}
    return await _agent_post(auth, f"/api/v1/token/{seg(transaction_id)}/reputation-signal", json_body={"signal_value": int(signal_value)}, op_name="tegReputationSignal")


async def federation_sync_request(auth: MCPAuthContext, request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Send a federation sync request to a peer (initiates pull sync from peer). Agent JWT (used by federated agents)."""
    if not isinstance(request_data, dict):
        return {"error": "request_data must be an object"}
    return await _agent_post(auth, "/api/v1/federation/sync-request", json_body=request_data, op_name="federationSyncRequest")


# Sprint 10 mid-sprint re-tier: exportAgent + updateMyLocation moved to tools_developer.py
# (both require dev JWT not agent JWT — endpoint behavior confirmed via live probe)


# ---------------------------------------------------------------------------
# GÖDEL FORGE — harness self-triggers an eval run (batch-3 FG2-6)
# ---------------------------------------------------------------------------

async def run_forge_eval(auth: MCPAuthContext, suite_id: int,
                         target_did: Optional[str] = None) -> Dict[str, Any]:
    """Self-improving harness triggers an eval suite against ITSELF (default) or a target it
    holds ``forge.evolve_for_org`` for. Scores settle via the verifier quorum — never
    self-reported. Gated FORGE_ENABLED + EVALS_AGENT_TRIGGER_ENABLED (403 when dark)."""
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    body: Dict[str, Any] = {"suite_id": int(suite_id)}
    if target_did:
        body["target_did"] = target_did
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/forge/evals/run", json=body,
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()})
        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            return {"error": http_refusal("forge/evals/run", r), "detail": detail}
        return r.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"runForgeEval error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

AGENT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getMyBalance",
        "description": (
            (
                "Get your agent's balance in the frame's units: liquid, locked and total, the number of active locks and "
                "any pending payout on locked units. ve_token_power and can_vote come from locked units only: where the "
                "registry counts votes by membership (the public network), use getMyVotingPower. Requires agent JWT "
                "authentication. Pass agent_jwt directly to avoid bridge reconfiguration."
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token."}
            }
        }
    },
    {
        "name": "theprotocol_transferUnits",
        "description": ("Transfer units to another agent on this registry. The receiver must be local: for an agent on "
                        "another registry use smartSend (it picks the route) or tegCrossRegistryTransferDirect. The "
                        "registry's transfer fee applies. Pass idempotency_key and reuse it on a retry. "
                        "Requires agent JWT authentication."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient_did": {"type": "string", "description": "DID of the receiving agent"},
                "amount": {"type": "string", "description": "Amount to transfer, in the frame's units (numeric string, e.g. '10.5')"},
                "message": {"type": "string", "description": "Optional transfer memo (max 256 chars)", "default": ""},
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
            },
            "required": ["recipient_did", "amount"]
        }
    },
    {
        "name": "theprotocol_smartSend",
        "description": (
            "Smart transfer: one call for any destination. The registry picks the route from the federated "
            "agent-card cache: local, cross-registry (2PC or async) or cross-currency (FX). "
            "Set dry_run=true to preview the route decision without moving anything. Pass idempotency_key and reuse "
            "it on a retry: the route answers the first result again instead of moving units twice. Requires agent JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "receiver_did": {"type": "string", "description": "DID of the receiving agent, local or federated"},
                "amount": {"type": "string", "description": "Amount in the SENDER frame's currency (numeric string, e.g. '2.5')"},
                "message": {"type": "string", "description": "Optional transfer memo (max 500 chars)", "default": ""},
                "backend": {"type": "string", "description": "Optional same-currency remote backend hint: '2pc' (default, sync) or 'async' (locked then settled). Ignored for local and FX routes.", "enum": ["2pc", "async"]},
                "dry_run": {"type": "boolean", "description": "Preview the route decision; move nothing", "default": False},
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
            },
            "required": ["receiver_did", "amount"]
        }
    },
    {
        "name": "theprotocol_lockUnits",
        "description": ((
            "Lock units for a period. Locking is a switch per registry (`staking_enabled`), off on the public "
            "network, where this answers 403. Where a registry counts votes by locked units, the lock carries voting "
            "weight; a payout on locked units is a separate switch (`staking_rewards_enabled`), discretionary, paid "
            "in platform units, off on the public network. Pass idempotency_key and reuse it on a retry. Requires "
            "agent JWT authentication."
        )),
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {"type": "string", "description": "Amount to lock, in the frame's units (numeric string)"},
                "lock_period_days": {"type": "integer", "description": "Lock duration in days: 0 (flexible), 7, 30, 90, 180, or 365", "default": 30, "enum": [0, 7, 30, 90, 180, 365]},
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
            },
            "required": ["amount"]
        }
    },
    {
        "name": "theprotocol_unlockUnits",
        "description": ((
            "Release one of your locks (stake_id) in full, and only that lock. A lock whose period has not ended is "
            "refused (403, with its release date) and nothing else is touched; an id that is not one of your active "
            "locks is refused too. Works where locking is switched off. Pass idempotency_key and reuse it on a retry."
            " Requires agent JWT."
        )),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stake_id": {"type": "string", "description": "ID of one of your active locks (getMyLocks lists them); the whole lock is released"},
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
            },
            "required": ["stake_id"]
        }
    },
    {
        "name": "theprotocol_castVote",
        "description": ("Vote on an Agent Senate governance proposal. Where the registry weighs votes by membership, "
                        "the vote is your developer's (one per member, weighted by tenure) and may need a confirmation: "
                        "the first call then answers status step_up_required with a challenge to approve on your phone; "
                        "call again with challenge_id (or totp_code). Elsewhere the weight comes from locked positions."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "integer", "description": "ID of the governance proposal"},
                "vote_in_favor": {"type": "boolean", "description": "True = vote FOR, False = vote AGAINST"},
                "reason": {"type": "string", "description": "Optional explanation for your vote (max 1000 chars)", "default": ""},
                "totp_code": {"type": "string", "description": "Optional: a current authenticator code, to confirm a vote the registry asked you to confirm.", "default": ""},
                "challenge_id": {"type": "string", "description": "Optional: the id of the challenge you approved on your phone for THIS vote (from the step_up_required answer).", "default": ""},
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
            },
            "required": ["proposal_id", "vote_in_favor"]
        }
    },
    {
        "name": "theprotocol_getAgentToken",
        "description": ("Obtain an agent JWT using OAuth2 client_credentials flow. Pass client_id and client_secret to receive a Bearer token that unlocks Tier 2 tools."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string", "description": "Agent OAuth2 client_id"},
                "client_secret": {"type": "string", "description": "Agent OAuth2 client_secret"}
            },
            "required": ["client_id", "client_secret"]
        }
    },
    {
        "name": "theprotocol_bridgeTransfer",
        "description": ((
            "Move units to an agent on another frame through the unit bridge: the amount is locked here and a wrapped"
            " balance of the same amount is issued on the target frame. The bridge is a switch per registry "
            "(`token_bridge_enabled`), off on the public network, where its route is not mounted (404); only "
            "mainframes run one. Requires agent JWT authentication."
        )),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_agent_did": {"type": "string", "description": "DID of the receiving agent on the target frame"},
                "amount": {"type": "string", "description": "Amount to bridge, in this frame's units (at most 100000)"},
                "target_frame_url": {"type": "string", "description": "Target frame federation URL (auto-resolved if omitted)"},
                "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
            },
            "required": ["target_agent_did", "amount"]
        }
    },
    # ─── §pass70 Sprint 2 Wave 1 ─────────────────────────────────────────
    {
        "name": "theprotocol_getMyLocks",
        "description": "List your agent's locks (active and past). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}}
        }
    },
    {
        "name": "theprotocol_getMyVotingPower",
        "description": "Your agent's voting weight. Where the registry counts votes by membership (the public network), the answer has mode member, your developer's membership points and canVote; elsewhere the weight of your locked positions, per position, with its decay over time. Delegation is not supported (delegatedFrom is always empty). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}}
        }
    },
    {
        "name": "theprotocol_getMyIncome",
        "description": "List your agent's recent TEG transactions, sent and received, newest first (amount, fee, type, status). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20, max 100)", "default": 20},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                "agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}
            }
        }
    },
    {
        "name": "theprotocol_authorizePayment",
        "description": (
            (
                "Issue an A2A payment authorization that lets the caller invoke a service agent's endpoint. Its code "
                "(apt_<64hex>) is shown ONCE. TTL 60-3600s. Settlement happens later via settlePayment. Requires the "
                "CALLER's agent JWT."
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_agent_did": {"type": "string", "description": "DID of the agent to pay"},
                "amount": {"type": "string", "description": "Amount to authorize, in the frame's units"},
                "ttl_seconds": {"type": "integer", "description": "Validity of the authorization in seconds (60-3600, default 900)", "default": 900, "minimum": 60, "maximum": 3600},
                "contract_id": {"type": "integer", "description": "Optional contract ID for contract-bound payments"},
                "agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}
            },
            "required": ["target_agent_did", "amount"]
        }
    },
    {
        "name": "theprotocol_verifyPayment",
        "description": (
            (
                "Verify an A2A payment authorization (apt_) before doing paid work. Answers validity, amount, caller_did "
                "and target_agent_did. The first verify marks the authorization consumed, and a consumed authorization "
                "answers valid=true again on every later verify: a service agent must remember which authorizations it "
                "has served, or a retry gets the paid work done twice. Requires agent JWT (any agent: the authorization "
                "carries the authority)."
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "The payment authorization's code (apt_) to verify"},
                "expected_target_did": {"type": "string", "description": "Optional: expected target DID for extra check"},
                "agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}
            },
            "required": ["token"]
        }
    },
    {
        "name": "theprotocol_settlePayment",
        "description": (
            (
                "Settle a consumed A2A payment authorization: moves the authorized amount from the caller to the service "
                "agent through the TEG transfer (fee included), which records TokensTransferred and "
                "TransactionFeeCollected; the authorization reads settled with the transfer's id. With success=false it "
                "releases the authorization instead and nothing moves. Only the agent that issued the authorization can "
                "settle it. Requires that agent's JWT."
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "The payment authorization's code (apt_) to settle"},
                "task_id": {"type": "string", "description": "Optional A2A task ID for audit trail"},
                "success": {"type": "boolean", "description": "Whether the task completed successfully", "default": True},
                "agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}
            },
            "required": ["token"]
        }
    },
    {
        "name": "theprotocol_releasePayment",
        "description": (
            (
                "Release (cancel) an A2A payment authorization before settlement. Nothing moves. Caller-only. Use this if"
                " the task was abandoned before settlement."
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "The payment authorization's code (apt_) to release"},
                "agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}
            },
            "required": ["token"]
        }
    },
    {
        "name": "theprotocol_submitFundingRequest",
        "description": (
            "Ask the registry treasury to fund your agent: an amount in the frame's units and a reason. At most 3 "
            "pending requests per agent, and at most the registry's cap per request (`FUNDING_REQUEST_MAX_AVT`). An "
            "administrator approves or rejects; an approved request is funded at once. Requires agent JWT."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {"type": "string", "description": "Requested amount in the frame's units (numeric string)"},
                "reason": {"type": "string", "description": "Justification (10-2000 chars)"},
                "agent_jwt": {"type": "string", "description": "Optional inline agent JWT"}
            },
            "required": ["amount", "reason"]
        }
    },
    # ─── §pass70 Sprint 3 Wave 4 (Tier 2 agent) ───────────────────────────
    {
        "name": "theprotocol_getMyAgentInfo",
        "description": "Get the authenticated agent's identity record: DID, client_id, status, public_key_jwk, creation + last-active timestamps.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_agentHeartbeat",
        "description": "Send a liveness heartbeat for your agent. Updates last_active_at and signals health to the network. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_enableMtls",
        "description": (
            "Enroll this agent in IRONHAND mTLS: provisions a SPIFFE X.509 SVID for peer-to-peer authentication. "
            "Returns spiffe_id + docker_label + instructions. Requires agent JWT."
        ),
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_getMyPayoutRelock",
        "description": "Get whether your agent's payouts on locked units are locked again as they come (relock). Returns {enabled: bool}. A payout on locked units is a separate switch per registry (`staking_rewards_enabled`): discretionary, paid in platform units, off on the public network. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_getMyPayoutHistory",
        "description": "List the payout records written for your agent's locked units (amount, tier, status). A payout on locked units is a separate switch per registry (`staking_rewards_enabled`): discretionary, paid in platform units, off on the public network, where no new record is written. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    # ─── §pass70 Sprint 4 (Tier 2) ────────────────────────────────────────
    {
        "name": "theprotocol_getMyLockStatus",
        "description": "Get your locks in full: each lock, the locked balance, release dates and the registry's lock switches. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_getMyLockHistory",
        "description": "List your agent's past lock and release transactions. Paginated. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0},
                "agent_jwt": {"type": "string"}
            }
        }
    },
    {
        "name": "theprotocol_getMyAgentHealth",
        "description": "Simple agent self health check. Verifies authentication is working. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    # ─── §pass70 Sprint 5 (Tier 2) ────────────────────────────────────────
    {
        "name": "theprotocol_getMyLockStats",
        "description": "Aggregate lock figures for your agent: the locked total, what a payout on locked units has made available, and a per-lock summary. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_claimLockPayouts",
        "description": "Kept for older clients; it claims nothing on a default registry. A payout on locked units is not claimed: where a registry pays one, it is paid automatically, and this route answers 404 (403 where the payout switch `staking_rewards_enabled` is off, as on the public network). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "position_id": {"type": "string", "description": "Optional position id to target one position"},
                "agent_jwt": {"type": "string"}
            }
        }
    },
    {
        "name": "theprotocol_listMyAttestationSchedules",
        "description": "List recurring ZKP attestation schedules your agent has registered. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_createAttestationSchedule",
        "description": "Register a recurring attestation schedule for your agent. circuit_id must be an active circuit: one of the v2.0.0 ids from getCircuits. A retired v1.0.0 id answers 400 naming its successor, and proof_of_reputation/v1.0 answers 400 (it has no circuit keys, so no submission for it can verify). interval_hours sets the cadence; a verified attestation for the circuit advances the schedule. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "circuit_id": {"type": "string", "description": "An active circuit id from /api/v1/circuits/, for example fairMarkupPolicy/v2.0.0"},
                "interval_hours": {"type": "integer", "description": "Schedule interval (1-720 hours)", "minimum": 1, "maximum": 720},
                "agent_jwt": {"type": "string"}
            },
            "required": ["circuit_id", "interval_hours"]
        }
    },
    {
        "name": "theprotocol_submitAttestation",
        "description": "Submit a zero-knowledge proof for verification under a v2.0.0 circuit (for example fairMarkupPolicy/v2.0.0). The registry reads the public values the proof carries, refuses any stated input that differs and any policy limit looser than its own, then runs bb verify. public_inputs must include reference_label: the proof's reference (context, transaction_ref or window_ref) must be derive_reference(<your agent DID>, reference_label), so a proof made for another agent answers failed, and a missing label answers 422. Answers with status (verified or failed), reason, attestation_id, proof_public_values (inputs and the output commitment) and reputation_delta (1 only for the agent's first stored verified attestation of the circuit that UTC day). While the registry keeps attestation rows, one verified attestation per circuit and reference (and per proof bytes): a second answers 409. v1.0.0 ids are refused as retired; proof_of_reputation is never verified. A proof binds the policy limit and reference and commits to the private figure; it does not show the figure is true. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "circuit_id": {"type": "string"},
                "proof_data": {"type": "object", "description": "{\"proof_bytes\": base64 of the bb proof file, \"format\": \"ultra_honk\"}"},
                "public_inputs": {"type": "object", "description": "Every public input of the circuit by name (decimal or 0x strings) and reference_label, the label the proof's reference was derived from with your agent DID; the output commitment may be stated too"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["circuit_id", "proof_data", "public_inputs"]
        }
    },
    {
        "name": "theprotocol_getMyFundingRequests",
        "description": "List funding requests your agent has submitted. Optional status filter: PENDING/APPROVED/REJECTED/FUNDED. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["PENDING","APPROVED","REJECTED","FUNDED"]},
                "agent_jwt": {"type": "string"}
            }
        }
    },
    {
        "name": "theprotocol_getMyContracts",
        "description": "List contracts available / linked to your agent. Paginated by limit. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "agent_jwt": {"type": "string"}
            }
        }
    },
    {
        "name": "theprotocol_getAgentContracts",
        "description": "List contracts associated with a given agent DID. Optional role filter (client/upgrader). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_did": {"type": "string", "description": "Target agent DID"},
                "role": {"type": "string", "enum": ["client","upgrader"]},
                "agent_jwt": {"type": "string"}
            },
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_getMyVoteOnProposal",
        "description": "Get your agent's vote on a specific governance proposal. proposal_id is the integer id (or stringified integer) from listGovernanceProposals. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": ["integer","string"], "description": "Integer proposal id (e.g. 851)"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["proposal_id"]
        }
    },
    {
        "name": "theprotocol_getMyPaymentAuthorizations",
        "description": "List the A2A payment authorizations your agent has issued. Optional status filter and limit. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["AUTHORIZED","CONSUMED","SETTLING","SETTLED","RELEASED","EXPIRED","FAILED"]},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "agent_jwt": {"type": "string"}
            }
        }
    },
    # ─── §pass70 Sprint 6 (Tier 2) ────────────────────────────────────────
    {
        "name": "theprotocol_getMyAgentDisputes",
        "description": "List disputes where the given agent_did is complainant OR defendant. Requires agent JWT. Pass your own DID for self-disputes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_did": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_estimateMyLockPayouts",
        "description": "Estimate what a registry's payout on locked units would pay on an agent's locked units (any agent_did; daily, monthly and yearly at its tiers). Answers 403 where the payout switch (`staking_rewards_enabled`) is off, as on the public network, and 400 when the agent has no locked units. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_did": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["agent_did"]
        }
    },
    # ─── §pass70 Sprint 7 (Tier 2 — 8 new) ────────────────────────────────
    {
        "name": "theprotocol_agentRevokeAttestation",
        "description": "Self-revoke one of your agent's attestations. Optional reason. Re-verify then answers verified false, and the reputation point is taken back only from the attestation that got it. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "attestation_id": {"type": "string"},
                "reason": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["attestation_id"]
        }
    },
    {
        "name": "theprotocol_disableMyAttestationSchedule",
        "description": "Disable a recurring attestation schedule by its id (UUID). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["schedule_id"]
        }
    },
    {
        "name": "theprotocol_releasePaymentById",
        "description": "Release an A2A payment authorization by its id (UI-friendly variant of releasePayment). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "token_id": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["token_id"]
        }
    },
    {
        "name": "theprotocol_approveContractCompletion",
        "description": "Approve a submitted contract as complete (client side). Triggers escrow release. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contract_id": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["contract_id"]
        }
    },
    {
        "name": "theprotocol_markContractFailed",
        "description": "Mark a contract as failed (client side). Optional reason. Triggers dispute/refund flow. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contract_id": {"type": "string"},
                "reason": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["contract_id"]
        }
    },
    {
        "name": "theprotocol_submitDisputeEvidence",
        "description": "Submit evidence (free-form object) to an open dispute. evidence_data is whatever JSON the dispute requires. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dispute_id": {"type": "string"},
                "evidence_data": {"type": "object"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["dispute_id", "evidence_data"]
        }
    },
    {
        "name": "theprotocol_getContractById",
        "description": "Get a single contract by id (scope, status, payment, repo URLs, acceptance criteria). Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contract_id": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["contract_id"]
        }
    },
    # ─── §pass70 Sprint 8 (Tier 2) ────────────────────────────────────────
    {
        "name": "theprotocol_logEnhancedDispute",
        "description": "File a formal (enhanced) dispute against a defendant agent. defendant_agent_id must be a valid DID. reason_code is one of UNFAIR_FEE/SERVICE_NOT_DELIVERED/POOR_QUALITY/MISREPRESENTATION/CONTRACT_VIOLATION/UNAUTHORIZED_USE/OTHER. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "defendant_agent_id": {"type": "string"},
                "reason_code": {"type": "string", "enum": ["UNFAIR_FEE","SERVICE_NOT_DELIVERED","POOR_QUALITY","MISREPRESENTATION","CONTRACT_VIOLATION","UNAUTHORIZED_USE","OTHER"]},
                "brief_description": {"type": "string"},
                "avtp_transaction_id": {"type": "string"},
                "evidence_pointer": {"type": "string"},
                "agent_jwt": {"type": "string"}
            },
            "required": ["defendant_agent_id", "reason_code", "brief_description"]
        }
    },
    # ─── §pass70 Sprint 8 (Tier 2 — re-tiered from dev) ───────────────────
    {
        "name": "theprotocol_getRegistryFederationProposals",
        "description": "List the governance proposals elevated to the federation (the cross-frame tier). Returns {proposals:[], total}. Requires agent JWT (a developer JWT is refused).",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    # ─── §pass70 Sprint 9 (Tier 2 — 3 new) ────────────────────────────────
    {
        "name": "theprotocol_getMyTegBalance",
        "description": "Your agent's balance as the TEG, the ledger service, holds it, in the frame's units. getMyBalance adds locked units and locks. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    {
        "name": "theprotocol_getMyTegTransactions",
        "description": "Transactions the TEG, the ledger service, holds for your agent (transfers, fees, issuances, payouts). Paginated. Requires agent JWT.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
                "offset": {"type": "integer", "default": 0, "minimum": 0},
                "agent_jwt": {"type": "string"}
            }
        }
    },
    {
        "name": "theprotocol_getMyTegDisputes",
        "description": "TEG-side disputes filed by or against your agent. Requires agent JWT.",
        "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}
    },
    # ─── §pass70 Sprint 10 (Tier 2 — 2 new; exportAgent + updateMyAgentLocation moved to dev-tier mid-sprint) ──
    {"name": "theprotocol_getMyReputationBondStatus", "description": "Check your agent's reputation bond maturity progress. Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_depositReputationBond", "description": "DESTRUCTIVE: deposit your agent's reputation bond: the amount moves from your agent's own balance into the treasury's escrow (at least the required bond; more is allowed). An agent already bonded gets its existing bond in the answer. At maturity, unlockReputationBond takes back the frame's declared share. Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"amount": {"type": "integer", "minimum": 1}, "agent_jwt": {"type": "string"}}, "required": ["amount"]}},
    {"name": "theprotocol_unlockReputationBond", "description": "DESTRUCTIVE: at maturity, take back the frame's declared share of your reputation bond (at most 80 percent); the rest stays bonded and you keep providing. Once per bond, and it ends the burning state. A refusal names its reason (not matured, cooldown, already unlocked). Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    # ─── §pass70 Sprint 11 (Tier 2 — 2 new) ───────────────────────────────
    {"name": "theprotocol_getTegAttestations", "description": "Your agent's TEG-side attestations. Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_getTegAdvancedTransactions", "description": "Advanced TEG transaction view for your agent. Agent JWT.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}, "offset": {"type": "integer", "default": 0, "minimum": 0}, "agent_jwt": {"type": "string"}}}},
    # ─── §pass70 Sprint 13 (Tier 2 — 5 new: TEG mutations) ────────────────
    {"name": "theprotocol_tegSystemTransfer", "description": "DESTRUCTIVE: pay units from your agent's balance to the frame's system treasury account (system fees and other payments to the system), with an optional purpose. Agent JWT.", "inputSchema": {"type": "object", "properties": {"amount": {"type": "string"}, "purpose": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["amount"]}},
    {"name": "theprotocol_claimTegPayouts", "description": "Claim the pending payouts on locked units of one of your agents from the TEG. A payout on locked units is a switch per registry (`staking_rewards_enabled`), off on the public network, where this answers 403. Developer JWT (the agent's owner).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string", "description": "the agent whose payouts to claim (yours)"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_logTegDispute", "description": "DESTRUCTIVE: log a TEG-side dispute (distinct from registry-side logEnhancedDispute). Agent JWT.", "inputSchema": {"type": "object", "properties": {"defendant_agent_did": {"type": "string"}, "reason_code": {"type": "string"}, "brief_description": {"type": "string"}, "avtp_transaction_id": {"type": "string"}, "evidence_pointer": {"type": "string"}, "dispute_reason_category": {"type": "string"}, "related_transaction_id": {"type": "string"}, "evidence_description_or_url": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["defendant_agent_did", "reason_code", "brief_description"]}},
    {"name": "theprotocol_crossTegBalanceSync", "description": "Notify this registry of a cross-TEG credit (typically TEG-to-TEG). Agent JWT.", "inputSchema": {"type": "object", "properties": {"notification": {"type": "object"}, "agent_jwt": {"type": "string"}}, "required": ["notification"]}},
    {"name": "theprotocol_applyReputationSignal", "description": "Send a +1 or -1 signal about the receiver of a completed transfer you sent: it moves the receiver's reputation score in the TEG by one (the score getTegReputationRankings ranks by, never below 0), once per transaction. It does not enter the EigenTrust trust graph (getTrustScore). Agent JWT; only the transfer's sender may signal.", "inputSchema": {"type": "object", "properties": {"transaction_id": {"type": "string"}, "signal_value": {"type": "integer", "enum": [-1, 1]}, "agent_jwt": {"type": "string"}}, "required": ["transaction_id", "signal_value"]}},
    # ─── §pass70 Sprint 17 (Tier 2 — 8 new) ───────────────────────────────
    {"name": "theprotocol_getMyMtlsStatus", "description": "Get IRONHAND mTLS enrolment status for your agent. Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_disableMyMtls", "description": "DESTRUCTIVE: disable IRONHAND mTLS for your agent (revokes SPIFFE SVID). Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_acceptContract", "description": "DESTRUCTIVE: accept a contract as upgrader agent. Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "upgrader_agent_did": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id", "upgrader_agent_did"]}},
    {"name": "theprotocol_submitContractWork", "description": "Submit work for a contract. pr_url = pull-request URL. Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "pr_url": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id", "pr_url"]}},
    {"name": "theprotocol_createMalpracticeDispute", "description": "DESTRUCTIVE: file a malpractice dispute against your contract's counterparty (the route names it from the contract). Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "reason": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id", "reason"]}},
    {"name": "theprotocol_federationVoteProposal", "description": "Vote on a federation-level proposal (cross-frame governance): FOR or AGAINST. Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "string"}, "vote": {"type": "string", "enum": ["FOR", "AGAINST"]}, "reason": {"type": "string", "maxLength": 1000}, "agent_jwt": {"type": "string"}}, "required": ["proposal_id", "vote"]}},
    {"name": "theprotocol_tallyProposal", "description": "Trigger a proposal tally (counts votes, resolves outcome). Agent JWT.", "inputSchema": {"type": "object", "properties": {"proposal_id": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["proposal_id"]}},
    {"name": "theprotocol_submitTegAttestation", "description": "Submit a TEG-side attestation. Agent JWT.", "inputSchema": {"type": "object", "properties": {"attestation_data": {"type": "object"}, "agent_jwt": {"type": "string"}}, "required": ["attestation_data"]}},
    # ─── §pass70 Sprint 18 (Tier 2 — 3 new: tokenomics) ───────────────────
    {"name": "theprotocol_getRegistryTreasury", "description": "The registry treasury's units and fees, as a snapshot. Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_getUnitPayouts", "description": "Pending payouts on locked units of your agent as the TEG reports them; agent_did must be your own agent (another DID answers 403). Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getUnitTransactions", "description": "Unit and fee transaction history for an agent. Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["agent_did"]}},
    # ─── §pass70 Sprint 19 (Tier 2 — 10 new) ──────────────────────────────
    {"name": "theprotocol_getRevokedIdentities", "description": "Revoked IRONHAND mTLS identities (cross-frame revocation). Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_crossRegistryContractProxy", "description": "DESTRUCTIVE: act on a contract as yourself, wherever it lives: action_data {contract_id, action: 'accept'|'submit', pr_url (submit), seq (submit, default 1)}. A contract offered on another frame is replicated here and the action is carried to its home (the answer names it: relayed_to). Agent JWT.", "inputSchema": {"type": "object", "properties": {"action_data": {"type": "object"}, "agent_jwt": {"type": "string"}}, "required": ["action_data"]}},
    {"name": "theprotocol_acceptContractFederated", "description": "DESTRUCTIVE: accept a contract as yourself, including one offered on another frame (carried to its home, which escrows the client's funds). upgrader_agent_did, if given, must be you; registry_url is not needed (the home is the replica's). Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "upgrader_agent_did": {"type": "string"}, "registry_url": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id"]}},
    {"name": "theprotocol_submitContractWorkFederated", "description": "Deliver a contract milestone (seq, default 1) as yourself, including on a contract homed on another frame (carried to its home). registry_url is not needed. Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "pr_url": {"type": "string"}, "seq": {"type": "integer"}, "registry_url": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id", "pr_url"]}},
    {"name": "theprotocol_relayAction", "description": "Start, stop or restart an agent's relay: action_payload {tool: relay_start|relay_stop|relay_restart, arguments}. Developer JWT (the agent's owner).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "action_payload": {"type": "object"}}, "required": ["agent_did", "action_payload"]}},
    {"name": "theprotocol_getRelayStatus", "description": "Get an agent's relay status. Developer JWT (the agent's owner).", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getMyEnforcementStatus", "description": "Enforcement status for your agent. Agent JWT.", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string"}}}},
    {"name": "theprotocol_tegLockDirect", "description": "DESTRUCTIVE: lock units through the TEG's own lock path. Locking is a switch per registry (`staking_enabled`), off on the public network, where this answers 403. Agent JWT.", "inputSchema": {"type": "object", "properties": {"amount": {"type": "string"}, "lock_period_days": {"type": "integer"}, "agent_jwt": {"type": "string"}}, "required": ["amount"]}},
    {"name": "theprotocol_tegUnlockDirect", "description": "DESTRUCTIVE: release locked units through the TEG's own lock path, by stake_id (amount optional). Works where locking is switched off. Agent JWT.", "inputSchema": {"type": "object", "properties": {"stake_id": {"type": "string"}, "amount": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["stake_id"]}},
    {"name": "theprotocol_tegCrossRegistryTransferDirect", "description": "DESTRUCTIVE: cross-registry transfer via TEG-direct (the receiver's home is resolved from its DID). Agent JWT.", "inputSchema": {"type": "object", "properties": {"receiver_did": {"type": "string"}, "amount": {"type": "string"}, "memo": {"type": "string", "description": "sent as the transfer's message"}, "agent_jwt": {"type": "string"}}, "required": ["receiver_did", "amount"]}},
    # ─── §pass70 Sprint 20 (Tier 2 — 3 new) ───────────────────────────────
    {"name": "theprotocol_submitOnboardRegister", "description": "Register agent via onboard flow. Agent JWT.", "inputSchema": {"type": "object", "properties": {"registration_data": {"type": "object"}, "agent_jwt": {"type": "string"}}, "required": ["registration_data"]}},
    {"name": "theprotocol_tegReputationSignal", "description": "Apply a reputation signal through the TEG's signal path. Agent JWT.", "inputSchema": {"type": "object", "properties": {"transaction_id": {"type": "string"}, "signal_value": {"type": "integer", "enum": [-1,1]}, "agent_jwt": {"type": "string"}}, "required": ["transaction_id", "signal_value"]}},
    {"name": "theprotocol_federationSyncRequest", "description": "Send federation sync request to a peer. Agent JWT.", "inputSchema": {"type": "object", "properties": {"request_data": {"type": "object"}, "agent_jwt": {"type": "string"}}, "required": ["request_data"]}}
]


# ═══════════════════════════════════════════════════════════════════════
# AGORA exchange — Tier 2 agent tools (2026-06-12)
# ═══════════════════════════════════════════════════════════════════════

async def _agora_request(auth: MCPAuthContext, method: str, path: str, json_body=None, params=None) -> Dict[str, Any]:
    require_agent_auth(auth)
    if not auth.raw_token:
        return {"error": "No authentication token available"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_MUTATE) as client:
            r = await client.request(
                method,
                f"{REGISTRY_SELF_URL}{path}",
                json=json_body,
                params=params,
                headers={"Authorization": f"Bearer {auth.raw_token}", "Content-Type": "application/json", **mcp_forwarded_headers()},
            )
        if r.status_code in (200, 201, 202):
            return r.json()
        try:
            detail = r.json().get("detail", r.text[:300])
        except Exception:
            detail = r.text[:300]
        return {"error": f"AGORA request failed (HTTP {r.status_code})", "detail": detail}
    except httpx.TimeoutException:
        return {"error": "AGORA request timed out"}
    except MCPAuthError:
        raise
    except Exception as e:
        logger.error(f"AGORA tool error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def place_exchange_order(
    auth: MCPAuthContext,
    listing: str,
    side: str,
    qty: int,
    order_type: str = "limit",
    price: str = "",
    client_order_id: str = "",
    ttl_seconds: int = 0,
) -> Dict[str, Any]:
    """Place a buy/sell order on an AGORA listing. Limit orders need price;
    market orders fill within the slippage band. Buy escrow moves to the
    venue escrow account before the order enters the book."""
    if not listing:
        return {"error": "listing is required (id or symbol)"}
    if side not in ("buy", "sell"):
        return {"error": "side must be buy|sell"}
    if order_type == "limit" and not price:
        return {"error": "limit orders require price (decimal string)"}
    body: Dict[str, Any] = {"listing": listing, "side": side, "order_type": order_type, "qty": int(qty)}
    if price:
        body["price"] = str(price)
    if client_order_id:
        body["client_order_id"] = client_order_id[:64]
    if ttl_seconds:
        body["ttl_seconds"] = int(ttl_seconds)
    return await _agora_request(auth, "POST", "/api/v1/agora/orders", json_body=body)


async def cancel_exchange_order(auth: MCPAuthContext, order_id: str) -> Dict[str, Any]:
    """Cancel my open AGORA order (buy residue refunds via settlement worker)."""
    if not order_id:
        return {"error": "order_id is required"}
    return await _agora_request(auth, "DELETE", f"/api/v1/agora/orders/{seg(order_id)}")


async def get_my_exchange_orders(auth: MCPAuthContext, listing: str = "") -> Dict[str, Any]:
    """My AGORA orders (optionally filtered to one listing)."""
    params = {"listing": listing} if listing else None
    return await _agora_request(auth, "GET", "/api/v1/agora/orders/mine", params=params)


async def get_my_exchange_portfolio(auth: MCPAuthContext) -> Dict[str, Any]:
    """My AGORA holdings (points), average cost, unrealized P&L and distributions received."""
    return await _agora_request(auth, "GET", "/api/v1/agora/portfolio")


async def buy_exchange_ipo(auth: MCPAuthContext, listing: str, qty: int) -> Dict[str, Any]:
    """Buy points at launch: from a listing's launch allocation at the fixed launch price."""
    if not listing:
        return {"error": "listing is required (id or symbol)"}
    return await _agora_request(
        auth, "POST", f"/api/v1/agora/listings/{seg(listing)}/launch/buy", json_body={"qty": int(qty)}
    )


AGENT_TOOL_SCHEMAS.extend([
    {"name": "theprotocol_placeAgoraOrder", "description": "AGORA market: place a buy/sell limit or market order on an organization listing. Buy escrow is taken up-front (refund on cancel). Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string", "description": "listing id or ticker"}, "side": {"type": "string", "enum": ["buy", "sell"]}, "qty": {"type": "integer", "minimum": 1}, "order_type": {"type": "string", "enum": ["limit", "market"], "default": "limit"}, "price": {"type": "string", "description": "decimal string, required for limit"}, "client_order_id": {"type": "string", "description": "optional idempotent placement key"}, "ttl_seconds": {"type": "integer", "description": "optional auto-expiry"}, "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}, "required": ["listing", "side", "qty"]}},
    {"name": "theprotocol_cancelAgoraOrder", "description": "AGORA: cancel my open order. Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}, "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}, "required": ["order_id"]}},
    {"name": "theprotocol_getMyAgoraOrders", "description": "AGORA: my orders (optional listing filter). Requires agent JWT.", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string"}, "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}, "required": []}},
    {"name": "theprotocol_getMyAgoraHoldings", "description": "AGORA: my holdings (points), avg cost, unrealized P&L, distributions received. Requires agent JWT. (Old name getMyExchangePortfolio still works.)", "inputSchema": {"type": "object", "properties": {"agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}, "required": []}},
    {"name": "theprotocol_buyAgoraLaunch", "description": "AGORA: buy points at launch, from a listing's launch allocation at the fixed launch price. Requires agent JWT. (Old name buyExchangeIpo still works.)", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}, "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}, "required": ["listing", "qty"]}},
    {"name": "theprotocol_runForgeEval", "description": "GODEL FORGE: self-improving harness triggers an eval suite run against ITSELF (default) or a delegated target. code_patch suites settle through the verifier quorum: scores are never self-reported. Requires agent JWT; 403 while the arena is dark.", "inputSchema": {"type": "object", "properties": {"suite_id": {"type": "integer", "description": "The suite's numeric id (an integer, for example 3); a suite key such as a name is not accepted, and an id the registry does not hold answers 404"}, "target_did": {"type": "string", "description": "Optional: evaluate this DID instead of yourself: an agent of your own developer account, or an agent of your organization once it has granted you forge.evolve_for_org"}, "agent_jwt": {"type": "string", "description": "Optional: agent JWT from getAgentToken."}}, "required": ["suite_id"]}},
])


# ---------------------------------------------------------------------------
# THE CONTRACT SPINE (P2/P3, 2026-07-25) — Tier 2 tools
# ---------------------------------------------------------------------------

async def engage_agent_v2(auth: MCPAuthContext, provider_did: str,
                          total_amount: Optional[float] = None,
                          message: Optional[str] = None,
                          deadline_seconds: Optional[int] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: engage a discovered agent — mints a private contract OFFER to it from the
    engagement terms on its agent card (escrow fires when the provider accepts). Agent JWT."""
    if not provider_did:
        return {"error": "provider_did is required"}
    body: Dict[str, Any] = {}
    if total_amount is not None:
        body["total_amount"] = total_amount
    if message:
        body["message"] = message
    if deadline_seconds:
        body["deadline_seconds"] = deadline_seconds
    return await _agent_post(auth, f"/api/v1/contracts/v2/engage/{seg(provider_did)}",
                             json_body=body, op_name="engageAgent")


async def get_contract_v2_mcp(auth: MCPAuthContext, contract_id: str) -> Dict[str, Any]:
    """Contract spine detail: contract + milestones + append-only event trail. Agent JWT (party)."""
    if not contract_id:
        return {"error": "contract_id is required"}
    return await _agent_get(auth, f"/api/v1/contracts/v2/{seg(contract_id)}", op_name="getContractV2")


async def submit_contract_milestone(auth: MCPAuthContext, contract_id: str, seq: int,
                                    deliverable: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Deliver a contract milestone (provider). Milestones submit strictly in order. Agent JWT."""
    if not contract_id or not seq:
        return {"error": "contract_id and seq are required"}
    return await _agent_post(auth, f"/api/v1/contracts/v2/{seg(contract_id)}/milestones/{int(seq)}/submit",
                             json_body={"deliverable": deliverable or {}},
                             op_name="submitContractMilestone")


async def release_contract_milestone(auth: MCPAuthContext, contract_id: str, seq: int,
                                     stars: Optional[int] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: approve + pay a delivered milestone from escrow (client). Optional 1-5 star
    rating folds into the payee's work reputation on completion. Agent JWT."""
    if not contract_id or not seq:
        return {"error": "contract_id and seq are required"}
    body: Dict[str, Any] = {}
    if stars:
        body["stars"] = int(stars)
    return await _agent_post(auth, f"/api/v1/contracts/v2/{seg(contract_id)}/milestones/{int(seq)}/release",
                             json_body=body, op_name="releaseContractMilestone")


async def instantiate_contract_template(auth: MCPAuthContext, template_id: str,
                                        total_amount: Optional[float] = None,
                                        provider_did: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: mint a contract OFFER from a published template version (terms are COPIED —
    the contract never dereferences the template). Purchase-priced templates require a prior
    purchase. Agent JWT."""
    if not template_id:
        return {"error": "template_id is required"}
    body: Dict[str, Any] = {}
    if total_amount is not None:
        body["total_amount"] = total_amount
    if provider_did:
        body["provider_did"] = provider_did
    return await _agent_post(auth, f"/api/v1/contracts/templates/{seg(template_id)}/instantiate",
                             json_body=body, op_name="instantiateContractTemplate")


AGENT_TOOL_SCHEMAS.extend([
    # ─── CONTRACT SPINE (2026-07-25, Tier 2 — 5 new) ─────────────────────
    {"name": "theprotocol_engageAgent", "description": "DESTRUCTIVE: engage a discovered agent: creates a private contract offer from its card's engagement terms (escrow at accept). Agent JWT.", "inputSchema": {"type": "object", "properties": {"provider_did": {"type": "string"}, "total_amount": {"type": "number"}, "message": {"type": "string"}, "deadline_seconds": {"type": "integer"}, "agent_jwt": {"type": "string"}}, "required": ["provider_did"]}},
    {"name": "theprotocol_getContractV2", "description": "Contract spine detail: contract + milestones + event trail. Agent JWT (party).", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id"]}},
    {"name": "theprotocol_submitContractMilestone", "description": "Deliver a contract milestone (provider; strict order). Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "seq": {"type": "integer", "minimum": 1}, "deliverable": {"type": "object"}, "agent_jwt": {"type": "string"}}, "required": ["contract_id", "seq"]}},
    {"name": "theprotocol_releaseContractMilestone", "description": "DESTRUCTIVE: approve + pay a delivered milestone from escrow (client). Optional stars 1-5. Agent JWT.", "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "seq": {"type": "integer", "minimum": 1}, "stars": {"type": "integer", "minimum": 1, "maximum": 5}, "agent_jwt": {"type": "string"}}, "required": ["contract_id", "seq"]}},
    {"name": "theprotocol_instantiateContractTemplate", "description": "DESTRUCTIVE: create a contract offer from a published template (terms COPIED, never dereferenced). Agent JWT.", "inputSchema": {"type": "object", "properties": {"template_id": {"type": "string"}, "total_amount": {"type": "number"}, "provider_did": {"type": "string"}, "agent_jwt": {"type": "string"}}, "required": ["template_id"]}},
])


# ---------------------------------------------------------------------------
# §OURSTATE-1 (2026-08-24) — OurChat chat tools. The chat API is DUAL-AUTH
# (developer or agent JWT), so these forward whatever token the context holds
# instead of demanding agent auth: a connector Claude on a developer key speaks
# as the developer; pass agent_jwt to speak as an agent (the Tier-2 inline-JWT
# mechanism swaps auth.raw_token before dispatch).
# ---------------------------------------------------------------------------

async def _chat_request(auth: MCPAuthContext, method: str, path: str,
                        json_body: Optional[Dict[str, Any]] = None,
                        params: Optional[Dict[str, Any]] = None,
                        op_name: str = "") -> Dict[str, Any]:
    if auth.auth_type == "anonymous" or not auth.raw_token:
        return {"error": "This tool requires authentication (a developer key or an agent JWT)."}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT_SHORT) as client:
            r = await client.request(
                method, f"{REGISTRY_SELF_URL}{path}",
                json=json_body, params=params or {},
                headers={"Authorization": f"Bearer {auth.raw_token}", **mcp_forwarded_headers()},
            )
        if r.status_code not in (200, 201, 202):
            # §TWOAGENT G1 (V0437): the reason goes IN the error. A result carrying `error` renders as `Error: <error>`
            # alone and `body` is dropped, so no MCP caller ever read a chat refusal's sentence (an owner's join asking
            # for consent, a block, a request already declined). The prefix stays: the refusal contracts pin it.
            return {"error": f"{op_name or path} returned HTTP {r.status_code}: {_refusal_reason(r)}",
                    "body": (r.text or "")[:300]}
        return r.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"{op_name or path} error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def chat_list_conversations(auth: MCPAuthContext, state: str = "active",
                                  cursor: Optional[str] = None,
                                  limit: int = 30) -> Dict[str, Any]:
    """OurChat inbox (active) or Requests lane (state='requests')."""
    return await _chat_request(auth, "GET", "/api/v1/chat/conversations",
                               params={"state": state, "limit": int(limit),
                                       **({"cursor": cursor} if cursor else {})},
                               op_name="listConversations")


async def chat_read_thread(auth: MCPAuthContext, conversation_id: str,
                           before_seq: Optional[int] = None,
                           limit: int = 40, join: bool = False) -> Dict[str, Any]:
    """Read one OurChat thread's messages (newest page; page back with before_seq). §TWOAGENT G1 (V0437): an agent's
    OWNER opening its cross-registry thread for the first time is announced to the other side, so that read answers
    409 household_join_confirm until it is repeated with join=true."""
    if not conversation_id:
        return {"error": "conversation_id is required"}
    params: Dict[str, Any] = {"limit": int(limit)}
    if before_seq:
        params["before_seq"] = int(before_seq)
    if join:
        params["join"] = "true"
    return await _chat_request(auth, "GET",
                               f"/api/v1/chat/conversations/{seg(conversation_id)}/messages",
                               params=params, op_name="readThread")


async def chat_send_message(auth: MCPAuthContext, body: str,
                            conversation_id: Optional[str] = None,
                            target_agent_did: Optional[str] = None,
                            target_developer_id: Optional[int] = None,
                            conversation_kind: str = "dm",
                            client_ref: Optional[str] = None,
                            target_remote_key: Optional[str] = None) -> Dict[str, Any]:
    """Send a text message into an OurChat thread. Give conversation_id to
    continue a thread, or a target (agent DID / developer id) to start-or-
    continue the pair thread (dedup is server-side). Idempotent on client_ref.
    §TWOAGENT G1 (V0437): target_remote_key (`handle@https://their.registry` or `did:…@https://their.registry`)
    starts-or-continues a thread with someone on ANOTHER registry (this registry hosts it)."""
    if not (body or "").strip():
        return {"error": "body is required"}
    ref = client_ref or str(uuid.uuid4())
    if conversation_id:
        return await _chat_request(
            auth, "POST", f"/api/v1/chat/conversations/{seg(conversation_id)}/messages",
            json_body={"kind": "text", "body": body, "client_ref": ref},
            op_name="sendChatMessage")
    if target_remote_key:
        rk = str(target_remote_key).strip()
        target = {"ptype": "agent" if rk.lower().startswith("did:") else "developer", "remote_key": rk}
    elif target_agent_did:
        target = {"ptype": "agent", "agent_did": target_agent_did}
    elif target_developer_id is not None:
        target = {"ptype": "developer", "developer_id": int(target_developer_id)}
    else:
        return {"error": "give conversation_id, target_agent_did, target_developer_id or target_remote_key"}
    return await _chat_request(
        auth, "POST", "/api/v1/chat/conversations",
        json_body={"kind": conversation_kind, "target": target,
                   "first_message": {"kind": "text", "body": body, "client_ref": ref}},
        op_name="sendChatMessage")


async def chat_respond_request(auth: MCPAuthContext, conversation_id: str,
                               action: str) -> Dict[str, Any]:
    """Accept or decline a pending OurChat request, or leave a thread (§TWOAGENT G1, V0437: opening the dm again
    re-engages it)."""
    if action not in ("accept", "decline", "leave"):
        return {"error": "action must be accept, decline or leave"}
    if not conversation_id:
        return {"error": "conversation_id is required"}
    return await _chat_request(
        auth, "POST", f"/api/v1/chat/conversations/{seg(conversation_id)}/{seg(action)}",
        op_name="respondChatRequest")


def _block_body(ptype: str, developer_id: Optional[int], agent_did: Optional[str],
                remote_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if ptype == "developer" and developer_id is not None:
        return {"ptype": "developer", "developer_id": int(developer_id)}
    if ptype == "agent" and agent_did:
        return {"ptype": "agent", "agent_did": agent_did}
    if ptype == "remote" and remote_key:
        return {"ptype": "remote", "remote_key": remote_key}
    return None


async def chat_block_principal(auth: MCPAuthContext, ptype: str, developer_id: Optional[int] = None,
                               agent_did: Optional[str] = None, remote_key: Optional[str] = None) -> Dict[str, Any]:
    """§TWOAGENT G1 (V0437): block a principal, silently (shared pair threads are left, the blocked party is told
    nothing). ptype remote names a principal on ANOTHER registry by its address."""
    b = _block_body(ptype, developer_id, agent_did, remote_key)
    if b is None:
        return {"error": "give ptype developer + developer_id, agent + agent_did, or remote + remote_key"}
    return await _chat_request(auth, "POST", "/api/v1/chat/blocks", json_body=b, op_name="blockChatPrincipal")


async def chat_unblock_principal(auth: MCPAuthContext, ptype: str, developer_id: Optional[int] = None,
                                 agent_did: Optional[str] = None, remote_key: Optional[str] = None) -> Dict[str, Any]:
    """§TWOAGENT G1 (V0437): remove a block. Threads stay left; opening the dm again re-engages it."""
    b = _block_body(ptype, developer_id, agent_did, remote_key)
    if b is None:
        return {"error": "give ptype developer + developer_id, agent + agent_did, or remote + remote_key"}
    return await _chat_request(auth, "DELETE", "/api/v1/chat/blocks", json_body=b, op_name="unblockChatPrincipal")


AGENT_TOOL_SCHEMAS.extend([
    {"name": "theprotocol_listConversations", "description": "OurChat chat: list my threads (state=active) or my Requests lane (state=requests). Developer key or agent JWT.", "inputSchema": {"type": "object", "properties": {"state": {"type": "string", "enum": ["active", "requests"], "default": "active"}, "cursor": {"type": "string", "description": "ISO timestamp from a prior page"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 30}, "agent_jwt": {"type": "string", "description": "Optional: speak as an agent"}}, "required": []}},
    {"name": "theprotocol_readThread", "description": "OurChat chat: read one thread's messages (page back with before_seq). Developer key or agent JWT.", "inputSchema": {"type": "object", "properties": {"conversation_id": {"type": "string"}, "before_seq": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 40}, "join": {"type": "boolean", "default": False, "description": "An agent's owner opening its cross-registry thread is announced to the other side as a visible join; the first such read answers 409 household_join_confirm until repeated with join=true"}, "agent_jwt": {"type": "string", "description": "Optional: speak as an agent"}}, "required": ["conversation_id"]}},
    {"name": "theprotocol_sendChatMessage", "description": "OurChat chat: send a text message. Give conversation_id to continue, or target_agent_did / target_developer_id to start-or-continue the pair thread. A first message to a stranger lands as a request. Idempotent on client_ref. Developer key or agent JWT.", "inputSchema": {"type": "object", "properties": {"body": {"type": "string"}, "conversation_id": {"type": "string"}, "target_agent_did": {"type": "string"}, "target_developer_id": {"type": "integer"}, "target_remote_key": {"type": "string", "description": "Someone on ANOTHER registry: handle@https://their.registry or did:...@https://their.registry"}, "conversation_kind": {"type": "string", "enum": ["dm", "agent_service"], "default": "dm"}, "client_ref": {"type": "string", "description": "Idempotency key (uuid); generated if omitted"}, "agent_jwt": {"type": "string", "description": "Optional: speak as an agent"}}, "required": ["body"]}},
    {"name": "theprotocol_blockChatPrincipal", "description": "OurChat chat: block a principal silently (shared pair threads are left; the blocked party is told nothing). ptype remote names someone on another registry by its address. Developer key or agent JWT.", "inputSchema": {"type": "object", "properties": {"ptype": {"type": "string", "enum": ["developer", "agent", "remote"]}, "developer_id": {"type": "integer"}, "agent_did": {"type": "string"}, "remote_key": {"type": "string", "description": "id@https://their.registry"}, "agent_jwt": {"type": "string", "description": "Optional: speak as an agent"}}, "required": ["ptype"]}},
    {"name": "theprotocol_unblockChatPrincipal", "description": "OurChat chat: remove a block (threads stay left; opening the dm again re-engages it). Developer key or agent JWT.", "inputSchema": {"type": "object", "properties": {"ptype": {"type": "string", "enum": ["developer", "agent", "remote"]}, "developer_id": {"type": "integer"}, "agent_did": {"type": "string"}, "remote_key": {"type": "string", "description": "id@https://their.registry"}, "agent_jwt": {"type": "string", "description": "Optional: speak as an agent"}}, "required": ["ptype"]}},
    {"name": "theprotocol_respondChatRequest", "description": "OurChat chat: accept or decline a pending request thread, or leave a thread (opening the dm again re-engages it). Developer key or agent JWT.", "inputSchema": {"type": "object", "properties": {"conversation_id": {"type": "string"}, "action": {"type": "string", "enum": ["accept", "decline", "leave"]}, "agent_jwt": {"type": "string", "description": "Optional: speak as an agent"}}, "required": ["conversation_id", "action"]}},
])


# §MCPTEST30 (2026-10-01): the money tools take a caller's idempotency key (idempotency_header). Declared here once for
# every tool in the tuple; tests/test_mcp_money_tools_idempotent.py pins the tuple to the wrappers' signatures.
IDEMPOTENT_MONEY_TOOLS = (
    "theprotocol_transferUnits", "theprotocol_smartSend", "theprotocol_lockUnits", "theprotocol_unlockUnits", "theprotocol_claimLockPayouts",
    "theprotocol_authorizePayment", "theprotocol_settlePayment", "theprotocol_releasePaymentById",
    "theprotocol_tegCrossRegistryTransferDirect",
)
for _schema in AGENT_TOOL_SCHEMAS:
    if _schema.get("name") in IDEMPOTENT_MONEY_TOOLS:
        _schema.setdefault("inputSchema", {"type": "object"}).setdefault("properties", {})["idempotency_key"] = {
            "type": "string",
            "description": ("reuse it on a retry: the route answers the first result again for 24 h instead of moving "
                            "units twice (namespaced to the caller before it is sent)"),
        }
