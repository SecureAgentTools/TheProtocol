"""§SECFIX-7 (2026-09-25): under EVENTSTORE_MTLS_REQUIRED the internal key authenticates reads only.

The architecture audit of 2026-09-25 found the key accepted as "origin" for every method even when the store requires
mTLS: anything on the frame's networks holding it could append events or register a federation operator directly,
around the TLS terminators. Measured before the change on EU, ASIA and the sandbox pair: every write arrived through a
terminator (the sidecar, or the public vhost with an operator's certificate), which clears the key; nothing wrote with
the key alone. EVENTSTORE_INTERNAL_KEY_WRITES=allow is the break-glass.

Pure tests import src/es_auth.py alone; the wiring tests read the router's source.
RED on the pre-change tree: every test (the rule does not exist there).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import es_auth  # noqa: E402

EVENTS = ROOT / "src" / "routers" / "events.py"


def test_under_mtls_required_the_key_may_read_and_may_not_change():
    for m in ("GET", "HEAD", "OPTIONS", "get"):
        assert es_auth.internal_key_may_change(m, True, None)
    for m in ("POST", "PUT", "PATCH", "DELETE", "post", "", None):
        assert not es_auth.internal_key_may_change(m, True, None)


def test_without_mtls_required_the_key_keeps_its_old_reach():
    assert es_auth.internal_key_may_change("POST", False, None)


def test_the_break_glass_restores_it():
    assert es_auth.internal_key_may_change("POST", True, "allow")
    assert es_auth.internal_key_may_change("POST", True, " ALLOW ")
    assert not es_auth.internal_key_may_change("POST", True, "yes")  # only the documented word


def _function(name):
    for node in ast.walk(ast.parse(EVENTS.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def test_the_key_branch_asks_the_rule_before_it_grants_origin():
    fn = _function("verify_event_auth")
    src = ast.unparse(fn)
    key_at = src.index("internal_key_ok(x_internal_key)")
    rule_at = src.index("internal_key_may_change(request.method, MTLS_REQUIRED, INTERNAL_KEY_WRITES)")
    grant_at = src.index("{'auth_type': 'internal', 'operator': 'origin'}")
    assert key_at < rule_at < grant_at
    assert "request" in [a.arg for a in fn.args.args], "verify_event_auth must see the request's method"
