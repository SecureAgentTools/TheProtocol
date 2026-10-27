"""§ORPHANLIST (2026-09-10) — a deleted account must not keep offering services.

His report: *"on registry-a our state throwaway agents are still displayed at distiguished
agents … its from the our state throwaways. so maybe we should make them not list."*

MEASURED on frame-c before the fix: 35 `OSFE …` OurState E2E agents, 32 of them owned by
SOFT-DELETED developers, every card `is_active` and LISTED — and because each carries a
shadow_chancellor flare sidecar, filling registry-a's Distinguished Agents shelf ahead of every
real flare-bearer, on a mirror, on another frame.

THE PART THAT MAKES IT A ONE-WAY DOOR, and the reason an admin sweep had to exist:
  * `PATCH /agent-cards/{id}/listing` is OWNER-ONLY and admins deliberately get no bypass
    ("deciding whether someone else's agent is listed is the owner's call, not an operator's");
  * a soft-deleted developer has `hashed_password = "!deleted!"` and cannot sign in;
  * `POST /admin/developers/{id}/reinstate` refuses outright: "Cannot reinstate a deleted
    developer".
So once the owner was deleted there was NO path, for anyone, to take the card off the shelf.
Proven live: driving the owner's own rail unlisted the 3 cards whose owner was still alive and
answered 400 on all 32 whose owner was gone.

These are SOURCE assertions on purpose. Both behaviours live in admin handlers that need a
database, a developer row, a card row and an admin identity to exercise; what actually went
wrong is that one handler did not touch a table at all, and that is a question you can ask of the
code itself. The controls below fail against the pre-fix source.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/routers"


def _fn(path: str, name: str):
    tree = ast.parse((ROOT / path).read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)


def _assigned_attrs(fn):
    """Every `x.attr = ...` target inside the function."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute):
                    out.add(t.attr)
    return out


def test_deleting_a_developer_unlists_their_cards():
    """The defect: deletion revoked the API keys and left the CARDS advertising."""
    fn = _fn("admin_developers.py", "delete_developer")
    attrs = _assigned_attrs(fn)
    assert "unlisted" in attrs, (
        "soft-delete does not unlist the developer's agent cards — a deleted account keeps "
        "offering services and nobody can take the listing down"
    )


def test_the_unlisting_touches_updated_at_so_it_can_travel():
    """§LISTPROP's export walks `updated_at > cursor`. A silent column write never reaches the
    peers already holding a mirror, which is the whole population that was showing them."""
    fn = _fn("admin_developers.py", "delete_developer")
    assert "updated_at" in _assigned_attrs(fn), (
        "the unlisting does not move updated_at, so no peer would ever hear about it"
    )


def test_there_is_a_sweep_for_cards_orphaned_before_the_fix():
    fn = _fn("admin_agents.py", "sweep_orphaned_listings")
    attrs = _assigned_attrs(fn)
    assert {"unlisted", "updated_at"} <= attrs, f"sweep writes {attrs}"


def test_the_sweep_defaults_to_a_dry_run():
    """A bulk write that acts by default is a foot-gun; the caller has to ask for it."""
    tree = ast.parse((ROOT / "admin_agents.py").read_text())
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "OrphanedListingSweepIn")
    dry = next(n for n in cls.body
               if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", None) == "dry_run")
    assert isinstance(dry.value, ast.Call) and dry.value.args[0].value is True, \
        "dry_run must default to True"


# ── controls: these describe what must NOT change ────────────────────────────────────
def test_the_card_is_unlisted_not_deactivated():
    """CONTROL. A counterparty holding a past receipt must still be able to fetch the card by
    DID and read who they dealt with. Hiding it from discovery is the whole ask; deleting its
    readability is not.

    ⚠ THE FIRST CUT OF THIS CONTROL FAILED IN BOTH DIRECTIONS, which makes it not a control.
    It grepped the unparsed handler for `is_active = False` — and `delete_developer` legitimately
    contains exactly that, for the developer's API KEYS. A control that fires for the wrong
    reason proves nothing about the thing it is guarding. So look at the LOOP that walks the
    cards and assert on what THAT body writes.
    """
    for path, name in (("admin_developers.py", "delete_developer"),
                       ("admin_agents.py", "sweep_orphaned_listings")):
        fn = _fn(path, name)
        card_loops = [n for n in ast.walk(fn)
                      if isinstance(n, ast.For) and getattr(n.target, "id", None) == "card"
                      or (isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
                          and any(getattr(e, "id", None) == "card" for e in n.target.elts))]
        assert card_loops, f"{name} has no loop over cards"
        written = set()
        for loop in card_loops:
            for node in ast.walk(loop):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Attribute) and getattr(t.value, "id", None) == "card":
                            written.add(t.attr)
        assert written == {"unlisted", "updated_at"}, (
            f"{name} writes {sorted(written)} on each card; it must only unlist and touch the clock"
        )


def test_the_owner_rail_still_refuses_an_operator():
    """CONTROL. The sweep exists BECAUSE the owner-only rule is right. It must stay: a listing
    decision for a LIVE owner is still theirs, and nothing here may add an admin bypass."""
    src = (ROOT / "agent_cards.py").read_text()
    fn = _fn("agent_cards.py", "set_agent_card_listing")
    body = ast.unparse(fn)
    assert "developer_id != current_developer.id" in body, \
        "the owner-only check on the listing rail is gone"
    assert "Admins deliberately do NOT get a bypass" in src, \
        "the reasoning for the owner-only rule was removed from the source"
