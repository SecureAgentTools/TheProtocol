"""V0650 (l) (2026-10-31, agentvault2-14) — approvals in the chat.

The maintainer's words in the sessions' room (2026-10-31 02:55Z): "commander account approval click needed for anything
you would ask in the session. the approvals should not scroll up with the history ... it should stay locked above the
chat window. manually approveable each or approve all button." And in agentvault2-14's session (03:13Z): "we have a
whole advanced approval system in but i want this as a master switch for quick response times on intended human
guideded development work. dont implement rails that already exist. (i dont intend to use phone approvals for this for
now. should also be possible to configure)."

WHAT IS REUSED. Everything a decision needs already exists, and this module only composes it:

  * the closed card vocabulary and its rail-only gate (`chat_service.RAIL_ONLY_CARDS`): `approval.request` and
    `approval.decided` are rail-only, so neither a client nor a federated peer can type one;
  * the one message writer (`chat_service.insert_message`) and its post-commit delivery (`chat_service.deliver`: the
    room's live cue, the owners' `chat.message.received` webhook, `/chat/sync`);
  * the org room's live membership (`resolve_membership`, `room_posting_gate`) and the org owner rule;
  * the step-up rail (`services/stepup.py`: `mint_challenge`, the phone's Pocket Approvals, single-use spending) for
    the optional presence switch, which is OFF unless the registry or the org turns it on;
  * the registry's attestation signer for the decision statement, and `security_audit_logs` for the audit trail.

WHAT IS NEW, AND WHY. The record (`chat_approvals`): the Cockpit's `liability_challenges` cannot carry it (a challenge
has one addressee, lives 120 seconds, refuses any answer without a presence proof and lights up the phone, which is the
flow he does not want here), the spend approvals cannot either (an amount is required and an approval is consumed by an
exact-amount retry), and the chat log cannot (a room's timer deletes messages, and the decision must outlive them).

WHO DECIDES. The org's owner, or an active member the owner named an approver (`organization_members.can_approve`),
re-derived on every decision. Agents never decide: the decide route takes a developer credential only.

WHAT A DECISION PROVES. Until presence is switched on, a decision proves the ACCOUNT that made it (and records how:
the credential kind, whether this registry's MCP server relayed it), not the hand. That is stated in every record.
Nothing here moves money or writes the ledger (Δ-irrelevant).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import secrets
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChatApproval, Conversation

logger = logging.getLogger(__name__)

ACTION_TYPE = "chat.approval"
STATUSES = ("pending", "approved", "denied", "expired")
DECISIONS = {"approve": "approved", "deny": "denied"}
EXPIRY_MIN_S = 60
EXPIRY_MAX_S = 7 * 86400
EXPIRY_DEFAULT_S = 3600
DECIDE_MAX_IDS = 50
PRESENCE_BATCH_MAX = 20     # one fingerprint may cover a batch, but a bounded one
WAIT_MAX_S = 20
WAIT_STEP_S = 1.5
TITLE_MAX = 200
REASON_MAX = 2000
UNLOCKS_MAX = 500
LABEL_MAX = 200
NOTE_MAX = 500
_PRESENCE_RANK = {"off": 0, "production": 1, "all": 2}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OFF_WORDS = {"0", "false", "off", "no"}

# Said in every record and every status answer, so nobody reads more into a click than it carries.
WHAT_IT_PROVES_ACCOUNT = ("This decision was made with the decider's account (see `via`); without a presence proof it "
                          "proves the account, not the hand that used it.")
WHAT_IT_PROVES_PRESENCE = ("This decision carries a presence proof: the decider's enrolled device signed the challenge "
                           "with user verification.")


class ApprovalError(Exception):
    """A refusal with an HTTP status and a named reason (the chat router translates it). `body` carries a structured
    answer where one is owed (the 428 step-up payload)."""

    def __init__(self, status_code: int, detail: str, body: Optional[dict] = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.body = body


# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------

def enabled() -> bool:
    """`CHAT_APPROVALS_ENABLED` (default on: the rail is inert until an agent in an org room asks)."""
    return (os.getenv("CHAT_APPROVALS_ENABLED", "true") or "true").strip().lower() not in _OFF_WORDS


def max_pending() -> int:
    """How many undecided requests one agent may hold in one room (`CHAT_APPROVAL_MAX_PENDING`, default 20)."""
    try:
        return max(1, min(200, int(os.getenv("CHAT_APPROVAL_MAX_PENDING", "20"))))
    except (TypeError, ValueError):
        return 20


def registry_presence() -> str:
    """The registry's presence floor, `CHAT_APPROVAL_PRESENCE` = off (default) | production | all. A value nobody can
    read is never `off`: it resolves to `production`, with a WARNING, so a typo cannot silently remove a floor."""
    raw = (os.getenv("CHAT_APPROVAL_PRESENCE", "off") or "off").strip().lower()
    if raw in _PRESENCE_RANK:
        return raw
    logger.warning("[CHATAPPROVAL] CHAT_APPROVAL_PRESENCE=%r is not off|production|all: read as production", raw)
    return "production"


def presence_policy(registry_value: str, org_settings: Optional[dict]) -> str:
    """The stricter of the registry's floor and the org's setting (`chat_approvals.presence`); an org can only add a
    floor, never remove the registry's."""
    rank = _PRESENCE_RANK.get(registry_value, 1)
    block = (org_settings or {}).get("chat_approvals") if isinstance(org_settings, dict) else None
    if isinstance(block, dict):
        ov = str(block.get("presence") or "").strip().lower()
        if ov in _PRESENCE_RANK:
            rank = max(rank, _PRESENCE_RANK[ov])
    return {v: k for k, v in _PRESENCE_RANK.items()}[rank]


