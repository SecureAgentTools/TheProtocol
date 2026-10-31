"""§MCPTEST30 (V0637): the cloud-operator sweeps run the earned lifecycles on the operator itself.

Until V0637 the two operator sweeps (flow_mcp_lifecycle_cloudop_sandboxalpha / _sandboxdelta) ran no lifecycle at all: a
tool an earned lifecycle measures on the frame read on an operator only what its contract asks, a refusal on a made-up
id or a named skip (BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, the cloud-operator item). Pinned here:
  - an operator run takes only the lifecycles it can give everything to; one that needs a peer frame is not run, and
    says why (V0638: the operator's own database is asked in its database container, never in-process, where the
    tester's database is the parent frame's);
  - every earned lifecycle that reaches the database or a peer, directly or through a helper, declares it (a gate on
    the declaration, with a control), and the database is reached one way only, mcp_lifecycles._target_db (V0638);
  - psql in the operator's database container: values bound as literals that cannot leave their place, a read's
    type kept, a write's rows counted, a failure said;
  - the throwaway developer registers with an invite code where the target asks for one (the operators do:
    beta_invite_required, measured 2026-10-24), from the operator admin's generateInviteCodes;
  - the sweep wires it: the lifecycles run, a lifecycle row decides a public tool, the earned admin rows join the
    admin rows before the reachability probes, and the rows naming no tool are kept after each sweep.
"""
from __future__ import annotations

import ast
import asyncio
import base64
import inspect
import json
import textwrap

import pytest

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_admin_dev, earned_agent_public


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


# ── which lifecycles an operator takes ──────────────────────────────────────────────────────────────────────────────

def test_an_operator_run_takes_only_what_it_can_give():
    lcs = [{"name": "plain", "runner": None},
           {"name": "reads_db", "runner": None, "needs": ("target_db",)},
           {"name": "needs_both", "runner": None, "needs": ("target_db", "peer")}]
    # V0638: an operator run gives its own database (psql in its database container), never a peer frame
    run, not_run = F.operator_lifecycles(lcs)
    assert [lc["name"] for lc in run] == ["plain", "reads_db"]
    assert set(not_run) == {"needs_both"} and "peer frame" in not_run["needs_both"]
    # a run with no way to the database takes the plain one only, and says why
    run, not_run = F.operator_lifecycles(lcs, offers=())
    assert [lc["name"] for lc in run] == ["plain"]
    assert "database" in not_run["reads_db"] and "database" in not_run["needs_both"]
    # a run that can give both takes all three
    run_all, none = F.operator_lifecycles(lcs, offers={"target_db", "peer"})
    assert len(run_all) == 3 and none == {}


def test_the_lists_an_operator_takes_today():
    # V0638: mcp_lifecycles' LIFECYCLES (its own and the earned lists it ends with) but the two that probe a tool
    # acting on the operator itself; not run: the one that needs a peer frame and the one that needs a frame (V0641:
    # the canary recipient runs on an operator too, its dust to the parent frame's canary receiver, d6's word)
    from agentvault_registry.api_tests.contracts import mcp_lifecycles
    lcs = F.cloudop_lifecycle_list()
    assert {lc["name"] for lc in mcp_lifecycles.LIFECYCLES} - {lc["name"] for lc in lcs} == {
        "misc_safe", "self_revocation_safe"}
    run, not_run = F.operator_lifecycles(lcs)
    assert set(not_run) == {"earned_guild_cross_registry", "reputation_eigentrust_setup"}
    names = {lc["name"] for lc in run}
    assert {"earned_contracts", "earned_system_transfer", "earned_by_design", "earned_public_reads",
            "earned_auth_chain", "trust_score_newest_epoch", "webhook_full_crud", "organization_full_crud",
            "bundle_full_crud", "pipeline_full_crud", "cross_registry_canary_recipient"} <= names
    assert not names & set(not_run)
    assert len(run) + len(not_run) == len(lcs)


def test_the_newest_epochs_trust_score_is_read_by_its_own_lifecycle_alone():
    # V0638: getTrustScore's earned read left the EigenTrust seed lifecycle, so an operator run reads it without the seed
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as M
    src = inspect.getsource(M)
    tree = ast.parse(src)
    callers = sorted(fn.name for fn in tree.body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and _calls(fn, "_trust_score_of_the_newest_epoch"))
    assert callers == ["lifecycle_trust_score_newest_epoch"]


# ── V0638: no lifecycle an operator run takes names a tool that acts on the operator itself ─────────────────────

_CONTRACTS_PKG = "agentvault_registry.api_tests.contracts"


