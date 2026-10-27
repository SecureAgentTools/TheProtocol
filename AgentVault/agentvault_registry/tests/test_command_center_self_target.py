"""§MCPTEST30 (V0562, agentvault2-09): the Command Center measures the registry it runs on, on every frame.

Measured 2026-10-03: EU, ASIA and Sandbox Beta listed no target at all (no Docker socket since F6, or fleet scope off),
so the page had nothing to diagnose on the frames that matter most. Every frame now lists ITSELF (role "frame"), and
its checks read only what the registry reaches on its own: its event store's supply audit (read twice before a breach
is called, the HTTP audit's two sums being two queries), its Redis leader keys, its own SVID file, its own trust bundle
against the federation's frames, and its TEG's health through the mTLS sidecar. Operators stay behind the fleet scope.
"""
from datetime import datetime, timedelta, timezone

import pytest

from agentvault_registry.routers import admin_diagnostics as ad
from agentvault_registry.services.diagnostics import targets as T
from agentvault_registry.services.diagnostics.checks import (
    applies_to, frame_teg_health, frame_trust_bundle, identity_network, leader_election, supply_audit, svid_expiry,
)

SELF = {"operator_id": "sandbox-alpha", "display_name": "Sandbox Alpha", "frame": "sandbox alpha", "role": "frame",
        "cloud_url": None, "containers": {}, "self": True}


@pytest.fixture
def as_sandbox_alpha(monkeypatch):
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "Sandbox Alpha")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.example")
    monkeypatch.delenv("MINTING_AUTHORITY", raising=False)


# ── the target ───────────────────────────────────────────────────────────────

def test_the_self_target_is_this_registry(as_sandbox_alpha):
    t = T.self_target()
    assert (t["operator_id"], t["display_name"], t["role"], t["containers"], t["self"]) == \
        ("sandbox-alpha", "Sandbox Alpha", "frame", {}, True)


@pytest.mark.asyncio
async def test_every_frame_lists_itself_even_with_fleet_scope_off(monkeypatch, as_sandbox_alpha):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "local")
    out = await T.list_targets(db=None)
    assert [x["operator_id"] for x in out] == ["sandbox-alpha"] and out[0]["role"] == "frame"


@pytest.mark.asyncio
async def test_the_route_explains_a_list_that_holds_no_operator(monkeypatch, as_sandbox_alpha):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "local")

    async def _no_cache(check_id, target):
        return None
    monkeypatch.setattr(ad.cache, "get_cached", _no_cache)
    out = await ad.get_targets(db=None)
    assert [x["role"] for x in out["targets"]] == ["frame"]
    assert out["reason_code"] == "no_operators", "this registry alone is no operator: the note still says why none is listed"
    assert out["containers_reason_code"] == "scope_off"

    async def _with_op(_db):
        return [T.self_target(), {"operator_id": "op-x", "display_name": "x", "frame": "sandbox alpha",
                                  "role": "operator", "containers": {"registry": "cloud-op-x-registry"}}]
    monkeypatch.setattr(ad, "list_targets", _with_op)
    out = await ad.get_targets(db=None)
    assert out["reason_code"] is None and out["reason"] is None


def test_an_operator_registry_lists_itself_as_an_operator(monkeypatch):
    # an operator has no store of its own (it writes to its parent frame's): its own Command Center must not show the
    # parent's supply audit as its own, nor call the operator "this frame"
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbxalphaop")
    monkeypatch.setenv("MINTING_AUTHORITY", "disabled")
    t = T.self_target()
    assert (t["operator_id"], t["role"], t["self"]) == ("sbxalphaop", "operator", True)
    assert T.empty_summary(t).is_self is True and T.empty_summary(SELF).is_self is True
    assert T.empty_summary({**SELF, "self": False, "role": "operator"}).is_self is False
    applied = {c for c in ("supply-audit", "leader-election", "svid-expiry", "frame-trust-bundle", "frame-teg-health",
                           "operator-card", "operator-federation-reach", "identity-network-aliases") if applies_to(c, t)}
    assert applied == {"leader-election", "svid-expiry", "frame-trust-bundle", "frame-teg-health"}


