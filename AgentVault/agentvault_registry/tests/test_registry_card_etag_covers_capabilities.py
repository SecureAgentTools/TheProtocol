"""§DOCSFIX CB-426: the card's entity tag changes when a signed or federation-relevant value derived from the
environment changes.

The capabilities block is signed as a whole, but it was outside the ETag basis, as were identity.federation_base_url
and the SPIRE bundle endpoint: a registry recreated with the bridge, the euro lane or a ZKP phase switched, or with a
new federation address, answered 304 to every peer's conditional fetch, and each peer kept the old signed values until
something else turned the tag. They are in the basis now, read the same way on the cheap 304 path and in a full build.
"""
import pytest

from agentvault_registry.crud import crud_enforcement
from agentvault_registry.services import jurisdiction
from agentvault_registry.services import registry_card_builder as rcb
from agentvault_registry.services import regulatory_auth


def _tag(identity=None):
    return rcb._etag_from_basis({}, rcb._id_subset(identity or {}), None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("TOKEN_BRIDGE_ENABLED", "FIAT_ONRAMP_ENABLED", "ZKP_PHASE_2_ENABLED", "ZKP_PHASE_6_ENABLED",
              "SPIRE_BUNDLE_ENDPOINT", "IS_CENTRAL_REGISTRY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")


@pytest.mark.parametrize("name,value", [("TOKEN_BRIDGE_ENABLED", "false"), ("FIAT_ONRAMP_ENABLED", "true"),
                                        ("ZKP_PHASE_2_ENABLED", "true"), ("IS_CENTRAL_REGISTRY", "true")])
def test_a_capability_switch_turns_the_tag(monkeypatch, name, value):
    before = _tag()
    monkeypatch.setenv(name, value)
    assert _tag() != before


def test_a_new_bundle_endpoint_turns_the_tag(monkeypatch):
    before = _tag()
    monkeypatch.setenv("SPIRE_BUNDLE_ENDPOINT", "https://frame.example:8665/")
    assert _tag() != before


def test_a_new_federation_address_turns_the_tag():
    assert _tag({"federation_base_url": "https://a.example:8443"}) != _tag({"federation_base_url": "https://b.example:8443"})


def test_the_software_version_still_does_not():
    # by design: every roll changes it, and it must not make every peer re-read every card (the spec, section 8)
    assert _tag({"software_version": "TheProtocolReleaseV0618"}) == _tag({"software_version": "TheProtocolReleaseV0619"})


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


async def test_the_304_path_and_the_full_build_agree(monkeypatch):
    async def _empty(*_a, **_k):
        return {}

    async def _none(*_a, **_k):
        return None

    async def _no_auths(db):
        return []

    monkeypatch.setattr(rcb, "_fetch_supply_audit", _empty)
    monkeypatch.setattr(rcb, "_fetch_fee_config", _empty)
    monkeypatch.setattr(rcb, "_build_stats_block", _empty)
    monkeypatch.setattr(rcb, "_FOUNDED_AT_CACHE", None)
    monkeypatch.setattr(crud_enforcement, "get_active_policy", _none)
    monkeypatch.setattr(jurisdiction, "get_profile", _none)
    monkeypatch.setattr(regulatory_auth, "active_card_authorizations", _no_auths)
    for k in ("EXCHANGE_ENABLED", "EXCHANGE_SOLVENCY_CARD_ENABLED", "RC_PUBLISH_PEER_ROSTER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("SPIRE_BUNDLE_ENDPOINT", "https://frame.example:8665/")
    card = await rcb.build_registry_card(_Db(), sign=False)
    assert card["capabilities"]["bridge_capability"] == "none"
    assert card["lifecycle"]["card_etag"] == await rcb.compute_serve_etag(_Db())
