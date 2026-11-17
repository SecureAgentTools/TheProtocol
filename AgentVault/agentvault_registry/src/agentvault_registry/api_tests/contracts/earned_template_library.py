"""§MCPTEST30 V0666 Tests package, part B (Guild order gwo_c8a03e81f09c9fa4d1df4a23): the success legs of the six workflow template tools V0664 added and that pass the
MCP suite on a refusal alone (EU's History, the V0664 pair run nt261115x3, 0ef93bd0d1ba481c; session-tester's SPLIT_2026-11-15.md).

The six, in one chain on two throwaway developers of the run's own:
  createWorkflowTemplate           the seller's agent creates a PUBLIC, purchase-priced template with a draft v1 (a kit whose manifest has
                                   a workflow section); read back: the seller's own list names it, a draft, at the price asked
  publishWorkflowTemplateVersion   the seller publishes v1; read back: the public read names v1 as the current version, with the hash
                                   create answered; a second publish is refused ("a published version never changes", kept)
  getWorkflowTemplate              the public read of that template (no auth): its listing says what was created (slug, price, owner,
                                   the current version and its hash) and its structure says what the kit's manifest holds
  purchaseWorkflowTemplate         the buyer (a second developer, funded for it) buys it; read back: the buyer's balance fell by the price
                                   and the seller's rose by it (the escrow's two legs, no fee), and the buyer now reads the version's
                                   files, which it was refused (402, kept) before
  forkWorkflowTemplate             the buyer forks it; read back: its own list names the fork, private, naming the parent; the parent's
                                   public read counts the fork
  instantiateWorkflowTemplate      the buyer starts a workflow draft from it (budget 10); read back: the workflow's template block names the template, its
                                   version and its content hash, with the manifest's two steps; the draft is cancelled after
The refusals kept beside the successes (`refusal:` rows, never the tool's own row): a kit with no migration.yaml, a second publish, a
fork of the paid template before it was bought.

Only where the target itself states "sandbox" AND is torn down after its run (MCP_TESTER_EPHEMERAL_TARGET: the nightly and proof
pairs): a template stays in the library for good (no route removes one) and a priced one needs a seller whose reputation bond stays
locked (the commons member's helper, which funds and bonds a throwaway). Elsewhere each of the five is NOT MEASURED, said. The public
read getWorkflowTemplate has no such need: where the chain cannot run it reads a public template the target already lists and checks
the answer against the list's own entry; no public template there is NOT MEASURED, said. Nothing moves value but the one purchase
(buyer to seller: Δ-neutral; both agents' balances go back to the treasury in Throwaways.close)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import EPHEMERAL_ENV, ephemeral_target
from agentvault_registry.api_tests.contracts.earned_agent_public import _check, _d, _rest, _tag, sandbox_stated

CREATE = "theprotocol_createWorkflowTemplate"
PUBLISH = "theprotocol_publishWorkflowTemplateVersion"
GET = "theprotocol_getWorkflowTemplate"
PURCHASE = "theprotocol_purchaseWorkflowTemplate"
FORK = "theprotocol_forkWorkflowTemplate"
INSTANTIATE = "theprotocol_instantiateWorkflowTemplate"
VERSION = "theprotocol_getWorkflowTemplateVersion"
LIST_MINE = "theprotocol_listMyWorkflowTemplates"
LIST_PUBLIC = "theprotocol_listWorkflowTemplates"
BALANCES = "theprotocol_getBatchAgentBalances"
TOOLS: Tuple[Tuple[str, str], ...] = ((CREATE, "2"), (PUBLISH, "2"), (PURCHASE, "2"), (FORK, "2"), (INSTANTIATE, "2"), (GET, "1"))
PRICE = "1"

NOT_EPHEMERAL = ("a template stays in the library for good (no route removes one) and a priced one needs a seller whose reputation bond "
                 f"stays locked: the chain is written only where the target is torn down after its run ({EPHEMERAL_ENV}=true: the "
                 "nightly and proof pairs)")

# a kit the library accepts: the manifest has a workflow section (what instantiate reads), nothing in it names a destination of its own
MANIFEST = """\
schema: theprotocol.migration/v1
name: mcp-tester-customers
title: Customers from a CRM table to PostgreSQL
summary: One table to one table, upsert by the old id
from: {kind: sql, engines: [postgresql, mysql, sqlserver, sqlite], what: a customers table}
to: {kind: sql, engines: [postgresql], what: public.customers}
parameters:
  SOURCE_ENGINE: {description: the old database, default: sqlite, enum: [postgresql, mysql, sqlserver, sqlite]}
  SOURCE_PASSWORD: {description: a read-only login, secret: true}
  TARGET_TABLE: {default: public.customers}
