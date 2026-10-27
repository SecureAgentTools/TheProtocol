"""Canonical identifier helpers — single source of truth for derived DIDs.

Keeping the developer→wallet mapping in ONE place is what makes the TEG wallet
init durable: the verify-time initialization and every developer-initiated TEG
operation must address the *same* account, or the initialized wallet is a
phantom the developer never transacts with.
"""

import os
import re
import uuid
from typing import Optional

# ─── §DIDWIDEN (2026-09-06) — THE ONE random agent-DID generator ────────────
# Every freshly minted agent DID (create_agent, spawn, fiat onramp, bundle
# restore, clone) comes from here. Two suffix shapes exist in the wild and BOTH
# stay valid forever: a DID is an opaque string everywhere it is stored,
# compared or routed; nothing parses the suffix.
#   legacy  (minted before 2026-09-06): 8-4-4-4 hex, 80 random bits
#           (secrets.token_hex(4)-(2)-(2)-(2)); 39 chars under did:theprotocol:
#   current (§DIDWIDEN):                a canonical uuid4, 8-4-4-4-12,
#           122 random bits; 52 chars under did:theprotocol:
# Why: the DID carries no issuer component, so every frame in a federation draws
# from ONE shared random space with no coordination. 80 bits was fine against
# accident (birthday bound ~n²/2^81) but the whitepaper promised <uuid>; the
# issuer-bound namespace (did:theprotocol:<frame>:<uuid>) is the structural fix
# and is PLANNED for the fresh standup (PLAN_2026-09-06_DID_ISSUER_NAMESPACE.md).
AGENT_DID_METHODS = ("theprotocol", "cos")

_HEX = "[0-9a-f]"
LEGACY_DID_SUFFIX_RE = re.compile(rf"^{_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}$")
UUID4_DID_SUFFIX_RE = re.compile(rf"^{_HEX}{{8}}-{_HEX}{{4}}-4{_HEX}{{3}}-[89ab]{_HEX}{{3}}-{_HEX}{{12}}$")

# ─── The ISSUER segment (item 1, his approval 2026-09-06) ─────────────────────
# did:theprotocol:<issuer>:<uuid4> — the issuer is the minting frame's SPIFFE trust
# domain (lowercase, DNS-shaped), the one name every federation channel already
# proves with mTLS. Two frames cannot collide by construction, and a peer that
# presents a namespace it does not own is refusable at ingest (the guard).
# Unset ⇒ the two-segment uuid4 form; every older shape stays valid for life.
DID_ISSUER_ENV = "DID_ISSUER_NAMESPACE"
ISSUER_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$")
# Second segments that already exist and are NOT issuers (deterministic system DIDs):
RESERVED_ISSUERS = frozenset({
    "operator", "cloud", "org", "agora-gateway", "developer", "api-tester", "system", "teg",
    "treasury", "gateway", "fx", "fee", "fee_collector", "admin", "registry", "frame", "template",
})
# Every method-specific id shape that is a VALID agent DID today (the acceptance rule):
#   <8-4-4-4>  ·  <uuid4>  ·  <issuer>:<uuid4>  ·  the deterministic system forms ([a-z0-9_][a-z0-9_-]{2,80})
AGENT_DID_PATTERN_STR = r"^did:(theprotocol|cos):(?:[a-z0-9][a-z0-9.-]{0,61}[a-z0-9]:)?[a-z0-9_][a-z0-9_\-]{2,80}$"
AGENT_DID_PATTERN = re.compile(AGENT_DID_PATTERN_STR)


def valid_issuer(issuer) -> bool:
    return isinstance(issuer, str) and bool(ISSUER_RE.match(issuer)) and issuer not in RESERVED_ISSUERS


def registry_issuer() -> Optional[str]:
    """This registry's issuer namespace (``DID_ISSUER_NAMESPACE``), or None when unset.

    A set-but-invalid value is a misconfiguration and raises — a frame must never
    mint under a namespace the guard would refuse (see assert_issuer_posture).
    """
    raw = (os.environ.get(DID_ISSUER_ENV) or "").strip().lower()
    if not raw:
        return None
    if not valid_issuer(raw):
        raise ValueError(f"{DID_ISSUER_ENV}={raw!r} is not a valid issuer namespace (DNS-shaped, lowercase, not reserved)")
    return raw


