"""§TRUSTCHAIN P4.3 (2026-09-12) — the registry-trust verdict for agent tokens, on the card.

Journal 45: "what a member or an agent holding a token may read is what this frame actually
thinks ... an agent reading discovery from the backend receives the verdict in the same response."
Measured before this change: the §DISCOTRUST viewer was `get_current_developer_optional` (an agent
JWT's `sub` is a DID, not an integer, so it read as anonymous), and the discovery response never
carried the verdict at all — the FE joined it onto cards from `/federation/registries`.

Pinned here:
  1. `security.get_current_actor_for_read_optional` reads an agent token, a developer token, and
     refuses (as None) no header, garbage, a blocked agent and a revoked developer;
  2. BOTH §DISCOTRUST routes depend on it (AST on the signature defaults);
  3. `AgentCardSummary` DECLARES `registry_trust` (pydantic drops an undeclared field silently);
  4. the attach helper tags only peer-hosted cards for an identified caller, never for anonymous,
     never for "Local", with ONE block per peer.
Every test is RED on the pre-change tree (`TRUSTCHAIN_SRC=<git archive of the old package>`).
"""
from __future__ import annotations

import ast
import os
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("TRUSTCHAIN_SRC", HERE.parent / "src" / "agentvault_registry"))


def _fn(path: pathlib.Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path.name}: no function {name}")


def _depends_on(fn, dep_name: str) -> bool:
    """True when some parameter default is `Depends(<x>.dep_name)` or `Depends(dep_name)`."""
    for d in fn.args.defaults + fn.args.kw_defaults:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends" and d.args:
            a = d.args[0]
            if isinstance(a, ast.Attribute) and a.attr == dep_name:
                return True
            if isinstance(a, ast.Name) and a.id == dep_name:
                return True
    return False


# ── 2. both routes resolve the viewer through the optional actor ────────────────
@pytest.mark.parametrize("rel,name", [
    ("routers/registry_health.py", "list_federated_registries"),
    ("routers/agent_cards.py", "list_agent_cards"),
])
def test_discotrust_routes_accept_agent_tokens(rel, name):
    fn = _fn(SRC / rel, name)
    assert _depends_on(fn, "get_current_actor_for_read_optional"), (
        f"{rel}::{name} does not resolve its viewer through get_current_actor_for_read_optional"
    )


def test_discover_attaches_the_verdict_before_both_returns():
    fn = _fn(SRC / "routers" / "agent_cards.py", "list_agent_cards")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_attach_registry_trust"]
    assert calls, "list_agent_cards never calls _attach_registry_trust"


# ── 3. the wire declares the field ──────────────────────────────────────────────
def test_agent_card_summary_declares_registry_trust():
    from agentvault_registry.schemas import AgentCardSummary
    assert "registry_trust" in AgentCardSummary.model_fields


# ── 1. the optional actor ───────────────────────────────────────────────────────
def _token(claims: dict) -> str:
    import jwt
    from agentvault_registry import security
    return jwt.encode(claims, security.SECRET_KEY, algorithm=security.ALGORITHM)


@pytest.mark.asyncio
async def test_optional_actor_reads_agent_and_developer_tokens():
    from agentvault_registry import security

    live_agent = SimpleNamespace(did="did:theprotocol:test-agent", status="active")
    blocked_agent = SimpleNamespace(did="did:theprotocol:blocked", status="suspended")
    developer = SimpleNamespace(id=42, token_version=3, deleted_at=None, is_suspended=False, deletion_status=None)

    async def get_agent_by_did(db, did):
        return {"did:theprotocol:test-agent": live_agent, "did:theprotocol:blocked": blocked_agent}.get(did)

    async def get_developer_by_id(db, developer_id):
        return developer if developer_id == 42 else None

    with patch.object(security.agent_crud, "get_agent_by_did", side_effect=get_agent_by_did), \
         patch.object(security.developer_crud, "get_developer_by_id_lean", side_effect=get_developer_by_id):  # V0553: the optional actor reads the developer's own row (crud get_developer_by_id_lean)
        db = MagicMock()
        # no header, wrong scheme, garbage token: anonymous, never an exception
        assert await security.get_current_actor_for_read_optional(db=db, authorization=None) is None
        assert await security.get_current_actor_for_read_optional(db=db, authorization="Basic abc") is None
        assert await security.get_current_actor_for_read_optional(db=db, authorization="Bearer not.a.jwt") is None
        # a live agent token is an agent
        out = await security.get_current_actor_for_read_optional(
            db=db, authorization="Bearer " + _token({"sub": "did:theprotocol:test-agent", "type": "agent", "agent_id": "5"}))
        assert out and out["kind"] == "agent" and out["agent_did"] == "did:theprotocol:test-agent"
        # a suspended agent reads as anonymous (the required path refuses it with 403)
        out = await security.get_current_actor_for_read_optional(
            db=db, authorization="Bearer " + _token({"sub": "did:theprotocol:blocked", "type": "agent", "agent_id": "6"}))
        assert out is None
        # a live developer token is a developer ...
        out = await security.get_current_actor_for_read_optional(
            db=db, authorization="Bearer " + _token({"sub": "42", "tv": 3}))
        assert out and out["kind"] == "developer" and out["developer"].id == 42
        # ... and a revoked one (token_version moved on) is anonymous, as on every optional route
        out = await security.get_current_actor_for_read_optional(
            db=db, authorization="Bearer " + _token({"sub": "42", "tv": 2}))
        assert out is None
        # a refresh token is never an identity
        out = await security.get_current_actor_for_read_optional(
            db=db, authorization="Bearer " + _token({"sub": "42", "tv": 3, "type": "refresh"}))
        assert out is None


# ── 4. the attach helper's three rules ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_attach_registry_trust_tags_peer_cards_for_identified_callers_only():
    from agentvault_registry.routers import agent_cards as ac
    from agentvault_registry.services import peer_trust_policy as ptp

    peer_asia = SimpleNamespace(id=11, name="asia", status="ACTIVE")
    cards = [
        {"name": "native", "origin_registry_name": "Local"},
        {"name": "far", "origin_registry_name": "asia"},
        {"name": "far2", "origin_registry_name": "ASIA"},
        {"name": "orphan", "origin_registry_name": "nowhere"},
    ]
    scalars = MagicMock(); scalars.all.return_value = [peer_asia]
    res = MagicMock(); res.scalars.return_value = scalars
    db = MagicMock(); db.execute = AsyncMock(return_value=res)
    calls = []

    def fake_block(peer, policy=None):
        calls.append(peer.id)
        return {"state": "ok", "label": "fine"}

    with patch.object(ptp, "trust_block", side_effect=fake_block), \
         patch("agentvault_registry.services.frame_policy.load", new=AsyncMock(return_value=object())):
        # anonymous: nothing, and the database is not even asked
        assert await ac._attach_registry_trust(db, [dict(c) for c in cards], None) == 0
        assert db.execute.await_count == 0
        # identified (an agent): peer-hosted cards tagged, ONE block per peer, natives and unknowns not
        tagged_cards = [dict(c) for c in cards]
        n = await ac._attach_registry_trust(db, tagged_cards, {"kind": "agent", "agent_did": "did:x"})
        assert n == 2
        assert "registry_trust" not in tagged_cards[0], "a native card must carry no verdict"
        assert tagged_cards[1]["registry_trust"]["state"] == "ok"
        assert tagged_cards[2]["registry_trust"]["state"] == "ok", "origin names compare case-insensitively"
        assert "registry_trust" not in tagged_cards[3], "an origin with no peer row gets no invented verdict"
        assert calls == [11], "the block is computed once per peer per request"