def presence_required(policy: str, decision: str, production_impact: bool) -> bool:
    """Deny never asks: refusing must always be the easy path."""
    if decision != "approve":
        return False
    return policy == "all" or (policy == "production" and bool(production_impact))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return "apr_" + secrets.token_hex(16)


def normalize_sha256(value: Any) -> Optional[str]:
    """An artifact's sha256 as 64 lowercase hex; a `sha256:` prefix is accepted and dropped. Empty means none."""
    if value is None:
        return None
    t = str(value).strip().lower()
    if not t:
        return None
    if t.startswith("sha256:"):
        t = t[len("sha256:"):]
    if not _SHA256_RE.match(t):
        raise ApprovalError(422, "artifact_sha256 must be the sha256 of the artifact: 64 hexadecimal characters")
    return t


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def iso(ts: Optional[_dt.datetime]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return ts.astimezone(_dt.timezone.utc).isoformat()


def request_facts(*, approval_id: str, conversation_id: str, org_id: Optional[str], requester_agent_did: str,
                  title: str, reason: Optional[str], unlocks: Optional[str], artifact_sha256: Optional[str],
                  artifact_label: Optional[str], production_impact: bool, created_at: _dt.datetime,
                  expires_at: _dt.datetime, client_ref: str) -> dict:
    """The request as the registry recorded it. `facts_digest` is the sha256 of exactly this, and every decision
    repeats it, so a requester can check that the decision answers its own request and nothing else."""
    return {
        "type": "theprotocol.chat-approval.request.v1",
        "approval_id": approval_id,
        "conversation_id": conversation_id,
        "org_id": org_id,
        "requester_agent_did": requester_agent_did,
        "title": title,
        "reason": reason,
        "unlocks": unlocks,
        "artifact_sha256": artifact_sha256,
        "artifact_label": artifact_label,
        "production_impact": bool(production_impact),
        "created_at": iso(created_at),
        "expires_at": iso(expires_at),
        "client_ref": client_ref,
    }


def effective_status(status: str, expires_at: Optional[_dt.datetime], now: _dt.datetime) -> str:
    """A pending request past its expiry IS expired, whatever its column says: expiry is server-clocked and lazy."""
    if status == "pending" and expires_at is not None:
        ex = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=_dt.timezone.utc)
        if ex <= now:
            return "expired"
    return status


def partition_for_decision(rows: Iterable[Any], ids: Sequence[str],
                           now: _dt.datetime) -> Tuple[List[Any], Dict[str, str]]:
    """Which of the asked ids can be decided now, and why each other one cannot.

    Only rows that are pending AND unexpired are decidable. Every other id is reported by name: `not_found` (not a
    request of this conversation), `expired`, `already_approved`, `already_denied`. Approve all therefore decides
    exactly the pending ones, and an expired request can never be approved."""
    by_id = {r.id: r for r in rows}
    decidable: List[Any] = []
    skipped: Dict[str, str] = {}
    seen = set()
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        r = by_id.get(i)
        if r is None:
            skipped[i] = "not_found"
            continue
        st = effective_status(r.status, r.expires_at, now)
        if st == "pending":
            decidable.append(r)
        elif st == "expired":
            skipped[i] = "expired"
        else:
            skipped[i] = f"already_{st}"
    return decidable, skipped


