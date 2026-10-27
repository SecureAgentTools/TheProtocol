"""§MCPTEST30 (V0636): the subjects and row helpers the earned lifecycles share (api_tests/contracts/earned_fixtures.py).

A refusal-only tool earns its success path on a subject the run makes for it alone. These pin the helpers offline: a
refusal is filed under `refusal: <tool> <what>` and passes only on the refusal it names; the throwaway developer and
agent are made, verified and cleared away through the rails a person uses; an admin step without an admin bridge is
NOT MEASURED, named; and the earned modules register without an import cycle, whichever is imported first.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import subprocess
import sys
from typing import Any, Dict, List, Tuple

from agentvault_registry.api_tests.contracts import earned_fixtures as ef

CONTRACTS = pathlib.Path(ef.__file__).resolve().parent
RUNNER = CONTRACTS.parent / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py"
EARNED = ("earned_fixtures", "earned_admin_dev", "earned_agent_public")
# every module that holds earned lifecycles: the two above and the family modules they gather
EARNED_ALL = tuple(sorted({p.stem for p in CONTRACTS.glob("earned_*.py")}))


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


class _Rpc:
    """A bridge that answers from a script: tool -> (ok, result, http code)."""

    def __init__(self, answers: Dict[str, Tuple[bool, Dict[str, Any], str]]):
        self.answers, self.calls = answers, []

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args), jwt))
        ok, result, code = self.answers.get(tool, (False, {"_text": "Error: no such tool here"}, "404"))
        return ok, {"result": result}, code


class _Bag:
    developer_jwt = "runner-dev-jwt"

    def __init__(self, rpc_admin=None):
        self.rpc_admin = rpc_admin
        self.deleted: List[str] = []

        async def _mint(role: str) -> Dict[str, Any]:
            return {"email": f"mcp-throwaway-{role}@throwaway-pl.example.com", "password": "pw", "developer_id": "77",
                    "access_token": "throwaway-dev-jwt", "refresh_token": ""}
        self.mint_throwaway = _mint

        async def _login(email: str, password: str):
            self.deleted.append(email)
            return "200", {"access_token": "login-jwt"}
        self.dev_login = _login


def _run(coro):
    return asyncio.run(coro)


def test_a_refusal_is_filed_under_its_own_name_and_passes_only_on_the_refusal_it_names():
    rpc = _Rpc({"theprotocol_rotateAgentCredentials": (False, {"_text": "Error: Agent x not found"}, "404")})
    out: Dict[str, dict] = {}
    assert _run(ef.refusal_step(rpc, _parse, "theprotocol_rotateAgentCredentials", "admin", {"agent_did": "x"}, "j",
                                out, "an agent that does not exist", codes=(404,), text="not found"))
    assert list(out) == ["refusal: rotateAgentCredentials an agent that does not exist"]
    row = out["refusal: rotateAgentCredentials an agent that does not exist"]
    assert row["tool_name"] == "refusal: rotateAgentCredentials an agent that does not exist" and row["healthy"]
    # another refusal code, another reason, or a success: the row fails
    out = {}
    assert not _run(ef.refusal_step(rpc, _parse, "theprotocol_rotateAgentCredentials", "admin", {}, "j", out, "w",
                                    codes=(422,)))
    assert "not one of [422]" in out["refusal: rotateAgentCredentials w"]["fail_reason"]
    out = {}
    assert not _run(ef.refusal_step(rpc, _parse, "theprotocol_rotateAgentCredentials", "admin", {}, "j", out, "w",
                                    codes=(404,), text="already rotated"))
    assert "not for the rule under test" in out["refusal: rotateAgentCredentials w"]["fail_reason"]
    ok_rpc = _Rpc({"theprotocol_rotateAgentCredentials": (True, {"rotated": True}, "200")})
    out = {}
    assert not _run(ef.refusal_step(ok_rpc, _parse, "theprotocol_rotateAgentCredentials", "admin", {}, "j", out, "w"))
    assert out["refusal: rotateAgentCredentials w"]["healthy"] is False


def test_a_throwaway_developer_and_agent_are_made_and_cleared_away_through_the_rails():
    admin = _Rpc({"theprotocol_forceEmailVerify": (False, {"_text": "Error: Email already verified"}, "400")})
    bag = _Bag(rpc_admin=admin)
    rpc = _Rpc({
        "theprotocol_createAgent": (True, {"did": "did:theprotocol:t1", "client_id": "c1", "client_secret": "s1"}, "200"),
        "theprotocol_getAgentToken": (True, {"access_token": "agent-jwt"}, "200"),
        "theprotocol_deleteMyAgentByDev": (True, {"deleted": True}, "200"),
        "theprotocol_requestAccountDeletion": (True, {"status": "pending_deletion"}, "200"),
    })
    t = ef.Throwaways(rpc, _parse, bag, "unit")
    dev = _run(t.developer("unit"))
    assert dev["developer_id"] == 77 and not dev.get("why")
    assert admin.calls == [("theprotocol_forceEmailVerify", {"developer_id": 77}, "runner-dev-jwt")]
    ag = _run(t.agent(dev))
    assert (ag["did"], ag["agent_jwt"], ag["owner_jwt"]) == ("did:theprotocol:t1", "agent-jwt", "throwaway-dev-jwt")
    # the tier-0 token call rides the owner's bearer (V0614)
    assert ("theprotocol_getAgentToken", {"client_id": "c1", "client_secret": "s1"}, "throwaway-dev-jwt") in rpc.calls
    _run(t.close())
    assert ("theprotocol_deleteMyAgentByDev", {"agent_did": "did:theprotocol:t1"}, "throwaway-dev-jwt") in rpc.calls
    assert bag.deleted == ["mcp-throwaway-unit@throwaway-pl.example.com"]
    assert [c[0] for c in rpc.calls].count("theprotocol_requestAccountDeletion") == 1


def test_a_subject_that_cannot_be_made_says_why():
    bag = _Bag(rpc_admin=_Rpc({"theprotocol_forceEmailVerify": (False, {"_text": "Error: nope"}, "500")}))
    t = ef.Throwaways(_Rpc({}), _parse, bag, "unit")
    dev = _run(t.developer("unit"))
    assert "forceEmailVerify for the throwaway developer answered HTTP 500" in dev["why"]
    ag = _run(t.agent(dev))
    assert ag.get("why") and not ag.get("did")
    bag.mint_throwaway = None
    assert "no mint_throwaway" in _run(ef.Throwaways(_Rpc({}), _parse, bag, "u").developer("u"))["why"]


def test_an_admin_step_without_an_admin_bridge_is_not_measured_named():
    out: Dict[str, dict] = {}
    ok, _ = _run(ef.effect(_Bag(rpc_admin=None), _parse, "theprotocol_suspendAgent", {"agent_did": "x"}, out))
    assert not ok
    row = out["admin_effect: suspendAgent"]
    assert row["skip_reason"].startswith("NOT MEASURED") and row["contract_tier"] == "admin_effect"


def test_the_earned_modules_never_import_the_lifecycles_module_at_import_time():
    assert set(EARNED) <= set(EARNED_ALL)
    for mod in EARNED_ALL:
        tree = ast.parse((CONTRACTS / f"{mod}.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            assert not any("mcp_lifecycles" in n for n in names), f"{mod} imports mcp_lifecycles at module level"


def test_the_lifecycles_module_carries_both_earned_lists_whichever_is_imported_first():
    for first in EARNED_ALL + ("mcp_lifecycles",):
        code = (f"import agentvault_registry.api_tests.contracts.{first}\n"
                "from agentvault_registry.api_tests.contracts import mcp_lifecycles as m, earned_admin_dev as a, "
                "earned_agent_public as b\n"
                "names = [lc['name'] for lc in m.LIFECYCLES]\n"
                "assert all(lc['name'] in names for lc in a.LIFECYCLES + b.LIFECYCLES)\n"
                "assert len(names) == len(set(names)), 'a lifecycle registered twice'\n"
                "print('ok', len(names))\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0 and "ok" in r.stdout, f"importing {first} first: {r.stderr[-600:]}"


def test_the_runner_keeps_refusal_rows():
    src = RUNNER.read_text()
    start = src.index("_SYNTHETIC_ROW_PREFIXES = (")
    end = src.index(")", src.index('"refusal: "', start))
    assert '"refusal: "' in src[start:end + 1]
    assert ef.REFUSAL == "refusal: "
