"""V0667 D6 part 3 (order gwo_fa3b8d7611f2573a2e63ac1c): the scoped release channel of a distribution, its pure rules and its wiring.
session-release's contract (room seq 5534 and 5540): one migration-0238 row per distribution BUILD; the admin routes record a build,
publish it with the release key's signed index and withdraw it; the index (schema theprotocol-distribution/1) answers only the registries
it names; images live under distributions/<tag>/registry with tag 'dist-' + the lowercase name, and the token server's scope is
distributions/<tag>/*. The routes on a real Postgres: test_distribution_releases_v0667_db.py.
RED: there is no services/distribution_releases, no routers/distribution_releases and no migration 0238.
"""
from __future__ import annotations

import base64
import importlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "agentvault_registry"


def _key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pem, base64.b64encode(pub).decode()


def _index(name="V0667_lyceum", registries=None):
    return {"schema": "theprotocol-distribution/1", "name": name, "release": name.split("_")[0], "base_commit": "a" * 40,
            "head": "b" * 40, "head_tree": "c" * 40,
            "images": {"prefix": "images.theprotocol.cloud/distributions/dist-" + name.lower(), "tag": name,
                       "digests": {"registry": "sha256:" + "d" * 64}},
            "registries": registries if registries is not None else [{"name": "ASIA", "trust_domain": "asia.dist.test"}],
            "protected": {"verdict": "intact", "removed": []}, "carry": {"applied": 1}}


def test_the_tag_and_the_scope_follow_session_releases_contract():
    from agentvault_registry.services import distribution_releases as dr
    assert dr.SCHEMA == "theprotocol-distribution/1"
    assert dr.dist_tag("V0667_Lyceum") == "dist-v0667_lyceum"
    assert dr.repo_prefix("V0667_lyceum") == "distributions/dist-v0667_lyceum/"
    assert dr.NAME.match("V0667_lyceum") and not dr.NAME.match("lyceum") and not dr.NAME.match("V0667_Lyceum/../x")
    assert set(dr.STATES) == {"built", "refused", "failed", "published", "withdrawn"}


def test_an_index_verifies_by_the_release_keys_signature_then_its_schema(monkeypatch):
    from agentvault_registry.core import release_channel as rc
    from agentvault_registry.services import distribution_releases as dr
    pem, pub = _key()
    doc = rc.sign(_index(), pem)
    assert dr.verify_index(doc, pub) == (True, "ok")
    monkeypatch.setenv("RELEASE_CHANNEL_PUBKEY_B64", pub)
    assert dr.verify_index(doc) == (True, "ok")                              # the key the public channel's reader carries
    assert rc.verify(doc)[0] is False                                         # the public verifier does not accept this schema
    tampered = dict(doc, head="e" * 40)
    assert dr.verify_index(tampered, pub)[0] is False
    other_pem, other_pub = _key()
    assert dr.verify_index(rc.sign(_index(), other_pem), pub)[1].startswith("signed by a key")
    assert dr.verify_index(rc.sign(dict(_index(), schema="theprotocol-release/1"), pem), pub)[1].startswith("unknown schema")
    assert dr.verify_index({k: v for k, v in doc.items() if k != "signature"}, pub)[0] is False
    assert dr.verify_index("not a dict", pub)[0] is False


def test_a_registry_is_listed_only_by_its_own_trust_domain():
    from agentvault_registry.services import distribution_releases as dr
    idx = _index(registries=[{"name": "ASIA", "trust_domain": "spiffe://Asia.Dist.Test/"}, {"name": "OP", "trust_domain": "op.dist.test"}])
    assert dr.listed(idx, "asia.dist.test") == {"name": "ASIA", "trust_domain": "asia.dist.test"}
    assert dr.listed(idx, "op.dist.test")["name"] == "OP"
    assert dr.listed(idx, "eu.dist.test") is None
    assert dr.listed(idx, "") is None and dr.listed({"registries": "ASIA"}, "asia.dist.test") is None


def test_a_pull_grant_holds_its_own_lines_images_and_pull_only():
    from agentvault_registry.services import distribution_releases as dr
    want = [{"type": "repository", "name": "distributions/dist-v0667_lyceum/registry", "actions": ["pull", "push"]},
            {"type": "repository", "name": "distributions/dist-v0667_other/registry", "actions": ["pull"]},
            {"type": "repository", "name": "registry", "actions": ["pull"]},
            {"type": "repository", "name": "distributions/dist-v0667_lyceum", "actions": ["pull"]},
            {"type": "registry", "name": "catalog", "actions": ["*"]}]
    assert dr.grant_scopes("V0667_lyceum", want) == [
        {"type": "repository", "name": "distributions/dist-v0667_lyceum/registry", "actions": ["pull"]}]
    assert dr.grant_scopes("V0667_lyceum", []) == []                          # the client's /v2/ ping


def test_the_routes_and_their_gates():
    from agentvault_registry.routers import distribution_releases as R
    paths = {(r.path, tuple(sorted(r.methods))) for r in R.router.routes}
    for p in (("/api/v1/admin/distribution-releases/{name}/builds", ("POST",)),
              ("/api/v1/admin/distribution-releases/{name}/publish", ("POST",)),
              ("/api/v1/admin/distribution-releases/{name}/withdraw", ("POST",)),
              ("/api/v1/admin/distribution-releases/{name}", ("GET",)),
              ("/api/v1/admin/distribution-releases", ("GET",)),
              ("/api/v1/federation/release-channel/distributions/{name}/index", ("GET",)),
              ("/api/v1/federation/release-channel/distributions/{name}/pull-grant", ("POST",)),
              ("/api/v1/federation/release-channel/distributions", ("GET",)),
              ("/api/v1/admin/release-channel/distributions", ("GET",))):
        assert p in paths, p
    admin = [r for r in R.router.routes if r.path.startswith("/api/v1/admin/")]
    assert len(admin) == 6
    for r in admin:                                                           # each one behind admin_platform, by its own dependency
        assert any(d.call is R._ADMIN for d in r.dependant.dependencies), r.path
    public = [r for r in R.router.routes if r.path.startswith("/api/v1/federation/release-channel/")]
    for r in public:                                                          # the caller's certificate, never a 401 that says it exists
        assert any(d.call is R._caller_spiffe for d in r.dependant.dependencies), r.path


def test_the_router_is_mounted_and_the_token_server_knows_the_distribution_lane():
    main = (SRC / "main.py").read_text()
    assert "distribution_releases" in main
    tok = (SRC / "routers" / "docker_token_auth.py").read_text()
    assert "distribution_releases" in tok and "USER_PREFIX" in tok


def test_migration_0238_follows_0237_and_its_id_fits():
    mig = ROOT / "alembic" / "versions" / "0238_distribution_releases.py"
    text = mig.read_text()
    rev = re.search(r'^revision\s*=\s*"([^"]+)"', text, re.M).group(1)
    down = re.search(r'^down_revision\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert rev == "0238_distribution_releases" and len(rev) <= 32
    assert down == "0237_code_change_upstream"
    for word in ("distribution_releases", "distribution_pull_grants", "ck_distribution_releases_state", "uq_distribution_releases_published"):
        assert word in text, word
    importlib.import_module("agentvault_registry.models").DistributionRelease  # noqa: B018
    importlib.import_module("agentvault_registry.models").DistributionPullGrant  # noqa: B018
