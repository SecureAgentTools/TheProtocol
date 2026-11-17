"""V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511), TWO registries in one test on REAL Postgres via asyncpg:
a home ("ASIA") and the governing registry ("EU"), each on its own database, both naming EU in CODE_CHANGES_GOVERNING_REGISTRY. The real
route functions run on both sides; only the wire between them is replaced, by a call into the other registry's own route function:
  - home -> EU: services/code_passport.send_to_governing (federation mTLS in production) calls EU's /api/v1/federation/code-passport/{act}
    with the home's peer identity
  - EU -> home: services/exchange_passport.fetch_home_jwks calls the home's /.well-known/registry-jwks.json, so EU verifies the card
    with the key the home really signed it with (minted in the home's database)

Pinned:
  - a developer who has not pressed "Take part on EU" relays nothing, and nothing is disclosed
  - with the consent, the home relays its agent's propose and review; EU records them under one contributor row per (home registry,
    home developer id), no account, the agent's DID on the change; the home writes its disclosure row (purpose code_governance)
  - a forged card (a field changed after signing) and an expired card are refused; a card relayed by a peer that is not its home is
    refused
  - a suspended home developer is refused and EU pauses the contributor; reinstatement at home restores it
  - a vote from a foreign contributor is refused with a sentence; a contributor does not review their own change
  - the contributor track records a contributor's unlocks on EU in its own table (the developer table's key cannot hold them)
  - phase 4 (session-lead seq 5367): the press links a repository account on the code host through the same relay, the account naming
    the home registry and the developer; with the code host open a contributor proposes only with it linked; its standing follows home
    on the governing registry's own pull (pause, restore, close; a closed account never restores), and a home answers that pull only to
    the governing registry
Skipped unless CODE_PASSPORT_TEST_DB (EU) and CODE_PASSPORT_HOME_TEST_DB (the home) name throwaway databases it may WIPE. Skipped, never
silently passed. RED: there is no services/code_passport, no routers/code_passport and no migration 0235.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import uuid

import pytest

EU_DB = os.environ.get("CODE_PASSPORT_TEST_DB")
HOME_DB = os.environ.get("CODE_PASSPORT_HOME_TEST_DB")
if not (EU_DB and HOME_DB):
    pytest.skip("needs two REAL Postgres databases it may wipe: set CODE_PASSPORT_TEST_DB and CODE_PASSPORT_HOME_TEST_DB. Skipped, "
                "never silently passed.", allow_module_level=True)

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

HOME_TD, OTHER_TD, EU_TD = "asia.passport.test", "elsewhere.passport.test", "eu.passport.test"
HOME_PEER, EU_PEER = f"spiffe://{HOME_TD}/service/registry", f"spiffe://{EU_TD}/service/registry"


class FakeHost:
    """The code host's admin API as the registry calls it (services/repo_accounts.ForgejoClient's four calls)."""

    def __init__(self):
        self.users, self.next_id = {}, 100

    async def create_user(self, username, email, password, full_name=None):
        if username in self.users:
            from agentvault_registry.services.repo_accounts import HostError
            raise HostError("taken", status=422)
        self.next_id += 1
        self.users[username] = {"id": self.next_id, "email": email, "full_name": full_name, "prohibit_login": False}
        return self.next_id

    async def get_user(self, username):
        return dict(self.users[username])

    async def edit_user(self, username, fields):
        self.users[username].update(fields)
        return dict(self.users[username])

    async def delete_user(self, username):
        self.users.pop(username, None)
DOC = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/oracle/38_release_notes.md"
PROPOSAL = {"repository": "theprotocol/AgentVault", "paths": [DOC], "title": "Fix a typo", "problem": "A typo in the release notes.",
            "branch": "fix/typo", "commit": "0123456789abcdef0123456789abcdef01234567"}


async def _fresh(url):
    from agentvault_registry.models import Base
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.fixture
async def world(monkeypatch):
    """Two registries. `on(name)` opens a session on that registry with its own name in force (nested calls stack and restore)."""
    from agentvault_registry.models import Agent, Developer, PeerRegistry
    from agentvault_registry.routers import code_passport as R
    from agentvault_registry.routers import registry_card as RC
    from agentvault_registry.services import code_passport as cp
    from agentvault_registry.services import exchange_passport as xp

    monkeypatch.setenv("CODE_CHANGES_GOVERNING_REGISTRY", "EU")
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "enforce")
    monkeypatch.delenv("CODE_CHANGE_OPEN_PATHS", raising=False)
    engines = {"EU": await _fresh(EU_DB), "ASIA": await _fresh(HOME_DB)}
    makers = {k: async_sessionmaker(e, expire_on_commit=False) for k, e in engines.items()}
    names = []

    @contextlib.asynccontextmanager
    async def on(name):
        names.append(os.environ.get("REGISTRY_FEDERATION_NAME"))
        os.environ["REGISTRY_FEDERATION_NAME"] = name
        try:
            async with makers[name]() as s:
                yield s
        finally:
            prev = names.pop()
            if prev is None:
                os.environ.pop("REGISTRY_FEDERATION_NAME", None)
            else:
                os.environ["REGISTRY_FEDERATION_NAME"] = prev

    peer = {"spiffe": HOME_PEER}

    async def send_to_governing(db, path, body):                     # home -> EU, as the federation lane carries it
        act = path.rstrip("/").rsplit("/", 1)[-1]
        async with on("EU") as eu:
            return _read(await R.federation_act(act, json.loads(json.dumps(body)), peer["spiffe"], eu))

    async def fetch_home_jwks(db, home, *, force=False):                # EU -> home: the home's own public keys
        assert home == "ASIA", home
        async with on("ASIA") as h:
            return json.loads((await RC.get_well_known_registry_jwks(db=h)).body)["keys"]

    async def ask_home(db, home, agent_did):                          # EU -> home: the standing pull, as the federation lane carries it
        assert home == "ASIA", home
        async with on("ASIA") as h:
            return _read(await R.federation_standing({"agent_did": agent_did}, EU_PEER, h))

    from agentvault_registry.services import repo_accounts as ra
    host = FakeHost()
    monkeypatch.setattr(ra, "ForgejoClient", lambda *a, **k: host)
    monkeypatch.setattr(cp, "ask_home", ask_home)
    monkeypatch.setattr(cp, "send_to_governing", send_to_governing)
    monkeypatch.setattr(xp, "fetch_home_jwks", fetch_home_jwks)
    monkeypatch.setattr(xp, "_JWKS_CACHE", {})

    async with on("EU") as eu:
        owner = Developer(name="eu-admin", email="admin@eu.test", hashed_password="x", is_verified=True)
        eu.add(owner)
        await eu.flush()
        eu.add(PeerRegistry(name="ASIA", base_url="https://asia.passport.test", admin_contact_email="ops@asia.test", status="ACTIVE",
                            discovery_auth_info={}, peer_type="frame", trust_domain=HOME_TD, licence_state="licensed",
                            owner_developer_id=owner.id))
        await eu.commit()
    async with on("ASIA") as h:
        dev = Developer(name="ada-account", display_name="Ada", email=f"ada-{uuid.uuid4().hex[:6]}@asia.test", hashed_password="x",
                        is_verified=True)
        h.add(dev)
        await h.flush()
        agent = Agent(did=f"did:theprotocol:asia:{uuid.uuid4().hex}", client_id=f"c-{uuid.uuid4().hex[:12]}", hashed_client_secret="x",
                      creator_developer_id=dev.id, status="active")
        h.add(agent)
        h.add(PeerRegistry(name="EU", base_url="https://eu.passport.test", admin_contact_email="ops@eu.test", status="ACTIVE",
                           discovery_auth_info={}, peer_type="frame", trust_domain=EU_TD, licence_state="licensed",
                           owner_developer_id=dev.id))
        await h.commit()
    yield {"on": on, "R": R, "cp": cp, "dev_id": dev.id, "agent_did": agent.did, "peer": peer, "host": host, "ra": ra}
    for e in engines.values():
        await e.dispose()


def _read(resp):
    if isinstance(resp, dict):
        return 200, resp
    return resp.status_code, json.loads(resp.body or b"{}")


async def _agent(world, s):
    from agentvault_registry.models import Agent
    return (await s.execute(select(Agent).where(Agent.did == world["agent_did"]))).scalar_one()


async def _developer(world, s):
    from agentvault_registry.models import Developer
    return (await s.execute(select(Developer).where(Developer.id == world["dev_id"]))).scalar_one()


async def _consent(world):
    async with world["on"]("ASIA") as h:
        return _read(await world["R"].set_my_passport(world["R"].ConsentIn(consent=True), await _developer(world, h), h))


async def _propose(world, body=PROPOSAL):
    async with world["on"]("ASIA") as h:
        return _read(await world["R"].relay_propose(dict(body), await _agent(world, h), h))


async def test_without_the_press_nothing_is_relayed_or_disclosed(world):
    status, out = await _propose(world)
    assert status == 403 and out["code"] == "no_consent", out
    async with world["on"]("ASIA") as h:
        assert (await h.execute(text("SELECT count(*) FROM dev_card_disclosures"))).scalar() == 0
    async with world["on"]("EU") as eu:
        assert (await eu.execute(text("SELECT count(*) FROM code_changes"))).scalar() == 0


async def test_a_relayed_proposal_is_recorded_under_the_contributor_and_disclosed_at_home(world):
    assert (await _consent(world))[0] == 200
    status, out = await _propose(world)
    assert status == 201, out
    assert out["state"] == "proposed" and out["proposer_did"] == world["agent_did"]
    async with world["on"]("EU") as eu:
        c = (await eu.execute(text("SELECT id, home_registry, home_developer_id, display_name, standing FROM code_contributors"))).one()
        assert (c.home_registry, c.home_developer_id, c.display_name, c.standing) == ("ASIA", str(world["dev_id"]), "Ada", "active")
        row = (await eu.execute(text("SELECT proposer_developer_id, proposer_did FROM code_changes"))).one()
        assert row.proposer_developer_id == world["cp"].contributor_key(c.id) and row.proposer_did == world["agent_did"]
        assert (await eu.execute(text("SELECT count(*) FROM developers"))).scalar() == 1          # no account on EU
    async with world["on"]("ASIA") as h:
        d = (await h.execute(text("SELECT developer_id, agent_did, requested_by, purpose FROM dev_card_disclosures"))).one()
        assert (d.developer_id, d.agent_did, d.requested_by, d.purpose) == (world["dev_id"], world["agent_did"], "EU", "code_governance")


async def test_a_bounty_from_another_registry_is_refused_with_a_sentence(world):
    await _consent(world)
    body = {k: v for k, v in PROPOSAL.items() if k not in ("branch", "commit")}
    status, out = await _propose(world, {**body, "bounty": 5})
    assert status == 422 and out["code"] == "contributor_branch_only", out


async def _accepted_eu_change(world, proposer_key=None):
    """A change on EU in state accepted (its check is the governing registry's own step; seeded here, the review is what is relayed)."""
    from agentvault_registry.services import code_changes as cc
    async with world["on"]("EU") as eu:
        owner = (await eu.execute(text("SELECT id FROM developers LIMIT 1"))).scalar()
        cid = "cc_" + uuid.uuid4().hex[:24]
        now = dt.datetime.now(dt.timezone.utc)
        await cc.DbStore(eu).insert({"id": cid, "repository": "theprotocol/AgentVault", "paths": [DOC], "title": "t", "problem": "p",
                                     "mode": "branch", "branch": "b", "commit": PROPOSAL["commit"], "order_id": None,
                                     "proposer_did": "did:theprotocol:eu:native", "proposer_developer_id": proposer_key or owner,
                                     "sensitive": False, "state": "proposed", "acceptance": None, "proposal_id": None,
                                     "passed_at": None, "veto": None, "go": None, "merged": None, "created_at": now, "updated_at": now})
        await eu.execute(text("UPDATE code_changes SET state = 'accepted' WHERE id = :c"), {"c": cid})
        await eu.commit()
    return cid


async def _review(world, cid):
    async with world["on"]("ASIA") as h:
        return _read(await world["R"].relay_review(cid, {"verdict": "approve", "commit": PROPOSAL["commit"], "findings": "reads well"},
                                                   await _agent(world, h), h))


async def test_a_relayed_review_is_recorded_under_the_contributor_and_never_on_their_own_change(world):
    await _consent(world)
    cid = await _accepted_eu_change(world)
    status, out = await _review(world, cid)
    assert status == 200 and out["review_verdict"]["approvals"] == 1, out
    async with world["on"]("EU") as eu:
        cid_row = (await eu.execute(text("SELECT id FROM code_contributors"))).scalar()
        assert (await eu.execute(text("SELECT reviewer_developer_id FROM code_change_reviews"))).scalar() == -cid_row
    own = await _accepted_eu_change(world, proposer_key=-cid_row)
    status, out = await _review(world, own)
    assert status == 403 and out["code"] == "not_independent", out


async def _signed(world, **over):
    async with world["on"]("ASIA") as h:
        return await world["cp"].signed_card(h, await _developer(world, h), await _agent(world, h), requested_by="EU", **over)


async def _at_eu(world, act, env, args=None, peer=HOME_PEER):
    async with world["on"]("EU") as eu:
        return _read(await world["R"].federation_act(act, {"dev_card": env, "args": args or dict(PROPOSAL)}, peer, eu))


async def test_a_forged_an_expired_and_a_borrowed_card_are_refused(world):
    await _consent(world)
    forged = await _signed(world)
    forged["payload"]["display_name"] = "Someone else"
    status, out = await _at_eu(world, "propose", forged)
    assert status == 403 and out["code"] == "card_signature", out
    old = await _signed(world, issued_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=world["cp"].CARD_MAX_AGE_SECONDS + 5))
    status, out = await _at_eu(world, "propose", old)
    assert status == 403 and out["code"] == "card_expired", out
    status, out = await _at_eu(world, "propose", await _signed(world), peer=f"spiffe://{OTHER_TD}/service/registry")
    assert status == 403 and out["code"] == "unknown_peer", out
    async with world["on"]("EU") as eu:
        assert (await eu.execute(text("SELECT count(*) FROM code_changes"))).scalar() == 0


