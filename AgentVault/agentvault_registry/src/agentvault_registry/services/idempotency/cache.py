"""§pass57: Generic Idempotency-Key request-level cache.

Promoted from services/bundles/service.py (proven in production since §pass51).
Generalized over `scope` so multiple endpoint families can share the same
helper without colliding on cache keys.

Behavior:
- No key provided → (None, None) → caller proceeds normally (no dedup)
- Key exists, same body hash → returns cached response → caller returns it directly
- Key exists, DIFFERENT body hash → raises IdempotencyError → caller raises 422
- Redis unavailable → fail-open (caller proceeds normally) — sandbox-friendly,
  matches the existing bundles pattern.

TTL: 24h by default (Stripe convention), configurable via env.

Cache key format: `idempotency@{caller tag}:{scope}:{idempotency_key}` (D6-777, below)
  e.g. `idempotency@3fa9c0d1e2b4a567:teg.transfer:a1b2c3...`
       `idempotency@0c41d29e77a1b5f0:teg.treasury.fund-agent:a1b2c3...`

Different scopes mean different namespaces — same client-supplied key on two
different endpoints does NOT collide (intentional — the endpoints have
different side effects). Different callers mean different namespaces too: a key
is the caller's own (D6-777).
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Any, Awaitable, Callable, Optional, Tuple

from fastapi import HTTPException
from starlette.exceptions import HTTPException as _AnyHTTPException

logger = logging.getLogger(__name__)

# Default 24h, configurable. Matches bundles service default.
IDEMPOTENCY_TTL_SECONDS = int(
    os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400")
)

# §pass57-hardening (2026-06-13): atomic SETNX claim closes the concurrent
# same-key race (two parallel requests both GET-miss → both execute the guarded
# side effect). At lookup, exactly one of N concurrent callers wins `SET NX` and
# proceeds; the rest replay the winner's result (or briefly wait if it's still
# in-flight). See idempotency_lookup for the full state machine.
#
# CLAIM_TTL is the PENDING-placeholder lifetime and MUST exceed the slowest
# guarded operation (cross-reg 2PC worst case ≈ 60s: 25s POST timeout + 2 backoff
# retries) — otherwise a third request could re-claim mid-flight and double-
# execute, reopening the exact race we close. A crash/failure between claim and
# store auto-releases the key at this TTL (degrades to today's re-execute, never
# a permanent lock). INFLIGHT_WAIT is how long a race-loser blocks for the
# winner's result before returning "in progress, retry"; it must be < CLAIM_TTL
# and short enough not to starve a worker.
IDEMPOTENCY_CLAIM_TTL_SECONDS = int(
    os.environ.get("IDEMPOTENCY_CLAIM_TTL_SECONDS", "90")
)
IDEMPOTENCY_INFLIGHT_WAIT_SECONDS = float(
    os.environ.get("IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", "8")
)
IDEMPOTENCY_INFLIGHT_POLL_SECONDS = float(
    os.environ.get("IDEMPOTENCY_INFLIGHT_POLL_SECONDS", "0.15")
)


async def _claim_seconds_left(redis, ck: str) -> Optional[int]:
    """Seconds left on a claim, or None when the store cannot say. A failure here must NOT reach the caller's
    fail-open `except`: that answers (None, None) and the caller would execute the guarded side effect again."""
    try:
        left = await redis.ttl(ck)
    except Exception:  # noqa: BLE001
        return None
    return left if isinstance(left, int) and left >= 0 else None


def unresolved_claim_message(idempotency_key: str, seconds_left: Optional[int]) -> str:
    """§MCPTEST30 (2026-10-01): a claim with no stored result is EITHER a request still running OR one that ended without
    storing a result (a refusal or an error stores none; only a success calls idempotency_store). The cache cannot tell
    the two apart, so the answer names both and when the key frees itself, instead of asserting "in progress" about a
    request that was refused. "in progress" and "Idempotency-Key" stay in the text: the AGORA repatriation reads a 422
    carrying either as in-flight (services/exchange_service.py)."""
    when = f"in {seconds_left} s" if seconds_left is not None else f"within {IDEMPOTENCY_CLAIM_TTL_SECONDS} s"
    return (
        f"Idempotency-Key '{idempotency_key}' is claimed on this endpoint by an earlier request that has not stored "
        f"a result: it is still in progress, or it ended without one (a refusal or an error stores none). The key "
        f"frees itself {when}; a retry after that replays a stored result or runs the request again. Use a new key "
        f"for a new attempt."
    )


def _mismatch_message(idempotency_key: str) -> str:
    return (
        f"Idempotency-Key '{idempotency_key}' already used on this endpoint "
        f"with a different request payload. Use a unique key per logical "
        f"operation, or replay with the EXACT same body."
    )


class IdempotencyError(Exception):
    """Raised when a key was previously used with a DIFFERENT request body.

    Callers should catch and surface as HTTP 422 to the client. This is the
    Stripe-compatible behavior — the same key cannot be reused for a
    semantically different request.
    """
    pass


# ── D6-777 (2026-10-17): a record is the caller's ──────────────────────────────────────────────────────────────────────
# Every record is kept under the caller the route acts for (the agent, the developer, the federation identity or the
# licence that authenticated the request): its key carries the caller's tag and its body hash is bound to the caller, so
# a record only ever matches the caller that wrote it, and the same key value from another caller is another key. A
# record kept by an older image (under the scope and key alone) names no caller: it is never replayed and never lets the
# request run; it answers as not matching (unscoped_record_message) until it expires (IDEMPOTENCY_TTL_SECONDS at most).
# Routes that derive further keys from the client's key (escrow legs, ledger events) derive them from caller_key().
ANONYMOUS_CALLER = "anonymous"   # a route that serves an unauthenticated flow (the anonymous fiat checkout)


def _named(kind: str, value: Any) -> str:
    v = str(value if value is not None else "").strip()
    if not v:
        raise ValueError(f"an idempotency record needs its caller: no {kind} named")
    return f"{kind}:{v}"


def agent_caller(did: Any) -> str:
    return _named("agent", did)


def developer_caller(developer_id: Any) -> str:
    return _named("developer", developer_id)


def federation_caller(identity: Any) -> str:
    return _named("federation", identity)


def licence_caller(licence_id: Any) -> str:
    return _named("licence", licence_id)


def _caller(principal: Any) -> str:
    """The caller a record is kept under, refused when absent (a record no caller owns is the defect D6-777 closed).
    Raised before any store is touched, so no fail-open path can turn a missing caller into a shared key."""
    if not isinstance(principal, str) or not principal.strip():
        raise ValueError("an idempotency record needs its caller (principal)")
    return principal


def _caller_tag(principal: str) -> str:
    return hashlib.sha256(_caller(principal).encode()).hexdigest()[:16]


def _cache_key(scope: str, idempotency_key: str, principal: str) -> str:
    """Build the Redis cache key: the caller's tag, then the scope, so neither two callers nor two endpoint families
    collide on one key value. The root `idempotency@` never begins a key written before D6-777 (`idempotency:`)."""
    return f"idempotency@{_caller_tag(principal)}:{scope}:{idempotency_key}"


def _unscoped_cache_key(scope: str, idempotency_key: str) -> str:
    """Where a record written before D6-777 lives (the scope and the key alone, no caller)."""
    return f"idempotency:{scope}:{idempotency_key}"


def _durable_key(idempotency_key: str, principal: str) -> str:
    """The durable copy's idem_key for the caller's key (idempotency_kept.idem_key holds 255 characters: a longer key is
    kept under its digest)."""
    k = f"@{_caller_tag(principal)}:{idempotency_key}"
    if len(k) > 255:
        k = f"@{_caller_tag(principal)}:#" + hashlib.sha256(str(idempotency_key).encode()).hexdigest()
    return k


def caller_key(principal: str, idempotency_key: str) -> str:
    """The client's Idempotency-Key bound to its caller, for every key a route derives from it downstream (the escrow
    legs of a treasury move, the ledger event that records it). The same caller's retry derives the same keys and
    replays its own legs; two callers never share one. 33 characters, whatever the client sent."""
    return "k" + hashlib.sha256(f"{_caller(principal)}\n{idempotency_key}".encode()).hexdigest()[:32]


def unscoped_record_message(idempotency_key: str) -> str:
    """A record of the key written before records were the caller's (D6-777): nobody can say whose it is, so it is not
    replayed and this request was not run. "(outcome not known)" is in the text on purpose: the console keeps the key and
    the payout lane holds the credit for such an answer (services/money/sendOutcome.ts, services/payout_outcome), as for
    any answer that cannot say whether money moved."""
    return (
        f"Idempotency-Key '{idempotency_key}' is held on this endpoint by a request recorded before keys were kept per "
        f"caller, so that request cannot be matched to this one, and this one was not run. The earlier request's result "
        f"cannot be given back under this key {_OUTCOME_UNKNOWN}: if it was yours, read the balance and the transactions "
        f"before paying again. A new request needs a new key; this key frees itself within "
        f"{max(1, IDEMPOTENCY_TTL_SECONDS // 3600)} hours."
    )


def _canonical_json(body: dict) -> str:
    """Stable serialization for body-hash comparison.

    sort_keys + tight separators give the same string regardless of dict
    insertion order or whitespace. Decimals stringified by default encoder.
    """
    def _default(o):
        # Decimal, datetime, UUID, etc. — fall back to str
        return str(o)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=_default)


def _body_hash(body: dict) -> str:
    return hashlib.sha256(_canonical_json(body).encode()).hexdigest()


def _record_hash(principal: str, body: dict) -> str:
    """The body hash a record keeps (D6-777): bound to the caller, so a record matches only its own caller's request
    with the same body, and never one written before records were the caller's (those keep the bare body hash)."""
    return hashlib.sha256(f"{_caller(principal)}\n{_body_hash(body)}".encode()).hexdigest()