def assert_issuer_posture() -> Optional[str]:
    """G2 — the boot check. The issuer must be the frame's own SPIFFE trust domain.

    Returns the issuer (or None when unset). Raises RuntimeError on a mismatch so the
    registry refuses to start rather than mint DIDs a peer would drop.
    """
    issuer = registry_issuer()  # raises on a malformed value
    if issuer is None:
        return None
    td = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip().lower()
    if td and td != issuer:
        raise RuntimeError(
            f"{DID_ISSUER_ENV}={issuer!r} does not equal SPIRE_TRUST_DOMAIN={td!r}: the issuer segment is the "
            "trust domain mTLS proves — refusing to start (fix the env, never the check)"
        )
    return issuer


def generate_agent_did(did_method: str = "theprotocol", issuer: Optional[str] = None) -> str:
    """Mint a fresh random agent DID: ``did:<method>:<uuid4>`` or, with an issuer,
    ``did:<method>:<issuer>:<uuid4>``.

    Raises ValueError on an unsupported method (the create_agent 400 depends on
    that message shape) or an invalid issuer. Uniqueness against rows that already
    exist locally is the caller's job — see ``routers.onboarding.mint_unique_agent_did``.
    """
    if did_method not in AGENT_DID_METHODS:
        raise ValueError(f"Unsupported DID method: {did_method}")
    if issuer is not None:
        if not valid_issuer(issuer):
            raise ValueError(f"Invalid DID issuer namespace: {issuer!r}")
        return f"did:{did_method}:{issuer}:{uuid.uuid4()}"
    return f"did:{did_method}:{uuid.uuid4()}"


def generate_local_agent_did(did_method: str = "theprotocol") -> str:
    """A fresh DID under THIS registry's issuer (``DID_ISSUER_NAMESPACE``), two-segment when unset."""
    return generate_agent_did(did_method, issuer=registry_issuer())


def agent_did_parts(did: str):
    """(method, issuer|None, method_specific_id) — reserved second segments are never an issuer."""
    parts = (did or "").split(":")
    if len(parts) < 3 or parts[0] != "did":
        return None, None, did or ""
    method = parts[1]
    if len(parts) >= 4 and valid_issuer(parts[2]):
        return method, parts[2], ":".join(parts[3:])
    return method, None, ":".join(parts[2:])


def agent_did_issuer(did: str) -> Optional[str]:
    return agent_did_parts(did)[1]


def agent_did_suffix_shape(did: str) -> str:
    """Classify a DID's method-specific id: ``namespaced`` | ``uuid4`` | ``legacy`` | ``other``.

    Telemetry and tests only — never a gate. ``other`` covers the deterministic
    system DIDs (operators, gateways, treasuries, developer wallets, clones).
    """
    _method, issuer, rest = agent_did_parts(did)
    if issuer is not None:
        return "namespaced" if UUID4_DID_SUFFIX_RE.match(rest) else "other"
    if UUID4_DID_SUFFIX_RE.match(rest):
        return "uuid4"
    if LEGACY_DID_SUFFIX_RE.match(rest):
        return "legacy"
    return "other"


def developer_teg_did(email: str) -> str:
    """Return the canonical TEG account DID for a developer.

    This is the ONE definition of a developer's wallet identity. It is used by:
      * the verify-time wallet bootstrap (`routers/auth_secure.py`, `routers/auth.py`)
      * every developer-initiated TEG operation (`routers/teg_integration_mtls.py`)

    so the wallet that gets created on verification is exactly the wallet the
    developer later transacts with.

    History / why this exists: the bootstrap used ``did:theprotocol:{developer_id}``
    (a bare integer) while real operations used the email form below. The two never
    matched, so the bootstrap created a phantom, never-funded account — the
    long-standing "Failed to initialize TEG account" papercut. One helper removes
    the drift permanently.

    Note: the email form is the de-facto identity already deployed in the live
    transaction path. A future hardening could move to a stable, id-based DID with
    a balance migration (the "proper ID mapping" TODO in teg_integration_mtls) — but
    that requires a migration and is intentionally out of scope here.
    """
    return f"did:theprotocol:{email.replace('@', '_at_')}"


