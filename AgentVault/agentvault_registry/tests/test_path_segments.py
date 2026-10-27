"""§MCPTEST30 (V0523, 2026-10-01) — a caller's value is ONE path segment, encoded (core/path_segment.seg).

The MCP tools put their arguments into route paths unencoded, and the registry did the same when it forwards a path
value to its TEG. httpx resolves dot segments client-side, so `/api/v1/webhooks/123/../../agents/x` was sent as
`/api/v1/agents/x`: a value could steer a tool to another route with the caller's credentials and the tool's method.
The hostile-input probe measured it on sbx-alpha (V0515): 108 values that never left their tool (a NUL is refused by
httpx itself) and eight TEG-proxied routes answering 503 for a `%` the TEG's nginx refused. This file pins the
encoding, and holds the line over every route path the tools and the TEG calls build.
"""
from __future__ import annotations

import ast
import pathlib

import httpx

from agentvault_registry.core.path_segment import seg

import agentvault_registry  # noqa: E402

PKG = pathlib.Path(agentvault_registry.__file__).parent   # the code under test, wherever it is imported from
TEG_FILES = ("routers/teg_integration.py", "routers/teg_integration_mtls.py", "routers/federation_blocklist.py",
             "routers/token_bridge.py", "background_tasks/balance_reconciliation_guard.py",
             "background_tasks/eventstore_balance_sync.py", "background_tasks/showcase_visitor_sweeper.py",
             "background_tasks/supply_auditor.py")


def test_a_value_becomes_one_segment():
    did = "did:theprotocol:9f1c2e7a-0b6d-4c1e-9a7b-3d2f1e0c5b4a"
    assert seg(did) == did                                  # a DID reads the same
    assert seg("ops@example.org") == "ops@example.org"      # so does an email
    assert seg(42) == "42"
    assert seg("a/b?c=d#e") == "a%2Fb%3Fc%3Dd%23e"
    assert seg("100%_\\") == "100%25_%5C"
    assert seg("x\x00y") == "x%00y"
    assert seg(".") == "%2E" and seg("..") == "%2E%2E"     # quote() leaves dots alone; httpx would resolve them
    assert seg("...") == "..." and seg("a..b") == "a..b"   # not a dot segment


def test_httpx_keeps_an_encoded_value_where_it_was_put():
    for hostile in ("../../agents/did:x", "..", "x?admin=1#f", "a/b"):
        raw = httpx.URL(f"http://h:8000/api/v1/webhooks/{seg(hostile)}/test").raw_path.decode()
        assert raw.startswith("/api/v1/webhooks/") and raw.endswith("/test"), (hostile, raw)
        assert raw.count("/") == "/api/v1/webhooks/x/test".count("/"), (hostile, raw)
    # the control: unencoded, httpx sends the call somewhere else
    assert httpx.URL("http://h:8000/api/v1/webhooks/123/../../agents/did:x/test").raw_path == b"/api/v1/agents/did:x/test"


def _unwrapped(src: str, mode: str):
    """(line, expression) for every interpolation into a route path that is not seg(...), int(...) or a CONSTANT."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.JoinedStr) or not node.values:
            continue
        if mode == "teg":
            first = node.values[0]
            if not (isinstance(first, ast.FormattedValue) and "teg" in ast.unparse(first.value).lower()):
                continue
        seen = False
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                seen = seen or (("/api/v1" in v.value) if mode == "mcp" else ("/" in v.value))
            elif isinstance(v, ast.FormattedValue) and seen:
                e = v.value
                if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id in ("seg", "int"):
                    continue
                if ast.unparse(e).split(".")[-1].isupper():
                    continue
                out.append((node.lineno, ast.unparse(e)))
    return out


def test_every_route_path_the_tools_build_encodes_its_values():
    bad = {}
    for p in sorted((PKG / "mcp").glob("tools_*.py")):
        found = _unwrapped(p.read_text(), "mcp")
        if found:
            bad[p.name] = found[:5]
    assert bad == {}, bad


def test_every_teg_url_the_registry_builds_encodes_its_values():
    bad = {f: _unwrapped((PKG / f).read_text(), "teg")[:5] for f in TEG_FILES}
    assert {f: v for f, v in bad.items() if v} == {}


def test_the_gate_sees_an_unencoded_value():
    src = ('async def t(auth, webhook_id, n, did):\n'
           '    await get(f"{BASE}/api/v1/webhooks/{webhook_id}/x/{int(n)}/{seg(did)}/{TEG_API_V1_PREFIX}")\n'
           '    await get(f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/policies/{webhook_id}")\n')
    assert _unwrapped(src, "mcp") == [(2, "webhook_id")]
    assert _unwrapped(src, "teg") == [(3, "webhook_id")]


def test_the_seg_import_sits_in_every_module_that_uses_it():
    for p in sorted((PKG / "mcp").glob("tools_*.py")) + [PKG / f for f in TEG_FILES]:
        s = p.read_text()
        if "seg(" in s.replace("def seg(", ""):
            assert "from ..core.path_segment import seg" in s, p.name
