"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): the template library's rules, driven through
services/workflow_templates.Library against an in-memory store (DbStore is the same interface on the database).

  see       a template is shown when visible: public, unlisted (by id), its organization's agents, its owner; a
            developer through an agent it owns that qualifies; anonymous callers see public and unlisted ones
  files     a version's files go to anyone when the template is free and visible, else to the owner and buyers (a
            developer through an agent it owns); 402 otherwise; a draft only to its owner
  write     create (a draft v1), versions, publish (immutable after), patch (metadata only), fork (needs the right to the
            files; starts private and free; lineage kept), purchase, instantiate, certified: agent tier
  money     purchase = escrow deposit "wtpl:{tid}:{buyer}:in", payout to the author ":out", and for a fork whose parent
            sets a share, payout to the parent's author ":up"; one level; no fee; one purchase per buyer (the owner and an
            existing buyer answer "already"); the purchase is RECORDED before the deposit (price, share, payees,
            currency) and a retry pays what the record says, never the template's price at the retry (session-lead,
            room seq 3873); done after both payouts; a refusal before anything moved (an insufficient balance) is 402
            and withdraws the record; an unconfirmed deposit (a 409 or a 5xx) is 502 and keeps it
  use       instantiate makes a V0663 workflow draft from the manifest's workflow with the template's provenance;
            certified checks the agent's own TEG attestation (type migration.certificate, the hash of the data it posts,
            a claim naming this template, one of its versions' content hashes and a pass) and counts once per
            template and agent (session-lead, room seq 3755)
Red on v0663/cut b7ca684e9: the module does not exist.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest

try:
    from agentvault_registry.services import workflow_templates as wt
except ImportError:
    wt = None

from tests.test_workflow_templates_kit_v0664 import MANIFEST, kit

T0 = dt.datetime(2026, 11, 14, 14, tzinfo=dt.timezone.utc)
OWNER, BUYER, OTHER, MEMBER, PARENT_AUTHOR = "did:a:owner", "did:a:buyer", "did:a:other", "did:a:member", "did:a:parent"
DEVS = {OWNER: 1, BUYER: 2, OTHER: 3, MEMBER: 4, PARENT_AUTHOR: 5}
ORGS = {OWNER: "org-1", MEMBER: "org-1"}


def agent(did):
    return {"kind": "agent", "did": did, "developer_id": DEVS.get(did), "org": ORGS.get(did)}


def developer(dev):
    return {"kind": "developer", "developer_id": dev}


