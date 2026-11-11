"""V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf (session-lead's option B, the sessions' room seq 2435): a
cross-registry settlement says what happened to it.

Found by V0658 (k)'s sandbox drive: with CROSS_REGISTRY_SETTLEMENT_DELIVERY unset (sbx-beta, and production's EU and
ASIA), core/settlement_origin named the internal federation proxy as the settlement's origin and callback, every peer
refused the slash request with 400 "Callback URL must belong to a registered peer registry", nothing moved, and the
settlement waited at PENDING_SLASH, was retried three times, refused the same way, and expired after 24 h (sbx-beta
settlement 24ca7222). The ruling said "Auto-mint will occur when slash is confirmed", while the payout is a transfer.

The flag stays the gate. Now:
  * off, or on with no address a stranger can dial: no request goes out, the settlement ends at once as NOT_DELIVERED
    and the ruling's compensation says why and that nothing moved;
  * on: the origin and the callback are the address the card publishes;
  * every peer refusing (a 4xx, 404 included) ends it at once as REFUSED with each peer's answer, first send and retry;
    a transport error or a 5xx keeps the retry; a retry with the flag now off sends nothing;
  * an administrator closes a settlement no peer holds (POST .../settlements/{id}/close, a reason required), the
    confirmation's claim refuses the three new end states, and the saga sweep leaves them alone;
  * the delivered ruling names a transfer from the payout funding, never a mint.
Each test imports what it needs itself, so on 4b79322d7 they fail one by one (the control).
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

PUBLIC = "https://sandbox-b.theprotocol.cloud:8443"
INTERNAL = "http://sbx-beta-nginx-federation:8443"
REFUSAL = '{"detail":"Callback URL must belong to a registered peer registry: its address sbx-beta-nginx-federation:8443"}'
# our mTLS client certificate (svid_client.get_client_cert_config); the peers below are https, so a request goes out
# only with it (V0660 (k) review item 1)
CERT = {"cert": ("/certs/svid.0.pem", "/certs/svid.0.key"), "verify": "/certs/bundle.0.pem"}


@pytest.fixture
def origin(monkeypatch):
    mod = importlib.import_module("agentvault_registry.core.settlement_origin")
    monkeypatch.setattr(mod.settings, "FEDERATION_BASE_URL", INTERNAL, raising=False)
    monkeypatch.setenv("FEDERATION_BASE_URL", INTERNAL)
    monkeypatch.setenv("BILATERAL_PEER_URL", PUBLIC)
    monkeypatch.delenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", raising=False)
    return mod


# ─── the doubles ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, code: int, text: str = ""):
        self.status_code, self.text = code, text

    def json(self):
        return {}


def _client(answers, sent):
    """httpx.AsyncClient answering each POST by the peer it goes to (`answers`: peer url -> (code, text) or an
    exception), recording (url, payload)."""
    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent.append((url, json))
            answer = next(v for k, v in answers.items() if url.startswith(k))
            if isinstance(answer, Exception):
                raise answer
            return _Resp(*answer)
    return _Client


ATTEMPTS: list = []      # every client a no-send test saw made (the senders catch exceptions, so a raise is not enough)


def _no_client():
    ATTEMPTS.clear()

    class _Never:
        def __init__(self, **kw):
            ATTEMPTS.append(kw)
            raise AssertionError("a request went out")
    return _Never


class _Peer:
    def __init__(self, name, url):
        self.name, self.base_url, self.status, self.federation_access_token = name, url, "ACTIVE", None


ALPHA = _Peer("Sandbox Alpha", "https://sandbox-a.theprotocol.cloud:8443")
OP = _Peer("sbxbetaop", "https://sbxbetaop.op.theprotocol.cloud:8443")


class _Rows:
    def __init__(self, rows):
        self.rows, self.rowcount = rows, 1

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, rows):
        self.rows, self.added, self.commits = rows, [], 0

    async def execute(self, stmt, *a, **k):
        return _Rows(self.rows)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def refresh(self, row):
        pass

    async def rollback(self):
        pass


class _Dispute:
    id, complainant_did, defendant_did = 50, "did:c", "did:d"


received: list = []     # what the emitter double was handed (tests/test_doubles_assert_receipt: a double asserts receipt)


def _wire_first_send(monkeypatch, answers=None, sent=None, cert=True):
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.identity import svid_client

    received.clear()

    class _Emitter:
        async def emit_dispute_compensation_request(self, **kw):
            received.append(kw)
            return True
    monkeypatch.setattr(cd, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(svid_client, "get_client_cert_config", lambda *a, **k: dict(CERT) if cert else None)
    monkeypatch.setattr(cd.httpx, "AsyncClient", _no_client() if answers is None else _client(answers, sent))
    return cd


def _first_send(monkeypatch, peers, answers=None, sent=None, cert=True):
    cd = _wire_first_send(monkeypatch, answers, sent, cert)
    db = _Db(peers)
    out = asyncio.run(cd._process_cross_registry_compensation(db, _Dispute(), "IN_FAVOR_OF_COMPLAINANT", 3, {}))
    (settlement,) = db.added
    return out, settlement


class _Settlement:
    def __init__(self, held=""):
        self.id, self.dispute_id, self.ruling, self.requested_amount = "24ca7222", 50, "IN_FAVOR_OF_COMPLAINANT", 3
        self.complainant_did, self.defendant_did = "did:c", "did:d"
        self.origin_registry_url = PUBLIC
        self.callback_url = PUBLIC + "/api/v1/federation/disputes/slash-confirmation"
        self.defendant_registry_url, self.error_message, self.status = held, None, "PENDING_SLASH"
        self.saga_state, self.saga_last_step_at = "INITIATED", None


def _retry(monkeypatch, settlement, peers, answers=None, sent=None, cert=True):
    from agentvault_registry.tasks import settlement_reconciliation as rec
    monkeypatch.setattr(rec.httpx, "AsyncClient", _no_client() if answers is None else _client(answers, sent))
    monkeypatch.setattr(rec.svid_client, "get_client_cert_config", lambda *a, **k: dict(CERT) if cert else None)
    asyncio.run(rec._retry_slash_request(_Db(peers), settlement, 1))
    return settlement


# ─── (a) off: nothing goes out, and the ruling says so ───────────────────────────────────────────────────────────────

def test_off_no_request_goes_out_and_the_settlement_ends_not_delivered(origin, monkeypatch):
    out, s = _first_send(monkeypatch, [ALPHA, OP])            # _no_client: any request fails the test
    assert ATTEMPTS == []
    assert s.status == "NOT_DELIVERED" and s.defendant_registry_url == ""
    assert "CROSS_REGISTRY_SETTLEMENT_DELIVERY" in s.error_message and "Nothing moved" in s.error_message
    assert out["settlement_status"] == "not_delivered" and out["settlement_id"] == s.id
    assert "CROSS_REGISTRY_SETTLEMENT_DELIVERY is off" in out["reason"] and "Nothing moved" in out["reason"]
    assert "retried" not in out["reason"] and "mint" not in out["reason"].lower()
    # the public record of the ruling is still written (no balance effect), naming the dispute and the amount
    assert len(received) == 1 and received[0]["dispute_id"] == 50 and received[0]["amount"] == 3, received
    assert received[0]["ruling"] == "IN_FAVOR_OF_COMPLAINANT"


def test_off_the_saga_sweep_and_the_reconciliation_leave_it_alone(origin):
    from agentvault_registry.core import settlement_origin
    from agentvault_registry.services import settlement_saga
    assert {"NOT_DELIVERED", "REFUSED", "CLOSED"} <= set(settlement_saga.DECIDED_STATUSES)
    assert set(settlement_origin.ENDED) == {"NOT_DELIVERED", "REFUSED", "CLOSED"}
    from agentvault_registry.tasks import settlement_reconciliation as rec
    src = inspect.getsource(rec.reconcile_pending_settlements)
    assert '.in_(["PENDING_SLASH", "SLASHING"])' in src        # an ended settlement is never picked up again


# ─── (b) on: the public address; on with none dialable: nothing goes out ─────────────────────────────────────────────

def test_on_the_request_names_the_public_address_as_origin_and_callback(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    sent = []
    out, s = _first_send(monkeypatch, [ALPHA], {ALPHA.base_url: (202, "{}")}, sent)
    ((url, payload),) = sent
    assert url == ALPHA.base_url + "/api/v1/federation/disputes/slash-request"
    assert payload["origin_registry_url"] == PUBLIC and s.origin_registry_url == PUBLIC
    assert payload["callback_url"] == PUBLIC + "/api/v1/federation/disputes/slash-confirmation"
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ALPHA.base_url
    assert out["settlement_status"] == "pending_remote_slash"


def test_on_without_a_dialable_address_nothing_goes_out_and_it_says_why(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    monkeypatch.setenv("BILATERAL_PEER_URL", "http://agentvault_registry_test:8000")   # a docker name
    out, s = _first_send(monkeypatch, [ALPHA])
    assert ATTEMPTS == []
    assert s.status == "NOT_DELIVERED" and out["settlement_status"] == "not_delivered"
    assert "no federation address a peer can dial" in s.error_message
    assert "no federation address a peer can dial" in out["reason"] and "Nothing moved" in out["reason"]


def test_the_helper_says_why_a_request_cannot_go(origin, monkeypatch):
    assert "CROSS_REGISTRY_SETTLEMENT_DELIVERY is off" in origin.why_not_delivered()
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    assert origin.why_not_delivered() is None and origin.origin_url() == PUBLIC
    monkeypatch.setenv("BILATERAL_PEER_URL", "")
    monkeypatch.setenv("FEDERATION_BASE_URL", "http://sbx-beta-nginx-federation:8443")
    assert "no federation address a peer can dial" in origin.why_not_delivered()


# ─── (c) every peer refusing ends it visibly; a transport error or a 5xx retries ─────────────────────────────────────

def test_every_peer_refusing_ends_it_refused_with_each_answer(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    sent = []
    out, s = _first_send(monkeypatch, [ALPHA, OP], {ALPHA.base_url: (400, REFUSAL), OP.base_url: (404, "")}, sent)
    assert len(sent) == 2
    assert s.status == "REFUSED" and s.defendant_registry_url == ""
    assert "Sandbox Alpha 400: Callback URL must belong to a registered peer registry" in s.error_message
    assert "sbxbetaop 404" in s.error_message and "Nothing moved" in s.error_message
    assert out["settlement_status"] == "refused" and "Sandbox Alpha 400" in out["reason"]
    assert "retried" not in out["reason"] and "Nothing moved" in out["reason"]


@pytest.mark.parametrize("second", [(503, "unavailable"), httpx.ConnectError("refused")])
def test_a_transport_error_or_a_5xx_keeps_the_retry(origin, monkeypatch, second):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    out, s = _first_send(monkeypatch, [ALPHA, OP], {ALPHA.base_url: (400, REFUSAL), OP.base_url: second}, [])
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ""
    assert out["settlement_status"] == "pending_remote_slash" and "retried" in out["reason"]
    assert "Nothing has moved" in out["reason"]


def test_a_retry_every_peer_refuses_ends_it_refused(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    s = _retry(monkeypatch, _Settlement(), [ALPHA, OP], {ALPHA.base_url: (400, REFUSAL), OP.base_url: (404, "")}, [])
    assert s.status == "REFUSED" and s.defendant_registry_url == ""
    assert s.error_message.startswith("retry_count=2, ")
    assert "Sandbox Alpha 400: Callback URL must belong" in s.error_message and "sbxbetaop 404" in s.error_message


@pytest.mark.parametrize("second", [(502, "bad gateway"), httpx.ReadTimeout("slow")])
def test_a_retry_with_a_transport_error_or_a_5xx_stays_pending(origin, monkeypatch, second):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    s = _retry(monkeypatch, _Settlement(), [ALPHA, OP], {ALPHA.base_url: (400, REFUSAL), OP.base_url: second}, [])
    assert s.status == "PENDING_SLASH" and s.error_message.startswith("retry_count=2, ")


def test_a_retry_records_the_registry_it_asks_while_the_request_is_open(origin, monkeypatch):
    """the defendant's home calls the confirmation back while it is still answering; a confirmation is accepted only
    from the registry recorded (as the first send does)"""
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    s = _Settlement()
    seen = []

    class _C:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            seen.append(s.defendant_registry_url)
            return _Resp(404 if url.startswith(ALPHA.base_url) else 202)
    from agentvault_registry.tasks import settlement_reconciliation as rec
    monkeypatch.setattr(rec.httpx, "AsyncClient", _C)
    monkeypatch.setattr(rec.svid_client, "get_client_cert_config", lambda *a, **k: dict(CERT))
    asyncio.run(rec._retry_slash_request(_Db([ALPHA, OP]), s, 1))
    assert seen == [ALPHA.base_url, OP.base_url] and s.defendant_registry_url == OP.base_url


def test_a_retry_with_the_flag_now_off_sends_nothing_and_ends_not_delivered(origin, monkeypatch):
    s = _retry(monkeypatch, _Settlement(), [ALPHA, OP])          # _no_client: any request fails the test
    assert ATTEMPTS == []
    assert s.status == "NOT_DELIVERED"
    assert "CROSS_REGISTRY_SETTLEMENT_DELIVERY is off" in s.error_message and "Nothing moved" in s.error_message


def test_a_retry_with_the_flag_now_off_leaves_a_settlement_a_home_holds_waiting(origin, monkeypatch):
    """a home that holds the request may still slash and confirm: it is never ended under it, and nothing is sent"""
    s = _retry(monkeypatch, _Settlement(held=ALPHA.base_url), [ALPHA, OP])
    assert ATTEMPTS == []
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ALPHA.base_url


# ─── (d) an administrator closes what no peer holds; the confirmation's claim refuses the end states ─────────────────

ADMIN = SimpleNamespace(id=6, email="admin@example.test")


class _CloseDb:
    def __init__(self, row):
        self.row, self.commits, self.statements, self.log = row, 0, [], []

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: self.row)

    async def commit(self):
        self.commits += 1
        self.log.append(("commit", getattr(self.row, "status", None)))

    async def refresh(self, row):
        self.log.append(("refresh", row.status))

    async def rollback(self):
        self.log.append(("rollback", getattr(self.row, "status", None)))


def _row(status="REFUSED", held=""):
    return SimpleNamespace(id="24ca7222", dispute_id=50, status=status, defendant_registry_url=held,
                           error_message="Refused by every peer registry: Sandbox Alpha 400", saga_state="INITIATED",
                           saga_last_step_at=None, origin_registry_url=PUBLIC, requested_amount=Decimal("3"))


def _close(monkeypatch, row, reason="the peers never knew this address", slash=None, audit_raises=None):
    """`slash`: what the event store check finds (None: nothing; a dict: a DisputeSlash; an exception: raised, an event
    store that cannot be read). `audit_raises`: the admin audit write fails."""
    from agentvault_registry.routers import federation_disputes as fd
    from agentvault_registry.tasks import settlement_reconciliation as rec
    audited, asked = [], []

    async def audit(db, **kw):
        db.log.append(("audit", row.status))
        if audit_raises:
            raise audit_raises
        audited.append(kw)

    async def find(settlement):
        asked.append(settlement.id)
        if isinstance(slash, Exception):
            raise slash
        return slash
    from agentvault_registry.services import admin_audit
    monkeypatch.setattr(admin_audit, "log_admin_action", audit)
    monkeypatch.setattr(rec, "find_slash_on_eventstore", find, raising=False)
    db = _CloseDb(row)
    _close.asked = asked
    out = asyncio.run(fd.close_settlement(row.id if row else "nope", fd.SettlementCloseBody(reason=reason),
                                          current_admin=ADMIN, db=db))
    return out, db, audited


@pytest.mark.parametrize("status", ["REFUSED", "NOT_DELIVERED", "PENDING_SLASH", "EXPIRED", "FAILED"])
def test_an_administrator_closes_a_settlement_no_peer_holds(monkeypatch, status):
    row = _row(status)
    out, db, audited = _close(monkeypatch, row)
    assert row.status == "CLOSED" and out["status"] == "CLOSED" and db.commits >= 1
    assert "Closed by admin admin@example.test" in row.error_message
    assert "the peers never knew this address" in row.error_message and f"was {status}" in row.error_message
    (a,) = audited
    assert a["action"] == "federation.settlement.closed" and a["actor_id"] == "6" and a["target_id"] == "24ca7222"
    assert a["details"]["reason"] == "the peers never knew this address" and a["details"]["previous_status"] == status


def test_a_settlement_a_peer_holds_is_not_closed(monkeypatch):
    row = _row("PENDING_SLASH", held=ALPHA.base_url)
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, row)
    assert e.value.status_code == 409 and row.status == "PENDING_SLASH"
    assert "holds this settlement's slash request" in str(e.value.detail)


@pytest.mark.parametrize("status", ["SETTLED", "COMPENSATING", "SLASHED", "SLASHING", "CLOSED"])
def test_a_settlement_that_moved_or_is_moving_or_is_closed_is_not_closed(monkeypatch, status):
    row = _row(status)
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, row)
    assert e.value.status_code == 409 and row.status == status and f"is {status}" in str(e.value.detail)


def test_closing_a_settlement_that_does_not_exist_is_404(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, None)
    assert e.value.status_code == 404 and "Settlement not found" in str(e.value.detail)


def test_a_close_needs_a_reason():
    from pydantic import ValidationError
    from agentvault_registry.routers import federation_disputes as fd
    for bad in ("", "   "):
        with pytest.raises(ValidationError):
            fd.SettlementCloseBody(reason=bad)
    with pytest.raises(ValidationError):
        fd.SettlementCloseBody(reason="x" * 501)


def test_the_close_route_is_an_admin_enforcement_route():
    from agentvault_registry.routers import federation_disputes as fd
    route = next(r for r in fd.router.routes if getattr(r, "path", "") == "/api/v1/federation/disputes/settlements/{settlement_id}/close")
    assert route.methods == {"POST"}
    src = inspect.getsource(fd.close_settlement)
    assert 'require_admin_flag("admin_enforcement")' in src and ".with_for_update()" in src


@pytest.mark.parametrize("status", ["CLOSED", "NOT_DELIVERED", "REFUSED"])
def test_the_confirmations_claim_refuses_the_end_states(monkeypatch, status):
    """a confirmation for a closed or undelivered settlement pays nothing (the claim excluded only SETTLED and
    COMPENSATING, so a confirmation would have paid a closed settlement)"""
    from agentvault_registry.routers import federation_disputes as fd
    from agentvault_registry.services import federation_license_gate as gate
    paid = []

    async def nothing(*a, **k):
        return None
    monkeypatch.setattr(gate, "assert_federation_peer_not_quarantined", nothing)
    monkeypatch.setattr(fd, "_bind_confirmation_to_caller", lambda *a, **k: None)
    from agentvault_registry.services import reward_funding
    monkeypatch.setattr(reward_funding, "fund_reward_via_waterfall", lambda *a, **k: paid.append(1))
    row = _row(status)
    row.complainant_did, row.defendant_did, row.callback_url = "did:c", "did:d", ""

    class _Db2:
        def __init__(self):
            self.updates = 0

        async def execute(self, stmt, *a, **k):
            if type(stmt).__name__ == "Update":
                self.updates += 1
            return SimpleNamespace(scalar_one_or_none=lambda: row if "cross_registry" in str(stmt) else None,
                                   rowcount=1)

        async def commit(self):
            pass

        async def rollback(self):
            pass
    db = _Db2()
    conf = fd.SlashConfirmation(settlement_id=row.id, status="slashed", amount=3, slash_tx_id="t")
    with pytest.raises(HTTPException) as e:
        asyncio.run(fd.receive_slash_confirmation(conf, "spiffe://x/service/registry", db))
    assert e.value.status_code == 409 and status in str(e.value.detail)
    assert paid == [] and db.updates == 0 and row.status == status


def test_the_claim_statement_excludes_every_end_state():
    from agentvault_registry.core import settlement_origin
    from agentvault_registry.routers import federation_disputes as fd
    assert {"SETTLED", "COMPENSATING", *settlement_origin.ENDED} <= set(fd.UNCLAIMABLE)
    assert "CrossRegistrySettlement.status.notin_(UNCLAIMABLE)" in inspect.getsource(fd.receive_slash_confirmation)


# ─── (e) the delivered ruling names a transfer, never a mint ─────────────────────────────────────────────────────────

def test_the_delivered_ruling_names_a_transfer_from_the_payout_funding(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    out, _s = _first_send(monkeypatch, [ALPHA], {ALPHA.base_url: (202, "{}")}, [])
    reason = out["reason"]
    assert "payout funding" in reason and "transfer" in reason and "mint" not in reason.lower()
    from agentvault_registry.crud import crud_disputes as cd
    for fn in (cd.process_compensation, cd._process_cross_registry_compensation):
        assert "auto-mint" not in (fn.__doc__ or "").lower(), fn.__name__


def test_the_parties_hear_the_cross_registry_words(monkeypatch):
    from agentvault_registry.services import dispute_settlement as ds
    heard = []

    async def notify(event, dids, **kw):
        heard.append(kw["message"])

    import agentvault_registry.background_tasks.push_notify as pn
    monkeypatch.setattr(pn, "notify_agent_owners", notify)
    d = SimpleNamespace(id=50, ruling="IN_FAVOR_OF_COMPLAINANT", ruling_note=None, complainant_did="did:c",
                        defendant_did="did:d")

    async def go():
        ds.notify_ruled(d, {"applied": False, "cross_registry": True, "settlement_status": "not_delivered",
                            "reason": "Cross-registry: no slash request was sent. Nothing moved."})
        await asyncio.sleep(0)
    asyncio.run(go())
    assert heard and "no slash request was sent. Nothing moved." in heard[0]


# ─── the settlements list counts the new states ──────────────────────────────────────────────────────────────────────

def test_the_list_counts_the_new_states():
    from agentvault_registry.routers import federation_disputes as fd
    rows = [SimpleNamespace(id=str(i), status=st, requested_amount=Decimal("1"), slashed_amount=Decimal("0"),
                            minted_amount=Decimal("0"), dispute_id=i, complainant_did="c", defendant_did="d",
                            ruling="IN_FAVOR_OF_COMPLAINANT", origin_registry_url=PUBLIC, defendant_registry_url="",
                            callback_url="", slash_tx_id="", mint_tx_id="", requested_at=None, slashed_at=None,
                            settled_at=None, error_message=None, saga_state="INITIATED", saga_timeout_at=None)
            for i, st in enumerate(["NOT_DELIVERED", "REFUSED", "REFUSED", "CLOSED", "SETTLED"])]

    class _ListDb:
        async def execute(self, stmt, *a, **k):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))
    out = asyncio.run(fd.list_settlements(None, db=_ListDb(), current_developer=ADMIN))
    st = out["stats"]
    assert (st["not_delivered"], st["refused"], st["closed"], st["settled"]) == (1, 2, 1, 1)
    assert [s["closable"] for s in out["settlements"]] == [True, True, True, False, False]


# ─── the MCP tool beside approve and reject ──────────────────────────────────────────────────────────────────────────

def test_close_dispute_settlement_is_wired_like_its_siblings():
    from agentvault_registry.mcp import audit, server, tool_categories, tools_developer
    name = "theprotocol_closeDisputeSettlement"
    assert server.TOOL_DISPATCH[name] is tools_developer.close_dispute_settlement
    assert name in server.TIER3_TOOLS and name in audit._TIER_3_TOOLS
    assert tool_categories.PUBLIC_TOOL_CATEGORIES["closeDisputeSettlement"] == "payments-a2a"
    (schema,) = [t for t in server.ALL_TOOL_SCHEMAS if t["name"] == name]
    props = schema["inputSchema"]["properties"]
    assert schema["inputSchema"]["required"] == ["settlement_id", "reason"]
    assert props["reason"]["maxLength"] == 500 and props["reason"]["minLength"] == 1
    assert schema["description"].startswith("DESTRUCTIVE")
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    assert derive_annotations(name)["destructiveHint"] is True


def test_close_dispute_settlement_posts_the_reason_to_the_route(monkeypatch):
    from agentvault_registry.mcp import tools_developer as T
    seen = []

    async def dev(auth, method, path, json_body=None, **kw):
        seen.append((method, path, json_body))
        return {"status": "CLOSED"}
    monkeypatch.setattr(T, "_dev_request", dev)
    out = asyncio.run(T.close_dispute_settlement(object(), "24ca7222", "the peers never knew this address"))
    assert out == {"status": "CLOSED"}
    assert seen == [("POST", "/api/v1/federation/disputes/settlements/24ca7222/close",
                     {"reason": "the peers never knew this address"})]
    assert "error" in asyncio.run(T.close_dispute_settlement(object(), "24ca7222", ""))


def test_the_testers_contracts_know_the_tool():
    from agentvault_registry.api_tests.contracts import earned_agent_public as EAP
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    name = "theprotocol_closeDisputeSettlement"
    c = MCP_CONTRACTS[name]
    assert c.tier == "3" and c.expect_status == "error_4xx" and "Settlement not found" in c.expect_error_message_contains
    assert name in {t for t, _, _ in EAP.NOT_DRIVEN}
    rows = {t: (a, codes, words) for t, a, _w, codes, words in EAP.not_driven_refusals(SimpleNamespace(sentinel_did=""))}
    args, codes, words = rows[name]
    assert codes == (404,) and words == ("settlement not found",) and args["reason"]


# ─── the review of 0d6b7ff9e (session-code, before hand-in) ──────────────────────────────────────────────────────────
# (1) a 4xx that is not a final answer keeps the retry; no request goes out without our mTLS client certificate

@pytest.mark.parametrize("code", [408, 425, 429])
def test_a_4xx_that_is_not_a_final_answer_keeps_the_first_send_waiting(origin, monkeypatch, code):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    out, s = _first_send(monkeypatch, [ALPHA, OP], {ALPHA.base_url: (404, ""), OP.base_url: (code, "later")}, [])
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ""
    assert out["settlement_status"] == "pending_remote_slash" and "retried" in out["reason"]
    assert f"sbxbetaop {code}" in s.error_message


@pytest.mark.parametrize("code", [408, 425, 429])
def test_a_4xx_that_is_not_a_final_answer_keeps_the_retry(origin, monkeypatch, code):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    s = _retry(monkeypatch, _Settlement(), [ALPHA, OP], {ALPHA.base_url: (400, REFUSAL), OP.base_url: (code, "")}, [])
    assert s.status == "PENDING_SLASH" and s.error_message.startswith("retry_count=2, ")


def test_the_definite_refusal_rule_leaves_out_the_retryable_4xx(origin):
    assert [c for c in (400, 401, 403, 404, 409, 410, 422) if not origin.is_definite_refusal(c)] == []
    assert [c for c in (408, 425, 429, 500, 502, 503, 504) if origin.is_definite_refusal(c)] == []


def test_without_our_client_certificate_the_first_send_sends_nothing_and_waits(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    out, s = _first_send(monkeypatch, [ALPHA, OP], cert=False)      # _no_client: any request fails the test
    assert ATTEMPTS == []
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ""
    assert "mTLS client certificate" in s.error_message and "Nothing has moved" in s.error_message
    assert out["settlement_status"] == "pending_remote_slash"
    assert "mTLS client certificate" in out["reason"] and "Nothing has moved" in out["reason"]


def test_without_our_client_certificate_a_retry_sends_nothing_and_spends_no_attempt(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    s = _Settlement()
    s.error_message = "retry_count=1, last_retry=2026-11-08T10:00:00+00:00"
    _retry(monkeypatch, s, [ALPHA, OP], cert=False)                   # _no_client: any request fails the test
    assert ATTEMPTS == []
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ""
    assert s.error_message.startswith("retry_count=1, ") and "mTLS client certificate" in s.error_message


# (2) a close never ends a settlement a peer may have slashed: the reconciliation's own event store check first

SLASH = {"event_id": "e1", "amount": 3, "slash_tx_id": "dispute-slash-50-abcd", "defendant_did": "did:d"}


@pytest.mark.parametrize("status", ["PENDING_SLASH", "EXPIRED", "FAILED"])
def test_a_close_asks_the_event_store_first_and_closes_when_it_finds_no_slash(monkeypatch, status):
    row = _row(status)
    out, _db, _a = _close(monkeypatch, row)
    assert _close.asked == ["24ca7222"] and row.status == "CLOSED" and out["status"] == "CLOSED"


@pytest.mark.parametrize("status", ["NOT_DELIVERED", "REFUSED"])
def test_a_settlement_no_request_reached_closes_without_the_event_store(monkeypatch, status):
    row = _row(status)
    out, _db, _a = _close(monkeypatch, row, slash=RuntimeError("the store is down"))
    assert _close.asked == [] and row.status == "CLOSED" and out["status"] == "CLOSED"


@pytest.mark.parametrize("status", ["PENDING_SLASH", "EXPIRED", "FAILED"])
def test_a_slash_on_the_event_store_refuses_the_close(monkeypatch, status):
    row = _row(status)
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, row, slash=dict(SLASH))
    assert e.value.status_code == 409 and row.status == status
    detail = str(e.value.detail)
    assert "DisputeSlash" in detail and "dispute-slash-50-abcd" in detail and "not closed" in detail


def test_a_slash_found_for_a_waiting_settlement_names_the_reconciliation_that_pays_it(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, _row("PENDING_SLASH"), slash=dict(SLASH))
    assert "reconciliation pays the complainant" in str(e.value.detail)


@pytest.mark.parametrize("status", ["PENDING_SLASH", "EXPIRED"])
def test_an_event_store_that_cannot_be_read_refuses_the_close(monkeypatch, status):
    from agentvault_registry.tasks import settlement_reconciliation as rec
    row = _row(status)
    unreadable = getattr(rec, "EventStoreUnreadable", RuntimeError)("the event store answered 503")
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, row, slash=unreadable)
    assert e.value.status_code == 503 and row.status == status
    assert "event store" in str(e.value.detail) and "not closed" in str(e.value.detail)


def test_a_settlement_that_records_no_origin_is_not_closed_blind(monkeypatch):
    row = _row("PENDING_SLASH")
    row.origin_registry_url = ""
    with pytest.raises(HTTPException) as e:
        _close(monkeypatch, row)
    assert e.value.status_code == 409 and row.status == "PENDING_SLASH" and "origin" in str(e.value.detail)


class _EsResp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


def _es(monkeypatch, answer):
    from agentvault_registry.tasks import settlement_reconciliation as rec

    class _C:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            if isinstance(answer, Exception):
                raise answer
            return _EsResp(*answer)
    monkeypatch.setattr(rec.httpx, "AsyncClient", _C)
    monkeypatch.setattr(rec, "settings", SimpleNamespace(EVENT_STORE_URL="http://es.example:8200", EVENT_STORE_API_KEY="k"))
    return rec


@pytest.mark.parametrize("answer", [(503, {}), httpx.ConnectError("refused")])
def test_the_finder_says_when_the_store_cannot_be_read_and_so_does_the_reconciliations_check(monkeypatch, answer):
    # session-lead's seq 2452: "could not verify" is not "nothing found" (test_settlement_unverified_v0660k)
    rec = _es(monkeypatch, answer)
    s = _row("PENDING_SLASH")
    s.defendant_did = "did:d"
    with pytest.raises(rec.EventStoreUnreadable):
        asyncio.run(rec.find_slash_on_eventstore(s))
    with pytest.raises(rec.EventStoreUnreadable):
        asyncio.run(rec._check_eventstore_for_slash(s))


def test_the_finder_returns_this_settlements_slash_and_none_when_there_is_none(monkeypatch):
    s = _row("PENDING_SLASH")
    s.defendant_did = "did:d"
    ev = {"id": "e1", "data": {"dispute_id": 50, "origin_registry_url": PUBLIC, "defendant_did": "did:d", "amount": 3,
                               "slash_tx_id": "t"}}
    rec = _es(monkeypatch, (200, [ev]))
    assert asyncio.run(rec.find_slash_on_eventstore(s))["slash_tx_id"] == "t"
    rec = _es(monkeypatch, (200, []))
    assert asyncio.run(rec.find_slash_on_eventstore(s)) is None


# (3) the close is committed before the audit row, and the answer is the row's state after the commit

def test_a_failed_audit_write_leaves_the_close_committed_and_the_answer_true(monkeypatch):
    row = _row("REFUSED")
    out, db, audited = _close(monkeypatch, row, audit_raises=RuntimeError("audit table unavailable"))
    assert row.status == "CLOSED" and out["status"] == "CLOSED" and audited == []
    kinds = [k for k, _ in db.log]
    assert kinds.index("commit") < kinds.index("audit"), db.log            # the close lands before the audit row
    assert ("commit", "CLOSED") in db.log and kinds.index("refresh") < kinds.index("audit")
    assert out["audit_recorded"] is False


def test_the_answer_is_read_back_from_the_row_after_the_commit(monkeypatch):
    row = _row("REFUSED")

    class _Db(_CloseDb):
        async def refresh(self, r):
            await super().refresh(r)
            r.status = "CLOSED_AS_STORED"                                   # what the database holds
    from agentvault_registry.routers import federation_disputes as fd
    from agentvault_registry.services import admin_audit

    async def audit(db, **kw):
        pass
    monkeypatch.setattr(admin_audit, "log_admin_action", audit)
    out = asyncio.run(fd.close_settlement(row.id, fd.SettlementCloseBody(reason="r"), current_admin=ADMIN, db=_Db(row)))
    assert out["status"] == "CLOSED_AS_STORED" and out["audit_recorded"] is True


# (5) delivery off ends a settlement no peer holds even after its retries are spent; a retry keeps the holder

def _reconcile(monkeypatch, settlement):
    from agentvault_registry.tasks import settlement_reconciliation as rec
    retried = []

    async def no_slash(_s):
        return None

    async def retry(_db, _s, count):
        retried.append(count)
    monkeypatch.setattr(rec, "_check_eventstore_for_slash", no_slash)
    monkeypatch.setattr(rec, "_retry_slash_request", retry)
    asyncio.run(rec._reconcile_single_settlement(_Db([]), settlement))
    return retried


def test_delivery_off_ends_a_settlement_no_peer_holds_after_its_retries_are_spent(origin, monkeypatch):
    from datetime import datetime, timezone
    s = _Settlement()
    s.requested_at = datetime.now(timezone.utc)
    s.error_message = "retry_count=3, last_retry=x, exhausted_at=y"
    assert _reconcile(monkeypatch, s) == []
    assert s.status == "NOT_DELIVERED" and "CROSS_REGISTRY_SETTLEMENT_DELIVERY is off" in s.error_message
    assert "Nothing moved" in s.error_message


def test_delivery_off_leaves_a_settlement_a_home_holds_waiting_after_its_retries(origin, monkeypatch):
    from datetime import datetime, timezone
    s = _Settlement(held=ALPHA.base_url)
    s.requested_at = datetime.now(timezone.utc)
    s.error_message = "retry_count=3, last_retry=x, exhausted_at=y"
    _reconcile(monkeypatch, s)
    assert s.status == "PENDING_SLASH" and s.defendant_registry_url == ALPHA.base_url


@pytest.mark.parametrize("answer", [(202, "{}"), (409, '{"detail":"Settlement 24ca7222 already received"}')])
def test_a_retry_a_second_peer_takes_keeps_the_registry_that_already_holds_it(origin, monkeypatch, answer):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    s = _retry(monkeypatch, _Settlement(held=ALPHA.base_url), [ALPHA, OP],
               {ALPHA.base_url: (409, '{"detail":"conflict"}'), OP.base_url: answer}, [])
    assert s.defendant_registry_url == ALPHA.base_url and s.status == "PENDING_SLASH"
