"""SEC-21 (2026-10-17): the registry refuses an operator name the network reserves, at every door where an operator
gets its name: the application, its approval, its activation and the self-service provisioning.

The event store reads "origin" as this frame's own services (its is_origin rule) and refuses a caller named so since
fix/es-sec3 59e7548; the registry reserved no name, so an operator could be approved as "origin", provisioned, and then
refused by its frame's store. The rule (core/operator_names.reserved_operator_name) also covers the other names the
store or this code treats as something other than one operator's: unknown, commander, local registry, a name starting
with peer:, a name whose TEG id would read as a frame's (layer, layer-*), a name starting with registry- (read without
that prefix), and the four container labels the network maps onto other operators. A name is compared as typed (case
and surrounding spaces ignored) and in the slug forms the provisioner and the licence matching derive from it.

Through FastAPI on the real routers. Doubles: the database session (it answers each read by the table it names and
records what is added), the notification mail, the rate limiter (off), the host reach and the route the provisioning
would take (the base must reach the point where it spends the activation code), the self-service capacity count.
RED on 453cc8b8: every reserved name is accepted at each door; the controls (ordinary names) pass on both.
"""
from __future__ import annotations

import hashlib
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import operator_applications as oa
from agentvault_registry.routers import operator_self_service as oss

NOW = datetime.now(timezone.utc)

RESERVED = [
    "origin", "Origin", "  ORIGIN ", "o r i g i n", "Ori.gin",       # the store's own-services name, any spelling
    "unknown", "Commander", "Local Registry", "peer:asia.theprotocol.cloud",
    "layer", "Layer-EU",                                             # teg-layer, teg-layer-eu: a frame's TEG id
    "registry-eu",                                                   # read as eu
    "op-tokyo", "OP-SINGAPORE",                                      # labels mapped onto other operators
]
ORDINARY = ["Amsterdam Freight", "originals", "layered", "lisbon", "op-berlin"]

ADMIN = types.SimpleNamespace(id=7, email="admin@example.test", name="Admin", is_admin=True,
                              must_change_password=False, admin_treasury=False, admin_support=False,
                              admin_enforcement=False, admin_federation=True, admin_platform=False)


class _Res:
    def __init__(self, one=None, rows=()):
        self._one, self._rows = one, list(rows)

    def scalar_one_or_none(self):
        return self._one

    def scalar(self):
        return 0

    def scalars(self):
        return types.SimpleNamespace(first=lambda: self._one, all=lambda: [])

    def all(self):
        return list(self._rows)


class _Db:
    """Answers a lookup of a table in `rows` with that row; records every object added and every commit."""

    def __init__(self, rows=None):
        self.rows, self.added, self.commits = dict(rows or {}), [], 0

    async def execute(self, stmt, *a, **k):
        sql = " ".join(str(stmt).split())
        for table, row in self.rows.items():
            if f"FROM {table} " in sql + " ":
                return _Res(one=row)
        return _Res()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def refresh(self, obj):
        # what the database would fill in for a new application row
        for attr, value in (("created_at", NOW), ("bundle_download_count", 0), ("cloud_hosted", False),
                            ("env_choices", {})):
            if getattr(obj, attr, None) is None:
                setattr(obj, attr, value)


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(oa, "_send_themed_notification", lambda **kw: sent.append(kw.get("template")))
    monkeypatch.setattr(oa.limiter, "enabled", False)
    return sent


def _client(router, db, developer=ADMIN):
    app = FastAPI()
    app.include_router(router)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: developer
    app.dependency_overrides[oa.get_current_developer] = lambda: developer
    return TestClient(app, raise_server_exceptions=False)


def _apply(name, db):
    return _client(oa.router, db).post("/api/v1/operator-applications", json={
        "name": name, "email": "applicant@example.test", "accept_operator_terms": True})


# ── POST /api/v1/operator-applications ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", RESERVED)
def test_red_an_application_under_a_reserved_name_is_refused_before_anything_is_stored(name, mail):
    db = _Db()
    r = _apply(name, db)
    assert r.status_code == 422, (name, r.status_code, r.text)
    assert "is reserved" in r.json()["detail"], r.text
    assert db.added == [] and db.commits == 0 and mail == [], (name, db.added, mail)


@pytest.mark.parametrize("name", ORDINARY)
def test_control_an_ordinary_name_is_stored(name, mail):
    db = _Db()
    r = _apply(name, db)
    assert r.status_code == 200, (name, r.status_code, r.text)
    assert r.json()["name"] == name and r.json()["status"] == "pending"
    assert any(isinstance(o, oa.models.OperatorApplication) for o in db.added)