def _module_tables(tree: ast.Module) -> dict:
    """{name: value} of a module's top-level assignments: the tables a function may read by name."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            out.update({t.id: n.value for t in n.targets if isinstance(t, ast.Name)})
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            out[n.target.id] = n.value
    return out


def _table_names(tables: dict, name: str, tools, seen=()) -> set:
    """The `tools` a module-level table names, with those of the tables it is built from (`A = B + (...)`)."""
    if name in seen or name not in tables:
        return set()
    got = set()
    for n in ast.walk(tables[name]):
        if isinstance(n, ast.Constant) and n.value in tools:
            got.add(n.value)
        elif isinstance(n, ast.Name) and n.id in tables:
            got |= _table_names(tables, n.id, tools, seen + (name,))
    return got


def _names_an_operator_self_tool(src: str, roots, tools, tables_of=None) -> dict:
    """{function: [tools]} over the functions reachable (same-module calls) from `roots` in `src` that name one of
    `tools`: as a string literal, or (V0643) through a module-level table the function reads, this module's by its
    name or another contracts module's through the alias it is imported under (`tables_of(module)`: its tables)."""
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    tables = _module_tables(tree)
    aliases = {a.asname or a.name: a.name for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) and n.module == _CONTRACTS_PKG for a in n.names}
    seen, todo, out = set(), [r for r in roots if r in funcs], {}
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        hit = set()
        for n in ast.walk(funcs[name]):
            if isinstance(n, ast.Constant) and n.value in tools:
                hit.add(n.value)
            elif isinstance(n, ast.Name) and n.id in tables:
                hit |= _table_names(tables, n.id, tools)
            elif (tables_of is not None and isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                  and n.value.id in aliases):
                hit |= _table_names(tables_of(aliases[n.value.id]), n.attr, tools)
            if isinstance(n, ast.Call):
                callee = n.func.id if isinstance(n.func, ast.Name) else (
                    n.func.attr if isinstance(n.func, ast.Attribute) else None)
                if callee in funcs:
                    todo.append(callee)
        if hit:
            out[name] = sorted(hit)
    return out


def test_no_lifecycle_an_operator_takes_names_an_operator_self_tool():
    # 2026-10-24: lifecycle_misc_safe's operatorPortalSelfRestart (a refusal on a frame) restarted both sandbox operators
    import pathlib
    from agentvault_registry.api_tests import contracts
    from agentvault_registry.api_tests.contracts import mcp_lifecycles
    assert "theprotocol_operatorPortalSelfRestart" in F.OPERATOR_SELF_TOOLS
    lcs = F.operator_lifecycles(F.cloudop_lifecycle_list())[0]
    runners = {lc["runner"] for lc in lcs}
    by_module = {}
    for r in runners:
        by_module.setdefault(r.__module__, set()).add(r.__name__)
    # the mcp_lifecycles helpers the earned modules borrow (ef.lc().<helper>, m.<helper>) run on the operator too
    lc_funcs = {n.name for n in ast.parse(inspect.getsource(mcp_lifecycles)).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    here = pathlib.Path(contracts.__file__).parent
    for f in here.glob("earned_*.py"):
        borrowed = {n.attr for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.Attribute)
                    and n.attr in lc_funcs}
        by_module.setdefault(mcp_lifecycles.__name__, set()).update(borrowed)
    cache = {}

    def tables_of(module):
        if module not in cache:
            f = here / f"{module}.py"
            cache[module] = _module_tables(ast.parse(f.read_text())) if f.exists() else {}
        return cache[module]

    found = {}
    for mod, roots in by_module.items():
        src = (here / (mod.rsplit(".", 1)[-1] + ".py")).read_text()
        hit = _names_an_operator_self_tool(src, roots, F.OPERATOR_SELF_TOOLS, tables_of=tables_of)
        if hit:
            found[mod] = hit
    assert found == {}


def test_the_operator_self_tool_check_sees_the_restart_probe():
    # control: mcp_lifecycles' lifecycle_misc_safe is a frame lifecycle that probes operatorPortalSelfRestart
    from agentvault_registry.api_tests.contracts import mcp_lifecycles
    hit = _names_an_operator_self_tool(inspect.getsource(mcp_lifecycles), ["lifecycle_misc_safe"],
                                       F.OPERATOR_SELF_TOOLS)
    assert "theprotocol_operatorPortalSelfRestart" in hit.get("lifecycle_misc_safe", [])


# §MCPTEST30 (V0643): the gate read string literals inside the functions alone, so a tool named in a module-level table
# that a lifecycle iterates (NOT_DRIVEN's shape) passed it unseen; it reads those tables too, its own module's and another
# contracts module's (agentvault2-aa's frame-only rows of V0643 were the occasion)
_TABLE_SRC = textwrap.dedent('''
    SELF = ("theprotocol_requestFrame",)
    BOTH = SELF + ("theprotocol_getMyBalance",)
    async def lifecycle_reads_a_table(rpc):
        for tool in BOTH:
            await rpc(tool)
    async def lifecycle_plain(rpc):
        await rpc("theprotocol_getMyBalance")
''')


def test_the_operator_self_tool_check_reads_the_tables_a_lifecycle_reads():
    hit = _names_an_operator_self_tool(_TABLE_SRC, ["lifecycle_reads_a_table", "lifecycle_plain"],
                                       F.OPERATOR_SELF_TOOLS)
    assert hit == {"lifecycle_reads_a_table": ["theprotocol_requestFrame"]}
    # the literal sits in a table two names away, never in the function: only the table read finds it
    fn = next(n for n in ast.parse(_TABLE_SRC).body if getattr(n, "name", "") == "lifecycle_reads_a_table")
    assert "theprotocol_requestFrame" not in ast.unparse(fn)