def record_is_of(record: Any, principal: Optional[str], bodies) -> bool:
    """Is `record` (a record the store keeps: Redis's or the durable copy's) a record of one of `bodies`, kept as
    `principal`'s? With no principal: a record written before records were the caller's (the bare body hash). A reader
    that knows what request its key was used for asks this before it trusts the record (the A2A stale-settlement sweep:
    the payer can derive the settlement key and use it for a transfer of its own)."""
    kept = record.get("body_hash") if isinstance(record, dict) else None
    if not kept:
        return False
    for body in bodies or ():
        want = _record_hash(principal, body) if principal else _body_hash(body)
        if kept == want:
            return True
    return False


# ── §REPATLANE-8 (V0610): the durable copy (services/idempotency/durable.py, idempotency_kept) ──────────────────────────
# Redis evicts (allkeys-lru), so a record it lost inside its 24 h window made the same key run again. The copy is written
# after Redis and read only when Redis has no record of the key; a copy that cannot be used leaves the behaviour this
# module had without it (Redis alone), never a refusal of its own. A claim the copy kept while Redis lost it reads as a
# request still running for this long after it began, and as one that ended without an answer after that.
DURABLE_CLAIM_RUNNING_S = int(os.environ.get("IDEMPOTENCY_DURABLE_CLAIM_RUNNING_S", "180"))


