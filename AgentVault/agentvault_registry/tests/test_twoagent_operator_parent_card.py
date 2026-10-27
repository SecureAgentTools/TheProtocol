"""§TWOAGENT (V0439, 2026-09-24) — a cloud operator accepts its parent frame's registry card (findings row 187's mirror).

Measured on production before this change: every operator refused its parent's card on every pull
(`[RegistryCardValidator] card refused from peer=... did_namespace_self` on every two-minute card-sync cycle: 30 an hour
each on amsterdam and lisbon, about 720 a day), so none of them had ever cached its parent's card, signature or logo (amsterdam's EU row: no
card, no signature, never pulled) while each held the OTHER frame's current card. The sandbox operators' parent cards froze
on 09-12/13 the same way. Row 187 let a frame accept its own operators' cards (they declare the frame's namespace by design);
nothing covered the operator side, where the parent's card declares the namespace the operator shares.

The allowance is decided by the operator's own configuration and its own peer row, never by the card. RED on 04642a97
(V0438): all but the control. V0440: the fixture mirrors the MEASURED env (FEDERATION_OPERATOR_ID empty); RED on
a425661d (V0439, which required it): the parent is not recognised.
"""
from __future__ import annotations

import os
import types

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import pytest

EU, ASIA = "eu.theprotocol.cloud", "asia.theprotocol.cloud"


def _row(name, peer_type, td):
    return types.SimpleNamespace(name=name, peer_type=peer_type, trust_domain=td, base_url=f"https://{name.lower()}.example:8443")


def _card(td):
    return {"registry_card_version": "0.6", "identity": {"registry_name": "EU", "trust_domain": td, "did_namespace": td}}


@pytest.fixture
def operator(monkeypatch):
    """amsterdam AS MEASURED (V0440): OPERATOR_DID set, FEDERATION_OPERATOR_ID present but EMPTY (all six running operators
    carry it so; V0439's fixture set it and so tested its own assumption), its parent's trust domain and namespace, not
    a mainframe."""
    from agentvault_registry.config import settings
    monkeypatch.setenv("FEDERATION_OPERATOR_ID", "")
    monkeypatch.setenv("OPERATOR_DID", "did:theprotocol:eu.theprotocol.cloud:5b0c3a1e-0000-4000-8000-00000000a001")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", EU)
    monkeypatch.setenv("DID_ISSUER_NAMESPACE", EU)
    monkeypatch.delenv("IS_CENTRAL_REGISTRY", raising=False)
    monkeypatch.setattr(settings, "REGISTRY_NAME", "amsterdam", raising=False)
    return monkeypatch


def _fs():
    from agentvault_registry.background_tasks import federation_sync as fs
    return fs


def test_an_operator_recognises_its_parent_frame(operator):
    assert _fs().is_my_parent_frame(_row("EU", "frame", EU)) is True


def test_the_other_frame_is_not_its_parent(operator):
    assert _fs().is_my_parent_frame(_row("asia", "frame", ASIA)) is False


def test_only_a_frame_row_can_be_the_parent(operator):
    for t in ("discovered", "cloud_operator", "", None):
        assert _fs().is_my_parent_frame(_row("EU", t, EU)) is False, t


def test_a_registry_without_an_operator_did_has_no_parent(operator):
    operator.delenv("OPERATOR_DID", raising=False)
    assert _fs().is_my_parent_frame(_row("EU", "frame", EU)) is False
    operator.setenv("OPERATOR_DID", "  ")
    assert _fs().is_my_parent_frame(_row("EU", "frame", EU)) is False


def test_a_sovereign_frame_never_takes_a_card_claiming_its_own_namespace(operator):
    """The impersonation defence stays on every mainframe, even with a frame row in its own trust domain."""
    from agentvault_registry.config import settings
    operator.setenv("IS_CENTRAL_REGISTRY", "true")
    operator.setenv("MAINFRAME_REGISTRY_NAMES", "eu")
    operator.setattr(settings, "REGISTRY_NAME", "eu", raising=False)
    assert _fs().is_my_parent_frame(_row("EU", "frame", EU)) is False


def test_the_parents_card_passes_the_validator_on_the_operator(operator):
    from agentvault_registry.services import registry_card_validator as v
    parent = _row("EU", "frame", EU)
    # the V0438 call site asked only the frame-side question: refused
    assert v.check_card_namespace(_card(EU), peer_trust_domain=EU, allow_own_namespace=False) == "did_namespace_self"
    # the V0439 call site adds the mirror: accepted, the other consistency checks still run
    assert v.check_card_namespace(_card(EU), peer_trust_domain=EU, allow_own_namespace=_fs().is_my_parent_frame(parent)) is None


def test_control_an_impostor_card_claiming_our_namespace_from_another_row_is_still_refused(operator):
    """Passes on both trees: the row decides, never the card."""
    from agentvault_registry.services import registry_card_validator as v
    other = _row("asia", "frame", ASIA)
    allow = getattr(_fs(), "is_my_parent_frame", lambda p: False)(other)
    assert v.check_card_namespace(_card(EU), peer_trust_domain=ASIA, allow_own_namespace=allow) in (
        "did_namespace_mismatch", "did_namespace_self")


def test_the_card_sync_asks_the_mirror_at_its_one_call_site():
    import inspect
    fs = _fs()
    src = inspect.getsource(fs)
    assert src.count("allow_own_namespace=_own_op or is_my_parent_frame(peer)") == 1