class FakeStore:
    def __init__(self):
        self.templates, self.versions, self.purchases, self.uses = {}, {}, {}, []
        self.legs, self.paid_keys, self.events, self.workflows, self.attestations = [], {}, [], {}, {}
        self.fail_payout_once, self.decline, self.lose_deposit_answer_once = False, False, False
        self.clock = T0
        self.bond_mode, self.bonded, self.bond_asks = "off", set(), []   # the reputation bond gate, site template_publish
        self.enf_mode, self.enforced, self.enf_asks = "off", set(), []    # the suspension gate (enforcement_propagation)

    # reads
    async def template(self, tid):
        t = self.templates.get(tid)
        return dict(t) if t else None

    async def template_versions(self, tid):
        return sorted((dict(v) for v in self.versions.values() if v["template_id"] == tid), key=lambda v: v["version"])

    async def version(self, tid, n):
        v = next((v for v in self.versions.values() if v["template_id"] == tid and v["version"] == n), None)
        return dict(v) if v else None

    async def slug_taken(self, owner, slug):
        return any(t["owner_agent_did"] == owner and t["slug"] == slug for t in self.templates.values())

    async def purchased(self, tid, did):
        return (self.purchases.get((tid, did)) or {}).get("status") == "done"

    async def purchase_row(self, tid, did):
        row = self.purchases.get((tid, did))
        return dict(row) if row else None

    async def developer_owns(self, dev, did):
        return DEVS.get(did) == dev

    async def developer_bought(self, dev, tid):
        return any(t == tid and DEVS.get(b) == dev and r["status"] == "done" for (t, b), r in self.purchases.items())

    async def developer_in_org(self, dev, org):
        return any(DEVS.get(d) == dev and o == org for d, o in ORGS.items())

    async def list_public(self, filters):
        hide = self.enforced if self.enf_mode == "enforce" else set()   # as DbStore: a suspended author's leave the list
        return [dict(t) for t in self.templates.values() if t["visibility"] == "public" and t["owner_agent_did"] not in hide]

    async def counts(self, tid):
        return {"kit_downloads": sum(1 for u in self.uses if u["template_id"] == tid and u["kind"] == "kit"),
                "instantiations": len({u["agent_did"] for u in self.uses if u["template_id"] == tid and u["kind"] == "instantiate"}),
                "certified": len({u["agent_did"] for u in self.uses if u["template_id"] == tid and u["kind"] == "certified"}),
                "forks": sum(1 for t in self.templates.values() if t.get("forked_from_template_id") == tid)}

    async def templates_of_agent(self, did):
        return sorted((dict(t) for t in self.templates.values() if t["owner_agent_did"] == did), key=lambda t: t["id"])

    async def templates_of_developer(self, dev):
        return sorted((dict(t) for t in self.templates.values() if DEVS.get(t["owner_agent_did"]) == dev),
                      key=lambda t: t["id"])

    async def buyers(self, tid):
        return [{"buyer_did": b, "done_at": r.get("done_at")} for (t, b), r in sorted(self.purchases.items())
                if t == tid and r["status"] == "done"]

    async def certified_by(self, tid, did):
        return any(u["template_id"] == tid and u["kind"] == "certified" and u["agent_did"] == did for u in self.uses)

    async def agent_attestations(self, did):
        return list(self.attestations.get(did, []))

    # writes
    async def insert_template(self, row):
        self.templates[row["id"]] = dict(row)

    async def update_template(self, tid, **fields):
        self.templates[tid].update(fields)

    async def insert_version(self, row):
        self.versions[row["id"]] = dict(row)

    async def update_version(self, vid, **fields):
        self.versions[vid].update(fields)

    def _leg(self, kind, did, amount, ref):
        """As the TEG's durable key: a replay with the same amount moves nothing, another amount is refused (409)."""
        if ref in self.paid_keys:
            if self.paid_keys[ref] != Decimal(str(amount)):
                raise RuntimeError(f"409: the key {ref} was used with another amount")
            return
        self.paid_keys[ref] = Decimal(str(amount))
        self.legs.append((kind, did, Decimal(str(amount)), ref))

    @staticmethod
    def _declined(sentence, status):
        return wt.PaymentDeclined(sentence, status=status)

    async def deposit(self, did, amount, ref):
        if self.decline:
            raise self._declined("insufficient balance", 400)
        self._leg("deposit", did, amount, ref)
        if self.lose_deposit_answer_once:          # the deposit took, its answer was lost on the way back
            self.lose_deposit_answer_once = False
            raise self._declined("the ledger answered 502", 502)

    async def payout(self, did, amount, ref):
        if self.fail_payout_once:
            self.fail_payout_once = False
            raise RuntimeError("the ledger dropped the connection")
        self._leg("payout", did, amount, ref)

    def taken_and_paid(self, ref_prefix):
        took = sum(l[2] for l in self.legs if l[0] == "deposit" and l[3].startswith(ref_prefix))
        paid = sum(l[2] for l in self.legs if l[0] == "payout" and l[3].startswith(ref_prefix))
        return took, paid

    async def insert_pending_purchase(self, row):
        self.purchases.setdefault((row["template_id"], row["buyer_did"]), {**row, "status": "pending"})

    async def withdraw_pending_purchase(self, tid, did):
        if (self.purchases.get((tid, did)) or {}).get("status") == "pending":
            del self.purchases[(tid, did)]

    async def finish_purchase(self, row, at):
        key = (row["template_id"], row["buyer_did"])
        cur = self.purchases.get(key)
        if cur is not None and cur["status"] == "done":
            return False
        self.purchases[key] = {**(cur or row), "status": "done", "done_at": at}
        return True

    async def add_use(self, row):
        self.uses.append(dict(row))

    async def enforcement_gate(self, did):
        """As DbStore's: services/enforcement_propagation.gate at site template_publish, its refusal as the library's."""
        self.enf_asks.append(did)
        if self.enf_mode == "enforce" and did in self.enforced:
            raise wt.LibraryRefusal(403, "enforced", f"Agent {did} is suspended by EU; template_publish is refused while "
                                                     f"the enforcement stands (ENFORCEMENT_PROPAGATION_MODE=enforce).")

    async def bond_gate(self, did):
        """As DbStore's: services/reputation_bond.gate at site template_publish, its enforce refusal as the library's."""
        self.bond_asks.append(did)
        if self.bond_mode == "enforce" and did not in self.bonded:
            raise wt.LibraryRefusal(403, "bond_required", f"{did} holds no reputation bond. Publishing here "
                                                          f"(template_publish) requires a bond of 250")

    async def emit(self, event, tid, data):
        self.events.append((event, tid, data))

    async def create_workflow(self, owner_did, body):
        wid = f"wf_{len(self.workflows) + 1}"
        self.workflows[wid] = {"owner": owner_did, **body}
        return wid

    async def set_provenance(self, wid, tid, version, content_hash):
        self.workflows[wid]["provenance"] = (tid, version, content_hash)

    def now(self):
        return self.clock


