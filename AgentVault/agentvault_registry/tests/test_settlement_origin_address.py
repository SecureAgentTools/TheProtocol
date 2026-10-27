"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): a cross-registry settlement names its origin by the address its peers
know, when CROSS_REGISTRY_SETTLEMENT_DELIVERY is on.

The origin named itself by FEDERATION_BASE_URL, the stack's internal federation proxy, and the defendant's home takes
a slash request only when its callback lies under an ACTIVE peer's base_url: dispute 50 on sbx-beta (2026-10-24 17:36Z)
was refused by all three peers with 400 "Callback URL must belong to a registered peer registry", and no cross-frame
settlement was ever delivered on any frame. On, the origin is the address the registry's signed card publishes
(BILATERAL_PEER_URL where a stranger could dial it), the one its peers hold as its base_url; off (the default) it is the
internal address exactly as before. Each test imports the module itself, so on V0638 they fail one by one (the control).
"""
from __future__ import annotations

import importlib
import inspect

import pytest

PUBLIC = "https://sandbox-b.theprotocol.cloud:8443"
INTERNAL = "http://sbx-beta-nginx-federation:8443"


@pytest.fixture
def origin(monkeypatch):
    mod = importlib.import_module("agentvault_registry.core.settlement_origin")
    monkeypatch.setattr(mod.settings, "FEDERATION_BASE_URL", INTERNAL, raising=False)
    monkeypatch.setenv("FEDERATION_BASE_URL", INTERNAL)
    monkeypatch.setenv("BILATERAL_PEER_URL", PUBLIC)
    monkeypatch.delenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", raising=False)
    return mod


def test_off_by_default_the_origin_is_the_internal_address_as_before(origin):
    assert origin.delivery_on() is False and origin.origin_url() == INTERNAL


def test_on_the_origin_is_the_address_its_peers_hold(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    assert origin.origin_url() == PUBLIC
    callback = f"{origin.origin_url()}/api/v1/federation/disputes/slash-confirmation"
    # the defendant's home's rule (federation_disputes.receive_slash_request): under an ACTIVE peer's base_url
    assert callback.lower().startswith(PUBLIC.lower())
    assert not f"{INTERNAL}/api/v1/federation/disputes/slash-confirmation".lower().startswith(PUBLIC.lower())


def test_on_without_a_dialable_address_it_keeps_the_internal_one(origin, monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    monkeypatch.setenv("BILATERAL_PEER_URL", "http://agentvault_registry_test:8000")    # a docker name: not dialable
    assert origin.origin_url() == INTERNAL


def test_the_settlement_and_its_retry_both_ask_the_helper():
    importlib.import_module("agentvault_registry.core.settlement_origin")
    from agentvault_registry.crud import crud_disputes
    from agentvault_registry.tasks import settlement_reconciliation
    make = inspect.getsource(crud_disputes._process_cross_registry_compensation)
    assert "settlement_origin.origin_url()" in make and "settings.FEDERATION_BASE_URL" not in make
    retry = inspect.getsource(settlement_reconciliation)
    assert "(settlement.origin_registry_url or \"\").rstrip('/') or settlement_origin.origin_url()" in retry
    assert "origin_url = (settings.FEDERATION_BASE_URL" not in retry


# ─── agentvault2-d6's pins (2026-10-24) ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bilateral,federation", [
    (PUBLIC, INTERNAL),                                            # the frames: BILATERAL_PEER_URL dialable
    ("http://agentvault_registry_test:8000", INTERNAL),            # a docker name: none dialable
    ("", "https://op-x.op.theprotocol.cloud:8443"),                # only the federation address dialable
])
def test_the_origin_and_the_card_name_one_address(origin, monkeypatch, bilateral, federation):
    """(1) one helper: the settlement's origin is the card's identity.federation_base_url wherever the card has one."""
    from agentvault_registry.services import registry_card_builder as card
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    monkeypatch.setenv("BILATERAL_PEER_URL", bilateral)
    monkeypatch.setenv("FEDERATION_BASE_URL", federation)
    published = card.federation_base_url()
    assert origin.origin_url() == (published or INTERNAL).rstrip("/")
    assert '"federation_base_url": federation_base_url(),' in inspect.getsource(card)


class _Resp:
    def __init__(self, code: int, text: str):
        self.status_code, self.text = code, text

    def json(self):
        return {}


def _client_answering(code: int, text: str):
    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp(code, text)
    return _Client


class _Peer:
    name, status = "Sandbox Alpha", "ACTIVE"
    base_url = "https://sandbox-a.theprotocol.cloud:8443"
    federation_access_token = None


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows, self.added = rows, []

    async def execute(self, stmt):
        return _Rows(self.rows)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        pass


class _Settlement:
    id, dispute_id, ruling, requested_amount = "s-1", 50, "IN_FAVOR_OF_COMPLAINANT", 3
    complainant_did, defendant_did = "did:c", "did:d"
    origin_registry_url, callback_url = PUBLIC, PUBLIC + "/api/v1/federation/disputes/slash-confirmation"
    defendant_registry_url, error_message = "", None


DUP = '{"detail":"Settlement s-1 already received (duplicate slash request)"}'


@pytest.mark.parametrize("code,text,held", [(409, DUP, True), (409, '{"detail":"conflict"}', False)])
async def test_a_retry_the_home_already_holds_is_delivered_once(monkeypatch, code, text, held):
    """(2) the home claims the settlement id before any money moves, so a redelivery is one slash; the origin reads
    its 409 as delivered and records the home a confirmation may come from, never as another failure."""
    from agentvault_registry.tasks import settlement_reconciliation as rec
    monkeypatch.setattr(rec.httpx, "AsyncClient", _client_answering(code, text))
    monkeypatch.setattr(rec.svid_client, "get_client_cert_config", lambda: None)
    s = _Settlement()
    await rec._retry_slash_request(_Db([_Peer()]), s, 1)
    assert (s.defendant_registry_url == _Peer.base_url) is held
    assert ("already_held=" in (s.error_message or "")) is held


async def test_the_first_delivery_reads_the_homes_claim_the_same_way(monkeypatch):
    from agentvault_registry.core import settlement_origin
    from agentvault_registry.crud import crud_disputes as cd
    received = []

    class _Emitter:
        async def emit_dispute_compensation_request(self, **kw):
            received.append(kw)
    monkeypatch.setattr(cd, "get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(cd.httpx, "AsyncClient", _client_answering(409, DUP))
    from agentvault_registry.identity import svid_client
    monkeypatch.setattr(svid_client, "get_client_cert_config", lambda: None)

    class _Dispute:
        id, complainant_did, defendant_did = 50, "did:c", "did:d"
    db = _Db([_Peer()])
    out = await cd._process_cross_registry_compensation(db, _Dispute(), "IN_FAVOR_OF_COMPLAINANT", 3, {})
    (settlement,) = db.added
    assert settlement.defendant_registry_url == _Peer.base_url and out["settlement_status"] == "pending_remote_slash"
    assert "could not be delivered" not in out["reason"]
    # the public record goes out once, naming the origin the settlement names
    assert received == [{"dispute_id": 50, "complainant_did": "did:c", "defendant_did": "did:d", "amount": 3,
                         "origin_registry_url": settlement_origin.origin_url(), "ruling": "IN_FAVOR_OF_COMPLAINANT"}]
    assert settlement.origin_registry_url == settlement_origin.origin_url()


async def test_the_homes_refusal_names_the_hosts_it_compared():
    """(4) hosts only: the callback's host and the active peers' hosts, so the next mismatch names itself."""
    from fastapi import HTTPException
    from agentvault_registry.routers import federation_disputes as fd
    req = fd.SlashRequest(settlement_id="s-1", dispute_id=50, ruling="IN_FAVOR_OF_COMPLAINANT", amount=3,
                          complainant_did="did:c", defendant_did="did:d",
                          origin_registry_url="https://sbx-beta-nginx-federation:8443",
                          callback_url="https://sbx-beta-nginx-federation:8443/api/v1/federation/disputes/slash-confirmation")

    class _Db400:
        async def execute(self, stmt):
            return _Rows([("https://sandbox-a.theprotocol.cloud:8443",), ("https://sbxbetaop.op.theprotocol.cloud:8443",)])
    with pytest.raises(HTTPException) as e:
        await fd.receive_slash_request(req, "spiffe://sandbox-b.theprotocol.cloud/service/sbx-beta-registry", _Db400())
    d = str(e.value.detail)
    assert e.value.status_code == 400 and d.startswith("Callback URL must belong to a registered peer registry")
    assert "its host sbx-beta-nginx-federation" in d
    assert "sandbox-a.theprotocol.cloud, sbxbetaop.op.theprotocol.cloud" in d and "/api/" not in d
