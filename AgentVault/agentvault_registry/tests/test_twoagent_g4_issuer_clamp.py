"""§TWOAGENT G4 (2026-09-23) — a cross-registry delegation conveys no more than its issuer holds NOW, at its home.

Measured by Session A on the EU/ASIA pair (V0430): a delegate kept acting "on behalf of" an issuer after the issuer's
home had cut the issuer back, because the delegate's home minted the grant once from the signed claim and honoured it
for its whole TTL. The only other signal, the issuer's revoke, ships best-effort with no retry.

Now the delegate's home asks the issuer's home at use (`GET /api/v1/federation/ironkey/issuer-authority`, cached,
failing CLOSED) and conveys granted ∩ the issuer's current permissions, or nothing when the issuer or the credential is
no longer live. The issuer's home answers only the registry the credential was shipped to; anything else is a 404 that
confirms nothing. The act-token route says why a delegation conveys nothing instead of minting an empty token.

RED on V0430: the module and the route do not exist and the resolver conveys the whole grant. The controls (a dev:
principal's grant is untouched; an org grant still needs its link) pass on both trees.
"""
from __future__ import annotations

import collections
import json
import types

import pytest
from fastapi import HTTPException

ISS = "did:theprotocol:eu.test:issuer"
DEL = "did:theprotocol:asia.test:delegate"
CID = "cred-0001"


def _xia():
    from agentvault_registry.services import xreg_issuer_authority as m
    return m


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0][0] if self._rows else None


class _Db:
    """Answers each query by the first needle its SQL contains."""

    def __init__(self, handlers):
        self.handlers = handlers
        self.sql = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        for needle, rows in self.handlers:
            if needle in sql:
                return _Result(rows(params) if callable(rows) else rows)
        return _Result([])

    async def commit(self):
        return None

    def add(self, *_a, **_k):
        return None


# ─────────────────────────────── the pure rule ───────────────────────────────

def test_the_grant_is_intersected_with_what_the_issuer_holds_now():
    m = _xia()
    live = {"credential": "active", "issuer_status": "active"}
    assert m.decide({"teg.transfer", "gov.vote"}, {**live, "issuer_permissions": ["teg.transfer", "gov.vote", "x"]}) \
        == ({"teg.transfer", "gov.vote"}, "ok")
    assert m.decide({"teg.transfer", "gov.vote"}, {**live, "issuer_permissions": ["teg.transfer"]}) \
        == ({"teg.transfer"}, "clamped")


def test_a_dead_issuer_or_credential_conveys_nothing():
    m = _xia()
    g = {"teg.transfer"}
    held = {"issuer_permissions": ["teg.transfer"]}
    assert m.decide(g, {"credential": "revoked", "issuer_status": "active", **held}) == (set(), "credential_revoked")
    assert m.decide(g, {"credential": "expired", "issuer_status": "active", **held}) == (set(), "credential_expired")
    assert m.decide(g, {"credential": "active", "issuer_status": "inactive", **held}) == (set(), "issuer_inactive")
    assert m.decide(g, {"credential": "??", "issuer_status": "active", **held}) == (set(), "not_vouched")


# ─────────────────────────────── the issuer's home ───────────────────────────────

def _issuer_db(*, delegate_registry="https://asia.theprotocol.cloud:8443", revoked=False, status=("active", "active"),
               expires_at="2099-01-01T00:00:00+00:00"):
    issued = {"credential_id": CID, "delegate_registry": delegate_registry, "permissions": ["teg.transfer"],
              "expires_at": expires_at}
    return _Db([
        ("xreg_delegation_issue", [(json.dumps({"credential_id": "other"}),), (json.dumps(issued),)]),
        ("xreg_delegation_revoke", [(1,)] if revoked else []),
        ("FROM agents WHERE did", [status] if status else []),
    ])


@pytest.fixture
def _peer_names(monkeypatch):
    async def _resolve(db, value):
        v = str(value or "")
        return "asia" if "asia" in v else ("eu" if "eu" in v else None)

    async def _held(db, did, act_principal=None):
        return {"teg.transfer", "gov.vote"}
    from agentvault_registry.services import contract_xframe
    from agentvault_registry import agent_authz
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(agent_authz, "resolve_agent_permissions", _held)


