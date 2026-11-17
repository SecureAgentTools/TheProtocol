"""V0667 D6 part 3 (order gwo_fa3b8d7611f2573a2e63ac1c): the scoped release channel of a distribution through its REAL routes on a REAL
Postgres via asyncpg. The governing registry ("EU") records the builds session-release's pipeline reports, publishes one with the release
key's signed index and serves that index, and a pull grant for its images, ONLY to a caller whose mTLS trust domain AND presented frame
licence name a registry the index lists, read live from the database at every call. Everyone else gets 404: the line's existence is not
disclosed.

Pinned (the order's negative tests first):
  - a listed registry whose licence is revoked gets 404 at once, and its earlier pull grant stops working (the live verdict, never a
    cached one); restored, it reads again. A peer row whose licence verdict is refused gets 404 the same way
  - a valid licence presented over another frame's trust domain gets 404 (both ways round)
  - an unlisted registry gets 404; no certificate or no licence gets 404
  - a grant for line A cannot pull line B, never pushes, and holds nothing outside distributions/<tag>/
  - a refused build is never published; a bad signature or another schema is refused at publish; one published row per name
  - a withdrawn line answers no one, and its row (and index) stays for the record
  - a registry that does not govern code serves no line and records no build
Skipped unless DISTRIBUTION_RELEASES_TEST_DB names a throwaway database it may WIPE. Skipped, never silently passed.
RED: there is no services/distribution_releases, no routers/distribution_releases and no migration 0238.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid

import pytest

DB = os.environ.get("DISTRIBUTION_RELEASES_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres database it may wipe: set DISTRIBUTION_RELEASES_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

ASIA_TD, OTHER_TD = "asia.dist.test", "other.dist.test"
ASIA, OTHER = f"spiffe://{ASIA_TD}/service/registry", f"spiffe://{OTHER_TD}/service/registry"
ASIA_KEY, OTHER_KEY = "tp_fed_" + "a" * 64, "tp_fed_" + "b" * 64


def _ed25519():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return pem, base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def _record(name, state="built"):
    return {"name": name, "release": name.split("_")[0], "tag": "dist-" + name.lower(), "base_commit": "a" * 40, "base_tree": "f" * 40,
            "head": "b" * 40, "head_tree": "c" * 40, "changes": [{"id": "cc-1", "commit": "d" * 40}],
            "carry": {"cc-1": {"outcome": "applied", "words": "applied cleanly"}},
            "protected": {"verdict": "intact" if state == "built" else "touched", "removed": []},
            "image_id": "sha256:" + "e" * 64, "build_rc": 0 if state == "built" else 1, "built_at": "2026-11-16T19:00:00Z",
            "state": state}


def _index(pem, name, registries):
    from agentvault_registry.core import release_channel as rc
    doc = {"schema": "theprotocol-distribution/1", "name": name, "release": name.split("_")[0], "generated_at": "2026-11-16T19:05:00Z",
           "base_commit": "a" * 40, "head": "b" * 40, "head_tree": "c" * 40,
           "images": {"prefix": f"images.theprotocol.cloud/distributions/dist-{name.lower()}", "tag": name,
                      "digests": {"registry": "sha256:" + "9" * 64}},
           "registries": registries, "protected": {"verdict": "intact", "removed": []}, "carry": {"applied": 1}}
    return rc.sign(doc, pem)


def _read(resp):
    if isinstance(resp, dict):
        return 200, resp
    return resp.status_code, json.loads(resp.body or b"{}")


@pytest.fixture
async def world(monkeypatch):
    from agentvault_registry.models import Base, CodeDistribution, Developer, FederationLicense, Organization, PeerRegistry
    from agentvault_registry.routers import distribution_releases as R
    from agentvault_registry.routers import docker_token_auth as T
    pem, pub = _ed25519()
    monkeypatch.setenv("RELEASE_CHANNEL_PUBKEY_B64", pub)
    monkeypatch.setenv("CODE_CHANGES_GOVERNING_REGISTRY", "EU")
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "EU")
    monkeypatch.setenv("CODE_DISTRIBUTIONS_ENABLED", "true")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(T, "_signing_key_pem", rsa_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                      serialization.NoEncryption()))
    monkeypatch.setattr(T, "_signing_key_id", "TEST:KID")
    engine = create_async_engine(DB)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        admin = Developer(name="eu-admin", email="admin@eu.dist.test", hashed_password="x", is_verified=True, is_admin=True)
        s.add(admin)
        await s.flush()
        org = Organization(id=f"org-{uuid.uuid4().hex[:8]}", name="Lyceum", slug=f"lyceum-{uuid.uuid4().hex[:6]}", owner_id=admin.id)
        s.add(org)
        await s.flush()
        for slug in ("lyceum", "other", "broken"):
            s.add(CodeDistribution(id=uuid.uuid4().hex, organization_id=org.id, slug=slug, title=slug.title(), base_release="V0666",
                                   open_paths=["agentvault_registry/src/agentvault_registry/static/"], created_by_developer_id=admin.id))
        for name, td, key in (("ASIA", ASIA_TD, ASIA_KEY), ("OTHER", OTHER_TD, OTHER_KEY)):
            s.add(PeerRegistry(name=name, base_url=f"https://{td}", admin_contact_email=f"ops@{td}", status="ACTIVE", discovery_auth_info={},
                               peer_type="frame", trust_domain=td, licence_state="licensed", owner_developer_id=admin.id))
            s.add(FederationLicense(operator_name=name, operator_did=f"spiffe://{td}", licensee_type="frame", status="active",
                                    license_key_hash=hashlib.sha256(key.encode()).hexdigest(), license_key_prefix=key[:12]))
        await s.commit()
    yield {"maker": maker, "R": R, "T": T, "pem": pem, "admin": admin}
    await engine.dispose()


async def _call(world, fn, *args, **kw):
    async with world["maker"]() as s:
        return _read(await fn(*args, db=s, **kw))


async def _token(world, username, password, scope):
    from starlette.requests import Request
    raw = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = Request({"type": "http", "method": "GET", "path": "/api/v1/docker-registry/token", "query_string": b"",
                   "headers": [(b"authorization", f"Basic {raw}".encode())], "client": ("127.0.0.1", 40000)})
    from fastapi import HTTPException
    try:
        async with world["maker"]() as s:
            body = await world["T"].docker_registry_token(req, service="images.theprotocol.cloud", scope=scope, account=None, db=s)
    except HTTPException as e:
        return e.status_code, None
    import jwt
    return 200, jwt.decode(body["token"], options={"verify_signature": False})["access"]


async def _publish_lyceum(world, R, registries=None):
    st, _ = await _call(world, R.record_build, "V0667_lyceum", _record("V0667_lyceum"), admin=world["admin"])
    assert st == 200
    idx = _index(world["pem"], "V0667_lyceum", registries or [{"name": "ASIA", "trust_domain": ASIA_TD}])
    st, body = await _call(world, R.publish, "V0667_lyceum", {"index": idx, "card_word": "approved. go (his card)"}, admin=world["admin"])
    assert st == 200 and body["state"] == "published", body
    return idx


async def test_a_listed_registry_reads_its_line_and_everyone_else_gets_404(world):
    R = world["R"]
    idx = await _publish_lyceum(world, R)
    st, body = await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY)
    assert st == 200 and body == idx                                              # the signed document itself, verifiable as served
    from agentvault_registry.services import distribution_releases as dr
    assert dr.verify_index(body) == (True, "ok")
    for spiffe, licence in ((OTHER, OTHER_KEY),                                   # an unlisted registry
                            (OTHER, ASIA_KEY), (ASIA, OTHER_KEY),                 # a valid licence over another frame's trust domain
                            (ASIA, None), (None, ASIA_KEY), (ASIA, "tp_fed_" + "0" * 64)):
        st, body = await _call(world, R.distribution_index, "V0667_lyceum", spiffe=spiffe, licence=licence)
        assert st == 404 and body == {"detail": "Not Found"}, (spiffe, licence, st, body)
    st, body = await _call(world, R.distribution_index, "V0667_nosuch", spiffe=ASIA, licence=ASIA_KEY)
    assert (st, body) == (404, {"detail": "Not Found"})                          # the same answer as a line that exists


async def test_a_revoked_licence_is_404_at_once_and_its_grant_stops(world):
    from agentvault_registry.models import FederationLicense, PeerRegistry
    R = world["R"]
    await _publish_lyceum(world, R)
    st, grant = await _call(world, R.pull_grant, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY)
    assert st == 200 and grant["username"] == "dist.ASIA" and grant["scope"] == "distributions/dist-v0667_lyceum/*", grant
    assert await _token(world, grant["username"], grant["password"], "repository:distributions/dist-v0667_lyceum/registry:pull") == (
        200, [{"type": "repository", "name": "distributions/dist-v0667_lyceum/registry", "actions": ["pull"]}])
    async with world["maker"]() as s:
        await s.execute(update(FederationLicense).where(FederationLicense.operator_name == "ASIA").values(status="revoked"))
        await s.commit()
    st, body = await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY)
    assert (st, body) == (404, {"detail": "Not Found"})                          # at once: no cache between the revocation and the read
    assert (await _token(world, grant["username"], grant["password"], "repository:distributions/dist-v0667_lyceum/registry:pull"))[0] == 401
    async with world["maker"]() as s:
        await s.execute(update(FederationLicense).where(FederationLicense.operator_name == "ASIA").values(status="active"))
        await s.commit()
    assert (await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY))[0] == 200
    async with world["maker"]() as s:                                             # the network licence's verdict on the peer row
        await s.execute(update(PeerRegistry).where(PeerRegistry.name == "ASIA").values(licence_state="revoked"))
        await s.commit()
    assert (await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY))[0] == 404
    assert (await _call(world, R.pull_grant, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY))[0] == 404


async def test_a_grant_for_line_a_cannot_pull_line_b(world):
    R = world["R"]
    both = [{"name": "ASIA", "trust_domain": ASIA_TD}]
    await _publish_lyceum(world, R, both)
    assert (await _call(world, R.record_build, "V0667_other", _record("V0667_other"), admin=world["admin"]))[0] == 200
    st, _ = await _call(world, R.publish, "V0667_other", {"index": _index(world["pem"], "V0667_other", both), "card_word": "approved. go"},
                        admin=world["admin"])
    assert st == 200
    _, grant = await _call(world, R.pull_grant, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY)
    st, access = await _token(world, grant["username"], grant["password"],
                              "repository:distributions/dist-v0667_other/registry:pull repository:distributions/dist-v0667_lyceum/registry:pull,push "
                              "repository:registry:pull")
    assert st == 200 and access == [{"type": "repository", "name": "distributions/dist-v0667_lyceum/registry", "actions": ["pull"]}]
    assert await _token(world, grant["username"], "dpg_" + "0" * 48, "repository:distributions/dist-v0667_lyceum/registry:pull") == (401, None)
    assert await _token(world, "dist.OTHER", grant["password"], "repository:distributions/dist-v0667_lyceum/registry:pull") == (401, None)
    st, lines = await _call(world, R.my_lines, spiffe=ASIA, licence=ASIA_KEY)
    assert st == 200 and sorted(x["name"] for x in lines["lines"]) == ["V0667_lyceum", "V0667_other"]
    st, lines = await _call(world, R.my_lines, spiffe=OTHER, licence=OTHER_KEY)
    assert st == 200 and lines["lines"] == []


async def test_publish_refuses_what_must_never_ship_and_withdraw_keeps_the_record(world):
    from agentvault_registry.core import release_channel as rc
    R = world["R"]
    reg = [{"name": "ASIA", "trust_domain": ASIA_TD}]
    assert (await _call(world, R.record_build, "V0667_broken", _record("V0667_broken", "refused"), admin=world["admin"]))[0] == 200
    st, body = await _call(world, R.publish, "V0667_broken", {"index": _index(world["pem"], "V0667_broken", reg), "card_word": "go"},
                           admin=world["admin"])
    assert st == 409 and body["code"] == "not_built", body
    st, body = await _call(world, R.record_build, "V0667_nosuch", _record("V0667_nosuch"), admin=world["admin"])
    assert st == 404 and body["code"] == "no_line", body                       # a build names a line that exists
    st, body = await _call(world, R.record_build, "V0667_lyceum", dict(_record("V0667_lyceum"), name="V0667_other"), admin=world["admin"])
    assert st == 422 and body["code"] == "name_mismatch", body
    assert (await _call(world, R.record_build, "V0667_lyceum", _record("V0667_lyceum"), admin=world["admin"]))[0] == 200
    other_pem, _ = _ed25519()
    for bad, code in ((_index(other_pem, "V0667_lyceum", reg), "index_unverified"),
                      (rc.sign(dict({k: v for k, v in _index(world["pem"], "V0667_lyceum", reg).items() if k != "signature"},
                                    schema="theprotocol-release/1"), world["pem"]), "index_unverified"),
                      (_index(world["pem"], "V0667_other", reg), "name_mismatch"),
                      (_index(world["pem"], "V0667_lyceum", []), "no_registries")):
        st, body = await _call(world, R.publish, "V0667_lyceum", {"index": bad, "card_word": "approved. go"}, admin=world["admin"])
        assert st in (409, 422) and body["code"] == code, (code, st, body)
    st, body = await _call(world, R.publish, "V0667_lyceum", {"index": _index(world["pem"], "V0667_lyceum", reg), "card_word": ""},
                           admin=world["admin"])
    assert st == 422 and body["code"] == "no_card_word"
    idx = _index(world["pem"], "V0667_lyceum", reg)
    assert (await _call(world, R.publish, "V0667_lyceum", {"index": idx, "card_word": "approved. go"}, admin=world["admin"]))[0] == 200
    assert (await _call(world, R.record_build, "V0667_lyceum", _record("V0667_lyceum"), admin=world["admin"]))[0] == 200
    st, body = await _call(world, R.publish, "V0667_lyceum", {"index": idx, "card_word": "approved. go"}, admin=world["admin"])
    assert st == 409 and body["code"] == "already_published", body
    st, body = await _call(world, R.withdraw, "V0667_lyceum", {"reason": "a defect"}, admin=world["admin"])
    assert st == 200 and body["state"] == "withdrawn"
    assert (await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY))[0] == 404
    assert (await _call(world, R.pull_grant, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY))[0] == 404
    st, rows = await _call(world, R.inbox, admin=world["admin"])
    states = sorted((r["name"], r["state"]) for r in rows["releases"])
    assert states == [("V0667_broken", "refused"), ("V0667_lyceum", "built"), ("V0667_lyceum", "withdrawn")], states
    st, row = await _call(world, R.read_release, "V0667_lyceum", admin=world["admin"])
    assert st == 200 and row["state"] in ("built", "withdrawn") and any(r["index"] == idx for r in row["builds"]) and row["published"] is None


async def test_a_registry_that_does_not_govern_code_serves_no_line(world, monkeypatch):
    R = world["R"]
    await _publish_lyceum(world, R)
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "ASIA")
    assert await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY) == (404, {"detail": "Not Found"})
    st, body = await _call(world, R.record_build, "V0667_x", _record("V0667_x"), admin=world["admin"])
    assert st == 403 and body["code"] == "code_change_not_governed_here", body


async def test_with_the_lines_switched_off_nothing_answers(world, monkeypatch):
    R = world["R"]
    await _publish_lyceum(world, R)
    _, grant = await _call(world, R.pull_grant, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY)
    monkeypatch.delenv("CODE_DISTRIBUTIONS_ENABLED")
    assert await _call(world, R.distribution_index, "V0667_lyceum", spiffe=ASIA, licence=ASIA_KEY) == (404, {"detail": "Not Found"})
    assert (await _token(world, grant["username"], grant["password"], "repository:distributions/dist-v0667_lyceum/registry:pull"))[0] == 401


async def test_migration_0238_down_then_up_builds_exactly_what_the_models_hold(world):
    """The models created the two tables; 0238's downgrade drops them and its upgrade builds them again, column for column, with the same
    checks, indexes (the partial unique one included), uniques and foreign keys."""
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0238_distribution_releases.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def schema(sync_conn):
        insp, out = inspect(sync_conn), {}
        for t in ("distribution_releases", "distribution_pull_grants"):
            if not insp.has_table(t):
                out[t] = None
                continue
            out[t] = {"columns": sorted((c["name"], str(c["type"]), c["nullable"]) for c in insp.get_columns(t)),
                      "checks": sorted((c["name"], c["sqltext"]) for c in insp.get_check_constraints(t)),
                      "indexes": sorted((i["name"], i["unique"], tuple(i["column_names"]),
                                         str((i.get("dialect_options") or {}).get("postgresql_where"))) for i in insp.get_indexes(t)),
                      "uniques": sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(t)),
                      "fks": sorted((tuple(f["constrained_columns"]), f["referred_table"], (f.get("options") or {}).get("ondelete"))
                                    for f in insp.get_foreign_keys(t))}
        return out

    async def run(fn):
        def go(sync_conn):
            with Operations.context(MigrationContext.configure(sync_conn)):
                getattr(mod, fn)()
        async with world["maker"]().bind.begin() as conn:
            await conn.run_sync(go)

    async with world["maker"]().bind.begin() as conn:
        before = await conn.run_sync(schema)
    assert before["distribution_releases"] and before["distribution_pull_grants"]
    assert ("uq_distribution_releases_published", True, ("name",), "((state)::text = 'published'::text)") in before["distribution_releases"]["indexes"]
    await run("downgrade")
    async with world["maker"]().bind.begin() as conn:
        assert await conn.run_sync(schema) == {"distribution_releases": None, "distribution_pull_grants": None}
    await run("upgrade")
    async with world["maker"]().bind.begin() as conn:
        assert await conn.run_sync(schema) == before
