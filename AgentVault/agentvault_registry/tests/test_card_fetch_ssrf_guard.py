"""§SSRFGUARD (2026-09-16, his word "1-3 approved"): the agent-card fetch asks about every redirect hop.

`_is_skippable_host` runs on the url a card NAMES, and both fetch sites built their client with
`follow_redirects=True`, so a host the registry was pointed at could answer 302 and send the fetch to a loopback or
private address. The body then came back through `_merge_pulled_card` into a publicly readable card. Measured on the
image the fleet runs (httpx 0.27.0, an isolated container): the hop was followed and the internal body landed in the
merged card. A reporter named the class on 2026-09-12; the redirect half is the half that reaches inside.

  1. (behaviour) a redirect to a loopback, private or link-local target is refused, and the control proves the server
     really redirects: a plain client with follow_redirects=True reaches the internal body through the same url;
  2. (behaviour) a chain longer than the cap is refused, with the hop check held open so only the cap can stop it;
  3. (behaviour) a plain 200 and a 304 still come back untouched;
  4. (behaviour) a body that is not an agent card is not merged (an internal service's JSON is not a card);
  5. (structure) both fetch sites call the guarded fetch, neither calls client.get itself, and no client in the module
     is built with follow_redirects=True;
  6. (behaviour) the library's HTTPS rule is a hostname check: http://localhost keeps its exemption and a public host
     named http://localhost.attacker.example.com does not.

RED on the tree before the change: fetch_agent_card and _looks_like_agent_card do not exist, both clients pass
follow_redirects=True, and the library accepts http://localhost.attacker.example.com.
Run: python -m pytest tests/test_card_fetch_ssrf_guard.py -q   (in the registry image; needs httpx and pytest)
"""
from __future__ import annotations

import ast
import asyncio
import http.server
import json
import pathlib
import threading
from typing import Any, Dict, Optional, Tuple

import httpx
import pytest

from agentvault_registry.background_tasks import agent_card_pullsync as pull

SRC = pathlib.Path(pull.__file__).resolve()
CARD = {"name": "lab agent", "protocolVersion": "1.0", "supportedInterfaces": [{"url": "https://agent.example/a2a"}]}
INTERNAL_BODY = {"result": {"token": "INTERNAL-ONLY-VALUE"}}


