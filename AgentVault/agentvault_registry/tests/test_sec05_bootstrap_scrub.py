"""SEC-05 (2026-10-17): migration 0193 leaves no bootstrap token in `bootstrap_tokens.token_value`.

D6-283 stores a new token as its hash, with the marker "sha256:<hash>" in the legacy column. Rows written before kept
the token itself there, and rows from before P23-001 had no hash. The migration gives every such row its marker (and its
hash, computed as the registry computes it), leaves marked rows alone, and is idempotent; its downgrade changes nothing.

The migration runs through Alembic's own Operations on the model's table in SQLite (it uses no PostgreSQL-only SQL), with
rows of every kind. RED on 15620967: the migration does not exist there.
"""
import hashlib
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.pool import StaticPool

from agentvault_registry.crud.bootstrap_token import _hash_token, _stored_marker
from agentvault_registry.models import BootstrapToken

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
PLAIN_WITH_HASH = "bst_0123456789abcdef_00112233445566778899aabbccddeeff"
PLAIN_NO_HASH = "bst_fedcba9876543210_ffeeddccbbaa99887766554433221100"
NEW = "bst_aaaaaaaaaaaaaaaa_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _migration():
    path = VERSIONS / "0193_bootstrap_plain_scrub.py"
    spec = importlib.util.spec_from_file_location("m0193", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def conn():
    eng = sa.create_engine("sqlite://", poolclass=StaticPool)
    BootstrapToken.__table__.create(eng)
    c = eng.connect()
    t = BootstrapToken.__table__
    now = datetime.now(timezone.utc)
    rows = [
        # written between P23-001 and D6-283: the token and its hash, used
        dict(token_value=PLAIN_WITH_HASH, token_value_hash=_hash_token(PLAIN_WITH_HASH), used_at=now,
             used_by_agent_did="did:theprotocol:a", is_used=True),
        # written before P23-001: the token alone, expired
        dict(token_value=PLAIN_NO_HASH, token_value_hash=None, is_used=False),
        # written by this release: the marker and the hash
        dict(token_value=_stored_marker(_hash_token(NEW)), token_value_hash=_hash_token(NEW), is_used=False),
    ]
    for r in rows:
        c.execute(sa.insert(t).values(creator_developer_id=1, expires_at=now - timedelta(days=1),
                                      created_at=now - timedelta(days=2), **r))
    c.commit()
    yield c
    c.close()


def _upgrade(conn):
    with Operations.context(MigrationContext.configure(conn)):
        _migration().upgrade()
    conn.commit()


def _rows(conn):
    t = BootstrapToken.__table__
    return {r.id: r for r in conn.execute(sa.select(t).order_by(t.c.id))}


def test_no_row_keeps_a_token_after_the_migration(conn):
    _upgrade(conn)
    rows = _rows(conn)
    for r in rows.values():
        assert r.token_value == f"sha256:{r.token_value_hash}", r
        assert not r.token_value.startswith("bst_")
    every_cell = " ".join(str(v) for r in rows.values() for v in r)
    assert PLAIN_WITH_HASH not in every_cell and PLAIN_NO_HASH not in every_cell


def test_a_row_without_a_hash_gets_the_hash_the_registry_computes(conn):
    _upgrade(conn)
    by_hash = {r.token_value_hash: r for r in _rows(conn).values()}
    assert hashlib.sha256(PLAIN_NO_HASH.encode()).hexdigest() in by_hash   # a lookup by the token's hash finds it
    assert _hash_token(PLAIN_WITH_HASH) in by_hash and _hash_token(NEW) in by_hash


def test_a_marked_row_is_left_alone_and_the_migration_is_idempotent(conn):
    new_before = [r for r in _rows(conn).values() if r.token_value_hash == _hash_token(NEW)][0]
    _upgrade(conn)
    once = {i: tuple(r) for i, r in _rows(conn).items()}
    _upgrade(conn)
    assert {i: tuple(r) for i, r in _rows(conn).items()} == once
    assert tuple(_rows(conn)[new_before.id]) == tuple(new_before)


def test_the_downgrade_changes_nothing(conn):
    _upgrade(conn)
    once = {i: tuple(r) for i, r in _rows(conn).items()}
    with Operations.context(MigrationContext.configure(conn)):
        _migration().downgrade()
    assert {i: tuple(r) for i, r in _rows(conn).items()} == once


def test_the_revision_follows_0192_and_fits_the_version_column():
    m = _migration()
    assert m.down_revision == "0192_agent_mtls_revoked_at" and len(m.revision) <= 32
    # The whole graph (one head, no problems) is CI's migrations job (.forgejo/checks/alembic_graph.py, run from the
    # repository root). CI's test stage mounts no .forgejo, so a run of it here could only skip, and CI refuses a skip
    # it does not name.
