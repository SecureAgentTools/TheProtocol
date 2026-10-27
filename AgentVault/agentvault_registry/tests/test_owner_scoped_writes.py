"""§MCPTEST30 (2026-10-01) — writes and reads that took a caller's token and never asked whose object it was.

Found by three read-only audits of every owner-scoped MCP tool, each confirmed in the code before it was changed:
  * POST /agents/{did}/deployments/{id}/status and /logs took a developer JWT and never used it (the status update
    looked the deployment up by id alone, and blanked its logs when the body carried none);
  * the agent log routes decided ownership from `card_data['did']`, a field of the card CONTENT its owner writes;
  * POST /bundles/{id}/rating wrote a rating without looking the bundle up (private and hidden bundles included);
  * GET /guild/orders/{id} served the delivered work to anyone, with no login, before the poster verified or paid;
  * the legacy POST /contracts/{id}/mark-failed let the client cancel over submitted work and refund it to itself,
    and both cancel doors refunded a milestone whose release was already in flight.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

OWNER, STRANGER = 7, 8
DID = "did:theprotocol:owner-agent"


def _status(coro):
    with pytest.raises(HTTPException) as e:
        asyncio.run(coro)
    return e.value.status_code


class _R:
    def __init__(self, row=None, rows=None, scalar=None):
        self._row, self._rows, self._scalar = row, rows or [], scalar

    def first(self):
        return self._row

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    @property
    def rowcount(self):
        return 1


class RecordingDB:
    """Records every statement; answers from a handler (sql, params) -> _R."""

    def __init__(self, handler=None):
        self.sql, self.handler, self.commits = [], handler or (lambda sql, p: _R()), 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append((sql, params))
        return self.handler(sql, params)

    async def commit(self):
        self.commits += 1


# ── CI/CD: the deployment writes ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cicd(monkeypatch):
    from agentvault_registry.routers import agent_cicd as R
    calls = []

    async def permission(db, agent_did, developer_id):
        calls.append(("permission", agent_did, developer_id))
        if developer_id != OWNER:
            raise HTTPException(status_code=403, detail="You don't have permission to manage this agent")
        return SimpleNamespace(did=agent_did)

    async def update(db, deployment_id, upd, agent_did=None):
        calls.append(("update", deployment_id, agent_did))
        return {"ok": True}
    monkeypatch.setattr(R.agent_cicd_service, "_get_agent_with_permission", permission)
    monkeypatch.setattr(R.agent_cicd_service, "update_deployment_status", update)
    return R, calls


def test_a_stranger_cannot_rewrite_a_deployment_status_and_nothing_is_called(cicd):
    R, calls = cicd
    body = R.UpdateDeploymentStatusBody(status="failed")
    dep = uuid.uuid4()
    assert _status(R.update_deployment_status(agent_did=DID, deployment_id=dep, status_update=body,
                                              current_developer=SimpleNamespace(id=STRANGER), db=None)) == 403
    assert [c[0] for c in calls] == ["permission"]
    out = asyncio.run(R.update_deployment_status(agent_did=DID, deployment_id=dep, status_update=body,
                                                 current_developer=SimpleNamespace(id=OWNER), db=None))
    assert out == {"ok": True} and calls[-1] == ("update", str(dep), DID), "the service is told which agent"


def test_a_stranger_cannot_append_deployment_logs_and_nothing_is_written(cicd):
    R, calls = cicd
    db = RecordingDB()
    assert _status(R.append_deployment_logs(agent_did=DID, deployment_id=uuid.uuid4(),
                                            log_data=R.AppendDeploymentLogsBody(logs="x"),
                                            current_developer=SimpleNamespace(id=STRANGER), db=db)) == 403
    assert db.sql == [] and db.commits == 0


def test_the_status_update_binds_the_agent_and_keeps_logs_it_was_not_given():
    from agentvault_registry.services.agent_cicd_service import agent_cicd_service as svc

    def handler(sql, p):
        if "SELECT agent_did, status, started_at" in sql:
            return _R(row=None)   # a deployment of ANOTHER agent: the bound read finds nothing
        return _R()
    db = RecordingDB(handler)
    assert _status(svc.update_deployment_status(db, "dep-1", {"status": "success"}, agent_did=DID)) == 404
    sql, params = db.sql[0]
    assert "agent_did = :agent_did" in sql and params["agent_did"] == DID
    assert not any(s.lstrip().upper().startswith("UPDATE") for s, _ in db.sql), "nothing written for a foreign one"
    import inspect
    src = inspect.getsource(type(svc).update_deployment_status)
    assert "logs = COALESCE(:logs, logs)" in src and "logs = :logs," not in src


# ── agent logs ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_log_ownership_comes_from_server_set_columns_only():
    import inspect
    from agentvault_registry.routers import agent_logs as L
    src = inspect.getsource(L)
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("#", '"', "'")))
    assert "card_data['did']" not in code.replace("`card_data['did']`", ""), "card content is not ownership"
    assert src.count("await _developer_owns_agent(") == 3, "GET, POST (developer) and DELETE ask the one rule"


@pytest.mark.parametrize("owner_rows,expected", [((None, None), False), ((("a",), None), True), ((None, ("c",)), True)])
def test_the_rule_asks_the_agent_row_then_the_linked_card(owner_rows, expected):
    from agentvault_registry.routers import agent_logs as L
    answers = iter(owner_rows)
    db = RecordingDB(lambda sql, p: _R(row=next(answers)))
    assert asyncio.run(L._developer_owns_agent(db, DID, STRANGER)) is expected
    first = db.sql[0][0]
    assert "agents.creator_developer_id" in first
    if len(db.sql) > 1:
        assert "agent_cards.agent_did" in db.sql[1][0] and "card_data" not in db.sql[1][0]


def test_a_stranger_reads_no_logs_and_deletes_none(monkeypatch):
    from agentvault_registry.routers import agent_logs as L

    async def never(db, agent_did, developer_id):
        return False
    monkeypatch.setattr(L, "_developer_owns_agent", never)
    db = RecordingDB()
    out = asyncio.run(L.get_agent_logs(agent_did=DID, db=db, current_developer=SimpleNamespace(id=STRANGER),
                                       limit=100, offset=0, level=None, start_time=None, end_time=None))
    assert out == [] and db.sql == []
    assert _status(L.delete_agent_logs(agent_did=DID, db=db, current_developer=SimpleNamespace(id=STRANGER),
                                       before=None)) == 404
    assert db.sql == [] and db.commits == 0


# ── bundle rating ────────────────────────────────────────────────────────────────────────────────────────────────────

def _rate(db, dev_id, bid=None):
    from agentvault_registry.routers import bundles as B
    return B.rate_bundle(bundle_id=bid or str(uuid.uuid4()), body=B.RatingRequest(rating=5, comment=None),
                         current_developer=SimpleNamespace(id=dev_id), db=db)


def _bundle_db(row):
    # the route selects source_dev_id, visibility, is_official, is_hidden, source_org_id (D6-481: an 'org' bundle is
    # also rated by its organization's readers; a row with no organization asks no membership)
    return RecordingDB(lambda sql, p: _R(row=row) if "SELECT source_dev_id" in sql else _R())


@pytest.mark.parametrize("row,who", [
    ((OWNER, "private", False, False, None), STRANGER),
    ((OWNER, "org", False, False, None), STRANGER),
    ((OWNER, "public", False, True, None), STRANGER),
    ((OWNER, "public", True, True, None), OWNER),
    (None, STRANGER),
])
def test_a_bundle_the_caller_cannot_read_cannot_be_rated(row, who):
    db = _bundle_db(row)
    assert _status(_rate(db, who)) == 404
    assert not any("INSERT INTO bundle_ratings" in s for s, _ in db.sql) and db.commits == 0


def test_a_malformed_id_is_not_found_before_any_sql():
    db = _bundle_db(None)
    assert _status(_rate(db, STRANGER, bid="not-a-uuid")) == 404 and db.sql == []


@pytest.mark.parametrize("row,who", [((OWNER, "private", False, False, None), OWNER), ((OWNER, "public", False, False, None), STRANGER),
                                     ((OWNER, "private", True, False, None), STRANGER)])
def test_control_a_readable_bundle_is_rated(monkeypatch, row, who):
    from agentvault_registry.routers import bundles as B
    monkeypatch.setattr(B, "_emit_bundle", lambda *a, **k: None)
    db = _bundle_db(row)
    assert asyncio.run(_rate(db, who)) == {"ok": True}
    assert any("INSERT INTO bundle_ratings" in s for s, _ in db.sql) and db.commits == 1


# ── the Guild deliverable ────────────────────────────────────────────────────────────────────────────────────────────

ORDER = {"id": "o1", "poster_did": "did:p", "worker_did": "did:w", "status": "submitted",
         "deliverable": {"uri": "https://example.invalid/work", "hash": "abc123"}}


def _guild_db(creator_of=None, org_member=False, poster_org=None):
    def handler(sql, p):
        if "FROM guild_work_orders WHERE id" in sql:
            return _R(row=dict(ORDER))
        if "FROM organizations WHERE treasury_agent_did" in sql:
            return _R(row=poster_org)
        if "FROM agents WHERE did = ANY" in sql:
            return _R(row=("1",) if creator_of is not None and p["dev"] == creator_of else None)
        if "FROM organization_members" in sql:
            return _R(row=("1",) if org_member else None)
        return _R(rows=[])
    return RecordingDB(handler)


def _detail(db, dev, monkeypatch):
    from agentvault_registry.routers import guild as G
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    return asyncio.run(G.order_detail(oid="o1", db=db, dev=dev))["order"]


@pytest.mark.parametrize("dev,db_kw,sees", [
    (None, {}, False),
    (SimpleNamespace(id=STRANGER, is_admin=False), {"creator_of": OWNER}, False),
    (SimpleNamespace(id=OWNER, is_admin=False), {"creator_of": OWNER}, True),
    (SimpleNamespace(id=STRANGER, is_admin=True), {}, True),
    (SimpleNamespace(id=STRANGER, is_admin=False), {"org_member": True, "poster_org": ("org-1", "Firm")}, True),
    (SimpleNamespace(id=STRANGER, is_admin=False), {"org_member": True, "poster_org": None}, False),
])
def test_the_deliverable_is_the_parties(monkeypatch, dev, db_kw, sees):
    o = _detail(_guild_db(**db_kw), dev, monkeypatch)
    if sees:
        assert o["deliverable"] == ORDER["deliverable"] and not o.get("deliverable_withheld")
    else:
        assert o["deliverable"] is None and o["deliverable_withheld"] is True
        assert o["deliverable_keys"] == ["hash", "uri"], "the key names, as the events already carry"


# ── the contract cancel doors ────────────────────────────────────────────────────────────────────────────────────────

def _contract_db(milestones, status="in_progress"):
    c = {"id": "c1", "client_did": "did:client", "provider_did": "did:provider", "status": status}

    def handler(sql, p):
        if "GROUP BY status" in sql:
            return _R(rows=[(k, v) for k, v in milestones.items() if v])
        if "status='releasing'" in sql and "COUNT" in sql:
            return _R(scalar=milestones.get("releasing", 0))
        if "status='submitted'" in sql and "COUNT" in sql:
            return _R(scalar=milestones.get("submitted", 0))
        return _R()
    return c, RecordingDB(handler)


@pytest.fixture
def legacy(monkeypatch):
    from agentvault_registry.routers import contracts as C

    def run(milestones, who, status="in_progress"):
        c, db = _contract_db(milestones, status)

        async def resolve(db_, cid):
            return dict(c)
        monkeypatch.setattr(C, "_resolve", resolve)
        coro = C.mark_contract_failed(contract_id="c1", body=C.ContractMarkFailed(reason="r"), db=db,
                                      current_agent=SimpleNamespace(did=who))
        return coro, db
    return run


def _wrote(db):
    return any(s.lstrip().upper().startswith("UPDATE CONTRACTS") for s, _ in db.sql)


@pytest.mark.parametrize("milestones,who", [
    ({"submitted": 1}, "did:client"),
    ({"releasing": 1}, "did:client"),
    ({"releasing": 1}, "did:provider"),
])
def test_legacy_mark_failed_refuses_over_delivered_or_releasing_work(legacy, milestones, who):
    coro, db = legacy(milestones, who)
    assert _status(coro) == 409 and not _wrote(db)


def test_control_the_provider_may_still_concede_over_submitted_work(legacy):
    coro, db = legacy({"submitted": 1}, "did:provider")
    try:
        asyncio.run(coro)
    except Exception:  # noqa: BLE001 — past the guards the fake has no settlement; reaching the UPDATE is the point
        pass
    assert _wrote(db), "the provider's concession (a refund against its own interest) is not refused"


@pytest.mark.parametrize("who", ["did:client", "did:provider"])
def test_the_v2_cancel_refuses_while_a_release_is_in_flight(monkeypatch, who):
    from agentvault_registry.routers import contracts_v2 as V
    c, db = _contract_db({"releasing": 1})

    async def must_load(db_, cid):
        return dict(c)
    monkeypatch.setattr(V, "_must_load", must_load)
    assert _status(V.cancel_as(db, "c1", who)) == 409 and not _wrote(db)


def test_control_the_v2_client_rule_over_submitted_work_still_stands(monkeypatch):
    from agentvault_registry.routers import contracts_v2 as V
    c, db = _contract_db({"submitted": 1})

    async def must_load(db_, cid):
        return dict(c)
    monkeypatch.setattr(V, "_must_load", must_load)
    assert _status(V.cancel_as(db, "c1", "did:client")) == 409 and not _wrote(db)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
