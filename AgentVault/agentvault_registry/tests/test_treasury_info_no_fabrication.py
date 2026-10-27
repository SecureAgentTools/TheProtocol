"""§MONEY-R27 — a supply surface must fail rather than invent numbers.

`TEGClient.get_treasury_info()` returned INVENTED figures whenever the TEG could not answer —
total_supply "1000000", circulating_supply "500000", treasury_balance "300000" — from TWO
branches (non-200, and connection error). Two public routers serve it straight through
(`routers/endpoints_tokenomics_proxy.py`, `routers/teg_summary_enhanced.py`), so "could not
check" was rendered to callers as a confident, specific, wrong answer about how much money
exists. Its own docstring already promised `Raises: TEGClientError` — the contract was
documented correctly and the code violated it, which is why no reader caught it.

Every OTHER method on this client raises TEGClientError on failure (7 sites). This one was the
outlier, and an AST sweep for "a return dict of hardcoded numeric strings" finds zero now.
"""
from __future__ import annotations

import ast
import contextlib
import pathlib
from unittest import mock

import httpx
import pytest

from agentvault_registry.teg_client import TEGClient, TEGClientError

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "teg_client.py"


@contextlib.contextmanager
def _client_with(transport_result):
    """A TEGClient whose only live parts are the ones get_treasury_info touches.

    ⚠ `_client` is a self-healing PROPERTY (it rebuilds the httpx client when the SVID
    rotates), so it has no setter and its backing attribute would be overwritten. Replace
    the property itself for the duration of the test.
    """
    class _FakeHTTP:
        async def get(self, *_a, **_kw):
            if isinstance(transport_result, Exception):
                raise transport_result
            return transport_result

    c = TEGClient.__new__(TEGClient)
    c.base_url, c.api_prefix = "http://teg.invalid", "/api/v1"
    c.get_service_token = lambda: "tok"                      # type: ignore[method-assign]
    with mock.patch.object(TEGClient, "_client", new_callable=mock.PropertyMock) as m:
        m.return_value = _FakeHTTP()
        yield c


class _Resp:
    def __init__(self, code): self.status_code = code
    def json(self): return {}


@pytest.mark.asyncio
async def test_non_200_raises_instead_of_fabricating():
    with _client_with(_Resp(503)) as c:
        with pytest.raises(TEGClientError):
            await c.get_treasury_info()


@pytest.mark.asyncio
async def test_connection_error_raises_instead_of_fabricating():
    with _client_with(httpx.RequestError("TEG unreachable")) as c:
        with pytest.raises(TEGClientError):
            await c.get_treasury_info()


@pytest.mark.asyncio
async def test_a_healthy_teg_still_returns_its_real_numbers():
    """The control the fix exists to serve: a gate that only proves refusal is half a gate."""
    class _OK(_Resp):
        def __init__(self): super().__init__(200)
        def json(self): return {"total_supply": 42, "circulating_supply": 7,
                                "treasury_balance": 5, "last_updated": "now"}
    with _client_with(_OK()) as c:
        out = await c.get_treasury_info()
    assert out["total_supply"] == "42" and out["circulating_supply"] == "7"
    assert out["treasury_balance"] == "5"


def test_no_hardcoded_numeric_return_dict_survives_anywhere_in_the_client():
    """The CLASS, not the instance — a second fabricator would be the same defect."""
    tree = ast.parse(_SRC.read_text())
    offenders = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            vals = [v.value for v in n.value.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            nums = [v for v in vals if v.replace(".", "", 1).isdigit() and v not in ("0", "0.0")]
            if nums:
                offenders.append((n.lineno, nums))
    assert not offenders, f"fabricated money figures returned at {offenders}"


def test_the_summary_router_says_when_detail_is_unavailable():
    """`except: treasury_info = {}` is the same two-state collapse one level up."""
    src = (_SRC.parent / "routers" / "teg_summary_enhanced.py").read_text()
    tree = ast.parse(src)
    bare = [h.lineno for h in ast.walk(tree)
            if isinstance(h, ast.ExceptHandler) and h.type is None]
    assert not bare, f"bare `except:` at {bare} — it would swallow the R27 raise silently"
    assert "additional_info_available" in src, (
        "the router must publish whether the detail was reachable, not just an empty dict"
    )
