"""§REPATLANE (V0603): what one payout send's answer proves about the money.

The AGORA passport gateway pays foreign traders back through POST /api/v1/teg/send (services/exchange_service.py: the
per-credit pass and the aggregated pass). Every answer is read here, once, into one of five outcomes:

  paid            the payout went out (a 2xx whose status says so)
  retry           nothing reached the trader and nothing will: send it again later, one attempt spent
  wait            an earlier send under the same Idempotency-Key is still claimed at the server: no attempt spent
  sender_refused  IRONKEY refused the gateway itself (§GATEWAYROLE): no attempt spent
  hold            money may have moved: the credit is marked 'unresolved' and is never sent again on its own

Why a hold exists: the registry's idempotency store keeps a success under a key for 24 h (and the async branch's
answers, which this lane never takes: smart send asks for the 2PC backend), so a send that FAILED runs again when the
same key comes back after its 90 s claim, and a new key runs again at once. Measured on the sandbox 2026-09-22 to
10-12: 28 FX routes from the two operator gateways stranded after the payer's leg had moved, the lane sent every one
again about 90 s later, and the FX keeper's recovery then delivered 14 of the stranded routes as well: 14 traders paid
twice, 146.1084 SBXA and 27.8151 SBXB. And a 200 whose body said "failed" was marked paid.

So a retry needs PROOF that the payout reached nobody: a sentence a rail writes only when it can prove it (NO_FUNDS_MOVED,
NOT_DELIVERED and the siblings in _NO_MOVE), a refusal the dispatcher made before dispatching (an answer without its
"smart_send_method" wrapper), a 402, a 422 the store or the validator gave, or a connection that was never made.
Everything else holds, and so does any answer that says its outcome is not known (OUTCOME_UNKNOWN), whatever else it
quotes. "(origin refunded)" and "(source refunded)" are not proof: they say the PAYER got its money back, and a leg that
timed out may have paid the receiver first.

A held payout is released by hand after the ledger is read: status 'pending', attempts 0, rearm_count 0, tx_ref NULL
once nothing moved, or 'paid' when it went out; a held payout whose answer the store later shows as a success is marked
paid by the lane. §REPATLANE-5 (V0606): the inner endpoints keep a held answer under the key for 24 h and answer it again
(services/idempotency/cache.run_kept), so releasing one within that time also deletes its key's record in both scopes
(_SCOPES: idempotency@<the gateway's caller tag>:<scope>:<key>, services/idempotency/cache._cache_key), or the next send
replays the held answer and the credit holds again.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import httpx

PAID, RETRY, WAIT, SENDER_REFUSED, HOLD = "paid", "retry", "wait", "sender_refused", "hold"

# A refusal made before any money moved anywhere. The FX route's ingress refusal has said it since §FXSTRAND; V0603
# adds it to the dispatcher's, the cross-registry endpoint's, the FX booth's and the 2PC's refusals that can prove it.
NO_FUNDS_MOVED = "(no funds moved)"
# An FX route's payment reached nobody and nothing will deliver it later: the gateway refused it before its receiver
# leg and returned it to the payer (the route's fees stay spent, so it is not NO_FUNDS_MOVED).
NOT_DELIVERED = "(nothing reached the receiver)"
# A failure that may have moved money (a leg that timed out, a 5xx, an "in flight" answer). Checked before every proof:
# an answer that quotes a far side's refusal can carry a proof sentence that is not this payout's.
OUTCOME_UNKNOWN = "(outcome not known)"

# Sentences written only when the payout reached nobody (matched lower-cased, anywhere in the answer).
_NO_MOVE = (
    NO_FUNDS_MOVED,
    NOT_DELIVERED,
    "no funds were moved",              # the FX egress breaker, in front of the conversion
    "came back to you",                 # §LEDGERGATE V0602: the receiving frame's ledger was down, the route returned
    "ledger_unavailable:",              # §LEDGERGATE: the TEG's ledger gate refused before anything moved
    "registry temporarily overloaded",  # admission control shed the request before any handler ran
)
# Sentences that say money moved and is on its way, parked or split, or that nobody knows. Checked FIRST.
_MOVED = (
    OUTCOME_UNKNOWN,
    "the ingress is parked at the gateway",   # FxRouteStranded: the payer's leg moved, no refund was reported
    "failed post-conversion",                 # converted money parked for re-delivery to the receiver
    "partial commit",                         # the 2PC committed on one side only
    "core swap did not complete",
)
# A 2xx with one of these statuses is a payout that went out. "locked" and "initiated" are the async cross-frame rail:
# the lock moved the money and the saga settles it (or refunds the gateway after its timeout).
_SUCCESS = frozenset({"completed", "settled", "success", "initiated", "locked"})
_CLAIMED = ("is claimed on this endpoint", "already in progress")
_MISMATCH = "with a different request payload"
_PERM = re.compile(r"lacks required permission:\s*([a-z_.]+)")
_ROUTE = re.compile(r"route_id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
# routers/teg_send.py wraps every inner rail's non-2xx answer under this key; an answer without it is the dispatcher's
# own refusal (made before it dispatched) or a proxy's in front of it.
_WRAPPED = "smart_send_method"
# The connection was never made, so the request never reached the registry. A read timeout or a dropped answer is NOT
# here: the registry may be running the payout right now.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)
# The scopes the dispatcher's inner endpoints store their answers under (routers/teg_integration.py).
_SCOPES = ("teg.cross-registry-transfer", "teg.transfer")
# A credit's tx_ref after a retry starts with this, so a credit the lane attempted under V0603 can be told from one the
# lane before it attempted (whose attempts may include a payout that moved).
RETRY_PREFIX = "r|"


def never_sent(error: BaseException) -> bool:
    """True when the connection was never made, so the request reached nothing (the rails mark such a refusal with
    NO_FUNDS_MOVED). A read timeout or a dropped answer is False: the far side may be running it right now."""
    return isinstance(error, _NEVER_SENT)


@dataclass(frozen=True)
class Outcome:
    kind: str
    reason: str
    tx: str = ""  # paid: the transfer or route id; hold: the route the answer names, when it names one


def _text(response: Any) -> str:
    try:
        return str(getattr(response, "text", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _json(response: Any) -> dict:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def _tx_of(body: dict) -> str:
    for k in ("transfer_id", "transaction_id", "route_id", "transaction_hash"):
        v = body.get(k)
        if v:
            return str(v)
    return ""


def permission_refused(response: Any) -> Optional[str]:
    """The permission a 403 names when IRONKEY refused the SENDER (the gateway itself), else None."""
    if response is None or getattr(response, "status_code", None) != 403:
        return None
    m = _PERM.search(_text(response))
    return m.group(1) if m else None


def _failed_message(body: dict) -> Optional[str]:
    """The error_message of a 2xx body whose status is "failed" (the dispatcher's, or the inner endpoint's), else None."""
    if str(body.get("status", "") or "").strip().lower() != "failed":
        return None
    inner = body.get("detail") if isinstance(body.get("detail"), dict) else body
    return str((inner or {}).get("error_message") or "")


def answer_moved_nothing(answer: Any) -> bool:
    """§REPATLANE-5 (V0606): a 2xx answer that proves the payment reached nobody: status "failed" with NO_FUNDS_MOVED and
    no OUTCOME_UNKNOWN. A kept attempt gives its key back for such an answer (services/idempotency/cache.run_kept)."""
    if hasattr(answer, "model_dump"):
        try:
            answer = answer.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            return False
    msg = _failed_message(answer) if isinstance(answer, dict) else None
    low = (msg or "").lower()
    return msg is not None and NO_FUNDS_MOVED in low and OUTCOME_UNKNOWN not in low


def says_moved(detail: Any) -> bool:
    """An answer that says money moved, is parked, or that nobody knows (_MOVED): never a proof of anything."""
    low = (detail if isinstance(detail, str) else json.dumps(detail, default=str)).lower()
    return any(s in low for s in _MOVED)


def error_moved_nothing(status_code: int, detail: Any) -> bool:
    """§REPATLANE-5 (V0606): an error answer an endpoint gives AFTER it dispatched a payment, read as this lane reads one:
    True only when it proves the payment reached nobody (a _NO_MOVE sentence, or a 402), never when it says money moved or
    that nobody knows (_MOVED, checked first). A kept attempt gives its key back only for such an answer; any other is
    kept under the key and replayed (services/idempotency/cache.run_kept)."""
    low = (detail if isinstance(detail, str) else json.dumps(detail, default=str)).lower()
    if any(s in low for s in _MOVED):
        return False
    if any(s in low for s in _NO_MOVE):
        return True
    return int(status_code or 0) == 402


def _from_body(body: dict, where: str) -> Outcome:
    """A 2xx body (the dispatcher's answer, or the inner answer the idempotency store kept)."""
    st = str(body.get("status", "") or "").strip().lower()
    if st in _SUCCESS:
        return Outcome(PAID, st, _tx_of(body))
    msg = _failed_message(body)
    if msg is not None:
        if answer_moved_nothing(body):
            return Outcome(RETRY, f"{where}:failed, nothing moved")
        return Outcome(HOLD, f"{where}:failed: {msg[:60]}")
    return Outcome(HOLD, f"{where}:status {st or 'missing'}")


def classify(response: Any, error: Optional[BaseException]) -> Outcome:
    """One send's answer (`response`, or the transport `error` when there was none) as an Outcome."""
    if error is not None:
        name = type(error).__name__
        if never_sent(error):
            return Outcome(RETRY, f"transport:{name}, never sent")
        return Outcome(HOLD, f"transport:{name}")
    if response is None:
        return Outcome(HOLD, "no answer")
    code = int(getattr(response, "status_code", 0) or 0)
    text = _text(response)
    low = text.lower()
    if 200 <= code < 300:
        return _from_body(_json(response), "answer")
    for s in _MOVED:
        if s in low:
            m = _ROUTE.search(text)
            return Outcome(HOLD, f"http {code}: {s.strip('()')}", m.group(1) if m else "")
    if permission_refused(response):
        return Outcome(SENDER_REFUSED, "IRONKEY refused the gateway")
    if code == 422:
        if any(s in low for s in _CLAIMED):
            return Outcome(WAIT, "the key is claimed by an earlier send")
        if _MISMATCH in low:
            return Outcome(HOLD, "the key was used with another body")
        return Outcome(RETRY, "http 422, refused before dispatch")
    for s in _NO_MOVE:
        if s in low:
            return Outcome(RETRY, f"http {code}: {s.strip('():')}")
    if code == 402:
        return Outcome(RETRY, "http 402, the TEG refused before moving")
    if _WRAPPED not in text and 400 <= code < 500:
        return Outcome(RETRY, f"http {code}, the dispatcher refused before dispatching")
    m = _ROUTE.search(text)
    return Outcome(HOLD, f"http {code}" + (", a rail's refusal that does not say nothing moved"
                                           if _WRAPPED in text and code < 500 else ""), m.group(1) if m else "")


def classify_stored(stored: Any) -> Outcome:
    """The answer the idempotency store kept for a key (a success, or the async branch's answer): paid only when it
    says so, anything else holds."""
    return _from_body(stored if isinstance(stored, dict) else {}, "stored")


def stage_failure_outcome(response: Any, error: Optional[BaseException]) -> Outcome:
    """§DOCSFIX D6-776: the answer of a stage-through-the-payer transfer, read for the one decision that follows a
    failure: may the staged units go back to escrow and the step run again (RETRY), or may the transfer have paid the
    payee (HOLD)? Three sites stage a payout through the payer under a fresh escrow key and send it on with the payer's
    own POST /api/v1/teg/cross-registry-transfer under a stable key: services/contract_settlement.drive_release and
    routers/guild.py's verify and dispute payout. They took the staged units back after ANY failure, judging the
    transfer reversed when the payer still held them; a payer that holds other units passes that test, so a transfer
    that paid and then timed out, or answered that its outcome is not known, was reopened and could be paid again under
    the same stable key once the endpoint's 24 hours had passed.

    The call goes to the inner endpoint itself, never through /teg/send, so classify()'s reading of an unwrapped 4xx (the
    dispatcher's own refusal, made before it dispatched) does not hold here. RETRY needs proof:
      the connection was never made (never_sent)
      a 2xx "failed" that says nothing moved (answer_moved_nothing)
      an error answer that says nothing moved (error_moved_nothing: a _NO_MOVE sentence, or a 402; never with _MOVED)
      a refusal made before the endpoint ran: 401 (authentication), an IRONKEY 403 naming the permission the payer
      lacks, 429 (the rate limiter), a 422 from the request's validation (not the idempotency store's "claimed" or
      "different request payload" answers)
    Everything else is HOLD: a read timeout or a dropped answer, an answer that says money moved or that nobody knows, a
    2xx "failed" without the proof, any other error the endpoint gave. A 2xx that says the transfer went out is PAID."""
    if error is not None:
        name = type(error).__name__
        if never_sent(error):
            return Outcome(RETRY, f"transport:{name}, never sent")
        return Outcome(HOLD, f"transport:{name}")
    if response is None:
        return Outcome(HOLD, "no answer")
    code = int(getattr(response, "status_code", 0) or 0)
    if 200 <= code < 300:
        return _from_body(_json(response), "answer")
    text = _text(response)
    low = text.lower()
    for s in _MOVED:
        if s in low:
            return Outcome(HOLD, f"http {code}: {s.strip('()')}")
    if error_moved_nothing(code, text):
        return Outcome(RETRY, f"http {code}, nothing moved")
    if code == 401:
        return Outcome(RETRY, "http 401, refused before the endpoint ran")
    if permission_refused(response):
        return Outcome(RETRY, "http 403, IRONKEY refused the payer before the endpoint ran")
    if code == 429:
        return Outcome(RETRY, "http 429, the rate limiter refused before the endpoint ran")
    if code == 422 and not any(s in low for s in _CLAIMED) and _MISMATCH not in low:
        return Outcome(RETRY, "http 422, refused before the endpoint ran")
    return Outcome(HOLD, f"http {code}")


async def stored_answer(key: str, scopes: Tuple[str, ...] = _SCOPES, *, callers: Tuple[str, ...],
                        unscoped_reads: bool = False,
                        bodies: Optional[Tuple[dict, ...]] = None) -> Tuple[str, Optional[dict]]:
    """What the registry's idempotency store holds for a payout key, read WITHOUT claiming it (a plain GET; the cache's
    own lookup claims the key, which would block the next real send). `scopes`: the endpoints whose records count (by
    default both of the dispatcher's inner endpoints; a caller that knows which endpoint ran its send names that one).
    `callers`: whose records count (D6-777: a record is its caller's, services/idempotency/cache.agent_caller; the lane
    names the gateway it sends as). A record of the key written before records were the caller's names no caller: it is
    "unmatched", never an answer, unless `unscoped_reads` (a key only the send's own parties can derive, the A2A
    settlement's, whose earlier records are read as they were written). `bodies`: when given, the requests the key was
    used for: a record of another body under the key is not this send's and is passed over, as if the store held
    nothing for its caller (services/idempotency/cache.record_is_of; the A2A sweep, whose payer can derive its key).

      ("stored", answer)   a send under this key finished and stored its answer
      ("held", error)      §REPATLANE-5 (V0606): a send under this key ended with an answer that may have been the payment
                           (the inner endpoint kept it: {status_code, detail}); a send under the key gets it again
      ("claimed", None)    a send under this key started and stored nothing yet: still running, or it ended without an
                           answer and its claim has not expired
      ("unmatched", None)  the store holds a record of the key from before records were the caller's: nobody can say
                           whose send it was; never read as "none"
      ("none", None)       the store holds nothing under this key
      ("unknown", None)    the store could not be read; never read as "none"
    """
    if not key:
        return "none", None
    if not callers:
        raise ValueError("stored_answer needs the callers whose records count")
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        from agentvault_registry.services.idempotency.cache import _cache_key, _unscoped_cache_key, record_is_of
        redis = await get_redis()
        if redis is None:
            return "unknown", None
        claimed = unmatched = False
        for scope in scopes:
            recs = [(c, await redis.get(_cache_key(scope, key, c))) for c in callers]
            if all(raw is None for _c, raw in recs):
                raw = await redis.get(_unscoped_cache_key(scope, key))
                if raw is None:
                    continue
                if not unscoped_reads:
                    unmatched = True
                    continue
                recs = [(None, raw)]
            for caller, raw in recs:
                if raw is None:
                    continue
                rec = json.loads(raw)
                if bodies is not None and not record_is_of(rec, caller, bodies):
                    continue   # another request under the key: not this send's record
                if isinstance(rec, dict) and "response" in rec:
                    ans = rec.get("response")
                    return "stored", (ans if isinstance(ans, dict) else {})
                if isinstance(rec, dict) and "error" in rec:
                    err = rec.get("error")
                    return "held", (err if isinstance(err, dict) else {})
                claimed = True
        if claimed:
            return "claimed", None
        return ("unmatched" if unmatched else "none"), None
    except Exception:  # noqa: BLE001 — a read that could not be made is not an answer
        return "unknown", None


def hold_ref(key: str, reason: str, now: Optional[float] = None) -> str:
    """The tx_ref of a held credit: the key it was sent under, why it holds, and when (epoch seconds)."""
    why = re.sub(r"[|\s]+", " ", reason).strip()
    stamp = int(now if now is not None else time.time())
    return f"{key}|{why}"[:116] + f"|{stamp}"


def parse_hold_ref(tx_ref: Optional[str]) -> Tuple[str, str, Optional[int]]:
    """(key, reason, epoch) of a held credit's (or a claim's) tx_ref; ("", "", None) for anything else."""
    parts = str(tx_ref or "").split("|")
    if len(parts) < 3:
        return "", "", None
    try:
        stamp = int(parts[-1])
    except ValueError:
        return "", "", None
    return parts[0], "|".join(parts[1:-1]), stamp


def claim_nonce() -> str:
    """One pass's own mark, so a write after a send can only land on the rows THIS pass claimed."""
    return secrets.token_hex(4)


def claim_ref(key: str, nonce: str, now: Optional[float] = None) -> str:
    """The tx_ref of a credit claimed for a send ('sending' or 'batched'): the key, the pass's nonce, the claim time."""
    return hold_ref(key, f"claim {nonce}", now)


def retry_ref(reason: str, now: Optional[float] = None) -> str:
    """The tx_ref a credit carries after a retry (RETRY_PREFIX: an attempt V0603 proved moved nothing)."""
    return hold_ref(RETRY_PREFIX[:-1], reason, now)
