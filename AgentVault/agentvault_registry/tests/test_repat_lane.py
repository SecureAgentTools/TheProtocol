"""§REPATLANE (V0603): the AGORA gateway's payout lane, pass by pass (services/exchange_service.py).

The three flaws, each driven through the real pass against a strict double of the credits table (tests/_gateway_credits:
every statement applied with the WHERE clause the lane wrote) and a fake /teg/send:
  1. stranding: a credit at the attempt limit stayed 'pending' where nothing looked again. Now an attempt is spent only
     on an answer that proves nothing reached the trader, 'failed' at the limit on both passes, and the keeper's recon
     re-arms every size.
  2. paying twice: any failure was sent again (the store keeps only a success, so the same key ran again after its 90 s
     claim, and a re-formed bundle took a new key). Measured: 14 traders paid twice on the sandbox in three weeks. Now
     an answer that may have moved money holds the credit ('unresolved'), every send is claimed first under the pass's
     own nonce, every write after a send lands only on that claim, a claim left behind is settled by reading the store,
     and a credit the lane before V0603 attempted is held for a ledger read.
  3. a 200 whose body said "failed" was marked paid. Now it holds (or retries when the rail says nothing moved).
The races the review found (an overlapping pass releasing another's bundle; a late answer overwriting another pass's
hold) are driven here too. RED control: these tests fail against the tree before §REPATLANE.
"""
from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace

import httpx
import pytest

from agentvault_registry.services import exchange_service as svc
from agentvault_registry.services import payout_outcome as po
from agentvault_registry.services.idempotency import cache as svc_cache
from tests._gateway_credits import CreditsTable, credit

_RID = "6e062ba7-0f5e-4a3c-9d0e-6c1f2b3a4d5e"
_STRANDED = (f"FX route did not settle (route_id={_RID}) and the gateway did not report a refund; the ingress is "
             f"parked at the gateway: gateway unreachable")
_CLAIMED_422 = ("Idempotency-Key 'k' is claimed on this endpoint by an earlier request that has not stored a result: "
                "it is still in progress, or it ended without one")


class _Resp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def _wrapped(code, inner):
    return _Resp(code, {"detail": json.dumps({"smart_send_method": "fx", "via": "/api/v1/teg/cross-registry-transfer",
                                              "inner": inner})})


_PAID = _Resp(200, {"ok": True, "status": "completed", "transfer_id": _RID})
_FAILED_200 = _Resp(200, {"ok": True, "status": "failed", "transfer_id": _RID,
                          "detail": {"status": "failed", "error_message": "Partial commit - manual intervention required"}})
_INSUFFICIENT = _Resp(402, {"detail": "Insufficient balance"})


def _client(answer, seen):
    """A fake httpx.AsyncClient: each post records its key and calls `answer(json, headers)` (which may change the
    table, as another pass would while the send is in flight)."""
    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            seen.append({"key": (headers or {}).get("Idempotency-Key"), "json": json})
            out = answer(json, headers)
            if isinstance(out, BaseException):
                raise out
            return out
    return _C


@pytest.fixture
def lane(monkeypatch):
    """The lane's surroundings: no role heal, a dummy JWT, and an idempotency store the test fills (key -> answer)."""
    monkeypatch.setattr(svc, "_GATEWAY_ROLE_OK", True)
    import agentvault_registry.security as security
    monkeypatch.setattr(security, "create_access_token", lambda *a, **k: "jwt")
    store = {}

    async def _stored(key, scopes=None, *, callers, unscoped_reads=False):
        # D6-777: the lane reads the store as the gateway it sends as, and never takes a record from before as its own
        assert callers == (svc_cache.agent_caller(svc.GATEWAY_DID),) and not unscoped_reads
        return store.get(key, ("none", None))
    monkeypatch.setattr(po, "stored_answer", _stored)
    return store


def _table(*rows, batch=20):
    return CreditsTable(list(rows), dust=svc.REPAT_DUST, max_attempts=svc.REPAT_MAX_ATTEMPTS, batch=batch)


async def _credit_pass(monkeypatch, table, answer):
    seen = []
    monkeypatch.setattr(svc.httpx, "AsyncClient", _client(answer, seen))
    done = await svc.repatriate_gateway_credits(table)
    return done, seen


