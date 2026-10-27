"""COCKPIT CARD core (L1, 2026-07-25) — liable hybrid identity: dev ∘ agent.

SPEC: sessionlogs2026/SPEC_2026-07-25_LIABLE_IDENTITY_COCKPIT_CARD.md

The one rule everything hangs off (the issuer-current clamp, same shape that makes IRONKEY L4
capability tokens safe — resolve_capability = caveats ∩ ISSUER-CURRENT authority):

    effective = agent_own_rbac ∪ ( delegated(dev) ∩ dev_authority_now ∩ mandate.scope )
                ∩ att_ caveats ∩ mandate.limits

Re-derived EVERY request, never snapshotted into power. This module owns the mandate side:
`dev_authority_now`, the dev-RBAC → delegatable-permission map, scope validation at issue,
canonical hashing, the per-mandate evidence hash chain, and the presence rail (TOTP live;
phone-enclave ES256 verify ready for the Pocket key enrolment).

Deny-only + pre-escrow → Δ-irrelevant. All writes ride the caller's session/txn.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# §1.1 dev-RBAC → delegatable agent permissions (narrow, explicit — the whole map)
# ---------------------------------------------------------------------------
# Base = what ANY developer in good standing may underwrite (no admin flag needed).
DELEGATABLE_BASE: frozenset[str] = frozenset({
    "contracts.engage", "disputes.file", "a2a.pay", "reputation.signal",
})
# Each dev-RBAC flag unlocks a narrow slice of delegatable authority.
DELEGATABLE_MAP: dict[str, frozenset[str]] = {
    "admin_treasury":    frozenset({"teg.transfer", "teg.transfer_xreg", "teg.system_transfer"}),
    "admin_enforcement": frozenset({"enforcement.act", "disputes.rule"}),
    "admin_federation":  frozenset({"federation.manage"}),
    "admin_platform":    frozenset({"cicd.deploy", "bundle.write"}),
    "admin_support":     frozenset({"support.act"}),
}
# A mandate is for DOING WORK, never for handing out authority — these never delegate.
NON_DELEGATABLE: frozenset[str] = frozenset({"authz.delegate", "contract.template.publish"})

_ADMIN_FLAGS = ("admin_treasury", "admin_support", "admin_enforcement", "admin_federation", "admin_platform")


def dev_authority_now(dev) -> tuple[set[str], list[str]]:
    """The developer's LIVE standing authority → (flag set, deny reasons).

    Suspension / deletion empties authority entirely (the liability rail inherits AL-2/AL-3
    for free). Reasons are returned so verify can be ledger-truthful, not just boolean.
    """
    reasons: list[str] = []
    if dev is None:
        return set(), ["dev_not_found"]
    if getattr(dev, "is_suspended", False):
        reasons.append("dev_suspended")
    if getattr(dev, "deleted_at", None) is not None or getattr(dev, "deletion_status", None) in ("pending", "deleted"):
        reasons.append("dev_deleted")
    if reasons:
        return set(), reasons
    flags = {f for f in _ADMIN_FLAGS if getattr(dev, f, False)}
    if getattr(dev, "is_admin", False):
        flags.add("is_admin")
        flags.update(_ADMIN_FLAGS)  # superflag carries every sub-flag (require_admin_flag semantics)
    return flags, reasons


def delegatable_for(flags: set[str]) -> set[str]:
    """Everything this flag set may underwrite (base + per-flag slices, minus NON_DELEGATABLE)."""
    out = set(DELEGATABLE_BASE)
    for f in flags:
        out |= DELEGATABLE_MAP.get(f, frozenset())
    return out - NON_DELEGATABLE


def validate_scope(scope: list[str], flags: set[str]) -> list[str]:
    """Scope requested at issue must be ⊆ what the human actually holds — we never store a lie.
    Returns the list of offending permissions (empty = valid)."""
    allowed = delegatable_for(flags)
    return sorted(set(scope) - allowed)


# ---------------------------------------------------------------------------
# Canonical hashing + evidence chain
# ---------------------------------------------------------------------------
def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def mandate_content_hash(*, mandate_id: str, developer_id: int, agent_did: str, tier: str,
                         scope: list[str], limits: Optional[dict], authority_snapshot: dict,
                         presence_method: str, issued_at: str, expires_at: Optional[str]) -> str:
    return sha256_hex(canonical({
        "id": mandate_id, "developer_id": developer_id, "agent_did": agent_did, "tier": tier,
        "scope": sorted(scope), "limits": limits or {}, "authority_snapshot": authority_snapshot,
        "presence_method": presence_method, "issued_at": issued_at, "expires_at": expires_at,
    }))


async def append_evidence(db: AsyncSession, mandate_id: str, event_type: str, payload: dict, *,
                          action_ref: Optional[str] = None,
                          authority_snapshot: Optional[dict] = None,
                          presence: Optional[dict] = None) -> dict:
    """Append one link to the mandate's hash chain (same txn as the caller — an evidence row
    commits atomically with the action it records). UNIQUE(mandate_id, seq) is the race guard;
    one retry re-reads the head on collision.

    §DISCREFINE (mig 0154): a step-up challenge has no mandate behind it, so there is
    no chain to extend. Guarded HERE rather than at each call site — the four callers
    in routers/liability.py all mean the same thing by it, and a fifth would forget."""
    if not mandate_id:
        return {"skipped": "no mandate chain for this action"}
    for attempt in (1, 2):
        row = (await db.execute(text(
            "SELECT seq, chain_hash FROM liability_evidence WHERE mandate_id = :m ORDER BY seq DESC LIMIT 1"
        ), {"m": mandate_id})).first()
        seq = (row[0] + 1) if row else 0
        prev = row[1] if row else ""
        digest = sha256_hex(canonical({
            "mandate_id": mandate_id, "seq": seq, "event_type": event_type,
            "action_ref": action_ref, "payload": payload,
            "authority_snapshot": authority_snapshot, "presence": presence,
        }))
        chain = sha256_hex(prev + digest)
        try:
            await db.execute(text("""
                INSERT INTO liability_evidence
                    (mandate_id, seq, event_type, action_ref, payload, authority_snapshot, presence,
                     digest, prev_hash, chain_hash)
                VALUES (:m, :s, :e, :a, CAST(:p AS JSONB), CAST(:snap AS JSONB), CAST(:pr AS JSONB),
                        :d, :ph, :ch)
            """), {"m": mandate_id, "s": seq, "e": event_type, "a": action_ref,
                   "p": json.dumps(payload), "snap": json.dumps(authority_snapshot) if authority_snapshot else None,
                   "pr": json.dumps(presence) if presence else None,
                   "d": digest, "ph": prev, "ch": chain})
            return {"seq": seq, "digest": digest, "chain_hash": chain}
        except Exception:
            if attempt == 2:
                raise
            # concurrent append won the seq — re-read the head once
    raise RuntimeError("unreachable")


async def verify_chain(db: AsyncSession, mandate_id: str) -> tuple[bool, Optional[int]]:
    """Recompute the whole chain. Returns (ok, first_broken_seq)."""
    rows = (await db.execute(text("""
        SELECT seq, event_type, action_ref, payload, authority_snapshot, presence,
               digest, prev_hash, chain_hash
        FROM liability_evidence WHERE mandate_id = :m ORDER BY seq ASC
    """), {"m": mandate_id})).mappings().all()
    prev = ""
    for r in rows:
        digest = sha256_hex(canonical({
            "mandate_id": mandate_id, "seq": r["seq"], "event_type": r["event_type"],
            "action_ref": r["action_ref"], "payload": r["payload"],
            "authority_snapshot": r["authority_snapshot"], "presence": r["presence"],
        }))
        if digest != r["digest"] or r["prev_hash"] != prev or sha256_hex(prev + digest) != r["chain_hash"]:
            return False, r["seq"]
        prev = r["chain_hash"]
    return True, None


# ---------------------------------------------------------------------------
# The clamp — mandate-side resolution (agent-own union happens at the gate)
# ---------------------------------------------------------------------------
async def resolve_mandate(db: AsyncSession, mandate, dev) -> dict:
    """Re-derive what this mandate conveys RIGHT NOW. Never trusts stored snapshots.

    Returns {valid, effective_scope, reasons, authority_now} — reasons are cumulative and
    ledger-truthful (a revoked mandate on a suspended dev reports both)."""
    reasons: list[str] = []
    now = datetime.datetime.now(datetime.timezone.utc)
    if mandate.status == "revoked":
        reasons.append("mandate_revoked")
    elif mandate.status == "expired":
        reasons.append("mandate_expired")
    if mandate.expires_at is not None and mandate.expires_at <= now:
        if "mandate_expired" not in reasons:
            reasons.append("mandate_expired")
    flags, dev_reasons = dev_authority_now(dev)
    reasons.extend(dev_reasons)
    effective = sorted(set(mandate.scope or []) & delegatable_for(flags)) if not dev_reasons else []
    if not effective and not reasons:
        reasons.append("scope_empty_now")  # flags withdrawn since issue — clamp did its job
    return {
        "valid": (not reasons) and bool(effective),
        "effective_scope": effective if not reasons else [],
        "reasons": reasons,
        "authority_now": sorted(flags),
    }


# ---------------------------------------------------------------------------
# Presence rail — TOTP (live) + phone-enclave ES256 (verify-ready)
# ---------------------------------------------------------------------------
def verify_totp_for_dev(dev, code: str) -> bool:
    """Reuse the EXISTING 2FA rail (Fernet-at-rest transparent via decrypt_secret fallback)."""
    if not getattr(dev, "totp_secret", None) or not code:
        return False
    try:
        from agentvault_registry.services.two_factor_auth import TwoFactorAuthService
        secret = TwoFactorAuthService.decrypt_secret(dev.totp_secret, os.getenv("TWO_FACTOR_ENCRYPTION_KEY", ""))
        return TwoFactorAuthService.verify_token(secret, code)
    except Exception:
        logger.warning("[LIABILITY] TOTP verify errored for dev %s", getattr(dev, "id", "?"), exc_info=True)
        return False


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def verify_es256_signature(pubkey_jwk: dict, challenge_hash_hex: str, signature_b64url: str) -> bool:
    """Verify a phone-enclave ES256 signature over the RAW challenge_hash bytes.

    Accepts raw 64-byte r||s (WebCrypto/StrongBox default) or DER. The phone signs
    sha256-of-facts — proof of THIS human, on THIS enrolled device, for THIS exact action."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        from cryptography.hazmat.primitives import hashes
        if not pubkey_jwk or pubkey_jwk.get("kty") != "EC" or pubkey_jwk.get("crv") != "P-256":
            return False
        x = int.from_bytes(_b64url_decode(pubkey_jwk["x"]), "big")
        y = int.from_bytes(_b64url_decode(pubkey_jwk["y"]), "big")
        pub = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        sig = _b64url_decode(signature_b64url)
        if len(sig) == 64:  # raw r||s (WebCrypto/StrongBox default) → DER
            sig = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        # WIRE CONTRACT: the device signs the 32-byte challenge hash AS A MESSAGE — i.e. the
        # signature is over SHA-256(challenge_hash_bytes). NOT Prehashed: every real client-side
        # keystore (WebCrypto `ECDSA`+`SHA-256`, iOS Secure Enclave
        # `ecdsaSignatureMessageX962SHA256`, Android StrongBox `SHA256withECDSA`) hashes the input
        # internally and none of them expose a prehashed mode. An earlier Prehashed version here
        # verified only against a test signer that made the same assumption — it would have
        # rejected every genuine phone signature.
        pub.verify(sig, bytes.fromhex(challenge_hash_hex), ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_from_hex(hex_str: str) -> str:
    """The WebAuthn challenge is the challenge hash BYTES, so the browser echoes it back
    base64url-encoded in clientDataJSON — compare in that encoding, not in hex."""
    return b64u(bytes.fromhex(hex_str))


def challenge_hash_for(facts: dict, nonce: str) -> str:
    """sha256(canonical(facts) || nonce) — a signature can never be replayed onto a different
    action, and the server refuses any summary it didn't generate."""
    return sha256_hex(canonical(facts) + nonce)


# ---------------------------------------------------------------------------
# §SUBAGENT-LIABILITY (2026-08-13) — "hands, not persons"
#   A sub-agent spawned WALLETLESS (§SPAWN-ANCHOR) is a HAND: it owns no money and is a party to
#   nothing; its spend/contract walks up to the wallet-holding PRINCIPAL. The principal (and the
#   human whose mandate underwrites it) is the party of record for money, outcome and liability.
#   The hand's DID is EVIDENCE (which hand acted → the principal traces it, cuts it off), never a
#   defendant. P0 = record that attribution on live traffic; no behaviour change.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# §FACTS2 (2026-08-31) — a fact that names its own unit and its own counterparty
# ---------------------------------------------------------------------------
_UNSET: Any = object()   # "the caller did not say" — distinct from "there is none"


def frame_currency() -> str:
    """This frame's settlement currency — the SAME env the registry card, the FX desk
    and the flare shop read (`FRAME_CURRENCY`; A/B = AVT, C = BVT).

    ⚠ This is only ever a FALLBACK. Where the action has its own denominated record —
    a contract row carries a `currency` column — that record wins, because §FOREIGNACT's
    law is that a label must come from the same place the number does. The frame's
    currency is the right answer for a local action and the WRONG one for a cross-frame
    contract settled in the counterparty's unit.
    """
    import os as _os
    return (_os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"


def money_str(amount: Any) -> Optional[str]:
    """The amount, as the exact string a human is asked to underwrite.

    🔴 NOT `str(float(x))`. Two ways that lies about money, both live here:
      * it DROPS SIGNIFICANT ZEROS — "42.50" becomes "42.5", so the record stops
        saying what the contract said;
      * it goes EXPONENTIAL at scale — this fleet already returns balances as
        "1E+3", and a confirm screen reading "1E+3" is not a confirm screen.
    `Decimal(str(x))` keeps the caller's own precision (never the binary expansion
    `Decimal(float)` would give), and `:f` guarantees positional notation at any
    magnitude.

    ⚠ What this canNOT fix, and does not pretend to: a caller that hands over a
    FLOAT has already lost the distinction — `0.1 + 0.2` is `0.30000000000000004`
    before this function ever sees it. The real protection is upstream, and it is
    why the three call sites now pass the Decimal straight from the row (or the int
    straight from the request) instead of wrapping it in `float()` first.
    """
    if amount is None:
        return None
    from decimal import Decimal, InvalidOperation
    try:
        d = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        return f"{d:f}"
    except (InvalidOperation, ValueError, TypeError):
        return str(amount)


def build_facts_v2(*, verb: str, action_ref: Optional[str], mandate_id: str, agent_did: str,
                   amount: Any = None, currency: Optional[str] = None,
                   counterparty_did: Any = _UNSET,
                   counterparty_home_registry: Optional[str] = None,
                   auto_stepped_up: bool = False,
                   extra: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
    """The ONE builder for challenge facts. Returns (facts, refusal_reason).

    v1 facts said `{"action_type", "action_ref", "mandate_id", "agent_did", "amount"}` —
    an amount with **no unit and no counterparty**. A human confirming "42.50" was being
    asked to underwrite a number whose currency the record did not contain, which is the
    §FOREIGNACT failure in the one place it matters most: the Commander staked "1.337"
    believing BVT and locked 1337 AVT, ledgers perfect and label lying.

    I11 — A MONEY FACT MUST NAME ITS UNIT. When `amount` is present and no currency can
    be established, this REFUSES to build rather than guessing the frame's. A challenge
    that cannot say what it is denominated in is not a challenge worth signing.

    The counterparty is recorded as `_UNSET` vs `None` deliberately: "the caller forgot"
    and "this action genuinely has no counterparty yet" are different facts, and only the
    first is a bug. Contract CREATE really has no counterparty — the work is being posted,
    nobody has accepted — so it passes None explicitly and the fact says so. A future call
    site that simply forgets is refused, loudly.
    """
    if amount is not None and not (currency or "").strip():
        return None, "facts_v2_missing_currency"
    if amount is not None and counterparty_did is _UNSET:
        return None, "facts_v2_counterparty_undeclared"
    facts = {
        "schema": "facts.v2",
        "verb": verb,
        "action_ref": action_ref,
        "mandate_id": mandate_id,
        "agent_did": agent_did,
        "amount": money_str(amount),
        "currency": (currency or "").strip().upper() or None,
        "counterparty_did": None if counterparty_did is _UNSET else counterparty_did,
        "counterparty_home_registry": counterparty_home_registry or None,
        "auto_stepped_up": bool(auto_stepped_up),
        # kept so every existing renderer that reads `action_type` keeps working; `verb`
        # is the v2 name and they are always the same string.
        "action_type": verb,
    }
    if extra:
        for k, v in extra.items():
            facts.setdefault(k, v)
    return facts, None


# ---------------------------------------------------------------------------
# §POSTURE (P4) — "are these the same facts the human already read?"
# ---------------------------------------------------------------------------
# The R9 read-floor rule needs one question answered honestly: does a pre-flight
# preview show the SAME thing the challenge is about to ask? Comparing whole facts
# blobs would answer "no" forever, because a preview is by construction not
# auto-stepped-up and carries no mandate-side provenance — an always-false predicate
# is the unsatisfiable-gate class, a feature that looks shipped and is inert.
#
# So the comparison is over the fields a human actually READS and could be harmed by
# a change in. `auto_stepped_up` and `schema` are provenance, not content; `verb` and
# `action_type` are the same string by construction, so only one is compared.
_COMPARABLE_FACT_KEYS = (
    "verb", "action_ref", "mandate_id", "agent_did",
    "amount", "currency", "counterparty_did", "counterparty_home_registry",
)


def facts_comparable(facts: Optional[dict]) -> dict:
    """The subset of a facts blob that a divergence must be measured over."""
    f = facts or {}
    out = {}
    for k in _COMPARABLE_FACT_KEYS:
        v = f.get(k)
        if k == "verb" and v is None:
            v = f.get("action_type")   # v1 blobs only ever carried action_type
        out[k] = v
    return out


def facts_comparable_digest(facts: Optional[dict]) -> str:
    """sha256 over the comparable subset — the join key for "same thing"."""
    return sha256_hex(canonical(facts_comparable(facts)))


def facts_diff(a: Optional[dict], b: Optional[dict]) -> dict:
    """Field-wise divergence between two facts blobs, over the comparable subset.

    Returns {} when they say the same thing. The SHAPE is deliberately
    {field: {"was": ..., "now": ...}} because this is also what P8's pre-flight diff
    renders — one function, two readers, so the refusal and the UI can never disagree
    about what changed.
    """
    ca, cb = facts_comparable(a), facts_comparable(b)
    return {k: {"was": ca[k], "now": cb[k]} for k in _COMPARABLE_FACT_KEYS if ca[k] != cb[k]}


# ---------------------------------------------------------------------------
# §CEILING (P7) — standing consent, and what it is allowed to cover
# ---------------------------------------------------------------------------
def _dec(v, default=None):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return default


def ceiling_of(limits: Optional[dict]) -> Optional[dict]:
    """The `auto_ceiling` block on a mandate's limits, or None."""
    if not isinstance(limits, dict):
        return None
    c = limits.get("auto_ceiling")
    return c if isinstance(c, dict) else None


def ceiling_covers(limits: Optional[dict], *, needed: str, amount: Any, currency: Optional[str],
                   posture: Optional[dict] = None, org_settings: Optional[dict] = None,
                   now: Optional[datetime.datetime] = None) -> tuple[bool, str]:
    """Does a live standing consent already cover THIS action? Returns (covered, why).

    `why` is always populated, because the receipt records it either way: a ceiling that
    covered an action has to say which one, and a ceiling that did NOT has to say what
    stopped it. §6d / I6 — a ceiling turns questions into RECEIPTS, never into silence.

    🔴 Re-derived on every call, never trusted from a snapshot (the §ORGLIFE law). All
    four of these can change under a standing consent that was perfectly valid when it
    was granted, and each one has to bite on the very next request:
      · the human let it decay;
      · the org lowered its cap below what was granted;
      · the org switched standing consent off entirely;
      · the deployment moved to `hardened`, where every action asks.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    c = ceiling_of(limits)
    if not c:
        return False, "no_ceiling"
    # The posture wins over anything an individual granted: `hardened` means every
    # action asks, so a ceiling granted under a looser posture stops covering the
    # moment the org tightens — without anyone having to go and revoke it.
    if posture is not None and not posture.get("ceilings", True):
        return False, "ceilings_off_by_posture"
    org = org_settings if isinstance(org_settings, dict) else {}
    if org.get("cockpit_ceilings_enabled") is False:
        return False, "ceilings_off_by_org"
    if (c.get("scope") or "") != needed:
        return False, f"scope_mismatch:{c.get('scope')}"
    if (c.get("currency") or "").upper() != (currency or "").upper():
        # §FOREIGNACT: a ceiling granted in BVT must not silently cover an action
        # denominated in something else. Same number, different money.
        return False, f"currency_mismatch:{c.get('currency')}"
    decays = c.get("decays_at")
    if not decays:
        return False, "no_decay"          # a ceiling with no end is not a ceiling
    try:
        dt = datetime.datetime.fromisoformat(str(decays).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return False, "bad_decay"
    if dt <= now:
        # Decayed ceilings are ignored AT READ TIME. Correctness never depends on a
        # sweeper having run; the panes render the decay state so it is visible too.
        return False, "decayed"
    cap = _dec(c.get("max_per_tx"))
    amt = _dec(amount)
    if cap is None or amt is None:
        return False, "unparseable"
    org_cap = _dec(org.get("cockpit_ceiling_max_amount")) if org.get("cockpit_ceiling_max_amount") else None
    if org_cap is not None and org_cap > 0 and cap > org_cap:
        # D7 — the org caps the ceiling. Enforced at USE as well as at grant, so
        # lowering the org cap immediately shrinks every standing consent under it
        # rather than waiting for someone to re-grant.
        cap = org_cap
    if amt > cap:
        return False, f"above_ceiling:{cap:f}"
    return True, f"covered_by_ceiling:{cap:f}"


async def presence_state(dev_id: Any) -> str:
    """`present` | `absent` | `unknown` — three states, deliberately.

    🔴 `ws_manager.is_present()` answers a BOOLEAN and folds "nobody is there" together
    with "I could not tell". That is the safe direction for a notification (when in
    doubt, send it) and the WRONG one for a gate: D5 refuses an agent because no human
    is watching, so a Redis outage would turn every gated action into `human_away` and
    the rail would refuse everything while looking like policy.
    Unknown therefore falls back to today's behaviour — raise the ask — because being
    unable to see the human is not evidence that the human is gone.

    The key comes from `ws_manager` rather than being re-spelled here: two definitions
    of `presence:ws:{id}` is the §ORGLEAK class waiting to happen.
    """
    try:
        # ⚠ `manager`, NOT `ws_manager`. There is no `ws_manager` in that module and never
        # was (routers/websocket.py:622 defines `manager`), so this import raised
        # ImportError, fell into the except below, and returned "unknown" — FOREVER.
        # And "unknown" deliberately does not refuse, so the D5 presence gate was dead on
        # arrival while behaving exactly like correct policy: nothing errored, nothing
        # logged, every action simply took the ordinary path. Found only by a battery that
        # exercised the rail. A three-state function whose failure state is the permissive
        # one MUST be proven to reach the other two.
        from agentvault_registry.routers.websocket import manager as _ws
        if str(dev_id) in getattr(_ws, "active_connections", {}):
            return "present"                    # this worker holds the socket: certain
        r = await _ws._get_redis()
        if r is None:
            return "unknown"
        return "present" if await r.exists(_ws._presence_key(str(dev_id))) else "absent"
    except Exception:  # noqa: BLE001
        return "unknown"


def presence_threshold() -> float:
    """Amount at/above which a dispute-bearing or over-leash HAND action steps up to presence.
    0 = disabled (default, byte-inert)."""
    from agentvault_registry.config import settings as _settings
    try:
        return float(getattr(_settings, "LIABILITY_PRESENCE_THRESHOLD_AVT", 0.0) or 0.0)
    except Exception:
        return 0.0


async def record_hand_action(db: AsyncSession, *, principal_did: str, hand_did: str,
                             action: str, action_ref: Optional[str] = None) -> None:
    """P0 — a walletless HAND acted; the PRINCIPAL (wallet-holder) is the party of record.

    Byte-cheap, gated by LIABILITY_MODE, and structurally UNABLE to harm the money leg it records:
      * always logs the attribution (the shadow proof on live traffic);
      * only when the principal carries a live signed mandate does it append a `hand_action` link
        to that mandate's evidence chain, and it does so inside a SAVEPOINT so an evidence failure
        rolls back JUST the savepoint — the caller's transaction (the actual spend/escrow) is never
        poisoned;
      * never raises.

    Called from the ONE money-leg seam that already knows a redirect happened
    (``spawn_anchor.resolve_spend_purse_agent``), so every anchored-hand spend is attributed with
    zero handler edits."""
    try:
        from agentvault_registry.config import settings as _settings
        mode = (getattr(_settings, "LIABILITY_MODE", "off") or "off").lower()
        if mode not in ("shadow", "enforce"):
            return
        logger.info("[LIABILITY-%s] hand_action principal=%s hand=%s action=%s ref=%s",
                    mode.upper(), principal_did, hand_did, action, action_ref)
        mrow = (await db.execute(text(
            "SELECT id FROM liability_mandates WHERE agent_did = CAST(:a AS VARCHAR) "
            "AND status = 'signed' ORDER BY issued_at DESC LIMIT 1"), {"a": principal_did})).first()
        if not mrow:
            return  # principal not under-written → the log line is the whole record in shadow
        mid = mrow[0]
        try:
            async with db.begin_nested():  # SAVEPOINT — isolate the evidence write from the money leg
                await append_evidence(db, mid, "hand_action",
                                      {"hand": hand_did, "action": action},
                                      action_ref=action_ref)
        except Exception:
            logger.warning("[LIABILITY] hand_action evidence append failed principal=%s (isolated, "
                           "money leg unaffected)", principal_did, exc_info=True)
    except Exception:
        logger.warning("[LIABILITY] record_hand_action non-fatal error", exc_info=True)


# ---------------------------------------------------------------------------
# §PROOFBIND (2026-08-31) — what a presence proof is allowed to be
# ---------------------------------------------------------------------------
# 🔴 WHAT THIS REPLACED, AND WHY IT HAD TO GO.
#
# The previous `_presence_ok()` verified the enclave branch using the public key,
# the facts and the nonce **taken from the proof the caller supplied**:
#
#     facts, nonce = presence["facts"], presence["nonce"]
#     pubkey, sig  = presence["pubkey_jwk"], presence["signature"]
#     return verify_es256_signature(pubkey, challenge_hash_for(facts, nonce), sig)
#
# It never checked that the key belonged to an enrolled, unrevoked device of that
# developer, and never checked that the facts matched the challenge or the action
# being gated. The party that sets `X-Presence-Proof` is the ACTING AGENT — the very
# party the step-up exists to interpose a human in front of — so an agent could mint
# a keypair, sign facts it chose, and be recorded as a present human. Proven in
# `scratchpad/cockpit/probe_p0_proofbind.py`: a wholly attacker-generated proof over
# a fabricated mandate and amount 999999 was ACCEPTED, with controls showing the
# verifier does reject a corrupted signature and a bogus TOTP.
#
# It had never bitten because `needs_presence` requires a positive threshold and
# `LIABILITY_PRESENCE_THRESHOLD_AVT` was 0 on all 16 nodes, so the branch was
# unreachable. §COCKPIT P6 lifts that threshold, which is exactly what would have
# made it live: `gate_pass` evidence stamped `presence_stepped_up: true` for a human
# who was never asked.
#
# THE NEW RULE — one shape, and the server owns every part of it:
#
#     X-Presence-Proof: {"method": "challenge", "challenge_id": "lch_…"}
#
# The gate does not verify signatures at all any more. It verifies that a challenge
# WAS APPROVED through `POST /liability/challenges/{id}/approve`, which already does
# the work properly: it loads the enrolled `device_push_registrations` row, refuses a
# revoked key, requires the WebAuthn UV bit, watches sign-count regression, and
# verifies against the SERVER's stored `challenge_hash`. One rail, one truth
# (strategy §15.5) — rather than a second, weaker copy of presence verification
# living in the gate where nothing audits it.
#
# The citation is bound on five axes, all server-side:
#   owner      — the challenge belongs to this developer
#   mandate    — …and to the mandate that underwrites this agent
#   action     — …and to THIS action_ref, so an approval for one milestone cannot
#                release another
#   state      — …and it is `approved`, not pending/denied/expired
#   exactly-once — …and no earlier `gate_pass` already spent it. That is enforced by
#                reading the evidence chain rather than by a new column: the chain is
#                already the record, and a receipt that says which approval paid for
#                it is worth more than a boolean.
#
# TOTP and raw enclave signatures are NO LONGER accepted here. Both still work — as
# methods on `approve_challenge`, where they are verified against enrolled material.
# A TOTP code proves a human is present SOMEWHERE; it does not say what they agreed
# to. Under a live threshold that is precisely the "authorised something other than
# what they read" failure this whole rail exists to prevent.
#
# ⚠ Nothing live sent the old shapes: a tree-wide grep found the header only in
# scratchpad probes, planning docs, and `admin_jurisdiction.py`, which merely NOTES
# its presence without verifying it. So this narrows what passes and breaks nothing.

_PRESENCE_SHAPE_HINT = (
    'X-Presence-Proof: {"method":"challenge","challenge_id":"<id>"} — approve the '
    'challenge first via POST /api/v1/liability/challenges/{id}/approve'
)


async def verify_presence_citation(db: AsyncSession, dev, presence: Optional[dict], *,
                                   mandate_id: str, action_ref: Optional[str]
                                   ) -> tuple[bool, Optional[str], str]:
    """Is this proof a valid, unspent citation of an approved challenge for THIS action?

    Returns (ok, challenge_id, reason). `reason` is always populated so the denial can
    say which axis failed — a 403 that cannot explain itself trains people to retry
    blindly. Never raises: a malformed proof is a denial, not a 500.
    """
    if dev is None:
        return False, None, "no_developer"
    if not presence or not isinstance(presence, dict):
        return False, None, "no_presence_proof"
    method = (presence.get("method") or "").lower()
    if method in ("totp", "enclave"):
        # Named explicitly rather than falling through to "unknown method": whoever
        # sends these is following the old, unbound contract and deserves to be told
        # where the rail moved.
        return False, None, f"method_retired:{method}"
    if method != "challenge":
        return False, None, f"unsupported_method:{method or 'none'}"
    chid = (presence.get("challenge_id") or "").strip()
    if not chid:
        return False, None, "no_challenge_id"

    row = (await db.execute(text(
        "SELECT id, mandate_id, developer_id, action_ref, status, method, device_id "
        "FROM liability_challenges WHERE id = :c LIMIT 1"), {"c": chid})).mappings().first()
    if not row:
        return False, None, "challenge_not_found"
    if int(row["developer_id"]) != int(getattr(dev, "id", -1)):
        # Same answer as "not found" would be safer against enumeration, but this is
        # a developer citing their OWN mandate's challenge; naming the axis is worth
        # more here than hiding the existence of an id the caller already guessed.
        return False, None, "challenge_not_yours"
    if row["mandate_id"] != mandate_id:
        return False, None, "challenge_other_mandate"
    if (row["action_ref"] or None) != (action_ref or None):
        return False, None, "challenge_other_action"
    if row["status"] != "approved":
        return False, None, f"challenge_{row['status']}"

    # exactly-once, read off the chain that already exists
    spent = (await db.execute(text(
        "SELECT 1 FROM liability_evidence WHERE mandate_id = :m "
        "AND event_type = 'gate_pass' AND payload->>'presence_challenge_id' = :c LIMIT 1"),
        {"m": mandate_id, "c": chid})).first()
    if spent:
        return False, chid, "challenge_already_spent"
    return True, chid, f"approved:{row['method'] or 'unknown'}"


def presence_from_request(request) -> Optional[dict]:
    """Extract an optional per-action presence proof from `X-Presence-Proof: <json>`. Returns None
    when absent/unparseable — the gate treats None as 'no proof' (a denial only when a step-up is
    actually required). Never raises."""
    try:
        raw = request.headers.get("X-Presence-Proof") if request is not None else None
        if not raw:
            return None
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The gate — first consumers: contracts_v2 money actions (shadow-safe)
# ---------------------------------------------------------------------------
async def check_liability_gate(db: AsyncSession, agent_did: str, needed: str, *,
                               action_ref: Optional[str] = None,
                               amount: Any = None,
                               currency: Optional[str] = None,
                               counterparty_did: Any = _UNSET,
                               counterparty_home_registry: Optional[str] = None,
                               acting_hand_did: Optional[str] = None,
                               presence: Optional[dict] = None) -> None:
    """Registry-policy gate: when LIABILITY_MODE=enforce, an agent performing a gated action
    must be underwritten by a live mandate whose CURRENT effective scope covers `needed`.
    shadow → [LIABILITY-SHADOW] log line only (byte-cheap); off → no-op.

    Call BEFORE the caller's state claim: enforce-block raises 403 with its evidence committed;
    enforce-pass evidence rides the caller's own commit (atomic with the action it records)."""
    from agentvault_registry.config import settings as _settings
    from agentvault_registry.services import org_policy as _op
    reg_mode = (getattr(_settings, "LIABILITY_MODE", "off") or "off").lower()
    # §ORGPOLICY: an organization can TIGHTEN liability for its OWN agents (agent → creator developer →
    # organizations.settings). effective mode = strictest(registry, org); effective step-up threshold =
    # the strictest (lowest positive). Tighten-only: an org can turn liability on when the registry is
    # off, never off when it enforces. No org ⇒ registry default; a lookup error refuses with a 503
    # (org_policy.OrgSettingsUnavailable, §SECFIX D6-491: it fell back to the registry default).
    _org_settings = await _op.get_org_settings(db, agent_did)
    mode, thr = _op.effective_liability(reg_mode, presence_threshold(), _org_settings)
    if mode not in ("shadow", "enforce"):
        return
    # §29 OPA I5 `liability_composition_ok` — LIVE CALL SITE. Python owns the per-mandate decision;
    # OPA owns the COMPOSITION (mode + value + mandate + presence considered together).
    amt = float(amount) if amount is not None else 0.0
    over_threshold = amount is not None and thr > 0 and amt >= thr
    needs_presence = over_threshold   # narrowed by the ceiling once the mandate is loaded
    try:
        from agentvault_registry import opa_shadow as _opa
        await _opa.shadow_check("agentvault/invariants/liability_composition_ok",
            {"liability_mode": mode, "amount": amt, "threshold": thr, "has_live_mandate": True},
            True, label=f"liability:{needed}")
    except Exception:
        pass
    from types import SimpleNamespace
    from agentvault_registry import models as _m
    mrow = (await db.execute(text(
        "SELECT id, developer_id, agent_did, tier, scope, limits, status, expires_at "
        "FROM liability_mandates WHERE agent_did = CAST(:a AS VARCHAR) AND status = 'signed' "
        "ORDER BY issued_at DESC LIMIT 1"), {"a": agent_did})).mappings().first()
    ok, reasons, mid, dev = False, ["no_mandate"], None, None
    if mrow:
        mid = mrow["id"]
        dev = await db.get(_m.Developer, mrow["developer_id"])
        res = await resolve_mandate(db, SimpleNamespace(**dict(mrow)), dev)
        ok = res["valid"] and needed in set(res["effective_scope"])
        reasons = res["reasons"] or ([] if ok else [f"scope_missing:{needed}"])
    # §CEILING (P7) — a live standing consent turns an ASK into a RECEIPT. It never turns
    # it into silence (I6): a covered action still writes `gate_pass`, and that row names
    # the ceiling that paid for it, so "why was I not asked about this?" is answerable
    # from the same chain as everything else.
    # Evaluated HERE and not earlier because it reads the mandate's own `limits`, and the
    # mandate is not loaded until this point — the first cut checked it above and would
    # have read None for every ceiling that exists.
    ceiling_ok, ceiling_why = False, "not_checked"
    if needs_presence and ok and mrow is not None:
        from agentvault_registry.services import consent_posture as _cpm
        _cname, _cbundle = _cpm.resolve(_cpm.registry_posture(), _org_settings)
        ceiling_ok, ceiling_why = ceiling_covers(
            mrow["limits"], needed=needed, amount=amount, currency=currency,
            posture=_cbundle, org_settings=_org_settings)
        if ceiling_ok:
            needs_presence = False

    # graduated autonomy: an otherwise-ok mandate STILL steps up to a live presence proof for a
    # big/liable action (amount >= threshold). No proof / bad proof ⇒ denial.
    # §PROOFBIND — the proof must CITE an approved challenge for this exact action;
    # the gate no longer verifies signatures of its own (see the block above).
    presence_ok, cited_chid, presence_reason = True, None, "not_required"
    if needs_presence:
        presence_ok, cited_chid, presence_reason = await verify_presence_citation(
            db, dev, presence, mandate_id=mid, action_ref=action_ref) if mid else (False, None, "no_mandate")
    if needs_presence and ok and not presence_ok:
        reasons = list(reasons) + [f"presence_required:{presence_reason}"]
    hand = acting_hand_did  # None when the agent acted itself; the HAND's DID when a hand acted for it
    if mode == "shadow":
        logger.info("[LIABILITY-SHADOW] gate agent=%s needed=%s ok=%s presence_req=%s presence_ok=%s "
                    "presence_reason=%s amt=%s ccy=%s thr=%s hand=%s reasons=%s ref=%s",
                    agent_did, needed, ok, needs_presence, presence_ok, presence_reason,
                    amt, currency, thr, hand, ",".join(reasons), action_ref)
        return
    if ok and presence_ok:
        # `presence_challenge_id` is what makes the citation single-use: the next
        # attempt reads this row back and refuses to spend the same approval twice.
        # It also makes the receipt say WHICH human approval paid for this pass,
        # which is the thing a dispute actually needs.
        await append_evidence(db, mid, "gate_pass",
                              {"needed": needed, "amount": amt, "currency": currency,
                               "counterparty_did": None if counterparty_did is _UNSET else counterparty_did,
                               "hand": hand,
                               # I6 — a ceiling converts a question into a RECEIPT. Both
                               # fields are always written: `covered_by_ceiling` says a
                               # standing consent paid for this, and `ceiling_reason`
                               # says WHY one did or did not apply, so an action nobody
                               # was asked about still explains itself.
                               "covered_by_ceiling": bool(ceiling_ok),
                               "ceiling_reason": ceiling_why if over_threshold else None,
                               "presence_stepped_up": needs_presence,
                               "presence_challenge_id": cited_chid,
                               "presence_method": presence_reason if needs_presence else None},
                              action_ref=action_ref,
                              presence={"cited_challenge": cited_chid} if needs_presence else None)
        return
    # ── B3 (RBAC plan): a presence-only block PARKS instead of dead-ending ──────────
    # When the mandate itself is fine and the ONLY missing thing is a live human
    # (presence_required), auto-open the presence challenge the human would otherwise
    # have to mint by hand, push it to their phone, and hand the challenge id back in
    # the 403 — the retry then carries the signed X-Presence-Proof from the EXISTING
    # verify rail. The challenge machinery is unchanged; only the reach-out is new.
    stepped_chid = None

    # ── §PREFLIGHT D5: NEVER ASK A QUESTION NOBODY CAN HEAR ─────────────────────────
    # Expiry is a denial (I3). So minting a challenge into an empty room does not defer
    # the decision — it SPENDS the window and denies the agent on the human's behalf,
    # for the crime of the human being away from the desk. With presence gating on, an
    # absent human means we mint NOTHING and say so; the agent backs off and retries,
    # and the moment a desk or Pocket socket opens the ordinary park flow runs.
    #
    # 🔴 `absent` ONLY. `presence_state` is deliberately three-valued and `unknown`
    # (Redis down, or a socket held by another worker we cannot see) must NOT refuse:
    # being unable to see the human is not evidence that the human is gone, and a
    # Redis outage that silently converted every action into `human_away` would look
    # exactly like policy while being an outage.
    human_away = False
    if mid and ok and needs_presence and not presence_ok and dev is not None:
        try:
            from agentvault_registry.services import consent_posture as _cp0
            if _cp0.resolve(_cp0.registry_posture(), _org_settings)[1].get("presence_gated_raise"):
                if (await presence_state(dev.id)) == "absent":
                    human_away = True
                    reasons = list(reasons) + ["human_away"]
                    logger.info("[PREFLIGHT] not minting into an empty room: dev=%s ref=%s",
                                dev.id, action_ref)
        except Exception:  # noqa: BLE001 — a presence check that fails must not deny
            human_away = False

    if mid and ok and needs_presence and not presence_ok and dev is not None and not human_away:
        try:
            facts, facts_err = build_facts_v2(
                verb=needed, action_ref=action_ref, mandate_id=mid, agent_did=agent_did,
                # the ORIGINAL value, not the float the threshold comparison used:
                # `amt` is for arithmetic, `amount` is what the human reads.
                amount=amount,
                currency=currency or (frame_currency() if amount is not None else None),
                counterparty_did=counterparty_did,
                counterparty_home_registry=counterparty_home_registry,
                auto_stepped_up=True)
            if facts is None:
                # I11 — refuse to mint a money challenge that cannot name its unit or
                # declare its counterparty. The block still stands; the human is simply
                # not asked to sign a summary the server could not state honestly.
                logger.error("[LIABILITY] refusing to mint a step-up challenge: %s "
                             "(agent=%s ref=%s amount=%s currency=%s)",
                             facts_err, agent_did, action_ref, amt, currency)
                raise ValueError(facts_err)
            nonce = secrets.token_hex(16)
            stepped_chid = new_id("lch")
            # §POSTURE P4 — TTL by bundle, and the STRICTER of bundle and operator env.
            # An auto-stepped challenge and a hand-minted one must expire on the same
            # clock, or the posture would apply to only half the asks a human sees.
            from agentvault_registry.services import consent_posture as _cp
            # Reuse the org settings the gate ALREADY resolved at the top rather than
            # re-querying: this block runs after evidence has been appended, and
            # `get_org_settings` opens a SAVEPOINT — one fewer nested transaction in
            # the middle of a live money path is worth more than the symmetry.
            _pname, _pb = _cp.resolve(_cp.registry_posture(), _org_settings)
            # Same law as the manual mint site: an UNSET env is not an operator
            # decision, and defaulting it to 120 silently capped every humane TTL.
            ttl = int(_pb.get("challenge_ttl_seconds") or 900)
            _raw_ttl = os.getenv("LIABILITY_CHALLENGE_TTL_SECONDS")
            if _raw_ttl:
                try:
                    ttl = min(ttl, int(_raw_ttl))
                except ValueError:
                    pass
            ttl = max(1, ttl)
            await db.execute(text(
                "INSERT INTO liability_challenges (id, mandate_id, developer_id, action_type, "
                "action_ref, facts, nonce, challenge_hash, status, expires_at) VALUES "
                "(:id, :m, :dev, :at, :ar, CAST(:f AS JSONB), :n, :h, 'pending', "
                " now() + make_interval(secs => :ttl))"
            ), {"id": stepped_chid, "m": mid, "dev": dev.id, "at": needed, "ar": action_ref,
                "f": json.dumps(facts), "n": nonce,
                "h": challenge_hash_for(facts, nonce), "ttl": ttl})
            await append_evidence(db, mid, "challenge_created",
                                  {"challenge_id": stepped_chid, "action_type": needed,
                                   "auto_stepped_up": True, "ttl_seconds": ttl},
                                  action_ref=action_ref)
        except Exception:  # noqa: BLE001 — the park is best-effort; the deny stands regardless
            logger.warning("[LIABILITY] auto step-up challenge failed", exc_info=True)
            stepped_chid = None
    if mid:
        await append_evidence(db, mid, "gate_block",
                              {"needed": needed, "reasons": reasons, "amount": amt, "hand": hand,
                               "stepped_up_challenge": stepped_chid},
                              action_ref=action_ref)
        await db.commit()  # the 403 must not roll the block evidence (or the parked challenge) away
    if stepped_chid:
        try:  # push AFTER the commit so the phone never sees a challenge that vanished
            import asyncio as _aio
            from agentvault_registry.background_tasks.push_notify import notify as _notify
            _aio.get_running_loop().create_task(_notify(
                "security.liability_challenge", [dev.id],
                title="Confirm action — Cockpit Card",
                message=f"Approve {needed} ({stepped_chid[:12]}…) in your Cockpit",
                tags="closed_lock_with_key", priority="high"))
            # §SHOWN — the desk's live cue. BOTH mint sites emit it (this one and the
            # manual router), because a decision that arrives by only one of the two
            # paths is a decision the desk learns about late. Type is deliberately NOT
            # `notification`: prefs and quiet hours filter that type, and a muted human
            # must still be told that something waits on their signature.
            from agentvault_registry.routers.liability import _cue as _liab_cue
            _aio.get_running_loop().create_task(_liab_cue(dev.id, "liability.cue", {
                "challenge_id": stepped_chid, "action_type": needed, "action_ref": action_ref,
                "auto_stepped_up": True}))
        except Exception:  # noqa: BLE001
            pass
    from fastapi import HTTPException
    _extra = (f"; presence challenge {stepped_chid} pushed — approve it "
              f"(POST /api/v1/liability/challenges/{stepped_chid}/approve) then retry with "
              f'X-Presence-Proof: {{"method":"challenge","challenge_id":"{stepped_chid}"}}'
              ) if stepped_chid else ""
    # An agent that is told only "denied" retries the same way and is denied the same
    # way. `human_away` is the one refusal here that is expected to succeed later
    # UNCHANGED, so it says so — and says that nothing was spent waiting.
    if human_away:
        _extra = ("; no confirmation was minted and no window was spent — nobody is at a "
                  "desk or phone to answer. Retry with backoff; the ask appears the moment "
                  "a human is present.")
    raise HTTPException(403, detail=f"Liability mandate required for '{needed}' "
                                    f"({', '.join(reasons)}){_extra}")