async def test_a_suspended_home_developer_is_refused_and_paused_and_reinstatement_restores(world):
    await _consent(world)
    assert (await _propose(world))[0] == 201
    async with world["on"]("ASIA") as h:
        await h.execute(text("UPDATE developers SET is_suspended = true WHERE id = :d"), {"d": world["dev_id"]})
        await h.commit()
    status, out = await _propose(world)
    assert status == 403 and out["code"] == "home_suspended", out
    async with world["on"]("EU") as eu:
        assert (await eu.execute(text("SELECT standing FROM code_contributors"))).scalar() == "paused"
    async with world["on"]("ASIA") as h:
        await h.execute(text("UPDATE developers SET is_suspended = false WHERE id = :d"), {"d": world["dev_id"]})
        await h.commit()
    assert (await _propose(world))[0] == 201
    async with world["on"]("EU") as eu:
        assert (await eu.execute(text("SELECT standing FROM code_contributors"))).scalar() == "active"
        assert (await eu.execute(text("SELECT count(*) FROM code_changes"))).scalar() == 2


async def test_a_vote_from_a_foreign_contributor_is_refused_with_a_sentence(world):
    await _consent(world)
    status, out = await _at_eu(world, "vote", await _signed(world), {"code_change_id": "cc_x", "vote": True})
    assert status == 403 and out["code"] == "votes_members_only" and "members" in out["detail"], out