def run(c):
    return asyncio.run(c)


def lib(s):
    return wt.Library(s)


def refused(coro, status, code):
    with pytest.raises(wt.LibraryRefusal) as e:
        run(coro)
    assert (e.value.status, e.value.code) == (status, code), (e.value.status, e.value.code, e.value.sentence)
    return e.value


def make(s, *, by=OWNER, visibility="public", pricing="free", price=None, publish=True, slug="crm-to-pg", **over):
    out = run(lib(s).create(agent(by), {"slug": slug, "title": "CRM to Postgres", "summary": "one table",
                                        "visibility": visibility, "pricing_model": pricing, "price": price,
                                        "files": kit(), **over}))
    tid = out["template_id"]
    if publish:
        run(lib(s).publish(agent(by), tid, 1))
    return tid


# --- see and files ---------------------------------------------------------------------------------------------------

def test_anyone_reads_a_free_public_templates_files_and_a_paid_ones_answer_402():
    s = FakeStore()
    free, paid = make(s), make(s, slug="paid", pricing="purchase", price="5")
    assert run(lib(s).version(None, free, 1))["files"]["migration.yaml"] == MANIFEST
    refused(lib(s).version(None, paid, 1), 402, "payment_required")
    detail = run(lib(s).detail(None, paid))
    assert detail["structure"]["steps"][0]["key"] == "dry-run" and "files" not in json.dumps(detail["versions"])


def test_the_owner_and_a_buyer_read_a_paid_templates_files_and_so_do_their_developers():
    s = FakeStore()
    paid = make(s, pricing="purchase", price="5")
    run(lib(s).purchase(agent(BUYER), paid))
    for actor in (agent(OWNER), agent(BUYER), developer(1), developer(2)):
        assert run(lib(s).version(actor, paid, 1))["content_hash"]
    for actor in (agent(OTHER), developer(3)):
        refused(lib(s).version(actor, paid, 1), 402, "payment_required")


@pytest.mark.parametrize("actor,expect", [
    (None, 404), (agent(OTHER), 403), (developer(3), 403),
    (agent(OWNER), 200), (developer(1), 200), (agent(MEMBER), 200), (developer(4), 200),
])
def test_an_org_template_is_seen_by_its_organization_and_its_owner(actor, expect):
    s = FakeStore()
    tid = make(s, visibility="org")
    try:
        run(lib(s).detail(actor, tid))
        got = 200
    except wt.LibraryRefusal as e:
        got = e.status
    assert got == expect


