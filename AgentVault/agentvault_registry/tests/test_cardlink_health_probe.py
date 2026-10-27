"""§CARDLINK (2026-09-08) — the health probe must answer ITS OWN question.

His report was that published card addresses are dead. They were — and this worker called
thirty of them `healthy`, because `_origin_health()` reduced
`https://eu.theprotocol.cloud/agents/weather-agent/a2a` to `https://eu.theprotocol.cloud/health`,
the FRAME's own page, which is 200 by definition. The probe substituted an easier question and
its answer then endorsed the defect.

⚠ THE CONTROL THAT MATTERS IS THE FIRST ONE: a 404 on the declared address must read
`unhealthy`. Under the old rule it read `healthy`, so this file fails on the code it replaced —
which is the only thing that makes it a gate rather than a description.
"""
import asyncio

import pytest

from agentvault_registry.background_tasks import agent_health_checker as ahc


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class _Client:
    """Answers per (method, url); anything unnamed raises, which is a transport failure."""

    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    async def request(self, method, url, **kw):
        self.seen.append((method, url))
        key = (method, url)
        if key in self.answers:
            return _Resp(self.answers[key])
        if url in self.answers:
            return _Resp(self.answers[url])
        raise ConnectionError("no route to host")

    async def get(self, url, **kw):
        return await self.request("GET", url, **kw)


URL = "https://eu.theprotocol.cloud/agents/weather-agent/a2a"


def _run(coro):
    # §DEPS: pytest-asyncio 1.x leaves no current event loop for a synchronous test, so a shared-loop lookup
    # passes or fails by test order; a private loop does not depend on what ran before.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.parametrize("status,expected", [
    (404, "unhealthy"),   # THE ONE THAT WAS LOST: nothing is published at this address
    (410, "unhealthy"),
    (405, "healthy"),     # GET on a JSON-RPC route — the address EXISTS
    (402, "healthy"),     # unpaid A2A call — the agent itself answered
    (401, "healthy"),
    (200, "healthy"),
    (503, "unhealthy"),   # there, and broken
])
def test_declared_address_decides(status, expected):
    c = _Client({("HEAD", URL): status, ("GET", URL): status})
    verdict, _detail = _run(ahc._probe_declared(c, URL))
    assert verdict == expected, f"{status} should read {expected}, got {verdict}"


def test_no_answer_at_all_is_unreachable_not_unhealthy():
    """A DNS/connect failure and a 404 are different facts and must not share a word."""
    verdict, _ = _run(ahc._probe_declared(_Client({}), URL))
    assert verdict == "unreachable"


def test_head_404_asks_get_before_concluding():
    """A HEAD and a GET can genuinely disagree; the probe asks the other one."""
    c = _Client({("HEAD", URL): 404, ("GET", URL): 405})
    verdict, _ = _run(ahc._probe_declared(c, URL))
    assert verdict == "healthy"
    assert ("GET", URL) in c.seen


def test_own_host_is_not_a_dedicated_origin(monkeypatch):
    """The frame's own /health is a fact about the FRAME. It must not answer for an agent."""
    monkeypatch.setenv("PUBLIC_UI_URL", "https://eu.theprotocol.cloud")
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.delenv("MAINFRAME_PUBLIC_URL", raising=False)
    assert ahc._origin_is_dedicated(URL) is False
    # …while a sovereign subdomain is one host for one agent, which is §COCKPITA's real case.
    assert ahc._origin_is_dedicated("https://hagrid.theprotocol.cloud/api/terminal/query") is True


def test_unknown_own_host_still_allows_the_fallback(monkeypatch):
    """With nothing configured we cannot say a host is ours, so we do not claim it is."""
    for k in ("PUBLIC_UI_URL", "BASE_URL", "PUBLIC_URL", "MAINFRAME_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    assert ahc._origin_is_dedicated(URL) is True


# ─── the READ side: what a card read publishes about its own address ──────────────────────
# §CARDLINK (2026-09-08). The probe above decides the word; this decides whether anyone can
# SEE it. Measured before this: an anonymous `/explore` visitor opened a card the discover rail
# already knew was `unhealthy` and the modal showed "not checked from this registry", because
# `endpoint_health` shipped on /agent-cards/discover only and the modal falls through to
# /agent-cards/{id} whenever its list cache is empty — which is every anonymous visit.

class _Card:
    """The fields the read builder actually touches."""
    def __init__(self, agent_did="did:x:1"):
        import datetime as _dt
        self.id = "0a1b2c3d-1111-4a4a-8b8b-000000000001"
        self.agent_did = agent_did
        self.developer_id = 1
        self.card_data = {"name": "X"}
        self.name = "X"
        self.description = ""
        self.is_active = True
        self.unlisted = False
        self.created_at = _dt.datetime(2026, 9, 8)
        self.updated_at = _dt.datetime(2026, 9, 8)
        self.developer = None


def _build(health):
    from agentvault_registry.routers import agent_cards as ac
    return ac._build_agent_card_read_dict(_Card(), health=health)


def test_a_read_publishes_the_word_the_probe_chose():
    d = _build(("unhealthy", None))
    assert d["endpoint_health"] == "unhealthy"


def test_never_probed_here_is_null_not_a_guess():
    """A federated mirror has no local agent row. Null is the THIRD state, not 'dead'."""
    for h in (None, (None, None), ("", None)):
        assert _build(h)["endpoint_health"] is None, f"{h!r} must publish null, not a verdict"


def test_the_checked_timestamp_rides_along():
    import datetime as _dt
    when = _dt.datetime(2026, 9, 8, 4, 43, 22)
    assert _build(("healthy", when))["endpoint_checked_at"] == when
