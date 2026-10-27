"""§DOCSFIX CB-412 and CB-425: the card's compliance block states the scope the gate applies, and never goes out
without its digest.

CB-412: a regulated action declared without a scope was published with scope 'registry', while the gate
(regulatory_auth.check_regulatory_authorization) applied the action's default, per_subject for exchange.listing and
exchange.ipo; the profile PUT stores the document as written, so the signed card could state a scope the gate did not
apply. CB-425: the digest was added inside the same try as the authorization read; when that read raised while a
profile was declared, the card carried a compliance block without `digest` (schema-invalid, its signed leaf null).

The card is built whole (build_registry_card, unsigned) over a session that answers every read with nothing, with the
supply, the TEG fee config and the stats stubbed: the block is checked where peers read it.
"""
from types import SimpleNamespace

import pytest

from agentvault_registry.crud import crud_enforcement
from agentvault_registry.services import jurisdiction
from agentvault_registry.services import registry_card_builder as rcb
from agentvault_registry.services import regulatory_auth

PROFILE = {"name": "test-profile", "version": 1, "declared_at": "2026-10-16T00:00:00+00:00",
           "features_denied": ["fiat"],
           "requires_authorization": {"exchange.ipo": {"authority": "Example Authority", "mode": "enforce"},
                                      "fiat.lane": {"authority": "None held", "mode": "enforce"}}}


class _Rows:
    def scalar_one_or_none(self):
        return None

    def scalar(self):
        return 0

    def all(self):
        return []

    def first(self):
        return None

    def scalars(self):
        return self


class _Db:
    async def execute(self, *_a, **_k):
        return _Rows()


@pytest.fixture(autouse=True)
def _quiet_registry(monkeypatch):
    async def _empty():
        return {}

    async def _no_row(db):
        return None

    async def _stats(db):
        return {}

    async def _profile(db, *, fresh=False):
        return dict(PROFILE)

    monkeypatch.setattr(rcb, "_fetch_supply_audit", _empty)
    monkeypatch.setattr(rcb, "_fetch_fee_config", _empty)
    monkeypatch.setattr(rcb, "_build_stats_block", _stats)
    monkeypatch.setattr(rcb, "_FOUNDED_AT_CACHE", None)
    monkeypatch.setattr(crud_enforcement, "get_active_policy", _no_row)
    monkeypatch.setattr(jurisdiction, "get_profile", _profile)
    for k in ("EXCHANGE_ENABLED", "EXCHANGE_SOLVENCY_CARD_ENABLED", "RC_PUBLISH_PEER_ROSTER"):
        monkeypatch.delenv(k, raising=False)


def _auths(monkeypatch, result):
    async def _active(db):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(regulatory_auth, "active_card_authorizations", _active)


async def test_an_entry_without_a_scope_publishes_the_scope_the_gate_applies(monkeypatch):
    _auths(monkeypatch, [])
    card = await rcb.build_registry_card(_Db(), sign=False)
    actions = card["compliance"]["jurisdiction_profile"]["regulated_actions"]
    assert actions["exchange.ipo"]["scope"] == "per_subject"
    assert actions["fiat.lane"]["scope"] == "registry"
    for a, e in PROFILE["requires_authorization"].items():
        assert actions[a]["scope"] == regulatory_auth.declared_scope(a, e)


async def test_a_failed_authorization_read_still_publishes_the_digest(monkeypatch):
    _auths(monkeypatch, RuntimeError("authorization read failed"))
    card = await rcb.build_registry_card(_Db(), sign=False)
    block = card["compliance"]
    assert "jurisdiction_profile" in block and "regulatory_authorizations" not in block
    assert block["digest"] == regulatory_auth.compliance_digest(block)


def test_the_gate_and_the_card_read_one_rule():
    assert regulatory_auth.declared_scope("exchange.listing", {}) == "per_subject"
    assert regulatory_auth.declared_scope("exchange.ipo", {"scope": "registry"}) == "registry"
    assert regulatory_auth.declared_scope("fiat.lane", {}) == "registry"


async def test_the_gate_still_looks_up_per_subject_for_an_ipo_declared_without_scope(monkeypatch):
    """Not a change: the gate's own lookup, now through declared_scope, asks for the subject (control for the card)."""
    asked = []

    async def _active(db, action, subject_ref):
        asked.append((action, subject_ref))
        return SimpleNamespace(id=1, reference_id="REF-1")   # covered: the gate allows

    monkeypatch.setattr(jurisdiction, "mode", lambda: "shadow")
    monkeypatch.setattr(regulatory_auth, "active_authorization", _active)
    await regulatory_auth.check_regulatory_authorization(_Db(), "exchange.ipo", subject_ref="ACME")
    await regulatory_auth.check_regulatory_authorization(_Db(), "fiat.lane", subject_ref="ignored")
    assert asked == [("exchange.ipo", "ACME"), ("fiat.lane", None)]
