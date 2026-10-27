"""§MCPTEST30 (V0636): every earned lifecycle, run offline against bridges that hold each call to its tool's schema.

An earned lifecycle runs a tool's success path on a subject the run makes for it alone (earned_fixtures.py). Its
mistakes that need no live registry are found here, before a build: a tool that is not on the bridge it was sent to,
an argument the tool does not declare, a required one missing, a value of the wrong JSON type, a row recorded under a
name the runner drops, a subject it made and never cleared away, and a raise. The bridges answer 2xx from a script
(createAgent a fresh DID and credentials, getAgentToken a token, every other call its own arguments back), so a row
may read healthy or a BUG-FIND here: this test judges the calls, never the verdicts.
"""
from __future__ import annotations

import asyncio
import itertools
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev, earned_agent_public
from agentvault_registry.api_tests.contracts.mcp_lifecycles import LIFECYCLES

EARNED = [*earned_admin_dev.LIFECYCLES, *earned_agent_public.LIFECYCLES]
_JSON_TYPES = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,), "object": (dict,),
               "array": (list, tuple)}
# the ids a lifecycle reads from an answer before its later calls: the scripted bridges add them, so the gate reaches
# those calls too
_ANSWER_IDS = {
    "theprotocol_createVersion": ("version_id",),
    "theprotocol_triggerDeployment": ("deployment_id",),
    "theprotocol_transferUnits": ("transaction_id",),
    "theprotocol_sendChatMessage": ("conversation_id",),
    "theprotocol_grantSupportReview": ("grant_id",),
    "theprotocol_inviteOrganizationMember": ("token", "invitation_id"),
    "theprotocol_resetAgentCredentialsOnboard": ("client_id", "client_secret"),
}


def _schemas() -> Tuple[Dict[str, dict], Dict[str, dict]]:
    from agentvault_registry.mcp import server, server_admin
    pub = {s["name"]: s for s in server.ALL_TOOL_SCHEMAS if isinstance(s, dict) and "name" in s}
    adm = {s["name"]: s for s in server_admin.ADMIN_TOOL_SCHEMAS if isinstance(s, dict) and "name" in s}
    return pub, adm


def _problems(tool: str, args: Dict[str, Any], schemas: Dict[str, dict], surface: str) -> List[str]:
    sc = schemas.get(tool)
    if sc is None:
        return [f"{tool} is not a tool of the {surface} bridge"]
    inp = sc.get("inputSchema") or {}
    props = inp.get("properties") or {}
    extra = {"agent_jwt"} if surface == "public" else set()
    out = [f"{tool}: '{k}' is required and not sent" for k in inp.get("required") or [] if k not in args]
    for k, v in args.items():
        if k not in props and k not in extra:
            out.append(f"{tool}: '{k}' is not an argument it declares ({sorted(props)})")
            continue
        want = (props.get(k) or {}).get("type")
        kinds = want if isinstance(want, list) else [want] if want else []
        ok = any(isinstance(v, _JSON_TYPES.get(w, object)) and not (w in ("integer", "number") and isinstance(v, bool))
                 for w in kinds if w != "null") or (v is None and "null" in kinds) or not kinds
        if not ok:
            out.append(f"{tool}: '{k}' is {type(v).__name__}, the schema says {want}")
    return out


class _World:
    """Both bridges and the runner's hooks, answering from a script and remembering what the lifecycle made."""

    def __init__(self) -> None:
        self.pub, self.adm = _schemas()
        self.problems: List[str] = []
        self.made: Dict[str, str] = {}          # did -> its owner's token
        self.deleted: List[str] = []
        self.calls: List[Tuple[str, str]] = []
        self._n = itertools.count(1)

    def _answer(self, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[bool, dict, str]:
        n = next(self._n)
        if tool == "theprotocol_createAgent":
            did = f"did:theprotocol:offline-{n}"
            self.made[did] = jwt
            return True, {"did": did, "client_id": f"cid-{n}", "client_secret": f"sec-{n}"}, "200"
        if tool == "theprotocol_getAgentToken":
            return True, {"access_token": f"agent-jwt-{n}"}, "200"
        if tool in ("theprotocol_deleteMyAgentByDev", "theprotocol_deleteAdminAgent"):
            self.deleted.append(str(args.get("agent_did")))
        if tool == "theprotocol_forceEmailVerify":
            return False, {"_text": "Error: HTTP 400: Email already verified"}, "400"
        echo = {k: v for k, v in args.items() if k != "agent_jwt" and isinstance(v, (str, int, float, bool))}
        return True, {"status": "ok", "id": n, **echo, **{k: f"{k}-{n}" for k in _ANSWER_IDS.get(tool, ())}}, "200"

    def bridge(self, surface: str):
        schemas = self.adm if surface == "admin" else self.pub

        async def call(tool: str, args: dict, jwt: str = "", timeout: int = 20):
            self.calls.append((surface, tool))
            self.problems.extend(_problems(tool, dict(args or {}), schemas, surface))
            ok, result, code = self._answer(tool, dict(args or {}), jwt)
            return ok, {"result": result}, code
        return call


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


def _bag(world: _World) -> Any:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    n = itertools.count(100)

    async def _mint(role: str) -> Dict[str, Any]:
        i = next(n)
        return {"email": f"mcp-throwaway-{role}-{i}@throwaway-pl.example.com", "password": "pw", "developer_id": str(i),
                "access_token": f"dev-jwt-{i}", "refresh_token": ""}

    async def _login(email: str, password: str):
        return "200", {"access_token": "login-jwt"}

    bag.mint_throwaway = _mint            # type: ignore[attr-defined]
    bag.dev_login = _login
    bag.rpc_admin = world.bridge("admin")  # type: ignore[attr-defined]
    bag.admin_lifecycle_rows = {}          # type: ignore[attr-defined]

    async def _events(types, tool):
        return True, None
    bag.event_verifier = _events           # type: ignore[attr-defined]
    return bag


def test_the_earned_lifecycles_are_registered_once():
    names = [lc["name"] for lc in LIFECYCLES]
    for lc in EARNED:
        assert names.count(lc["name"]) == 1, lc["name"]


@pytest.mark.parametrize("lc", EARNED, ids=[lc["name"] for lc in EARNED])
def test_an_earned_lifecycle_calls_each_tool_as_its_schema_says_and_clears_away_what_it_made(lc):
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
        _SYNTHETIC_ROW_PREFIXES,
    )
    world = _World()
    bag = _bag(world)
    outcomes: Dict[str, dict] = {}
    asyncio.run(lc["runner"](world.bridge("public"), _parse, bag, outcomes))
    assert not world.problems, "\n".join(sorted(set(world.problems)))
    raised = [n for n, r in outcomes.items() if "lifecycle raised" in str(r.get("skip_reason") or "")]
    assert not raised, {n: outcomes[n]["skip_reason"] for n in raised}
    assert outcomes, "the lifecycle recorded no row"
    for name in outcomes:
        assert name.startswith("theprotocol_") or name.startswith(_SYNTHETIC_ROW_PREFIXES), \
            f"{name!r} is recorded under a name the runner drops"
    left = sorted(set(world.made) - set(world.deleted))
    assert not left, f"made and never cleared away: {left}"