async def _durable(op: str, call):
    """One durable call, or None when the copy is off or cannot be used (logged and counted, never raised)."""
    from . import durable
    if not durable.enabled():
        return None
    try:
        return await call(durable)
    except Exception as e:  # noqa: BLE001 — Redis alone, as before the copy
        durable.count(op, "error")
        logger.warning(f"[idempotency] the durable copy could not {op} ({type(e).__name__}: {e}); Redis alone keeps this key")
        return None


async def _put_back(redis, ck: str, record: dict, left_s: float) -> None:
    """The durable record back into Redis for the rest of its life (best effort: the copy answers again otherwise)."""
    try:
        await redis.set(ck, json.dumps(record, default=str), ex=max(1, int(left_s)))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[idempotency] could not put a durable record back into Redis: {e}")


async def _take_back(redis, ck: str, claim: str) -> None:
    """This request's own placeholder out of Redis (a record elsewhere answers for the key)."""
    try:
        if await redis.get(ck) == claim:
            await redis.delete(ck)
    except Exception:  # noqa: BLE001 — the placeholder expires after IDEMPOTENCY_CLAIM_TTL_SECONDS
        pass


async def _after_claim(redis, ck: str, claim: str, scope: str, idempotency_key: str, principal: str,
                       bh: str) -> Tuple[Optional[dict], Optional[str]]:
    """This request won the claim of its key, which Redis held no record of. D6-777: a record of the key written before
    records were the caller's answers as not matching; then the durable copy may hold an answer Redis evicted."""
    from . import durable
    if await redis.get(_unscoped_cache_key(scope, idempotency_key)) is not None:
        await _take_back(redis, ck, claim)
        return None, unscoped_record_message(idempotency_key)
    rec = await _durable("read", lambda d: d.get(scope, _durable_key(idempotency_key, principal),
                                                 unscoped_key=idempotency_key))
    if rec is None:
        return None, None  # we are first — proceed; idempotency_store overwrites
    if rec.get("unscoped"):
        durable.count("read", "unscoped")
        await _take_back(redis, ck, claim)
        return None, unscoped_record_message(idempotency_key)
    return await _legacy_from_durable(redis, ck, claim, rec, bh, idempotency_key, scope)


