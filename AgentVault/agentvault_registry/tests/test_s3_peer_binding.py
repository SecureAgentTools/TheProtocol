"""§S3BIND (2026-09-24): the S3 peer-identity binding matched an incoming SVID against `peer_registries.spiffe_id` as an
exact string, and a frame stamps that column only on its OWN cloud operators' rows. Measured on the running cluster:
every call from the peer frame, from the peer frame's operators, from an operator's svid-writer and every licence-
authenticated call "matched no stamped peer row" and was allowed with a warning, about 4,200 an hour across EU, ASIA and
the sandbox pair, and strict mode would have refused all frame-to-frame traffic. These tests pin the canonical binding
(trust domain + peer type or name), the exact path left as it was, strict mode, the licence skip and the warning that
names an identity once an hour. The whole file fails on V0445 (the helpers do not exist there)."""
import logging
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry import database
from agentvault_registry.core import federation_auth as fa


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    fa._S3_CACHE.clear()
    fa._S3_WARNED.clear()
    monkeypatch.delenv("FEDERATION_REQUIRE_PEER_SPIFFE_BIND", raising=False)
    yield
    fa._S3_CACHE.clear()
    fa._S3_WARNED.clear()


# ── the canonical form ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("svid, want", [
    ("spiffe://asia.theprotocol.cloud/service/registry", ("asia.theprotocol.cloud", "frame", "")),
    ("spiffe://asia.theprotocol.cloud/service/asia-registry", ("asia.theprotocol.cloud", "frame", "")),
    ("spiffe://sandbox-b.theprotocol.cloud/service/sbx-beta-registry", ("sandbox-b.theprotocol.cloud", "frame", "")),
    ("spiffe://agentvault.com/ns/agentvault/sa/registry-frame-b", ("agentvault.com", "frame", "")),
    ("spiffe://eu.theprotocol.cloud/operator/amsterdam/registry", ("eu.theprotocol.cloud", "operator", "amsterdam")),
    ("spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/svid-writer",
     ("sandbox-a.theprotocol.cloud", "operator", "sbxalphaop")),
    ("spiffe://eu.theprotocol.cloud/registry/lisbon", ("eu.theprotocol.cloud", "named", "lisbon")),
    ("spiffe://eu.theprotocol.cloud/service/teg-layer", None),
    ("https://eu.theprotocol.cloud/service/registry", None),
])
def test_the_canonical_form_of_an_identity(svid, want):
    assert fa._s3_canonical(svid) == want


def test_the_frame_query_filters_on_the_authoritative_trust_domain_and_the_frame_type():
    sql = str(fa._s3_canonical_query(("asia.theprotocol.cloud", "frame", "")).compile(
        compile_kwargs={"literal_binds": True})).lower()
    assert "lower(peer_registries.trust_domain) = 'asia.theprotocol.cloud'" in sql
    assert "peer_registries.peer_type = 'frame'" in sql


def test_an_operator_query_does_not_restrict_the_peer_type():
    sql = str(fa._s3_canonical_query(("eu.theprotocol.cloud", "operator", "lisbon")).compile(
        compile_kwargs={"literal_binds": True})).lower()
    where = re.split(r"\swhere\s", sql, maxsplit=1)[1]  # the column list names peer_type too; only the filter matters
    assert "lower(peer_registries.trust_domain) = 'eu.theprotocol.cloud'" in where and "peer_type" not in where


def _row(name, status="ACTIVE", spiffe_id=None):
    return SimpleNamespace(name=name, status=status, spiffe_id=spiffe_id)


def test_the_verdict_prefers_the_active_row_over_a_deactivated_ghost():
    assert fa._s3_verdict([_row("ASIA", "INACTIVE"), _row("asia")], ("asia.theprotocol.cloud", "frame", "")) == "bound"


def test_the_verdict_is_inactive_when_only_deactivated_rows_are_this_peer():
    assert fa._s3_verdict([_row("ASIA", "INACTIVE")], ("asia.theprotocol.cloud", "frame", "")) == "inactive"


def test_an_operator_binds_by_its_name_and_nothing_else():
    rows = [_row("amsterdam"), _row("lisbon", "INACTIVE")]
    assert fa._s3_verdict(rows, ("eu.theprotocol.cloud", "operator", "amsterdam")) == "bound"
    assert fa._s3_verdict(rows, ("eu.theprotocol.cloud", "operator", "lisbon")) == "inactive"
    assert fa._s3_verdict(rows, ("eu.theprotocol.cloud", "operator", "porto")) == "unbound"


# ── the check itself, over a fake session ───────────────────────────────────────────────────────────────────────────

class _Session:
    """Answers the three statements the check issues: the exact spiffe_id lookup, the canonical rows, the stamped count."""

    def __init__(self, exact=None, canonical=(), stamped=2):
        self.exact, self.canonical, self.stamped = exact, list(canonical), stamped
        self.canonical_reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        sql = str(stmt).lower()
        if "count(" in sql:
            return SimpleNamespace(scalar=lambda: self.stamped)
        if "peer_registries.spiffe_id =" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.exact))
        self.canonical_reads += 1
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.canonical)))


def _using(monkeypatch, session):
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: session)
    return session


def _s3_warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "[S3]" in r.getMessage()]


