"""§B6 (2026-09-05) — the admin escape-hatch wrappers (adminRequest, adminQueryEventStore,
adminGrafanaQuery) must surface an upstream non-2xx as an `upstream_error` key, not only as
`ok: false` buried beside a 200 MCP call. Found by agentvault2-07: a fund-agent that 422'd
read as a funded agent until three steps later.
"""
import os
import re
import pathlib

# importing the MCP module builds Settings; give it the two fields it requires (throwaway values)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from agentvault_registry.mcp.tools_admin import _upstream_error  # noqa: E402


def test_2xx_carries_no_error():
    assert _upstream_error(200, {"ok": True}) is None
    assert _upstream_error(201, "created") is None


def test_rfc7807_detail_is_quoted():
    body = {"type": "about:blank", "title": "Unprocessable Entity", "status": 422,
            "detail": "Field required: target_agent_did", "instance": "/api/v1/teg/treasury/fund-agent"}
    assert _upstream_error(422, body) == "upstream HTTP 422: Field required: target_agent_did"


def test_title_when_no_detail_and_text_bodies():
    assert _upstream_error(403, {"title": "Forbidden"}) == "upstream HTTP 403: Forbidden"
    assert _upstream_error(502, "Bad Gateway\n") == "upstream HTTP 502: Bad Gateway"
    assert _upstream_error(500, "") == "upstream HTTP 500"


def test_every_wrapper_return_attaches_the_upstream_error_key():
    """Structural: each `"ok": resp.status_code < 400` envelope in tools_admin.py is followed by
    the _upstream_error attachment — a fourth wrapper added without it would be the B6 shape again."""
    src = (pathlib.Path(os.environ.get("WRAPPER_SRC", str(pathlib.Path(__file__).resolve().parent.parent / "src/agentvault_registry"))) / "mcp/tools_admin.py").read_text()
    envelopes = [m.start() for m in re.finditer(r'"ok":\s+resp\.status_code < 400,', src)]
    assert len(envelopes) >= 3, envelopes
    for pos in envelopes:
        window = src[pos:pos + 400]
        assert "_upstream_error(resp.status_code, response_data)" in window, src[pos:pos + 200]
