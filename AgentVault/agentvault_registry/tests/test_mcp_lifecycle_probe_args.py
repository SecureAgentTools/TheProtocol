"""§MCPSWEEP 2026-09-27 — every lifecycle probe sends the arguments its tool DECLARES, and every one it requires.

A probe with an undeclared argument (or a required one missing) is refused by the MCP dispatcher with -32602 before the
tool runs, so it measures nothing. Measured on sbx-alpha's audit rows of the 03:00Z nightly: 57 admin-lifecycle probes
were of that kind and all read green. Static, read from source (no import of the app):

  * the ADMIN lifecycle (mcp_admin_lifecycles.py): every probe conforms. Zero exceptions.
  * the PUBLIC lifecycle (mcp_lifecycles.py): the probes of PUBLIC tools that do not conform are a named, SHRINKING
    list (KNOWN_PUBLIC_MISMATCHES): a new one fails this test. And its calls to tools the public bridge does not carry
    (admin tools: the public dispatcher answers -32601, and the public sweep never scores them) may only shrink.
The dispatcher consumes `capability_token` for every tool, but `agent_jwt` ONLY for tier-2 tools (server.py pops it
inside `if tool_name in TIER2_TOOLS`); a tier-3 tool is handed it as an argument and refuses it with -32602. The public
check is tier-aware for that reason (2026-09-27: federationSlashConfirmation's probe carried one and read as conforming).
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
ADMIN_LC = SRC / "api_tests" / "contracts" / "mcp_admin_lifecycles.py"
PUBLIC_LC = SRC / "api_tests" / "contracts" / "mcp_lifecycles.py"
DISPATCHER_KEYS = {"agent_jwt", "capability_token"}

# the public-tool probes that do not conform today (tool names); FIX ONE, REMOVE IT HERE. Never add to this list.
KNOWN_PUBLIC_MISMATCHES: set = set()
# §MCPSWEEP 2026-09-27: 17 corrected, then the last seven (a dispute, a TEG policy, a bridge transfer, a cross-TEG sync,
# a reputation signal, a token transfer, a frame invitation) once each had a measured safe probe: every route read for
# the order of its refusal and its side effects, pinned by tests/test_mcp_lifecycle_refusal_probes.py. Keep it empty.
# calls in the public lifecycle to tools the public bridge does not carry (measured by THIS reader 2026-09-27: 140,
# then 11 after the dead admin lifecycles went: the admin steps of five mixed flows, which go through rpc_admin since
# §MCPTEST30 V0553); may only shrink
PHANTOM_CEILING = 0


def _lit(n):
    return n.value if isinstance(n, ast.Constant) else None


def schemas():
    out = {}
    for f in (SRC / "mcp").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if not isinstance(node, ast.Dict):
                continue
            ks = [_lit(k) for k in node.keys]
            if "name" in ks and "inputSchema" in ks and isinstance(node.values[ks.index("inputSchema")], ast.Dict):
                sch = node.values[ks.index("inputSchema")]
                sk = [_lit(k) for k in sch.keys]
                props = set()
                if "properties" in sk and isinstance(sch.values[sk.index("properties")], ast.Dict):
                    props = {_lit(k) for k in sch.values[sk.index("properties")].keys}
                req = set()
                if "required" in sk and isinstance(sch.values[sk.index("required")], ast.List):
                    req = {_lit(e) for e in sch.values[sk.index("required")].elts}
                out[_lit(node.values[ks.index("name")])] = (props, req)
    return out


def dispatch_keys(filename: str, var: str) -> set:
    """The dispatch table's literal keys: its assignment AND every `VAR.update({...})` (§MEMBERSHIP V0551: the AGORA, guild
    and commons tools join by update; a reader of the assignment alone counted their calls as tools the bridge lacks)."""
    keys = set()
    for node in ast.walk(ast.parse((SRC / "mcp" / filename).read_text())):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(getattr(t, "id", "") == var for t in targets) and isinstance(node.value, ast.Dict):
                keys |= {_lit(k) for k in node.value.keys if isinstance(_lit(k), str)}
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update"
              and getattr(node.func.value, "id", "") == var and node.args and isinstance(node.args[0], ast.Dict)):
            keys |= {_lit(k) for k in node.args[0].keys if isinstance(_lit(k), str)}
    return keys


def bridge_calls(source: str):
    """(line, tool, bridge) for every _exec_step / _expect_refusal / _admin_effect call with a literal tool: "admin" when
    the call goes through `rpc_admin` (a public lifecycle's admin steps: §MEMBERSHIP V0551's commons season, §MCPTEST30
    V0553's admin_effect family), else "public"."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") in ("_exec_step", "_exec_function_safe", "_expect_refusal", "_admin_effect")
                and len(node.args) >= 3 and isinstance(_lit(node.args[2]), str)):
            out.append((node.lineno, _lit(node.args[2]),
                        "admin" if getattr(node.args[0], "id", "") == "rpc_admin" else "public"))
    return out