@pytest.mark.asyncio
async def test_no_action_reaches_this_registry_itself(monkeypatch):
    # an operator registry's own target carries role "operator": the actions still refuse it, by the self flag
    from agentvault_registry.services.diagnostics import actions
    me = {**SELF, "operator_id": "sbxalphaop", "role": "operator",
          "containers": {"teg": "cloud-op-sbxalphaop-teg", "nginx_federation": "cloud-op-sbxalphaop-nginx-federation"}}
    for fn in (actions.teg_restart, actions.nginx_reload):
        r = await fn(me, probe=None, dry_run=True, actor="test")
        assert r.status == "skipped", (fn.__name__, r.summary)


def test_which_checks_apply_to_this_registry():
    applied = {c for c in ("supply-audit", "leader-election", "svid-expiry", "frame-trust-bundle", "frame-teg-health",
                           "identity-network-aliases", "nginx-config-valid", "pgbouncer-reachable", "operator-dns-errors",
                           "spire-cert-rotation", "kafka-consumer-lag", "eventstore-batch-failures", "spire-federation",
                           "teg-cross-frame-reach") if applies_to(c, SELF)}
    assert applied == {"supply-audit", "leader-election", "svid-expiry", "frame-trust-bundle", "frame-teg-health"}


# ── leader keys: measured for this registry, still "not measured" for an operator ──

class _Redis:
    def __init__(self, keys):
        self._k = keys

    async def keys(self, _p):
        return list(self._k)

    async def get(self, k):
        return "worker-1"

    async def ttl(self, k):
        return self._k[k]


@pytest.mark.asyncio
async def test_this_registrys_leader_keys_are_measured(monkeypatch):
    async def _r():
        return _Redis({"leader:supply_auditor": 22, "leader:compliance_poller": 17})
    monkeypatch.setattr(leader_election, "get_redis", _r)
    r = await leader_election.run(SELF, probe=None)
    assert r.status == "ok" and r.summary == "2 leader key(s) held"

    async def _leaked():
        return _Redis({"leader:supply_auditor": -1})
    monkeypatch.setattr(leader_election, "get_redis", _leaked)
    assert (await leader_election.run(SELF, probe=None)).status == "warn"


# ── identity network: not this registry's, and a probe that could not ask is not a finding ──

@pytest.mark.asyncio
async def test_identity_network_says_unknown_when_docker_cannot_be_asked():
    assert identity_network.applies(SELF) is False

    class _P:
        def __init__(self, err):
            self.err = err

        async def network_inspect(self, _n):
            return {"error": self.err}
    op = {"operator_id": "op-x", "role": "operator", "containers": {"teg": "cloud-op-x-teg"}}
    r = await identity_network.run(op, _P("Error while fetching server API version: ('Connection aborted.', FileNotFoundError(2))"))
    assert r.status == "unknown" and r.summary.startswith("not measured")
    r = await identity_network.run(op, _P("404 Client Error: Not Found (\"network agentvault_identity_network not found\")"))
    assert r.status == "fail" and "does not exist" in r.summary


# ── supply audit: this registry's own store, read twice before a breach ─────

class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, str(body)
        self.request = type("Q", (), {"url": "https://es.example/api/v1/projections/supply-audit"})()

    def json(self):
        return self._b