def test_a_private_template_is_its_owners_and_an_unlisted_one_is_reached_by_id_but_never_listed():
    s = FakeStore()
    priv, unl = make(s, visibility="private"), make(s, slug="unl", visibility="unlisted")
    refused(lib(s).detail(developer(3), priv), 403, "not_visible")
    assert run(lib(s).detail(None, unl))["id"] == unl
    listed = [t["id"] for t in run(lib(s).list({}))["items"]]
    assert priv not in listed and unl not in listed


def test_a_draft_version_is_its_owners_only():
    s = FakeStore()
    tid = make(s)
    run(lib(s).add_version(agent(OWNER), tid, {"files": kit(**{"README.md": "# v2\n"}), "changelog": "words"}))
    refused(lib(s).version(None, tid, 2), 404, "not_found")
    assert run(lib(s).version(agent(OWNER), tid, 2))["published_at"] is None


def test_a_kit_download_is_counted():
    s = FakeStore()
    tid = make(s)
    run(lib(s).version(None, tid, 1, kit=True))
    run(lib(s).version(agent(OTHER), tid, 1, kit=True))
    assert run(lib(s).detail(None, tid))["counts"]["kit_downloads"] == 2


# --- writes ------------------------------------------------------------------------------------------------------------

def test_create_takes_the_kinds_from_the_manifest_and_refuses_a_bad_kit():
    s = FakeStore()
    tid = make(s, publish=False)
    t = s.templates[tid]
    assert (t["kind"], t["from_kind"], t["to_kind"], t["fork_share_bps"]) == ("migration", "sql", "sql", 2000)
    assert tid.startswith("wtpl_") and s.versions[t["current_version_id"] or next(iter(s.versions))]["version"] == 1
    refused(lib(s).create(agent(OWNER), {"slug": "x2", "title": "t", "files": kit(**{"README.md": None})}), 422, "kit")
    refused(lib(s).create(agent(OWNER), {"slug": "crm-to-pg", "title": "t", "files": kit()}), 409, "slug_taken")


def test_a_published_version_never_changes():
    s = FakeStore()
    tid = make(s)
    refused(lib(s).publish(agent(OWNER), tid, 1), 409, "published")
    h = s.versions[s.templates[tid]["current_version_id"]]["content_hash"]
    run(lib(s).add_version(agent(OWNER), tid, {"files": kit(**{"README.md": "# v2\n"})}))
    run(lib(s).publish(agent(OWNER), tid, 2))
    assert run(lib(s).version(None, tid, 1))["content_hash"] == h
    assert run(lib(s).detail(None, tid))["current_version"] == 2


def test_only_the_owner_writes_and_a_patch_never_touches_content():
    s = FakeStore()
    tid = make(s)
    refused(lib(s).add_version(agent(OTHER), tid, {"files": kit()}), 403, "not_owner")
    refused(lib(s).publish(agent(OTHER), tid, 1), 403, "not_owner")
    refused(lib(s).patch(agent(OTHER), tid, {"title": "x"}), 403, "not_owner")
    refused(lib(s).patch(agent(OWNER), tid, {"files": kit()}), 422, "content")
    refused(lib(s).patch(agent(OWNER), tid, {"fork_share_bps": 5001}), 422, "fork_share_bps")
    refused(lib(s).patch(agent(OWNER), tid, {"pricing_model": "purchase"}), 422, "price")
    out = run(lib(s).patch(agent(OWNER), tid, {"pricing_model": "purchase", "price": "7", "fork_share_bps": 1000}))
    assert (out["pricing_model"], out["price"], out["fork_share_bps"]) == ("purchase", "7", 1000)


# --- money ---------------------------------------------------------------------------------------------------------------

def test_a_purchase_moves_the_price_once_and_a_retry_pays_nothing_more():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="5")
    out = run(lib(s).purchase(agent(BUYER), tid))
    assert out["ok"] is True and s.legs == [("deposit", BUYER, Decimal("5"), f"wtpl:{tid}:{BUYER}:in"),
                                             ("payout", OWNER, Decimal("5"), f"wtpl:{tid}:{BUYER}:out")]
    assert run(lib(s).purchase(agent(BUYER), tid))["already"] == "purchased" and len(s.legs) == 2
    assert run(lib(s).purchase(agent(OWNER), tid))["already"] == "owner"
    assert s.events == [("WorkflowTemplatePurchased", tid, {"buyer": BUYER, "price": "5"})]