async def idempotency_lookup(
    scope: str,
    idempotency_key: Optional[str],
    body: dict,
    *,
    principal: str,
) -> Tuple[Optional[dict], Optional[str]]:
    """Atomically CLAIM the scope+key, or replay/await a prior/in-flight result.

    D6-777: `principal` is the caller the route acts for (agent_caller, developer_caller, federation_caller,
    licence_caller or ANONYMOUS_CALLER): the record is that caller's, and another caller's record under the same key
    value is never seen. Required; a missing caller raises before any store is touched.

    §pass57-hardening: this is *claim-then-act*, not *check-then-act*. The first
    of N concurrent same-key callers wins an atomic `SET NX` (writing a short-TTL
    PENDING placeholder) and is told to proceed; the rest find the reservation and
    replay the winner's result (or briefly wait if it's still in-flight). This
    closes the window where two parallel requests both GET-miss and both execute
    the guarded side effect (e.g. a money move).

    Returns:
        (cached_response, error_message)
        - (None, None)            → no key, OR we WON the claim → caller proceeds
                                    normally and MUST call idempotency_store on success
                                    (the store overwrites the placeholder with the
                                    real response at the long TTL).
        - (response_dict, None)   → prior result exists (same body) → caller returns it
        - (None, error_message)   → key reused with a DIFFERENT body, OR the winner is
                                    still in-flight past the wait → caller raises
                                    HTTPException(422, error) (the in-flight message
                                    tells the client to retry shortly).

    Fail-open on Redis errors / no Redis (matches bundles service behavior —
    sandboxes often run without Redis). No key → no dedup (Stripe opt-in).
    """
    if not idempotency_key:
        return None, None
    _caller(principal)
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        redis = await get_redis()
        if redis is None:
            return None, None
        ck = _cache_key(scope, idempotency_key, principal)
        bh = _record_hash(principal, body)
        _mismatch = _mismatch_message(idempotency_key)
        # Atomic claim. Winner writes a PENDING placeholder (carries body_hash so a
        # different-body collision is caught even while in-flight). NX guarantees
        # exactly one winner among concurrent callers.
        claim = json.dumps({"body_hash": bh, "pending": True})
        won = await redis.set(ck, claim, nx=True, ex=IDEMPOTENCY_CLAIM_TTL_SECONDS)
        if won:
            # §REPATLANE-8: Redis had no record of the key; the durable copy may (an evicted answer). D6-777: nor may a
            # record written before records were the caller's.
            return await _after_claim(redis, ck, claim, scope, idempotency_key, principal, bh)

        # Lost the claim — another request owns this key. Replay its result, or
        # wait (bounded) if it is still executing.
        deadline = time.monotonic() + IDEMPOTENCY_INFLIGHT_WAIT_SECONDS
        while True:
            cached_raw = await redis.get(ck)
            if cached_raw is None:
                # Owner's placeholder expired (crash, or op slower than CLAIM_TTL).
                # Try to re-claim; if we win, proceed, else re-read the new owner.
                won = await redis.set(ck, claim, nx=True, ex=IDEMPOTENCY_CLAIM_TTL_SECONDS)
                if won:
                    return await _after_claim(redis, ck, claim, scope, idempotency_key, principal, bh)
                continue
            cached = json.loads(cached_raw)
            if cached.get("body_hash") != bh:
                return None, _mismatch
            if "response" in cached:
                return cached.get("response"), None  # winner finished — replay
            # Still PENDING — bounded wait for the winner to store its result.
            if time.monotonic() >= deadline:
                return None, unresolved_claim_message(idempotency_key, await _claim_seconds_left(redis, ck))
            await asyncio.sleep(IDEMPOTENCY_INFLIGHT_POLL_SECONDS)
    except Exception as e:
        logger.warning(f"[idempotency] lookup failed (fail-open): {e}")
        return None, None


async def _legacy_from_durable(redis, ck: str, claim: str, rec: dict, bh: str, idempotency_key: str,
                               scope: str) -> Tuple[Optional[dict], Optional[str]]:
    """idempotency_lookup's answer from a durable record Redis had lost: a kept answer is replayed and put back; a claim
    or an error kept by a kept attempt on this scope reads as a claim with no stored result (this path stores none)."""
    from . import durable
    await _take_back(redis, ck, claim)   # our placeholder out: the durable record is the key's record
    if rec.get("body_hash") != bh:
        durable.count("read", "mismatch")
        return None, _mismatch_message(idempotency_key)
    if rec.get("state") == "answer":
        durable.count("read", "answer")
        logger.warning(f"[idempotency] Redis had no record of key {idempotency_key!r} on scope={scope!r}; the durable copy "
                       f"replays its kept answer and puts it back")
        await _put_back(redis, ck, {"body_hash": bh, "response": rec.get("payload")}, rec.get("left_s") or 0)
        return rec.get("payload"), None
    durable.count("read", rec.get("state") or "unknown")
    return None, unresolved_claim_message(idempotency_key, None)