async def test_the_issuers_home_answers_the_registry_the_credential_went_to(_peer_names):
    a = await _xia().issuer_answer(_issuer_db(), ISS, CID, "asia")
    assert a["credential"] == "active" and a["issuer_status"] == "active"
    # V0432 (Session A's review): only what this credential granted that the issuer still holds, never its whole set
    assert a["issuer_permissions"] == ["teg.transfer"]


async def test_the_issuers_home_confirms_nothing_to_anyone_else(_peer_names):
    m = _xia()
    assert await m.issuer_answer(_issuer_db(), ISS, CID, "eu") is None          # another registry
    assert await m.issuer_answer(_issuer_db(), ISS, "cred-unknown", "asia") is None   # not a credential issued here
    assert await m.issuer_answer(_issuer_db(), ISS, CID, None) is None          # an SVID that resolves to no peer


async def test_a_revoke_whose_ship_failed_still_counts_and_a_suspended_issuer_holds_nothing(_peer_names):
    m = _xia()
    assert (await m.issuer_answer(_issuer_db(revoked=True), ISS, CID, "asia"))["credential"] == "revoked"
    a = await m.issuer_answer(_issuer_db(status=("active", "suspended")), ISS, CID, "asia")
    assert a["issuer_status"] == "inactive" and a["issuer_permissions"] == []
    assert (await m.issuer_answer(_issuer_db(expires_at="2020-01-01T00:00:00+00:00"), ISS, CID, "asia"))[
        "credential"] == "expired"


async def test_the_route_404s_with_a_detail_that_confirms_nothing(monkeypatch, _peer_names):
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "true")
    from agentvault_registry.routers import agent_delegation_api as api
    with pytest.raises(HTTPException) as e:
        await api.issuer_authority(issuer_did=ISS, credential_id=CID, db=_issuer_db(),
                                   peer_spiffe_id="spiffe://eu.theprotocol.cloud/service/registry")
    assert e.value.status_code == 404 and e.value.detail == _xia().NOT_VOUCHED_DETAIL
    ok = await api.issuer_authority(issuer_did=ISS, credential_id=CID, db=_issuer_db(),
                                    peer_spiffe_id="spiffe://asia.theprotocol.cloud/service/registry")
    assert ok["credential"] == "active"


# ─────────────────────────────── the delegate's home ───────────────────────────────

class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


def _wire_http(monkeypatch, outcome):
    seen: dict = {}

    class _Client:
        def __init__(self, **cfg):
            seen["timeout"] = cfg.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, params=None):
            seen["url"], seen["headers"], seen["params"] = url, dict(headers or {}), dict(params or {})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    async def _peer(db, url):
        return "https://asia-registry-internal:8443"

    from agentvault_registry.routers import guild
    import httpx
    monkeypatch.setattr(guild, "_resolve_peer_url", _peer)
    monkeypatch.setattr(guild, "_fed_client_config",
                        lambda t: ({"timeout": 15.0}, {"X-Federation-Secret": "s", "X-Federation-SPIFFE-ID": "x"}))
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return seen


async def test_the_delegates_home_reads_each_answer_honestly(monkeypatch):
    m = _xia()
    seen = _wire_http(monkeypatch, _Resp(200, {"credential": "active"}))
    assert await m._ask_issuer_home(None, "https://eu.theprotocol.cloud", ISS, CID) == ({"credential": "active"},
                                                                                         "answered")
    assert seen["url"].endswith("/api/v1/federation/ironkey/issuer-authority")
    assert "X-Federation-Secret" not in seen["headers"] and seen["params"] == {"issuer_did": ISS, "credential_id": CID}
    _wire_http(monkeypatch, _Resp(404, {"detail": m.NOT_VOUCHED_DETAIL}))
    assert (await m._ask_issuer_home(None, "h", ISS, CID))[1] == "not_vouched"
    _wire_http(monkeypatch, _Resp(404, {"detail": "Not Found"}))
    assert (await m._ask_issuer_home(None, "h", ISS, CID))[1] == "issuer_home_predates"
    _wire_http(monkeypatch, ConnectionError("down"))
    assert (await m._ask_issuer_home(None, "h", ISS, CID))[1] == "issuer_home_unreachable"


