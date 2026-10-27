"""§MCPTEST30 (V0549) — the rule that reads a header a handler checks itself (tests/mcp_handler_headers.py).

The request survey uses it to see a route that refuses a request without a header no signature declares
(getCloudOperatorSelfLogs, cloudOperatorSelfRestart and federationCliAudit send none and answer 401 or 400 to every MCP
caller). The rule must report a header only where its absence certainly ends in a 400, 401 or 403: a header read
optionally, behind a branch, after a possible return, or compared with a value the source cannot know is never reported.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mcp_handler_headers as H  # noqa: E402  (pure ast: importing it patches nothing)


def _found(src: str):
    return H.required_headers_in(ast.parse(src).body[0])


def test_a_header_read_then_refused_when_absent_is_required():
    assert _found('''
async def h(request, body):
    if body.service not in ALLOWED:
        raise HTTPException(status_code=400, detail="service")
    license_key = request.headers.get("X-Federation-License")
    if not license_key:
        raise HTTPException(status_code=401, detail="X-Federation-License header required")
    return {"ok": True}
''') == [("X-Federation-License", 401)]


def test_an_optional_header_parameter_checked_in_the_body_is_required_by_its_alias_or_name():
    assert _found('''
async def h(body, x_federation_license: Optional[str] = Header(None, alias="X-Federation-License")):
    if not _enabled():
        raise HTTPException(status_code=503, detail="off")
    if not x_federation_license:
        raise HTTPException(status_code=400, detail="X-Federation-License header required")
    return {}
''') == [("X-Federation-License", 400)]
    assert _found('''
def h(x_phase_six: str = Header(default=None)):
    if x_phase_six is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no")
    return 1
''') == [("x-phase-six", 403)]


def test_an_inline_read_and_a_short_circuit_are_read_with_python_semantics():
    assert _found('''
def h(request):
    if not request.headers.get("X-Internal-Key") or other():
        raise HTTPException(status_code=401)
    return 1
''') == [("X-Internal-Key", 401)]


def test_what_is_not_certainly_a_refusal_is_never_reported():
    # a header the handler accepts when PRESENT (and falls through without)
    assert _found('''
def h(request):
    s = request.headers.get("X-Federation-Secret")
    if s and other:
        raise HTTPException(status_code=401)
    return 1
''') == []
    # a comparison with a value the source cannot know (the reset secret from the environment)
    assert _found('''
def h(request):
    expected = os.environ.get("SANDBOX_RESET_SECRET", "")
    provided = request.headers.get("X-Reset-Secret", "")
    if not expected or provided != expected:
        raise HTTPException(status_code=403)
    return 1
''') == []
    # a check after a statement that can return: the route may answer without the header
    assert _found('''
def h(request):
    if cheap():
        return {"cached": True}
    k = request.headers.get("X-Federation-License")
    if not k:
        raise HTTPException(status_code=401)
    return 1
''') == []
    # a check nested inside a branch, a status that is not a refusal, a required Header(...) (FastAPI's own 422)
    assert _found('''
def h(request, mode):
    if mode:
        k = request.headers.get("X-Federation-License")
        if not k:
            raise HTTPException(status_code=401)
    k2 = request.headers.get("X-Other")
    if not k2:
        raise HTTPException(status_code=503)
    return 1
''') == []
    assert _found('''
def h(stripe_signature: str = Header(..., alias="Stripe-Signature")):
    if not stripe_signature:
        raise HTTPException(status_code=400)
    return 1
''') == []


def test_a_function_without_source_reports_nothing():
    assert H.function_required_headers(len) == []
    assert H.function_required_headers(object()) == []


def test_the_routes_it_finds_in_the_registry_today():
    """The four routes on 2026-10-02 (1,437 served): two own-licence routes, the CLI audit entry and the licence
    rotation, all a federation licence. Read from the real handlers, not copies."""
    from agentvault_registry.routers import cloud_operators, federation_cli_audit, federation_license_self
    assert H.function_required_headers(cloud_operators.cloud_operator_self_logs) == [("X-Federation-License", 401)]
    assert H.function_required_headers(cloud_operators.cloud_operator_self_restart) == [("X-Federation-License", 401)]
    assert H.function_required_headers(federation_cli_audit.receive_cli_audit) == [("X-Federation-License", 400)]
    assert H.function_required_headers(federation_license_self.rotate_self) == [("X-Federation-License", 400)]
    # the sync trigger reads the internal secret only to ACCEPT a caller (an admin developer may call it): not required
    from agentvault_registry.routers import federation_sync
    assert H.function_required_headers(federation_sync.require_sync_trigger_identity) == []



# ── §MCPTEST30 (V0550): the keys a handler reads from an untyped dict body ──────────────────────────────────────────
def _reads(src: str, name: str = "body"):
    return H._body_param_reads(ast.parse(src).body[0], name)


def test_constant_key_reads_of_an_untyped_body_are_named():
    assert _reads('''
async def h(body):
    m = body.get("method", "GET")
    p = body["path"]
    if "isFormData" in body:
        pass
    x = body.pop("extra", None)
    return m, p, x
''') == {"method", "path", "isFormData", "extra"}


def test_any_other_use_of_the_body_makes_the_set_unknowable():
    for src in ('''
def h(body):
    return forward(body)
''', '''
def h(body):
    for k in body:
        pass
''', '''
def h(body):
    alias = body
    return alias.get("x")
''', '''
def h(body, key):
    return body.get(key)
''', '''
def h(body):
    return {**body}
'''):
        assert _reads(src) is None, src


def test_the_handlers_it_found_in_the_registry():
    from agentvault_registry.routers import admin_api_test, admin_tutorial
    reads = H.handler_body_reads(admin_api_test.test_endpoint, "endpoint_test")
    assert reads is not None and "path" in reads and "endpoint_path" not in reads
    assert H.handler_body_reads(admin_tutorial.generate_zkp_proof, "request") == {"circuit_id", "agent_did"}
    assert H.handler_body_reads(admin_tutorial.generate_zkp_proof, "no_such_param") is None