# §SECFIX D6-606 (2026-10-16): developer_teg_did carries the developer's e-mail address, and public reads listed such
# ids (GET /api/v1/teg/reputation/rankings, GET /api/v1/public/eventstore-recent). The account keeps its id (balances
# key on it); a PUBLIC answer shows an opaque one instead. The SVID subject form writes '.' as '_dot_' too: same mark.
_EMAIL_DERIVED_DID_RE = re.compile(r"did:theprotocol:[^\s\"<>/?#:,;()\[\]{}]*_at_[^\s\"<>/?#:,;()\[\]{}]*")
_EMAIL_ADDRESS_RE = re.compile(r"[A-Za-z0-9.!#$%&*+=?^_`{|}~'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PUBLIC_ACCOUNT_PREFIX = "account:"
EMAIL_WITHHELD = "[address withheld]"


def is_email_derived_account_id(account_id) -> bool:
    """True for a TEG account id built from an e-mail address (developer_teg_did): no agent DID carries `_at_`."""
    return isinstance(account_id, str) and _EMAIL_DERIVED_DID_RE.fullmatch(account_id.strip()) is not None


_MIN_STORE_KEY_LEN = 16   # the store's own floor for a usable key (agentvault-event-store/src/personal_ids.py)


def _public_account_key() -> bytes:
    """SEC-12 (2026-10-17): the key of the public account id.

    This registry's own event store shows an account in its public stream under the same `account:<16 hex>` form, keyed
    with the store's internal key (agentvault-event-store/src/personal_ids.py). This registry presents that very key on
    every event it writes to its store (event_emitter.own_store_key: a frame's template gives the registry's
    EVENT_STORE_API_KEY and the store's INTERNAL_API_KEY one value), so it keys its own public id with it too, and an
    account shows one id on the registry's public reads and in the store's public stream. No secret is shared that was
    not shared already, and an HMAC answer reveals nothing of its key. A registry without a usable store key keeps its
    API_KEY_SECRET (its public ids then differ from the store's). The id changes with the key: when the store's key is
    rotated, both move to the new one as each takes it."""
    from agentvault_registry.event_emitter import own_store_key

    store_key = str(own_store_key() or "")
    if len(store_key) >= _MIN_STORE_KEY_LEN:
        return store_key.encode()
    from agentvault_registry.config import settings

    return str(getattr(settings, "API_KEY_SECRET", "") or "").encode()


def public_account_id(account_id: str) -> str:
    """The id a PUBLIC answer shows for an account whose id is built from an e-mail address: `account:<16 hex>`, an
    HMAC-SHA256 under the key of _public_account_key (the one this registry's event store keys its own with), stable
    here, which nobody can turn back into the address or test a guessed address against (a plain hash of an address
    can). Not resolvable and not a DID, on purpose."""
    import hashlib
    import hmac

    mac = hmac.new(_public_account_key(), b"public-account-id\x00" + account_id.strip().encode(),
                   hashlib.sha256).hexdigest()
    return f"{PUBLIC_ACCOUNT_PREFIX}{mac[:16]}"


def withhold_personal_ids(value):
    """A copy of a JSON value fit for a PUBLIC answer: every e-mail-derived account id becomes its public_account_id and
    every e-mail address is withheld, in values and in keys, at any depth. The stored value is never changed."""
    if isinstance(value, str):
        if "_at_" in value:
            value = _EMAIL_DERIVED_DID_RE.sub(lambda m: public_account_id(m.group(0)), value)
        if "@" in value:
            value = _EMAIL_ADDRESS_RE.sub(EMAIL_WITHHELD, value)
        return value
    if isinstance(value, dict):
        return {withhold_personal_ids(k): withhold_personal_ids(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [withhold_personal_ids(v) for v in value]
    return value