def test_the_operator_self_tool_check_reads_another_modules_table_through_its_alias():
    tables = {"earned_fixtures": _module_tables(ast.parse(
        'LABELS = {"theprotocol_operatorPortalSelfRestart": "a reason"}\nDUST = "0.01"\n'))}
    src = textwrap.dedent('''
        from agentvault_registry.api_tests.contracts import earned_fixtures as ef
        async def lifecycle_reads_ef(rpc):
            for tool in ef.LABELS:
                await rpc(tool)
        async def lifecycle_reads_ef_constant(rpc):
            await rpc("theprotocol_getMyBalance", ef.DUST)
    ''')
    hit = _names_an_operator_self_tool(src, ["lifecycle_reads_ef", "lifecycle_reads_ef_constant"],
                                       F.OPERATOR_SELF_TOOLS, tables_of=lambda m: tables.get(m, {}))
    assert hit == {"lifecycle_reads_ef": ["theprotocol_operatorPortalSelfRestart"]}


def test_the_label_table_names_an_operator_self_tool_and_no_lifecycle_module_reads_it():
    # refusal_reasons.BY_DESIGN_REFUSAL labels the rows the flow hands the router, requestFrame's among them; a lifecycle
    # module that read it would be refused by the gate above, which cannot tell a label from a call
    import pathlib
    from agentvault_registry.api_tests import contracts
    from agentvault_registry.api_tests.contracts import refusal_reasons
    assert set(refusal_reasons.BY_DESIGN_REFUSAL) & F.OPERATOR_SELF_TOOLS, "the label table names one (precondition)"
    here = pathlib.Path(contracts.__file__).parent
    readers = sorted(f.name for f in [here / "mcp_lifecycles.py", *here.glob("earned_*.py")]
                     if "refusal_reasons" in f.read_text())
    assert readers == []


# ── the declaration gate: a lifecycle that reaches the database or a peer says so ──────────────────────────────────

# the target's database is reached through agentvault_registry.database's session factory, so the gate reads the
# import, not a helper's name (agentvault2-aa's note: mcp_lifecycles' _trust_score_of_the_newest_epoch used it
# directly until V0638); since V0638 the one way to it is mcp_lifecycles._target_db (earned_agent_public._db_one
# imports it inside the function), which the gate counts as reaching it too; a peer frame is reached through _Peer
_DB_MODULE, _DB_FACTORY = "agentvault_registry.database", "AsyncSessionLocal"
_REACHES = {"_Peer": "peer", "_target_db": "target_db"}


def _undeclared(module_src: str, lifecycles):
    """{lifecycle name: needs it reaches (through any module-level helper) and does not declare}."""
    tree = ast.parse(module_src)
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # a module-level import of the session factory: any function naming it (or its alias) reaches the database
    factory = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == _DB_MODULE
               for a in n.names if a.name == _DB_FACTORY}
    if any(isinstance(n, ast.Import) and any(a.name == _DB_MODULE for a in n.names) for n in tree.body):
        factory.add(_DB_FACTORY)   # `import agentvault_registry.database` then `...database.AsyncSessionLocal`

    def direct(fn):
        out, calls = set(), set()
        for n in ast.walk(fn):
            if isinstance(n, ast.ImportFrom) and n.module == _DB_MODULE and any(a.name == _DB_FACTORY for a in n.names):
                out.add("target_db")
            if isinstance(n, ast.Name) and n.id in factory:
                out.add("target_db")
            if isinstance(n, ast.Attribute) and n.attr == _DB_FACTORY:
                out.add("target_db")
            if isinstance(n, ast.Name) and n.id in _REACHES:
                out.add(_REACHES[n.id])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs:
                calls.add(n.func.id)
        return out, calls

    memo = {}

    def reach(name, seen=()):
        if name in memo:
            return memo[name]
        if name in seen:
            return set()
        got, calls = direct(funcs[name])
        for c in calls:
            got |= reach(c, seen + (name,))
        memo[name] = got
        return got

    out = {}
    for lc in lifecycles:
        runner = lc["runner"] if isinstance(lc["runner"], str) else lc["runner"].__name__
        if runner not in funcs:
            continue
        missing = reach(runner) - set(lc.get("needs") or ())
        if missing:
            out[lc["name"]] = sorted(missing)
    return out


def test_every_earned_lifecycle_that_reaches_the_database_or_a_peer_declares_it():
    from agentvault_registry.api_tests.contracts import (earned_ad_agents, earned_ad_chat_approvals,
                                                         earned_ad_developers, earned_ad_devtools, earned_ad_ephemeral,
                                                         earned_ad_federation, earned_ad_platform)
    mods = (earned_agent_public, earned_ad_agents, earned_ad_developers, earned_ad_devtools, earned_ad_federation,
            earned_ad_platform, earned_ad_ephemeral, earned_ad_chat_approvals)
    # every lifecycle an operator run may take lives in one of these modules
    assert sum(len(m.LIFECYCLES) for m in mods) == len(earned_agent_public.LIFECYCLES) + len(earned_admin_dev.LIFECYCLES)
    for m in mods:
        assert _undeclared(inspect.getsource(m), m.LIFECYCLES) == {}, m.__name__
    # V0638: mcp_lifecycles' own runners too (its LIFECYCLES also lists the earned ones, whose runners live elsewhere)
    from agentvault_registry.api_tests.contracts import mcp_lifecycles
    assert _undeclared(inspect.getsource(mcp_lifecycles), mcp_lifecycles.LIFECYCLES) == {}


