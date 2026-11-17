"""V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane through the REAL routes on a REAL Postgres (asyncpg): an organization's own content changed after its line's
ballot and our check, applied to its own space, recorded, undone in one step.

  each kind   a kit and a proxy spec (a new unpublished version of the organization's own template), a policy value, a console text and a branding change: proposed,
              voted by the line's deciders, APPLIED on the pass, and UNDONE, the space back exactly as it was
  refused     a template of another organization, a settings key the catalog does not name (a global value), a secret in the text and a destination of the kit's own: 422 from our
              checker BEFORE anything is written and before any vote; a guest proposes nothing; a non-decider votes nothing
  the record  its fields are pinned: who proposed, the checker's verdict, the ballot's rule and result, the before and after, the time applied, who undid it
  the posture a registry that does not govern code writes nothing; reads stay open to the organization's members and platform admins, and to nobody else
  the undo    refused, with the content left as it is, when something else changed it since

Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE (postgresql+asyncpg://...). Skipped, never silently passed.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import types
import uuid

import httpx
import pytest

DB = os.environ.get("CODE_DISTRIBUTIONS_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from tests.test_code_distributions_v0666_db import _dist, _seed  # noqa: E402
from tests.test_workflow_templates_kit_v0664 import MANIFEST, PROXY, kit  # noqa: E402

from agentvault_registry.services import code_authority as ca  # noqa: E402

ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migration(name: str):
    spec = importlib.util.spec_from_file_location(name, ALEMBIC / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LIBRARY_DDL = (
    "CREATE TABLE workflow_templates (id VARCHAR(32) PRIMARY KEY, slug VARCHAR(120) NOT NULL, title VARCHAR(200) NOT NULL, summary VARCHAR(500), "
    "kind VARCHAR(20) NOT NULL DEFAULT 'migration', from_kind VARCHAR(20), to_kind VARCHAR(20), owner_agent_did VARCHAR(120) NOT NULL, source_org_id VARCHAR(64), "
    "visibility VARCHAR(12) NOT NULL DEFAULT 'private', pricing_model VARCHAR(12) NOT NULL DEFAULT 'free', price NUMERIC(38,10), price_currency VARCHAR(12), "
    "fork_share_bps INTEGER NOT NULL DEFAULT 2000, forked_from_template_id VARCHAR(32), forked_from_version INTEGER, current_version_id VARCHAR(32), "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), CONSTRAINT uq_wtpl_owner_slug UNIQUE (owner_agent_did, slug))",
    "CREATE TABLE workflow_template_versions (id VARCHAR(32) PRIMARY KEY, template_id VARCHAR(32) NOT NULL REFERENCES workflow_templates(id) ON DELETE CASCADE, "
    "version INTEGER NOT NULL, manifest JSONB NOT NULL, files JSONB NOT NULL, content_hash VARCHAR(64) NOT NULL, changelog VARCHAR(500), published_at TIMESTAMPTZ, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), CONSTRAINT uq_wtpv_template_version UNIQUE (template_id, version))",
)


@pytest.fixture
async def world(monkeypatch):
    from fastapi import FastAPI
    from agentvault_registry import database, security
    from agentvault_registry.models import Base, Developer, Organization, OrganizationMember
    from agentvault_registry.routers import content_changes as route
    from agentvault_registry.routers.utils import get_current_agent
    from agentvault_registry.services import workflow_templates as wt

    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    monkeypatch.setenv(ca.ENV, "eu")
    monkeypatch.setattr(ca, "own_name", lambda: "eu")
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

        for ddl in LIBRARY_DDL:                 # the library's tables are the migration's alone (no model): 0228's columns, the two this lane reads and writes
            await conn.execute(text(ddl))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    devs, org, team = await _seed(maker)
    async with maker() as s:
        other_owner = Developer(name=f"o2-{uuid.uuid4().hex[:6]}", email=f"o2{uuid.uuid4().hex[:6]}@test.local", hashed_password="x", is_verified=True)
        s.add(other_owner)
        await s.flush()
        org2 = Organization(id=f"org-{uuid.uuid4().hex[:8]}", name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", owner_id=other_owner.id)
        s.add(org2)
        await s.flush()
        s.add(OrganizationMember(id=uuid.uuid4().hex, organization_id=org2.id, developer_id=other_owner.id, role="owner", is_active=True))
        outsider = Developer(name=f"out-{uuid.uuid4().hex[:6]}", email=f"out{uuid.uuid4().hex[:6]}@test.local", hashed_password="x", is_verified=True)
        s.add(outsider)
        line = _dist(org, team, slug="lyceum", quorum_percent=50)
        s.add(line)
        await s.commit()
        devs["other_owner"], devs["outsider"], org2_id, line_id = other_owner.id, outsider.id, org2.id, line.id
        await s.refresh(line)
    store_wt = None
    async with maker() as s:
        store_wt = wt.DbStore(s)
        now = dt.datetime.now(dt.timezone.utc)
        for tid, owner_org, slug in (("wtpl_mine", org, "mine"), ("wtpl_theirs", org2_id, "theirs")):
            await store_wt.insert_template({
                "id": tid, "slug": slug, "title": slug, "summary": None, "kind": "migration", "from_kind": "sql", "to_kind": "sql", "owner_agent_did": f"did:owner:{slug}",
                "source_org_id": owner_org, "visibility": "org", "pricing_model": "free", "price": None, "price_currency": "ECU", "fork_share_bps": 2000,
                "forked_from_template_id": None, "forked_from_version": None, "current_version_id": None, "created_at": now, "updated_at": now})
            manifest = wt.check_kit(kit())
            await store_wt.insert_version({"id": f"wtpv_{slug}1", "template_id": tid, "version": 1, "manifest": manifest, "files": kit(),
                                           "content_hash": wt.content_hash(manifest, kit()), "changelog": "first", "published_at": None, "created_at": now})

    who = {"dev": devs["owner"], "admin": False}

    def agent():
        return types.SimpleNamespace(did=f"did:a:{who['dev']}", creator_developer_id=who["dev"])

    def developer():
        return types.SimpleNamespace(id=who["dev"], is_admin=who["admin"])

    async def get_db():
        async with maker() as s:
            yield s

    app = FastAPI()
    app.include_router(route.router)
    from agentvault_registry.routers import distribution_reports as reports_route        # V0667 D7: the signed report and records of a line
    app.include_router(reports_route.router)
    app.dependency_overrides[database.get_db] = get_db
    app.dependency_overrides[get_current_agent] = agent
    app.dependency_overrides[security.get_current_agent] = agent
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    app.dependency_overrides[security.get_current_developer] = developer
    app.dependency_overrides[route._ADMIN] = developer

    async def call(method, path, body=None, *, as_=None, admin=False):
        who["dev"], who["admin"] = (devs[as_] if as_ else devs["owner"]), admin
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.request(method, path, json=body)

    ns = types.SimpleNamespace(maker=maker, devs=devs, org=org, org2=org2_id, line_id=line_id, call=call, who=who)
    yield ns
    await engine.dispose()


PROP = {"code_distribution": "lyceum", "title": "A content change", "problem": "Because the organization wants it so."}


async def propose(w, kind, target, content, *, as_="member"):
    return await w.call("POST", "/api/v1/content-changes", {**PROP, "kind": kind, "target": target, "content": content}, as_=as_)


async def vote_all(w, cid, votes):
    """Each named decider votes (True/False) through an agent; the last vote may close the ballot."""
    out = None
    for who, v in votes:
        out = await w.call("POST", f"/api/v1/content-changes/{cid}/vote", {"vote": v}, as_=who)
        assert out.status_code == 200, (who, out.status_code, out.text)
    return out


async def one(w, sql, **p):
    async with w.maker() as s:
        return (await s.execute(text(sql), p)).mappings().all()


async def settings(w):
    from agentvault_registry.models import Organization
    async with w.maker() as s:
        o = await s.get(Organization, w.org)
        await s.refresh(o)
        return json.loads(json.dumps(o.settings or {}))


async def counts(w):
    return {t: (await one(w, f"SELECT count(*) AS n FROM {t}"))[0]["n"] for t in ("content_changes", "content_change_votes", "workflow_template_versions")}


async def deciders_vote_for(w):
    """The seeded line's deciders (owner, admin, the team's lead) all vote FOR: the ballot closes early and passes."""
    from agentvault_registry.services import code_distributions as cd
    from agentvault_registry.services import content_changes as cc
    async with w.maker() as s:
        who, _ = await cd.deciders(cc.DbStore(s), await cc.DbStore(s).distribution_by_slug("lyceum"))
    names = {v: k for k, v in w.devs.items()}
    return [(names[d], True) for d in sorted(who)]


# ── each kind: proposed, voted, applied, undone ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_policy_value_applied_then_undone(world):
    w = world
    before = await settings(w)
    r = await propose(w, "policy_value", "contract_offer_ttl_days", {"value": 14})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["state"] == "balloting" and r.json()["checker"]["ok"] is True
    assert (await settings(w)) == before, "nothing applies before the ballot"
    voters = await deciders_vote_for(w)
    assert len(voters) >= 2
    last = await vote_all(w, cid, voters)
    rec = last.json()
    assert rec["state"] == "applied" and rec["ballot"]["result"]["status"] == "PASSED"
    assert (await settings(w))["contract_offer_ttl_days"] == 14
    assert rec["before"] == {"value": before.get("contract_offer_ttl_days")} and rec["after"] == {"value": 14} and rec["applied_at"]
    u = await w.call("POST", f"/api/v1/content-changes/{cid}/undo", {"reason": "changed our mind"}, as_="owner")
    assert u.status_code == 200 and u.json()["state"] == "undone" and u.json()["undone"]["reason"] == "changed our mind"
    assert (await settings(w)) == before, "the space is back exactly as it was"


async def test_console_text_and_branding_applied_then_undone(world):
    w = world
    for kind, target, content, at in (("console_text", "landing.tagline", {"text": "Quiet releases."}, ["console_texts", "landing.tagline"]),
                                      ("branding", "branding", {"tagline": "Lyceum", "accent_color": "#12ab9f"}, ["branding"])):
        before = await settings(w)
        cid = (await propose(w, kind, target, content)).json()["id"]
        rec = (await vote_all(w, cid, await deciders_vote_for(w))).json()
        assert rec["state"] == "applied", rec
        cur = await settings(w)
        for k in at:
            cur = cur[k]
        assert cur == (content["text"] if kind == "console_text" else content)
        assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="admin")).json()["state"] == "undone"
        assert (await settings(w)) == before


async def test_a_compliance_pack_is_applied_under_its_name_and_undone_and_one_outside_the_allowed_set_is_refused_before_a_vote(world):
    """V0667 D7: a regulator's rules inside the allowed set, voted like any content change and applied to the organization's own space; outside it, refused with nothing written."""
    w = world
    before = await settings(w)
    rules = {"data_residency": {"regions": ["de"]}, "retention": {"audit_log_days": 2555}, "reporting": {"interval_days": 90, "label": "Quarterly"}}
    cid = (await propose(w, "compliance_pack", "eu-retention", {"rules": rules})).json()["id"]
    rec = (await vote_all(w, cid, await deciders_vote_for(w))).json()
    assert rec["state"] == "applied" and rec["after"] == {"value": rules} and rec["checker"]["rules"][0] == "allowed_set"
    assert (await settings(w))["compliance_packs"]["eu-retention"] == rules
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="owner")).json()["state"] == "undone"
    assert (await settings(w)) == before, "the pack is gone and the space is as it was"
    start = await counts(w)
    r = await propose(w, "compliance_pack", "eu-retention", {"rules": {"data_sharing": {"partners": ["x"]}}})
    assert r.status_code == 422 and r.json()["code"] == "checker_refused" and "data_sharing" in r.json()["detail"]
    assert await counts(w) == start


async def test_a_kit_and_a_proxy_spec_are_new_unpublished_versions_of_the_organizations_own_template_and_undo_removes_them(world):
    w = world
    new_kit = kit(**{"README.md": "# Customers, version two\n"})
    cid = (await propose(w, "kit", "wtpl_mine", {"files": new_kit})).json()["id"]
    rec = (await vote_all(w, cid, await deciders_vote_for(w))).json()
    assert rec["state"] == "applied" and rec["after"]["version"] == 2 and rec["before"] == {"latest_version": 1}
    v2 = (await one(w, "SELECT files, published_at FROM workflow_template_versions WHERE template_id='wtpl_mine' AND version=2"))[0]
    assert v2["files"]["README.md"] == "# Customers, version two\n" and v2["published_at"] is None, "a new version, never published by a content change"
    cid2 = (await propose(w, "proxy_spec", "wtpl_mine", {"proxy_yaml": PROXY.replace("table: customers", "table: customers_v2")})).json()["id"]
    rec2 = (await vote_all(w, cid2, await deciders_vote_for(w))).json()
    assert rec2["state"] == "applied" and rec2["after"]["version"] == 3
    v3 = (await one(w, "SELECT files FROM workflow_template_versions WHERE template_id='wtpl_mine' AND version=3"))[0]["files"]
    assert "customers_v2" in v3["proxy.yaml"] and v3["README.md"] == "# Customers, version two\n", "a proxy spec keeps the rest of the latest version"
    # the older change cannot be undone under a newer version; the newest can, then the older
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="owner")).status_code == 409
    assert (await w.call("POST", f"/api/v1/content-changes/{cid2}/undo", None, as_="owner")).json()["state"] == "undone"
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="owner")).json()["state"] == "undone"
    assert [r["version"] for r in await one(w, "SELECT version FROM workflow_template_versions WHERE template_id='wtpl_mine' ORDER BY version")] == [1]


# ── refused before anything is written or voted ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_checker_refuses_before_a_row_a_ballot_or_a_vote_exists(world):
    w = world
    start = await counts(w)
    cases = [
        ("kit", "wtpl_theirs", {"files": kit()}, "own"),                                                     # another organization's template
        ("proxy_spec", "wtpl_theirs", {"proxy_yaml": PROXY}, "own"),
        ("policy_value", "name", {"value": "Hijack"}, "not an organization setting"),                       # nothing global, no column
        ("policy_value", "frame.fee_bps", {"value": 5}, "not an organization setting"),
        ("console_text", "landing.tagline", {"text": "key " + "avreg" + "_abcdefghijklmnopqrstuvwxyz0123456789"}, "secret"),   # a secret in the text
        ("kit", "wtpl_mine", {"files": kit(**{"proxy.yaml": PROXY.replace('table: "${TARGET_TABLE}"', 'table: "${TARGET_TABLE}", host: "db.internal.example.org"')})}, "destination"),
        ("branding", "branding", {"accent_color": "red"}, "accent_color"),
    ]
    for kind, target, content, bit in cases:
        r = await propose(w, kind, target, content)
        assert r.status_code == 422 and r.json()["code"] == "checker_refused" and bit in r.json()["detail"], (kind, target, r.status_code, r.text)
        assert r.json()["reasons"]
    assert await counts(w) == start, "a refused change wrote nothing: no row, no vote, no version"


async def test_only_a_member_proposes_and_only_a_decider_votes(world):
    w = world
    body = ("console_text", "landing.tagline", {"text": "ok"})
    assert (await propose(w, *body, as_="guestlead")).status_code == 403             # a guest of the organization
    assert (await propose(w, *body, as_="outsider")).status_code == 403
    cid = (await propose(w, *body)).json()["id"]
    r = await w.call("POST", f"/api/v1/content-changes/{cid}/vote", {"vote": True}, as_="member")
    assert r.status_code == 403 and r.json()["code"] == "not_a_decider"
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/vote", {"vote": True}, as_="owner")).status_code == 200
    again = await w.call("POST", f"/api/v1/content-changes/{cid}/vote", {"vote": False}, as_="owner")
    assert again.status_code == 409 and again.json()["code"] == "already_voted"


async def test_a_ballot_that_fails_applies_nothing(world):
    w = world
    before = await settings(w)
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "No."})).json()["id"]
    rec = (await vote_all(w, cid, [(n, False) for n, _ in await deciders_vote_for(w)])).json()
    assert rec["state"] == "failed" and rec["ballot"]["result"]["status"] == "FAILED" and rec["applied_at"] is None
    assert (await settings(w)) == before


async def test_the_proposer_withdraws_while_it_balloting_and_nobody_else_does(world):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "ok"})).json()["id"]
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/withdraw", None, as_="owner")).status_code == 403
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/withdraw", None, as_="member")).json()["state"] == "withdrawn"


# ── the record, the reads, the posture ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_record_pins_its_fields(world):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "Quiet releases."})).json()["id"]
    rec = (await vote_all(w, cid, await deciders_vote_for(w))).json()
    for k in ("id", "kind", "target", "title", "problem", "content", "checker", "state", "proposer_did", "proposer_developer_id", "ballot", "before", "after", "applied_at",
              "undone", "code_distribution", "organization_id", "created_at"):
        assert k in rec, k
    assert rec["kind"] == "console_text" and rec["proposer_developer_id"] == w.devs["member"] and rec["code_distribution"]["slug"] == "lyceum"
    assert rec["checker"]["ok"] is True and "secrets" in rec["checker"]["rules"] and rec["checker"]["kind"] == "console_text"
    assert rec["ballot"]["rule"]["quorum_percent"] == 50 and rec["ballot"]["result"]["status"] == "PASSED"
    assert rec["before"] == {"value": None} and rec["after"] == {"value": "Quiet releases."}


async def test_reads_belong_to_the_organizations_members_and_platform_admins(world):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "ok"})).json()["id"]
    assert (await w.call("GET", f"/api/v1/content-changes/{cid}", as_="guestlead")).status_code == 200            # a guest member reads
    assert (await w.call("GET", f"/api/v1/content-changes/{cid}", as_="outsider")).status_code == 404
    assert (await w.call("GET", f"/api/v1/content-changes/{cid}", as_="other_owner")).status_code == 404
    assert (await w.call("GET", f"/api/v1/content-changes/{cid}", as_="outsider", admin=True)).status_code == 200
    assert [c["id"] for c in (await w.call("GET", "/api/v1/content-changes", as_="member")).json()["content_changes"]] == [cid]
    assert (await w.call("GET", "/api/v1/content-changes", as_="other_owner")).json()["content_changes"] == []
    inbox = (await w.call("GET", "/api/v1/admin/content-changes?kind=console_text", as_="outsider", admin=True)).json()["content_changes"]
    assert [c["id"] for c in inbox] == [cid]


async def test_a_registry_that_does_not_govern_writes_nothing_and_still_reads(world, monkeypatch):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "ok"})).json()["id"]
    start = await counts(w)
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    r = await propose(w, "console_text", "landing.tagline", {"text": "elsewhere"})
    assert r.status_code == 403 and r.json()["code"] == "code_change_not_governed_here"
    for path, body in ((f"/api/v1/content-changes/{cid}/vote", {"vote": True}), (f"/api/v1/content-changes/{cid}/undo", None), (f"/api/v1/content-changes/{cid}/withdraw", None)):
        r = await w.call("POST", path, body, as_="owner")
        assert r.status_code == 403 and r.json()["code"] == "code_change_not_governed_here", path
    assert await counts(w) == start
    assert (await w.call("GET", f"/api/v1/content-changes/{cid}", as_="member")).status_code == 200


async def test_the_switch_off_every_route_answers_not_found(world, monkeypatch):
    w = world
    monkeypatch.delenv("CODE_DISTRIBUTIONS_ENABLED", raising=False)
    assert (await w.call("GET", "/api/v1/content-changes", as_="member")).status_code == 404
    assert (await propose(w, "console_text", "landing.tagline", {"text": "ok"})).status_code == 404


async def test_a_paused_line_closes_nothing_and_applies_nothing(world):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "ok"})).json()["id"]
    async with w.maker() as s:
        await s.execute(text("UPDATE code_distributions SET state='paused', paused_reason='x', paused_by_developer_id=1, paused_at=now()"))
        await s.commit()
    r = await w.call("POST", f"/api/v1/content-changes/{cid}/vote", {"vote": True}, as_="owner")
    assert r.status_code == 409 and r.json()["code"] == "line_paused"
    assert (await propose(w, "console_text", "landing.tagline", {"text": "later"})).status_code == 409


async def test_the_undo_is_refused_and_the_content_left_when_something_else_changed_it_since(world):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "first"})).json()["id"]
    await vote_all(w, cid, await deciders_vote_for(w))
    from agentvault_registry.models import Organization
    async with w.maker() as s:
        o = await s.get(Organization, w.org)
        cur = json.loads(json.dumps(o.settings))
        cur["console_texts"]["landing.tagline"] = "edited by someone else"
        o.settings = cur
        await s.commit()
    r = await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="owner")
    assert r.status_code == 409 and r.json()["code"] == "changed_since"
    assert (await settings(w))["console_texts"]["landing.tagline"] == "edited by someone else"


async def test_only_a_decider_or_an_admin_undoes(world):
    w = world
    cid = (await propose(w, "console_text", "landing.tagline", {"text": "x"})).json()["id"]
    await vote_all(w, cid, await deciders_vote_for(w))
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="member")).status_code == 403
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="outsider")).status_code in (403, 404)
    assert (await w.call("POST", f"/api/v1/content-changes/{cid}/undo", None, as_="admin")).status_code == 200


# ── the migration ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_0236_down_then_up_restores_exactly_its_two_tables_and_touches_nothing_else(world):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect as sa_inspect
    mod = _migration("0236_content_changes")

    def schema(sync_conn):
        insp = sa_inspect(sync_conn)
        return {t: {"columns": sorted(c["name"] for c in insp.get_columns(t)), "indexes": sorted(i["name"] for i in insp.get_indexes(t) if i.get("name")),
                    "checks": sorted(c["name"] for c in insp.get_check_constraints(t) if c.get("name")), "fks": sorted(f["name"] for f in insp.get_foreign_keys(t) if f.get("name"))}
                for t in sorted(insp.get_table_names())}

    async def run(conn, fn):
        def go(sync_conn):
            with Operations.context(MigrationContext.configure(sync_conn)):
                getattr(mod, fn)()
        await conn.run_sync(go)
    engine = world.maker.kw["bind"]
    async with engine.begin() as conn:
        # the rows the fixture's tests would add are not here: a clean database from the models
        before = await conn.run_sync(schema)
        await run(conn, "downgrade")
        mid = await conn.run_sync(schema)
        assert "content_changes" not in mid and "content_change_votes" not in mid
        assert {t: v for t, v in mid.items()} == {t: v for t, v in before.items() if t not in ("content_changes", "content_change_votes")}, "the downgrade touched another table"
        await run(conn, "upgrade")
        after = await conn.run_sync(schema)
    assert after == before, f"the round trip left a different schema: {({t: (before.get(t), after.get(t)) for t in before if before.get(t) != after.get(t)})}"


def test_the_graph_has_one_head_and_0236_sits_directly_on_the_passports_0235():
    """The chain 0233 -> 0234_repo_accounts -> 0235_code_passport -> 0236_content_changes, one head, one file per number (D5 took 0236 on v0667/dev-passport: 0234 was taken twice)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC.parent))
    sd = ScriptDirectory.from_config(cfg)
    assert len(sd.get_heads()) == 1, sd.get_heads()
    rev, chain = sd.get_revision("0236_content_changes"), []
    while rev is not None and rev.revision != "0232_code_change_room":
        chain.append(rev.revision)
        rev = sd.get_revision(rev.down_revision) if rev.down_revision else None
    assert list(reversed(chain)) == ["0233_guild_orders_agent_org", "0234_repo_accounts", "0235_code_passport", "0236_content_changes"]
    for n in ("0234", "0235", "0236"):
        assert len(list(ALEMBIC.glob(f"{n}_*.py"))) == 1, f"two migrations share the number {n}"
