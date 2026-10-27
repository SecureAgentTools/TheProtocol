"""R57 / §JSONCAST-3 (2026-09-05, his word "r57 approved") — converge the seven json-family
columns that drifted to `json` on the four older Frame-A operators onto `jsonb`, the type every
mainframe, qatest16 and both sandbox frames already carry.

WHY: op-berlin / op-paris / op-washington / op-london were provisioned by `Base.metadata.create_all`
before the provisioner moved to `migration_bridge + alembic upgrade head` (2026-04-27), and the ORM
declared `JSON`; the migration that made the mainframes' `card_data` jsonb survives only as a
`.pyc`. Postgres resolves function types for the whole statement at parse time, so every uncast
`jsonb_*()` over these columns FAILED on those four nodes — `/agent-cards/discover` answered 500
from V0213 to V0218 (§JSONCAST), and the operator-rename rail's two writes could not run or roll
back (§JSONCAST-2). Casting call sites fixes the surface someone is looking at; converging the
column type retires the class.

WHAT: for each (table, column) below, IF the column exists AND is `json`, rewrite it in place:
    ALTER TABLE t ALTER COLUMN c TYPE jsonb USING c::jsonb
A node whose column is already `jsonb` (every mainframe) is untouched — a NO-OP by construction.
An absent table/column (a fresh frame has no `*_backup_v0052` tables) is skipped and logged.
Any OTHER type is REFUSED (RuntimeError): this migration converges a measured drift, it does
not guess.

LOSSLESS BY VALUE, not by text: jsonb normalises whitespace, key order and duplicate keys.
Every consumer canonicalises (`tp-sorted-ascii-v1` for card signatures); registry-a has served
these columns as jsonb for months.

DOWNGRADE reverts ONLY the columns THIS migration converted, read back from the
`r57_json_column_convergence` ledger it writes — a downgrade on a node that was jsonb before
0174 must not manufacture the drift it exists to close.

Rehearsed 2026-09-05 on a throwaway restore of op-berlin's five tables (15,571 cards, 105 MB):
see SESSION_LOG_2026-09-05_REPBOND.md addendum 3 for the measured duration and the value-equality
checksums. ACCESS EXCLUSIVE lock for the rewrite; boot-applied before the app serves.

Revision ID: 0174_json_columns_to_jsonb
Revises: 0173_reputation_bond_escrow
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "0174_json_columns_to_jsonb"
down_revision = "0173_reputation_bond_escrow"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# (table, column) — measured 2026-09-05 with information_schema on the 6 running DBs: these seven
# are `json` on op-berlin/paris/washington/london and `jsonb` on registry-a and qatest16.
COLUMNS: list[tuple[str, str]] = [
    ("agent_cards", "card_data"),
    ("developers", "backup_codes"),
    ("developers", "trusted_devices"),
    ("developer_achievements", "metadata_json"),
    ("agent_cards_orphan_backup_v0052", "card_data"),
    ("developers_ghost_backup_v0052", "backup_codes"),
    ("developers_ghost_backup_v0052", "trusted_devices"),
]

LEDGER = "r57_json_column_convergence"


def _current_type(conn, table: str, column: str):
    return conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(
        f'CREATE TABLE IF NOT EXISTS "{LEDGER}" ('
        "table_name VARCHAR(128) NOT NULL, column_name VARCHAR(128) NOT NULL, "
        "converted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "PRIMARY KEY (table_name, column_name))"
    )
    converted, already, absent = [], [], []
    for table, column in COLUMNS:
        typ = _current_type(conn, table, column)
        if typ is None:
            absent.append(f"{table}.{column}")
            continue
        if typ == "jsonb":
            already.append(f"{table}.{column}")
            continue
        if typ != "json":
            raise RuntimeError(
                f"0174 refuses {table}.{column}: expected json or jsonb, found {typ!r}"
            )
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE jsonb USING "{column}"::jsonb')
        conn.execute(
            sa.text(
                f'INSERT INTO "{LEDGER}" (table_name, column_name) VALUES (:t, :c) '
                "ON CONFLICT (table_name, column_name) DO NOTHING"
            ),
            {"t": table, "c": column},
        )
        converted.append(f"{table}.{column}")
    log.info(
        "0174 json->jsonb: converted=%s already_jsonb=%s absent=%s",
        converted or "-", already or "-", absent or "-",
    )


def downgrade() -> None:
    conn = op.get_bind()
    has_ledger = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": LEDGER},
    ).scalar()
    if not has_ledger:
        log.info("0174 downgrade: no convergence ledger — nothing was converted here; nothing to revert")
        return
    rows = conn.execute(sa.text(f'SELECT table_name, column_name FROM "{LEDGER}"')).all()
    for table, column in rows:
        if _current_type(conn, table, column) == "jsonb":
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE json USING "{column}"::json')
        conn.execute(
            sa.text(f'DELETE FROM "{LEDGER}" WHERE table_name = :t AND column_name = :c'),
            {"t": table, "c": column},
        )
    op.execute(f'DROP TABLE IF EXISTS "{LEDGER}"')
    log.info("0174 downgrade: reverted %s", [f"{t}.{c}" for t, c in rows] or "-")
