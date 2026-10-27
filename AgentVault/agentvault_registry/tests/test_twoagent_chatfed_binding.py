"""§TWOAGENT (2026-09-23, on the way, G1 survey) — cross-registry chat: a caller speaks only for itself, and a peer is not a rail.

Found while mapping G1 (agent-to-agent chat across frames). The federated chat path is live only where
CHAT_FEDERATION_ENABLED is set (frame-c today), and it carried two trust defects its own module docstring said it did
not have ("a caller that authenticates as one peer cannot then claim to be speaking for another"):
  * `POST /federation/chat/deliver` checked only that the envelope's `host_registry` was SOME active peer, never that
    it was the CALLER: any active peer could create a mirror in another peer's name and write into it;
  * `POST /federation/chat/relay-send` never compared the caller with the sender's home: any active peer could relay
    as another peer's participant;
  * `deliver` validated cards as a RAIL (`rail_author=True`), so a host could deliver `service.result`,
    `share.certificate`, `org.work.receipt` or `engagement.*` cards naming records this registry cannot verify.
    `relay-send` already refused them.

RED on V0430: both routes go past the stranger, and the deliver call site passes rail_author=True.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from fastapi import HTTPException

HOST = "https://eu.theprotocol.cloud"
EU_SVID = "spiffe://eu.theprotocol.cloud/service/registry"
STRANGER_SVID = "spiffe://lantern.theprotocol.cloud/service/registry"


@pytest.fixture
def peers(monkeypatch):
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import contract_xframe

    async def _resolve(db, value):
        v = str(value or "")
        return "eu" if "eu." in v else ("lantern" if "lantern" in v else None)

    async def _allowed(db, base):
        return None
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    return fed


def _envelope():
    return {"v": 1, "host_registry": HOST, "conversation": {"id": "c-1", "kind": "dm", "participants": []},
            "message": {"seq": 1, "kind": "text", "body": "hello", "sender": {"id": "dev:1", "registry": HOST}}}


async def test_deliver_refuses_a_caller_that_is_not_the_host(peers):
    from agentvault_registry.services import chat_service as cs
    with pytest.raises(cs.ChatError) as e:
        await peers.receive_delivery(None, _envelope(), STRANGER_SVID)
    assert e.value.status_code == 403 and "host" in e.value.detail


async def test_relay_send_refuses_a_caller_that_is_not_the_senders_home(peers):
    from agentvault_registry.routers import chat_federation as route
    req = route.RelaySend(conversation_ref="c-1", sender_key=f"alice@{HOST}", client_ref="ref-12345678", body="hi")
    with pytest.raises(HTTPException) as e:
        await route.relay_send(req, peer=STRANGER_SVID, db=None)
    assert e.value.status_code == 403 and "sender's home" in e.value.detail


def test_deliver_validates_cards_as_a_peer_not_a_rail():
    from agentvault_registry.services import chat_federation as fed
    tree = ast.parse(textwrap.dedent(inspect.getsource(fed.receive_delivery)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("validate_card")]
    assert calls, "receive_delivery no longer validates cards: check the test, not the code"
    for c in calls:
        kw = {k.arg: ast.unparse(k.value) for k in c.keywords}
        assert kw.get("rail_author", "False") == "False", ast.unparse(c)


def test_control_a_peer_rail_only_card_is_refused_by_the_validator():
    from agentvault_registry.services import chat_service as cs
    ctype = sorted(cs.RAIL_ONLY_CARDS)[0]
    assert cs.validate_card({"v": 1, "type": ctype, "data": {}}, rail_author=False)