def _client(answers, seen):
    class _C:
        def __init__(self, *a, **kw):
            seen.append(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            seen.append(url)
            return answers.pop(0)
    return _C


@pytest.fixture
def own_store(monkeypatch):
    monkeypatch.setattr(supply_audit, "_own_store", lambda: ("https://es.example", {"X-Internal-Key": "k"}, "CTX"))

    async def _fast(_s):
        return None
    monkeypatch.setattr(supply_audit.asyncio, "sleep", _fast)


@pytest.mark.asyncio
async def test_the_supply_audit_reads_this_registrys_own_store(monkeypatch, own_store):
    seen = []
    monkeypatch.setattr(supply_audit.httpx, "AsyncClient", _client([_Resp(200, {"delta": 0.0, "status": "OK"})], seen))
    r = await supply_audit.run(SELF, probe=None)
    assert r.status == "ok" and r.summary == "delta=0.0"
    assert seen[0]["verify"] == "CTX" and seen[0]["headers"] == {"X-Internal-Key": "k"}
    assert seen[1] == "https://es.example/api/v1/projections/supply-audit"


@pytest.mark.asyncio
async def test_a_delta_that_does_not_survive_a_second_read_is_read_skew(monkeypatch, own_store):
    seen = []
    monkeypatch.setattr(supply_audit.httpx, "AsyncClient", _client(
        [_Resp(200, {"delta": 2.0, "status": "BREACH"}), _Resp(200, {"delta": 0.0, "status": "OK"})], seen))
    r = await supply_audit.run(SELF, probe=None)
    assert r.status == "ok" and "read skew" in r.summary and r.details["first_delta"] == 2.0


@pytest.mark.asyncio
async def test_a_delta_that_persists_is_a_breach(monkeypatch, own_store):
    seen = []
    monkeypatch.setattr(supply_audit.httpx, "AsyncClient", _client(
        [_Resp(200, {"delta": 2.0, "status": "BREACH"}), _Resp(200, {"delta": 2.0, "status": "BREACH"})], seen))
    r = await supply_audit.run(SELF, probe=None)
    assert r.status == "fail" and r.summary == "BREACH delta=2.0"


# ── certificates written for the test ──────────────────────────────────────

def _cert_pem(td, hours_left, ca=True):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SPIFFE")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(hours=2))
            .not_valid_after(now + timedelta(hours=hours_left))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(f"spiffe://{td}")]), critical=False)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.mark.asyncio
async def test_this_registrys_svid_is_read_from_its_own_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    (tmp_path / "svid.0.pem").write_text(_cert_pem("sandbox-a.example/service/registry", 2, ca=False))
    r = await svid_expiry.run(SELF, probe=None)
    assert r.status == "ok" and r.details["path"].endswith("svid.0.pem") and 110 <= r.details["minutes_remaining"] <= 120
    (tmp_path / "svid.0.pem").write_text(_cert_pem("sandbox-a.example/service/registry", -0.5, ca=False))
    assert (await svid_expiry.run(SELF, probe=None)).status == "fail"
    (tmp_path / "svid.0.pem").unlink()
    assert (await svid_expiry.run(SELF, probe=None)).status == "unknown"


# ── the trust bundle against the federation's frames ────────────────────────