def refusal_when_nothing_decided(skipped: Dict[str, str], decision: str) -> Tuple[int, str, bool]:
    """(status, sentence, already) when no id was decidable. `already` = every found id already carries THIS decision
    (an idempotent repeat answers 200)."""
    found = {k: v for k, v in skipped.items() if v != "not_found"}
    if not found:
        return 404, "none of these approval requests belong to this conversation", False
    if all(v == "expired" for v in found.values()):
        return 410, "these approval requests expired; an expired request cannot be approved", False
    same = f"already_{DECISIONS[decision]}"
    if all(v in (same, "expired") for v in found.values()) and any(v == same for v in found.values()):
        return 200, "already decided this way", True
    return 409, "already decided the other way; a decision is final", False


def action_ref_for(decision: str, ids: Sequence[str], conversation_id: str) -> str:
    """What a presence challenge is bound to: this decision, on exactly these requests, in this conversation."""
    h = hashlib.sha256(f"{decision}|{','.join(sorted(set(ids)))}|{conversation_id}".encode()).hexdigest()
    return f"{ACTION_TYPE}:{h}"


def challenge_facts(decision: str, rows: Sequence[Any], conversation_id: str) -> dict:
    """What the phone shows and signs when presence is asked for: the requests by title and artifact, never a
    client-supplied sentence."""
    return {
        "action": ACTION_TYPE,
        "decision": decision,
        "conversation_id": conversation_id,
        "count": len(rows),
        "approval_ids": sorted(r.id for r in rows),
        "titles": [r.title for r in rows][:PRESENCE_BATCH_MAX],
        "artifact_sha256": [r.artifact_sha256 for r in rows if r.artifact_sha256][:PRESENCE_BATCH_MAX],
        "production_impact": any(bool(r.production_impact) for r in rows),
    }


def build_statement(row: Any, *, decision: str, decided_at: _dt.datetime, decider_id: int, decider_name: str,
                    role: str, via: dict, presence: Optional[dict], registry: str = "") -> dict:
    """The registry's signed statement of one decision. The public key travels OUTSIDE the signed object (the share
    certificate's lesson: a field added after signing breaks verification), and a statement the registry cannot verify
    itself is served unsigned with the reason, never as if it were signed."""
    stmt: Dict[str, Any] = {
        "type": "theprotocol.chat-approval.decision.v1",
        "registry": registry or None,
        "approval_id": row.id,
        "conversation_id": row.conversation_id,
        "org_id": row.org_id,
        "requester_agent_did": row.requester_agent_did,
        "title": row.title,
        "artifact_sha256": row.artifact_sha256,
        "request_digest": row.facts_digest,
        "decision": DECISIONS[decision],
        "decided_at": iso(decided_at),
        "decided_by": {"developer_id": int(decider_id), "name": decider_name, "role": role},
        "via": via,
        "presence": presence,
        "signature": "",
    }
    try:
        from .attestation_signer import sign_bundle, verify_bundle_signature
        sign_bundle(stmt)
        ok, why = verify_bundle_signature(dict(stmt))
        if not ok:
            logger.error("[CHATAPPROVAL] statement self-check failed for %s: %s", row.id, why)
            stmt["signature"] = None
            stmt["unsigned_reason"] = (f"The registry signed this decision but could not verify its own signature "
                                       f"({why}), so it is served unsigned.")
    except Exception as e:  # noqa: BLE001 — an unsigned statement says so; it never pretends
        logger.warning("[CHATAPPROVAL] signer unavailable for %s: %s", row.id, e)
        stmt["signature"] = None
        stmt["unsigned_reason"] = ("This registry could not reach its attestation signer, so the decision is "
                                   "recorded but not signed.")
    return stmt


def request_card(row: Any) -> dict:
    data: Dict[str, Any] = {
        "approval_id": row.id,
        "title": row.title,
        "expires_at": iso(row.expires_at),
        "production_impact": bool(row.production_impact),
        "requester_did": row.requester_agent_did,
    }
    for k in ("reason", "unlocks", "artifact_sha256", "artifact_label"):
        v = getattr(row, k, None)
        if v:
            data[k] = v if k != "reason" else str(v)[:REASON_MAX]
    return {"v": 1, "type": "approval.request", "data": data, "refs": {"approval_id": row.id}}


