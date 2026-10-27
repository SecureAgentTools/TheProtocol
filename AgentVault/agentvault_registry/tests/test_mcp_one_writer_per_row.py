"""§MCPTEST30 (V0636): a tool a lifecycle earns a success row for is never probed under its own name elsewhere.

The runner runs lifecycles in parallel into ONE dict keyed by tool name, so a second writer of a tool's row replaces
the first, whichever finishes last (agentvault2-aa's note, 2026-10-24). Batch 3 gave tegSystemTransfer, and run_zk_v2
gave getAttestationDetail and getAttestationBundle, a real success row while mcp_lifecycles still probed each under its
own name with an any answer: the nightly row would have been a coin toss between a 200 and a 400/403 "pass". A
refusal kept as a test is a `refusal:` row (earned_fixtures.refusal_step), never the tool's own.
"""
from __future__ import annotations

import ast
import pathlib

C = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "contracts"


def _literal_tool(call: ast.Call, idx: int, names: dict):
    a = call.args
    if len(a) <= idx:
        return None
    v = a[idx].value if isinstance(a[idx], ast.Constant) else names.get(getattr(a[idx], "id", None))
    return v if isinstance(v, str) and v.startswith("theprotocol_") else None


def _kw(call: ast.Call, name: str):
    for k in call.keywords:
        if k.arg == name and isinstance(k.value, ast.Constant):
            return k.value.value
    return None