def test_the_declaration_gate_sees_a_helper_one_call_away():
    # control: the gate must refuse a lifecycle that reaches the session factory through two helpers and declares nothing
    src = textwrap.dedent('''
        async def _db_one(sql, params):
            from agentvault_registry.database import AsyncSessionLocal as _S
            async with _S() as db:
                return None, None
        async def _helper():
            return await _db_one("SELECT 1", {})
        async def lifecycle_quiet(rpc, parse, bag, outcomes):
            await _helper()
        async def lifecycle_honest(rpc, parse, bag, outcomes):
            await _helper()
    ''')
    lcs = [{"name": "quiet", "runner": "lifecycle_quiet"},
           {"name": "honest", "runner": "lifecycle_honest", "needs": ("target_db",)}]
    assert _undeclared(src, lcs) == {"quiet": ["target_db"]}


def test_the_declaration_gate_sees_the_session_factory_used_directly():
    # agentvault2-aa's case: a module-level import, used straight from a lifecycle's helper
    src = textwrap.dedent('''
        from agentvault_registry.database import AsyncSessionLocal
        async def _newest_epoch():
            async with AsyncSessionLocal() as db:
                return None
        async def lifecycle_reads_epoch(rpc, parse, bag, outcomes):
            await _newest_epoch()
    ''')
    assert _undeclared(src, [{"name": "epoch", "runner": "lifecycle_reads_epoch"}]) == {"epoch": ["target_db"]}


# ── the throwaway developer and the invite ──────────────────────────────────────────────────────────────────────────

def _mint(monkeypatch, invite):
    sent = []

    async def fake_http(container, method, path, body=None, **kw):
        sent.append((path, json.loads(body.decode()) if body else None))
        return "200", "{}"

    async def fake_login(container, email, password):
        return "200", {"access_token": "h.eyJzdWIiOiI0MiJ9.s", "refresh_token": "r"}

    monkeypatch.setattr(F, "_http_in_target", fake_http)
    monkeypatch.setattr(F, "_dev_login", fake_login)
    return asyncio.run(F._mint_throwaway_developer("cloud-op-x-registry", "earned", invite=invite)), sent


def test_the_mint_carries_the_invite_where_the_target_asks_for_one(monkeypatch):
    async def invite():
        return "INV-ONE-RUN", ""
    got, sent = _mint(monkeypatch, invite)
    assert got.get("access_token") and got.get("developer_id") == "42"
    assert sent[0][0] == "/api/v1/auth/register" and sent[0][1]["invite_code"] == "INV-ONE-RUN"


def test_without_an_invite_source_the_registration_is_as_before(monkeypatch):
    got, sent = _mint(monkeypatch, None)
    assert got.get("access_token") and "invite_code" not in sent[0][1]


def test_no_invite_no_registration_and_the_reason(monkeypatch):
    async def invite():
        return None, "generateInviteCodes answered HTTP 403"
    got, sent = _mint(monkeypatch, invite)
    assert sent == [] and "invite" in got["why"] and "HTTP 403" in got["why"]


def test_the_invite_is_the_first_code_the_operator_admin_generates():
    asked = []

    async def rpc_admin(tool, args, jwt="", timeout=20):
        asked.append((tool, args))
        return True, _answer({"codes": [{"code": "ABC123", "max_uses": 1}], "count": 1}), "200"

    assert asyncio.run(F.cloudop_invite(rpc_admin, "jwt")) == ("ABC123", "")
    assert asked[0][0] == "theprotocol_generateInviteCodes" and asked[0][1]["count"] == 1

    async def refused(tool, args, jwt="", timeout=20):
        return False, _answer({"detail": "admin_support required"}), "403"

    code, why = asyncio.run(F.cloudop_invite(refused, "jwt"))
    assert code is None and "403" in why


def test_the_operator_is_named_by_its_own_container():
    assert F.operator_slug("cloud-op-sbxalphaop-registry") == "sbxalphaop"
    assert F.operator_slug("sbx-alpha-registry") == "sbx-alpha-registry"


# ── the sweep wires it ──────────────────────────────────────────────────────────────────────────────────────────────

def _sweep():
    return ast.parse(textwrap.dedent(inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)))


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def test_the_sweep_runs_the_earned_lifecycles_and_keeps_their_rows():
    fn = _sweep()
    assert _calls(fn, "operator_lifecycles"), "the operator sweep never asks which earned lifecycles it can run"
    # V0638: from cloudop_lifecycle_list (LIFECYCLES but the lifecycles that probe an operator-self tool), never LIFECYCLES
    assert _calls(fn, "cloudop_lifecycle_list")
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "LIFECYCLES"]
    # one kept_lifecycle_rows after the public sweep, one after the admin sweep
    assert len(_calls(fn, "kept_lifecycle_rows")) == 2


def test_a_lifecycle_row_decides_a_public_tool_before_its_contract():
    fn = _sweep()
    pub = next(n for n in ast.walk(fn) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_cloudop_one_public")
    first_contract = min(c.lineno for c in _calls(pub, "get_contract"))
    reads = [n.lineno for n in ast.walk(pub) if isinstance(n, ast.Compare) and any(
        isinstance(c, ast.Name) and c.id == "lifecycle_outcomes" for c in n.comparators)]
    assert reads and min(reads) <= first_contract


def test_the_earned_admin_rows_join_before_the_reachability_probes():
    fn = _sweep()
    joins = [c.lineno for c in _calls(fn, "update") if isinstance(c.func, ast.Attribute)
             and isinstance(c.func.value, ast.Name) and c.func.value.id == "admin_lifecycle_outcomes"]
    probes = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.For) and isinstance(n.iter, ast.Name)
              and n.iter.id == "_CLOUDOP_ADMIN_LIFECYCLES"]
    assert joins and probes and min(joins) < min(probes)


