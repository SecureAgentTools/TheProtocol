"""The commons: seasons, submissions, ballots and awards (§MEMBERSHIP phase B).

Revision ID: 0183_commons_seasons
Revises: 0182_fed_licence_certs

His word 2026-10-02 ("approved", "do it fully autonomously") on sessionlogs2026/DESIGN_2026-10-02_STAKING_REPLACEMENT.md
§ 12 (S3): a registry's fee income funds a commons that its members steer, and it pays only for work. A season has a
published budget; anyone submits work already done, with its evidence; each member spreads 100 points over the
submissions (never their own); a submission's share is the median of its points; awards go out through the reward
funding waterfall (services/reward_funding.py), never by holdings.

  commons_seasons      one row per season: window, budget and how it was set, the rules in force, the tally
  commons_submissions  work submitted to a season, with its evidence; `struck` by a reviewer with a reason
  commons_ballots      one ballot per member developer per season, replaceable until the close
  commons_awards       one row per (season, submission): the median, the share, the amount, and the payment

Plus three event_emission_policies rows (registry-emitted, audit only): the balance move is the TokensTransferred the
waterfall emits, the same partition as RewardsDistributed.

Adds only; touches no existing column. The downgrade removes the policy rows it added and KEEPS the four tables: a
season's history survives a rollback (the code that reads them is simply absent on the older image).
"""
from alembic import op
from sqlalchemy import text

revision = "0183_commons_seasons"
down_revision = "0182_fed_licence_certs"
branch_labels = None
depends_on = None

_POLICY_DESC = "§MEMBERSHIP commons audit event (0183): registry-emitted, audit only; the money is the waterfall's TokensTransferred."
_POLICIES = ("CommonsSeasonOpened", "CommonsSeasonClosed", "CommonsAwardPaid")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commons_seasons (
            id                              SERIAL PRIMARY KEY,
            title                           VARCHAR(160) NOT NULL,
            status                          VARCHAR(16) NOT NULL DEFAULT 'open',
            opens_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            ends_at                         TIMESTAMPTZ NOT NULL,
            currency                        VARCHAR(16) NOT NULL,
            fee_share_percent               NUMERIC(6, 3) NOT NULL DEFAULT 0,
            fee_collector_balance_at_open   NUMERIC(36, 18) NULL,
            seed                            NUMERIC(36, 18) NOT NULL DEFAULT 0,
            budget                          NUMERIC(36, 18) NOT NULL,
            recipient_cap_percent           NUMERIC(6, 3) NOT NULL,
            min_voters                      INTEGER NOT NULL,
            rules                           JSONB NOT NULL DEFAULT '{}'::jsonb,
            tally                           JSONB NULL,
            created_by                      INTEGER NULL,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed_at                       TIMESTAMPTZ NULL,
            closed_by                       INTEGER NULL,
            paid_at                         TIMESTAMPTZ NULL,
            paid_by                         INTEGER NULL,
            cancelled_at                    TIMESTAMPTZ NULL,
            cancel_reason                   VARCHAR(240) NULL
        );
        """
    )
    # One season at a time: at most one row that is still open or closed-but-unpaid.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_commons_one_live_season ON commons_seasons ((true)) "
        "WHERE status IN ('open', 'closed');"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commons_submissions (
            id               SERIAL PRIMARY KEY,
            season_id        INTEGER NOT NULL REFERENCES commons_seasons(id),
            submitter_did    VARCHAR(255) NOT NULL,
            developer_id     INTEGER NOT NULL,
            kind             VARCHAR(24) NOT NULL,
            title            VARCHAR(200) NOT NULL,
            description      TEXT NOT NULL DEFAULT '',
            evidence         JSONB NOT NULL DEFAULT '[]'::jsonb,
            status           VARCHAR(16) NOT NULL DEFAULT 'submitted',
            struck_reason    VARCHAR(240) NULL,
            struck_by        INTEGER NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_commons_submissions_season ON commons_submissions (season_id, status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_commons_submissions_dev ON commons_submissions (season_id, developer_id);")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commons_ballots (
            id                      SERIAL PRIMARY KEY,
            season_id               INTEGER NOT NULL REFERENCES commons_seasons(id),
            voter_developer_id      INTEGER NOT NULL,
            voter_did               VARCHAR(255) NOT NULL,
            allocations             JSONB NOT NULL,
            total_points            INTEGER NOT NULL,
            presence_challenge_id   VARCHAR(44) NULL,
            cast_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_commons_ballot_member UNIQUE (season_id, voter_developer_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commons_awards (
            id                    SERIAL PRIMARY KEY,
            season_id             INTEGER NOT NULL REFERENCES commons_seasons(id),
            submission_id         INTEGER NOT NULL REFERENCES commons_submissions(id),
            recipient_did         VARCHAR(255) NOT NULL,
            developer_id          INTEGER NOT NULL,
            median_points         NUMERIC(10, 4) NOT NULL,
            voters                INTEGER NOT NULL,
            share                 NUMERIC(20, 18) NOT NULL,
            amount                NUMERIC(36, 18) NOT NULL,
            status                VARCHAR(16) NOT NULL DEFAULT 'pending',
            idempotency_key       VARCHAR(160) NULL,
            teg_transaction_id    VARCHAR(120) NULL,
            funded_amount         NUMERIC(36, 18) NULL,
            shortfall             NUMERIC(36, 18) NULL,
            error                 VARCHAR(500) NULL,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            attempted_at          TIMESTAMPTZ NULL,
            paid_at               TIMESTAMPTZ NULL,
            written_off_at        TIMESTAMPTZ NULL,
            written_off_by        INTEGER NULL,
            written_off_reason    VARCHAR(240) NULL,
            CONSTRAINT uq_commons_award_submission UNIQUE (season_id, submission_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_commons_awards_recipient ON commons_awards (season_id, recipient_did);")
    for event_type in _POLICIES:
        op.execute(
            text(
                """
                INSERT INTO event_emission_policies
                    (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
                VALUES (:event_type, false, true, true, :desc, NOW())
                ON CONFLICT (event_type) DO NOTHING
                """
            ).bindparams(event_type=event_type, desc=_POLICY_DESC)
        )


def downgrade() -> None:
    for event_type in _POLICIES:
        op.execute(
            text("DELETE FROM event_emission_policies WHERE event_type = :event_type AND description = :desc")
            .bindparams(event_type=event_type, desc=_POLICY_DESC)
        )
    # The four tables are kept on purpose (see the module docstring).
