"""V0657 (b), session-code 2026-11-06: orgs v2 on a REAL Postgres, and the MIRROR TEST from the discovery's build
sequence (room seq 1475): an agent assigned to a listed organization on its home shows the organization's mark on a
peer within two pull cycles, and unassigned, the mark goes.

The mirror test drives the real federation feed (routers/federation_sync.get_agent_cards_for_sync, paged, as a peer
pulls it) on the HOME database and the real ingest (crud_peer_registry.upsert_agent_cards_from_peer) on the PEER
database, one pull cycle each:
  1. listed organization, agent assigned: the home exports the card with the org block, the peer's mirror stores it;
  2. the agent unassigned: its card moved, so the next pull carries it again, without the block, and the peer's
     mirror loses it;
and the control: an organization that is not listed exports no block at all.

Also on Postgres: the mark's predicate (listed, shown, active), an agent's level from its real grant, and one open join
request per agent and organization.

Skipped unless ORGS_TEST_DB and ORGS_TEST_PEER_DB name two throwaway databases it may WIPE (postgresql+asyncpg://...).
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

HOME = os.environ.get("ORGS_TEST_DB")
PEER = os.environ.get("ORGS_TEST_PEER_DB")
if not (HOME and PEER):
    pytest.skip("needs two REAL Postgres databases it may wipe: set ORGS_TEST_DB and ORGS_TEST_PEER_DB. Skipped, "
                "never silently passed.", allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
PEER_SVID = "spiffe://peer.test/service/peer-registry"
HOME_SVID = "spiffe://home.test/service/home-registry"


async def _fresh(url):
    from agentvault_registry.models import Base
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def home(monkeypatch):
    # the work record's loader reads a table only a migration creates (guild_travel_credentials); it is not under test
    async def no_record(db, dids):
        return {}
    monkeypatch.setattr("agentvault_registry.services.track_record.compact_track_records", no_record)
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_origin", lambda: "https://home.example")
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_url_static", lambda: "https://home.example/ui")
    engine, maker = await _fresh(HOME)
    yield maker
    await engine.dispose()


@pytest.fixture
async def peer():
    engine, maker = await _fresh(PEER)
    yield maker
    await engine.dispose()


async def _seed(maker, *, listed=True, show=True):
    """A developer, a listed (or not) organization with a logo, and its agent with a native card."""
    from agentvault_registry.models import Agent, AgentCard, Developer, Organization, OrganizationLogo
    async with maker() as s:
        dev = Developer(name=f"owner-{uuid.uuid4().hex[:8]}", email=f"o{uuid.uuid4().hex[:6]}@test.local", hashed_password="x",
                        is_verified=True)
        s.add(dev)
        await s.flush()
        org = Organization(id=str(uuid.uuid4()), name="TheProtocol Sessions", slug=f"sessions-{uuid.uuid4().hex[:6]}",
                           owner_id=dev.id, is_active=True, settings={"public_listing": listed})
        s.add(org)
        await s.flush()
        s.add(OrganizationLogo(organization_id=org.id, content_type="image/png", data=b"\x89PNG\r\n\x1a\n",
                               sha256="b" * 64, size=8))
        did = f"did:theprotocol:home.test:{uuid.uuid4()}"
        s.add(Agent(did=did, client_id=f"c-{uuid.uuid4().hex[:10]}", hashed_client_secret="x",
                    creator_developer_id=dev.id, status="active", enforcement_status="active",
                    organization_id=org.id, show_org=show))
        await s.flush()
        card = AgentCard(id=uuid.uuid4(), developer_id=dev.id, agent_did=did, name="session-code",
                         description="the implementation lane", is_active=True,
                         card_data=_exportable_card(did))
        s.add(card)
        await s.commit()
        return types_ns(dev=dev.id, org=org.id, slug=org.slug, did=did, card=str(card.id))


def _exportable_card(did):
    """A card the home may EXPORT. The feed withholds a card a fail-closed peer would refuse (routers/federation_sync
    export_skip_reason, the V0657 [FEDEXPORT] gate: it must validate as `agentvault.AgentCard`), and the old fixture (no
    protocolVersion, no humanReadableId, no authSchemes ...) was withheld, so both mirror tests failed with "coroutine
    raised StopIteration" on `next(...)` finding no exported card: the control then proved nothing about privacy. The
    fixture is checked against the same model HERE, so a schema that moves again fails in the fixture, naming the field,
    and never as a missing card."""
    from agentvault import AgentCard
    card = {"protocolVersion": "0.3.0", "humanReadableId": "home/session-code", "agentVersion": "1.0.0", "name": "session-code",
            "description": "the implementation lane", "url": "https://home.example/a2a",
            "provider": {"name": "Acme Labs", "url": "https://home.example"}, "capabilities": {},
            "authSchemes": [{"scheme": "none"}], "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
            "skills": [{"id": "implement", "name": "Implement", "description": "writes code", "tags": ["code"]}], "did": did}
    AgentCard.model_validate(card)
    return card


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


async def _pull(home_maker, peer_maker, since):
    """One pull cycle: the peer reads the home's feed from `since` and ingests what it carries. Returns the exported
    cards (as dicts) and the cursor after them."""
    from fastapi import Response
    from agentvault_registry.crud import crud_peer_registry
    from agentvault_registry.routers.federation_sync import get_agent_cards_for_sync
    async with home_maker() as h:
        page = await get_agent_cards_for_sync(since=since, limit=100, paged=True, peer_protocol_version="1.0",
                                              listing_carry=True, db=h, spiffe_id=PEER_SVID, response=Response())
    cards = [c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c) for c in page]
    async with peer_maker() as p:
        for c in cards:
            await crud_peer_registry.upsert_agent_cards_from_peer(p, HOME_SVID, c, peer_trust_domain="home.test",
                                                                  from_origin=True)
    cursor = max((dt.datetime.fromisoformat(str(c["updated_at"])) for c in cards), default=since)
    return cards, cursor


async def _mirror_mark(peer_maker, did):
    from agentvault_registry.services import org_mark
    async with peer_maker() as p:
        row = (await p.execute(text("SELECT card_data FROM agent_cards WHERE agent_did = :d"), {"d": did})).first()
    assert row is not None, "the peer holds no mirror of the card"
    return org_mark.extension_from_card(row[0])


async def test_mirror_an_agent_in_a_listed_org_shows_its_mark_on_a_peer_and_unassigned_it_goes(home, peer):
    from agentvault_registry.services import org_mark
    seeded = await _seed(home)
    cards, cursor = await _pull(home, peer, EPOCH)                       # pull cycle 1
    exported = next(c for c in cards if c["card_data"].get("did") == seeded.did)
    block = org_mark.extension_from_card(exported["card_data"])
    assert block and block["name"] == "TheProtocol Sessions" and block["slug"] == seeded.slug
    assert block["logo"] == f"https://home.example/api/v1/organizations/{seeded.org}/logo?v={'b' * 12}"
    mark = await _mirror_mark(peer, seeded.did)
    assert mark and mark["id"] == seeded.org, "the peer shows the organization's mark"

    async with home() as h:                                              # unassigned at home: the card moves
        await h.execute(text("UPDATE agents SET organization_id = NULL WHERE did = :d"), {"d": seeded.did})
        await org_mark.touch_agent_cards_no_commit(h, [seeded.did])
        await h.commit()
    cards, _ = await _pull(home, peer, cursor)                           # pull cycle 2
    again = [c for c in cards if c["card_data"].get("did") == seeded.did]
    assert again, "the moved card is in the next pull"
    assert org_mark.extension_from_card(again[0]["card_data"]) is None
    assert await _mirror_mark(peer, seeded.did) is None, "the mark is gone from the peer"


async def test_control_an_unlisted_org_or_a_hidden_mark_never_leaves_home(home, peer):
    from agentvault_registry.services import org_mark
    a = await _seed(home, listed=False)
    b = await _seed(home, listed=True, show=False)
    cards, _ = await _pull(home, peer, EPOCH)
    for seeded in (a, b):
        exported = next(c for c in cards if c["card_data"].get("did") == seeded.did)
        assert org_mark.extension_from_card(exported["card_data"]) is None
        assert await _mirror_mark(peer, seeded.did) is None


async def test_the_mark_predicate_and_an_agents_level_on_postgres(home):
    from agentvault_registry.services import org_actor, org_authz, org_mark
    from agentvault_registry.models import Organization
    seeded = await _seed(home)
    async with home() as s:
        assert list(await org_mark.card_states(s, [seeded.did])) == [seeded.did]
        await s.execute(text("UPDATE organizations SET is_active = FALSE WHERE id = :o"), {"o": seeded.org})
        await s.commit()
        assert await org_mark.card_states(s, [seeded.did]) == {}
        await s.execute(text("UPDATE organizations SET is_active = TRUE WHERE id = :o"), {"o": seeded.org})
        await org_authz.grant_org_slice(s, org_slug=seeded.slug, agent_dids=[seeded.did], role="admin",
                                        granted_by=seeded.dev)
        await s.commit()
        org = await s.get(Organization, seeded.org)
        assert await org_actor.agent_org_level(s, seeded.did, org) == "admin"
        await s.execute(text("UPDATE agent_delegation_grants SET revoked_at = now() WHERE delegate_agent_did = :d"),
                        {"d": seeded.did})
        await s.commit()
        assert await org_actor.agent_org_level(s, seeded.did, org) is None


async def test_one_open_join_request_per_agent_and_organization(home):
    seeded = await _seed(home)
    ins = ("INSERT INTO organization_agent_requests (id, organization_id, agent_did, requested_by_kind, "
           "requested_by_ref, status) VALUES (:id, :o, :d, 'agent', :d, :st)")
    async with home() as s:
        await s.execute(text(ins), {"id": "oar_1", "o": seeded.org, "d": seeded.did, "st": "declined"})
        await s.execute(text(ins), {"id": "oar_2", "o": seeded.org, "d": seeded.did, "st": "pending"})
        await s.commit()
        with pytest.raises(IntegrityError):
            await s.execute(text(ins), {"id": "oar_3", "o": seeded.org, "d": seeded.did, "st": "pending"})
            await s.commit()
