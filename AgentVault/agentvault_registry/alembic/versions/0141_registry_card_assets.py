"""registry_card_assets — persist the card icon/avatar BYTES, not just their URL (additive)

The upload handler has always written the image to
`STATIC_DIR/registry-cards/<slug>/icon.<ext>` and stored only the URL + etag + size in
`registry_card.card_json.visual`. `STATIC_DIR` is `static/new_registry_frontend/dist`, i.e.
INSIDE the built frontend — so the bytes lived in the container's ephemeral layer, under a
directory that an image rebuild replaces wholesale.

Consequence: every `--force-recreate` AND every image rebuild deleted the file while the DB
kept `icon_url` pointing at it. The operator saw their logo silently vanish with no error in
any log, and re-uploading only bought time until the next roll. The upload docstring already
CLAIMED a "DB BLOB backup" — this migration is what makes that claim true.

Deliberately its own table rather than columns on `registry_card`: that row's `card_json` is
canonicalised, hashed into `card_etag` and SIGNED on every serve, so parking 500 KB of image
bytes in it would bloat the signed payload and change the card digest on every icon upload.
Assets are addressed by `kind` ('icon' | 'avatar') — a singleton per kind, mirroring the
singleton card.

Revision ID: 0141_registry_card_assets (≤32 chars — alembic_version.version_num is VARCHAR(32))
Revises: 0140_notif_legacy_backfill
"""
from alembic import op
from sqlalchemy import text

revision = "0141_registry_card_assets"
down_revision = "0140_notif_legacy_backfill"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS registry_card_assets (
            kind        VARCHAR(16)  PRIMARY KEY,
            content     BYTEA        NOT NULL,
            mime        VARCHAR(64)  NOT NULL,
            ext         VARCHAR(8)   NOT NULL,
            sha256      VARCHAR(64)  NOT NULL,
            size_bytes  INTEGER      NOT NULL,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_by  INTEGER      REFERENCES developers(id) ON DELETE SET NULL
        )
    """))
    # 'icon' and 'avatar' are the only kinds the upload routes produce. A CHECK keeps a
    # typo'd kind from creating a row nothing will ever rehydrate.
    bind.execute(text("""
        DO $$ BEGIN
            ALTER TABLE registry_card_assets
              ADD CONSTRAINT ck_registry_card_assets_kind CHECK (kind IN ('icon','avatar'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """))


def downgrade():
    # Deliberate no-op, same rule as 0137-0140: an image rollback must never drop
    # operator-visible state ([[feedback_registry_rollback_alembic_downgrade_crash]]).
    # Dropping this table would re-arm the exact bug it exists to fix.
    pass