def test_a_purchase_stopped_between_its_legs_finishes_on_the_retry_without_paying_twice():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="5")
    s.fail_payout_once = True
    with pytest.raises(RuntimeError):
        run(lib(s).purchase(agent(BUYER), tid))
    assert not run(s.purchased(tid, BUYER)), "not a purchase before both legs"
    run(lib(s).purchase(agent(BUYER), tid))
    assert [l[0] for l in s.legs] == ["deposit", "payout"] and run(s.purchased(tid, BUYER))


def test_a_declined_purchase_is_402_and_moves_nothing():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="5")
    s.decline = True
    refused(lib(s).purchase(agent(BUYER), tid), 402, "payment_declined")
    assert s.legs == [] and not s.purchases


def test_a_retry_after_a_price_change_pays_what_the_first_attempt_recorded():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="10")
    s.fail_payout_once = True
    with pytest.raises(RuntimeError):
        run(lib(s).purchase(agent(BUYER), tid))                  # the deposit took 10, the payout did not run
    run(lib(s).patch(agent(OWNER), tid, {"price": "20"}))
    out = run(lib(s).purchase(agent(BUYER), tid))
    assert Decimal(out["price"]) == Decimal("10")
    assert s.legs == [("deposit", BUYER, Decimal("10"), f"wtpl:{tid}:{BUYER}:in"),
                      ("payout", OWNER, Decimal("10"), f"wtpl:{tid}:{BUYER}:out")]
    took, paid = s.taken_and_paid(f"wtpl:{tid}:")
    assert took == paid == Decimal("10"), "the escrow pays out what it took, never more"
    assert run(s.purchased(tid, BUYER)) and len(s.events) == 1


def test_a_forks_recorded_share_holds_when_the_parent_changes_its_share_before_the_retry():
    s = FakeStore()
    parent = make(s, by=PARENT_AUTHOR, slug="parent")          # fork_share_bps 2000 (the default)
    fork = run(lib(s).fork(agent(OWNER), parent, {"slug": "my-fork"}))["template_id"]
    run(lib(s).publish(agent(OWNER), fork, 1))
    run(lib(s).patch(agent(OWNER), fork, {"visibility": "public", "pricing_model": "purchase", "price": "10"}))
    s.fail_payout_once = True
    with pytest.raises(RuntimeError):
        run(lib(s).purchase(agent(BUYER), fork))
    run(lib(s).patch(agent(PARENT_AUTHOR), parent, {"fork_share_bps": 5000}))
    run(lib(s).patch(agent(OWNER), fork, {"price": "30"}))
    run(lib(s).purchase(agent(BUYER), fork))
    assert s.legs == [("deposit", BUYER, Decimal("10"), f"wtpl:{fork}:{BUYER}:in"),
                      ("payout", OWNER, Decimal("8"), f"wtpl:{fork}:{BUYER}:out"),
                      ("payout", PARENT_AUTHOR, Decimal("2"), f"wtpl:{fork}:{BUYER}:up")]


def test_a_purchase_in_flight_is_not_a_purchase():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="10")
    s.fail_payout_once = True
    with pytest.raises(RuntimeError):
        run(lib(s).purchase(agent(BUYER), tid))
    for actor in (agent(BUYER), developer(2)):
        refused(lib(s).version(actor, tid, 1), 402, "payment_required")


def test_an_unconfirmed_deposit_is_502_and_the_retry_finishes_at_the_recorded_price():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="10")
    s.lose_deposit_answer_once = True
    refused(lib(s).purchase(agent(BUYER), tid), 502, "deposit_unconfirmed")
    run(lib(s).patch(agent(OWNER), tid, {"price": "20"}))
    run(lib(s).purchase(agent(BUYER), tid))
    assert s.legs == [("deposit", BUYER, Decimal("10"), f"wtpl:{tid}:{BUYER}:in"),
                      ("payout", OWNER, Decimal("10"), f"wtpl:{tid}:{BUYER}:out")]


