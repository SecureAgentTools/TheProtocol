"""§DOCSFIX CB-394: the schema a registry serves is the published one, and it accepts the registry's own cards.

GET /.well-known/registry-card-schema.json served a vendored copy (static_schemas/registry_card_v0.6.schema.json) that
had drifted from the published schema (the doc source's specs/registry-card-v0.6.schema.json): it typed
endpoints.agent_card_well_known and endpoints.spire_bundle as strings while the builder publishes null in the first by
design (and in the second when no bundle endpoint is configured), lacked the date-time formats and several members, and
carried internal prose. Every live card failed it (EU, ASIA and four operator cards, one error each). The vendored file
is now a byte copy of the published one, and a card the builder makes validates against what the route serves.
"""
import json
import pathlib

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from agentvault_registry.crud import crud_enforcement
from agentvault_registry.routers import registry_card as rc
from agentvault_registry.services import jurisdiction
from agentvault_registry.services import registry_card_builder as rcb
from agentvault_registry.services import regulatory_auth

SRC = pathlib.Path(rc.__file__).resolve().parents[1]
VENDORED = SRC / "static_schemas" / "registry_card_v0.6.schema.json"
PUBLISHED = SRC / "static" / "new_registry_frontend" / "src" / "assets" / "docs" / "specs" / "registry-card-v0.6.schema.json"


def test_the_served_file_is_the_published_schema():
    assert VENDORED.read_bytes() == PUBLISHED.read_bytes()


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


@pytest.fixture
def built_card(monkeypatch):
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
    for k in ("EXCHANGE_ENABLED", "EXCHANGE_SOLVENCY_CARD_ENABLED", "RC_PUBLISH_PEER_ROSTER", "SPIRE_BUNDLE_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    # the session above answers every read with nothing, so no admin account lends the operator block its name;
    # a registry that has one (every frame and operator) publishes it as display_name
    persona = rcb.operator_persona
    monkeypatch.setattr(rcb, "operator_persona", lambda stored, admin: {**persona(stored, admin),
                                                                        "display_name": "Example Frame"})

    async def _build():
        return await rcb.build_registry_card(_Db(), sign=False)
    return _build


async def test_a_built_card_validates_against_what_the_route_serves(monkeypatch, built_card):
    monkeypatch.setattr(rc, "_SCHEMA_V06_BODY", None)
    schema = json.loads((await rc.get_well_known_registry_card_schema()).body)
    assert schema == json.loads(PUBLISHED.read_text(encoding="utf-8"))
    card = json.loads(json.dumps(await built_card(), default=str))   # as the route serializes it
    assert card["endpoints"]["agent_card_well_known"] is None and card["endpoints"]["spire_bundle"] is None
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(card),
                    key=lambda e: list(e.absolute_path))
    assert [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors] == []
