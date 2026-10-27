"""§EMITDIAG 2026-09-07 — the emission poller must name the store it read and why
it could not read it.

HIS REPORT: "EventStore emission ES query unavailable for A2APaymentAuthorized,
i think this is emitted. i am sure."  He was right: 1,228 A2APaymentAuthorized
rows sat in sbx-alpha's EventStore while the EU console — which drives the sweep
against sbx-alpha — polled `event-store-test`, a hostname retired with the old
sandbox tier.  Every poll raised gaierror, `except Exception: continue` swallowed
it, and 93 event-types read 'unknown' with one undifferentiated word: unavailable.

Two defects, one class (a fact computed in two places):
  (1) the EventStore to poll is a property of the TARGET, and it was a literal
      default belonging to a tier that no longer exists;
  (2) a probe that cannot read its source must say WHY — a wrong hostname, a
      403, a timeout and an empty store are four different findings with four
      different fixes, and they all printed the same sentence.

Every test here carries its control: one case that must be GREEN (the property
holds) and one that must be RED (the property is absent), because a gate that
can only pass measures nothing.
"""
import importlib
import os

import pytest


def _mod(monkeypatch, target=None, es_url=None):
    """Import mcp_tester with a chosen target/ES env.

    `_EMIT_ES_URL` is resolved at IMPORT, so the env must be set before the reload
    — a test that mutates os.environ against an already-imported module measures
    nothing.  The module also registers Prometheus gauges at import, and a reload
    re-registers them into a process-wide registry, so drop this module's
    collectors first; without that every test here fails on Duplicated timeseries
    and reports a defect that is purely the harness."""
    if target is None:
        monkeypatch.delenv("API_TEST_TARGET_URL", raising=False)
    else:
        monkeypatch.setenv("API_TEST_TARGET_URL", target)
    if es_url is None:
        monkeypatch.delenv("API_TEST_EVENT_STORE_URL", raising=False)
    else:
        monkeypatch.setenv("API_TEST_EVENT_STORE_URL", es_url)
    import agentvault_registry.routers.mcp_tester as m
    try:
        from prometheus_client import REGISTRY
        for _c in list(getattr(REGISTRY, "_collector_to_names", {})):
            if getattr(_c, "_name", "").startswith("mcp_tester"):
                REGISTRY.unregister(_c)
    except Exception:
        pass
    return importlib.reload(m)


# ── 1. the EventStore follows the TARGET ────────────────────────────────────
@pytest.mark.parametrize("target,expect", [
    # the case that was broken: a console driving another frame
    ("http://sbx-alpha-registry:8000", "http://sbx-alpha-event-store:8200"),
    ("http://eu-registry:8000",        "http://eu-event-store:8200"),
    # the legacy pairing the old literal default encoded — preserved, so this fix
    # is not a regression anywhere the literal happened to be right
    ("http://registry-test:8000",      "http://event-store-test:8200"),
    ("http://registry-test-b:8000",    "http://event-store-test-b:8200"),
    ("https://registry-test-c:8443",   "http://event-store-test-c:8200"),
])
def test_es_url_derives_from_target(monkeypatch, target, expect):
    m = _mod(monkeypatch, target=target)
    assert m._derive_es_url_from_target(target) == expect
    assert m._EMIT_ES_URL == expect


@pytest.mark.parametrize("target", [
    "http://localhost:8000",      # the code's own default target — names no frame
    "http://172.17.0.1:8150",     # an IP: nothing to derive a store name from
    "",
    None,
])
def test_undecidable_target_yields_empty_not_a_guess(monkeypatch, target):
    """CONTROL. An empty URL is honest; a guessed one is the defect wearing a fix's
    costume. This must NOT quietly become the retired hostname again."""
    m = _mod(monkeypatch, target=target if target is not None else "")
    assert m._derive_es_url_from_target(target or "") == ""


def test_explicit_env_beats_the_derivation(monkeypatch):
    """An operator's word outranks our rule — the derivation fills a gap, it does
    not overrule a configured store."""
    m = _mod(monkeypatch, target="http://sbx-alpha-registry:8000",
             es_url="http://somewhere-else:9999/")
    assert m._EMIT_ES_URL == "http://somewhere-else:9999"   # and rstrip("/") still applies