# ── the operator's posture reaches the lifecycles (the live check of 2026-10-24) ───────────────────────────────────

def _attest(monkeypatch, posture):
    from types import SimpleNamespace
    from agentvault_registry.api_tests.contracts import earned_fixtures as ef
    asked = []

    async def fake_refusal_step(*a, **k):
        asked.append(a[2])
        return True

    async def rpc(tool, args, jwt="", timeout=20):
        return False, {}, "500"     # no attesting agent can be made: the lifecycle stops after the refusal

    monkeypatch.setattr(ef, "refusal_step", fake_refusal_step)
    bag = SimpleNamespace(sentinel_jwt="s", sentinel_did="did:theprotocol:x", developer_jwt="d", developer_id="1",
                          rpc_admin=None, flow_values={})
    if posture is not None:
        bag.target_posture = posture
    outcomes = {}
    asyncio.run(earned_agent_public.lifecycle_earned_teg_attestation(rpc, F._parse_rpc_result, bag, outcomes))
    return asked, outcomes


def test_where_agent_permissions_are_not_enforced_the_refusal_is_not_measured(monkeypatch):
    # measured live on both sandbox operators: no AGENT_RBAC_MODE, so the sentinel's attestation answered 200
    asked, outcomes = _attest(monkeypatch, {"AGENT_RBAC_MODE": "", "AGENT_DELEGATION_MODE": ""})
    assert asked == []
    row = outcomes["refusal: submitTegAttestation an agent without reputation.signal"]
    assert not row.get("healthy") and "AGENT_RBAC_MODE unset" in str(row.get("skip_reason"))


def test_a_run_that_does_not_say_its_posture_asks_as_before(monkeypatch):
    asked, _ = _attest(monkeypatch, None)
    assert asked == ["theprotocol_submitTegAttestation"]
    asked, _ = _attest(monkeypatch, {"AGENT_RBAC_MODE": "enforce"})
    assert asked == ["theprotocol_submitTegAttestation"]


def test_the_sweep_hands_its_posture_to_the_lifecycles_before_they_run():
    fn = _sweep()
    sets = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Attribute) and t.attr == "target_posture" for t in n.targets)]
    runs = [c.lineno for c in _calls(fn, "_bounded_sweep") if c.args and isinstance(c.args[0], ast.Name)
            and c.args[0].id == "_cop_lcs"]
    assert sets and runs and min(sets) < min(runs)


# ── V0638: the one way to the target's database, and an operator's own through psql in its database container ──────

def _naming_the_factory(module_src):
    """The module-level functions naming the session factory (an import of it, its name or an attribute); a
    module-level import of it is '<module>'."""
    tree = ast.parse(module_src)

    def names_it(node):
        return any((isinstance(n, ast.ImportFrom) and n.module == _DB_MODULE
                    and any(a.name == _DB_FACTORY for a in n.names))
                   or (isinstance(n, ast.Name) and n.id == _DB_FACTORY)
                   or (isinstance(n, ast.Attribute) and n.attr == _DB_FACTORY) for n in ast.walk(node))

    out = ["<module>"] if any(names_it(n) for n in tree.body
                              if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))) else []
    return out + [fn.name for fn in tree.body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and names_it(fn)]


def test_a_lifecycle_reaches_the_target_database_one_way_only():
    # an operator run gives bag.target_db; a lifecycle that opened the session factory itself would read the parent
    # frame's database (the runner's process) as if it were the operator's. Every module of the contracts package is
    # read (the lifecycles call helpers in a dozen of them), from its source: nothing is imported
    import pathlib
    from agentvault_registry.api_tests import contracts
    files = sorted(pathlib.Path(contracts.__file__).parent.glob("*.py"))
    assert len(files) > 20
    seen = {}
    for f in files:
        got = _naming_the_factory(f.read_text())
        if got:
            seen[f.stem] = got
    assert seen == {"mcp_lifecycles": ["_target_db"]}


def test_the_one_way_check_refuses_a_direct_read():
    # control: V0637's _trust_score_of_the_newest_epoch opened the session factory itself
    src = textwrap.dedent('''
        async def _target_db(bag, sql, params, *, write=False):
            from agentvault_registry.database import AsyncSessionLocal as _S
        async def _trust_score_of_the_newest_epoch(rpc, parse, dev_jwt, outcomes):
            from agentvault_registry.database import AsyncSessionLocal as _S
    ''')
    assert _naming_the_factory(src) == ["_target_db", "_trust_score_of_the_newest_epoch"]


def test_the_declaration_gate_counts_the_one_way_as_reaching_the_database():
    # control for _REACHES["_target_db"]: earned_agent_public's helpers import it from mcp_lifecycles inside the
    # function, so without the entry the gate would see no database reach in that module at all
    src = textwrap.dedent('''
        async def _db_one(bag, sql, params):
            from agentvault_registry.api_tests.contracts.mcp_lifecycles import _target_db
            return await _target_db(bag, sql, params)
        async def lifecycle_quiet(rpc, parse, bag, outcomes):
            await _db_one(bag, "SELECT 1", {})
        async def lifecycle_honest(rpc, parse, bag, outcomes):
            await _db_one(bag, "SELECT 1", {})
    ''')
    lcs = [{"name": "quiet", "runner": "lifecycle_quiet"},
           {"name": "honest", "runner": "lifecycle_honest", "needs": ("target_db",)}]
    assert _undeclared(src, lcs) == {"quiet": ["target_db"]}


