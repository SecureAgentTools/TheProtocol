"""§RELEASEHARDEN D2 (2026-09-14) — the MCP tester's SSE streams take the JWT from the header only.

A `?access_token=` caller is refused with the sentence that says why (the query string is written to the
access log) rather than a bare "missing token"; the header path still resolves the admin.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
import jwt
from starlette.requests import Request

from agentvault_registry import security
from agentvault_registry.routers import mcp_tester


def _req(headers: dict | None = None) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/api/v1/admin/mcp-tester/event-stream", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("127.0.0.1", 1),
    }
    return Request(scope)


class _Admin:
    id = 7
    is_admin = True


async def test_a_query_string_token_is_refused_with_the_reason():
    with pytest.raises(HTTPException) as exc:
        await mcp_tester._resolve_admin_from_header(_req(), access_token="eyJ.x.y", db=None)
    assert exc.value.status_code == 401
    assert exc.value.detail == mcp_tester.SSE_QUERY_TOKEN_REFUSED
    assert "access logs" in exc.value.detail


async def test_no_token_at_all_is_still_missing_token():
    with pytest.raises(HTTPException) as exc:
        await mcp_tester._resolve_admin_from_header(_req(), access_token=None, db=None)
    assert exc.value.status_code == 401 and exc.value.detail == "missing token"


async def test_the_header_path_resolves_the_admin(monkeypatch):
    async def load(db, dev_id):
        assert dev_id == 7
        return _Admin()

    monkeypatch.setattr(mcp_tester.developer_crud, "get_developer_by_id", load)
    token = jwt.encode({"sub": "7"}, security.SECRET_KEY, algorithm=security.ALGORITHM)
    dev = await mcp_tester._resolve_admin_from_header(_req({"Authorization": f"Bearer {token}"}), access_token=None, db=None)
    assert dev.id == 7


def test_both_streams_declare_the_query_parameter_so_a_stale_caller_hears_the_sentence():
    import inspect

    for fn in (mcp_tester.event_stream_proxy, mcp_tester.event_stream_proxy_multi):
        assert "access_token" in inspect.signature(fn).parameters, fn.__name__


def test_the_old_name_is_gone():
    assert not hasattr(mcp_tester, "_resolve_admin_from_query_or_header")