async def _bundle_pass(monkeypatch, table, answer):
    seen = []
    monkeypatch.setattr(svc.httpx, "AsyncClient", _client(answer, seen))
    done = await svc.repatriate_gateway_credits_aggregated(table)
    return done, seen


def _frags(*ids, amount="0.3", did="did:theprotocol:trader-x", **kw):
    return [credit(i, did=did, amount=amount, **kw) for i in ids]


# ── flaw 3: a 200 that says failed ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_200_whose_body_says_failed_is_not_paid(monkeypatch, lane):
    t = _table(credit(100))
    done, _ = await _credit_pass(monkeypatch, t, lambda j, h: _FAILED_200)
    r = t.rows[100]
    assert done == 0 and r.status == "unresolved" and r.paid_at is None and r.attempts == 0
    assert r.tx_ref.startswith("repat-100|")


@pytest.mark.asyncio
async def test_control_a_completed_200_is_paid(monkeypatch, lane):
    t = _table(credit(100))
    done, _ = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert done == 1 and t.rows[100].status == "paid" and t.rows[100].tx_ref == _RID


# ── flaw 2: never send again what may have moved ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer", [
    _wrapped(409, _STRANDED),
    httpx.ReadTimeout("45 s"),
    httpx.RemoteProtocolError("disconnected"),
    _Resp(500, {"detail": "Internal Server Error"}),
    # the direct FX booth refunded its sender after a credit leg whose outcome it cannot know (the review's case 1)
    _wrapped(409, "FX swap credit at destination failed (outcome not known) (credit key=k); the source was refunded: "
                  "dest TEG unreachable: timed out"),
    # the route's gateway refunded the payer after a local egress that timed out: the trader may have been paid
    _wrapped(409, f"FX route did not settle (route_id={_RID}); the gateway compensates pre-conversion / dead-letters "
                  f"post-conversion: it returned this payment (origin refunded)."),
    # a rail's refusal that does not say nothing moved
    _wrapped(400, "FX leg1 (source lock) failed: TEG 500"),
])
@pytest.mark.asyncio
async def test_an_answer_that_may_have_moved_holds_and_is_never_sent_again(monkeypatch, caplog, lane, answer):
    t = _table(credit(100))
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        await _credit_pass(monkeypatch, t, lambda j, h: answer)
    r = t.rows[100]
    assert r.status == "unresolved" and r.attempts == 0
    key, why, at = po.parse_hold_ref(r.tx_ref)
    assert key == "repat-100" and why and at
    assert [m for m in (x.getMessage() for x in caplog.records) if "HELD as 'unresolved'" in m]
    _done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == [] and t.rows[100].status == "unresolved", "a held credit is never sent again on its own"


@pytest.mark.parametrize("answer", [
    _wrapped(409, "FX swap refused at destination (source refunded) (no funds moved): fx_reserve solvency gate"),
    _wrapped(409, f"FX route did not settle (route_id={_RID}); the gateway compensates pre-conversion / dead-letters "
                  f"post-conversion: it returned this payment (origin refunded) (nothing reached the receiver)."),
    _wrapped(402, "FX route ingress failed (no funds moved): 2pc leg 402: Insufficient balance"),
    _INSUFFICIENT,
    httpx.ConnectError("refused"),
])
@pytest.mark.asyncio
async def test_an_answer_that_proves_nothing_reached_the_trader_retries(monkeypatch, lane, answer):
    t = _table(credit(100))
    await _credit_pass(monkeypatch, t, lambda j, h: answer)
    r = t.rows[100]
    assert (r.status, r.attempts) == ("pending", 1) and r.tx_ref.startswith(po.RETRY_PREFIX)
    _done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert [s["key"] for s in seen] == ["repat-100"] and t.rows[100].status == "paid"


