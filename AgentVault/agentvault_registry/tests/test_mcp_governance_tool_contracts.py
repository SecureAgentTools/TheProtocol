"""AN MCP TOOL MUST BE ABLE TO SUCCEED — ITS BODY KEY AND ITS TYPES MUST MATCH THE ROUTE.

§MCPGOVFIX 2026-09-07. Two governance tools shipped in a state where NO argument
could work, and the api-tester correctly reported both as "cannot succeed as
shipped" (EVTYPES2) — a skip that had been sitting there as a permanent finding
nobody could close, because the defect was in the tool, not the test.

  federationProposeRaise  posted {"proposal_id": …} at a route whose model is
                          FederationProposeRequest(local_proposal_id: int, …) and
                          which reads `body.local_proposal_id` → 422 "Field required"
                          on every call, forever.
  federationVetoProposal  declared proposal_id as an INTEGER and sent int(proposal_id)
                          into a path the EventStore parses as a UUID → 422
                          uuid_parsing. Its own sibling federationVoteProposal already
                          takes the UUID as a string, so the right type was readable
                          from the code the whole time.

This pins BOTH halves against the route they call, so the next edit to either side
has to notice. It reads source rather than calling the tools, deliberately: both are
marked DESTRUCTIVE and one is a commander-only veto — the only honest way to test
"can this succeed" for a tool you must not fire is to check that what it sends
matches what the route demands.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
_TOOLS = _SRC / "mcp" / "tools_developer.py"
_AGENT_TOOLS = _SRC / "mcp" / "tools_agent.py"   # federationVoteProposal lives here
_GOV = _SRC / "routers" / "governance.py"


def _func(tree: ast.Module, name: str) -> ast.AST:
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found — renamed? re-point this gate")


def test_propose_raise_sends_the_field_the_route_requires() -> None:
    gov = _GOV.read_text()
    m = re.search(r"class FederationProposeRequest\(BaseModel\):(.*?)\n\n", gov, re.S)
    assert m, "FederationProposeRequest not found in governance.py"
    required = {
        f for f in re.findall(r"^\s{4}(\w+):", m.group(1), re.M)
        if "= Field(default" not in m.group(1).split(f + ":")[1].split("\n")[0]
    }
    assert "local_proposal_id" in required, (
        f"the route's model no longer requires local_proposal_id ({required}) — "
        f"re-read it and re-point this gate")
    body = ast.dump(_func(ast.parse(_TOOLS.read_text()), "federation_propose_raise"))
    assert "'local_proposal_id'" in body, (
        "federation_propose_raise does not send `local_proposal_id`, the field its "
        "route reads — every call answers 422 'Field required' and the tool cannot "
        "succeed as shipped")


def test_veto_passes_the_proposal_id_through_unchanged() -> None:
    """A UUID must not be coerced to int, and must not be advertised as one."""
    tools = _TOOLS.read_text()
    fn = _func(ast.parse(tools), "federation_veto_proposal")
    # ⚠ AST, not text. The first version of this gate grepped the function's SOURCE
    # for "int(proposal_id)" and failed on the COMMENT that explains the fix — a
    # source-reading gate finds its own documentation first (§V0160's class). The
    # question is whether the CODE coerces, so ask the tree.
    coerces = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "int"
        and any(getattr(a, "id", None) == "proposal_id" for a in n.args)
    ]
    assert not coerces, (
        "federation_veto_proposal still coerces proposal_id to int; the EventStore "
        "path parses a UUID (422 uuid_parsing), so no argument can satisfy both")
    ann = [a.annotation for a in fn.args.args if a.arg == "proposal_id"]
    assert ann and getattr(ann[0], "id", None) == "str", (
        "federation_veto_proposal must take proposal_id as str — federation proposal "
        "ids are UUIDs, as its sibling federationVoteProposal already declares")
    schema = re.search(
        r'\{"name": "theprotocol_federationVetoProposal".*?\}\},', tools, re.S)
    assert schema, "the advertised schema for federationVetoProposal is gone"
    assert '"proposal_id": {"type": "string"}' in schema.group(0), (
        "the advertised inputSchema still says proposal_id is an integer — an "
        "integer cannot address any real federation proposal, so the schema would "
        "describe a tool that cannot be called")


def test_the_sibling_that_was_right_all_along_still_is() -> None:
    """The control: federationVoteProposal is where the correct type was readable.

    If it ever changes to an integer, the reasoning behind the two fixes above is
    gone and this gate should say so rather than keep asserting from memory.
    """
    tools = _AGENT_TOOLS.read_text()
    m = re.search(r'\{"name": "theprotocol_federationVoteProposal".*?\}\},', tools, re.S)
    assert m, "federationVoteProposal schema not found"
    assert '"proposal_id": {"type": "string"}' in m.group(0), (
        "federationVoteProposal no longer declares proposal_id as a string — the "
        "premise these fixes were measured against has moved")
