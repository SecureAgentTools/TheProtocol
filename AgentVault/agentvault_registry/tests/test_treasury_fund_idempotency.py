"""§MONEY-R36 — every treasury-funding caller has decided about exactly-once.

R36 named ONE unkeyed caller (the forge verifier pay). The parameter is optional,
so the real question was how many callers omit it: seven did. Reading them split
cleanly into two kinds, and the split is the rule this gate enforces.

  DETERMINISTIC reference  -> the same logical payment can be attempted twice
                              (a quorum re-run, a retried approve, a re-run
                              suite). It MUST carry an idempotency_key.

  DELIBERATELY UNIQUE ref  -> a keeper topping a float up to a watermark. A
                              retry SHOULD move money again, because the balance
                              is still low. Keying it to a constant would freeze
                              the keeper at its first top-up — the R28 lesson:
                              a prescribed fix can open a worse hole than the
                              defect, so walk what the remedy touches.

  Keyed one layer up       -> the admin route wraps its own idempotency_lookup /
                              idempotency_store around the call.

An EIGHTH caller must therefore land in one of these lists deliberately. That is
the whole point: this gate fails on a new unkeyed call site, not on the six that
were reasoned about.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():                      # CI/image layout
    SRC = pathlib.Path("/w/src/agentvault_registry")
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/agentvault_registry")

FUNC = "_fund_agent_from_treasury_internal"

# Callers that must NOT pass a key, with the reason. A keeper's job is to react
# to the balance it finds now.
KEEPERS = {
    "background_tasks/canary_rebalancer.py": "top-up to a floor; ref carries ts+token_hex per call",
    "background_tasks/gateway_float_keeper.py": "top-up to a watermark; ref is a fresh uuid4 per call",
    "background_tasks/fx_router_keeper.py": "top-up to a target; no ref, by design",
}
# Callers keyed by an enclosing idempotency layer rather than this argument.
KEYED_ELSEWHERE = {
    "routers/teg_integration.py": "the admin route wraps idempotency_lookup/store on the header key",
}


def _call_sites():
    """Every call to FUNC, as (relative path, line, passes_key)."""
    out = []
    for p in sorted(SRC.rglob("*.py")):
        if ".bak" in p.name:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name != FUNC:
                continue
            has_key = any(k.arg == "idempotency_key" for k in node.keywords)
            out.append((str(p.relative_to(SRC)), node.lineno, has_key))
    return out


@pytest.fixture(scope="module")
def sites():
    found = _call_sites()
    assert found, (
        f"no call sites for {FUNC} found under {SRC} — this gate would pass by "
        "not looking. Fix the path before trusting it."
    )
    return found


def test_every_caller_is_keyed_or_deliberately_exempt(sites):
    unaccounted = [
        f"{rel}:{line}" for rel, line, has_key in sites
        if not has_key and rel not in KEEPERS and rel not in KEYED_ELSEWHERE
    ]
    assert not unaccounted, (
        "these treasury-funding call sites pass no idempotency_key and are on "
        "neither exemption list — a retry there pays twice. Either key them, or "
        f"add them to KEEPERS with the reason a key would be wrong: {unaccounted}"
    )


@pytest.mark.parametrize("rel", sorted(KEEPERS))
def test_a_keeper_stays_unkeyed(sites, rel):
    """The exemptions are load-bearing: keying a keeper freezes it."""
    mine = [s for s in sites if s[0] == rel]
    assert mine, f"{rel} no longer calls {FUNC} — drop it from KEEPERS"
    assert all(not has_key for _, _, has_key in mine), (
        f"{rel} now passes an idempotency_key. {KEEPERS[rel]} — a key makes the "
        "second top-up a no-op and the float never recovers. If this is "
        "deliberate, move it out of KEEPERS and say why."
    )


def test_the_three_deterministic_callers_are_keyed(sites):
    must = {
        "services/forge_verify.py",        # R36 as filed
        "background_tasks/eval_runner.py",  # the same class, royalty legs
        "routers/funding_requests.py",      # the same class, approve
    }
    for rel in must:
        mine = [s for s in sites if s[0] == rel]
        assert mine, f"{rel} no longer calls {FUNC}"
        assert all(has_key for _, _, has_key in mine), \
            f"{rel} calls {FUNC} without an idempotency_key — a replay pays twice"


def test_the_pay_amount_is_not_a_float():
    """§MONEY-R15's class: a float() on the way to a transfer amount."""
    src = (SRC / "services" / "forge_verify.py").read_text(encoding="utf-8")
    assert 'float(os.getenv("FORGE_VERIFIER_PAY"' not in src, \
        "FORGE_VERIFIER_PAY goes through float() again — use Decimal"
