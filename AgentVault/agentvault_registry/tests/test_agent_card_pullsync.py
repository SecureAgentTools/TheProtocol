"""§FEDSYNCTRUTH — the pull-sync cursor: every attempt is stamped, failures back off, unreachable hosts are
not candidates, and each HTTP outcome leaves the row where the next cycle expects it (no network: MockTransport)."""
import asyncio
import os
import re
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import httpx  # noqa: E402

from agentvault_registry.background_tasks import agent_card_pullsync as ps  # noqa: E402


def _row(url="https://agent.probe-fixture.net/api/a2a", etag=None, failures=0):
    card = {
        "name": "Probe", "description": "d", "url": url,
        "supportedInterfaces": [{"url": url, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "federation_metadata": {},
    }
    # the worker canonicalises what it pulls before diffing; store the same canonical shape so an
    # identical response is, correctly, "no drift" (a non-canonical fixture reads as drift)
    card = ps.canonicalize_card_data(card)
    return SimpleNamespace(agent_did="did:theprotocol:test-1", card_data=card, last_pulled_at=None, last_pulled_etag=etag,
                           last_pull_attempt_at=None, last_pull_status=None, pull_failures=failures)


def _stats():
    return {"candidates": 0, "fetched_200": 0, "fetched_304": 0, "fetched_4xx": 0, "fetched_5xx": 0, "fetched_timeout": 0,
            "skipped_internal": 0, "drift_agents": 0, "drift_field_counts": {}, "errors": 0, "last_pull_per_agent": {}}


def _run(handler, row):
    stats = _stats()
    transport = httpx.MockTransport(handler)

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            await ps.AgentCardPullSync()._pull_one(None, client, row, stats)
    asyncio.run(go())
    return stats


def test_backoff_doubles_per_failure_and_caps_at_a_week():
    assert ps._backoff_seconds(0) == ps._INTERVAL_SEC
    assert ps._backoff_seconds(1) == 2 * ps._INTERVAL_SEC
    assert ps._backoff_seconds(3) == min(8 * ps._INTERVAL_SEC, ps._BACKOFF_CAP_SEC)
    assert ps._backoff_seconds(40) == ps._BACKOFF_CAP_SEC
    assert ps._backoff_seconds(-3) == ps._INTERVAL_SEC


def test_stamp_moves_the_cursor_on_every_outcome_and_only_success_resets_failures():
    r = _row(failures=2)
    ps._stamp_attempt(r, "4xx", False)
    assert r.last_pull_attempt_at is not None and r.last_pull_status == "4xx" and r.pull_failures == 3
    ps._stamp_attempt(r, "304", True)
    assert r.pull_failures == 0 and r.last_pull_status == "304"
    ps._stamp_attempt(r, "a-status-name-longer-than-sixteen", False)
    assert len(r.last_pull_status) == 16 and r.pull_failures == 1


def test_the_sql_prefilter_agrees_with_the_python_skip_rule():
    """The query's regex (Postgres `~*`) and `_is_skippable_host` must draw the same line; the SQL
    twin exists only so unreachable hosts never occupy a slot, the Python rule stays the authority."""
    rx = re.compile(ps._INTERNAL_URL_SQL_REGEX, re.I)
    internal = ["http://localhost:8000/api", "http://127.0.0.1/x", "http://10.0.0.5:8000/", "http://172.16.0.9/",
                "http://192.168.1.4:9000/a", "http://8.8.8.8/", "http://sim-agent:8000/api", "http://temp-test-agent:8080",
                "http://host.docker.internal:1234/",
                # special-use TLDs never resolve (RFC 6761 / 6762): the spawned sim children and the probe fixtures
                "https://sub-129d376f-bb3b-b903-1563.agents.local/a2a", "https://liab-e2e.agents.local:8443/x",
                "https://extmtls-probe.invalid/x", "http://foo.example/", "https://a.b.test/api", "http://x.localhost/"]
    public = ["https://veridian.theprotocol.cloud/api/witness", "https://sim-agent-7.theprotocol.cloud/a2a",
              "https://op-berlin.op.theprotocol.cloud/api", "https://agent.probe-fixture.net/api/a2a",
              # a reserved word in the MIDDLE of a real hostname is not a reserved TLD
              "https://pocket7-b.invalid.example.theprotocol.cloud/a2a", "https://epa-8c23c2.probe.invalid.theprotocol.cloud/x"]
    for u in internal:
        assert rx.search(u), u
        assert ps._is_skippable_host(u), u
    for u in public:
        assert not rx.search(u), u
        assert not ps._is_skippable_host(u), u
    # the candidate must also CARRY a scheme+host — a card with no interface URL is not a candidate
    # (bake 1 measured 97 of 100 slots going to such cards, each one stamped `skipped`)
    sh = re.compile(ps._SCHEME_HOST_SQL_REGEX, re.I)
    for u in public + internal:
        assert sh.search(u), u
    for u in ["", "example.invalid/agent", "/relative/path", "did:theprotocol:abc"]:
        assert not sh.search(u), u
    assert "card_data->>'url'" not in ps._CANDIDATE_URL_SQL_EXPR      # the ONE field the Python reads


def test_sandbox_mode_keeps_docker_names_as_candidates_in_both_rules(monkeypatch):
    """§pass47 B8 — in sandbox mode IPv4 literals and single-label docker names are reachable; the SQL
    twin must agree with the Python rule THERE too (bake 1-3's constant regex silently did not)."""
    monkeypatch.setattr(ps, "_is_sandbox_mode", lambda: True)
    rx = re.compile(ps._internal_url_sql_regex(), re.I)
    for u in ["http://temp-test-agent:8080/x", "http://10.0.0.5:8000/", "http://8.8.8.8/"]:
        assert not rx.search(u), u
        assert not ps._is_skippable_host(u), u
    for u in ["http://localhost:8000/api", "http://host.docker.internal:1234/", "https://sub-1.agents.local/a2a",
              "https://p.invalid/x"]:
        assert rx.search(u), u
        assert ps._is_skippable_host(u), u
    monkeypatch.setattr(ps, "_is_sandbox_mode", lambda: False)
    assert ps._internal_url_sql_regex() == ps._INTERNAL_URL_SQL_REGEX
    assert re.compile(ps._internal_url_sql_regex(), re.I).search("http://temp-test-agent:8080/x")


def test_the_candidate_field_is_supported_interfaces_only():
    """`_well_known_url_for` reads supportedInterfaces[0].url and nothing else — a url-only legacy
    card yields None (skipped), so the SQL prefilter must exclude it up front."""
    iface = {"supportedInterfaces": [{"url": "https://agent.probe-fixture.net/api/a2a"}], "url": "https://ignored.example/x"}
    assert ps._well_known_url_for(iface) == "https://agent.probe-fixture.net/.well-known/agent-card.json"
    assert ps._well_known_url_for({"supportedInterfaces": [{"url": "https://sub-1.agents.local/a2a"}]}) is None
    assert ps._well_known_url_for({"url": "https://canary.frame-c.theprotocol.cloud/canary-c-1"}) is None
    assert ps._well_known_url_for({"supportedInterfaces": [], "url": "https://example.invalid/agent"}) is None
    assert ps._well_known_url_for({"supportedInterfaces": [{"url": "example.invalid/agent"}]}) is None
    assert ps._well_known_url_for({}) is None


def test_200_without_drift_stamps_success_and_pulled():
    def handler(req):
        assert req.url.path == "/.well-known/agent-card.json"
        return httpx.Response(200, json=_row().card_data, headers={"etag": "W/\"v1\""})
    r = _row(failures=4); st = _run(handler, r)
    assert st["fetched_200"] == 1 and st["drift_agents"] == 0
    assert r.last_pulled_at is not None and r.last_pulled_etag == 'W/"v1"'
    assert r.last_pull_status == "200" and r.pull_failures == 0 and r.last_pull_attempt_at is not None


def test_304_stamps_success_without_touching_the_etag():
    def handler(req):
        assert req.headers.get("if-none-match") == 'W/"v1"'
        return httpx.Response(304)
    r = _row(etag='W/"v1"', failures=1); st = _run(handler, r)
    assert st["fetched_304"] == 1 and r.last_pulled_at is not None and r.last_pulled_etag == 'W/"v1"'
    assert r.last_pull_status == "304" and r.pull_failures == 0


def test_404_and_500_stamp_failures_and_never_touch_the_stored_card():
    r = _row(); st = _run(lambda req: httpx.Response(404), r)
    assert st["fetched_4xx"] == 1 and r.last_pulled_at is None and r.last_pull_status == "4xx" and r.pull_failures == 1
    r2 = _row(failures=1); st2 = _run(lambda req: httpx.Response(503), r2)
    assert st2["fetched_5xx"] == 1 and r2.last_pull_status == "5xx" and r2.pull_failures == 2 and r2.last_pulled_at is None


def test_timeout_and_dead_hostname_are_attempts_too():
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)
    r = _row(); st = _run(timeout, r)
    assert st["fetched_timeout"] == 1 and r.last_pull_status == "timeout" and r.pull_failures == 1

    def dead(req):
        raise httpx.ConnectError("name resolution failed", request=req)
    r2 = _row(failures=5); st2 = _run(dead, r2)
    assert st2["errors"] == 1 and r2.last_pull_status == "error" and r2.pull_failures == 6
    assert r2.last_pull_attempt_at is not None        # the cursor moved — the old code left it NULL forever


def test_an_internal_host_is_stamped_skipped_if_it_ever_reaches_the_worker():
    r = _row(url="http://localhost:8000/api"); st = _run(lambda req: httpx.Response(200, json={}), r)
    assert st["skipped_internal"] == 1 and r.last_pull_status == "skipped" and r.pull_failures == 1


def test_candidate_query_shape_pins_the_field_the_filters_and_the_priority():
    """Compile the candidate SELECT for Postgres and pin what matters: the ONE candidate field, the
    scheme+host and internal-host filters, the backoff window, the slot limit, and the PRIORITY —
    never-attempted and live cards (pull_failures = 0) before anything in backoff."""
    from sqlalchemy.dialects import postgresql
    sql = str(ps._candidate_stmt().compile(dialect=postgresql.dialect()))
    assert ps._CANDIDATE_URL_SQL_EXPR in sql
    assert "card_data->>'url'" not in sql
    assert "~* %(scheme_re)s" in sql and "!~* %(internal_re)s" in sql
    assert "last_pull_attempt_at IS NULL OR last_pull_attempt_at <" in sql
    assert "LIMIT" in sql
    order = sql.split("ORDER BY", 1)[1]
    i_fail, i_att, i_pulled = order.find("pull_failures"), order.find("last_pull_attempt_at"), order.find("last_pulled_at")
    assert 0 <= i_fail < i_att < i_pulled, order


def _clear_own_hosts(monkeypatch):
    for key in ps._OWN_HOST_ENV_KEYS + ("AGENT_CARD_PULLSYNC_OWN_HOSTS",):
        monkeypatch.delenv(key, raising=False)


def test_the_registrys_own_hosts_are_not_candidates_in_either_rule(monkeypatch):
    """§ALERTFIX — a card on the registry's own host is a card it hosts itself: one root document for all of them
    (EU: 26 cards, one 404). Both rules refuse it; an agent on its own host, or a lookalike host, stays a candidate."""
    _clear_own_hosts(monkeypatch)
    own = "https://eu.theprotocol.cloud/agents/weather-agent/a2a"
    assert ps._own_hosts() == frozenset() and ps._own_host_sql_regex() is None
    assert not ps._is_skippable_host(own)            # the control: nothing configured, nothing skipped
    monkeypatch.setenv("PUBLIC_URL", "https://eu.theprotocol.cloud")
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud/")
    monkeypatch.setenv("AGENT_CARD_PULLSYNC_OWN_HOSTS", "api.theprotocol.cloud, not a host!")
    assert ps._own_hosts() == {"eu.theprotocol.cloud", "theprotocol.cloud", "api.theprotocol.cloud"}
    rx = re.compile(ps._own_host_sql_regex(), re.I)
    for u in [own, "https://eu.theprotocol.cloud/agents/eu-1-sender", "https://EU.theprotocol.cloud:443/x",
              "https://theprotocol.cloud/agents/x/a2a", "https://api.theprotocol.cloud/a2a"]:
        assert rx.search(u), u
        assert ps._is_skippable_host(u), u
        assert ps._well_known_url_for({"supportedInterfaces": [{"url": u}]}) is None, u
    for u in ["https://boris.theprotocol.cloud/a2a", "https://veridian.theprotocol.cloud/api/witness",
              "https://eu.theprotocol.cloud.evil.net/a2a", "https://xeu.theprotocol.cloud/a2a"]:
        assert not rx.search(u), u
        assert not ps._is_skippable_host(u), u


def test_the_candidate_query_carries_the_own_host_filter_only_when_hosts_are_known(monkeypatch):
    from sqlalchemy.dialects import postgresql
    _clear_own_hosts(monkeypatch)
    assert "own_re" not in str(ps._candidate_stmt().compile(dialect=postgresql.dialect()))
    monkeypatch.setenv("BASE_URL", "https://asia.theprotocol.cloud")
    sql = str(ps._candidate_stmt().compile(dialect=postgresql.dialect()))
    assert "!~* %(own_re)s" in sql and "~* %(scheme_re)s" in sql and "LIMIT" in sql