def test_the_runs_way_to_the_database_wins_and_the_process_own_is_not_touched(monkeypatch):
    from types import SimpleNamespace
    from agentvault_registry import database as D
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as M
    asked = []

    async def via(sql, params, *, write=False):
        asked.append(write)
        return (1, None) if write else ("did:theprotocol:op-epoch", None)

    def _never(*a, **k):
        raise AssertionError("the in-process session factory was opened")

    monkeypatch.setattr(D, "AsyncSessionLocal", _never)
    bag = SimpleNamespace(target_db=via)
    assert asyncio.run(M._target_db(bag, "SELECT agent_did FROM global_trust_vectors", {})) == (
        "did:theprotocol:op-epoch", None)
    assert asyncio.run(M._target_db(bag, "UPDATE t SET a = 1", {}, write=True)) == (1, None)
    # earned_agent_public's two helpers go the same way
    assert asyncio.run(earned_agent_public._db_one(bag, "SELECT 2", {})) == ("did:theprotocol:op-epoch", None)
    assert asyncio.run(earned_agent_public._db_write(bag, "UPDATE t SET a = 2", {})) == (1, None)
    assert asked == [False, True, False, True]


def test_without_one_the_lifecycle_reads_in_its_own_process(monkeypatch):
    from agentvault_registry import database as D
    from agentvault_registry.api_tests.contracts import mcp_lifecycles as M

    class _Res:
        rowcount = 3

        def scalar(self):
            return "in-process"

    class _Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt, params):
            return _Res()

        async def commit(self):
            return None

    monkeypatch.setattr(D, "AsyncSessionLocal", lambda: _Db())
    assert asyncio.run(M._target_db(None, "SELECT 1", {})) == ("in-process", None)
    assert asyncio.run(M._target_db(None, "UPDATE t SET a = 1", {}, write=True)) == (3, None)


def test_a_bound_value_cannot_leave_its_literal():
    nasty = "x'); DROP TABLE developers; -- \\ :e"
    sql = F._bind_sql("SELECT id FROM developers WHERE email = :e AND id = :i AND ok = :b AND gone IS :n",
                      {"e": nasty, "i": 7, "b": True, "n": None})
    assert nasty not in sql and "DROP" not in sql
    assert f"email = convert_from(decode('{base64.b64encode(nasty.encode()).decode()}', 'base64'), 'UTF8')" in sql
    assert "id = (7) AND ok = TRUE AND gone IS NULL" in sql
    # a negative int after a minus cannot open a comment
    assert F._bind_sql("UPDATE t SET a = a -:i WHERE id = :j", {"i": -5, "j": 2}) == (
        "UPDATE t SET a = a -(-5) WHERE id = (2)")
    # quoted literals and casts that are no placeholder are left as they are (text()'s rule: a colon after a word
    # character binds nothing)
    assert F._bind_sql("SELECT x::text, 'at 12:30', now() + interval '1 hour' WHERE id = :i", {"i": 1}) == (
        "SELECT x::text, 'at 12:30', now() + interval '1 hour' WHERE id = (1)")
    # forms the in-process text() would read differently are refused, never sent
    for bad in ("SELECT :a::text", "SELECT 'it''s :a'", "SELECT a FROM t WHERE b = \\:x"):
        with pytest.raises(ValueError):
            F._bind_sql(bad, {"a": 1, "x": 1})
    with pytest.raises(KeyError):
        F._bind_sql("SELECT :missing", {})
    with pytest.raises(TypeError):
        F._sql_literal(1.5)


def _psql(monkeypatch, rc, out):
    sent = []

    def fake(container, sql, db_name=None):
        sent.append((container, sql))
        return rc, out

    monkeypatch.setattr(F, "run_psql_in_db_container", fake)
    return sent


def test_a_read_in_the_operator_database_keeps_its_type(monkeypatch):
    for out, want in (("[42]\n", 42), ("[true]\n", True), ('["tok-abc"]\n', "tok-abc"), ("[null]\n", None)):
        sent = _psql(monkeypatch, 0, out)
        got = asyncio.run(F._db_in_target("cloud-op-x-db", "SELECT id FROM developers WHERE email = :e",
                                          {"e": "a@b.example"}))
        assert got == (want, None), out
    container, sql = sent[0]
    assert container == "cloud-op-x-db"
    assert sql.startswith("SELECT json_build_array((SELECT to_json(q.v) FROM (SELECT id FROM developers WHERE email = "
                          "convert_from(decode(")
    assert sql.endswith(") AS q(v) LIMIT 1));")


def test_a_read_whose_answer_was_lost_is_never_no_row(monkeypatch):
    # a docker exec now and then returns rc 0 with its output cut: [null] is the one "no row" answer
    for out in ("", "\n", "42\n", "[1, 2]\n"):
        _psql(monkeypatch, 0, out)
        v, why = asyncio.run(F._db_in_target("cloud-op-x-db", "SELECT id FROM developers", {}))
        assert v is None and why, out
    _psql(monkeypatch, 0, "")
    assert "lost in transit" in asyncio.run(F._db_in_target("cloud-op-x-db", "SELECT 1", {}))[1]