@pytest.mark.asyncio
async def test_each_credit_is_claimed_under_this_passs_nonce_and_committed_before_its_send(monkeypatch, lane):
    t = _table(credit(100), credit(101), credit(102))
    states = []

    def answer(j, h):
        states.append(({r.status for r in t.rows.values()}, [r.tx_ref for r in t.rows.values()], t.commits))
        return _PAID
    await _credit_pass(monkeypatch, t, answer)
    statuses, refs, commits = states[0]
    assert statuses == {"sending"} and commits >= 1
    parsed = [po.parse_hold_ref(x) for x in refs]
    assert [p[0] for p in parsed] == ["repat-100", "repat-101", "repat-102"]
    assert len({p[1] for p in parsed}) == 1 and parsed[0][1].startswith("claim "), "one nonce for the pass"
    assert {r.status for r in t.rows.values()} == {"paid"}


# ── a claim left behind is read from the store, never sent again ────────────────────────────────────────────────────

def _stale_claim(key, nonce="dead0000"):
    """A claim older than the lane's stale limit (read when called, so a tree without the limit still collects)."""
    return po.claim_ref(key, nonce, time.time() - getattr(svc, "REPAT_CLAIM_STALE_S", 900) - 60)


@pytest.mark.parametrize("state,ans,want", [
    ("stored", {"status": "completed", "transfer_id": _RID}, "paid"),
    ("stored", {"status": "failed", "error_message": "Partial commit"}, "unresolved"),
    ("none", None, "unresolved"),
    ("claimed", None, "unresolved"),
    ("unmatched", None, "unresolved"),   # D6-777: a record from before records were the caller's is nobody's answer
    ("unknown", None, "unresolved"),
])
@pytest.mark.asyncio
async def test_a_stale_claim_is_settled_from_the_store_and_never_sent_again(monkeypatch, lane, state, ans, want):
    lane["repat-55"] = (state, ans)
    t = _table(credit(55, status="sending", tx_ref=_stale_claim("repat-55")))
    _done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == [] and t.rows[55].status == want
    if want == "paid":
        assert t.rows[55].tx_ref == _RID


@pytest.mark.asyncio
async def test_a_live_passs_claim_is_left_alone(monkeypatch, lane):
    # another pass claimed it a moment ago and is sending it now: neither held nor sent here
    young = po.claim_ref("repat-56", "live0000")
    t = _table(credit(56, status="sending", tx_ref=young))
    _done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == [] and (t.rows[56].status, t.rows[56].tx_ref) == ("sending", young)


@pytest.mark.parametrize("state,want", [("stored", "paid"), ("none", "unresolved")])
@pytest.mark.asyncio
async def test_a_bundle_claim_from_the_lane_before_v0603_is_settled_from_the_store(monkeypatch, lane, state, want):
    # the lane before V0603 claimed bundles with the bare key and re-sent them every cycle
    lane["repagg-aaaaaaaaaaaaaaaaaaaa"] = (state, {"status": "completed", "transfer_id": _RID} if state == "stored"
                                           else None)
    t = _table(*_frags(7, 8, status="batched", tx_ref="repagg-aaaaaaaaaaaaaaaaaaaa"))
    _done, seen = await _bundle_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == [] and {r.status for r in t.rows.values()} == {want}


@pytest.mark.asyncio
async def test_a_held_credit_whose_store_later_shows_a_success_is_paid(monkeypatch, lane):
    lane["repat-60"] = ("stored", {"status": "completed", "transfer_id": _RID})
    t = _table(credit(60, status="unresolved", tx_ref=po.hold_ref("repat-60", "transport:ReadTimeout")),
               credit(61, status="unresolved", tx_ref=po.hold_ref("repat-61", "http 500")))
    done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == [] and done == 1
    assert (t.rows[60].status, t.rows[60].tx_ref) == ("paid", _RID)
    assert t.rows[61].status == "unresolved", "nothing stored for 61: it stays held"


# ── flaw 1: no credit stranded at the attempt limit ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_connection_never_made_spends_an_attempt_and_fails_at_the_limit(monkeypatch, lane):
    t = _table(credit(100, attempts=svc.REPAT_MAX_ATTEMPTS - 1, tx_ref=po.retry_ref("http 402")))
    await _credit_pass(monkeypatch, t, lambda j, h: httpx.ConnectError("refused"))
    r = t.rows[100]
    assert (r.attempts, r.status) == (svc.REPAT_MAX_ATTEMPTS, "failed") and r.tx_ref.startswith(po.RETRY_PREFIX)