async def idempotency_store(
    scope: str,
    idempotency_key: Optional[str],
    body: dict,
    response,
    *,
    principal: str,
    redact_keys: Optional[list[str]] = None,
) -> None:
    """Cache (scope, key, body_hash, response) for IDEMPOTENCY_TTL_SECONDS, as the record of `principal` (the caller
    idempotency_lookup was given; D6-777).

    Accepts response as `dict` OR Pydantic model (any object with a `model_dump`
    method). Pydantic models are auto-serialized via `model_dump(mode="json")`
    so the cached shape matches what FastAPI would emit on a fresh execution —
    critical for endpoints with `response_model=...` validation. Without this,
    a model passed as-is would fall through to `str(model)` via JSON's default
    encoder and the cached replay would fail FastAPI's response validator with
    8-field-missing errors (see §pass57 v2 audit).

    If `redact_keys` is provided, those top-level keys of the cached response
    are replaced with the literal string '[REDACTED on replay]' — use this for
    secrets (client_secret, plain_api_key) that should never be re-leaked on
    replay. The bundles service does the same for produced_agents[*].client_secret.

    Fail-open on Redis errors. Skip-cache (with warning) on unsupported types.

    §pass57-hardening: this OVERWRITES the short-TTL PENDING placeholder that
    idempotency_lookup's `SET NX` claim wrote (plain SET, no NX — only the claim
    winner reaches here for a given key), promoting it to the real response at the
    long IDEMPOTENCY_TTL_SECONDS so subsequent same-key callers replay it.
    """
    if not idempotency_key:
        return
    _caller(principal)
    bh = _record_hash(principal, body)
    redacted: Optional[dict] = None
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        redis = await get_redis()
        if redis is None:
            return

        # §pass57.5: type-aware serialization. Order matters — check dict FIRST
        # because some Pydantic models inherit from dict-like, and we want the
        # dict path to win for plain dicts that happen to have model_dump.
        if isinstance(response, dict):
            redacted = dict(response)
        elif hasattr(response, "model_dump"):
            try:
                redacted = response.model_dump(mode="json")
            except Exception as dump_err:
                logger.warning(
                    f"[idempotency] model_dump failed for {type(response).__name__} "
                    f"on scope={scope!r}: {dump_err}. Skipping cache."
                )
                return
        elif response is None:
            redacted = {}  # null response — cache empty dict so replay returns {}
        else:
            logger.warning(
                f"[idempotency] unsupported response type {type(response).__name__} "
                f"on scope={scope!r}; skipping cache. Caller must pass dict or "
                f"Pydantic model (call .model_dump(mode='json') first)."
            )
            return

        if redact_keys:
            for k in redact_keys:
                if k in redacted:
                    redacted[k] = "[REDACTED on replay]"
        payload = json.dumps(
            {"body_hash": bh, "response": redacted},
            default=str,
        )
        await redis.set(
            _cache_key(scope, idempotency_key, principal),
            payload,
            ex=IDEMPOTENCY_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning(f"[idempotency] store failed (non-fatal): {e}")
    if redacted is None:
        return
    # §REPATLANE-8: the same answer in the durable copy (also when Redis could not take it), so an eviction does not
    # make the key run again
    await _durable("store", lambda d: d.store(scope, _durable_key(idempotency_key, principal), bh, redacted,
                                              IDEMPOTENCY_TTL_SECONDS))


# ── §REPATLANE-5 (V0606): a money endpoint that keeps EVERY answer that may be the payment ───────────────────────────────
#
# idempotency_lookup/idempotency_store keep a success and nothing else, so a payment whose answer was "held" (its outcome
# not known: a leg that timed out, a 5xx, a partial commit) ran AGAIN when the same key came back after the 90 s claim.
# The console does exactly that: PocketSend keeps the key of a send whose outcome is unknown, so a second press asks the
# server once more and "the server answers from its claim instead of paying twice" (services/money/sendOutcome.ts); the
# guild's settle retries on its stable key too. A kept attempt (begin_attempt + run_kept) closes it:
#
#   success, or an answer that may be the payment   kept under the key for IDEMPOTENCY_TTL_SECONDS, replayed as it was,
#                                                   with the Idempotent-Replayed header (a success since §REPATLANE-7)
#   an answer that proves nothing moved             the key is given back, so the same key runs again (the payout lane
#                                                   sends a credit again under its stable key only after such a proof)
#   no answer at all (the worker died, the request  the claim stays for IDEMPOTENCY_TTL_SECONDS and its liveness beat
#   was cancelled, the store could not be written)  stops: a later request under the key answers 409 "ended without an
#                                                   answer (outcome not known)" instead of running the payment again
#
# The claim no longer expires after IDEMPOTENCY_CLAIM_TTL_SECONDS while its request runs, so a route slower than 90 s is
# never claimed and run a second time; the beat (IDEMPOTENCY_BEAT_TTL_SECONDS, refreshed every IDEMPOTENCY_BEAT_SECONDS)
# is what tells a running request from one that ended. A claim and its beat are written in one step (_CLAIM_LUA).
IDEMPOTENCY_BEAT_SECONDS = float(os.environ.get("IDEMPOTENCY_BEAT_SECONDS", "10"))
IDEMPOTENCY_BEAT_TTL_SECONDS = int(os.environ.get("IDEMPOTENCY_BEAT_TTL_SECONDS", "45"))
REPLAYED_HEADER = "Idempotent-Replayed"
# services/payout_outcome: OUTCOME_UNKNOWN and NO_FUNDS_MOVED (the payout lane and the console read them; a test pins
# that these are the same text)
_OUTCOME_UNKNOWN = "(outcome not known)"
_NO_FUNDS_MOVED = "(no funds moved)"

_CLAIM_LUA = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[4])
  return 1
end
return 0
"""


def _beat_key(ck: str) -> str:
    return f"{ck}:beat"


def kept_claim_message(idempotency_key: str) -> str:
    """A kept claim whose request is still running. "is claimed on this endpoint" and "in progress" stay in the text: the
    payout lane reads a 422 carrying either as an earlier send still claimed (services/payout_outcome._CLAIMED)."""
    return (
        f"Idempotency-Key '{idempotency_key}' is claimed on this endpoint by an earlier request that is still in "
        f"progress. Send the same request again shortly: it answers with that request's answer."
    )


def ended_without_answer_message(idempotency_key: str) -> str:
    """A kept claim whose request ended without an answer (its beat stopped): nobody can say what it moved."""
    return (
        f"Idempotency-Key '{idempotency_key}': an earlier request under this key ended without an answer "
        f"{_OUTCOME_UNKNOWN}, so it may have moved the money. Read the balance and the transactions before paying "
        f"again; a new payment needs a new key."
    )


def _store_unreadable_message(idempotency_key: str) -> str:
    return (
        f"Idempotency-Key '{idempotency_key}' is held by an earlier request and the idempotency store could not be read, "
        f"so this request was not sent {_NO_FUNDS_MOVED}. Try again shortly."
    )


def mark_replayed(response) -> None:
    """§REPATLANE-7: a kept 2xx answer given again says that it is one, as a replayed error answer does
    (Idempotent-Replayed: true), so a client can tell the earlier request's payment, answered again, from a new payment.
    `response` is the route's injected Response, None when the route is called in-process (the batch transfer)."""
    if response is None:
        return
    try:
        response.headers[REPLAYED_HEADER] = "true"
    except Exception as e:  # noqa: BLE001 — the answer itself is right without the header
        logger.warning(f"[idempotency] could not mark a replayed answer: {e}")


