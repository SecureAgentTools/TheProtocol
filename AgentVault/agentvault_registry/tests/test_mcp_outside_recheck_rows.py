"""§MCPTEST30 (V0650, tester batch 2 item 5, agentvault2-d3, Guild order gwo_e3bad842b1a5943022b01d40): rows that would
have caught what the outside view's V0649 re-check found (the dev machine, 2026-10-31; order (n), session-release's
19a504ab8): (a) a manifest whose size for the rendered CLAUDE.md no download matched, and no digest for any file; (d) an
external enrolment's answer naming a docker_label. (c), the manual's address, is in test_mcp_onboard_agent_name.py; (b),
the bridges' version negotiation, is the stack's bridges-tests job and the proof's served-bridge digests.

RED on the code before: the lifecycle, manifest_findings and external_label_finding do not exist.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
from typing import Any, Dict, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_ad_devtools as D
from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import mcp_lifecycles as ML

BRIDGE = b"#!/usr/bin/env node\n// the public bridge\n"
ADMIN = b"#!/usr/bin/env node\n// the admin bridge\n"
TEMPLATE = b"# Operator manual\n\n<!-- LIVE_FACTS -->\n{REGISTRY_URL}/api/v1\n"
RENDERED = b"# Operator manual\n\n> | `REGISTRY_URL` | `https://nt.theprotocol.cloud` |\nhttps://nt.theprotocol.cloud/api/v1\n"


def _v0650() -> list:
    def stored(name: str, data: bytes) -> Dict[str, Any]:
        return {"filename": name, "available": True, "url": f"/api/v1/downloads/{name}", "rendered_per_request": False,
                "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return [stored("mcp-stdio-bridge.js", BRIDGE), stored("mcp-stdio-bridge-admin.js", ADMIN),
            {"filename": "CLAUDE.md", "available": True, "url": "/api/v1/downloads/CLAUDE.md",
             "rendered_per_request": True, "size_bytes": None, "sha256": None,
             "template_size_bytes": len(TEMPLATE), "template_sha256": hashlib.sha256(TEMPLATE).hexdigest()}]


def _v0649() -> list:
    # what the outside view read: a size for every file (the manual's the template's), no digest, nothing marked rendered
    return [{"filename": n, "available": True, "url": f"/api/v1/downloads/{n}", "size_bytes": len(d)}
            for n, d in (("mcp-stdio-bridge.js", BRIDGE), ("mcp-stdio-bridge-admin.js", ADMIN), ("CLAUDE.md", TEMPLATE))]


SERVED = {"/api/v1/downloads/mcp-stdio-bridge.js": BRIDGE, "/api/v1/downloads/mcp-stdio-bridge-admin.js": ADMIN,
          "/api/v1/downloads/CLAUDE.md": RENDERED}


def test_v0650s_manifest_matches_its_downloads():
    assert D.manifest_findings(_v0650(), SERVED) == ([], [], 3)


def test_v0649s_manifest_is_red_where_the_outside_view_was_refused():
    findings, unread, checked = D.manifest_findings(_v0649(), SERVED)
    said = " | ".join(findings)
    assert checked == 3 and not unread
    assert f"CLAUDE.md has {len(TEMPLATE)} bytes, its download has {len(RENDERED)}" in said, said
    assert "sha256 for mcp-stdio-bridge.js (none)" in said and "sha256 for CLAUDE.md (none)" in said, said


def test_a_rendered_file_that_claims_a_size_is_red_and_a_changed_byte_too():
    files = _v0650()
    files[2]["size_bytes"] = len(TEMPLATE)
    assert any("rendered per request, yet" in f for f in D.manifest_findings(files, SERVED)[0])
    served = dict(SERVED)
    served["/api/v1/downloads/mcp-stdio-bridge.js"] = BRIDGE.replace(b"public", b"pubLic")
    assert any("sha256 for mcp-stdio-bridge.js" in f for f in D.manifest_findings(_v0650(), served)[0])


def test_an_unread_download_is_named_not_judged():
    served = dict(SERVED)
    served["/api/v1/downloads/CLAUDE.md"] = None
    assert D.manifest_findings(_v0650(), served) == ([], ["CLAUDE.md"], 2)


class _Target:
    def __init__(self, files: list, served: Dict[str, Optional[bytes]]):
        self.files, self.served, self.reads = files, served, []

    async def rpc(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        assert tool == D.MANIFEST and args == {} and jwt == "d", "a public tool still carries the run's token"
        return True, {"result": {"files": self.files}}, "200"

    async def b64(self, path: str) -> Tuple[str, str]:
        self.reads.append(path)
        raw = self.served.get(path)
        return ("200", base64.b64encode(raw).decode()) if raw is not None else ("", "")


def _run(target: Optional[_Target]) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline", sentinel_jwt="s", developer_jwt="d", developer_id="1")
    if target is not None:
        bag.http_b64_in_target = target.b64   # type: ignore[attr-defined]
    out: Dict[str, dict] = {}

    async def no_rpc(*_a, **_k):
        raise AssertionError("no call expected")
    asyncio.run(D.lifecycle_earn_downloads_as_served(target.rpc if target else no_rpc,
                                                    lambda b: b.get("result") if isinstance(b, dict) else {}, bag, out))
    return out


def test_the_lifecycle_earns_the_manifest_on_v0650_and_keeps_no_bytes():
    t = _Target(_v0650(), SERVED)
    row = _run(t)[D.MANIFEST]
    assert row["healthy"] and not row.get("fail_reason"), row
    assert row["result_excerpt"]["checked"] == 3 and row["result_excerpt"]["rendered_per_request"] == ["CLAUDE.md"]
    assert sorted(t.reads) == sorted(SERVED)
    assert "the public bridge" not in repr(row) and "REGISTRY_URL" not in repr(row)


def test_the_lifecycle_finds_v0649s_manifest():
    row = _run(_Target(_v0649(), SERVED))[D.MANIFEST]
    assert not row["healthy"] and str(row.get("fail_reason")).startswith("BUG-FIND"), row
    assert "CLAUDE.md has" in row["fail_reason"]


def test_no_transport_or_no_download_is_said():
    assert "bag.http_b64_in_target" in str(_run(None)[D.MANIFEST].get("skip_reason"))
    row = _run(_Target(_v0650(), {}))[D.MANIFEST]
    assert "could be downloaded inside the target" in str(row.get("skip_reason")), row


def test_it_is_registered():
    assert "earn_downloads_as_served" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]


# ── (d) the external enrolment's answer ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("answer,red", [
    ({"deployment": "external", "deployment_signal": "indeterminate_via_loopback_proxy",
      "docker_label": "docker:label:agentvault.agent_did:did:theprotocol:x"}, True),
    ({"deployment": "external", "deployment_signal": "public_network_source"}, False),
    ({"deployment": "onbox", "docker_label": "docker:label:agentvault.agent_did:did:theprotocol:x"}, False),
    ({"docker_label": "docker:label:agentvault.agent_did:did:theprotocol:x"}, False),   # an older image: no deployment
])
def test_an_external_answer_names_no_docker_label(answer, red):
    why = ML.external_label_finding(answer)
    assert bool(why) is red, why
    if red:
        assert "external" in why and "did:theprotocol:x" not in why


def test_the_toggle_asks_it_after_the_not_enrolled_branch():
    src = inspect.getsource(ML.lifecycle_mtls_toggle)
    assert src.index("_mtls_not_delivered(") < src.index("external_label_finding(enabled)")


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