load:
  mappings: [customers]
  batch_rows: 1000
reconcile:
  - mapping: customers
    source: {key: [id], fields: [name, email, created_at]}
    target: {key: [legacy_id], fields: [full_name, email, created]}
    pairs: {name: full_name, email: email, created_at: created}
sample:
  customers: {file: sample/customers.csv, format: csv}
cutover:
  checklist: [Stop writes to the old system, Load again, Reconcile again, Point the readers at the new system]
rollback: auto
workflow:
  - {key: dry-run, role: migration.runner, acceptance: a dry-run report whose verdict is pass, budget_share: 40}
  - {key: reconcile, role: migration.reconciler, input_from: dry-run, acceptance: a reconcile report whose verdict is pass, budget_share: 60}
"""
PROXY = """\
version: 1
sources:
  customers: {type: sqlpoll, config: {engine: "${SOURCE_ENGINE}", password: "env:SOURCE_PASSWORD", table: customers}}
sinks:
  crm: {type: sql_upsert, config: {engine: postgresql, password: "file:/run/secrets/target", table: "${TARGET_TABLE}"}}
mappings:
  customers: {source: customers, sink: crm, fields: {legacy_id: $.id, full_name: $.name, email: $.email}}
"""
KIT: Dict[str, str] = {"migration.yaml": MANIFEST, "proxy.yaml": PROXY, "README.md": "# MCP tester customers\n",
                       "sample/customers.csv": "id,name,email,created_at\n1,Ada,ada@example.org,2026-01-01\n"}


def _money(x: Any) -> Optional[Decimal]:
    try:
        v = Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return v if v.is_finite() else None


def _all_unmeasured(outcomes: Dict[str, dict], why: str, tools: Tuple[Tuple[str, str], ...] = TOOLS) -> None:
    for tool, tier in tools:
        if tool not in outcomes:
            ef.unmeasured(outcomes, tool, tier, why)


async def _sandbox(rpc: Any, parse: Any, bag: Any) -> Tuple[bool, str]:
    ok, body, code = await rpc("theprotocol_getPublicRegistryConfig", {}, jwt=bag.developer_jwt, timeout=30)
    return sandbox_stated(bool(ok), code, _d(parse(body)) if ok else None)


async def _bonded_seller(rpc: Any, parse: Any, bag: Any, tag: str) -> Dict[str, Any]:
    """A throwaway developer with an agent funded and bonded by its own deposit (the commons member's helper, which the commons ballot
    legs use on a pair): {"agent_jwt", "access_token", "did", "email", "password"} or {"why"}."""
    return await ef.lc()._commons_member_of_the_run(rpc, parse, bag, tag, "-tpl")


async def _read(rpc: Any, parse: Any, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[bool, Dict[str, Any], str]:
    """A call that records no row: (ok, the answer parsed, the code)."""
    ok, body, code = await rpc(tool, args, jwt=jwt, timeout=30)
    return bool(ok), _d(parse(body) if isinstance(body, dict) else {}), str(code)


async def _held(rpc: Any, parse: Any, did: str, owner_jwt: str) -> Optional[Decimal]:
    ok, ans, _c = await _read(rpc, parse, BALANCES, {"agent_dids": [did]}, owner_jwt)
    entry = _d(_d(ans.get("balances")).get(did)) if ok else {}
    return None if entry.get("error") else _money(entry.get("balance"))


async def _mine(rpc: Any, parse: Any, agent_jwt: str, owner_jwt: str, tid: str) -> Dict[str, Any]:
    """The agent's own list, the item for `tid` (or {})."""
    ok, ans, _c = await _read(rpc, parse, LIST_MINE, {"agent_jwt": agent_jwt}, owner_jwt)
    return next((i for i in ans.get("items") or [] if isinstance(i, dict) and i.get("id") == tid), {}) if ok else {}