@pytest.mark.asyncio
async def test_an_exact_match_to_an_active_row_passes(monkeypatch, caplog):
    _using(monkeypatch, _Session(exact=_row("amsterdam")))
    await fa._assert_peer_spiffe_binding("spiffe://eu.theprotocol.cloud/operator/amsterdam/registry")
    assert not _s3_warnings(caplog)


@pytest.mark.asyncio
async def test_an_exact_match_to_an_inactive_row_is_still_refused(monkeypatch):
    _using(monkeypatch, _Session(exact=_row("amsterdam", "INACTIVE")))
    with pytest.raises(HTTPException) as e:
        await fa._assert_peer_spiffe_binding("spiffe://eu.theprotocol.cloud/operator/amsterdam/registry")
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_the_peer_frame_binds_to_its_frame_row_without_a_warning(monkeypatch, caplog):
    _using(monkeypatch, _Session(canonical=[_row("ASIA", "INACTIVE"), _row("asia")]))
    with caplog.at_level(logging.DEBUG, logger=fa.logger.name):
        await fa._assert_peer_spiffe_binding("spiffe://asia.theprotocol.cloud/service/registry")
    assert not _s3_warnings(caplog)


@pytest.mark.asyncio
async def test_an_operators_svid_writer_binds_to_the_operator_row(monkeypatch, caplog):
    _using(monkeypatch, _Session(canonical=[_row("sbxalphaop", spiffe_id="spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/registry")]))
    await fa._assert_peer_spiffe_binding("spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/svid-writer")
    assert not _s3_warnings(caplog)


@pytest.mark.asyncio
async def test_a_peer_with_only_inactive_rows_warns_once_or_is_refused_in_strict_mode(monkeypatch, caplog):
    _using(monkeypatch, _Session(canonical=[_row("ASIA", "INACTIVE")]))
    await fa._assert_peer_spiffe_binding("spiffe://asia.theprotocol.cloud/service/registry")
    said = _s3_warnings(caplog)
    assert len(said) == 1 and "INACTIVE" in said[0]
    fa._S3_CACHE.clear()
    monkeypatch.setenv("FEDERATION_REQUIRE_PEER_SPIFFE_BIND", "true")
    with pytest.raises(HTTPException) as e:
        await fa._assert_peer_spiffe_binding("spiffe://asia.theprotocol.cloud/service/registry")
    assert e.value.status_code == 403 and e.value.detail == "Peer registry is not active"


@pytest.mark.asyncio
async def test_an_unknown_identity_warns_or_is_refused_in_strict_mode(monkeypatch, caplog):
    _using(monkeypatch, _Session(canonical=[], stamped=2))
    await fa._assert_peer_spiffe_binding("spiffe://stranger.example/service/registry")
    assert len(_s3_warnings(caplog)) == 1
    fa._S3_CACHE.clear()
    monkeypatch.setenv("FEDERATION_REQUIRE_PEER_SPIFFE_BIND", "true")
    with pytest.raises(HTTPException) as e:
        await fa._assert_peer_spiffe_binding("spiffe://stranger.example/service/registry")
    assert e.value.detail == "Peer identity is not bound to a known registry"


@pytest.mark.asyncio
async def test_an_unstamped_fleet_with_no_canonical_row_stays_quiet(monkeypatch, caplog):
    _using(monkeypatch, _Session(canonical=[], stamped=0))
    await fa._assert_peer_spiffe_binding("spiffe://stranger.example/service/registry")
    assert not _s3_warnings(caplog)


@pytest.mark.asyncio
async def test_an_unbound_identity_is_named_once_an_hour_with_a_count(monkeypatch, caplog):
    _using(monkeypatch, _Session(canonical=[], stamped=2))
    for _ in range(5):
        await fa._assert_peer_spiffe_binding("spiffe://stranger.example/service/registry")
    assert len(_s3_warnings(caplog)) == 1
    assert fa._S3_WARNED[("unbound", "spiffe://stranger.example/service/registry")][1] == 4


@pytest.mark.asyncio
async def test_the_canonical_verdict_is_cached(monkeypatch):
    s = _using(monkeypatch, _Session(canonical=[_row("asia")]))
    for _ in range(3):
        await fa._assert_peer_spiffe_binding("spiffe://asia.theprotocol.cloud/service/registry")
    assert s.canonical_reads == 1


# ── the licence skip ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_licence_authenticated_identity_skips_s3_and_nothing_else_does(monkeypatch):
    calls = []

    async def _recorder(spiffe_id):
        calls.append(spiffe_id)

    monkeypatch.setattr(fa, "_assert_peer_spiffe_binding", _recorder)
    synthetic = "spiffe://theprotocol.cloud/service/registry-did:theprotocol:cloud:sbxbetaop"
    token = fa._LICENSE_IDENTITY.set(synthetic)
    try:
        assert await fa.require_peer_registry_identity(spiffe_id=synthetic) == synthetic
        assert calls == []
        # control: the same request presenting any OTHER identity is still bound by S3
        other = "spiffe://sandbox-a.theprotocol.cloud/service/registry"
        await fa.require_peer_registry_identity(spiffe_id=other)
        assert calls == [other]
    finally:
        fa._LICENSE_IDENTITY.reset(token)
