"""§FEFRAME W3 (V0504): acting as your own agent needs no secret, and the token that allows it lives only while the
session that minted it could act.

POST /developers/me/agents/{did}/session-token mints an agent token from the OWNER's signed-in session: the claims
/auth/agent/token issues (so every agent-tier route admits it unchanged) plus `via: owner`, the owner's id and
token_version. `security.owner_token_refusal` is the one check every agent-token entry point asks; each refusal below
has its control (the same token while the owner is live passes). DB-free: fake sessions answer the one read.
"""
import datetime as dt
import types

import jwt
import pytest
from fastapi import HTTPException

from agentvault_registry import security


class _Row:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _DB:
    """Answers owner_token_refusal's one read with `row`; counts reads (an ordinary token must cause none)."""

    def __init__(self, row=None, explode=False):
        self.row, self.explode, self.reads = row, explode, 0

    async def execute(self, *_a, **_k):
        self.reads += 1
        if self.explode:
            raise AssertionError("an ordinary agent token must not read the owner")
        return _Row(self.row)


def _agent(**over):
    d = dict(id=7, did="did:theprotocol:eu.theprotocol.cloud:3f1c0e8e-0000-4000-8000-000000000007",
             creator_developer_id=42, status="active", enforcement_status="active", client_id="c-7")
    d.update(over)
    return types.SimpleNamespace(**d)


def _developer(**over):
    d = dict(id=42, token_version=3, is_suspended=False, deleted_at=None, deletion_status=None)
    d.update(over)
    return types.SimpleNamespace(**d)


def _claims(token):
    return jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])


def _live_row(dev=None):
    dev = dev or _developer()
    return (dev.token_version, dev.is_suspended, dev.deleted_at, dev.deletion_status)


# ── the token ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_owner_token_carries_every_claim_the_agent_token_carries(monkeypatch):
    monkeypatch.delenv("OWNER_SESSION_TOKEN_MINUTES", raising=False)
    agent, dev = _agent(), _developer()
    token, lifetime = security.create_owner_session_token(agent, dev)
    c = _claims(token)
    # /auth/agent/token's claims (routers/auth_secure.py agent_token): sub = the DID, type = agent, agent_id = str(id)
    assert c["sub"] == agent.did and c["type"] == "agent" and c["agent_id"] == str(agent.id)
    assert c["via"] == "owner" and c["owner"] == str(dev.id) and c["owner_tv"] == dev.token_version
    assert lifetime == 30 * 60
    exp = dt.datetime.fromtimestamp(c["exp"], dt.timezone.utc)
    assert dt.timedelta(minutes=29) < exp - dt.datetime.now(dt.timezone.utc) <= dt.timedelta(minutes=30)
    assert c.get("jti")


async def test_the_agent_token_verifier_admits_it_and_passes_the_owner_claims_on():
    token, _ = security.create_owner_session_token(_agent(), _developer())
    info = await security.verify_agent_token(request=types.SimpleNamespace(state=types.SimpleNamespace()), token=token)
    assert info["did"] == _agent().did and info["id"] == 7
    assert info["via"] == "owner" and info["owner"] == "42" and info["owner_tv"] == 3


@pytest.mark.parametrize("raw,want", [(None, 30), ("5", 5), ("0", 1), ("999", 120), ("soon", 30), ("", 30)])
def test_the_lifetime_is_bounded_and_survives_a_bad_value(monkeypatch, raw, want):
    if raw is None:
        monkeypatch.delenv("OWNER_SESSION_TOKEN_MINUTES", raising=False)
    else:
        monkeypatch.setenv("OWNER_SESSION_TOKEN_MINUTES", raw)
    assert security.owner_session_token_minutes() == want


# ── the refusal: one function, every entry point ───────────────────────────────────────────────────────────────────

async def test_an_ordinary_agent_token_is_never_asked_about_an_owner():
    db = _DB(explode=True)
    assert await security.owner_token_refusal(db, {"did": "x", "id": 1, "act": None}, _agent()) is None
    assert await security.owner_token_refusal(db, {"did": "x", "via": None}, _agent()) is None
    assert db.reads == 0


async def test_a_live_owner_passes():
    db = _DB(row=_live_row())
    assert await security.owner_token_refusal(db, {"via": "owner", "owner": "42", "owner_tv": 3}, _agent()) is None
    assert db.reads == 1