def probes(source: str):
    """(line, tool, keys or None when a key is not a literal) for every (tool, {args}) tuple, every _exec_step call
    with a literal argument dict, and every name in a `_dash_tools` list (those are called with {})."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Tuple) and len(node.elts) == 2 and isinstance(_lit(node.elts[0]), str) \
                and _lit(node.elts[0]).startswith("theprotocol_") and isinstance(node.elts[1], ast.Dict):
            d = node.elts[1]
            out.append((node.lineno, _lit(node.elts[0]), None if None in d.keys else {_lit(k) for k in d.keys}))
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("_exec_step", "_exec_function_safe") \
                and len(node.args) >= 5 and isinstance(_lit(node.args[2]), str) and isinstance(node.args[4], ast.Dict):
            d = node.args[4]
            out.append((node.lineno, _lit(node.args[2]), None if None in d.keys else {_lit(k) for k in d.keys}))
        # §MCPTEST30: the refusal probes of the self-account lifecycle (`_expect_refusal(rpc, parse, tool, {args}, …)`)
        # are real calls too; a malformed one would be refused by the dispatcher and "pass" as a refusal of the rule.
        # V0553: so are the admin_effect steps (`_admin_effect(rpc_admin, parse, tool, {args}, …)`)
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("_expect_refusal", "_admin_effect") \
                and len(node.args) >= 4 and isinstance(_lit(node.args[2]), str) and isinstance(node.args[3], ast.Dict):
            d = node.args[3]
            out.append((node.lineno, _lit(node.args[2]), None if None in d.keys else {_lit(k) for k in d.keys}))
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_dash_tools" for t in node.targets) \
                and isinstance(node.value, ast.List):
            out += [(e.lineno, _lit(e), set()) for e in node.value.elts if isinstance(_lit(e), str)]
    return out


def tier2_tools() -> set:
    """The public dispatcher's TIER2_TOOLS literal: the tools for which it consumes `agent_jwt` itself."""
    for node in ast.walk(ast.parse((SRC / "mcp" / "server.py").read_text())):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TIER2_TOOLS" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError("TIER2_TOOLS not found in mcp/server.py: the reader is not seeing the dispatcher")


def mismatches(found, schema, tier2=None):
    """`tier2=None` allows `agent_jwt` everywhere (the admin lifecycle's rule, unchanged); a set allows it only there."""
    bad = []
    for line, tool, keys in found:
        if keys is None or tool not in schema:
            continue
        props, req = schema[tool]
        allowed = DISPATCHER_KEYS if tier2 is None or tool in tier2 else DISPATCHER_KEYS - {"agent_jwt"}
        undeclared, missing = (keys - allowed) - props, req - keys
        if undeclared or missing:
            bad.append((line, tool, sorted(undeclared), sorted(missing)))
    return bad


def test_every_admin_lifecycle_probe_sends_what_its_tool_declares():
    schema = schemas()
    found = probes(ADMIN_LC.read_text())
    judged = [p for p in found if p[2] is not None and p[1] in schema]
    assert len(judged) >= 150, f"only {len(judged)} admin probes judged: the reader is not seeing the lifecycle"
    bad = mismatches(found, schema)
    assert not bad, "admin lifecycle probes the dispatcher will refuse before the tool runs:\n" + "\n".join(
        f"  line {ln} {t}: undeclared {u} missing {m}" for ln, t, u, m in bad)