def _own_name_writes(path: pathlib.Path):
    """(tool, expected answer, line) for every call that files a row under the tool's own name. A tool named by a
    variable resolves to the module constant of that name, or to the latest assignment of a tool name to it above the
    call in the same function (`tool = "theprotocol_..."; await step(rpc, parse, tool, ...)`, agentvault2-aa's modules)."""
    out = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
             for t in n.targets if isinstance(t, ast.Name)}     # module constants: SYSTEM_TRANSFER = "theprotocol_..."
    scopes = [tree] + [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        local = sorted((n.lineno, t.id, n.value.value) for n in ast.walk(scope) if isinstance(n, ast.Assign)
                       and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                       and n.value.value.startswith("theprotocol_") for t in n.targets if isinstance(t, ast.Name))
        for n in ast.walk(scope):
            if not isinstance(n, ast.Call):
                continue
            here = {**names, **{nm: v for ln, nm, v in local if ln < n.lineno}} if scope is not tree else names
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            if name in ("_exec_step", "step"):
                tool = _literal_tool(n, 2, here)
                if tool and _kw(n, "record_as_separate") is not False:
                    out.add((tool, _kw(n, "expect_status") or "success", n.lineno))
            elif name == "tool_row":
                tool = _literal_tool(n, 0, here)
                if tool:
                    out.add((tool, "success", n.lineno))
    return sorted(out, key=lambda x: x[2])


def test_no_tool_earned_elsewhere_is_probed_under_its_own_name():
    files = ["earned_agent_public.py", "zk_v2_attestations.py", *sorted(p.name for p in C.glob("earned_ad_*.py"))]
    earned = {t for f in files for t, want, _ in _own_name_writes(C / f) if want == "success"}
    assert {"theprotocol_tegSystemTransfer", "theprotocol_getAttestationDetail", "theprotocol_getAttestationBundle",
            "theprotocol_getFederationPeerByID", "theprotocol_deleteVersion",
            "theprotocol_readThread"} <= earned, "the census lost its subject"
    probes = [(t, want, line) for t, want, line in _own_name_writes(C / "mcp_lifecycles.py")
              if want in ("any", "error_4xx", "error") and t in earned]
    assert not probes, ("probed under the own name of a tool another lifecycle earns (make it a refusal row): "
                        f"{probes}")


def test_the_census_sees_a_probe_under_an_earned_name(tmp_path):
    """CONTROL: the shape the gate exists for is found when it is there (a name constant included)."""
    src = ('T = "theprotocol_guildCrossRegistryBid"\n'
           'async def f(rpc, parse, bag, outcomes):\n'
           '    await _exec_step(rpc, parse, "theprotocol_tegSystemTransfer", "2", {}, "", outcomes, '
           'expect_status="any")\n'
           '    await _exec_step(rpc, parse, "theprotocol_getAttestationDetail", "3", {}, "", outcomes, '
           'record_as_separate=False)\n'
           '    await ef.step(rpc, parse, T, "2", {}, "", outcomes)\n')
    p = tmp_path / "control.py"
    p.write_text(src, encoding="utf-8")
    assert _own_name_writes(p) == [("theprotocol_tegSystemTransfer", "any", 3),
                                   ("theprotocol_guildCrossRegistryBid", "success", 5)]


def test_the_census_resolves_a_tool_named_by_a_local(tmp_path):
    """CONTROL: `tool = "theprotocol_..."` then `step(..., tool, ...)` in one function is that tool's write, and a later
    reassignment names the next call's tool."""
    src = ('async def f(rpc, parse, bag, outcomes):\n'
           '    tool = "theprotocol_deleteVersion"\n'
           '    await step(rpc, parse, tool, "3", {}, "", outcomes)\n'
           '    tool = "theprotocol_readThread"\n'
           '    await step(rpc, parse, tool, "3", {}, "", outcomes, expect_status="any")\n')
    p = tmp_path / "control_local.py"
    p.write_text(src, encoding="utf-8")
    assert _own_name_writes(p) == [("theprotocol_deleteVersion", "success", 3), ("theprotocol_readThread", "any", 5)]

# one lifecycle runs its helpers in turn, so a helper's success and the lifecycle's own probe do not race
_ONE_LIFECYCLE = {"theprotocol_castVote": "_member_vote runs inside lifecycle_governance_proposal_vote_tally"}


def _writes_by_function(path: pathlib.Path):
    """{tool: {expected answer: {top-level function}}} for every own-name write, as _own_name_writes reads them."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    spans = sorted((f.lineno, f.end_lineno, f.name) for f in tree.body
                   if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)))
    out: dict = {}
    for tool, want, line in _own_name_writes(path):
        fn = next((name for a, b, name in spans if a <= line <= b), "<module>")
        out.setdefault(tool, {}).setdefault(want, set()).add(fn)
    return out


def test_no_tool_is_a_success_in_one_lifecycle_and_probed_in_another_of_mcp_lifecycles():
    """The same race inside one module (agentvault2-66's census of 2026-10-24 found deleteOrganization there)."""
    races = {}
    for tool, by in _writes_by_function(C / "mcp_lifecycles.py").items():
        probes = set().union(*(by.get(k, set()) for k in ("any", "error_4xx", "error")))
        succ = by.get("success", set())
        if succ and (probes - succ) and tool not in _ONE_LIFECYCLE:
            races[tool] = {"success": sorted(succ), "probe": sorted(probes - succ)}
    assert not races, f"a success row and an own-name probe in two lifecycles (make the probe a refusal row): {races}"


def test_the_module_census_sees_a_cross_lifecycle_probe(tmp_path):
    """CONTROL: a success in one function and an `any` probe of the same tool in another is named."""
    src = ('async def a(rpc, parse, bag, outcomes):\n'
           '    await _exec_step(rpc, parse, "theprotocol_deleteOrganization", "3", {}, "", outcomes)\n'
           'async def b(rpc, parse, bag, outcomes):\n'
           '    await _exec_step(rpc, parse, "theprotocol_deleteOrganization", "3", {}, "", outcomes, '
           'expect_status="any")\n')
    p = tmp_path / "control_module.py"
    p.write_text(src, encoding="utf-8")
    assert _writes_by_function(p) == {"theprotocol_deleteOrganization": {"success": {"a"}, "any": {"b"}}}
