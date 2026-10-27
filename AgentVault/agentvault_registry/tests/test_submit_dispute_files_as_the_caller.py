"""D6-784 (2026-10-17): submitDispute files a dispute as the calling agent, and says so.

The dispute route has no complainant field: it files as the agent of the token (routers/disputes.py, create_dispute). The
tool's schema still required complainant_did, sent it in the body (the route's model drops it), refused when the
argument equalled the defendant, and echoed the argument back as the complainant, so a caller naming another DID was
told the dispute had been filed as that DID. complainant_did is optional now and never sent; the result names the
complainant the route recorded, never the argument, with a note when the argument named another DID; and the
self-dispute check is on the caller, as the route's is. The route is a fake that answers the way create_dispute does.
"""
import json

from agentvault_registry.mcp import tools_developer as td
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

ME = "did:theprotocol:d6784-caller"
OTHER = "did:theprotocol:d6784-someone-else"
THEM = "did:theprotocol:d6784-defendant"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


def _route(monkeypatch):
    posts = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posts.append((url, json))
            if url.endswith("/api/v1/disputes/"):
                # create_dispute's answer: the complainant is the agent of the token, whatever the body said
                return _Resp(201, {"id": 9, "status": "OPEN", "complainant_did": ME,
                                   "defendant_did": json["defendant_did"], "created_at": "2026-10-17T01:00:00Z"})
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(td.httpx, "AsyncClient", _Client)
    return posts


def _me():
    return MCPAuthContext(auth_type="agent", agent_did=ME, raw_token="t")


def _schema():
    return next(s for s in td.DEVELOPER_TOOL_SCHEMAS if s["name"] == "theprotocol_submitDispute")


def test_the_schema_asks_only_for_the_defendant_and_says_who_files():
    s = _schema()
    assert s["inputSchema"]["required"] == ["defendant_did"]
    assert "complainant_did" in s["inputSchema"]["properties"], "older callers that still send it are not refused"
    assert "in the name of the calling agent" in s["description"]
    assert "Not used" in s["inputSchema"]["properties"]["complainant_did"]["description"]


async def test_another_complainant_did_is_neither_sent_nor_reported_as_the_filer(monkeypatch):
    posts = _route(monkeypatch)
    out = await td.submit_dispute(_me(), defendant_did=THEM, complainant_did=OTHER)
    assert "error" not in out and out["dispute_id"] == 9
    assert posts == [(f"{td.REGISTRY_SELF_URL}/api/v1/disputes/", {"defendant_did": THEM})]
    assert out["complainant_did"] == ME and out["defendant_did"] == THEM
    assert OTHER in out["note"] and "filed as the calling agent" in out["note"] and ME in out["note"]


async def test_the_self_dispute_check_is_on_the_caller_not_the_argument(monkeypatch):
    posts = _route(monkeypatch)
    # an argument naming the defendant as complainant does not make it a self-dispute: the caller files
    out = await td.submit_dispute(_me(), defendant_did=THEM, complainant_did=THEM)
    assert "error" not in out and out["complainant_did"] == ME and len(posts) == 1
    # the caller as defendant is one, whatever the argument names; refused before any call, as the route would
    posts.clear()
    out = await td.submit_dispute(_me(), defendant_did=ME, complainant_did=OTHER)
    assert "same agent" in out["error"] and posts == []


async def test_control_the_callers_own_did_carries_no_note(monkeypatch):
    _route(monkeypatch)
    out = await td.submit_dispute(_me(), defendant_did=THEM, complainant_did=ME)
    assert out["complainant_did"] == ME and "note" not in out
