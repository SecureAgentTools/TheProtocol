"""§FRAMELIC (2026-09-07, findings row 151) — A REFUSED CREATE MUST NOT MINT AN IDENTITY.

MEASURED live on the EU frame before the fix: `POST /api/v1/onboard/create_agent` with a card
that fails AgentCard validation answered **400 "Invalid agent card"** — and the developer's agent
count went **22 → 23**. The refused caller was told nothing was created while the frame had
minted a DID, client credentials, a wallet and IRONKEY birth roles, with no card attached. Eleven
such agents already existed on EU from one failed pass of the showcase re-onboarding; every
card-based rail (discovery, health, pull-sync, the showcase) is blind to them, so they read as
absent while holding an identity.

The cause is a rollback that rolls back nothing. `routers/onboarding.py` does:

    created_agent = await create_agent_db(...)      # crud/agent.py — COMMITTED here
    try:
        agent_card = await card_crud.create_agent_card(...)
    except ValueError:
        await db.rollback()                         # ← undoes nothing; the agent is committed
        raise HTTPException(400, "Invalid agent card: ...")

Same family as §29e: the handler LOOKS like it compensates, so nobody re-reads it. The fix is a
transaction switch on the callee rather than a second write at the call site — `commit=False`
flushes instead, the agent row stays inside the caller's transaction, and the rollback that was
always written there becomes true.

Two callers deliberately keep a cardless agent and MUST NOT change: `/agents/spawn` (the child's
authority rides its birth token, the card is explicitly non-fatal) and the fiat wallet flow (the
buyer paid — an agent with no card beats no agent). They pass nothing, so `commit=True` keeps
them byte-identical. That is the control leg below: the default still commits.
"""
import ast
import asyncio
import pathlib
import sys

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

CRUD = SRC_ROOT / "agentvault_registry" / "crud" / "agent.py"
ONBOARDING = SRC_ROOT / "agentvault_registry" / "routers" / "onboarding.py"


class _FakeSession:
    """Records the transaction verbs in order. Nothing else about it matters."""

    def __init__(self):
        self.calls = []

    def add(self, obj):
        self.calls.append("add")

    async def commit(self):
        self.calls.append("commit")

    async def flush(self):
        self.calls.append("flush")

    async def refresh(self, obj):
        self.calls.append("refresh")


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _create(commit=None):
    from agentvault_registry.crud.agent import create_agent

    db = _FakeSession()
    kwargs = dict(db=db, did="did:theprotocol:test:1", client_id="agent-test",
                  client_secret="s3cret-not-a-real-credential", creator_developer_id=1)
    if commit is not None:
        kwargs["commit"] = commit
    _run(create_agent(**kwargs))
    return db.calls


def test_commit_false_flushes_and_does_not_commit():
    """The row stays in the caller's transaction, so the caller's rollback can undo it."""
    calls = _create(commit=False)
    assert "flush" in calls, calls
    assert "commit" not in calls, f"create_agent(commit=False) still committed: {calls}"


def test_default_still_commits():
    """CONTROL — spawn and the fiat wallet flow pass nothing and must be unchanged."""
    calls = _create()
    assert "commit" in calls, calls
    assert "flush" not in calls, calls


def test_onboarding_creates_the_agent_inside_its_own_transaction():
    """The call site that answers 400 must own the row it may have to undo.

    Read off the AST rather than the text: a comment naming commit=False is not the keyword,
    and this is exactly the shape a grep window gets wrong.
    """
    tree = ast.parse(ONBOARDING.read_text())
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "create_agent_db"]
    assert hits, "create_agent_db call not found in onboarding.py"
    for call in hits:
        kw = {k.arg: k.value for k in call.keywords}
        assert "commit" in kw, "onboarding must state its transaction intent explicitly"
        assert isinstance(kw["commit"], ast.Constant) and kw["commit"].value is False, (
            "onboarding must pass commit=False, or its rollback undoes nothing")


def test_the_rollback_it_relies_on_is_still_there():
    """If the compensating rollback is ever deleted, commit=False alone leaks an open row."""
    tree = ast.parse(ONBOARDING.read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Try) and node.handlers):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "create_agent_card" not in body:
            continue
        for h in node.handlers:
            dumped = ast.dump(ast.Module(body=h.body, type_ignores=[]))
            assert "rollback" in dumped, (
                "the create_agent_card handler must roll back — it is what undoes the agent row")
        return
    raise AssertionError("no try/except around create_agent_card in onboarding.py")


def test_callee_documents_why_the_switch_exists():
    """A switch with no reason gets 'simplified' away by the next reader."""
    src = CRUD.read_text()
    assert "commit: bool = True" in src
    assert "row 151" in src, "the finding that earned the parameter must be named at the callee"


# ── §FRAMELIC row 156 ────────────────────────────────────────────────────────────────────
# The three legs above drove `crud.agent.create_agent`. The onboard rail does NOT call that
# name: `routers/onboarding.py` imports `create_agent` from `crud_agent_enhanced`, where it is
# an ALIAS for `enhanced_create_agent` (`create_agent = enhanced_create_agent`, bottom of file),
# and only falls back to the crud function on ImportError. So the parameter landed on the callee
# and not on the wrapper the router reaches, and the first real use answered
# `TypeError: enhanced_create_agent() got an unexpected keyword argument 'commit'` — a 500 that
# took a live standup down at its canary-seeding step.
#
# I had grepped `def create_agent` in that module, got nothing, and concluded the fallback was
# what ran. The export is an assignment, not a def. **A gate that drives a different function
# from the one the caller imports is the §DISCECHO shape** — green while the shipped path is
# broken. These legs drive the name the ROUTER imports.

def _import_name_used_by_onboarding():
    """Resolve `create_agent` exactly as routers/onboarding.py does."""
    try:
        from agentvault_registry.crud_agent_enhanced import create_agent
        return create_agent
    except ImportError:                                    # pragma: no cover - matches the router
        from agentvault_registry.crud.agent import create_agent
        return create_agent


def test_the_name_onboarding_imports_accepts_commit():
    import inspect

    fn = _import_name_used_by_onboarding()
    sig = inspect.signature(fn)
    assert "commit" in sig.parameters, (
        f"{fn.__name__} does not accept commit — onboarding's call site raises TypeError")
    assert sig.parameters["commit"].default is True, (
        "the default must stay True so every other caller is unchanged")


def test_the_wrapper_forwards_commit_rather_than_swallowing_it():
    """Accepting the argument and dropping it would be worse than the TypeError:
    the standup would pass and the agent row would be committed again, silently."""
    import asyncio

    from agentvault_registry import crud_agent_enhanced as mod

    seen = {}

    async def _spy(**kw):
        seen.update(kw)
        return type("A", (), {"did": kw["did"]})()

    real = mod._original_create_agent
    mod._original_create_agent = _spy
    try:
        _run(mod.enhanced_create_agent(
            db=None, did="did:theprotocol:test:1", client_id="c", client_secret="s",
            creator_developer_id=1, commit=False))
    finally:
        mod._original_create_agent = real
    assert seen.get("commit") is False, f"commit was not forwarded: {seen}"

