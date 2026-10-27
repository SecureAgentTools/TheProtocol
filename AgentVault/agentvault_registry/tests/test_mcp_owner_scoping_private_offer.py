"""§MCPTEST30 (V0556): the owner-scoping contract checks make their own subject, a PRIVATE offer.

The sentinel is fresh every run, so the only contracts it could read were open offers, which any agent may read by
design: "getContractV2 (a non-party agent)" and "getContractById (a non-party agent)" read NOT MEASURED on every run, and
a private offer stayed readable by any agent holding its id (V0556 (1) closes that in the product). Now, where the
sentinel holds only an open offer, the lifecycle gives a provider of the run's own engagement terms, has the sentinel
engage it (engageAgent's success path), asks both views as the run's second agent (no party to it), and withdraws the
offer and deletes the provider. Pinned against the owner-scoping suite's fake registry, awaited (never asyncio.run).
"""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _parse_rpc_result
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

from tests import test_mcp_owner_scoping as OS   # the owner-scoping suite's fake registry and bag

ROWS = ("getContractV2 (a non-party agent)", "getContractById (a non-party agent)")


class PrivateOfferFake(OS.FakeRegistry):
    def __init__(self, engage_fails=False, private_readable=False, **kw):
        super().__init__(**kw)
        self.engage_fails, self.private_readable = engage_fails, private_readable
        self.cards, self.offers, self.deleted, self.cancelled, self.admin_calls = {}, {}, [], [], []

    async def rpc(self, tool, args, jwt="", timeout=20):
        name = tool.replace("theprotocol_", "")
        if name == "createAgent":
            did = f"did:theprotocol:offer-provider-{len(self.cards) + 1}"
            self.cards[did] = {"name": args["name"], "skills": []}
            return OS._ok({"agent_did": did, "client_id": "cid", "client_secret": "csec"})
        if name == "engageAgent":
            did = args["provider_did"]
            if self.engage_fails or "engagement" not in self.cards.get(did, {}):
                return OS._refuse(404, "This agent's card does not advertise engagement terms")
            cid = f"ctr_private{len(self.offers) + 1}"
            self.offers[cid] = {"id": cid, "client_did": OS.SENTINEL_DID, "provider_did": did, "status": "offered",
                                "title": self.cards[did]["engagement"]["title"], "total_amount": "1"}
            return OS._ok(self.offers[cid])
        if name in ("getContractV2", "getContractById") and args.get("contract_id") in self.offers:
            off = self.offers[args["contract_id"]]
            if args.get("agent_jwt") == OS.SENT or self.private_readable:
                return OS._ok(off)
            return OS._refuse(403, "Not a party to this contract")
        if name == "deleteMyAgentByDev":
            self.deleted.append(args["agent_did"])
            return OS._ok({"deleted": True})
        return await super().rpc(tool, args, jwt, timeout)

    async def rpc_admin(self, tool, args, jwt="", timeout=20):
        method, ep = args.get("method"), args.get("endpoint", "")
        self.admin_calls.append((method, ep, args.get("developer_jwt")))
        if ep.startswith("/api/v1/agent-cards/"):
            did = ep.rsplit("/", 1)[1]
            if method == "GET":
                return OS._ok({"status_code": 200, "response": {"card_data": dict(self.cards[did])}, "ok": True})
            if method == "PUT":
                self.cards[did] = args["body"]["card_data"]
                return OS._ok({"status_code": 200, "response": {}, "ok": True})
        if method == "POST" and ep.endswith("/cancel"):
            cid = ep.split("/")[-2]
            self.offers[cid]["status"] = "cancelled"
            self.cancelled.append((cid, args.get("developer_jwt")))
            return OS._ok({"status_code": 200, "response": {"status": "cancelled"}, "ok": True})
        return OS._refuse(404, "no fake")


class Bag(OS.Bag):
    def __init__(self, fake, **extra):
        super().__init__(fake, **extra)
        self.rpc_admin = fake.rpc_admin


async def _run(fake, **extra):
    outcomes = {}
    await L.lifecycle_owner_scoping(fake.rpc, _parse_rpc_result, Bag(fake, **extra), outcomes)
    return outcomes


async def test_an_open_offer_run_makes_a_private_offer_and_measures_both_views():
    fake = PrivateOfferFake()
    outcomes = await _run(fake, contract_v2_status="offered")
    st = OS._state(outcomes)
    assert [st[r] for r in ROWS] == ["ok", "ok"], st
    assert len(fake.offers) == 1
    (cid, offer), = fake.offers.items()
    assert offer["provider_did"] in fake.deleted, "the provider the run made is deleted"
    assert fake.cancelled == [(cid, OS.SENT)], "the sentinel withdraws its own offer with its own token"
    assert fake.cards[offer["provider_did"]]["engagement"]["price"] == 1
    for r in ROWS:
        assert "a private offer" in str(outcomes[L._OWN + r]), r     # the row says what it measured


async def test_a_registry_that_shows_a_stranger_a_private_offer_is_red():
    fake = PrivateOfferFake(private_readable=True)
    outcomes = await _run(fake, contract_v2_status="offered")
    st = OS._state(outcomes)
    assert [st[r] for r in ROWS] == ["red", "red"], st
    assert all(outcomes[L._OWN + r]["fail_reason"].startswith("BUG-FIND: owner scoping") for r in ROWS)
    assert len(fake.cancelled) == 1, "a red still withdraws the offer"


async def test_no_terms_taken_reads_not_measured_and_names_why_and_cleans_up():
    fake = PrivateOfferFake(engage_fails=True)
    outcomes = await _run(fake, contract_v2_status="offered")
    st = OS._state(outcomes)
    assert [st[r] for r in ROWS] == ["skip", "skip"], st
    for r in ROWS:
        why = outcomes[L._OWN + r]["skip_reason"]
        assert why.startswith("NOT MEASURED: the sentinel's contract is an open offer") and "engageAgent minted no private offer" in why
    assert not fake.offers and len(fake.deleted) == 1 and not fake.cancelled


async def test_a_contract_the_sentinel_is_a_party_to_needs_no_private_offer():
    fake = PrivateOfferFake()
    outcomes = await _run(fake)          # the fixture's contract is active: a party read and a stranger's refusal
    st = OS._state(outcomes)
    assert [st[r] for r in ROWS] == ["ok", "ok"], st
    assert not fake.cards and not fake.offers and not fake.admin_calls


@pytest.fixture(autouse=True)
def _a_loop_for_the_next_file():
    yield
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