# ── POST /api/v1/admin/operator-applications/{id}/approve (an application filed before the rule) ──────────────────

def _application(name, status="pending", **kw):
    return types.SimpleNamespace(
        id="app-sec21", developer_id=None, name=name, email="applicant@example.test", organization=None,
        deployment="cloud", experience="beginner", use_case=None, status=status, reviewed_by=None, reviewed_at=None,
        review_notes=None, created_at=NOW, env_choices={}, bundle_path=None, bundle_generated_at=None,
        bundle_download_count=0, bundle_expires_at=None, docker_registry_username=None, spire_fingerprint=None,
        revoked_at=None, revoked_reason=None, revoked_by=None, activation_code_hash=None,
        activation_code_expires_at=None, activated_at=None, activated_developer_id=None,
        docker_pull_token_prefix=None, docker_pull_token_issued_at=None, cloud_hosted=False, cloud_url=None,
        cloud_port_base=None, cloud_provisioned_at=None, cloud_torn_down_at=None, cloud_stack_dir=None, **kw)


def test_red_an_application_under_a_reserved_name_is_not_approved(mail):
    app_row = _application("Origin")
    r = _client(oa.router, _Db({"operator_applications": app_row})).post(
        "/api/v1/admin/operator-applications/app-sec21/approve", json={"notes": ""})
    assert r.status_code == 409, (r.status_code, r.text)
    assert "is reserved" in r.json()["detail"], r.text
    assert app_row.status == "pending" and app_row.activation_code_hash is None, vars(app_row)
    assert mail == [], mail


def test_control_an_ordinary_application_is_approved(mail):
    app_row = _application("Amsterdam Freight")
    r = _client(oa.router, _Db({"operator_applications": app_row})).post(
        "/api/v1/admin/operator-applications/app-sec21/approve", json={"notes": ""})
    assert r.status_code == 200, (r.status_code, r.text)
    assert app_row.status == "approved" and app_row.activation_code_hash


# ── POST /api/v1/operators/activate (an application approved before the rule) ──────────────────────────────────────

def test_red_an_approved_reserved_name_is_not_activated_and_the_code_is_not_spent(mail, monkeypatch):
    from agentvault_registry.core import host_reach
    monkeypatch.setattr(host_reach, "host_reach_available", lambda: (True, "test: a runner answers"))
    monkeypatch.setattr(host_reach, "host_route", lambda: (None, "test: no provisioning in this test"))
    code = "op_activate_" + "ab" * 32
    app_row = _application("layer-eu", status="approved",)
    app_row.activation_code_hash = hashlib.sha256(code.encode()).hexdigest()
    app_row.activation_code_expires_at = NOW + timedelta(days=3)
    dev = types.SimpleNamespace(id=11, email="applicant@example.test", name="Applicant", is_admin=False,
                                is_federation_operator=False, federation_operator_status=None, flare_tier=None)
    r = _client(oa.router, _Db({"operator_applications": app_row}), developer=dev).post(
        "/api/v1/operators/activate", json={"activation_code": code})
    assert r.status_code == 409, (r.status_code, r.text)
    assert "is reserved" in r.json()["detail"] and "NOT been used" in r.json()["detail"], r.text
    assert app_row.activated_at is None and dev.is_federation_operator is False, vars(app_row)


# ── POST /api/v1/operators/self-provision ──────────────────────────────────────────────────────────────────────────

def test_red_self_provisioning_under_a_reserved_name_is_refused(monkeypatch):
    monkeypatch.setenv("FIAT_GENESIS_REGISTRY", "true")

    async def _none_active(_db):
        return 0

    monkeypatch.setattr(oss, "count_active_cloud_operators", _none_active)
    dev = types.SimpleNamespace(id=12, email="backer@example.test", name="Backer", is_admin=False,
                                is_federation_operator=False, federation_operator_status=None,
                                provisioning_unlocked_until=NOW + timedelta(days=20), provisioning_months_total=1)
    for name in ("origin", "registry-eu", "op-seoul"):
        db = _Db()
        r = _client(oss.router, db, developer=dev).post("/api/v1/operators/self-provision", json={"name": name})
        assert r.status_code == 400, (name, r.status_code, r.text)
        assert "is reserved" in r.json()["detail"], (name, r.text)
        assert db.added == [] and db.commits == 0, (name, db.added)
