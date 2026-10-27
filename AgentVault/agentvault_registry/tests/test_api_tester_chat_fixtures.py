"""§SUITES1018 (2026-10-18): the api-tester keeps ONE conversation, ONE agent and ONE org room through the chat rows.

Measured on sbx-alpha 2026-10-18 (rehearsals of the ourchat_chat category with the V0624 tester code):
  * every {conversation_id} row named a conversation an older run had captured: ourchat_chat has no category module,
    so its rows take the direct path, where nothing captured the id POST /chat/conversations answered. The stored one
    was a DM between two agents which the sweep's developer had left: 409 "you have left this conversation" on
    messages, ping, room, support-review.
  * a 401 that only meant "this route takes an agent" (certificate, service-call asked with the developer's token)
    was read as a stale token: the cache was dropped and the bootstrap onboarded, funded and staked two NEW agents,
    twice inside one category, so the agent the request bodies named changed between the create row and the rejoin
    after the leave row.
  * members and room act only on an org room (409 "member sheets exist only for org rooms" / "room actions run only
    in org rooms"); support-review sent ticket 1, nobody's ticket (404 "no such ticket of yours").
  * accept and decline on the sweep's own, active DM answer 409 "cannot accept a conversation you are 'active' in":
    a documented refusal the fixture meets by construction; the 'left' sentence stays a finding.

  * the ticket state and the ticket reply were asked on the DM: 404 "this conversation is not a support thread".

RED on a635830e: every test here fails there (the test_control_* ones too, their symbols are new; they pin what each
change must NOT do).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agentvault_registry.api_tests import base as B


def _router(monkeypatch, values=None):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", dict(values or {}))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    return R


def _fake_http(monkeypatch, handler):
    """Every httpx.AsyncClient the tester opens answers from `handler`; the requests are recorded."""
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


# ── a 401 from a route that refuses the principal is not a stale token ──────────────────────────────────────────────

class _Tester:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def test_endpoint(self, **kw):
        self.calls.append(kw)
        return dict(self.answers.pop(0))


def _retry(R, tester):
    return asyncio.run(R._retry_before_classification(
        tester, {"healthy": False, "statusCode": 401, "responseData": {"detail": "Not authenticated"}},
        method="POST", path="/chat/conversations/c1/certificate",
        original_path="/chat/conversations/{conversation_id}/certificate", auth_type="developer",
        developer_token="dev.jwt", agent_token="agent.jwt"))


def test_red_a_401_with_live_credentials_never_rebootstraps(monkeypatch):
    R = _router(monkeypatch)
    reacquired = []

    async def _tokens():
        reacquired.append(1)
        return "new.dev", "new.agent"

    async def _live(dev, agent):
        return True
    monkeypatch.setattr(R, "get_sandbox_tokens", _tokens)
    monkeypatch.setattr(R, "_sweep_credentials_answer", _live)
    tester = _Tester([{"healthy": False, "statusCode": 409, "responseData": {"detail": "a refusal the agent earned"}}])
    out = _retry(R, tester)
    assert reacquired == [], "a 401 the live credentials explain re-onboarded the sweep's agents"
    assert [c.get("auth_type") for c in tester.calls] == ["agent"], tester.calls   # the principal retry still runs
    assert out["statusCode"] == 409 and out["principal_retry"] == "agent", out


def test_control_a_401_after_the_credentials_died_still_reacquires(monkeypatch):
    R = _router(monkeypatch)
    reacquired = []

    async def _tokens():
        reacquired.append(1)
        return "new.dev", "new.agent"

    async def _dead(dev, agent):
        return False

    class _Cache(dict):
        async def clear_redis(self):
            return None
    monkeypatch.setattr(R, "_sandbox_tokens", _Cache(developer="dev.jwt"))
    monkeypatch.setattr(R, "get_sandbox_tokens", _tokens)
    monkeypatch.setattr(R, "_sweep_credentials_answer", _dead)
    tester = _Tester([{"healthy": True, "statusCode": 200, "responseData": {}}])
    out = _retry(R, tester)
    assert reacquired == [1] and out.get("stale_token_retry") is True, out


def test_red_the_credential_check_asks_both_principals(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json={}))
    assert asyncio.run(R._sweep_credentials_answer("dev.jwt", "agent.jwt")) is True
    assert [r.url.path for r in seen] == ["/api/v1/developers/me", "/api/v1/agents/me"]


def test_control_a_developer_token_the_logout_row_killed_is_not_live(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(401 if r.url.path.endswith("/developers/me") else 200, json={}))
    assert asyncio.run(R._sweep_credentials_answer("dev.jwt", "agent.jwt")) is False
    assert asyncio.run(R._sweep_credentials_answer(None, "agent.jwt")) is False


# ── the direct path captures what the chat rows act on ──────────────────────────────────────────────────────────────

_PAIR = {"kind": "dm", "target": {"ptype": "agent", "agent_did": "did:theprotocol:sandbox-a.theprotocol.cloud:a-1"}}


def test_red_the_direct_path_captures_the_conversation_and_its_pair(monkeypatch):
    R = _router(monkeypatch, {"conversation_id": "older-run"})
    R._capture_chat_fixtures("/chat/conversations", "POST",
                             {"healthy": True, "statusCode": 201, "responseData": {"conversation_id": "c-new"}}, _PAIR)
    assert R.DYNAMIC_VALUES["conversation_id"] == "c-new"
    assert R.DYNAMIC_VALUES["conversation_pair_body"] == _PAIR


def test_control_a_refused_create_leaves_the_fixture_alone(monkeypatch):
    R = _router(monkeypatch, {"conversation_id": "kept"})
    R._capture_chat_fixtures("/chat/conversations", "POST",
                             {"healthy": False, "statusCode": 404, "responseData": {"detail": "target agent not found"}}, _PAIR)
    R._capture_chat_fixtures("/chat/conversations", "POST", {"healthy": True, "expected_failure": True,
                                                              "responseData": {"conversation_id": "x"}}, _PAIR)
    assert R.DYNAMIC_VALUES == {"conversation_id": "kept"}


def test_red_the_review_grant_is_captured_for_its_delete_row(monkeypatch):
    R = _router(monkeypatch)
    R._capture_chat_fixtures("/chat/conversations/{conversation_id}/support-review", "POST",
                             {"healthy": True, "statusCode": 201, "responseData": {"grant_id": 7, "ticket_id": 9}})
    assert R.DYNAMIC_VALUES["grant_id"] == "7"
    path = asyncio.run(R.replace_path_placeholders("/chat/conversations/{conversation_id}/support-review/{grant_id}",
                                                   method="DELETE"))
    assert path.endswith("/support-review/7"), path


def test_red_the_rejoin_opens_the_captured_pair_not_whatever_the_bodies_name_now(monkeypatch):
    R = _router(monkeypatch, {"conversation_id": "c-new", "conversation_pair_body": _PAIR})
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={"conversation_id": "c-new"}))
    asyncio.run(R._rejoin_after_leave("/chat/conversations/{conversation_id}/leave", "/chat/conversations/c-new/leave",
                                      {"healthy": True}, "dev.jwt"))
    assert len(seen) == 1 and json.loads(seen[0].content) == _PAIR


def test_control_no_rejoin_without_a_real_pair(monkeypatch):
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    R = _router(monkeypatch)
    rb = RequestBodies()
    rb.enable_sandbox_mode()
    monkeypatch.setattr(R, "request_bodies", rb)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={}))
    asyncio.run(R._rejoin_after_leave("/chat/conversations/{conversation_id}/leave", "/chat/conversations/c/leave",
                                      {"healthy": True}, "dev.jwt"))
    assert seen == []   # the catalog body still names no agent


# ── org-room rows ask the sweep's org room ──────────────────────────────────────────────────────────────────────────

def test_red_members_and_room_ask_the_sweeps_org_room(monkeypatch):
    R = _router(monkeypatch, {"org_id": "o-1", "conversation_id": "dm-1"})
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={"conversation_id": "room-1"}))
    for row in ("/chat/conversations/{conversation_id}/members", "/chat/conversations/{conversation_id}/room"):
        assert asyncio.run(R.replace_path_placeholders(row, developer_token="dev.jwt", method="GET")) \
            == row.replace("{conversation_id}", "room-1")
    assert [r.url.path for r in seen] == ["/api/v1/chat/org-rooms/o-1/open"]   # opened once, cached


def test_control_every_other_chat_row_keeps_the_sweeps_dm(monkeypatch):
    R = _router(monkeypatch, {"org_id": "o-1", "conversation_id": "dm-1"})
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(201, json={"conversation_id": "room-1"}))
    assert asyncio.run(R.replace_path_placeholders("/chat/conversations/{conversation_id}/messages",
                                                   developer_token="dev.jwt", method="POST")) \
        == "/chat/conversations/dm-1/messages"
    assert seen == []


# ── support-review takes an open ticket of the sweep's own ──────────────────────────────────────────────────────────

def test_red_the_chat_prereq_reuses_an_open_ticket_of_the_sweeps_developer(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json=[{"id": 5, "status": "closed"},
                                                                      {"id": 9, "status": "open"}]))
    asyncio.run(R._setup_ourchat_chat("dev.jwt", "agent.jwt"))
    assert R.DYNAMIC_VALUES["chat_review_ticket_id"] == "9"
    assert [r.method for r in seen] == ["GET"]


def test_red_the_chat_prereq_files_a_ticket_when_none_is_open(monkeypatch):
    R = _router(monkeypatch)

    def _answer(r):
        if r.method == "GET":
            return httpx.Response(200, json=[{"id": 5, "status": "closed"}])
        return httpx.Response(201, json={"id": 11})
    _fake_http(monkeypatch, _answer)
    asyncio.run(R._setup_ourchat_chat("dev.jwt", "agent.jwt"))
    assert R.DYNAMIC_VALUES["chat_review_ticket_id"] == "11"
    assert R.CATEGORY_PREREQS["ourchat_chat"] is R._setup_ourchat_chat


def test_red_the_support_review_body_waits_for_that_ticket():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    assert RequestBodies().get_body("/chat/conversations/{conversation_id}/support-review") \
        == {"ticket_id": "__CHAT_TICKET_ID__"}


# ── accept / decline / ping: documented refusals, keyed on their sentence ───────────────────────────────────────────

@pytest.mark.parametrize("action", ["accept", "decline"])
def test_red_accept_and_decline_on_the_sweeps_active_dm_are_expected(action):
    r = B._classify_sentence_refusal("POST", f"/chat/conversations/c-1/{action}", 409,
                                     {"detail": f"cannot {action} a conversation you are 'active' in"})
    assert "never is" in r, r


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_control_the_left_sentence_stays_a_finding(action):
    assert B._classify_sentence_refusal("POST", f"/chat/conversations/c-1/{action}", 409,
                                        {"detail": f"cannot {action} a conversation you are 'left' in"}) == ""


def test_red_the_ping_limit_is_expected_and_only_the_ping_limit():
    assert B._classify_sentence_refusal("POST", "/chat/conversations/c-1/ping", 429,
                                        {"detail": "one ping per thread per 10 minutes"})
    assert B._classify_sentence_refusal("POST", "/chat/conversations/c-1/ping", 409,
                                        {"detail": "you are not active in this conversation"}) == ""


# ── the ticket rows ask a support thread of the sweep's own ─────────────────────────────────────────────────────────

def test_red_the_ticket_rows_reuse_a_support_thread_from_the_inbox(monkeypatch):
    R = _router(monkeypatch, {"conversation_id": "dm-1"})
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"conversations": [
        {"id": "dm-1", "kind": "dm"}, {"id": "sup-1", "kind": "support"}]}))
    for row in ("/chat/conversations/{conversation_id}/support", "/chat/conversations/{conversation_id}/support-reply"):
        assert asyncio.run(R.replace_path_placeholders(row, developer_token="dev.jwt", method="GET")) \
            == row.replace("{conversation_id}", "sup-1")
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/chat/conversations")]


def test_red_the_ticket_rows_open_a_thread_when_the_inbox_has_none(monkeypatch):
    R = _router(monkeypatch, {"conversation_id": "dm-1"})

    def _answer(r):
        if r.method == "GET":
            return httpx.Response(200, json={"conversations": [{"id": "dm-1", "kind": "dm"}]})
        return httpx.Response(201, json={"ticket_id": 4, "conversation_id": "sup-new"})
    seen = _fake_http(monkeypatch, _answer)
    assert asyncio.run(R.replace_path_placeholders("/chat/conversations/{conversation_id}/support",
                                                   developer_token="dev.jwt", method="GET")) \
        == "/chat/conversations/sup-new/support"
    assert seen[-1].url.path == "/api/v1/chat/support/open" and json.loads(seen[-1].content)["subject"]


def test_control_support_review_keeps_the_sweeps_dm(monkeypatch):
    """The review grant is asked on a NON-support conversation (the desk already sees its own thread: 409)."""
    R = _router(monkeypatch, {"conversation_id": "dm-1", "support_conversation_id": "sup-1"})
    assert asyncio.run(R.replace_path_placeholders("/chat/conversations/{conversation_id}/support-review",
                                                   developer_token="dev.jwt", method="POST")) \
        == "/chat/conversations/dm-1/support-review"


# ── a refresh never reads back a value its own process just replaced ────────────────────────────────────────────────

class _SlowRedis:
    def __init__(self, data):
        self.data = dict(data)

    async def hset(self, key, field, value):
        await asyncio.sleep(0.02)   # the write is still in flight when the next row starts
        self.data[field] = value

    async def hgetall(self, key):
        return dict(self.data)


def test_red_a_refresh_waits_for_this_processes_own_writes(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    fake = _SlowRedis({"conversation_id": json.dumps("previous-run")})

    async def _redis():
        return fake
    monkeypatch.setattr(R, "_get_leader_redis", _redis)

    async def _rows():
        d = R.RedisSyncDict("api_test:dynamic_values:test")
        d["conversation_id"] = "just-captured"      # the create row
        await d.refresh_from_redis()                # the next row starts
        return d["conversation_id"]
    assert asyncio.run(_rows()) == "just-captured"


def test_control_a_refresh_still_pulls_another_workers_value(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    fake = _SlowRedis({"org_id": json.dumps("from-another-worker")})

    async def _redis():
        return fake
    monkeypatch.setattr(R, "_get_leader_redis", _redis)

    async def _rows():
        d = R.RedisSyncDict("api_test:dynamic_values:test")
        await d.refresh_from_redis()
        return d.get("org_id")
    assert asyncio.run(_rows()) == "from-another-worker"


# ── markers resolve in any body; the handle rows ask the sweep's own handle ─────────────────────────────────────────

def test_red_markers_resolve_in_a_body_chosen_before_the_catalog_block(monkeypatch):
    R = _router(monkeypatch, {"conversation_id": "c-9", "chat_review_ticket_id": "12"})
    out = asyncio.run(R._resolve_body_markers({"conversation_id": "__CONVERSATION_ID__", "seq": 1,
                                               "ticket_id": "__CHAT_TICKET_ID__"}))
    assert out == {"conversation_id": "c-9", "seq": 1, "ticket_id": 12}


def test_control_a_marker_with_no_live_value_is_left_for_the_route_to_judge(monkeypatch):
    R = _router(monkeypatch)
    body = {"conversation_id": "__CONVERSATION_ID__", "ticket_id": "__CHAT_TICKET_ID__"}
    assert asyncio.run(R._resolve_body_markers(dict(body))) == body


def test_red_the_handle_rows_ask_the_handle_the_sweep_claimed(monkeypatch):
    R = _router(monkeypatch)
    seen = _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"handle": "apitest-h1"}))
    for row in ("/chat/handles/{handle}", "/chat/handles/{handle}/pulse"):
        assert asyncio.run(R.replace_path_placeholders(row, developer_token="dev.jwt", method="GET")) \
            == row.replace("{handle}", "apitest-h1")
    assert [r.url.path for r in seen] == ["/api/v1/chat/handles/me"]


def test_control_no_handle_yet_leaves_the_placeholder(monkeypatch):
    R = _router(monkeypatch)
    _fake_http(monkeypatch, lambda r: httpx.Response(200, json={"handle": None}))
    assert asyncio.run(R.replace_path_placeholders("/chat/handles/{handle}", developer_token="dev.jwt",
                                                   method="GET")) == "/chat/handles/{handle}"


def test_red_certificate_and_service_call_carry_bodies_and_their_refusals_are_named():
    from agentvault_registry.api_tests.request_bodies import RequestBodies
    rb = RequestBodies()
    assert rb.get_body("/chat/conversations/{conversation_id}/certificate")["symbol"] == "APITEST"
    assert len(rb.get_body("/chat/conversations/{conversation_id}/service-call")["client_ref"]) >= 8
    assert B._classify_sentence_refusal("POST", "/chat/conversations/c/certificate", 409, {"detail": (
        "you hold no APITEST on this registry, so there is nothing to certify")})
    assert B._classify_sentence_refusal("POST", "/chat/conversations/c/service-call", 409, {
        "detail": "service calls run only in agent_service threads"})
    # control: the membership refusal on the same route stays a finding
    assert B._classify_sentence_refusal("POST", "/chat/conversations/c/certificate", 409, {
        "detail": "you are not active in this conversation"}) == ""


# ── a family only the OpenAPI catalog knows still gets its prereq ───────────────────────────────────────────────────

def _catalog(monkeypatch, R, legacy=None):
    from agentvault_registry.api_tests.core import catalog_sync

    async def _build(*a, **k):
        return {"ourchat_chat": [{"method": "POST", "path": "/chat/conversations/{conversation_id}/support-review",
                                  "auth": "developer"}]}
    monkeypatch.setattr(catalog_sync, "build_catalog", _build)
    monkeypatch.setattr(R.endpoints_registry, "get_endpoint", lambda m, p: legacy)


def test_red_a_catalog_only_row_finds_its_prereq_category(monkeypatch):
    R = _router(monkeypatch)
    _catalog(monkeypatch, R)
    assert asyncio.run(R._prereq_category("POST", "/chat/conversations/{conversation_id}/support-review")) \
        == "ourchat_chat"


def test_control_the_legacy_registry_still_answers_first_and_unknown_stays_unknown(monkeypatch):
    R = _router(monkeypatch)
    _catalog(monkeypatch, R, legacy={"category": "support", "auth": "developer"})
    assert asyncio.run(R._prereq_category("POST", "/chat/conversations/{conversation_id}/support-review")) == "support"
    _catalog(monkeypatch, R)
    assert asyncio.run(R._prereq_category("GET", "/nowhere")) == "unknown"


# ── a reset reaches the shared prereq flags ─────────────────────────────────────────────────────────────────────────

class _FlagRedis(_SlowRedis):
    def __init__(self, data):
        super().__init__(data)
        self.deleted = []

    async def delete(self, key):
        self.deleted.append(key)
        self.data.clear()


def test_red_a_reset_clears_the_shared_prereq_flags_in_redis(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    fake = _FlagRedis({"ourchat_chat": json.dumps(True), "support": json.dumps(True)})

    async def _redis():
        return fake
    monkeypatch.setattr(R, "_get_leader_redis", _redis)
    flags = R.RedisSyncDict("api_test:category_setup_complete", {"support": True})
    monkeypatch.setattr(R, "CATEGORY_SETUP_COMPLETE", flags)

    async def _reset_then_next_row():
        await R.reset_category_prereqs_shared()
        await flags.refresh_from_redis()     # what ensure_category_ready does first
        return dict(flags)
    assert asyncio.run(_reset_then_next_row()) == {}, "the next row found every category still 'done'"
    assert fake.deleted == ["api_test:category_setup_complete"]


def test_control_a_worker_local_flag_set_is_simply_cleared(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    flags = {"support": True}
    monkeypatch.setattr(R, "CATEGORY_SETUP_COMPLETE", flags)
    asyncio.run(R.reset_category_prereqs_shared())
    assert flags == {}
