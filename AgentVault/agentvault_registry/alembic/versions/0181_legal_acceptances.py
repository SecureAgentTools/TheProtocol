"""Legal acceptances: one record per accepted document, whoever accepted it and however.

Revision ID: 0181_legal_acceptances
Revises: 0180_frame_request_kit

§LEGALKIT (2026-09-20). Terms § 10.3 promises "the version you accepted is recorded in your account".
Until now that was two columns on `developers` (registration) and two on fiat purchases (checkout), and
nothing at all for an operator application, a frame request, or the renewed acceptance § 10.2 promises
at the next login after a material change. One table, written by every rail:

  subject_kind   developer · operator_application · frame_request · checkout
  subject_id     the developer id, the application id, the request id, or the purchase id (as text)
  document       terms · operators · age18 · (any published document key)
  version        the document version the server served at that moment (never the client's word)
  via            register · login · checkout · operator_application · frame_request · mcp
  source_ip / user_agent   the same evidence the audit log keeps, retained under the same cap

The `developers.tos_accepted_*` columns stay as the fast path and are written together with the row.
Rolling back past this revision is two steps: downgrade first.
"""
from alembic import op

revision = "0181_legal_acceptances"
down_revision = "0180_frame_request_kit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legal_acceptances (
            id            BIGSERIAL PRIMARY KEY,
            developer_id  INTEGER NULL REFERENCES developers(id) ON DELETE SET NULL,
            subject_kind  VARCHAR(32) NOT NULL,
            subject_id    VARCHAR(64) NULL,
            document      VARCHAR(32) NOT NULL,
            version       VARCHAR(40) NOT NULL,
            via           VARCHAR(32) NULL,
            accepted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            source_ip     VARCHAR(45) NULL,
            user_agent    VARCHAR(255) NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_legal_acceptances_developer_document "
        "ON legal_acceptances (developer_id, document, accepted_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_legal_acceptances_subject "
        "ON legal_acceptances (subject_kind, subject_id);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_legal_acceptances_subject;")
    op.execute("DROP INDEX IF EXISTS ix_legal_acceptances_developer_document;")
    op.execute("DROP TABLE IF EXISTS legal_acceptances;")