@pytest.mark.parametrize("row,claims,agent,needle", [
    # a logout everywhere or a password change bumps token_version
    (_live_row(_developer(token_version=4)), {"via": "owner", "owner": "42", "owner_tv": 3}, _agent(), "session ended"),
    (_live_row(_developer(is_suspended=True)), {"via": "owner", "owner": "42", "owner_tv": 3}, _agent(), "suspended"),
    (_live_row(_developer(deleted_at=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))),
     {"via": "owner", "owner": "42", "owner_tv": 3}, _agent(), "deleted"),
    (_live_row(_developer(deletion_status="anonymized")), {"via": "owner", "owner": "42", "owner_tv": 3}, _agent(), "deleted"),
    (None, {"via": "owner", "owner": "42", "owner_tv": 3}, _agent(), "no longer exists"),
    # the agent was transferred to someone else
    (_live_row(), {"via": "owner", "owner": "42", "owner_tv": 3}, _agent(creator_developer_id=99), "no longer belongs"),
    (_live_row(), {"via": "owner", "owner": "x", "owner_tv": 3}, _agent(), "malformed"),
    (_live_row(), {"via": "owner", "owner": "42"}, _agent(), "malformed"),
])
async def test_an_owner_token_ends_with_its_session(row, claims, agent, needle):
    why = await security.owner_token_refusal(_DB(row=row), claims, agent)
    assert why and needle in why


async def test_get_current_agent_refuses_an_owner_token_after_a_logout_everywhere(monkeypatch):
    agent = _agent()

    async def _by_did(db, did):
        return agent

    async def _touch(db, agent_id):
        return None

    monkeypatch.setattr(security.agent_crud, "get_agent_by_did", _by_did)
    monkeypatch.setattr(security.agent_crud, "update_agent_last_active", _touch)
    info = {"did": agent.did, "id": agent.id, "act": None, "via": "owner", "owner": "42", "owner_tv": 3}
    # control: the same token while the owner is live is the agent
    assert await security.get_current_agent(db=_DB(row=_live_row()), agent_info=info) is agent
    with pytest.raises(HTTPException) as e:
        await security.get_current_agent(db=_DB(row=_live_row(_developer(token_version=4))), agent_info=info)
    assert e.value.status_code == 401 and "Owner session token refused" in str(e.value.detail)


async def test_the_second_agent_resolver_asks_the_same_question(monkeypatch):
    from agentvault_registry.routers import utils as rutils
    agent = _agent()

    class _ResDB(_DB):
        def __init__(self, owner_row):
            super().__init__(row=owner_row)
            self.calls = 0

        async def execute(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:      # the agent lookup
                return types.SimpleNamespace(scalar_one_or_none=lambda: agent)
            return _Row(self.row)    # the owner read

    info = {"did": agent.did, "id": agent.id, "via": "owner", "owner": "42", "owner_tv": 3}
    assert await rutils.get_current_agent(db=_ResDB(_live_row()), token_data=info) is agent
    with pytest.raises(HTTPException) as e:
        await rutils.get_current_agent(db=_ResDB(_live_row(_developer(is_suspended=True))), token_data=info)
    assert e.value.status_code == 401


# ── the mint's own refusals ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_mint_refuses_what_it_must():
    from agentvault_registry.routers.developers import owner_mint_refusal
    dev = _developer()
    assert owner_mint_refusal(_agent(), dev, "eyJhbGciOi.jwt.token") is None                      # the control
    assert owner_mint_refusal(_agent(), dev, "avreg_abc")[0] == 403                                # an API key
    assert owner_mint_refusal(None, dev, "eyJ.x.y")[0] == 404                                      # no such agent
    assert owner_mint_refusal(_agent(creator_developer_id=99), dev, "eyJ.x.y")[0] == 404           # not yours
    assert owner_mint_refusal(_agent(status="suspended"), dev, "eyJ.x.y")[0] == 403
    assert owner_mint_refusal(_agent(status="revoked"), dev, "eyJ.x.y")[0] == 403
    assert owner_mint_refusal(_agent(enforcement_status="suspended"), dev, "eyJ.x.y")[0] == 403


def test_the_route_is_mounted_and_rate_limited():
    from agentvault_registry.routers import developers
    routes = {(r.path, tuple(sorted(r.methods))) for r in developers.router.routes}
    assert ("/developers/me/agents/{agent_did}/session-token", ("POST",)) in routes
    import inspect
    params = inspect.signature(developers.mint_owner_session_token).parameters
    # slowapi needs both by NAME, or the decorated route answers 500 (§RATEFIX)
    assert "request" in params and "response" in params
