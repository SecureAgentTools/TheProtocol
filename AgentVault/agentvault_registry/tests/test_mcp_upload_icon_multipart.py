"""§MCPSWEEP 2026-09-27 — the registry-card icon tool sends the MULTIPART `file` its route takes.

/api/v1/admin/registry-card/icon is `file: UploadFile = File(...)` (PNG or JPEG, <= 500 KB, validated before it is
written); the MCP tool POSTed JSON, so every call answered 422 and no icon could ever be set through MCP. The lifecycle
probe never saw it: it sent an argument the tool did not declare and was refused before the tool ran.
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.mcp import tools_admin as ta  # noqa: E402


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    # This file drives coroutines with asyncio.run(), which leaves the thread with no current loop; put one back, or the
    # next file's get_event_loop() fails and the red lands in a file this one never touched.
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Resp:
    status_code = 415
    text = "Icon must be PNG or JPEG (detected: None). SVG rejected for XSS safety."

    def json(self):
        return {}


def _capture(monkeypatch):
    seen = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            seen.append((url, kw))
            return _Resp()

    monkeypatch.setattr(ta.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ta, "require_admin_auth", lambda auth: None)
    monkeypatch.setattr(ta, "_get_effective_jwt", lambda auth: "jwt")
    return seen


def test_the_icon_goes_as_a_multipart_file(monkeypatch):
    seen = _capture(monkeypatch)
    out = asyncio.run(ta.upload_registry_card_icon(object(), base64.b64encode(b"phase6-not-an-image").decode(),
                                                   "image/png"))
    assert len(seen) == 1
    url, kw = seen[0]
    assert url.endswith("/api/v1/admin/registry-card/icon")
    assert "json" not in kw, "the route takes a multipart file; a JSON body is refused with 422"
    name, raw, ctype = kw["files"]["file"]
    assert raw == b"phase6-not-an-image" and ctype == "image/png" and name == "icon.png"
    assert "HTTP 415" in out["error"] and "must be PNG or JPEG" in out["error"]


def test_bad_base64_sends_nothing(monkeypatch):
    seen = _capture(monkeypatch)
    out = asyncio.run(ta.upload_registry_card_icon(object(), "%%% not base64 %%%"))
    assert seen == [] and "not valid base64" in out["error"]


def test_a_jpeg_is_named_as_one(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(ta.upload_registry_card_icon(object(), base64.b64encode(b"x").decode(), "image/jpeg"))
    assert seen[0][1]["files"]["file"][0] == "icon.jpg"