def decided_card(row: Any, statement: dict) -> dict:
    by = statement.get("decided_by") or {}
    data: Dict[str, Any] = {
        "approval_id": row.id,
        "decision": statement.get("decision"),
        "title": row.title,
        "decided_at": statement.get("decided_at"),
        "decided_by_developer_id": by.get("developer_id"),
        "decided_by_name": by.get("name"),
        "role": by.get("role"),
        "request_digest": row.facts_digest,
    }
    if row.artifact_sha256:
        data["artifact_sha256"] = row.artifact_sha256
    if getattr(row, "decision_note", None):
        data["note"] = row.decision_note
    refs: Dict[str, Any] = {"approval_id": row.id}
    if row.request_message_id:
        refs["request_message_id"] = row.request_message_id
    return {"v": 1, "type": "approval.decided", "data": data, "refs": refs}


def validate_card_data(ctype: str, data: dict) -> Optional[str]:
    """The two card types' shapes (their authority is that only this rail may post them at all)."""
    aid = data.get("approval_id")
    if not isinstance(aid, str) or not aid.startswith("apr_") or len(aid) > 44:
        return f"{ctype}: data.approval_id must name the approval record"
    title = data.get("title")
    if not isinstance(title, str) or not (1 <= len(title) <= TITLE_MAX):
        return f"{ctype}: data.title is required (1-{TITLE_MAX} chars)"
    sha = data.get("artifact_sha256")
    if sha is not None and (not isinstance(sha, str) or not _SHA256_RE.match(sha)):
        return f"{ctype}: data.artifact_sha256 must be 64 lowercase hexadecimal characters"
    if ctype == "approval.request":
        if not isinstance(data.get("expires_at"), str) or not data["expires_at"]:
            return "approval.request: data.expires_at is required"
    elif ctype == "approval.decided":
        if data.get("decision") not in ("approved", "denied"):
            return "approval.decided: data.decision must be approved or denied"
        if not isinstance(data.get("decided_by_developer_id"), int):
            return "approval.decided: data.decided_by_developer_id must name the developer who decided"
    return None


def via_record(*, api_key_id: Optional[int], api_key_scopes: Optional[List[str]], mcp_relay: bool,
               surface: Optional[str]) -> dict:
    """How a decision was made. The first two fields are attested by this registry; `surface` is what the client said
    about itself and is labelled so."""
    return {
        "credential": "api_key" if api_key_id is not None or api_key_scopes is not None else "session",
        "api_key_id": api_key_id,
        "api_key_scopes": list(api_key_scopes) if api_key_scopes is not None else None,
        "mcp_relay": bool(mcp_relay),
        "attested": ["credential", "api_key_id", "api_key_scopes", "mcp_relay"],
        "surface": (str(surface)[:40] if surface else None),
        "surface_is": "client_asserted",
    }


def serialize(row: Any, now: _dt.datetime, *, requester_name: Optional[str] = None,
              decider_name: Optional[str] = None, include_proof: bool = False) -> dict:
    st = effective_status(row.status, row.expires_at, now)
    out: Dict[str, Any] = {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "status": st,
        "title": row.title,
        "reason": row.reason,
        "unlocks": row.unlocks,
        "artifact_sha256": row.artifact_sha256,
        "artifact_label": row.artifact_label,
        "production_impact": bool(row.production_impact),
        "requester": {"agent_did": row.requester_agent_did, "name": requester_name or row.requester_agent_did},
        "created_at": iso(row.created_at),
        "expires_at": iso(row.expires_at),
        "request_message_id": row.request_message_id,
        "request_digest": row.facts_digest,
    }
    if st in ("approved", "denied"):
        out["decision"] = {
            "decision": st,
            "decided_at": iso(row.decided_at),
            "decided_by": {"developer_id": row.decided_by_developer_id, "name": decider_name,
                           "role": row.decided_by_role},
            "note": row.decision_note,
            "presence_method": row.presence_method,
            "what_it_proves": WHAT_IT_PROVES_PRESENCE if row.presence_method == "webauthn_uv"
            else WHAT_IT_PROVES_ACCOUNT,
        }
        if include_proof:
            out["decision"]["via"] = row.decision_via
            out["decision"]["presence_challenge_id"] = row.presence_challenge_id
            out["decision"]["statement"] = row.decision_statement
    if include_proof:
        out["facts"] = row.facts
    return out


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def db_now(db: AsyncSession) -> _dt.datetime:
    """The database's clock (constant inside one transaction), so expiry never depends on a worker's clock."""
    ts = (await db.execute(sa_text("SELECT now()"))).scalar_one()
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


