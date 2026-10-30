"""§MONEY-R35 — creating a TEG account must not be a way to create money.

Three admin-key rails accepted an OPENING BALANCE and wrote `token_balance` /
`audited_balance` straight to the row: no mint event, no `teg.entry_type`, no
idempotency, no Commander. The supply invariant cannot see it — an untagged
balance write books as transit (§MONEY-R18) — so the money would simply be
there, and Δ would read 0.0 the whole time.

Both real callers (the registry's two `initialize-teg-account` sites) already
pass "0", and nothing anywhere calls either bulk rail. The capability was a door
left open behind a shared key.

⚠ The refusal is NOT a retirement. Unmounting these rails is decision D8 and the
Commander's; a refusal is reversible and a deletion is a release decision.
"""
from decimal import Decimal

import pytest

from teg_core_service.core.error_handling import TEGException
from teg_core_service.core.supply_guard import refuse_nonzero_opening_balance


# ── zero, in every shape a caller sends it ──────────────────────────────────

@pytest.mark.parametrize("v", ["0", "0.0", "0.000000000000000000", 0, 0.0,
                               Decimal("0"), None, "", "  0  "])
def test_zero_is_accepted(v):
    assert refuse_nonzero_opening_balance(v, rail="t") == Decimal("0")


# ── anything else is refused ────────────────────────────────────────────────

@pytest.mark.parametrize("v", ["1", "0.000000000000000001", "1000000", "-5",
                               Decimal("0.5"), 42])
def test_a_non_zero_opening_balance_is_refused(v):
    with pytest.raises(TEGException) as ei:
        refuse_nonzero_opening_balance(v, rail="agent/initialize-teg-account")
    assert ei.value.status_code == 400
    # `detail=` is stored as detail_info and serialised by teg_exception_handler
    # into ErrorDetail.detail — that is what a caller actually reads.
    assert "treasury funding rail" in str(ei.value.detail_info), \
        "the refusal must say where to go instead, or it just looks broken"


def test_dust_is_refused_too():
    """One unit of the 18th decimal is still supply from nowhere."""
    with pytest.raises(TEGException):
        refuse_nonzero_opening_balance("0.000000000000000001", rail="t")


def test_an_unparseable_value_is_refused_not_treated_as_zero():
    """'abc' is not zero. Silently reading it as zero would hide a caller that
    believes it is funding an account."""
    with pytest.raises(TEGException) as ei:
        refuse_nonzero_opening_balance("abc", rail="t")
    assert ei.value.status_code == 400


def test_the_rail_name_reaches_the_error():
    with pytest.raises(TEGException) as ei:
        refuse_nonzero_opening_balance("1", rail="admin/agents/bulk-initialize")
    assert "admin/agents/bulk-initialize" in str(ei.value.metadata)


# ── the guard is actually WIRED, not merely written ─────────────────────────
# A helper nobody calls is the most comfortable kind of dead code.

import pathlib  # noqa: E402

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "teg_core_service"
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/teg_core_service")


@pytest.mark.parametrize("rel,fn", [
    ("api/v1/endpoints_agent.py", "initialize_teg_account"),
    ("api/v1/endpoints_agent.py", "bulk_initialize_agents"),
    ("api/v1/endpoints_admin.py", "bulk_initialize_agents"),
])
def test_every_opening_balance_rail_calls_the_guard(rel, fn):
    import ast
    src = (SRC / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn),
        None,
    )
    assert target is not None, f"{rel}: {fn} is gone — re-point this gate"
    calls = [
        n for n in ast.walk(target)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
        == "refuse_nonzero_opening_balance"
    ]
    assert calls, f"{rel}:{fn} no longer calls refuse_nonzero_opening_balance"


def test_bulk_initialize_no_longer_overwrites_an_existing_balance():
    """It used to assign token_balance UNCONDITIONALLY, so calling it on an
    agent that held money OVERWROTE it — a destruction path, not only a
    creation one. Its sibling in endpoints_admin.py always had the guard."""
    import ast
    src = (SRC / "api/v1/endpoints_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "bulk_initialize_agents")
    assigns = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "attr", None) == "token_balance" for t in n.targets)
    ]
    assert assigns, "no token_balance assignment found — re-point this gate"
    guarded = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            guarded.extend(
                n for n in ast.walk(node)
                if isinstance(n, ast.Assign)
                and any(getattr(t, "attr", None) == "token_balance" for t in n.targets)
            )
    assert len(guarded) == len(assigns), (
        "a token_balance assignment in bulk_initialize_agents is outside an if — "
        "an unconditional write there overwrites a real balance"
    )


# ── the kwargs-to-a-stdlib-logger class ─────────────────────────────────────
# Found while proving R35 live: the ZERO path (the one every real caller uses)
# answered 400 too, and not because of the guard. `get_logger()` returns a plain
# logging.Logger; three calls in initialize_teg_account passed structured fields
# as KEYWORDS, which raises TypeError, which the function's own
# `except Exception` turned into 400 "Failed to initialize TEG account". It fired
# BEFORE db.commit(), so a first-time initialisation created nothing and said so
# only as a generic error. An AST census found exactly three, all in that one
# function — bounded, and now zero.

def test_no_logger_call_passes_kwargs_a_stdlib_logger_cannot_take():
    """Parse, never grep: a regex cannot tell a logger call from a lookalike."""
    import ast
    ok = {"exc_info", "extra", "stack_info", "stacklevel"}
    levels = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
    offenders, scanned = [], 0
    for p in SRC.rglob("*.py"):
        if ".bak" in p.name:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        scanned += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr not in levels:
                continue
            name = getattr(fn.value, "id", None) or getattr(fn.value, "attr", None) or ""
            if "logger" not in str(name).lower():
                continue
            bad = [k.arg for k in node.keywords if k.arg and k.arg not in ok]
            if bad:
                offenders.append(f"{p.relative_to(SRC)}:{node.lineno} logger.{fn.attr}({', '.join(bad)}=)")
    assert scanned > 50, (
        f"only {scanned} files scanned from {SRC} — this gate would pass by not looking"
    )
    assert not offenders, (
        "these calls pass keywords to a stdlib logging.Logger and raise TypeError "
        f"the moment they run: {offenders}"
    )