def test_the_public_lifecycle_gains_no_new_malformed_probe():
    schema, public = schemas(), dispatch_keys("server.py", "TOOL_DISPATCH")
    found = [p for p in probes(PUBLIC_LC.read_text()) if p[1] in public]
    assert len(found) >= 200, f"only {len(found)} public-tool probes found: the reader is not seeing the lifecycle"
    bad = {t.replace("theprotocol_", "") for _, t, _, _ in mismatches(found, schema, tier2=tier2_tools())}
    new = sorted(bad - KNOWN_PUBLIC_MISMATCHES)
    assert not new, f"new malformed public probes (fix them, never add them to the known list): {new}"
    fixed = sorted(KNOWN_PUBLIC_MISMATCHES - bad)
    assert not fixed, f"these now conform: remove them from KNOWN_PUBLIC_MISMATCHES so the list keeps shrinking: {fixed}"


def test_the_public_lifecycle_names_no_more_tools_its_bridge_lacks():
    public = dispatch_keys("server.py", "TOOL_DISPATCH")
    admin = dispatch_keys("server_admin.py", "ADMIN_TOOL_DISPATCH")
    source = PUBLIC_LC.read_text()
    via_admin = {(line, tool) for line, tool, bridge in bridge_calls(source) if bridge == "admin"}
    phantom = [p for p in probes(source) if (p[0], p[1]) not in via_admin and p[1] not in public]
    assert len(phantom) <= PHANTOM_CEILING, (
        f"{len(phantom)} calls to tools the public bridge does not carry (ceiling {PHANTOM_CEILING}): an admin tool "
        f"belongs in mcp_admin_lifecycles.py, which runs on the admin bridge, or behind the lifecycle's rpc_admin")
    # a call that goes through rpc_admin must name a tool the ADMIN bridge carries
    assert via_admin and all(tool in admin for _, tool in via_admin), sorted(t for _, t in via_admin if t not in admin)


def test_the_public_lifecycles_admin_steps_send_what_their_tools_declare():
    """§MCPTEST30 (V0553): a public lifecycle's admin steps (rpc_admin: the commons season, the admin_effect family) are
    held to the ADMIN tools' schemas, as the admin lifecycle's probes are. hideBundle's step sent no `reason` until V0553:
    harmless while the public dispatcher refused the call, a -32602 the moment it reached the admin bridge."""
    schema, source = schemas(), PUBLIC_LC.read_text()
    via_admin = {(line, tool) for line, tool, bridge in bridge_calls(source) if bridge == "admin"}
    found = [p for p in probes(source) if (p[0], p[1]) in via_admin]
    assert len(found) >= 15, f"only {len(found)} admin steps read in the public lifecycle: the reader is not seeing them"
    assert "theprotocol_hideBundle" in {t for _, t, _ in found}
    bad = mismatches(found, schema)
    assert not bad, "public-lifecycle admin steps the admin dispatcher will refuse before the tool runs:\n" + "\n".join(
        f"  line {ln} {t}: undeclared {u} missing {m}" for ln, t, u, m in bad)
    # control: an admin_effect step with an undeclared argument and a missing one is caught, through the same readers
    src = ("async def lc(rpc, parse, bag, outcomes):\n"
           "    await _admin_effect(rpc_admin, parse, \"theprotocol_z\", {\"wrong\": 1}, j, outcomes)\n")
    va = {(line, tool) for line, tool, bridge in bridge_calls(src) if bridge == "admin"}
    caught = mismatches([p for p in probes(src) if (p[0], p[1]) in va], {"theprotocol_z": ({"right"}, {"right"})})
    assert [(t, u, m) for _, t, u, m in caught] == [("theprotocol_z", ["wrong"], ["right"])]