def test_retired_hostname_is_no_longer_a_literal_default(monkeypatch):
    """CONTROL on the excision itself: prove the dead default is GONE, not merely
    that a derivation exists beside it. `event-store-test` may appear only as the
    derived answer for the `registry-test` target."""
    m = _mod(monkeypatch, target="http://localhost:8000")
    assert m._EMIT_ES_URL == "", (
        "an undecidable target must leave the store UNSET, not fall back to a "
        f"hostname from a torn-down tier (got {m._EMIT_ES_URL!r})")


# ── 2. an unreadable poll names its cause ───────────────────────────────────
@pytest.mark.anyio
async def test_unconfigured_store_names_itself_once(monkeypatch):
    m = _mod(monkeypatch, target="http://localhost:8000")
    diag = {}
    out = await m._collect_emissions("2026-09-07T00:00:00Z", set(), diag=diag)
    assert out == {}
    assert "no EventStore configured" in diag["__cause__"]
    assert "http://localhost:8000" in diag["__cause__"], "the cause must name the TARGET it could not resolve a store for"
    # and every type carries a reason, so no row can print a bare 'unavailable'
    assert diag["A2APaymentAuthorized"] == "no EventStore configured"


@pytest.mark.anyio
async def test_dead_hostname_is_reported_as_a_named_failure(monkeypatch):
    """The exact shape of his report: a store that does not resolve. The poll must
    come back with the exception NAMED, not with silence."""
    m = _mod(monkeypatch, target="http://sbx-alpha-registry:8000",
             es_url="http://host.invalid.example:8200")
    diag = {}
    out = await m._collect_emissions("2026-09-07T00:00:00Z", set(),
                                     expect_types=["A2APaymentAuthorized"], diag=diag)
    assert out == {}
    reason = diag.get("A2APaymentAuthorized", "")
    assert reason, "an unreadable event-type must record WHY, not vanish into 'unknown'"
    assert "Error" in reason or "error" in reason or ":" in reason
    assert diag["__url__"] == "http://host.invalid.example:8200", "the store that was actually read must be named"


def test_first_emit_reason_reports_the_modal_cause(monkeypatch):
    m = _mod(monkeypatch, target="http://sbx-alpha-registry:8000")
    # GREEN: one cause shared by many types is ONE finding, counted
    r = m._first_emit_reason({"__url__": "x", "A": "HTTP 403 from es", "B": "HTTP 403 from es", "C": "boom"})
    assert r.startswith("HTTP 403 from es") and "2 event-type(s)" in r
    # a single reason is stated bare
    assert m._first_emit_reason({"A": "HTTP 403 from es"}) == "HTTP 403 from es"
    # CONTROL: no reasons (a healthy poll) must produce NO sentence — a verdict
    # that always has something to say is not a verdict
    assert m._first_emit_reason({}) == ""
    assert m._first_emit_reason({"__url__": "x", "__cause__": "y"}) == ""
    assert m._first_emit_reason(None) == ""


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── 3. §EMITDIAG-4: the three siblings of the same rot ──────────────────────
def test_no_retired_tier_hostname_survives_as_a_default(monkeypatch):
    """CONTROL on the whole class. Fixing the A-side store left THREE literals from
    the torn-down tier — the peer store and the two ES mTLS gateways — and the first
    EU-driven run reported all three as things being *unreachable*, which is a claim
    about the network that was false: no address had ever been configured.

    `event-store-test` may survive ONLY as the derived answer for a `registry-test`
    target. It may not be a default anywhere."""
    m = _mod(monkeypatch, target="http://sbx-alpha-registry:8000")
    assert m._EMIT_ES_B_URL == "", (
        f"the peer EventStore still defaults to a retired hostname ({m._EMIT_ES_B_URL!r})")
    assert m._ES_MTLS_GW_A == "" and m._ES_MTLS_GW_B == "", (
        "the ES mTLS gateways still default to `nginx-event-store-test*`, which no "
        "container on the current sandbox tier answers — the check has been probing a "
        f"host that cannot exist (A={m._ES_MTLS_GW_A!r} B={m._ES_MTLS_GW_B!r})")