@pytest.mark.parametrize("prior", [None, "r|http 402: insufficient|1760000000"])
@pytest.mark.asyncio
async def test_a_claimed_key_waits_without_an_attempt_and_keeps_its_mark(monkeypatch, lane, prior):
    attempts = 0 if prior is None else 1
    t = _table(credit(100, attempts=attempts, tx_ref=prior))
    await _credit_pass(monkeypatch, t, lambda j, h: _wrapped(422, _CLAIMED_422))
    r = t.rows[100]
    assert (r.status, r.attempts, r.tx_ref) == ("pending", attempts, prior)


# ── the lane before V0603 ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_credit_the_lane_before_v0603_attempted_is_held_and_never_sent(monkeypatch, caplog, lane):
    t = _table(
        credit(1, attempts=3),                                   # pending, attempted, no mark
        credit(2, status="failed", attempts=6),                  # failed after six answers of any kind
        credit(3, attempts=0, rearm_count=2),                    # re-armed by the old recon to attempts 0
        credit(4, attempts=2, tx_ref=po.retry_ref("http 402")),  # attempted by V0603: sendable
        credit(5),                                               # never attempted: sendable
        credit(6, status="abandoned", attempts=6),               # left to the keeper (it never re-arms it)
    )
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        _done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert [t.rows[i].status for i in (1, 2, 3)] == ["unresolved"] * 3
    assert all(po.parse_hold_ref(t.rows[i].tx_ref)[0] == "" for i in (1, 2, 3)), "a legacy hold names no key"
    assert sorted(s["key"] for s in seen) == ["repat-4", "repat-5"]
    assert t.rows[6].status == "abandoned"
    said = [x.getMessage() for x in caplog.records if "attempted by the lane before V0603" in x.getMessage()]
    assert len(said) == 1 and said[0].startswith("[AGORA-repat] 3 credit(s)")
    await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert [t.rows[i].status for i in (1, 2, 3)] == ["unresolved"] * 3


# ── the per-credit pass, raced ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_answer_never_overwrites_what_another_pass_wrote_while_the_send_ran(monkeypatch, caplog, lane):
    t = _table(credit(100))
    other = po.hold_ref("repat-100", "unanswered send, nothing stored")

    def answer(j, h):
        # another pass found this claim (as stale) and held it while the send was in flight
        t.rows[100].status, t.rows[100].tx_ref = "unresolved", other
        return _wrapped(422, _CLAIMED_422)   # this pass's answer would put it back to 'pending'
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        await _credit_pass(monkeypatch, t, answer)
    assert (t.rows[100].status, t.rows[100].tx_ref) == ("unresolved", other)
    assert [x for x in caplog.records if "was not applied over it" in x.getMessage()]


@pytest.mark.asyncio
async def test_a_paid_answer_that_lost_its_claim_is_paid_later_from_the_store(monkeypatch, lane):
    t = _table(credit(100))

    def answer(j, h):
        t.rows[100].status = "unresolved"
        t.rows[100].tx_ref = po.hold_ref("repat-100", "unanswered send, nothing stored")
        lane["repat-100"] = ("stored", {"status": "completed", "transfer_id": _RID})
        return _PAID
    await _credit_pass(monkeypatch, t, answer)
    assert t.rows[100].status == "unresolved"
    _done, seen = await _credit_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == [] and t.rows[100].status == "paid"


# ── the aggregated pass ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_bundle_is_claimed_sent_once_and_paid(monkeypatch, lane):
    t = _table(*_frags(1, 2, 3))
    done, seen = await _bundle_pass(monkeypatch, t, lambda j, h: _PAID)
    assert done == 3 and [s["key"] for s in seen] == [svc._repat_bucket_key([1, 2, 3])]
    assert {r.status for r in t.rows.values()} == {"paid"}