def test_the_dispatch_reader_sees_tools_that_join_by_update():
    public = dispatch_keys("server.py", "TOOL_DISPATCH")
    # the guild and the commons join TOOL_DISPATCH by .update({...}); the assignment alone does not carry them
    assert {"theprotocol_guildBid", "theprotocol_castCommonsBallot", "theprotocol_getMembershipStats"} <= public
    assert "theprotocol_adminCommonsPaySeason" in dispatch_keys("server_admin.py", "ADMIN_TOOL_DISPATCH")
    assert "theprotocol_adminCommonsPaySeason" not in public
    # control: a call through any other name than rpc_admin is read as a public call
    src = ("async def lc(rpc, parse, bag, outcomes):\n"
           "    await _exec_step(rpc_admin, parse, \"theprotocol_a\", \"admin\", {}, j, o)\n"
           "    await _exec_step(rpc, parse, \"theprotocol_b\", \"1\", {}, j, o)\n"
           "    await _exec_step(bag.rpc_admin, parse, \"theprotocol_c\", \"admin\", {}, j, o)\n")
    assert [(t, b) for _, t, b in bridge_calls(src)] == [("theprotocol_a", "admin"), ("theprotocol_b", "public"),
                                                         ("theprotocol_c", "public")]


def test_the_checker_can_fail():
    # a control: a synthetic lifecycle with one undeclared and one missing argument must be caught
    source = (
        "async def lc(rpc, parse, bag, outcomes):\n"
        "    for tool, args in [(\"theprotocol_x\", {\"wrong\": 1})]:\n"
        "        pass\n"
        "    await _exec_step(rpc, parse, \"theprotocol_y\", \"admin\", {}, jwt, outcomes)\n"
    )
    schema = {"theprotocol_x": ({"right"}, {"right"}), "theprotocol_y": ({"id"}, {"id"})}
    bad = mismatches(probes(source), schema)
    assert [(t, u, m) for _, t, u, m in bad] == [
        ("theprotocol_x", ["wrong"], ["right"]), ("theprotocol_y", [], ["id"])]


def test_the_checker_refuses_agent_jwt_on_a_tier3_tool():
    # a control for the tier-aware rule: the same probe conforms for a tier-2 tool and is caught for a tier-3 one
    source = ("async def lc(rpc, parse, bag, outcomes):\n"
              "    await _exec_step(rpc, parse, \"theprotocol_t2\", \"2\", {\"agent_jwt\": j, \"id\": 1}, jwt, outcomes)\n"
              "    await _exec_step(rpc, parse, \"theprotocol_t3\", \"3\", {\"agent_jwt\": j, \"id\": 1}, jwt, outcomes)\n")
    schema = {"theprotocol_t2": ({"id"}, {"id"}), "theprotocol_t3": ({"id"}, {"id"})}
    bad = mismatches(probes(source), schema, tier2={"theprotocol_t2"})
    assert [(t, u, m) for _, t, u, m in bad] == [("theprotocol_t3", ["agent_jwt"], [])]
    assert "theprotocol_transferUnits" in tier2_tools() and "theprotocol_createTegPolicy" not in tier2_tools()


E2E_NAME = r"(Test|Tester|Teardown)$"


def _unguarded_e2e(source: str) -> list:
    """Tools named like an end-to-end test that the admin lifecycle calls outside _LIFECYCLE_NEVER_INVOKE."""
    import re
    tree = ast.parse(source)
    never = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_LIFECYCLE_NEVER_INVOKE" for t in node.targets):
            never = {_lit(e) for e in ast.walk(node.value) if isinstance(_lit(e), str)}
    called = {tool for _, tool, _ in probes(source)}
    return sorted(t for t in called if re.search(E2E_NAME, t) and t not in never)


def test_the_sweep_never_starts_an_end_to_end_run():
    # §MCPSWEEP V0464: crossRegTransferTest was called with {} every night; its first stage removes host containers,
    # volumes, stack dirs and SPIRE entries by name prefix, and only its own container-count preflight kept it from
    # provisioning a frame through the Docker socket. Every tool named like an end-to-end run is guarded.
    bad = _unguarded_e2e(ADMIN_LC.read_text())
    assert not bad, f"end-to-end tools the admin lifecycle would run: {bad} (add them to _LIFECYCLE_NEVER_INVOKE)"


def test_control_an_unguarded_e2e_probe_is_caught():
    src = ADMIN_LC.read_text() + '\n\nasync def _x():\n    for tool, args in [("theprotocol_phase6FrameLifecycleTest", {})]:\n        pass\n'
    assert _unguarded_e2e(src) == ["theprotocol_phase6FrameLifecycleTest"]