def _replayed_error(err: dict) -> HTTPException:
    headers = {REPLAYED_HEADER: "true"}
    if err.get("retry_after"):
        headers["Retry-After"] = str(err["retry_after"])
    return HTTPException(status_code=int(err.get("status_code") or 500), detail=err.get("detail"), headers=headers)


async def _redis():
    from agentvault_registry.background_tasks.leader import get_redis
    return await get_redis()


class IdempotentAttempt:
    """One request's hold on its Idempotency-Key on an endpoint that keeps every answer (begin_attempt).

    replay       a stored success: return it as it is (nothing ran)
    claimed      this request owns the key and runs; run_kept then keeps its answer, or gives the key back when the
                 answer proves nothing moved
    dispatched   the endpoint sets it (mark_dispatched) right before its first call that may move money: any answer
                 before that moved nothing
    Without a key, or with a store that cannot be used, nothing is claimed and the request runs unkeyed (fail-open, as
    idempotency_lookup)."""

    def __init__(self, scope: str, idempotency_key: Optional[str], body: dict, principal: str):
        self.scope = scope
        self.key = idempotency_key
        self.body = body
        self.principal = _caller(principal)   # D6-777: whose record this attempt keeps
        self.replay: Optional[dict] = None
        self.dispatched = False
        self._claim: Optional[str] = None
        self._token: Optional[str] = None

    @property
    def claimed(self) -> bool:
        return self._claim is not None

    def mark_dispatched(self) -> None:
        self.dispatched = True

    @contextlib.asynccontextmanager
    async def alive(self):
        """While the request runs, its beat says so: a claim whose beat stops belongs to a request that ended."""
        task = asyncio.ensure_future(self._beat()) if self._claim is not None else None
        try:
            yield self
        finally:
            if task is not None:
                task.cancel()

    async def _beat(self) -> None:
        bk = _beat_key(_cache_key(self.scope, self.key, self.principal))
        while True:
            await asyncio.sleep(IDEMPOTENCY_BEAT_SECONDS)
            try:
                redis = await _redis()
                if redis is not None:
                    await redis.set(bk, self._token, ex=IDEMPOTENCY_BEAT_TTL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — a missed beat reads as an ended request: the safe side
                logger.warning(f"[idempotency] beat failed for scope={self.scope!r}: {e}")

    async def keep_answer(self, response) -> None:
        """Keep a 2xx answer under the key (idempotency_store: it overwrites the claim)."""
        if self._claim is not None:
            await idempotency_store(self.scope, self.key, self.body, response, principal=self.principal)

    async def keep_error(self, status_code: int, detail: Any, headers: Optional[dict] = None) -> None:
        """Keep an error answer under the key; a request under it later gets this answer again. If the store cannot be
        written, the claim stays and its beat stops: a later request answers that this one ended without an answer."""
        if self._claim is None:
            return
        err: dict = {"status_code": int(status_code), "detail": detail}
        ra = next((v for k, v in (headers or {}).items() if str(k).lower() == "retry-after"), None)
        if ra:
            err["retry_after"] = str(ra)
        try:
            redis = await _redis()
            if redis is None:
                return
            record = {"body_hash": _record_hash(self.principal, self.body), "error": err}
            await redis.set(_cache_key(self.scope, self.key, self.principal), json.dumps(record, default=str),
                            ex=IDEMPOTENCY_TTL_SECONDS)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[idempotency] could not keep the answer for key {self.key!r} on scope={self.scope!r} "
                         f"(the claim stays: a request under it answers that this one ended without an answer): {e}")
        dk = _durable_key(self.key, self.principal)
        await _durable("settle", lambda d: d.settle(self.scope, dk, self._token, "error", err, IDEMPOTENCY_TTL_SECONDS))

    async def release(self) -> None:
        """Give the key back (the answer proved nothing moved): the same key runs again. Only this request's own claim is
        deleted (nobody else writes a key while its claim stands)."""
        if self._claim is None:
            return
        ck = _cache_key(self.scope, self.key, self.principal)
        # §REPATLANE-8: the durable row first, so a Redis that lost the claim cannot leave the row to answer for it
        await _durable("release", lambda d: d.release(self.scope, _durable_key(self.key, self.principal), self._token))
        try:
            redis = await _redis()
            if redis is None:
                return
            if await redis.get(ck) == self._claim:
                await redis.delete(ck)
            await redis.delete(_beat_key(ck))
        except Exception as e:  # noqa: BLE001
            logger.error(f"[idempotency] could not give back key {self.key!r} on scope={self.scope!r} (a request under "
                         f"it answers that this one ended without an answer until the claim expires): {e}")