def _manifest(*frames):
    entries = [{"role": "frame", "trust_domain": td, "display_name": name} for td, name in frames]
    return {"self": entries[0], "peers": entries[1:] + [{"role": "operator", "trust_domain": "sandbox-a.example",
                                                           "display_name": "sbxalphaop"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("bundle_hours,status,words", [
    ({"sandbox-a.example": [42, 126], "sandbox-b.example": [43, 127]}, "ok", "2 frame(s) trusted"),
    ({"sandbox-a.example": [42, 126], "sandbox-b.example": [30, 50]}, "warn", "rotation is late for Sandbox Beta"),
    ({"sandbox-a.example": [42, 126], "sandbox-b.example": [5, 20]}, "fail", "its rotation has stopped"),
    ({"sandbox-a.example": [42, 126]}, "fail", "no CA of Sandbox Beta"),
])
async def test_the_trust_bundle_covers_every_frame_with_time_left(monkeypatch, tmp_path, bundle_hours, status, words):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    (tmp_path / "bundle.0.pem").write_text("".join(_cert_pem(td, h) for td, hs in bundle_hours.items() for h in hs))
    from agentvault_registry.core import federation_view as fv

    async def _m():
        return _manifest(("sandbox-a.example", "Sandbox Alpha"), ("sandbox-b.example", "Sandbox Beta"))
    monkeypatch.setattr(fv, "manifest_now", _m)
    r = await frame_trust_bundle.run(SELF, probe=None)
    assert r.status == status and words in r.summary, r.summary


@pytest.mark.asyncio
async def test_the_trust_bundle_check_says_when_it_could_not_measure(monkeypatch, tmp_path):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    assert (await frame_trust_bundle.run(SELF, probe=None)).summary.startswith("not measured")
    (tmp_path / "bundle.0.pem").write_text(_cert_pem("sandbox-a.example", 100))
    from agentvault_registry.core import federation_view as fv

    async def _none():
        return None
    monkeypatch.setattr(fv, "manifest_now", _none)
    r = await frame_trust_bundle.run(SELF, probe=None)
    assert r.status == "unknown" and "manifest" in r.summary


# ── the TEG, through the sidecar the registry pays through ───────────────────

class _TResp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, str(body)

    def json(self):
        if isinstance(self._b, Exception):
            raise self._b
        return self._b


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,status", [
    (_TResp(200, {"status": "healthy", "checks": {"database": {"status": "healthy"}}}), "ok"),
    (_TResp(200, {"status": "healthy", "checks": {"database": {"status": "unhealthy"}}}), "warn"),
    (_TResp(200, {"status": "degraded", "checks": {}}), "warn"),
    (_TResp(503, {"status": "unhealthy"}), "fail"),
    (RuntimeError("connection refused"), "fail"),
])
async def test_the_teg_health_check(monkeypatch, answer, status):
    monkeypatch.setenv("TEG_API_BASE_URL", "https://sbx-alpha-nginx-teg:8443")
    seen = []

    class _C:
        def __init__(self, *a, **kw):
            seen.append(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            seen.append(url)
            if isinstance(answer, Exception):
                raise answer
            return answer
    monkeypatch.setattr(frame_teg_health.httpx, "AsyncClient", _C)
    r = await frame_teg_health.run(SELF, probe=None)
    assert r.status == status, r.summary
    assert seen[1] == "https://sbx-alpha-nginx-teg:8443/health"


@pytest.mark.asyncio
async def test_the_teg_health_check_says_when_no_teg_is_configured(monkeypatch):
    monkeypatch.delenv("TEG_API_BASE_URL", raising=False)
    r = await frame_teg_health.run(SELF, probe=None)
    assert r.status == "unknown" and "TEG_API_BASE_URL" in r.summary


# ── this frame's operators, from its own peer rows ──────────────────────────

from agentvault_registry import models  # noqa: E402
from agentvault_registry.services.diagnostics.checks import operator_card, operator_federation_reach  # noqa: E402


def _op_row(i, name, *, synced_minutes_ago=5, failures=0, verified=True, version="TheProtocolReleaseV0562", card=True):
    p = models.PeerRegistry(name=name, base_url=f"https://{name}.op.example:8443", status="ACTIVE", peer_type="cloud_operator")
    p.id = i
    now = datetime.now(timezone.utc)
    p.last_synced_at = None if synced_minutes_ago is None else now - timedelta(minutes=synced_minutes_ago)
    p.last_sync_attempt_at = now - timedelta(minutes=1)
    p.registered_at = now - timedelta(days=20)
    p.consecutive_sync_failures = failures
    p.last_sync_error = None
    p.cached_registry_card = ({"identity": {"display_name": name, "public_url": f"https://{name}.op.example",
                                            "software_version": version}} if card else None)
    p.card_signature_verified = verified
    p.card_signature_kid = f"spiffe://x/registry/{name}#1"
    p.card_last_pulled_at = now
    return p


class _RowsDB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        class _R:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return list(self._rows)
        return _R(self.rows)


@pytest.mark.asyncio
async def test_with_fleet_scope_off_a_frame_lists_itself_and_its_operator_rows(monkeypatch, as_sandbox_alpha):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "local")
    out = await T.list_targets(db=_RowsDB([_op_row(7, "sbxalphaop")]))
    assert [(x["operator_id"], x["role"], x.get("peer_registry_id"), x["containers"]) for x in out] == [
        ("sandbox-alpha", "frame", None, {}), ("op-sbxalphaop", "operator", 7, {})]
    assert applies_to("operator-card", out[1]) and applies_to("operator-federation-reach", out[1])
    assert not applies_to("leader-election", out[1]) and not applies_to("svid-expiry", out[1]), \
        "an operator known from its row alone names no container to read a key or an SVID in"


@pytest.mark.asyncio
async def test_under_fleet_scope_a_docker_operator_gains_its_rows_id_and_no_twin(monkeypatch, as_sandbox_alpha):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "fleet")

    async def _slugs():
        return ["sbxalphaop"]

    async def _enrich(_db):
        return {}

    async def _own(_db):
        return {"sbxalphaop"}
    monkeypatch.setattr(T, "_discover_operator_slugs", _slugs)
    monkeypatch.setattr(T, "_enrichment_map", _enrich)
    monkeypatch.setattr(T, "_own_operator_names", _own)
    out = await T.list_targets(db=_RowsDB([_op_row(7, "sbxalphaop"), _op_row(9, "farop")]))
    ids = [x["operator_id"] for x in out]
    assert ids == ["sandbox-alpha", "op-sbxalphaop", "op-farop"], "one target per operator"
    docker = out[1]
    assert docker["peer_registry_id"] == 7 and docker["containers"]["registry"] == "cloud-op-sbxalphaop-registry"
    assert out[2]["containers"] == {} and out[2]["peer_registry_id"] == 9