async def test_the_track_records_a_contributors_unlocks_on_eu_in_its_own_table(world):
    from agentvault_registry.services import contributor_track as ct
    await _consent(world)
    assert (await _propose(world))[0] == 201
    async with world["on"]("EU") as eu:
        cid = (await eu.execute(text("SELECT id FROM code_contributors"))).scalar()
        store = ct.DbTrackStore(eu)
        row = {"developer_id": -cid, "kind": "title", "item_key": "passport-probe", "tier": None,
               "unlocked_at": dt.datetime.now(dt.timezone.utc), "source": "test"}
        await store.insert([row])
        await store.insert([row])                                                       # a row exists once
        await eu.commit()
        assert (-cid, "title", "passport-probe") in await store.existing([-cid])
        assert (await eu.execute(text("SELECT count(*) FROM code_contributor_unlocks WHERE contributor_id = :c AND item_key = 'passport-probe'"),
                                 {"c": cid})).scalar() == 1
        # and the relayed proposal itself unlocked the track's first item for them, through the rail's own step
        assert (await eu.execute(text("SELECT kind, item_key FROM code_contributor_unlocks WHERE contributor_id = :c AND source LIKE 'code_change:%'"),
                                 {"c": cid})).all() == [("corner", "initiate")]
        assert (await eu.execute(text("SELECT count(*) FROM cosmetic_unlocks"))).scalar() == 0