# ── getWorkflowTemplate on a template the target already lists (where the chain does not run) ───────────────────

async def _get_existing(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    ok, ans, code = await _read(rpc, parse, LIST_PUBLIC, {"limit": 20}, bag.developer_jwt)
    items = [i for i in (ans.get("items") or []) if isinstance(i, dict) and i.get("id")] if ok else []
    if not items:
        return ef.unmeasured(outcomes, GET, "1", "the target lists no public template to read (listWorkflowTemplates answered "
                                                 f"{'none' if ok else 'HTTP ' + code}): the chain that makes one runs only where the target is torn down")
    want = items[0]
    ok, got = await ef.step(rpc, parse, GET, "1", {"template_id": want["id"]}, bag.developer_jwt, outcomes)
    if ok:
        why = None
        for k in ("id", "slug", "title", "owner_agent_did", "price"):
            if got.get(k) != want.get(k):
                why = f"the page's {k} is {got.get(k)!r}, the list's own entry says {want.get(k)!r}"
                break
        _check(outcomes, GET, why)


# ── the chain ─────────────────────────────────────────────────────────────────────────────────────

async def lifecycle_earn_workflow_templates(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The module docstring."""
    staged, why = await _sandbox(rpc, parse, bag)
    if not staged:
        return _all_unmeasured(outcomes, f"templates are written only where the target itself states 'sandbox': {why}")
    if not ephemeral_target():
        _all_unmeasured(outcomes, NOT_EPHEMERAL, tuple(x for x in TOOLS if x[0] != GET))
        return await _get_existing(rpc, parse, bag, outcomes)
    tag = _tag()
    seller = await _bonded_seller(rpc, parse, bag, tag)
    if not seller.get("agent_jwt"):
        _all_unmeasured(outcomes, f"no seller with a reputation bond could be made ({seller.get('why')})", tuple(x for x in TOOLS if x[0] != GET))
        if seller.get("email") and seller.get("password"):
            await ef.lc()._schedule_own_deletion(rpc, bag, seller["email"], seller["password"], "the template chain's seller")
        return await _get_existing(rpc, parse, bag, outcomes)
    t = ef.Throwaways(rpc, parse, bag, "wt-buyer")
    sown, sdid = seller["access_token"], seller["did"]
    wids: List[str] = []
    buyer: Dict[str, Any] = {}
    slug = f"mcp-earn-{tag}".lower()
    tid, chash, forked = "", "", False
    try:
        tid, chash = await _create_and_publish(rpc, parse, bag, outcomes, seller, slug)
        if not tid:
            _all_unmeasured(outcomes, "the seller's template could not be made (see the createWorkflowTemplate row)",
                            tuple(x for x in TOOLS if x[0] not in (CREATE, PUBLISH, GET)))
        else:
            forked = await _buyer_steps(rpc, parse, bag, outcomes, t, tid, chash, seller, buyer, tag, wids)
        await _get_chain(rpc, parse, bag, outcomes, tid, slug, chash, forked)
    finally:
        if tid:                # no route removes a template: the owner's own patch takes it out of every public list (before its agent goes)
            await _rest(bag, parse, "PATCH", f"/api/v1/workflow-templates/{tid}", {"visibility": "private"}, as_jwt=seller["agent_jwt"])
        for wid in wids:      # a draft posts nothing: cancelled so no workflow of the run is left open
            if buyer.get("agent_jwt"):         # the workflow is the agent's own: its token reads and cancels it
                await _rest(bag, parse, "POST", f"/api/v1/workflows/{wid}/cancel", {}, as_jwt=buyer["agent_jwt"])
        await t.close()
        # the seller's agent goes back to the treasury and is deleted; its bond stays with the pair that is torn down after the run
        try:
            held = await _held(rpc, parse, sdid, sown)
            if held and held > 0 and getattr(bag, "rpc_admin", None) is not None:
                await bag.rpc_admin("theprotocol_tegTreasuryReceive", {
                    "source_agent_did": sdid, "amount": format(held, "f"), "reason": "mcp_tester_fixture_retired",
                    "reference_id": f"mcp-tester-retire-{sdid[-12:]}"}, jwt=bag.developer_jwt, timeout=25)
            await rpc("theprotocol_deleteMyAgentByDev", {"agent_did": sdid}, jwt=sown, timeout=30)
        except Exception:                                              # noqa: BLE001 - cleanup is never a finding
            pass
        if seller.get("email") and seller.get("password"):
            await ef.lc()._schedule_own_deletion(rpc, bag, seller["email"], seller["password"], "the template chain's seller")


async def _buyer_steps(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], t: Any, tid: str, chash: str,
                       seller: Dict[str, Any], buyer: Dict[str, Any], tag: str, wids: List[str]) -> bool:
    """The buyer's half: purchase, fork, instantiate. Whether the fork was made (the public page then counts it)."""
    rest = tuple(x for x in TOOLS if x[0] in (PURCHASE, FORK, INSTANTIATE))
    if getattr(bag, "rpc_admin", None) is None:
        _all_unmeasured(outcomes, "the buyer's agent cannot be funded: this flow carries no admin bridge (bag.rpc_admin)", rest)
        return False
    dev = await t.developer("wt-buyer")
    buyer.update(await t.agent(dev, "buyer"))
    if buyer.get("why"):
        _all_unmeasured(outcomes, f"no buyer agent could be made ({buyer.get('why')})", rest)
        return False
    bjwt, bown, bdid = buyer["agent_jwt"], buyer["owner_jwt"], buyer["did"]
    held = await _held(rpc, parse, bdid, bown)
    if held is None or held < Decimal(PRICE) + 1:
        st, resp = await _rest(bag, parse, "POST", "/api/v1/teg/treasury/fund-agent", {
            "target_agent_did": bdid, "amount": str(Decimal(PRICE) + 1), "reason": "admin_grant",
            "reference_id": f"mcp-wt-buyer-{tag}"})
        if st != 200:
            _all_unmeasured(outcomes, f"the treasury could not fund the buyer (HTTP {st}: {ef.said(resp)})", rest)
            return False
    # the buyer's refusals before it bought: the paid files are for the owner and the buyers
    await ef.refusal_step(rpc, parse, FORK, "2", {"template_id": tid, "agent_jwt": bjwt}, bown, outcomes,
                          "a paid template before it was bought", codes=(402,), text="purchase-priced")
    await ef.refusal_step(rpc, parse, VERSION, "2", {"template_id": tid, "version": 1, "agent_jwt": bjwt}, bown, outcomes,
                          "a paid template's files before it was bought", codes=(402,), text="purchase-priced")
    await _purchase(rpc, parse, outcomes, tid, seller, buyer)
    forked = await _fork(rpc, parse, outcomes, tid, buyer)
    wid = await _instantiate(rpc, parse, bag, outcomes, tid, chash, buyer)
    if wid:
        wids.append(wid)
    return forked


async def _create_and_publish(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], seller: Dict[str, Any],
                              slug: str) -> Tuple[str, str]:
    sjwt, sown = seller["agent_jwt"], seller["access_token"]
    # a kit with no migration.yaml is refused naming it (kept beside the success)
    bad = {k: v for k, v in KIT.items() if k != "migration.yaml"}
    await ef.refusal_step(rpc, parse, CREATE, "2", {"slug": slug + "-bad", "title": "no manifest", "files": bad, "agent_jwt": sjwt},
                          sown, outcomes, "a kit with no migration.yaml", codes=(422,), text="migration.yaml")
    ok, ans = await ef.step(rpc, parse, CREATE, "2", {
        "slug": slug, "title": f"MCP tester template {slug[-12:]}", "files": KIT, "summary": "made by the MCP tester for one run",
        "visibility": "public", "pricing_model": "purchase", "price": PRICE, "fork_share_bps": 2000,
        "changelog": "first version", "agent_jwt": sjwt}, sown, outcomes)
    tid, chash = str(ans.get("template_id") or ""), str(ans.get("content_hash") or "")
    if not ok or not tid:
        return "", ""
    mine = await _mine(rpc, parse, sjwt, sown, tid)
    versions = mine.get("versions") if isinstance(mine.get("versions"), list) else []
    price = _money(mine.get("price"))
    why = None
    if not mine:
        why = "the seller's own list does not name the template create answered"
    elif mine.get("slug") != slug or price != Decimal(PRICE) or mine.get("pricing_model") != "purchase":
        why = f"the seller's list reads slug {mine.get('slug')!r}, price {mine.get('price')!r}: not what was created"
    elif not any(isinstance(v, dict) and v.get("version") == 1 and v.get("published") is False for v in versions):
        why = f"the seller's list shows no draft v1 (versions {versions!r})"
    _check(outcomes, CREATE, why)
    if why:
        return "", ""
    ok, pub = await ef.step(rpc, parse, PUBLISH, "2", {"template_id": tid, "version": 1, "agent_jwt": sjwt}, sown, outcomes)
    if ok:
        okg, page, _c = await _read(rpc, parse, GET, {"template_id": tid}, bag.developer_jwt)
        why = None
        if not okg:
            why = "the public read of the published template failed"
        elif page.get("current_version") != 1 or str(page.get("current_content_hash") or "") != chash:
            why = (f"the public read names current version {page.get('current_version')!r} with hash "
                   f"{str(page.get('current_content_hash'))[:12]!r}, not v1 with {chash[:12]!r}")
        _check(outcomes, PUBLISH, why)
        if why:
            return "", ""
        await ef.refusal_step(rpc, parse, PUBLISH, "2", {"template_id": tid, "version": 1, "agent_jwt": sjwt}, sown, outcomes,
                              "a version already published", codes=(409,), text="never changes")
    else:
        return "", ""
    return tid, chash


async def _get_chain(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], tid: str, slug: str, chash: str,
                     forked: bool) -> None:
    """getWorkflowTemplate on the run's own template (no auth), read after the buyers' steps so its counts are in."""
    if not tid:
        return await _get_existing(rpc, parse, bag, outcomes)
    ok, page = await ef.step(rpc, parse, GET, "1", {"template_id": tid}, bag.developer_jwt, outcomes)
    if not ok:
        return
    structure = _d(page.get("structure"))
    why = None
    if page.get("slug") != slug or _money(page.get("price")) != Decimal(PRICE) or page.get("pricing_model") != "purchase":
        why = f"the page reads slug {page.get('slug')!r}, price {page.get('price')!r}, not what was created"
    elif page.get("current_version") != 1 or str(page.get("current_content_hash") or "") != chash:
        why = "the page does not name the published v1 and its hash"
    elif structure.get("steps") not in (2, ["dry-run", "reconcile"]) and len(structure.get("steps") or []) != 2:
        why = f"the page's structure does not show the manifest's two steps ({structure.get('steps')!r})"
    elif forked and int(_d(page.get("counts")).get("forks") or 0) < 1:
        why = f"the page's counts do not include the buyer's fork ({page.get('counts')!r})"
    _check(outcomes, GET, why)