async def org_facts(db: AsyncSession, org_id: str) -> Optional[dict]:
    row = (await db.execute(sa_text(
        "SELECT owner_id, chat_enabled, settings FROM organizations WHERE id = :o"), {"o": org_id})).first()
    if row is None:
        return None
    return {"owner_id": row[0], "chat_enabled": bool(row[1]) if row[1] is not None else True,
            "settings": row[2] if isinstance(row[2], dict) else {}}


async def decider_role(db: AsyncSession, org_id: str, developer_id: int,
                       owner_id: Optional[int] = None) -> Optional[str]:
    """`owner`, `approver` or None, read live: the org's owner (or a member holding the owner role), or an ACTIVE
    member the owner named an approver. An admin flag on the account grants nothing here."""
    if owner_id is not None and int(owner_id) == int(developer_id):
        return "owner"
    row = (await db.execute(sa_text(
        "SELECT role, can_approve FROM organization_members "
        "WHERE organization_id = :o AND developer_id = :d AND is_active = true LIMIT 1"),
        {"o": org_id, "d": int(developer_id)})).first()
    if row is None:
        return None
    if str(row[0] or "") == "owner":
        return "owner"
    if bool(row[1]):
        return "approver"
    return None


async def pending_count(db: AsyncSession, conversation_id: str, agent_did: str) -> int:
    return int((await db.execute(sa_text(
        "SELECT count(*) FROM chat_approvals WHERE conversation_id = :c AND requester_agent_did = :a "
        "AND status = 'pending' AND expires_at > now()"), {"c": conversation_id, "a": agent_did})).scalar_one())


async def by_client_ref(db: AsyncSession, agent_did: str, client_ref: str) -> Optional[ChatApproval]:
    return (await db.execute(select(ChatApproval).where(
        ChatApproval.requester_agent_did == agent_did,
        ChatApproval.client_ref == client_ref))).scalars().first()


async def fetch(db: AsyncSession, approval_id: str, *, fresh: bool = False) -> Optional[ChatApproval]:
    q = select(ChatApproval).where(ChatApproval.id == approval_id)
    if fresh:
        q = q.execution_options(populate_existing=True)
    return (await db.execute(q)).scalars().first()


async def list_for_conversation(db: AsyncSession, conversation_id: str, status: str = "pending",
                                limit: int = 50) -> List[ChatApproval]:
    q = select(ChatApproval).where(ChatApproval.conversation_id == conversation_id)
    if status == "pending":
        q = q.where(ChatApproval.status == "pending", ChatApproval.expires_at > sa_text("now()")).order_by(
            ChatApproval.created_at.asc())
    elif status == "decided":
        q = q.where(ChatApproval.status.in_(("approved", "denied"))).order_by(ChatApproval.decided_at.desc())
    else:
        q = q.order_by(ChatApproval.created_at.desc())
    return list((await db.execute(q.limit(max(1, min(int(limit or 50), 200))))).scalars().all())


async def names_for(db: AsyncSession, rows: Iterable[Any]) -> Tuple[Dict[str, str], Dict[int, str]]:
    """Display names: requesters by their agent card, deciders by their developer name."""
    from . import chat_service as cs
    rows = list(rows)
    agent_keys = [cs.principal_key("agent", r.requester_agent_did) for r in rows]
    dev_ids = sorted({int(r.decided_by_developer_id) for r in rows if r.decided_by_developer_id is not None})
    keys = agent_keys + [cs.principal_key("developer", d) for d in dev_ids]
    names = await cs.display_names(db, keys) if keys else {}
    agents = {r.requester_agent_did: names.get(cs.principal_key("agent", r.requester_agent_did), "") for r in rows}
    devs = {d: names.get(cs.principal_key("developer", d), "") for d in dev_ids}
    return agents, devs


