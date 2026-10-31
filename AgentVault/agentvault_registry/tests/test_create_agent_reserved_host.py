"""V0650 (e) (2026-10-31, agentvault2-14): an agent created on a special-use host is refused, before anything is made.

Order gwo_940ce3d7c4dfac6c47a3890f. create_agent with agent_host and no agent_card builds a placeholder card that the
card pull-sync replaces with the agent's own card once the host answers. A host on a special-use name (RFC 6761/6762:
.invalid, .test, .example, .local, .localhost) never resolves on any public DNS and the pull-sync never asks it, so
such an agent kept its placeholder for good, silently. It is now refused (400) with a sentence, after the token and
proof-of-work checks and before the DID mint: no DID, no credentials, no row, and the bootstrap token stays unused. The
rule is the pull-sync's own (agent_card_pullsync.reserved_tld_of), so the skip and the refusal cannot drift apart. A
public host, and a caller that sends its card itself, are not affected.

Through FastAPI on the real onboarding route; the database is a double that holds one live bootstrap token, and the DID
mint is a spy that raises, so reaching it is observable without faking the rest of creation. Cases marked BASE fail on
6c1f036b (V0649).
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.background_tasks import agent_card_pullsync as ps
from agentvault_registry.database import get_db
from agentvault_registry.middleware.rate_limiter import shared_limiter
from agentvault_registry.routers import onboarding

PLAIN = "bst_0123456789abcdef_" + "e" * 32
RESERVED = ["https://exttest-agent-1.invalid", "https://a.b.test/api", "http://foo.example/",
            "https://canary-x-sender.agents.local", "http://x.localhost:8080", "http://localhost:8790"]
PUBLIC = ["https://exttest-agent-1.example.com", "https://pocket7-b.invalid.example.theprotocol.cloud/a2a"]


def _sha(v):
    return hashlib.sha256(v.encode()).hexdigest()


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self):
        self.token = SimpleNamespace(id=1, token_value=f"sha256:{_sha(PLAIN)}", token_value_hash=_sha(PLAIN),
                                     is_used=False, used_at=None, creator_developer_id=41,
                                     expires_at=datetime.now(timezone.utc) + timedelta(minutes=4))
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def execute(self, stmt, *a, **k):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if f"'{self.token.token_value_hash}'" in sql:
            return _Result(self.token)
        return _Result(None)


class _Reached(Exception):
    pass


@pytest.fixture()
def create(monkeypatch):
    monkeypatch.setattr(shared_limiter, "enabled", False)
    monkeypatch.delenv("POW_REQUIRED", raising=False)
    calls = []

    async def _mint(db, method, site=None):
        calls.append(site)
        raise onboarding.DidMintCollision("sentinel: the request reached the DID mint")
    monkeypatch.setattr(onboarding, "mint_unique_agent_did", _mint)

    def call(body):
        db = _Db()
        app = FastAPI()
        app.state.limiter = shared_limiter
        app.include_router(onboarding.router)
        app.dependency_overrides[get_db] = lambda: db
        r = TestClient(app, raise_server_exceptions=False).post(
            "/onboard/create_agent", json=body, headers={"Bootstrap-Token": PLAIN})
        return r, db
    call.calls = calls
    return call


def test_the_rule_is_the_pull_syncs_own():
    # BASE: ImportError (no reserved_tld_of)
    from agentvault_registry.background_tasks.agent_card_pullsync import reserved_tld_of
    assert [reserved_tld_of(u) for u in RESERVED] == ["invalid", "test", "example", "local", "localhost", "localhost"]
    assert [reserved_tld_of(u) for u in PUBLIC + ["https://veridian.theprotocol.cloud/api/witness"]] == [None] * 3
    assert all(ps._is_skippable_host(u) for u in RESERVED), "the worker never asks a host create refuses"


@pytest.mark.parametrize("host", RESERVED)
def test_a_special_use_host_is_refused_before_anything_is_created(create, host):
    # BASE: the call reaches the DID mint (500 sentinel)
    r, db = create({"agent_did_method": "theprotocol", "agent_host": host, "agent_name": "probe"})
    assert r.status_code == 400, (r.status_code, r.text[:300])
    detail = r.json().get("detail", "") if isinstance(r.json(), dict) else ""
    detail = detail if isinstance(detail, str) else json.dumps(detail)
    tld = host.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].rsplit(".", 1)[-1]
    assert "agent_host" in detail and f".{tld}" in detail and "agent_card" in detail, detail
    assert create.calls == [] and db.added == [] and db.token.is_used is False


@pytest.mark.parametrize("host", PUBLIC)
def test_a_public_host_goes_on_to_the_mint(create, host):
    # control: the refusal is not a blanket one
    r, _ = create({"agent_did_method": "theprotocol", "agent_host": host})
    assert r.status_code == 500 and "sentinel" in r.text and create.calls == ["create_agent"], r.text[:200]


def test_a_card_sent_with_a_special_use_host_is_not_refused_here(create):
    # control: the Forge and older callers send their card; nobody asks them to be reachable
    card = {"protocolVersion": "1.0", "agentVersion": "1.0.0", "humanReadableId": "forge-x", "name": "forge-x",
            "description": "d", "url": "https://forge-x.invalid",
            "supportedInterfaces": [{"url": "https://forge-x.invalid", "protocolBinding": "JSONRPC",
                                     "protocolVersion": "1.0"}],
            "provider": {"name": "p"}, "capabilities": {"streaming": False}}
    r, _ = create({"agent_did_method": "theprotocol", "agent_card": card, "agent_host": "https://forge-x.invalid"})
    assert r.status_code == 500 and "sentinel" in r.text, r.text[:200]


def test_the_canary_recipe_sends_a_card_this_registry_takes():
    """The operator manual's canary step is run, not read: its create_agent body sends a card, no reserved agent_host,
    and the card validates as the registry validates it."""
    from agentvault_registry.background_tasks.agent_card_pullsync import reserved_tld_of
    docs = Path(onboarding.__file__).resolve().parents[1] / "static" / "new_registry_frontend" / "src" / "assets" / "docs"
    text = (docs / "operator" / "18_canaries.md").read_text(encoding="utf-8")
    m = re.search(r"create_agent\".*?-d '(\{.*?\})'\n", text, re.S)
    assert m, "the canary recipe's create_agent body was not found"
    body = json.loads(m.group(1).replace("<reg>", "myframe"))
    assert "agent_host" not in body and "agent_card" in body
    from agentvault import AgentCard
    AgentCard.model_validate(body["agent_card"])
    assert reserved_tld_of(body["agent_card"]["supportedInterfaces"][0]["url"]) == "local"