@pytest.mark.asyncio
async def test_a_bundle_that_moved_nothing_spends_an_attempt_marks_it_and_fails_at_the_limit(monkeypatch, lane):
    mark = po.retry_ref("http 402")
    t = _table(*_frags(1, 2, 3, attempts=svc.REPAT_MAX_ATTEMPTS - 1, tx_ref=mark))
    await _bundle_pass(monkeypatch, t, lambda j, h: _INSUFFICIENT)
    assert {(r.status, r.attempts) for r in t.rows.values()} == {("failed", svc.REPAT_MAX_ATTEMPTS)}
    assert all(r.tx_ref.startswith(po.RETRY_PREFIX) for r in t.rows.values())


@pytest.mark.parametrize("answer", [_wrapped(409, _STRANDED), _FAILED_200, httpx.ReadTimeout("45 s")])
@pytest.mark.asyncio
async def test_a_bundle_that_may_have_moved_is_held_under_its_key(monkeypatch, lane, answer):
    t = _table(*_frags(1, 2, 3))
    await _bundle_pass(monkeypatch, t, lambda j, h: answer)
    key = svc._repat_bucket_key([1, 2, 3])
    assert {r.status for r in t.rows.values()} == {"unresolved"}
    assert {po.parse_hold_ref(r.tx_ref)[0] for r in t.rows.values()} == {key}
    _done, seen = await _bundle_pass(monkeypatch, t, lambda j, h: _PAID)
    assert seen == []


@pytest.mark.asyncio
async def test_a_waiting_bundle_goes_back_to_pending_without_an_attempt_and_keeps_its_marks(monkeypatch, lane):
    t = _table(credit(1, did="did:theprotocol:trader-x", amount="0.3"),
               credit(2, did="did:theprotocol:trader-x", amount="0.3", attempts=1, tx_ref=po.retry_ref("http 402")),
               credit(3, did="did:theprotocol:trader-x", amount="0.3", rearm_count=1, tx_ref=po.retry_ref("http 402")))
    await _bundle_pass(monkeypatch, t, lambda j, h: _wrapped(422, _CLAIMED_422))
    assert [(t.rows[i].status, t.rows[i].attempts) for i in (1, 2, 3)] == [("pending", 0), ("pending", 1), ("pending", 0)]
    assert t.rows[1].tx_ref is None
    assert t.rows[2].tx_ref.startswith(po.RETRY_PREFIX) and t.rows[3].tx_ref.startswith(po.RETRY_PREFIX)


@pytest.mark.asyncio
async def test_an_overlapping_pass_that_lost_the_claim_releases_nothing_and_sends_nothing(monkeypatch, lane):
    t = _table(*_frags(1, 2, 3))
    winner = po.claim_ref(svc._repat_bucket_key([1, 2, 3]), "winner00")

    def _the_other_pass_claims_first(table, ids):
        for i in ids:
            table.rows[i].status, table.rows[i].tx_ref = "batched", winner
    t.before_claim = _the_other_pass_claims_first
    done, seen = await _bundle_pass(monkeypatch, t, lambda j, h: _PAID)
    assert done == 0 and seen == []
    assert {(r.status, r.tx_ref) for r in t.rows.values()} == {("batched", winner)}, "the winner's claim is untouched"


@pytest.mark.asyncio
async def test_a_bundle_that_changed_under_its_claim_releases_only_the_rows_this_pass_took(monkeypatch, lane):
    t = _table(*_frags(1, 2, 3))
    other = po.claim_ref("repagg-other", "other000")

    def _the_other_pass_takes_one(table, ids):
        table.rows[2].status, table.rows[2].tx_ref = "batched", other
    t.before_claim = _the_other_pass_takes_one
    done, seen = await _bundle_pass(monkeypatch, t, lambda j, h: _PAID)
    assert done == 0 and seen == []
    assert [(t.rows[i].status, t.rows[i].tx_ref) for i in (1, 3)] == [("pending", None)] * 2
    assert (t.rows[2].status, t.rows[2].tx_ref) == ("batched", other)


@pytest.mark.asyncio
async def test_a_late_wait_does_not_release_a_bundle_another_pass_held(monkeypatch, caplog, lane):
    t = _table(*_frags(1, 2, 3))
    held = po.hold_ref(svc._repat_bucket_key([1, 2, 3]), "unanswered send, nothing stored")

    def answer(j, h):
        for r in t.rows.values():
            r.status, r.tx_ref = "unresolved", held
        return _wrapped(422, _CLAIMED_422)
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        await _bundle_pass(monkeypatch, t, answer)
    assert {(r.status, r.tx_ref) for r in t.rows.values()} == {("unresolved", held)}
    assert [x for x in caplog.records if "were settled by another pass" in x.getMessage()]


