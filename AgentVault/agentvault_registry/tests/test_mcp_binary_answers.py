"""§MCPTEST30 (V0640): an MCP tool answers a file by its manifest, its content only where it asks, never into the audit.

A developer tool whose route answered a file (agentBuilderGenerate's package, downloadBundleViaOnboard's bundle) handed
its caller the first 300 characters of the file decoded as text, which no MCP caller could use (agentvault2-66,
2026-10-24; agentvault2-d6's terms for V0640). Pinned: a file answers status, content_type, filename, size_bytes, files
(a zip's names and sizes) and sha256, in that order; content_base64 only where the tool asks (the agent builder's two
tools) and only up to the 2 MB cap, the answer saying why above it; the onboarding bundle, which carries the agent's
secret, never carries its content; JSON, text and the raw path answer as before; and the audit's summary of a zip
answer holds no base64 payload (control: the summary before the drop did).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile

import pytest

from agentvault_registry.mcp import audit
from agentvault_registry.mcp import binary_answers as BA
from agentvault_registry.mcp import server
from agentvault_registry.mcp import tools_developer as td


def _zip(files) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files:
            zf.writestr(name, text)
    return buf.getvalue()


BUNDLE = _zip([(".env", "AGENT_NAME=x\n"), (".env.secret", "CLIENT_SECRET=tp_secret_" + "z9" * 20 + "\n")])
HEADERS = {"content-type": "application/zip", "content-disposition": 'attachment; filename="agent-x.zip"'}


def test_a_zip_answers_its_manifest_in_order_and_no_content_unless_asked():
    m = BA.file_manifest(BUNDLE, "application/zip", HEADERS["content-disposition"])
    assert list(m)[:6] == ["status", "content_type", "filename", "size_bytes", "files", "sha256"]
    assert m["filename"] == "agent-x.zip" and m["size_bytes"] == len(BUNDLE)
    assert [f["name"] for f in m["files"]] == [".env", ".env.secret"] and BA.CONTENT_KEY not in m
    assert "not sent over MCP" in m["content_withheld"]
    asked = BA.file_manifest(BUNDLE, "application/zip", "", content=True)
    assert base64.b64decode(asked[BA.CONTENT_KEY]) == BUNDLE and "content_withheld" not in asked


def test_content_above_the_cap_is_withheld_and_says_so(monkeypatch):
    monkeypatch.setattr(BA, "CONTENT_CAP_BYTES", 16)
    m = BA.file_manifest(BUNDLE, "application/zip", "", content=True)
    assert BA.CONTENT_KEY not in m and f"over the 16-byte cap" in m["content_withheld"] and m["files"]


@pytest.mark.parametrize("ct,data,want", [
    ("application/zip", b"anything", True), ("", BUNDLE[:8], True), ("application/octet-stream", b"\x00\x01", True),
    ("application/json", b'{"a": 1}', False), ("application/problem+json", b"{}", False),
    ("text/html; charset=utf-8", b"<html>", False), ("text/plain", b"hi", False), ("", b"plain", False),
])
def test_what_counts_as_a_file(ct, data, want):
    assert BA.is_file(ct, data) is want


class _Resp:
    def __init__(self, code, data, headers):
        self.status_code, self.content, self.headers = code, data, headers
        self.text = data.decode("latin-1")

    def json(self):
        return json.loads(self.content)


def _client(resp):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, *a, **k):
            return resp
    return _Client


class _Auth:
    raw_token = "t"


@pytest.fixture(autouse=True)
def _no_auth_check(monkeypatch):
    monkeypatch.setattr(td, "require_developer_auth", lambda auth: None)


def test_the_agent_builder_gets_the_content_and_the_onboarding_bundle_never(monkeypatch):
    monkeypatch.setattr(td.httpx, "AsyncClient", _client(_Resp(200, BUNDLE, HEADERS)))
    built = asyncio.run(td.agent_builder_generate(_Auth(), {"agent_name": "x"}))
    assert base64.b64decode(built[BA.CONTENT_KEY]) == BUNDLE and "raw" not in built
    bundle = asyncio.run(td.download_bundle_via_onboard(_Auth(), {"agent_did": "d", "client_id": "c",
                                                                  "client_secret": "s"}))
    assert BA.CONTENT_KEY not in bundle and "raw" not in bundle
    assert [f["name"] for f in bundle["files"]] == [".env", ".env.secret"] and b"tp_secret_" not in json.dumps(
        bundle).encode()


def test_json_text_and_raw_answers_are_unchanged(monkeypatch):
    monkeypatch.setattr(td.httpx, "AsyncClient", _client(_Resp(200, b'{"a": 1}', {"content-type": "application/json"})))
    assert asyncio.run(td._dev_request(_Auth(), "GET", "/x")) == {"a": 1}
    monkeypatch.setattr(td.httpx, "AsyncClient", _client(_Resp(200, b"<html>hi</html>", {"content-type": "text/html"})))
    assert asyncio.run(td._dev_request(_Auth(), "GET", "/x")) == {"status": "ok", "raw": "<html>hi</html>"}
    assert asyncio.run(td._dev_request(_Auth(), "GET", "/x", raw=True)) == "<html>hi</html>"


def test_the_audit_never_keeps_a_files_content():
    asked = BA.file_manifest(BUNDLE, "application/zip", HEADERS["content-disposition"], content=True)
    payload = server._tool_result_payload(asked)
    head = asked[BA.CONTENT_KEY][:24]
    summary = json.dumps(audit._summarize_result(payload), default=str)
    assert head not in summary and BA.CONTENT_KEY not in summary and ".env.secret" in summary
    assert BA.CONTENT_KEY not in json.dumps(audit._summarize_result(asked), default=str)
    # control: the same answer summarized without the drop carries the payload's first characters
    before = json.dumps(audit.sanitize_result(payload), default=str)
    assert head in before
