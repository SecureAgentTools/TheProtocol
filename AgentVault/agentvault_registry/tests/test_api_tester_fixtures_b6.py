"""§SUITES1018 batch 6 (2026-10-18): the api-tester stops passing the refusals its contracts accept, and measures rows it
left NOT MEASURED for want of a fixture.

Measured in the 2026-10-18 rehearsals of the sweep on sbx-alpha (the batch-4 tester code):
  * 106 rows read PASS on a refusal status: a contract listing a 4xx in expected_status counted it healthy (GET
    /governance/proposals/{proposal_id} answered 404 on the fallback id and passed; 34 of them a REQUEST-validation
    422, a call whose handler never ran). A refusal the contract accepts is now an EXPECTED FAILURE, and a validation
    422 NOT MEASURED, as batch 3 made them on the legacy chain.
  * a contract READ resolved its placeholders from its own fallbacks ("99999", "test-circuit"), never the router's list
    resolvers. It asks the router first now.
  * NOT MEASURED for want of a fixture: a commons season, a template version, an issued licence, the sweep's push
    device, a hosted federation proposal; the IRONKEY rows on the sweep's own agent ran in path order, so consume,
    attenuate and the token revokes came before any token existed, and act-token before any grant.

RED on 9ec86feb: every test_red_* fails there. The test_control_* ones pin what each change must NOT do: six pass
there too; two fail only because their functions are new, and the failure-mode one because 9ec86feb passed the refusal.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from agentvault_registry.api_tests.core import contract as C


def _router(monkeypatch, values=None):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", dict(values or {}))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    return R


def _fake_http(monkeypatch, handler):
    seen = []
    real = httpx.AsyncClient

    def _handler(request):
        seen.append(request)
        return handler(request)

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handler)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return seen


# ── a refusal a contract accepts is an expected failure, never a pass ───────────────────────────────────────────────

def _run_contract(expected, status, body, failures=None, path="/x/plain", method="GET"):
    contract = C.EndpointContract(method=method, path=path, auth="developer", category="t",
                                  expected_status=expected, failures=failures or [])
    ctx = C.BootstrapContext() if hasattr(C, "BootstrapContext") else None
    if ctx is None:
        from agentvault_registry.api_tests.core.fixtures import BootstrapContext
        ctx = BootstrapContext()
    ctx.extras["admin_token"] = "dev.jwt"

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))) as c:
            return await C.execute(contract, ctx, http_client=c, target_url="http://t")
    return asyncio.run(go())


def test_red_a_404_the_contract_accepts_is_an_expected_failure():
    r = _run_contract([200, 404], 404, {"detail": "Proposal not found"})
    assert r.healthy is True and r.expected_failure is True, r
    assert r.expected_failure_reason == "the contract accepts 404: Proposal not found", r
    assert r.failure_bucket == "accepted_refusal"


def test_control_a_200_the_contract_expects_stays_a_pass():
    r = _run_contract([200, 404], 200, {"ok": True})
    assert r.healthy is True and r.expected_failure is False, r


def test_control_a_named_failure_mode_keeps_its_own_reason():
    from agentvault_registry.api_tests.core.failure_modes import FailureMode
    fm = FailureMode.business_rule(condition=lambda p: p.status == 409, reason="already tallied")
    r = _run_contract([200, 409], 409, {"detail": "x"}, failures=[fm])
    assert r.expected_failure is True and r.expected_failure_reason == "already tallied", r


def test_red_a_validation_422_a_contract_accepted_is_not_measured(monkeypatch):
    R = _router(monkeypatch)
    row = {"healthy": True, "expected_failure": True, "statusCode": 422,
           "expected_failure_reason": "the contract accepts 422: Field required",
           "responseData": {"error": {"code": "VALIDATION_FAILED", "field": "query -> q", "detail": "Field required"}}}
    out = R._runner_gap_is_not_measured(row)
    assert out["not_measured"] is True and out["expected_failure"] is False and out["healthy"] is False, out
    assert "query -> q" in out["not_measured_reason"]


def test_control_a_handler_422_a_contract_accepted_stays_an_expected_failure(monkeypatch):
    R = _router(monkeypatch)
    row = {"healthy": True, "expected_failure": True, "statusCode": 422,
           "expected_failure_reason": "the contract accepts 422: Unknown permissions",
           "responseData": {"detail": "Unknown permissions: ['x']"}}
    assert R._runner_gap_is_not_measured(dict(row))["expected_failure"] is True


def test_red_a_contract_read_asks_the_router_placeholders_first(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R

    async def _resolved(path, developer_token=None, agent_token=None, method=None):
        assert method == "GET" and developer_token == "dev.jwt"
        return path.replace("{circuit_id}", "fairMarkupPolicy")
    monkeypatch.setattr(R, "replace_path_placeholders", _resolved)
    seen = []

    contract = C.EndpointContract(method="GET", path="/circuits/{circuit_id}", auth="developer", category="t")
    from agentvault_registry.api_tests.core.fixtures import BootstrapContext
    ctx = BootstrapContext()
    ctx.extras["admin_token"] = "dev.jwt"

    async def go():
        def h(r):
            seen.append(r.url.path)
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            return await C.execute(contract, ctx, http_client=c, target_url="http://t")
    asyncio.run(go())
    assert seen == ["/api/v1/circuits/fairMarkupPolicy"], seen


def test_control_a_contract_write_keeps_its_own_map(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    called = []

    async def _resolved(*a, **k):
        called.append(1)
        return "/never"
    monkeypatch.setattr(R, "replace_path_placeholders", _resolved)
    r = _run_contract(200, 200, {}, path="/x/{contract_id}", method="POST")
    assert called == [] and r.healthy is True


# ── reads that name a real row ──────────────────────────────────────────────────────────────────────────────────────

def test_red_the_new_list_resolvers_name_a_real_row(monkeypatch):
    R = _router(monkeypatch, {"agent_did": "did:x"})

    def _answer(r):
        p = r.url.path
        if p == "/api/v1/commons/seasons":
            return httpx.Response(200, json={"seasons": [{"id": 7}]})
        if p == "/api/v1/contracts/templates":
            return httpx.Response(200, json={"items": [{"id": "tpl_1"}]})
        if p == "/api/v1/admin/federation/licence/issued":
            return httpx.Response(200, json={"licences": [{"hash": "ab" * 32}]})
        if p == "/api/v1/governance/federation/proposals":
            return httpx.Response(200, json=[{"id": "3f2a"}])
        if p == "/api/v1/governance/proposals":
            assert r.url.params.get("include_closed") == "true"
            return httpx.Response(200, json=[{"id": 12}])
        return httpx.Response(404, json={})
    _fake_http(monkeypatch, _answer)

    def rp(path):
        return asyncio.run(R.replace_path_placeholders(path, developer_token="dev.jwt", agent_token="ag.jwt", method="GET"))
    assert rp("/commons/seasons/{season_id}/mine") == "/commons/seasons/7/mine"
    assert rp("/contracts/templates/{tid}/versions/{n}") == "/contracts/templates/tpl_1/versions/1"
    assert rp("/public/federation/licences/{cert_hash}") == "/public/federation/licences/" + "ab" * 32
    assert rp("/governance/federation/proposals/{proposal_id}/ballots") == "/governance/federation/proposals/3f2a/ballots"
    assert rp("/governance/proposals/{proposal_id}/votes") == "/governance/proposals/12/votes"


def test_control_a_write_under_the_same_prefixes_is_never_resolved_from_a_list(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"seasons": [{"id": 7}]}))
    out = asyncio.run(R.replace_path_placeholders("/commons/seasons/{season_id}/ballot", developer_token="dev.jwt",
                                                  method="POST"))
    assert "{season_id}" in out and seen == []
    out = asyncio.run(R.replace_path_placeholders("/contracts/templates/{tid}/versions/{n}/publish",
                                                  developer_token="dev.jwt", method="POST"))
    assert out.endswith("/versions/{n}/publish")


# ── the sweep's own push device ─────────────────────────────────────────────────────────────────────────────────────

_DEVICES = {"devices": [{"id": 4, "target": "someone-elses-phone"}, {"id": 9, "target": "apitest-device-token-2026"}]}


def test_red_the_device_rows_take_the_sweeps_own_device(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json=_DEVICES))
    assert asyncio.run(R.replace_path_placeholders("/devices/{device_id}", developer_token="dev.jwt",
                                                   method="DELETE")) == "/devices/9"
    assert asyncio.run(R.replace_path_placeholders("/liability/devices/{device_id}/webauthn/options",
                                                   developer_token="dev.jwt", method="GET")) \
        == "/liability/devices/9/webauthn/options"


def test_control_no_device_of_the_sweeps_own_leaves_the_placeholder(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"devices": [{"id": 4, "target": "someone-elses-phone"}]}))
    assert asyncio.run(R.replace_path_placeholders("/devices/{device_id}", developer_token="dev.jwt",
                                                   method="DELETE")) == "/devices/{device_id}"


def test_red_the_device_is_registered_again_after_the_delete_row(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={}))
    asyncio.run(R._reregister_after_delete("/devices/{device_id}", "/devices/9", {"healthy": True}, "dev.jwt"))
    assert [(r.method, r.url.path) for r in seen] == [("POST", "/api/v1/devices/register")]
    assert json.loads(seen[0].content)["target"] == "apitest-device-token-2026"


def test_control_no_reregister_when_the_delete_named_no_device(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={}))
    asyncio.run(R._reregister_after_delete("/devices/{device_id}", "/devices/{device_id}", {}, "dev.jwt"))
    assert seen == []


# ── the IRONKEY rows on the sweep's own agent ───────────────────────────────────────────────────────────────────────

def test_red_each_capability_row_takes_its_own_token(monkeypatch):
    R = _router(monkeypatch, {"agent_did": "did:x", "cap_token_id": "A1", "cap_token_revoke_id": "B2"})
    _fake_http(monkeypatch, lambda r: httpx.Response(404, json={}))

    def rp(path, method):
        return asyncio.run(R.replace_path_placeholders(path, developer_token="dev.jwt", agent_token="ag.jwt",
                                                       method=method))
    assert rp("/agents/capabilities/{token_id}", "DELETE") == "/agents/capabilities/B2"
    assert rp("/agents/capabilities/{token_id}/attenuate", "POST") == "/agents/capabilities/A1/attenuate"
    assert rp("/agents/{did}/capabilities/{token_id}", "DELETE") == "/agents/did:x/capabilities/A1"


def test_control_a_payment_token_id_is_never_a_capability_token(monkeypatch):
    R = _router(monkeypatch, {"cap_token_id": "A1", "cap_token_revoke_id": "B2"})
    out = asyncio.run(R.replace_path_placeholders("/a2a-payment/release-by-id/{token_id}", developer_token="dev.jwt",
                                                  method="POST"))
    assert "A1" not in out and "B2" not in out


def test_red_the_grant_delete_takes_the_sweeps_own_newest_grant(monkeypatch):
    R = _router(monkeypatch, {"agent_did": "did:x", "act_as_principal": "dev:5"})
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"grants": [
        {"id": 3, "principal": "dev:5"}, {"id": 8, "principal": "dev:5"}, {"id": 11, "principal": "org:acme"}]}))
    assert asyncio.run(R.replace_path_placeholders("/delegations/{grant_id}", developer_token="dev.jwt",
                                                   method="DELETE")) == "/delegations/8"


def test_red_the_markers_carry_the_prereqs_values(monkeypatch):
    R = _router(monkeypatch, {"cap_token": "att_live", "act_as_principal": "dev:5"})
    out = asyncio.run(R._resolve_body_markers({"token": "__CAP_TOKEN__", "act_as": "__ACT_AS__",
                                               "principal_ref": "__DEV_PRINCIPAL__"}))
    assert out == {"token": "att_live", "act_as": "dev:5", "principal_ref": "dev:5"}


def test_red_the_delegation_prereq_prepares_the_sweeps_own_agent(monkeypatch):
    R = _router(monkeypatch, {"agent_did": "did:x"})
    issued = iter([{"id": "A1", "token": "att_a"}, {"id": "B2", "token": "att_b"}])

    def _answer(r):
        if r.url.path == "/api/v1/developers/me":
            return httpx.Response(200, json={"id": 5})
        if r.url.path.endswith("/capabilities/issue-as-owner"):
            return httpx.Response(200, json=next(issued))
        return httpx.Response(200, json={"ok": True})
    seen = _fake_http(monkeypatch, _answer)
    asyncio.run(R._setup_agent_delegation("dev.jwt", "ag.jwt"))
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/api/v1/developers/me"), ("PUT", "/api/v1/agents/did:x/authz"),
        ("POST", "/api/v1/agents/did:x/capabilities/issue-as-owner"),
        ("POST", "/api/v1/agents/did:x/capabilities/issue-as-owner"),
        ("POST", "/api/v1/agents/did:x/delegations")]
    assert json.loads(seen[1].content) == {"delegate_enabled": True}
    assert json.loads(seen[4].content)["principal_ref"] == "dev:5"
    assert R.DYNAMIC_VALUES["cap_token_id"] == "A1" and R.DYNAMIC_VALUES["cap_token"] == "att_a"
    assert R.DYNAMIC_VALUES["cap_token_revoke_id"] == "B2" and R.DYNAMIC_VALUES["act_as_principal"] == "dev:5"
    assert R.CATEGORY_PREREQS["agent_delegation"] is R._setup_agent_delegation


def test_control_the_prereq_does_nothing_without_the_sweeps_agent(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json={}))
    asyncio.run(R._setup_agent_delegation("dev.jwt", "ag.jwt"))
    assert seen == []


def test_red_the_ironkey_rows_carry_bodies():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    assert rb.get_body("/agents/act-token") == {"act_as": "__ACT_AS__"}
    assert rb.get_body("/agents/capabilities/consume") == {"token": "__CAP_TOKEN__", "amount": 0}
    for p in ("/agents/capabilities", "/agents/capabilities/{token_id}/attenuate",
              "/agents/{did}/capabilities/issue-as-owner"):
        assert rb.get_body(p)["caveats"] == {"permissions": ["fx.quote"]}, p
    assert rb.get_body("/agents/{did}/delegations")["principal_ref"] == "__DEV_PRINCIPAL__"
    assert rb.get_body("/agents/spawn")["permissions"] == ["fx.quote"]


# ── writes that name nothing real; reads with their required input ──────────────────────────────────────────────────

def test_red_the_guild_writes_carry_bodies_and_their_refusal_is_named():
    from agentvault_registry.api_tests import base as B
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    for tail in ("bids", "award", "submit", "verify"):
        assert rb.get_body(f"/guild/orders/{{oid}}/{tail}"), tail
        assert B._classify_sentence_refusal("POST", f"/guild/orders/gwo_apitest_none/{tail}", 404,
                                            {"detail": "Order not found"}), tail
    # control: a bid refused for another reason stays a finding
    assert B._classify_sentence_refusal("POST", "/guild/orders/gwo_apitest_none/bids", 409,
                                        {"detail": "Order is closed"}) == ""


def test_red_a_structured_refusal_is_matched_on_its_code():
    from agentvault_registry.api_tests import base as B
    rd = {"detail": {"error": "no_underwriter", "agent_did": "did:x", "remedy": "no live mandate underwrites this agent"}}
    assert "no live mandate" in B._classify_sentence_refusal("POST", "/liability/intents", 404, rd)
    assert B._classify_sentence_refusal("POST", "/liability/intents", 404, {"detail": {"error": "other"}}) == ""


def test_red_the_forge_run_names_no_suite():
    from agentvault_registry.api_tests import base as B
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    assert RequestBodies().get_body("/forge/evals/run") == {"suite_id": 999999}
    assert B._classify_sentence_refusal("POST", "/forge/evals/run", 404, {"detail": "Suite not found"})


def test_red_enroll_key_takes_a_fresh_p256_key_on_the_sweeps_device(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json=_DEVICES))
    assert asyncio.run(R.replace_path_placeholders("/liability/devices/{device_id}/enroll-key", developer_token="dev.jwt",
                                                   method="POST")) == "/liability/devices/9/enroll-key"
    body = asyncio.run(R._resolve_body_markers({"pubkey_jwk": "__P256_JWK__"}))
    jwk = body["pubkey_jwk"]
    assert jwk["kty"] == "EC" and jwk["crv"] == "P-256" and len(jwk["x"]) == 43 and len(jwk["y"]) == 43, jwk
    # the point is on the curve: the route's own reader would accept it
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    num = lambda v: int.from_bytes(base64.urlsafe_b64decode(v + "="), "big")
    ec.EllipticCurvePublicNumbers(num(jwk["x"]), num(jwk["y"]), ec.SECP256R1()).public_key()
    assert asyncio.run(R._resolve_body_markers({"pubkey_jwk": "__P256_JWK__"}))["pubkey_jwk"] != jwk   # fresh per call


def test_red_the_passport_portfolio_names_the_peer_market(monkeypatch):
    R = _router(monkeypatch)

    async def _peer():
        return "sandbox-beta"
    monkeypatch.setattr(R, "_peer_frame_name", _peer)
    q = R._REQUIRED_QUERY_DEFAULTS["/agora/passport/portfolio"]({})
    assert asyncio.run(q) == "venue_registry=sandbox-beta"


# ── a frame's live configuration and the routes that move value are named for what they are ──────────────────────────

def test_red_frame_control_and_money_routes_are_not_measured_for_what_they_change():
    from agentvault_registry.api_tests import base as B
    for m, p in (("PUT", "/admin/enforcement/policy"), ("POST", "/agora/admin/global-halt"),
                 ("PUT", "/admin/registry-card"), ("POST", "/admin/federation/licence/abc/revoke")):
        assert B._classify_frame_control(m, p)[0] == "frame_control", (m, p)
    for m, p in (("POST", "/agora/orders"), ("POST", "/teg/send"),
                 ("POST", "/agora/organizations/o1/treasury/ACME/transfer"),
                 ("POST", "/contracts/v2/c1/milestones/1/release")):
        assert B._classify_frame_control(m, p)[0] == "moves_money", (m, p)
    r = asyncio.run(B.APITestBase(base_url="http://127.0.0.1:1").test_endpoint(method="POST", path="/teg/send",
                                                                                 auth_type="agent"))
    assert r["not_measured"] is True and r["failure_bucket"] == "not_measured_moves_money", r


def test_control_reads_and_unlisted_writes_are_untouched():
    from agentvault_registry.api_tests import base as B
    for m, p in (("GET", "/admin/enforcement/policy"), ("GET", "/agora/orders"), ("GET", "/admin/registry-card"),
                 ("POST", "/agora/orders/cancel-all-of-nothing"), ("POST", "/teg/send/quote")):
        assert B._classify_frame_control(m, p) == ("", ""), (m, p)


def test_red_the_router_refuses_them_before_any_contract_runs():
    import inspect
    from agentvault_registry.routers import admin_api_test as R
    src = inspect.getsource(R.test_endpoint)
    assert src.index("_classify_frame_control(method, path)") < src.index("_contract_for(method, path)")


def test_red_the_feed_row_marks_an_entry_of_the_sweeps_own_feed(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"entries": [{"id": 41}, {"id": 40}]}))
    assert asyncio.run(R.replace_path_placeholders("/notifications/feed/{entry_id}/read", developer_token="dev.jwt",
                                                   method="POST")) == "/notifications/feed/41/read"
    assert seen[0].url.path == "/api/v1/notifications/feed"


def test_control_an_empty_feed_leaves_the_placeholder(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"entries": []}))
    assert asyncio.run(R.replace_path_placeholders("/notifications/feed/{entry_id}/read", developer_token="dev.jwt",
                                                   method="POST")) == "/notifications/feed/{entry_id}/read"


def test_red_the_simulation_and_the_own_ticket_rows_carry_bodies():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    assert rb.get_body("/admin/fiat/pricing/simulate")["purchases_eur"] == ["10.00", "25.00"]
    assert rb.get_body("/support/tickets/{ticket_id}/status") == {"status": "open"}
    assert rb.get_body("/admin/support/tickets/{ticket_id}/triage") == {"priority": "low"}


def test_red_the_flare_override_rows_clear_the_sweeps_own_override():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    assert rb.get_body("/fiat/flare/agent/{agent_did}/variant") == {"variant": "__clear__"}
    assert rb.get_body("/fiat/flare/agent/{agent_did}/overlay") == {"overlay": "__clear__"}
    assert rb.get_body("/fiat/flare/agent/{agent_did}/corner-variant") == {"variant": "__clear__"}


# ── batch 6b: the file upload row sends a file; the chat fixtures exist before the category's first row ─────────────

def test_red_the_upload_row_sends_a_real_file_and_keeps_its_id(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={"attachment_id": "att1", "mime": "text/plain"}))
    out = asyncio.run(R._multipart_row("/chat/conversations/c-1/attachments",
                                       "/chat/conversations/{conversation_id}/attachments", "developer", "dev.jwt"))
    req = seen[0]
    assert req.url.path == "/api/v1/chat/conversations/c-1/attachments"
    assert req.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="apitest-probe.txt"' in req.content and b"text/plain" in req.content
    assert out["healthy"] is True and out["statusCode"] == 201 and R.DYNAMIC_VALUES["attachment_id"] == "att1"


def test_control_a_refused_upload_is_a_failure_with_its_status(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(415, json={"detail": "not an accepted file type"}))
    out = asyncio.run(R._multipart_row("/chat/conversations/c-1/attachments",
                                       "/chat/conversations/{conversation_id}/attachments", "developer", "dev.jwt"))
    assert out["healthy"] is False and out["statusCode"] == 415 and "attachment_id" not in R.DYNAMIC_VALUES


def test_red_the_chat_prereq_opens_the_conversation_and_its_attachment_up_front(monkeypatch):
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    R = _router(monkeypatch)
    rb = RequestBodies()
    rb.enable_sandbox_mode(agent_did="did:theprotocol:sandbox-a.theprotocol.cloud:a-1",
                           agent_002_did="did:theprotocol:sandbox-a.theprotocol.cloud:b-2")
    monkeypatch.setattr(R, "request_bodies", rb)

    def _answer(r):
        if r.url.path == "/api/v1/support/tickets":
            return httpx.Response(200, json=[{"id": 9, "status": "open"}])
        if r.url.path == "/api/v1/chat/conversations":
            return httpx.Response(201, json={"conversation_id": "c-77"})
        return httpx.Response(201, json={"attachment_id": "att-5"})
    seen = _fake_http(monkeypatch, _answer)
    asyncio.run(R._setup_ourchat_chat("dev.jwt", "ag.jwt"))
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/api/v1/support/tickets"), ("POST", "/api/v1/chat/conversations"),
        ("POST", "/api/v1/chat/conversations/c-77/attachments")]
    assert R.DYNAMIC_VALUES["chat_review_ticket_id"] == "9" and R.DYNAMIC_VALUES["conversation_id"] == "c-77"
    assert R.DYNAMIC_VALUES["attachment_id"] == "att-5"
    assert R.DYNAMIC_VALUES["conversation_pair_body"]["target"]["agent_did"].endswith(":a-1")
    path = asyncio.run(R.replace_path_placeholders("/chat/attachments/{attachment_id}", developer_token="dev.jwt",
                                                   method="GET"))
    assert path == "/chat/attachments/att-5"


def test_red_the_sweeps_own_device_key_revoke_is_measured(monkeypatch):
    from agentvault_registry.api_tests import base as B
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json=_DEVICES))
    assert asyncio.run(R.replace_path_placeholders("/liability/devices/{device_id}/revoke-key", developer_token="dev.jwt",
                                                   method="POST")) == "/liability/devices/9/revoke-key"
    assert B._classify_destructive("POST", "/liability/devices/9/revoke-key") == ""


def test_control_every_other_revocation_stays_withheld():
    from agentvault_registry.api_tests import base as B
    # (§SUITES1018 batch 8 part 3: the mandate revoke left this list; {mid} is the sweep's own mandate since then,
    # tests/test_api_tester_liability_b8.py)
    for p in ("/attestations/a1/revoke", "/admin/federation/frames/3/revoke"):
        assert B._classify_destructive("POST", p), p
