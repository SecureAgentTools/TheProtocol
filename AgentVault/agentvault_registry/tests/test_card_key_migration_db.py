"""§MEMBERSHIP (V0560): an operator's card key MIGRATES to the card's name, against a REAL Postgres.

The keystore is keyed by the card spiffe, so the first signature after the change mints a new key under the new kid. The
old key has no expiry and /.well-known/registry-jwks.json publishes every unexpired key, so what it signed still
verifies: proven here with a ballot signed under each. The stock-card cache (source_spiffe_id is unique) re-keys the
same peer's row instead of listing its catalog twice.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database it may WIPE.
"""
from __future__ import annotations

import json
import os

import pytest

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TD = "sandbox-b.theprotocol.cloud"
OLD = f"spiffe://{TD}/registry/cloud-op-sbxbetaop"
NEW = f"spiffe://{TD}/registry/sbxbetaop"


@pytest.fixture
async def session():
    from agentvault_registry.models import Base
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _ballot(fb):
    return fb.build_ballot(proposal_id="5f1c0b9e-0000-4000-8000-0000000000d2",
                           host={"trust_domain": TD, "name": "Sandbox Beta"},
                           voter={"trust_domain": TD, "name": "sbxbetaop"}, choice="abstain", basis={"mode": "operator"})


async def test_the_old_key_stays_published_and_both_signatures_verify(session, monkeypatch):
    from agentvault_registry.config import settings
    from agentvault_registry.routers.registry_card import get_well_known_registry_jwks
    from agentvault_registry.services import federation_ballot as fb
    from agentvault_registry.services.registry_card_keystore import get_or_mint_signing_key
    from agentvault_registry.services.registry_card_signer_impl import sign_with_keypair
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", TD)
    monkeypatch.setenv("REGISTRY_SIGNING_KEY_PASSPHRASE", "throwaway-test-passphrase")   # the encrypted path, as in prod
    monkeypatch.setattr(settings, "REGISTRY_NAME", "cloud-op-sbxbetaop")
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbxbetaop")

    old_key = await get_or_mint_signing_key(session, OLD)          # what the operator signed with before V0560
    await session.commit()
    old_jwk = dict(old_key.public_jwk)
    new_env = await fb.sign_ballot(session, _ballot(fb))              # the first signature after: the new key
    await session.commit()
    assert new_env["kid"] == f"{NEW}#1", new_env["kid"]

    jwks = json.loads((await get_well_known_registry_jwks(db=session)).body)
    kids = {k["kid"]: k for k in jwks["keys"]}
    assert {f"{OLD}#1", f"{NEW}#1"} <= set(kids), sorted(kids)
    assert kids[f"{OLD}#1"]["x"] == old_jwk["x"] and kids[f"{NEW}#1"]["x"] != old_jwk["x"]

    b = _ballot(fb)
    old_env = {"ballot": b, "alg": "EdDSA", "kid": f"{OLD}#1", "signature": sign_with_keypair(b, old_key)}
    for env in (new_env, old_env):
        ok, why = fb.verify_envelope(env, jwks, caller_td=TD)
        assert ok, (env["kid"], why)


async def test_a_peers_catalog_row_is_rekeyed_never_duplicated(session):
    from agentvault_registry.background_tasks.federation_sync import _stock_card_row
    from agentvault_registry.models import FederatedStockCard
    session.add_all([
        FederatedStockCard(source_spiffe_id=OLD, source_registry_name="sbxbetaop", listings_json=[], digest="d1"),
        FederatedStockCard(source_spiffe_id="spiffe://sandbox-a.theprotocol.cloud/registry/sbxbetaop",
                           source_registry_name="sbxbetaop", listings_json=[], digest="d2"),   # a namesake elsewhere
    ])
    await session.commit()
    row = await _stock_card_row(session, NEW, "sbxbetaop")
    assert row is not None and row.digest == "d1" and row.source_spiffe_id == NEW, "the same peer's row, re-keyed"
    await session.commit()
    assert (await session.execute(select(func.count()).select_from(FederatedStockCard))).scalar() == 2
    again = await _stock_card_row(session, NEW, "sbxbetaop")
    assert again is not None and again.id == row.id, "found by its new spiffe from now on"

    assert await _stock_card_row(session, f"spiffe://{TD}/registry/nobody", "nobody") is None, "unknown peer: create"
    session.add(FederatedStockCard(source_spiffe_id=f"spiffe://{TD}/registry/twin-a", source_registry_name="twin",
                                   listings_json=[], digest="t1"))
    session.add(FederatedStockCard(source_spiffe_id=f"spiffe://{TD}/registry/twin-b", source_registry_name="twin",
                                   listings_json=[], digest="t2"))
    await session.commit()
    assert await _stock_card_row(session, f"spiffe://{TD}/registry/twin", "twin") is None, \
        "two candidates: no guess, the caller creates its own row"