async def _attempt_from_durable(a: "IdempotentAttempt", redis, ck: str, rec: dict, bh: str,
                                idempotency_key: str) -> "IdempotentAttempt":
    """begin_attempt's answer from a durable record Redis had lost (§REPATLANE-8): a kept answer is replayed and a kept
    error raised again, each put back into Redis; a claim reads as a request still running for DURABLE_CLAIM_RUNNING_S
    after it began, then as one that ended without an answer. Never a second run of the payment. D6-777: a record of the
    key written before records were the caller's ({"unscoped": True}, from Redis or from the copy) answers as not
    matching, and this request does not run."""
    from . import durable
    if rec.get("unscoped"):
        durable.count("claim", "unscoped")
        raise HTTPException(status_code=422, detail=unscoped_record_message(idempotency_key))
    if rec.get("body_hash") != bh:
        durable.count("claim", "mismatch")
        raise HTTPException(status_code=422, detail=_mismatch_message(idempotency_key))
    state = rec.get("state")
    durable.count("claim", state or "unknown")
    logger.warning(f"[idempotency] Redis had no record of key {idempotency_key!r} on scope={a.scope!r}; the durable "
                   f"copy kept one ({state}, {int(rec.get('age_s') or 0)} s old) and answers for it")
    if state == "answer":
        await _put_back(redis, ck, {"body_hash": bh, "response": rec.get("payload")}, rec.get("left_s") or 0)
        a.replay = rec.get("payload")
        return a
    if state == "error":
        err = rec.get("payload") or {}
        await _put_back(redis, ck, {"body_hash": bh, "error": err}, rec.get("left_s") or 0)
        raise _replayed_error(err)
    if (rec.get("age_s") or 0) < DURABLE_CLAIM_RUNNING_S:
        raise HTTPException(status_code=422, detail=kept_claim_message(idempotency_key))
    raise HTTPException(status_code=409, detail=ended_without_answer_message(idempotency_key))