def test_configured_peer_store_is_still_honoured(monkeypatch):
    """GREEN half: removing a bad default must not remove the ability to configure it —
    a gate that only proves an absence can be satisfied by deleting the feature."""
    monkeypatch.setenv("API_TEST_EVENT_STORE_B_URL", "http://sbx-beta-event-store:8200/")
    monkeypatch.setenv("API_TEST_ES_MTLS_GATEWAY_A", "https://gw-a:8443")
    m = _mod(monkeypatch, target="http://sbx-alpha-registry:8000")
    assert m._EMIT_ES_B_URL == "http://sbx-beta-event-store:8200"   # rstrip("/") intact
    assert m._ES_MTLS_GW_A == "https://gw-a:8443"


def test_no_retired_hostname_is_an_env_default_anywhere_in_the_module():
    """§EMITDIAG-4b — THE PROPERTY, NOT A COUNT.

    The build gate printed "expect <=6 occurrences of event-store-test" and the
    image answered 13, because I had widened the grep. A printed number is not a
    gate; checking what the number was supposed to STAND FOR found a FOURTH site of
    the same rot (`EVENT_STORE_B_INTERNAL_URL`, feeding the SSE proxy's B stream).

    So assert the property directly: no `os.getenv(..., "<retired host>")` default
    may survive. Comments and the one legacy derivation are free to mention the name
    — that is what a count could never distinguish."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "routers" / "mcp_tester.py").read_text()
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv"):
            continue
        if len(node.args) < 2:
            continue
        default = node.args[1]
        if isinstance(default, ast.Constant) and isinstance(default.value, str):
            if "event-store-test" in default.value or "registry-test" in default.value:
                offenders.append((node.lineno, default.value))
    assert not offenders, (
        "a hostname from the torn-down sandbox tier is still an env DEFAULT: "
        f"{offenders} — that is how 93 event-types read 'unavailable' about a store "
        "nobody asked for")


# ── 4. §PEERVANTAGE: ask the vantage point that can see the peer ─────────────
def test_the_relay_takes_no_address(monkeypatch):
    """The security property, asserted structurally rather than by reading the prose.

    A relay that fetches a URL the CALLER supplies is an SSRF surface in a
    test-harness costume. This one reads only the peer store the node is already
    configured with, so the endpoint must never take a url/base/target parameter."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "routers" / "mcp_tester.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == "peer_es_facts"), None)
    assert fn is not None, "peer_es_facts not found — re-point this gate"
    args = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert args == ["request"], f"the relay must take only `request`, got {args}"
    body = ast.unparse(fn)
    for banned in ("query_params.get('url'", 'query_params.get("url"',
                   "query_params.get('store'", 'query_params.get("store"',
                   "query_params.get('base'", 'query_params.get("base"'):
        assert banned not in body, f"the relay reads a caller-supplied address: {banned}"
    assert "_EMIT_ES_B_URL" in body, "the relay must read the node's OWN configured peer store"
    # §PROXYKEY 2026-09-11: the key now has ONE reader (`core/api_test_proxy_key`) with no literal
    # default; the relay must still ask it (the module-level `_PROXY_INTERNAL_KEY` is gone).
    assert "_proxy_key_ok(" in body, "the relay must be authenticated by the shared key reader"


def test_es_reachable_is_one_if_chain():
    """CONTROL for the bug I wrote and caught: my first version spliced a second
    `if` into the middle of the existing chain, so the a-unreadable verdicts were
    written and then OVERWRITTEN a few lines below — a branch running in addition
    to its siblings rather than instead of them. Assert the chain has exactly one
    `if` at that indent level."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
           / "routers" / "mcp_tester.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == "_compute_emission_integrity"), None)
    assert fn is not None
    # every `checks["es_reachable"] = ...` assignment must sit in ONE if/elif tree
    roots = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        txt = ast.unparse(node)
        if 'checks["es_reachable"]' in txt or "checks['es_reachable']" in txt:
            roots.append(node)
    # a single if/elif chain nests: the outermost one contains all the others
    outer = [r for r in roots if not any(r is not o and r in ast.walk(o) for o in roots)]
    assert len(outer) == 1, (
        f"es_reachable is decided by {len(outer)} separate if-chains — a later one "
        "will overwrite an earlier one's verdict")