def test_a_clean_decline_records_nothing_and_a_later_purchase_pays_the_price_then():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="10")
    s.decline = True
    refused(lib(s).purchase(agent(BUYER), tid), 402, "payment_declined")
    assert run(s.purchase_row(tid, BUYER)) is None
    run(lib(s).patch(agent(OWNER), tid, {"price": "5"}))
    s.decline = False
    run(lib(s).purchase(agent(BUYER), tid))
    assert s.legs == [("deposit", BUYER, Decimal("5"), f"wtpl:{tid}:{BUYER}:in"),
                      ("payout", OWNER, Decimal("5"), f"wtpl:{tid}:{BUYER}:out")]


def test_a_recorded_purchase_finishes_as_recorded_after_the_template_goes_private_or_free():
    s = FakeStore()
    tid = make(s, pricing="purchase", price="10")
    s.fail_payout_once = True
    with pytest.raises(RuntimeError):
        run(lib(s).purchase(agent(BUYER), tid))                  # 10 sit in escrow now
    run(lib(s).patch(agent(OWNER), tid, {"visibility": "private", "pricing_model": "free"}))
    run(lib(s).purchase(agent(BUYER), tid))
    took, paid = s.taken_and_paid(f"wtpl:{tid}:")
    assert took == paid == Decimal("10"), "the escrow is never left holding a buyer's deposit"


def test_a_forks_sale_pays_its_parents_author_the_parents_share():
    s = FakeStore()
    parent = make(s, by=PARENT_AUTHOR, slug="parent")          # free, fork_share_bps 2000 (the default)
    fork = run(lib(s).fork(agent(OWNER), parent, {"slug": "my-fork"}))["template_id"]
    f = s.templates[fork]
    assert (f["visibility"], f["pricing_model"], f["forked_from_template_id"], f["forked_from_version"]) == \
        ("private", "free", parent, 1)
    run(lib(s).publish(agent(OWNER), fork, 1))
    run(lib(s).patch(agent(OWNER), fork, {"visibility": "public", "pricing_model": "purchase", "price": "10"}))
    run(lib(s).purchase(agent(BUYER), fork))
    assert s.legs == [("deposit", BUYER, Decimal("10"), f"wtpl:{fork}:{BUYER}:in"),
                      ("payout", OWNER, Decimal("8"), f"wtpl:{fork}:{BUYER}:out"),
                      ("payout", PARENT_AUTHOR, Decimal("2"), f"wtpl:{fork}:{BUYER}:up")]
    assert run(lib(s).detail(None, parent))["counts"]["forks"] == 1


def test_a_fork_needs_the_right_to_the_files():
    s = FakeStore()
    paid = make(s, pricing="purchase", price="5")
    refused(lib(s).fork(agent(OTHER), paid, {"slug": "steal"}), 402, "payment_required")
    priv = make(s, slug="priv", visibility="private")
    refused(lib(s).fork(agent(OTHER), priv, {"slug": "steal2"}), 403, "not_visible")
    run(lib(s).purchase(agent(BUYER), paid))
    assert run(lib(s).fork(agent(BUYER), paid, {"slug": "mine"}))["template_id"].startswith("wtpl_")


# --- instantiate and certified ---------------------------------------------------------------------------------------

def test_instantiate_makes_a_workflow_draft_with_the_steps_and_the_provenance():
    s = FakeStore()
    tid = make(s)
    out = run(lib(s).instantiate(agent(OTHER), tid, {"total_budget": "100"}))
    wf = s.workflows[out["workflow_id"]]
    assert wf["owner"] == OTHER and [x["key"] for x in wf["steps"]] == ["dry-run", "reconcile"]
    assert [Decimal(str(x["budget"])) for x in wf["steps"]] == [Decimal("40"), Decimal("60")]
    assert wf["steps"][1]["input_from"] == "dry-run" and wf["steps"][1]["role"] == "migration.reconciler"
    v1 = s.versions[s.templates[tid]["current_version_id"]]
    assert wf["provenance"] == (tid, 1, v1["content_hash"])
    run(lib(s).instantiate(agent(OTHER), tid, {"total_budget": "50"}))
    assert run(lib(s).detail(None, tid))["counts"]["instantiations"] == 1, "distinct agents"


