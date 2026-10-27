"""SEC-23 (2026-10-18): the registry refuses an operator name the network would confuse with a registry it already
knows, at every door where an operator gets its name: the application, its approval, its activation and the
self-service provisioning.

A TEG's partner rule (agentvault2-5b's ledgergate3 TEG) matches an operator's certificate name against a partner entry's
TEG id or registry id with one teg-layer-, teg- or registry- prefix dropped and only letters and digits kept. So an
operator of EU named asia, teg-asia or a-sia would match the partner entry of the frame ASIA, and a remove-partner for
that operator (its quarantine) would drop the frame's entry with it. The rule (core/operator_names.colliding_peer_name)
compares a name by that key against this frame's own name (its trust domain, registry id and TEG id) and against every
peer_registries row's name and trust domain. A cloud operator's row under the same safe name is not a collision (it is
the operator's own row, or an exact duplicate the duplicate-name checks refuse).

Through FastAPI on the real routers, with the doubles of tests/test_sec_reserved_operator_names.py; the database double
also answers the peer rows. RED on mcptest/v0622 3665f8cb: every colliding name is accepted at each door; the controls
(names that collide with nothing) pass on both.
"""
from __future__ import annotations

import hashlib
import types
from datetime import timedelta

import pytest

from agentvault_registry.routers import operator_applications as oa
from agentvault_registry.routers import operator_self_service as oss
from tests.test_sec_reserved_operator_names import (  # noqa: F401  (mail is a fixture)
    NOW, _Db, _Res, _application, _apply, _client, mail,
)

PEERS = [
    ("ASIA", "asia.theprotocol.cloud", "frame"),                  # a peer frame
    ("amsterdam", "eu.theprotocol.cloud", "cloud_operator"),      # another operator of this frame
    ("Sandbox Alpha", "sbx-alpha.theprotocol.cloud", "discovered"),
]
COLLIDING = ["asia", "ASIA", " Asia ", "teg-asia", "a-sia", "ams-terdam", "eu", "sbx-alpha", "sandboxalpha"]
ORDINARY = ["lisbon", "Amsterdam Freight", "asian-cargo"]


class _PeerDb(_Db):
    """_Db, and the rows of peer_registries for the collision read."""

    def __init__(self, rows=None, peers=PEERS):
        super().__init__(rows)
        self.peers = list(peers)

    async def execute(self, stmt, *a, **k):
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT peer_registries.name, peer_registries.trust_domain, peer_registries.peer_type"):
            return _Res(rows=self.peers)
        return await super().execute(stmt, *a, **k)


@pytest.fixture(autouse=True)
def eu_frame(monkeypatch):
    """This registry is the frame EU."""
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    monkeypatch.setenv("LOCAL_TEG_ID", "teg-layer-eu")


def test_the_key_is_the_partner_rules():
    from agentvault_registry.core.operator_names import peer_key
    assert {peer_key(v) for v in ("asia", "ASIA", "teg-asia", "teg-layer-asia", "registry-asia", "a-sia")} == {"asia"}
    assert peer_key("teg-layer-sandbox-beta") == "sandboxbeta" and peer_key("") == ""


# ── POST /api/v1/operator-applications ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", COLLIDING)
def test_red_an_application_under_a_colliding_name_is_refused_before_anything_is_stored(name, mail):
    db = _PeerDb()
    r = _apply(name, db)
    assert r.status_code == 422, (name, r.status_code, r.text)
    assert "would be confused with" in r.json()["detail"], r.text
    assert db.added == [] and db.commits == 0 and mail == [], (name, db.added, mail)


@pytest.mark.parametrize("name", ORDINARY)
def test_control_a_name_that_collides_with_nothing_is_stored(name, mail):
    db = _PeerDb()
    r = _apply(name, db)
    assert r.status_code == 200, (name, r.status_code, r.text)
    assert any(isinstance(o, oa.models.OperatorApplication) for o in db.added)


# ── the approval, the activation and the self-provisioning ─────────────────────────────────────────────────────────

def test_red_an_application_that_now_collides_is_not_approved(mail):
    app_row = _application("asia")
    r = _client(oa.router, _PeerDb({"operator_applications": app_row})).post(
        "/api/v1/admin/operator-applications/app-sec21/approve", json={"notes": ""})
    assert r.status_code == 409, (r.status_code, r.text)
    assert "would be confused with" in r.json()["detail"], r.text
    assert app_row.status == "pending" and app_row.activation_code_hash is None, vars(app_row)
    assert mail == [], mail


def test_red_an_approved_colliding_name_is_not_activated_and_the_code_is_not_spent(mail, monkeypatch):
    from agentvault_registry.core import host_reach
    monkeypatch.setattr(host_reach, "host_reach_available", lambda: (True, "test: a runner answers"))
    monkeypatch.setattr(host_reach, "host_route", lambda: (None, "test: no provisioning in this test"))
    code = "op_activate_" + "cd" * 32
    app_row = _application("teg-asia", status="approved")
    app_row.activation_code_hash = hashlib.sha256(code.encode()).hexdigest()
    app_row.activation_code_expires_at = NOW + timedelta(days=3)
    dev = types.SimpleNamespace(id=11, email="applicant@example.test", name="Applicant", is_admin=False,
                                is_federation_operator=False, federation_operator_status=None, flare_tier=None)
    r = _client(oa.router, _PeerDb({"operator_applications": app_row}), developer=dev).post(
        "/api/v1/operators/activate", json={"activation_code": code})
    assert r.status_code == 409, (r.status_code, r.text)
    assert "would be confused with" in r.json()["detail"] and "NOT been used" in r.json()["detail"], r.text
    assert app_row.activated_at is None and dev.is_federation_operator is False, vars(app_row)


def test_red_self_provisioning_under_a_colliding_name_is_refused(monkeypatch):
    monkeypatch.setenv("FIAT_GENESIS_REGISTRY", "true")

    async def _none_active(_db):
        return 0

    monkeypatch.setattr(oss, "count_active_cloud_operators", _none_active)
    dev = types.SimpleNamespace(id=12, email="backer@example.test", name="Backer", is_admin=False,
                                is_federation_operator=False, federation_operator_status=None,
                                provisioning_unlocked_until=NOW + timedelta(days=20), provisioning_months_total=1)
    for name in ("asia", "a-sia", "sbx-alpha"):
        db = _PeerDb()
        r = _client(oss.router, db, developer=dev).post("/api/v1/operators/self-provision", json={"name": name})
        assert r.status_code == 400, (name, r.status_code, r.text)
        assert "would be confused with" in r.json()["detail"], (name, r.text)
        assert db.added == [] and db.commits == 0, (name, db.added)


def test_an_operators_own_row_under_its_safe_name_is_no_collision(mail):
    """A cloud operator's row under the applicant's own safe name is the operator's own (a provisioning tried again) or
    an exact duplicate the duplicate-name checks refuse: this rule does not refuse it."""
    db = _PeerDb(peers=[("lisbon", "eu.theprotocol.cloud", "cloud_operator")])
    r = _apply("lisbon", db)
    assert r.status_code == 200, (r.status_code, r.text)
