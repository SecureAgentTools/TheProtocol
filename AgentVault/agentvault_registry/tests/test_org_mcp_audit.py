"""V0650 (d) (2026-10-31, agentvault2-14): an organization's MCP calls, for its owners and admins.

Order gwo_a30897812b96ce9f5968fb75. GET /api/v1/organizations/{org_id}/mcp-audit serves the MCP call rows of the
organization's agents, newest first, paged on (timestamp, id): the tool, which agent, when, tier, outcome, latency and
whether the tool answered an error; never the arguments, the error text, the caller's address or user agent. Owner or
admin only. Through FastAPI on the real organizations router over real (SQLite) tables. Cases marked BASE fail on
6c1f036b (V0649), where the route and the helpers do not exist.
"""
from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import organizations
from agentvault_registry.security import get_current_developer
from agentvault_registry.security_oauth.audit_logger import SecurityAuditLog, SecurityEventType
from tests._sqlite_db import sqlite_db

OWNER, ADMIN, MEMBER, GUEST, P_OWNER, LAPSED = 1, 2, 3, 4, 5, 6
A1, A2, B1, C1 = "did:x:a1", "did:x:a2", "did:x:b1", "did:x:c1"
T0 = dt.datetime(2026, 10, 31, 5, 0, 0)
SECRET_JWT = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiJ4In0", "c2lnbmF0dXJlc2ln"])
SECRET_KEY = "avreg_" + "Zq9" * 12
SECRET_CS = "cs_" + "k7" * 16


def _row(rid, actor, ts, *, event=SecurityEventType.MCP_TOOL_INVOKED, actor_type="agent", target_type="mcp_tool",
         target="theprotocol_getMyBalance", details=None, outcome="success"):
    return SecurityAuditLog(id=rid, timestamp=ts, event_type=event, actor_type=actor_type, actor_id=actor,
                            target_type=target_type, target_id=target, action="tools/call", outcome=outcome,
                            severity="info",
                            details=json.dumps(details or {"tier": "2", "latency_ms": 12.5, "is_admin_server": False}),
                            actor_ip="203.0.113.9", user_agent="ua-secret", request_id="req-secret",
                            error_message=f"boom {SECRET_CS}")


def _seed():
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.Agent, SecurityAuditLog)
    s = db.sync
    db.devs = {}
    for i in (OWNER, ADMIN, MEMBER, GUEST, P_OWNER, LAPSED):
        db.devs[i] = models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x")
        s.add(db.devs[i])
    s.add(models.Organization(id="org-o", name="O", slug="o", owner_id=OWNER, settings={}))
    s.add(models.Organization(id="org-p", name="P", slug="p", owner_id=P_OWNER, settings={}))
    for n, (dev, org, role, active) in enumerate(((OWNER, "org-o", "owner", True), (ADMIN, "org-o", "admin", True),
                                                  (MEMBER, "org-o", "member", True), (GUEST, "org-o", "guest", True),
                                                  (LAPSED, "org-o", "admin", False), (P_OWNER, "org-p", "owner", True))):
        s.add(models.OrganizationMember(id=f"m{n}", organization_id=org, developer_id=dev, role=role, is_active=active))
    for i, (did, org) in enumerate(((A1, "org-o"), (A2, "org-o"), (B1, "org-p"), (C1, None)), start=1):
        s.add(models.Agent(id=i, did=did, client_id=f"c{i}", hashed_client_secret="x", creator_developer_id=OWNER,
                           organization_id=org, status="active"))
    planted = {"tier": "2", "latency_ms": 40.0, "is_admin_server": False,
               "args": {"client_secret": SECRET_CS, "jwt": SECRET_JWT},
               "result_summary": {"isError": True, "text": f"key {SECRET_KEY}"}}
    s.add_all([
        _row("r-a1-old", A1, T0, target="theprotocol_getMyBalance"),
        _row("r-a2", A2, T0 + dt.timedelta(minutes=5), event=SecurityEventType.MCP_TOOL_FAILED, outcome="failure",
             target="theprotocol_transferUnits", details=planted),
        _row("r-a1-new", A1, T0 + dt.timedelta(minutes=9), target="theprotocol_sendChatMessage"),
        _row("r-dev", "1", T0 + dt.timedelta(minutes=1), actor_type="developer"),                    # a developer's
        _row("r-b1", B1, T0 + dt.timedelta(minutes=2)),                                               # another org's
        _row("r-c1", C1, T0 + dt.timedelta(minutes=3)),                                               # no org
        _row("r-meta", "99", T0 + dt.timedelta(minutes=4), event=SecurityEventType.ADMIN_READ_MCP_AUDIT,
             actor_type="admin", target_type="developer_audit_log", target=A1),                       # a meta row
        _row("r-ironkey", A1, T0 + dt.timedelta(minutes=6), event=SecurityEventType.SUSPICIOUS_ACTIVITY,
             target_type="agent", target="ironkey.role_add"),                                         # not a call
    ])
    s.commit()
    return db


@pytest.fixture()
def call():
    db = _seed()
    app = FastAPI()
    app.include_router(organizations.router)
    who = {"id": OWNER}

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_developer] = lambda: db.devs[who["id"]]

    async def do(dev, org="org-o", **params):
        who["id"] = dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(f"/api/v1/organizations/{org}/mcp-audit", params=params)
    do.db = db
    return do