async def begin_attempt(scope: str, idempotency_key: Optional[str], body: dict, *, principal: str) -> IdempotentAttempt:
    """Claim the key for a kept attempt, or answer from what an earlier request under it left.

    `principal` is the caller the route acts for (D6-777, as idempotency_lookup): only that caller's records answer.

    Returns an attempt that is claimed (run it), or carries `replay` (return it). Raises HTTPException for:
      422  the key with another body, or an earlier request still in progress past IDEMPOTENCY_INFLIGHT_WAIT_SECONDS, or
           a record of the key written before records were the caller's (unscoped_record_message)
      409  an earlier request ended without an answer (outcome not known)
      503  the key is held and the store could not be read (nothing sent)
      the earlier request's own error answer, replayed (Idempotent-Replayed: true)
    A claim written by an endpoint that is not kept (an older image during a roll) is read as idempotency_lookup reads
    it."""
    a = IdempotentAttempt(scope, idempotency_key, body, principal)
    if not idempotency_key:
        return a
    try:
        redis = await _redis()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[idempotency] attempt lookup failed (fail-open): {e}")
        return a
    if redis is None:
        return a
    ck, bh = _cache_key(scope, idempotency_key, principal), _record_hash(principal, body)
    bk = _beat_key(ck)
    token = secrets.token_hex(8)
    claim = json.dumps({"body_hash": bh, "pending": True, "kept": True, "owner": token})

    async def _claim_it():
        """True: this request holds the key (in Redis, and in the durable copy when it can be written). False: another
        request holds it in Redis. A dict: Redis had no record of the key but the durable copy kept an earlier
        request's (an eviction): that record answers, and this request's Redis claim is taken back. D6-777: a record of
        the key written before records were the caller's answers the same way, as {"unscoped": True}."""
        won = await redis.eval(_CLAIM_LUA, 2, ck, bk, claim, IDEMPOTENCY_TTL_SECONDS, token,
                               IDEMPOTENCY_BEAT_TTL_SECONDS)
        if not won:
            return False

        async def _give_back():
            try:
                if await redis.get(ck) == claim:
                    await redis.delete(ck, bk)
            except Exception:  # noqa: BLE001 — the claim keeps its beat 45 s at most; the durable record still answers
                pass
        try:
            unscoped = await redis.get(_unscoped_cache_key(scope, idempotency_key)) is not None
        except Exception:
            # the store took the claim and failed this read: the claim goes back, so no claim of this request is left
            # to answer "ended without an answer" for 24 h, and the failure is handled as any store failure here
            await _give_back()
            raise
        if unscoped:
            rec = {"unscoped": True}
        else:
            rec = await _durable("claim", lambda d: d.claim(scope, _durable_key(idempotency_key, principal), bh, token,
                                                            IDEMPOTENCY_TTL_SECONDS, unscoped_key=idempotency_key))
        if rec is None:
            a._claim, a._token = claim, token
            return True
        await _give_back()
        return rec

    try:
        got = await _claim_it()
    except Exception as e:  # noqa: BLE001 — the store cannot be used at all: the request runs unkeyed (fail-open)
        logger.warning(f"[idempotency] attempt claim failed (fail-open): {e}")
        return a
    if got is True:
        return a
    if isinstance(got, dict):
        return await _attempt_from_durable(a, redis, ck, got, bh, idempotency_key)
    deadline = time.monotonic() + IDEMPOTENCY_INFLIGHT_WAIT_SECONDS
    while True:
        lost: Optional[dict] = None
        try:
            raw = await redis.get(ck)
            if raw is None:
                # given back (a refusal that proved nothing moved), expired or evicted: claim it (the durable copy
                # answers for an evicted record)
                got = await _claim_it()
                if got is True:
                    return a
                if not isinstance(got, dict):
                    continue
                lost = got
            else:
                cached = json.loads(raw)
                running = True
                if cached.get("kept") and "response" not in cached and "error" not in cached:
                    running = bool(await redis.exists(bk))
                    if not running:
                        # the claim may have become its answer between the two reads (a stored answer keeps no beat)
                        again = await redis.get(ck)
                        if again is not None and again != raw:
                            continue
        except Exception as e:  # noqa: BLE001 — another request holds the key: never run past it unread
            logger.warning(f"[idempotency] attempt lookup failed with the key held: {e}")
            raise HTTPException(status_code=503, detail=_store_unreadable_message(idempotency_key))
        if lost is not None:
            return await _attempt_from_durable(a, redis, ck, lost, bh, idempotency_key)
        if cached.get("body_hash") != bh:
            raise HTTPException(status_code=422, detail=_mismatch_message(idempotency_key))
        if "response" in cached:
            a.replay = cached.get("response")
            return a
        if "error" in cached:
            raise _replayed_error(cached.get("error") or {})
        if cached.get("kept") and not running:
            raise HTTPException(status_code=409, detail=ended_without_answer_message(idempotency_key))
        if time.monotonic() >= deadline:
            if cached.get("kept"):
                raise HTTPException(status_code=422, detail=kept_claim_message(idempotency_key))
            raise HTTPException(status_code=422, detail=unresolved_claim_message(
                idempotency_key, await _claim_seconds_left(redis, ck)))
        await asyncio.sleep(IDEMPOTENCY_INFLIGHT_POLL_SECONDS)


async def _settled(aw: Awaitable) -> None:
    """Finish a store write even if the request is being cancelled (the write runs in its own task)."""
    await asyncio.shield(asyncio.ensure_future(aw))


async def run_kept(
    attempt: IdempotentAttempt,
    run: Callable[[], Awaitable[Any]],
    *,
    error_moved_nothing: Callable[[int, Any], bool],
    answer_moved_nothing: Callable[[Any], bool] = lambda _answer: False,
):
    """Run the endpoint's work under a kept attempt and settle the key by its answer:

      a 2xx answer                       kept, unless answer_moved_nothing(answer) (a "failed" answer that proves
                                         nothing moved): then the key is given back
      an HTTPException before dispatch   the key is given back (nothing moved)
      an HTTPException after dispatch    the key is given back if error_moved_nothing(status, detail), else kept
      any other error after dispatch     a 500 "(outcome not known)" is kept and raised instead (logged with its cause)
    A request without a claim (no key, no store) just runs."""
    if not attempt.claimed:
        return await run()
    try:
        async with attempt.alive():
            answer = await run()
    except _AnyHTTPException as exc:
        if not attempt.dispatched or error_moved_nothing(exc.status_code, exc.detail):
            await _settled(attempt.release())
        else:
            await _settled(attempt.keep_error(exc.status_code, exc.detail, getattr(exc, "headers", None)))
        raise
    except asyncio.CancelledError:
        # cancelled before it sent anything: give the key back; after, the claim stays and its beat stops, so a request
        # under the key answers that this one ended without an answer
        if not attempt.dispatched:
            await _settled(attempt.release())
        raise
    except Exception as exc:  # noqa: BLE001
        if not attempt.dispatched:
            await _settled(attempt.release())
            raise
        logger.exception(f"[idempotency] scope={attempt.scope!r} key={attempt.key!r}: an error after dispatch, kept as "
                         f"an answer whose outcome is not known")
        held = HTTPException(status_code=500, detail=(
            f"The request failed after it was sent on {_OUTCOME_UNKNOWN}: it may have moved the money. Read the balance "
            f"and the transactions before paying again."))
        await _settled(attempt.keep_error(held.status_code, held.detail))
        raise held from exc
    if answer_moved_nothing(answer):
        await _settled(attempt.release())
    else:
        await _settled(attempt.keep_answer(answer))
    return answer