def test_a_write_in_the_operator_database_counts_its_rows_and_a_failure_is_said(monkeypatch):
    sent = _psql(monkeypatch, 0, "UPDATE 1\n")
    assert asyncio.run(F._db_in_target("cloud-op-x-db", "UPDATE developers SET is_verified = false WHERE id = :i",
                                       {"i": 9}, write=True)) == (1, None)
    assert sent == [("cloud-op-x-db", "UPDATE developers SET is_verified = false WHERE id = (9);")]
    _psql(monkeypatch, 0, "garbage\n")
    n, why = asyncio.run(F._db_in_target("cloud-op-x-db", "UPDATE t SET a = 1", {}, write=True))
    assert n is None and "no rows" in why
    _psql(monkeypatch, 3, "ERROR:  relation \"t\" does not exist\n")
    v, why = asyncio.run(F._db_in_target("cloud-op-x-db", "SELECT a FROM t", {}))
    assert v is None and "psql exited 3" in why
    # an unbound placeholder is never sent
    sent = _psql(monkeypatch, 0, "1\n")
    v, why = asyncio.run(F._db_in_target("cloud-op-x-db", "SELECT :nope", {}))
    assert v is None and "could not be bound" in why and sent == []


def test_the_sweep_gives_the_operators_own_database_and_its_invite_to_the_lifecycles():
    fn = _sweep()

    def assigned(attr):
        return [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == attr for t in n.targets)]

    db, inv = assigned("target_db"), assigned("registration_invite")
    runs = [c.lineno for c in _calls(fn, "_bounded_sweep") if c.args and isinstance(c.args[0], ast.Name)
            and c.args[0].id == "_cop_lcs"]
    assert db and inv and runs and max(db + inv) < min(runs)
    assert "functools.partial(_db_in_target, op.db_container)" in ast.unparse(fn)
    # the lifecycles are chosen by what this run can give
    assert any(k.arg == "offers" for c in _calls(fn, "operator_lifecycles") for k in c.keywords)


def _auth_chain(invite):
    from types import SimpleNamespace
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        return False, _answer({"detail": "registration refused"}), "400"

    bag = SimpleNamespace(developer_jwt="d", flow_values={})
    if invite is not None:
        bag.registration_invite = invite
    outcomes = {}
    asyncio.run(earned_agent_public.lifecycle_earned_auth_chain(rpc, F._parse_rpc_result, bag, outcomes))
    return calls, outcomes


def test_the_auth_chain_registers_with_the_operators_invite():
    async def invite():
        return "INV-AUTH", ""

    calls, _ = _auth_chain(invite)
    assert calls[0][0] == "theprotocol_authRegister" and calls[0][1]["invite_code"] == "INV-AUTH"
    calls, _ = _auth_chain(None)   # a frame: no invite asked for
    assert calls[0][0] == "theprotocol_authRegister" and "invite_code" not in calls[0][1]


def test_no_invite_no_auth_chain_and_the_reason():
    async def invite():
        return None, "generateInviteCodes answered HTTP 403"

    calls, outcomes = _auth_chain(invite)
    assert calls == []
    for tool, _tier in earned_agent_public.AUTH_TOOLS:
        row = json.dumps(outcomes[tool], default=str)
        assert "invite" in row and "HTTP 403" in row and not outcomes[tool].get("healthy")


def test_a_failed_read_back_leaves_the_verify_row_not_measured_never_a_bug_find():
    # the reviewers' case: the verification read through psql comes back lost; that says nothing about the product
    from types import SimpleNamespace

    async def rpc(tool, args, jwt="", timeout=20):
        if tool == "theprotocol_authRegister":
            return True, _answer({"message": "registered", "recovery_keys": ["k1", "k2"]}), "200"
        if tool == "theprotocol_authVerifyEmail":
            return True, _answer({"message": "Email verified"}), "200"
        return False, _answer({"detail": "not in this test"}), "400"

    async def target_db(sql, params, *, write=False):
        if write:
            return 1, None
        if sql.startswith("SELECT id FROM developers"):
            return 77, None
        if "is_verified" in sql:
            return None, "psql's answer was lost in transit (exit 0, nothing printed)"
        return None, None

    bag = SimpleNamespace(developer_jwt="d", flow_values={}, target_db=target_db)
    outcomes = {}
    asyncio.run(earned_agent_public.lifecycle_earned_auth_chain(rpc, F._parse_rpc_result, bag, outcomes))
    row = outcomes["theprotocol_authVerifyEmail"]
    assert not row.get("healthy") and "could not be read back" in str(row.get("skip_reason"))
    assert "BUG-FIND" not in str(row.get("fail_reason") or "")