async def _purchase(rpc: Any, parse: Any, outcomes: Dict[str, dict], tid: str, seller: Dict[str, Any], buyer: Dict[str, Any]) -> None:
    b0 = await _held(rpc, parse, buyer["did"], buyer["owner_jwt"])
    s0 = await _held(rpc, parse, seller["did"], seller["access_token"])
    ok, ans = await ef.step(rpc, parse, PURCHASE, "2", {"template_id": tid, "agent_jwt": buyer["agent_jwt"]}, buyer["owner_jwt"], outcomes)
    if not ok:
        return
    b1 = await _held(rpc, parse, buyer["did"], buyer["owner_jwt"])
    s1 = await _held(rpc, parse, seller["did"], seller["access_token"])
    price = Decimal(PRICE)
    why = None
    if None in (b0, s0, b1, s1):
        why = "a balance could not be read before or after the purchase"
    elif b0 - b1 != price or s1 - s0 != price:
        why = f"the legs read buyer {b0}->{b1} and seller {s0}->{s1}, not {price} out and {price} in"
    else:
        okv, files, code = await _read(rpc, parse, VERSION, {"template_id": tid, "version": 1, "agent_jwt": buyer["agent_jwt"]},
                                       buyer["owner_jwt"])
        if not okv or "migration.yaml" not in _d(files.get("files")):
            why = f"the buyer still cannot read the version's files (HTTP {code})"
    _check(outcomes, PURCHASE, why)