@pytest.mark.asyncio
@pytest.mark.parametrize("dev", [OWNER, ADMIN])
async def test_owners_and_admins_read_their_agents_calls_newest_first(call, dev):
    # BASE: 404
    r = await call(dev)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["id"] for x in body["rows"]] == ["r-a1-new", "r-a2", "r-a1-old"]
    assert body["agent_count"] == 2 and body["next_cursor"] is None and body["org_id"] == "org-o"


@pytest.mark.asyncio
@pytest.mark.parametrize("dev", [MEMBER, GUEST, LAPSED, P_OWNER])
async def test_members_guests_lapsed_admins_and_outsiders_are_refused(call, dev):
    # BASE: 404
    assert (await call(dev)).status_code == 403


@pytest.mark.asyncio
async def test_an_unknown_organization_is_named(call):
    # BASE: 404 "Not Found" from the bare app
    r = await call(OWNER, org="org-nope")
    assert r.status_code == 404 and "Organization not found" in r.text


@pytest.mark.asyncio
async def test_no_secret_reaches_a_row(call):
    # BASE: 404
    stored = call.db.sync.get(SecurityAuditLog, "r-a2")
    assert SECRET_CS in stored.details and SECRET_KEY in stored.details and stored.actor_ip   # the plant is there
    r = await call(OWNER)
    for secret in (SECRET_CS, SECRET_JWT, SECRET_KEY, "203.0.113.9", "ua-secret", "req-secret"):
        assert secret not in r.text, secret
    from agentvault_registry.routers.mcp_audit_log import ORG_ROW_KEYS
    for row in r.json()["rows"]:
        assert tuple(row.keys()) == ORG_ROW_KEYS
        assert all(row[k] is None for k in ("actor_ip", "user_agent", "request_id", "details", "error_message"))
    a2 = {x["id"]: x for x in r.json()["rows"]}["r-a2"]
    assert a2["is_error"] is True and a2["tier"] == "2" and a2["latency_ms"] == 40.0


@pytest.mark.asyncio
async def test_paging_partitions_rows_that_share_an_instant(call):
    # BASE: 404
    s = call.db.sync
    tie = T0 + dt.timedelta(hours=1)
    s.add_all([_row(f"tie-{k}", A1, tie) for k in ("a", "b", "c")] + [_row("after", A2, tie + dt.timedelta(minutes=1))])
    s.commit()
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await call(OWNER, **params)).json()
        seen += [x["id"] for x in body["rows"]]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 7 and pages == 4, seen
    assert seen[:4] == ["after", "tie-c", "tie-b", "tie-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["nonsense", "2026-10-31T05:00:00", "2026-10-31T05:00:00+00:00|r1", "x|y"])
async def test_a_malformed_cursor_is_refused(call, bad):
    # BASE: 404
    assert (await call(OWNER, cursor=bad)).status_code == 400


@pytest.mark.asyncio
async def test_a_cursor_whose_row_was_purged_still_pages(call):
    # BASE: 404
    cursor = f"{(T0 + dt.timedelta(minutes=7)).isoformat()}|gone-row"
    body = (await call(OWNER, cursor=cursor)).json()
    assert [x["id"] for x in body["rows"]] == ["r-a2", "r-a1-old"]


@pytest.mark.asyncio
@pytest.mark.parametrize("on", [True, False])
async def test_recording_says_whether_calls_are_recorded(call, monkeypatch, on):
    # BASE: 404
    from agentvault_registry.mcp import audit
    monkeypatch.setattr(audit, "MCP_AUDIT_LOGGING_ENABLED", on)
    assert (await call(OWNER)).json()["recording"] is on


@pytest.mark.asyncio
async def test_an_organization_without_agents_reads_empty(call):
    # BASE: 404
    s = call.db.sync
    s.add(models.Organization(id="org-e", name="E", slug="e", owner_id=OWNER, settings={}))
    s.commit()
    body = (await call(OWNER, org="org-e")).json()
    assert body["rows"] == [] and body["next_cursor"] is None and body["agent_count"] == 0


def test_the_statement_asks_for_agent_calls_ordered_with_a_tiebreak():
    # BASE: AttributeError
    from agentvault_registry.routers import mcp_audit_log as mal
    sql = str(mal.org_mcp_audit_stmt(["did:x:a1"], 51, (T0, "r9")).compile(dialect=postgresql.dialect()))
    assert "security_audit_logs.actor_type = " in sql and "security_audit_logs.target_type = " in sql
    assert "security_audit_logs.actor_id IN" in sql and " OR " in sql
    assert "ORDER BY security_audit_logs.timestamp DESC, security_audit_logs.id DESC" in sql


def test_the_serializer_reads_the_error_flag_and_redacts_a_credential_shaped_tool_name():
    # BASE: AttributeError
    from agentvault_registry.routers import mcp_audit_log as mal
    row = _row("r", A1, T0, target=f"theprotocol_x {SECRET_KEY}",
               details={"tier": 3, "latency_ms": 7, "result_summary": {"isError": False}})
    out = mal.serialize_org_call_row(row)
    assert out["is_error"] is False and out["tier"] == "3" and out["latency_ms"] == 7
    assert SECRET_KEY not in out["target_id"]
