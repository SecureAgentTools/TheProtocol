"""§MCPTEST30 (V0639): the webhook lifecycle asks whether the TARGET mounts the sandbox webhook sink.

_webhook_sink_url read SANDBOX_WEBHOOK_SINK_ENABLED in its own process, which is the target's only when the frame's
tester runs the lifecycle. The cloud-operator sweep runs it from its frame: the frame's flag (on since V0637) pointed
the operators' webhooks at a path no operator mounts, and testWebhook, testDeveloperWebhookAlt and
getWebhookDeliveries read red on both operators (2026-10-24 13:39-13:46Z, a 404 each). Pinned: a sweep's answer about
the target (bag.target_webhook_sink) wins over this process's flag in both directions; an unread answer is said; no
answer leaves the process's flag deciding, as before; the probe is a GET on the sink's POST-only path, 405 = mounted,
404 = not, anything else unknown; the sweep sets it and the lifecycle hands its bag over.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import mcp_lifecycles as M
from agentvault_registry.routers import sandbox_webhook_sink as SINK

WID = "0b0c4f2e-6a0d-4c43-9d3a-2f8e1b9a7c55"
CARD = {"identity": {"public_url": "https://sbxalphaop.example.test"}}


async def _rpc(tool, args, jwt="", timeout=15):
    return True, {"result": CARD}, "200"


def _parse(body):
    return body.get("result") or {}


def _url(bag, monkeypatch, flag_here):
    if flag_here:
        monkeypatch.setenv(SINK.FLAG, "true")
    else:
        monkeypatch.delenv(SINK.FLAG, raising=False)
    return asyncio.run(M._webhook_sink_url(_rpc, _parse, WID, "jwt", bag))


def test_the_targets_off_wins_over_this_process_on(monkeypatch):
    bag = SimpleNamespace(target_webhook_sink=(False, f"{SINK.FLAG} is off there: its path answers 404"))
    url, why = _url(bag, monkeypatch, flag_here=True)
    assert url is None and "is off there" in why


def test_the_targets_on_wins_over_this_process_off(monkeypatch):
    bag = SimpleNamespace(target_webhook_sink=(True, f"{SINK.FLAG} is on there: its path answers 405 to a GET"))
    url, why = _url(bag, monkeypatch, flag_here=False)
    assert url == f"https://sbxalphaop.example.test{SINK.PATH}/{WID}" and why == ""


def test_an_unread_answer_is_said(monkeypatch):
    bag = SimpleNamespace(target_webhook_sink=(None, "its path answered HTTP 502 to a GET"))
    url, why = _url(bag, monkeypatch, flag_here=True)
    assert url is None and "could not be read" in why and "502" in why


def test_without_an_answer_this_process_decides_as_before(monkeypatch):
    for bag in (None, SimpleNamespace()):
        url, why = _url(bag, monkeypatch, flag_here=False)
        assert url is None and f"{SINK.FLAG} is off" in why
        url, why = _url(bag, monkeypatch, flag_here=True)
        assert url == f"https://sbxalphaop.example.test{SINK.PATH}/{WID}"


def _probe(monkeypatch, answer=None, raises=None):
    seen = []

    async def fake_http(container, method, path, *, body=None, **kw):
        seen.append((container, method, path, body))
        if raises:
            raise raises
        return answer

    monkeypatch.setattr(F, "_http_in_target", fake_http)
    return asyncio.run(F._probe_webhook_sink("cloud-op-sbxbetaop-registry")), seen


def test_the_probe_is_a_get_on_the_post_only_path(monkeypatch):
    out, seen = _probe(monkeypatch, ("405", '{"detail":"Method Not Allowed"}'))
    assert seen == [("cloud-op-sbxbetaop-registry", "GET", f"{SINK.PATH}/mcp-probe", None)]
    assert out[0] is True


def test_the_probe_reads_404_as_off_and_anything_else_as_unknown(monkeypatch):
    assert _probe(monkeypatch, ("404", "{}"))[0][0] is False
    for code in ("200", "403", "500", ""):
        on, why = _probe(monkeypatch, (code, ""))[0]
        assert on is None and "to a GET" in why, code
    on, why = _probe(monkeypatch, raises=TimeoutError())[0]
    assert on is None and why == "TimeoutError"


def test_the_sweep_asks_the_operator_and_the_lifecycle_hands_its_bag_over():
    sweep = ast.parse("class X:\n" + inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep))
    sets = [n for n in ast.walk(sweep) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "target_webhook_sink" for t in n.targets)]
    assert len(sets) == 1 and "_probe_webhook_sink(op.registry_container)" in ast.unparse(sets[0].value)
    life = ast.parse(inspect.getsource(M.lifecycle_webhook_full_crud))
    calls = [n for n in ast.walk(life) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_webhook_sink_url"]
    assert calls and all(any(isinstance(a, ast.Name) and a.id == "bag" for a in c.args) for c in calls)