async def _fork(rpc: Any, parse: Any, outcomes: Dict[str, dict], tid: str, buyer: Dict[str, Any]) -> bool:
    ok, ans = await ef.step(rpc, parse, FORK, "2", {"template_id": tid, "agent_jwt": buyer["agent_jwt"]}, buyer["owner_jwt"], outcomes)
    nid = str(ans.get("template_id") or "")
    if not ok or not nid:
        return False
    mine = await _mine(rpc, parse, buyer["agent_jwt"], buyer["owner_jwt"], nid)
    why = None
    if not mine:
        why = "the buyer's own list does not name the fork"
    elif mine.get("forked_from_template_id") != tid or ans.get("forked_from") != tid:
        why = f"the fork names parent {mine.get('forked_from_template_id')!r}, not {tid!r}"
    elif mine.get("visibility") != "private" or mine.get("pricing_model") != "free":
        why = f"the fork is {mine.get('visibility')!r}/{mine.get('pricing_model')!r}, not private and free"
    _check(outcomes, FORK, why)
    return True


async def _instantiate(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], tid: str, chash: str, buyer: Dict[str, Any]) -> str:
    ok, ans = await ef.step(rpc, parse, INSTANTIATE, "2", {"template_id": tid, "total_budget": "10", "agent_jwt": buyer["agent_jwt"]},
                            buyer["owner_jwt"], outcomes)
    wid = str(ans.get("workflow_id") or "")
    if not ok or not wid:
        return ""
    st, wf = await _rest(bag, parse, "GET", f"/api/v1/workflows/{wid}", as_jwt=buyer["agent_jwt"])
    wf = _d(wf)
    steps = [s.get("key") for s in (wf.get("steps") or []) if isinstance(s, dict)]
    why = None
    if st != 200:
        why = f"the workflow read answers HTTP {st}"
    elif steps != ["dry-run", "reconcile"]:
        why = f"the workflow's steps are {steps!r}, not the manifest's dry-run and reconcile"
    elif _d(wf.get("template")).get("id") != tid or str(_d(wf.get("template")).get("content_hash") or "") != chash \
            or _d(wf.get("template")).get("version") != 1:
        blk = _d(wf.get("template"))
        why = (f"the workflow's template block names {blk.get('id')!r} v{blk.get('version')!r} with hash "
               f"{str(blk.get('content_hash'))[:12]!r}, not {tid!r} v1 with {chash[:12]!r}")
    _check(outcomes, INSTANTIATE, why)
    return wid


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_workflow_templates", "runner": lifecycle_earn_workflow_templates},
]
