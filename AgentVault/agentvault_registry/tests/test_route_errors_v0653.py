"""V0653 (am), item 2 (the hardening list in the sessions' room): a route's 5xx answer never carries the text of an
exception it caught.

50 HTTPException details in 23 routers were built from `except Exception as e` (f"Cannot reach TEG: {e}", str(e)[:200]),
so a connection error's internal host and port, a database message or a path reached the caller. They go through
core/caller_errors.internal_detail now: the route's own words and an error id, the exception in the log under the same
id. 4xx answers keep their text where it is the caller's own input judged (a schema they sent, a credential they
presented, an upload): that is the answer. The gate reads every router (the AST) and refuses a 5xx (or a computed status)
built from a caught exception that does not go through internal_detail. BASE (a5ef48ddd, V0652): 50; the TEG's internal
address is in balance-reconcile's answer.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import pathlib
import re

import httpx
import pytest
from fastapi import HTTPException

ROUTERS = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers"


def _status(call):
    sc = next((k.value for k in call.keywords if k.arg == "status_code"), call.args[0] if call.args else None)
    if sc is None:
        return None
    if isinstance(sc, ast.Constant) and isinstance(sc.value, int):
        return sc.value
    m = re.search(r"HTTP_(\d{3})_", ast.unparse(sc))
    return int(m.group(1)) if m else None


def _only_type_name(value, ename):
    uses = [n for n in ast.walk(value) if isinstance(n, ast.Name) and n.id == ename]
    typed = [n for n in ast.walk(value) if isinstance(n, ast.Attribute) and n.attr == "__name__"
             and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", None) == "type" and n.value.args
             and isinstance(n.value.args[0], ast.Name) and n.value.args[0].id == ename]
    return bool(uses) and len(uses) == len(typed)


def _outside_internal_detail(node):
    """The names a detail uses outside internal_detail(...) (a marker after it, internal_detail(e, ...) + _none, is fine)."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "internal_detail":
        return set()
    out = {node.id} if isinstance(node, ast.Name) else set()
    for c in ast.iter_child_nodes(node):
        out |= _outside_internal_detail(c)
    return out


def scan(text, where="<src>"):
    found = []
    for h in ast.walk(ast.parse(text)):
        if not isinstance(h, ast.ExceptHandler) or not h.name:
            continue
        if (ast.unparse(h.type) if h.type is not None else "BaseException") not in ("Exception", "BaseException"):
            continue
        for n in ast.walk(h):
            if not (isinstance(n, ast.Call) and "HTTPException" in (getattr(n.func, "id", None), getattr(n.func, "attr", None))):
                continue
            code = _status(n)
            if code is not None and code < 500:
                continue
            for kw in n.keywords:
                if kw.arg != "detail":
                    continue
                if h.name in _outside_internal_detail(kw.value) and not _only_type_name(kw.value, h.name):
                    found.append(f"{where}:{kw.value.lineno}: {ast.unparse(kw.value)[:80]}")
    return found


def test_no_5xx_answer_carries_a_caught_exceptions_text():
    files = sorted(ROUTERS.rglob("*.py"))
    assert len(files) > 100                                   # a gate over nothing passes loudest
    found = [f for p in files for f in scan(p.read_text(encoding="utf-8"), p.name)]
    assert not found, "\n".join(found)


def test_the_gate_catches_each_shape():
    planted = (
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=502, detail=f'Cannot reach TEG: {e}')\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(500, detail=str(e)[:200])\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=code, detail=f'{e}')\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=502, detail=internal_detail(e, 'Cannot reach TEG', logger))\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=422, detail=f'terms invalid: {e}')\n"
        "try:\n    x()\nexcept ValueError as e:\n    raise HTTPException(status_code=500, detail=str(e))\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=503, detail=f'down ({type(e).__name__})')\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=502, detail=internal_detail(e, 'x', logger) + _none)\n"
        "try:\n    x()\nexcept Exception as e:\n    raise HTTPException(status_code=502, detail=internal_detail(e, 'x', logger) + str(e))\n")
    assert [f.split(": ", 1)[1] for f in scan(planted)] == ["f'Cannot reach TEG: {e}'", "str(e)[:200]", "f'{e}'",
                                                             "internal_detail(e, 'x', logger) + str(e)"]


def test_an_unreachable_teg_is_named_without_its_address(monkeypatch, caplog):
    from agentvault_registry.routers import balance_reconcile as br

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            raise httpx.ConnectError(f"All connection attempts failed: {url}")

    monkeypatch.setattr(br.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(br, "get_httpx_verify", lambda: False)
    monkeypatch.setenv("TEG_API_BASE_URL", "http://eu-teg-internal:8080")
    with caplog.at_level(logging.DEBUG), pytest.raises(HTTPException) as e:
        asyncio.run(br.balance_reconcile_local(current_developer=None))
    assert e.value.status_code == 502
    assert "eu-teg-internal" not in str(e.value.detail) and str(e.value.detail).startswith("local TEG unreachable (error id ")
    eid = str(e.value.detail).split("error id ", 1)[1].rstrip(")")
    assert any(eid in r.getMessage() and "eu-teg-internal" in r.getMessage() for r in caplog.records)


def test_a_refusal_of_the_routes_own_keeps_its_words():
    from agentvault_registry.core.caller_errors import internal_detail
    assert internal_detail(HTTPException(403, "not this agent's order"), "Failed to tally") == \
        "Failed to tally: not this agent's order"