def _grant_db(ptype="agent", pref=f"agent:{ISS}", perms=("teg.transfer", "gov.vote"), cred=True, org_linked=True):
    return _Db([
        ("FROM agent_delegation_grants", [(list(perms), ptype, pref)]),
        ("FROM agent_delegation_credentials", [(CID, "https://eu.theprotocol.cloud")] if cred else []),
        ("FROM agents a JOIN organizations", [(1,)] if org_linked else []),
        ("FROM developers WHERE id", [(False, None, None)]),   # a live developer (dev: grants are clamped too)
        ("AND creator_developer_id = :dev", [(1,)]),           # D6-270: the delegate is that developer's own agent
    ])


async def _resolve(db, pref=f"agent:{ISS}"):
    from agentvault_registry.agent_authz import resolve_delegated_permissions
    return await resolve_delegated_permissions(db, DEL, pref)


def _answer(monkeypatch, answer, outcome="answered"):
    async def _fetch(db, host, iss, cid):
        return answer, outcome
    monkeypatch.setattr(_xia(), "fetch_issuer_answer", _fetch, raising=False)


async def test_a_clamped_issuer_clamps_the_delegate(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    _answer(monkeypatch, {"credential": "active", "issuer_status": "active", "issuer_permissions": ["teg.transfer"]})
    assert await _resolve(_grant_db()) == {"teg.transfer"}


async def test_an_unreachable_issuer_home_conveys_nothing(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    _answer(monkeypatch, None, "issuer_home_unreachable")
    assert await _resolve(_grant_db()) == set()


async def test_shadow_reports_the_clamp_and_conveys_the_grant(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    monkeypatch.setenv("XREG_ISSUER_AUTHORITY_MODE", "shadow")
    _answer(monkeypatch, None, "issuer_home_unreachable")
    assert await _resolve(_grant_db()) == {"teg.transfer", "gov.vote"}


async def test_a_local_agent_principal_is_clamped_from_this_registrys_rows(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    db = _grant_db(cred=False)
    db.handlers.append(("FROM agents WHERE did", [("suspended", "active")]))
    assert await _resolve(db) == set()


async def test_control_a_dev_principal_grant_is_untouched(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    assert await _resolve(_grant_db(ptype="dev", pref="dev:41"), "dev:41") == {"teg.transfer", "gov.vote"}


async def test_control_an_org_grant_still_needs_its_link(monkeypatch):
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    assert await _resolve(_grant_db(ptype="org", pref="org:acme", org_linked=False), "org:acme") == set()


async def test_the_act_token_says_why_a_delegation_conveys_nothing(monkeypatch):
    from agentvault_registry.routers import agent_delegation_api as api

    async def _clamp(db, delegate, issuer, granted):
        return set(), "issuer_home_unreachable"
    monkeypatch.setattr(_xia(), "clamp_agent_principal", _clamp, raising=False)
    Row = collections.namedtuple("Row", ["permissions"])
    db = _Db([("FROM agent_delegation_grants", [Row(["teg.transfer"])])])
    with pytest.raises(HTTPException) as e:
        await api.mint_act_token(body=api.ActTokenIn(act_as=f"agent:{ISS}"),
                                 agent=types.SimpleNamespace(did=DEL, id=7), db=db)
    assert e.value.status_code == 403
    assert "could not confirm its authority right now" in e.value.detail


async def test_end_to_end_an_issuer_suspended_at_its_home_conveys_nothing(monkeypatch):
    """Behavioral on both trees: only the HTTP edge is stubbed. V0430 conveys the whole grant here."""
    monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    monkeypatch.delenv("REDIS_URL", raising=False)
    _wire_http(monkeypatch, _Resp(200, {"credential": "active", "issuer_status": "inactive",
                                        "issuer_permissions": []}))
    assert await _resolve(_grant_db()) == set()