async def wait_until_decided(db: AsyncSession, approval_id: str, wait_s: float) -> Optional[ChatApproval]:
    """Read the record again every ~1.5 s while it is pending, for at most `wait_s` (20) seconds. The transaction is
    ended between reads, so no pooled connection is held while nothing happens."""
    deadline = asyncio.get_event_loop().time() + max(0.0, min(float(wait_s), WAIT_MAX_S))
    row = await fetch(db, approval_id, fresh=True)
    while row is not None:
        now = await db_now(db)
        if effective_status(row.status, row.expires_at, now) != "pending":
            return row
        left = deadline - asyncio.get_event_loop().time()
        if left <= 0:
            return row
        await db.rollback()
        await asyncio.sleep(min(WAIT_STEP_S, left))
        row = await fetch(db, approval_id, fresh=True)
    return row


# ---------------------------------------------------------------------------
# Presence (only when the registry or the org switched it on)
# ---------------------------------------------------------------------------

async def require_device_presence(db: AsyncSession, developer: Any, *, decision: str, rows: Sequence[Any],
                                  conversation_id: str, challenge_id: Optional[str]) -> dict:
    """A user-verified device signature for this decision, through the existing step-up rail, or a refusal.

    The rail's own `stepup.require` passes on the password alone when an account has no factor and accepts an
    authenticator code; both are what a presence switch exists to rule out, so this asks for exactly one thing: a
    challenge approved on an enrolled device with user verification (`webauthn_uv`, recorded by the approve route).
    A challenge answered any other way is refused WITHOUT being spent (single-use binds answers, not refusals) and a
    fresh one is minted. No device enrolled = 403 by name; the decider can still deny, which never asks.

    ⚠ The strength of this rests on how a device is enrolled: see the security-sensitive backlog entry filed with
    this rail before the switch is turned on anywhere."""
    from .. import models
    from . import stepup
    from .governance_presence import announce_challenge
    if len(rows) > PRESENCE_BATCH_MAX:
        raise ApprovalError(422, f"a decision that needs presence covers at most {PRESENCE_BATCH_MAX} requests; "
                                 "decide them in smaller groups")
    factors = await stepup.available_factors(db, developer)
    if not factors["device"]:
        raise ApprovalError(403, "device_required: this decision needs a fingerprint on an enrolled phone, and this "
                                 "account has no enrolled device. Enroll one (Pocket, Approvals), or ask the owner "
                                 "to lower chat_approvals.presence. Denying never asks.")
    action_ref = action_ref_for(decision, [r.id for r in rows], conversation_id)
    reason = "presence required"
    if challenge_id:
        ch = await db.get(models.LiabilityChallenge, challenge_id)
        if ch is None or ch.developer_id != developer.id:
            reason = "challenge not found"
        elif ch.action_type != ACTION_TYPE or (ch.action_ref or "") != action_ref:
            reason = "the challenge was minted for a different decision"
        elif ch.status == "approved" and ch.method != "webauthn_uv":
            reason = (f"the challenge was answered with {ch.method or 'an unknown method'}; this decision needs an "
                      "enrolled device with user verification")
        else:
            ok, why = await stepup.consume_approved(db, developer, challenge_id, action_type=ACTION_TYPE,
                                                    action_ref=action_ref)
            if ok:
                return {"method": "webauthn_uv", "challenge_id": ch.id, "challenge_hash": ch.challenge_hash,
                        "nonce": ch.nonce, "device_id": ch.device_id, "signature": ch.signature,
                        "facts": ch.facts}
            reason = why
    ch = await stepup.mint_challenge(db, developer, action_type=ACTION_TYPE, action_ref=action_ref,
                                     facts=challenge_facts(decision, rows, conversation_id))
    await db.commit()   # the phone must find the row the cue names
    title = rows[0].title if len(rows) == 1 else f"{len(rows)} approval requests"
    await announce_challenge(int(developer.id), ch.id, action_type=ACTION_TYPE,
                             title="Confirm an approval", message=f"{decision.capitalize()}: {title}"[:180])
    raise ApprovalError(428, "step_up_required", body={
        "error": "step_up_required",
        "message": "Confirm this decision on your phone (Pocket, Approvals), then send it again with challenge_id.",
        "reason": reason,
        "step_up": {
            "challenge_id": ch.id, "challenge_hash": ch.challenge_hash, "facts": ch.facts,
            "expires_at": iso(ch.expires_at), "ttl_seconds": stepup.CHALLENGE_TTL_SECONDS,
            "methods": ["device"],
            "how": "Approve it on your phone (Pocket, Approvals), then resend this decision with challenge_id.",
        },
    })