class _Handler(http.server.BaseHTTPRequestHandler):
    """One server, several shapes: a redirect to a named target, a self-chain, a card, a 304 and a non-card body."""

    def _send(self, code: int, body: Optional[dict] = None, headers: Optional[Dict[str, str]] = None) -> None:
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path
        if path.startswith("/to/"):                       # /to/<host-and-port>/rest → a redirect we name
            self._send(302, headers={"Location": "http://" + path[4:]})
        elif path.startswith("/chain"):                   # an endless chain on this same server
            self._send(302, headers={"Location": f"http://127.0.0.1:{self.server.server_address[1]}/chain"})
        elif path.startswith("/card"):
            self._send(200, CARD, {"ETag": '"v1"'})
        elif path.startswith("/notmodified"):
            self._send(304)
        elif path.startswith("/notacard"):
            self._send(200, INTERNAL_BODY)
        else:
            self._send(200, INTERNAL_BODY)                # what an internal service would answer

    def log_message(self, *a: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """`asyncio.run()` closes its loop and leaves the thread without a current one, and the NEXT FILE's
    `get_event_loop()` then raises. Measured: this file collects immediately before test_cardlink_health_probe.py,
    which failed 9 times in the whole-suite run and passed alone. The pollution is this file's to clean up."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture()
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _fetch(url: str, **client_kwargs: Any) -> Tuple[Optional[httpx.Response], Optional[BaseException]]:
    """Run the module's guarded fetch with the fetcher's own client settings; return (response, refusal)."""
    fetch = getattr(pull, "fetch_agent_card", None)
    assert callable(fetch), "agent_card_pullsync.fetch_agent_card is missing: the redirect hops are unchecked"

    async def run():
        async with httpx.AsyncClient(timeout=5.0, verify=True, follow_redirects=False, **client_kwargs) as client:
            return await fetch(client, url, {})

    try:
        return asyncio.run(run()), None
    except Exception as e:  # the refusal the guard raises
        return None, e


def _refusal_class():
    cls = getattr(pull, "FetchRefused", None)
    assert isinstance(cls, type) and issubclass(cls, Exception), "agent_card_pullsync.FetchRefused is missing"
    return cls


@pytest.mark.parametrize("target", ["127.0.0.1:9/internal", "10.1.2.3/internal", "169.254.169.254/latest",
                                    "localhost:8000/internal", "192.168.1.9:8200/internal"])
def test_red_a_redirect_to_an_internal_target_is_refused(server, target):
    resp, refusal = _fetch(f"{server}/to/{target}")
    assert resp is None and isinstance(refusal, _refusal_class()), f"followed the hop to {target}: {resp}"
    assert target.split("/")[0].split(":")[0] in str(refusal), str(refusal)


def test_control_the_same_redirect_is_followed_without_the_guard(server):
    """The server really redirects, and a plain client really reaches the internal body: the guard is what stops it."""
    async def run():
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as c:
            return await c.get(f"{server}/to/127.0.0.1:{server.rsplit(':', 1)[1]}/internal")

    resp = asyncio.run(run())
    assert resp.status_code == 200 and resp.json() == INTERNAL_BODY


def test_red_the_redirect_chain_is_bounded(server, monkeypatch):
    """With the hop check held open, only the cap can stop an endless chain."""
    assert getattr(pull, "fetch_agent_card", None), "fetch_agent_card is missing"
    monkeypatch.setattr(pull, "_redirect_hop_ok", lambda url: True, raising=True)
    resp, refusal = _fetch(f"{server}/chain")
    assert resp is None and isinstance(refusal, _refusal_class()), f"the chain was not bounded: {resp}"
    assert "redirect" in str(refusal).lower()


def test_a_plain_200_and_a_304_still_come_back(server):
    resp, refusal = _fetch(f"{server}/card")
    assert refusal is None and resp is not None and resp.status_code == 200 and resp.json() == CARD
    assert resp.headers.get("etag") == '"v1"'
    resp, refusal = _fetch(f"{server}/notmodified")
    assert refusal is None and resp is not None and resp.status_code == 304


def test_red_a_body_that_is_not_an_agent_card_is_not_merged():
    looks = getattr(pull, "_looks_like_agent_card", None)
    assert callable(looks), "_looks_like_agent_card is missing: any internal JSON still merges into a public card"
    assert looks(CARD) is True
    assert looks({"name": "v0.3 shape", "url": "https://agent.example/a2a"}) is True
    for body in (INTERNAL_BODY, {"result": "ok"}, [], "a string", None, {"name": 5, "url": "https://x.example"}):
        assert looks(body) is False, body


def test_red_both_fetch_sites_use_the_guarded_fetch():
    tree = ast.parse(SRC.read_text())
    clients = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("AsyncClient")]
    assert clients, "no client is built in this module any more: check the test, not the code"
    for call in clients:
        for kw in call.keywords:
            assert not (kw.arg == "follow_redirects" and getattr(kw.value, "value", None) is True), ast.unparse(call)
    for name in ("_pull_one", "trigger_pull_for_did"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
        assert "fetch_agent_card" in calls, f"{name} does not go through the guarded fetch"
        assert "client.get" not in calls, f"{name} still fetches without the hop check"


def test_red_the_https_rule_is_a_hostname_check():
    from agentvault.models.agent_card import AgentCard

    check = getattr(AgentCard, "check_url_scheme", None)
    if check is None or not callable(check):  # pydantic keeps the function in its decorator registry
        check = AgentCard.__pydantic_decorators__.field_validators["check_url_scheme"].func
        call = lambda v: check(AgentCard, v)  # noqa: E731
    else:
        call = lambda v: check(v)  # noqa: E731
    for good in ("https://agent.example/a2a", "http://localhost:8000/a2a", "http://localhost/a2a"):
        assert call(good) == good, good
    for bad in ("http://localhost.attacker.example.com/a2a", "http://localhost-evil.example/a2a",
                "http://agent.example/a2a"):
        with pytest.raises(ValueError):
            call(bad)
