"""§GATEWAYROLE (2026-09-24): the AGORA exchange gateway signs every repatriation as itself, so under IRONKEY enforce it
needs a role; every gateway on the cluster was born with none, and every cross-frame repatriation was refused. Measured
on the sandbox pair: 6,876 credits parked as `failed` in two days, each refusal logged as a delivery attempt, and a fleet
warning storm. These tests pin the three halves of the fix: the `gateway` role (exactly teg.transfer + teg.transfer_xreg),
the heal that grants it at birth and on the hot path, and the repatriation passes treating a permission refusal as a
wall the SENDER meets (no attempt spent, one line per cycle) rather than a failed delivery. Each fails on V0444."""
import logging
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agentvault_registry import agent_authz
from agentvault_registry.services import exchange_passport as pp
from agentvault_registry.services import exchange_service as svc


# ── the role ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_gateway_role_carries_exactly_the_two_transfer_permissions():
    assert agent_authz.ROLE_PERMISSIONS["gateway"] == agent_authz.BASE_PERMISSIONS | {"teg.transfer", "teg.transfer_xreg"}


def test_the_gateway_role_grants_nothing_the_canary_stopgap_did_not():
    # step 1 of the fix granted `canary` by hand; the heal swaps it for `gateway` and must not widen anything
    assert agent_authz.ROLE_PERMISSIONS["gateway"] == agent_authz.ROLE_PERMISSIONS["canary"]


# ── the heal ────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, rows=None, first=None):
        self._rows, self._first = rows or [], first

    def first(self):
        return self._first

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _GrantsDB:
    """Answers the heal's three reads from a fake agent_role_grants and records its writes."""

    def __init__(self, agent_exists=True, live=(), permanent_gateway=False):
        self.agent_exists, self.live, self.permanent_gateway = agent_exists, list(live), permanent_gateway
        self.writes = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT 1 FROM agents"):
            return _Res(first=(1,) if self.agent_exists else None)
        if sql.startswith("SELECT value FROM agent_role_grants"):
            return _Res(rows=self.live)
        if sql.startswith("SELECT 1 FROM agent_role_grants"):
            return _Res(first=(1,) if self.permanent_gateway else None)
        self.writes.append((sql.split()[0], dict(params or {})))
        return _Res()


@pytest.mark.asyncio
async def test_a_gateway_born_without_a_role_gets_exactly_the_gateway_role():
    db = _GrantsDB(live=[])
    assert await pp.ensure_gateway_role(db, did="did:theprotocol:agora-gateway-t") is True
    kinds = [w[0] for w in db.writes]
    assert kinds == ["DELETE", "INSERT"]
    assert db.writes[1][1]["role"] == "gateway"


@pytest.mark.asyncio
async def test_the_canary_stopgap_is_retired_and_replaced():
    db = _GrantsDB(live=["canary"])
    assert await pp.ensure_gateway_role(db, did="did:theprotocol:agora-gateway-t") is True
    assert [w[0] for w in db.writes] == ["DELETE", "INSERT"]


@pytest.mark.asyncio
async def test_a_gateway_that_already_holds_its_permanent_role_is_left_alone():
    db = _GrantsDB(live=["gateway"], permanent_gateway=True)
    assert await pp.ensure_gateway_role(db, did="did:theprotocol:agora-gateway-t") is False
    assert db.writes == []


@pytest.mark.asyncio
async def test_an_expiring_gateway_grant_is_replaced_by_a_permanent_one():
    db = _GrantsDB(live=["gateway"], permanent_gateway=False)
    assert await pp.ensure_gateway_role(db, did="did:theprotocol:agora-gateway-t") is True
    assert [w[0] for w in db.writes] == ["DELETE", "INSERT"]


@pytest.mark.asyncio
async def test_no_grant_is_written_for_a_gateway_that_does_not_exist():
    db = _GrantsDB(agent_exists=False)
    assert await pp.ensure_gateway_role(db, did="did:theprotocol:agora-gateway-t") is False
    assert db.writes == []


# ── the refusal ─────────────────────────────────────────────────────────────────────────────────────────────────────

