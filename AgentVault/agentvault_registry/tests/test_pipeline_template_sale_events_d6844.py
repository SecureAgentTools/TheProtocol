"""D6-844 (V0657 (e), session-lead's review, seq 1538): a paid template sale reaches the event store as /teg/transfer's
sales do.

With the author set, agent_cicd_service._pay_for_template's author branch is live, and it posts straight to the TEG's
/token/transfer, which emits no TokensTransferred (the TEG's is policy-denied) or TransactionFeeCollected, records no
EigenTrust signal or fee audit and syncs no balance cache. A sale now takes /teg/transfer's own steps: the fee computed
before the move and passed to the TEG, the balance sync, both events keyed xfer-/fee-<tx> (the REAL
teg_integration._emit_transfer_events, received by a recording emitter), the EigenTrust signal and the fee audit. The
treasury branch (an author-less template, the frame's own) emits its TokensTransferred keyed xfer-<tx> and syncs the
buyer's cached balance. RED on v0656/cut's service: the emitter receives nothing on either branch.
"""
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from agentvault_registry import event_emitter as ee
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import agent_cicd_service as svc_mod

BUYER = SimpleNamespace(id=11, did="did:theprotocol:buyer", liquid_balance=Decimal("100"))
AUTHOR = "did:theprotocol:author"


class Emitter:
    def __init__(self):
        self.received = []

    def emit_background(self, event_type, aggregate_id, data, idempotency_key=None):
        self.received.append({"type": event_type, "agg": aggregate_id, "data": data, "key": idempotency_key})


class Fee:
    async def get_fee_for_transfer(self, db, sender_did, transfer_amount):
        return Decimal("0.05"), 1.0


class Db:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def rig(monkeypatch):
    calls, steps = [], []
    emitter = Emitter()

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            calls.append({"url": url, "json": json, "idem": (headers or {}).get("Idempotency-Key")})
            if url.endswith("/token/transfer"):
                body = {"transaction_id": "tx-author-1", "status": "completed", "amount": json["amount"],
                        "fee_amount": json.get("fee_amount", "0"), "new_sender_balance": "94.95"}
            else:
                body = {"transaction_id": "tx-treasury-1", "treasury_did": "did:theprotocol:treasury",
                        "new_source_balance": "95"}
            return httpx.Response(200, json=body)

    async def token(agent_id, did):
        return "teg-token"

    async def sync(db, agent, receiver, data, client):
        steps.append(("sync", agent.did, receiver, data.get("transaction_id")))

    async def ancillary(db, sender, receiver, amount, tx, fee, fee_svc):
        steps.append(("ancillary", sender, receiver, amount, tx, str(fee), fee_svc is not None))

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", token)
    monkeypatch.setattr(ti, "_sync_balances_after_transfer", sync)
    monkeypatch.setattr(ti, "_record_transfer_ancillary", ancillary)
    monkeypatch.setattr(ee, "get_event_emitter", lambda: emitter)
    from agentvault_registry.services import transaction_fee_service as tfs
    monkeypatch.setattr(tfs, "get_transaction_fee_service", lambda: Fee())
    return SimpleNamespace(calls=calls, steps=steps, emitter=emitter)


async def test_an_author_sale_takes_the_transfer_routes_steps(rig):
    db = Db()
    tx = await svc_mod.agent_cicd_service._pay_for_template(BUYER, "tpl-1", AUTHOR, 5, "deploy", db=db)
    assert tx == "tx-author-1"
    assert rig.calls[0]["json"]["fee_amount"] == "0.05", "the registry's fee rides the move, as /teg/transfer's does"
    kinds = {e["type"]: e for e in rig.emitter.received}
    assert kinds["TokensTransferred"]["data"]["from"] == BUYER.did and kinds["TokensTransferred"]["data"]["to"] == AUTHOR
    assert kinds["TokensTransferred"]["key"] == "xfer-tx-author-1"
    assert kinds["TransactionFeeCollected"]["key"] == "fee-tx-author-1"
    assert ("sync", BUYER.did, AUTHOR, "tx-author-1") in rig.steps
    assert ("ancillary", BUYER.did, AUTHOR, "5", "tx-author-1", "0.05", True) in rig.steps


async def test_a_treasury_sale_emits_its_transfer_and_syncs_the_buyer(rig):
    db = Db()
    buyer = SimpleNamespace(id=12, did="did:theprotocol:buyer2", liquid_balance=Decimal("100"))
    tx = await svc_mod.agent_cicd_service._pay_for_template(buyer, "tpl-2", None, 5, "official", db=db)
    assert tx == "tx-treasury-1"
    assert rig.calls[0]["url"].endswith("/admin/treasury/receive") and "fee_amount" not in rig.calls[0]["json"]
    got = [e for e in rig.emitter.received if e["type"] == "TokensTransferred"]
    assert len(got) == 1 and got[0]["key"] == "xfer-tx-treasury-1"
    assert got[0]["data"]["to"] == "did:theprotocol:treasury" and got[0]["data"]["amount"] == "5"
    assert buyer.liquid_balance == Decimal("95") and db.commits == 1


async def test_a_treasury_answer_without_its_treasury_emits_no_invented_recipient(rig, monkeypatch, caplog):
    """session-lead's review, seq 1543: never an invented recipient in a ledger event; the cached balance still syncs."""
    class NoTreasury:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            return httpx.Response(200, json={"transaction_id": "tx-treasury-2", "new_source_balance": "95"})

    monkeypatch.setattr(httpx, "AsyncClient", NoTreasury)
    buyer = SimpleNamespace(id=13, did="did:theprotocol:buyer3", liquid_balance=Decimal("100"))
    caplog.set_level("WARNING")
    tx = await svc_mod.agent_cicd_service._pay_for_template(buyer, "tpl-4", None, 5, "official", db=Db())
    assert tx == "tx-treasury-2"
    assert rig.emitter.received == [], "no TokensTransferred names a recipient the TEG did not"
    assert "names no treasury_did" in caplog.text
    assert buyer.liquid_balance == Decimal("95")


async def test_a_declined_sale_emits_nothing(rig, monkeypatch):
    class Declined:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            return httpx.Response(400, json={"detail": "insufficient balance"})

    monkeypatch.setattr(httpx, "AsyncClient", Declined)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await svc_mod.agent_cicd_service._pay_for_template(BUYER, "tpl-3", AUTHOR, 5, "deploy", db=Db())
    assert e.value.status_code == 402
    assert rig.emitter.received == [] and rig.steps == []
