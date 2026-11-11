"""D6-825 (V0658 (c)): a claimant withdraws its own OPEN TEG dispute.

There was no way to close a TEG dispute short of an admin's ruling, so every dispute filed stayed OPEN: the MCP tester's
phase-4 fixture alone was 187 of the 319 OPEN disputes on sbx-alpha's TEG (2026-09-03 to 10-24). Now
POST /api/v1/disputes/{dispute_log_id}/withdraw takes the claimant's own OPEN dispute to WITHDRAWN: no ruling, no penalty,
no money, the row keeping who withdrew it, when and why. Anyone else, and any other status, is refused and the row stays
as it was.

Through FastAPI on the real dispute router, on a SQLite database holding the real dispute table; the agent credential
is a double. RED on v0657/cut (e70fb58b2): the route does not exist (405) and DisputeStatus has no WITHDRAWN.
"""
import ast
import pathlib
import re
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from teg_core_service.api.v1 import endpoints_dispute as ep
from teg_core_service.core.security import verify_agent_token
from teg_core_service.database.db_session import get_db
from teg_core_service.database.models import DisputeStatus, TEGDisputeLog

ROOT = pathlib.Path(__file__).resolve().parents[1]
A, B, C = "did:theprotocol:claimant-a", "did:theprotocol:defendant-b", "did:theprotocol:stranger-c"


@pytest.fixture
def teg():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TEGDisputeLog.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    who = {"did": A}

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(ep.router, prefix="/api/v1/disputes")
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[verify_agent_token] = lambda: who["did"]

    def file(status=DisputeStatus.OPEN, claimant=A, defendant=B):
        with Session() as db:
            row = TEGDisputeLog(claimant_agent_did=claimant, defendant_agent_did=defendant, reason_code="test_dispute",
                                brief_description="phase-4 mcp-tester dispute fixture", status=status)
            db.add(row)
            db.commit()
            return row.dispute_log_id

    def read(dispute_id):
        with Session() as db:
            return db.get(TEGDisputeLog, dispute_id)

    def withdraw(dispute_id, as_did, body=None):
        who["did"] = as_did
        kw = {} if body is None else {"json": body}
        return TestClient(app).post(f"/api/v1/disputes/{dispute_id}/withdraw", **kw)

    return file, read, withdraw


def test_the_claimant_withdraws_its_open_dispute(teg):
    file, read, withdraw = teg
    d = file()
    r = withdraw(d, A, {"reason": "the fixture of this run"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["dispute_log_id"] == d and out["status"] == "WITHDRAWN", out
    assert re.match(rf"^Withdrawn by its claimant {re.escape(A)} at \d{{4}}-.*: the fixture of this run$",
                    out["resolution_notes"]), out["resolution_notes"]
    row = read(d)
    assert row.status == DisputeStatus.WITHDRAWN and row.resolution_notes == out["resolution_notes"]


def test_the_reason_is_optional(teg):
    file, read, withdraw = teg
    d = file()
    r = withdraw(d, A)
    assert r.status_code == 200, r.text
    assert re.fullmatch(rf"Withdrawn by its claimant {re.escape(A)} at \S+", r.json()["resolution_notes"]), r.json()
    assert read(d).status == DisputeStatus.WITHDRAWN


@pytest.mark.parametrize("who", [B, C])
def test_no_one_but_the_claimant_withdraws_it(teg, who):
    file, read, withdraw = teg
    d = file()
    r = withdraw(d, who)
    assert r.status_code == 403 and r.json()["detail"] == "Only the dispute's claimant can withdraw it", r.text
    assert read(d).status == DisputeStatus.OPEN and read(d).resolution_notes is None


@pytest.mark.parametrize("status", [DisputeStatus.UNDER_REVIEW, DisputeStatus.RESOLVED_FAVOR_INITIATOR,
                                    DisputeStatus.REJECTED, DisputeStatus.RESOLVED_NO_ACTION])
def test_a_dispute_that_is_no_longer_open_stays_as_it_is(teg, status):
    file, read, withdraw = teg
    d = file(status=status)
    r = withdraw(d, A)
    assert r.status_code == 409 and r.json()["detail"] == f"Only an OPEN dispute can be withdrawn; this one is {status.value}"
    assert read(d).status == status


def test_a_second_withdrawal_is_refused(teg):
    file, read, withdraw = teg
    d = file()
    assert withdraw(d, A).status_code == 200
    first = read(d).resolution_notes
    r = withdraw(d, A, {"reason": "again"})
    assert r.status_code == 409 and r.json()["detail"].endswith("this one is WITHDRAWN"), r.text
    assert read(d).resolution_notes == first


def test_an_unknown_dispute_is_not_found(teg):
    _, _, withdraw = teg
    r = withdraw("00000000-0000-4000-8000-000000000000", A)
    assert r.status_code == 404 and r.json()["detail"] == "Dispute not found", r.text


def test_a_reason_longer_than_500_is_refused_and_nothing_changes(teg):
    file, read, withdraw = teg
    d = file()
    r = withdraw(d, A, {"reason": "x" * 501})
    assert r.status_code == 422, r.text
    assert read(d).status == DisputeStatus.OPEN


def test_the_status_and_its_migration():
    assert DisputeStatus.WITHDRAWN.value == "WITHDRAWN"
    src = (ROOT / "alembic" / "versions" / "0009_dispute_withdrawn.py").read_text()
    tree = ast.parse(src)
    assigns = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    assert assigns["revision"] == "0009_dispute_withdrawn" and len(assigns["revision"]) <= 32
    assert assigns["down_revision"] == "0008_widen_memo_errmsg_text"
    assert "ADD VALUE IF NOT EXISTS 'WITHDRAWN'" in src   # idempotent: every boot replays it
    # the label goes to the enum type the column has (dispute_status_enum on every database 0001 made), read from the
    # catalog, never to the unused disputestatus by name
    assert "ALTER TYPE disputestatus" not in src and "a.attname = 'status'" in src and "teg_dispute_logs" in src
    heads = {n for n in (ROOT / "alembic" / "versions").glob("*.py")}
    downs = set()
    for f in heads:
        t = ast.parse(f.read_text())
        for n in t.body:
            if isinstance(n, ast.Assign) and any(getattr(x, "id", "") == "down_revision" for x in n.targets):
                if isinstance(n.value, ast.Constant) and n.value.value:
                    downs.add(n.value.value)
    revs = set()
    for f in heads:
        for n in ast.parse(f.read_text()).body:
            if isinstance(n, ast.Assign) and any(getattr(x, "id", "") == "revision" for x in n.targets):
                revs.add(n.value.value)
    assert revs - downs == {"0009_dispute_withdrawn"}, revs - downs   # one head, this one


def test_the_ledger_gate_knows_the_route_moves_no_value():
    from teg_core_service.core import ledger_gate as lg
    route = ("POST", "/api/v1/disputes/{dispute_log_id}/withdraw")
    assert route in lg.NO_VALUE and route not in lg.STARTING and route not in lg.FINISHING
