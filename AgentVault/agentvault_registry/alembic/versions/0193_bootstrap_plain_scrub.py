"""SEC-05 (2026-10-17) — no bootstrap token stays in the registry's database as itself.

D6-283 keeps a bootstrap token as its SHA-256 hash only: since then `token_value` (NOT NULL, UNIQUE, read by no lookup)
holds the marker "sha256:<hash>" derived from that hash. Rows written before D6-283 still held the token itself in
`token_value` (used or expired: a token lives 300 s), and rows written before P23-001 (2026-04-30) had no hash at all.
This data migration gives each such row its marker, and its hash where it had none, so the column holds no token.

The smaller safe change: the column stays as it is. It is NOT NULL and UNIQUE, which a marker satisfies and NULL would
not without relaxing the column, and the release writes the marker into it for every new token; dropping it would also
break the older image's own writes during a rollback. Nothing else is touched.

Idempotent: a row that already holds a marker is left as it is.

Downgrade does nothing: the plaintext is gone and is not put back. An older image keeps working on these rows (it looks a
token up by its hash first, and every row has one now).

Revision ID: 0193_bootstrap_plain_scrub
Revises: 0192_agent_mtls_revoked_at
"""
import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0193_bootstrap_plain_scrub"
down_revision = "0192_agent_mtls_revoked_at"
branch_labels = None
depends_on = None

MARKER = "sha256:"   # crud/bootstrap_token._stored_marker

# substr, not LIKE: no percent sign for a DBAPI's paramstyle to read
_NOT_MARKED = "substr(token_value, 1, 7) <> 'sha256:'"


def _hash(token_value: str) -> str:
    """crud/bootstrap_token._hash_token: SHA-256 of the token's UTF-8 bytes, hex."""
    return hashlib.sha256(str(token_value).encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    # a row that carries its hash: the marker comes from it in the statement
    bind.execute(sa.text(
        f"UPDATE bootstrap_tokens SET token_value = 'sha256:' || token_value_hash "
        f"WHERE token_value_hash IS NOT NULL AND {_NOT_MARKED}"))
    # a row from before the hash column: its hash is computed here, as the registry computes it
    rows = bind.execute(sa.text(
        f"SELECT id, token_value FROM bootstrap_tokens WHERE token_value_hash IS NULL AND {_NOT_MARKED}")).fetchall()
    for row_id, value in rows:
        h = _hash(value)
        bind.execute(sa.text("UPDATE bootstrap_tokens SET token_value = :marker, token_value_hash = :hash WHERE id = :id"),
                     {"marker": MARKER + h, "hash": h, "id": row_id})


def downgrade() -> None:
    # Nothing to undo: the tokens this migration replaced by their markers are not kept anywhere.
    pass