def test_a_signal_lifecycle_that_cannot_measure_never_replaces_a_measured_row(monkeypatch):
    # applyReputationSignal has two writers (the EigenTrust seed's success leg and earned_reputation_signals); a skip
    # of the second must leave the first's measured row in place
    from types import SimpleNamespace
    from agentvault_registry.api_tests.contracts import earned_fixtures as ef

    class _Throwaways:
        def __init__(self, *a, **k):
            pass

        async def agent(self, *a, **k):
            return {"did": "did:theprotocol:receiver"}

        async def close(self):
            return None

    async def rpc(tool, args, jwt="", timeout=20):
        return False, _answer({"detail": "insufficient balance"}), "402"   # every dust transfer fails

    monkeypatch.setattr(ef, "Throwaways", _Throwaways)
    bag = SimpleNamespace(sentinel_jwt="s", sentinel_did="did:theprotocol:sentinel", developer_jwt="d",
                          developer_id="1", rpc_admin=None, flow_values={})
    measured = {"tool_name": "theprotocol_applyReputationSignal", "healthy": True, "status_code": 200}
    outcomes = {"theprotocol_applyReputationSignal": dict(measured)}
    asyncio.run(earned_agent_public.lifecycle_earned_reputation_signals(rpc, F._parse_rpc_result, bag, outcomes))
    assert outcomes["theprotocol_applyReputationSignal"] == measured
    other = outcomes["theprotocol_tegReputationSignal"]
    assert not other.get("healthy") and "did not complete" in str(other.get("skip_reason"))


# ── §MCPTEST30 (V0644): a run with no phase 4 files its own TEG dispute ─────────────────────────────────────────────

_TEG_LOG = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
_PHASE4_LOG = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"


def _disputes_run(monkeypatch, flow_values, agents=None):
    """lifecycle_earned_disputes against a fake run: (the calls it made, the rows it wrote)."""
    from types import SimpleNamespace
    from agentvault_registry.api_tests.contracts import earned_fixtures as ef
    agents = agents or {"complainant": {"did": "did:theprotocol:a", "agent_jwt": "jwt-a"},
                        "defendant": {"did": "did:theprotocol:b", "agent_jwt": "jwt-b"}}

    class _Throwaways:
        def __init__(self, *a, **k):
            pass

        async def agent(self, dev, label=""):
            return dict(agents[label])

        async def close(self):
            return None

    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool == "theprotocol_submitDispute":
            return True, _answer({"dispute_id": 41, "complainant_did": "did:theprotocol:a"}), "200"
        if tool == "theprotocol_submitDisputeEvidence":
            return True, _answer({"dispute_id": 41}), "200"
        if tool == "theprotocol_logEnhancedDispute":
            return True, _answer({"id": 42}), "200"
        if tool == "theprotocol_logTegDispute":
            return True, _answer({"dispute_log_id": _TEG_LOG, "status": "logged"}), "200"
        if tool == "theprotocol_getTegDisputeDetail":
            return True, _answer({"dispute_log_id": args.get("dispute_log_id")}), "200"
        if tool == "theprotocol_resolveTegDispute":
            return False, _answer({"detail": "Not authorized"}), "403"
        return False, _answer({"detail": "not in this test"}), "400"

    monkeypatch.setattr(ef, "Throwaways", _Throwaways)
    bag = SimpleNamespace(sentinel_jwt="jwt-sentinel", sentinel_did="did:theprotocol:sentinel", developer_jwt="d",
                          developer_id="1", rpc_admin=None, flow_values=dict(flow_values))
    outcomes = {}
    asyncio.run(earned_agent_public.lifecycle_earned_disputes(rpc, F._parse_rpc_result, bag, outcomes))
    return calls, outcomes


def test_a_run_with_no_phase_4_files_its_own_teg_dispute_and_reads_it_back(monkeypatch):
    # a cloud operator's run: no phase 4, so no TEG dispute in flow_values (logTegDispute read "refusal only" on V0641's
    # operators, getTegDisputeDetail not measured); A files one against B and reads it back as its claimant
    calls, outcomes = _disputes_run(monkeypatch, {})
    filed = [a for t, a in calls if t == "theprotocol_logTegDispute"]
    assert len(filed) == 1 and filed[0]["agent_jwt"] == "jwt-a" and filed[0]["defendant_agent_did"] == "did:theprotocol:b"
    read = [a for t, a in calls if t == "theprotocol_getTegDisputeDetail"]
    assert read == [{"agent_jwt": "jwt-a", "dispute_log_id": _TEG_LOG}]
    assert outcomes["theprotocol_logTegDispute"].get("healthy") is True
    assert outcomes["theprotocol_getTegDisputeDetail"].get("healthy") is True


def test_a_frame_run_reads_phase_4s_dispute_and_files_no_second_one(monkeypatch):
    calls, outcomes = _disputes_run(monkeypatch, {"dispute_id": _PHASE4_LOG})
    assert [t for t, _ in calls if t == "theprotocol_logTegDispute"] == []
    read = [a for t, a in calls if t == "theprotocol_getTegDisputeDetail"]
    assert read == [{"agent_jwt": "jwt-sentinel", "dispute_log_id": _PHASE4_LOG}]
    assert "theprotocol_logTegDispute" not in outcomes, "phase 4's row is the frame's own"


def test_without_a_complainant_no_teg_dispute_is_filed_and_the_read_says_why(monkeypatch):
    # control: the throwaway agents could not be made, so nothing is filed and the read is not measured, with the reason
    lost = {"complainant": {"why": "createAgent answered HTTP 503"}, "defendant": {"why": "createAgent answered HTTP 503"}}
    calls, outcomes = _disputes_run(monkeypatch, {}, agents=lost)
    assert [t for t, _ in calls if t == "theprotocol_logTegDispute"] == []
    row = outcomes["theprotocol_getTegDisputeDetail"]
    assert not row.get("healthy") and "no TEG dispute was filed" in str(row) and "HTTP 503" in str(row)