async def test_the_migration_creates_exactly_what_the_models_declare_and_its_downgrade_removes_it():
    import importlib.util
    import pathlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0235_code_passport.py"
    spec = importlib.util.spec_from_file_location("m0235", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "0234_repo_accounts" and len(mod.revision) <= 32
    engine = await _fresh(EU_DB)
    tables = ("code_contributors", "code_contributor_unlocks", "contributor_repo_accounts", "contributor_repo_account_ops")
    listed = ", ".join(f"'{x}'::regclass" for x in tables)
    named = ", ".join(f"'{x}'" for x in tables)

    async def shape(conn):
        cons = (await conn.execute(text(
            "SELECT conrelid::regclass::text || '.' || conname, pg_get_constraintdef(oid) FROM pg_constraint "
            f"WHERE conrelid IN ({listed}) ORDER BY 1"))).all()
        idx = (await conn.execute(text(f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ({named}) ORDER BY 1"))).all()
        col = (await conn.execute(text("SELECT data_type, is_nullable FROM information_schema.columns WHERE table_name = 'developers' "
                                       "AND column_name = 'code_passport_consent_at'"))).all()
        return dict(cons), dict(idx), col

    def run(sync_conn, fn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            fn()

    async with engine.begin() as conn:
        from_models = await shape(conn)
        await conn.run_sync(run, mod.downgrade)
        for t in tables:
            assert (await conn.execute(text(f"SELECT to_regclass('{t}')"))).scalar() is None, t
        assert (await conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'developers' "
                                        "AND column_name = 'code_passport_consent_at'"))).scalar() == 0
        await conn.run_sync(run, mod.upgrade)
        from_migration = await shape(conn)
    await engine.dispose()
    assert from_migration == from_models, (from_migration, from_models)
    assert from_models[2] == [("timestamp with time zone", "YES")]


async def _link(world, username="ada-asia"):
    async with world["on"]("ASIA") as h:
        return _read(await world["R"].relay_repo_link({"username": username, "confirm": True, "accept_terms": world["ra"].terms_version()},
                                                      await _developer(world, h), h))


async def test_the_press_links_a_repository_account_that_names_the_home_and_the_developer(world, monkeypatch):
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    status, out = await _link(world)
    assert status == 403 and out["code"] == "no_consent", out                      # the press first, then the account
    await _consent(world)
    status, out = await _link(world)
    assert status == 201 and out["username"] == "ada-asia" and out["password"], out
    assert out["git_config"] == "git config user.email ada-asia@users.code.theprotocol.cloud"
    user = world["host"].users["ada-asia"]
    assert user["full_name"] == f"Ada (ASIA, developer {world['dev_id']})" and user["email"] == "ada-asia@users.code.theprotocol.cloud"
    async with world["on"]("EU") as eu:
        a = (await eu.execute(text("SELECT a.username, a.host_user_id, a.state, a.terms_version, c.home_registry FROM "
                                   "contributor_repo_accounts a JOIN code_contributors c ON c.id = a.contributor_id"))).one()
        assert (a.username, a.host_user_id, a.state, a.terms_version, a.home_registry) == (
            "ada-asia", user["id"], "active", world["ra"].terms_version(), "ASIA")
        assert (await eu.execute(text("SELECT count(*) FROM repo_accounts"))).scalar() == 0         # never a member's account
    async with world["on"]("ASIA") as h:
        status, st = _read(await world["R"].relay_repo_status(None, await _developer(world, h), h))
    assert status == 200 and st["linked"] is True and st["username"] == "ada-asia" and st["state"] == "active", st
    assert "password" not in st                                                                    # answered once, at the link


async def test_with_the_code_host_open_a_contributor_proposes_only_with_a_linked_account(world, monkeypatch):
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    await _consent(world)
    status, out = await _propose(world)
    assert status == 409 and out["code"] == "repo_account_required", out
    assert (await _link(world))[0] == 201
    assert (await _propose(world))[0] == 201


async def _set_home(world, **cols):
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    async with world["on"]("ASIA") as h:
        await h.execute(text(f"UPDATE developers SET {sets} WHERE id = :d"), {**cols, "d": world["dev_id"]})
        await h.commit()


async def _pull_and_drain(world):
    async with world["on"]("EU") as eu:
        pulled = await world["cp"].pull_standing_once(eu)
        await world["ra"].RepoAccounts(world["ra"].DbStore(eu), world["host"]).drain_once()
        row = (await eu.execute(text("SELECT c.standing, a.state FROM code_contributors c JOIN contributor_repo_accounts a "
                                     "ON a.contributor_id = c.id"))).one()
    return pulled, (row.standing, row.state, world["host"].users["ada-asia"]["prohibit_login"])


async def test_standing_pulled_from_home_pauses_restores_and_closes_the_account(world, monkeypatch):
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    await _consent(world)
    assert (await _link(world))[0] == 201
    pulled, now = await _pull_and_drain(world)
    assert pulled == 1 and now == ("active", "active", False)
    await _set_home(world, is_suspended=True)
    assert (await _pull_and_drain(world))[1] == ("paused", "paused", True)        # a git push needs no act: the pull pauses it
    await _set_home(world, is_suspended=False)
    assert (await _pull_and_drain(world))[1] == ("active", "active", False)
    await _set_home(world, deleted_at=dt.datetime.now(dt.timezone.utc))
    assert (await _pull_and_drain(world))[1] == ("closed", "closed", True)
    await _set_home(world, deleted_at=None)
    assert (await _pull_and_drain(world))[1] == ("closed", "closed", True)        # closed never restores
    status, out = await _propose(world)
    assert status == 403 and out["code"] == "contributor_closed", out


async def test_a_home_answers_the_standing_pull_only_to_the_governing_registry_and_only_with_consent(world):
    async with world["on"]("ASIA") as h:
        status, out = _read(await world["R"].federation_standing({"agent_did": world["agent_did"]}, EU_PEER, h))
    assert status == 403 and out["code"] == "no_consent", out
    await _consent(world)
    async with world["on"]("ASIA") as h:
        status, out = _read(await world["R"].federation_standing({"agent_did": world["agent_did"]}, f"spiffe://{OTHER_TD}/service/registry", h))
        assert status == 403 and out["code"] == "not_the_governing_registry", out
        status, env = _read(await world["R"].federation_standing({"agent_did": world["agent_did"]}, EU_PEER, h))
        assert status == 200 and env["payload"]["purpose"] == "code_governance" and env["payload"]["standing"] == "active", env
        assert (await h.execute(text("SELECT count(*) FROM dev_card_disclosures WHERE requested_by = 'EU'"))).scalar() == 1