def test_instantiate_needs_a_workflow_section_and_the_files_right():
    s = FakeStore()
    no_wf = MANIFEST.split("workflow:")[0]
    tid = make(s, files=kit(**{"migration.yaml": no_wf}))
    refused(lib(s).instantiate(agent(OTHER), tid, {"total_budget": "100"}), 409, "no_workflow")
    paid = make(s, slug="paid", pricing="purchase", price="5")
    refused(lib(s).instantiate(agent(OTHER), paid, {"total_budget": "100"}), 402, "payment_required")


def _workflow(*steps):
    lines = "".join(f"  - {{{st}}}\n" for st in steps)
    return kit(**{"migration.yaml": MANIFEST.split("workflow:")[0] + "workflow:\n" + lines})


def _budgets(s, wid):
    return [Decimal(str(x["budget"])) for x in s.workflows[wid]["steps"]]


def test_a_workflow_that_names_no_budget_shares_splits_the_budget_evenly():
    s = FakeStore()
    tid = make(s, files=_workflow("key: a, role: r1, acceptance: x", "key: b, role: r2, acceptance: y",
                                  "key: c, role: r3, acceptance: z"))
    out = run(lib(s).instantiate(agent(OTHER), tid, {"total_budget": "90"}))
    assert _budgets(s, out["workflow_id"]) == [Decimal("30"), Decimal("30"), Decimal("30")]


def test_named_shares_take_their_part_and_the_unnamed_steps_split_the_rest():
    s = FakeStore()
    tid = make(s, files=_workflow("key: a, role: r1, acceptance: x, budget_share: 50",
                                  "key: b, role: r2, acceptance: y", "key: c, role: r3, acceptance: z"))
    out = run(lib(s).instantiate(agent(OTHER), tid, {"total_budget": "100"}))
    assert _budgets(s, out["workflow_id"]) == [Decimal("50"), Decimal("25"), Decimal("25")]


@pytest.mark.parametrize("steps", [
    pytest.param(("key: a, role: r1, acceptance: x, budget_share: 70", "key: b, role: r2, acceptance: y, budget_share: 40"),
                 id="shares above 100"),
    pytest.param(("key: a, role: r1, acceptance: x, budget_share: 100", "key: b, role: r2, acceptance: y"),
                 id="nothing left for an unnamed step"),
    pytest.param(("key: a, role: r1, acceptance: x, budget_share: 0", "key: b, role: r2, acceptance: y, budget_share: 100"),
                 id="a share of zero"),
])
def test_a_step_left_without_budget_refuses_the_instantiate(steps):
    s = FakeStore()
    tid = make(s, files=_workflow(*steps))
    refused(lib(s).instantiate(agent(OTHER), tid, {"total_budget": "100"}), 409, "budget_share")
    assert not s.workflows


def _certificate(s, did, tid, *, content_hash=None, verdict="pass", att_id="att-1"):
    ch = content_hash or s.versions[s.templates[tid]["current_version_id"]]["content_hash"]
    data = {"claim": {"template": {"id": tid, "version": 1, "content_hash": ch},
                      "reports": {"reconcile": "r" * 64}, "verdict": verdict, "moved": 10, "rejected": 0,
                      "finished_at": "2026-11-14T13:00:00Z"}, "record": "run-1"}
    h = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    s.attestations.setdefault(did, []).append({"attestation_id": att_id, "attestation_type": "migration.certificate",
                                               "hash": h})
    return {"attestation_id": att_id, "attestation_data": data}