_NESTED_403 = ('{"error":{"detail":"{\\"smart_send_method\\": \\"2pc\\", \\"via\\": \\"/api/v1/teg/cross-registry-transfer'
               '?backend=2pc\\", \\"inner\\": \\"Agent lacks required permission: teg.transfer_xreg\\"}"}}')


def test_a_nested_permission_refusal_names_its_permission():
    assert svc._permission_refused(SimpleNamespace(status_code=403, text=_NESTED_403)) == "teg.transfer_xreg"


@pytest.mark.parametrize("r", [SimpleNamespace(status_code=403, text="Not your agent"),
                               SimpleNamespace(status_code=500, text="Agent lacks required permission: teg.transfer"),
                               None])
def test_other_refusals_are_not_permission_refusals(r):
    assert svc._permission_refused(r) is None


# ── the per-credit pass ─────────────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text

    def json(self):
        return {}


def _client_answering(resp):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return resp
    return _Client


def _table(n=0, frags=False):
    """§REPATLANE (V0603): the passes run against the strict credits double (tests/_gateway_credits)."""
    from tests._gateway_credits import CreditsTable, credit
    rows = ([credit(i, did="did:theprotocol:seller-x", amount="0.3", origin="trade") for i in (1, 2, 3)] if frags
            else [credit(i, did=f"did:theprotocol:seller-{i}", origin="trade") for i in range(n)])
    return CreditsTable(rows, dust=svc.REPAT_DUST, max_attempts=svc.REPAT_MAX_ATTEMPTS)


@pytest.fixture
def _no_heal_no_jwt(monkeypatch):
    monkeypatch.setattr(svc, "_GATEWAY_ROLE_OK", True)
    import agentvault_registry.security as security
    monkeypatch.setattr(security, "create_access_token", lambda *a, **k: "jwt")


@pytest.mark.asyncio
async def test_a_permission_refusal_spends_no_attempt_and_is_said_once(monkeypatch, caplog, _no_heal_no_jwt):
    t = _table(5)
    monkeypatch.setattr(svc.httpx, "AsyncClient", _client_answering(_Resp(403, _NESTED_403)))
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert await svc.repatriate_gateway_credits(t) == 0
    rows = list(t.rows.values())
    assert [c.attempts for c in rows] == [0] * 5 and {c.status for c in rows} == {"pending"}
    assert {c.tx_ref for c in rows} == {None}, "the credit is left exactly as it was"
    said = [r.getMessage() for r in caplog.records if "IRONKEY refused the gateway" in r.getMessage()]
    assert len(said) == 1 and "teg.transfer_xreg" in said[0] and "5 credit(s)" in said[0]
    assert not [r for r in caplog.records if "send 403" in r.getMessage()]


@pytest.mark.asyncio
async def test_control_a_refusal_that_moved_nothing_still_counts_as_an_attempt(monkeypatch, caplog, _no_heal_no_jwt):
    # §REPATLANE (V0603): this control was a 500, which may have moved money and now HOLDS (tests/test_repat_lane.py);
    # an attempt is spent on a refusal that proves nothing moved, such as the TEG's insufficient balance
    t = _table(2)
    monkeypatch.setattr(svc.httpx, "AsyncClient", _client_answering(_Resp(402, "Insufficient balance")))
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        await svc.repatriate_gateway_credits(t)
    rows = list(t.rows.values())
    assert [c.attempts for c in rows] == [1, 1] and {c.status for c in rows} == {"pending"}
    assert len([r for r in caplog.records if "send 402" in r.getMessage()]) == 2


# ── the aggregated pass ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_aggregated_pass_releases_a_refused_bucket_without_an_attempt(monkeypatch, caplog, _no_heal_no_jwt):
    t = _table(frags=True)
    monkeypatch.setattr(svc.httpx, "AsyncClient", _client_answering(_Resp(403, _NESTED_403)))
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert await svc.repatriate_gateway_credits_aggregated(t) == 0
    rows = list(t.rows.values())
    assert {(c.status, c.attempts, c.tx_ref) for c in rows} == {("pending", 0, None)}
    said = [r.getMessage() for r in caplog.records if "IRONKEY refused the gateway" in r.getMessage()]
    assert len(said) == 1 and "3 credit(s)" in said[0]