def _load(monkeypatch, row):
    async def _peer(_id):
        return row
    monkeypatch.setattr(operator_federation_reach, "load_peer", _peer)


OP = {"operator_id": "op-sbxalphaop", "role": "operator", "containers": {}, "peer_registry_id": 7}


@pytest.mark.asyncio
@pytest.mark.parametrize("row,status,words", [
    (dict(synced_minutes_ago=5), "ok", "OK: last answered 5 min ago"),
    (dict(synced_minutes_ago=60 * 9), "warn", "STALE"),
    (dict(synced_minutes_ago=None), "fail", "NEVER_SYNCED"),
])
async def test_the_operator_reach_check_reads_the_rows_own_record(monkeypatch, row, status, words):
    _load(monkeypatch, _op_row(7, "sbxalphaop", **row))
    r = await operator_federation_reach.run(OP, probe=None)
    assert r.status == status and r.summary.startswith(words), r.summary


@pytest.mark.asyncio
async def test_the_operator_checks_say_when_the_row_is_gone(monkeypatch):
    _load(monkeypatch, None)
    assert (await operator_federation_reach.run(OP, probe=None)).status == "unknown"
    assert (await operator_card.run(OP, probe=None)).status == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("row,status,words", [
    (dict(version="TheProtocolReleaseV0562"), "ok", "card verified, runs V0562"),
    (dict(version="TheProtocolReleaseV0520"), "warn", "runs V0520, this registry V0562"),
    (dict(verified=False), "fail", "does not verify"),
    (dict(card=False), "unknown", "not measured: no card"),
])
async def test_the_operator_card_check(monkeypatch, row, status, words):
    _load(monkeypatch, _op_row(7, "sbxalphaop", **row))
    from agentvault_registry.core import registry_identity
    monkeypatch.setattr(registry_identity, "BUNDLED_IMAGE_TAG", "TheProtocolReleaseV0562")
    r = await operator_card.run(OP, probe=None)
    assert r.status == status and words in r.summary, r.summary