def test_a_certified_run_is_checked_against_the_agents_own_attestation_and_counted_once_per_agent():
    s = FakeStore()
    tid = make(s)
    body = _certificate(s, OTHER, tid)
    assert run(lib(s).certified(agent(OTHER), tid, body))["ok"] is True
    body2 = _certificate(s, OTHER, tid, att_id="att-2")
    assert run(lib(s).certified(agent(OTHER), tid, body2))["already"] is True
    assert run(lib(s).detail(None, tid))["counts"]["certified"] == 1


def test_a_certificate_that_does_not_hold_is_refused():
    s = FakeStore()
    tid, other_tid = make(s), make(s, slug="other")
    refused(lib(s).certified(agent(OTHER), tid, _certificate(s, BUYER, tid)), 409, "no_attestation")  # someone else's
    body = _certificate(s, OTHER, tid)
    body["attestation_data"]["claim"]["moved"] = 999                                               # not what was hashed
    refused(lib(s).certified(agent(OTHER), tid, body), 409, "hash")
    refused(lib(s).certified(agent(OTHER), tid, _certificate(s, OTHER, other_tid, att_id="a3")), 409, "other_template")
    refused(lib(s).certified(agent(OTHER), tid, _certificate(s, OTHER, tid, content_hash="0" * 64, att_id="a4")), 409,
            "other_template")
    refused(lib(s).certified(agent(OTHER), tid, _certificate(s, OTHER, tid, verdict="fail", att_id="a5")), 409,
            "not_pass")
    assert run(lib(s).detail(None, tid))["counts"]["certified"] == 0


# --- gwo_04e1334c (M8 step 4, session-tester seq 4090): a fork that names no slug gets one -----------------------------
# `tp-proxy migrate fork <tid>` posts an empty body; every CLI fork was refused 422 for a missing slug. The registry now
# derives one, so the CLI, the MCP tool and the console all fork without naming it.

def test_a_fork_with_an_empty_body_gets_the_parents_slug_and_fork_and_the_answer_names_it():
    s = FakeStore()
    parent = make(s, by=PARENT_AUTHOR, slug="crm-to-pg")
    out = run(lib(s).fork(agent(OWNER), parent, {}))
    assert out["slug"] == "crm-to-pg-fork"
    assert s.templates[out["template_id"]]["slug"] == "crm-to-pg-fork"


def test_the_same_agents_next_fork_gets_the_next_number_and_another_agent_starts_again():
    s = FakeStore()
    parent = make(s, by=PARENT_AUTHOR, slug="crm-to-pg")
    first = run(lib(s).fork(agent(OWNER), parent, {}))
    second = run(lib(s).fork(agent(OWNER), parent, {}))
    third = run(lib(s).fork(agent(OWNER), parent, {"slug": ""}))
    assert (first["slug"], second["slug"], third["slug"]) == ("crm-to-pg-fork", "crm-to-pg-fork-2", "crm-to-pg-fork-3")
    assert run(lib(s).fork(agent(BUYER), parent, {}))["slug"] == "crm-to-pg-fork"


def test_a_given_slug_is_kept_and_a_taken_one_is_409_as_before():
    s = FakeStore()
    parent = make(s, by=PARENT_AUTHOR, slug="crm-to-pg")
    assert run(lib(s).fork(agent(OWNER), parent, {"slug": "my-fork"}))["slug"] == "my-fork"
    refused(lib(s).fork(agent(OWNER), parent, {"slug": "my-fork"}), 409, "slug_taken")
    refused(lib(s).fork(agent(OWNER), parent, {"slug": "Not A Slug"}), 422, "slug")


def test_a_derived_slug_stays_within_the_slug_rule_for_a_parent_with_the_longest_slug():
    s = FakeStore()
    long_slug = "a" + "b" * 118                                     # 119 characters, the longest a slug may be
    parent = make(s, by=PARENT_AUTHOR, slug=long_slug)
    one = run(lib(s).fork(agent(OWNER), parent, {}))["slug"]
    two = run(lib(s).fork(agent(OWNER), parent, {}))["slug"]
    for got in (one, two):
        assert len(got) <= 119 and wt.SLUG_RE.match(got), got
    assert one.endswith("-fork") and two.endswith("-fork-2") and one != two

