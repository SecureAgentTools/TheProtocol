"""§SUITES1018 (2026-10-18): the api-tester reports what it measured, and only that.

Measured on the 2026-10-18 sweep of sbx-alpha (1,269 rows):
  * 92 rows the tester never called (a destructive, cross-frame, manual-only or WebSocket route) answered healthy=True,
    status 200, 1 ms: counted as passes, and three of them then "failed" the EventStore check for events no call could
    have emitted. A skip is now NOT MEASURED: healthy False, no status, the reason, and `unmeasured` so every summary
    keeps it out of the rate.
  * 157 rows answering 4xx counted as PASSES (an accepted refusal: "no arena match on a clean sandbox: 404"). A refusal
    the harness accepts is an EXPECTED FAILURE, as the contract layer has always stamped one.
  * the classifiers withheld reads: GET /admin/simulation/fund-status ("/simulation/fund"), GET /chat/blocks
    ("/block"), every GET under /frame-invitations and /governance/federation/. A read is never destructive.
  * the infra reason said the peer was "not present on the single-frame sandbox"; the sandbox has been a federated pair
    since 2026-09.
  * every peer-only federation route was refused: the tester declared Frame A's agentvault.com (untrusted on every
    sandbox frame) or, inline, a literal secret of the retired tier. It now declares an ACTIVE peer frame's identity, or
    for the routes a frame's own operator calls that operator's, read from the registry's own peer rows.

RED on 9ac0925c (each test named test_red_*): the behaviour described above is absent there.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests import auth_manager as AM
from agentvault_registry.api_tests import base as B


# ── a row the tester did not call is NOT MEASURED ────────────────────────────────────────────────────────────────────

def _skip(method, path):
    return asyncio.run(B.APITestBase(base_url="http://127.0.0.1:1").test_endpoint(method=method, path=path,
                                                                                    auth_type="developer"))


@pytest.mark.parametrize("method,path,kind", [
    ("POST", "/admin/developers/{developer_id}/suspend", "destructive"),
    ("POST", "/teg/cross-registry-transfer", "infra_gated"),
    ("POST", "/auth/2fa/backup-codes", "manual_only"),
    ("POST", "/teg/batch-transfer", "unbuilt"),
    ("GET", "/ws/events", "websocket"),
])
def test_red_a_skipped_row_is_not_measured_never_a_pass(method, path, kind):
    r = _skip(method, path)
    assert r["healthy"] is False and r["statusCode"] is None, r
    assert r["not_measured"] is True and r["unmeasured"] is True and r["not_measured_reason"], r
    assert r["failure_bucket"] == f"not_measured_{kind}" and r["expected_failure"] is False, r


def test_red_a_category_summary_leaves_not_measured_rows_out_of_its_rate():
    rows = [{"healthy": True}, {"healthy": False}, B.not_measured_result("POST", "/x/suspend", "developer",
                                                                       "destructive", "why")]
    assert B._summarize_results(rows) == {"total": 2, "healthy": 1, "unhealthy": 1, "percentage": 50.0,
                                          "not_measured": 1}


# ── reads run ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/admin/simulation/fund-status", "/chat/blocks", "/agent/revoked-identities",
                                  "/admin/federation/frame-invitations", "/governance/federation/proposals",
                                  "/bridge/status/{bridge_tx_id}", "/oauth/federation/status"])
def test_red_a_read_is_never_withheld(path):
    assert B._classify_destructive("GET", path) == "" and B._classify_infra_gated("GET", path) == "", path


def test_control_the_same_routes_as_writes_are_still_withheld():
    assert B._classify_destructive("POST", "/admin/simulation/fund")
    assert B._classify_destructive("POST", "/chat/blocks")
    assert B._classify_infra_gated("POST", "/admin/federation/frame-invitations/{invitation_id}/reject")


def test_red_a_proxy_shell_is_not_an_endpoint_and_the_reason_names_no_single_frame_sandbox():
    shell = B._classify_infra_gated("GET", "/sandbox/es/{path}")
    assert "not an endpoint" in shell, shell
    action = B._classify_infra_gated("POST", "/teg/cross-registry-transfer")
    assert action and "single-frame" not in action and "counterparty" in action, action


# ── a refusal the harness accepts is an EXPECTED FAILURE ─────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.content = b"x"
        self.url = "http://t/api/v1/x"

    def json(self):
        return self._body


def _answered(monkeypatch, method, path, status, body):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, **kw):
            return _Resp(status, body)
    monkeypatch.setattr(B.httpx, "AsyncClient", _Client)
    t = B.APITestBase(base_url="http://127.0.0.1:1")
    t._dynamic_ids["_populated"] = True
    return asyncio.run(t.test_endpoint(method=method, path=path, auth_type="none"))


@pytest.mark.parametrize("method,path,status,body", [
    ("POST", "/staking/claim-rewards", 404, {"detail": "Payouts on locked units are not claimed"}),
    ("GET", "/arena/matches/{match_id}", 404, {"detail": "Match not found"}),
    ("POST", "/teg/rewards/x", 400, {"error": {"detail": "No payouts to claim"}}),
    ("POST", "/x/a-route-declared-unbuilt", 501, {"detail": "not implemented"}),
])
def test_red_an_accepted_refusal_is_an_expected_failure_not_a_pass(monkeypatch, method, path, status, body):
    r = _answered(monkeypatch, method, path, status, body)
    assert r["healthy"] is True and r["expected_failure"] is True, r
    assert r["failure_bucket"] == "accepted_refusal" and r["expected_failure_reason"], r


def test_red_410_gone_is_a_deliberate_answer(monkeypatch):
    r = _answered(monkeypatch, "POST", "/x/a-retired-route", 410, {"detail": "retired: use /y"})
    assert r["healthy"] is True and r["expected_failure"] is True and "retired: use /y" in r["expected_failure_reason"], r


def test_control_a_refusal_nobody_accepted_stays_a_failure(monkeypatch):
    r = _answered(monkeypatch, "POST", "/staking/claim-rewards", 409, {"detail": "something else"})
    assert r["healthy"] is False and not r["expected_failure"], r


def test_control_a_2xx_is_a_pass(monkeypatch):
    r = _answered(monkeypatch, "GET", "/arena/matches/{match_id}", 200, {"id": 1})
    assert r["healthy"] is True and not r["expected_failure"], r


def test_red_a_placeholder_key_matches_the_substituted_path():
    # the router substitutes placeholders BEFORE the classifier, so "{did}" must stand for a segment
    did_path = "/developers/me/agents/did:theprotocol:sandbox-a.theprotocol.cloud:dc20/reputation-bond/unlock"
    assert B._classify_expected_4xx("POST", did_path, 409, {"detail": "No locked or matured bond"})
    assert not B._classify_expected_4xx("POST", "/developers/me/agents/a/b/reputation-bond/unlock", 409,
                                        {"detail": "x"})


def test_red_the_operator_lane_is_an_accepted_refusal_and_peer_routes_are_not():
    assert B._classify_expected_4xx("GET", "/federation/operator-self/logs", 401, {"detail": "operator lane"})
    for p in ("/federation/peers", "/federation/sync-digest", "/federation/guild/board"):
        assert not B._classify_expected_4xx("GET", p, 403, {"detail": "refused"}), p


# ── the federation identity is a real peer's, derived from the registry's own rows ──────────────────────────────────

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, q):
        self.queries.append(str(q))
        wanted = "cloud_operator" if "cloud_operator" in str(q.compile(compile_kwargs={"literal_binds": True})) \
            else "frame"
        return _Rows([(td, sid) for (kind, td, sid) in self.rows if kind == wanted])


@pytest.fixture()
def peers(monkeypatch):
    import agentvault_registry.database as D
    rows = [("frame", "sandbox-a.theprotocol.cloud", None),            # never this frame itself
            ("frame", "sandbox-b.theprotocol.cloud", None),
            ("cloud_operator", "sandbox-a.theprotocol.cloud",
             "spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/registry"),
            ("cloud_operator", "sandbox-b.theprotocol.cloud",        # another frame's operator: not ours
             "spiffe://sandbox-b.theprotocol.cloud/operator/sbxbetaop/registry")]
    monkeypatch.setattr(D, "AsyncSessionLocal", lambda: _Session(rows))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.theprotocol.cloud")
    monkeypatch.delenv("API_TEST_FEDERATION_SPIFFE_ID", raising=False)


def test_red_a_peer_route_is_called_as_the_active_peer_frame(peers):
    assert asyncio.run(AM.federation_spiffe_id("/federation/sync-digest")) == \
        "spiffe://sandbox-b.theprotocol.cloud/service/registry"


def test_red_an_operator_route_is_called_as_this_frames_own_operator(peers):
    assert asyncio.run(AM.federation_spiffe_id("/federation/licence/mine")) == \
        "spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/registry"


def test_control_an_explicit_identity_wins(peers, monkeypatch):
    monkeypatch.setenv("API_TEST_FEDERATION_SPIFFE_ID", "spiffe://x.example/service/registry")
    assert asyncio.run(AM.federation_spiffe_id("/federation/peers")) == "spiffe://x.example/service/registry"


def test_control_no_peer_frame_means_no_identity(monkeypatch):
    import agentvault_registry.database as D
    monkeypatch.setattr(D, "AsyncSessionLocal", lambda: _Session([("frame", "sandbox-a.theprotocol.cloud", None)]))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.theprotocol.cloud")
    monkeypatch.delenv("API_TEST_FEDERATION_SPIFFE_ID", raising=False)
    assert asyncio.run(AM.federation_spiffe_id("/federation/peers")) == ""


def test_red_the_mtls_headers_carry_the_derived_identity_and_no_literal(peers, monkeypatch):
    monkeypatch.setenv("FEDERATION_INTERNAL_SECRET", "s" * 48)
    h = asyncio.run(AM.AuthManager().get_headers(auth_type="mtls", path="/federation/sync-digest"))
    assert h["X-Federation-SPIFFE-ID"] == "spiffe://sandbox-b.theprotocol.cloud/service/registry", h
    assert "agentvault.com" not in str(h)


# ── inputs the 2026-10-18 sweep never sent ───────────────────────────────────────────────────────────────────────────

def test_red_the_required_query_parameters_are_supplied(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    D = R._REQUIRED_QUERY_DEFAULTS
    for p in ("/public/geocode", "/frame-kit/download", "/federation/ironkey/delegations-for-issuer",
              "/federation/ironkey/issuer-authority", "/federation/fx/parked-at", "/federation/contract-digest"):
        assert p in D, p
    dv = {"agent_did": "did:theprotocol:sandbox-a.theprotocol.cloud:abc"}
    assert D["/federation/ironkey/delegations-for-issuer"](dv) == "issuer_did=did:theprotocol:sandbox-a.theprotocol.cloud:abc"
    monkeypatch.setenv("FX_ROUTE_PEERS", '[{"currency": "SBXB", "router_did": "did:theprotocol:sandbox-b:fx"}]')
    assert D["/federation/fx/parked-at"](dv) == "router_did=did:theprotocol:sandbox-b:fx"
    monkeypatch.setenv("FX_ROUTE_PEERS", "")
    assert D["/federation/fx/parked-at"](dv) is None


def test_red_the_bodies_name_what_the_route_checks(monkeypatch):
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    from agentvault_registry.core import legal_versions as L
    rb = RequestBodies()
    assert rb.get_body("/legal/accept") == {"document": "terms", "version": L.current_version("terms")}
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.theprotocol.cloud")
    assert rb.get_body("/public/reach-probe") == {"public_name": "sandbox-a.theprotocol.cloud"}
    q = rb.get_body("/public/directory/graphql")
    assert q["query"].startswith("query(") and q["variables"] == {"n": 3}
    assert rb.get_body("/developers/me/agents/{did}/reputation-bond") == {"funder_did": "__AGENT_DID__"}


# ── the peer-only writes: called as a peer only with a body refused before it acts ──────────────────────────────────

def test_red_a_peer_write_with_no_vetted_body_is_never_called(monkeypatch):
    def _no_call(*a, **k):
        raise AssertionError("the tester called a peer write with no vetted body")
    monkeypatch.setattr(B.httpx, "AsyncClient", _no_call)
    r = asyncio.run(B.APITestBase(base_url="http://127.0.0.1:1").test_endpoint(
        method="POST", path="/federation/some-future-peer-write", auth_type="mtls", body=None))
    assert r["not_measured"] is True and r["failure_bucket"] == "not_measured_peer_write", r


def test_red_every_peer_write_the_sweep_calls_has_its_vetted_body_and_its_expected_refusal():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    for key in B.PEER_WRITE_REFUSALS:
        if key == "/federation/sync-request":
            continue   # sent by the router's own federation block, with the catalog body checked below
        assert rb.get_body(key) is not None, key


def test_red_the_dangerous_peer_writes_carry_their_safe_bodies():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    # an empty body funds every canary sender from the treasury: only a dry run is ever sent
    assert rb.get_body("/federation/canary-refill") == {"dry_run": True}
    # a probe without a LOCAL source moves units: the sweep names a source that is not homed anywhere
    probe = rb.get_body("/federation/ironhand-probe")
    assert probe["source_did"].startswith("did:theprotocol:apitest-not-local"), probe
    # an accepted sync from the peer would stamp its last_synced_at: the source is never a real registry
    sync = rb.get_body("/federation/sync-request")
    assert sync["source_registry"] == "spiffe://apitest.invalid/service/registry" and sync["agent_cards"] == []
    # a real template would send mail
    assert rb.get_body("/federation/mail-relay")["template"] == "apitest-none"


def test_red_the_synthesizer_never_writes_a_peer_body():
    from agentvault_registry.routers import admin_api_test as R
    for p in ("/federation/canary-refill", "/federation/ironhand-probe", "/federation/mail-relay",
              "/federation/agora-order", "/federation/guild/stake"):
        assert R._body_synthesis_allowed(p, "POST") is False, p


def test_red_the_slash_routes_are_out_of_the_federation_block():
    import inspect
    from agentvault_registry.routers import admin_api_test as R
    line = next(ln for ln in inspect.getsource(R.test_endpoint).splitlines() if "_federation_mtls_paths = {" in ln)
    assert "slash" not in line, line
    assert B._classify_destructive("POST", "/federation/disputes/slash-request")


def test_red_a_peer_write_refusal_is_an_expected_failure(monkeypatch):
    r = _answered_as(monkeypatch, "POST", "/federation/ironhand-probe", 400,
                     {"detail": "source_did must be an agent registered on this registry"},
                     body={"source_did": "did:theprotocol:apitest-not-local"})
    assert r["healthy"] is True and r["expected_failure"] is True and "refused before it acts" in r["expected_failure_reason"], r
    assert "source_did must be an agent registered" in r["expected_failure_reason"], r   # the route's own sentence


def test_red_a_peer_write_reason_belongs_to_its_own_route_only():
    assert B._classify_peer_write_refusal("POST", "/federation/agora-order", 404, {"detail": "listing not found"})
    # a sibling sharing the prefix is not the same route
    assert not B._classify_peer_write_refusal("POST", "/federation/agora-order-status", 422, {"detail": "x"})
    assert B._classify_peer_write_refusal("POST", "/federation/guild/orders/gwo_apitest_none/bid", 403, {"detail": "x"})


def test_control_a_peer_write_that_acted_is_not_hidden(monkeypatch):
    r = _answered_as(monkeypatch, "POST", "/federation/ironhand-probe", 200, {"ok": True, "moved": "10"},
                     body={"source_did": "did:theprotocol:apitest-not-local"})
    assert r["healthy"] is True and not r["expected_failure"], r      # a 2xx stays a pass the reader can see
    r = _answered_as(monkeypatch, "POST", "/federation/ironhand-probe", 500, {"detail": "boom"},
                     body={"source_did": "did:theprotocol:apitest-not-local"})
    assert r["healthy"] is False and not r["expected_failure"], r


def test_red_a_refusal_in_the_body_of_a_2xx_is_no_pass(monkeypatch):
    r = _answered_as(monkeypatch, "POST", "/federation/canary-fire", 200,
                     {"ok": False, "error": "no local canary path id=-1"}, body={"remote_path_id": -1})
    assert r["healthy"] is True and r["expected_failure"] is True, r


def _answered_as(monkeypatch, method, path, status, body_out, body):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, **kw):
            return _Resp(status, body_out)
    monkeypatch.setattr(B.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(AM, "federation_spiffe_id", _fixed_identity)
    t = B.APITestBase(base_url="http://127.0.0.1:1")
    t._dynamic_ids["_populated"] = True
    return asyncio.run(t.test_endpoint(method=method, path=path, auth_type="mtls", body=body))


async def _fixed_identity(path=""):
    return "spiffe://sandbox-b.theprotocol.cloud/service/registry"


# ── a runner gap is NOT MEASURED, never an expected failure ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("stamp,kind", [
    ("POST/PUT body required — runner sends empty body (no template yet)", "body"),
    ("Endpoint requires agent JWT — runner sends developer JWT", "principal"),
    ("Templated path placeholder fails validation — needs fixture data", "fixture"),
])
def test_red_a_runner_gap_stamp_leaves_the_route_not_measured(stamp, kind):
    from agentvault_registry.routers import admin_api_test as R
    r = R._runner_gap_is_not_measured({"healthy": True, "expected_failure": True, "expected_failure_reason": stamp,
                                       "statusCode": 422})
    assert r["not_measured"] is True and r["unmeasured"] is True and r["healthy"] is False, r
    assert r["expected_failure"] is False and r["failure_bucket"] == f"not_measured_runner_gap_{kind}", r
    assert "runner gap" in r["not_measured_reason"] and stamp[:20] in r["not_measured_reason"], r


def test_control_an_expected_failure_about_the_endpoint_stays_one():
    from agentvault_registry.routers import admin_api_test as R
    r = {"healthy": True, "expected_failure": True, "expected_failure_reason": "Duplicate policy prevention - working as designed"}
    assert R._runner_gap_is_not_measured(dict(r)) == r
    assert R._runner_gap_is_not_measured("a JSONResponse passes through") == "a JSONResponse passes through"


def test_red_the_route_reports_through_the_relabel():
    import inspect
    from agentvault_registry.routers import admin_api_test as R
    assert inspect.unwrap(R.test_endpoint) is not R.test_endpoint          # the exit is wrapped
    assert "endpoint_test" in inspect.signature(R.test_endpoint).parameters  # FastAPI still sees the route's parameters


# ── once the agent principal is past authentication, its answer is the route's answer ──────────────────────────────

class _Tester:
    """Answers like a route that takes an agent: the developer token is refused at auth, the agent gets `agent_answer`."""
    def __init__(self, agent_answer):
        self.agent_answer, self.calls = agent_answer, []

    async def test_endpoint(self, **kw):
        self.calls.append(kw.get("auth_type"))
        if kw.get("auth_type") == "agent":
            return dict(self.agent_answer)
        return {"healthy": False, "statusCode": 401, "error": "HTTP 401"}


def _retry(tester, path="/guild/orders/{oid}/bids"):
    from agentvault_registry.routers import admin_api_test as R
    return asyncio.run(R._retry_before_classification(
        tester, {"healthy": False, "statusCode": 401, "error": "HTTP 401"}, method="POST", path=path,
        original_path=path, auth_type="developer", body={"x": 1}, developer_token="dev", agent_token="agent"))


def test_red_the_agents_answer_stands_for_the_developers_401(monkeypatch):
    r = _retry(_Tester({"healthy": False, "statusCode": 403, "error": "HTTP 403",
                        "responseData": {"detail": "Agent lacks required permission: authz.delegate"}}))
    assert r["statusCode"] == 403 and r["principal_retry"] == "agent", r


def test_control_an_agent_refused_at_authentication_changes_nothing():
    r = _retry(_Tester({"healthy": False, "statusCode": 401, "error": "HTTP 401"}))
    assert r["statusCode"] == 401 and "principal_retry" not in r, r


def test_control_an_agent_pass_is_adopted_as_before():
    r = _retry(_Tester({"healthy": True, "statusCode": 201}))
    assert r["healthy"] is True and r["principal_retry"] == "agent", r


def test_red_a_runner_job_id_never_names_another_kind_of_job(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {"frame_runner_job_id": "69421eb6f9f84d0d", "agent_did": "did:x"})
    sandbox = asyncio.run(R.replace_path_placeholders("/admin/mcp-tester/sandbox/jobs/{job_id}/events"))
    assert sandbox == "/admin/mcp-tester/sandbox/jobs/{job_id}/events", sandbox
    runner = asyncio.run(R.replace_path_placeholders("/admin/frame-runner/jobs/{job_id}/events"))
    assert runner == "/admin/frame-runner/jobs/69421eb6f9f84d0d/events", runner


def test_red_a_guild_write_names_no_live_order(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {"guild_order_id": "gwo_live", "agent_did": "did:x"})
    assert asyncio.run(R.replace_path_placeholders("/federation/guild/orders/{oid}/bid")) == \
        "/federation/guild/orders/gwo_apitest_none/bid"
    assert asyncio.run(R.replace_path_placeholders("/federation/guild/orders/{oid}")) == "/federation/guild/orders/gwo_live"


def test_red_a_captured_conversation_reaches_the_paths(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {"conversation_id": "c0ffee00-0000-4000-8000-000000000001", "agent_did": "did:x"})
    assert asyncio.run(R.replace_path_placeholders("/chat/conversations/{conversation_id}/messages")) == \
        "/chat/conversations/c0ffee00-0000-4000-8000-000000000001/messages"


def test_red_the_root_webhook_store_is_left_to_its_own_resolver(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {"webhook_id": "dev-store-id", "agent_did": "did:x"})
    assert asyncio.run(R.replace_path_placeholders("/webhooks/{webhook_id}")) == "/webhooks/{webhook_id}"
    assert asyncio.run(R.replace_path_placeholders("/developers/me/webhooks/{webhook_id}")) == \
        "/developers/me/webhooks/dev-store-id"


def test_red_list_fixtures_serve_reads_only(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {"list_fixture:/contracts/v2/{cid}": "ctr_real", "agent_did": "did:x"})
    assert asyncio.run(R.replace_path_placeholders("/contracts/v2/{cid}", "dev", "agent", method="GET")) == \
        "/contracts/v2/ctr_real"
    # a write on the same prefix never gets a real contract
    assert "{cid}" in asyncio.run(R.replace_path_placeholders("/contracts/v2/{cid}/accept", "dev", "agent", method="POST"))
    assert "{cid}" in asyncio.run(R.replace_path_placeholders("/contracts/v2/{cid}", "dev", "agent"))   # method unknown


@pytest.mark.parametrize("method,path", [
    ("POST", "/admin/mcp-tester/run"), ("POST", "/admin/console-suite/runs"), ("POST", "/admin/mcp-tester/sandbox"),
    ("POST", "/admin/api-test/test-flow"), ("POST", "/admin/api-test/reset-flow-values"),
    ("POST", "/admin/evals/suites/{suite_id}/run"), ("POST", "/admin/evals/suites/s1/run"),
])
def test_red_the_sweep_never_starts_another_suite(monkeypatch, method, path):
    def _no_call(*a, **k):
        raise AssertionError("the sweep called a suite-launching route")
    monkeypatch.setattr(B.httpx, "AsyncClient", _no_call)
    r = asyncio.run(B.APITestBase(base_url="http://127.0.0.1:1").test_endpoint(method=method, path=path,
                                                                                auth_type="developer"))
    assert r["not_measured"] is True and r["failure_bucket"] == "not_measured_suite_launch", r


def test_control_reading_a_suites_runs_is_still_measured():
    assert B._classify_suite_launch("GET", "/admin/mcp-tester/runs") == ""
    assert B._classify_suite_launch("POST", "/admin/mcp-tester/runs/x/stop") == ""   # not a launch route


def test_red_the_router_refuses_a_suite_launch_before_any_contract(monkeypatch):
    from starlette.requests import Request
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "_delegation_target", lambda: None)
    def _no_contract(*a, **k):
        raise AssertionError("a contract was dispatched for a suite launch")
    import agentvault_registry.api_tests.core.contract as C
    monkeypatch.setattr(C, "get_contract", _no_contract)
    req = Request({"type": "http", "method": "POST", "path": "/api/v1/admin/api-test/test-endpoint", "headers": []})
    for method, path in (("POST", "/admin/api-test/reset-flow-values"), ("GET", "/admin/api-test/run-all"),
                         ("POST", "/admin/api-test/test-category")):
        r = asyncio.run(R.test_endpoint(req, {"method": method, "path": path, "body": None}, None))
        assert r["not_measured"] is True and r["failure_bucket"] == "not_measured_suite_launch", (path, r)


# ── the sweep's peer rows touch only its own fixture peer, and never leave it ACTIVE ────────────────────────────────

def test_red_a_fixture_peer_is_the_sweeps_own_and_nothing_else():
    from agentvault_registry.routers import admin_api_test as R
    assert R._is_fixture_peer({"name": "Test Federation Peer 1792334245459",
                               "base_url": "https://test-peer-1792334245459.theprotocol.test"})
    assert not R._is_fixture_peer({"name": "Sandbox Beta", "base_url": "https://sandbox-b.theprotocol.cloud:8443"})
    assert not R._is_fixture_peer({"name": "Test Federation Peer 1", "base_url": "https://real.example.org"})


class _PeerHttp:
    def __init__(self, rows):
        self.rows, self.posts = rows, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **k):
        return type("R", (), {"json": lambda _s: list(self.rows), "status_code": 200})()

    async def post(self, url, params=None, **k):
        self.posts.append((url, params))
        return type("R", (), {"status_code": 200})()


def test_red_the_approved_fixture_peer_is_retired_at_once(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    http = _PeerHttp([{"id": 33, "name": "Test Federation Peer 1792334245459", "status": "ACTIVE",
                       "base_url": "https://test-peer-1792334245459.theprotocol.test"}])
    monkeypatch.setattr(R.httpx, "AsyncClient", http)
    asyncio.run(R._retire_fixture_peer("/admin/federation/peers/{peer_id}/approve",
                                       "/admin/federation/peers/33/approve", {"healthy": True}, "dev"))
    assert http.posts and http.posts[0][0].endswith("/admin/federation/peers/33/deactivate"), http.posts


def test_control_a_real_peer_is_never_retired_by_the_sweep(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    http = _PeerHttp([{"id": 2, "name": "Sandbox Beta", "status": "ACTIVE",
                       "base_url": "https://sandbox-b.theprotocol.cloud:8443"}])
    monkeypatch.setattr(R.httpx, "AsyncClient", http)
    asyncio.run(R._retire_fixture_peer("/admin/federation/peers/{peer_id}/approve",
                                       "/admin/federation/peers/2/approve", {"healthy": True}, "dev"))
    asyncio.run(R._retire_fixture_peer("/federation/peers/{peer_id}", "/federation/peers/2", {"healthy": True}, "dev"))
    assert http.posts == [], http.posts


def test_red_a_request_validation_422_is_a_runner_gap():
    from agentvault_registry.routers import admin_api_test as R
    r = R._runner_gap_is_not_measured({"healthy": False, "statusCode": 422, "responseData": {
        "error": {"detail": "Field required", "code": "VALIDATION_FAILED", "field": "query -> receiver_did"}}})
    assert r["not_measured"] is True and r["failure_bucket"] == "not_measured_runner_gap_input", r
    assert "query -> receiver_did" in r["not_measured_reason"], r


def test_control_a_handler_422_stays_a_failure():
    from agentvault_registry.routers import admin_api_test as R
    r = R._runner_gap_is_not_measured({"healthy": False, "statusCode": 422,
                                       "responseData": {"detail": "pubkey_jwk must be an EC P-256 key"}})
    assert not r.get("not_measured") and r["healthy"] is False, r


def test_red_the_permission_gate_refusing_the_sweeps_agent_is_an_expected_failure():
    from agentvault_registry.routers import admin_api_test as R
    r = R._runner_gap_is_not_measured({"healthy": False, "statusCode": 403, "responseData": {
        "detail": "Agent lacks required permission: cicd.version"}})
    assert r["healthy"] is True and r["expected_failure"] is True and "cicd.version" in r["expected_failure_reason"], r


def test_control_another_403_stays_a_failure():
    from agentvault_registry.routers import admin_api_test as R
    r = R._runner_gap_is_not_measured({"healthy": False, "statusCode": 403,
                                       "responseData": {"detail": "not a participant in this conversation"}})
    assert r["healthy"] is False and not r.get("expected_failure"), r


# ── every worker's bodies carry the sweep's agent DIDs ───────────────────────────────────────────────────────────────

class _CachedTokens(dict):
    async def refresh_from_redis(self):
        return None


def _cached_worker(monkeypatch, rb):
    from agentvault_registry.routers import admin_api_test as R

    async def _no_redis():
        return None
    monkeypatch.setattr(R, "request_bodies", rb)
    monkeypatch.setattr(R, "DYNAMIC_VALUES", {})
    monkeypatch.setattr(R, "_get_leader_redis", _no_redis)
    monkeypatch.setattr(R, "_tokens_not_near_expiry", lambda *a, **k: True)
    import time
    monkeypatch.setattr(R, "_sandbox_tokens", _CachedTokens(
        developer="dev.jwt", agent="agent.jwt", acquired_at=time.time(), _bootstrapped=True,
        agent_did="did:theprotocol:sandbox-a.theprotocol.cloud:primary-0001",
        agent_002_did="did:theprotocol:sandbox-a.theprotocol.cloud:counter-0002", client_id="agent-x", client_secret="s"))
    return R


def test_red_a_worker_that_reuses_the_cached_tokens_fills_its_bodies_with_the_cached_dids(monkeypatch):
    """Measured on sbx-alpha 2026-10-18 (10 workers): only the bootstrapping worker rewrote its bodies, so POST
    /chat/conversations named AGENT_NOT_ONBOARDED and answered 404 wherever another worker served the row."""
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    rb.enable_sandbox_mode()                      # what module import does on a worker that never bootstrapped
    assert rb.get_body("/chat/conversations")["target"]["agent_did"] == "AGENT_DID_PLACEHOLDER"
    R = _cached_worker(monkeypatch, rb)
    assert asyncio.run(R.get_sandbox_tokens()) == ("dev.jwt", "agent.jwt")
    assert rb.get_body("/chat/conversations")["target"]["agent_did"] == "did:theprotocol:sandbox-a.theprotocol.cloud:primary-0001"
    assert rb.get_body("/teg/transfer")["receiver_agent_id"] == "did:theprotocol:sandbox-a.theprotocol.cloud:counter-0002"


def test_control_a_worker_whose_bodies_already_carry_the_did_is_left_alone(monkeypatch):
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    rb.enable_sandbox_mode(agent_did="did:theprotocol:sandbox-a.theprotocol.cloud:primary-0001",
                           agent_002_did="did:theprotocol:sandbox-a.theprotocol.cloud:counter-0002")
    calls = []
    real = rb.enable_sandbox_mode
    monkeypatch.setattr(rb, "enable_sandbox_mode", lambda *a, **k: (calls.append(k), real(*a, **k)))
    R = _cached_worker(monkeypatch, rb)
    asyncio.run(R.get_sandbox_tokens())
    assert calls == [], calls