@pytest.mark.asyncio
async def test_fragments_the_lane_before_v0603_attempted_are_held_not_bundled(monkeypatch, lane):
    t = _table(*_frags(1, 2, attempts=2), *_frags(3, 4, did="did:theprotocol:trader-y", amount="0.4"))
    _done, seen = await _bundle_pass(monkeypatch, t, lambda j, h: _PAID)
    assert [t.rows[i].status for i in (1, 2)] == ["unresolved"] * 2
    assert [s["key"] for s in seen] == [svc._repat_bucket_key([3, 4])]


# ── the keeper's recon ──────────────────────────────────────────────────────────────────────────────────────────────

class _KeeperDB:
    """Records the keeper's statements with their bound values (the ORM's), and answers its selects with one id."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        try:
            bound = dict(stmt.compile().params)
        except Exception:  # noqa: BLE001 — a text() statement carries its values in `params`
            bound = {}
        bound.update(params or {})
        self.statements.append((sql, bound))
        if sql.startswith("SELECT"):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [1]), scalar_one=lambda: 0)
        return SimpleNamespace(rowcount=0)

    async def commit(self):
        pass


def _marked(sql, bound):
    """The statement keeps to V0603's marks: a LIKE on tx_ref bound to RETRY_PREFIX%."""
    return "tx_ref LIKE" in sql and po.RETRY_PREFIX + "%" in bound.values()


@pytest.mark.asyncio
async def test_recon_touches_only_credits_v0603_attempted_or_nobody_did(monkeypatch):
    from agentvault_registry.background_tasks import gateway_float_keeper as gk
    monkeypatch.setenv("GATEWAY_RECON_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_SUBDUST_SWEEP_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_REARM_ABANDONED_BATCH", "5")
    db = _KeeperDB()
    await gk.GatewayFloatKeeper()._reconcile(db)
    by = {}
    for sql, bound in db.statements:
        if sql.startswith("UPDATE exchange_gateway_credits SET status=:status") and "rearm_count >=" in sql:
            by["abandon"] = (sql, bound)
        elif sql.startswith("SELECT") and "rearm_count <" in sql:
            by["rearm_failed"] = (sql, bound)
        elif "SET status='abandoned'" in sql:
            by["sweep"] = (sql, bound)
        elif sql.startswith("SELECT") and "ORDER BY exchange_gateway_credits.amount DESC" in sql:
            by["rearm_abandoned"] = (sql, bound)
    assert set(by) == {"abandon", "rearm_failed", "sweep", "rearm_abandoned"}, list(by)
    assert "failed" in by["abandon"][1].values() and _marked(*by["abandon"])
    assert "failed" in by["rearm_failed"][1].values() and _marked(*by["rearm_failed"])
    assert "amount >=" not in by["rearm_failed"][0], "every size is re-armed"
    sql, bound = by["sweep"]
    assert "sum(o.amount)" in sql and "make_interval" in sql and "c.tx_ref LIKE :retry_mark" in sql
    assert "(c.attempts = 0 AND c.rearm_count = 0)" in sql and bound["retry_mark"] == po.RETRY_PREFIX + "%"
    sql, bound = by["rearm_abandoned"]
    assert "abandoned" in bound.values() and _marked(sql, bound)
    assert "exchange_gateway_credits.attempts =" in sql and "exchange_gateway_credits.rearm_count =" in sql


@pytest.mark.asyncio
async def test_the_keeper_owes_every_credit_still_owed_of_every_size():
    from agentvault_registry.background_tasks import gateway_float_keeper as gk
    db = _KeeperDB()
    await gk.GatewayFloatKeeper()._obligations(db)
    s = db.statements[-1][0]
    assert "IN (" in s and "amount >=" not in s
    assert set(svc.REPAT_OWED_STATUSES) == {"pending", "sending", "batched"}
